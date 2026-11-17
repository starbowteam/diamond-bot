# -*- coding: utf-8 -*-
import os
import re
import json
import time
import math
import asyncio
import logging
import glob
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

import aiohttp
import disnake
from disnake import ui, ButtonStyle, TextInputStyle
from disnake.ui import Modal, TextInput
from disnake.ext import commands, tasks

from core.utils import (
    CONFIG, DATA_DIR, CATALOG_DIR, logger, db, cur,
    load_json, save_json, now_ts, get_dc_cache,
    get_ticket_owner,
)
from core.catalog import load_catalog_from_db, auto_init
from modules.tickets import ReceiptView, generate_receipt_png, generate_receipt_id
from modules.commands_tickets import (
    CustomRoleSetupView, get_user_purchases, remove_purchase
)

# ============================================================
# КОНСТАНТЫ
# ============================================================
AI_MANAGER_TOKEN = os.getenv("AI_MANAGER_TOKEN")
AI_MANAGER_API_KEY = os.getenv("AI_MANAGER_API_KEY")
AI_MANAGER_BASE_URL = os.getenv("AI_MANAGER_BASE_URL", "https://api.zveno.ai/v1").rstrip("/")

DIAMOND_AI_MODEL = os.getenv("AI_MANAGER_MODEL", "google/gemini-3-flash-preview")
LAST_RESORT_MODEL = os.getenv("AI_MANAGER_LAST_RESORT_MODEL", "qwen/qwen-2.5-72b-instruct")

# Zveno model names can change by catalog. Override with AI_MANAGER_MODELS.
DEFAULT_AI_MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "google/gemini-2.5-flash-lite-preview-09-2025:free",
    "qwen/qwen3-4b:free",
    "meta-llama/llama-3.3-8b-instruct:free",
    DIAMOND_AI_MODEL,
    LAST_RESORT_MODEL,
]
AI_MODELS = list(dict.fromkeys(
    x.strip() for x in os.getenv("AI_MANAGER_MODELS", ",".join(DEFAULT_AI_MODELS)).split(",") if x.strip()
))
VISION_MODELS = list(dict.fromkeys(
    x.strip() for x in os.getenv(
        "AI_MANAGER_VISION_MODELS",
        ",".join(["google/gemini-2.0-flash-exp:free", "google/gemini-2.5-flash-lite-preview-09-2025:free", DIAMOND_AI_MODEL, LAST_RESORT_MODEL])
    ).split(",") if x.strip()
))

LLM_TIMEOUT = 30
ABUSE_TIMEOUT = 10

SELLER_ROLE = 1471844291595731016
OWNER_IDS = [796293832751972352, 1168943921171288135]
ANALYTICS_USER_ID = 796293832751972352
LOG_CHANNEL = 1530453871581855744

SESSION_MAX_MESSAGES = 20
SESSION_MAX_FAILS = 3
DEBOUNCE_SEC = 2.0
HISTORY_TTL_SEC = 20 * 60
HISTORY_MAX_MSG = 10

MANAGER_SILENCE_SEC = 300
FALLBACK_WAIT_SEC = 300
CLIENT_MAX_SILENCE_SEC = 600

ABUSE_COOLDOWN_SEC = 120
SPAM_WINDOW_SEC = 60
SPAM_SHORT_COUNT = 5

COLOR_GREY = 0x676767
COLOR_GREEN = 0x2ecc71
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aeaabe3&is=6ae95a63&hm=9f64fd7deb75b088ad88aec985099620a358aa0dde41e94db426b5a0d8b4fa36&"

YES_EMOJI = "<:Yes:1540361827295170722>"

ADS_CATEGORY_ID = 1568673531900727407
ADS_CHANNEL_ID = 1553694881564590143

CHANNEL_LOCKS = {}
def get_lock(channel_id: int) -> asyncio.Lock:
    if channel_id not in CHANNEL_LOCKS:
        CHANNEL_LOCKS[channel_id] = asyncio.Lock()
    return CHANNEL_LOCKS[channel_id]

ABUSE_WORDS = [
    "хуй", "хуя", "хуе", "хуи", "пизд", "бляд", "блят", "ебан", "ебал", "ебат",
    "сука", "суки", "нахуй", "нахер", "заткнись", "тупой", "тупая", "идиот",
    "дебил", "дебилы", "мразь", "гандо", "пидо", "педик", "долбоеб", "мудак",
]

