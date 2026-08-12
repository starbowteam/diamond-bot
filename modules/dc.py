# -*- coding: utf-8 -*-
import os
import json
import time
import random
from datetime import datetime, timezone, timedelta, time as dt_time
from typing import Optional, Dict, Any, List
import disnake
from disnake.ext import commands, tasks
from disnake.ui import View, Button, Select, Modal, TextInput
from disnake import ButtonStyle, SelectOption

from core.utils import (
    CONFIG, FILES, BASE_DIR, DATA_DIR, CATALOG_DIR, ADD_DIR, ACTIONS_DIR,
    logger, db, cur,
    load_json, save_json, now_ts,
    log_discord, log_command,
    has_admin_command_roles,
    clean_embed_for_discohook,
    get_dc_cache, save_dc_cache, sync_dc_to_json,
    update_user_roles
)

# ============================================================
# Глобальная переменная для хранения текущей акции
# ============================================================
current_flash_item = None  # (cat_key, item_key, item_data, original_price, new_price)

def set_current_flash_item(cat_key, item_key, item_data, original_price, new_price):
    global current_flash_item
    current_flash_item = (cat_key, item_key, item_data, original_price, new_price)

def get_current_flash_item():
    return current_flash_item

# ============================================================
# DC DATA (работа с кешем)
# ============================================================
def get_user_dc_data(user_id: int) -> dict:
    data = get_dc_cache(user_id)
    return data

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

