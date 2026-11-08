# -*- coding: utf-8 -*-
import os
import re
import json
import time
import math
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

import aiohttp
import disnake
from disnake.ext import commands, tasks

from core.utils import (
    CONFIG, DATA_DIR, logger, db, cur,
    load_json, save_json, now_ts,
    get_ticket_owner,
)
from core.catalog import load_catalog_from_db, auto_init
from modules.tickets import ReceiptView, generate_receipt_png, generate_receipt_id
from modules.commands_tickets import (
    CustomRoleSetupView, get_user_purchases, remove_purchase
)
# 👇 Импорт системы рекламы (включая новые View)
from modules.ads_system import init_ads_db, AdStartView, AdPublishConfirmView, ADS_CHANNEL_ID

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

SALES_MANAGER_ROLE = 1154757071330365490
OWNER_IDS = [796293832751972352, 1168943921171288135]
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

CATALOG_SYNONYMS = {
    "discord_nitro": ["нитро", "nitro", "нт", "дс нитро", "discord nitro", "дискорд нитро"],
    "discord_nitro_basic": ["басик", "бейсик", "базовое", "basic", "нитро басик", "нитро бейсик", "дешевое нитро", "нитро базовое", "базовая подписка"],
    "discord_nitro_gift": ["гифт", "gift", "подарочное", "подарок нитро", "нитро подарок"],
    "discord_nitro_trial": ["триал", "trial", "пробное", "пробник", "триал нитро"],
    "discord_nitro_activation": ["активация", "activation", "актив", "активировать"],
    "discord_boosts": ["буст", "бусты", "boost", "boosts", "бустик", "буст сервер", "буст канал"],
    "steam_region": ["регион steam", "смена региона", "сменить регион", "регион стим", "стим регион", "перенос региона"],
    "steam_rub": ["стим пополнение", "пополнение стим", "steam пополн", "пополнить стим", "стим рубл", "рубли стим", "steam rub", "баланс стим"],
    "tg_stars": ["звезды тг", "звёзды тг", "тг старс", "tg stars", "stars", "telegram stars", "телеграм звезды", "телеграм звёзды", "звезды телеграм", "звёзды телеграм", "тг звезды", "тг звёзды", "телега звезды", "телега звёзды", "звезда", "телега", "телеграм старс", "звезды", "звёзды"],
    "tg_acc": ["акк тг", "акк телеграм", "телеграм аккаунт", "тг аккаунт", "tg account", "аккаунт телега", "акк телега"],
    "roblox_robux": ["робукс", "robux", "рб робукс", "роблокс робукс", "робуксы", "роблокс", "рб"],
    "roblox_plus": ["роблокс плюс", "roblox plus", "роблокс премиум", "рб плюс", "плюс роблокс"],
    "spotify": ["споти", "спф", "spotify", "спотифай", "спот", "музыка споти", "спотифай подписка", "подписка музыка"],
    "gift_marker": ["подарок", "подарочек", "подарить", "подари", "другу", "друг", "подруге", "подарок другу", "хочу подарить"],
}

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
        post_invoice_text_count INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS ai_manager_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER NOT NULL,
        role TEXT NOT NULL, content TEXT NOT NULL, created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ai_hist_channel ON ai_manager_history(channel_id, id);
    CREATE TABLE IF NOT EXISTS ai_manager_user_prefs (user_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 1);
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

def _ensure_col(table: str, column: str, ddl: str):
    try:
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()]
        if column not in cols:
            cur.execute(f'ALTER TABLE "{table}" ADD COLUMN {ddl}')
            db.commit()
    except Exception as e:
        ai_logger.warning(f"Миграция {table}.{column}: {e}")

init_ai_manager_tables()
init_ads_db()

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

# ============================================================
# ИСТОРИЯ
# ============================================================
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

# ============================================================
# DEBOUNCE И АБЬЮЗ
# ============================================================
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