# ============================================================
# ЛОГГЕР
# ============================================================
ai_logger = logging.getLogger("ai_manager")
ai_logger.setLevel(logging.INFO)
if not ai_logger.handlers:
    fh = logging.FileHandler("ai_manager.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    ai_logger.addHandler(fh)
    ai_logger.addHandler(sh)

async def log_discord(title: str, description: str, color: int = 0x00ff00, channel_id: int = None):
    try:
        ch_id = channel_id or LOG_CHANNEL
        ch = bot.get_channel(ch_id)
        if not ch:
            ch = await bot.fetch_channel(ch_id)
        if not ch: return
        embed = disnake.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
        await ch.send(embed=embed)
    except Exception as e:
        ai_logger.warning(f"log_discord: {e}")

# ============================================================
# ПАРСЕР РЕАЛЬНОГО КАТАЛОГА
# ============================================================
def build_real_catalog_text():
    files = glob.glob(os.path.join(CATALOG_DIR, "menu_*.json"))
    lines = []
    for f in files:
        if "shop_catalog" in f: 
            continue
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            for e in data.get("embeds", []):
                title = e.get("title", "")
                if title: 
                    lines.append(f"\n--- {title} ---")
                for field in e.get("fields", []):
                    name = field.get("name", "").replace("*", "").replace(">", "").strip()
                    value = field.get("value", "").replace("`", "").strip()
                    if name and value:
                        lines.append(f"  • {name} [НАША ЦЕНА: {value}]")
        except Exception:
            pass
    return "\n".join(lines)

# ============================================================
# БД И МИГРАЦИИ
# ============================================================
def init_ai_manager_tables():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS ai_manager_sessions (
        channel_id INTEGER PRIMARY KEY, user_id INTEGER, message_count INTEGER DEFAULT 0,
        fail_count INTEGER DEFAULT 0, started_at INTEGER, escalated INTEGER DEFAULT 0,
        receipt_url TEXT, created_at INTEGER, stub_sent INTEGER DEFAULT 0,
        invoice_sent INTEGER DEFAULT 0, last_client_msg_ts INTEGER DEFAULT 0,
        last_manager_msg_ts INTEGER DEFAULT 0, last_ai_response_ts INTEGER DEFAULT 0,
        last_abuse_check_ts INTEGER DEFAULT 0, abuse_closed INTEGER DEFAULT 0,
        post_invoice_text_count INTEGER DEFAULT 0,
        abandoned_notified INTEGER DEFAULT 0, close_requested_at INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS ai_manager_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER NOT NULL,
        role TEXT NOT NULL, content TEXT NOT NULL, created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ai_hist_channel ON ai_manager_history(channel_id, id);
    CREATE TABLE IF NOT EXISTS ai_manager_user_prefs (user_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 1);
    
    CREATE TABLE IF NOT EXISTS active_ads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        channel_id INTEGER,
        message_id INTEGER,
        is_personal INTEGER DEFAULT 0,
        expires_at INTEGER
    );
    
    CREATE TABLE IF NOT EXISTS ai_escalations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        channel_id INTEGER,
        question TEXT,
        reason TEXT,
        created_at INTEGER
    );

    CREATE TABLE IF NOT EXISTS ai_manager_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id INTEGER,
        user_id INTEGER,
        event_type TEXT NOT NULL,
        payload TEXT,
        model TEXT,
        latency_ms INTEGER,
        success INTEGER DEFAULT 1,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ai_events_channel ON ai_manager_events(channel_id, id);
    """)
    db.commit()
    
    _ensure_col("ai_manager_sessions", "stub_sent", "stub_sent INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "invoice_sent", "invoice_sent INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "last_client_msg_ts", "last_client_msg_ts INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "last_manager_msg_ts", "last_manager_msg_ts INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "last_ai_response_ts", "last_ai_response_ts INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "last_abuse_check_ts", "last_abuse_check_ts INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "abuse_closed", "abuse_closed INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "post_invoice_text_count", "post_invoice_text_count INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "abandoned_notified", "abandoned_notified INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "close_requested_at", "close_requested_at INTEGER DEFAULT 0")

def _ensure_col(table: str, column: str, ddl: str):
    try:
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()]
        if column not in cols:
            cur.execute(f'ALTER TABLE "{table}" ADD COLUMN {ddl}')
            db.commit()
    except Exception as e:
        ai_logger.warning(f"Миграция {table}.{column}: {e}")

init_ai_manager_tables()

def log_ai_event(event_type: str, channel_id: int = 0, user_id: int = 0,
                 payload: Optional[dict] = None, model: str = "",
                 latency_ms: int = 0, success: bool = True):
    try:
        cur.execute(
            "INSERT INTO ai_manager_events "
            "(channel_id, user_id, event_type, payload, model, latency_ms, success, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (channel_id, user_id, event_type, json.dumps(payload or {}, ensure_ascii=False)[:4000],
             model[:200], int(latency_ms), 1 if success else 0, 1 if success else 0, int(time.time()))
        )
        db.commit()
    except Exception as e:
        ai_logger.debug(f"log_ai_event: {e}")


def _extract_confidence(text: str) -> Tuple[str, Optional[int]]:
    if not text:
        return text, None
    match = re.search(r"<confidence>\s*(\d{1,3})\s*</confidence>", text, re.I)
    if not match:
        return text, 0
    score = max(0, min(100, int(match.group(1))))
    cleaned = re.sub(r"\s*<confidence>.*?</confidence>\s*", "", text, flags=re.I | re.S).strip()
    return cleaned, score


async def notify_low_confidence(channel, user_id: int, answer: str, score: int):
    if score >= 70:
        return
    try:
        user = bot.get_user(ANALYTICS_USER_ID) or await bot.fetch_user(ANALYTICS_USER_ID)
        if user:
            await user.send(
                f"⚠️ Низкая уверенность AI: **{score}%**\n"
                f"Канал: <#{channel.id}>\nПользователь: {user_id}\n"
                f"Ответ: {answer[:1700]}"
            )
    except Exception as e:
        ai_logger.warning(f"notify_low_confidence: {e}")


# ============================================================
# СИСТЕМА РЕКЛАМЫ
# ============================================================
def build_ad_embed(item_name: str) -> disnake.Embed:
    embed = disnake.Embed(
        title=f"📢 Оформление рекламы: {item_name}",
        description=(
            "> Нажмите на кнопку ниже, чтобы заполнить бриф.\n"
            "> Укажите заголовок, текст и при желании добавьте картинку.\n"
            "> После отправки вы сможете проверить предпросмотр."
        ),
        color=0x2b2d31
    )
    embed.set_image(url=IMG_STRIPE)
    return embed

class AdStartView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="📝 Заполнить бриф", style=ButtonStyle.secondary, custom_id="ad_start_btn")
    async def start(self, button, inter: disnake.MessageInteraction):
        item_name = "Реклама"
        if inter.message.embeds:
            embed_title = inter.message.embeds[0].title or ""
            if ":" in embed_title:
                item_name = embed_title.split(":", 1)[1].strip()
            else:
                desc = inter.message.embeds[0].description or ""
                match = re.search(r"Вы приобрели:\s*\*\*(.+?)\*\*", desc)
                if match:
                    item_name = match.group(1)
        
        old_title, old_text, old_image = "", "", ""
        async for msg in inter.channel.history(limit=20):
            if msg.author == bot.user and msg.components and any(c.custom_id == "ad_pub_confirm" for row in msg.components for c in row.children):
                if msg.embeds:
                    old_title = msg.embeds[0].title or ""
                    old_text = msg.embeds[0].description or ""
                    if msg.embeds[0].image and msg.embeds[0].image.url:
                        old_image = msg.embeds[0].image.url
                break

        await inter.response.send_modal(AdTextViewModal(item_name=item_name, title=old_title, text=old_text, image=old_image))

class AdTextViewModal(Modal):
    def __init__(self, item_name: str, title: str = "", text: str = "", image: str = ""):
        self.item_name = item_name
        super().__init__(title="Бриф рекламы", components=[
            TextInput(label="Заголовок рекламы (жирный)", placeholder="Например: Мой крутой сервер", custom_id="ad_title", min_length=2, max_length=256, value=title[:256]),
            TextInput(label="Текст рекламы", placeholder="Опишите проект, добавьте ссылки.", style=TextInputStyle.paragraph, custom_id="ad_text", min_length=5, max_length=2000, value=text[:2000]),
            TextInput(label="Ссылка на картинку (необязательно)", placeholder="https://...", custom_id="ad_image", required=False, max_length=512, value=image[:512])
        ])

    async def callback(self, inter: disnake.ModalInteraction):
        title = inter.text_values["ad_title"]
        text = inter.text_values["ad_text"]
        image = inter.text_values.get("ad_image", "").strip()

        try:
            async for msg in inter.channel.history(limit=20):
                if msg.author == bot.user and msg.components and any(c.custom_id == "ad_pub_confirm" for row in msg.components for c in row.children):
                    await msg.delete()
        except Exception:
            pass

        ping = ""
        if "@everyone" in self.item_name: ping = "@everyone"
        elif "@here" in self.item_name: ping = "@here"
        
        is_personal = "Личный канал" in self.item_name
        is_24h = "24ч" in self.item_name
        
        if is_personal:
            embed = disnake.Embed(
                title="Шаг 2: Название канала",
                description="Бриф принят! Нажмите на кнопку ниже, чтобы ввести название для вашего личного канала.",
                color=0x2b2d31
            )
            view = AdChannelNameView(self.item_name, title, text, image, ping)
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            embed = disnake.Embed(title=f"**{title}**", description=text, color=0x2b2d31)
            if image: 
                try: embed.set_image(url=image)
                except: pass
            
            view = AdPreviewView(self.item_name, title, text, image, ping, is_24h)
            await inter.channel.send(content=f"> **Предпросмотр рекламы:**\n{ping}", embed=embed, view=view)
            await inter.response.send_message("✅ Предпросмотр отправлен. Если что-то не так — измените бриф.", ephemeral=True)

class AdPreviewView(ui.View):
    def __init__(self, item_name, title, text, image, ping, is_24h):
        super().__init__(timeout=None)
        self.item_name = item_name
        self.title = title
        self.text = text
        self.image = image
        self.ping = ping
        self.is_24h = is_24h

    @ui.button(label="✅ Опубликовать", style=ButtonStyle.secondary, custom_id="ad_pub_confirm")
    async def publish(self, button, inter: disnake.MessageInteraction):
        for child in self.children: child.disabled = True
        try: await inter.message.edit(view=self)
        except: pass

        await inter.response.defer(ephemeral=True)
        
        guild = inter.guild
        ad_channel = guild.get_channel(ADS_CHANNEL_ID)
        if not ad_channel: 
            return await inter.followup.send("❌ Канал для рекламы не найден.", ephemeral=True)

        embed = disnake.Embed(title=f"**{self.title}**", description=self.text, color=0x2b2d31)
        if self.image:
            try: embed.set_image(url=self.image)
            except: pass
            
        try:
            msg = await ad_channel.send(content=self.ping, embed=embed)
        except Exception as e:
            return await inter.followup.send(f"❌ Ошибка публикации: {e}", ephemeral=True)
        
        expires = int(time.time()) + (24 * 3600) if self.is_24h else 0
        cur.execute("INSERT INTO active_ads (user_id, channel_id, message_id, is_personal, expires_at) VALUES (?, ?, ?, ?, ?)", (inter.author.id, ad_channel.id, msg.id, 0, expires))
        db.commit()

        success_embed = disnake.Embed(
            title="✅ Реклама успешно опубликована!",
            description=f"Ваш пост отправлен в канал: {ad_channel.mention}\n> **Срок размещения:** {'24 часа' if self.is_24h else 'Навсегда'}.\n> Ссылка: [Клик]({msg.jump_url})",
            color=0x2b2d31
        )
        success_embed.set_image(url=IMG_STRIPE)
        await inter.channel.send(embed=success_embed)

        try: await inter.message.delete()
        except: pass

class AdChannelNameView(ui.View):
    def __init__(self, item_name, title, text, image, ping):
        super().__init__(timeout=300)
        self.item_name = item_name
        self.title = title
        self.text = text
        self.image = image
        self.ping = ping

    @ui.button(label="📝 Ввести название канала", style=ButtonStyle.secondary, custom_id="ad_chan_name_btn")
    async def enter_name(self, button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(AdChannelNameModal(self.item_name, self.title, self.text, self.image, self.ping))

class AdChannelNameModal(Modal):
    def __init__(self, item_name, title, text, image, ping):
        self.item_name = item_name
        self.title = title
        self.text = text
        self.image = image
        self.ping = ping
        super().__init__(title="Название личного канала", components=[
            TextInput(label="Введите название канала", placeholder="Например: реклама-моего-сервера", custom_id="chan_name", min_length=2, max_length=90)
        ])

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        
        raw_name = inter.text_values["chan_name"].lower().replace(" ", "-")
        clean_name = re.sub(r"[^a-zа-яё0-9\-_]", "", raw_name)
        channel_name = f"├┃📚・{clean_name}"[:100] 
        
        if not clean_name: channel_name = f"├┃📚・ad-{inter.author.id}"
        
        guild = inter.guild
        category = guild.get_channel(ADS_CATEGORY_ID)
        if not category: 
            return await inter.followup.send("❌ Категория не найдена.", ephemeral=True)

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(read_messages=True, send_messages=False),
            guild.me: disnake.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        try:
            new_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites)
        except Exception as e:
            return await inter.followup.send(f"❌ Ошибка создания: {e}", ephemeral=True)
        
        embed = disnake.Embed(title=f"**{self.title}**", description=self.text, color=0x2b2d31)
        if self.image:
            try: embed.set_image(url=self.image)
            except: pass
            
        msg = await new_channel.send(content=self.ping, embed=embed)
        
        expires = int(time.time()) + (7 * 24 * 3600)
        cur.execute("INSERT INTO active_ads (user_id, channel_id, message_id, is_personal, expires_at) VALUES (?, ?, ?, ?, ?)", (inter.author.id, new_channel.id, msg.id, 1, expires))
        db.commit()

        success_embed = disnake.Embed(
            title="✅ Реклама успешно опубликована!",
            description=f"Ваш личный канал создан: {new_channel.mention}\n> **Срок размещения:** 1 неделя.\n> После этого канал будет автоматически удален.",
            color=0x2b2d31
        )
        success_embed.set_image(url=IMG_STRIPE)
        
        await inter.channel.send(embed=success_embed)

        try:
            async for msg_hist in inter.channel.history(limit=15):
                if msg_hist.author.bot and msg_hist.embeds and msg_hist.embeds[0].title and "Оформление рекламы" in msg_hist.embeds[0].title:
                    await msg_hist.delete()
                    break
        except Exception:
            pass

        await inter.edit_original_response(content="Канал создан.")

# ============================================================
# ФУНКЦИИ РАБОТЫ С СЕССИЯМИ
# ============================================================
def get_session(channel_id: int) -> Optional[dict]:
    row = cur.execute("SELECT * FROM ai_manager_sessions WHERE channel_id=?", (channel_id,)).fetchone()
    return dict(row) if row else None

def create_session(channel_id: int, user_id: int):
    now = int(time.time())
    cur.execute(
        "INSERT OR IGNORE INTO ai_manager_sessions (channel_id, user_id, message_count, fail_count, started_at, escalated, receipt_url, created_at, stub_sent, invoice_sent, last_client_msg_ts, last_manager_msg_ts, last_ai_response_ts, post_invoice_text_count, abandoned_notified, close_requested_at) VALUES (?, ?, 0, 0, ?, 0, '', ?, 0, 0, 0, 0, 0, 0, 0, 0)",
        (channel_id, user_id, now, now),
    )
    db.commit()

def update_session(channel_id: int, **kwargs):
    if not kwargs: return
    fields = ", ".join(f"{k}=?" for k in kwargs.keys())
    values = list(kwargs.values()) + [channel_id]
    cur.execute(f"UPDATE ai_manager_sessions SET {fields} WHERE channel_id=?", values)
    db.commit()

def touch_client_msg(channel_id: int, user_id: int):
    sess = get_session(channel_id)
    if not sess: create_session(channel_id, user_id)
    update_session(channel_id, last_client_msg_ts=int(time.time()))

def touch_manager_msg(channel_id: int):
    sess = get_session(channel_id)
    if not sess: return
    update_session(channel_id, last_manager_msg_ts=int(time.time()))

def touch_ai_response(channel_id: int):
    update_session(channel_id, last_ai_response_ts=int(time.time()))

def is_ai_muted(channel_id: int) -> bool:
    sess = get_session(channel_id)
    if not sess: return False
    lmt = sess.get("last_manager_msg_ts") or 0
    if not lmt: return False
    return (int(time.time()) - lmt) < MANAGER_SILENCE_SEC

def hist_load(channel_id: int, ttl_sec: int = HISTORY_TTL_SEC, limit: int = HISTORY_MAX_MSG):
    cutoff = int(time.time()) - ttl_sec
    rows = cur.execute("SELECT role, content, created_at FROM ai_manager_history WHERE channel_id=? AND created_at >= ? ORDER BY id DESC LIMIT ?", (channel_id, cutoff, limit)).fetchall()
    return [(r["role"], r["content"]) for r in reversed(rows)]

def hist_append(channel_id: int, role: str, content: str):
    if not content: return
    cur.execute("INSERT INTO ai_manager_history (channel_id, role, content, created_at) VALUES (?,?,?,?)", (channel_id, role, content[:2000], int(time.time())))
    db.commit()

def hist_clear(channel_id: int):
    cur.execute("DELETE FROM ai_manager_history WHERE channel_id=?", (channel_id,))
    db.commit()

def hist_last_client_msg(channel_id: int) -> Optional[str]:
    row = cur.execute("SELECT content FROM ai_manager_history WHERE channel_id=? AND role='user' ORDER BY id DESC LIMIT 1", (channel_id,)).fetchone()
    return row["content"] if row else None

def hist_recent_user(channel_id: int, window_sec: int = SPAM_WINDOW_SEC, limit: int = 10) -> List[str]:
    cutoff = int(time.time()) - window_sec
    rows = cur.execute("SELECT content FROM ai_manager_history WHERE channel_id=? AND role='user' AND created_at > ? ORDER BY id DESC LIMIT ?", (channel_id, cutoff, limit)).fetchall()
    return [r["content"] for r in rows]

DEBOUNCE: Dict[int, dict] = {}

async def _debounce_flush(channel, user, gen: int, delay: float = DEBOUNCE_SEC):
    try:
        await asyncio.sleep(delay)
        state = DEBOUNCE.get(channel.id)
        if not state or state.get("gen") != gen: return
        msgs = state.get("messages", [])
        image_urls = state.get("images", [])
        DEBOUNCE.pop(channel.id, None)
        combined = "\n".join(m if isinstance(m, str) else str(m) for m in msgs if m).strip()
        if not combined and not image_urls: return
        await _handle_dialog(channel, user, combined, image_urls=image_urls)
    except asyncio.CancelledError: raise
    except Exception: ai_logger.exception("debounce_flush")

def is_potential_abuse(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in ABUSE_WORDS)

async def check_abuse_llm(messages: List[str]) -> Tuple[bool, str]:
    if not AI_MANAGER_API_KEY: return False, ""
    sample = "\n".join(f"- {m[:200]}" for m in messages[:5])
    prompt = f"Проанализируй последние сообщения клиента:\n{sample}\n\nОтветь РОВНО ОДНИМ словом:\n- ABUSE — мат, оскорбления\n- SPAM — флуд\n- NORMAL — нормальный клиент\n"
    payload = {"model": DIAMOND_AI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 10}
    url = f"{AI_MANAGER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {AI_MANAGER_API_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=ABUSE_TIMEOUT)) as resp:
                if resp.status != 200: return False, ""
                data = await resp.json()
                choices = data.get("choices", [])
                if not choices: return False, ""
                text = (choices[0].get("message", {}).get("content") or "").strip().upper()
                text = re.sub(r"[^A-Z]", "", text)
                if "ABUSE" in text: return True, "abuse"
                if "SPAM" in text: return True, "spam"
                return False, ""
    except Exception as e:
        ai_logger.warning(f"check_abuse_llm: {e}")
        return False, ""

async def _check_and_close_abuse(channel, user_id: int) -> bool:
    sess = get_session(channel.id)
    if not sess or sess.get("abuse_closed"): return False
    last_check = sess.get("last_abuse_check_ts") or 0
    now = int(time.time())
    if now - last_check < ABUSE_COOLDOWN_SEC: return False
    texts = hist_recent_user(channel.id, window_sec=SPAM_WINDOW_SEC, limit=10)
    if not texts: return False
    has_abuse_word = any(is_potential_abuse(t) for t in texts)
    many_short = (len(texts) >= SPAM_SHORT_COUNT and all(len(t.strip()) < 15 for t in texts[:SPAM_SHORT_COUNT]))
    if not (has_abuse_word or many_short): return False
    update_session(channel.id, last_abuse_check_ts=now)
    is_abuse, reason = await check_abuse_llm(texts)
    if not is_abuse: return False
    update_session(channel.id, abuse_closed=1)
    await close_ticket_abuse(channel, reason, user_id)
    return True

async def close_ticket_abuse(channel, reason: str, user_id: int):
    try:
        embed = disnake.Embed(title="🚫 Тикет закрыт автоматически", description=f"> **Причина:** {'неадекватное поведение' if reason == 'abuse' else 'спам / флуд'}", color=0xed4245)
        await channel.send(embed=embed)
        await asyncio.sleep(5)
        await channel.delete(reason=f"AI: {reason}")
        ai_logger.warning(f"🤖 AI закрыл тикет {channel.id} по причине {reason}")
        await log_discord(title=f"🚫 AI закрыл тикет ({reason})", description=f"> **Канал:** `{channel.name}` (`{channel.id}`)\n> **Клиент:** <@{user_id}>", color=0xed4245, channel_id=LOG_CHANNEL)
    except Exception as e:
        ai_logger.exception(f"close_ticket_abuse: {e}")

def _is_paid_category(channel) -> bool:
    return channel.category and channel.category.id == CONFIG.get("PAID_CATEGORY_ID")

def _is_coins_category(channel) -> bool:
    return channel.category and channel.category.id == CONFIG.get("COINS_CATEGORY_ID")

def _is_real_category(channel) -> bool:
    return channel.category and channel.category.id == CONFIG.get("TICKET_CATEGORY_ID")

def _is_questions_category(channel) -> bool:
    return channel.category and channel.category.id == 1569979195369725973

def _is_ai_ticket(channel) -> bool:
    if _is_paid_category(channel): return False
    if _is_coins_category(channel): return False
    if _is_real_category(channel): return True
    if _is_questions_category(channel): return True
    return bool(get_ticket_owner(channel.id))

def _is_manager(member) -> bool:
    return member.id in OWNER_IDS or any(r.id == SELLER_ROLE for r in getattr(member, "roles", []))

async def get_ticket_discount(channel) -> int:
    try:
        async for msg in channel.history(limit=50):
            if msg.author.bot and msg.embeds and len(msg.embeds) >= 2:
                for field in msg.embeds[1].fields:
                    if "скидка" in field.name.lower():
                        val = field.value.strip("`\n ")
                        if val in ("", "Не активирована", "Не введён", "Не активирован"):
                            return 0
                        m = re.search(r"(\d+)", val)
                        return int(m.group(1)) if m else 10
    except Exception:
        pass
    return 0

async def _update_ticket_discount_embed(channel, discount_str: str):
    try:
        cur.execute(
            "INSERT INTO pending_ticket_updates (channel_id, discount_text, created_at) VALUES (?, ?, ?)",
            (channel.id, discount_str, int(time.time()))
        )
        db.commit()
        ai_logger.info(f"📝 Задача на обновление эмбеда со скидкой {discount_str} отправлена в БД.")
    except Exception as e:
        ai_logger.warning(f"Ошибка при создании задачи обновления эмбеда: {e}")

# ============================================================
# ИСТОРИЯ КЛИЕНТА
# ============================================================
def _get_user_history_text(user_id: int) -> str:
    try:
        dc = get_dc_cache(user_id)
        balance = dc.get("balance", 0)
        purchases = dc.get("purchases", [])
        history = dc.get("history", [])

        text = f"Баланс: {balance} DC.\n"
        
        if purchases:
            unused_items = [p.get("value") for p in purchases if not p.get("used") and p.get("type") != "discounts"]
            unused_discounts = [p.get("value") for p in purchases if not p.get("used") and p.get("type") == "discounts"]
            
            if unused_items:
                text += "Неиспользованные товары (напомни): " + ", ".join(unused_items[:5]) + "\n"
            if unused_discounts:
                text += "Купленные скидки в инвентаре: " + ", ".join(unused_discounts[:3]) + "\n"
        
        if history:
            spends = [h for h in history if h.get("amount", 0) < 0 and "Покупка" in h.get("reason", "")]
            if spends:
                last_buys = [h.get("reason", "").replace("Покупка: ", "") for h in spends[-3:]]
                text += "Последние покупки: " + ", ".join(last_buys) + "\n"

        return text.strip()
    except Exception as e:
        ai_logger.warning(f"_get_user_history_text: {e}")
        return "История недоступна."

# ============================================================
# СИСТЕМНЫЙ ПРОМПТ (УМНЫЙ UPSELL, АНАЛИЗ ТОНАЛЬНОСТИ, DC ВМЕСТО СКИДКИ)
# ============================================================
REAL_CATALOG_TEXT = build_real_catalog_text()

SYSTEM_PROMPT = """ты — ai-менеджер магазина diamond shop в discord-тикете. задача — помочь клиенту оформить заказ, как живой помощник.

