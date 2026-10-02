# -*- coding: utf-8 -*-
"""
Логика витрины DC-Shop: навигация, покупка, подарок.
Каждое нажатие = новый рендер + edit_message. Без кэша.
"""
import io
import os
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, List

import disnake

from core.utils import (
    CONFIG, ADD_DIR, CATALOG_DIR, DATA_DIR, FILES,
    logger, db, cur, load_json, save_json, now_ts,
    get_dc_cache, save_dc_cache, log_discord,
)
from modules.dc import (
    load_shop_catalog, get_user_balance, remove_dc, add_purchase,
    get_user_purchases, remove_purchase, get_user_dc_data,
)
from modules.shop import state
from modules.shop import render as shop_render
from modules.shop.views import (
    ShopMainView, ShopProductsView, ShopDetailView,
    ShopPurchasesView, ShopDealView, ShopHistoryView,
)


DAILY_DEAL_FILE = os.path.join(DATA_DIR, "daily_deal.json")
DAILY_DEAL_REFRESH_HOURS = 5

REVIEW_CHANNEL_ID = CONFIG.get("REVIEW_COUNT_CHANNEL", 1462074763437543435)


# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _get_total_spent(user_id: int) -> int:
    """
    Сумма покупок за DC. Считаем по истории операций
    (отрицательные amounts с reason, начинающимся на "Покупка").
    """
    data = get_dc_cache(user_id)
    total = 0
    for h in data.get("history", []) or []:
        amt = h.get("amount", 0) or 0
        reason = h.get("reason", "") or ""
        if amt < 0 and reason.startswith("Покупка"):
            total += abs(amt)
    return total


def _strip_emoji(s: str) -> str:
    if not s:
        return s
    out = []
    for ch in s:
        cp = ord(ch)
        if (
            0x1F300 <= cp <= 0x1FAFF
            or 0x2600 <= cp <= 0x27BF
            or 0x1F000 <= cp <= 0x1F02F
            or 0x2190 <= cp <= 0x21FF
            or cp in (0xFE0F, 0x200D, 0x20E3)
        ):
            continue
        out.append(ch)
    return "".join(out).strip()


def _get_categories_list() -> List[Dict]:
    catalog = load_shop_catalog()
    result = []
    for key, cat in catalog.items():
        items = cat.get("items", {})
        label = cat.get("label", key)
        clean_label = _strip_emoji(label)
        result.append({
            "key": key,
            "label": clean_label,
            "count": len(items),
            "fa": shop_render.CATEGORY_FA.get(key, shop_render.I_CUBE),
        })
    return result


def _get_items_for_category(cat_key: str) -> List[Dict]:
    catalog = load_shop_catalog()
    cat = catalog.get(cat_key, {})
    items = cat.get("items", {})
    result = []
    for key, it in items.items():
        name = _strip_emoji(it.get("name", key))
        result.append({
            "key": key,
            "name": name,
            "price": int(it.get("price", 0)),
            "description": it.get("description", ""),
            "fa": shop_render.CATEGORY_FA.get(cat_key, shop_render.I_CUBE),
        })
    result.sort(key=lambda x: x["price"])
    return result


# ============================================================
# ОТПРАВКА / РЕДАКТИРОВАНИЕ
# ============================================================
async def _send_screen(inter, *, buf: io.BytesIO, view):
    fname = f"shop_{inter.author.id}_{int(time.time() * 1000)}.png"
    file = disnake.File(buf, filename=fname)
    embed = disnake.Embed(color=shop_render.EMBED_COLOR)
    embed.set_image(url=f"attachment://{fname}")
    await inter.response.send_message(
        embed=embed, file=file, view=view, ephemeral=True
    )


async def _edit_screen(inter, *, buf: io.BytesIO, view):
    """
    Меняет исходное сообщение: новое вложение, старые — удаляем.
    disnake: file=File — новое, attachments=[] — что оставить из старых.
    """
    fname = f"shop_{inter.author.id}_{int(time.time() * 1000)}.png"
    file = disnake.File(buf, filename=fname)
    embed = disnake.Embed(color=shop_render.EMBED_COLOR)
    embed.set_image(url=f"attachment://{fname}")
    await inter.response.edit_message(
        content=None,
        embed=embed,
        file=file,
        attachments=[],
        view=view,
    )


