# -*- coding: utf-8 -*-
import os
import re
import io
import json
import time
import math
import base64
import asyncio
import logging
import glob
import difflib
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

import aiohttp
import disnake
from PIL import Image
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

DIAMOND_AI_MODEL = "google/gemini-3-flash-preview"
LAST_RESORT_MODEL = "qwen/qwen-2.5-72b-instruct"

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

# ------------------------------------------------------------
# ИНДЕКС ЦЕН КАТАЛОГА (для проверки счетов)
# ------------------------------------------------------------
# Каталог в JSON — единственный источник правды по ценам.
# LLM только предлагает товар, а цену мы сверяем здесь.
_PRICE_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
_QTY_RE = re.compile(
    r"(?<![a-zа-я0-9])(\d+)\s*(?:шт|штук[аи]?|раз|★|робукс\w*)"
    r"|(?<![a-zа-я0-9])[xх]\s*(\d+)",
    re.IGNORECASE,
)

# Категории, где в каталоге указана цена ЗА 1 единицу, а не за товар.
RATE_CATEGORIES = {"робуксы", "пополнение аккаунта steam"}


def _norm_cat(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    return " ".join(text.split())


def build_catalog_index() -> List[dict]:
    """Собирает плоский список товаров: категория, название, цена, тип."""
    items = []
    for f in glob.glob(os.path.join(CATALOG_DIR, "menu_*.json")):
        if "shop_catalog" in f:
            continue
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception:
            continue
        for e in data.get("embeds", []):
            category = _norm_cat(e.get("title", ""))
            for field in e.get("fields", []):
                name = _norm_cat(field.get("name", ""))
                raw_value = (field.get("value") or "").replace("`", "").strip()
                if not name or not raw_value:
                    continue
                low = raw_value.lower()
                if "обсужда" in low or "уточн" in low or "узнавать" in low:
                    items.append({"category": category, "name": name, "price": None, "kind": "negotiable"})
                    continue
                m = _PRICE_RE.search(raw_value)
                if not m:
                    items.append({"category": category, "name": name, "price": None, "kind": "negotiable"})
                    continue
                price = float(m.group(1).replace(",", "."))
                if re.search(r"(?<![a-zа-я])(от)(?![a-zа-я])", low):
                    kind = "from"
                elif category in RATE_CATEGORIES:
                    kind = "rate"
                else:
                    kind = "fixed"
                items.append({"category": category, "name": name, "price": price, "kind": kind})
    return items


CATALOG_ITEMS = build_catalog_index()


def _best_category(q: str) -> Optional[str]:
    """Самая длинная категория каталога, упомянутая в запросе."""
    best = None
    for cat in {it["category"] for it in CATALOG_ITEMS if it["category"]}:
        if f" {cat} " in f" {q} " and (best is None or len(cat) > len(best)):
            best = cat
    return best


def _name_score(q: str, name: str) -> int:
    if not name:
        return 0
    if q == name:
        return 120
    if name in q:
        return 90
    q_tokens, n_tokens = set(q.split()), set(name.split())
    if not n_tokens:
        return 0
    jaccard = len(q_tokens & n_tokens) / len(q_tokens | n_tokens)
    return int(jaccard * 80)


def find_catalog_item(item_name: str) -> Tuple[Optional[dict], str]:
    """Ищет товар в каталоге. Возвращает (товар, статус)."""
    q = _norm_cat(item_name)
    if not q:
        return None, "not_found"

    # 1) Сначала ищем внутри явно названной категории.
    category = _best_category(q)
    candidates = [it for it in CATALOG_ITEMS if category and it["category"] == category]
    if not candidates:
        candidates = CATALOG_ITEMS

    scored = sorted(
        ((_name_score(q, it["name"]), it) for it in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored:
        return None, "not_found"

    top_score, top_item = scored[0]
    if top_score < 55:
        return None, "not_found"

    ties = [it for score, it in scored if score == top_score]
    if len(ties) > 1 and len({it["price"] for it in ties}) > 1:
        return None, "ambiguous"

    return top_item, "ok"


def _parse_quantity(item_name: str, quantity) -> int:
    try:
        qty = int(quantity)
        if qty > 0:
            return qty
    except Exception:
        pass
    for m in _QTY_RE.finditer(item_name or ""):
        for group in m.groups():
            if group:
                return max(1, int(group))
    return 1


def resolve_invoice_line(item_name: str, claimed_price, quantity) -> dict:
    """Проверяет одну строку счёта по каталогу.

    Возвращает dict: status = ok | negotiable | ambiguous | not_found | bad_price,
    price — итоговая цена строки (0, если выставлять нельзя).
    """
    item, status = find_catalog_item(item_name)
    if status != "ok" or not item:
        return {"status": status, "price": 0, "name": item_name}

    if item["kind"] == "negotiable":
        return {"status": "negotiable", "price": 0, "name": item_name}

    try:
        claimed = float(claimed_price)
    except Exception:
        claimed = 0.0
    if claimed < 0:
        claimed = 0.0

    catalog_price = float(item["price"] or 0)
    qty = _parse_quantity(item_name, quantity)

    if item["kind"] == "rate":
        # Цена за единицу: итог = ставка × количество.
        if qty <= 1 and claimed >= catalog_price:
            total = claimed  # количество не распознано, но сумма не ниже ставки
        else:
            total = catalog_price * max(qty, 1)
    elif item["kind"] == "from":
        # «от N»: ниже минимума выставлять нельзя.
        total = max(claimed, catalog_price * max(qty, 1))
    else:
        total = catalog_price * max(qty, 1)

    total = int(round(total))
    if total <= 0:
        return {"status": "bad_price", "price": 0, "name": item_name}

    if claimed and abs(claimed - total) > max(1.0, total * 0.02):
        ai_logger.warning(
            f"⚠️ Цена скорректирована по каталогу: «{item_name}» "
            f"{claimed:.0f} ₽ → {total} ₽ (каталог: {item['category']} / {item['name']}, {item['kind']})"
        )
    return {"status": "ok", "price": total, "name": item_name}

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
        post_invoice_text_count INTEGER DEFAULT 0, invoice_amount INTEGER DEFAULT 0,
        invoice_order_id TEXT DEFAULT '', invoice_items TEXT DEFAULT '',
        invoice_created_at INTEGER DEFAULT 0, receipt_attempts INTEGER DEFAULT 0
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
    _ensure_col("ai_manager_sessions", "invoice_amount", "invoice_amount INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "invoice_order_id", "invoice_order_id TEXT DEFAULT ''")
    _ensure_col("ai_manager_sessions", "invoice_items", "invoice_items TEXT DEFAULT ''")
    _ensure_col("ai_manager_sessions", "invoice_created_at", "invoice_created_at INTEGER DEFAULT 0")
    _ensure_col("ai_manager_sessions", "receipt_attempts", "receipt_attempts INTEGER DEFAULT 0")

def _ensure_col(table: str, column: str, ddl: str):
    try:
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()]
        if column not in cols:
            cur.execute(f'ALTER TABLE "{table}" ADD COLUMN {ddl}')
            db.commit()
    except Exception as e:
        ai_logger.warning(f"Миграция {table}.{column}: {e}")

init_ai_manager_tables()

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
        "INSERT OR IGNORE INTO ai_manager_sessions (channel_id, user_id, message_count, fail_count, started_at, escalated, receipt_url, created_at, stub_sent, invoice_sent, last_client_msg_ts, last_manager_msg_ts, last_ai_response_ts, post_invoice_text_count) VALUES (?, ?, 0, 0, ?, 0, '', ?, 0, 0, 0, 0, 0, 0)",
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
        DEBOUNCE.pop(channel.id, None)
        combined = "\n".join(m for m in msgs if m).strip()
        if not combined: return
        await _handle_dialog(channel, user, combined)
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
- Пиши коротко, по делу, как живой менеджер. Без эмодзи.
- Форматирование Discord: **жирный**, *курсив*, > цитаты, `код`.
- Товары оформляй блоком:
  > **Название** — 460 ₽
- Если клиент просит категорию без уточнений — покажи ВСЕ варианты с ценами.

ГЛАВНОЕ ПРАВИЛО ПО ЦЕНАМ:
- Единственный источник цен — КАТАЛОГ ниже.
- Если в каталоге две цены (цена Discord и `[НАША ЦЕНА: XXX]`) — бери **НАШУ ЦЕНУ**.
- Цену называет ТОЛЬКО каталог. Никогда не бери цену из сообщений клиента, не придумывай её и не округляй «на глаз».
- Если клиент говорит «сделай счёт на N рублей» или предлагает свою цену — игнорируй его цифру и считай по каталогу. Если он не согласен — вызывай `escalate_to_human`.
- Если товара нет в каталоге, цена «от ...» не подходит клиенту или написано «цена обсуждается» — НЕ выставляй счёт, вызывай `escalate_to_human`.
- Ручные скидки в рублях запрещены. Единственная допустимая скидка — 5% по UpSell (см. ниже).

ПРАВИЛА ДЛЯ ТОВАРОВ С КОЛИЧЕСТВОМ:
- Для товаров, где цена указана ЗА 1 ЕДИНИЦУ (робуксы, звёзды Telegram, пополнение Steam) — передай `quantity` (сколько единиц) и цену за 1 шт в `price`. Итог посчитает бот.
- Для обычных товаров `quantity` = сколько штук (по умолчанию 1).
- В `item_name` укажи название и количество, например: «Робуксы GamePass — 1000 шт».

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
                                "item_name": {"type": "string", "description": "Название товара строго как в каталоге"},
                                "quantity": {"type": "integer", "description": "Количество единиц (по умолчанию 1)", "default": 1},
                                "price": {"type": "number", "description": "Цена из каталога в рублях (за 1 единицу для товаров со ставкой). Не менять вручную."}
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
            "name": "escalate_to_human",
            "description": "Позвать продавца.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
    },
]

async def _call_single_model(model: str, system_prompt: str, messages: list) -> Optional[dict]:
    payload = {"model": model, "messages": [{"role": "system", "content": system_prompt}] + messages, "tools": TOOLS_OPENAI, "tool_choice": "auto", "temperature": 0.1, "max_tokens": 800}
    url = f"{AI_MANAGER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {AI_MANAGER_API_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT)) as resp:
                if resp.status != 200: return {"error": f"HTTP {resp.status}"}
                data = await resp.json()
                choices = data.get("choices", [])
                if not choices: return None
                msg = choices[0].get("message", {})
                text = (msg.get("content") or "").strip()
                tool_calls = msg.get("tool_calls") or []
                funcs = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    raw_args = fn.get("arguments", "{}")
                    try: args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception: args = {}
                    funcs.append({"name": fn.get("name"), "args": args})
                return {"text": text, "funcs": funcs}
    except Exception as e:
        return {"error": str(e)}

async def call_llm(system_prompt: str, history: list, user_msg: str) -> Optional[dict]:
    if not AI_MANAGER_API_KEY: return None
    messages = []
    for role, text in history[-HISTORY_MAX_MSG:]:
        messages.append({"role": "assistant" if role == "ai" else "user", "content": text})
    messages.append({"role": "user", "content": user_msg})
    
    models_to_try = [DIAMOND_AI_MODEL, LAST_RESORT_MODEL]
    for model in models_to_try:
        res = await _call_single_model(model, system_prompt, messages)
        if res and "error" not in res:
            return res
    return None

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

    ping = f"<@&{SELLER_ROLE}>"
    embed = disnake.Embed(title="⚠️ Требуется помощь продавца", description=f"> {ping}, клиент ждёт ответа.\n> **Причина:** {reason}", color=COLOR_GREY)
    embed.set_image(url=IMG_STRIPE)
    await channel.send(embed=embed)
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

async def send_invoice(channel, product_display: str, amount: int, discount: int, user_name: str) -> Optional[Tuple[int, str]]:
    """Отправляет счёт. Возвращает (сумма к оплате, номер заказа) или None."""
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
            description=f"> **Товары:** {product_display}\n> **Сумма:** `{amount} ₽`" + (f"\n> **Скидка:** `{discount}%`" if discount else "") + "\n\n> Проверьте реквизиты и пришлите чек скриншотом или PDF — я сверю сумму автоматически.",
            color=COLOR_GREY,
        )
        embed.set_image(url=f"attachment://receipt_{order_id}.png")
        await channel.send(embed=embed, file=file, view=ReceiptView())
        return total, order_id
    except Exception as e:
        ai_logger.exception(f"send_invoice: {e}")
        return None

