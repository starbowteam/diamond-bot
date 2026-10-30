# -*- coding: utf-8 -*-
"""
AI Manager — третий бот. Ведёт диалог в тикетах, создаёт счёты, ловит чеки.
Использует OpenAI-совместимый API ZvenoAI (Qwen).

Правила:
  ✅ Отвечает в TICKET_CATEGORY_ID (обычные тикеты) или там, где есть owner_id.
  🚫 НИКОГДА не лезет в PAID_CATEGORY_ID (оплаченные заказы).
  🛑 Как только менеджер написал в тикет — AI уходит навсегда (escalated=1).
"""
import os
import re
import json
import time
import math
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict

import aiohttp
import disnake
from disnake.ext import commands

from core.utils import (
    CONFIG, DATA_DIR, logger, db, cur,
    load_json, save_json, now_ts, log_discord,
    get_ticket_owner,
)
from core.catalog import (
    load_catalog_from_db,
    auto_init,
)
from modules.tickets import ReceiptView

# ============================================================
# КОНСТАНТЫ
# ============================================================
AI_MANAGER_TOKEN = os.getenv("AI_MANAGER_TOKEN")
AI_MANAGER_API_KEY = os.getenv("AI_MANAGER_API_KEY")
AI_MANAGER_BASE_URL = os.getenv("AI_MANAGER_BASE_URL", "https://api.zveno.ai/v1").rstrip("/")
AI_MANAGER_MODEL = os.getenv("AI_MANAGER_MODEL", "qwen/qwen-2.5-72b-instruct")
LLM_TIMEOUT = 30

SALES_MANAGER_ROLE = 1154757071330365490
OWNER_ID = 796293832751972352
LOG_CHANNEL = 1530453871581855744

