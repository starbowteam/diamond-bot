# -*- coding: utf-8 -*-
import os
import re
import json
import time
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
from modules.ads_system import ADS_CHANNEL_ID # 👈 Импорт

# ============================================================
# КОНСТАНТЫ
# ============================================================
AI_MANAGER_TOKEN = os.getenv("AI_MANAGER_TOKEN")
AI_MANAGER_API_KEY = os.getenv("AI_MANAGER_API_KEY")
AI_MANAGER_BASE_URL = os.getenv("AI_MANAGER_BASE_URL", "https://api.zveno.ai/v1").rstrip("/")

DIAMOND_AI_MODEL = "google/gemini-3-flash-preview"
LAST_RESORT_MODEL = "qwen/qwen-2.5-72b-instruct"

LLM_TIMEOUT = 30
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

COLOR_GREY = 0x676767
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aeaabe3&is=6ae95a63&hm=9f64fd7deb75b088ad88aec985099620a358aa0dde41e94db426b5a0d8b4fa36&"

# ============================================================
# ЛОГГЕР И БД
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
        if not ch: ch = await bot.fetch_channel(ch_id)
        if not ch: return
        embed = disnake.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
        await ch.send(embed=embed)
    except Exception as e: ai_logger.warning(f"log_discord: {e}")

def init_ai_manager_tables():
    cur.executescript("""
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
    """)
    db.commit()

init_ai_manager_tables()

# ============================================================
# СЕССИИ
# ============================================================
def get_session(channel_id: int) -> Optional[dict]:
    row = cur.execute("SELECT * FROM ai_manager_sessions WHERE channel_id=?", (channel_id,)).fetchone()
    return dict(row) if row else None

def create_session(channel_id: int, user_id: int):
    now = int(time.time())
    cur.execute("INSERT OR IGNORE INTO ai_manager_sessions (channel_id, user_id, message_count, fail_count, started_at, escalated, receipt_url, created_at) VALUES (?, ?, 0, 0, ?, 0, '', ?)", (channel_id, user_id, now, now))
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
    update_session(channel_id, last_manager_msg_ts=int(time.time()))

def touch_ai_response(channel_id: int):
    update_session(channel_id, last_ai_response_ts=int(time.time()))

def is_ai_muted(channel_id: int) -> bool:
    sess = get_session(channel_id)
    if not sess: return False
    lmt = sess.get("last_manager_msg_ts") or 0
    if not lmt: return False
    return (int(time.time()) - lmt) < MANAGER_SILENCE_SEC

def hist_load(channel_id: int, limit: int = HISTORY_MAX_MSG):
    cutoff = int(time.time()) - HISTORY_TTL_SEC
    rows = cur.execute("SELECT role, content FROM ai_manager_history WHERE channel_id=? AND created_at >= ? ORDER BY id DESC LIMIT ?", (channel_id, cutoff, limit)).fetchall()
    return [(r["role"], r["content"]) for r in reversed(rows)]

def hist_append(channel_id: int, role: str, content: str):
    if not content: return
    cur.execute("INSERT INTO ai_manager_history (channel_id, role, content, created_at) VALUES (?,?,?,?)", (channel_id, role, content[:2000], int(time.time())))
    db.commit()

# ============================================================
# LLM SYSTEM PROMPT (ОБНОВЛЕН)
# ============================================================
SYSTEM_PROMPT = """ты — ai-менеджер магазина diamond shop в discord-тикете.

ПРАВИЛА ОБЩЕНИЯ:
- Пиши коротко, по делу.
- Товары оформляй блоком: > **Название** — 460 ₽
- Не выставляй счет, пока не спросишь «Выставить счёт?» и не получишь «да».

ВАЖНО: СПЕЦИАЛЬНЫЕ ТИКЕТЫ
Если ты видишь в истории сообщений слова "Оформление рекламы" или "Настройка кастомной роли":
- НЕ пытайся выставить счет.
- НЕ вызывай start_ad_brief (форма уже висит в чате).
- Просто отвечай на вопросы клиента, если они есть. Если вопросов нет — молчи.

каталог:
{catalog}

контекст:
- клиент: {user_name}
"""

