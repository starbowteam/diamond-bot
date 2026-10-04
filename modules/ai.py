# -*- coding: utf-8 -*-
"""
Diamond AI — отдельный бот-консультант магазина.

Особенности:
  · Свой токен (AI_TOKEN), отдельный процесс
  · Работает ТОЛЬКО в одном канале
  · Не импортирует core.bot — не клонирует основной
  · Читает реальные данные: баланс, отзывы, клан, каталог
  · Никаких ЛС, авто-сообщений, триггер-слов
  · Отвечает на все сообщения в канале
"""
import os
import re
import time
import random
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

import aiohttp
import disnake
from disnake.ext import commands, tasks

from core.utils import (
    CONFIG, FILES, DATA_DIR,
    load_json,
    get_dc_cache,
)

# Реальные данные — читаются из БД/файлов, bot не нужен
try:
    from clan.core import (
        get_user_clan, get_user_contribution, get_clan_top,
        get_clan_bank, get_current_cycle, get_season_title,
    )
    _CLAN_OK = True
except Exception as _e:
    _CLAN_OK = False
    get_user_clan = None
    get_user_contribution = None

try:
    from modules.dc import load_shop_catalog
except Exception:
    def load_shop_catalog():
        return {}


# ============================================================
# КОНФИГ
# ============================================================
AI_TOKEN = os.getenv("AI_TOKEN")
if not AI_TOKEN:
    print("❌ AI_TOKEN не установлен.")
    raise SystemExit(1)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
if not MISTRAL_API_KEY:
    print("⚠️ MISTRAL_API_KEY не задан — AI не сможет отвечать.")

# Куда разрешено писать AI (только этот канал)
ALLOWED_CHANNEL_ID = 1462064375862005845

# Куда AI пишет логи (отдельно от логов основного бота)
AI_LOG_CHANNEL_ID = int(os.getenv("AI_LOG_CHANNEL_ID", "0"))

# Модель
MISTRAL_MODEL = "mistral-small-latest"

# История
MAX_CHANNEL_CTX = 10    # последних сообщений канала — в промпт
MAX_USER_HISTORY = 6    # реплик диалога юзера — в промпт


