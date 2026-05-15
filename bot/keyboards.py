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
            row = [InlineKeyboardButton(f"⚙️ Validar INFO (Slot {n})", callback_data=f"validate_{n}")]
        elif status == "validated":
            row = [
                InlineKeyboardButton(f"🚀 POSTAR (Slot {n})", callback_data=f"send_{n}"),
                InlineKeyboardButton(f"❌ Remover", callback_data=f"remove_prompt_{n}"),
            ]
        elif status == "uploading":
            row = [InlineKeyboardButton(f"⏳ Enviando...", callback_data="noop")]
        elif status == "posted":
            row = [InlineKeyboardButton(f"✅ Slot {n} Postado", callback_data="noop")]
        else:
            row = [InlineKeyboardButton(f"❓ Slot {n}", callback_data="noop")]

        buttons.append(row)

    # Botões de controle
    buttons.append([
        InlineKeyboardButton("🔄 Atualizar Painel", callback_data="refresh"),
        InlineKeyboardButton("⛏️ Forçar Mineração", callback_data="trigger_mining")
    ])
    return InlineKeyboardMarkup(buttons)

def view_full_keyboard(slot: int) -> InlineKeyboardMarkup:
    """Teclado para o painel de visualização completa antes da postagem."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Voltar", callback_data="refresh"),
            InlineKeyboardButton("✏️ Editar Info", callback_data=f"validate_{slot}")
        ],
        [
            InlineKeyboardButton("🚀 POSTAR AGORA", callback_data=f"send_{slot}")
        ]
    ])


def remove_reason_keyboard(slot: int) -> InlineKeyboardMarkup:
    """Sub-menu para o motivo de remoção."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑️ Já postei antes", callback_data=f"remove_history_{slot}"),
            InlineKeyboardButton("👎 Não gostei", callback_data=f"remove_discard_{slot}")
        ],
        [InlineKeyboardButton("⬅️ Cancelar", callback_data="refresh")]
    ])


def title_carousel_keyboard(slot: int, current: int, total: int) -> InlineKeyboardMarkup:
    """Navegação de títulos no Passo 1/4 do túnel."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀️ Anterior", callback_data=f"title_prev_{slot}_{current}"),
            InlineKeyboardButton(f"{current+1}/{total}", callback_data="noop"),
            InlineKeyboardButton("Próxima ▶️", callback_data=f"title_next_{slot}_{current}"),
        ],
        [InlineKeyboardButton("✅ Confirmar Título", callback_data=f"title_confirm_{slot}_{current}")],
        [InlineKeyboardButton("✏️ Edição Manual", callback_data=f"edit_manual_title_{slot}")]
    ])


def description_carousel_keyboard(slot: int) -> InlineKeyboardMarkup:
    """Navegação de sinopses no Passo 2/4."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀️ Anterior", callback_data=f"desc_prev_{slot}"),
            InlineKeyboardButton("Próxima ▶️", callback_data=f"desc_next_{slot}"),
        ],
        [InlineKeyboardButton("✅ Confirmar Descrição", callback_data=f"desc_confirm_{slot}")],
        [InlineKeyboardButton("✏️ Edição Manual", callback_data=f"edit_manual_desc_{slot}")]
    ])


def thumbnail_carousel_keyboard(slot: int, current: int, total: int) -> InlineKeyboardMarkup:
    """Navegação de capas no Passo 3/4."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀️ Capa Anterior", callback_data=f"thumb_prev_{slot}_{current}"),
            InlineKeyboardButton(f"{current+1}/{total}", callback_data="noop"),
            InlineKeyboardButton("Próxima Capa ▶️", callback_data=f"thumb_next_{slot}_{current}"),
        ],
        [
            InlineKeyboardButton("✅ Confirmar Capa", callback_data=f"thumb_confirm_{slot}_{current}"),
            InlineKeyboardButton("❌ Pular/Sem Capa", callback_data=f"thumb_skip_{slot}")
        ],
        [InlineKeyboardButton("✏️ Enviar Capa Manual", callback_data=f"edit_manual_thumb_{slot}")]
    ])


def video_match_keyboard(slot: int) -> InlineKeyboardMarkup:
    """Confirmação de match no Passo 4/4."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Erro de Match (Descartar)", callback_data=f"match_discard_{slot}"),
            InlineKeyboardButton("✅ TUDO CERTO!", callback_data=f"match_confirm_{slot}"),
        ]
    ])
