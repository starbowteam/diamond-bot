# -*- coding: utf-8 -*-
"""
AI Manager — третий бот. Ведёт диалог в тикетах, создаёт счёты, ловит чеки.
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
    get_ticket_owner, has_admin_command_roles,
)
from core.catalog import (
    load_catalog_from_db,
    reload_catalog_from_json,
    auto_init,
)

# ============================================================
# КОНСТАНТЫ
# ============================================================
AI_MANAGER_TOKEN = os.getenv("AI_MANAGER_TOKEN")
GEMINI_API_KEY = os.getenv("MISTRAL_API_KEY")
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

GEMINI_MODELS_PRIORITY = ["gemini-flash-latest"]
_env_model = os.getenv("GEMINI_MODEL")
if _env_model:
    GEMINI_MODELS_PRIORITY = [m.strip() for m in _env_model.split(",") if m.strip()]

_AVAILABLE_MODELS: List[str] = []
_AVAILABLE_MODELS_FETCHED_AT: float = 0.0
_MODELS_CACHE_TTL = 3600

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
    ai_logger.info(f"Эскалация: {channel.id} — {reason}")


# ============================================================
# GEMINI — fetch моделей как в ai.py
# ============================================================
async def _fetch_available_models(session: aiohttp.ClientSession) -> List[str]:
    global _AVAILABLE_MODELS, _AVAILABLE_MODELS_FETCHED_AT
    now = time.time()
    if _AVAILABLE_MODELS and now - _AVAILABLE_MODELS_FETCHED_AT < _MODELS_CACHE_TTL:
        return _AVAILABLE_MODELS

    url = GEMINI_API_BASE
    headers = {"X-goog-api-key": GEMINI_API_KEY}
    try:
        async with session.get(url, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return _AVAILABLE_MODELS
            data = await resp.json()
            models = []
            for m in data.get("models", []):
                name = m.get("name", "")
                if not name.startswith("models/"):
                    continue
                short = name[len("models/"):]
                if "generateContent" not in m.get("supportedGenerationMethods", []):
                    continue
                n_low = short.lower()
                if "flash" not in n_low:
                    continue
                if any(x in n_low for x in ("image", "tts", "omni")):
                    continue
                models.append(short)

            def sort_key(n):
                n_low = n.lower()
                score = 0
                if "latest" in n_low: score -= 1000
                m = re.search(r"gemini-(\d+)\.(\d+)", n_low)
                if m:
                    score -= int(m.group(1)) * 100
                    score -= int(m.group(2)) * 10
                if "preview" in n_low or "exp" in n_low:
                    score += 500
                if "8b" in n_low:
                    score += 100
                return score

            models.sort(key=sort_key)
            _AVAILABLE_MODELS = models
            _AVAILABLE_MODELS_FETCHED_AT = now
            ai_logger.info(f"Доступные модели: {models[:5]}")
            return models
    except Exception as e:
        ai_logger.warning(f"listModels: {e}")
        return _AVAILABLE_MODELS


async def _try_model(
    session: aiohttp.ClientSession,
    model: str,
    payload: dict,
) -> tuple:
    url = f"{GEMINI_API_BASE}/{model}:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY}
    try:
        async with session.post(
            url, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                cands = data.get("candidates", [])
                if not cands:
                    return False, {"error": "no candidates"}, 200
                parts = cands[0].get("content", {}).get("parts", [])
                text_parts, funcs = [], []
                for p in parts:
                    if "text" in p:
                        text_parts.append(p["text"])
                    if "functionCall" in p:
                        fc = p["functionCall"]
                        funcs.append({"name": fc.get("name"), "args": fc.get("args", {})})
                return True, {"text": "".join(text_parts).strip(), "funcs": funcs}, 200
            err = await resp.text()
            ai_logger.warning(f"[{model}] {resp.status}: {err[:200]}")
            if resp.status == 429:
                return False, {"error": "rate_limit"}, 429
            return False, {"error": f"http {resp.status}"}, resp.status
    except asyncio.TimeoutError:
        ai_logger.warning(f"[{model}] timeout 60s")
        return False, {"error": "timeout"}, -1
    except Exception as e:
        ai_logger.warning(f"[{model}] {type(e).__name__}: {e}")
        return False, {"error": str(e)}, -1


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

каталог (только эти товары):
{catalog}

контекст:
- клиент: {user_name}
- скидка в тикете: {discount}%
"""

