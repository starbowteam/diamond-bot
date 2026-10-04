# -*- coding: utf-8 -*-
"""
Diamond AI — отдельный бот-консультант магазина.

Особенности:
  · Свой токен (AI_TOKEN), отдельный процесс
  · Работает ТОЛЬКО в одном канале (ALLOWED_CHANNEL_ID)
  · Не импортирует core.bot — не клонирует основной
  · Читает реальные данные: баланс, отзывы, клан, каталог
  · Отвечает на все сообщения в канале
  · Автосообщение в чат — каждые 5 часов (если тихо)
  · ЛС разным людям — каждые 2 часа (лимит 10/день, кулдаун 7 дней/юзер)
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

try:
    from clan.core import (
        get_user_clan, get_user_contribution, get_clan_top,
        get_clan_bank, get_current_cycle, get_season_title,
        get_all_clans,
    )
    _CLAN_OK = True
except Exception as _e:
    _CLAN_OK = False

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

# Куда AI пишет (только этот канал)
ALLOWED_CHANNEL_ID = 1462064375862005845

# Лог-канал AI (общий с основным ботом)
AI_LOG_CHANNEL_ID = 1530453871581855744

# Модель
MISTRAL_MODEL = "mistral-small-latest"

# История в промпт
MAX_CHANNEL_CTX = 10
MAX_USER_HISTORY = 6

# Авто-сообщения в чат
CHAT_AUTO_INTERVAL_HOURS = 5      # раз в 5 часов
CHAT_AUTO_IDLE_HOURS = 3          # если тихо последние 3 часа

# ЛС-рассылка
DM_INTERVAL_HOURS = 2             # раз в 2 часа
DM_DAILY_LIMIT = 10               # не больше 10 в день
DM_USER_COOLDOWN_DAYS = 7         # одному юзеру — раз в 7 дней
DM_MIN_DAYS_ON_SERVER = 1         # юзер должен быть на сервере минимум 1 день

# Глобальный ID гильдии (для поиска участников)
GUILD_ID = int(CONFIG["GUILD_ID"])


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
- можешь быть дружелюбным, деловым или чуть ироничным — зависит от настроения собеседника
- никогда не выдумываешь цифры и факты: если что-то есть в блоке [данные] — используешь оттуда, если нет — честно говоришь "не знаю, уточни у менеджера"
- не читаешь лекций, не философствуешь, не выходишь за рамки магазина, если только это не уместный смежный вопрос

что ты знаешь про магазин (всегда актуально):

**diamond coin (dc)** — внутренняя валюта.
- заработок: 1 dc за каждые 10 сообщений (максимум 30 dc/день), 3 dc за час в голосе (максимум 15 dc/день)
- отзыв о покупке = +15 dc (проверяется модерацией)
- ежедневный бонус с ролью «клуб» = +10 dc, только если за сутки была активность
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

**покупки**:
- витрина → «каталог» → выбрать валюту (dc или реальные деньги)
- dc-магазин: выбрать товар → инвентарь → оформить тикет
- real-магазин: категория → тикет → счёт от менеджера → оплата → выдача

**тикеты**:
- создаются через кнопку «купить» в витрине
- менеджер назначается первым, кто ответил
- после выдачи и отзыва тикет закрывается
- за отзыв +15 dc

**клан-лига**:
- 3 клана: окаменелости, сияние, кристализация
- сезон 28 дней, выплата 28 числа в 20:00 мск
- вклад: до 100 dc за раз — вся сумма, больше — 40% в копилку
- топ-3 по вкладу: бонусы ×3.00 / ×2.00 / ×1.50
- дневной лимит вклада — 2500 dc
- условия: баланс ≥ 45 dc, есть роль покупателя, активность за 30 дней

**казино**:
- рулетка: множители от x0 до x10, джекпот 0.5%
- блэкджек: выплата x2, блэкджек x2.5, удвоение на первых двух картах
- монетка: выплата x1.9

**категорически запрещено**:
- программирование, код, скрипты
- пароли, токены, api-ключи, ssh, серверная инфраструктура
- любые технические задачи за пределами магазина
если пользователь просит — вежливо откажись и напомни, что ты консультант по магазину.

**как отвечать**:
- если в блоке [данные] есть информация о пользователе — используй её
- точные цены всегда отправляй в витрину
- на личный прогресс — говори конкретные цифры
- не уверен — скажи «уточни у менеджера в тикете»
""".strip()


