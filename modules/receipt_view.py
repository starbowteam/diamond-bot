# -*- coding: utf-8 -*-
"""
Persistent view с селектом реквизитов для счёта.
Один селект — 4 пункта: Т-Банк / СБП / ОзонБанк / АльфаБанк.
При выборе — эфемерный ЭМБЕД с реквизитами + страйп внизу.
"""
import disnake
from disnake import SelectOption, PartialEmoji
from disnake.ui import View, Select

from core.utils import logger


IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"

EMOJI_BANKS = PartialEmoji(name="banks", id=1556311895106003075)
EMOJI_PHONE = PartialEmoji(name="phone", id=1556311870627905657)


# ============================================================
# РЕКВИЗИТЫ
# ============================================================
REQUISITES = {
    "tbank": {
        "label": "Т-Банк",
        "description": "Перевод на карту Т-Банк",
        "emoji": EMOJI_BANKS,
        "title": "Т-Банк",
        "value": "2200 7020 8029 9345",
        "type": "Карта",
    },
    "sbp": {
        "label": "СБП",
        "description": "Система быстрых платежей · телефон",
        "emoji": EMOJI_PHONE,
        "title": "СБП (Система быстрых платежей)",
        "value": "+7 983 694 76 41",
        "type": "Телефон",
    },
    "ozon": {
        "label": "ОзонБанк",
        "description": "Перевод на карту ОзонБанк",
        "emoji": EMOJI_BANKS,
        "title": "ОзонБанк",
        "value": "2204 3204 4881 5151",
        "type": "Карта",
    },
    "alfa": {
        "label": "АльфаБанк",
        "description": "Перевод на карту АльфаБанк",
        "emoji": EMOJI_BANKS,
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
            e1 = disnake.Embed(color=6776679)
            e1.set_image(url=IMG_STRIPE)

            e2 = disnake.Embed(
                title=f"{data['title']} · {data['type']}",
                description=(
                    f"> **Номер для перевода:**\n"
                    f"> `{data['value']}`\n\n"
                    f"> Нажми на номер — он скопируется."
                ),
                color=6776679,
            )
            e2.set_image(url=IMG_STRIPE)
            e2.set_footer(text="Нажми на номер — он скопируется")

            await inter.response.send_message(
                embeds=[e1, e2],
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
