"""
modules/validator.py — Validação de Hype Global e montagem do Top 6 Vitrine.

Fase 4 do funil:
  - Para cada candidato (em memória), conta clones no Telegram
  - Calcula score final: (engagement_rate * 0.6) + (clone_score * 0.4)
  - Seleciona Top 6 e popula a tabela top6_vitrine (estado do painel)
  - Candidatos NÃO são persistidos — vivem apenas na RAM do ciclo atual
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from core.config import config
from core import database as db
from modules.scraper import TelegramScraper, VideoCandidate, extract_title_from_caption, clean_title

logger = logging.getLogger(__name__)

# Quantos slots na vitrine
VITRINE_SIZE = 6

# Peso do engagement vs hype de clones
W_ENGAGEMENT = 0.6
W_CLONE = 0.4

# Máximo de clones esperado para normalização (score de 1.0)
CLONE_NORM_MAX = 20

# Plano B em memória — candidatos que não entraram no Top 6
_reserve_pool: list[VideoCandidate] = []


def get_reserve_pool() -> list[VideoCandidate]:
    return _reserve_pool


class HypeValidator:
    def __init__(self, client: TelegramClient):
        self.client = client

    async def count_clone_channels(self, title: str) -> int:
        """
        Pesquisa o título na rede Telegram e conta quantos canais/grupos
        estão promovendo esse drama.
        """
        title_clean = clean_title(title)
        if not title_clean:
            return 0

        try:
            await self.client.get_dialogs(limit=0)  # força cache de dialogs
            search_results = await self.client(
                __import__("telethon.tl.functions.contacts", fromlist=["SearchRequest"]).SearchRequest(
                    q=title_clean,
                    limit=50,
                )
            )
            count = len(search_results.chats) if hasattr(search_results, "chats") else 0
            logger.debug("[VALIDATOR] '%s' → %d clones encontrados", title_clean, count)
            return count

        except FloodWaitError as e:
            logger.warning("[VALIDATOR] FloodWait %ds — pulando busca de clones", e.seconds)
            await asyncio.sleep(e.seconds)
            return 0
        except Exception as e:
            logger.warning("[VALIDATOR] Erro ao buscar clones para '%s': %s", title_clean, e)
            return 0

    def _calculate_score(self, engagement_rate: float, clone_channels: int) -> float:
        clone_score = min(clone_channels / CLONE_NORM_MAX, 1.0)
        score = (engagement_rate * W_ENGAGEMENT) + (clone_score * W_CLONE)
        return round(score, 6)

    async def validate_candidates(self, candidates: list[VideoCandidate]) -> list[VideoCandidate]:
        """
        Recebe VideoCandidate em memória.
        Atribui hype_score e retorna ordenados do maior para o menor.
        """
        logger.info("[VALIDATOR] Calculando hype para %d candidatos...", len(candidates))

        for cand in candidates:
            title = extract_title_from_caption(cand.caption)
            clones = await self.count_clone_channels(title)
            cand.hype_score = self._calculate_score(cand.engagement_rate, clones)
            # Pequena pausa para não estourar rate limit
            await asyncio.sleep(1.5)

        candidates.sort(key=lambda c: c.hype_score, reverse=True)
        logger.info("[VALIDATOR] Scoring concluído.")
        return candidates

    def build_top6_vitrine(self, scored_candidates: list[VideoCandidate]) -> list[VideoCandidate]:
        """
        Monta o Top 6 na vitrine (estado do painel).
        - Slots com status 'validated' ou 'uploading' são intocáveis.
        - Slots 'awaiting_validation' são substituídos pelos novos tops Hype.
        - Os que não entraram ficam no _reserve_pool em memória.
        """
        global _reserve_pool

        current_vitrine = db.get_top6_vitrine()

        # Slots travados (usuário já aprovou ou está enviando)
        protected_statuses = {"validated", "uploading"}
        protected_candidate_ids = set()
        used_slots = set()

        for slot in current_vitrine:
            if slot["status"] in protected_statuses:
                used_slots.add(slot["slot_number"])
                if slot.get("candidate_id"):
                    protected_candidate_ids.add(slot["candidate_id"])

        # Slots livres (awaiting_validation e vazios são todos substituíveis)
        free_slots = [i for i in range(1, VITRINE_SIZE + 1) if i not in used_slots]

        logger.info(
            "[VALIDATOR] Slots protegidos: %s. Slots livres: %s",
            list(used_slots), free_slots
        )

        assigned = []
        reserve = list(scored_candidates)

        for slot_num in free_slots:
            if not reserve:
                break
            cand = reserve.pop(0)

            # Persiste apenas o estado do painel (sem candidatos no banco)
            db.upsert_vitrine_slot_memory(
                slot_number=slot_num,
                candidate=cand,
            )
            assigned.append(cand)
            logger.info(
                "[VALIDATOR] Slot %d → '%s' (hype=%.4f)",
                slot_num,
                extract_title_from_caption(cand.caption)[:30],
                cand.hype_score,
            )

        # Plano B — armazena em memória
        _reserve_pool = reserve
        logger.info(
            "[VALIDATOR] Reposição concluída: %d no painel, %d na reserva RAM.",
            len(assigned), len(_reserve_pool)
        )
        return assigned


# ------------------------------------------------------------------ #
#  Orquestrador: Scraper → Validator → Top 6 (tudo em memória)
# ------------------------------------------------------------------ #

async def run_full_mining_cycle(client: Optional[TelegramClient] = None):
    """
    Pipeline completo: mineração + validação + montagem do Top 6 Vitrine.
    Candidatos vivem APENAS em memória RAM neste ciclo.
    Apenas posted_history é consultado para anti-duplicata.
    """
    logger.info("=" * 60)
    logger.info("[PIPELINE] Iniciando ciclo de mineração completo")
    logger.info("=" * 60)

    async with TelegramScraper(client) as scraper:
        # Fase 1–3: Scraping → retorna VideoCandidate[] em memória
        candidates: list[VideoCandidate] = await scraper.run()

        if not candidates:
            logger.warning("[PIPELINE] Sem candidatos para validar.")
            return

        # Fase 4: Score de Hype
        validator = HypeValidator(scraper.client)
        scored = await validator.validate_candidates(candidates)

        # Fase 5: Top 6 Vitrine
        top6 = validator.build_top6_vitrine(scored)

    logger.info("[PIPELINE] Ciclo concluído. Top 6 Vitrine atualizado.")
    return top6


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(run_full_mining_cycle())