async def _auto_confirm_receipt(channel, message, sess, receipt_att=None):
    user_id = sess.get("user_id") or message.author.id
    try: await message.add_reaction(YES_EMOJI)
    except Exception: pass

    sellers_ping = f"<@&{SELLER_ROLE}>"
    embed = disnake.Embed(
        title="💚 Оплата принята.",
        description=f">>> Чек у меня, все проверил. Спасибо что выбираете нас!\n\n{sellers_ping} скоро подключатся и выдадут заказ! ",
        color=COLOR_GREEN
    )
    embed.set_image(url=IMG_STRIPE)
    try: await channel.send(embed=embed)
    except Exception as e: ai_logger.warning(f"auto_confirm: send msg failed: {e}")

    paid_cat = bot.get_channel(CONFIG.get("PAID_CATEGORY_ID"))
    if paid_cat:
        try:
            await channel.edit(category=paid_cat)
            ai_logger.info(f"✅ auto_confirm: {channel.id} перенесен в категорию {paid_cat.name}")
        except Exception as e:
            ai_logger.warning(f"⚠️ auto_confirm edit fail: {e}")

    try:
        seller_role = channel.guild.get_role(SELLER_ROLE)
        if seller_role:
            await channel.set_permissions(seller_role, send_messages=True, view_channel=True)
    except Exception as e:
        ai_logger.warning(f"auto_confirm: seller perms failed: {e}")

    update_session(
        channel.id, invoice_sent=0,
        receipt_url=(receipt_att.url if receipt_att else (message.attachments[0].url if message.attachments else "")),
        post_invoice_text_count=0, last_ai_response_ts=int(time.time()), escalated=1
    )

