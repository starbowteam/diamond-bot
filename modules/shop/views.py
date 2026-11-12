# -*- coding: utf-8 -*-
"""UI витрины DC-Shop — Полностью на селектах."""
import time
import asyncio
from typing import List, Dict

import disnake
from disnake import ButtonStyle, SelectOption, PartialEmoji
from disnake.ui import View, Button, Select, Modal, TextInput

from core.utils import logger, CONFIG

REVIEW_CHANNEL_ID = CONFIG.get("REVIEW_COUNT_CHANNEL", 1462074763437543435)

# ============================================================
# ЭМОДЗИ (Сохранены из старых кнопок)
# ============================================================
E_BAG     = PartialEmoji(name="prize",     id=1539657202170859561)
E_FIRE    = PartialEmoji(name="skidka",    id=1540819242625146961)
E_HISTORY = PartialEmoji(name="Otziv",     id=1541808692314243172)
E_BACK    = PartialEmoji(name="OffTicket", id=1539657125716824185)
E_BUY     = PartialEmoji(name="Oplacheno", id=1539657164778512496)
E_GIFT    = PartialEmoji(name="gid1",      id=1555654337953267794)
E_STAR    = PartialEmoji(name="Otziv",     id=1541808692314243172)
E_SHOP    = PartialEmoji(name="shop1",     id=1555654407776112750)

E_CAT_ADS    = PartialEmoji(name="reklama", id=1555654392202535073)
E_CAT_ROLES  = PartialEmoji(name="peope",   id=1555654375781834883)
E_CAT_CASINO = PartialEmoji(name="kazik",   id=1555654356152623104)

CATEGORY_EMOJI = {
    "discounts":    PartialEmoji(name="skidka", id=1540819242625146961),
    "design":       PartialEmoji(name="image",  id=1550869363266027641),
    "ads_forever":  PartialEmoji(name="nacves",    id=1568670488698421333),
    "ads_24h":      PartialEmoji(name="twefoping", id=1568669931594190889),
    "ads_personal": PartialEmoji(name="mycha",     id=1568669912103260261),
    "roles_auto":   E_CAT_ROLES,
    "roles_custom": E_CAT_ROLES,
    "gifts":        PartialEmoji(name="prize",  id=1539657202170859561),
}

