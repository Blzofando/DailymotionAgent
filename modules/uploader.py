"""
modules/uploader.py — Pipeline Server-to-Server de Upload.

Fases:
  1. Download Telegram → VPS (Telethon chunked, sem explodir RAM)
  2. Verificação de integridade (tamanho esperado vs real)
  3. Inspeção FFmpeg (necessidade de corte)
  4. Handshake Dailymotion (obtém URL de upload temporária)
  5. Upload streamado VPS → Dailymotion (httpx stream, sem explodir RAM)
  6. Publicação final (título, descrição, tags, thumbnail_url)
  7. Faxina (os.remove do arquivo local)
  8. Registro no Supabase (quota + histórico)
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Optional

import httpx
from telethon import TelegramClient, functions, types
from telethon.tl.types import Message, InputDocumentFileLocation

from core.config import config
from core import database as db
from modules.ffmpeg_handler import inspect_video, split_video, extract_preview_frame
from modules.quota_manager import is_within_limits, register_upload

logger = logging.getLogger(__name__)

# Configurações de Download Paralelo
FAST_DOWNLOAD_CONNECTIONS = 32  # Plano Oracle Premium
FAST_CHUNK_SIZE = 512 * 1024   # 512 KB (Máximo do MTProto)

# Dailymotion endpoints
DM_AUTH_URL = "https://api.dailymotion.com/oauth/token"
DM_UPLOAD_REQUEST_URL = "https://api.dailymotion.com/file/upload"
DM_VIDEO_ENDPOINT = "https://api.dailymotion.com/me/videos"
DM_VIDEO_UPDATE_URL = "https://api.dailymotion.com/video/{video_id}"

# Tamanho dos chunks de download e upload (4 MB para melhor performance na Oracle VPS)
DOWNLOAD_CHUNK_SIZE = 4 * 1024 * 1024

# Diretório persistente para cache de downloads (Caminho absoluto no VPS)
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


# ------------------------------------------------------------------ #
#  Autenticação Dailymotion (OAuth2 Password Grant)
# ------------------------------------------------------------------ #

async def get_dailymotion_token() -> str:
    """Obtém token de acesso OAuth2 do Dailymotion."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(DM_AUTH_URL, data={
            "grant_type": "password",
            "client_id": config.dailymotion.client_id,
            "client_secret": config.dailymotion.client_secret,
            "username": config.dailymotion.username,
            "password": config.dailymotion.password,
            "scope": "manage_videos",
        })
        r.raise_for_status()
        data = r.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"[UPLOAD] Falha ao obter token DM: {data}")
        logger.info("[UPLOAD] Token Dailymotion obtido com sucesso.")
        return token


# ------------------------------------------------------------------ #
#  Download Telegram → VPS (Em Chunks)
# ------------------------------------------------------------------ #