# ============================================================
# ОТКРЫТИЕ
# ============================================================
async def open_shop(inter: disnake.MessageInteraction):
    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    total_spent = _get_total_spent(user_id)
    categories = _get_categories_list()

    buf = shop_render.render_categories(
        user_id=user_id,
        balance=balance,
        total_spent=total_spent,
        categories=categories,
    )
    view = ShopMainView(categories, active=categories[0]["key"] if categories else "")
    await _send_screen(inter, buf=buf, view=view)


# ============================================================
# НАВИГАЦИЯ
# ============================================================
async def goto_categories(inter: disnake.MessageInteraction):
    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    total_spent = _get_total_spent(user_id)
    categories = _get_categories_list()
    buf = shop_render.render_categories(
        user_id=user_id, balance=balance, total_spent=total_spent,
        categories=categories,
    )
    view = ShopMainView(categories, active=categories[0]["key"] if categories else "")
    await _edit_screen(inter, buf=buf, view=view)


async def goto_products(inter: disnake.MessageInteraction, cat_key: str):
    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    total_spent = _get_total_spent(user_id)
    catalog = load_shop_catalog()
    cat = catalog.get(cat_key)
    if not cat:
        return await inter.response.send_message(
            "Категория не найдена.", ephemeral=True
        )
    cat_label = _strip_emoji(cat.get("label", cat_key))
    items = _get_items_for_category(cat_key)

    buf = shop_render.render_products(
        user_id=user_id, balance=balance, total_spent=total_spent,
        category_key=cat_key, category_label=cat_label, items=items,
    )
    view = ShopProductsView(cat_key, items, balance)
    await _edit_screen(inter, buf=buf, view=view)


async def goto_detail(inter: disnake.MessageInteraction, cat_key: str, item_key: str):
    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    total_spent = _get_total_spent(user_id)
    catalog = load_shop_catalog()
    cat = catalog.get(cat_key, {})
    item = cat.get("items", {}).get(item_key)
    if not item:
        return await inter.response.send_message("Товар не найден.", ephemeral=True)
    cat_label = _strip_emoji(cat.get("label", cat_key))
    item_view = {
        "name": _strip_emoji(item.get("name", item_key)),
        "price": int(item.get("price", 0)),
        "description": item.get("description", ""),
        "fa": shop_render.CATEGORY_FA.get(cat_key, shop_render.I_CUBE),
    }
    buf = shop_render.render_detail(
        user_id=user_id, balance=balance, total_spent=total_spent,
        category_key=cat_key, category_label=cat_label, item=item_view,
    )
    view = ShopDetailView(cat_key, item_key, item_view["price"])
    await _edit_screen(inter, buf=buf, view=view)


async def goto_purchases(inter: disnake.MessageInteraction):
    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    total_spent = _get_total_spent(user_id)
    purchases = await get_user_purchases(user_id, only_unused=True)
    filtered = [p for p in purchases if p.get("type") != "discounts"]
    buf = shop_render.render_purchases(
        user_id=user_id, balance=balance, total_spent=total_spent,
        purchases=filtered,
    )
    view = ShopPurchasesView()
    await _edit_screen(inter, buf=buf, view=view)


