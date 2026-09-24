# -*- coding: utf-8 -*-
"""Квесты клановой лиги."""
import os
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

import disnake

from core.utils import (
    CONFIG, logger, db, cur, load_json, save_json, log_discord
)

MSK = timezone(timedelta(hours=3))

IMG_STRIPE = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
              "1537851307757539390/image.png?ex=6ab5efe3&is=6ab49e63&"
              "hm=d1b48b6ea98c9662564b5a77012797024de47fbc9444922b72184d6d0a6d5a2a&")

EMBEDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embeds")


# ============================================================
# ОПРЕДЕЛЕНИЕ КВЕСТОВ
# ============================================================
QUESTS: Dict[str, dict] = {
    # ---------- DAILY ----------
    "msg_50": {
        "title": "💬 Болтун",
        "desc": "Напиши 50 сообщений",
        "reward": 10, "goal": 50, "type": "daily",
        "unit": "сообщений", "icon": "💬",
    },
    "voice_1h": {
        "title": "🎙 Голос",
        "desc": "Проведи 1 час в голосовых каналах",
        "reward": 15, "goal": 3600, "type": "daily",
        "unit": "секунд", "icon": "🎙",
    },
    "casino_3": {
        "title": "🎲 Азарт",
        "desc": "Сыграй 3 партии в казино",
        "reward": 10, "goal": 3, "type": "daily",
        "unit": "партий", "icon": "🎲",
    },
    "cmds_5": {
        "title": "🎯 Активный",
        "desc": "5 взаимодействий с панелями клана",
        "reward": 5, "goal": 5, "type": "daily",
        "unit": "действий", "icon": "🎯",
    },

    # ---------- WEEKLY ----------
    "review_1": {
        "title": "📝 Отзыв недели",
        "desc": "Оставь 1 отзыв в канале отзывов",
        "reward": 25, "goal": 1, "type": "weekly",
        "unit": "отзывов", "icon": "📝",
    },
    "msg_300": {
        "title": "💎 Мега-болтун",
        "desc": "300 сообщений за неделю",
        "reward": 50, "goal": 300, "type": "weekly",
        "unit": "сообщений", "icon": "💎",
    },
    "voice_5h": {
        "title": "🎙 Марафонец",
        "desc": "5 часов в голосовых каналах за неделю",
        "reward": 60, "goal": 18000, "type": "weekly",
        "unit": "секунд", "icon": "🎙",
    },
    "shop_100": {
        "title": "👑 Инвестор",
        "desc": "Потрать 100 DC в магазине за неделю",
        "reward": 30, "goal": 100, "type": "weekly",
        "unit": "DC", "icon": "👑",
    },
    "win_500": {
        "title": "🎰 Удачливый",
        "desc": "Выиграй 500+ DC в казино за неделю",
        "reward": 75, "goal": 500, "type": "weekly",
        "unit": "DC", "icon": "🎰",
    },

    # ---------- ONCE (за цикл) ----------
    "first_review": {
        "title": "🌟 Первый отзыв сезона",
        "desc": "Оставь первый отзыв в этом сезоне",
        "reward": 40, "goal": 1, "type": "once",
        "unit": "отзывов", "icon": "🌟",
    },
    "gift_50": {
        "title": "🎁 Щедрость",
        "desc": "Подари кому-то 50 DC через магазин",
        "reward": 20, "goal": 50, "type": "once",
        "unit": "DC", "icon": "🎁",
    },
    "jackpot": {
        "title": "🎰 Джекпот",
        "desc": "Выиграй 1000+ DC за одну партию в казино",
        "reward": 100, "goal": 1000, "type": "once",
        "unit": "DC", "icon": "🎰",
    },
    "top_contributor": {
        "title": "👑 Лидер клана",
        "desc": "Стань топ-1 по вкладу в клане хотя бы раз",
        "reward": 200, "goal": 1, "type": "once",
        "unit": "раз", "icon": "👑",
    },
}


def init_clan_quests():
    """Регистрирует квесты в БД (для истории)."""
    for key, q in QUESTS.items():
        cur.execute(
            "INSERT OR IGNORE INTO quests (key, title, description, reward, goal, type, emoji, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (key, q["title"], q["desc"], q["reward"], q["goal"], q["type"], q["icon"])
        )
    db.commit()


# ============================================================
# ПРОГРЕСС
# ============================================================
def _get_cycle_id() -> int:
    from clan.core import get_current_cycle
    cycle = get_current_cycle()
    return cycle["id"] if cycle else 0


def get_quest_progress(user_id: int, quest_key: str, cycle_id: Optional[int] = None) -> dict:
    if cycle_id is None:
        cycle_id = _get_cycle_id()
    row = cur.execute(
        "SELECT progress, completed_at, claimed FROM quest_progress "
        "WHERE user_id=? AND quest_key=? AND cycle_id=?",
        (user_id, quest_key, cycle_id)
    ).fetchone()
    if row:
        return {"progress": row["progress"], "completed_at": row["completed_at"], "claimed": row["claimed"]}
    return {"progress": 0, "completed_at": None, "claimed": 0}


