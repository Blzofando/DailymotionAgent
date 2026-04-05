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

def check_duplicate(file_unique_id: str) -> bool:
    """
    Retorna True se o vídeo já foi processado (candidates ou posted_history).
    Isso é o guardião principal contra re-postagem.
    """
    db = get_client()

    # Verifica histórico de postados
    r = db.table("posted_history").select("id").eq("file_unique_id", file_unique_id).limit(1).execute()
    if r.data:
        return True

    # Verifica candidatos já em pipeline
    r = db.table("candidates").select("id").eq("file_unique_id", file_unique_id).limit(1).execute()
    return bool(r.data)


# ------------------------------------------------------------------ #
#  Candidatos
# ------------------------------------------------------------------ #

def insert_candidate(data: dict) -> Optional[dict]:
    """Insere candidato minerado. Retorna o registro ou None se duplicata."""
    if check_duplicate(data["file_unique_id"]):
        logger.debug("[DB] Duplicata ignorada: %s", data.get("file_unique_id"))
        return None

    db = get_client()
    r = db.table("candidates").insert(data).execute()
    return r.data[0] if r.data else None


def update_candidate(candidate_id: str, updates: dict) -> None:
    db = get_client()
    db.table("candidates").update(updates).eq("id", candidate_id).execute()


def get_candidates_by_status(status: str) -> list[dict]:
    db = get_client()
    r = (
        db.table("candidates")
        .select("*")
        .eq("status", status)
        .order("hype_score", desc=True)
        .execute()
    )
    return r.data or []


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
    """Retorna os slots da vitrine com dados do candidato via join."""
    db = get_client()
    r = (
        db.table("top6_vitrine")
        .select("*, candidates(*)")
        .order("slot_number")
        .execute()
    )
    return r.data or []


def upsert_vitrine_slot(slot_number: int, candidate_id: str) -> dict:
    """Cria ou substitui um slot na vitrine."""
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


def update_vitrine_slot(slot_number: int, updates: dict) -> None:
    db = get_client()
    db.table("top6_vitrine").update(updates).eq("slot_number", slot_number).execute()


def discard_vitrine_slot(slot_number: int) -> None:
    """Descarta slot e marca candidato como descartado."""
    db = get_client()
    slot = db.table("top6_vitrine").select("candidate_id").eq("slot_number", slot_number).execute()
    if slot.data:
        cid = slot.data[0]["candidate_id"]
        db.table("candidates").update({"status": "discarded"}).eq("id", cid).execute()
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
    # Atualiza status do candidato
    db.table("candidates").update({"status": "posted"}).eq("file_unique_id", file_unique_id).execute()
    logger.info("[DB] Vídeo marcado como postado: %s → DM:%s", title, dailymotion_id)