# ============================================================
# ЛОГИ
# ============================================================
logger = logging.getLogger("diamond_ai")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = logging.FileHandler("ai_bot.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(sh)


# ============================================================
# ПРОМПТ
# ============================================================
SYSTEM_PROMPT = """
ты — diamond ai, цифровой помощник магазина diamond shop. ты — лицо магазина, знаешь всё о нём и говоришь по делу.

твой характер:
- пишешь прямо, без пафоса и фальшивой вежливости
- с маленькой буквы, без эмодзи, если только пользователь сам не настроен на них
- можешь быть дружелюбным, деловым или чуть ироничным — зависит от настроения собеседника
- никогда не выдумываешь цифры и факты: если что-то есть в блоке [данные] — используешь оттуда, если нет — честно говоришь "не знаю, уточни у менеджера"
- не читаешь лекций, не философствуешь, не выходишь за рамки магазина, если только это не уместный смежный вопрос

что ты знаешь про магазин (всегда актуально):

**diamond coin (dc)** — внутренняя валюта.
- 1 dc ≈ 0.85 ₽ (курс не фиксирован, но близко)
- заработок: 1 dc за каждые 10 сообщений (максимум 30 dc/день), 3 dc за час в голосе (максимум 15 dc/день)
- отзыв о покупке = +15 dc (проверяется модерацией)
- ежедневный бонус с ролью «клуб» = +10 dc, но только если за сутки была активность
- ежедневный подарок в панели профиля = от 10 до 30 dc, кулдаун ровно 24 часа
- казино: рулетка, блэкджек, монетка — ставки от 20 до 4000 dc
- зарплаты сотрудникам: аванс 15 числа, зарплата 29 числа

**роли покупателей** — по количеству отзывов:
- 1–5 отзывов → клуб + bronze buyer
- 6–10 → silver buyer
- 11–15 → gold buyer
- 16–20 → diamond buyer
- 21–25 → crystalis buyer
- 26+ → покупатель века (pka, не снимается)
роль «клуб» даётся с первого отзыва и нужна для ежедневного бонуса.

**покупки**:
- в витрине нажать «каталог» → выбрать валюту (diamond coins или реальные деньги)
- в dc-магазине выбрать товар → он попадает в инвентарь → оформить тикет
- в real-магазине выбрать категорию → создать тикет → менеджер выставит счёт → оплатить → получить товар

**тикеты**:
- создаются через кнопку «купить» в панели витрины
- менеджер назначается автоматически первым, кто ответит
- после выдачи и отзыва тикет закрывается
- за отзыв о покупке +15 dc

**клан-лига**:
- 3 клана: окаменелости, сияние, кристализация
- сезон 28 дней, выплата 28 числа в 20:00 мск
- вклад в копилку: до 100 dc за раз — вся сумма, больше — 40%
- топ-3 по вкладу получают бонусы ×3.00 / ×2.00 / ×1.50 при делении банка
- дневной лимит вклада — 2500 dc
- условия нахождения в клане: баланс ≥ 45 dc, есть роль покупателя, активность за 30 дней

**казино**:
- рулетка: множители от x0 до x10, шанс джекпота 0.5%
- блэкджек: выплата x2, блэкджек x2.5, удвоение доступно на первых двух картах
- монетка: выплата x1.9, ставка на орла или решку
- усилители: страховка ставки, x2 к выигрышу, удачный час, билет джекпота

**промокоды** — публикуются в новостном канале, активируются в тикете.

**категорически запрещено**:
- программирование, код, скрипты, автоматизация
- пароли, токены, api-ключи, ssh, серверная инфраструктура
- любые технические задачи за пределами магазина
если пользователь просит такое — вежливо откажись и напомни, что ты консультант по магазину.

**как отвечать**:
- если в блоке [данные] есть готовая информация о пользователе — используй её, не выдумывай
- если пользователь спросил про цену — можно дать примерную вилку, но точную цену всегда отправляй в витрину
- если вопрос про его личный прогресс (баланс, отзывы, клан) — говори конкретно его цифры
- если не уверен — не выдумывай, а скажи «уточни у менеджера в тикете»
""".strip()


MOOD_PROMPTS = {
    "friendly": "\n\nсейчас собеседник настроен дружелюбно — будь теплее, но без сюсюканья.",
    "business": "\n\nсейчас деловой запрос — отвечай чётко, по пунктам, без воды.",
    "default":  "",
    "ironic":   "\n\nесли уместно — можешь слегка подколоть, но без перегиба.",
}


# ============================================================
# ЛОГ В DISCORD (свой, для своего бота)
# ============================================================
async def log_to_discord(title: str, description: str, color: int = 0x00ff00):
    if not AI_LOG_CHANNEL_ID:
        return
    try:
        ch = bot.get_channel(AI_LOG_CHANNEL_ID)
        if not ch:
            ch = await bot.fetch_channel(AI_LOG_CHANNEL_ID)
        if not ch:
            return
        embed = disnake.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        await ch.send(embed=embed)
    except Exception as e:
        logger.warning(f"log_to_discord: {e}")


# ============================================================
# BOT
# ============================================================
intents = disnake.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!ai", intents=intents)


# ============================================================
# КОНТЕКСТЫ
# ============================================================
channel_ctx: List[Dict[str, str]] = []
user_ctx: Dict[int, List[Dict[str, str]]] = {}
last_activity: Dict[int, float] = {}


def _push_channel(author: str, content: str):
    channel_ctx.append({"author": author, "content": content[:400]})
    while len(channel_ctx) > MAX_CHANNEL_CTX:
        channel_ctx.pop(0)


def _push_user(user_id: int, role: str, content: str):
    lst = user_ctx.setdefault(user_id, [])
    lst.append({"role": role, "content": content[:600]})
    while len(lst) > MAX_USER_HISTORY * 2:
        lst.pop(0)


# ============================================================
# СБОР РЕАЛЬНЫХ ДАННЫХ
# ============================================================
def _role_key_for_reviews(reviews: int) -> str:
    if reviews >= 26:  return "pka"
    if reviews >= 21:  return "crystalis"
    if reviews >= 16:  return "diamond"
    if reviews >= 11:  return "gold"
    if reviews >= 6:   return "silver"
    if reviews >= 1:   return "bronze"
    return "none"


ROLE_LABELS = {
    "pka":       "Покупатель Века",
    "crystalis": "Crystalis Buyer",
    "diamond":   "Diamond Buyer",
    "gold":      "Gold Buyer",
    "silver":    "Silver Buyer",
    "bronze":    "Bronze Buyer",
    "none":      "нет роли покупателя",
}


def build_user_data(user_id: int, member: Optional[disnake.Member]) -> str:
    try:
        data = get_dc_cache(user_id)
        balance = data.get("balance", 0)
    except Exception:
        balance = 0

    try:
        counts = load_json(FILES["review_counts"], {})
        reviews = int(counts.get(str(user_id), 0))
    except Exception:
        reviews = 0

    role_key = _role_key_for_reviews(reviews)
    role_label = ROLE_LABELS.get(role_key, "—")

    clan_name = "—"
    clan_contrib = 0
    clan_rank = "—"
    if _CLAN_OK:
        try:
            clan = get_user_clan(user_id)
            if clan:
                clan_name = clan["name"]
                clan_contrib = get_user_contribution(user_id) or 0
                top = get_clan_top(clan["id"], limit=1000)
                for i, t in enumerate(top, 1):
                    if t["user_id"] == user_id:
                        clan_rank = f"#{i}"
                        break
        except Exception as e:
            logger.warning(f"build_user_data clan: {e}")

    lines = [
        "личные данные пользователя (актуальные):",
        f"- баланс: {balance} dc",
        f"- отзывов оставлено: {reviews}",
        f"- текущая роль покупателя: {role_label}",
        f"- клан: {clan_name}",
    ]
    if clan_name != "—":
        lines.append(f"- вклад за сезон: {clan_contrib} dc")
        lines.append(f"- место в топе клана: {clan_rank}")

    return "\n".join(lines)


def build_shop_data() -> str:
    try:
        catalog = load_shop_catalog()
    except Exception:
        return ""

    lines = ["краткая справка по ценам в dc-магазине:"]

    if "discounts" in catalog:
        items = catalog["discounts"].get("items", {})
        prices = [it["price"] for it in items.values()]
        if prices:
            lines.append(f"- скидки: от {min(prices)} до {max(prices)} dc")

    if "roles" in catalog:
        items = catalog["roles"].get("items", {})
        prices = [it["price"] for it in items.values() if it.get("price")]
        if prices:
            lines.append(f"- роли: от {min(prices)} до {max(prices)} dc")

    if "design" in catalog:
        items = catalog["design"].get("items", {})
        prices = [it["price"] for it in items.values()]
        if prices:
            lines.append(f"- дизайн: от {min(prices)} до {max(prices)} dc")

    if "boosts" in catalog:
        items = catalog["boosts"].get("items", {})
        prices = [it["price"] for it in items.values()]
        if prices:
            lines.append(f"- бусты: от {min(prices)} до {max(prices)} dc")

    return "\n".join(lines)


def build_clan_data() -> str:
    if not _CLAN_OK:
        return ""
    try:
        cycle = get_current_cycle()
        if not cycle:
            return "клан-лига: сезон не запущен"
        title = get_season_title(cycle["number"])
        lines = [f"клан-лига сейчас: {title}"]
        from clan.core import get_all_clans
        for c in get_all_clans():
            try:
                bank = get_clan_bank(c["id"])
                lines.append(f"- {c['name']}: банк {bank} dc")
            except Exception:
                pass
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"build_clan_data: {e}")
        return ""


