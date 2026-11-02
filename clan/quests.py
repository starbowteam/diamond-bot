# -*- coding: utf-8 -*-
"""Квесты клановой лиги + рендер Pillow."""
import os, io, time, asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
import disnake
from core.utils import CONFIG, logger, db, cur, load_json, save_json, log_discord

MSK = timezone(timedelta(hours=3))
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"
EMBEDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embeds")

QUESTS: Dict[str, dict] = {
    "msg_50": {"title": "Болтун", "desc": "Напиши 50 сообщений в чате", "reward": 30, "goal": 50, "type": "daily", "unit": "сообщений", "icon": "fa-comment"},
    "voice_1h": {"title": "Голос", "desc": "Проведи 1 час в голосовых каналах", "reward": 50, "goal": 3600, "type": "daily", "unit": "секунд", "icon": "fa-microphone"},
    "casino_3": {"title": "Азарт", "desc": "Сыграй 3 партии в казино", "reward": 30, "goal": 3, "type": "daily", "unit": "партий", "icon": "fa-dice"},
    "cmds_5": {"title": "Активный", "desc": "5 взаимодействий с панелями клана", "reward": 20, "goal": 5, "type": "daily", "unit": "действий", "icon": "fa-computer-mouse"},
    "msg_1000": {"title": "Мега-болтун", "desc": "1000 сообщений за неделю", "reward": 200, "goal": 1000, "type": "weekly", "unit": "сообщений", "icon": "fa-comments"},
    "voice_10h": {"title": "Марафонец", "desc": "10 часов в ГЧ", "reward": 250, "goal": 36000, "type": "weekly", "unit": "секунд", "icon": "fa-headphones"},
    "casino_30": {"title": "Азартная неделя", "desc": "Сыграй 30 партий в казино", "reward": 150, "goal": 30, "type": "weekly", "unit": "партий", "icon": "fa-dice-five"},
    "win_3000": {"title": "Удачливый", "desc": "Выиграй 3000 DC в казино за неделю", "reward": 350, "goal": 3000, "type": "weekly", "unit": "DC", "icon": "fa-trophy"},
    "first_review": {"title": "Первый отзыв", "desc": "Оставь первый отзыв в этом сезоне", "reward": 150, "goal": 1, "type": "once", "unit": "отзывов", "icon": "fa-star"},
    "gift_500": {"title": "Щедрость", "desc": "Подари кому-то 500 DC через магазин", "reward": 200, "goal": 500, "type": "once", "unit": "DC", "icon": "fa-gift"},
    "jackpot": {"title": "Джекпот", "desc": "Более 10K DC за раз", "reward": 500, "goal": 10000, "type": "once", "unit": "DC", "icon": "fa-fire"},
    "top_contributor": {"title": "Лидер клана", "desc": "Стань топ-1 клана", "reward": 400, "goal": 1, "type": "once", "unit": "раз", "icon": "fa-crown"},
}

def init_clan_quests():
    for key, q in QUESTS.items(): cur.execute("INSERT OR IGNORE INTO quests (key, title, description, reward, goal, type, emoji, active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)", (key, q["title"], q["desc"], q["reward"], q["goal"], q["type"], q["icon"]))
    db.commit()

def _get_cycle_id() -> int:
    from clan.core import get_current_cycle
    cycle = get_current_cycle()
    return cycle["id"] if cycle else 0

def get_quest_progress(user_id: int, quest_key: str, cycle_id: Optional[int] = None) -> dict:
    if cycle_id is None: cycle_id = _get_cycle_id()
    row = cur.execute("SELECT progress, completed_at, claimed FROM quest_progress WHERE user_id=? AND quest_key=? AND cycle_id=?", (user_id, quest_key, cycle_id)).fetchone()
    return {"progress": row["progress"], "completed_at": row["completed_at"], "claimed": row["claimed"]} if row else {"progress": 0, "completed_at": None, "claimed": 0}

def _ensure_row(user_id: int, quest_key: str, cycle_id: int): cur.execute("INSERT OR IGNORE INTO quest_progress (user_id, quest_key, cycle_id, progress) VALUES (?, ?, ?, 0)", (user_id, quest_key, cycle_id))

def update_progress(user_id: int, quest_key: str, delta: int = 1, absolute: Optional[int] = None):
    if quest_key not in QUESTS: return
    quest = QUESTS[quest_key]; cycle_id = _get_cycle_id()
    if cycle_id == 0: return
    from clan.core import get_user_clan
    if not get_user_clan(user_id): return
    _ensure_row(user_id, quest_key, cycle_id)
    row = cur.execute("SELECT progress, completed_at FROM quest_progress WHERE user_id=? AND quest_key=? AND cycle_id=?", (user_id, quest_key, cycle_id)).fetchone()
    if row["completed_at"]: return
    new_progress = min(absolute if absolute is not None else (row["progress"] + delta), quest["goal"])
    if new_progress >= quest["goal"]:
        cur.execute("UPDATE quest_progress SET progress=?, completed_at=? WHERE user_id=? AND quest_key=? AND cycle_id=?", (new_progress, int(time.time()), user_id, quest_key, cycle_id)); db.commit()
        asyncio.create_task(_reward_user(user_id, quest_key, quest))
    else:
        cur.execute("UPDATE quest_progress SET progress=? WHERE user_id=? AND quest_key=? AND cycle_id=?", (new_progress, user_id, quest_key, cycle_id)); db.commit()