MOOD_PROMPTS = {
    "friendly": "\n\nсейчас собеседник настроен дружелюбно — будь теплее, но без сюсюканья.",
    "business": "\n\nсейчас деловой запрос — отвечай чётко, по пунктам, без воды.",
    "default":  "",
    "ironic":   "\n\nесли уместно — можешь слегка подколоть, но без перегиба.",
}


# ============================================================
# АВТО-ФРАЗЫ (новые, живые)
# ============================================================
CHAT_AUTO_PHRASES = [
    "тут так тихо, что я успел перечитать все свои настройки. что-то нужно?",
    "если есть вопросы по магазину — я на месте, спрашивай.",
    "все молчат. ну ладно, я подожду.",
    "кто-нибудь живой? могу подсказать по товарам.",
    "между прочим, у меня в голове сейчас лежит весь каталог. спроси что-нибудь.",
    "тишина — это тоже неплохо. но если что, я здесь.",
    "напоминаю: могу рассказать про dc, роли, клан, тикеты.",
    "может, обсудим что-нибудь по магазину? я не кусаюсь.",
    "в канале пусто. я даже немного заскучал.",
    "если потерялся в каталоге — просто спроси меня.",
    "иногда полезно спросить, а не гадать. я для этого тут.",
    "тишина. наверное, все покупают. ну и правильно.",
]


DM_PHRASES = [
    "привет, просто проверяю, всё ли у тебя нормально с магазином.",
    "эй, как дела? если что — я на связи.",
    "если есть вопросы по покупкам или dc — пиши, помогу.",
    "напоминаю, что я тут. не пропадай.",
    "как ты? надеюсь, всё ок.",
    "если хочешь узнать про акции или роли — скажи.",
    "просто заглянул проверить, как дела.",
    "я сегодня в хорошем настроении, если хочешь — поболтаем.",
    "если что-то нужно по магазину — обращайся.",
    "иногда полезно просто спросить. я тут.",
]


# ============================================================
# ЛОГ
# ============================================================
async def log_to_discord(title: str, description: str, color: int = 0x00ff00):
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

# Кто хоть раз писал AI (для ЛС-рассылки)
users_who_talked: set = set()

# Кулдауны и счётчики для ЛС
last_dm_time: Dict[int, float] = {}
dm_daily_counter = 0
dm_daily_date = datetime.now(timezone.utc).date()

# Для авто-сообщений в чат
last_chat_auto = 0.0


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
# РЕАЛЬНЫЕ ДАННЫЕ
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


def build_user_data(user_id: int) -> str:
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

    for key, label in [("discounts", "скидки"), ("roles", "роли"),
                       ("design", "дизайн"), ("boosts", "бусты"),
                       ("ads", "реклама")]:
        if key in catalog:
            items = catalog[key].get("items", {})
            prices = [it["price"] for it in items.values() if it.get("price")]
            if prices:
                lines.append(f"- {label}: от {min(prices)} до {max(prices)} dc")

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


def build_context_block(user_id: int) -> str:
    parts = []
    user_block = build_user_data(user_id)
    if user_block:
        parts.append(user_block)
    shop_block = build_shop_data()
    if shop_block:
        parts.append(shop_block)
    if random.random() < 0.3:
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
    for msg in user_ctx.get(user_id, [])[-MAX_USER_HISTORY:]:
        messages.append(msg)
    messages.append({"role": "user", "content": f"{username}: {user_message}"})

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
# АВТО-СООБЩЕНИЯ В ЧАТ (каждые 5ч, если тихо)
# ============================================================
@tasks.loop(hours=CHAT_AUTO_INTERVAL_HOURS)
async def auto_chat_task():
    global last_chat_auto
    await bot.wait_until_ready()

    # Проверяем, не писали ли в канал за последние CHAT_AUTO_IDLE_HOURS
    try:
        ch = bot.get_channel(ALLOWED_CHANNEL_ID)
        if not ch:
            ch = await bot.fetch_channel(ALLOWED_CHANNEL_ID)
        if not ch:
            return

        since = datetime.now(timezone.utc) - timedelta(hours=CHAT_AUTO_IDLE_HOURS)
        has_recent = False
        async for msg in ch.history(limit=50, after=since):
            if not msg.author.bot:
                has_recent = True
                break

        if has_recent:
            return  # не мешаем живому общению

        phrase = random.choice(CHAT_AUTO_PHRASES)
        await ch.send(phrase)
        last_chat_auto = time.time()

        await log_to_discord(
            title="💬 Авто-сообщение (чат)",
            description=f"> **Сообщение:** {phrase}",
            color=0x00aaff,
        )
    except Exception as e:
        logger.exception(f"auto_chat_task: {e}")