# ------------------------------------------------------------
# ПРОВЕРКА ЧЕКА: распознаём сумму (vision) и сверяем со счётом
# ------------------------------------------------------------
RECEIPT_TOLERANCE = 1          # допуск в рублях
RECEIPT_MAX_BYTES = 8 * 1024 * 1024
RECEIPT_MAX_ATTEMPTS = 3
RECEIPT_VISION_MODEL = os.getenv("RECEIPT_VISION_MODEL", DIAMOND_AI_MODEL)

RECEIPT_SYSTEM_PROMPT = """Ты читаешь скриншот или PDF из банковского приложения.
Верни ТОЛЬКО JSON, без markdown и пояснений:
{"doc_type": "payment_confirmation|invoice|other", "amount": <число или null>, "currency": "RUB"}

Правила:
- payment_confirmation — подтверждение перевода: видно «Выполнено», «Успешно», «Перевод совершён», «Оплачено», «Чек», «Квитанция».
- invoice — счёт на оплату или реквизиты: заголовки «Счёт», «Реквизиты», «Шаг 1 · Оплата», кнопки «Оплатить», «Перевести».
- всё остальное (переписка, товар, мем, просто баланс) — other.
- amount — итоговая сумма именно перевода. Не бери баланс, комиссию, номер карты, номер телефона, дату.
- Если сумму не видно или не уверен — null, не угадывай."""