ПРАВИЛА ОБЩЕНИЯ:
- В конце каждого обычного ответа добавь скрытую метку строго в формате `<confidence>ЧИСЛО</confidence>`, где ЧИСЛО от 0 до 100. Это не показывается клиенту.
- Если не уверен, задай уточняющий вопрос или вызови `escalate_to_human`.
- Не подтверждай оплату по изображению или тексту клиента; только распознай данные и передай продавцу на проверку.
- Товары оформляй блоком:
  > **Название** — 460 ₽
- Если клиент просит категорию без уточнений — покажи ВСЕ варианты с ценами.
- В вопросных тикетах отвечай на вопрос и не предлагай счёт без явного намерения купить.
- Счёт создаётся только после отдельного явного подтверждения клиентом показанной суммы.
- Инструменты check_user_balance, check_past_purchases и check_promo_code используют фактические данные; не выдумывай их результаты.

ГЛАВНОЕ ПРАВИЛО ПО ЦЕНАМ:
- В каталоге ниже некоторые товары имеют ДВЕ цены: цена Discord (в скобках) и НАША ЦЕНА (указана как `[НАША ЦЕНА: XXX]`).
- Для выставления счета ВСЕГДА бери **НАШУ ЦЕНУ**.

ПРАВИЛА ДЛЯ ТОВАРОВ С КОЛИЧЕСТВОМ:
- Если клиент покупает несколько штук, умножь цену за 1 шт на количество и укажи ИТОГОВУЮ сумму в `price`.
- В `item_name` укажи название и количество.
- НЕ ИСПОЛЬЗУЙ параметр `quantity`.

