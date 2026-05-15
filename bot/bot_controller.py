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
from telegram.error import BadRequest
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telethon import TelegramClient

from core.config import config
from core import database as db
from modules.quota_manager import get_quota_status
from modules.seo_engine import generate_seo_package
from modules.uploader import run_upload_pipeline
from modules.scraper import extract_title_from_caption
from modules.validator import run_full_mining_cycle
from bot.keyboards import (
    lobby_keyboard,
    title_carousel_keyboard,
    description_carousel_keyboard,
    thumbnail_carousel_keyboard,
    video_match_keyboard,
    remove_reason_keyboard,
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
        "🎛️ *PAINEL DE CONTROLE OMNI | DAILYMOTION*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔋 *Capacidade Restante:* {quota.hours_remaining:.1f}h | {quota.uploads_remaining} Uploads",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    status_icons = {
        "awaiting_validation": "🔴 Pendente",
        "validated": "🟢 Pronto p/ Upload",
        "uploading": "⏳ Enviando...",
        "posted": "✅ Publicado",
        "discarded": "❌ Descartado",
    }

    if not vitrine:
        lines.append("ℹ️ Nenhum drama na vitrine. Execute o ciclo de mineração.")
    else:
        for slot in vitrine[:quota.visible_slots]:
            n = slot["slot_number"]
            # Novo modelo: snapshot inline, sem join
            cand = slot.get("candidate_snapshot") or slot.get("candidates") or {}
            
            # Formata título para não poluir
            title = cand.get("title") or extract_title_from_caption(cand.get("caption", f"Slot {n}"))
            if len(title) > 35:
                title = title[:35] + "..."
                
            dur = cand.get("duration_sec", 0)
            h, m = divmod(dur // 60, 60)
            hype = cand.get("hype_score", 0)
            icon_status = status_icons.get(slot.get("status", ""), "❓ Oculto")

            lines.append(
                f"🎬 *[SLOT {n}]* {title}\n"
                f"      ├ Status: {icon_status}\n"
                f"      ├ Duração: {h}h {m:02d}m\n"
                f"      └ Relevância: {hype:.0%}\n"
            )

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
        msg = update.callback_query.message
        if msg and msg.photo:
            await msg.delete()
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
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
    try:
        await query.answer()
    except BadRequest as e:
        logger.warning(f"[BOT] Timeout tolerado no callback answer: {e}")
        
    data = query.data

    if data == "noop":
        return

    if data == "refresh":
        await _show_lobby(update, ctx, edit=True)

    elif data == "trigger_mining":
        await query.answer("⛏️ Iniciando varredura profunda no canal... Isso fará uma busca demorada.", show_alert=True)
        await query.edit_message_text(
            "⏳ *Varredura em background rodando...*\nIsso pode levar de 2 a 10 minutos dependendo da IA e dos downloads de capa. Não se preocupe, quando os novos vídeos forem encontrados eu irei atualizar o banco de dados. Volte aqui e clique em 'Atualizar Painel' no menu /start mais tarde.",
            parse_mode=ParseMode.MARKDOWN
        )
        # Roda em background para não bugar o callback que tem timeout de 60s
        asyncio.create_task(_run_background_mining(ctx, update.effective_chat.id))

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

    elif data.startswith("remove_prompt_"):
        slot = int(data.split("_")[2])
        kb = remove_reason_keyboard(slot)
        await query.edit_message_text(
            f"❌ *Remover Slot {slot} da Vitrine*\n\nPor que deseja remover este vídeo da lista de Prontos para Envio?",
            reply_markup=kb, parse_mode=ParseMode.MARKDOWN
        )

    elif data.startswith("remove_history_"):
        slot = int(data.split("_")[2])
        vitrine = db.get_top6_vitrine()
        slot_data = next((s for s in vitrine if s["slot_number"] == slot), None)
        if slot_data:
            cand = slot_data.get("candidate_snapshot") or slot_data.get("candidates") or {}
            title = slot_data.get("approved_title") or cand.get("title") or "Drama"
            # Marca como postado para não voltar
            db.mark_as_posted(
                file_unique_id=cand.get("file_unique_id", "manual"),
                dailymotion_id="manual_removal",
                title=title,
                duration_sec=cand.get("duration_sec", 0)
            )
        db.discard_vitrine_slot(slot)
        from modules.validator import get_reserve_pool
        reserve = get_reserve_pool()
        if reserve:
            db.upsert_vitrine_slot_memory(slot_number=slot, candidate=reserve.pop(0))
        await query.answer("🗑️ Adicionado ao histórico para não voltar mais.")
        await _show_lobby(update, ctx, edit=True)

    elif data.startswith("remove_discard_"):
        slot = int(data.split("_")[2])
        db.discard_vitrine_slot(slot)
        from modules.validator import get_reserve_pool
        reserve = get_reserve_pool()
        if reserve:
            db.upsert_vitrine_slot_memory(slot_number=slot, candidate=reserve.pop(0))
        await query.answer("👎 Removido. Retornando ao pool.")
        await _show_lobby(update, ctx, edit=True)

    elif data.startswith("edit_manual_"):
        # Format: edit_manual_{type}_{slot}
        parts = data.split("_")
        edit_type = parts[2]
        slot = int(parts[3])
        
        user_id = update.effective_user.id
        _session[f"awaiting_edit_{user_id}"] = {"type": edit_type, "slot": slot}
        
        if edit_type == "title":
            titles = _session.get(f"slot_{slot}_titles", [])
            idx = _session.get(f"slot_{slot}_title_idx", 0)
            current = titles[idx] if titles else ""
            msg = f"✍️ *Edição Manual de Título (Slot {slot})*\nCopie o texto abaixo, faça suas alterações e me envie no chat:\n\n`{current}`"
        elif edit_type == "desc":
            descs = _session.get(f"slot_{slot}_descs", [])
            idx = _session.get(f"slot_{slot}_desc_idx", 0)
            current = descs[idx] if descs else ""
            msg = f"✍️ *Edição Manual de Sinopse (Slot {slot})*\nCopie o texto abaixo, edite e me envie aqui no chat:\n\n`{current}`"
        elif edit_type == "thumb":
            msg = f"🖼️ *Edição Manual de Capa (Slot {slot})*\nMe envie aqui no chat o **Link URL** da imagem que você quer usar."
        
        msg_obj = update.effective_message
        if msg_obj and msg_obj.photo:
            await msg_obj.delete()
            await ctx.bot.send_message(chat_id=user_id, text=msg, parse_mode=ParseMode.MARKDOWN)
        else:
            await query.edit_message_text(text=msg, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("force_send_"):
        slot = int(data.split("_")[-1])
        await _trigger_upload(update, ctx, slot, force=True)
        
    elif data.startswith("viewfull_"):
        slot = int(data.split("_")[1])
        await _handle_view_full(update, ctx, slot)


# ------------------------------------------------------------------ #
#  Visualizador Completo da Vitrine
# ------------------------------------------------------------------ #

async def _handle_view_full(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    vitrine = db.get_top6_vitrine()
    slot_data = next((s for s in vitrine if s["slot_number"] == slot), None)
    if not slot_data:
        return
        
    title = slot_data.get("approved_title", "")
    desc = slot_data.get("approved_description", "")
    thumb = slot_data.get("thumbnail_url", "")
    
    caption_text = f"🎬 *Título SEO:*\n{title}\n\n📝 *Descrição Completa:*\n{desc}"
    kb = view_full_keyboard(slot)
    
    await update.callback_query.message.delete()
    
    if thumb:
        try:
            await ctx.bot.send_photo(chat_id=update.effective_chat.id, photo=thumb)
        except Exception as e:
            logger.warning(f"Não foi possivel enviar a cover no preview: {e}")
            
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=caption_text,
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN
    )



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

    # Lê do candidate_snapshot (novo modelo sem join)
    cand = slot_data.get("candidate_snapshot") or slot_data.get("candidates") or {}
    cand_file_id = cand.get("file_unique_id")

    # Verifica se já temos variantes na session para este slot e se pertencem ao vídeo atual
    session_titles = _session.get(f"slot_{slot}_titles")
    session_file_id = _session.get(f"slot_{slot}_file_id")

    if not session_titles or session_file_id != cand_file_id:
        await query.edit_message_text("⚙️ Gerando SEO... Aguarde.")
        pkg = await generate_seo_package(cand)

        # Armazena em session e invalida caches antigos
        _session[f"slot_{slot}_file_id"] = cand_file_id
        _session[f"slot_{slot}_titles"] = pkg.get("title_variants", [cand.get("title", "Sem título")])
        _session[f"slot_{slot}_description"] = pkg.get("description", "")
        _session[f"slot_{slot}_tags"] = pkg.get("tags", "")
        
        # Limpa escolhas anteriores
        _session.pop(f"slot_{slot}_thumbs", None)
        _session.pop(f"slot_{slot}_descs", None)

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
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
        )
    else:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id, text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
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
    cand = (slot_data.get("candidate_snapshot") or slot_data.get("candidates") or {}) if slot_data else {}

    # Usa a descrição já gerada na session (gerada no _step_title)
    session_desc = _session.get(f"slot_{slot}_description")
    if session_desc:
        _session[f"slot_{slot}_descs"] = [session_desc]
    else:
        _session[f"slot_{slot}_descs"] = [cand.get("synopsis", "Sem descrição disponivel.")]
    _session[f"slot_{slot}_desc_idx"] = 0

    await _render_desc_step(update, ctx, slot)


async def _render_desc_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    descs = _session.get(f"slot_{slot}_descs", [])
    idx = _session.get(f"slot_{slot}_desc_idx", 0)
    current_desc = descs[idx] if descs else "Sem descrição"

    text = f"📝 *PASSO 2/4: Revisão da Descrição (Slot {slot})*\n\n{current_desc}"
    kb = description_carousel_keyboard(slot)
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
        )
    else:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id, text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
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
    vitrine = db.get_top6_vitrine()
    slot_data = next((s for s in vitrine if s["slot_number"] == slot), None)
    cand = (slot_data.get("candidate_snapshot") or slot_data.get("candidates") or {}) if slot_data else {}

    thumbs = _session.get(f"slot_{slot}_thumbs", [])
    if not thumbs:
        msg = update.effective_message
        loading_text = "🔍 Buscando capa do drama globalmente..."
        # Se a mensagem atual é foto, deleta e envia texto (Telegram não permite edit_message_text em fotos)
        if msg and msg.photo:
            await msg.delete()
            loading_msg = await ctx.bot.send_message(
                chat_id=update.effective_chat.id, text=loading_text
            )
        else:
            loading_msg = await update.callback_query.edit_message_text(loading_text)
        
        from modules.thumbnail_engine import search_and_upload_thumbnail
        from modules.scraper import extract_title_from_caption
        
        telethon_client = ctx.bot_data.get("telethon_client")
        base_title = extract_title_from_caption(cand.get("caption", "") if isinstance(cand, dict) else cand.caption if hasattr(cand, "caption") else "")
        
        if telethon_client:
            urls = await search_and_upload_thumbnail(telethon_client, base_title[:20])
            if urls:
                thumbs.extend(urls)
                
        if not thumbs:
            snap_thumb = cand.get("thumbnail_url") if isinstance(cand, dict) else None
            if snap_thumb:
                thumbs = [snap_thumb]
            
        thumbs = [t for t in thumbs if t]
        _session[f"slot_{slot}_thumbs"] = thumbs
        
    _session[f"slot_{slot}_thumb_idx"] = 0
    await _render_thumb_step(update, ctx, slot)


async def _render_thumb_step(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    thumbs = _session.get(f"slot_{slot}_thumbs", [])
    idx = _session.get(f"slot_{slot}_thumb_idx", 0)
    current_url = thumbs[idx] if thumbs else None
    kb = thumbnail_carousel_keyboard(slot, idx, len(thumbs))

    text = f"🖼️ *PASSO 3/4: Revisão da Capa (Slot {slot})*\n\n"
    if not current_url:
        text += "⚠️ Nenhuma capa encontrada em canais públicos. O Dailymotion usará um frame automático do vídeo."
        msg = update.effective_message
        if msg.photo:
            await msg.delete()
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
        else:
            if update.callback_query:
                await update.callback_query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            else:
                await ctx.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        msg = update.effective_message
        if update.callback_query and msg.photo:
            from telegram import InputMediaPhoto
            try:
                await update.callback_query.edit_message_media(
                    media=InputMediaPhoto(current_url, caption=text[:1024], parse_mode=ParseMode.MARKDOWN),
                    reply_markup=kb
                )
            except BadRequest as e:
                # Trata erro de URL invalida
                if "Wrong type of the web page content" in str(e) or "Failed to get http" in str(e):
                    thumbs.pop(idx)
                    _session[f"slot_{slot}_thumbs"] = thumbs
                    await update.callback_query.answer("❌ O link inserido era inválido. Removendo...", show_alert=True)
                    return await _render_thumb_step(update, ctx, slot)
        else:
            if update.callback_query:
                await msg.delete()
            try:
                await ctx.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=current_url,
                    caption=text[:1024],
                    reply_markup=kb,
                    parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest as e:
                if "Wrong type of the web page content" in str(e) or "Failed to get http" in str(e):
                    thumbs.pop(idx)
                    _session[f"slot_{slot}_thumbs"] = thumbs
                    await ctx.bot.send_message(chat_id=update.effective_chat.id, text="❌ O link dessa imagem era um site/página (e não uma imagem direta). Removido da lista de capas!")
                    return await _render_thumb_step(update, ctx, slot)


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

    elif action == "skip":
        db.update_vitrine_slot(slot, {"thumbnail_url": None})
        await _step_video_match(update, ctx, slot)


# ------------------------------------------------------------------ #
#  Passo 4/4 — Confirmação de Match do Vídeo
# ------------------------------------------------------------------ #

async def _step_video_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int):
    vitrine = db.get_top6_vitrine()
    slot_data = next((s for s in vitrine if s["slot_number"] == slot), None)
    cand = (slot_data.get("candidate_snapshot") or slot_data.get("candidates") or {}) if slot_data else {}
    title = slot_data.get("approved_title") or cand.get("title") or "Drama" if slot_data else "Drama"

    # Encaminha o vídeo original do canal para o admin visualizar + mensagens ao redor (preview)
    msg_id = cand.get("msg_id")
    telethon_client: TelegramClient = ctx.bot_data.get("telethon_client")
    if msg_id and telethon_client:
        to_forward = [msg_id - 1, msg_id, msg_id + 1]
        try:
            await telethon_client.forward_messages(
                entity=update.effective_chat.id,
                messages=to_forward,
                from_peer=config.telegram.source_channel
            )
        except Exception as e:
            # Em caso de falha no lote (ex: alguma msg_id foi apagada), tenta enviar o principal isolado
            try:
                await telethon_client.forward_messages(
                    entity=update.effective_chat.id,
                    messages=msg_id,
                    from_peer=config.telegram.source_channel
                )
            except Exception as inner_e:
                logger.warning("[BOT] Erro ao encaminhar vídeo para preview principal: %s", inner_e)

    text = (
        f"🎥 *PASSO 4/4: Confirmação do Arquivo (Slot {slot})*\n\n"
        f"Título aprovado: *{title}*\n\n"
        f"O vídeo associado a esta sinopse está correto?\n"
        f"*(O arquivo original foi encaminhado acima para você conferir)*"
    )
    kb = video_match_keyboard(slot)
    msg = update.callback_query.message
    if msg and msg.photo:
        await msg.delete()
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.callback_query.edit_message_text(
            text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
        )


async def _handle_match(update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str):
    parts = data.split("_")
    action = parts[1]  # discard ou confirm
    slot = int(parts[2])

    if action == "discard":
        db.discard_vitrine_slot(slot)
        # Puxa próximo da reserva em memória (Plano B)
        from modules.validator import get_reserve_pool
        reserve = get_reserve_pool()
        if reserve:
            next_cand = reserve.pop(0)
            db.upsert_vitrine_slot_memory(slot_number=slot, candidate=next_cand)
            await update.callback_query.answer("❌ Slot descartado. Próximo da reserva carregado.")
        else:
            await update.callback_query.answer("❌ Slot descartado. Reserva vazia — aguarde próxima mineração.")
        # Limpa session do slot descartado
        for key in [f"slot_{slot}_titles", f"slot_{slot}_description", f"slot_{slot}_descs", f"slot_{slot}_thumbs"]:
            _session.pop(key, None)
        await _show_lobby(update, ctx, edit=True)

    elif action == "confirm":
        db.update_vitrine_slot(slot, {"status": "validated"})
        await update.callback_query.answer("✅ Validação concluída!")
        await _show_lobby(update, ctx, edit=True)


# ------------------------------------------------------------------ #
#  Trigger de Upload
# ------------------------------------------------------------------ #

async def _trigger_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE, slot: int, force: bool = False):
    """Inicia o pipeline de upload com feedback em tempo real ao usuário."""
    query = update.callback_query
    chat_id = update.effective_chat.id
    
    # Criamos uma referência mutável para a mensagem de status atual
    class StatusMsg:
        msg = query.message

    async def progress(status_text: str):
        try:
            # Tenta editar a mensagem atual
            StatusMsg.msg = await StatusMsg.msg.edit_text(status_text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            # Se for Flood Control (RetryAfter), enviamos uma nova mensagem
            if "Retry in" in str(e) or "Flood control" in str(e):
                try:
                    # Tenta apagar a anterior (opcional, pode falhar também)
                    await StatusMsg.msg.delete()
                except Exception: pass
                
                # Envia nova mensagem e atualiza a referência para as próximas edições
                StatusMsg.msg = await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=f"{status_text}\n\n_(Nota: Nova mensagem enviada para contornar limite do Telegram)_",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                logger.warning("[BOT] Erro não-letal no progresso: %s", e)

    # Feedback inicial
    await query.answer("🚀 Iniciando processamento...")
    await progress(f"⏳ *Iniciando envio do Slot {slot}...*")

    # O cliente Telethon é passado via context (configurado no main.py)
    telethon_client: TelegramClient = ctx.bot_data.get("telethon_client")
    if not telethon_client:
        await progress("❌ Erro: cliente Telethon não inicializado.")
        return

    try:
        result = await run_upload_pipeline(
            client=telethon_client,
            slot_number=slot,
            progress_callback=progress,
            force=force,
        )
        await progress(
            f"✅ *UPLOAD CONCLUÍDO!*\n"
            f"🎬 {result['title']}\n"
            f"🔗 {result['url']}"
        )
    except Exception as e:
        logger.error("[BOT] Erro no upload do Slot %d: %s", slot, e, exc_info=True)
        db.update_vitrine_slot(slot, {"status": "validated"})  # Reverte lock
        await progress(f"❌ *Erro no upload:*\n`{str(e)[:300]}`")


# ------------------------------------------------------------------ #
#  Mineração em Background
# ------------------------------------------------------------------ #

async def _run_background_mining(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        telethon_client = ctx.bot_data.get("telethon_client")
        await run_full_mining_cycle(telethon_client)
        await ctx.bot.send_message(
            chat_id=chat_id, 
            text="✅ *Mineração concluída!* ⛏️ Novos doramas (ou a falta deles) já foram processados. Clique em /start para ver o painel.", 
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error("[BOT] Erro na mineração manual: %s", e)
        await ctx.bot.send_message(chat_id=chat_id, text=f"❌ Erro na mineração manual: {e}")

# ------------------------------------------------------------------ #
#  Fábrica do Bot
# ------------------------------------------------------------------ #

async def handle_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Intercepta mensagens de texto para edição manual (Título, Descrição, Capa)."""
    user_id = update.effective_user.id
    state = _session.get(f"awaiting_edit_{user_id}")
    if not state:
        return

    slot = state["slot"]
    edit_type = state["type"]
    new_text = update.message.text or ""
    photo = update.message.photo

    # Verifica se os dados da sessão do slot existem
    if f"slot_{slot}_titles" not in _session and edit_type in ["title", "desc", "thumb"]:
        await update.message.reply_text("❌ Sessão expirada para esse slot. Comece novamente.")
        _session.pop(f"awaiting_edit_{user_id}", None)
        return

    if edit_type == "title":
        titles = _session.get(f"slot_{slot}_titles", [])
        idx = _session.get(f"slot_{slot}_title_idx", 0)
        if titles:
            titles[idx] = new_text
        else:
            _session[f"slot_{slot}_titles"] = [new_text]
            _session[f"slot_{slot}_title_idx"] = 0
        await update.message.reply_text(f"✅ Título atualizado manualmente!")
        _session.pop(f"awaiting_edit_{user_id}", None)
        await _render_title_step(update, ctx, slot)

    elif edit_type == "desc":
        descs = _session.get(f"slot_{slot}_descs", [])
        idx = _session.get(f"slot_{slot}_desc_idx", 0)
        if descs:
            descs[idx] = new_text
        else:
            _session[f"slot_{slot}_descs"] = [new_text]
            _session[f"slot_{slot}_desc_idx"] = 0
        await update.message.reply_text(f"✅ Sinopse atualizada manualmente!")
        _session.pop(f"awaiting_edit_{user_id}", None)
        await _render_desc_step(update, ctx, slot)

    elif edit_type == "thumb":
        thumbs = _session.get(f"slot_{slot}_thumbs", [])
        if photo:
            photo_file_id = photo[-1].file_id
            thumbs.insert(0, photo_file_id)
            _session[f"slot_{slot}_thumbs"] = thumbs
            _session[f"slot_{slot}_thumb_idx"] = 0
            await update.message.reply_text(f"✅ Nova Capa adicionada via arquivo de imagem!")
        elif new_text.startswith("http"):
            if "t.me/" in new_text:
                await update.message.reply_text("⏳ Baixando imagem do Telegram (Isso pode levar alguns segundos)...")
                try:
                    from modules.thumbnail_engine import download_telegram_link
                    telethon_client: TelegramClient = ctx.bot_data.get("telethon_client")
                    url = await download_telegram_link(telethon_client, new_text)
                    if url:
                        thumbs.insert(0, url)
                        _session[f"slot_{slot}_thumbs"] = thumbs
                        _session[f"slot_{slot}_thumb_idx"] = 0
                        await update.message.reply_text(f"✅ Capa do canal privado baixada e adicionada!")
                    else:
                        await update.message.reply_text("❌ Falha ao encontrar/baixar a foto. O link pode ser de arquivo ou o bot não tem permissão.")
                except Exception as e:
                    await update.message.reply_text(f"❌ Erro baixando telegram: {e}")
            else:
                thumbs.insert(0, new_text) # Coloca com primeira opção
                _session[f"slot_{slot}_thumbs"] = thumbs
                _session[f"slot_{slot}_thumb_idx"] = 0
                await update.message.reply_text(f"✅ Nova Capa adicionada por link direto!")
        else:
            await update.message.reply_text("❌ Envie uma Imagem ou um Link direto de imagem (http...).")
            _session.pop(f"awaiting_edit_{user_id}", None)
            return await _render_thumb_step(update, ctx, slot)
        
        _session.pop(f"awaiting_edit_{user_id}", None)
        await _render_thumb_step(update, ctx, slot)


def create_bot(telethon_client: TelegramClient) -> Application:
    """Cria e configura a aplicação do Bot."""
    app = Application.builder().token(config.telegram.bot_token).build()
    app.bot_data["telethon_client"] = telethon_client

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & (~filters.COMMAND), handle_text_input))

    logger.info("[BOT] Bot configurado e pronto.")
    return app