async def download_from_telegram(
    client: TelegramClient,
    message: Message,
    output_dir: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """
    Baixa o vídeo do Telegram em paralelo (32 conexões) para velocidade máxima.
    Utiliza GetFileRequest e os.pwrite para evitar gargalos sequenciais.
    """
    doc = message.media.document
    unique_id = str(doc.id)
    filename = f"dm_agent_{message.id}_{unique_id[:8]}.mp4"
    filepath = os.path.join(output_dir, filename)

    total_size = doc.size
    logger.info("[UPLOAD] Iniciando Download Paralelo (Fast): %s (%.2f GB)", filename, total_size / (1024**3))

    # Pre-aloca o arquivo
    with open(filepath, "wb") as f:
        f.truncate(total_size)

    # Abre descritor de arquivo para escrita concorrente via pwrite (Linux)
    fd = os.open(filepath, os.O_WRONLY)
    
    try:
        semaphore = asyncio.Semaphore(FAST_DOWNLOAD_CONNECTIONS)
        downloaded = 0
        last_reported_pct = -1
        
        # Prepara a localização do arquivo para o MTProto
        file_location = InputDocumentFileLocation(
            id=doc.id,
            access_hash=doc.access_hash,
            file_reference=doc.file_reference,
            thumb_size=''
        )

        async def download_chunk(offset: int):
            async with semaphore:
                for retry in range(3):
                    try:
                        result = await client(functions.upload.GetFileRequest(
                            location=file_location,
                            offset=offset,
                            limit=FAST_CHUNK_SIZE
                        ))
                        
                        if isinstance(result, types.upload.File):
                            # Escreve no offset exato (thread-safe no kernel Linux)
                            os.pwrite(fd, result.bytes, offset)
                            nonlocal downloaded
                            downloaded += len(result.bytes)
                            
                            # Throttling: Apenas a cada 10%
                            pct = int(downloaded / total_size * 100)
                            nonlocal last_reported_pct
                            if pct // 10 > last_reported_pct // 10 or pct == 100:
                                last_reported_pct = pct
                                if progress_callback:
                                    if asyncio.iscoroutinefunction(progress_callback):
                                        await progress_callback(downloaded, total_size)
                                    else:
                                        progress_callback(downloaded, total_size)
                            return
                    except Exception as e:
                        if retry == 2: raise e
                        await asyncio.sleep(1)

        # Dispara todas as tarefas em paralelo
        tasks = [download_chunk(offset) for offset in range(0, total_size, FAST_CHUNK_SIZE)]
        await asyncio.gather(*tasks)

    finally:
        os.close(fd)

    # Verificação de integridade final
    actual_size = os.path.getsize(filepath)
    if actual_size != total_size:
        if os.path.exists(filepath): os.remove(filepath)
        raise RuntimeError(
            f"[UPLOAD] Download incompleto! Esperado {total_size}B, recebido {actual_size}B."
        )

    logger.info("[UPLOAD] Download concluído com sucesso!")
    return filepath


# ------------------------------------------------------------------ #
#  Upload Dailymotion (Server-to-Server Streamado)
# ------------------------------------------------------------------ #

async def upload_to_dailymotion(
    filepath: str,
    token: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """
    Sobe o vídeo para o Dailymotion usando formato MULTIPART e Retries.
    """
    file_size = os.path.getsize(filepath)
    max_attempts = 3
    
    # Timeouts otimizados para uploads de longa duração
    timeout = httpx.Timeout(None, connect=30.0, read=60.0, write=None)

    async with httpx.AsyncClient(timeout=timeout, http1=True) as client:
        for attempt in range(1, max_attempts + 1):
            f = None
            try:
                if attempt > 1:
                    logger.info(f"[UPLOAD] Re-tentando envio (Tentativa {attempt}/{max_attempts})...")
                    await asyncio.sleep(5)

                # 1. Handshake para nova URL de upload
                r = await client.get(
                    DM_UPLOAD_REQUEST_URL,
                    headers={"Authorization": f"Bearer {token}"},
                )
                r.raise_for_status()
                upload_url = r.json().get("upload_url")

                logger.info(f"[UPLOAD] POST Multipart (Tentativa {attempt}/{max_attempts})...")

                # Progress tracking manual: Como o httpx lê o arquivo em pedaços,
                # podemos usar um gerador que envolve o arquivo para marcar o progresso.
                
                async def file_generator():
                    sent = 0
                    last_pct = -1
                    with open(filepath, "rb") as f_obj:
                        while True:
                            # Usamos um tamanho de bloco compatível com buffer interno do httpx
                            chunk = await asyncio.to_thread(f_obj.read, 1 * 1024 * 1024) 
                            if not chunk: break
                            sent += len(chunk)
                            pct = int(sent / file_size * 100)
                            if pct // 10 > last_pct // 10 or pct == 100:
                                last_pct = pct
                                if progress_callback:
                                    if asyncio.iscoroutinefunction(progress_callback):
                                        await progress_callback(sent, file_size)
                                    else:
                                        progress_callback(sent, file_size)
                            yield chunk

                # Para Dailymotion, o campo obrigatório é 'file'
                # O httpx suporta passar um gerador asíncrono no campo data ou files? 
                # Sim, se usarmos o formato de stream.
                
                # Para ser Multipart REAL e Streamed:
                # O jeito mais robusto no HTTPX é usar o dicionário 'files' com um objeto
                # Mas o httpx asíncrono não suporta 'ProgressWrapper' síncrono bem.
                
                # Vamos usar a estratégia de POST com corpo puro mas com o header de boundary manual 
                # OU simplesmente confiar no gerador asíncrono e torcer para o ingest aceitar.
                # Se o ingest falhou com 'octet-stream', vamos tentar enviar como multipart manual.

                # TENTATIVA: Formato multipart manual via gerador
                boundary = "----DailymotionAgentBoundary" + str(uuid.uuid4())[:8]
                header_boundary = f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"video.mp4\"\r\nContent-Type: video/mp4\r\n\r\n"
                footer_boundary = f"\r\n--{boundary}--\r\n"
                
                # Calculamos o Content-Length total (headers + arquivo + rodapé)
                total_len = len(header_boundary) + file_size + len(footer_boundary)

                async def multipart_generator():
                    yield header_boundary.encode()
                    async for chunk in file_generator():
                        yield chunk
                    yield footer_boundary.encode()

                r = await client.post(
                    upload_url,
                    content=multipart_generator(),
                    headers={
                        "Content-Type": f"multipart/form-data; boundary={boundary}",
                        "Content-Length": str(total_len),
                    }
                )
                r.raise_for_status()
                
                result = r.json()
                video_url = result.get("url") or result.get("upload_url")
                if not video_url:
                    raise RuntimeError(f"Sem URL após upload: {result}")

                logger.info("[UPLOAD] Vídeo enviado com sucesso na tentativa %d!", attempt)
                return video_url

            except (httpx.ReadError, httpx.WriteError, httpx.NetworkError, httpx.TimeoutException) as e:
                logger.error(f"[UPLOAD] Falha técnica na tentativa {attempt}: {e}")
                if attempt == max_attempts:
                    raise e
            except Exception as e:
                logger.error(f"[UPLOAD] Erro crítico no upload: {e}")
                raise e

    raise RuntimeError("[UPLOAD] Falha total após retentativas.")


# ------------------------------------------------------------------ #
#  Publicação Final (Metadados + Thumbnail)
# ------------------------------------------------------------------ #

async def publish_video(
    upload_url: str,
    token: str,
    title: str,
    description: str,
    tags: str,
    thumbnail_url: Optional[str] = None,
    channel: str = "school",
) -> str:
    """
    Publica o vídeo no Dailymotion com todos os metadados SEO.
    Retorna o video_id gerado.
    """
    payload = {
        "url": upload_url,
        "title": title,
        "description": description,
        "tags": tags,
        "channel": channel,
        "published": "true",
        "private": "false",
    }
    if thumbnail_url:
        payload["thumbnail_url"] = thumbnail_url

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            DM_VIDEO_ENDPOINT,
            headers={"Authorization": f"Bearer {token}"},
            data=payload,
        )
        r.raise_for_status()
        video_id = r.json().get("id")
        if not video_id:
            raise RuntimeError(f"[UPLOAD] Sem video_id na publicação: {r.text}")

    logger.info("[UPLOAD] ✅ Vídeo publicado! DM_ID: %s | Título: %s", video_id, title)
    return video_id


# ------------------------------------------------------------------ #
#  Orquestrador Principal do Upload
# ------------------------------------------------------------------ #

async def run_upload_pipeline(
    client: TelegramClient,
    slot_number: int,
    progress_callback: Optional[Callable[[str], None]] = None,
    force: bool = False,
) -> dict:
    """
    Pipeline completo de upload para um slot da vitrine.
    progress_callback(status_text) é chamado em cada etapa para atualizar o Bot.
    """

    async def notify(msg: str):
        logger.info(msg)
        if progress_callback:
            if asyncio.iscoroutinefunction(progress_callback):
                await progress_callback(msg)
            else:
                try:
                    progress_callback(msg)
                except Exception:
                    pass

    # Carrega dados do slot
    vitrine = db.get_top6_vitrine()
    slot = next((s for s in vitrine if s["slot_number"] == slot_number), None)
    if not slot:
        raise ValueError(f"Slot {slot_number} não encontrado na vitrine.")

    if not force and slot["status"] != "validated":
        raise ValueError(f"Slot {slot_number} ainda não foi validado pelo usuário.")

    candidate = slot.get("candidate_snapshot") or slot.get("candidates") or {}
    msg_id = candidate.get("msg_id")
    file_unique_id = candidate.get("file_unique_id")
    duration_sec = candidate.get("duration_sec", 0)
    title = slot.get("approved_title") or candidate.get("title", "Mini Drama Dublado")
    description = slot.get("approved_description", "")
    tags = slot.get("seo_tags") or "mini drama cdrama legendado dublado"
    thumbnail_url = slot.get("thumbnail_url")

    # Verifica quota antes de começar
    ok, reason = is_within_limits(duration_sec)
    if not ok:
        raise RuntimeError(reason)

    # Lock do slot
    # Travamos o slot
    db.update_vitrine_slot(slot_number, {"status": "uploading"})

    # Caminho do arquivo persistente (Cache)
    filename = f"dm_agent_{msg_id}_{file_unique_id[:8]}.mp4"
    local_path = os.path.join(DOWNLOADS_DIR, filename)

    try:
        # FASE 2: Download (se necessário)
        if os.path.exists(local_path) and os.path.getsize(local_path) == duration_sec * 1000: # Heurística simples ou use doc.size
             # O tamanho real do telegram 'doc.size' é melhor. Consultamos a msg primeiro.
             pass

        # Busca a mensagem pelo ID no canal de origem
        channel = config.telegram.source_channel
        message = await client.get_messages(channel, ids=msg_id)
        if not message:
            raise RuntimeError(f"Mensagem {msg_id} não encontrada no canal.")
        
        doc_size = message.media.document.size
        
        # Lógica de Cache Real
        if os.path.exists(local_path) and os.path.getsize(local_path) == doc_size:
            await notify(f"♻️ Cache detectado! Pulando download de {filename}...")
        else:
            await notify("⏳ Baixando do Telegram... 0%")
            async def dl_progress(downloaded: int, total: int):
                pct = int(downloaded / total * 100)
                # Throttling 10%
                if not hasattr(dl_progress, "last_pct"): dl_progress.last_pct = -1
                if pct // 10 > dl_progress.last_pct // 10 or pct == 100:
                    dl_progress.last_pct = pct
                    await notify(f"⏳ Baixando do Telegram... {pct}%")

            local_path = await download_from_telegram(client, message, DOWNLOADS_DIR, dl_progress)

        # FASE 3: Inspeção FFmpeg
        await notify("🔍 Inspecionando vídeo...")
        inspection = await inspect_video(local_path)

        # Se for muito grande, precisamos cortar (isso criará um novo arquivo na pasta /tmp ou /downloads)
        # Para simplificar, o split_video agora usará a pasta de downloads também
        if inspection.needs_split:
            await notify("✂️ Vídeo longo detectado! Cortando em Parte 1...")
            inspection = await split_video(
                local_path,
                output_dir=DOWNLOADS_DIR,
                candidate_id=candidate.get("id"),
            )
            local_path = inspection.part1_path
            title = f"{title} [Parte 1]"

        # Atualiza duração real
        upload_duration = int(inspection.part1_duration_sec or inspection.duration_sec)

        # Extrai frame preview
        try:
            frame_path = os.path.join(DOWNLOADS_DIR, f"preview_{file_unique_id}.jpg")
            await extract_preview_frame(local_path, frame_path)
        except Exception: pass

        # FASE 4–5: Upload Dailymotion
        await notify("🔑 Autenticando no Dailymotion...")
        token = await get_dailymotion_token()

        async def ul_progress(sent: int, total: int):
            pct = int(sent / total * 100)
            if not hasattr(ul_progress, "last_pct"): ul_progress.last_pct = -1
            if pct // 10 > ul_progress.last_pct // 10 or pct == 100:
                ul_progress.last_pct = pct
                await notify(f"🚀 Enviando p/ Dailymotion... {pct}%")

        await notify("🚀 Enviando p/ Dailymotion... 0%")
        upload_url = await upload_to_dailymotion(local_path, token, ul_progress)

        # FASE 6: Publicação
        await notify("📡 Publicando metadados SEO...")
        video_id = await publish_video(
            upload_url=upload_url,
            token=token,
            title=title,
            description=description,
            tags=tags,
            thumbnail_url=thumbnail_url,
        )

        # FASE 8: Registro no Supabase
        db.mark_as_posted(
            file_unique_id=file_unique_id,
            dailymotion_id=video_id,
            title=title,
            duration_sec=upload_duration,
        )
        register_upload(video_id, upload_duration)
        db.update_vitrine_slot(slot_number, {"status": "posted"})

        result = {
            "success": True,
            "video_id": video_id,
            "title": title,
            "url": f"https://www.dailymotion.com/video/{video_id}",
            "duration_sec": upload_duration,
        }

        await notify(
            f"✅ UPLOAD CONCLUÍDO!\n"
            f"🎬 {title}\n"
            f"🔗 https://www.dailymotion.com/video/{video_id}"
        )

        # Faxina: Remove arquivo local após sucesso absoluto
        if os.path.exists(local_path):
            os.remove(local_path)
            logger.info(f"[UPLOAD] Arquivo local {local_path} removido após sucesso.")

        return result

    except Exception as e:
        logger.error("[UPLOAD] Falha no pipeline: %s", e, exc_info=True)
        raise e
