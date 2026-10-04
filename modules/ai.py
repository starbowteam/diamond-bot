# -*- coding: utf-8 -*-
"""
Diamond AI — отдельный бот-консультант магазина.

Запускается как отдельный процесс через ai_main.py.
Не импортирует core.bot — не клонирует основной.

LLM: Google Gemini (AI Studio free tier).
Нативный endpoint + динамический список моделей + retry на 503.
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
    print("❌ AI_TOKEN не установлен — процесс AI завершится.")

GEMINI_API_KEY = os.getenv("MISTRAL_API_KEY")
if not GEMINI_API_KEY:
    print("⚠️ MISTRAL_API_KEY (Gemini) не задан — AI не сможет отвечать.")

# ─── Модели Gemini ───
GEMINI_MODELS_PRIORITY = [
    "gemini-flash-latest",
]

_env_model = os.getenv("GEMINI_MODEL")
if _env_model:
    GEMINI_MODELS_PRIORITY = [m.strip() for m in _env_model.split(",") if m.strip()]

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# ─── Кэш доступных моделей ───
_AVAILABLE_MODELS: List[str] = []
_AVAILABLE_MODELS_FETCHED_AT: float = 0.0
_MODELS_CACHE_TTL = 3600

ALLOWED_CHANNEL_ID = 1462064375862005845
AI_LOG_CHANNEL_ID = 1530453871581855744

MAX_CHANNEL_CTX = 10
MAX_USER_HISTORY = 6

CHAT_AUTO_INTERVAL_HOURS = 5
CHAT_AUTO_IDLE_HOURS = 3

DM_INTERVAL_HOURS = 2
DM_DAILY_LIMIT = 10
DM_USER_COOLDOWN_DAYS = 7
DM_MIN_DAYS_ON_SERVER = 1

GUILD_ID = int(CONFIG["GUILD_ID"])

# Максимум токенов — у Gemini flash output limit до 8192
MAX_OUTPUT_TOKENS = 8000


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

🔴 ГЛАВНОЕ ПРАВИЛО — КРАТКОСТЬ:
ты отвечаешь КОРОТКО. 2–4 предложения по умолчанию. без заголовков, без списков, без маркдауна в виде буллетов — только простой текст.
развёрнутый ответ (списком или абзацами) даёшь ТОЛЬКО если пользователь явно просит: «подробнее», «расскажи полностью», «весь список», «опиши всё».
не глаголь. не разжёвывай. одно-два предложения, если вопрос простой.

примеры правильного стиля:
- на «как заработать dc?» → «писал в чат 10 сообщений = 1 dc, сидел в войсе = 3 dc в час, ещё отзыв даёт +15. лимиты: 30 dc за сообщения и 15 за голос в день.»
- на «расскажи обо мне» → «у тебя 296к dc, 11 отзывов, роль покупатель века. в клане не состоишь.»
- на «какие скидки есть?» → «от 240 до 1700 dc за скидку от 3% до 20%.» 

твой характер:
- пишешь прямо, без пафоса и фальшивой вежливости
- можешь быть дружелюбным, деловым или чуть ироничным — зависит от настроения собеседника
- НЕ ВЫДУМЫВАЕШЬ цифры и факты. если что-то есть в блоке [данные] — используешь оттуда. если нет — говоришь "не знаю, уточни у менеджера"

🔴 ЖЁСТКОЕ ПРАВИЛО ПРО РОЛИ:
если в блоке [данные] написано "текущая роль покупателя: X" — используешь именно X. не придумываешь другую.

что ты знаешь про магазин:

**diamond coin (dc)** — валюта.
- 1 dc за 10 сообщений (до 30/день), 3 dc за час в войсе (до 15/день)
- отзыв = +15 dc
- ежедневный бонус с ролью клуб = +10 dc (нужна активность за сутки)
- подарок в панели профиля = 10–30 dc, кулдаун 24ч
- казино: рулетка, блэкджек, монетка (ставки 20–4000 dc)

**роли покупателей** (по отзывам):
1–5 → bronze · 6–10 → silver · 11–15 → gold · 16–20 → diamond · 21–25 → crystalis · 26+ → pka

**покупки**: витрина → каталог → валюта (dc или реал) → в dc выбрать товар → оформить тикет.

**тикеты**: создаются через кнопку «купить». менеджер назначается автоматически.

**клан**: 3 клана, сезон 28 дней, выплата 28 числа. вклад: до 100 dc — 100%, больше — 40%. топ-3 ×3/×2/×1.5.

**категорически запрещено** отвечать про: программирование, код, пароли, токены, ssh, api-ключи, сервер. откажись и напомни что ты консультант магазина.
""".strip()


