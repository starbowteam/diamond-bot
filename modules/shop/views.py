# -*- coding: utf-8 -*-
"""UI витрины DC-Shop."""
import time
import asyncio
from typing import List, Dict

import disnake
from disnake import ButtonStyle, SelectOption, PartialEmoji
from disnake.ui import View, Button, Select, Modal, TextInput

from core.utils import logger, CONFIG


P = "\u3164"

REVIEW_CHANNEL_ID = CONFIG.get("REVIEW_COUNT_CHANNEL", 1462074763437543435)


def L(text: str) -> str:
    """Одиночный паддинг 1+1."""
    return f"{P}{text}{P}"


def _L_total(labels, total: int):
    """
    Раскидывает невидимые пробелы так, чтобы СУММА длин == total.
    Используется, когда из вью убрали кнопку — компенсируем длины.
    """
    base = sum(len(s) for s in labels)
    extra = max(0, total - base)
    n = len(labels)
    if n == 0:
        return labels
    per = extra // n
    rem = extra % n
    result = []
    for i, s in enumerate(labels):
        pad = per + (1 if i < rem else 0)
        left = pad // 2
        right = pad - left
        result.append(f"{P * left}{s}{P * right}")
    return result


# Суммарная длина 2 кнопок ShopMainView = 27
# (раньше было 3 кнопки: Мои покупки + Акция дня + История = 27)
_L_PURCHASES, _L_HISTORY = _L_total(["Мои покупки", "История"], 27)


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
    "discounts": PartialEmoji(name="skidka", id=1540819242625146961),
    "design":    PartialEmoji(name="image",  id=1550869363266027641),
    "ads":       E_CAT_ADS,
    "roles":     E_CAT_ROLES,
    "boosts":    PartialEmoji(name="flash",  id=1551289202279325756),
    "casino":    E_CAT_CASINO,
    "gifts":     PartialEmoji(name="prize",  id=1539657202170859561),
}


