"""
core/database.py — Cliente Supabase singleton.
Single Source of Truth para todas as operações de banco de dados.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from supabase import create_client, Client

from core.config import config

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  Singleton
# ------------------------------------------------------------------ #
_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.supabase.url, config.supabase.key)
        logger.info("[DB] Supabase conectado: %s", config.supabase.url)
    return _client


# ------------------------------------------------------------------ #
#  Anti-Duplicata
# ------------------------------------------------------------------ #

def check_duplicate(file_unique_id: str, title: str = None) -> bool:
    """
    Retorna True se o vídeo já foi postado (posted_history).
    Candidatos já não são persistidos, então só o histórico importa.
    Também verifica correspondência parcial do título para evitar clones reenviados.
    """
    db = get_client()
    r = db.table("posted_history").select("id").eq("file_unique_id", file_unique_id).limit(1).execute()
    if r.data:
        return True
        
    if title:
        # Busca parcial no título SEO salvo (ex: "🎬 LEGENDADO: {title} - Dublado")
        r2 = db.table("posted_history").select("id").ilike("title", f"%{title}%").limit(1).execute()
        if r2.data:
            return True
            
    return False


# Candidatos (Legado/Depreciado - Usar Snapshots)
# ------------------------------------------------------------------ #

def get_candidates_by_status(status: str) -> list[dict]:
    """Mantido apenas para compatibilidade legada."""
    db = get_client()
    try:
        r = (
            db.table("candidates")
            .select("*")
            .eq("status", status)
            .order("hype_score", desc=True)
            .execute()
        )
        return r.data or []
    except Exception:
        return []


# ------------------------------------------------------------------ #
#  SEO Variants
# ------------------------------------------------------------------ #

def insert_seo_variants(variants: list[dict]) -> None:
    db = get_client()
    db.table("seo_variants").insert(variants).execute()


def get_seo_variants(candidate_id: str, variant_type: str) -> list[dict]:
    db = get_client()
    r = (
        db.table("seo_variants")
        .select("*")
        .eq("candidate_id", candidate_id)
        .eq("variant_type", variant_type)
        .order("variant_index")
        .execute()
    )
    return r.data or []


# ------------------------------------------------------------------ #
#  Top 6 Vitrine
# ------------------------------------------------------------------ #

def get_top6_vitrine() -> list[dict]:
    """Retorna os slots da vitrine com o snapshot do candidato."""
    db = get_client()
    r = (
        db.table("top6_vitrine")
        .select("*")
        .order("slot_number")
        .execute()
    )
    return r.data or []


def upsert_vitrine_slot(slot_number: int, candidate_id: str) -> dict:
    """Cria ou substitui um slot na vitrine (legado, para compatibilidade)."""
    db = get_client()
    r = db.table("top6_vitrine").upsert(
        {
            "slot_number": slot_number,
            "candidate_id": candidate_id,
            "status": "awaiting_validation",
            "approved_title": None,
            "approved_description": None,
            "thumbnail_url": None,
        },
        on_conflict="slot_number",
    ).execute()
    return r.data[0] if r.data else {}


def upsert_vitrine_slot_memory(slot_number: int, candidate) -> dict:
    """
    Grava o estado do painel para um candidato em memória (VideoCandidate).
    Armazena os camposessenciais inline no row da vitrine — sem tabela candidates.
    """
    db = get_client()
    from modules.scraper import extract_title_from_caption  # import lazy
    r = db.table("top6_vitrine").upsert(
        {
            "slot_number": slot_number,
            "status": "awaiting_validation",
            # Snapshot inline do candidato
            "candidate_id": None,  # sem FK obrigatória
            "candidate_snapshot": {
                "file_unique_id": candidate.file_unique_id,
                "msg_id": candidate.msg_id,
                "channel_id": candidate.channel_id,
                "caption": candidate.caption,
                "duration_sec": candidate.duration_sec,
                "file_size_bytes": candidate.file_size_bytes,
                "views": candidate.views,
                "reactions": candidate.reactions,
                "synopsis": candidate.synopsis,
                "synopsis_msg_id": candidate.synopsis_msg_id,
                "hype_score": candidate.hype_score,
                "title": extract_title_from_caption(candidate.caption),
            },
            "approved_title": None,
            "approved_description": None,
            "thumbnail_url": None,
        },
        on_conflict="slot_number",
    ).execute()
    return r.data[0] if r.data else {}


def update_vitrine_slot(slot_number: int, updates: dict) -> None:
    db = get_client()
    db.table("top6_vitrine").update(updates).eq("slot_number", slot_number).execute()


def discard_vitrine_slot(slot_number: int) -> None:
    """Descarta slot deletando a linha da vitrine."""
    db = get_client()
    db.table("top6_vitrine").delete().eq("slot_number", slot_number).execute()


# ------------------------------------------------------------------ #
#  Partes Pendentes (Cortes FFmpeg)
# ------------------------------------------------------------------ #

def add_pending_part(data: dict) -> None:
    db = get_client()
    db.table("pending_parts").insert(data).execute()


def get_pending_parts(status: str = "queued") -> list[dict]:
    db = get_client()
    r = (
        db.table("pending_parts")
        .select("*")
        .eq("status", status)
        .order("created_at")
        .execute()
    )
    return r.data or []


# ------------------------------------------------------------------ #
#  Controle de Quota Dailymotion
# ------------------------------------------------------------------ #

def log_quota(dailymotion_id: str, duration_sec: int) -> None:
    db = get_client()
    db.table("quota_log").insert({
        "dailymotion_id": dailymotion_id,
        "duration_sec": duration_sec,
    }).execute()


def get_daily_quota_used() -> dict:
    """
    Retorna dict com horas e uploads usados nas últimas 24h.
    """
    db = get_client()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    r = db.table("quota_log").select("duration_sec").gte("uploaded_at", since).execute()

    rows = r.data or []
    total_sec = sum(row["duration_sec"] for row in rows)
    return {
        "uploads_used": len(rows),
        "hours_used": round(total_sec / 3600, 2),
        "seconds_used": total_sec,
    }


# ------------------------------------------------------------------ #
#  Histórico de Postados
# ------------------------------------------------------------------ #

def mark_as_posted(file_unique_id: str, dailymotion_id: str, title: str, duration_sec: int) -> None:
    """Move vídeo para histórico permanente e bloqueia re-mineração."""
    db = get_client()
    db.table("posted_history").insert({
        "file_unique_id": file_unique_id,
        "dailymotion_id": dailymotion_id,
        "title": title,
        "duration_sec": duration_sec,
    }).execute()
    logger.info("[DB] Vídeo marcado como postado: %s → DM:%s", title, dailymotion_id)
