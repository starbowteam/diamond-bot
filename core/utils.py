# -*- coding: utf-8 -*-
import os
import sys
import json
import sqlite3
import logging
import functools
import time
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from PIL import Image, ImageDraw, ImageFont
import disnake
from disnake.ext import commands
from disnake import PartialEmoji, ButtonStyle

# ============================================================
# Базовая директория проекта
# ============================================================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADD_DIR = os.path.join(BASE_DIR, "add")
DATA_DIR = os.path.join(BASE_DIR, "data")
CATALOG_DIR = os.path.join(BASE_DIR, "catalog")
ACTIONS_DIR = os.path.join(BASE_DIR, "actions")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CATALOG_DIR, exist_ok=True)
os.makedirs(ADD_DIR, exist_ok=True)
os.makedirs(ACTIONS_DIR, exist_ok=True)

# ============================================================
# Конфигурация
# ============================================================
CONFIG = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN"),
    "ADMIN_COMMAND_ROLES": [1127428607606796294, 1471844291595731016],
    "REVIEW_MODERATION_ROLES": [1154757071330365490, 1513935883475226796, 1127428607606796294, 1471844291595731016],
    "TICKET_VIEW_ROLES": [1459249476236607498, 1154757071330365490, 1513935883475226796, 1471844291595731016, 1127428607606796294],
    "TICKET_MANAGE_ROLES": [1154757071330365490, 1513935883475226796, 1471844291595731016, 1127428607606796294],
    "LOG_CHANNEL_ID": 1462418981825810535,
    "LOG_CHANNEL_ID_PANEL": 1462418981825810535,
    "MODERATION_LOG_CHANNEL": 1531731027272269895,
    "DC_PANEL_CHANNEL": 1531731804828991611,
    "TOP_CHANNEL_ID": 1532278656519635104,
    "ACTIONS_CHANNEL_ID": 1469698608390606898,
    "ANALYTICS_CHANNEL_ID": 1536947571082403840,
    "MANAGER_ROLE_ID": 1127428607606796290,  # для пинга в акциях
    "EMBED_IMAGE_URL": "https://media.discordapp.net/attachments/1527006158282555412/1527007499192893561/image.png?ex=6a60584e&is=6a5f06ce&hm=1b0ba12a8c8d57f41c57bc03a6998178f6cfb6b83db5837d448d1ab495c46830&=&format=webp&quality=lossless&width=1766&height=686",
    "PANEL_CHANNEL_ID": 1462136361711829053,
    "TICKET_CATEGORY_ID": 1462419587835363614,
    "PAID_CATEGORY_ID": 1470779295650549885,
    "TARGET_REVIEWER_ID": 796293832751972352,
    "REVIEW_COUNT_CHANNEL": 1462074763437543435,
    "TICKET_COOLDOWN_SECONDS": 5,
    "INFO_TEMPLATE_PATH": os.path.join(ADD_DIR, "info-o-zakaze.json"),
    "PK_FILE_PATH": os.path.join(ADD_DIR, "pk.json"),
    "GUILD_ID": "1127428607606796288",
    "VOICE_CHANNEL_ID": 1464699044751478815,
    "MANAGER_ROLE_ID": 1154757071330365490,
    "PAID_NOTIFY_CHANNEL_ID": 1462418981825810535,
    "ROLE_IDS": {
        "club": 1284697274655576186,
        "bronze": 1127430321214861395,
        "silver": 1137721688683970643,
        "gold": 1184886111722545232,
        "diamond": 1195799151783461016,
        "emerald": 1208442450373513277,
        "amethyst": 1471005335111335957,
        "legendary": 1208442449425334372,
        "pka": 1208442176321626162
    },
    "DC_RECALC_IGNORE": [796293832751972352, 1168943921171288135],
    "FIXED_PKA_ROLE_ID": 1208442176321626162,
    "MAX_DAILY_MESSAGES": 20,
    "MAX_DAILY_VOICE": 15,
    "VOICE_RATE": 3,
    "MESSAGE_RATE": 1,
    "MESSAGE_BATCH": 10,
    "MIN_MESSAGE_LENGTH": 3,
    "SHOP_CATALOG_PATH": os.path.join(CATALOG_DIR, "shop_catalog.json"),
}