# ============================================================
# SELECT КАТЕГОРИЙ
# ============================================================
class ShopCategorySelect(Select):
    def __init__(self, categories: List[Dict], active: str = ""):
        options = []
        for c in categories[:25]:
            key = c["key"]
            label = c["label"][:100]
            count = c["count"]
            count_word = (
                "товар" if count == 1
                else "товара" if 2 <= count <= 4
                else "товаров"
            )
            desc = f"Смотреть {count} {count_word} →"[:100]
            options.append(SelectOption(
                label=label,
                description=desc,
                value=key,
                emoji=CATEGORY_EMOJI.get(key),
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
        await goto_products(inter, cat_key, page=0)


# ============================================================
# SELECT ТОВАРОВ (скрывает купленные роли)
# ============================================================
class ShopItemSelect(Select):
    def __init__(self, cat_key: str, items: List[Dict], balance: int):
        available = [it for it in items if not it.get("owned")]

        options = []
        for it in available[:25]:
            price = it["price"]
            ok = balance >= price
            label = f"{it['name']} · {price} DC"[:100]
            if ok:
                desc = f"Доступно · {it.get('description', '')[:60]}"[:100]
            else:
                missing = price - balance
                desc = f"Не хватает {missing} DC"[:100]
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
# КНОПКИ
# ============================================================
class BtnPurchases(Button):
    def __init__(self, row: int = 1, label: str = None):
        super().__init__(
            label=label if label else L("Мои покупки"),
            style=ButtonStyle.gray,
            custom_id="shop:btn_purchases",
            emoji=E_BAG,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        from modules.shop.handlers import goto_purchases
        await goto_purchases(inter)


class BtnHistory(Button):
    def __init__(self, row: int = 1, label: str = None):
        super().__init__(
            label=label if label else L("История"),
            style=ButtonStyle.gray,
            custom_id="shop:btn_history",
            emoji=E_HISTORY,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        from modules.shop.handlers import goto_history
        await goto_history(inter)


class BtnBack(Button):
    def __init__(self, target: str = "categories", row: int = 1, cat_key: str = ""):
        super().__init__(
            label=L("Назад"),
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
            await goto_products(inter, cat_key, page=0)


class BtnBackToShop(Button):
    def __init__(self, row: int = 0):
        super().__init__(
            label=L("В магазин"),
            style=ButtonStyle.gray,
            custom_id="shop:btn_back_to_shop",
            emoji=E_SHOP,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        from modules.shop.handlers import goto_categories
        await goto_categories(inter)


class BtnPurchasesWide(Button):
    def __init__(self, row: int = 0):
        super().__init__(
            label=L("Мои покупки"),
            style=ButtonStyle.gray,
            custom_id="shop:btn_purchases_success",
            emoji=E_BAG,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        from modules.shop.handlers import goto_purchases
        await goto_purchases(inter)


class BtnReviewHint(Button):
    def __init__(self, row: int = 0):
        super().__init__(
            label=L("Оставить отзыв"),
            style=ButtonStyle.primary,
            custom_id="shop:btn_review_hint",
            emoji=E_STAR,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_message(
            f"Перейди в <#{REVIEW_CHANNEL_ID}> и оставь отзыв о покупке.\n"
            f"За каждый одобренный отзыв мы даём **+15 DC** на баланс.",
            ephemeral=True,
        )


class BtnBuy(Button):
    def __init__(self, cat_key: str, item_key: str, price: int, row: int = 0):
        super().__init__(
            label=L(f"Купить за {price} DC"),
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


class BtnGift(Button):
    def __init__(self, cat_key: str, item_key: str, row: int = 0):
        super().__init__(
            label=L("Подарить"),
            style=ButtonStyle.gray,
            custom_id=f"shop:btn_gift:{cat_key}:{item_key}",
            emoji=E_GIFT,
            row=row,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        parts = self.custom_id.split(":")
        cat_key = parts[2]
        item_key = parts[3]
        try:
            await inter.response.send_modal(
                ShopGiftModal(cat_key=cat_key, item_key=item_key)
            )
        except Exception as e:
            logger.warning(f"ShopGiftModal send err: {e}")


class BtnPageLeft(Button):
    def __init__(self, cat_key: str, page: int, row: int = 2):
        super().__init__(
            label=L("← Назад"),
            style=ButtonStyle.gray,
            custom_id=f"shop:page_left:{cat_key}:{page}",
            row=row,
            disabled=(page <= 0),
        )

    async def callback(self, inter: disnake.MessageInteraction):
        parts = self.custom_id.split(":")
        cat_key = parts[2]
        page = int(parts[3])
        from modules.shop.handlers import goto_products
        await goto_products(inter, cat_key, page=max(page - 1, 0))


class BtnPageRight(Button):
    def __init__(self, cat_key: str, page: int, total_pages: int, row: int = 2):
        super().__init__(
            label=L("Дальше →"),
            style=ButtonStyle.gray,
            custom_id=f"shop:page_right:{cat_key}:{page}",
            row=row,
            disabled=(page >= total_pages - 1),
        )

    async def callback(self, inter: disnake.MessageInteraction):
        parts = self.custom_id.split(":")
        cat_key = parts[2]
        page = int(parts[3])
        from modules.shop.handlers import goto_products
        await goto_products(inter, cat_key, page=page + 1)


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
        await handle_gift(inter, self.cat_key, self.item_key, int(recipient))


# ============================================================
# VIEWS
# ============================================================
class ShopMainView(View):
    """
    Главная витрины. Кнопка «Акция дня» убрана —
    акции теперь в канале Бонусы. Длины двух кнопок компенсированы
    до суммарных 27 символов (как было с 3 кнопками).
    """
    def __init__(self, categories: List[Dict], active: str = ""):
        super().__init__(timeout=None)
        self.add_item(ShopCategorySelect(categories, active))
        self.add_item(BtnPurchases(row=1, label=_L_PURCHASES))
        self.add_item(BtnHistory(row=1, label=_L_HISTORY))


class ShopProductsView(View):
    def __init__(self, cat_key: str, items: List[Dict], balance: int,
                 page: int = 0, total_pages: int = 1):
        super().__init__(timeout=None)

        available = [it for it in items if not it.get("owned")]
        if available:
            self.add_item(ShopItemSelect(cat_key, items, balance))

        self.add_item(BtnBack(target="categories", row=1))
        self.add_item(BtnPurchases(row=1))
        self.add_item(BtnHistory(row=1))

        if total_pages > 1:
            self.add_item(BtnPageLeft(cat_key, page, row=2))
            self.add_item(BtnPageRight(cat_key, page, total_pages, row=2))


class ShopDetailView(View):
    def __init__(self, cat_key: str, item_key: str, price: int):
        super().__init__(timeout=None)
        self.add_item(BtnBuy(cat_key, item_key, price, row=0))
        self.add_item(BtnGift(cat_key, item_key, row=0))
        self.add_item(BtnBack(target="products", cat_key=cat_key, row=0))


class ShopDetailOwnedView(View):
    def __init__(self, cat_key: str):
        super().__init__(timeout=None)
        self.add_item(BtnBack(target="products", cat_key=cat_key, row=0))


class ShopPurchasesView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BtnBackToShop(row=0))
        self.add_item(BtnHistory(row=0))


class ShopDealView(View):
    """Оставлено на всякий — акция дня теперь в /bonus."""
    def __init__(self, cat_key: str = "", item_key: str = "", price: int = 0):
        super().__init__(timeout=None)
        if cat_key and item_key and price > 0:
            self.add_item(BtnBuy(cat_key, item_key, price, row=0))
            self.add_item(BtnBackToShop(row=0))
            self.add_item(BtnPurchasesWide(row=0))
        else:
            self.add_item(BtnBackToShop(row=0))
            self.add_item(BtnPurchasesWide(row=0))


class ShopHistoryView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BtnBackToShop(row=0))
        self.add_item(BtnPurchasesWide(row=0))


class ShopSuccessView(View):
    def __init__(self, show_review: bool = False):
        super().__init__(timeout=None)
        if show_review:
            self.add_item(BtnPurchasesWide(row=0))
            self.add_item(BtnReviewHint(row=0))
            self.add_item(BtnBackToShop(row=0))
        else:
            self.add_item(BtnPurchasesWide(row=0))
            self.add_item(BtnBackToShop(row=0))
