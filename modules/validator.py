"""
modules/validator.py — Validação de Hype Global e montagem do Top 6 Vitrine.

Fase 4 do funil:
  - Para cada candidato, conta quantos canais Telegram promovem o drama (clone_channels)
  - Calcula score final: (engagement_rate * 0.6) + (clone_score * 0.4)
  - Seleciona Top 6 e popula a tabela top6_vitrine
  - Demais ficam em 'reserve' como Plano B
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


class HypeValidator:
    def __init__(self, client: TelegramClient):
        self.client = client

    async def count_clone_channels(self, title: str) -> int:
        """
        Pesquisa o título na rede Telegram e conta quantos canais/grupos
        estão promovendo esse drama. Limita a busca para não explodir o rate limit.
        """
        title_clean = clean_title(title)
        if not title_clean:
            return 0

        try:
            results = await self.client.get_dialogs(limit=0)  # força cache
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
        """
        Score final normalizado entre 0 e 1.
        engagement_rate: reactions/views (0 a 1)
        clone_channels: número de canais que promovem (normalizado pelo máximo esperado)
        """
        clone_score = min(clone_channels / CLONE_NORM_MAX, 1.0)
        score = (engagement_rate * W_ENGAGEMENT) + (clone_score * W_CLONE)
        return round(score, 6)

    async def validate_candidates(self, candidates: list[dict]) -> list[dict]:
        """
        Recebe candidatos do banco (com id, views, reactions, caption).
        Atribui hype_score e retorna ordenados do maior para o menor.
        """
        logger.info("[VALIDATOR] Calculando hype para %d candidatos...", len(candidates))
        scored = []

        for cand in candidates:
            views = cand.get("views", 0) or 0
            reactions = cand.get("reactions", 0) or 0
            engagement = reactions / views if views > 0 else 0.0

            title = extract_title_from_caption(cand.get("caption", ""))
            clones = await self.count_clone_channels(title)

            score = self._calculate_score(engagement, clones)

            # Atualiza no banco
            db.update_candidate(cand["id"], {
                "hype_score": score,
                "clone_channels": clones,
            })

            cand["hype_score"] = score
            cand["clone_channels"] = clones
            scored.append(cand)

            # Pequena pausa para não explodir o rate limit do Telegram
            await asyncio.sleep(1.5)

        scored.sort(key=lambda c: c["hype_score"], reverse=True)
        logger.info("[VALIDATOR] Scoring concluído.")
        return scored

    def build_top6_vitrine(self, scored_candidates: list[dict]) -> list[dict]:
        """
        Popula os 6 primeiros candidatos na vitrine.
        Demais permanecem em 'reserve' como Plano B.
        """
        top6 = scored_candidates[:VITRINE_SIZE]
        reserve = scored_candidates[VITRINE_SIZE:]

        logger.info(
            "[VALIDATOR] Top 6 selecionados. %d ficam na reserva (Plano B).",
            len(reserve),
        )

        for i, cand in enumerate(top6, start=1):
            db.upsert_vitrine_slot(slot_number=i, candidate_id=cand["id"])
            db.update_candidate(cand["id"], {"status": "vitrine"})
            logger.info(
                "[VALIDATOR] Slot %d → '%s' (score=%.4f)",
                i, extract_title_from_caption(cand.get("caption", "")), cand["hype_score"]
            )

        return top6


# ------------------------------------------------------------------ #
#  Orquestrador: Scraper → Validator → Top 6
# ------------------------------------------------------------------ #

async def run_full_mining_cycle():
    """
    Pipeline completo: mineração + validação + montagem do Top 6 Vitrine.
    Chamado pelo main.py no ciclo agendado.
    """
    logger.info("=" * 60)
    logger.info("[PIPELINE] Iniciando ciclo de mineração completo")
    logger.info("=" * 60)

    async with TelegramScraper() as scraper:
        # Fase 1–3: Scraping
        await scraper.run()

        # Carrega candidatos recém inseridos do banco
        candidates = db.get_candidates_by_status("reserve")
        if not candidates:
            logger.warning("[PIPELINE] Sem candidatos novos para validar.")
            return

        # Fase 4: Hype Global
        validator = HypeValidator(scraper.client)
        scored = await validator.validate_candidates(candidates)

        # Fase 5: Top 6 Vitrine
        top6 = validator.build_top6_vitrine(scored)

    logger.info("[PIPELINE] Ciclo concluído. Top 6 Vitrine atualizado.")
    return top6


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(run_full_mining_cycle())
