# -*- coding: utf-8 -*-
import os
import json
import time
import random
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import disnake
from disnake.ext import commands
from disnake.ui import View, Button, Select, Modal, TextInput
from disnake import ButtonStyle, SelectOption

from core.utils import (
    CONFIG, FILES, BASE_DIR, DATA_DIR, CATALOG_DIR, ADD_DIR,
    logger, db, cur,
    load_json, save_json, now_ts,
    log_discord, log_command,
    has_admin_command_roles,
    clean_embed_for_discohook,
    get_dc_cache, save_dc_cache, sync_dc_to_json,
    update_user_roles
)

IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6ab152a3&is=6ab00123&hm=c5c2963ca1ebbe6eb37f673fcef993cacf375c5a80490205c230d4c4adfe8b58&"
IMG_UNUSED = "https://cdn.discordapp.com/attachments/1527006158282555412/1551572210811011142/image.png?ex=6ab275b9&is=6ab12439&hm=7d8e471545619f792391577a7a0bf5335995f759c5c8b09534ac840b881fc806&"


# ============================================================
# DC DATA
# ============================================================
def get_user_dc_data(user_id: int) -> dict:
    return get_dc_cache(user_id)


def save_user_dc_data(user_id: int, user_data: dict):
    save_dc_cache(user_id, user_data)
    sync_dc_to_json()


async def get_user_balance(user_id: int) -> int:
    return get_dc_cache(user_id)["balance"]


async def set_user_balance(user_id: int, amount: int):
    data = get_dc_cache(user_id)
    data["balance"] = amount
    save_dc_cache(user_id, data)
    sync_dc_to_json()


