# -*- coding: utf-8 -*-
import os
import json
import time
from datetime import datetime, timezone
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
from modules.boosts import (
    apply_boost, get_review_cooldown, get_multiplier,
)

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

async def add_dc(user_id: int, amount: int, reason: str):
    data = get_dc_cache(user_id)
    data["balance"] += amount
    data["history"].append({
        "date": int(time.time()),
        "amount": amount,
        "reason": reason
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

async def remove_dc(user_id: int, amount: int, reason: str) -> bool:
    data = get_dc_cache(user_id)
    if data["balance"] < amount:
        return False
    data["balance"] -= amount
    data["history"].append({
        "date": int(time.time()),
        "amount": -amount,
        "reason": reason
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
        "date": int(time.time())
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
# Активность
# ============================================================
async def check_and_reset_daily(user_id: int):
    """Обнуляет счётчики раз в 24 часа. Бусты daily_reset не трогают этот код."""
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
    await check_and_reset_daily(user_id)
    data = get_dc_cache(user_id)
    data["messages_today"] = data.get("messages_today", 0) + 1

    if data["messages_today"] % CONFIG["MESSAGE_BATCH"] == 0:
        max_dc = CONFIG["MAX_DAILY_MESSAGES"]
        current = data["messages_today"] // CONFIG["MESSAGE_BATCH"]
        if current <= max_dc:
            base = CONFIG["MESSAGE_RATE"]
            mult = get_multiplier(user_id, "messages")
            reward = int(base * mult)

            reason = f"За {CONFIG['MESSAGE_BATCH']} сообщений в чате"
            if mult > 1.0:
                reason += f" (x{mult:.1f} буст)"

            await add_dc(user_id, reward, reason)

            data = get_dc_cache(user_id)
            data["messages_today"] = data.get("messages_today", 0)
            save_dc_cache(user_id, data)
            sync_dc_to_json()
        else:
            save_dc_cache(user_id, data)
            sync_dc_to_json()
    else:
        save_dc_cache(user_id, data)
        sync_dc_to_json()

async def add_voice_dc(user_id: int, seconds: int):
    await check_and_reset_daily(user_id)
    data = get_dc_cache(user_id)
    data["voice_time_today"] = data.get("voice_time_today", 0) + seconds
    hours = data["voice_time_today"] // 3600

    mult = get_multiplier(user_id, "voice")
    base_rate = CONFIG["VOICE_RATE"]
    max_dc = CONFIG["MAX_DAILY_VOICE"]

    if mult > 1.0:
        target = min(int(hours * base_rate * mult), max_dc * 2)
    else:
        target = min(hours * base_rate, max_dc)

    last_voice_dc = data.get("last_voice_dc", 0)

    if target > last_voice_dc:
        diff = target - last_voice_dc
        if diff > 0:
            reason = f"За {hours} часов в голосовом канале"
            if mult > 1.0:
                reason += f" (x{mult:.1f} буст)"
            await add_dc(user_id, diff, reason)
            data["last_voice_dc"] = target
            save_dc_cache(user_id, data)
            sync_dc_to_json()
    else:
        save_dc_cache(user_id, data)
        sync_dc_to_json()

# ============================================================
# Каталог
# ============================================================
def load_shop_catalog() -> dict:
    path = CONFIG["SHOP_CATALOG_PATH"]
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                logger.error("Ошибка парсинга shop_catalog.json, создаю дефолтный")
                return create_default_catalog()
    else:
        return create_default_catalog()

def create_default_catalog() -> dict:
    catalog = {
        "discounts": {
            "label": "🛒 Скидки",
            "description": "Скидки на заказы в магазине",
            "items": {
                "3":  {"name": "Скидка 3%",  "price": 120, "description": "Скидка 3% на любой заказ"},
                "5":  {"name": "Скидка 5%",  "price": 200, "description": "Скидка 5% на любой заказ"},
                "7":  {"name": "Скидка 7%",  "price": 280, "description": "Скидка 7% на любой заказ"},
                "10": {"name": "Скидка 10%", "price": 420, "description": "Скидка 10% на любой заказ"},
                "15": {"name": "Скидка 15%", "price": 650, "description": "Скидка 15% на любой заказ"},
                "20": {"name": "Скидка 20%", "price": 850, "description": "Скидка 20% на любой заказ"}
            }
        },
        "design": {
            "label": "🎨 Дизайн от Diamond",
            "description": "Услуги дизайнера",
            "items": {
                "avatar": {"name": "Аватарка", "price": 60, "description": "Уникальная аватарка"},
                "banner": {"name": "Баннер",   "price": 120, "description": "Баннер для профиля"},
                "logo":   {"name": "Логотип",  "price": 180, "description": "Логотип для бренда"}
            }
        },
        "ads": {
            "label": "📢 Реклама",
            "description": "Продвижение в соцсетях и сервере",
            "items": {
                "ad_post": {"name": "Пост в канале",         "price": 90,  "description": "Рекламный пост в канале"},
                "ad_pin":  {"name": "Закреп на 24ч",         "price": 120, "description": "Закреп сообщения на 24 часа"},
                "ad_news": {"name": "Упоминание в новостях", "price": 150, "description": "Упоминание в новостной ленте"}
            }
        },
        "roles": {
            "label": "🎭 Особые роли",
            "description": "Временные и постоянные роли",
            "items": {
                "role_active": {"name": "Роль «Активный»", "price": 40, "description": "Постоянная роль «Активный»", "role_id": 1533140263789395998},
                "role_helper": {"name": "Роль «Помощник»", "price": 50, "description": "Роль «Помощник» (навсегда)", "role_id": 1536948551265812551},
                "role_vip":    {"name": "Роль «VIP»",      "price": 60, "description": "VIP-роль на 30 дней",         "role_id": 1533549996790513685},
                "role_mega":   {"name": "Роль «Мега-активный»", "price": 80, "description": "Роль «Мега-активный»", "role_id": 1536948737514151976},
                "role_legend": {"name": "Роль «Легенда»", "price": 95, "description": "Легендарная роль", "role_id": 1535638212557541438},
                "role_newbie": {"name": "Роль «Новичок месяца»", "price": 100, "description": "Роль для новичков", "role_id": 1536948841394212934}
            }
        },
        "boosts": {
            "label": "⚡ Бусты",
            "description": "Временные усилители DC-заработка",
            "items": {
                "boost_messages_x2":   {"name": "x2 к DC за сообщения (24ч)",     "price": 120, "description": "Удвоение награды за 10 сообщений на сутки", "boost_type": "messages_mult", "value": 2.0, "duration_hours": 24},
                "boost_voice_x2":      {"name": "x2 к DC за войс (24ч)",          "price": 120, "description": "Удвоение награды за час в войсе на сутки",  "boost_type": "voice_mult",    "value": 2.0, "duration_hours": 24},
                "boost_all_x2":        {"name": "x2 ко всему DC-заработку (12ч)", "price": 280, "description": "Удвоение ЛЮБОГО заработка на 12 часов",     "boost_type": "all_mult",      "value": 2.0, "duration_hours": 12},
                "boost_review_x2":     {"name": "x2 к DC за отзывы (7 дней)",     "price": 320, "description": "Удвоение награды за отзывы на неделю",       "boost_type": "review_mult",   "value": 2.0, "duration_hours": 168},
                "boost_cooldown_half": {"name": "Кулдаун отзыва 60 сек (24ч)",    "price": 90,  "description": "Отзыв можно оставить через минуту вместо двух", "boost_type": "review_cd",  "value": 60,  "duration_hours": 24},
                "boost_daily_reset":   {"name": "Сброс дневного лимита",          "price": 60,  "description": "Мгновенно обнуляет счётчики сообщений/войса", "boost_type": "daily_reset", "value": 0,   "duration_hours": 0}
            }
        },
        "casino": {
            "label": "🎲 Казино-предметы",
            "description": "Усилители и бонусы для игр в казино",
            "items": {
                "casino_insurance":     {"name": "Страховка ставки",        "price": 90,  "description": "Возврат 50% при проигрыше",  "boost_type": "insurance",      "value": 0.5, "uses": 1},
                "casino_boost_x2":      {"name": "x2 к следующему выигрышу", "price": 280, "description": "Удвоение любой выплаты в 1 партии", "boost_type": "next_mult", "value": 2.0, "uses": 1},
                "casino_lucky_hour":    {"name": "Удачный час (60 мин)",    "price": 320, "description": "Все множители +20% на час",   "boost_type": "lucky_hour",     "value": 1.2, "duration_hours": 1},
                "casino_jackpot_ticket":{"name": "Билет в мега-джекпот",   "price": 400, "description": "Участвует в розыгрыше банка казино", "boost_type": "jackpot_ticket", "value": 0, "uses": 1}
            }
        },
        "gifts": {
            "label": "🎁 Подарки",
            "description": "Подарить Diamond Coins другому участнику",
            "items": {
                "gift_100":  {"name": "Подарить 100 DC",  "price": 105,  "description": "Отправка 100 DC другому юзеру (комиссия 5%)",  "gift_amount": 100},
                "gift_500":  {"name": "Подарить 500 DC",  "price": 525,  "description": "Отправка 500 DC другому юзеру (комиссия 5%)",  "gift_amount": 500},
                "gift_1000": {"name": "Подарить 1000 DC", "price": 1050, "description": "Отправка 1000 DC другому юзеру (комиссия 5%)", "gift_amount": 1000},
                "gift_2500": {"name": "Подарить 2500 DC", "price": 2625, "description": "Отправка 2500 DC другому юзеру (комиссия 5%)", "gift_amount": 2500},
                "gift_5000": {"name": "Подарить 5000 DC", "price": 5250, "description": "Отправка 5000 DC другому юзеру (комиссия 5%)", "gift_amount": 5000}
            }
        }
    }
    with open(CONFIG["SHOP_CATALOG_PATH"], "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    return catalog

# ============================================================
# Ежедневный бонус
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
        (float('inf'), "pka", "Покупатель века")
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
            "last_voice_dc": row["last_voice_dc"]
        }
    return data

def setup_dc(bot):
    pass
