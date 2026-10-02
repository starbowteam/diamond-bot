# -*- coding: utf-8 -*-
"""
UI витрины DC-Shop. Каждое взаимодействие — перерисовка PNG
и edit_message с новым файлом. Без кэша.
"""
import time
import asyncio
from typing import List, Dict

import disnake
from disnake import ButtonStyle, SelectOption, PartialEmoji
from disnake.ui import View, Button, Select, Modal, TextInput

from core.utils import logger
from modules.shop import state


P = "\u3164"


# ============================================================
# FA-EMOJI для кнопок Discord (компонентов)
# ============================================================
# Discord-кнопки требуют иконку из Discord CDN или unicode.
# Используем кастомные эмодзи сервера, как в старом коде.
E_BAG     = PartialEmoji(name="prize",   id=1539657202170859561)
E_FIRE    = PartialEmoji(name="skidka",  id=1540819242625146961)
E_HISTORY = PartialEmoji(name="Otziv",   id=1541808692314243172)
E_BACK    = PartialEmoji(name="OffTicket", id=1539657125716824185)
E_BUY     = PartialEmoji(name="Oplacheno", id=1539657164778512496)
E_GIFT    = PartialEmoji(name="prom1",   id=1539646792139014234)
E_CART    = PartialEmoji(name="shopg",   id=1539646815530651718)