ИСТОРИЯ КЛИЕНТА:
{user_history}
- Если у клиента висят неиспользованные товары, деликатно напомни ему об этом.
- Если у клиента есть купленная скидка, можешь предложить применить её: "У вас есть скидка 5%, применить её?".

АНАЛИЗ ТОНАЛЬНОСТИ:
- Если клиент пишет капсом, оскорбляет или явно злится — НЕ ШУТИ, ответь сухо и СРАЗУ вызови продавца функцией `escalate_to_human`.
- Если клиент пишет с эмодзи и дружелюбно — можешь ответить чуть теплее и пошутить.

УМНЫЙ UPSELL (ДОПРОДАЖИ):
- Если сумма заказа превышает 750₽:
  1. Предложи клиенту скидку 5% на ВСЮ корзину, если он добавит ЛЮБОЙ сопутствующий товар.
  2. Предлагай ЛОГИЧНЫЕ товары: если берет Нитро — предложи Бусты; если Робуксы — предложи Роблокс Плюс; если ТГ Звезды — предложи Аккаунт ТГ.
  3. Если клиент соглашается, СНАЧАЛА добавь новый товар в корзину.
  4. При вызове `create_invoice` передай параметр `discount_percent: 5`.

ТОРГ (СКИДКИ В РУБЛЯХ ЗАПРЕЩЕНЫ):
- Если клиент просит скидку в рублях, которую ты не можешь дать, или торгуется:
  - Предложи ему альтернативу: "Я не могу снизить цену в рублях, но могу начислить вам 200 DC на баланс за эту покупку. Устроит?"
  - Если да — применяй стандартную цену (без `discount_percent`), а в поле `item_name` добавь пометку (DC кэшбек).
  - (Бот сам вычтет DC из копилки и начислит юзеру, тебе не нужно вызывать функции для DC, просто напиши это в тексте).