async def goto_daily(inter: disnake.MessageInteraction):
    from modules.actions import refresh_daily_deal
    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    total_spent = _get_total_spent(user_id)

    deal = refresh_daily_deal()
    slot_seconds = DAILY_DEAL_REFRESH_HOURS * 3600
    now_ts = int(time.time())
    next_ts = ((now_ts // slot_seconds) + 1) * slot_seconds
    hours_left = max((next_ts - now_ts) // 3600, 0)

    buf = shop_render.render_daily_deal(
        user_id=user_id, balance=balance, total_spent=total_spent,
        deal=deal, hours_left=hours_left,
    )
    if deal:
        view = ShopDealView(
            deal.get("cat_key", ""),
            deal.get("item_key", ""),
            deal.get("new_price", 0),
        )
    else:
        view = ShopDealView()
    await _edit_screen(inter, buf=buf, view=view)


async def goto_history(inter: disnake.MessageInteraction):
    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    total_spent = _get_total_spent(user_id)
    data = get_dc_cache(user_id)
    history = list(reversed((data.get("history") or [])[-20:]))
    buf = shop_render.render_history(
        user_id=user_id, balance=balance, total_spent=total_spent,
        history=history,
    )
    view = ShopHistoryView()
    await _edit_screen(inter, buf=buf, view=view)


# ============================================================
# ПОКУПКА
# ============================================================
async def handle_buy(inter: disnake.MessageInteraction, cat_key: str, item_key: str):
    user_id = inter.author.id
    catalog = load_shop_catalog()
    cat = catalog.get(cat_key, {})
    item = cat.get("items", {}).get(item_key)
    if not item:
        return await inter.response.send_message("Товар не найден.", ephemeral=True)

    price = int(item.get("price", 0))
    name = _strip_emoji(item.get("name", item_key))

    await inter.response.defer(ephemeral=True)

    balance = await get_user_balance(user_id)
    if balance < price:
        return await inter.edit_original_response(
            content=f"Недостаточно DC. Нужно: **{price} DC**, у тебя: **{balance} DC**."
        )

    success = await remove_dc(user_id, price, f"Покупка: {name}")
    if not success:
        return await inter.edit_original_response(
            content="Не удалось списать DC. Попробуй ещё раз."
        )

    await add_purchase(user_id, cat_key, name)

    try:
        from clan.quests import on_purchase_quest_hook
        await on_purchase_quest_hook(user_id, price)
    except Exception as e:
        logger.warning(f"shop buy clan hook: {e}")

    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot
        await check_and_unlock(user_id, "first_purchase", bot=bot)
        await check_and_unlock(user_id, "shop_spent", value=price, bot=bot)
    except Exception as e:
        logger.warning(f"shop buy ach: {e}")

    asyncio.create_task(log_discord(
        title="Покупка в DC-Shop",
        description=(
            f"**Пользователь:** <@{user_id}>\n"
            f"**Товар:** {name}\n"
            f"**Цена:** {price} DC"
        ),
        color=0x00aaff,
    ))

    await goto_purchases_after_buy(inter, user_id)


async def goto_purchases_after_buy(inter: disnake.MessageInteraction, user_id: int):
    balance = await get_user_balance(user_id)
    total_spent = _get_total_spent(user_id)
    purchases = await get_user_purchases(user_id, only_unused=True)
    filtered = [p for p in purchases if p.get("type") != "discounts"]

    buf = shop_render.render_purchases(
        user_id=user_id, balance=balance, total_spent=total_spent,
        purchases=filtered,
    )
    view = ShopPurchasesView()
    await _edit_screen(inter, buf=buf, view=view)


# ============================================================
# ПОДАРОК
# ============================================================
async def handle_gift(inter: disnake.ModalInteraction,
                      cat_key: str, item_key: str, recipient_id: int):
    user_id = inter.author.id

    if recipient_id == user_id:
        return await inter.response.send_message(
            "Нельзя подарить самому себе.", ephemeral=True
        )

    guild = inter.guild
    target = guild.get_member(recipient_id)
    if not target:
        return await inter.response.send_message(
            "Получатель не найден на сервере.", ephemeral=True
        )
    if target.bot:
        return await inter.response.send_message(
            "Нельзя дарить ботам.", ephemeral=True
        )

    catalog = load_shop_catalog()
    cat = catalog.get(cat_key, {})
    item = cat.get("items", {}).get(item_key)
    if not item:
        return await inter.response.send_message("Товар не найден.", ephemeral=True)

    price = int(item.get("price", 0))
    name = _strip_emoji(item.get("name", item_key))

    await inter.response.defer(ephemeral=True)

    balance = await get_user_balance(user_id)
    if balance < price:
        return await inter.edit_original_response(
            content=f"Недостаточно DC. Нужно: **{price} DC**, у тебя: **{balance} DC**."
        )

    success = await remove_dc(user_id, price, f"Покупка: {name} (подарок для {recipient_id})")
    if not success:
        return await inter.edit_original_response(
            content="Не удалось списать DC. Попробуй позже."
        )

    await add_purchase(recipient_id, cat_key, name)

    try:
        embed = disnake.Embed(
            title="Тебе подарили товар!",
            description=(
                f"**От:** <@{user_id}>\n"
                f"**Товар:** {name}\n\n"
                f"Оформить можно в витрине — открой тикет за DC."
            ),
            color=0x2ecc71,
            timestamp=datetime.now(timezone.utc),
        )
        await target.send(embed=embed)
    except disnake.Forbidden:
        pass
    except Exception as e:
        logger.warning(f"shop gift DM {recipient_id}: {e}")

    await log_discord(
        title="Подарок в DC-Shop",
        description=(
            f"**От:** <@{user_id}>\n"
            f"**Кому:** <@{recipient_id}>\n"
            f"**Товар:** {name}\n"
            f"**Цена:** {price} DC"
        ),
        color=0xffaa00,
    )

    await inter.edit_original_response(
        content=f"Готово! **{name}** подарен <@{recipient_id}>."
    )


async def handle_shop_modal(inter):
    pass