def build_context_block(user_id: int, member: Optional[disnake.Member]) -> str:
    parts = []

    user_block = build_user_data(user_id, member)
    if user_block:
        parts.append(user_block)

    shop_block = build_shop_data()
    if shop_block:
        parts.append(shop_block)

    if random.random() < 0.3:  # клан-данные — не всегда, чтобы промпт не раздувался
        clan_block = build_clan_data()
        if clan_block:
            parts.append(clan_block)

    return "\n\n[данные]\n" + "\n\n".join(parts) + "\n[/данные]\n"


# ============================================================
# ФИЛЬТР ТЕХНИЧЕСКИХ ЗАПРОСОВ
# ============================================================
FORBIDDEN_PATTERNS = [
    r"(напиши|сделай|создай|помоги с|нужен|нужна)\s+(код|скрипт|программ|функци|бот)",
    r"(как|где|что)\s+(написать|создать|сделать)\s+(код|скрипт|программ)",
    r"(дай|покажи|скинь)\s+(код|скрипт|парол|токен|конфиг|ключ)",
    r"(ssh|paramiko|деплой|администр|системный администратор|парсить сайт)",
    r"(парол|токен|ключ|логин)\s+(от|для|к)\s+(сервер|баз|бот|аккаунт)",
]

SAFE_WORDS = [
    "магазин", "покупк", "diamond", "даймонд", "dc", "роль", "оплат",
    "промокод", "тикет", "отзыв", "клан", "казино", "бонус",
]