FILES = {
    "promo": os.path.join(DATA_DIR, "promo_codes.json"),
    "used_promo": os.path.join(DATA_DIR, "used_promo.json"),
    "promo_txt": os.path.join(DATA_DIR, "promo_codes.txt"),
    "rates": os.path.join(DATA_DIR, "rates.json"),
    "last_review_id": os.path.join(DATA_DIR, "last_review_id.json"),
    "review_counts": os.path.join(DATA_DIR, "review_counts.json"),
    "shop_json": os.path.join(CATALOG_DIR, "menu_coins_shop.json"),
    "dc_data": os.path.join(ADD_DIR, "dc_data.json"),
}

# ============================================================
# Logging
# ============================================================
LOG_FILE = os.path.join(BASE_DIR, "bot.log")
logger = logging.getLogger("dmshop")
logger.setLevel(logging.INFO)
fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
fh.setFormatter(fmt)
sh = logging.StreamHandler()
sh.setFormatter(fmt)
logger.addHandler(fh)
logger.addHandler(sh)

# ============================================================
# SQLite БД (основная)
# ============================================================
db = sqlite3.connect(os.path.join(DATA_DIR, "diamond.db"), check_same_thread=False, timeout=30)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA synchronous=NORMAL")

cur = db.cursor()

# Таблицы (инвайты, реакции, кеш DC)
cur.executescript("""
CREATE TABLE IF NOT EXISTS invites_snapshot (
    invite_code TEXT PRIMARY KEY,
    guild_id    INTEGER,
    uses        INTEGER,
    inviter_id  INTEGER
);
CREATE TABLE IF NOT EXISTS invites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER,
    inviter_id  INTEGER,
    member_id   INTEGER,
    joined_at   INTEGER,
    is_bot      INTEGER DEFAULT 0,
    is_fake     INTEGER DEFAULT 0,
    left_at     INTEGER DEFAULT NULL
);
CREATE TABLE IF NOT EXISTS reaction_roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER,
    channel_id  INTEGER,
    message_id  INTEGER,
    emoji       TEXT,
    role_id     INTEGER
);
CREATE TABLE IF NOT EXISTS dc_cache (
    user_id         INTEGER PRIMARY KEY,
    balance         INTEGER DEFAULT 0,
    purchases       TEXT,   -- JSON-строка
    history         TEXT,   -- JSON-строка
    last_review     INTEGER DEFAULT 0,
    last_bonus      INTEGER DEFAULT 0,
    messages_today  INTEGER DEFAULT 0,
    voice_time_today INTEGER DEFAULT 0,
    last_reset_date INTEGER DEFAULT 0,
    last_voice_dc   INTEGER DEFAULT 0
);
""")
db.commit()