# ============================================================
# КАТАЛОГ И ТИКЕТЫ
# ============================================================
def get_filtered_catalog(user_text: str, full_catalog: Dict[str, dict]) -> Dict[str, dict]:
    t = user_text.lower()
    result = {}
    keywords = {
        "discord":  ["дискорд", "discord", "нитро", "nitro", "буст", "boost", "гифт", "активация"],
        "telegram": ["телега", "телеграм", "telegram", "тг", "tg", "звезд", "звёзд", "stars"],
        "steam":    ["стим", "steam", "пополнени", "регион", "рубл"],
        "roblox":   ["роблокс", "roblox", "робукс", "robux", "плюс"],
        "spotify":  ["споти", "spotify", "спф"],
        "decoration": ["украшени", "декор", "бейдж", "профиль"],
        "ads": ["реклама", "ad", "пинг", "everyone", "here", "личный канал"]
    }
    matched_cats = [cat_key for cat_key, words in keywords.items() if any(w in t for w in words)]
    if not matched_cats: return full_catalog
    for db_key, cat_data in full_catalog.items():
        for mc in matched_cats:
            if mc in db_key.lower() or mc in cat_data["label"].lower():
                result[db_key] = cat_data
                break
    return result if result else full_catalog

def find_relevant_items(user_text: str, full_catalog: Dict[str, dict]) -> List[str]:
    t = (user_text or "").lower().strip()
    result, seen = [], set()
    for item_key, words in CATALOG_SYNONYMS.items():
        for w in words:
            if w in t:
                found_ids = [it.get("id", "") for cat in full_catalog.values() for it in cat.get("items", []) if it.get("id", "").startswith(item_key)]
                for fid in found_ids:
                    if fid not in seen:
                        seen.add(fid)
                        result.append(fid)
                break
    if any(x in t for x in ["подар", "другу", "подарить"]):
        for key in ("discord_nitro_gift_basic", "discord_nitro_gift_full", "discord_nitro_gift"):
            if key not in seen and any(it.get("id") == key for cat in full_catalog.values() for it in cat.get("items")):
                seen.add(key)
                result.insert(0, key)
    return result

def build_catalog_block(user_text: str, filtered_catalog: Dict[str, dict]) -> str:
    relevant = find_relevant_items(user_text, filtered_catalog)
    parts = []
    if relevant:
        parts.append("🎯 ВОЗМОЖНО РЕЛЕВАНТНО:")
        for rid in relevant[:15]:
            for cat in filtered_catalog.values():
                for it in cat.get("items", []):
                    if it.get("id") == rid:
                        parts.append(f"  ⭐ {it['id']}: {it['name']} — {it['price']}₽" + (f" / {it['unit']}" if it.get("unit") else ""))
                        break
        parts.append("")
    parts.append("📦 ДОСТУПНЫЕ ТОВАРЫ:")
    for cat_label, cat in filtered_catalog.items():
        parts.append(f"\n[{cat_label}]")
        for it in cat.get("items", []):
            parts.append(f"  - {it['id']}: {it['name']} — {it['price']}₽" + (f" / {it['unit']}" if it.get("unit") else ""))
    return "\n".join(parts)

def _is_paid_category(channel) -> bool:
    return channel.category and channel.category.id == CONFIG.get("PAID_CATEGORY_ID")

def _is_coins_category(channel) -> bool:
    return channel.category and channel.category.id == CONFIG.get("COINS_CATEGORY_ID")

def _is_real_category(channel) -> bool:
    return channel.category and channel.category.id == CONFIG.get("TICKET_CATEGORY_ID")

def _is_ai_ticket(channel) -> bool:
    if _is_paid_category(channel): return False
    if _is_coins_category(channel): return False
    if _is_real_category(channel): return True
    return bool(get_ticket_owner(channel.id))

def _is_manager(member) -> bool:
    return member.id in OWNER_IDS or any(r.id == SALES_MANAGER_ROLE for r in getattr(member, "roles", []))

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