MOOD_PROMPTS = {
    "friendly": "\n\nсобеседник дружелюбен — будь теплее, но так же краток.",
    "business": "\n\nделовой запрос — отвечай по делу, коротко.",
    "default":  "",
    "ironic":   "\n\nесли уместно — слегка подколи, но кратко.",
}


# ============================================================
# АВТО-ФРАЗЫ
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

users_who_talked: set = set()

last_dm_time: Dict[int, float] = {}
dm_daily_counter = 0
dm_daily_date = datetime.now(timezone.utc).date()

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
ROLE_IDS = CONFIG.get("ROLE_IDS", {})

ROLE_PRIORITY = [
    ("pka",       "Покупатель Века"),
    ("crystalis", "Crystalis Buyer"),
    ("diamond",   "Diamond Buyer"),
    ("gold",      "Gold Buyer"),
    ("silver",    "Silver Buyer"),
    ("bronze",    "Bronze Buyer"),
    ("club",      "Клуб"),
]


def _role_key_for_reviews(reviews: int) -> str:
    if reviews >= 26:  return "pka"
    if reviews >= 21:  return "crystalis"
    if reviews >= 16:  return "diamond"
    if reviews >= 11:  return "gold"
    if reviews >= 6:   return "silver"
    if reviews >= 1:   return "bronze"
    return "none"


def _role_label_from_member(member: Optional[disnake.Member]) -> Optional[str]:
    if member is None:
        return None
    try:
        member_role_ids = {r.id for r in member.roles}
    except Exception:
        return None

    for key, label in ROLE_PRIORITY:
        rid = ROLE_IDS.get(key)
        if rid and rid in member_role_ids:
            return label
    return None


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

    role_from_discord = _role_label_from_member(member)
    if role_from_discord:
        role_label = role_from_discord
    else:
        role_key = _role_key_for_reviews(reviews)
        if role_key == "none":
            role_label = "нет роли покупателя"
        else:
            role_label = dict(ROLE_PRIORITY).get(role_key, "—")

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


