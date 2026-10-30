# -*- coding: utf-8 -*-
"""
AI Manager v2.7 — умный менеджер тикетов Diamond Shop.
Фикс: последовательный тест моделей с задержкой, фильтрация embedding/safety, правильный лог.
"""
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
    load_json, save_json, now_ts, log_discord,
    get_ticket_owner,
)
from core.catalog import load_catalog_from_db, auto_init
from modules.tickets import ReceiptView, generate_receipt_png, generate_receipt_id

# ============================================================
# КОНСТАНТЫ
# ============================================================
AI_MANAGER_TOKEN = os.getenv("AI_MANAGER_TOKEN")
AI_MANAGER_API_KEY = os.getenv("AI_MANAGER_API_KEY")
AI_MANAGER_BASE_URL = os.getenv("AI_MANAGER_BASE_URL", "https://api.zveno.ai/v1").rstrip("/")
# Дефолтная модель на случай, если все бесплатные откажут
AI_MANAGER_MODEL = os.getenv("AI_MANAGER_MODEL", "qwen/qwen-2.5-72b-instruct")

LLM_TIMEOUT = 30
ABUSE_TIMEOUT = 10

SALES_MANAGER_ROLE = 1154757071330365490
OWNER_ID = 796293832751972352
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
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"

ABUSE_WORDS = [
    "хуй", "хуя", "хуе", "хуи", "пизд", "бляд", "блят", "ебан", "ебал", "ебат",
    "сука", "суки", "нахуй", "нахер", "заткнись", "тупой", "тупая", "идиот",
    "дебил", "дебилы", "мразь", "гандо", "пидо", "педик", "долбоеб", "мудак",
]

