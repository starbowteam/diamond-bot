# -*- coding: utf-8 -*-
"""
Единый модуль вспомогательных систем: Бусты, Казино-предметы, Анонс акции, Подарки, Розыгрыши.
"""
import os
import io
import re
import ast
import time
import random
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List

import disnake
from disnake import ui

from core.utils import (
    DATA_DIR, CONFIG, logger, log_discord, load_json, save_json,
    get_item, get_active_items, activate_item, consume_use, clear_item,
    get_dc_cache, save_dc_cache, sync_dc_to_json, db, cur,
)
from modules.dc import get_user_balance, remove_dc, add_dc

# ============================================================
# БЛОК 1: БУСТЫ
# ============================================================
def format_remaining(seconds: int) -> str:
    if seconds <= 0: return "истёк"
    h = seconds // 3600; m = (seconds % 3600) // 60; s = seconds % 60
    if h > 0: return f"{h}ч {m}м"
    if m > 0: return f"{m}м"
    return f"{s}с"

def get_multiplier(user_id: int, kind: str) -> float:
    m_all = 1.0
    item_all = get_item(user_id, "boost_all_x2")
    if item_all: m_all = float(item_all["value"] or 1.0)
    key_map = {"messages": "boost_messages_x2", "voice": "boost_voice_x2", "review": "boost_review_x2"}
    key = key_map.get(kind); m_spec = 1.0
    if key:
        item_spec = get_item(user_id, key)
        if item_spec: m_spec = float(item_spec["value"] or 1.0)
    return max(m_all, m_spec)

def apply_boost(user_id: int, kind: str, base: int) -> int:
    mult = get_multiplier(user_id, kind)
    return int(base * mult)

def get_review_cooldown(user_id: int) -> int:
    item = get_item(user_id, "boost_cooldown_half")
    if item and item["value"]:
        try: return int(item["value"])
        except Exception: pass
    return 120

def can_activate(user_id: int, item_key: str) -> tuple[bool, str]:
    existing = get_item(user_id, item_key)
    if existing:
        if existing["expires_at"] > 0:
            left = existing["expires_at"] - int(time.time())
            if left > 0: return False, f"⏱ У вас уже активен **{existing['item_key']}**. Осталось: **{format_remaining(left)}**"
        elif existing["uses_left"] > 0: return False, f"⏱ У вас уже есть **{existing['item_key']}** ({existing['uses_left']} исп.)"
    return True, ""

async def do_activate(user_id: int, item_key: str, item: dict) -> str:
    if item_key == "boost_daily_reset":
        data = get_dc_cache(user_id)
        data["messages_today"] = 0; data["voice_time_today"] = 0; data["last_voice_dc"] = 0
        save_dc_cache(user_id, data); sync_dc_to_json()
        return "✅ Лимит сообщений и войса **обнулён на сегодня**!"
    duration = int(item.get("duration_hours", 0) or 0); uses = int(item.get("uses", -1))
    activate_item(user_id=user_id, item_key=item_key, item_type=item.get("_category", "boosts"), value=float(item.get("value", 0) or 0), duration_hours=duration, uses=uses)
    if duration > 0: return f"✅ Активирован на **{duration}ч** — применяется сразу."
    if uses > 0: return f"✅ Активирован (**{uses}** исп.) — применяется сразу."
    return "✅ Активирован — применяется сразу."

def apply_casino_win(user_id: int, base_payout: int) -> tuple[int, list]:
    used = []; payout = base_payout
    lh = get_item(user_id, "casino_lucky_hour")
    if lh and lh["value"]: payout = int(payout * float(lh["value"])); used.append("удачный час")
    nm = get_item(user_id, "casino_boost_x2")
    if nm and nm["value"]: payout = int(payout * float(nm["value"])); consume_use(user_id, "casino_boost_x2"); used.append("x2 к выигрышу")
    return payout, used

def try_insurance(user_id: int, bet: int) -> int:
    ins = get_item(user_id, "casino_insurance")
    if not ins: return 0
    refund = int(bet * float(ins["value"] or 0.5)); consume_use(user_id, "casino_insurance"); return refund

# ============================================================
# БЛОК 2: АНОНС АКЦИИ ДНЯ
# ============================================================
ANNOUNCE_CHANNEL_ID = 1462136361711829053
PING_ROLE_ID = 1127428607606796290
DAILY_DEAL_FILE = os.path.join(DATA_DIR, "daily_deal.json")
STATE_FILE = os.path.join(DATA_DIR, "deal_announce.json")
ANNOUNCE_LIFETIME = 3600

def _load_state() -> dict: return load_json(STATE_FILE, {"slot": 0, "message_id": 0, "sent_at": 0, "channel_id": 0})
def _save_state(state: dict): save_json(STATE_FILE, state)

async def _delete_announce(bot, state: dict):
    mid, cid = state.get("message_id"), state.get("channel_id") or ANNOUNCE_CHANNEL_ID
    if not mid: return
    try:
        ch = bot.get_channel(cid) or await bot.fetch_channel(cid)
        msg = await ch.fetch_message(mid); await msg.delete()
    except Exception: pass
    state["message_id"] = 0; state["sent_at"] = 0; _save_state(state)

def _build_text(deal: dict) -> str:
    item_data = deal.get("item_data", {}); name = item_data.get("name", "—"); orig = deal.get("original_price", 0); new = deal.get("new_price", 0); discount = deal.get("discount", 0)
    return f"<@&{PING_ROLE_ID}> — **новая акция за DC!**\n\nСкидка **{discount}%** на **«{name}»** — сейчас **{new} DC** вместо ~~{orig} DC~~.\n\n**Как забрать:**\n> **Каталог** → **Diamond Coins** → **Акция дня**\nУспей — товар дня меняется каждые несколько часов."