# ============================================================
# СЕЛЕКТ КАТЕГОРИЙ
# ============================================================
class ShopCategorySelect(Select):
    def __init__(self, categories: List[Dict], active: str = ""):
        options = []
        for c in categories[:25]:
            label = c["label"][:100]
            desc = f"{c['count']} шт."[:100]
            options.append(SelectOption(
                label=label,
                description=desc,
                value=c["key"],
                default=(c["key"] == active),
            ))
        super().__init__(
            placeholder="Выберите категорию магазина...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop:cat_select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        cat_key = inter.data.values[0]
        from modules.shop.handlers import goto_products
        await goto_products(inter, cat_key)


# ============================================================
# СЕЛЕКТ ТОВАРОВ
# ============================================================
class ShopItemSelect(Select):
    def __init__(self, cat_key: str, items: List[Dict], balance: int):
        options = []
        for it in items[:25]:
            price = it["price"]
            ok = balance >= price
            label = f"{it['name']} · {price} DC"[:100]
            desc = ("Можешь купить" if ok else "Не хватает DC")[:100]
            options.append(SelectOption(
                label=label,
                description=desc,
                value=it["key"],
            ))
        super().__init__(
            placeholder="Выберите товар для покупки...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"shop:item_select:{cat_key}",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        it_key = inter.data.values[0]
        cat_key = self.custom_id.split(":")[-1]
        from modules.shop.handlers import goto_detail
        await goto_detail(inter, cat_key, it_key)


# ============================================================
# КНОПКА «МОИ ПОКУПКИ»
# ============================================================
class BtnPurchases(Button):
    def __init__(self, row: int = 1):
        super().__init__(
            label=f"{P}Мои покупки{P}",
            style=ButtonStyle.gray,
            custom_id="shop:btn_purchases",
            emoji=E_BAG,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        from modules.shop.handlers import goto_purchases
        await goto_purchases(inter)


# ============================================================
# КНОПКА «АКЦИЯ ДНЯ»
# ============================================================
class BtnDailyDeal(Button):
    def __init__(self, row: int = 1):
        super().__init__(
            label=f"{P}Акция дня{P}",
            style=ButtonStyle.gray,
            custom_id="shop:btn_daily",
            emoji=E_FIRE,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        from modules.shop.handlers import goto_daily
        await goto_daily(inter)


# ============================================================
# КНОПКА «ИСТОРИЯ»
# ============================================================
class BtnHistory(Button):
    def __init__(self, row: int = 1):
        super().__init__(
            label=f"{P}История{P}",
            style=ButtonStyle.gray,
            custom_id="shop:btn_history",
            emoji=E_HISTORY,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        from modules.shop.handlers import goto_history
        await goto_history(inter)


# ============================================================
# КНОПКА «НАЗАД»
# ============================================================
class BtnBack(Button):
    def __init__(self, target: str = "categories", row: int = 1, cat_key: str = ""):
        super().__init__(
            label=f"{P}Назад{P}",
            style=ButtonStyle.gray,
            custom_id=f"shop:btn_back:{target}:{cat_key}",
            emoji=E_BACK,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        parts = self.custom_id.split(":")
        target = parts[2] if len(parts) > 2 else "categories"
        cat_key = parts[3] if len(parts) > 3 else ""
        from modules.shop.handlers import goto_categories, goto_products
        if target == "categories":
            await goto_categories(inter)
        elif target == "products":
            await goto_products(inter, cat_key)


# ============================================================
# КНОПКА «КУПИТЬ»
# ============================================================
class BtnBuy(Button):
    def __init__(self, cat_key: str, item_key: str, price: int, row: int = 0):
        super().__init__(
            label=f"Купить за {price} DC",
            style=ButtonStyle.success,
            custom_id=f"shop:btn_buy:{cat_key}:{item_key}",
            emoji=E_BUY,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        parts = self.custom_id.split(":")
        cat_key = parts[2]
        item_key = parts[3]
        from modules.shop.handlers import handle_buy
        await handle_buy(inter, cat_key, item_key)


# ============================================================
# КНОПКА «ПОДАРИТЬ»
# ============================================================
class BtnGift(Button):
    def __init__(self, cat_key: str, item_key: str, row: int = 0):
        super().__init__(
            label=f"{P}Подарить{P}",
            style=ButtonStyle.gray,
            custom_id=f"shop:btn_gift:{cat_key}:{item_key}",
            emoji=E_GIFT,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        parts = self.custom_id.split(":")
        cat_key = parts[2]
        item_key = parts[3]
        # Модалку можно отправить только первым ответом на интеракцию.
        # Мы отвечаем модалкой — исходное сообщение не редактируем.
        try:
            await inter.response.send_modal(
                ShopGiftModal(cat_key=cat_key, item_key=item_key)
            )
        except Exception as e:
            logger.warning(f"ShopGiftModal send err: {e}")


# ============================================================
# МОДАЛКА ПОДАРКА
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
        await handle_gift(
            inter, self.cat_key, self.item_key, int(recipient)
        )


# ============================================================
# ГЛАВНОЕ VIEW — КАТЕГОРИИ
# ============================================================
class ShopMainView(View):
    def __init__(self, categories: List[Dict], active: str = ""):
        super().__init__(timeout=None)
        self.add_item(ShopCategorySelect(categories, active))
        self.add_item(BtnPurchases(row=1))
        self.add_item(BtnDailyDeal(row=1))
        self.add_item(BtnHistory(row=1))


# ============================================================
# VIEW — ТОВАРЫ
# ============================================================
class ShopProductsView(View):
    def __init__(self, cat_key: str, items: List[Dict], balance: int):
        super().__init__(timeout=None)
        self.add_item(ShopItemSelect(cat_key, items, balance))
        self.add_item(BtnBack(target="categories", row=1))
        self.add_item(BtnPurchases(row=1))
        self.add_item(BtnHistory(row=1))


# ============================================================
# VIEW — КАРТОЧКА ТОВАРА
# ============================================================
class ShopDetailView(View):
    def __init__(self, cat_key: str, item_key: str, price: int):
        super().__init__(timeout=None)
        self.add_item(BtnBuy(cat_key, item_key, price, row=0))
        self.add_item(BtnGift(cat_key, item_key, row=0))
        self.add_item(BtnBack(target="products", cat_key=cat_key, row=0))


# ============================================================
# VIEW — МОИ ПОКУПКИ
# ============================================================
class ShopPurchasesView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BtnBack(target="categories", row=0))


# ============================================================
# VIEW — АКЦИЯ ДНЯ
# ============================================================
class ShopDealView(View):
    def __init__(self, cat_key: str = "", item_key: str = "", price: int = 0):
        super().__init__(timeout=None)
        if cat_key and item_key and price > 0:
            self.add_item(BtnBuy(cat_key, item_key, price, row=0))
        self.add_item(BtnBack(target="categories", row=0))


# ============================================================
# VIEW — ИСТОРИЯ
# ============================================================
class ShopHistoryView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BtnBack(target="categories", row=0))