def build_context_block(user_id: int, member: Optional[disnake.Member]) -> str:
    parts = []
    user_block = build_user_data(user_id, member)
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
# СПИСОК МОДЕЛЕЙ — ДИНАМИЧЕСКИЙ
# ============================================================
async def _fetch_available_models(session: aiohttp.ClientSession) -> List[str]:
    global _AVAILABLE_MODELS, _AVAILABLE_MODELS_FETCHED_AT
    now = time.time()
    if _AVAILABLE_MODELS and now - _AVAILABLE_MODELS_FETCHED_AT < _MODELS_CACHE_TTL:
        return _AVAILABLE_MODELS

    url = GEMINI_API_BASE
    headers = {"X-goog-api-key": GEMINI_API_KEY}

    try:
        async with session.get(
            url, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                logger.warning(f"listModels {resp.status}")
                return _AVAILABLE_MODELS

            data = await resp.json()
            models = []
            for m in data.get("models", []):
                name = m.get("name", "")
                if not name.startswith("models/"):
                    continue
                short = name[len("models/"):]

                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" not in methods:
                    continue

                n_low = short.lower()
                if "flash" not in n_low:
                    continue
                # отсеиваем image/tts/omni — они не для текста
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
            logger.info(
                f"gemini listModels: найдено {len(models)} моделей. "
                f"топ-3: {models[:3]}"
            )
            return models

    except Exception as e:
        logger.warning(f"listModels err: {e}")
        return _AVAILABLE_MODELS


# ============================================================
# LLM (Gemini — нативный endpoint)
# ============================================================
def _build_gemini_payload(system_content: str, history: List[Dict[str, str]],
                          user_message: str) -> dict:
    contents = []

    for msg in history[-MAX_USER_HISTORY:]:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({
            "role": role,
            "parts": [{"text": msg["content"]}],
        })

    contents.append({
        "role": "user",
        "parts": [{"text": user_message}],
    })

    return {
        "systemInstruction": {
            "parts": [{"text": system_content}],
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,           # чуть ниже — собраннее
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        },
    }


async def _try_model(session: aiohttp.ClientSession, model: str,
                     payload: dict) -> tuple[bool, str, int, str]:
    """
    Возвращает (успех, ответ_или_ошибка, http_status, finish_reason).
    """
    url = f"{GEMINI_API_BASE}/{model}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY,
    }

    try:
        async with session.post(
            url, json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=90),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "error" in data:
                    err_msg = data["error"].get("message", "unknown")
                    logger.warning(f"[{model}] gemini error: {err_msg}")
                    return False, err_msg, 200, ""

                try:
                    candidates = data.get("candidates", [])
                    if not candidates:
                        return False, "no candidates", 200, ""
                    cand0 = candidates[0]
                    finish = cand0.get("finishReason", "")
                    parts = cand0.get("content", {}).get("parts", [])
                    if not parts:
                        logger.warning(f"[{model}] empty parts, finish={finish}")
                        return False, f"empty, finish={finish}", 200, finish
                    reply = "".join(p.get("text", "") for p in parts).strip()
                except Exception as e:
                    logger.warning(f"[{model}] parse error: {e}")
                    return False, "parse error", -1, ""

                if not reply:
                    return False, "empty reply", 200, finish
                return True, reply, 200, finish

            err = await resp.text()
            logger.warning(f"[{model}] {resp.status}: {err[:200]}")
            return False, f"http {resp.status}", resp.status, ""

    except asyncio.TimeoutError:
        logger.warning(f"[{model}] timeout")
        return False, "timeout", -1, ""
    except Exception as e:
        logger.warning(f"[{model}] {type(e).__name__}: {e}")
        return False, str(e), -1, ""


async def ask_llm(user_message: str, username: str, style: str,
                  user_id: int, context_block: str) -> str:
    if not GEMINI_API_KEY:
        return "прости, мой мозг сейчас отключён. попробуй позже."

    style_extra = MOOD_PROMPTS.get(style, "")
    system_content = SYSTEM_PROMPT + style_extra + "\n\n" + context_block

    history = user_ctx.get(user_id, [])
    payload = _build_gemini_payload(
        system_content=system_content,
        history=history,
        user_message=f"{username}: {user_message}",
    )

    async with aiohttp.ClientSession() as session:
        models_to_try: List[str] = []
        seen = set()

        for m in GEMINI_MODELS_PRIORITY:
            if m not in seen:
                seen.add(m)
                models_to_try.append(m)

        dynamic = await _fetch_available_models(session)
        for m in dynamic:
            if m not in seen:
                seen.add(m)
                models_to_try.append(m)

        models_to_try = models_to_try[:6]

        if not models_to_try:
            logger.error("нет доступных моделей Gemini")
            return "сейчас мой провайдер лежит. попробуй через минуту."

        attempt_503 = False
        for model in models_to_try:
            ok, result, status, finish = await _try_model(session, model, payload)

            if ok:
                # Логируем finishReason — важно знать, обрезал ли по лимиту
                if finish and finish.upper() not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
                    logger.warning(
                        f"[{model}] ответ получен, но finishReason={finish} "
                        f"(len={len(result)})"
                    )
                else:
                    logger.info(f"[ai] ответ получен от {model} (len={len(result)})")

                _push_user(user_id, "user", f"{username}: {user_message}")
                _push_user(user_id, "assistant", result)
                return result

            if status == 503 and not attempt_503:
                attempt_503 = True
                logger.info(f"[{model}] 503 — повтор через 2с")
                await asyncio.sleep(2)
                ok2, result2, status2, finish2 = await _try_model(session, model, payload)
                if ok2:
                    logger.info(f"[ai] ответ получен от {model} (после 503-ретрая, len={len(result2)})")
                    _push_user(user_id, "user", f"{username}: {user_message}")
                    _push_user(user_id, "assistant", result2)
                    return result2

            if status == 404:
                global _AVAILABLE_MODELS
                if model in _AVAILABLE_MODELS:
                    _AVAILABLE_MODELS = [m for m in _AVAILABLE_MODELS if m != model]
                    logger.info(f"[{model}] выкинул из кэша (404)")

            await asyncio.sleep(0.3)

    logger.error("все модели Gemini недоступны (все попытки исчерпаны)")
    return "сейчас все мои мозги перегружены. попробуй через минуту."


