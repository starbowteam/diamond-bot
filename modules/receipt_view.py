# -*- coding: utf-8 -*-
"""
Persistent view с кнопками-реквизитами для счёта.
4 кнопки: Т-Банк / СБП / ОзонБанк / АльфаБанк — все на row 0.
Серая, длина каждой ~11 (суммарно ~46). Без эмодзи.
"""
import disnake
from disnake import ButtonStyle
from disnake.ui import View, Button

from core.utils import logger


# \u2800 (BRAILLE PATTERN BLANK) — широкий пробел
P = "\u2800"

# 4 кнопки × 11 = 44 символа (с запасом до 46)
_BTN_LABEL_MAX = 9


def _btn_label(text: str, total: int = _BTN_LABEL_MAX) -> str:
    text = text.strip()
    if len(text) >= total:
        return text[:total]
    padding = total - len(text)
    left = padding // 2
    right = padding - left
    return f"{P * left}{text}{P * right}"


# ============================================================
# РЕКВИЗИТЫ
# ============================================================
REQUISITES = {
    "tbank": {
        "title": "Т-Банк",
        "value": "2200 7020 8029 9345",
        "type": "Карта",
    },
    "sbp": {
        "title": "СБП (Система быстрых платежей)",
        "value": "+7 983 694 76 41",
        "type": "Телефон",
    },
    "ozon": {
        "title": "ОзонБанк",
        "value": "2204 3204 4881 5151",
        "type": "Карта",
    },
    "alfa": {
        "title": "АльфаБанк",
        "value": "2200 1545 6426 7465",
        "type": "Карта",
    },
}


class ReceiptView(View):
    """
    Persistent view. Все 4 кнопки на row 0, компактно.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=_btn_label("Т-Банк"),
        style=ButtonStyle.gray,
        custom_id="receipt:req:tbank",
        row=0,
    )
    async def btn_tbank(self, button: Button, inter: disnake.MessageInteraction):
        await self._send_req(inter, "tbank")

    @disnake.ui.button(
        label=_btn_label("СБП"),
        style=ButtonStyle.gray,
        custom_id="receipt:req:sbp",
        row=0,
    )
    async def btn_sbp(self, button: Button, inter: disnake.MessageInteraction):
        await self._send_req(inter, "sbp")

    @disnake.ui.button(
        label=_btn_label("ОзонБанк"),
        style=ButtonStyle.gray,
        custom_id="receipt:req:ozon",
        row=0,
    )
    async def btn_ozon(self, button: Button, inter: disnake.MessageInteraction):
        await self._send_req(inter, "ozon")

    @disnake.ui.button(
        label=_btn_label("АльфаБанк"),
        style=ButtonStyle.gray,
        custom_id="receipt:req:alfa",
        row=0,
    )
    async def btn_alfa(self, button: Button, inter: disnake.MessageInteraction):
        await self._send_req(inter, "alfa")

    async def _send_req(self, inter: disnake.MessageInteraction, key: str):
        data = REQUISITES.get(key)
        if not data:
            return await inter.response.send_message(
                "❌ Реквизит не найден.", ephemeral=True,
            )
        try:
            await inter.response.send_message(
                content=(
                    f"> **{data['title']}** · {data['type']}\n"
                    f"> `{data['value']}`\n\n"
                    f"> Нажми на номер — он скопируется."
                ),
                ephemeral=True,
            )
        except Exception as e:
            logger.warning(f"ReceiptView send req {key}: {e}")