TOOLS = [
    {
        "name": "create_invoice",
        "description": "Выставить счёт. Вызывай когда клиент явно выбрал конкретный товар.",
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


def _build_payload(system_prompt: str, contents: list) -> dict:
    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "tools": [{"function_declarations": TOOLS}],
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": 800},
    }


async def call_gemini(
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

    payload = _build_payload(system_prompt, contents)

    async with aiohttp.ClientSession() as session:
        models_to_try = []
        seen = set()
        for m in GEMINI_MODELS_PRIORITY:
            if m not in seen:
                seen.add(m)
                models_to_try.append(m)
        for m in await _fetch_available_models(session):
            if m not in seen:
                seen.add(m)
                models_to_try.append(m)
        models_to_try = models_to_try[:5]

        if not models_to_try:
            ai_logger.error("Нет доступных моделей")
            return None

        ai_logger.info(f"Пробую модели: {models_to_try}")

        for model in models_to_try:
            ok, res, status = await _try_model(session, model, payload)
            if ok:
                ai_logger.info(f"✅ Ответ от {model}")
                return res
            if status == 429:
                ai_logger.warning(f"Rate limit на {model}")
                break
            await asyncio.sleep(0.3)

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
    ai_logger.info(f"AI Manager: {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=disnake.Game("AI-менеджер · онлайн"))

    # Автоинициализация каталога
    count = auto_init()
    ai_logger.info(f"Каталог на старте: {count} товаров")

    # Прогрев моделей
    try:
        async with aiohttp.ClientSession() as s:
            models = await _fetch_available_models(s)
            if models:
                ai_logger.info(f"Доступные модели: {models[:5]}")
    except Exception as e:
        ai_logger.warning(f"прогрев моделей: {e}")

    # Лог в канал
    try:
        ch = bot.get_channel(LOG_CHANNEL)
        if ch:
            await ch.send(embed=disnake.Embed(
                title="🤖 AI Manager запущен",
                description=(
                    f"> **Бот:** {bot.user.mention}\n"
                    f"> **Каталог:** `{count}` товаров\n"
                    f"> **AI включён:** {'✅' if is_ai_enabled() else '❌'}"
                ),
                color=COLOR_GREY,
            ))
    except Exception as e:
        ai_logger.warning(f"log channel: {e}")


@bot.slash_command(name="am_status", description="AI Manager — диагностика")
async def am_status(ctx: disnake.ApplicationCommandInteraction):
    catalog = load_catalog_from_db()
    total = sum(len(c["items"]) for c in catalog.values())
    cats = len(catalog)

    embed = disnake.Embed(
        title="🤖 AI Manager · Диагностика",
        color=COLOR_GREY,
    )
    embed.add_field(name="🟢 Бот", value=f"{bot.user.mention if bot.user else '❌'}", inline=False)
    embed.add_field(name="⚙️ AI включён", value="✅ Да" if is_ai_enabled() else "❌ Нет", inline=True)
    embed.add_field(name="📦 Каталог", value=f"`{total}` в `{cats}` категориях", inline=True)
    embed.add_field(name="🔑 Gemini API", value="✅" if GEMINI_API_KEY else "❌", inline=True)
    embed.add_field(name="🎯 Модели", value=f"`{_AVAILABLE_MODELS[:2]}`" if _AVAILABLE_MODELS else "не загружены", inline=False)
    await ctx.send(embed=embed, ephemeral=True)


@bot.slash_command(name="am_test", description="Тест AI без тикета")
async def am_test(
    ctx: disnake.ApplicationCommandInteraction,
    text: str = "Привет, сколько стоит Nitro 1 Month?",
):
    if not GEMINI_API_KEY:
        return await ctx.send("❌ MISTRAL_API_KEY не установлен", ephemeral=True)

    await ctx.response.defer(ephemeral=True)

    catalog = load_catalog_from_db()
    if not catalog:
        return await ctx.edit_original_response(
            content="❌ Каталог пуст. Используй `/am_reload`."
        )

    lines = []
    for cat_label, cat in catalog.items():
        lines.append(f"\n[{cat_label}]")
        for item in cat["items"]:
            unit = f" / {item['unit']}" if item.get("unit") else ""
            lines.append(f"  - {item['id']}: {item['name']} — {item['price']}₽{unit}")
    catalog_text = "\n".join(lines)

    system_prompt = SYSTEM_PROMPT.format(
        catalog=catalog_text,
        user_name=ctx.author.display_name,
        discount=0,
    )

    start = time.time()
    result = await call_gemini(system_prompt, [], text)
    elapsed = time.time() - start

    if not result:
        return await ctx.edit_original_response(
            content=f"❌ Gemini не ответил за {elapsed:.1f}с. Смотри `ai_manager.log`."
        )

    resp = result.get("text") or "—"
    funcs = result.get("funcs", [])

    embed = disnake.Embed(
        title=f"🤖 Тест AI · {elapsed:.1f}с",
        description=f"**Ты:** {text}\n\n**AI:** {resp}",
        color=COLOR_GREY,
    )
    if funcs:
        embed.add_field(
            name="🔧 Function calls",
            value="\n".join(f"`{f['name']}({f['args']})`" for f in funcs),
            inline=False,
        )
    await ctx.edit_original_response(embed=embed)


@bot.slash_command(name="am_toggle", description="Включить/выключить AI-менеджер")
async def am_toggle(ctx: disnake.ApplicationCommandInteraction):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ Нет прав.", ephemeral=True)

    current = get_setting("ai_manager_enabled", "0")
    new_state = "0" if current == "1" else "1"
    set_setting("ai_manager_enabled", new_state)

    await ctx.send(
        f"✅ AI Manager: **{'ВКЛЮЧЁН' if new_state == '1' else 'ВЫКЛЮЧЕН'}**",
        ephemeral=True,
    )
    ai_logger.info(f"Toggle от {ctx.author.id}: {new_state}")


@bot.slash_command(name="am_reload", description="Перезагрузить каталог из файла")
async def am_reload(ctx: disnake.ApplicationCommandInteraction):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ Нет прав.", ephemeral=True)

    count = reload_catalog_from_json()
    catalog = load_catalog_from_db()
    await ctx.send(
        f"✅ Загружено **{count}** товаров из **{len(catalog)}** категорий.",
        ephemeral=True,
    )


@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return
    if not isinstance(message.channel, disnake.TextChannel):
        return
    if message.content.startswith("!am"):
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

    # ЧЕК
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
            ai_logger.info(f"Чек: {channel.id} от {user_id}")
            return

    if sess["message_count"] >= SESSION_MAX_MESSAGES:
        await escalate(channel, "лимит сообщений исчерпан")
        return
    update_session(channel.id, message_count=sess["message_count"] + 1)

    hist = HISTORY.setdefault(channel.id, [])
    hist.append(("user", message.content or ""))
    discount = await get_ticket_discount(channel)

    catalog = load_catalog_from_db()
    if not catalog:
        await channel.send("⚠️ Каталог пуст. Админ должен загрузить его.")
        return

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

    async with channel.typing():
        result = await call_gemini(system_prompt, hist, message.content or "")

    if not result:
        new_fails = sess["fail_count"] + 1
        update_session(channel.id, fail_count=new_fails)
        ai_logger.warning(f"AI fail #{new_fails} в {channel.id}")
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
                await channel.send(f"❌ Товар `{item_id}` не найден.")
                continue
            item = dict(row)
            item["category"] = row["category"]
            ok = await send_invoice(channel, item, discount, message.author.display_name)
            if ok:
                update_session(channel.id, fail_count=0)
                ai_logger.info(f"Счёт: {channel.id} → {item['name']}")

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
    ai_logger.info(f"Запуск AI Manager (token len={len(AI_MANAGER_TOKEN)})")
    try:
        bot.run(AI_MANAGER_TOKEN)
    except Exception as e:
        ai_logger.exception(f"Ошибка запуска: {e}")
        raise