ГЛАВНОЕ ПРАВИЛО ПЕРЕД СЧЁТОМ:
- Сначала спроси: «Выставить счёт на <товар> за <цена>?»
- Жди явного подтверждения.
- Только после подтверждения — вызывай create_invoice.

ЗАПРЕТ НА DC (В ТИКЕТАХ ЗА РЕАЛ):
- В этом тикете ты продаешь ТОЛЬКО за реальные деньги (рубли).
- Если клиент просит что-то купить за DC, скажи: "Покупка за Diamond Coins происходит в канале витрины <#1462136361711829053> (DC-Shop). Здесь я оформляю только заказы за реальные деньги."

FAQ-РЕЖИМ (ЕСЛИ ТИКЕТ ВОПРОСОВ):
- Если клиент задает вопрос (например, "как работает нитро", "что дает роблокс плюс") — отвечай своими знаниями, не выставляй счет.

КАТАЛОГ:
{real_catalog}

контекст:
- клиент: {user_name}
- скидка в тикете (уже применена кнопкой): {discount}%
"""

TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "create_invoice",
            "description": "Выставить счёт. Можно передать ОДИН ИЛИ НЕСКОЛЬКО товаров в массиве items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_name": {"type": "string", "description": "Название товара"},
                                "price": {"type": "number", "description": "ИТОГОВАЯ цена в рублях"}
                            },
                            "required": ["item_name", "price"]
                        }
                    },
                    "discount_percent": {"type": "integer", "description": "Процент скидки (UpSell или скидка из инвентаря)", "default": 0}
                },
                "required": ["items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_user_balance",
            "description": "Получить баланс DC текущего клиента.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_past_purchases",
            "description": "Получить последние покупки текущего клиента.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_promo_code",
            "description": "Проверить промокод без автоматического применения.",
            "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Позвать продавца.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"]
            }
        }
    }
]

async def _call_single_model(model: str, system_prompt: str, messages: list,
                             tools=None, max_tokens: int = 800) -> Optional[dict]:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    url = f"{AI_MANAGER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {AI_MANAGER_API_KEY}", "Content-Type": "application/json"}
    started = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT)) as resp:
                if resp.status != 200:
                    log_ai_event("llm_error", payload={}, model=model, latency_ms=int((time.monotonic() - started) * 1000), success=False)
                    return {"error": f"HTTP {resp.status}"}
                data = await resp.json()
                choices = data.get("choices", [])
                if not choices:
                    return None
                msg = choices[0].get("message", {})
                text = (msg.get("content") or "").strip()
                tool_calls = msg.get("tool_calls") or []
                funcs = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    raw_args = fn.get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {}
                    funcs.append({"name": fn.get("name"), "args": args})
                result = {"text": text, "funcs": funcs, "model": model}
                log_ai_event("llm_response", payload={"has_text": bool(text), "tools": [f["name"] for f in funcs]}, model=model, latency_ms=int((time.monotonic() - started) * 1000))
                return result
    except Exception as e:
        log_ai_event("llm_exception", payload={"error": str(e)}, model=model, latency_ms=int((time.monotonic() - started) * 1000), success=False)
        return {"error": str(e)}


async def call_vision_model(prompt: str, image_urls: list) -> Optional[dict]:
    if not AI_MANAGER_API_KEY or not image_urls:
        return None
    content = [{"type": "text", "text": prompt}]
    content.extend({"type": "image_url", "image_url": {"url": url}} for url in image_urls[:4])
    messages = [{"role": "user", "content": content}]
    for model in VISION_MODELS:
        result = await _call_single_model(
            model,
            "Ты аккуратный помощник магазина. Не выдумывай данные на изображении.",
            messages,
            tools=None,
            max_tokens=500,
        )
        if result and "error" not in result:
            return result
    return None


async def call_llm(system_prompt: str, history: list, user_msg: str, image_urls: Optional[list] = None) -> Optional[dict]:
    if not AI_MANAGER_API_KEY:
        return None
    messages = []
    for role, text in history[-HISTORY_MAX_MSG:]:
        messages.append({"role": "assistant" if role == "ai" else "user", "content": text})
    if image_urls:
        content = [{"type": "text", "text": user_msg or "Проанализируй приложенное изображение."}]
        content.extend({"type": "image_url", "image_url": {"url": url}} for url in image_urls[:4])
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_msg})

    for model in (VISION_MODELS if image_urls else AI_MODELS):
        res = await _call_single_model(model, system_prompt, messages, tools=(None if image_urls else TOOLS_OPENAI))
        if res and "error" not in res:
            return res
    return None


async def generate_escalation_summary(channel, user_question: str) -> str:
    history = hist_load(channel.id, limit=20)
    compact = "\n".join(f"{role}: {text}" for role, text in history[-20:])
    prompt = "Сделай краткое резюме продавцу: запрос, товары/цена, что сделано, причина и следующий шаг. Не выдумывай.\n" + compact + "\nПоследнее: " + user_question[:800]
    for model in AI_MODELS:
        result = await _call_single_model(model, "Краткий помощник оператора.", [{"role": "user", "content": prompt}], tools=None, max_tokens=200)
        if result and "error" not in result and result.get("text"):
            return result["text"][:1500]
    return "Откройте историю тикета для контекста."

async def escalate(channel, reason: str, user_question: str = ""):
    if _is_paid_category(channel): return
    sess = get_session(channel.id)
    if sess is None: create_session(channel.id, 0)
    elif sess.get("escalated"): return
    update_session(channel.id, escalated=1)
    
    user_id = sess.get("user_id") or 0
    cur.execute(
        "INSERT INTO ai_escalations (user_id, channel_id, question, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, channel.id, user_question[:500], reason[:500], int(time.time()))
    )
    db.commit()

    summary = await generate_escalation_summary(channel, user_question)
    ping = f"<@&{SELLER_ROLE}>"
    embed = disnake.Embed(
        title="⚠️ Требуется помощь продавца",
        description=f"> {ping}, клиент ждёт ответа.\n> **Причина:** {reason}\n\n**Краткое резюме:**\n{summary}",
        color=COLOR_GREY,
    )
    embed.set_image(url=IMG_STRIPE)
    await channel.send(embed=embed)
    log_ai_event("escalated", channel.id, user_id, {"reason": reason, "summary": summary})
    ai_logger.info(f"Эскалация: {channel.id} — {reason}")

# ============================================================
# ОБРАБОТКА СЧЁТА И ЧЕКА
# ============================================================
def _clean_ticket_name(text: str, user_id: int) -> str:
    if not text: return f"order-{user_id}"
    clean = text.lower().replace(" ", "-")
    clean = re.sub(r"[^a-zа-яё0-9\-_]", "", clean)
    clean = clean.strip("- _")
    return clean[:80] or f"order-{user_id}"

async def send_invoice(channel, product_display: str, amount: int, discount: int, user_name: str) -> bool:
    try:
        clean_name = _clean_ticket_name(product_display, channel.id)
        try:
            await channel.edit(name=clean_name)
        except Exception as e:
            ai_logger.warning(f"Не удалось переименовать: {e}")

        order_id = generate_receipt_id()
        buf = await asyncio.to_thread(
            generate_receipt_png, manager_name="AI Manager", customer_name=user_name or "Клиент",
            product_name=product_display, amount=amount, discount_percent=int(discount), order_id=order_id,
        )
        file = disnake.File(buf, filename=f"receipt_{order_id}.png")
        total = amount - int(amount * discount / 100)
        embed = disnake.Embed(
            title=f"Счёт для оплаты: к оплате {total} ₽",
            description=f"> **Товары:** {product_display}\n> **Сумма:** `{amount} ₽`" + (f"\n> **Скидка:** `{discount}%`" if discount else "") + "\n\n> Проверьте реквизиты и пришлите чек в этот канал.",
            color=COLOR_GREY,
        )
        embed.set_image(url=f"attachment://receipt_{order_id}.png")
        await channel.send(embed=embed, file=file, view=ReceiptView())
        return True
    except Exception as e:
        ai_logger.exception(f"send_invoice: {e}")
        return False

async def _auto_confirm_receipt(channel, message, sess):
    """Legacy compatibility: never treat an uploaded image as proof of payment."""
    names = ", ".join(a.filename for a in message.attachments) or "attachment"
    try:
        await channel.send("Вложение получено и передано продавцу для проверки. Автоматически подтвердить оплату по скриншоту я не могу.")
        await log_discord("Attachment review", f"Channel: {channel.id} | User: {message.author.id} | Files: {names}", channel_id=LOG_CHANNEL)
    except Exception as e:
        ai_logger.warning(f"receipt review handoff: {e}")


async def _handle_dialog(channel, author, user_text: str, is_fallback: bool = False, image_urls: Optional[list] = None):
    if not user_text.strip() or _is_paid_category(channel) or _is_coins_category(channel): return
    user_id = author.id
    
    lock = get_lock(channel.id)
    if lock.locked(): return

    async with lock:
        sess = get_session(channel.id)
        if not sess:
            create_session(channel.id, user_id)
            sess = get_session(channel.id)
        
        if sess.get("escalated") or sess.get("abuse_closed") or sess.get("invoice_sent"): return

        try:
            if await _check_and_close_abuse(channel, user_id): return
        except Exception: pass
        if is_ai_muted(channel.id): return
        if sess["message_count"] >= SESSION_MAX_MESSAGES:
            await escalate(channel, "исчерпан лимит сообщений", user_text)
            return

        update_session(channel.id, message_count=(sess["message_count"] or 0) + 1)
        hist_append(channel.id, "user", user_text)

        # Анализ капса (агрессия)
        caps_ratio = sum(1 for c in user_text if c.isupper()) / max(len(user_text), 1)
        if caps_ratio > 0.6 and len(user_text) > 10:
            await escalate(channel, "Клиент злится (капс)", user_text)
            return

        discount = await get_ticket_discount(channel)
        user_history = _get_user_history_text(user_id)
        
        ticket_mode = "вопросы — не оформляй счёт" if _is_questions_category(channel) else "заказ"
        system_prompt = SYSTEM_PROMPT.format(
            real_catalog=REAL_CATALOG_TEXT,
            user_name=author.display_name,
            discount=discount,
            user_history=user_history,
        )
        
        history = hist_load(channel.id)
        
        async with channel.typing():
            result = await call_llm(system_prompt, history, user_text, image_urls=image_urls)
            
        if not result:
            new_fails = (sess["fail_count"] or 0) + 1
            update_session(channel.id, fail_count=new_fails)
            if new_fails >= SESSION_MAX_FAILS:
                await escalate(channel, "сбой LLM", user_text)
            else:
                try: await channel.send("⏳ Секунду, уточняю информацию…")
                except Exception: pass
            return

        update_session(channel.id, fail_count=0)
        text = (result.get("text") or "").strip()
        text, confidence = _extract_confidence(text)
        if confidence is not None:
            log_ai_event("confidence", channel.id, user_id, {"score": confidence, "answer": text})
            asyncio.create_task(notify_low_confidence(channel, user_id, text, confidence))
        funcs = result.get("funcs") or []

        if text and "Зову продавцов" in text:
            try: await channel.send(text)
            except Exception: pass
            touch_ai_response(channel.id)
            update_session(channel.id, escalated=1)
            await escalate(channel, "Товар не найден / нужен продавец", user_text)
            return

        if text and not funcs:
            try: await channel.send(text)
            except Exception: pass
            hist_append(channel.id, "ai", text)

        touch_ai_response(channel.id)

        if funcs:
            fc = funcs[0]
            name = fc.get("name")
            args = fc.get("args", {})

            if name == "check_user_balance":
                balance = await get_user_balance(user_id)
                result_text = f"Баланс клиента: {balance} DC."
                hist_append(channel.id, "ai", f"[система: {result_text}]")
                await channel.send(result_text)
                log_ai_event("tool_balance", channel.id, user_id, {"balance": balance})
                return

            if name == "check_past_purchases":
                dc_data = get_dc_cache(user_id)
                purchases = [h.get("reason", "") for h in (dc_data.get("history") or []) if h.get("amount", 0) < 0 and "Покупка" in h.get("reason", "")][-5:]
                result_text = "Последние покупки: " + (", ".join(purchases) if purchases else "покупок не найдено")
                hist_append(channel.id, "ai", f"[система: {result_text}]")
                await channel.send(result_text)
                log_ai_event("tool_purchases", channel.id, user_id, {"count": len(purchases)})
                return

            if name == "check_promo_code":
                code = str(args.get("code", "")).strip()
                row = cur.execute("SELECT value FROM promo_codes WHERE lower(code)=lower(?)", (code,)).fetchone() if code else None
                result_text = f"Промокод найден: {row['value']}" if row else "Промокод не найден."
                hist_append(channel.id, "ai", f"[система: {result_text}]")
                await channel.send(result_text)
                log_ai_event("tool_promo", channel.id, user_id, {"found": bool(row)})
                return

            if name == "create_invoice":
                fresh_sess = get_session(channel.id)
                if fresh_sess and fresh_sess.get("invoice_sent"):
                    return
                # Fail-closed: до выставления счета клиент обязан явно подтвердить цену.
                recent_dialog = hist_load(channel.id, limit=8)
                last_client_turn = next((t for r, t in reversed(recent_dialog) if r == "user"), "")
                previous_turns = " ".join(t for r, t in recent_dialog[:-1] if r == "ai")
                offered = bool(re.search(r"(выставить сч[её]т|оформить заказ).{0,100}(?:за|итого|сумма).{0,30}\d", previous_turns.lower()))
                explicit = bool(re.search(r"(да|подтверждаю|согласен|оформляй|выставляй|оплачиваю)", last_client_turn.lower()))
                if not (offered and explicit):
                    await channel.send("Подтвердите, пожалуйста, что оформляем заказ по указанной выше сумме.")
                    return
                items_list = args.get("items", [])
                if not items_list:
                    await channel.send("Не удалось определить товары. Позову продавца.")
                    await escalate(channel, "Пустая корзина при создании счёта", user_text)
                    return
                total_amount = 0
                names = []
                for item in items_list:
                    name_item = str(item.get("item_name", "Товар"))[:120]
                    price = float(item.get("price", 0))
                    if price <= 0 or price > 1000000:
                        await channel.send("Не могу безопасно проверить сумму. Позову продавца.")
                        await escalate(channel, "Некорректная цена в запросе счёта", user_text)
                        return
                    names.append(name_item)
                    total_amount += int(round(price))
                discount = min(10, max(0, int(args.get("discount_percent", 0)), discount))
                ok = await send_invoice(channel, ", ".join(names), total_amount, discount, author.display_name)
                if ok:
                    hist_clear(channel.id)
                    hist_append(channel.id, "ai", f"[счёт выставлен: {', '.join(names)}]")
                    update_session(channel.id, invoice_sent=1, message_count=0, fail_count=0, abandoned_notified=0)
                    log_ai_event("invoice_created", channel.id, user_id, {"items": names, "amount": total_amount, "discount": discount})
                return

            if name == "escalate_to_human":
                await escalate(channel, args.get("reason", "Нужен продавец"), user_text)
                return

        if text:
            await channel.send(text)
            hist_append(channel.id, "ai", text)

# ============================================================
# БОТ И СОБЫТИЯ
# ============================================================
intents = disnake.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!am", intents=intents)

_CLEANUP_STARTED = False

@bot.event
async def on_ready():
    global _CLEANUP_STARTED
    count = auto_init()
    ai_logger.info(f"AI Manager v3.1 запущен. Каталог: {count}")
    
    bot.add_view(AdStartView())

    if not _CLEANUP_STARTED:
        _CLEANUP_STARTED = True
        asyncio.create_task(_cleanup_loop())
        if not fallback_task.is_running(): fallback_task.start()
        if not activity_ping_task.is_running(): activity_ping_task.start()
        if not ads_cleanup_task.is_running(): ads_cleanup_task.start()
        if not analytics_task.is_running(): analytics_task.start()
        if not abandoned_carts_task.is_running(): abandoned_carts_task.start()

@bot.event
async def on_guild_channel_create(channel):
    if not isinstance(channel, disnake.TextChannel):
        return
    if channel.category_id != CONFIG.get("COINS_CATEGORY_ID"):
        return
    
    item_name = None
    for _ in range(5):
        async for msg in channel.history(limit=10):
            if msg.author.bot and msg.embeds:
                for embed in msg.embeds:
                    for field in embed.fields:
                        if "Нужный товар" in field.name:
                            item_name = field.value.strip("`\n ")
                            break
                if item_name: break
        if item_name: break
        await asyncio.sleep(2)
            
    if not item_name:
        return

    if "кастомная роль" in item_name.lower():
        has_emoji = "эмодзи" in item_name.lower()
        embed = disnake.Embed(
            title="🎨 Настройка кастомной роли",
            description=(
                f"Давайте создадим вашу уникальную роль!\n\n"
                "> 🎨 Нажмите на кнопку ниже, чтобы выбрать цвет.\n"
                "> ✏️ Затем введите название роли."
                + ("\n> 😀 И не забудьте добавить эмодзи!" if has_emoji else "")
            ),
            color=COLOR_GREY
        )
        embed.set_image(url=IMG_STRIPE)
        view = CustomRoleSetupView(has_emoji=has_emoji)
        await channel.send(embed=embed, view=view)
        create_session(channel.id, get_ticket_owner(channel.id) or 0)
        update_session(channel.id, escalated=1)
    elif any(x in item_name.lower() for x in ["аватарка", "баннер", "персонаж", "логотип", "дизайн"]):
        embed = disnake.Embed(
            title="🎨 Оформление дизайна",
            description=(
                f"Вы приобрели: **{item_name}**\n\n"
                "Пожалуйста, опишите, что именно вы хотите получить.\n\n"
                "> 🎨 Укажите стиль, цвета, референсы (картинки-примеры) и ваши пожелания.\n"
                "> ✍️ Дизайнер приступит к работе после того, как вы отправите описание."
            ),
            color=COLOR_GREY
        )
        embed.set_image(url=IMG_STRIPE)
        await channel.send(embed=embed)
        create_session(channel.id, get_ticket_owner(channel.id) or 0)
        update_session(channel.id, escalated=1)
    elif any(x in item_name.lower() for x in ["реклама", "канал", "@everyone", "@here", "без пинга"]):
        embed = build_ad_embed(item_name)
        await channel.send(embed=embed, view=AdStartView())
        create_session(channel.id, get_ticket_owner(channel.id) or 0)
        update_session(channel.id, escalated=1)

@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot or not isinstance(message.channel, disnake.TextChannel): return
    channel = message.channel

    if _is_paid_category(channel):
        # Do not auto-accept payment proof; only send the upload to seller review.
        if message.attachments:
            await _auto_confirm_receipt(channel, message, get_session(channel.id) or {})
        return

    if _is_coins_category(channel): return

    owner_id = get_ticket_owner(channel.id)
    is_ticket_owner = (owner_id is not None and message.author.id == owner_id)

    if isinstance(message.author, disnake.Member) and _is_manager(message.author) and not is_ticket_owner:
        if _is_ai_ticket(channel):
            if get_user_ai_pref(owner_id) and not _is_paid_category(channel):
                return
            else:
                sess = get_session(channel.id)
                if sess is None: create_session(channel.id, message.author.id)
                touch_manager_msg(channel.id)
                DEBOUNCE.pop(channel.id, None)
        return

    if not _is_ai_ticket(channel): return
    if owner_id and not is_ticket_owner: return

    touch_client_msg(channel.id, message.author.id)

    if message.attachments:
        sess = get_session(channel.id)
        image_urls = [a.url for a in message.attachments if (a.content_type or "").startswith("image/") or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
        if sess and sess.get("invoice_sent"):
            names = ", ".join(a.filename for a in message.attachments)
            await channel.send(f"{YES_EMOJI} Вложение получил и передал продавцу для проверки. Оплату автоматически не подтверждаю.")
            await log_discord("📎 Вложение после счёта", f"Канал: <#{channel.id}>\nКлиент: <@{message.author.id}>\nФайлы: {names}\n" + "\n".join(image_urls), channel_id=LOG_CHANNEL)
            return
        if image_urls:
            text = (message.content or "").strip() or "Проанализируй изображение: опиши видимый текст/ошибку/товар. Если это чек, извлеки видимые данные, пометь их непроверенными и не подтверждай оплату."
            state = DEBOUNCE.setdefault(channel.id, {"messages": [], "gen": 0, "images": []})
            state["messages"].append(text)
            state["images"].extend(image_urls[:4])
            state["gen"] += 1
            asyncio.create_task(_debounce_flush(channel, message.author, state["gen"]))
        return

    text = (message.content or "").strip()
    if not text: return

    state = DEBOUNCE.setdefault(channel.id, {"messages": [], "gen": 0, "images": []})
    state["messages"].append(text)
    state["gen"] += 1
    asyncio.create_task(_debounce_flush(channel, message.author, state["gen"]))

def get_user_ai_pref(user_id: int) -> bool:
    row = cur.execute("SELECT enabled FROM ai_manager_user_prefs WHERE user_id=?", (user_id,)).fetchone()
    return bool(row["enabled"]) if row else True

def set_user_ai_pref(user_id: int, enabled: bool):
    cur.execute("INSERT INTO ai_manager_user_prefs (user_id, enabled) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled", (user_id, 1 if enabled else 0))
    db.commit()

# ============================================================
# ФОНОВЫЕ ЗАДАЧИ
# ============================================================
@tasks.loop(minutes=10)
async def abandoned_carts_task():
    """Через 2 часа тишины мягко возвращает клиента к обсуждавшемуся заказу."""
    await bot.wait_until_ready()
    now = int(time.time())
    rows = cur.execute(
        "SELECT channel_id, user_id FROM ai_manager_sessions "
        "WHERE last_client_msg_ts > 0 AND invoice_sent=0 AND escalated=0 "
        "AND abuse_closed=0 AND abandoned_notified=0 AND last_manager_msg_ts < ?",
        (now - 7200,),
    ).fetchall()
    for row in rows:
        channel = bot.get_channel(row["channel_id"])
        if not channel or not _is_ai_ticket(channel):
            continue
        history = hist_load(channel.id, limit=12)
        dialog = "\n".join(f"{r}: {t}" for r, t in history[-12:])
        prompt = (
            "Напиши одно короткое ненавязчивое сообщение клиенту, который перестал отвечать в магазине. "
            "Не выдумывай скидки, наличие, цены или акции; не дави. Если из переписки нельзя понять заказ, "
            "спроси, нужна ли ещё помощь.\n" + dialog
        )
        text = None
        for model in AI_MODELS:
            out = await _call_single_model(model, "Ты вежливый менеджер магазина.", [{"role": "user", "content": prompt}], tools=None, max_tokens=120)
            if out and "error" not in out and out.get("text"):
                text = out["text"][:700]
                break
        if not text:
            text = "Если заказ ещё актуален, напишите — помогу продолжить оформление."
        try:
            await channel.send(f"<@{row['user_id']}> {text}")
            update_session(channel.id, abandoned_notified=1)
            log_ai_event("abandoned_cart_followup", channel.id, row["user_id"], {"text": text})
        except Exception as e:
            ai_logger.warning(f"abandoned cart follow-up {channel.id}: {e}")


@tasks.loop(minutes=1)
async def ads_cleanup_task():
    try:
        now = int(time.time())
        rows = cur.execute("SELECT id, channel_id, message_id, is_personal FROM active_ads WHERE expires_at > 0 AND expires_at <= ?", (now,)).fetchall()
        
        for r in rows:
            cid = r["channel_id"]
            mid = r["message_id"]
            is_personal = r["is_personal"]
            
            ch = bot.get_channel(cid)
            if ch:
                try:
                    if is_personal:
                        await ch.delete(reason="Срок аренды личного канала истек")
                    else:
                        msg = await ch.fetch_message(mid)
                        await msg.delete()
                except Exception as e:
                    ai_logger.warning(f"Не удалось удалить рекламу (ch={cid}): {e}")
            
            cur.execute("DELETE FROM active_ads WHERE id=?", (r["id"],))
            db.commit()
            ai_logger.info(f"🧹 Удалена истекшая реклама ID={r['id']} (personal={is_personal})")
            
    except Exception as e:
        ai_logger.exception(f"Ошибка в ads_cleanup_task: {e}")

@tasks.loop(minutes=1)
async def fallback_task():
    await bot.wait_until_ready()
    now = int(time.time())
    rows = cur.execute("""
        SELECT channel_id, user_id, last_client_msg_ts, last_ai_response_ts,
               last_manager_msg_ts, invoice_sent, fail_count, abuse_closed, escalated
        FROM ai_manager_sessions
        WHERE last_client_msg_ts > 0 AND invoice_sent = 0 AND abuse_closed = 0 AND fail_count < 3 AND escalated = 0
    """).fetchall()
    for r in rows:
        channel_id = r["channel_id"]
        if (r["last_ai_response_ts"] or 0) >= (r["last_client_msg_ts"] or 0): continue
        if (now - (r["last_client_msg_ts"] or 0)) < 15: continue
        if r["last_manager_msg_ts"] and (now - r["last_manager_msg_ts"]) < MANAGER_SILENCE_SEC: continue
        if (now - (r["last_client_msg_ts"] or 0)) > CLIENT_MAX_SILENCE_SEC: continue
        if not get_user_ai_pref(r["user_id"]) and (now - (r["last_client_msg_ts"] or 0)) < FALLBACK_WAIT_SEC: continue
        
        channel = bot.get_channel(channel_id)
        if not channel or not _is_ai_ticket(channel): continue
            
        fresh_sess = get_session(channel_id)
        if fresh_sess and (fresh_sess.get("invoice_sent") or fresh_sess.get("escalated") or fresh_sess.get("abuse_closed")): continue

        try:
            if await _check_and_close_abuse(channel, r["user_id"]): continue
        except Exception: pass

        last_text = hist_last_client_msg(channel_id)
        if not last_text: continue
            
        try:
            member = channel.guild.get_member(r["user_id"])
            if member: await _handle_dialog(channel, member, last_text, is_fallback=True)
        except Exception as e:
            ai_logger.exception(f"fallback dialog: {e}")

@tasks.loop(minutes=1)
async def activity_ping_task():
    await bot.wait_until_ready()
    targets = [CONFIG.get("TICKET_CATEGORY_ID"), CONFIG.get("PAID_CATEGORY_ID")]
    for cat_id in targets:
        if not cat_id: continue
        cat = bot.get_channel(cat_id)
        if not cat or not isinstance(cat, disnake.CategoryChannel): continue
        for channel in cat.text_channels:
            try: age = (datetime.now(timezone.utc) - channel.created_at).total_seconds()
            except Exception: continue
            if age < 300 or age > 330: continue

            owner_id = get_ticket_owner(channel.id)
            if not owner_id: continue

            sess = get_session(channel.id)
            if sess:
                if sess.get("stub_sent"): continue
                if (sess.get("last_client_msg_ts") or 0) > 0: continue
            else:
                create_session(channel.id, owner_id)
                sess = get_session(channel.id)

            try:
                await channel.send(f"> <@{owner_id}>, привет.\n\nТикет открыт, но пока тихо. Что хочешь заказать?")
                update_session(channel.id, stub_sent=1)
            except Exception as e: ai_logger.warning(f"idle_ping send: {e}")

async def _cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        try:
            cutoff = int(time.time()) - 7 * 86400
            cur.execute("DELETE FROM ai_manager_sessions WHERE created_at < ?", (cutoff,))
            cur.execute("DELETE FROM ai_manager_history WHERE created_at < ?", (cutoff,))
            db.commit()
            ai_logger.info("Cleanup: старые сессии/история удалены")
        except Exception:
            ai_logger.exception("cleanup")

@tasks.loop(hours=24)
async def analytics_task():
    await bot.wait_until_ready()
    try:
        week_ago = int(time.time()) - 7 * 86400
        rows = cur.execute(
            "SELECT question, reason FROM ai_escalations WHERE created_at > ?", 
            (week_ago,)
        ).fetchall()

        if not rows:
            return

        questions = {}
        for r in rows:
            q = r["question"].strip().lower()
            if not q: q = "[Пустой вопрос/сбой]"
            questions[q] = questions.get(q, 0) + 1

        top_q = sorted(questions.items(), key=lambda x: -x[1])[:10]

        text = "📊 **Аналитика ИИ-менеджера за неделю**\n\n"
        text += f"Всего эскалаций (ИИ сдался): **{len(rows)}**\n\n"
        text += "**Топ вопросов, на которые ИИ не смог ответить:**\n"
        
        for i, (q, count) in enumerate(top_q, 1):
            text += f"{i}. {q} (встречался {count} раз)\n"
            
        text += "\n_Возможно, стоит добавить эти товары в каталог или обновить промпт._"

        user = bot.get_user(ANALYTICS_USER_ID)
        if not user:
            user = await bot.fetch_user(ANALYTICS_USER_ID)
            
        if user:
            await user.send(text)
            ai_logger.info("📊 Аналитика ИИ-менеджера отправлена в ЛС.")
            
    except Exception as e:
        ai_logger.exception(f"Ошибка в analytics_task: {e}")

def run_ai_manager():
    if not AI_MANAGER_TOKEN or not AI_MANAGER_API_KEY:
        ai_logger.error("Токены не заданы")
        raise SystemExit(1)
    try:
        bot.run(AI_MANAGER_TOKEN)
    except Exception as e:
        ai_logger.exception(f"Ошибка запуска: {e}")
        raise
