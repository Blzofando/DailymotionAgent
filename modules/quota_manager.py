"""
modules/quota_manager.py — Gestor de Limites Diários do Dailymotion.

Monitora em tempo real a "bateria" de:
  - 10 horas de vídeo por dia
  - 15 uploads por dia

Decide quantos slots o Dashboard deve exibir e bloqueia uploads
que excederiam os limites.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.config import config
from core import database as db

logger = logging.getLogger(__name__)

# Limite Dailymotion Starter
MAX_HOURS = config.dailymotion.max_hours_per_day
MAX_UPLOADS = config.dailymotion.max_uploads_per_day
MAX_SECONDS = int(MAX_HOURS * 3600)

# Duração média estimada de um slot (1h30m = 5400s)
AVG_SLOT_DURATION = 5400


@dataclass
class QuotaStatus:
    uploads_used: int
    hours_used: float
    seconds_used: int
    uploads_remaining: int
    hours_remaining: float
    seconds_remaining: int
    visible_slots: int
    can_upload: bool

    def summary_line(self) -> str:
        """String formatada para o Dashboard Telegram."""
        return (
            f"🔋 Capacidade Restante: "
            f"{self.hours_remaining:.1f}h | "
            f"{self.uploads_remaining} Uploads disponíveis"
        )


def get_quota_status() -> QuotaStatus:
    """
    Consulta o banco e calcula o status atual da quota Dailymotion.
    """
    used = db.get_daily_quota_used()

    uploads_used = used["uploads_used"]
    seconds_used = used["seconds_used"]
    hours_used = used["hours_used"]

    uploads_remaining = max(0, MAX_UPLOADS - uploads_used)
    seconds_remaining = max(0, MAX_SECONDS - seconds_used)
    hours_remaining = round(seconds_remaining / 3600, 2)

    # Quantos slots cabem no tempo restante (estimativa conservadora)
    visible_slots = min(
        uploads_remaining,
        seconds_remaining // AVG_SLOT_DURATION,
        6,  # Máximo do painel
    )

    can_upload = uploads_remaining > 0 and seconds_remaining > 0

    status = QuotaStatus(
        uploads_used=uploads_used,
        hours_used=hours_used,
        seconds_used=seconds_used,
        uploads_remaining=uploads_remaining,
        hours_remaining=hours_remaining,
        seconds_remaining=seconds_remaining,
        visible_slots=int(visible_slots),
        can_upload=can_upload,
    )

    logger.debug(
        "[QUOTA] Usados: %dh%02dm / %d uploads | Restam: %.1fh / %d uploads | Slots visíveis: %d",
        int(hours_used), int((hours_used % 1) * 60),
        uploads_used,
        hours_remaining,
        uploads_remaining,
        visible_slots,
    )

    return status


def is_within_limits(video_duration_sec: int) -> tuple[bool, str]:
    """
    Verifica se um vídeo específico pode ser uploadado agora.
    Retorna (pode_uplodar: bool, motivo: str).
    """
    status = get_quota_status()

    if not status.can_upload:
        return False, "❌ Limite diário atingido. Tente novamente amanhã."

    if video_duration_sec > status.seconds_remaining:
        horas = video_duration_sec / 3600
        return False, (
            f"❌ Vídeo de {horas:.1f}h excede o saldo restante de {status.hours_remaining:.1f}h. "
            f"Considere postar amanhã ou cortar o vídeo."
        )

    return True, "✅ Dentro dos limites."


def register_upload(dailymotion_id: str, duration_sec: int) -> None:
    """
    Registra um upload concluído no log de quota.
    Deve ser chamado APÓS confirmação de sucesso do upload.
    """
    db.log_quota(dailymotion_id=dailymotion_id, duration_sec=duration_sec)
    logger.info(
        "[QUOTA] Upload registrado: DM_ID=%s | Duração=%ds",
        dailymotion_id, duration_sec
    )
