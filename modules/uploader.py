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
from pathlib import Path
from typing import Callable, Optional

import httpx
from telethon import TelegramClient
from telethon.tl.types import Message

from core.config import config
from core import database as db
from modules.ffmpeg_handler import inspect_video, split_video, extract_preview_frame
from modules.quota_manager import is_within_limits, register_upload

logger = logging.getLogger(__name__)

# Dailymotion endpoints
DM_AUTH_URL = "https://api.dailymotion.com/oauth/token"
DM_UPLOAD_REQUEST_URL = "https://api.dailymotion.com/file/upload"
DM_VIDEO_ENDPOINT = "https://api.dailymotion.com/me/videos"
DM_VIDEO_UPDATE_URL = "https://api.dailymotion.com/video/{video_id}"

# Tamanho dos chunks de download (1 MB)
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


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
    Baixa o vídeo do Telegram em chunks de 1MB diretamente para o disco.
    Retorna o caminho do arquivo salvo.
    """
    doc = message.media.document
    filename = f"dm_agent_{message.id}_{doc.file_unique_id[:8]}.mp4"
    filepath = os.path.join(output_dir, filename)

    logger.info("[UPLOAD] Iniciando download: %s (%.2f GB)", filename, doc.size / (1024**3))

    total_size = doc.size
    downloaded = 0
    last_reported_pct = -1

    with open(filepath, "wb") as f:
        async for chunk in client.iter_download(message.media, chunk_size=DOWNLOAD_CHUNK_SIZE):
            f.write(chunk)
            downloaded += len(chunk)

            pct = int(downloaded / total_size * 100)
            if pct // 10 != last_reported_pct // 10:
                last_reported_pct = pct
                logger.info("[UPLOAD] Download: %d%%", pct)
                if progress_callback:
                    progress_callback(downloaded, total_size)

    # Verificação de integridade
    actual_size = os.path.getsize(filepath)
    if actual_size != total_size:
        os.remove(filepath)
        raise RuntimeError(
            f"[UPLOAD] Corrupção detectada! Esperado {total_size}B, recebido {actual_size}B. Abortando."
        )

    logger.info("[UPLOAD] Download concluído e íntegro: %s", filepath)
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
    Sobe o vídeo para o Dailymotion via upload streamado.
    Retorna a URL do vídeo recém-criado (url temporária).
    """
    file_size = os.path.getsize(filepath)

    async with httpx.AsyncClient(timeout=300) as client:
        # Fase 4a: Handshake — obtém URL de upload temporária
        r = await client.get(
            DM_UPLOAD_REQUEST_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        upload_url = r.json().get("upload_url")
        if not upload_url:
            raise RuntimeError(f"[UPLOAD] Sem upload_url no handshake: {r.text}")

        logger.info("[UPLOAD] Upload URL obtida. Iniciando envio streamado...")

        # Fase 4b: Upload streamado sem carregar arquivo na RAM
        def file_generator():
            sent = 0
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    sent += len(chunk)
                    if progress_callback:
                        progress_callback(sent, file_size)
                    yield chunk

        r = await client.post(
            upload_url,
            content=file_generator(),
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(file_size),
            },
            timeout=httpx.Timeout(None),  # Sem timeout para uploads grandes
        )
        r.raise_for_status()
        result = r.json()
        url = result.get("url")
        if not url:
            raise RuntimeError(f"[UPLOAD] Sem URL na resposta do upload: {result}")

        logger.info("[UPLOAD] Vídeo enviado ao Dailymotion. URL temporária obtida.")
        return url


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
) -> dict:
    """
    Pipeline completo de upload para um slot da vitrine.
    progress_callback(status_text) é chamado em cada etapa para atualizar o Bot.
    """

    def notify(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    # Carrega dados do slot
    vitrine = db.get_top6_vitrine()
    slot = next((s for s in vitrine if s["slot_number"] == slot_number), None)
    if not slot:
        raise ValueError(f"Slot {slot_number} não encontrado na vitrine.")

    if slot["status"] != "validated":
        raise ValueError(f"Slot {slot_number} ainda não foi validado pelo usuário.")

    candidate = slot.get("candidates") or {}
    msg_id = candidate.get("msg_id")
    file_unique_id = candidate.get("file_unique_id")
    duration_sec = candidate.get("duration_sec", 0)
    title = slot.get("approved_title", "Mini Drama Dublado")
    description = slot.get("approved_description", "")
    tags = slot.get("seo_tags", "mini drama")
    thumbnail_url = slot.get("thumbnail_url")

    # Verifica quota antes de começar
    ok, reason = is_within_limits(duration_sec)
    if not ok:
        raise RuntimeError(reason)

    # Lock do slot
    db.update_vitrine_slot(slot_number, {"status": "uploading"})

    # Diretório temporário de trabalho
    with tempfile.TemporaryDirectory(prefix="dm_agent_") as tmpdir:
        notify("⏳ Baixando do Telegram... 0%")

        # Busca a mensagem pelo ID no canal de origem
        channel = config.telegram.source_channel
        message = await client.get_messages(channel, ids=msg_id)
        if not message:
            raise RuntimeError(f"Mensagem {msg_id} não encontrada no canal.")

        def dl_progress(downloaded: int, total: int):
            pct = int(downloaded / total * 100)
            notify(f"⏳ Baixando do Telegram... {pct}%")

        # FASE 2: Download
        local_path = await download_from_telegram(client, message, tmpdir, dl_progress)

        # FASE 3: Inspeção FFmpeg
        notify("🔍 Inspecionando vídeo...")
        inspection = await inspect_video(local_path)

        if inspection.needs_split:
            notify("✂️ Vídeo longo detectado! Cortando em Parte 1...")
            inspection = await split_video(
                local_path,
                output_dir=tmpdir,
                candidate_id=candidate.get("id"),
            )
            local_path = inspection.part1_path
            title = f"{title} [Parte 1]"

        # Atualiza duração real (pode ter mudado após corte)
        upload_duration = int(inspection.part1_duration_sec or inspection.duration_sec)

        # Extrai frame preview (para logs)
        try:
            frame_path = os.path.join(tmpdir, "preview.jpg")
            await extract_preview_frame(local_path, frame_path)
        except Exception:
            pass  # Preview é opcional

        # FASE 4–5: Upload Dailymotion
        notify("🔑 Autenticando no Dailymotion...")
        token = await get_dailymotion_token()

        def ul_progress(sent: int, total: int):
            pct = int(sent / total * 100)
            notify(f"🚀 Enviando p/ Dailymotion... {pct}%")

        notify("🚀 Enviando p/ Dailymotion... 0%")
        upload_url = await upload_to_dailymotion(local_path, token, ul_progress)

        # FASE 6: Publicação
        notify("📡 Publicando metadados SEO...")
        video_id = await publish_video(
            upload_url=upload_url,
            token=token,
            title=title,
            description=description,
            tags=tags,
            thumbnail_url=thumbnail_url,
        )

        # FASE 7: Faxina — arquivo já deletado pelo TemporaryDirectory
        # (tmpdir é limpo automaticamente ao sair do with block)

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

        notify(
            f"✅ UPLOAD CONCLUÍDO!\n"
            f"🎬 {title}\n"
            f"🔗 https://www.dailymotion.com/video/{video_id}"
        )
        return result