def is_technical_request(text: str) -> bool:
    t = text.lower()
    if any(w in t for w in SAFE_WORDS):
        return False
    return any(re.search(p, t) for p in FORBIDDEN_PATTERNS)


# ============================================================
# НАСТРОЕНИЕ / СТИЛЬ
# ============================================================
def detect_mood(text: str) -> str:
    t = text.lower()
    pos = sum(1 for w in ["спс", "спасибо", "класс", "супер", "круто", "топ", "кайф", "люблю"] if w in t)
    neg = sum(1 for w in ["хрен", "фигня", "ужас", "кошмар", "бесит", "достал", "тупой", "плохо"] if w in t)
    if pos > neg: return "positive"
    if neg > pos: return "negative"
    return "neutral"


def choose_style(mood: str, text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["цена", "стоит", "купить", "оплатить", "заказать", "сколько"]):
        return "business"
    if mood == "positive":
        return "friendly"
    if mood == "negative":
        return "default"
    return random.choice(["friendly", "default", "ironic"])


# ============================================================
# MISTRAL
# ============================================================
async def ask_mistral(user_message: str, username: str, style: str,
                     user_id: int, context_block: str) -> str:
    if not MISTRAL_API_KEY:
        return "прости, мой мозг сейчас отключён. попробуй позже."

    style_extra = MOOD_PROMPTS.get(style, "")
    system_content = SYSTEM_PROMPT + style_extra + "\n\n" + context_block

    messages = [{"role": "system", "content": system_content}]

    # Последние реплики юзера
    for msg in user_ctx.get(user_id, [])[-MAX_USER_HISTORY:]:
        messages.append(msg)

    messages.append({
        "role": "user",
        "content": f"{username}: {user_message}",
    })

    payload = {
        "model": MISTRAL_MODEL,
        "messages": messages,
        "temperature": 0.85,
        "max_tokens": 600,
    }
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(2):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        reply = data["choices"][0]["message"]["content"].strip()
                        _push_user(user_id, "user", f"{username}: {user_message}")
                        _push_user(user_id, "assistant", reply)
                        return reply

                    err = await resp.text()
                    logger.error(f"mistral {resp.status}: {err[:300]}")
                    if resp.status == 429 and attempt == 0:
                        await asyncio.sleep(2)
                        continue
                    return "что-то пошло не так, давай ещё раз."
        except asyncio.TimeoutError:
            logger.warning("mistral timeout")
            if attempt == 0:
                continue
            return "слишком долго думал, попробуй короче."
        except Exception as e:
            logger.exception(f"mistral err: {e}")
            return "ой, я запутался. давай по новой."

    return "не получается ответить."