async def add_purchase(user_id: int, item_type: str, item_value: str):
    data = get_dc_cache(user_id)
    for p in data["purchases"]:
        if p["type"] == item_type and p["value"] == item_value and not p["used"]:
            return
    data["purchases"].append({
        "type": item_type,
        "value": item_value,
        "used": False,
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
            await add_dc(user_id, CONFIG["MESSAGE_RATE"], f"За {CONFIG['MESSAGE_BATCH']} сообщений в чате")
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
# Каталог магазина
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
                "3": {"name": "3% скидка", "price": 30, "description": "Скидка 3% на любой заказ"},
                "5": {"name": "5% скидка", "price": 60, "description": "Скидка 5% на любой заказ"},
                "7": {"name": "7% скидка", "price": 90, "description": "Скидка 7% на любой заказ"},
                "10": {"name": "10% скидка", "price": 140, "description": "Скидка 10% на любой заказ"},
                "15": {"name": "15% скидка", "price": 200, "description": "Скидка 15% на любой заказ"},
                "20": {"name": "20% скидка", "price": 300, "description": "Скидка 20% на любой заказ"}
            }
        },
        "design": {
            "label": "🎨 Дизайн от Diamond",
            "description": "Услуги дизайнера",
            "items": {
                "avatar": {"name": "Аватарка", "price": 40, "description": "Уникальная аватарка"},
                "banner": {"name": "Баннер", "price": 80, "description": "Баннер для профиля"},
                "logo": {"name": "Логотип", "price": 120, "description": "Логотип для бренда"},
                "cover": {"name": "Обложка для видео", "price": 100, "description": "Обложка для YouTube/стримов"},
                "header": {"name": "Шапка для сервера", "price": 150, "description": "Шапка для Discord-сервера"},
                "ticket_design": {"name": "Оформление тикета", "price": 180, "description": "Кастомное оформление тикета"},
                "stickers": {"name": "Стикер-пак", "price": 200, "description": "Набор стикеров"},
                "full_design": {"name": "Полный дизайн-пакет", "price": 350, "description": "Аватарка + баннер + логотип + оформление"}
            }
        },
        "ads": {
            "label": "📢 Реклама",
            "description": "Продвижение в соцсетях и сервере",
            "items": {
                "ad_post": {"name": "Пост в канале", "price": 60, "description": "Рекламный пост в канале"},
                "ad_pin": {"name": "Закреп на 24ч", "price": 80, "description": "Закреп сообщения на 24 часа"},
                "ad_news": {"name": "Упоминание в новостях", "price": 100, "description": "Упоминание в новостной ленте"},
                "ad_tg": {"name": "Реклама в ТГ-канале", "price": 150, "description": "Пост в Telegram-канале"},
                "ad_standard": {"name": "Рекламный пакет «Стандарт»", "price": 200, "description": "Пост + закреп на 24ч"},
                "ad_premium": {"name": "Рекламный пакет «Премиум»", "price": 350, "description": "Пост + закреп + упоминание в новостях"}
            }
        },
        "roles": {
            "label": "🎭 Особые роли",
            "description": "Временные и постоянные роли",
            "items": {
                "role_active": {"name": "Роль «Активный»", "price": 30, "description": "Постоянная роль «Активный»", "role_id": 1533140263789395998},
                "role_helper": {"name": "Роль «Помощник»", "price": 50, "description": "Роль «Помощник» (навсегда)", "role_id": 1536948551265812551},
                "role_vip": {"name": "VIP (30 дней)", "price": 80, "description": "VIP-роль на 30 дней", "role_id": 1533549996790513685},
                "role_mega": {"name": "Роль «Мега-активный»", "price": 120, "description": "Роль «Мега-активный»", "role_id": 1536948737514151976},
                "role_legend": {"name": "Роль «Легенда»", "price": 180, "description": "Легендарная роль", "role_id": 1535638212557541438},
                "role_newbie": {"name": "Роль «Новичок месяца»", "price": 20, "description": "Роль для новичков", "role_id": 1536948841394212934}
            }
        },
        "boosts": {
            "label": "⚡ Бусты",
            "description": "Ускорение процессов",
            "items": {
                "boost_ticket": {"name": "Приоритетный тикет", "price": 60, "description": "Приоритетная обработка тикета"},
                "boost_review": {"name": "Ускоренная проверка отзыва", "price": 40, "description": "Быстрая проверка отзыва"},
                "boost_discounts": {"name": "Ранний доступ к скидкам", "price": 30, "description": "Доступ к скидкам раньше других"}
            }
        },
        "packs": {
            "label": "🎁 Наборы",
            "description": "Комбо-паки со скидкой",
            "items": {
                "pack_start": {"name": "Стартовый набор", "price": 100, "description": "Скидка 5% + аватарка"},
                "pack_designer": {"name": "Набор дизайнера", "price": 180, "description": "Аватарка + баннер + логотип"},
                "pack_ad": {"name": "Набор рекламщика", "price": 200, "description": "Пост + закреп"},
                "pack_premium": {"name": "Премиум-набор", "price": 400, "description": "Скидка 10% + VIP-роль + баннер"}
            }
        },
        "custom": {
            "label": "👑 Кастом",
            "description": "Индивидуальные услуги",
            "items": {
                "custom_role": {"name": "Кастомная роль", "price": 50, "description": "Создание индивидуальной роли"},
                "custom_emoji": {"name": "Уникальный эмодзи", "price": 80, "description": "Создание эмодзи"},
                "custom_banner": {"name": "Персонализированный баннер", "price": 120, "description": "Баннер с вашим дизайном"},
                "custom_project": {"name": "Индивидуальный дизайн-проект", "price": 250, "description": "Полный проект под ключ"}
            }
        }
    }
    with open(CONFIG["SHOP_CATALOG_PATH"], "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    return catalog

# ============================================================
# Ежедневный бонус и комиссия
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

async def monthly_fee():
    rows = cur.execute("SELECT user_id, balance FROM dc_cache").fetchall()
    now = int(time.time())
    month = datetime.fromtimestamp(now).strftime("%Y-%m")
    for row in rows:
        uid = row["user_id"]
        balance = row["balance"]
        if balance > 500:
            fee = int(balance * 0.05)
            if fee > 50:
                fee = 50
            if fee > 0:
                data = get_dc_cache(uid)
                data["balance"] -= fee
                data["history"].append({
                    "date": now,
                    "amount": -fee,
                    "reason": f"Ежемесячная комиссия ({month})"
                })
                if len(data["history"]) > 50:
                    data["history"] = data["history"][-50:]
                save_dc_cache(uid, data)
                sync_dc_to_json()
                await log_discord(
                    title="💸 Ежемесячная комиссия",
                    description=f"> **Пользователь:** <@{uid}>\n> **Списано:** `{fee} DC`\n> **Причина:** хранение >500 DC",
                    color=0xff6600
                )

# ============================================================
# Топ-5 (обновление)
# ============================================================
async def update_top_embed():
    from core.bot import bot
    channel = bot.get_channel(CONFIG["TOP_CHANNEL_ID"])
    if not channel:
        logger.warning("TOP_CHANNEL_ID not found")
        return

    rows = cur.execute("SELECT user_id, balance FROM dc_cache ORDER BY balance DESC LIMIT 5").fetchall()
    fields = []
    emojis = ["🥇", "🥈", "🥉", "4.", "5."]
    for i, row in enumerate(rows):
        uid = row["user_id"]
        balance = row["balance"]
        member = channel.guild.get_member(uid)
        name = member.display_name if member else f"Пользователь {uid}"
        data = get_dc_cache(uid)
        purchases = data.get("purchases", [])
        unused = [p for p in purchases if not p.get("used", False)]
        if unused:
            items = ", ".join([f"{p['type']} {p['value']}" for p in unused[:3]])
            if len(unused) > 3:
                items += " и др."
        else:
            items = "Отсутствуют"
        field_name = f"> {emojis[i]} {name} - {balance} Diamond Coins"
        field_value = f"Купленные товары: {items}"
        fields.append((field_name, field_value, False))

    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1532277052227719188/image.png?ex=6a6c43b5&is=6a6af235&hm=f9d2c93ddc732cad6b06beacb3c57d17747abc84960dd67a17bfb5ac173103d0&")

    embed2 = disnake.Embed(
        title="Количественный топ сервера по Diamond Coins!",
        description="> Топ сервера, по количеству внутресерверной валюты, купленных товаров и многого другого, прозрачность - залог успеха.\n\n",
        color=6776679
    )
    embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1532256186026426408/pisk.png?ex=6a6c3046&is=6a6adec6&hm=03b0737541d747391eb599ff5e7e8d735456b1f51eda9fa1832c26cf4965eacd&")
    for field_name, field_value, inline in fields:
        embed2.add_field(name=field_name, value=field_value, inline=inline)

    async for msg in channel.history(limit=10):
        if msg.author == bot.user and msg.embeds:
            await msg.edit(embeds=[embed1, embed2])
            return

    await channel.send(embeds=[embed1, embed2])

# ============================================================
# Прогресс-бар для профиля
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



# ============================================================
# АКЦИИ (только по кнопке)
# ============================================================
def is_valid_for_flash(cat_key: str, item_key: str) -> bool:
    if cat_key == "discounts":
        allowed = ["3", "5", "7"]
        return item_key in allowed
    return True

async def send_flash_sale(manual: bool = True):
    from core.bot import bot
    channel = bot.get_channel(CONFIG["ACTIONS_CHANNEL_ID"])
    if not channel:
        logger.warning("Actions channel not found")
        return

    catalog = load_shop_catalog()
    items = []
    for cat_key, cat_data in catalog.items():
        for item_key, item_data in cat_data.get("items", {}).items():
            if is_valid_for_flash(cat_key, item_key):
                items.append((cat_key, item_key, item_data))

    if not items:
        return

    cat_key, item_key, item_data = random.choice(items)
    original_price = item_data["price"]
    new_price = max(1, original_price // 2)

    # Сохраняем в глобальную переменную
    set_current_flash_item(cat_key, item_key, item_data, original_price, new_price)

    category_label = catalog[cat_key]["label"]

    content = (
        f"@everyone, новая акция - товар \"{item_data['name']}\", "
        f"за {new_price} <:moneyPhotoroom:1531701289518628964> , "
        f"вместо {original_price} <:moneyPhotoroom:1531701289518628964>."
    )

    view = View(timeout=None)
    buy_btn = Button(
        label=f"Купить {item_data['name']} за {new_price} DC",
        style=ButtonStyle.success,
        custom_id=f"flash_buy_{cat_key}_{item_key}_{new_price}"
    )

    async def flash_buy_callback(inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        try:
            user_id = inter.author.id
            balance = await get_user_balance(user_id)
            if balance < new_price:
                return await inter.edit_original_message(content=f"❌ Недостаточно DC. Нужно: {new_price}, у вас: {balance}")

            success = await remove_dc(user_id, new_price, f"Покупка по акции: {item_data['name']}")
            if not success:
                return await inter.edit_original_message(content="❌ Ошибка списания DC.")

            if cat_key == "roles" and item_data.get("role_id"):
                role = inter.guild.get_role(item_data["role_id"])
                if role:
                    try:
                        await inter.author.add_roles(role)
                        await inter.edit_original_message(
                            content=f"✅ Вы купили **{item_data['name']}** по акции за **{new_price} DC**! Роль выдана. Не забудьте оставить отзыв в <#1462074763437543435>."
                        )
                        await log_discord(
                            title="🔥 Покупка по акции (роль)",
                            description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {item_data['name']}\n> **Цена:** {new_price} DC\n> **Категория:** {category_label}",
                            color=0xff6600
                        )
                        return
                    except Exception as e:
                        await inter.edit_original_message(content=f"❌ Не удалось выдать роль: {e}")
                        return

            await inter.edit_original_message(
                content=f"✅ Вы купили **{item_data['name']}** по акции за **{new_price} DC**! Товар будет выдан в ближайшее время. Не забудьте оставить отзыв в <#1462074763437543435>."
            )
            await log_discord(
                title="🔥 Покупка по акции",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {item_data['name']}\n> **Цена:** {new_price} DC\n> **Категория:** {category_label}",
                color=0xff6600
            )
        except Exception as e:
            logger.error(f"Ошибка в flash_buy_callback: {e}")
            await inter.edit_original_message(content=f"❌ Произошла ошибка: {e}")

    buy_btn.callback = flash_buy_callback
    view.add_item(buy_btn)

    await channel.send(content, view=view)
    await log_discord(
        title="🔥 Акция дня отправлена (ручной запуск)",
        description=f"> **Товар:** {item_data['name']}\n> **Цена:** {new_price} DC (было {original_price})",
        color=0xff6600
    )

# ============================================================
# Настройка модуля (для main.py)
# ============================================================
def setup_dc(bot):
    pass

# ============================================================
# Получение всех данных DC для статистики
# ============================================================
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