# ============================================================
# ЕДИНЫЙ СЕЛЕКТ (Заменяет все кнопки)
# ============================================================
class UniversalShopSelect(Select):
    def __init__(self, state: str, ctx: dict):
        self.state = state
        self.ctx = ctx
        options = []

        if state == "categories":
            for c in ctx.get("categories", [])[:20]:
                key = c["key"]
                count = c["count"]
                count_word = "товар" if count == 1 else "товара" if 2 <= count <= 4 else "товаров"
                desc = f"Смотреть {count} {count_word} →"
                options.append(SelectOption(
                    label=c["label"], description=desc, value=f"cat:{key}", emoji=CATEGORY_EMOJI.get(key),
                ))
            options.append(SelectOption(label="Акция дня", description="Скидка дня на товар", value="deal", emoji=E_FIRE))
            options.append(SelectOption(label="Мои покупки", description="Товары, ожидающие оформления", value="my_purchases", emoji=E_BAG))
            options.append(SelectOption(label="История покупок", description="Последние потраченные DC", value="history", emoji=E_HISTORY))

        elif state == "products":
            for it in ctx.get("items", [])[:20]:
                emoji = CATEGORY_EMOJI.get(ctx["cat_key"])
                if it.get("owned"):
                    options.append(SelectOption(label=f"{it['name']} (Куплено)", value=f"item:{it['key']}", emoji=emoji))
                else:
                    desc = f"{it['price']} DC | {it.get('description', '')[:50]}"
                    options.append(SelectOption(label=it['name'], description=desc, value=f"item:{it['key']}", emoji=emoji))
            
            # Пагинация через селект
            page = ctx.get("page", 0)
            total_pages = ctx.get("total_pages", 1)
            if page < total_pages - 1:
                options.append(SelectOption(label="Следующая страница →", value=f"page:{page+1}", emoji=PartialEmoji(name="rid1", id=1557225020265332816)))
            if page > 0:
                options.append(SelectOption(label="← Предыдущая страница", value=f"page:{page-1}", emoji=PartialEmoji(name="baa1", id=1557224983539749004)))

            options.append(SelectOption(label="Назад в категории", value="back:categories", emoji=E_BACK))
            options.append(SelectOption(label="Мои покупки", value="my_purchases", emoji=E_BAG))
            options.append(SelectOption(label="История покупок", value="history", emoji=E_HISTORY))

        elif state == "detail":
            options.append(SelectOption(label=f"Купить за {ctx['price']} DC", value="buy", emoji=E_BUY))
            options.append(SelectOption(label="Подарить другу", value="gift", emoji=E_GIFT))
            options.append(SelectOption(label="Назад к товарам", value="back:products", emoji=E_BACK))

        elif state in ("purchases", "history", "success", "deal"):
            options.append(SelectOption(label="В магазин", value="back:categories", emoji=E_SHOP))
            options.append(SelectOption(label="Мои покупки", value="my_purchases", emoji=E_BAG))
            options.append(SelectOption(label="История покупок", value="history", emoji=E_HISTORY))
            if state == "success" and ctx.get("show_review"):
                options.append(SelectOption(label="Оставить отзыв", value="review", emoji=E_STAR))

        super().__init__(
            placeholder="Выберите действие или товар...",
            min_values=1, max_values=1,
            options=options,
            custom_id=f"shop_universal:{state}",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        val = self.values[0]
        from modules.shop.handlers import (
            goto_categories, goto_products, goto_detail, goto_purchases,
            goto_history, goto_daily, handle_buy, open_shop
        )

        if val.startswith("cat:"):
            await goto_products(inter, val.split(":")[1], page=0)
        elif val.startswith("item:"):
            await goto_detail(inter, self.ctx["cat_key"], val.split(":")[1])
        elif val.startswith("page:"):
            await goto_products(inter, self.ctx["cat_key"], page=int(val.split(":")[1]))
        elif val == "back:categories":
            await goto_categories(inter)
        elif val == "back:products":
            await goto_products(inter, self.ctx["cat_key"], page=0)
        elif val == "my_purchases":
            await goto_purchases(inter)
        elif val == "history":
            await goto_history(inter)
        elif val == "deal":
            await goto_daily(inter)
        elif val == "buy":
            await handle_buy(inter, self.ctx["cat_key"], self.ctx["item_key"])
        elif val == "gift":
            await inter.response.send_modal(ShopGiftModal(self.ctx["cat_key"], self.ctx["item_key"]))
        elif val == "review":
            await inter.response.send_message(
                f"Перейди в <#{REVIEW_CHANNEL_ID}> и оставь отзыв о покупке.\n"
                f"За каждый одобренный отзыв мы даём **+15 DC** на баланс.",
                ephemeral=True,
            )


class ShopUniversalView(View):
    def __init__(self, state: str, ctx: dict = None):
        super().__init__(timeout=None)
        self.state = state
        self.ctx = ctx or {}
        self.add_item(UniversalShopSelect(state, self.ctx))


# ============================================================
# МОДАЛКА ДЛЯ ПОДАРКА
# ============================================================
class ShopGiftModal(Modal):
    def __init__(self, cat_key: str, item_key: str):
        self.cat_key = cat_key
        self.item_key = item_key
        super().__init__(
            title="Подарить товар",
            components=[
                TextInput(
                    label="ID получателя",
                    placeholder="Например, 123456789012345678",
                    custom_id="recipient_id",
                    min_length=1,
                    max_length=32,
                )
            ],
            custom_id="shop:gift_modal",
        )

    async def callback(self, inter: disnake.ModalInteraction):
        recipient = self.text_values["recipient_id"].strip()
        if not recipient.isdigit():
            return await inter.response.send_message(
                "ID должен состоять только из цифр.", ephemeral=True
            )
        from modules.shop.handlers import handle_gift
        await handle_gift(inter, self.cat_key, self.item_key, int(recipient))