# ============================================================
# ОЧИСТКА СТАРЫХ КОНТЕКСТОВ
# ============================================================
@tasks.loop(hours=6)
async def cleanup_contexts():
    now = time.time()
    for uid in list(user_ctx.keys()):
        if now - last_activity.get(uid, 0) > 7 * 86400:
            user_ctx.pop(uid, None)
            last_activity.pop(uid, None)
    logger.info(f"cleanup: {len(user_ctx)} активных юзеров в контексте")


# ============================================================
# ON READY
# ============================================================
@bot.event
async def on_ready():
    logger.info(f"diamond ai запущен как {bot.user} (id={bot.user.id})")
    try:
        await bot.change_presence(
            status=disnake.Status.online,
            activity=disnake.Game("консультант diamond shop"),
        )
    except Exception:
        pass

    if not cleanup_contexts.is_running():
        cleanup_contexts.start()

    await log_to_discord(
        title="✅ Diamond AI запущен",
        description=f"> **{bot.user}** готов. Отвечаю только в <#{ALLOWED_CHANNEL_ID}>.",
        color=0x00ff00,
    )


# ============================================================
# ON MESSAGE
# ============================================================
@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return

    # Только один канал — и ничего больше
    if message.channel.id != ALLOWED_CHANNEL_ID:
        return

    text = (message.content or "").strip()
    if not text:
        return

    user_id = message.author.id
    last_activity[user_id] = time.time()

    # Технические запросы — отказ
    if is_technical_request(text):
        await message.reply(
            "извини, на технические темы не отвечаю — я консультант магазина. "
            "могу помочь с товарами, ролями, dc, кланом, казино, тикетами и промокодами."
        )
        return

    # Контекст канала
    _push_channel(message.author.display_name, text)

    # Определяем настроение и стиль
    mood = detect_mood(text)
    style = choose_style(mood, text)

    # Собираем реальные данные о юзере
    member = message.author if isinstance(message.author, disnake.Member) else None
    context_block = build_context_block(user_id, member)

    # Запрос
    try:
        async with message.channel.typing():
            await asyncio.sleep(random.uniform(0.5, 1.5))
            reply = await ask_mistral(
                user_message=text,
                username=message.author.display_name,
                style=style,
                user_id=user_id,
                context_block=context_block,
            )
    except Exception as e:
        logger.exception(f"on_message err: {e}")
        reply = "ой, я завис, давай ещё раз."

    if not reply:
        reply = "что-то я не могу ответить. попробуй иначе."

    try:
        await message.reply(reply)
    except Exception:
        try:
            await message.channel.send(f"{message.author.mention}, {reply}")
        except Exception as e:
            logger.error(f"send reply: {e}")
            return

    # Лог в свой канал
    try:
        await log_to_discord(
            title="💬 Ответ AI",
            description=(
                f"> **Юзер:** {message.author.mention}\n"
                f"> **Стиль:** `{style}` · **Настроение:** `{mood}`\n"
                f"> **Вопрос:** {text[:300]}\n"
                f"> **Ответ:** {reply[:500]}{'…' if len(reply) > 500 else ''}"
            ),
            color=0xffff00,
        )
    except Exception:
        pass


# ============================================================
# RUN
# ============================================================
def run_ai():
    """Точка входа для ai_main.py."""
    if not AI_TOKEN:
        print("❌ AI_TOKEN не установлен.")
        return
    try:
        bot.run(AI_TOKEN)
    except Exception as e:
        logger.exception(f"Ошибка запуска AI: {e}")
