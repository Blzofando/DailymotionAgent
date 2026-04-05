"""
bot/keyboards.py — Teclados Inline reutilizáveis para o Dashboard Telegram.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def lobby_keyboard(slots: list[dict], quota_visible: int) -> InlineKeyboardMarkup:
    """
    Monta o teclado do Lobby com botões de Validar/Enviar/Re-editar
    para cada slot visível.
    """
    buttons = []
    for slot in slots[:quota_visible]:
        n = slot["slot_number"]
        status = slot.get("status", "awaiting_validation")

        if status == "awaiting_validation":
            row = [InlineKeyboardButton(f"⚙️ Validar Slot {n}", callback_data=f"validate_{n}")]
        elif status == "validated":
            row = [
                InlineKeyboardButton(f"🚀 ENVIAR SLOT {n}", callback_data=f"send_{n}"),
                InlineKeyboardButton(f"✏️ Re-editar", callback_data=f"validate_{n}"),
            ]
        elif status == "uploading":
            row = [InlineKeyboardButton(f"⏳ Slot {n} em Envio...", callback_data="noop")]
        elif status == "posted":
            row = [InlineKeyboardButton(f"✅ Slot {n} Postado", callback_data="noop")]
        else:
            row = [InlineKeyboardButton(f"❓ Slot {n}", callback_data="noop")]

        buttons.append(row)

    # Botão de atualizar dashboard
    buttons.append([InlineKeyboardButton("🔄 Atualizar Painel", callback_data="refresh")])
    return InlineKeyboardMarkup(buttons)


def title_carousel_keyboard(slot: int, current: int, total: int) -> InlineKeyboardMarkup:
    """Navegação de títulos no Passo 1/4 do túnel."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀️ Anterior", callback_data=f"title_prev_{slot}_{current}"),
            InlineKeyboardButton(f"{current+1}/{total}", callback_data="noop"),
            InlineKeyboardButton("Próxima ▶️", callback_data=f"title_next_{slot}_{current}"),
        ],
        [InlineKeyboardButton("✅ Confirmar Título", callback_data=f"title_confirm_{slot}_{current}")],
    ])


def description_carousel_keyboard(slot: int) -> InlineKeyboardMarkup:
    """Navegação de sinopses no Passo 2/4."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀️ Anterior", callback_data=f"desc_prev_{slot}"),
            InlineKeyboardButton("Próxima ▶️", callback_data=f"desc_next_{slot}"),
        ],
        [InlineKeyboardButton("✅ Confirmar Descrição", callback_data=f"desc_confirm_{slot}")],
    ])


def thumbnail_carousel_keyboard(slot: int, current: int, total: int) -> InlineKeyboardMarkup:
    """Navegação de capas no Passo 3/4."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀️ Capa Anterior", callback_data=f"thumb_prev_{slot}_{current}"),
            InlineKeyboardButton(f"{current+1}/{total}", callback_data="noop"),
            InlineKeyboardButton("Próxima Capa ▶️", callback_data=f"thumb_next_{slot}_{current}"),
        ],
        [InlineKeyboardButton("✅ Confirmar Capa", callback_data=f"thumb_confirm_{slot}_{current}")],
    ])


def video_match_keyboard(slot: int) -> InlineKeyboardMarkup:
    """Confirmação de match no Passo 4/4."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Erro de Match (Descartar)", callback_data=f"match_discard_{slot}"),
            InlineKeyboardButton("✅ TUDO CERTO!", callback_data=f"match_confirm_{slot}"),
        ]
    ])