SESSION_MAX_MESSAGES = 20
SESSION_MAX_FAILS = 3
DEBOUNCE_SEC = 2.0
HISTORY_TTL_SEC = 20 * 60
HISTORY_MAX_MSG = 10

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
    CREATE TABLE IF NOT EXISTS ai_manager_sessions (
        channel_id     INTEGER PRIMARY KEY,
        user_id        INTEGER,
        message_count  INTEGER DEFAULT 0,
        fail_count     INTEGER DEFAULT 0,
        started_at     INTEGER,
        escalated      INTEGER DEFAULT 0,
        receipt_url    TEXT,
        created_at     INTEGER,
        stub_sent      INTEGER DEFAULT 0,
        invoice_sent   INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS ai_manager_history (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id INTEGER NOT NULL,
        role       TEXT NOT NULL,
        content    TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ai_hist_channel
        ON ai_manager_history(channel_id, id);
    """)
    db.commit()
    try:
        cols = [r[1] for r in cur.execute("PRAGMA table_info(ai_manager_sessions)").fetchall()]
        if "stub_sent" not in cols:
            cur.execute("ALTER TABLE ai_manager_sessions ADD COLUMN stub_sent INTEGER DEFAULT 0")
        if "invoice_sent" not in cols:
            cur.execute("ALTER TABLE ai_manager_sessions ADD COLUMN invoice_sent INTEGER DEFAULT 0")
        db.commit()
    except Exception:
        pass

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
    return get_setting("ai_manager_enabled", "1") == "1"

# ============================================================
# СЕССИИ
# ============================================================
def get_session(channel_id: int) -> Optional[dict]:
    row = cur.execute("SELECT * FROM ai_manager_sessions WHERE channel_id=?", (channel_id,)).fetchone()
    return dict(row) if row else None

def create_session(channel_id: int, user_id: int):
    cur.execute(
        "INSERT OR IGNORE INTO ai_manager_sessions "
        "(channel_id, user_id, message_count, fail_count, started_at, escalated, "
        " receipt_url, created_at, stub_sent, invoice_sent) "
        "VALUES (?, ?, 0, 0, ?, 0, '', ?, 0, 0)",
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
# ИСТОРИЯ
# ============================================================
def hist_load(channel_id: int, ttl_sec: int = HISTORY_TTL_SEC, limit: int = HISTORY_MAX_MSG):
    cutoff = int(time.time()) - ttl_sec
    rows = cur.execute(
        "SELECT role, content FROM ai_manager_history "
        "WHERE channel_id=? AND created_at >= ? ORDER BY id DESC LIMIT ?",
        (channel_id, cutoff, limit),
    ).fetchall()
    return [(r["role"], r["content"]) for r in reversed(rows)]

def hist_append(channel_id: int, role: str, content: str):
    if not content:
        return
    cur.execute(
        "INSERT INTO ai_manager_history (channel_id, role, content, created_at) "
        "VALUES (?,?,?,?)",
        (channel_id, role, content[:2000], int(time.time())),
    )
    db.commit()

def hist_clear(channel_id: int):
    cur.execute("DELETE FROM ai_manager_history WHERE channel_id=?", (channel_id,))
    db.commit()

# ============================================================
# DEBOUNCE
# ============================================================
DEBOUNCE: Dict[int, dict] = {}

async def _debounce_flush(channel, user, gen: int, delay: float = DEBOUNCE_SEC):
    try:
        await asyncio.sleep(delay)
        state = DEBOUNCE.get(channel.id)
        if not state or state.get("gen") != gen:
            return
        msgs = state.get("messages", [])
        DEBOUNCE.pop(channel.id, None)
        combined = "\n".join(m for m in msgs if m).strip()
        if not combined:
            return
        await _handle_dialog(channel, user, combined)
    except asyncio.CancelledError:
        raise
    except Exception:
        ai_logger.exception("debounce_flush")

# ============================================================
# ФИЛЬТРАЦИЯ КАТАЛОГА
# ============================================================
def get_filtered_catalog(user_text: str, full_catalog: Dict[str, dict]) -> Dict[str, dict]:
    t = user_text.lower()
    result = {}
    keywords = {
        "discord": ["дискорд", "discord", "нитро", "nitro", "буст", "boost"],
        "telegram": ["телега", "телеграм", "telegram", "тг", "tg", "звезд", "звёзд", "stars"],
        "steam": ["стим", "steam", "пополнени", "регион", "рубл"],
        "roblox": ["роблокс", "roblox", "робукс", "robux"],
        "spotify": ["споти", "spotify"],
        "decoration": ["украшени", "декор", "бейдж", "профиль"]
    }
    matched_cat = None
    for cat_key, words in keywords.items():
        if any(w in t for w in words):
            matched_cat = cat_key
            break
    if matched_cat:
        for db_key, cat_data in full_catalog.items():
            if matched_cat in db_key.lower() or matched_cat in cat_data["label"].lower():
                result[db_key] = cat_data
                break
    return result if result else full_catalog

# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _get_category_id(channel) -> Optional[int]:
    try:
        return channel.category.id if channel.category else None
    except Exception:
        return None

def _is_paid_category(channel) -> bool:
    paid_id = CONFIG.get("PAID_CATEGORY_ID")
    if not paid_id:
        return False
    return _get_category_id(channel) == paid_id

def _is_ai_ticket(channel) -> bool:
    if _is_paid_category(channel):
        return False
    if get_ticket_owner(channel.id):
        return True
    if _get_category_id(channel) == CONFIG.get("TICKET_CATEGORY_ID"):
        return True
    return False

def _is_manager(member) -> bool:
    """True, если у участника есть роль SALES_MANAGER_ROLE или он владелец бота."""
    try:
        if member.id == OWNER_ID:
            return True
        return any(r.id == SALES_MANAGER_ROLE for r in member.roles)
    except Exception:
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

async def send_invoice(channel, item: dict, discount: int, user_name: str, quantity: int = 1) -> bool:
    try:
        from modules.tickets import generate_receipt_png, generate_receipt_id
        base_price = float(item["price"])
        total_base = base_price * quantity
        amount = int(total_base) if total_base % 1 == 0 else int(math.ceil(total_base))
        order_id = generate_receipt_id()
        product_display = item["name"]
        if quantity > 1:
            product_display += f" × {quantity}"

        buf = await asyncio.to_thread(
            generate_receipt_png,
            manager_name="AI Manager",
            customer_name=user_name or "Клиент",
            product_name=product_display,
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
                f"> **Количество:** `{quantity} шт.`\n"
                f"> **Сумма:** `{amount} ₽`"
                + (f"\n> **Скидка:** `{discount}%`" if discount else "")
                + "\n\n> Проверьте реквизиты и пришлите чек в этот канал."
            ),
            color=COLOR_GREY,
        )
        embed.set_image(url=f"attachment://receipt_{order_id}.png")
        await channel.send(embed=embed, file=file, view=ReceiptView())
        return True
    except Exception as e:
        ai_logger.exception(f"send_invoice: {e}")
        return False

async def escalate(channel, reason: str):
    if _is_paid_category(channel):
        return

    sess = get_session(channel.id)
    if sess is None:
        create_session(channel.id, 0)
    elif sess.get("escalated"):
        return
    update_session(channel.id, escalated=1)

    ping = f"<@{OWNER_ID}>" if "BuyALL" in reason or "не найден" in reason.lower() \
        else f"<@&{SALES_MANAGER_ROLE}>"

    embed = disnake.Embed(
        title="⚠️ Требуется помощь менеджера",
        description=(
            f"> {ping}, клиент ждёт ответа.\n"
            f"> **Причина:** {reason}\n"
            f"> 🤖 Я постараюсь в будущем понять данные методики тикетов."
        ),
        color=COLOR_GREY,
    )
    embed.set_image(url=IMG_STRIPE)
    await channel.send(embed=embed)
    ai_logger.info(f"Эскалация: {channel.id} — {reason}")

async def notify_managers_dm(message, file_url):
    guild = message.guild
    if not guild:
        return
    role = guild.get_role(SALES_MANAGER_ROLE)
    if not role:
        return

    embed = disnake.Embed(
        title="💳 Новый чек на проверку!",
        description=(
            f"> **Тикет:** {message.channel.mention}\n"
            f"> **Пользователь:** {message.author.mention} (`{message.author.id}`)\n"
            f"> **Ссылка на файл:** [открыть]({file_url})\n\n"
            f"> Проверьте оплату и подтвердите заказ."
        ),
        color=COLOR_GREY,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_image(url=file_url)

    for member in role.members:
        if member.bot:
            continue
        try:
            await member.send(embed=embed)
        except Exception:
            pass

# ============================================================
# LLM
# ============================================================
SYSTEM_PROMPT = """ты — ai-менеджер магазина diamond shop в discord-тикете.
твоя задача — помочь клиенту оформить заказ.

правила:
- говори коротко и по делу, 1–3 предложения
- используй ТОЛЬКО товары из списка ниже. Если нужного товара нет в списке, ты ОБЯЗАН сказать клиенту об этом.
- КРИТИЧЕСКОЕ ПРАВИЛО: Если клиент просит товар, а его нет в списке (например, просит Спотифай на год, а есть только на месяц), ты должен предложить то, что есть, или сказать "У нас нет такого товара".
- НИКОГДА не подсовывай товар из другой категории! Если просят Спотифай, не предлагай Звёзды Телеграм.
- Если клиент просит "пополнение стим на 150 рублей", передай item_id="steam_rub" и quantity=150.
- Если клиент просит "100 звезд", передай item_id="tg_stars" и quantity=100.
- НЕ ВЫСТАВЛЯЙ БОЛЬШЕ ОДНОГО СЧЕТА ЗА РАЗ.
- Если товара нет в каталоге — вызови escalate_to_human с причиной "Товар не найден в каталоге, возможно BuyALL".
- ВАЖНО: пометка "[счёт выставлен: ...]" в контексте означает, что предыдущий заказ УЖЕ оформлен. Новый запрос клиента — это НОВЫЙ заказ. Не смешивай товары из разных запросов.
- не подтверждай оплату сам — это делает менеджер.

каталог (цены за 1 единицу):
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
            "description": "Выставить счёт клиенту. Вызывай только если товар ТОЧНО есть в каталоге и клиент подтвердил выбор.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string", "description": "ID товара из каталога"},
                    "quantity": {"type": "integer", "description": "Количество", "default": 1},
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Позвать менеджера если не можешь понять или товара нет в каталоге.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Почему эскалируешь. Если товара нет в каталоге, напиши 'Товар не найден в каталоге, возможно BuyALL'."},
                },
                "required": ["reason"],
            },
        },
    },
]