def _media_kind(att) -> Optional[str]:
    ct = (getattr(att, "content_type", "") or "").lower()
    name = (getattr(att, "filename", "") or "").lower()
    if ct.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
        return "image"
    if ct == "application/pdf" or name.endswith(".pdf"):
        return "pdf"
    return None


def _to_jpeg_b64(img: Image.Image) -> str:
    img = img.convert("RGB")
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _pdf_first_page_b64(raw: bytes) -> Optional[str]:
    """Первая страница PDF → JPEG base64. Требует PyMuPDF (pip install pymupdf)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        ai_logger.error("PyMuPDF не установлен: чеки в PDF не читаются (pip install pymupdf)")
        return None
    try:
        with fitz.open(stream=raw, filetype="pdf") as doc:
            if doc.page_count == 0:
                return None
            pix = doc[0].get_pixmap(dpi=150)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            return _to_jpeg_b64(img)
    except Exception as e:
        ai_logger.warning(f"PDF → image: {e}")
        return None


def _parse_amount(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d,.\-]", "", str(value))
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            s = "".join(parts)  # 1.500 → 1500 (разделитель тысяч)
    try:
        return float(s)
    except Exception:
        return None


def _fmt_amount(value) -> str:
    a = _parse_amount(value)
    if a is None:
        return "—"
    if abs(a - round(a)) < 0.01:
        return str(int(round(a)))
    return f"{a:.2f}"


async def read_receipt(attachment) -> dict:
    """Отдаёт картинку/PDF vision-модели. Возвращает {doc_type, amount} или {error}."""
    kind = _media_kind(attachment)
    if not kind:
        return {"error": "unsupported"}
    try:
        if (attachment.size or 0) > RECEIPT_MAX_BYTES:
            return {"error": "too_big"}
        raw = await attachment.read()
    except Exception as e:
        return {"error": f"download: {e}"}

    if kind == "image":
        try:
            b64 = _to_jpeg_b64(Image.open(io.BytesIO(raw)))
        except Exception as e:
            return {"error": f"decode: {e}"}
    else:
        b64 = _pdf_first_page_b64(raw)
        if not b64:
            return {"error": "pdf"}

    if not AI_MANAGER_API_KEY:
        return {"error": "no_key"}

    payload = {
        "model": RECEIPT_VISION_MODEL,  # qwen текстовый — фолбэк на него для картинок запрещён
        "messages": [
            {"role": "system", "content": RECEIPT_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Прочитай документ и верни JSON."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]},
        ],
        "temperature": 0,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }
    url = f"{AI_MANAGER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {AI_MANAGER_API_KEY}", "Content-Type": "application/json"}
    for _ in range(2):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT)) as resp:
                    if resp.status == 400 and "response_format" in payload:
                        # Прокси не поддерживает json_object — повторяем без него.
                        payload.pop("response_format", None)
                        continue
                    if resp.status != 200:
                        return {"error": f"HTTP {resp.status}"}
                    data = await resp.json()
        except Exception as e:
            return {"error": str(e)}

        if not data.get("choices"):
            return {"error": "empty"}
        text = (data["choices"][0].get("message", {}).get("content") or "").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text).strip()
        try:
            parsed = json.loads(text)
        except Exception:
            return {"error": "bad_json"}
        return parsed if isinstance(parsed, dict) else {"error": "bad_json"}
    return {"error": "request"}


def check_receipt_amount(data: dict, expected: int) -> str:
    """Вердикт: ok | invoice | not_receipt | no_amount | amount_mismatch | error."""
    if not data or data.get("error"):
        return "error"
    if data.get("doc_type") == "invoice":
        return "invoice"
    if data.get("doc_type") != "payment_confirmation":
        return "not_receipt"
    amount = _parse_amount(data.get("amount"))
    if amount is None:
        return "no_amount"
    if abs(amount - expected) <= RECEIPT_TOLERANCE:
        return "ok"
    return "amount_mismatch"


async def _receipt_reject(channel, message, text: str, reason: str, escalate_now: bool = False):
    try:
        await message.reply(text, mention_author=False)
    except Exception:
        try:
            await channel.send(text)
        except Exception:
            pass

    sess = get_session(channel.id)
    attempts = int((sess or {}).get("receipt_attempts") or 0) + 1
    update_session(channel.id, receipt_attempts=attempts)

    await log_discord(
        "🧾 Чек не принят",
        f"> **Канал:** <#{channel.id}>\n> **Причина:** {reason}\n> **Попытка:** {attempts}/{RECEIPT_MAX_ATTEMPTS}",
        color=0xed4245,
    )

    if escalate_now or attempts >= RECEIPT_MAX_ATTEMPTS:
        await escalate(channel, reason, text[:300])


async def _handle_receipt(channel, message, sess):
    lock = get_lock(channel.id)
    if lock.locked():
        return
    async with lock:
        fresh = get_session(channel.id)
        if not fresh or not fresh.get("invoice_sent"):
            return
        await _process_receipt(channel, message, fresh)


async def _process_receipt(channel, message, sess):
    expected = int(sess.get("invoice_amount") or 0)
    att = next((a for a in message.attachments if _media_kind(a)), None)
    if not att:
        await message.reply(
            "⚠️ Пришлите чек картинкой (PNG/JPG) или PDF, чтобы я мог сверить сумму.",
            mention_author=False,
        )
        return

    try:
        await message.add_reaction("⏳")
    except Exception:
        pass

    data = await read_receipt(att)
    verdict = check_receipt_amount(data, expected) if expected > 0 else "error"

    try:
        await message.remove_reaction("⏳", channel.guild.me)
    except Exception:
        pass

    ai_logger.info(
        f"Чек {channel.id}: verdict={verdict}, ожидалось={expected}, "
        f"распознано={data.get('amount')} ({data.get('doc_type')}), "
        f"файл={att.filename}, ошибка={data.get('error')}"
    )

    if verdict == "ok":
        await log_discord(
            "✅ Чек проверен",
            f"> **Канал:** <#{channel.id}>\n> **Клиент:** <@{message.author.id}>\n"
            f"> **Сумма:** `{expected} ₽` совпадает\n> **Файл:** `{att.filename}`",
            color=COLOR_GREEN,
        )
        await _auto_confirm_receipt(channel, message, sess, receipt_att=att)
        return

    if verdict == "amount_mismatch":
        await _receipt_reject(
            channel, message,
            f"⚠️ В чеке сумма `{_fmt_amount(data.get('amount'))} ₽`, а в счёте `{expected} ₽`.\n"
            "> Пришлите чек на верную сумму.",
            f"Сумма в чеке не совпадает: {_fmt_amount(data.get('amount'))} ₽ / счёт {expected} ₽",
            escalate_now=True,
        )
        return

    if verdict == "invoice":
        await _receipt_reject(
            channel, message,
            "⚠️ Это счёт на оплату, а не подтверждение перевода.\n"
            "> Оплатите его и пришлите скриншот или PDF с отметкой «Выполнено».",
            "Клиент прислал счёт вместо чека об оплате",
            escalate_now=True,
        )
        return

    if verdict in ("not_receipt", "no_amount"):
        await _receipt_reject(
            channel, message,
            "⚠️ Не вижу сумму перевода на этом файле.\n"
            "> Пришлите скриншот чека, где видна итоговая сумма.",
            "Чек не распознан: нет подтверждения перевода или суммы",
        )
        return

    # error / pdf / нет сохранённой суммы счёта
    await _receipt_reject(
        channel, message,
        "⏳ Не смог автоматически проверить чек. Передаю продавцу.",
        f"Ошибка проверки чека: {data.get('error') or 'сумма счёта неизвестна'}",
        escalate_now=True,
    )

async def _handle_dialog(channel, author, user_text: str, is_fallback: bool = False):
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
        
        system_prompt = SYSTEM_PROMPT.format(
            real_catalog=REAL_CATALOG_TEXT,
            user_name=author.display_name, 
            discount=discount,
            user_history=user_history
        )
        
        history = hist_load(channel.id)
        
        async with channel.typing():
            result = await call_llm(system_prompt, history, user_text)
            
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
            name = fc["name"]
            args = fc.get("args", {})

            if name == "create_invoice":
                fresh_sess = get_session(channel.id)
                if fresh_sess and fresh_sess.get("invoice_sent"): return
                    
                items_list = args.get("items", [])
                if not items_list:
                    await channel.send("⚠️ Не удалось распознать товар.")
                    return

                # Сверяем каждую строку с каталогом: цену берём из JSON, а не из ответа модели.
                total_amount = 0
                receipt_names = []
                for itm in items_list:
                    item_name = str(itm.get("item_name", "")).strip() or "Товар"
                    line = resolve_invoice_line(item_name, itm.get("price", 0), itm.get("quantity", 1))

                    if line["status"] == "ambiguous":
                        await channel.send("⚠️ Уточните товар: в каталоге несколько вариантов с похожим названием.")
                        await escalate(channel, f"Неоднозначный товар в счёте: {item_name}", user_text)
                        return
                    if line["status"] in ("not_found", "negotiable", "bad_price"):
                        await channel.send("⚠️ Не могу выставить счёт: позиции нет в каталоге или цена обсуждается. Передаю продавцу.")
                        await escalate(channel, f"Товар вне каталога: {item_name}", user_text)
                        return

                    total_amount += line["price"]
                    receipt_names.append(item_name)

                product_display = ", ".join(receipt_names)

                # Скидка ограничена: скидка тикета или UpSell 5% при заказе от 750 ₽.
                upsell_discount = max(0, int(args.get("discount_percent", 0) or 0))
                allowed_discount = discount
                if total_amount >= 750:
                    allowed_discount = max(allowed_discount, 5)
                final_discount = min(max(upsell_discount, discount), allowed_discount, 90)
                
                if final_discount > discount:
                    purchases = await get_user_purchases(author.id, only_unused=True)
                    found_inv = False
                    for p in purchases:
                        if p.get("type") == "discounts" and str(final_discount) in p.get("value", ""):
                            await _update_ticket_discount_embed(channel, p['value'])
                            found_inv = True
                            break
                    if not found_inv:
                        await _update_ticket_discount_embed(channel, f"Скидка {final_discount}%")

                if final_discount > 0:
                    purchases = await get_user_purchases(author.id, only_unused=True)
                    for p in purchases:
                        if p.get("type") == "discounts" and str(final_discount) in p.get("value", ""):
                            full_purchases = await get_user_purchases(author.id, only_unused=False)
                            target_idx = next((idx for idx, fp in enumerate(full_purchases) if fp["value"] == p["value"] and fp["type"] == "discounts" and not fp.get("used")), None)
                            if target_idx is not None:
                                await remove_purchase(author.id, target_idx)
                                ai_logger.info(f"Скидка {p['value']} удалена из инвентаря {author.id} (применена в счете).")
                                break

                invoice = await send_invoice(channel, product_display, total_amount, final_discount, author.display_name)
                if invoice:
                    invoice_total, invoice_order_id = invoice
                    ai_logger.info(f"Счёт: {channel.id} → {product_display} (к оплате {invoice_total} Р, скидка {final_discount}%)")
                    hist_clear(channel.id)
                    hist_append(channel.id, "ai", f"[счёт выставлен: {product_display}]")
                    update_session(
                        channel.id, invoice_sent=1, message_count=0, fail_count=0,
                        invoice_amount=invoice_total, invoice_order_id=invoice_order_id,
                        invoice_items=product_display[:500],
                        invoice_created_at=int(time.time()), receipt_attempts=0,
                    )
                    touch_ai_response(channel.id)

            elif name == "escalate_to_human":
                await escalate(channel, args.get("reason", "Товар не найден"), user_text)
                update_session(channel.id, escalated=1)
                touch_ai_response(channel.id)

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
        touch_ai_response(channel.id)
        if message.attachments:
            try: await message.add_reaction(YES_EMOJI)
            except Exception: pass
            ai_logger.info(f"Доплата принята (файл): {channel.id} {message.attachments[0].filename}")
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
        if sess and sess.get("invoice_sent"):
            await _handle_receipt(channel, message, sess)
            return
        else: return

    text = (message.content or "").strip()
    if not text: return

    state = DEBOUNCE.setdefault(channel.id, {"messages": [], "gen": 0})
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