# ============================================================
# Загрузка JSON (промо, курсы)
# ============================================================
def load_json(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error("Ошибка загрузки JSON %s: %s", path, e)
    return default

def save_json(path: str, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Ошибка сохранения JSON %s: %s", path, e)

# ============================================================
# Общие утилиты
# ============================================================
def now_ts():
    return int(datetime.now(timezone.utc).timestamp())

def parse_emoji(emoji_str: str):
    try:
        return disnake.PartialEmoji.from_str(emoji_str)
    except Exception:
        return emoji_str

def clean_embed_for_discohook(embed_dict: Dict[str, Any]) -> Dict[str, Any]:
    e = dict(embed_dict)
    if "image" in e and isinstance(e["image"], dict) and "url" in e["image"]:
        e["image"] = {"url": e["image"]["url"]}
    return e

# ============================================================
# Проверки ролей
# ============================================================
def has_admin_command_roles(author):
    return any(r.id in CONFIG["ADMIN_COMMAND_ROLES"] for r in author.roles)

def has_review_moderation_roles(author):
    return any(r.id in CONFIG["REVIEW_MODERATION_ROLES"] for r in author.roles)

def has_ticket_view_roles(author):
    return any(r.id in CONFIG["TICKET_VIEW_ROLES"] for r in author.roles)

def has_ticket_manage_roles(author):
    return any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in author.roles)

# ============================================================
# Логирование в Discord
# ============================================================
async def log_discord(title: str, description: str, color: int = 0x00ff00, panel: bool = False, fields: list = None):
    try:
        from core.bot import bot  # импорт внутри для избежания циклической зависимости
    except ImportError:
        return
    try:
        ch_id = CONFIG["LOG_CHANNEL_ID_PANEL"] if panel else CONFIG["LOG_CHANNEL_ID"]
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild:
            logger.warning("log_discord: guild not found")
            return
        log_ch = guild.get_channel(ch_id)
        if not log_ch:
            logger.warning("log_discord: channel %s not found", ch_id)
            return
        embed = disnake.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        if fields:
            for name, value, inline in fields:
                embed.add_field(name=name, value=value, inline=inline)
        await log_ch.send(embed=embed)
    except Exception as e:
        logger.exception("Ошибка логирования в Discord: %s", e)

# ============================================================
# Декоратор для логов команд
# ============================================================
def log_command(func):
    @functools.wraps(func)
    async def wrapper(ctx, *args, **kwargs):
        if not has_admin_command_roles(ctx.author):
            await ctx.send("⛔ У вас нет прав на использование этой команды.", ephemeral=True)
            return
        try:
            from core.bot import bot
            guild = ctx.guild or bot.get_guild(int(CONFIG["GUILD_ID"]))
            if guild:
                log_ch = guild.get_channel(CONFIG["LOG_CHANNEL_ID_PANEL"])
                if log_ch:
                    embed = disnake.Embed(
                        title="🔧 Использована команда",
                        description=f"> **Команда:** `{func.__name__}`\n> **Пользователь:** {ctx.author} (`{ctx.author.id}`)\n> **Канал:** {getattr(ctx.channel, 'mention', 'dm')}",
                        timestamp=datetime.now(timezone.utc),
                        color=0x2f3136
                    )
                    await log_ch.send(embed=embed)
        except Exception as e:
            logger.exception("Ошибка в log_command: %s", e)
        try:
            return await func(ctx, *args, **kwargs)
        except Exception as e:
            logger.exception("Ошибка выполнения команды %s: %s", func.__name__, e)
            try:
                await ctx.send("Произошла ошибка при выполнении команды.", ephemeral=True)
            except Exception:
                pass
    return wrapper

# ============================================================
# Система ролей по отзывам
# ============================================================
def get_roles_for_count(count: int) -> list[int]:
    roles = []
    role_ids = CONFIG["ROLE_IDS"]
    if count >= 1:
        roles.append(role_ids["club"])
    if 1 <= count <= 2:
        roles.append(role_ids["bronze"])
    elif 3 <= count <= 4:
        roles.append(role_ids["silver"])
    elif 5 <= count <= 8:
        roles.append(role_ids["gold"])
    elif 9 <= count <= 12:
        roles.append(role_ids["diamond"])
    elif 13 <= count <= 17:
        roles.append(role_ids["emerald"])
    elif 18 <= count <= 23:
        roles.append(role_ids["amethyst"])
    elif 24 <= count <= 25:
        roles.append(role_ids["legendary"])
    elif count >= 26:
        roles.append(role_ids["pka"])
    return roles

async def update_user_roles(member: disnake.Member, count: int, keep_pka: bool = False):
    role_ids = CONFIG["ROLE_IDS"]
    all_buyer_roles = list(role_ids.values())
    target_role_ids = get_roles_for_count(count)
    current_role_ids = [r.id for r in member.roles]
    to_remove = [rid for rid in all_buyer_roles if rid in current_role_ids and rid not in target_role_ids]
    if keep_pka and CONFIG["FIXED_PKA_ROLE_ID"] in to_remove:
        to_remove.remove(CONFIG["FIXED_PKA_ROLE_ID"])
    to_add = [rid for rid in target_role_ids if rid not in current_role_ids]
    guild = member.guild
    for rid in to_remove:
        role = guild.get_role(rid)
        if role:
            await member.remove_roles(role)
            logger.info(f"Снята роль {role.name} у {member} (отзывов: {count})")
            await log_discord(
                title="🔄 Снята роль покупателя",
                description=f"> **Пользователь:** {member.mention}\n> **Роль:** {role.mention}\n> **Отзывов:** `{count}`",
                color=0xff6600
            )
    for rid in to_add:
        role = guild.get_role(rid)
        if role:
            await member.add_roles(role)
            logger.info(f"Выдана роль {role.name} пользователю {member} (отзывов: {count})")
            await log_discord(
                title="🔄 Выдана роль покупателя",
                description=f"> **Пользователь:** {member.mention}\n> **Роль:** {role.mention}\n> **Отзывов:** `{count}`",
                color=0x00ff00
            )

# ============================================================
# Функции для работы с инвайтами
# ============================================================
async def sync_invites(guild: disnake.Guild):
    try:
        invites = await guild.invites()
    except Exception:
        return
    for inv in invites:
        cur.execute("REPLACE INTO invites_snapshot (invite_code, guild_id, uses, inviter_id) VALUES (?, ?, ?, ?)",
                    (inv.code, guild.id, inv.uses, inv.inviter.id if inv.inviter else None))
    db.commit()

# ============================================================
# Промокоды и курсы (загружаются при старте)
# ============================================================
promo_codes: Dict[str, str] = {}
used_promo: Dict[str, list] = {}
rates: Dict[str, float] = {}

def reload_promo():
    global promo_codes, used_promo, rates
    promo_codes = load_json(FILES["promo"], {})
    used_promo = load_json(FILES["used_promo"], {})
    rates = load_json(FILES["rates"], {"KZT": 0.14, "UAH": 1.8, "RUB": 1.0, "ROBLOX_RATE": 0.65})
    try:
        lines = [f"{k} - {v}" for k, v in promo_codes.items()]
        with open(FILES["promo_txt"], "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        logger.exception("reload_promo: write promo_txt error: %s", e)

reload_promo()

# ============================================================
# Кеширование DC в SQLite
# ============================================================
def init_dc_cache_from_json():
    """Загружает DC данные из JSON в SQLite (при первом запуске или синхронизации)."""
    data = load_json(FILES["dc_data"], {})
    for uid_str, user_data in data.items():
        uid = int(uid_str)
        cur.execute("""
            INSERT OR REPLACE INTO dc_cache (
                user_id, balance, purchases, history,
                last_review, last_bonus, messages_today,
                voice_time_today, last_reset_date, last_voice_dc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            uid,
            user_data.get("balance", 0),
            json.dumps(user_data.get("purchases", [])),
            json.dumps(user_data.get("history", [])),
            user_data.get("last_review", 0),
            user_data.get("last_bonus", 0),
            user_data.get("messages_today", 0),
            user_data.get("voice_time_today", 0),
            user_data.get("last_reset_date", 0),
            user_data.get("last_voice_dc", 0)
        ))
    db.commit()

def get_dc_cache(user_id: int) -> dict:
    row = cur.execute("SELECT * FROM dc_cache WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        return {
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
    return {
        "balance": 0,
        "purchases": [],
        "history": [],
        "last_review": 0,
        "last_bonus": 0,
        "messages_today": 0,
        "voice_time_today": 0,
        "last_reset_date": 0,
        "last_voice_dc": 0
    }

def save_dc_cache(user_id: int, data: dict):
    cur.execute("""
        INSERT OR REPLACE INTO dc_cache (
            user_id, balance, purchases, history,
            last_review, last_bonus, messages_today,
            voice_time_today, last_reset_date, last_voice_dc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        data.get("balance", 0),
        json.dumps(data.get("purchases", [])),
        json.dumps(data.get("history", [])),
        data.get("last_review", 0),
        data.get("last_bonus", 0),
        data.get("messages_today", 0),
        data.get("voice_time_today", 0),
        data.get("last_reset_date", 0),
        data.get("last_voice_dc", 0)
    ))
    db.commit()

def sync_dc_to_json():
    """Синхронизирует все данные из SQLite обратно в JSON (для безопасности)."""
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
    save_json(FILES["dc_data"], data)

# При первом запуске инициализируем кеш, если таблица пуста
if cur.execute("SELECT COUNT(*) FROM dc_cache").fetchone()[0] == 0:
    init_dc_cache_from_json()