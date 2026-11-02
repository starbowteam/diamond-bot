# -*- coding: utf-8 -*-
"""Diamond AI v3.3 — умный консультант магазина."""
import os, re, io, time, json, random, asyncio, hashlib, logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
import aiohttp, disnake
from disnake.ext import commands, tasks
from core.utils import CONFIG, FILES, DATA_DIR, load_json, save_json, get_dc_cache, cur, db

logger = logging.getLogger("diamond_ai")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = logging.FileHandler("ai_bot.log", encoding="utf-8"); fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")); sh = logging.StreamHandler(); sh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")); logger.addHandler(fh); logger.addHandler(sh)

AI_TOKEN = os.getenv("AI_TOKEN")
if not AI_TOKEN: print("❌ AI_TOKEN не установлен — процесс AI завершится.")

GEMINI_API_KEY = os.getenv("MISTRAL_API_KEY")
if not GEMINI_API_KEY: print("⚠️ MISTRAL_API_KEY (Gemini) не задан — AI не сможет отвечать.")

GEMINI_MODELS_PRIORITY = ["gemini-flash-latest"]
_env_model = os.getenv("GEMINI_MODEL")
if _env_model: GEMINI_MODELS_PRIORITY = [m.strip() for m in _env_model.split(",") if m.strip()]
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_AVAILABLE_MODELS: List[str] = []
_AVAILABLE_MODELS_FETCHED_AT: float = 0.0
_MODELS_CACHE_TTL = 3600
ALLOWED_CHANNEL_ID = 1462064375862005845
AI_LOG_CHANNEL_ID = 1530453871581855744
OWNER_ID = 796293832751972352
GUILD_ID = int(CONFIG["GUILD_ID"])
MAX_USER_HISTORY = 6
MAX_OUTPUT_TOKENS = 8000
MEMORY_TTL_DAYS = 30
REPEAT_QUESTION_HOURS = 1
REPEAT_IDENTICAL_MINUTES = 5
CHAT_AUTO_INTERVAL_HOURS = 24
CHAT_AUTO_IDLE_HOURS = 12
BUSY_WINDOW_SECONDS = 120
BUSY_DISTINCT_AUTHORS = 3
_TOPIC_CACHE: Dict[str, Tuple[bool, float]] = {}
_TOPIC_CACHE_TTL = 600
_RECENT_QUESTIONS: Dict[int, Dict[str, Any]] = {}

def _init_ai_tables():
    try:
        cur.executescript("CREATE TABLE IF NOT EXISTS ai_user_memory (user_id INTEGER PRIMARY KEY, first_seen INTEGER DEFAULT 0, last_seen INTEGER DEFAULT 0, last_topic TEXT, last_question_hash TEXT, last_question_ts INTEGER DEFAULT 0, facts_json TEXT); CREATE TABLE IF NOT EXISTS ai_unknown_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, question TEXT, reply TEXT, ts INTEGER); CREATE TABLE IF NOT EXISTS ai_suggested (question_hash TEXT PRIMARY KEY, sample_question TEXT, sent_at INTEGER);")
        db.commit()
    except Exception as e: logger.exception(f"_init_ai_tables: {e}")

_init_ai_tables()

def memory_get(user_id: int) -> dict:
    try: row = cur.execute("SELECT * FROM ai_user_memory WHERE user_id=?", (user_id,)).fetchone(); return dict(row) if row else {}
    except Exception: return {}

def memory_upsert(user_id: int, **fields):
    try:
        now = int(time.time()); existing = memory_get(user_id)
        if not existing: cur.execute("INSERT INTO ai_user_memory (user_id, first_seen, last_seen) VALUES (?, ?, ?)", (user_id, now, now)); db.commit()
        updates = {k: v for k, v in fields.items() if v is not None}; updates["last_seen"] = now
        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates.keys()); values = list(updates.values()) + [user_id]
            cur.execute(f"UPDATE ai_user_memory SET {set_clause} WHERE user_id=?", values); db.commit()
    except Exception: pass

def memory_add_fact(user_id: int, fact: str):
    try:
        mem = memory_get(user_id); facts = []
        if mem.get("facts_json"):
            try: facts = json.loads(mem["facts_json"])
            except Exception: facts = []
        fact = fact.strip()
        if not fact or fact in facts: return
        facts.append(fact); facts = facts[-10:]
        memory_upsert(user_id, facts_json=json.dumps(facts, ensure_ascii=False))
    except Exception: pass

def memory_cleanup_old():
    try:
        cur.execute("DELETE FROM ai_user_memory WHERE last_seen < ?", (int(time.time()) - MEMORY_TTL_DAYS * 86400,)); db.commit()
    except Exception: pass

def memory_detect_interests(user_id: int):
    try:
        mem = memory_get(user_id); facts = json.loads(mem["facts_json"]) if mem.get("facts_json") else []
        topics = {}
        for f in facts:
            m = re.match(r"спрашивал про (.+)", f)
            if m: t = m.group(1).strip().lower(); topics[t] = topics.get(t, 0) + 1
        for t, c in topics.items():
            if c >= 3: memory_add_fact(user_id, f"интересуется {t}")
    except Exception: pass

def is_repeat_question(user_id: int, text: str) -> bool:
    mem = memory_get(user_id)
    if not mem: return False
    last_hash, last_ts = mem.get("last_question_hash"), mem.get("last_question_ts") or 0
    if not last_hash or int(time.time()) - last_ts > REPEAT_QUESTION_HOURS * 3600: return False
    return hashlib.md5(_normalize_text(text).encode("utf-8")).hexdigest() == last_hash

def mark_question_asked(user_id: int, text: str):
    memory_upsert(user_id, last_question_hash=hashlib.md5(_normalize_text(text).encode("utf-8")).hexdigest(), last_question_ts=int(time.time()))

def _normalize_text(text: str) -> str:
    t = text.lower().strip(); t = re.sub(r"[^\w\s]", "", t); return re.sub(r"\s+", " ", t)

def log_unknown(user_id: int, question: str, reply: str):
    try: cur.execute("INSERT INTO ai_unknown_log (user_id, question, reply, ts) VALUES (?, ?, ?, ?)", (user_id, question[:500], reply[:500], int(time.time()))); db.commit()
    except Exception: pass

