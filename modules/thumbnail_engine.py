"""
modules/thumbnail_engine.py — Motor de Busca Global de Capas (Thumbnails) no Telegram
"""

import os
import time
import logging
import asyncio
import tempfile
from typing import Optional

from telethon import TelegramClient
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import MessageMediaPhoto, Channel, Chat
from telethon.tl.functions.channels import GetMessagesRequest

from core.database import get_client

logger = logging.getLogger(__name__)

async def search_and_upload_thumbnail(client: TelegramClient, title: str) -> list[str]:
    """
    1. Realiza busca global no Telegram por canais que correspondam ao título.
    2. Entra no histórico recente desses canais procurando uma MessageMediaPhoto.
    3. Faz o download de até 4 fotos (1 por canal).
    4. Sobe para o bucket 'thumbnails' do Supabase.
    5. Retorna a lista de 4 URLs públicas.
    """
    logger.info(f"[THUMB] Iniciando busca global pela capa de: '{title}'")
    
    # 1. Busca Global de Canais
    try:
        # A busca pode retornar canais inteiros que roubam o nome do drama pelo Hype
        result = await client(SearchRequest(
            q=title,
            limit=5  # Top 5 canais é o suficiente
        ))
        
        target_peers = []
        for chat in result.chats:
            if getattr(chat, 'username', None) or getattr(chat, 'title', None):
                 target_peers.append(chat)
                 
    except Exception as e:
        logger.warning(f"[THUMB] Falha na busca global do Telegram: {e}")
        return None

    if not target_peers:
        logger.info("[THUMB] Nenhum canal global encontrado com esse título.")
        return []

    logger.info(f"[THUMB] {len(target_peers)} canais encontrados. Iniciando escaneamento interno...")

    photo_paths = []
    
    # 2. Busca pelas mensagens de Foto dentro desses canais
    with tempfile.TemporaryDirectory(prefix="thumb_") as tmpdir:
        for peer in target_peers:
            logger.debug(f"[THUMB] Inspecionando canal: {getattr(peer, 'title', 'Unknown')}")
            try:
                # Vamos iterar pelas últimas 20 mensagens do canal
                async for msg in client.iter_messages(peer, search=title[:15], limit=20):
                    if msg.media and getattr(msg.media, "photo", None):
                        logger.info(f"[THUMB] Capa encontrada no canal {getattr(peer, 'title', '')}! Baixando...")
                        
                        # --- ENCAMINHA PARA O ADMIN (FOTO + PREVIEW 1MIN + ADJACENTES) ---
                        try:
                            from core.config import config
                            # Encaminha a id anterior, a id atual (capa/album) e a id seguinte (provável preview)
                            to_forward = [msg.id - 1, msg.id, msg.id + 1]
                            await client.forward_messages(
                                entity=config.telegram.admin_chat_id,
                                messages=to_forward,
                                from_peer=peer
                            )
                        except Exception as f_err:
                            pass # Remove warning por flood de forwards, falha silenciosa permitida.
                        
                        filename = f"thumb_{int(time.time())}_{len(photo_paths)}.jpg"
                        path = os.path.join(tmpdir, filename)
                        path = await client.download_media(msg.media.photo, file=path)
                        if path:
                            photo_paths.append(path)
                        break # Uma capa por canal é suficiente
            except Exception as e:
                # Pode acontecer de não termos acesso de leitura a chats privados na busca
                continue
                
            if len(photo_paths) >= 4:
                break
                
        if not photo_paths:
            logger.info("[THUMB] Nenhuma capa em formato de foto encontrada nos canais catalogados.")
            return []
            
        # 3 e 4. Upload para o Supabase Storage
        logger.info(f"[THUMB] {len(photo_paths)} capas baixadas. Fazendo upload para Supabase Storage...")
        public_urls = []
        try:
            db = get_client()
            for path in photo_paths:
                if not os.path.exists(path):
                    continue
                filename_storage = f"thumb_{int(time.time())}_{os.path.basename(path)}"
                
                # Lê o arquivo para upload como bytes
                with open(path, "rb") as f:
                    upload_res = await asyncio.to_thread(
                        db.storage.from_("thumbnails").upload,
                        file=f.read(),
                        path=filename_storage,
                        file_options={"content-type": "image/jpeg"}
                    )
                    
                # 5. Obtém a URL pública
                public_url = db.storage.from_("thumbnails").get_public_url(filename_storage)
                public_urls.append(public_url)
                logger.info(f"[THUMB] Upload de capa concluído! URL Pública: {public_url}")
                
            return public_urls
            
        except Exception as e:
            logger.error(f"[THUMB] Erro no upload para o Supabase Storage: {e}")
            return public_urls # Pode retornar as que conseguiu antes de dar erro


async def download_telegram_link(client: TelegramClient, url: str) -> Optional[str]:
    """
    Downloads a photo from a direct telegram link (t.me/c/id/msg or t.me/channel/msg).
    Assumes the client has permission to read the channel.
    Uploads it to Supabase and returns the public URL.
    """
    try:
        parts = url.strip().split('/')
        if len(parts) >= 5 and parts[3] == "c":
            channel_id = int(parts[4])
            peer_id = int(f"-100{channel_id}")
            msg_id = int(parts[5].split('?')[0])
            entity = await client.get_entity(peer_id)
        elif len(parts) >= 4:
            channel_name = parts[3]
            msg_id = int(parts[4].split('?')[0])
            entity = await client.get_entity(channel_name)
        else:
            return None
            
        async for msg in client.iter_messages(entity, ids=[msg_id]):
            if msg and msg.media and getattr(msg.media, "photo", None):
                with tempfile.TemporaryDirectory(prefix="thumb_") as tmpdir:
                    filename = f"thumb_manual_{int(time.time())}.jpg"
                    path = os.path.join(tmpdir, filename)
                    path = await client.download_media(msg.media.photo, file=path)
                    
                    if not path or not os.path.exists(path):
                        return None
                        
                    db = get_client()
                    filename_storage = f"thumb_{int(time.time())}_{os.path.basename(path)}"
                    
                    with open(path, "rb") as f:
                        await asyncio.to_thread(
                            db.storage.from_("thumbnails").upload,
                            file=f.read(),
                            path=filename_storage,
                            file_options={"content-type": "image/jpeg"}
                        )
                        
                    public_url = db.storage.from_("thumbnails").get_public_url(filename_storage)
                    return public_url
        return None
    except Exception as e:
        logger.error(f"[THUMB] Erro fazendo download de link direto do telegram: {e}")
        return None