async def call_llm(system_prompt: str, history: list, user_msg: str) -> Optional[dict]:
    if not AI_MANAGER_API_KEY:
        ai_logger.error("AI_MANAGER_API_KEY не задан")
        return None

    messages = [{"role": "system", "content": system_prompt}]
    for role, text in history[-HISTORY_MAX_MSG:]:
        messages.append({
            "role": "assistant" if role == "ai" else "user",
            "content": text,
        })
    messages.append({"role": "user", "content": user_msg})

    payload = {
        "model": AI_MANAGER_MODEL,
        "messages": messages,
        "tools": TOOLS_OPENAI,
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_tokens": 800,
    }
    url = f"{AI_MANAGER_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {AI_MANAGER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    ai_logger.warning(f"LLM HTTP {resp.status}")
                    return None
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
                    name = fn.get("name")
                    raw_args = fn.get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {}
                    funcs.append({"name": name, "args": args})

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
    ai_logger.info(f"AI Manager запущен. Каталог: {count}")
    if not _CLEANUP_STARTED:
        _CLEANUP_STARTED = True
        asyncio.create_task(_cleanup_loop())

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

# ============================================================
# ДИАЛОГ
# ============================================================
async def _handle_dialog(channel, author, user_text: str):
    if not user_text.strip():
        return

    if _is_paid_category(channel):
        return

    user_id = author.id

    sess = get_session(channel.id)
    if not sess:
        create_session(channel.id, user_id)
        sess = get_session(channel.id)

    # Если менеджер уже заходил — молчим
    if sess["escalated"]:
        return

    if sess["message_count"] >= SESSION_MAX_MESSAGES:
        await escalate(channel, "исчерпан лимит сообщений — нужен живой менеджер")
        return

    if sess["message_count"] == SESSION_MAX_MESSAGES - 2:
        try:
            await channel.send("ℹ️ Скоро подключится менеджер — лимит автоматических сообщений почти исчерпан.")
        except Exception:
            pass

    update_session(channel.id, message_count=(sess["message_count"] or 0) + 1)
    hist_append(channel.id, "user", user_text)

    discount = await get_ticket_discount(channel)
    full_catalog = load_catalog_from_db()
    if not full_catalog:
        await channel.send("⚠️ Каталог пуст.")
        return

    filtered_catalog = get_filtered_catalog(user_text, full_catalog)

    lines = []
    for cat_label, cat in filtered_catalog.items():
        lines.append(f"\n[{cat_label}]")
        for item in cat["items"]:
            unit = f" / {item['unit']}" if item.get("unit") else ""
            lines.append(f"  - {item['id']}: {item['name']} — {item['price']}₽{unit}")
    catalog_text = "\n".join(lines)

    system_prompt = SYSTEM_PROMPT.format(
        catalog=catalog_text,
        user_name=author.display_name,
        discount=discount,
    )

    history = hist_load(channel.id)

    async with channel.typing():
        result = await call_llm(system_prompt, history, user_text)

    if not result:
        new_fails = (sess["fail_count"] or 0) + 1
        update_session(channel.id, fail_count=new_fails)
        if new_fails >= SESSION_MAX_FAILS:
            await escalate(channel, "сбой LLM")
        else:
            try:
                await channel.send("⏳ Секунду, уточняю информацию…")
            except Exception:
                pass
        return

    update_session(channel.id, fail_count=0)

    text = (result.get("text") or "").strip()
    funcs = result.get("funcs") or []

    if text:
        try:
            await channel.send(text)
        except Exception:
            pass
        hist_append(channel.id, "ai", text)

    if funcs:
        fc = funcs[0]
        name = fc["name"]
        args = fc.get("args", {})

        if name == "create_invoice":
            item_id = args.get("item_id", "")
            try:
                quantity = max(1, int(args.get("quantity", 1)))
            except (TypeError, ValueError):
                quantity = 1

            row = cur.execute("SELECT * FROM autoorder_catalog WHERE id=?", (item_id,)).fetchone()
            if not row:
                await escalate(channel, "Товар не найден в каталоге, возможно BuyALL")
                return
            item = dict(row)
            item["category"] = row["category"]

            user_low = user_text.lower()
            cat_low = item["category"].lower()
            if ("споти" in user_low or "spotify" in user_low) and "spotify" not in cat_low:
                await channel.send("❌ Извините, я не могу оформить этот товар.")
                await escalate(channel, "Ошибка сопоставления: запрошен Spotify")
                return

            ok = await send_invoice(channel, item, discount, author.display_name, quantity)
            if ok:
                ai_logger.info(f"Счёт: {channel.id} → {item['name']} x{quantity}")

                hist_clear(channel.id)
                hist_append(
                    channel.id, "ai",
                    f"[счёт выставлен: {item['name']} × {quantity}, ожидаем оплату]",
                )
                update_session(
                    channel.id,
                    invoice_sent=1,
                    message_count=0,
                    fail_count=0,
                )

        elif name == "escalate_to_human":
            await escalate(channel, args.get("reason", "Товар не найден в каталоге"))