SYSTEM_PROMPT = """ты — diamond ai, цифровой консультант магазина diamond shop. 🔴 ГЛАВНОЕ: КРАТКОСТЬ. по умолчанию 2–4 предложения простым текстом. без заголовков, без списков, без маркдауна. развёрнутый ответ только если юзер явно просит «подробнее». 🔴 ЯЗЫК: отвечай на том же языке, на котором написал юзер. 🔴 НИКОГДА не выдумывай цифры, каналы, товары, цены. всё что знаешь — в блоке [данные]. если чего-то нет — скажи «не знаю, уточни у менеджера». 🔴 ЗАПРЕЩЕНО отвечать про: код, скрипты, пароли, токены, ssh, api-ключи, админку сервера, программирование. откажись одной фразой. 🔴 ПАМЯТЬ: если в [данные] есть «в прошлый раз юзер интересовался X» — можешь коротко сослаться. не переспрашивай то, что уже знаешь. что ты знаешь про магазин: **diamond coin (dc)** — валюта. - 1 dc за 10 сообщений, 3 dc за час в войсе. - отзыв даёт 20-100 dc. - ежедневный бонус с ролью клуб = +10 dc. - подарок в панели профиля = 10–30 dc. - казино: рулетка, блэкджек, монетка. - кейсы: 100-2000 dc. **роли покупателей**: 1–5 → bronze, 6–10 → silver, 11–15 → gold, 16–20 → diamond, 21–25 → crystalis, 26+ → pka. **покупки**: витрина → каталог → валюта (dc или реал) → в dc выбрать товар → оформить тикет. **клан**: 3 клана, сезон 28 дней, выплата 28 числа. вклад: 100% от заработка. Бонусы: Топ-1 ×7.00, Топ-2 ×5.00, Топ-3 ×3.00, остальные ×1.50. 🔴 ДУША КЛАНА: питомец один на клан. кормят все (1 DC = 1 XP). доход: 1 ур = 30 DC/ч, каждый следующий ×1.5. раз в 24 часа в копилку. бонус к выплате от +3% до +27%."""

MOOD_SUFFIX = {"friendly": "\n\nсобеседник дружелюбен — будь теплее.", "business": "\n\nделовой запрос — отвечай по делу.", "default": "", "angry": "\n\nюзер раздражён — отвечай сухо, без смайлов.", "happy": "\n\nюзер в хорошем настроении — можешь добавить один эмодзи."}
REACTIONS_MAP = {"thanks": "💎", "laugh": "😄", "won": "🎉", "lost": "🤝", "thinking": "🤔", "agreed": "👍", "greeting": "👋"}
REACTION_WORDS = {"thanks": ["спасибо", "спс", "благодарю", "thanks", "thank", "thx", "сяб"], "laugh": ["ахах", "хаха", "лол", "lol", "ахаха", "хех", "rofl", "кек", "ахахах"], "won": ["ура", "купил", "забрал", "выиграл", "выбил", "получилось", "топ"], "lost": ["проиграл", "слил", "слилась", "опять", "не повезло", "обидно"], "thinking": ["думаю", "может", "наверное", "хм", "возможно"], "agreed": ["понял", "ок", "окей", "ясно", "принял", "ладно", "хорошо"], "greeting": ["привет", "хай", "здарова", "ку", "hello", "hi", "добрый"]}

def check_reaction_reply(text: str) -> Optional[str]:
    t = _normalize_text(text)
    if not t: return None
    words = t.split()
    if len(words) > 3: return None
    for category, kw_list in REACTION_WORDS.items():
        if all(w in kw_list for w in words): return REACTIONS_MAP.get(category)
    return None

ERROR_PHRASES = {"no_api": "связь с мозгом пропала, попробуй через минуту.", "timeout": "что-то долго думаю, давай ещё раз.", "no_model": "сейчас все модели недоступны, попробуй через пару минут.", "rate_limit": "слишком много вопросов за раз — дай мне минуту передохнуть.", "empty": "что-то не могу сообразить, спроси по-другому.", "parse": "сбой в мыслях, попробуй ещё раз."}

intents = disnake.Intents.default(); intents.messages = True; intents.guilds = True; intents.message_content = True; intents.members = True
bot = commands.Bot(command_prefix="!ai", intents=intents)
user_ctx: Dict[int, List[Dict[str, str]]] = {}

def _push_user(user_id: int, role: str, content: str):
    lst = user_ctx.setdefault(user_id, []); lst.append({"role": role, "content": content[:600]})
    while len(lst) > MAX_USER_HISTORY * 2: lst.pop(0)

def _is_reply_to_bot(message: disnake.Message) -> bool:
    try: return message.reference and isinstance(message.reference.resolved, disnake.Message) and message.reference.resolved.author.id == bot.user.id
    except Exception: return False
def _is_reply_to_user(message: disnake.Message) -> bool:
    try: return message.reference and isinstance(message.reference.resolved, disnake.Message) and message.reference.resolved.author.id != bot.user.id and not message.reference.resolved.author.bot
    except Exception: return False
def _get_replied_message(message: disnake.Message) -> Optional[disnake.Message]:
    try: return message.reference.resolved if message.reference else None
    except Exception: return None
def _mentions_bot(message: disnake.Message) -> bool:
    try: return bot.user in message.mentions
    except Exception: return False

TRIGGER_WORDS = ("как ", "как?", "где ", "где?", "сколько", "что такое", "что за", "когда ", "почему", "куда ", "помоги", "help", "подскажи", "можно ли", "есть ли", "интересует", "ищу", "хочу ", "надо ", "нужно ", "продаёте", "продаете")

def should_respond(message: disnake.Message) -> bool:
    if _is_reply_to_bot(message) or _mentions_bot(message): return True
    text = (message.content or "").lower()
    if "?" in text or "？" in text: return True
    return any(text.startswith(w) for w in TRIGGER_WORDS)

async def is_channel_busy(channel: disnake.TextChannel) -> bool:
    try:
        since = datetime.now(timezone.utc) - timedelta(seconds=BUSY_WINDOW_SECONDS); authors = set()
        async for msg in channel.history(limit=15, after=since):
            if msg.author.id == bot.user.id or msg.author.bot: continue
            authors.add(msg.author.id)
        return len(authors) >= BUSY_DISTINCT_AUTHORS
    except Exception: return False

ANGRY_WORDS = ["бесит", "достал", "ненавижу", "ужас", "кошмар", "говно", "хуй", "пиздец", "бляд", "ебан", "тупой", "дебил", "идиот", "заткнись", "хватит", "достало", "достали", "задолбал"]
HAPPY_WORDS = ["ура", "класс", "супер", "круто", "кайф", "топ", "люблю", "спасибо", "круто", "огонь", "ахах", "хаха", "лол", "❤", "😍", "🎉"]

def detect_sentiment(text: str) -> str:
    t = text.lower(); letters = [c for c in text if c.isalpha()]
    if len(letters) >= 20 and sum(1 for c in letters if c.isupper()) / len(letters) > 0.6: return "angry"
    if text.count("!") >= 3 or text.count("?") >= 3: return "angry"
    angry_score = sum(1 for w in ANGRY_WORDS if w in t); happy_score = sum(1 for w in HAPPY_WORDS if w in t)
    return "angry" if angry_score > happy_score else "happy" if happy_score > angry_score else "neutral"

def choose_style(sentiment: str, text: str) -> str:
    if sentiment == "angry": return "angry"
    if sentiment == "happy": return "happy"
    t = text.lower()
    return "business" if any(w in t for w in ["цена", "стоит", "купить", "оплатить", "заказать", "сколько"]) else "default"

