# -*- coding: utf-8 -*-
"""
Логика витрины DC-Shop: навигация, покупка, подарок,
успешный экран после покупки. Anti-double-click на покупке.
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
    add_dc,
)
from modules.shop import state
from modules.shop import render as shop_render
from modules.shop.views import (
    ShopMainView, ShopProductsView, ShopDetailView,
    ShopPurchasesView, ShopDealView, ShopHistoryView,
    ShopSuccessView,
)


DAILY_DEAL_REFRESH_HOURS = 5

REVIEW_CHANNEL_ID = CONFIG.get("REVIEW_COUNT_CHANNEL", 1462074763437543435)


# ============================================================
# ЗАЩИТА ОТ ДВОЙНОГО НАЖАТИЯ
# ============================================================
_BUY_LOCKS: dict = {}    # (user_id, "cat:item") → timestamp последнего клика


def _prune_locks(now: float):
    if len(_BUY_LOCKS) > 200:
        cutoff = now - 60
        for k in list(_BUY_LOCKS.keys()):
            if _BUY_LOCKS[k] < cutoff:
                _BUY_LOCKS.pop(k, None)


# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _get_total_spent(user_id: int) -> int:
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


def _default_cat_description(key: str) -> str:
    return {
        "discounts": (
            "Скидки на заказы в магазине. После покупки скидка "
            "применяется в тикете — выбери её на кнопке «Скидки» "
            "и она подставится в заказ."
        ),
        "design": (
            "Индивидуальный дизайн от команды Diamond. Аватарка, "
            "баннер, логотип — сделаем под твой вкус, уточним "
            "детали в тикете."
        ),
        "ads": (
            "Реклама сервера или проекта в каналах Diamond. Пост, "
            "закреп или упоминание в новостях — расскажем о тебе "
            "сообществу."
        ),
        "roles": (
            "Особые роли сервера. Часть выдаётся автоматически "
            "после покупки, часть — вручную в тикете. Каждая даёт "
            "свой стиль и доступ."
        ),
        "boosts": (
            "Усилители DC-заработка: ×2 к сообщениям, войсу, "
            "отзывам. Активируются сразу после покупки и работают "
            "указанное время."
        ),
        "casino": (
            "Предметы для казино: страховка ставки, ×2 выигрыш, "
            "удачный час, билет джекпота. Применяются автоматически "
            "в играх."
        ),
        "gifts": (
            "Подари Diamond Coins другому участнику — с комиссией 5%. "
            "Введи ID получателя и сумма сразу уйдёт на его баланс."
        ),
    }.get(key, "Товары этой категории — выбери что-то по вкусу и оформи в тикет.")


def _default_item_description(cat_key: str, name: str) -> str:
    m = {
        "discounts": f"Скидка «{name}» действует на любой заказ в магазине. Применяешь в тикете — она автоматически вычитается из итоговой суммы.",
        "design":    f"«{name}» делаем под тебя: стиль, цвета и композиция согласуются в тикете. Срок — до 2 рабочих дней.",
        "ads":       f"«{name}» публикуется в каналах Diamond. Расскажем о тебе или твоём проекте нашей аудитории.",
        "roles":     f"«{name}» — особая роль сервера. Даёт свой стиль, доступ к закрытым каналам и активностям.",
        "boosts":    f"«{name}» активируется сразу после покупки. Работает указанное время, потом можно купить снова.",
        "casino":    f"«{name}» — усилитель для игр в казино. Применяется автоматически в следующей партии.",
        "gifts":     f"«{name}» — подарок DC другому участнику. Комиссия магазина 5%.",
    }
    return m.get(cat_key, f"«{name}» — товар из категории магазина Diamond.")


def _get_categories_list() -> List[Dict]:
    catalog = load_shop_catalog()
    result = []
    for key, cat in catalog.items():
        items = cat.get("items", {})
        label = cat.get("label", key)
        description = _strip_emoji(cat.get("description", "") or "")
        prices = [int(it.get("price", 0)) for it in items.values()]
        min_price = min(prices) if prices else 0
        if not description:
            description = _default_cat_description(key)
        result.append({
            "key": key,
            "label": _strip_emoji(label),
            "count": len(items),
            "min_price": min_price,
            "description": description,
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
        desc = it.get("description", "") or ""
        if not desc:
            desc = _default_item_description(cat_key, name)
        result.append({
            "key": key,
            "name": name,
            "price": int(it.get("price", 0)),
            "description": desc,
            "fa": shop_render.CATEGORY_FA.get(cat_key, shop_render.I_CUBE),
        })
    result.sort(key=lambda x: x["price"])
    return result


def _filter_history_purchases(history: list) -> list:
    result = []
    for h in history or []:
        amt = h.get("amount", 0) or 0
        reason = h.get("reason", "") or ""
        if amt < 0 and reason.startswith("Покупка"):
            result.append(h)
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
    fname = f"shop_{inter.author.id}_{int(time.time() * 1000)}.png"
    file = disnake.File(buf, filename=fname)
    embed = disnake.Embed(color=shop_render.EMBED_COLOR)
    embed.set_image(url=f"attachment://{fname}")

    kwargs = dict(
        content=None,
        embed=embed,
        file=file,
        attachments=[],
        view=view,
    )

    try:
        if inter.response.is_done():
            await inter.edit_original_response(**kwargs)
        else:
            await inter.response.edit_message(**kwargs)
    except disnake.InteractionResponded:
        await inter.edit_original_response(**kwargs)


# ============================================================
# ОТКРЫТИЕ
# ============================================================
async def open_shop(inter: disnake.MessageInteraction):
    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    total_spent = _get_total_spent(user_id)
    categories = _get_categories_list()
    total_items = sum(c["count"] for c in categories)

    buf = shop_render.render_categories(
        user_id=user_id,
        balance=balance,
        total_spent=total_spent,
        categories=categories,
        total_items=total_items,
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
    total_items = sum(c["count"] for c in categories)

    buf = shop_render.render_categories(
        user_id=user_id,
        balance=balance,
        total_spent=total_spent,
        categories=categories,
        total_items=total_items,
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
        user_id=user_id,
        balance=balance,
        total_spent=total_spent,
        category_key=cat_key,
        category_label=cat_label,
        items=items,
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
    name = _strip_emoji(item.get("name", item_key))
    desc = item.get("description", "") or _default_item_description(cat_key, name)
    item_view = {
        "name": name,
        "price": int(item.get("price", 0)),
        "description": desc,
        "fa": shop_render.CATEGORY_FA.get(cat_key, shop_render.I_CUBE),
    }
    buf = shop_render.render_detail(
        user_id=user_id,
        balance=balance,
        total_spent=total_spent,
        category_key=cat_key,
        category_label=cat_label,
        item=item_view,
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
        user_id=user_id,
        balance=balance,
        total_spent=total_spent,
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
        user_id=user_id,
        balance=balance,
        total_spent=total_spent,
        deal=deal,
        hours_left=hours_left,
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
    raw = data.get("history") or []
    purchases = _filter_history_purchases(raw)
    history = list(reversed(purchases[-20:]))

    buf = shop_render.render_history(
        user_id=user_id,
        balance=balance,
        total_spent=total_spent,
        history=history,
    )
    view = ShopHistoryView()
    await _edit_screen(inter, buf=buf, view=view)


# ============================================================
# ВЫБОР ОУТКОМА ПОСЛЕ ПОКУПКИ
# ============================================================
def _build_outcome(cat_key: str, item: dict, name: str, price: int,
                   guild_id: int) -> dict:
    cat = (cat_key or "").lower()
    has_role = bool(item.get("role_id"))
    boost_type = item.get("boost_type")
    gift_amount = item.get("gift_amount")
    is_auto_role = (cat == "roles" and has_role)
    is_boost = bool(boost_type) and cat in ("boosts", "casino")

    if is_auto_role:
        return {
            "kind": "role",
            "icon": shop_render.I_CHECK,
            "color": shop_render.GREEN,
            "uid_label": "покупка · роль",
            "head_title": "Роль выдана",
            "head_sub": "проверь профиль",
            "title": "Роль на твоём аккаунте!",
            "subtitle": (
                f"Роль «{name}» уже выдана автоматически — "
                f"загляни в свой профиль Discord, она уже там. "
                f"Все привилегии роли активны сразу."
            ),
            "item_line": f"{name} · {price} DC",
            "steps": [
                "Открой свой профиль Discord — увидишь новую роль",
                "Оставь отзыв — за одобренный отзыв начислим +15 DC",
                "Возвращайся в магазин — есть ещё много интересного",
            ],
            "hint": "Оставь отзыв — это даёт +15 DC на баланс",
            "show_review": True,
            "left_blocks": [
                {
                    "label": "Роль выдана",
                    "value": name,
                    "icon": shop_render.I_MASKS,
                    "color": shop_render.GREEN,
                },
            ],
        }

    if is_boost:
        return {
            "kind": "boost",
            "icon": shop_render.I_BOLT,
            "color": shop_render.PURPLE,
            "uid_label": "покупка · буст",
            "head_title": "Активировано",
            "head_sub": "применено сразу",
            "title": "Буст уже работает!",
            "subtitle": (
                f"«{name}» активирован автоматически — можешь "
                f"пользоваться прямо сейчас. Действует ровно "
                f"указанное время с момента покупки."
            ),
            "item_line": f"{name} · {price} DC",
            "steps": [
                "Пиши в чат — награда за 10 сообщений удвоена",
                "Прогресс и активные бусты — в панели профиля",
                "Когда буст закончится — можно купить ещё раз",
            ],
            "hint": "Активировано — можно пользоваться",
            "show_review": False,
            "left_blocks": [
                {
                    "label": "Активировано",
                    "value": name,
                    "icon": shop_render.I_BOLT,
                    "color": shop_render.PURPLE,
                },
            ],
        }

    return {
        "kind": "ticket",
        "icon": shop_render.I_TICKET,
        "color": shop_render.BLUE,
        "uid_label": "покупка · товар",
        "head_title": "Товар в инвентаре",
        "head_sub": "оформи в тикет",
        "title": "Осталось оформить тикет",
        "subtitle": (
            f"«{name}» добавлен в твой инвентарь. Оформи тикет, "
            f"чтобы менеджер выдал товар вручную — согласуете "
            f"стиль и детали работы."
        ),
        "item_line": f"{name} · {price} DC",
        "steps": [
            "Открой панель магазина в канале витрины",
            "Нажми «Купить» → выбери «Diamond Coins»",
            "Выбери этот товар в списке — откроется тикет",
            "Менеджер свяжется и выдаст заказ до 2 рабочих дней",
        ],
        "hint": "Оформи тикет через «Купить» → Diamond Coins",
        "show_review": False,
        "left_blocks": [
            {
                "label": "Куплено",
                "value": name,
                "icon": shop_render.I_TICKET,
                "color": shop_render.BLUE,
            },
            {
                "label": "Что дальше",
                "value": "Оформить тикет",
                "icon": shop_render.I_INFO,
                "color": shop_render.SILVER,
            },
        ],
    }


# ============================================================
# ПОКУПКА (с anti-double-click)
# ============================================================
async def handle_buy(inter: disnake.MessageInteraction, cat_key: str, item_key: str):
    user_id = inter.author.id

    # Anti-double-click: 8 секунд блокировки на тот же товар
    lock_key = (user_id, f"{cat_key}:{item_key}")
    now_ts = time.time()
    prev = _BUY_LOCKS.get(lock_key, 0)
    if now_ts - prev < 8:
        try:
            await inter.response.send_message(
                "⏳ Покупка уже обрабатывается, подожди пару секунд...",
                ephemeral=True,
            )
        except Exception:
            pass
        return
    _BUY_LOCKS[lock_key] = now_ts
    _prune_locks(now_ts)

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
            content=f"❌ Недостаточно DC. Нужно: **{price} DC**, у тебя: **{balance} DC**."
        )

    success = await remove_dc(user_id, price, f"Покупка: {name}")
    if not success:
        return await inter.edit_original_response(
            content="❌ Не удалось списать DC. Попробуй ещё раз."
        )

    # Авто-выдача роли
    auto_role_given = False
    if cat_key == "roles" and item.get("role_id"):
        role = inter.guild.get_role(int(item["role_id"]))
        if role:
            try:
                member = inter.guild.get_member(user_id)
                if member and role not in member.roles:
                    await member.add_roles(role, reason=f"Покупка в DC-Shop: {name}")
                    auto_role_given = True
                elif member:
                    auto_role_given = True
            except Exception as e:
                logger.warning(f"shop auto-role give {user_id}: {e}")

    # Активация буста / казино-предмета
    if item.get("boost_type"):
        try:
            from core.utils import activate_item
            activate_item(
                user_id=user_id,
                item_key=item_key,
                item_type=cat_key,
                value=float(item.get("value", 0) or 0),
                duration_hours=int(item.get("duration_hours", 0) or 0),
                uses=int(item.get("uses", -1)),
            )
        except Exception as e:
            logger.warning(f"shop boost activate {user_id}: {e}")

    # В инвентарь — только не-автороли и не-бусты
    if not (cat_key == "roles" and item.get("role_id")) and not item.get("boost_type"):
        await add_purchase(user_id, cat_key, name)

    # Хуки квестов / достижений
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
            f"**Цена:** {price} DC\n"
            f"**Авто-роль:** {'да' if auto_role_given else 'нет'}"
        ),
        color=0x00aaff,
    ))

    await goto_success(inter, user_id, cat_key, item, name, price)


async def goto_success(inter, user_id: int,
                       cat_key: str, item: dict, name: str, price: int):
    balance = await get_user_balance(user_id)
    total_spent = _get_total_spent(user_id)

    outcome = _build_outcome(
        cat_key, item, name, price, inter.guild.id if inter.guild else 0
    )

    buf = shop_render.render_success(
        user_id=user_id,
        balance=balance,
        total_spent=total_spent,
        outcome=outcome,
    )
    view = ShopSuccessView(show_review=outcome.get("show_review", False))
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
    gift_amount = item.get("gift_amount")

    await inter.response.defer(ephemeral=True)

    balance = await get_user_balance(user_id)
    if balance < price:
        return await inter.edit_original_response(
            content=f"❌ Недостаточно DC. Нужно: **{price} DC**, у тебя: **{balance} DC**."
        )

    success = await remove_dc(
        user_id, price,
        f"Покупка: {name} (подарок для {recipient_id})"
    )
    if not success:
        return await inter.edit_original_response(
            content="❌ Не удалось списать DC. Попробуй позже."
        )

    if gift_amount:
        try:
            await add_dc(
                recipient_id,
                int(gift_amount),
                f"Подарок от {user_id}",
                notify=True,
                log=False,
            )
        except Exception as e:
            logger.warning(f"shop gift DC send {recipient_id}: {e}")

        try:
            embed = disnake.Embed(
                title="Тебе подарили Diamond Coins!",
                description=(
                    f"**От:** <@{user_id}>\n"
                    f"**Получено:** `+{gift_amount} DC`\n\n"
                    f"Ты можешь потратить их в DC-магазине."
                ),
                color=0x2ecc71,
                timestamp=datetime.now(timezone.utc),
            )
            await target.send(embed=embed)
        except disnake.Forbidden:
            pass
        except Exception as e:
            logger.warning(f"shop gift DC DM {recipient_id}: {e}")
    else:
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
            logger.warning(f"shop gift item DM {recipient_id}: {e}")

    await log_discord(
        title="Подарок в DC-Shop",
        description=(
            f"**От:** <@{user_id}>\n"
            f"**Кому:** <@{recipient_id}>\n"
            f"**Товар:** {name}\n"
            f"**Цена:** {price} DC"
            + (f"\n**DC получателю:** {gift_amount}" if gift_amount else "")
        ),
        color=0xffaa00,
    )

    if gift_amount:
        outcome = {
            "kind": "gift",
            "icon": shop_render.I_GIFT,
            "color": shop_render.GREEN,
            "uid_label": "подарок",
            "head_title": "Подарок отправлен",
            "head_sub": "получатель уведомлён",
            "title": "Подарок доставлен!",
            "subtitle": (
                f"<@{recipient_id}> получил {gift_amount} DC "
                f"и уведомление в ЛС."
            ),
            "item_line": f"{name} · {price} DC",
            "steps": [
                f"<@{recipient_id}> получил {gift_amount} DC на баланс",
                "Ему отправлено уведомление в личные сообщения",
                "Комиссия магазина 5% удержана при покупке",
                "Ты можешь подарить кому-то ещё",
            ],
            "hint": "Подарок доставлен получателю",
            "show_review": False,
            "left_blocks": [
                {
                    "label": "Подарок доставлен",
                    "value": f"+{gift_amount} DC",
                    "icon": shop_render.I_GIFT,
                    "color": shop_render.GREEN,
                },
            ],
        }
    else:
        outcome = {
            "kind": "gift",
            "icon": shop_render.I_GIFT,
            "color": shop_render.GREEN,
            "uid_label": "подарок",
            "head_title": "Подарок отправлен",
            "head_sub": "получатель уведомлён",
            "title": "Подарок доставлен!",
            "subtitle": (
                f"<@{recipient_id}> получил «{name}» в свой инвентарь."
            ),
            "item_line": f"{name} · {price} DC",
            "steps": [
                f"Товар добавлен в инвентарь <@{recipient_id}>",
                "Ему отправлено уведомление в личные сообщения",
                "Получатель оформит тикет и получит товар",
                "Ты можешь подарить кому-то ещё",
            ],
            "hint": "Подарок доставлен получателю",
            "show_review": False,
            "left_blocks": [
                {
                    "label": "Подарено",
                    "value": name,
                    "icon": shop_render.I_GIFT,
                    "color": shop_render.GREEN,
                },
            ],
        }

    try:
        balance = await get_user_balance(user_id)
        total_spent = _get_total_spent(user_id)
        buf = shop_render.render_success(
            user_id=user_id,
            balance=balance,
            total_spent=total_spent,
            outcome=outcome,
        )
        fname = f"shop_{user_id}_{int(time.time() * 1000)}.png"
        file = disnake.File(buf, filename=fname)
        embed = disnake.Embed(color=shop_render.EMBED_COLOR)
        embed.set_image(url=f"attachment://{fname}")
        await inter.edit_original_response(
            content=None, embed=embed, file=file, attachments=[],
            view=ShopSuccessView(show_review=False),
        )
    except Exception as e:
        logger.warning(f"gift success screen {user_id}: {e}")
        try:
            await inter.edit_original_response(
                content=f"Готово! Подарок отправлен <@{recipient_id}>."
            )
        except Exception:
            pass


async def handle_shop_modal(inter):
    pass