# ============================================================
# ON_MESSAGE
# ============================================================
@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return
    if not isinstance(message.channel, disnake.TextChannel):
        return

    channel = message.channel

    # 🔴 PAID — вне зоны AI (проверяем первым, до менеджера)
    if _is_paid_category(channel):
        return

    # 🛑 МЕНЕДЖЕР написал → AI покидает тикет
    if isinstance(message.author, disnake.Member) and _is_manager(message.author):
        if _is_ai_ticket(channel):
            sess = get_session(channel.id)
            if sess is None:
                create_session(channel.id, message.author.id)
            if not (sess and sess.get("escalated")):
                update_session(channel.id, escalated=1)
                ai_logger.info(f"AI покинул тикет {channel.id} — писал менеджер")
            # Отменяем pending debounce, если был
            DEBOUNCE.pop(channel.id, None)
        return

    # Дальше — только клиент
    if not _is_ai_ticket(channel):
        return

    owner_id = get_ticket_owner(channel.id)
    if owner_id and message.author.id != owner_id:
        return

    # === AI выключен ===
    if not is_ai_enabled():
        sess = get_session(channel.id)
        if not sess:
            create_session(channel.id, message.author.id)
            sess = get_session(channel.id)
        if not sess.get("stub_sent"):
            update_session(channel.id, stub_sent=1)
            embed = disnake.Embed(
                title="🤖 AI-менеджер временно отключён",
                description=(
                    f"> Сейчас бот не может помочь с оформлением заказа.\n"
                    f"> Пожалуйста, ожидайте ответа менеджера <@&{SALES_MANAGER_ROLE}>.\n\n"
                    f"> _Все тикеты работают в обычном режиме._"
                ),
                color=COLOR_GREY,
            )
            embed.set_image(url=IMG_STRIPE)
            await channel.send(embed=embed)
        return

    # === ФАЙЛ (только если ждём чек) ===
    if message.attachments:
        sess = get_session(channel.id)
        if not sess or not sess.get("invoice_sent"):
            return

        att = message.attachments[0]
        low = att.filename.lower()
        if any(low.endswith(x) for x in (".png", ".jpg", ".jpeg", ".pdf")):
            update_session(channel.id, receipt_url=att.url, escalated=1, invoice_sent=0)
            embed = disnake.Embed(
                title="✅ Чек получен",
                description=(
                    f"> <@&{SALES_MANAGER_ROLE}> — заказ готов к проверке.\n"
                    f"> **Файл сохранён и передан менеджерам.**\n"
                    f"> 🤖 Я постараюсь в будущем понять данные методики тикетов."
                ),
                color=COLOR_GREY,
            )
            embed.set_image(url=IMG_STRIPE)
            await channel.send(embed=embed)
            asyncio.create_task(notify_managers_dm(message, att.url))
        return

    # === ТЕКСТ → debounce ===
    text = (message.content or "").strip()
    if not text:
        return

    state = DEBOUNCE.setdefault(channel.id, {"messages": [], "gen": 0})
    state["messages"].append(text)
    state["gen"] += 1
    gen = state["gen"]
    asyncio.create_task(_debounce_flush(channel, message.author, gen))

# ============================================================
# ЗАПУСК
# ============================================================
def run_ai_manager():
    if not AI_MANAGER_TOKEN:
        ai_logger.error("AI_MANAGER_TOKEN не задан")
        raise SystemExit(1)
    if not AI_MANAGER_API_KEY:
        ai_logger.error("AI_MANAGER_API_KEY не задан")
        raise SystemExit(1)
    try:
        bot.run(AI_MANAGER_TOKEN)
    except Exception as e:
        ai_logger.exception(f"Ошибка запуска: {e}")
        raise