async def announce_deal(bot, deal: dict, slot: int):
    ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if not ch:
        try: ch = await bot.fetch_channel(ANNOUNCE_CHANNEL_ID)
        except Exception: return
    try: msg = await ch.send(_build_text(deal))
    except Exception: return
    _save_state({"slot": slot, "message_id": msg.id, "sent_at": int(time.time()), "channel_id": ch.id})

async def process_deal_announce(bot):
    try:
        deal_data = load_json(DAILY_DEAL_FILE, {}); cur_slot = deal_data.get("slot", 0); cur_deal = deal_data.get("item"); updated_at = deal_data.get("updated_at", 0); state = _load_state(); now = time.time()
        if state.get("message_id") and state.get("sent_at") and now - state["sent_at"] > ANNOUNCE_LIFETIME: await _delete_announce(bot, state)
        if cur_deal and cur_slot and cur_slot != state.get("slot"):
            if (now - updated_at) < ANNOUNCE_LIFETIME:
                if state.get("message_id"): await _delete_announce(bot, state)
                await announce_deal(bot, cur_deal, cur_slot)
            else: state["slot"] = cur_slot; _save_state(state)
    except Exception: pass

# ============================================================
# БЛОК 3: ПОДАРКИ DC
# ============================================================
GIFT_FEE_PERCENT = 5
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"

async def process_gift_dc(sender: disnake.Member, recipient_id: int, amount: int, price_paid: int) -> tuple[bool, str]:
    guild = sender.guild; recipient = guild.get_member(recipient_id)
    if not recipient: await add_dc(sender.id, price_paid, "Возврат — получатель не найден"); return False, "Получатель не найден на сервере"
    if recipient.bot: await add_dc(sender.id, price_paid, "Возврат — получатель бот"); return False, "Нельзя дарить ботам"
    if recipient.id == sender.id: await add_dc(sender.id, price_paid, "Возврат — сам себе"); return False, "Нельзя подарить самому себе"
    try: await add_dc(recipient.id, amount, f"Подарок от {sender.display_name}")
    except Exception as e:
        await add_dc(sender.id, price_paid, "Возврат — ошибка начисления"); return False, f"Ошибка начисления: {e}"
    try:
        from clan.quests import on_gift_quest_hook
        await on_gift_quest_hook(sender.id, amount)
    except Exception: pass
    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot
        data = get_dc_cache(sender.id); total_gifted = sum(h.get("amount", 0) for h in data.get("history", []) if h.get("reason", "").startswith("Подарок от") and h.get("amount", 0) > 0) + amount
        await check_and_unlock(sender.id, "gift_total", value=total_gifted, bot=bot)
    except Exception: pass
    try: await recipient.send(embed=disnake.Embed(title="🎁 Вам подарили Diamond Coins!", description=f"> **Отправитель:** {sender.display_name}\n> **Получено:** `+{amount} DC`\n\n> Спасибо за то, что вы с нами! Оставить отзыв можно в <#1462074763437543435>.", color=0x2ecc71, timestamp=datetime.now(timezone.utc)).set_image(url=IMG_STRIPE))
    except Exception: pass
    await log_discord(title="🎁 Подарок DC", description=f"> **Отправитель:** {sender.mention}\n> **Получатель:** {recipient.mention}\n> **Сумма:** `{amount} DC`\n> **Комиссия:** `{price_paid - amount} DC`", color=0x00ff00, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"])
    return True, f"Подарок отправлен! Получатель: {recipient.mention}"

# ============================================================
# БЛОК 4: АВТОЗАМЕНА ССЫЛОК СТРАЙПА
# ============================================================
NEW_URL = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"
STRIPE_URL_RE = re.compile(r"https://cdn\.discordapp\.com/attachments/1527006158282555412/1537851307757539390/image\.png\?[^\s\"'\)\]]+")
BASE_DIR = Path(__file__).parent.resolve()
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "node_modules", ".backup_stripe", ".idea", ".vscode"}
VALID_EXTS = {".py", ".json", ".txt", ".md"}

def should_skip(path: Path) -> bool: return any(part in EXCLUDE_DIRS for part in path.parts) or path.suffix.lower() not in VALID_EXTS
def fix_content(content: str) -> tuple[str, int]: matches = STRIPE_URL_RE.findall(content); return (STRIPE_URL_RE.sub(NEW_URL, content), len(matches)) if matches else (content, 0)

def run_fix(verbose: bool = True) -> dict:
    stats = {"scanned": 0, "changed": 0, "total_replacements": 0, "files": []}
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in files:
            path = Path(root) / fname
            if should_skip(path): continue
            stats["scanned"] += 1
            try:
                with open(path, "r", encoding="utf-8") as f: content = f.read()
            except Exception: continue
            new_content, count = fix_content(content)
            if count == 0: continue
            try:
                with open(path, "w", encoding="utf-8") as f: f.write(new_content)
                stats["changed"] += 1; stats["total_replacements"] += count; stats["files"].append((str(path.relative_to(BASE_DIR)), count))
                if verbose: print(f"  ✅ {path.relative_to(BASE_DIR)} — {count} замен")
            except Exception: pass
    return stats

def main():
    print("🔧 Автозамена ссылок страйпа (stripe)"); print(f"📂 {BASE_DIR}\n"); print("🔍 Сканирую ...\n")
    stats = run_fix(verbose=True)
    print(f"\n📊 Просканировано: {stats['scanned']}\n✏️  Изменено: {stats['changed']}\n🔄 Заменено: {stats['total_replacements']}")
    return stats

# ============================================================
# БЛОК 5: РОЗЫГРЫШИ (из giveaways.py)
# ============================================================
LOG_CHANNEL_ID = 1530453871581855744
GIVEAWAY_CHANNEL_ID = 1462390938851741923
STAFF_PANEL_CHANNEL_ID = 1551276116679860314
REPORT_DM_USER_ID = 796293832751972352
REVIEW_CHANNEL_ID = 1462074763437543435
GIVEAWAY_FULL_ROLES = [1530823425764098058, 1530822331188903966, 1127428607606796294, 1471844291595731016]
MSK = timezone(timedelta(hours=3))