async def _reward_user(user_id: int, quest_key: str, quest: dict):
    reward = quest["reward"]
    from clan.core import get_user_clan
    from modules.dc import add_dc
    clan = get_user_clan(user_id)
    if not clan: return
    try:
        from modules.dc import touch_activity
        touch_activity(user_id)
    except Exception: pass
    await add_dc(user_id, reward, f"Квест: {quest['title']}", notify=False, log=False, to_clan_pool=True)
    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot
        total_completed = cur.execute("SELECT COUNT(*) AS c FROM quest_progress WHERE user_id=? AND completed_at IS NOT NULL", (user_id,)).fetchone()
        asyncio.create_task(check_and_unlock(user_id, "quests", value=total_completed["c"] if total_completed else 0, bot=bot))
    except Exception: pass
    try:
        from core.bot import bot
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if user:
            e = disnake.Embed(title="✅ Квест выполнен!", description=f"> **Квест:** {quest['title']}\n> **Награда:** `+{reward} DC` на баланс\n> **В копилку клана:** `+{reward} DC` ({clan['emoji']} **{clan['name']}**)\n\n> Продолжай выполнять квесты!", color=clan["color"]).set_image(url=IMG_STRIPE)
            await user.send(embed=e)
    except Exception: pass
    await log_discord(title="🎯 Квест выполнен", description=f"> **Участник:** <@{user_id}>\n> **Клан:** {clan['emoji']} {clan['name']}\n> **Квест:** {quest['title']}\n> **На баланс:** `+{reward} DC`\n> **В копилку:** `+{reward} DC`", color=clan["color"], channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"])

def get_user_quests(user_id: int) -> List[dict]:
    cycle_id = _get_cycle_id(); result = []
    for key, q in QUESTS.items():
        row = cur.execute("SELECT progress, completed_at FROM quest_progress WHERE user_id=? AND quest_key=? AND cycle_id=?", (user_id, key, cycle_id)).fetchone()
        result.append({"key": key, "title": q["title"], "desc": q["desc"], "reward": q["reward"], "goal": q["goal"], "progress": row["progress"] if row else 0, "completed": bool(row["completed_at"]) if row else False, "type": q["type"], "icon": q["icon"]})
    return result

def build_quests_embeds(user_id: int):
    from clan.core import get_user_clan, clan_cut
    try: from modules.shop.render_quests import render_quests
    except Exception: render_quests = None
    clan = get_user_clan(user_id); quests = get_user_quests(user_id)
    for q in quests: q["reward_cut"] = clan_cut(q["reward"])
    e = disnake.Embed(color=clan["color"] if clan else 6776679); file = None
    if render_quests is not None:
        try: buf = render_quests(user_id, quests); file = disnake.File(buf, filename=f"quests_{user_id}.png"); e.set_image(url=f"attachment://quests_{user_id}.png")
        except Exception: pass
    return [e], file

def format_quests_embed(user_id: int):
    embeds, _ = build_quests_embeds(user_id); return embeds

def reset_daily_quests():
    cycle_id = _get_cycle_id(); daily_keys = [k for k, q in QUESTS.items() if q["type"] == "daily"]
    cur.execute(f"DELETE FROM quest_progress WHERE cycle_id=? AND quest_key IN ({','.join('?' * len(daily_keys))})", (cycle_id, *daily_keys)); db.commit()

def reset_weekly_quests():
    cycle_id = _get_cycle_id(); weekly_keys = [k for k, q in QUESTS.items() if q["type"] == "weekly"]
    cur.execute(f"DELETE FROM quest_progress WHERE cycle_id=? AND quest_key IN ({','.join('?' * len(weekly_keys))})", (cycle_id, *weekly_keys)); db.commit()

async def on_message_quest_hook(message: disnake.Message):
    if message.author.bot or not isinstance(message.channel, disnake.TextChannel): return
    user_id = message.author.id
    from clan.core import get_user_clan
    if not get_user_clan(user_id) or message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"] or len((message.content or "").strip()) < CONFIG.get("MIN_MESSAGE_LENGTH", 3): return
    update_progress(user_id, "msg_50", delta=1); update_progress(user_id, "msg_1000", delta=1)

async def on_voice_quest_hook(user_id: int, seconds: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id) or seconds <= 0: return
    update_progress(user_id, "voice_1h", delta=seconds); update_progress(user_id, "voice_10h", delta=seconds)

async def on_casino_quest_hook(user_id: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id): return
    update_progress(user_id, "casino_3", delta=1); update_progress(user_id, "casino_30", delta=1)

async def on_casino_win_hook(user_id: int, payout: int, bet: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id): return
    profit = max(payout - bet, 0)
    if profit > 0: update_progress(user_id, "win_3000", delta=profit)
    if profit >= 10000: update_progress(user_id, "jackpot", absolute=10000)

async def on_review_quest_hook(user_id: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id): return
    update_progress(user_id, "first_review", delta=1)

async def on_purchase_quest_hook(user_id: int, amount_dc: int): pass

async def on_gift_quest_hook(sender_id: int, amount_dc: int):
    from clan.core import get_user_clan
    if not get_user_clan(sender_id): return
    update_progress(sender_id, "gift_500", delta=amount_dc)

async def on_panel_click_quest_hook(user_id: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id): return
    update_progress(user_id, "cmds_5", delta=1)