async def _notify_dc_change(user_id: int, delta: int, reason: str, new_balance: int):
    """Отправляет ЛС при ручном изменении DC. Молча падает, если ЛС закрыты."""
    try:
        from core.bot import bot
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except Exception:
                return
        if user is None:
            return

        if delta >= 0:
            title = f"💎 Вам начислено {abs(delta)} DC"
            color = 0x2ecc71
        else:
            title = f"💎 У вас списано {abs(delta)} DC"
            color = 0xff6600

        embed = disnake.Embed(
            title=title,
            description=(
                f"> **Причина:** {reason}\n"
                f"> **Новый баланс:** `{new_balance} DC`"
            ),
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_image(url=IMG_STRIPE)
        await user.send(embed=embed)
    except disnake.Forbidden:
        logger.debug(f"ЛС закрыты у {user_id}")
    except Exception as e:
        logger.warning(f"_notify_dc_change {user_id}: {e}")


async def add_dc(user_id: int, amount: int, reason: str, notify: bool = False):
    """Начисляет DC. notify=True — отправит ЛС пользователю."""
    data = get_dc_cache(user_id)
    data["balance"] += amount
    data["history"].append({
        "date": int(time.time()),
        "amount": amount,
        "reason": reason,
    })
    if len(data["history"]) > 50:
        data["history"] = data["history"][-50:]
    save_dc_cache(user_id, data)
    sync_dc_to_json()

    await log_discord(
        title="💎 Начислены Diamond Coins",
        description=f"> **Пользователь:** <@{user_id}>\n> **Количество:** `+{amount} DC`\n> **Причина:** {reason}\n> **Новый баланс:** `{data['balance']} DC`",
        color=0x00ff00
    )

    if notify:
        await _notify_dc_change(user_id, amount, reason, data["balance"])


async def remove_dc(user_id: int, amount: int, reason: str, notify: bool = False) -> bool:
    """Списывает DC. notify=True — отправит ЛС пользователю."""
    data = get_dc_cache(user_id)
    if data["balance"] < amount:
        return False
    data["balance"] -= amount
    data["history"].append({
        "date": int(time.time()),
        "amount": -amount,
        "reason": reason,
    })
    if len(data["history"]) > 50:
        data["history"] = data["history"][-50:]
    save_dc_cache(user_id, data)
    sync_dc_to_json()

    await log_discord(
        title="💎 Списаны Diamond Coins",
        description=f"> **Пользователь:** <@{user_id}>\n> **Количество:** `-{amount} DC`\n> **Причина:** {reason}\n> **Новый баланс:** `{data['balance']} DC`",
        color=0xff6600
    )

    if notify:
        await _notify_dc_change(user_id, -amount, reason, data["balance"])

    return True


async def add_purchase(user_id: int, item_type: str, item_value: str, from_action: bool = False):
    data = get_dc_cache(user_id)
    for p in data["purchases"]:
        if p["type"] == item_type and p["value"] == item_value and not p["used"]:
            return
    data["purchases"].append({
        "type": item_type,
        "value": item_value,
        "used": False,
        "from_action": from_action,
        "date": int(time.time()),
    })
    save_dc_cache(user_id, data)
    sync_dc_to_json()


async def get_user_purchases(user_id: int, only_unused: bool = False) -> list:
    data = get_dc_cache(user_id)
    purchases = data.get("purchases", [])
    if only_unused:
        return [p for p in purchases if not p["used"]]
    return purchases


async def remove_purchase(user_id: int, purchase_index: int):
    data = get_dc_cache(user_id)
    if 0 <= purchase_index < len(data["purchases"]):
        del data["purchases"][purchase_index]
        save_dc_cache(user_id, data)
        sync_dc_to_json()
        return True
    return False


# ============================================================
# АКТИВНОСТЬ
# ============================================================
async def check_and_reset_daily(user_id: int):
    data = get_dc_cache(user_id)
    now = int(time.time())
    last_reset = data.get("last_reset_date", 0)
    if now - last_reset >= 86400:
        data["messages_today"] = 0
        data["voice_time_today"] = 0
        data["last_reset_date"] = now
        save_dc_cache(user_id, data)
        sync_dc_to_json()
        return True
    return False


async def add_message_dc(user_id: int):
    data = get_dc_cache(user_id)
    await check_and_reset_daily(user_id)
    data["messages_today"] = data.get("messages_today", 0) + 1
    if data["messages_today"] % CONFIG["MESSAGE_BATCH"] == 0:
        max_dc = CONFIG["MAX_DAILY_MESSAGES"]
        current = data["messages_today"] // CONFIG["MESSAGE_BATCH"]
        if current <= max_dc:
            await add_dc(user_id, CONFIG["MESSAGE_RATE"],
                         f"За {CONFIG['MESSAGE_BATCH']} сообщений в чате")
            data = get_dc_cache(user_id)
            data["messages_today"] = data.get("messages_today", 0)
            save_dc_cache(user_id, data)
            sync_dc_to_json()
    else:
        save_dc_cache(user_id, data)
        sync_dc_to_json()


async def add_voice_dc(user_id: int, seconds: int):
    data = get_dc_cache(user_id)
    await check_and_reset_daily(user_id)
    data["voice_time_today"] = data.get("voice_time_today", 0) + seconds
    hours = data["voice_time_today"] // 3600
    max_dc = CONFIG["MAX_DAILY_VOICE"]
    target = min(hours * CONFIG["VOICE_RATE"], max_dc)
    last_voice_dc = data.get("last_voice_dc", 0)
    if target > last_voice_dc:
        diff = target - last_voice_dc
        if diff > 0:
            await add_dc(user_id, diff, f"За {hours} часов в голосовом канале")
            data["last_voice_dc"] = target
            save_dc_cache(user_id, data)
            sync_dc_to_json()
    else:
        save_dc_cache(user_id, data)
        sync_dc_to_json()


# ============================================================
# КАТАЛОГ
# ============================================================
def load_shop_catalog() -> dict:
    path = CONFIG["SHOP_CATALOG_PATH"]
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                logger.error("shop_catalog.json parse err")
                return create_default_catalog()
    return create_default_catalog()


def create_default_catalog() -> dict:
    catalog = {
        "discounts": {"label": "🛒 Скидки", "description": "Скидки на заказы", "items": {
            "3": {"name": "3% скидка", "price": 30, "description": "Скидка 3%"},
        }},
        "design": {"label": "🎨 Дизайн", "description": "Услуги дизайнера", "items": {
            "avatar": {"name": "Аватарка", "price": 40, "description": "Уникальная аватарка"},
        }},
    }
    with open(CONFIG["SHOP_CATALOG_PATH"], "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    return catalog


# ============================================================
# ЕЖЕДНЕВНЫЙ БОНУС
# ============================================================
async def daily_bonus():
    from core.bot import bot
    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        return
    club_role = guild.get_role(CONFIG["ROLE_IDS"]["club"])
    if not club_role:
        return
    now = now_ts()
    for member in guild.members:
        if member.bot:
            continue
        if club_role not in member.roles:
            continue
        data = get_dc_cache(member.id)
        if data["last_bonus"] < now - 86400:
            await add_dc(member.id, 3, "Ежедневный бонус (Клуб)")
            data["last_bonus"] = now
            save_dc_cache(member.id, data)
            sync_dc_to_json()


# ============================================================
# НАПОМИНАНИЯ О НЕИСПОЛЬЗОВАННЫХ ТОВАРАХ
# ============================================================
async def check_unused_purchases(bot):
    now = int(time.time())
    week = 7 * 86400

    rows = cur.execute("SELECT user_id, purchases FROM dc_cache").fetchall()
    sent = 0
    checked = 0

    for row in rows:
        uid = row["user_id"]
        try:
            purchases = json.loads(row["purchases"]) if row["purchases"] else []
        except Exception:
            continue
        if not purchases:
            continue

        checked += 1
        old_unused = []
        for idx, p in enumerate(purchases):
            if p.get("used"):
                continue
            d = p.get("date", 0)
            if d == 0:
                continue
            age = now - d
            if week <= age <= 60 * 86400:
                last_rem = p.get("last_reminder", 0)
                if now - last_rem >= week:
                    old_unused.append((idx, p))

        if not old_unused:
            continue

        user = bot.get_user(uid)
        if user is None:
            try:
                user = await bot.fetch_user(uid)
            except Exception:
                continue

        try:
            items_lines = []
            for _, p in old_unused[:10]:
                v = p.get("value", "—")
                t = p.get("type", "")
                dstr = datetime.fromtimestamp(p.get("date", 0)).strftime("%d.%m.%Y")
                items_lines.append(f"> 💎 **{v}** — `{t}` (куплен {dstr})")
            items_text = "\n".join(items_lines)
            more = ""
            if len(old_unused) > 10:
                more = f"\n\n> …и ещё **{len(old_unused) - 10}** товаров"

            embed1 = disnake.Embed(color=6776679)
            embed1.set_image(url=IMG_UNUSED)
            embed2 = disnake.Embed(
                title="🎁 У вас есть неиспользованные товары!",
                description=(
                    f"> Привет, **{user.display_name}**! Мы заметили, что у вас есть купленные товары, которые вы **ещё не активировали**.\n\n"
                    f"**Товары:**\n{items_text}{more}\n\n"
                    f"**Как активировать?**\n"
                    f"> Перейдите в <#1462136361711829053>, нажмите кнопку **Купить** → выберите **Diamond Coins** → выберите нужный товар.\n\n"
                    f"> Если возникли вопросы — обратитесь в поддержку.\n"
                    f"> Приятных покупок! 💎"
                ),
                color=6776679,
                timestamp=datetime.now(timezone.utc)
            )
            embed2.set_image(url=IMG_STRIPE)
            await user.send(embeds=[embed1, embed2])

            for idx, p in old_unused:
                purchases[idx]["last_reminder"] = now

            dc_data = get_dc_cache(uid)
            dc_data["purchases"] = purchases
            save_dc_cache(uid, dc_data)
            sent += 1

            await asyncio.sleep(0.5)
        except disnake.Forbidden:
            continue
        except Exception as e:
            logger.warning(f"unused reminder {uid}: {e}")
            continue

    try:
        sync_dc_to_json()
    except Exception:
        pass

    logger.info(f"check_unused_purchases: проверено {checked}, отправлено {sent}")


# ============================================================
# ПРОГРЕСС-БАР
# ============================================================
def get_progress_bar(count: int):
    thresholds = [
        (1, "club", "Клуб"),
        (2, "bronze", "Бронзовый покупатель"),
        (4, "silver", "Серебряный покупатель"),
        (8, "gold", "Золотой покупатель"),
        (12, "diamond", "Алмазный покупатель"),
        (17, "emerald", "Изумрудный покупатель"),
        (23, "amethyst", "Аметистовый покупатель"),
        (25, "legendary", "Легендарный покупатель"),
        (float('inf'), "pka", "Покупатель века"),
    ]
    current_role = "Нет"
    next_role = "Клуб"
    next_threshold = 1
    for threshold, key, name in thresholds:
        if count >= threshold:
            current_role = name
        else:
            next_threshold = threshold
            next_role = name
            break
    if count >= 26:
        return f"Текущая: **{current_role}** (26+)\n🎉 Вы достигли максимальной роли!"
    else:
        progress = min(count / next_threshold, 1.0)
        bar_length = 10
        filled = int(progress * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        return (f"Текущая: **{current_role}**\n"
                f"Следующая: **{next_role}** (нужно {next_threshold} отзывов)\n"
                f"Прогресс: `{bar}` {int(progress*100)}%")


def get_dc_cache_all() -> dict:
    rows = cur.execute("SELECT * FROM dc_cache").fetchall()
    data = {}
    for row in rows:
        uid = row["user_id"]
        data[str(uid)] = {
            "balance": row["balance"],
            "purchases": json.loads(row["purchases"]) if row["purchases"] else [],
            "history": json.loads(row["history"]) if row["history"] else [],
            "last_review": row["last_review"],
            "last_bonus": row["last_bonus"],
            "messages_today": row["messages_today"],
            "voice_time_today": row["voice_time_today"],
            "last_reset_date": row["last_reset_date"],
            "last_voice_dc": row["last_voice_dc"],
        }
    return data


def setup_dc(bot):
    pass