GIVEAWAY_TEMPLATES = {
    "100": {"prize": "100 DC", "amount": 100, "winners": 1, "description": "🎉 Быстрый розыгрыш 100 Diamond Coins! Небольшой приз — хороший шанс испытать удачу. Жми участвовать!"},
    "150": {"prize": "150 DC", "amount": 150, "winners": 1, "description": "🎉 Стандартный розыгрыш 150 DC для всех! Отличный стартовый приз на любые нужды магазина. Заходи и участвуй!"},
    "350": {"prize": "350 DC", "amount": 350, "winners": 1, "description": "🎉 Розыгрыш 350 DC — средний куш для настоящих ценителей! Хорошая сумма для любых покупок. Не упусти свой шанс!"},
    "400": {"prize": "400 DC", "amount": 400, "winners": 2, "description": "🎉 Розыгрыш 400 DC на двоих победителей! Двойной шанс сорвать куш. Участвуй — удача может улыбнуться именно тебе!"},
    "450": {"prize": "450 DC", "amount": 450, "winners": 2, "description": "🎉 Розыгрыш 450 DC на двоих победителей! Щедрый приз для любителей адреналина. Жми участвовать и не упусти свой шанс!"},
    "600": {"prize": "600 DC", "amount": 600, "winners": 3, "description": "🎉 Розыгрыш 600 DC на троих победителей! Тройной шанс на хороший куш. Собирайся с мыслями — и вперёд!"},
    "700": {"prize": "700 DC", "amount": 700, "winners": 3, "description": "🎉 Розыгрыш 700 DC на троих победителей! Большие призы для активных ребят. Удача любит смелых!"},
    "1000": {"prize": "1000 DC", "amount": 1000, "winners": 5, "description": "👑 Большой розыгрыш 1000 DC на пятерых победителей! Крупный куш для настоящих везунчиков. Испытай судьбу!"},
    "1400": {"prize": "1400 DC", "amount": 1400, "winners": 7, "description": "🔥 Розыгрыш 1400 DC на семерых победителей! Огромная сумма — и множество шансов. Не упусти свой момент!"},
    "1800": {"prize": "1800 DC", "amount": 1800, "winners": 9, "description": "🔥 Розыгрыш 1800 DC на девятерых победителей! Щедрый куш для многих участников. Присоединяйся к борьбе за приз!"},
    "2400": {"prize": "2400 DC", "amount": 2400, "winners": 12, "description": "💎 Розыгрыш 2400 DC на двенадцать победителей! Массовый праздник щедрости для всех. Присоединяйся — весело и прибыльно!"},
    "3000": {"prize": "3000 DC", "amount": 3000, "winners": 15, "description": "💎 Розыгрыш 3000 DC на пятнадцать победителей! Большой призовой фонд для всех. Участвуй — и забери своё!"},
    "3600": {"prize": "3600 DC", "amount": 3600, "winners": 18, "description": "👑 Огромный розыгрыш 3600 DC на восемнадцать победителей! Максимум призов и возможностей. Докажи, что ты достоин!"},
    "4000": {"prize": "4000 DC", "amount": 4000, "winners": 20, "description": "👑 Мега-розыгрыш 4000 DC на двадцать победителей! Королевский куш и море победителей. Сражайся за свой шанс прямо сейчас!"},
}

def _ensure_col(table: str, column: str, ddl: str):
    try:
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()]
        if column not in cols: cur.execute(f'ALTER TABLE "{table}" ADD COLUMN {ddl}'); db.commit()
    except Exception: pass

def _init_giveaway_tables():
    cur.executescript("CREATE TABLE IF NOT EXISTS giveaways (giveaway_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, message_id INTEGER, host_id INTEGER, prize TEXT, description TEXT, winners_count INTEGER, end_time INTEGER, created_at INTEGER, required_invites INTEGER DEFAULT 0, participants TEXT, winners TEXT, status TEXT, valid_participants TEXT, final_embed_id INTEGER, auto_payout INTEGER DEFAULT 0, payout_done INTEGER DEFAULT 0);")
    db.commit()
    cur.executescript("CREATE TABLE IF NOT EXISTS giveaway_pending_payouts (id INTEGER PRIMARY KEY AUTOINCREMENT, giveaway_id INTEGER, user_id INTEGER, amount INTEGER, dm_message_id INTEGER DEFAULT 0, created_at INTEGER, paid_at INTEGER DEFAULT 0);")
    db.commit()
    _ensure_col("giveaway_pending_payouts", "giveaway_id", "giveaway_id INTEGER"); _ensure_col("giveaway_pending_payouts", "user_id", "user_id INTEGER"); _ensure_col("giveaway_pending_payouts", "amount", "amount INTEGER DEFAULT 0")
    _ensure_col("giveaways", "auto_payout", "auto_payout INTEGER DEFAULT 0"); _ensure_col("giveaways", "payout_done", "payout_done INTEGER DEFAULT 0")
    try: cur.executescript("CREATE INDEX IF NOT EXISTS idx_gpp_user ON giveaway_pending_payouts (user_id, paid_at); CREATE INDEX IF NOT EXISTS idx_gpp_giveaway ON giveaway_pending_payouts (giveaway_id, paid_at);"); db.commit()
    except Exception: pass

_bot = None; _setup_done = False

def list_from_str(data):
    if not data: return []
    try: return ast.literal_eval(data)
    except Exception: return []
def str_from_list(data): return str(data)
def parse_duration(duration_str: str):
    match = re.fullmatch(r'(\d+)\s*([mhd])', duration_str.strip().lower())
    if not match: return None
    value, unit = int(match.group(1)), match.group(2)
    return timedelta(minutes=value) if unit == 'm' else timedelta(hours=value) if unit == 'h' else timedelta(days=value)
def is_giveaway_staff(member: disnake.Member) -> bool: return any(r.id in GIVEAWAY_FULL_ROLES for r in member.roles)
def _parse_dc_amount(prize: str) -> int:
    if not prize: return 0
    m = re.search(r"(\d+)", prize)
    return int(m.group(1)) if m else 0