def is_owner(user_id: int) -> bool: return user_id == OWNER_ID
def is_staff(member: Optional[disnake.Member]) -> bool:
    if member is None: return False
    try: from core.utils import has_admin_command_roles; return has_admin_command_roles(member)
    except Exception: return False
def build_role_suffix(member: Optional[disnake.Member], is_first: bool) -> str:
    if member and is_owner(member.id): return "\n\nэто владелец diamond shop — обращайся «шеф», коротко, по делу."
    if is_staff(member): return "\n\nэто сотрудник — деловой тон, без шуток."
    if is_first: return "\n\nэто первое сообщение от юзера — будь чуть теплее."
    return ""

ROLE_IDS = CONFIG.get("ROLE_IDS", {})
ROLE_PRIORITY = [("pka", "Покупатель Века"), ("crystalis", "Crystalis Buyer"), ("diamond", "Diamond Buyer"), ("gold", "Gold Buyer"), ("silver", "Silver Buyer"), ("bronze", "Bronze Buyer"), ("club", "Клуб")]
def _role_label_from_member(member: Optional[disnake.Member]) -> Optional[str]:
    if member is None: return None
    try: member_role_ids = {r.id for r in member.roles}
    except Exception: return None
    for key, label in ROLE_PRIORITY:
        rid = ROLE_IDS.get(key)
        if rid and rid in member_role_ids: return label
    return None
def _role_key_for_reviews(reviews: int) -> str:
    if reviews >= 26: return "pka"
    if reviews >= 21: return "crystalis"
    if reviews >= 16: return "diamond"
    if reviews >= 11: return "gold"
    if reviews >= 6: return "silver"
    if reviews >= 1: return "bronze"
    return "none"

def build_clan_pet_block(user_id: int) -> str:
    try:
        from clan.core import get_user_clan
        from pet.core import get_clan_pet, get_pet_name, get_pet_bonus, get_pet_hourly_income
        clan = get_user_clan(user_id)
        if not clan: return "клановый питомец: юзер не состоит в клане"
        pet = get_clan_pet(clan["id"]); pet_name = get_pet_name(clan["id"]); bonus = get_pet_bonus(pet["level"]); income = get_pet_hourly_income(pet["level"])
        return f"клановый питомец (Душа Клана):\n- клан: {clan['name']}\n- питомец: {pet_name} (уровень {pet['level']})\n- бонус к выплате клана: +{int(bonus*100)}%\n- пассивный доход: {income:.0f} DC/ч (раз в сутки падает в копилку)\n- всего скормлено кланом: {pet['total_fed']} DC"
    except Exception: return ""

def build_user_block(user_id: int, member: Optional[disnake.Member]) -> str:
    try: balance = get_dc_cache(user_id).get("balance", 0)
    except Exception: balance = 0
    try: reviews = int(load_json(FILES["review_counts"], {}).get(str(user_id), 0))
    except Exception: reviews = 0
    role_from_discord = _role_label_from_member(member); role_label = role_from_discord if role_from_discord else ("нет роли покупателя" if _role_key_for_reviews(reviews) == "none" else dict(ROLE_PRIORITY).get(_role_key_for_reviews(reviews), "—"))
    lines = ["личные данные пользователя:", f"- баланс: {balance} dc", f"- отзывов: {reviews}", f"- текущая роль: {role_label}"]
    try:
        from clan.core import get_user_clan, get_user_contribution, get_clan_top
        clan = get_user_clan(user_id)
        if clan:
            contrib = get_user_contribution(user_id) or 0; my_rank = None
            try:
                top = get_clan_top(clan["id"], limit=1000)
                for i, t in enumerate(top, 1):
                    if t["user_id"] == user_id: my_rank = i; break
            except Exception: pass
            lines.append(f"- клан: {clan['name']}"); lines.append(f"- вклад за сезон: {contrib} dc")
            if my_rank: lines.append(f"- место в топе клана: #{my_rank}")
        else: lines.append("- клан: без клана")
    except Exception: lines.append("- клан: —")
    try:
        from modules.dc import get_daily_gift_status
        status = get_daily_gift_status(user_id)
        if status["ready"]: lines.append("- ежедневный подарок: готов к получению")
        else:
            left = max(status["next_ts"] - int(time.time()), 0); lines.append(f"- ежедневный подарок: через {left // 3600}ч {(left % 3600) // 60}м")
    except Exception: pass
    pet_block = build_clan_pet_block(user_id)
    if pet_block: lines.append(""); lines.append(pet_block)
    return "\n".join(lines)

def build_shop_block() -> str:
    try:
        from modules.dc import load_shop_catalog
        catalog = load_shop_catalog(); lines = ["цены в dc-магазине:"]
        for key, label in [("discounts", "скидки"), ("roles", "роли"), ("design", "дизайн"), ("boosts", "бусты"), ("casino", "казино"), ("gifts", "подарки")]:
            if key in catalog:
                prices = [it["price"] for it in catalog[key].get("items", {}).values() if it.get("price")]
                if prices: lines.append(f"- {label}: от {min(prices)} до {max(prices)} dc")
        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception: return ""

def build_active_block() -> str:
    lines = []
    try:
        from modules.actions import refresh_daily_deal
        deal = refresh_daily_deal()
        if deal: lines.append(f"- акция дня: скидка {deal.get('discount', 0)}% на «{deal.get('item_data', {}).get('name', '—')}», цена {deal.get('new_price', 0)} dc (обычно {deal.get('original_price', 0)})")
    except Exception: pass
    try:
        rows = cur.execute("SELECT giveaway_id, prize, end_time, participants FROM giveaways WHERE status='active' AND end_time > ? ORDER BY end_time LIMIT 3", (int(time.time()),)).fetchall()
        for r in rows:
            try: n = len(json.loads(r["participants"] or "[]"))
            except Exception: n = 0
            lines.append(f"- розыгрыш #{r['giveaway_id']}: {r['prize']}, участников {n}, до <t:{r['end_time']}:R>")
    except Exception: pass
    return "активное на сервере:\n" + "\n".join(lines) if lines else ""

def build_memory_block(user_id: int) -> str:
    mem = memory_get(user_id)
    if not mem: return ""
    parts = []
    last_ts = mem.get("last_seen") or 0
    if last_ts and int(time.time()) - last_ts > 3 * 86400:
        last_topic = mem.get("last_topic")
        if last_topic: parts.append(f"- юзер давно не писал, в прошлый раз интересовался: {last_topic}")
    facts_raw = mem.get("facts_json")
    if facts_raw:
        try:
            for f in (json.loads(facts_raw) or [])[:5]: parts.append(f"- {f}")
        except Exception: pass
    return "память о юзере:\n" + "\n".join(parts) if parts else ""