def _ensure_row(user_id: int, quest_key: str, cycle_id: int):
    cur.execute(
        "INSERT OR IGNORE INTO quest_progress (user_id, quest_key, cycle_id, progress) "
        "VALUES (?, ?, ?, 0)",
        (user_id, quest_key, cycle_id)
    )


def update_progress(user_id: int, quest_key: str, delta: int = 1, absolute: Optional[int] = None):
    """
    Обновляет прогресс. Если absolute задан — приравнивает.
    Если достигнут goal — выдаёт награду.
    """
    if quest_key not in QUESTS:
        return
    quest = QUESTS[quest_key]
    cycle_id = _get_cycle_id()
    if cycle_id == 0:
        return

    # Юзер должен быть в клане
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return

    _ensure_row(user_id, quest_key, cycle_id)
    row = cur.execute(
        "SELECT progress, completed_at FROM quest_progress "
        "WHERE user_id=? AND quest_key=? AND cycle_id=?",
        (user_id, quest_key, cycle_id)
    ).fetchone()

    if row["completed_at"]:
        return  # уже выполнено

    new_progress = absolute if absolute is not None else (row["progress"] + delta)
    new_progress = min(new_progress, quest["goal"])

    if new_progress >= quest["goal"]:
        cur.execute(
            "UPDATE quest_progress SET progress=?, completed_at=? "
            "WHERE user_id=? AND quest_key=? AND cycle_id=?",
            (new_progress, int(time.time()), user_id, quest_key, cycle_id)
        )
        db.commit()
        # Выдача награды
        asyncio.create_task(_reward_user(user_id, quest_key, quest))
    else:
        cur.execute(
            "UPDATE quest_progress SET progress=? "
            "WHERE user_id=? AND quest_key=? AND cycle_id=?",
            (new_progress, user_id, quest_key, cycle_id)
        )
        db.commit()


async def _reward_user(user_id: int, quest_key: str, quest: dict):
    """
    Выдаёт награду:
    - 100% в банк клана (вклад)
    - ЛС юзеру
    - Лог в канал
    """
    reward = quest["reward"]

    # 1. В банк клана (100%)
    from clan.core import add_clan_contribution, get_user_clan
    clan = get_user_clan(user_id)
    if not clan:
        return

    await add_clan_contribution(user_id, reward, f"Квест: {quest['title']}")

    # 2. ЛС юзеру
    try:
        from core.bot import bot
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if user:
            e1 = disnake.Embed(color=clan["color"])
            e1.set_image(url=IMG_STRIPE)
            e2 = disnake.Embed(
                title="✅ Квест выполнен!",
                description=(
                    f"> **Квест:** {quest['title']}\n"
                    f"> **Награда:** `+{reward} DC` в копилку клана {clan['emoji']} **{clan['name']}**\n\n"
                    f"> Продолжай выполнять квесты, чтобы поднять свой вклад!"
                ),
                color=clan["color"]
            )
            e2.set_image(url=IMG_STRIPE)
            await user.send(embeds=[e1, e2])
    except Exception as e:
        logger.warning(f"quest reward DM {user_id}: {e}")

    # 3. Лог
    await log_discord(
        title="🎯 Квест выполнен",
        description=(
            f"> **Участник:** <@{user_id}>\n"
            f"> **Клан:** {clan['emoji']} {clan['name']}\n"
            f"> **Квест:** {quest['title']}\n"
            f"> **Награда:** `+{reward} DC`"
        ),
        color=clan["color"],
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )


# ============================================================
# СПИСОК КВЕСТОВ ДЛЯ ЮЗЕРА
# ============================================================
def get_user_quests(user_id: int) -> List[dict]:
    cycle_id = _get_cycle_id()
    result = []
    for key, q in QUESTS.items():
        row = cur.execute(
            "SELECT progress, completed_at FROM quest_progress "
            "WHERE user_id=? AND quest_key=? AND cycle_id=?",
            (user_id, key, cycle_id)
        ).fetchone()
        progress = row["progress"] if row else 0
        completed = bool(row["completed_at"]) if row else False
        result.append({
            "key": key,
            "title": q["title"],
            "desc": q["desc"],
            "reward": q["reward"],
            "goal": q["goal"],
            "progress": progress,
            "completed": completed,
            "type": q["type"],
            "icon": q["icon"],
        })
    return result