IMG_BANNER_GW = "https://cdn.discordapp.com/attachments/1527006158282555412/1556735389618798632/image.png?backend=b2&ex=6ac53e4f&is=6ac3eccf&hm=ed4085879047dc6da3c00fc5a55edf0fe24d334f55f7086339380e0364a0ee09&"
IMG_STRIPE_GW = "https://cdn.discordapp.com/attachments/1527006158282555412/1530795801268453447/pisk.png?ex=6a66e02f&is=6a658eaf&hm=79e41273327d2e1048ba42df62868cbb88f5b06b112ca864de2c7a02326523e9&"
IMG_BANNER_FIN = "https://cdn.discordapp.com/attachments/1527006158282555412/1556735391875203082/image.png?backend=b2&ex=6ac53e50&is=6ac3ecd0&hm=b331ed1665f81621e08ee916aaabaf5bb78430e86de1d7a51c0ce7072ec175f9&"
COLOR_GW = 6776679

def build_giveaway_embeds(prize, description, winners_count, participants_count, end_dt):
    end_ts = int(end_dt.timestamp()); desc_text = (description or "").strip() or "Проводим розыгрыш — стоит нажать на кнопку участвовать, и больше условий нет!"
    embed_banner = disnake.Embed(color=COLOR_GW).set_image(url=IMG_BANNER_GW)
    embed_main = disnake.Embed(title=f"Розыгрыш на {prize} ! 🎁", description=f"> {desc_text}\n\nВремя окончания: <t:{end_ts}:R>", color=COLOR_GW).set_image(url=IMG_STRIPE_GW)
    embed_main.add_field(name="> **Участвуют:**", value=f"```{participants_count}```", inline=True).add_field(name="> **Победителей:**", value=f"```{winners_count}```", inline=True)
    return [embed_banner, embed_main]

def build_finished_giveaway_embed(prize, description, participants_count, winners_mentions, end_dt):
    end_ts = int(end_dt.timestamp()); date_str = datetime.fromtimestamp(end_ts, MSK).strftime("%d.%m.%Y"); desc_text = (description or "").strip() or "Розыгрыш завершён."
    embed_banner = disnake.Embed(color=COLOR_GW).set_image(url=IMG_BANNER_FIN)
    embed_main = disnake.Embed(title=f"Розыгрыш на {prize} завершён! 🏆", description=f"> {desc_text}\n\n> **Победитель(и):** {winners_mentions}\n\n> Спасибо за участие в розыгрышах! Ожидайте последующие розыгрыши!", color=COLOR_GW).set_image(url=IMG_STRIPE_GW)
    embed_main.add_field(name="> **Участвовали:**", value=f"```{participants_count}```", inline=True).add_field(name="> **Завершён:**", value=f"```{date_str}```", inline=True)
    return [embed_banner, embed_main]

class JoinButton(disnake.ui.Button):
    def __init__(self): super().__init__(label="ㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤ🎉 Участвоватьㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤ", style=disnake.ButtonStyle.secondary, custom_id="giveaway_join")
    async def callback(self, inter: disnake.MessageInteraction):
        try:
            row = cur.execute("SELECT * FROM giveaways WHERE message_id=? AND status='active'", (inter.message.id,)).fetchone()
            if not row: return await inter.response.send_message("❌ Розыгрыш не найден или завершён.", ephemeral=True)
            gid = row["giveaway_id"]; participants = list_from_str(row["participants"]); user_id = inter.user.id
            if user_id in participants: return await inter.response.send_message("🎊 Вы уже участвуете в розыгрыше!", ephemeral=True)
            participants.append(user_id); cur.execute("UPDATE giveaways SET participants=? WHERE giveaway_id=?", (str_from_list(participants), gid)); db.commit()
            end_dt = datetime.fromtimestamp(row["end_time"], timezone.utc); embeds = build_giveaway_embeds(row["prize"], row["description"], row["winners_count"], len(participants), end_dt)
            try: await inter.message.edit(embeds=embeds)
            except Exception: pass
            await inter.response.send_message("✅ Ты успешно присоединился к розыгрышу!", ephemeral=True)
            try: await inter.user.send(embed=disnake.Embed(title="✅ Ты участвуешь в розыгрыше!", description=f"> **Приз:** {row['prize']}\n> **ID розыгрыша:** `{gid}`\n> **Участников:** {len(participants)}", color=0x00ff00))
            except Exception: pass
        except Exception: pass

class GiveawayView(disnake.ui.View):
    def __init__(self): super().__init__(timeout=None); self.add_item(JoinButton())