# ============================================================
# СИНОНИМЫ КАТАЛОГА
# ============================================================
CATALOG_SYNONYMS: Dict[str, List[str]] = {
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

# ============================================================
# БД
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
            ai_logger.info(f"Миграция: {table}.{column} добавлена")
    except Exception as e:
        ai_logger.warning(f"Миграция {table}.{column}: {e}")

init_ai_manager_tables()

# ============================================================
# НАСТРОЙКИ
# ============================================================
def get_setting(key: str, default: str = "") -> str:
    row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    db.commit()

def get_user_ai_pref(user_id: int) -> bool:
    row = cur.execute("SELECT enabled FROM ai_manager_user_prefs WHERE user_id=?", (user_id,)).fetchone()
    return bool(row["enabled"]) if row else True

def set_user_ai_pref(user_id: int, enabled: bool):
    cur.execute("INSERT OR REPLACE INTO ai_manager_user_prefs (user_id, enabled) VALUES (?, ?)", (user_id, 1 if enabled else 0))
    db.commit()

# ============================================================
# СЕССИИ
# ============================================================
def get_session(channel_id: int) -> Optional[dict]:
    row = cur.execute("SELECT * FROM ai_manager_sessions WHERE channel_id=?", (channel_id,)).fetchone()
    return dict(row) if row else None

def create_session(channel_id: int, user_id: int):
    now = int(time.time())
    cur.execute(
        "INSERT OR IGNORE INTO ai_manager_sessions "
        "(channel_id, user_id, message_count, fail_count, started_at, escalated, "
        " receipt_url, created_at, stub_sent, invoice_sent, "
        " last_client_msg_ts, last_manager_msg_ts, last_ai_response_ts, post_invoice_text_count) "
        "VALUES (?, ?, 0, 0, ?, 0, '', ?, 0, 0, 0, 0, 0, 0)",
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
    rows = cur.execute(
        "SELECT role, content, created_at FROM ai_manager_history "
        "WHERE channel_id=? AND created_at >= ? ORDER BY id DESC LIMIT ?",
        (channel_id, cutoff, limit),
    ).fetchall()
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
# DEBOUNCE
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

# ============================================================
# ПРОВЕРКА НА АБЬЮЗ
# ============================================================
def is_potential_abuse(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in ABUSE_WORDS)

async def check_abuse_llm(messages: List[str]) -> Tuple[bool, str]:
    if not AI_MANAGER_API_KEY: return False, ""
    sample = "\n".join(f"- {m[:200]}" for m in messages[:5])
    prompt = f"Проанализируй последние сообщения клиента:\n{sample}\n\nОтветь РОВНО ОДНИМ словом:\n- ABUSE — мат, оскорбления\n- SPAM — флуд\n- NORMAL — нормальный клиент\n"
    payload = {"model": AI_MANAGER_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 10}
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
        embed = disnake.Embed(title="🚫 Тикет закрыт автоматически", description=f"> **Причина:** {'неадекватное поведение' if reason == 'abuse' else 'спам / флуд'}\n> **Что дальше:** вы можете открыть новый тикет, если это ошибка.", color=0xed4245)
        await channel.send(embed=embed)
        await asyncio.sleep(5)
        await channel.delete(reason=f"AI: {reason}")
        ai_logger.warning(f"🤖 AI закрыл тикет {channel.id} по причине {reason}")
        await log_discord(title=f"🚫 AI закрыл тикет ({reason})", description=f"> **Канал:** `{channel.name}` (`{channel.id}`)\n> **Клиент:** <@{user_id}>\n> **Причина:** {reason}", color=0xed4245, channel_id=LOG_CHANNEL)
        try:
            guild = channel.guild; member = guild.get_member(user_id)
            if member: await member.send(f"🚫 **Тикет закрыт автоматически**\n> **Причина:** {'неадекватное поведение' if reason == 'abuse' else 'спам / флуд'}")
        except Exception: pass
    except disnake.Forbidden:
        await escalate(channel, f"Обнаружен {reason}, но AI не имеет прав удалить канал")
    except Exception as e: ai_logger.exception(f"close_ticket_abuse: {e}")

# ============================================================
# ФИЛЬТРАЦИЯ КАТАЛОГА
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
        "decoration": ["украшени", "декор", "бейдж", "профиль"]
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
                    if fid not in seen: seen.add(fid); result.append(fid)
                break
    if any(x in t for x in ["подар", "другу", "подарить"]):
        for key in ("discord_nitro_gift_basic", "discord_nitro_gift_full", "discord_nitro_gift"):
            if key not in seen and any(it.get("id") == key for cat in full_catalog.values() for it in cat.get("items", [])):
                seen.add(key); result.insert(0, key)
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

# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _is_paid_category(channel) -> bool:
    return channel.category and channel.category.id == CONFIG.get("PAID_CATEGORY_ID")

def _is_ai_ticket(channel) -> bool:
    if _is_paid_category(channel): return False
    return bool(get_ticket_owner(channel.id)) or (channel.category and channel.category.id == CONFIG.get("TICKET_CATEGORY_ID"))

def _is_manager(member) -> bool:
    return member.id == OWNER_ID or any(r.id == SALES_MANAGER_ROLE for r in getattr(member, "roles", []))

async def get_ticket_discount(channel) -> int:
    try:
        async for msg in channel.history(limit=50):
            if msg.author.bot and msg.embeds and len(msg.embeds) >= 2:
                for field in msg.embeds[1].fields:
                    if "скидка" in field.name.lower():
                        val = field.value.strip("`\n ")
                        if val in ("", "Не активирована", "Не введён", "Не активирован"): return 0
                        m = re.search(r"(\d+)", val)
                        return int(m.group(1)) if m else 10
    except Exception: pass
    return 0

async def send_invoice(channel, product_display: str, amount: int, discount: int, user_name: str) -> bool:
    try:
        order_id = generate_receipt_id()
        buf = await asyncio.to_thread(generate_receipt_png, manager_name="AI Manager", customer_name=user_name or "Клиент", product_name=product_display, amount=amount, discount_percent=int(discount), order_id=order_id)
        file = disnake.File(buf, filename=f"receipt_{order_id}.png")
        total = amount - int(amount * discount / 100)
        embed = disnake.Embed(title=f"Счёт для оплаты: к оплате {total} ₽", description=f"> **Товары:** {product_display}\n> **Сумма:** `{amount} ₽`" + (f"\n> **Скидка:** `{discount}%`" if discount else "") + "\n\n> Проверьте реквизиты и пришлите чек в этот канал.", color=COLOR_GREY)
        embed.set_image(url=f"attachment://receipt_{order_id}.png")
        await channel.send(embed=embed, file=file, view=ReceiptView())
        return True
    except Exception as e: ai_logger.exception(f"send_invoice: {e}"); return False

async def escalate(channel, reason: str):
    if _is_paid_category(channel): return
    sess = get_session(channel.id)
    if sess is None: create_session(channel.id, 0)
    elif sess.get("escalated"): return
    update_session(channel.id, escalated=1)
    ping = f"<@{OWNER_ID}>" if "BuyALL" in reason or "не найден" in reason.lower() else f"<@&{SALES_MANAGER_ROLE}>"
    embed = disnake.Embed(title="⚠️ Требуется помощь менеджера", description=f"> {ping}, клиент ждёт ответа.\n> **Причина:** {reason}", color=COLOR_GREY)
    embed.set_image(url=IMG_STRIPE)
    await channel.send(embed=embed)
    ai_logger.info(f"Эскалация: {channel.id} — {reason}")

async def notify_managers_dm(message, file_url):
    guild = message.guild
    if not guild: return
    role = guild.get_role(SALES_MANAGER_ROLE)
    if not role: return
    embed = disnake.Embed(title="💳 Новый чек на проверку!", description=f"> **Тикет:** {message.channel.mention}\n> **Пользователь:** {message.author.mention} (`{message.author.id}`)\n> **Ссылка:** [открыть]({file_url})", color=COLOR_GREY, timestamp=datetime.now(timezone.utc))
    embed.set_image(url=file_url)
    for member in role.members:
        if not member.bot:
            try: await member.send(embed=embed)
            except Exception: pass

# ============================================================
# ЛУЧШАЯ МОДЕЛЬ (АВТО-ТЕСТ С ЗАДЕРЖКОЙ)
# ============================================================
BEST_MODEL: Optional[str] = None

def is_chat_model(model_id: str) -> bool:
    mid = model_id.lower()
    # Исключаем эмбеддинги, модерацию и прочий мусор
    if any(x in mid for x in ["embed", "safety", "moderation", "guard"]):
        return False
    # Исключаем слишком маленькие (глупые) модели, если есть выбор
    if "0.5b" in mid or "1b" in mid or "1.5b" in mid:
        return False
    return True

async def select_fastest_model():
    global BEST_MODEL
    ai_logger.info("⏳ Начинаю тестирование бесплатных моделей ZvenoAI...")
    url = f"{AI_MANAGER_BASE_URL}/models"
    headers = {"Authorization": f"Bearer {AI_MANAGER_API_KEY}"}
    free_models = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for m in data.get("data", []):
                        mid = m.get("id", "")
                        if (":free" in mid or "free" in m.get("name", "").lower()) and is_chat_model(mid):
                            free_models.append(mid)
                else:
                    ai_logger.warning(f"Не удалось получить список моделей: HTTP {resp.status}")
    except Exception as e:
        ai_logger.warning(f"Ошибка при получении списка моделей: {e}")

    if not free_models:
        ai_logger.warning("Не найдено подходящих бесплатных моделей, использую дефолтную.")
        BEST_MODEL = AI_MANAGER_MODEL
        return

    # Сортируем приоритетно, чтобы в первую очередь тестить самые мощные
    priority_keywords = ["ultra", "gemma", "nemotron-3.5-super", "lagoon", "dots", "flint"]
    free_models.sort(key=lambda m: any(kw in m.lower() for kw in priority_keywords), reverse=True)

    results = []
    url = f"{AI_MANAGER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {AI_MANAGER_API_KEY}", "Content-Type": "application/json"}
    
    # Тестируем первые 4 модели по очереди
    for model_id in free_models[:4]:
        payload = {"model": model_id, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5, "temperature": 0}
        start_time = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        latency = (time.time() - start_time) * 1000
                        results.append((model_id, latency, "OK"))
                    else:
                        err_text = await resp.text()
                        results.append((model_id, -1, f"HTTP {resp.status}: {err_text[:50]}"))
        except Exception as e:
            results.append((model_id, -1, str(e)[:50]))
        
        # ЖДЕМ 2 СЕКУНДЫ МЕЖДУ ТЕСТАМИ, ЧТОБЫ ИЗБЕЖАТЬ 429
        await asyncio.sleep(2.0)

    # Сортируем по скорости (сначала успешные)
    valid_results = [r for r in results if r[1] > 0]
    if valid_results:
        valid_results.sort(key=lambda x: x[1])
        BEST_MODEL = valid_results[0][0]
        ai_logger.info(f"🏆 Выбрана самая быстрая модель: {BEST_MODEL} ({valid_results[0][1]:.0f} ms)")
    else:
        BEST_MODEL = AI_MANAGER_MODEL
        ai_logger.warning(f"❌ Все бесплатные модели недоступны (429/ошибка), использую дефолт: {BEST_MODEL}")

    # Красивый лог результатов
    log_msg = ["\n📊 Результаты тестирования моделей:"]
    for m, lat, status in results:
        lat_str = f"{lat:.0f} ms" if lat > 0 else status
        log_msg.append(f"  {'⭐' if m == BEST_MODEL else '  '} {m}: {lat_str}")
    ai_logger.info("\n".join(log_msg))

# ============================================================
# LLM
# ============================================================
SYSTEM_PROMPT = """ты — ai-менеджер магазина diamond shop в discord-тикете. задача — помочь клиенту оформить заказ.

ПРАВИЛА ОБЩЕНИЯ:
- Говори коротко и по делу.
- КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать точки или звездочки (-, *) для списков!
- ИСПОЛЬЗУЙ ТОЛЬКО нумерованные списки (1., 2., 3.) или эмодзи (🔹, 🔸).
- Для группировки товаров используй **жирный шрифт** (например, **Full Nitro:**).
- Для цитат и выделения блоков используй > (например, > **Цена:** 460₽).
- Если клиент просит категорию (например, "нитро", "звезды") без уточнений — СРАЗУ выведи красивый структурированный список ВСЕХ доступных вариантов с ценами.
- Если просит несколько товаров из разных категорий (например, "нитро и 100 звезд") — передай их все в массиве `items` функции create_invoice.

💡 ПАМЯТКА ПО НИТРО (Full и Basic):
1. Nitro Trial 1 Month — **Full**.
2. Nitro 1 Month — **Full**.
3. Nitro Basic 1 Month — **Basic**.
4. Nitro Gift Basic — **Basic**.
5. Nitro Gift Full — **Full**.
6. Nitro 12 Month — **Full**.
7. Nitro Basic 12 Month — **Basic**.
8. Nitro Activation — подходит **И к Full, И к Basic**. Спроси, если непонятно.
9. Nitro Trial 3 Month — **Full**.

- Если клиент говорит "басик", "бейсик" — предлагай позиции 3, 4, 7.
- Если клиент говорит "фулл" — предлагай позиции 1, 2, 5, 6, 9.
- НИКОГДА не подсовывай товар из другой категории!

каталог:
{catalog}

контекст:
- клиент: {user_name}
- скидка в тикете: {discount}%
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

async def call_llm(system_prompt: str, history: list, user_msg: str) -> Optional[dict]:
    if not AI_MANAGER_API_KEY: return None
    model = BEST_MODEL or AI_MANAGER_MODEL
    messages = [{"role": "system", "content": system_prompt}]
    for role, text in history[-HISTORY_MAX_MSG:]:
        messages.append({"role": "assistant" if role == "ai" else "user", "content": text})
    messages.append({"role": "user", "content": user_msg})
    payload = {"model": model, "messages": messages, "tools": TOOLS_OPENAI, "tool_choice": "auto", "temperature": 0.1, "max_tokens": 800}
    url = f"{AI_MANAGER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {AI_MANAGER_API_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT)) as resp:
                if resp.status != 200:
                    ai_logger.warning(f"LLM HTTP {resp.status}")
                    return None
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
    except asyncio.TimeoutError:
        ai_logger.warning("LLM timeout")
        return None
    except Exception as e:
        ai_logger.exception(f"LLM error: {e}")
        return None

# ============================================================
# БОТ
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
    ai_logger.info(f"AI Manager v2.7 запущен. Каталог: {count}")
    asyncio.create_task(select_fastest_model())

    if not _CLEANUP_STARTED:
        _CLEANUP_STARTED = True
        asyncio.create_task(_cleanup_loop())
        if not fallback_task.is_running():
            fallback_task.start()

async def _cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        try:
            cutoff = int(time.time()) - 7 * 86400
            cur.execute("DELETE FROM ai_manager_sessions WHERE created_at < ?", (cutoff,))
            cur.execute("DELETE FROM ai_manager_history WHERE created_at < ?", (cutoff,))
            db.commit()
            ai_logger.info("Cleanup: старые сессии/история удалены")
        except Exception: ai_logger.exception("cleanup")

@tasks.loop(minutes=1)
async def fallback_task():
    await bot.wait_until_ready()
    now = int(time.time())
    rows = cur.execute("""
        SELECT channel_id, user_id, last_client_msg_ts, last_ai_response_ts,
               last_manager_msg_ts, invoice_sent, fail_count, abuse_closed
        FROM ai_manager_sessions
        WHERE last_client_msg_ts > 0 AND invoice_sent = 0 AND abuse_closed = 0 AND fail_count < 3
    """).fetchall()
    for r in rows:
        channel_id = r["channel_id"]
        if (r["last_ai_response_ts"] or 0) >= (r["last_client_msg_ts"] or 0): continue
        if r["last_manager_msg_ts"] and (now - r["last_manager_msg_ts"]) < MANAGER_SILENCE_SEC: continue
        if (now - (r["last_client_msg_ts"] or 0)) > CLIENT_MAX_SILENCE_SEC: continue
        if not get_user_ai_pref(r["user_id"]) and (now - (r["last_client_msg_ts"] or 0)) < FALLBACK_WAIT_SEC: continue
        channel = bot.get_channel(channel_id)
        if not channel or not _is_ai_ticket(channel): continue
        try:
            if await _check_and_close_abuse(channel, r["user_id"]): continue
        except Exception: pass
        last_text = hist_last_client_msg(channel_id)
        if not last_text: continue
        try: await channel.send("⏳ Подключаюсь, секунду…")
        except Exception: pass
        try:
            member = channel.guild.get_member(r["user_id"])
            if member: await _handle_dialog(channel, member, last_text, is_fallback=True)
        except Exception as e: ai_logger.exception(f"fallback dialog: {e}")

async def _handle_dialog(channel, author, user_text: str, is_fallback: bool = False):
    if not user_text.strip() or _is_paid_category(channel): return
    user_id = author.id
    sess = get_session(channel.id)
    if not sess:
        create_session(channel.id, user_id); sess = get_session(channel.id)
    try:
        if await _check_and_close_abuse(channel, user_id): return
    except Exception: pass
    if is_ai_muted(channel.id): return
    if sess["message_count"] >= SESSION_MAX_MESSAGES:
        await escalate(channel, "исчерпан лимит сообщений"); return
    if sess["message_count"] == SESSION_MAX_MESSAGES - 2:
        try: await channel.send("ℹ️ Скоро подключится менеджер.")
        except Exception: pass
    update_session(channel.id, message_count=(sess["message_count"] or 0) + 1)
    hist_append(channel.id, "user", user_text)
    discount = await get_ticket_discount(channel)
    full_catalog = load_catalog_from_db()
    if not full_catalog:
        await channel.send("⚠️ Каталог пуст."); return
    catalog_text = build_catalog_block(user_text, get_filtered_catalog(user_text, full_catalog))
    system_prompt = SYSTEM_PROMPT.format(catalog=catalog_text, user_name=author.display_name, discount=discount)
    history = hist_load(channel.id)
    async with channel.typing():
        result = await call_llm(system_prompt, history, user_text)
    if not result:
        new_fails = (sess["fail_count"] or 0) + 1
        update_session(channel.id, fail_count=new_fails)
        if new_fails >= SESSION_MAX_FAILS: await escalate(channel, "сбой LLM")
        else:
            try: await channel.send("⏳ Секунду, уточняю информацию…")
            except Exception: pass
        return
    update_session(channel.id, fail_count=0)
    text = (result.get("text") or "").strip()
    funcs = result.get("funcs") or []
    if text and not funcs:
        try: await channel.send(text)
        except Exception: pass
        hist_append(channel.id, "ai", text)
    touch_ai_response(channel.id)
    if funcs:
        fc = funcs[0]; name = fc["name"]; args = fc.get("args", {})
        if name == "create_invoice":
            items_list = args.get("items", [])
            if not items_list and args.get("item_id"):
                items_list = [{"item_id": args.get("item_id"), "quantity": args.get("quantity", 1)}]
            if not items_list:
                await channel.send("⚠️ Не удалось распознать товар."); return
            total_amount = 0; receipt_names = []
            for itm in items_list:
                item_id = itm.get("item_id")
                quantity = max(1, int(itm.get("quantity", 1)))
                row = cur.execute("SELECT * FROM autoorder_catalog WHERE id=?", (item_id,)).fetchone()
                if not row:
                    await escalate(channel, f"Товар `{item_id}` не найден"); return
                base_price = float(row["price"]); total_base = base_price * quantity
                amount = int(total_base) if total_base % 1 == 0 else int(math.ceil(total_base))
                total_amount += amount
                receipt_names.append(row["name"] if quantity == 1 else f"{row['name']} × {quantity}")
            product_display = ", ".join(receipt_names)
            ok = await send_invoice(channel, product_display, total_amount, discount, author.display_name)
            if ok:
                ai_logger.info(f"Счёт: {channel.id} → {product_display}")
                hist_clear(channel.id)
                hist_append(channel.id, "ai", f"[счёт выставлен: {product_display}]")
                update_session(channel.id, invoice_sent=1, post_invoice_text_count=0, message_count=0, fail_count=0)
        elif name == "escalate_to_human":
            await escalate(channel, args.get("reason", "Товар не найден"))

@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot or not isinstance(message.channel, disnake.TextChannel): return
    channel = message.channel
    if _is_paid_category(channel): return
    owner_id = get_ticket_owner(channel.id)
    is_ticket_owner = (owner_id is not None and message.author.id == owner_id)
    if isinstance(message.author, disnake.Member) and _is_manager(message.author) and not is_ticket_owner:
        if _is_ai_ticket(channel):
            sess = get_session(channel.id)
            if sess is None: create_session(channel.id, message.author.id)
            touch_manager_msg(channel.id)
            ai_logger.info(f"Менеджер активен в тикете {channel.id} — AI молчит 5 мин")
            DEBOUNCE.pop(channel.id, None)
        return
    if not _is_ai_ticket(channel): return
    if owner_id and not is_ticket_owner: return
    touch_client_msg(channel.id, message.author.id)
    if message.attachments:
        sess = get_session(channel.id)
        if not sess or not sess.get("invoice_sent"):
            try: await message.reply("📋 Сначала оформим заказ.", mention_author=False)
            except Exception: pass
            return
        att = message.attachments[0]; low = att.filename.lower()
        if not any(low.endswith(x) for x in (".png", ".jpg", ".jpeg", ".pdf")):
            try: await message.reply("📎 Пришлите чек как картинку или PDF.", mention_author=False)
            except Exception: pass
            return
        if sess.get("receipt_url"):
            try: await message.reply("⚠️ Вы уже прислали чек, ожидайте проверки.", mention_author=False)
            except Exception: pass
            await escalate(channel, "Клиент прислал второй чек"); update_session(channel.id, invoice_sent=0); return
        update_session(channel.id, receipt_url=att.url, invoice_sent=0)
        embed = disnake.Embed(title="✅ Чек получен", description=f"> <@&{SALES_MANAGER_ROLE}> — заказ готов к проверке.\n> 🤖 Я постараюсь в будущем понять данные методики тикетов.", color=COLOR_GREY)
        embed.set_image(url=IMG_STRIPE)
        await channel.send(embed=embed)
        asyncio.create_task(notify_managers_dm(message, att.url))
        return
    text = (message.content or "").strip()
    if not text: return
    sess = get_session(channel.id)
    if sess and sess.get("invoice_sent"):
        count = (sess.get("post_invoice_text_count") or 0) + 1
        if count >= 2:
            hist_clear(channel.id)
            update_session(channel.id, invoice_sent=0, post_invoice_text_count=0, receipt_url="")
            try: await channel.send("🔄 Понял, старый счёт отменён. Слушаю заказ заново.")
            except Exception: pass
        else:
            update_session(channel.id, post_invoice_text_count=count)
    state = DEBOUNCE.setdefault(channel.id, {"messages": [], "gen": 0})
    state["messages"].append(text); state["gen"] += 1
    asyncio.create_task(_debounce_flush(channel, message.author, state["gen"]))

def run_ai_manager():
    if not AI_MANAGER_TOKEN or not AI_MANAGER_API_KEY:
        ai_logger.error("Токены не заданы"); raise SystemExit(1)
    try: bot.run(AI_MANAGER_TOKEN)
    except Exception as e: ai_logger.exception(f"Ошибка запуска: {e}"); raise