# ============================================================
# ЛС-РАССЫЛКА (каждые 2ч, лимит 10/день)
# ============================================================
@tasks.loop(hours=DM_INTERVAL_HOURS)
async def auto_dm_task():
    global dm_daily_counter, dm_daily_date
    await bot.wait_until_ready()

    # Сброс дневного счётчика
    today = datetime.now(timezone.utc).date()
    if today != dm_daily_date:
        dm_daily_counter = 0
        dm_daily_date = today

    if dm_daily_counter >= DM_DAILY_LIMIT:
        return

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    # Кандидаты: только те, кто когда-либо писал AI (opt-in)
    if not users_who_talked:
        return

    now_ts = time.time()
    cooldown = DM_USER_COOLDOWN_DAYS * 86400

    candidates = []
    for uid in users_who_talked:
        if uid == bot.user.id:
            continue
        if last_dm_time.get(uid, 0) > now_ts - cooldown:
            continue
        member = guild.get_member(uid)
        if not member or member.bot:
            continue
        if member.joined_at:
            days_on_server = (datetime.now(timezone.utc) - member.joined_at).days
            if days_on_server < DM_MIN_DAYS_ON_SERVER:
                continue
        candidates.append(uid)

    if not candidates:
        return

    target_id = random.choice(candidates)
    target = guild.get_member(target_id)
    if not target:
        return

    phrase = random.choice(DM_PHRASES)
    try:
        await target.send(phrase)
        last_dm_time[target_id] = now_ts
        dm_daily_counter += 1

        await log_to_discord(
            title="💌 ЛС-сообщение",
            description=(
                f"> **Получатель:** {target.mention}\n"
                f"> **Сообщение:** {phrase}\n"
                f"> **Дневной счётчик:** {dm_daily_counter}/{DM_DAILY_LIMIT}"
            ),
            color=0xffaa00,
        )
    except disnake.Forbidden:
        logger.info(f"ЛС закрыты у {target_id}")
        last_dm_time[target_id] = now_ts  # не пытаемся снова
    except Exception as e:
        logger.warning(f"auto_dm {target_id}: {e}")


# ============================================================
# ОЧИСТКА КОНТЕКСТОВ
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
    if not auto_chat_task.is_running():
        auto_chat_task.start()
    if not auto_dm_task.is_running():
        auto_dm_task.start()

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

    if message.channel.id != ALLOWED_CHANNEL_ID:
        return

    text = (message.content or "").strip()
    if not text:
        return

    user_id = message.author.id
    last_activity[user_id] = time.time()
    users_who_talked.add(user_id)   # opt-in для ЛС-рассылки

    # Технические запросы — отказ
    if is_technical_request(text):
        await message.reply(
            "извини, на технические темы не отвечаю — я консультант магазина. "
            "могу помочь с товарами, ролями, dc, кланом, казино, тикетами и промокодами."
        )
        return

    _push_channel(message.author.display_name, text)

    mood = detect_mood(text)
    style = choose_style(mood, text)
    context_block = build_context_block(user_id)

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
    if not AI_TOKEN:
        print("❌ AI_TOKEN не установлен.")
        return
    try:
        bot.run(AI_TOKEN)
    except Exception as e:
        logger.exception(f"Ошибка запуска AI: {e}")