def build_context_block(user_id: int, member: Optional[disnake.Member]) -> str:
    parts = [build_user_block(user_id, member)]
    shop = build_shop_block()
    if shop: parts.append(shop)
    active = build_active_block()
    if active: parts.append(active)
    mem = build_memory_block(user_id)
    if mem: parts.append(mem)
    return "\n\n[данные]\n" + "\n\n".join(parts) + "\n[/данные]\n"

TOOLS_DECLARATIONS = [
    {"name": "claim_daily_gift", "description": "Забрать ежедневный подарок.", "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "buy_case", "description": "Открыть кейс за DC. Номера: 1 — Попробуй удачу (100 DC), 2 — Быстрый куш (300 DC), 3 — Серьёзный куш (500 DC), 4 — Королевский куш (1000 DC), 5 — Мифический куш (2000 DC).", "parameters": {"type": "OBJECT", "properties": {"case_num": {"type": "INTEGER", "description": "Номер кейса 1–5"}}, "required": ["case_num"]}},
]

async def tool_claim_daily_gift(user_id: int) -> str:
    try:
        from modules.dc import claim_daily_gift
        result = await claim_daily_gift(user_id)
        if result.get("ok"): return f"подарок забран: +{result['amount']} DC"
        left = max(result.get("next_ts", 0) - int(time.time()), 0); return f"кулдаун подарка — ждать {left // 3600}ч {(left % 3600) // 60}м"
    except Exception as e: return f"ошибка: {str(e)[:100]}"

async def tool_buy_case(user_id: int, case_num: int) -> str:
    try:
        from modules.cases import open_case, CASES_BY_NUM
        case = CASES_BY_NUM.get(case_num)
        if not case: return f"кейс {case_num} не существует"
        result = await open_case(bot, user_id, case_num)
        return f"кейс открыт, выпало: {result['desc']}" if result["ok"] else f"не получилось: {result.get('error', 'ошибка')}"
    except Exception as e: return f"ошибка: {str(e)[:100]}"

async def execute_tool(message: disnake.Message, name: str, args: dict) -> str:
    if name == "show_profile": return await tool_show_profile(message)
    if name == "claim_daily_gift": return await tool_claim_daily_gift(message.author.id)
    if name == "buy_case":
        try: return await tool_buy_case(message.author.id, int(args.get("case_num", 0)))
        except Exception: return "не понял номер кейса"
    return f"неизвестная функция: {name}"

PROFILE_TRIGGERS = ["покажи профиль", "мой профиль", "скинь профиль", "карточка профиля", "моя карточка", "покажи карточку", "мой баланс", "сколько у меня", "скинь карточку", "покажи баланс"]
GIFT_TRIGGERS = ["забери подарок", "получить подарок", "дай подарок", "забрать подарок", "получи подарок", "забери мне подарок"]
PURCHASES_TRIGGERS = ["мои покупки", "мой инвентарь", "что я купил", "мои товары", "список покупок", "неиспользованные покупки"]
DIGEST_TRIGGERS = ["что нового", "что у вас там", "дайджест", "что нового на сервере", "что происходит", "новости магазина", "чё нового", "че нового", "новости"]
ABOUT_TRIGGERS = ["ты кто", "кто ты", "что ты умеешь", "что умеешь", "ты кто такой", "расскажи о себе"]

def _match_any(text: str, patterns: List[str]) -> bool: return any(p in _normalize_text(text) for p in patterns)

async def quick_action(message: disnake.Message, text: str) -> Optional[str]:
    user_id = message.author.id
    if _match_any(text, PROFILE_TRIGGERS):
        result = await tool_show_profile(message)
        return "" if result.startswith("профиль") else result
    if _match_any(text, GIFT_TRIGGERS): return await tool_claim_daily_gift(user_id)
    m = re.search(r"кейс[аеуы\s]+(\d)", _normalize_text(text))
    if m:
        try: return await tool_buy_case(user_id, int(m.group(1)))
        except Exception: pass
    if _match_any(text, PURCHASES_TRIGGERS): return await build_purchases_reply(user_id)
    if _match_any(text, DIGEST_TRIGGERS): return await build_digest_reply(user_id)
    if _match_any(text, ABOUT_TRIGGERS): return "я diamond ai, консультант магазина. умею рассказать про товары, роли, dc, клан, душу клана, казино. могу показать твой профиль, забрать подарок, открыть кейс, найти что-то в каталоге. спрашивай."
    return None

async def tool_show_profile(message: disnake.Message) -> str:
    try:
        from modules.profile_card import generate_profile_card
        from modules.commands_profile import _role_info
        user = message.author
        if not isinstance(user, disnake.Member): return "ошибка: не могу получить участника"
        rc = load_json(FILES["review_counts"], {}).get(str(user.id), 0); role_key, _ = _role_info(rc); dc = get_dc_cache(user.id); balance = dc.get("balance", 0); history = list(reversed((dc.get("history") or [])[-5:]))
        avatar_bytes = await user.display_avatar.replace(size=256, format="png").read()
        buf = await asyncio.to_thread(generate_profile_card, user.display_name, user.id, avatar_bytes, role_key, rc, balance, user.joined_at, history)
        fname = f"profile_{user.id}_{int(time.time())}.png"; file = disnake.File(buf, filename=fname); embed = disnake.Embed(color=6776679); embed.set_image(url=f"attachment://{fname}")
        await message.channel.send(embed=embed, file=file); return "профиль отправил в чат"
    except Exception as e: return f"не получилось: {str(e)[:100]}"

async def build_purchases_reply(user_id: int) -> str:
    try:
        from modules.dc import get_user_purchases
        purchases = [p for p in await get_user_purchases(user_id, only_unused=True) if p.get("type") != "discounts"]
        if not purchases: return "у тебя нет неиспользованных покупок — всё оформлено."
        lines = [f"у тебя {len(purchases)} неиспользованных:"] + [f"• {p.get('value', '—')} · {p.get('type', '')}" for p in purchases[:5]]
        if len(purchases) > 5: lines.append(f"…и ещё {len(purchases) - 5}")
        lines.append("\nоформить можно в тикете через панель магазина."); return "\n".join(lines)
    except Exception: return "не смог получить список покупок."

async def build_digest_reply(user_id: int) -> str:
    parts = []
    try:
        from modules.actions import refresh_daily_deal
        deal = refresh_daily_deal()
        if deal: parts.append(f"💎 акция дня: скидка {deal.get('discount', 0)}% на «{deal.get('item_data', {}).get('name', '—')}» → {deal.get('new_price', 0)} DC")
    except Exception: pass
    try:
        row = cur.execute("SELECT giveaway_id, prize, end_time, participants FROM giveaways WHERE status='active' AND end_time > ? ORDER BY end_time LIMIT 1", (int(time.time()),)).fetchone()
        if row:
            try: n = len(json.loads(row["participants"] or "[]"))
            except Exception: n = 0
            parts.append(f"🎉 розыгрыш: {row['prize']} · {n} участников · до <t:{row['end_time']}:R>")
    except Exception: pass
    try:
        from modules.dc import get_daily_gift_status
        st = get_daily_gift_status(user_id)
        if st["ready"]: parts.append("🎁 у тебя не забран подарок — можно забрать прямо сейчас")
        else: left = max(st["next_ts"] - int(time.time()), 0); parts.append(f"🎁 подарок через {left // 3600}ч {(left % 3600) // 60}м")
    except Exception: pass
    try:
        from clan.core import get_user_clan
        from pet.core import get_clan_pet, get_pet_hourly_income
        clan = get_user_clan(user_id)
        if clan: pet = get_clan_pet(clan["id"]); parts.append(f"🐾 душа клана: уровень {pet['level']} · {get_pet_hourly_income(pet['level']):.0f} DC/ч в копилку")
    except Exception: pass
    try:
        purchases = await build_purchases_reply(user_id)
        if "неиспользованн" in purchases: parts.append("📦 " + purchases.split("\n")[0])
    except Exception: pass
    return "💠 свежее на сервере:\n" + "\n".join(parts) if parts else "сейчас всё тихо — ничего нового."

def search_catalog(query: str) -> List[Dict]:
    try: from modules.dc import load_shop_catalog; catalog = load_shop_catalog()
    except Exception: return []
    q = _normalize_text(query)
    if len(q) < 2: return []
    results = []
    for cat_key, cat in catalog.items():
        for item_key, item in (cat.get("items") or {}).items():
            name = (item.get("name") or "").lower(); desc = (item.get("description") or "").lower()
            if q in name or q in desc or q in item_key.lower(): results.append({"cat": cat_key, "cat_label": cat.get("label", cat_key), "name": item.get("name", item_key), "price": item.get("price", 0), "description": item.get("description", "")})
    return results[:5]

def build_catalog_search_reply(text: str) -> Optional[str]:
    t = _normalize_text(text); markers = ["есть ли", "есть ", "продаете", "продаёте", "можно купить", "можно ли купить", "ищу", "нужен", "нужна", "интересует", "хочу купить", "продается", "продаётся"]
    if not any(m in t for m in markers): return None
    for m in markers: t = t.replace(m, " ")
    words = [w for w in t.split() if len(w) >= 3]
    if not words: return None
    found = search_catalog(" ".join(words))
    if not found: return None
    return "да, есть:\n" + "\n".join([f"• **{r['name']}** — {r['price']} DC · {r['cat_label']}" for r in found[:3]]) + "\n\nоформляется в тикете через панель магазина."

SHOP_KEYWORDS = ["магазин", "покупк", "diamond", "даймонд", "dc", "роль", "оплат", "промокод", "тикет", "отзыв", "клан", "казино", "бонус", "кейс", "скидк", "акци", "розыгрыш", "нитро", "nitro", "steam", "roblox", "spotify", "телеграм", "telegram", "робукс", "буст", "подарок", "баланс", "профиль", "кланов", "лига", "сезон", "адвайтер", "реферал", "инвайт", "ставк", "рулетк", "блэкджек", "монетк", "хочу купить", "есть ли", "продаете", "продаёте", "цена", "стоит", "подскажи", "помоги с", "можешь", "сколько", "питомец", "питомц", "душа клана", "пет", "зоопарк", "кот", "лиса", "сова", "грифон", "дракон", "даймондик", "кормить", "покормить"]
def has_shop_keywords(text: str) -> bool: return any(k in text.lower() for k in SHOP_KEYWORDS)

async def is_on_topic(session: aiohttp.ClientSession, text: str) -> bool:
    if has_shop_keywords(text): return True
    cache_key = hashlib.md5(text[:200].encode("utf-8")).hexdigest(); cached = _TOPIC_CACHE.get(cache_key)
    if cached and time.time() - cached[1] < _TOPIC_CACHE_TTL: return cached[0]
    try:
        url = f"{GEMINI_API_BASE}/gemini-flash-latest:generateContent"; headers = {"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY}
        payload = {"contents": [{"role": "user", "parts": [{"text": f"относится ли это сообщение к магазину diamond shop (товары, dc-валюта, роли, кейсы, казино, клан, тикеты, душа клана)? ответь одним словом: да или нет.\n\nсообщение: {text[:300]}"}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": 10}}
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200: return True
            data = await resp.json(); parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            if not parts: return True
            answer = parts[0].get("text", "").strip().lower(); result = answer.startswith("да") or answer.startswith("yes"); _TOPIC_CACHE[cache_key] = (result, time.time()); return result
    except Exception: return True

_VALID_CHANNEL_IDS = set(); _VALID_ROLE_IDS = set()
def _build_valid_id_sets():
    global _VALID_CHANNEL_IDS, _VALID_ROLE_IDS
    for k, v in CONFIG.items():
        if isinstance(v, int) and "CHANNEL" in k and v > 1000000: _VALID_CHANNEL_IDS.add(v)
    _VALID_ROLE_IDS = {v for v in (CONFIG.get("ROLE_IDS") or {}).values() if isinstance(v, int)}
_build_valid_id_sets()

def sanitize_response(text: str) -> str:
    def _fix_channel(m):
        try: cid = int(m.group(1)); return m.group(0) if cid in _VALID_CHANNEL_IDS else ""
        except Exception: return m.group(0)
    def _fix_role(m):
        try: rid = int(m.group(1)); return m.group(0) if rid in _VALID_ROLE_IDS else ""
        except Exception: return m.group(0)
    return re.sub(r"<@&(\d+)>", _fix_role, re.sub(r"<#(\d+)>", _fix_channel, text))

async def _fetch_available_models(session: aiohttp.ClientSession) -> List[str]:
    global _AVAILABLE_MODELS, _AVAILABLE_MODELS_FETCHED_AT
    now = time.time()
    if _AVAILABLE_MODELS and now - _AVAILABLE_MODELS_FETCHED_AT < _MODELS_CACHE_TTL: return _AVAILABLE_MODELS
    url = GEMINI_API_BASE; headers = {"X-goog-api-key": GEMINI_API_KEY}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200: return _AVAILABLE_MODELS
            data = await resp.json(); models = []
            for m in data.get("models", []):
                name = m.get("name", "")
                if not name.startswith("models/"): continue
                short = name[len("models/"):]
                if "generateContent" not in m.get("supportedGenerationMethods", []): continue
                n_low = short.lower()
                if "flash" not in n_low or any(x in n_low for x in ("image", "tts", "omni")): continue
                models.append(short)
            def sort_key(n):
                n_low = n.lower(); score = 0
                if "latest" in n_low: score -= 1000
                m = re.search(r"gemini-(\d+)\.(\d+)", n_low)
                if m: score -= int(m.group(1)) * 100; score -= int(m.group(2)) * 10
                if "preview" in n_low or "exp" in n_low: score += 500
                if "8b" in n_low: score += 100
                return score
            models.sort(key=sort_key); _AVAILABLE_MODELS = models; _AVAILABLE_MODELS_FETCHED_AT = now; return models
    except Exception: return _AVAILABLE_MODELS

def _build_payload(system_content: str, contents: List[dict], use_tools: bool = True) -> dict:
    payload = {"systemInstruction": {"parts": [{"text": system_content}]}, "contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": MAX_OUTPUT_TOKENS}}
    if use_tools: payload["tools"] = [{"function_declarations": TOOLS_DECLARATIONS}]
    return payload

async def _try_model(session: aiohttp.ClientSession, model: str, payload: dict) -> Tuple[bool, dict, int]:
    url = f"{GEMINI_API_BASE}/{model}:generateContent"; headers = {"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY}
    try:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=90)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "error" in data: return False, {"error": data["error"].get("message", "unknown")}, 200
                cands = data.get("candidates", [])
                if not cands: return False, {"error": "no candidates"}, 200
                parts = cands[0].get("content", {}).get("parts", [])
                if not parts: return False, {"error": "empty parts"}, 200
                text_parts, fcs = [], []
                for p in parts:
                    if "text" in p: text_parts.append(p["text"])
                    if "functionCall" in p: fc = p["functionCall"]; fcs.append({"name": fc.get("name", ""), "args": fc.get("args", {})})
                return True, {"text": "".join(text_parts).strip(), "function_calls": fcs}, 200
            if resp.status == 429: return False, {"error": "rate_limit"}, 429
            return False, {"error": f"http {resp.status}"}, resp.status
    except asyncio.TimeoutError: return False, {"error": "timeout"}, -1
    except Exception as e: return False, {"error": str(e)}, -1

async def ask_llm(message: disnake.Message, user_message: str, system_content: str, user_id: int) -> Tuple[str, str]:
    if not GEMINI_API_KEY: return ERROR_PHRASES["no_api"], "no_api"
    history = user_ctx.get(user_id, []); contents = [{"role": "user" if msg["role"] == "user" else "model", "parts": [{"text": msg["content"]}]} for msg in history[-MAX_USER_HISTORY:]]
    contents.append({"role": "user", "parts": [{"text": user_message}]})
    async with aiohttp.ClientSession() as session:
        models_to_try, seen = [], set()
        for m in GEMINI_MODELS_PRIORITY:
            if m not in seen: seen.add(m); models_to_try.append(m)
        for m in await _fetch_available_models(session):
            if m not in seen: seen.add(m); models_to_try.append(m)
        models_to_try = models_to_try[:6]
        if not models_to_try: return ERROR_PHRASES["no_model"], "no_model"
        payload = _build_payload(system_content, contents, use_tools=True)
        for _ in range(3):
            response, last_status = None, -1
            for model in models_to_try:
                ok, res, status = await _try_model(session, model, payload)
                if ok: response = res; break
                last_status = status
                if status == 503: await asyncio.sleep(2); ok2, res2, _ = await _try_model(session, model, payload); response = res2 if ok2 else None
                if response: break
                await asyncio.sleep(0.3)
            if response is None: return (ERROR_PHRASES["rate_limit"], "rate_limit") if last_status == 429 else (ERROR_PHRASES["no_model"], "no_model")
            fcs, text = response.get("function_calls", []), response.get("text", "")
            if not fcs:
                if not text: return ERROR_PHRASES["empty"], "empty"
                _push_user(user_id, "user", user_message); _push_user(user_id, "assistant", text); return text, "ok"
            contents.append({"role": "model", "parts": [{"functionCall": {"name": fc["name"], "args": fc["args"]}} for fc in fcs]})
            tool_results = []
            for fc in fcs:
                result = await execute_tool(message, fc["name"], fc.get("args", {})); tool_results.append({"functionResponse": {"name": fc["name"], "response": {"result": result}}})
            contents.append({"role": "user", "parts": tool_results}); payload = _build_payload(system_content, contents, use_tools=True)
        return (text or ERROR_PHRASES["parse"]), ("ok" if text else "parse")

def is_unknown_reply(text: str) -> bool: return any(m in text.lower() for m in ["не знаю", "не могу", "уточни у менеджера", "уточни", "не уверен", "затрудняюсь"]) if text else False

async def ask_llm_smart(message: disnake.Message, user_message: str, system_content: str, user_id: int) -> Tuple[str, str]:
    reply, status = await ask_llm(message, user_message, system_content, user_id)
    if status in ("rate_limit", "no_model", "no_api", "timeout"): return reply, status
    if status == "ok" and is_unknown_reply(reply):
        extra = "\n\n🔴 ОТВЕЧАЙ ИСПОЛЬЗУЯ ТОЛЬКО ДАННЫЕ ИЗ [данные]. если в них есть ответ — дай его. НЕ отказывайся, не отвечай «не знаю», если есть хоть какая-то релевантная информация."
        reply2, status2 = await ask_llm(message, user_message, system_content + extra, user_id)
        if status2 == "ok" and not is_unknown_reply(reply2): return reply2, status2
    return reply, status

TICKET_CATEGORIES = {CONFIG.get("TICKET_CATEGORY_ID"), CONFIG.get("PAID_CATEGORY_ID"), CONFIG.get("COINS_CATEGORY_ID")}
def is_ticket_channel(channel: disnake.TextChannel) -> bool: return channel.category and channel.category.id in TICKET_CATEGORIES if channel else False

async def handle_ticket_mention(message: disnake.Message) -> bool:
    try:
        row = cur.execute("SELECT user_id, category_id FROM ticket_owners WHERE channel_id=?", (message.channel.id,)).fetchone()
        if not row: return False
        owner_id = row["user_id"]; manager_row = cur.execute("SELECT manager_id FROM ticket_managers WHERE channel_id=?", (message.channel.id,)).fetchone(); manager_id = manager_row["manager_id"] if manager_row else None
        try:
            delta = datetime.now(timezone.utc) - message.channel.created_at; age = f"{int(delta.total_seconds() // 3600)}ч {int((delta.total_seconds() % 3600) // 60)}м" if int(delta.total_seconds() // 3600) else f"{int((delta.total_seconds() % 3600) // 60)}м"
        except Exception: age = "—"
        cat_id = row["category_id"]; cat_name = "Реальные деньги" if cat_id == CONFIG.get("TICKET_CATEGORY_ID") else "Оплачен" if cat_id == CONFIG.get("PAID_CATEGORY_ID") else "Diamond Coins" if cat_id == CONFIG.get("COINS_CATEGORY_ID") else "—"
        lines = [f"📋 саммари тикета:", f"• заказчик: <@{owner_id}>", f"• менеджер: {f'<@{manager_id}>' if manager_id else 'не назначен'}", f"• категория: {cat_name}", f"• открыт: {age} назад"]
        await message.reply("\n".join(lines), mention_author=False); return True
    except Exception: return False

_last_auto_chat_ts = 0.0
def build_auto_deal() -> Optional[str]:
    try:
        from modules.actions import refresh_daily_deal
        deal = refresh_daily_deal()
        return f"💎 акция дня: скидка {deal.get('discount', 0)}% на «{deal.get('item_data', {}).get('name', '—')}» → {deal.get('new_price', 0)} DC. панель **Бонусы → Акция дня**." if deal else None
    except Exception: return None
def build_auto_giveaway() -> Optional[str]:
    try:
        row = cur.execute("SELECT giveaway_id, prize, end_time, participants FROM giveaways WHERE status='active' AND end_time > ? ORDER BY end_time LIMIT 1", (int(time.time()),)).fetchone()
        if not row: return None
        try: n = len(json.loads(row["participants"] or "[]"))
        except Exception: n = 0
        return f"🎉 идёт розыгрыш: {row['prize']} · уже {n} участников · до <t:{row['end_time']}:R>. заходи в канал розыгрышей."
    except Exception: return None
def build_auto_top_case() -> Optional[str]:
    try:
        row = cur.execute("SELECT prize_desc FROM bonus_case_opens WHERE prize_type='dc' AND opened_at > ? ORDER BY CAST(json_extract(prize_value, '$.value') AS INTEGER) DESC LIMIT 1", (int(time.time()) - 7 * 86400,)).fetchone()
        return f"🎰 топ-кейс недели: {row['prize_desc']}. крути в панели Бонусы." if row else None
    except Exception: return None
def build_auto_gift_reminder() -> Optional[str]: return "🎁 ежедневный подарок в панели профиля — 10–30 DC, кулдаун 24 часа. не забудь забрать сегодня!"
def build_auto_pets() -> Optional[str]:
    try:
        from pet.core import get_clan_pet, get_pet_hourly_income
        pet = get_clan_pet(1); return "🐾 душа клана качается! не забудьте покормить питомца, чтобы он приносил больше DC и бонусов в копилку." if pet["level"] > 1 else "🐾 питомец клана «Душа Клана» — кормите его всей семьёй (1 DC = 1 XP). Он приносит пассивный доход и даёт бонус к выплате!"
    except Exception: return None
AUTO_BUILDERS = [build_auto_deal, build_auto_giveaway, build_auto_top_case, build_auto_gift_reminder, build_auto_pets]

@tasks.loop(hours=CHAT_AUTO_INTERVAL_HOURS)
async def auto_chat_task():
    global _last_auto_chat_ts
    await bot.wait_until_ready()
    try:
        ch = bot.get_channel(ALLOWED_CHANNEL_ID) or await bot.fetch_channel(ALLOWED_CHANNEL_ID)
        if not ch: return
        since = datetime.now(timezone.utc) - timedelta(hours=CHAT_AUTO_IDLE_HOURS)
        async for msg in ch.history(limit=50, after=since):
            if not msg.author.bot: return
        now = time.time()
        if now - _last_auto_chat_ts < CHAT_AUTO_INTERVAL_HOURS * 3600 * 0.8: return
        random.shuffle(AUTO_BUILDERS); text = None
        for builder in AUTO_BUILDERS:
            try:
                text = builder()
                if text: break
            except Exception: pass
        if text: await ch.send(text); _last_auto_chat_ts = now
    except Exception: pass

STATUS_ROTATION = ["Консультант Магазина", "Готов работать!"]
@tasks.loop(minutes=30)
async def smart_status_task():
    await bot.wait_until_ready()
    try:
        now = datetime.now(timezone(timedelta(hours=3)))
        try:
            row = cur.execute("SELECT 1 FROM giveaways WHERE status='active' AND end_time > ? LIMIT 1", (int(time.time()),)).fetchone()
            if row: await bot.change_presence(status=disnake.Status.online, activity=disnake.Game("🎉 Новый розыгрыш!")); return
        except Exception: pass
        if 18 <= now.hour < 22 and random.random() < 0.4: await bot.change_presence(status=disnake.Status.online, activity=disnake.Game("🎁 Не забыл забрать подарок?")); return
        name = "Только проснулся" if 6 <= now.hour < 8 else random.choice(STATUS_ROTATION) if 8 <= now.hour < 22 else "Сплю, но отвечу"
        await bot.change_presence(status=disnake.Status.online, activity=disnake.Game(name))
    except Exception: pass

@tasks.loop(hours=24)
async def weekly_unknown_digest():
    await bot.wait_until_ready()
    try:
        now = datetime.now(timezone(timedelta(hours=3)))
        if now.weekday() != 0 or now.hour != 10: return
        week_ago = int(time.time()) - 7 * 86400; rows = cur.execute("SELECT user_id, question FROM ai_unknown_log WHERE ts > ?", (week_ago,)).fetchall()
        if not rows: return
        total_dialogs = cur.execute("SELECT COUNT(DISTINCT user_id) FROM ai_user_memory WHERE last_seen > ?", (week_ago,)).fetchone()[0] or 0; unknown_by_hash = {}
        for r in rows:
            h = hashlib.md5(_normalize_text(r["question"]).encode("utf-8")).hexdigest()
            if h not in unknown_by_hash: unknown_by_hash[h] = {"count": 0, "sample": r["question"]}
            unknown_by_hash[h]["count"] += 1
        top = sorted(unknown_by_hash.values(), key=lambda x: -x["count"])[:5]
        lines = ["📊 AI-отчёт за неделю:", f"• активных юзеров: {total_dialogs}", f"• «не знаю» случаев: {len(rows)}", "", "топ-5 неизвестных вопросов:"] + [f"  {i}. {t['sample'][:120]}  ({t['count']}×)" for i, t in enumerate(top, 1)] + ["", "стоит дополнить промпт / каталог по этим темам."]
        owner = bot.get_user(OWNER_ID) or await bot.fetch_user(OWNER_ID)
        if owner: await owner.send("\n".join(lines))
    except Exception: pass

@tasks.loop(hours=24)
async def auto_unknown_alert():
    await bot.wait_until_ready()
    try:
        week_ago = int(time.time()) - 7 * 86400; rows = cur.execute("SELECT question FROM ai_unknown_log WHERE ts > ?", (week_ago,)).fetchall()
        if not rows: return
        by_hash = {}
        for r in rows:
            h = hashlib.md5(_normalize_text(r["question"]).encode("utf-8")).hexdigest()
            if h not in by_hash: by_hash[h] = {"count": 0, "sample": r["question"]}
            by_hash[h]["count"] += 1
        owner = bot.get_user(OWNER_ID) or await bot.fetch_user(OWNER_ID)
        if not owner: return
        for h, data in by_hash.items():
            if data["count"] < 3 or cur.execute("SELECT 1 FROM ai_suggested WHERE question_hash=?", (h,)).fetchone(): continue
            cur.execute("INSERT INTO ai_suggested (question_hash, sample_question, sent_at) VALUES (?, ?, ?)", (h, data["sample"][:200], int(time.time()))); db.commit()
            try: await owner.send(f"⚠️ юзеры спрашивают про «{data['sample'][:150]}» ({data['count']}× за неделю). добавь инфу в промпт/каталог.")
            except Exception: pass
    except Exception: pass

@tasks.loop(hours=12)
async def review_reminder_task():
    await bot.wait_until_ready()
    try:
        now = int(time.time())
        for row in cur.execute("SELECT user_id, purchases FROM dc_cache").fetchall():
            uid = row["user_id"]
            try: purchases = json.loads(row["purchases"] or "[]")
            except Exception: continue
            if not purchases: continue
            changed = False
            for p in purchases:
                if p.get("used") or p.get("reminded_review"): continue
                pdate = p.get("date", 0)
                if not pdate or now - pdate < 3 * 86400: continue
                rc = int(load_json(FILES["review_counts"], {}).get(str(uid), 0) or 0); mem = memory_get(uid); last_seen = mem.get("last_seen") or 0
                if rc > 0 and now - last_seen < 7 * 86400: p["reminded_review"] = -1; changed = True; continue
                member = bot.get_user(uid) or await bot.fetch_user(uid)
                if member:
                    try: await member.send(f"привет! всё ок с покупкой «{p.get('value', 'товар')}»? если да — оставь отзыв в канале отзывов, начислим dc за него 💎")
                    except disnake.Forbidden: pass
                    except Exception: pass
                p["reminded_review"] = now; changed = True
            if changed: cur.execute("UPDATE dc_cache SET purchases=? WHERE user_id=?", (json.dumps(purchases, ensure_ascii=False), uid)); db.commit()
    except Exception: pass

async def _log_to_discord(title: str, description: str, color: int = 0x00ff00):
    try:
        ch = bot.get_channel(AI_LOG_CHANNEL_ID) or await bot.fetch_channel(AI_LOG_CHANNEL_ID)
        if ch: await ch.send(embed=disnake.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc)))
    except Exception: pass

@bot.event
async def on_ready():
    try:
        async with aiohttp.ClientSession() as session: await _fetch_available_models(session)
        memory_cleanup_old()
        for task in (auto_chat_task, smart_status_task, weekly_unknown_digest, auto_unknown_alert, review_reminder_task):
            if not task.is_running(): task.start()
        await _log_to_discord("✅ Diamond AI v3.3 запущен", f"> **{bot.user}** онлайн.\n> Отвечаю в <#{ALLOWED_CHANNEL_ID}> и тикетах.\n> Знаю про Душу Клана 🐾", color=0x00ff00)
    except Exception: pass

@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot: return
    if isinstance(message.channel, disnake.TextChannel) and is_ticket_channel(message.channel):
        if _mentions_bot(message): await handle_ticket_mention(message)
        return
    if message.channel.id != ALLOWED_CHANNEL_ID: return
    text = (message.content or "").strip()
    if not text: return
    user_id = message.author.id; member = message.author if isinstance(message.author, disnake.Member) else None
    reaction = check_reaction_reply(text)
    if reaction and not _is_reply_to_bot(message) and not _mentions_bot(message):
        try: await message.add_reaction(reaction)
        except Exception: pass
        memory_upsert(user_id); return
    quick = await quick_action(message, text)
    if quick is not None:
        if quick: await message.channel.send(quick)
        memory_upsert(user_id); return
    catalog_reply = build_catalog_search_reply(text)
    if catalog_reply:
        await message.channel.send(catalog_reply); memory_upsert(user_id); return
    if not should_respond(message): memory_upsert(user_id); return
    if not _is_reply_to_bot(message) and not _mentions_bot(message):
        if await is_channel_busy(message.channel): memory_upsert(user_id); return
        async with aiohttp.ClientSession() as s:
            if not await is_on_topic(s, text): memory_upsert(user_id); return
    norm = _normalize_text(text); prev = _RECENT_QUESTIONS.get(user_id)
    if prev and prev.get("norm") == norm and int(time.time()) - prev.get("ts", 0) < REPEAT_IDENTICAL_MINUTES * 60:
        await message.channel.send("я выше уже ответил — глянь 👆"); memory_upsert(user_id); return
    _RECENT_QUESTIONS[user_id] = {"norm": norm, "ts": int(time.time())}
    mem = memory_get(user_id); is_first = not mem; is_repeat = is_repeat_question(user_id, text); mark_question_asked(user_id, text)
    first_word = norm.split()[0] if norm.split() else ""
    if first_word and len(first_word) > 3:
        memory_upsert(user_id, last_topic=first_word); memory_add_fact(user_id, f"спрашивал про {first_word}"); memory_detect_interests(user_id)
    context_block = build_context_block(user_id, member); sentiment = detect_sentiment(text); style = choose_style(sentiment, text)
    style_suffix = MOOD_SUFFIX.get(style, ""); role_suffix = build_role_suffix(member, is_first); reply_context = ""
    if _is_reply_to_user(message):
        replied = _get_replied_message(message)
        if replied and replied.content: reply_context = f"\n\nюзер отвечает на сообщение другого участника:\n«{replied.content[:200]}»\nучитывай контекст этого сообщения."
    system_content = SYSTEM_PROMPT + style_suffix + role_suffix + reply_context + "\n\n" + context_block
    if is_repeat: system_content += "\n\n[важно] юзер задавал похожий вопрос недавно — ответь кратко, отсылкой к прошлому ответу."
    try:
        async with message.channel.typing():
            await asyncio.sleep(random.uniform(1.2, 2.4))
            reply_text, status = await ask_llm_smart(message=message, user_message=text, system_content=system_content, user_id=user_id)
    except Exception: reply_text, status = ERROR_PHRASES["empty"], "empty"
    reply_text = sanitize_response(reply_text or "").strip() or ERROR_PHRASES["empty"]
    if is_first and status == "ok": reply_text = "привет! я diamond ai. " + reply_text[0].lower() + reply_text[1:]
    try:
        if _is_reply_to_bot(message) or _mentions_bot(message): await message.reply(reply_text, mention_author=False)
        else: await message.channel.send(reply_text)
    except Exception:
        try: await message.channel.send(reply_text)
        except Exception: pass
    if is_unknown_reply(reply_text): log_unknown(user_id, text, reply_text)
    try: await _log_to_discord("💬 Ответ AI", f"> **Юзер:** {message.author.mention}\n> **Статус:** `{status}` · **Тон:** `{style}` · **Sentiment:** `{sentiment}`" + (" · повтор" if is_repeat else "") + (" · первое" if is_first else "") + f"\n> **Вопрос:** {text[:300]}\n> **Ответ:** {reply_text[:500]}{'…' if len(reply_text) > 500 else ''}", color=0xffff00)
    except Exception: pass

def run_ai():
    if not AI_TOKEN: raise SystemExit(1)
    bot.run(AI_TOKEN)

if __name__ == "__main__":
    run_ai()