# ============================================================
# ПРОМПТ И ИНСТРУМЕНТЫ
# ============================================================
SYSTEM_PROMPT = """ты — ai-менеджер магазина diamond shop в discord-тикете. задача — помочь клиенту оформить заказ, как живой помощник.

ПРАВИЛА ОБЩЕНИЯ:
- Пиши коротко, по делу, как живой менеджер. Без эмодзи.
- Форматирование Discord: **жирный**, *курсив*, > цитаты, `код`.
- Товары оформляй блоком:
  > **Название** — 460 ₽
- Если клиент просит категорию без уточнений — покажи ВСЕ варианты с ценами.

ГЛАВНОЕ ПРАВИЛО ПЕРЕД СЧЁТОМ:
- НИКОГДА не вызывай create_invoice сразу после того, как клиент назвал товар.
- Сначала спроси: «Выставить счёт на <товар> за <цена>?»
- Жди явного подтверждения: «да», «ок», «выставляй», «давай», «го», «+».
- Только после подтверждения — вызывай create_invoice.

ОСОБЕННОСТЬ: РЕКЛАМА
Если пользователь купил рекламу (в истории есть слова "Реклама @everyone", "Реклама @here", "Личный канал"):
- Не пытайся выставить счёт.
- Если клиент задает вопросы, отвечай, что нужно нажать на кнопку **"Заполнить бриф"**, которая уже висит в чате.
- Если клиент уже заполнил форму (в истории есть "Предпросмотр рекламы"), отвечай, что нужно нажать "Опубликовать".

ЕСЛИ ТОВАРА НЕТ В КАТАЛОГЕ:
- НЕ уточняй, НЕ угадывай.
- Просто ответь: "Зову менеджера <@&1154757071330365490> для уточнения."
- И больше не отвечай (передай тикет менеджеру).

каталог:
{catalog}

контекст:
- клиент: {user_name}
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
                        "description": "Список товаров для счёта",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_id": {"type": "string", "description": "ID товара из каталога"},
                                "quantity": {"type": "integer", "description": "Количество", "default": 1}
                            },
                            "required": ["item_id"]
                        }
                    }
                },
                "required": ["items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "start_ad_brief",
            "description": "Вызвать форму заполнения рекламы. Используй, если куплен товар категории ads.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "Название купленного товара рекламы"}
                },
                "required": ["item_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Позвать менеджера если не можешь понять или товара нет в каталоге.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Почему эскалируешь."},
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

# ============================================================
# ОСНОВНАЯ ЛОГИКА ИИ
# ============================================================
async def escalate(channel, reason: str):
    if _is_paid_category(channel): return
    sess = get_session(channel.id)
    if sess is None: create_session(channel.id, 0)
    elif sess.get("escalated"): return
    update_session(channel.id, escalated=1)
    
    owners_ping = " | ".join(f"<@{oid}>" for oid in OWNER_IDS)
    ping = owners_ping if "BuyALL" in reason or "не найден" in reason.lower() else f"<@&{SALES_MANAGER_ROLE}>"
    
    embed = disnake.Embed(title="⚠️ Требуется помощь менеджера", description=f"> {ping}, клиент ждёт ответа.\n> **Причина:** {reason}", color=COLOR_GREY)
    embed.set_image(url=IMG_STRIPE)
    await channel.send(embed=embed)
    ai_logger.info(f"Эскалация: {channel.id} — {reason}")

async def send_invoice(channel, product_display: str, amount: int, discount: int, user_name: str) -> bool:
    try:
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
            await escalate(channel, "исчерпан лимит сообщений")
            return

        update_session(channel.id, message_count=(sess["message_count"] or 0) + 1)
        hist_append(channel.id, "user", user_text)

        discount = await get_ticket_discount(channel)
        full_catalog = load_catalog_from_db()
        if not full_catalog:
            await channel.send("⚠️ Каталог пуст.")
            return
        
        catalog_text = build_catalog_block(user_text, get_filtered_catalog(user_text, full_catalog))
        system_prompt = SYSTEM_PROMPT.format(catalog=catalog_text, user_name=author.display_name)
        history = hist_load(channel.id)
        
        async with channel.typing():
            result = await call_llm(system_prompt, history, user_text)
            
        if not result:
            new_fails = (sess["fail_count"] or 0) + 1
            update_session(channel.id, fail_count=new_fails)
            if new_fails >= SESSION_MAX_FAILS:
                await escalate(channel, "сбой LLM")
            else:
                try: await channel.send("⏳ Секунду, уточняю информацию…")
                except Exception: pass
            return

        update_session(channel.id, fail_count=0)
        text = (result.get("text") or "").strip()
        funcs = result.get("funcs") or []

        if text and "Зову менеджера" in text:
            try: await channel.send(text)
            except Exception: pass
            touch_ai_response(channel.id)
            update_session(channel.id, escalated=1)
            await escalate(channel, "Товар не найден / нужен менеджер")
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
                if not items_list and args.get("item_id"):
                    items_list = [{"item_id": args.get("item_id"), "quantity": args.get("quantity", 1)}]
                if not items_list:
                    await channel.send("⚠️ Не удалось распознать товар.")
                    return
                total_amount = 0
                receipt_names = []
                for itm in items_list:
                    item_id = itm.get("item_id")
                    quantity = max(1, int(itm.get("quantity", 1)))
                    row = cur.execute("SELECT * FROM autoorder_catalog WHERE id=?", (item_id,)).fetchone()
                    if not row:
                        await escalate(channel, f"Товар `{item_id}` не найден")
                        return
                    base_price = float(row["price"])
                    total_base = base_price * quantity
                    amount = int(total_base) if total_base % 1 == 0 else int(math.ceil(total_base))
                    total_amount += amount
                    receipt_names.append(row["name"] if quantity == 1 else f"{row['name']} × {quantity}")

                product_display = ", ".join(receipt_names)
                ok = await send_invoice(channel, product_display, total_amount, discount, author.display_name)
                if ok:
                    ai_logger.info(f"Счёт: {channel.id} → {product_display}")
                    hist_clear(channel.id)
                    hist_append(channel.id, "ai", f"[счёт выставлен: {product_display}]")
                    update_session(channel.id, invoice_sent=1, message_count=0, fail_count=0)
                    touch_ai_response(channel.id)

            elif name == "start_ad_brief":
                item_name = args.get("item_name", "Реклама")
                # Отправляем кнопку (без аргументов, т.к. мы их убрали)
                from modules.ads_system import AdStartView, build_ad_embed
                embed = build_ad_embed(item_name)
                view = AdStartView()
                await channel.send(embed=embed, view=view)
                update_session(channel.id, escalated=1)
                return

            elif name == "escalate_to_human":
                await escalate(channel, args.get("reason", "Товар не найден"))
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
    
    # 👇 Инициализация таблиц рекламы (чтобы не было no such table)
    init_ads_db()
    
    # 👇 РЕГИСТРАЦИЯ VIEW ДЛЯ ПЕРЕЗАПУСКА
    bot.add_view(AdStartView())
    bot.add_view(AdPublishConfirmView())
    
    if not _CLEANUP_STARTED:
        _CLEANUP_STARTED = True
        asyncio.create_task(_cleanup_loop())
        if not fallback_task.is_running(): fallback_task.start()
        if not activity_ping_task.is_running(): activity_ping_task.start()
        if not ads_cleanup_task.is_running(): ads_cleanup_task.start()

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

    # Если пишет менеджер — ставим ИИ на паузу
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
            await _auto_confirm_receipt(channel, message, sess)
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

async def _auto_confirm_receipt(channel, message, sess):
    user_id = sess.get("user_id") or message.author.id
    try: await message.add_reaction(YES_EMOJI)
    except Exception: pass

    paid_cat = bot.get_channel(CONFIG.get("PAID_CATEGORY_ID"))
    if paid_cat:
        try:
            await channel.edit(category=paid_cat)
            manager_role = channel.guild.get_role(SALES_MANAGER_ROLE)
            if manager_role: await channel.set_permissions(manager_role, send_messages=True, view_channel=True)
        except Exception as e: ai_logger.warning(f"auto_confirm edit category: {e}")

    update_session(channel.id, invoice_sent=0, receipt_url=message.attachments[0].url if message.attachments else "", post_invoice_text_count=0, last_ai_response_ts=int(time.time()), escalated=1)

    owners_ping = " | ".join(f"<@{oid}>" for oid in OWNER_IDS)
    embed = disnake.Embed(title="💚 Оплата принята.", description=f">>> Чек у меня, все проверил. Спасибо что выбираете нас!\n\n{owners_ping} скоро подключатся и выдадут заказ! ", color=COLOR_GREEN)
    embed.set_image(url=IMG_STRIPE)
    try: await channel.send(embed=embed)
    except Exception: pass

# ============================================================
# ФОНОВЫЕ ЗАДАЧИ (ТАСКИ)
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

def run_ai_manager():
    if not AI_MANAGER_TOKEN or not AI_MANAGER_API_KEY:
        ai_logger.error("Токены не заданы")
        raise SystemExit(1)
    try:
        bot.run(AI_MANAGER_TOKEN)
    except Exception as e:
        ai_logger.exception(f"Ошибка запуска: {e}")
        raise
