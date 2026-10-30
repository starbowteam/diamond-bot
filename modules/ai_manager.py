# -*- coding: utf-8 -*-
"""
AI Manager — третий бот. Ведёт диалог в тикетах, создаёт счёты, ловит чеки.
Тумблер ON/OFF живёт в основной БД (settings), читается на каждом сообщении.
"""
import os
import re
import json
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict

import aiohttp
import disnake
from disnake.ext import commands
from disnake import PartialEmoji, ButtonStyle
from disnake.ui import Button, View

from core.utils import (
    CONFIG, DATA_DIR, logger, db, cur,
    load_json, save_json, now_ts, log_discord,
    get_ticket_owner,
)

# ============================================================
# КОНСТАНТЫ
# ============================================================
AI_MANAGER_TOKEN = os.getenv("AI_MANAGER_TOKEN")
GEMINI_API_KEY = os.getenv("MISTRAL_API_KEY")
GEMINI_MODEL = "gemini-flash-latest"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

SALES_MANAGER_ROLE = 1154757071330365490
LOG_CHANNEL = 1530453871581855744

SESSION_MAX_MESSAGES = 20
SESSION_COOLDOWN_SEC = 3
SESSION_MAX_FAILS = 3

COLOR_GREY = 0x676767
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"

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
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE IF NOT EXISTS autoorder_catalog (
        id        TEXT PRIMARY KEY,
        category  TEXT,
        name      TEXT,
        price     REAL,
        unit      TEXT,
        min_qty   INTEGER DEFAULT 1,
        max_qty   INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS ai_manager_sessions (
        channel_id     INTEGER PRIMARY KEY,
        user_id        INTEGER,
        message_count  INTEGER DEFAULT 0,
        fail_count     INTEGER DEFAULT 0,
        started_at     INTEGER,
        escalated      INTEGER DEFAULT 0,
        receipt_url    TEXT,
        created_at     INTEGER
    );
    """)
    db.commit()

init_ai_manager_tables()


# ============================================================
# SETTINGS
# ============================================================
def get_setting(key: str, default: str = "") -> str:
    row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    db.commit()


def is_ai_enabled() -> bool:
    return get_setting("ai_manager_enabled", "0") == "1"


# ============================================================
# КАТАЛОГ
# ============================================================
def load_catalog_from_db() -> Dict[str, dict]:
    rows = cur.execute(
        "SELECT * FROM autoorder_catalog ORDER BY category, name"
    ).fetchall()
    result: Dict[str, dict] = {}
    for r in rows:
        cat = r["category"]
        if cat not in result:
            result[cat] = {"label": cat, "items": []}
        result[cat]["items"].append({
            "id": r["id"], "name": r["name"], "price": r["price"],
            "unit": r["unit"], "min": r["min_qty"], "max": r["max_qty"],
        })
    return result


def reload_catalog_from_json() -> int:
    path = os.path.join(DATA_DIR, "autoorder_catalog.json")
    if not os.path.exists(path):
        ai_logger.warning(f"Каталог не найден: {path}")
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        ai_logger.exception(f"Ошибка чтения каталога: {e}")
        return 0

    cur.execute("DELETE FROM autoorder_catalog")
    count = 0
    for cat_key, cat in data.items():
        label = cat.get("label", cat_key)
        for item in cat.get("items", []):
            cur.execute(
                "INSERT INTO autoorder_catalog (id, category, name, price, unit, min_qty, max_qty) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item["id"], label, item["name"], float(item["price"]),
                 item.get("unit"), int(item.get("min", 1)), int(item.get("max", 1))),
            )
            count += 1
    db.commit()
    ai_logger.info(f"Каталог загружен: {count} товаров")
    return count


# ============================================================
# СЕССИИ
# ============================================================
def get_session(channel_id: int) -> Optional[dict]:
    row = cur.execute(
        "SELECT * FROM ai_manager_sessions WHERE channel_id=?", (channel_id,)
    ).fetchone()
    return dict(row) if row else None


def create_session(channel_id: int, user_id: int):
    cur.execute(
        "INSERT OR REPLACE INTO ai_manager_sessions "
        "(channel_id, user_id, message_count, fail_count, started_at, escalated, receipt_url, created_at) "
        "VALUES (?, ?, 0, 0, ?, 0, '', ?)",
        (channel_id, user_id, int(time.time()), int(time.time())),
    )
    db.commit()


def update_session(channel_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs.keys())
    values = list(kwargs.values()) + [channel_id]
    cur.execute(f"UPDATE ai_manager_sessions SET {fields} WHERE channel_id=?", values)
    db.commit()


# ============================================================
# ИСТОРИЯ / КУЛДАУН
# ============================================================
HISTORY: Dict[int, list] = {}
COOLDOWN: Dict[int, float] = {}


# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _is_ai_ticket(channel) -> bool:
    if get_ticket_owner(channel.id):
        return True
    try:
        if channel.category and channel.category.id in (
            CONFIG.get("TICKET_CATEGORY_ID"),
            CONFIG.get("PAID_CATEGORY_ID"),
        ):
            return True
    except Exception:
        pass
    return False


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
                        if m:
                            return int(m.group(1))
                        return 10
    except Exception:
        pass
    return 0


async def send_invoice(channel, item: dict, discount: int, user_name: str) -> bool:
    try:
        from modules.tickets import generate_receipt_png, generate_receipt_id
        amount = int(round(float(item["price"])))
        order_id = generate_receipt_id()
        buf = await asyncio.to_thread(
            generate_receipt_png,
            manager_name="AI Manager",
            customer_name=user_name or "Клиент",
            product_name=item["name"],
            amount=amount,
            discount_percent=int(discount),
            order_id=order_id,
        )
        file = disnake.File(buf, filename=f"receipt_{order_id}.png")
        total = amount - int(amount * discount / 100)
        embed = disnake.Embed(
            title=f"Счёт для оплаты: к оплате {total} ₽",
            description=(
                f"> **Категория:** {item.get('category', '—')}\n"
                f"> **Товар:** {item['name']}\n"
                f"> **Сумма:** `{amount} ₽`"
                + (f"\n> **Скидка:** `{discount}%`" if discount else "")
                + "\n\n> Проверьте реквизиты и пришлите чек в этот канал."
            ),
            color=COLOR_GREY,
        )
        embed.set_image(url=f"attachment://receipt_{order_id}.png")
        await channel.send(embed=embed, file=file)
        return True
    except Exception as e:
        ai_logger.exception(f"send_invoice: {e}")
        return False


async def escalate(channel, reason: str):
    sess = get_session(channel.id)
    if sess and sess["escalated"]:
        return
    if sess:
        update_session(channel.id, escalated=1)

    await channel.send(
        f"> <@&{SALES_MANAGER_ROLE}> — нужна помощь.\n"
        f"> **Причина:** {reason}\n"
        f"> 🤖 Я постараюсь в будущем понять данные методики тикетов."
    )
    await log_discord(
        title="🤖 AI Manager · эскалация",
        description=f"> **Канал:** {channel.mention}\n> **Причина:** {reason}",
        color=0xffaa00,
        channel_id=LOG_CHANNEL,
    )


# ============================================================
# GEMINI
# ============================================================
SYSTEM_PROMPT = """ты — ai-менеджер магазина diamond shop в discord-тикете.
твоя задача — помочь клиенту оформить заказ.

правила:
- говори коротко и по делу, 1–3 предложения
- используй только товары из каталога ниже, не выдумывай
- если клиент называет товар — найди его
- если вариантов несколько — предложи 2–3 с ценами
- если клиент выбрал конкретный — вызови create_invoice
- если не понимаешь клиента 3 раза — вызови escalate_to_human
- не подтверждай оплату сам — это делает менеджер
- не спрашивай про скидки — они уже учтены в контексте

каталог (только эти товары):
{catalog}

контекст:
- клиент: {user_name}
- скидка в тикете: {discount}%
"""

TOOLS = [
    {
        "name": "create_invoice",
        "description": "Выставить счёт клиенту. Вызывай когда клиент явно выбрал конкретный товар.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "item_id": {"type": "STRING", "description": "ID товара из каталога"},
            },
            "required": ["item_id"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Позвать менеджера если не можешь понять или это сложный вопрос.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "reason": {"type": "STRING", "description": "Почему эскалируешь"},
            },
            "required": ["reason"],
        },
    },
]


async def call_gemini(
    session: aiohttp.ClientSession,
    system_prompt: str,
    history: list,
    user_msg: str,
) -> Optional[dict]:
    if not GEMINI_API_KEY:
        ai_logger.error("MISTRAL_API_KEY не задан")
        return None

    contents = []
    for role, text in history[-8:]:
        contents.append({
            "role": "model" if role == "ai" else "user",
            "parts": [{"text": text}],
        })
    contents.append({"role": "user", "parts": [{"text": user_msg}]})

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "tools": [{"function_declarations": TOOLS}],
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": 800},
    }
    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY}

    try:
        async with session.post(
            url, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                ai_logger.warning(f"Gemini HTTP {resp.status}")
                return None
            data = await resp.json()
            cands = data.get("candidates", [])
            if not cands:
                return None
            parts = cands[0].get("content", {}).get("parts", [])
            text_parts, funcs = [], []
            for p in parts:
                if "text" in p:
                    text_parts.append(p["text"])
                if "functionCall" in p:
                    fc = p["functionCall"]
                    funcs.append({"name": fc.get("name"), "args": fc.get("args", {})})
            return {"text": "".join(text_parts).strip(), "funcs": funcs}
    except Exception as e:
        ai_logger.exception(f"Gemini call: {e}")
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


@bot.event
async def on_ready():
    ai_logger.info(f"AI Manager: {bot.user}")
    await bot.change_presence(activity=disnake.Game("AI-менеджер · онлайн"))
    reload_catalog_from_json()
    await log_discord(
        title="🤖 AI Manager запущен",
        description=f"> **{bot.user}** готов к работе.",
        color=COLOR_GREY,
        channel_id=LOG_CHANNEL,
    )


@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return
    if not isinstance(message.channel, disnake.TextChannel):
        return
    if not _is_ai_ticket(message.channel):
        return
    if not is_ai_enabled():
        return

    channel = message.channel
    user_id = message.author.id

    now = time.time()
    if now - COOLDOWN.get(user_id, 0) < SESSION_COOLDOWN_SEC:
        return
    COOLDOWN[user_id] = now

    sess = get_session(channel.id)
    if not sess:
        create_session(channel.id, user_id)
        sess = get_session(channel.id)

    if sess["escalated"]:
        return

    if message.attachments:
        att = message.attachments[0]
        low = att.filename.lower()
        if any(low.endswith(x) for x in (".png", ".jpg", ".jpeg", ".pdf")):
            update_session(channel.id, receipt_url=att.url, escalated=1)
            await channel.send(
                f"> ✅ Чек получен, файл сохранён.\n"
                f"> <@&{SALES_MANAGER_ROLE}> — заказ готов к проверке.\n"
                f"> 🤖 Я постараюсь в будущем понять данные методики тикетов."
            )
            await log_discord(
                title="🤖 AI Manager · чек получен",
                description=(
                    f"> **Канал:** {channel.mention}\n"
                    f"> **Юзер:** {message.author.mention}\n"
                    f"> **Файл:** [открыть]({att.url})"
                ),
                color=0x2ecc71,
                channel_id=LOG_CHANNEL,
            )
            return

    if sess["message_count"] >= SESSION_MAX_MESSAGES:
        await escalate(channel, "лимит сообщений исчерпан")
        return
    update_session(channel.id, message_count=sess["message_count"] + 1)

    hist = HISTORY.setdefault(channel.id, [])
    hist.append(("user", message.content or ""))
    discount = await get_ticket_discount(channel)

    catalog = load_catalog_from_db()
    lines = []
    for cat_label, cat in catalog.items():
        lines.append(f"\n[{cat_label}]")
        for item in cat["items"]:
            unit = f" / {item['unit']}" if item.get("unit") else ""
            lines.append(f"  - {item['id']}: {item['name']} — {item['price']}₽{unit}")
    catalog_text = "\n".join(lines)

    system_prompt = SYSTEM_PROMPT.format(
        catalog=catalog_text,
        user_name=message.author.display_name,
        discount=discount,
    )

    async with aiohttp.ClientSession() as http:
        async with channel.typing():
            result = await call_gemini(http, system_prompt, hist, message.content or "")

    if not result:
        new_fails = sess["fail_count"] + 1
        update_session(channel.id, fail_count=new_fails)
        if new_fails >= SESSION_MAX_FAILS:
            await escalate(channel, "не могу получить ответ от AI")
        return

    text = result.get("text", "").strip()
    funcs = result.get("funcs", [])

    if text:
        await message.reply(text, mention_author=False)
        hist.append(("ai", text))

    if funcs:
        update_session(channel.id, fail_count=0)

    for fc in funcs:
        name = fc["name"]
        args = fc.get("args", {})

        if name == "create_invoice":
            item_id = args.get("item_id", "")
            row = cur.execute("SELECT * FROM autoorder_catalog WHERE id=?", (item_id,)).fetchone()
            if not row:
                await channel.send(f"❌ Товар `{item_id}` не найден в каталоге.")
                continue
            item = dict(row)
            item["category"] = row["category"]
            ok = await send_invoice(channel, item, discount, message.author.display_name)
            if ok:
                update_session(channel.id, fail_count=0)

        elif name == "escalate_to_human":
            await escalate(channel, args.get("reason", "нужна помощь"))
            break

    HISTORY[channel.id] = hist[-20:]


def run_ai_manager():
    if not AI_MANAGER_TOKEN:
        print("❌ AI_MANAGER_TOKEN не установлен — процесс завершается")
        raise SystemExit(1)
    if not GEMINI_API_KEY:
        print("⚠️ MISTRAL_API_KEY не задан — AI не сможет отвечать")
    try:
        bot.run(AI_MANAGER_TOKEN)
    except Exception as e:
        ai_logger.exception(f"Ошибка запуска: {e}")
        raise
