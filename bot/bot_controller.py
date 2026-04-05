"""
bot/bot_controller.py — Dashboard de Controle Telegram.

Implementa o Loop completo do Bot:
  /start → Lobby (Health Check + Slots)
  [Validar Slot N] → Túnel de 4 passos (Título → Sinopse → Capa → Match)
  [Enviar Slot N]  → Pipeline de upload com feedback em tempo real
  [Descartar]      → Remove slot e puxa Plano B da reserva
"""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from telethon import TelegramClient

from core.config import config
from core import database as db
from modules.quota_manager import get_quota_status
from modules.seo_engine import generate_seo_package
from modules.uploader import run_upload_pipeline
from modules.scraper import extract_title_from_caption
from bot.keyboards import (
    lobby_keyboard,
    title_carousel_keyboard,
    description_carousel_keyboard,
    thumbnail_carousel_keyboard,
    video_match_keyboard,
)

logger = logging.getLogger(__name__)

# Estado de sessão em memória (não crítico — reinicia com o bot)
_session: dict = {}


def admin_only(func):
    """Decorator que bloqueia qualquer chat que não seja o do admin."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if uid != config.telegram.admin_chat_id:
            logger.warning("[BOT] Acesso negado para user_id=%s", uid)
            return
        return await func(update, ctx)
    return wrapper


# ------------------------------------------------------------------ #
#  Montagem do texto do Lobby
# ------------------------------------------------------------------ #

def build_lobby_text(vitrine: list[dict], quota) -> str:
    lines = [
        "🎛️ *PAINEL DE CONTROLE — DAILYMOTION*",
        f"🔋 Capacidade Restante: *{quota.hours_remaining:.1f}h* | *{quota.uploads_remaining} Uploads* disponíveis\n",
    ]

    status_icons = {
        "awaiting_validation": "🔴",
        "validated": "🟢",
        "uploading": "⏳",
        "posted": "✅",
        "discarded": "❌",
    }

    for slot in vitrine[:quota.visible_slots]:
        n = slot["slot_number"]
        cand = slot.get("candidates") or {}
        title = extract_title_from_caption(cand.get("caption", f"Slot {n}"))
        dur = cand.get("duration_sec", 0)
        h, m = divmod(dur // 60, 60)
        hype = cand.get("hype_score", 0)
        icon = status_icons.get(slot.get("status", ""), "❓")
        status_label = slot.get("status", "").replace("_", " ").title()

        lines.append(
            f"🎬 *SLOT {n}:* [Hype: {hype:.0%}] — {title}\n"
            f"   ⏱️ {h}h {m:02d}m | Status: {icon} {status_label}"
        )

    if not vitrine:
        lines.append("ℹ️ Nenhum drama na vitrine. Execute o ciclo de mineração.")

    return "\n".join(lines)


# ------------------------------------------------------------------ #
#  /start — Lobby
# ------------------------------------------------------------------ #

@admin_only
async def start_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_lobby(update, ctx)


async def _show_lobby(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    quota = get_quota_status()
    vitrine = db.get_top6_vitrine()
    text = build_lobby_text(vitrine, quota)
    kb = lobby_keyboard(vitrine, quota.visible_slots)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
        )
    else:
        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if msg:
            await msg.reply_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


# ------------------------------------------------------------------ #
#  Callback: validate_N → Passo 1/4 (Título)
# ------------------------------------------------------------------ #

@admin_only
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "noop":
        return

    if data == "refresh":
        await _show_lobby(update, ctx, edit=True)

    elif data.startswith("validate_"):
        slot = int(data.split("_")[1])
        await _step_title(update, ctx, slot)

    elif data.startswith("title_"):
        await _handle_title_nav(update, ctx, data)

    elif data.startswith("desc_"):
        await _handle_desc_nav(update, ctx, data)

    elif data.startswith("thumb_"):
        await _handle_thumb_nav(update, ctx, data)

    elif data.startswith("match_"):
        await _handle_match(update, ctx, data)

    elif data.startswith("send_"):
        slot = int(data.split("_")[1])
        await _trigger_upload(update, ctx, slot)


# ------------------------------------------------------------------ #
#  Passo 1/4 — Seleção de Título
# ------------------------------------------------------------------ #

async def _step_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    """Exibe as variações de título para o slot."""
    query = update.callback_query

    vitrine = db.get_top6_vitrine()
    slot_data = next((s for s in vitrine if s["slot_number"] == slot), None)
    if not slot_data:
        await query.edit_message_text("❌ Slot não encontrado.")
        return

    cand = slot_data.get("candidates") or {}
    cand_id = cand.get("id")

    # Carrega variantes de título do banco
    variants = db.get_seo_variants(cand_id, "title") if cand_id else []

    if not variants:
        # Gera SEO na hora se ainda não foi gerado
        await query.edit_message_text("⚙️ Gerando SEO... Aguarde.")
        pkg = await generate_seo_package(cand)
        variants = db.get_seo_variants(cand_id, "title")

    _session[f"slot_{slot}_titles"] = [v["content"] for v in variants]
    _session[f"slot_{slot}_title_idx"] = 0

    await _render_title_step(update, ctx, slot)


async def _render_title_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    titles = _session.get(f"slot_{slot}_titles", [])
    idx = _session.get(f"slot_{slot}_title_idx", 0)
    current_title = titles[idx] if titles else "Sem título"

    text = (
        f"🏷️ *PASSO 1/4: Escolha o Título (Slot {slot})*\n\n"
        f"Opção Atual:\n> {current_title}"
    )
    kb = title_carousel_keyboard(slot, idx, len(titles))
    await update.callback_query.edit_message_text(
        text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
    )


async def _handle_title_nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split("_")
    action = parts[1]  # prev, next, confirm
    slot = int(parts[2])
    current = int(parts[3]) if len(parts) > 3 else 0

    titles = _session.get(f"slot_{slot}_titles", [])

    if action == "prev":
        _session[f"slot_{slot}_title_idx"] = (current - 1) % len(titles)
        await _render_title_step(update, ctx, slot)

    elif action == "next":
        _session[f"slot_{slot}_title_idx"] = (current + 1) % len(titles)
        await _render_title_step(update, ctx, slot)

    elif action == "confirm":
        confirmed_title = titles[current] if titles else ""
        db.update_vitrine_slot(slot, {"approved_title": confirmed_title})
        _session[f"slot_{slot}_confirmed_title"] = confirmed_title
        await _step_description(update, ctx, slot)


# ------------------------------------------------------------------ #
#  Passo 2/4 — Revisão da Sinopse
# ------------------------------------------------------------------ #

async def _step_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    vitrine = db.get_top6_vitrine()
    slot_data = next((s for s in vitrine if s["slot_number"] == slot), None)
    cand = slot_data.get("candidates") or {} if slot_data else {}
    cand_id = cand.get("id")

    variants = db.get_seo_variants(cand_id, "description") if cand_id else []
    _session[f"slot_{slot}_descs"] = [v["content"] for v in variants]
    _session[f"slot_{slot}_desc_idx"] = 0

    await _render_desc_step(update, ctx, slot)


async def _render_desc_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    descs = _session.get(f"slot_{slot}_descs", [])
    idx = _session.get(f"slot_{slot}_desc_idx", 0)
    current_desc = descs[idx] if descs else "Sem descrição"

    preview = current_desc[:400] + "..." if len(current_desc) > 400 else current_desc
    text = f"📝 *PASSO 2/4: Revisão da Descrição (Slot {slot})*\n\n{preview}"
    kb = description_carousel_keyboard(slot)
    await update.callback_query.edit_message_text(
        text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
    )


async def _handle_desc_nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split("_")
    action = parts[1]
    slot = int(parts[2])

    descs = _session.get(f"slot_{slot}_descs", [])
    idx = _session.get(f"slot_{slot}_desc_idx", 0)

    if action == "prev":
        _session[f"slot_{slot}_desc_idx"] = (idx - 1) % len(descs)
        await _render_desc_step(update, ctx, slot)

    elif action == "next":
        _session[f"slot_{slot}_desc_idx"] = (idx + 1) % len(descs)
        await _render_desc_step(update, ctx, slot)

    elif action == "confirm":
        confirmed = descs[idx] if descs else ""
        # Extrai tags do texto da descrição (salvas junto nas variants)
        db.update_vitrine_slot(slot, {"approved_description": confirmed})
        await _step_thumbnail(update, ctx, slot)


# ------------------------------------------------------------------ #
#  Passo 3/4 — Seleção de Capa
# ------------------------------------------------------------------ #

async def _step_thumbnail(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    """Por ora, usa thumbnail_url já salva no candidato (raspagem do canal)."""
    vitrine = db.get_top6_vitrine()
    slot_data = next((s for s in vitrine if s["slot_number"] == slot), None)
    cand = slot_data.get("candidates") or {} if slot_data else {}

    # Thumbnails raspadas (funcionalidade futura: múltiplas do canal clone)
    thumbs = _session.get(f"slot_{slot}_thumbs", [cand.get("thumbnail_url") or ""])
    _session[f"slot_{slot}_thumbs"] = thumbs
    _session[f"slot_{slot}_thumb_idx"] = 0

    await _render_thumb_step(update, ctx, slot)


async def _render_thumb_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    thumbs = _session.get(f"slot_{slot}_thumbs", [])
    idx = _session.get(f"slot_{slot}_thumb_idx", 0)
    current_url = thumbs[idx] if thumbs else None
    kb = thumbnail_carousel_keyboard(slot, idx, len(thumbs))

    text = f"🖼️ *PASSO 3/4: Escolha a Capa Limpa (Slot {slot})*\n\n"
    if current_url:
        text += f"URL da Capa:\n`{current_url[:80]}...`"
    else:
        text += "⚠️ Nenhuma capa disponível. Será postado sem capa."

    await update.callback_query.edit_message_text(
        text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
    )


async def _handle_thumb_nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split("_")
    action = parts[1]
    slot = int(parts[2])
    current = int(parts[3]) if len(parts) > 3 else 0

    thumbs = _session.get(f"slot_{slot}_thumbs", [])

    if action == "prev":
        _session[f"slot_{slot}_thumb_idx"] = (current - 1) % max(len(thumbs), 1)
        await _render_thumb_step(update, ctx, slot)

    elif action == "next":
        _session[f"slot_{slot}_thumb_idx"] = (current + 1) % max(len(thumbs), 1)
        await _render_thumb_step(update, ctx, slot)

    elif action == "confirm":
        confirmed_url = thumbs[current] if thumbs else None
        db.update_vitrine_slot(slot, {"thumbnail_url": confirmed_url})
        await _step_video_match(update, ctx, slot)


# ------------------------------------------------------------------ #
#  Passo 4/4 — Confirmação de Match do Vídeo
# ------------------------------------------------------------------ #

async def _step_video_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    vitrine = db.get_top6_vitrine()
    slot_data = next((s for s in vitrine if s["slot_number"] == slot), None)
    cand = slot_data.get("candidates") or {} if slot_data else {}
    title = slot_data.get("approved_title", "Drama") if slot_data else "Drama"

    text = (
        f"🎥 *PASSO 4/4: Confirmação do Arquivo (Slot {slot})*\n\n"
        f"Título aprovado: *{title}*\n\n"
        f"O vídeo associado a esta sinopse está correto?"
    )
    kb = video_match_keyboard(slot)
    await update.callback_query.edit_message_text(
        text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
    )


async def _handle_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split("_")
    action = parts[1]  # discard ou confirm
    slot = int(parts[2])

    if action == "discard":
        db.discard_vitrine_slot(slot)
        # Puxa próximo da reserva (Plano B)
        reserves = db.get_candidates_by_status("reserve")
        if reserves:
            db.upsert_vitrine_slot(slot, reserves[0]["id"])
        await update.callback_query.answer("❌ Slot descartado. Próximo da reserva puxado.")
        await _show_lobby(update, ctx, edit=True)

    elif action == "confirm":
        db.update_vitrine_slot(slot, {"status": "validated"})
        await update.callback_query.answer("✅ Validação concluída!")
        await _show_lobby(update, ctx, edit=True)


# ------------------------------------------------------------------ #
#  Trigger de Upload
# ------------------------------------------------------------------ #

async def _trigger_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    """Inicia o pipeline de upload com feedback em tempo real ao usuário."""
    query = update.callback_query
    await query.edit_message_text(f"⏳ Iniciando envio do Slot {slot}...")

    # O cliente Telethon é passado via context (configurado no main.py)
    telethon_client: TelegramClient = ctx.bot_data.get("telethon_client")
    if not telethon_client:
        await query.edit_message_text("❌ Erro: cliente Telethon não inicializado.")
        return

    async def progress(status_text: str):
        try:
            await query.edit_message_text(status_text)
        except Exception:
            pass  # Ignora erros de edição (Telegram throttle)

    try:
        result = await run_upload_pipeline(
            client=telethon_client,
            slot_number=slot,
            progress_callback=progress,
        )
        await query.edit_message_text(
            f"✅ *UPLOAD CONCLUÍDO!*\n"
            f"🎬 {result['title']}\n"
            f"🔗 {result['url']}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error("[BOT] Erro no upload do Slot %d: %s", slot, e, exc_info=True)
        db.update_vitrine_slot(slot, {"status": "validated"})  # Reverte lock
        await query.edit_message_text(f"❌ Erro no upload:\n`{str(e)[:300]}`", parse_mode=ParseMode.MARKDOWN)


# ------------------------------------------------------------------ #
#  Fábrica do Bot
# ------------------------------------------------------------------ #

def create_bot(telethon_client: TelegramClient) -> Application:
    """Cria e configura a aplicação do Bot."""
    app = Application.builder().token(config.telegram.bot_token).build()
    app.bot_data["telethon_client"] = telethon_client

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("[BOT] Bot configurado e pronto.")
    return app