class GiveawaySelect(disnake.ui.StringSelect):
    def __init__(self):
        super().__init__(placeholder="Выберите нужный пункт", min_values=1, max_values=1, options=[disnake.SelectOption(label="・Начать розыгрыш", description="Создать розыгрыш вручную", emoji="<:__:1538399607699021895>", value="create"), disnake.SelectOption(label="・Шаблонные розыгрыши", description="Готовые шаблоны DC-розыгрышей", emoji="<:cakleb:1553236134316875846>", value="templates"), disnake.SelectOption(label="・Лист розыгрышей", description="Все существующие розыгрыши", emoji="<:banne1:1538551829246513312>", value="list"), disnake.SelectOption(label="・Завершить принудительно", description="Принудительно завершить розыгрыш", emoji="<:clear:1538561439491686410>", value="end"), disnake.SelectOption(label="・Перевыбрать победителя", description="Перевыбрать победителя", emoji="<:restart:1553231421190049813>", value="reroll")], custom_id="giveaway_select")
    async def callback(self, inter: disnake.MessageInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        value = inter.data.values[0]
        if value == "create": await inter.response.send_modal(GiveawayModal())
        elif value == "templates": await show_templates_panel(inter)
        elif value == "list": await inter.response.defer(ephemeral=True); await list_giveaways(inter)
        elif value == "end": await inter.response.send_modal(EndGiveawayModal())
        elif value == "reroll": await inter.response.send_modal(RerollModal())

class GiveawayPanelView(disnake.ui.View):
    def __init__(self): super().__init__(timeout=None); self.add_item(GiveawaySelect())

class GiveawayModal(ui.Modal):
    def __init__(self): super().__init__(title="Создание розыгрыша", components=[ui.TextInput(label="Приз", custom_id="prize", max_length=256), ui.TextInput(label="Описание", custom_id="description", style=disnake.TextInputStyle.paragraph, max_length=1024), ui.TextInput(label="Победителей (число)", custom_id="winners", max_length=3), ui.TextInput(label="Длительность (10m, 2h, 1d)", custom_id="duration", max_length=10, placeholder="Например: 30m, 2h, 7d")])
    async def callback(self, inter: disnake.MessageModalInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        prize, description = inter.text_values["prize"].strip(), inter.text_values["description"].strip()
        try: winners_count = int(inter.text_values["winners"].strip())
        except ValueError: return await inter.response.send_message("❌ Поле 'Победителей' должно быть целым числом ≥ 1.", ephemeral=True)
        duration_td = parse_duration(inter.text_values["duration"])
        if duration_td is None: return await inter.response.send_message("❌ Неверный формат длительности.", ephemeral=True)
        end_time = int((datetime.now(MSK) + duration_td).astimezone(timezone.utc).timestamp())
        embeds = build_giveaway_embeds(prize, description, winners_count, 0, datetime.fromtimestamp(end_time, timezone.utc))
        await inter.response.send_message("⏳ Создаю розыгрыш...", ephemeral=True)
        channel = _bot.get_channel(GIVEAWAY_CHANNEL_ID)
        if not channel: return await inter.edit_original_message(content="❌ Канал для розыгрышей не найден.")
        msg = await channel.send(content="|| @everyone ||", embeds=embeds, view=GiveawayView())
        cur.execute("""INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, description, winners_count, end_time, created_at, required_invites, participants, winners, status, auto_payout, payout_done) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (inter.guild.id, channel.id, msg.id, inter.author.id, prize, description, winners_count, end_time, int(time.time()), 0, "[]", "[]", "active", 0, 0))
        db.commit(); gid = cur.lastrowid; asyncio.create_task(schedule_end(gid))
        await inter.edit_original_message(content=f"✅ Розыгрыш создан! **ID: `{gid}`** (ручной — приз вручается вручную)")

async def get_valid_participants(gid: int, guild: disnake.Guild):
    row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
    if not row: return []
    participants = list_from_str(row["participants"]); valid = []
    for uid in participants:
        member = guild.get_member(uid)
        if not member or member.bot: continue
        valid.append(uid)
    return list(set(valid))

async def schedule_end(gid: int):
    row = cur.execute("SELECT end_time FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
    if not row: return
    delay = row["end_time"] - int(time.time())
    if delay > 0: await asyncio.sleep(delay)
    await finish_giveaway(gid)

async def _queue_pending_payouts(gid: int, row, winners: List[int]) -> int:
    auto_payout = row["auto_payout"]
    if not auto_payout or not winners:
        if not winners: cur.execute("UPDATE giveaways SET payout_done=1 WHERE giveaway_id=?", (gid,)); db.commit()
        return 0
    total_amount = _parse_dc_amount(row["prize"])
    if total_amount <= 0: return 0
    share = total_amount // len(winners)
    if share <= 0: return 0
    for uid in winners:
        cur.execute("INSERT INTO giveaway_pending_payouts (giveaway_id, user_id, amount, dm_message_id, created_at, paid_at) VALUES (?, ?, ?, 0, ?, 0)", (gid, uid, share, int(time.time())))
    cur.execute("UPDATE giveaways SET payout_done=1 WHERE giveaway_id=?", (gid,)); db.commit()
    return share

async def process_pending_payouts(bot, user_id: int) -> int:
    rows = cur.execute("SELECT id, giveaway_id, amount, dm_message_id FROM giveaway_pending_payouts WHERE user_id=? AND paid_at=0", (user_id,)).fetchall()
    if not rows:
        try:
            won_giveaways = cur.execute("SELECT giveaway_id, prize, winners FROM giveaways WHERE status='finished' AND auto_payout=1").fetchall()
            for g in won_giveaways:
                winners = list_from_str(g["winners"])
                if user_id not in winners: continue
                exists = cur.execute("SELECT paid_at FROM giveaway_pending_payouts WHERE giveaway_id=? AND user_id=?", (g["giveaway_id"], user_id)).fetchone()
                if exists: continue
                amount = _parse_dc_amount(g["prize"]) // max(len(winners), 1)
                if amount <= 0: continue
                cur.execute("INSERT INTO giveaway_pending_payouts (giveaway_id, user_id, amount, dm_message_id, created_at, paid_at) VALUES (?, ?, ?, 0, ?, 0)", (g["giveaway_id"], user_id, amount, int(time.time())))
            db.commit(); rows = cur.execute("SELECT id, giveaway_id, amount, dm_message_id FROM giveaway_pending_payouts WHERE user_id=? AND paid_at=0", (user_id,)).fetchall()
        except Exception: pass
    if not rows: return 0
    total_paid = 0
    for r in rows:
        pid, gid, amount, dm_mid = r["id"], r["giveaway_id"], r["amount"], r["dm_message_id"]
        try:
            await add_dc(user_id, amount, f"Победа в розыгрыше #{gid} (после отзыва)", notify=False, log=False, to_clan_pool=True)
            cur.execute("UPDATE giveaway_pending_payouts SET paid_at=? WHERE id=?", (int(time.time()), pid)); db.commit(); total_paid += amount
            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id); dm_channel = user.dm_channel or await user.create_dm()
                new_embeds = _build_paid_winner_dm(gid=gid, amount=amount)
                if dm_mid:
                    try: msg = await dm_channel.fetch_message(dm_mid); await msg.edit(embeds=new_embeds)
                    except Exception: await dm_channel.send(embeds=new_embeds)
                else: await dm_channel.send(embeds=new_embeds)
            except Exception: pass
            await log_discord(title="💎 Приз за розыгрыш выдан", description=f"> **Победитель:** <@{user_id}>\n> **Розыгрыш:** `#{gid}`\n> **Сумма:** `+{amount} DC`\n> **Условие:** отзыв написан", color=0x00ff88)
        except Exception: pass
    return total_paid

async def finish_giveaway(gid: int):
    try:
        row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
        if not row or row["status"] != "active": return
        guild = _bot.get_guild(row["guild_id"])
        if not guild: return
        channel = guild.get_channel(row["channel_id"]) or _bot.get_channel(row["channel_id"])
        if not channel: return
        valid_participants = await get_valid_participants(gid, guild); participants = list_from_str(row["participants"]); winners_count = row["winners_count"]
        pool = valid_participants.copy(); random.shuffle(pool); winners = pool[:winners_count] if pool else []
        cur.execute("UPDATE giveaways SET winners=?, status='finished', valid_participants=? WHERE giveaway_id=?", (str_from_list(winners), str_from_list(valid_participants), gid)); db.commit()
        try: msg = await channel.fetch_message(row["message_id"]); await msg.delete()
        except Exception: pass
        winners_mentions = " ".join(f"<@{u}>" for u in winners) if winners else "Нет победителей 😔"
        end_dt = datetime.fromtimestamp(row["end_time"], timezone.utc); finished_embeds = build_finished_giveaway_embed(row["prize"], row["description"], len(participants), winners_mentions, end_dt)
        try:
            embed_msg = await channel.send(embeds=finished_embeds); cur.execute("UPDATE giveaways SET final_embed_id=? WHERE giveaway_id=?", (embed_msg.id, gid)); db.commit()
        except Exception: pass
        share = await _queue_pending_payouts(gid, row, winners)
        try: await send_giveaway_report(gid=gid, prize=row["prize"], winners=winners, share=share, is_auto=bool(row["auto_payout"]))
        except Exception: pass
        prize_name, is_auto = row["prize"], bool(row["auto_payout"]); winner_ids = set(winners); fallback_share = _parse_dc_amount(prize_name) // max(len(winners), 1) if winners else 0
        for uid in participants:
            try:
                member = guild.get_member(uid)
                if not member: continue
                if uid in winner_ids: dm = _build_template_winner_dm(gid=gid, prize=prize_name, share=share if share > 0 else fallback_share) if is_auto else _build_manual_winner_dm(gid=gid, prize=prize_name)
                else: dm = _build_loser_dm(gid=gid, prize=prize_name)
                sent = await member.send(embeds=dm)
                if is_auto and uid in winner_ids and sent:
                    try: cur.execute("UPDATE giveaway_pending_payouts SET dm_message_id=? WHERE giveaway_id=? AND user_id=? AND paid_at=0", (sent.id, gid, uid)); db.commit()
                    except Exception: pass
            except Exception: pass
    except Exception: pass

def _build_manual_winner_dm(gid: int, prize: str) -> list:
    e1 = disnake.Embed(color=0xffaa00).set_image(url=IMG_STRIPE)
    e2 = disnake.Embed(title="🏆 Ты победил в розыгрыше!", description=f"> **Приз:** {prize}\n> **ID розыгрыша:** `#{gid}`\n\n> 📩 **Что делать:**\n> Отпиши в ЛС <@{REPORT_DM_USER_ID}> в течение **24 часов**,\n> иначе приз уйдёт следующему участнику.", color=0xffaa00).set_image(url=IMG_STRIPE)
    return [e1, e2]

def _build_template_winner_dm(gid: int, prize: str, share: int) -> list:
    e1 = disnake.Embed(color=0xffaa00).set_image(url=IMG_STRIPE)
    e2 = disnake.Embed(title="🏆 Ты выиграл в розыгрыше!", description=f"> **Приз:** {prize}\n> **Твоя доля:** `+{share} DC`\n> **ID розыгрыша:** `#{gid}`\n\n> ⏳ **Как забрать?**\n> Напиши **новый отзыв** в <#{REVIEW_CHANNEL_ID}> — и `{share} DC` автоматически упадут тебе на баланс.\n\n> ❗ Если ты уже писал отзыв раньше — нужно написать **ещё один** (кулдаун 2 минуты).\n\n> ✨ _После отзыва это сообщение обновится._", color=0xffaa00).set_image(url=IMG_STRIPE)
    return [e1, e2]

def _build_paid_winner_dm(gid: int, amount: int) -> list:
    e1 = disnake.Embed(color=0x00ff88).set_image(url=IMG_STRIPE)
    e2 = disnake.Embed(title="💎 Приз зачислен на баланс!", description=f"> **Сумма:** `+{amount} DC`\n> **ID розыгрыша:** `#{gid}`\n\n> ✨ DC уже у тебя на балансе. Спасибо за отзыв!", color=0x00ff88).set_image(url=IMG_STRIPE)
    return [e1, e2]

def _build_loser_dm(gid: int, prize: str) -> list:
    e1 = disnake.Embed(color=0x808080).set_image(url=IMG_STRIPE)
    e2 = disnake.Embed(title="🎲 Розыгрыш завершён", description=f"> **Приз:** {prize}\n> **ID розыгрыша:** `#{gid}`\n\n> **Результат:**\n> Ты не занял призовое место. Постарайся в следующий раз! 🍀", color=0x808080).set_image(url=IMG_STRIPE)
    return [e1, e2]

async def send_giveaway_report(gid: int, prize: str, winners: list, share: int = 0, is_auto: bool = False):
    try:
        if _bot is None: return
        user = _bot.get_user(REPORT_DM_USER_ID) or await _bot.fetch_user(REPORT_DM_USER_ID)
        if not user or not winners: return
        file = disnake.File(io.BytesIO("\n".join(str(uid) for uid in winners).encode("utf-8")), filename=f"winners_{gid}.txt")
        winners_mentions = " ".join(f"<@{u}>" for u in winners); type_label = "💎 Шаблонный" if is_auto else "📩 Ручной"
        extra = f"> **Каждому:** `+{share} DC`\n> **Всего:** `{share * len(winners)} DC`\n> ⏳ **Ждут нового отзыва в <#{REVIEW_CHANNEL_ID}>**\n> После отзыва DC упадут автоматически\n\n" if is_auto and share > 0 else "> ⏳ **Ждём отписи в ЛС** от каждого победителя\n> (в течение 24ч, иначе приз уйдёт следующему)\n\n"
        await user.send(embeds=[disnake.Embed(color=6776679).set_image(url=IMG_STRIPE), disnake.Embed(title=f"📊 Победители розыгрыша #{gid}", description=f"> **Приз:** {prize}\n> **Тип:** {type_label}\n> **Победителей:** `{len(winners)}`\n\n{extra}> 🏆 **Список победителей:**\n> {winners_mentions}", color=6776679).set_image(url=IMG_STRIPE)], file=file)
    except Exception: pass

async def reroll_giveaway(inter, gid: int):
    row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
    if not row: return await inter.edit_original_message(content="❌ Розыгрыш не найден.")
    if row["status"] == "active": return await inter.edit_original_message(content="❌ Розыгрыш ещё не завершён.")
    guild = _bot.get_guild(row["guild_id"]); channel = guild.get_channel(row["channel_id"]) or _bot.get_channel(row["channel_id"])
    valid_participants = await get_valid_participants(gid, guild)
    if not valid_participants: return await inter.edit_original_message(content="❌ Нет валидных участников.")
    old_winners = list_from_str(row["winners"]); pool = [u for u in valid_participants if u not in old_winners]
    if not pool: return await inter.edit_original_message(content="❌ Нет участников для перевыбора.")
    random.shuffle(pool); new_winners = pool[:row["winners_count"]]
    cur.execute("UPDATE giveaways SET winners=? WHERE giveaway_id=?", (str_from_list(new_winners), gid)); db.commit()
    try:
        if row["final_embed_id"]: msg = await channel.fetch_message(row["final_embed_id"]); await msg.delete()
    except Exception: pass
    winners_mentions = " ".join(f"<@{u}>" for u in new_winners) if new_winners else "Нет победителей 😔"
    end_dt = datetime.fromtimestamp(row["end_time"], timezone.utc); finished_embeds = build_finished_giveaway_embed(row["prize"], row["description"] or "", len(list_from_str(row["participants"])), winners_mentions, end_dt)
    embed_msg = await channel.send(embeds=finished_embeds); cur.execute("UPDATE giveaways SET final_embed_id=? WHERE giveaway_id=?", (embed_msg.id, gid)); db.commit()
    is_auto = bool(row["auto_payout"]); share = 0
    if is_auto and new_winners:
        share = _parse_dc_amount(row["prize"]) // len(new_winners)
        for old_uid in old_winners:
            if old_uid not in new_winners: cur.execute("DELETE FROM giveaway_pending_payouts WHERE giveaway_id=? AND user_id=? AND paid_at=0", (gid, old_uid))
        for uid in new_winners:
            if not cur.execute("SELECT id FROM giveaway_pending_payouts WHERE giveaway_id=? AND user_id=?", (gid, uid)).fetchone(): cur.execute("INSERT INTO giveaway_pending_payouts (giveaway_id, user_id, amount, dm_message_id, created_at, paid_at) VALUES (?, ?, ?, 0, ?, 0)", (gid, uid, share, int(time.time())))
        db.commit()
    if is_auto and new_winners:
        for uid in new_winners:
            try:
                member = guild.get_member(uid)
                if member:
                    sent = await member.send(embeds=_build_template_winner_dm(gid=gid, prize=row["prize"], share=share))
                    if sent: cur.execute("UPDATE giveaway_pending_payouts SET dm_message_id=? WHERE giveaway_id=? AND user_id=? AND paid_at=0", (sent.id, gid, uid)); db.commit()
            except Exception: pass
    try: await send_giveaway_report(gid=gid, prize=row["prize"], winners=new_winners, share=share, is_auto=is_auto)
    except Exception: pass
    await inter.edit_original_message(content=f"✅ Перевыбор выполнен для розыгрыша #{gid}")

class EndGiveawayModal(ui.Modal):
    def __init__(self): super().__init__(title="Принудительное завершение", components=[ui.TextInput(label="ID розыгрыша", custom_id="giveaway_id", max_length=10, placeholder="Введите числовой ID")])
    async def callback(self, inter: disnake.ModalInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        try: gid = int(inter.text_values["giveaway_id"].strip())
        except ValueError: return await inter.response.send_message("❌ ID должен быть числом.", ephemeral=True)
        if not cur.execute("SELECT * FROM giveaways WHERE giveaway_id=? AND status='active'", (gid,)).fetchone(): return await inter.response.send_message("❌ Активный розыгрыш не найден.", ephemeral=True)
        await inter.response.send_message("⏳ Завершаю...", ephemeral=True); await finish_giveaway(gid); await inter.edit_original_message(content=f"✅ Розыгрыш #{gid} завершён.")

class RerollModal(ui.Modal):
    def __init__(self): super().__init__(title="Перевыбор победителя", components=[ui.TextInput(label="ID розыгрыша", custom_id="giveaway_id", max_length=10, placeholder="Введите числовой ID")])
    async def callback(self, inter: disnake.ModalInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        try: gid = int(inter.text_values["giveaway_id"].strip())
        except ValueError: return await inter.response.send_message("❌ ID должен быть числом.", ephemeral=True)
        await inter.response.defer(ephemeral=True); await reroll_giveaway(inter, gid)

async def show_templates_panel(inter: disnake.MessageInteraction):
    e = disnake.Embed(title="💎 Шаблонные розыгрыши", description=f"> Выберите тип ниже — розыгрыш стартует сразу.\n\n> ⏱ **Длительность:** 1 день\n> 💰 **Выдача:** после отзыва в <#{REVIEW_CHANNEL_ID}>\n> ⭐ **Бонус:** за отзыв ещё начислят DC\n\n**Доступные шаблоны:** от **100** до **4000 DC**", color=6776679).set_image(url=IMG_STRIPE)
    await inter.response.send_message(embed=e, view=TemplateStartView(), ephemeral=True)

class TemplateSelect(disnake.ui.StringSelect):
    def __init__(self):
        super().__init__(placeholder="Выберите шаблон розыгрыша...", min_values=1, max_values=1, options=[disnake.SelectOption(label=f"{k} DC · {v['winners']} победителей", description=v["description"][:90], value=k) for k, v in GIVEAWAY_TEMPLATES.items()], custom_id="giveaway_template_select")
    async def callback(self, inter: disnake.MessageInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        key = inter.data.values[0]
        if key not in GIVEAWAY_TEMPLATES: return await inter.response.send_message("❌ Шаблон не найден.", ephemeral=True)
        await inter.response.defer(ephemeral=True); tpl = GIVEAWAY_TEMPLATES[key]
        end_time = int((datetime.now(MSK) + timedelta(days=1)).astimezone(timezone.utc).timestamp())
        channel = _bot.get_channel(GIVEAWAY_CHANNEL_ID)
        if not channel: return await inter.edit_original_response(content="❌ Канал не найден.")
        msg = await channel.send(content="|| @everyone ||", embeds=build_giveaway_embeds(tpl["prize"], tpl["description"], tpl["winners"], 0, datetime.fromtimestamp(end_time, timezone.utc)), view=GiveawayView())
        cur.execute("""INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, description, winners_count, end_time, created_at, required_invites, participants, winners, status, auto_payout, payout_done) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (inter.guild.id, channel.id, msg.id, inter.author.id, tpl["prize"], tpl["description"], tpl["winners"], end_time, int(time.time()), 0, "[]", "[]", "active", 1, 0))
        db.commit(); gid = cur.lastrowid; asyncio.create_task(schedule_end(gid))
        await inter.edit_original_response(content=f"✅ Шаблонный розыгрыш **{tpl['prize']}** создан! ID: `{gid}`\n> 💰 DC начислятся победителям после нового отзыва ({tpl['winners']} чел.)", embeds=[], view=None)

class TemplateStartView(disnake.ui.View):
    def __init__(self): super().__init__(timeout=180); self.add_item(TemplateSelect())

async def list_giveaways(inter: disnake.MessageInteraction):
    rows = cur.execute("SELECT * FROM giveaways WHERE guild_id=? ORDER BY giveaway_id DESC LIMIT 20", (inter.guild.id,)).fetchall()
    if not rows: return await inter.edit_original_response(content="Розыгрышей не найдено.")
    lines = []
    for r in rows:
        status_icon = "🟢" if r["status"] == "active" else "🔴"; participants_count = len(list_from_str(r["participants"])); winners = list_from_str(r["winners"])
        time_str = f"Конец: <t:{r['end_time']}:R>" if r["status"] == "active" else f"Закончился: <t:{r['end_time']}:d>"; winners_str = " | Победители: " + ", ".join(f"<@{w}>" for w in winners) if r["status"] == "finished" and winners else ""
        lines.append(f"{status_icon} **ID {r['giveaway_id']}**{' 💎' if r['auto_payout'] else ' 📩'} — {r['prize']}\n> Участников: **{participants_count}** | {time_str}{winners_str}")
    await inter.followup.send(embed=disnake.Embed(title="📋 Список розыгрышей (последние 20)", description="\n\n".join(lines), color=6776679).set_footer(text="💎 = шаблонный (после отзыва) · 📩 = ручной"), ephemeral=True)

async def send_giveaway_panel():
    try:
        ch = _bot.get_channel(STAFF_PANEL_CHANNEL_ID) or await _bot.fetch_channel(STAFF_PANEL_CHANNEL_ID)
        if not ch: return
        async for msg in ch.history(limit=50):
            if msg.author == _bot.user and msg.embeds:
                for e in msg.embeds:
                    if e.title and "розыгрыш" in e.title.lower():
                        try: await msg.delete(); break
                        except Exception: pass
        e1 = disnake.Embed(title="Управление розыгрышами", description="> Панель для управления всеми розыгрышами сервера.\n\n> **Начать розыгрыш** — создать вручную.\n> **Шаблонные розыгрыши** — готовые DC.\n> **Лист розыгрышей** — все текущие и завершённые.\n> **Завершить принудительно** — закрыть досрочно.\n> **Перевыбрать победителя** — реролл после завершения.", color=6776679).set_image(url=IMG_STRIPE)
        await ch.send(embed=e1, view=GiveawayPanelView())
    except Exception: pass

async def _delayed_gw_init():
    try:
        await _bot.wait_until_ready(); await asyncio.sleep(8)
        try:
            active_rows = cur.execute("SELECT giveaway_id, end_time FROM giveaways WHERE status='active'").fetchall()
            for r in active_rows:
                if r["end_time"] <= int(time.time()): asyncio.create_task(finish_giveaway(r["giveaway_id"]))
                else: asyncio.create_task(schedule_end(r["giveaway_id"]))
        except Exception: pass
        await send_giveaway_panel()
    except Exception: pass

def setup_giveaways(bot_instance):
    global _bot, _setup_done
    if _setup_done: return
    _setup_done = True; _bot = bot_instance
    _init_giveaway_tables()
    bot_instance.add_view(GiveawayView()); bot_instance.add_view(GiveawayPanelView())
    try: bot_instance.loop.create_task(_delayed_gw_init())
    except Exception: pass
