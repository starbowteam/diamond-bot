# -*- coding: utf-8 -*-
"""
Persistent view с селектом реквизитов для счёта.
Один селект — 4 пункта: Т-Банк / СБП / ОзонБанк / АльфаБанк.
При выборе — эфемерно высылает реквизит.
"""
import disnake
from disnake import SelectOption
from disnake.ui import View, Select

from core.utils import logger


# ============================================================
# РЕКВИЗИТЫ
# ============================================================
REQUISITES = {
    "tbank": {
        "label": "Т-Банк",
        "description": "Перевод на карту Т-Банк",
        "emoji": "🟡",
        "title": "Т-Банк",
        "value": "2200 7020 8029 9345",
        "type": "Карта",
    },
    "sbp": {
        "label": "СБП",
        "description": "Система быстрых платежей · телефон",
        "emoji": "🔵",
        "title": "СБП (Система быстрых платежей)",
        "value": "+7 983 694 76 41",
        "type": "Телефон",
    },
    "ozon": {
        "label": "ОзонБанк",
        "description": "Перевод на карту ОзонБанк",
        "emoji": "🟢",
        "title": "ОзонБанк",
        "value": "2204 3204 4881 5151",
        "type": "Карта",
    },
    "alfa": {
        "label": "АльфаБанк",
        "description": "Перевод на карту АльфаБанк",
        "emoji": "🔴",
        "title": "АльфаБанк",
        "value": "2200 1545 6426 7465",
        "type": "Карта",
    },
}


# ============================================================
# СЕЛЕКТ
# ============================================================
class ReceiptSelect(Select):
    def __init__(self):
        options = [
            SelectOption(
                label=data["label"],
                description=data["description"],
                emoji=data["emoji"],
                value=key,
            )
            for key, data in REQUISITES.items()
        ]
        super().__init__(
            placeholder="Выберите банк для оплаты...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="receipt:req_select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        key = inter.data.values[0]
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
            logger.warning(f"ReceiptSelect send req {key}: {e}")


# ============================================================
# VIEW
# ============================================================
class ReceiptView(View):
    """
    Persistent view. Один селект под картинкой счёта.
    """

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ReceiptSelect())
