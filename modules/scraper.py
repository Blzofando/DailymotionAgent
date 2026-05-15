"""
modules/scraper.py — Motor de Mineração MTProto (Telethon).

Executa o funil de 5 fases da documentação:
  Fase 1: Varre 100 vídeos longos (>40min) do canal de origem
  Fase 2: Filtra para 30 candidatos (10 frescos + 20 hype)
  Fase 3: Busca reversa da sinopse (Fuzzy Match)
  Fase 4: (delegado ao validator.py) Score de hype global
  Fase 5: (delegado ao validator.py) Top 6 Vitrine
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz
from telethon import TelegramClient
from telethon.tl.types import Message, MessageMediaDocument

from core.config import config
from core import database as db

logger = logging.getLogger(__name__)

# Duração mínima para ser considerado vídeo longo (40 min em segundos)
MIN_DURATION_SEC = 40 * 60


# ------------------------------------------------------------------ #
#  Estrutura de dados interna
# ------------------------------------------------------------------ #

@dataclass
class VideoCandidate:
    msg_id: int
    channel_id: int
    file_unique_id: str
    caption: str
    duration_sec: int
    file_size_bytes: int
    views: int
    reactions: int
    synopsis: Optional[str] = None
    synopsis_msg_id: Optional[int] = None
    hype_score: float = 0.0

    @property
    def engagement_rate(self) -> float:
        if self.views == 0:
            return 0.0
        return self.reactions / self.views


# ------------------------------------------------------------------ #
#  Limpeza de texto
# ------------------------------------------------------------------ #

_EMOJI_RE = re.compile(
    "[\U00010000-\U0010ffff"
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U00002600-\U000027BF"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_PART_RE = re.compile(r"\[?\s*(Parte|Part|Ep|Eps?\.?)\s*\d+\s*\]?", re.IGNORECASE)
_CLEAN_RE = re.compile(r"[\[\](){}|#@\-_]+")


def clean_title(text: str) -> str:
    """Remove emojis, anos, marcadores de parte e símbolos poluentes."""
    if not text:
        return ""
    text = _EMOJI_RE.sub(" ", text)
    text = _YEAR_RE.sub(" ", text)
    text = _PART_RE.sub(" ", text)
    text = _CLEAN_RE.sub(" ", text)
    return " ".join(text.split()).strip()


def extract_title_from_caption(caption: str) -> str:
    """Extrai o núcleo do título da legenda do vídeo."""
    if not caption:
        return ""
    # Pega apenas a primeira linha (geralmente contém o título)
    first_line = caption.strip().split("\n")[0]
    return clean_title(first_line)


# ------------------------------------------------------------------ #
#  Scraper Principal
# ------------------------------------------------------------------ #

class TelegramScraper:
    def __init__(self, client: Optional[TelegramClient] = None):
        self._owns_client = False
        if client:
            self.client = client
        else:
            self.client = TelegramClient(
                config.telegram.session_name,
                config.telegram.api_id,
                config.telegram.api_hash,
            )
            self._owns_client = True

    async def __aenter__(self):
        if self._owns_client:
            await self.client.start()
            logger.info("[SCRAPER] Telethon conectado como usuário MTProto")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._owns_client:
            await self.client.disconnect()

    # -------------------------------------------------------------- #
    #  FASE 1: Varredura de Vídeos Longos
    # -------------------------------------------------------------- #

    async def _fetch_long_videos(self, channel: str, limit: int) -> list[VideoCandidate]:
        """
        Varre o canal de cima para baixo coletando até `limit` vídeos
        com duração >= MIN_DURATION_SEC.
        """
        candidates: list[VideoCandidate] = []
        logger.info("[SCRAPER] Fase 1 — varrendo '%s' em busca de %d vídeos longos...", channel, limit)

        async for message in self.client.iter_messages(channel, filter=None):
            message: Message

            # Só processa mensagens com documento de vídeo
            if not isinstance(message.media, MessageMediaDocument):
                continue

            doc = message.media.document
            if not doc:
                continue

            # Verifica se é vídeo com duração
            duration = 0
            mime = getattr(doc, "mime_type", "") or ""
            if "video" not in mime:
                continue

            for attr in doc.attributes:
                if hasattr(attr, "duration"):
                    duration = int(attr.duration)
                    break

            if duration < MIN_DURATION_SEC:
                continue

            # Verifica anti-duplicata antes de adicionar
            unique_id = str(doc.id)
            title = extract_title_from_caption(message.message or "")
            if db.check_duplicate(unique_id, title):
                logger.debug("[SCRAPER] Ignorado (duplicata): %s | %s", unique_id, title)
                continue

            # Conta reações
            reactions_count = 0
            if message.reactions:
                for r in message.reactions.results:
                    reactions_count += r.count

            candidate = VideoCandidate(
                msg_id=message.id,
                channel_id=message.peer_id.channel_id if hasattr(message.peer_id, "channel_id") else 0,
                file_unique_id=unique_id,
                caption=message.message or "",
                duration_sec=duration,
                file_size_bytes=doc.size,
                views=message.views or 0,
                reactions=reactions_count,
            )
            candidates.append(candidate)
            logger.debug("[SCRAPER] Vídeo coletado: msg_id=%d dur=%ds", message.id, duration)

            if len(candidates) >= limit:
                break

        logger.info("[SCRAPER] Fase 1 concluída: %d vídeos longos coletados", len(candidates))
        return candidates

    # -------------------------------------------------------------- #
    #  FASE 2: Peneira 100 → 30 (10 frescos + 20 hype)
    # -------------------------------------------------------------- #

    def _apply_filter(self, candidates: list[VideoCandidate]) -> list[VideoCandidate]:
        """Seleciona 10 mais recentes + 20 com maior taxa de engajamento."""
        logger.info("[SCRAPER] Fase 2 — filtrando %d → 30...", len(candidates))

        # Os 10 mais recentes (primeira posição = mais recente no iter_messages)
        fresh = candidates[:config.agent.fresh_count]
        remaining = candidates[config.agent.fresh_count:]

        # Os 20 com maior engagement_rate dos restantes
        hype = sorted(remaining, key=lambda c: c.engagement_rate, reverse=True)
        hype = hype[:config.agent.hype_count]

        selected = fresh + hype
        logger.info(
            "[SCRAPER] Fase 2 concluída: %d frescos + %d hype = %d candidatos",
            len(fresh), len(hype), len(selected)
        )
        return selected

    # -------------------------------------------------------------- #
    #  FASE 3: Busca Reversa da Sinopse (Fuzzy Match)
    # -------------------------------------------------------------- #

    async def _find_synopsis(self, channel: str, video: VideoCandidate) -> Optional[tuple[str, int]]:
        """
        Sobe até LOOKUP_WINDOW mensagens acima do vídeo buscando a sinopse.
        Retorna (texto_sinopse, msg_id) ou None se não encontrado.
        """
        title_base = extract_title_from_caption(video.caption)
        if not title_base:
            return None

        window = config.agent.lookup_window
        threshold = config.agent.fuzzy_threshold

        # Busca mensagens anteriores ao vídeo
        messages_above = []
        async for msg in self.client.iter_messages(
            channel,
            limit=window,
            max_id=video.msg_id,
        ):
            messages_above.append(msg)

        for msg in messages_above:
            if not msg.message:
                continue

            # Ignora links de grupos/canais (Mensagem C)
            if "t.me/" in msg.message and len(msg.message) < 100:
                continue

            msg_clean = clean_title(msg.message[:200])  # Processa só o início
            score = fuzz.partial_ratio(title_base.lower(), msg_clean.lower())

            if score >= threshold:
                logger.debug(
                    "[SCRAPER] Sinopse encontrada: msg_id=%d score=%d%%",
                    msg.id, score
                )
                return msg.message, msg.id

        logger.debug("[SCRAPER] Sinopse não encontrada para: '%s'", title_base)
        return None

    # -------------------------------------------------------------- #
    #  Orquestrador Principal
    # -------------------------------------------------------------- #

    async def run(self) -> list[VideoCandidate]:
        """
        Executa o funil completo e persiste candidatos no Supabase.
        Retorna a lista de candidatos validados (com sinopse quando possível).
        """
        channel = config.telegram.source_channel

        # FASE 1
        all_videos = await self._fetch_long_videos(channel, config.agent.mining_limit)

        if not all_videos:
            logger.warning("[SCRAPER] Nenhum vídeo longo encontrado no canal.")
            return []

        # FASE 2
        selected = self._apply_filter(all_videos)

        # FASE 3 — Busca reversa de sinopse
        logger.info("[SCRAPER] Fase 3 — buscando sinopses para %d candidatos...", len(selected))
        for video in selected:
            result = await self._find_synopsis(channel, video)
            if result:
                video.synopsis, video.synopsis_msg_id = result

        logger.info("[SCRAPER] %d candidatos prontos em memória (sem persistência no banco).", len(selected))
        return selected


# ------------------------------------------------------------------ #
#  Execução direta (teste)
# ------------------------------------------------------------------ #

async def _test():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    async with TelegramScraper() as scraper:
        results = await scraper.run()
        print(f"\n✅ Total de candidatos gerados: {len(results)}")
        for c in results[:3]:
            print(f"  [{c.engagement_rate:.4f}%] {extract_title_from_caption(c.caption)}")


if __name__ == "__main__":
    asyncio.run(_test())
