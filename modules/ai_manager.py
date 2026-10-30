# -*- coding: utf-8 -*-
"""
AI Manager — третий бот. Ведёт диалог в тикетах, создаёт счёты, ловит чеки.
Использует OpenAI-совместимый API ZvenoAI (Qwen).
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
from modules.tickets import ReceiptView

# ============================================================
# КОНСТАНТЫ
# ============================================================
AI_MANAGER_TOKEN = os.getenv("AI_MANAGER_TOKEN")

AI_MANAGER_API_KEY = os.getenv(
    "AI_MANAGER_API_KEY",
    "sk-tBUQGfnb7_AIX0-Ia9oTApLlYqRvUM-P5pQj5MDMGqc",
)
AI_MANAGER_BASE_URL = os.getenv(
    "AI_MANAGER_BASE_URL",
    "https://api.zveno.ai/v1",
).rstrip("/")
AI_MANAGER_MODEL = os.getenv(
    "AI_MANAGER_MODEL",
    "qwen/qwen-2.5-72b-instruct",
)
LLM_TIMEOUT = 60

SALES_MANAGER_ROLE = 1154757071330365490
OWNER_ID = 796293832751972352
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
# ФИЛЬТРАЦИЯ КАТАЛОГА (ЗАЩИТА ОТ ГАЛЛЮЦИНАЦИЙ)
# ============================================================
def get_filtered_catalog(user_text: str, full_catalog: Dict[str, dict]) -> Dict[str, dict]:
    """Отдает только те категории, которые юзер упомянул (или всё, если не понял)."""
    t = user_text.lower()
    result = {}
    
    # Ключевые слова для поиска
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
        # Ищем категорию в БД (она может называться чуть иначе)
        for db_key, cat_data in full_catalog.items():
            if matched_cat in db_key.lower() or matched_cat in cat_data["label"].lower():
                result[db_key] = cat_data
                break
                
    # Если не нашли совпадений или нашли, возвращаем найденное (или всё, если пусто)
    return result if result else full_catalog


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


async def send_invoice(channel, item: dict, discount: int, user_name: str, quantity: int = 1) -> bool:
    try:
        from modules.tickets import generate_receipt_png, generate_receipt_id
        
        base_price = float(item["price"])
        total_base = base_price * quantity
        amount = int(total_base) if total_base % 1 == 0 else math.ceil(total_base)
        
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
    sess = get_session(channel.id)
    if sess and sess["escalated"]:
        return
    if sess:
        update_session(channel.id, escalated=1)

    ping = f"<@{OWNER_ID}>" if "BuyALL" in reason or "не найден" in reason.lower() else f"<@&{SALES_MANAGER_ROLE}>"
    
    embed = disnake.Embed(
        title="⚠️ Требуется помощь менеджера",
        description=(
            f"> {ping}, клиент ждёт ответа.\n"
            f"> **Причина:** {reason}\n"
            f"> 🤖 Я постараюсь в будущем понять данные методики тикетов."
        ),
        color=COLOR_GREY
    )
    embed.set_image(url=IMG_STRIPE)
    
    await channel.send(embed=embed)
    ai_logger.info(f"Эскалация: {channel.id} — {reason}")


async def notify_managers_dm(message, file_url):
    guild = message.guild
    if not guild: return
    role = guild.get_role(SALES_MANAGER_ROLE)
    if not role: return

    embed = disnake.Embed(
        title="💳 Новый чек на проверку!",
        description=(
            f"> **Тикет:** {message.channel.mention}\n"
            f"> **Пользователь:** {message.author.mention} (`{message.author.id}`)\n"
            f"> **Ссылка на файл:** [открыть]({file_url})\n\n"
            f"> Проверьте оплату и подтвердите заказ."
        ),
        color=COLOR_GREY,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_image(url=file_url)

    for member in role.members:
        if member.bot: continue
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
                    "item_id": {
                        "type": "string",
                        "description": "ID товара из каталога",
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "Количество",
                        "default": 1
                    }
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
                    "reason": {
                        "type": "string",
                        "description": "Почему эскалируешь. Если товара нет в каталоге, напиши 'Товар не найден в каталоге, возможно BuyALL'.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]


async def call_llm(
    system_prompt: str,
    history: list,
    user_msg: str,
) -> Optional[dict]:
    if not AI_MANAGER_API_KEY:
        ai_logger.error("AI_MANAGER_API_KEY не задан")
        return None

    messages = [{"role": "system", "content": system_prompt}]
    for role, text in history[-8:]:
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
        "temperature": 0.1, # МИНИМУМ КРЕАТИВА, ЧТОБЫ НЕ ВЫДУМЫВАЛ
        "max_tokens": 800,
    }
    url = f"{AI_MANAGER_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {AI_MANAGER_API_KEY}",
        "Content-Type": "application/json",
    }

    start = time.time()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=LLM_TIMEOUT),
            ) as resp:
                elapsed = time.time() - start
                if resp.status != 200:
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

    except Exception as e:
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
    count = auto_init()
    ai_logger.info(f"AI Manager запущен. Каталог: {count}")


@bot.slash_command(name="am_status", description="AI Manager — диагностика")
async def am_status(ctx: disnake.ApplicationCommandInteraction):
    catalog = load_catalog_from_db()
    total = sum(len(c["items"]) for c in catalog.values())
    
    embed = disnake.Embed(title="🤖 AI Manager · Диагностика", color=COLOR_GREY)
    embed.add_field(name="⚙️ AI", value="✅ Да" if is_ai_enabled() else "❌ Нет", inline=True)
    embed.add_field(name="📦 Каталог", value=f"`{total}` товаров", inline=True)
    embed.add_field(name="🎯 Модель", value=f"`{AI_MANAGER_MODEL}`", inline=False)
    await ctx.send(embed=embed, ephemeral=True)


@bot.slash_command(name="am_toggle", description="Включить/выключить AI")
async def am_toggle(ctx: disnake.ApplicationCommandInteraction):
    if not has_admin_command_roles(ctx.author): return
    current = get_setting("ai_manager_enabled", "0")
    new_state = "0" if current == "1" else "1"
    set_setting("ai_manager_enabled", new_state)
    await ctx.send(f"✅ AI: **{'ВКЛ' if new_state == '1' else 'ВЫКЛ'}**", ephemeral=True)


@bot.slash_command(name="am_reload", description="Перезагрузить каталог")
async def am_reload(ctx: disnake.ApplicationCommandInteraction):
    if not has_admin_command_roles(ctx.author): return
    count = reload_catalog_from_json()
    await ctx.send(f"✅ Загружено **{count}** товаров.", ephemeral=True)


@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot: return
    if not isinstance(message.channel, disnake.TextChannel): return
    if message.content.startswith("!am"): return
    if not _is_ai_ticket(message.channel): return
    if not is_ai_enabled(): return

    channel = message.channel
    user_id = message.author.id

    # === ЧЕК ===
    if message.attachments:
        owner_id = get_ticket_owner(channel.id)
        if owner_id and message.author.id != owner_id:
            return # Игнорируем чужие файлы

        att = message.attachments[0]
        low = att.filename.lower()
        if any(low.endswith(x) for x in (".png", ".jpg", ".jpeg", ".pdf")):
            update_session(channel.id, receipt_url=att.url, escalated=1)
            
            embed = disnake.Embed(
                title="✅ Чек получен",
                description=(
                    f"> <@&{SALES_MANAGER_ROLE}> — заказ готов к проверке.\n"
                    f"> **Файл сохранён и передан менеджерам.**\n"
                    f"> 🤖 Я постараюсь в будущем понять данные методики тикетов."
                ),
                color=COLOR_GREY
            )
            embed.set_image(url=IMG_STRIPE)
            await channel.send(embed=embed)
            
            asyncio.create_task(notify_managers_dm(message, att.url))
            return

    # === ДИАЛОГ ===
    now = time.time()
    if now - COOLDOWN.get(user_id, 0) < SESSION_COOLDOWN_SEC: return
    COOLDOWN[user_id] = now

    sess = get_session(channel.id)
    if not sess:
        create_session(channel.id, user_id)
        sess = get_session(channel.id)

    if sess["escalated"]: return
    if sess["message_count"] >= SESSION_MAX_MESSAGES:
        await escalate(channel, "лимит сообщений")
        return

    update_session(channel.id, message_count=sess["message_count"] + 1)
    hist = HISTORY.setdefault(channel.id, [])
    hist.append(("user", message.content or ""))
    discount = await get_ticket_discount(channel)

    full_catalog = load_catalog_from_db()
    if not full_catalog:
        await channel.send("⚠️ Каталог пуст.")
        return

    # ФИЛЬТРУЕМ КАТАЛОГ, ЧТОБЫ ИИ НЕ ВИДЕЛ ЛИШНЕГО
    filtered_catalog = get_filtered_catalog(message.content or "", full_catalog)

    lines = []
    for cat_label, cat in filtered_catalog.items():
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
        result = await call_llm(system_prompt, hist, message.content or "")

    if not result:
        new_fails = sess["fail_count"] + 1
        update_session(channel.id, fail_count=new_fails)
        if new_fails >= SESSION_MAX_FAILS:
            await escalate(channel, "сбой LLM")
        return

    text = result.get("text", "").strip()
    funcs = result.get("funcs", [])

    if text:
        await message.reply(text, mention_author=False)
        hist.append(("ai", text))

    if funcs:
        update_session(channel.id, fail_count=0)
        fc = funcs[0] # Только первый вызов
        name = fc["name"]
        args = fc.get("args", {})

        if name == "create_invoice":
            item_id = args.get("item_id", "")
            quantity = int(args.get("quantity", 1))
            
            row = cur.execute("SELECT * FROM autoorder_catalog WHERE id=?", (item_id,)).fetchone()
            if not row:
                await escalate(channel, "Товар не найден в каталоге, возможно BuyALL")
                return
                
            item = dict(row)
            item["category"] = row["category"]
            
            # === ЖЕСТКАЯ ПРОВЕРКА КАТЕГОРИИ ===
            # Если юзер просит Спотифай, а ИИ вернул tg_stars, мы это блокируем
            user_low = message.content.lower()
            cat_low = item["category"].lower()
            if ("споти" in user_low or "spotify" in user_low) and "spotify" not in cat_low:
                await channel.send("❌ Извините, я не могу оформить этот товар.")
                await escalate(channel, "Ошибка сопоставления: запрошен Spotify")
                return

            ok = await send_invoice(channel, item, discount, message.author.display_name, quantity)
            if ok:
                ai_logger.info(f"Счёт: {channel.id} → {item['name']} x{quantity}")

        elif name == "escalate_to_human":
            await escalate(channel, args.get("reason", "Товар не найден в каталоге"))

    HISTORY[channel.id] = hist[-20:]


def run_ai_manager():
    if not AI_MANAGER_TOKEN:
        raise SystemExit(1)
    try:
        bot.run(AI_MANAGER_TOKEN)
    except Exception as e:
        ai_logger.exception(f"Ошибка запуска: {e}")
        raise