# ============================================================
# БОТ И ОБРАБОТКА
# ============================================================
intents = disnake.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!am", intents=intents)

async def call_llm(system_prompt: str, history: list, user_msg: str) -> Optional[dict]:
    if not AI_MANAGER_API_KEY: return None
    messages = [{"role": "assistant" if r == "ai" else "user", "content": t} for r, t in history]
    messages.append({"role": "user", "content": user_msg})
    
    payload = {"model": DIAMOND_AI_MODEL, "messages": [{"role": "system", "content": system_prompt}] + messages, "temperature": 0.1, "max_tokens": 800}
    url = f"{AI_MANAGER_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {AI_MANAGER_API_KEY}", "Content-Type": "application/json"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                return {"text": text}
    except Exception: return None

async def _handle_dialog(channel, author, user_text: str):
    if not user_text.strip(): return
    lock = asyncio.Lock() # В реальном коде используй get_lock(channel.id)
    async with lock:
        sess = get_session(channel.id)
        if not sess:
            create_session(channel.id, author.id)
            sess = get_session(channel.id)
        
        if sess.get("escalated") or sess.get("invoice_sent"): return
        if is_ai_muted(channel.id): return

        update_session(channel.id, message_count=(sess["message_count"] or 0) + 1)
        hist_append(channel.id, "user", user_text)

        catalog_text = "каталог загружен..." 
        system_prompt = SYSTEM_PROMPT.format(catalog=catalog_text, user_name=author.display_name)
        
        history = hist_load(channel.id)
        async with channel.typing():
            result = await call_llm(system_prompt, history, user_text)
            
        if result and result.get("text"):
            await channel.send(result["text"])
            hist_append(channel.id, "ai", result["text"])
            touch_ai_response(channel.id)

# ============================================================
# ФОНОВЫЕ ЗАДАЧИ (УДАЛЕНИЕ РЕКЛАМЫ)
# ============================================================
@tasks.loop(minutes=1)
async def ads_cleanup_task():
    try:
        now = int(time.time())
        rows = cur.execute("SELECT id, channel_id, message_id, is_personal FROM active_ads WHERE expires_at > 0 AND expires_at <= ?", (now,)).fetchall()
        for r in rows:
            cid, mid, is_personal = r["channel_id"], r["message_id"], r["is_personal"]
            ch = bot.get_channel(cid)
            if ch:
                try:
                    if is_personal: await ch.delete(reason="Срок аренды истек")
                    else: await (await ch.fetch_message(mid)).delete()
                except Exception as e: ai_logger.warning(f"Ошибка удаления: {e}")
            cur.execute("DELETE FROM active_ads WHERE id=?", (r["id"],))
            db.commit()
            ai_logger.info(f"🧹 Реклама ID={r['id']} удалена.")
    except Exception as e: ai_logger.exception(f"Ошибка в ads_cleanup_task: {e}")

@bot.event
async def on_ready():
    auto_init()
    if not ads_cleanup_task.is_running(): ads_cleanup_task.start()
    ai_logger.info("AI Manager готов.")

@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot or not isinstance(message.channel, disnake.TextChannel): return
    
    # Игнорируем тикеты, чтобы ИИ не спамил, если клиент просто нажимает кнопки
    if message.channel.category_id in [CONFIG.get("TICKET_CATEGORY_ID"), CONFIG.get("COINS_CATEGORY_ID"), CONFIG.get("PAID_CATEGORY_ID")]:
        touch_client_msg(message.channel.id, message.author.id)
        # Запускаем ИИ только если это не кнопка/модалка, а реальный текст
        if not message.content.startswith("/") and len(message.content) > 2:
            asyncio.create_task(_handle_dialog(message.channel, message.author, message.content))
        return

def run_ai_manager():
    if not AI_MANAGER_TOKEN: raise SystemExit(1)
    bot.run(AI_MANAGER_TOKEN)