def format_quests_embed(user_id: int) -> List[disnake.Embed]:
    """Возвращает 2 эмбеда: картинка + список с прогресс-барами."""
    from clan.core import get_user_clan, make_progress_bar
    from clan.core import EMBEDS_DIR as CORE_EMBEDS

    clan = get_user_clan(user_id)
    quests = get_user_quests(user_id)

    daily = [q for q in quests if q["type"] == "daily"]
    weekly = [q for q in quests if q["type"] == "weekly"]
    once = [q for q in quests if q["type"] == "once"]

    def render(q):
        pct = q["progress"] / q["goal"] if q["goal"] > 0 else 0
        bar = make_progress_bar(pct)
        status = "✅" if q["completed"] else f"`{q['progress']}/{q['goal']}`"
        return f"> {q['icon']} **{q['title']}** — {q['desc']}\n> {bar} {status}  ·  +{q['reward']} DC"

    lines = []
    if daily:
        lines.append("**🕐 ЕЖЕДНЕВНЫЕ** (сброс 00:00 МСК)")
        lines += [render(q) for q in daily]
    if weekly:
        lines.append("\n**📅 НЕДЕЛЬНЫЕ** (сброс пн 00:00 МСК)")
        lines += [render(q) for q in weekly]
    if once:
        lines.append("\n**🌟 РАЗОВЫЕ (за цикл)**")
        lines += [render(q) for q in once]

    e1 = disnake.Embed(color=clan["color"] if clan else 6776679)
    data = load_json(os.path.join(EMBEDS_DIR, "quests.json"), {})
    for e in data.get("embeds", [])[:1]:
        e1 = disnake.Embed.from_dict(e)

    e2 = disnake.Embed(
        title="📋 Твои квесты",
        description="\n".join(lines),
        color=clan["color"] if clan else 6776679
    )
    e2.set_image(url=IMG_STRIPE)
    return [e1, e2]


# ============================================================
# СБРОСЫ
# ============================================================
def reset_daily_quests():
    cycle_id = _get_cycle_id()
    daily_keys = [k for k, q in QUESTS.items() if q["type"] == "daily"]
    placeholders = ",".join("?" * len(daily_keys))
    cur.execute(
        f"DELETE FROM quest_progress WHERE cycle_id=? AND quest_key IN ({placeholders})",
        (cycle_id, *daily_keys)
    )
    db.commit()
    logger.info(f"Сброс daily-квестов (cycle_id={cycle_id})")


def reset_weekly_quests():
    cycle_id = _get_cycle_id()
    weekly_keys = [k for k, q in QUESTS.items() if q["type"] == "weekly"]
    placeholders = ",".join("?" * len(weekly_keys))
    cur.execute(
        f"DELETE FROM quest_progress WHERE cycle_id=? AND quest_key IN ({placeholders})",
        (cycle_id, *weekly_keys)
    )
    db.commit()
    logger.info(f"Сброс weekly-квестов (cycle_id={cycle_id})")


# ============================================================
# ХУКИ
# ============================================================
async def on_message_quest_hook(message: disnake.Message):
    """Вызывается из bot.on_message после основного расчёта DC."""
    if message.author.bot:
        return
    if not isinstance(message.channel, disnake.TextChannel):
        return
    user_id = message.author.id

    # Только клубные и в клане
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return

    # msg_50 (daily) и msg_300 (weekly) — только в не-флудных каналах
    if message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        return
    if len((message.content or "").strip()) < CONFIG.get("MIN_MESSAGE_LENGTH", 3):
        return

    update_progress(user_id, "msg_50", delta=1)
    update_progress(user_id, "msg_300", delta=1)


async def on_voice_quest_hook(user_id: int, seconds: int):
    """Вызывается из bot.on_voice_state_update при выходе из войса."""
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return
    if seconds <= 0:
        return
    update_progress(user_id, "voice_1h", delta=seconds)
    update_progress(user_id, "voice_5h", delta=seconds)


async def on_casino_quest_hook(user_id: int):
    """Вызывается из actions.py при каждой партии."""
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return
    update_progress(user_id, "casino_3", delta=1)


async def on_casino_win_hook(user_id: int, payout: int, bet: int):
    """
    Вызывается при выигрыше в казино.
    payout — полная выплата (что вернулось юзеру)
    """
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return

    profit = max(payout - bet, 0)
    if profit > 0:
        update_progress(user_id, "win_500", delta=profit)

    # jackpot — разовый, если профит за раз ≥ 1000
    if profit >= 1000:
        # absolute=goal — сразу засчитываем
        update_progress(user_id, "jackpot", absolute=1000)


async def on_review_quest_hook(user_id: int):
    """Вызывается после успешного отзыва в REVIEW_COUNT_CHANNEL."""
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return
    update_progress(user_id, "review_1", delta=1)
    update_progress(user_id, "first_review", delta=1)


async def on_purchase_quest_hook(user_id: int, amount_dc: int):
    """Вызывается при покупке в магазине за DC."""
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return
    update_progress(user_id, "shop_100", delta=amount_dc)


async def on_gift_quest_hook(sender_id: int, amount_dc: int):
    """Вызывается при подарке DC."""
    from clan.core import get_user_clan
    if not get_user_clan(sender_id):
        return
    update_progress(sender_id, "gift_50", delta=amount_dc)


async def on_panel_click_quest_hook(user_id: int):
    """Вызывается при взаимодействии с панелями клана."""
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return
    update_progress(user_id, "cmds_5", delta=1)