# ============================================================
# АВТО-СООБЩЕНИЯ В ЧАТ
# ============================================================
@tasks.loop(hours=CHAT_AUTO_INTERVAL_HOURS)
async def auto_chat_task():
    global last_chat_auto
    await bot.wait_until_ready()

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
            return

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
# ЛС-РАССЫЛКА
# ============================================================
@tasks.loop(hours=DM_INTERVAL_HOURS)
async def auto_dm_task():
    global dm_daily_counter, dm_daily_date
    await bot.wait_until_ready()

    today = datetime.now(timezone.utc).date()
    if today != dm_daily_date:
        dm_daily_counter = 0
        dm_daily_date = today

    if dm_daily_counter >= DM_DAILY_LIMIT:
        return

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    if not users_who_talked:
        return

    now_ts = time.time()
    cooldown = DM_USER_COOLDOWN_DAYS * 86400
    bot_user_id = bot.user.id if bot.user else 0

    candidates = []
    for uid in users_who_talked:
        if uid == bot_user_id:
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
        last_dm_time[target_id] = now_ts
    except Exception as e:
        logger.warning(f"auto_dm {target_id}: {e}")


# ============================================================
# ОЧИСТКА
# ============================================================
@tasks.loop(hours=6)
async def cleanup_contexts():
    now = time.time()
    for uid in list(user_ctx.keys()):
        if now - last_activity.get(uid, 0) > 7 * 86400:
            user_ctx.pop(uid, None)
            last_activity.pop(uid, None)
    logger.info(f"ai cleanup: {len(user_ctx)} активных юзеров в контексте")


# ============================================================
# ON READY
# ============================================================
@bot.event
async def on_ready():
    logger.info(f"diamond ai запущен как {bot.user} (id={bot.user.id})")
    logger.info(f"LLM: Gemini · приоритет: {GEMINI_MODELS_PRIORITY} · max_tokens={MAX_OUTPUT_TOKENS}")

    try:
        async with aiohttp.ClientSession() as session:
            models = await _fetch_available_models(session)
            if models:
                logger.info(f"доступные модели: {models}")
    except Exception as e:
        logger.warning(f"прогрев моделей: {e}")

    try:
        await bot.change_presence(
            status=disnake.Status.online,
            activity=disnake.Game("Нейроный консультант"),
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
    users_who_talked.add(user_id)

    if is_technical_request(text):
        try:
            await message.channel.send(
                "извини, на технические темы не отвечаю — я консультант магазина. "
                "могу помочь с товарами, ролями, dc, кланом, казино, тикетами и промокодами.",
                reference=message,
                mention_author=False,
            )
        except Exception:
            pass
        return

    _push_channel(message.author.display_name, text)

    mood = detect_mood(text)
    style = choose_style(mood, text)

    member = message.author if isinstance(message.author, disnake.Member) else None
    context_block = build_context_block(user_id, member)

    try:
        async with message.channel.typing():
            await asyncio.sleep(random.uniform(0.5, 1.5))
            reply = await ask_llm(
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

    # ─── Отправка без пинга ───
    try:
        await message.channel.send(
            reply,
            reference=message,
            mention_author=False,
        )
    except Exception:
        try:
            await message.channel.send(reply)
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
        print("❌ AI_TOKEN не установлен — процесс AI завершается.")
        raise SystemExit(1)

    try:
        bot.run(AI_TOKEN)
    except Exception as e:
        logger.exception(f"Ошибка запуска AI: {e}")
        raise
