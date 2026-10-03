# -*- coding: utf-8 -*-
"""Квесты клановой лиги + рендер Pillow."""
import os
import io
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
              "1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&"
              "hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&")

EMBEDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embeds")


# ============================================================
# ОПРЕДЕЛЕНИЕ КВЕСТОВ — 15 разных, без повторов
# ============================================================
QUESTS: Dict[str, dict] = {
    # ---------- DAILY (5 разных) ----------
    "msg_50": {
        "title": "Болтун",
        "desc": "Напиши 50 сообщений в чате",
        "reward": 30, "goal": 50, "type": "daily",
        "unit": "сообщений", "icon": "fa-comment",
    },
    "voice_1h": {
        "title": "Голос",
        "desc": "Проведи 1 час в голосовых каналах",
        "reward": 50, "goal": 3600, "type": "daily",
        "unit": "секунд", "icon": "fa-microphone",
    },
    "casino_3": {
        "title": "Азарт",
        "desc": "Сыграй 3 партии в казино",
        "reward": 30, "goal": 3, "type": "daily",
        "unit": "партий", "icon": "fa-dice",
    },
    "cmds_5": {
        "title": "Активный",
        "desc": "5 взаимодействий с панелями клана",
        "reward": 20, "goal": 5, "type": "daily",
        "unit": "действий", "icon": "fa-computer-mouse",
    },
    "shop_buy": {
        "title": "Покупатель",
        "desc": "Купи любой товар в DC-магазине",
        "reward": 40, "goal": 1, "type": "daily",
        "unit": "покупок", "icon": "fa-cart-shopping",
    },

    # ---------- WEEKLY (5 разных) ----------
    "msg_1000": {
        "title": "Мега-болтун",
        "desc": "1000 сообщений за неделю",
        "reward": 200, "goal": 1000, "type": "weekly",
        "unit": "сообщений", "icon": "fa-comments",
    },
    "voice_10h": {
        "title": "Марафонец",
        "desc": "10 часов в голосовых каналах за неделю",
        "reward": 250, "goal": 36000, "type": "weekly",
        "unit": "секунд", "icon": "fa-headphones",
    },
    "casino_30": {
        "title": "Азартная неделя",
        "desc": "Сыграй 30 партий в казино",
        "reward": 150, "goal": 30, "type": "weekly",
        "unit": "партий", "icon": "fa-dice-five",
    },
    "shop_500": {
        "title": "Инвестор",
        "desc": "Потрать 500 DC в DC-магазине за неделю",
        "reward": 200, "goal": 500, "type": "weekly",
        "unit": "DC", "icon": "fa-sack-dollar",
    },
    "win_3000": {
        "title": "Удачливый",
        "desc": "Выиграй 3000 DC в казино за неделю",
        "reward": 350, "goal": 3000, "type": "weekly",
        "unit": "DC", "icon": "fa-trophy",
    },

    # ---------- ONCE (5 разных) ----------
    "first_review": {
        "title": "Первый отзыв",
        "desc": "Оставь первый отзыв в этом сезоне",
        "reward": 150, "goal": 1, "type": "once",
        "unit": "отзывов", "icon": "fa-star",
    },
    "gift_500": {
        "title": "Щедрость",
        "desc": "Подари кому-то 500 DC через магазин",
        "reward": 200, "goal": 500, "type": "once",
        "unit": "DC", "icon": "fa-gift",
    },
    "jackpot": {
        "title": "Джекпот",
        "desc": "Выиграй 10 000+ DC за одну партию в казино",
        "reward": 500, "goal": 10000, "type": "once",
        "unit": "DC", "icon": "fa-fire",
    },
    "top_contributor": {
        "title": "Лидер клана",
        "desc": "Стань топ-1 по вкладу в клане хотя бы раз",
        "reward": 400, "goal": 1, "type": "once",
        "unit": "раз", "icon": "fa-crown",
    },
    "rich_500k": {
        "title": "Полумиллионер",
        "desc": "Накопи 500 000 DC на балансе",
        "reward": 800, "goal": 500000, "type": "once",
        "unit": "DC", "icon": "fa-money-bill-wave",
    },
}


def init_clan_quests():
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
    if quest_key not in QUESTS:
        return
    quest = QUESTS[quest_key]
    cycle_id = _get_cycle_id()
    if cycle_id == 0:
        return

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
        return

    new_progress = absolute if absolute is not None else (row["progress"] + delta)
    new_progress = min(new_progress, quest["goal"])

    if new_progress >= quest["goal"]:
        cur.execute(
            "UPDATE quest_progress SET progress=?, completed_at=? "
            "WHERE user_id=? AND quest_key=? AND cycle_id=?",
            (new_progress, int(time.time()), user_id, quest_key, cycle_id)
        )
        db.commit()
        asyncio.create_task(_reward_user(user_id, quest_key, quest))
    else:
        cur.execute(
            "UPDATE quest_progress SET progress=? "
            "WHERE user_id=? AND quest_key=? AND cycle_id=?",
            (new_progress, user_id, quest_key, cycle_id)
        )
        db.commit()


async def _reward_user(user_id: int, quest_key: str, quest: dict):
    reward = quest["reward"]

    from clan.core import add_clan_contribution, get_user_clan, clan_cut
    clan = get_user_clan(user_id)
    if not clan:
        return

    try:
        from modules.dc import touch_activity
        touch_activity(user_id)
    except Exception as e:
        logger.warning(f"quest touch_activity: {e}")

    clan_amount = clan_cut(reward)
    if clan_amount <= 0:
        return

    await add_clan_contribution(user_id, clan_amount, f"Квест: {quest['title']}")

    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot
        total_completed = cur.execute(
            "SELECT COUNT(*) AS c FROM quest_progress WHERE user_id=? AND completed_at IS NOT NULL",
            (user_id,)
        ).fetchone()
        total = total_completed["c"] if total_completed else 0
        asyncio.create_task(check_and_unlock(user_id, "quests", value=total, bot=bot))
    except Exception as e:
        logger.warning(f"quest achievements: {e}")

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
                    f"> **Награда:** `+{clan_amount} DC` в копилку клана {clan['emoji']} **{clan['name']}**\n\n"
                    f"> Продолжай выполнять квесты, чтобы поднять свой вклад!"
                ),
                color=clan["color"]
            )
            e2.set_image(url=IMG_STRIPE)
            await user.send(embeds=[e1, e2])
    except Exception as e:
        logger.warning(f"quest reward DM {user_id}: {e}")

    await log_discord(
        title="🎯 Квест выполнен",
        description=(
            f"> **Участник:** <@{user_id}>\n"
            f"> **Клан:** {clan['emoji']} {clan['name']}\n"
            f"> **Квест:** {quest['title']}\n"
            f"> **В копилку:** `+{clan_amount} DC`"
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


# ============================================================
# ФОРМИРОВАНИЕ EMBED'ОВ С ПИЛЛОW
# ============================================================
def build_quests_embeds(user_id: int):
    """
    Возвращает (embeds, file) — готовый набор для send_message:
        await inter.response.send_message(embeds=embeds, file=file, ephemeral=True)
    """
    from clan.core import get_user_clan, clan_cut

    try:
        from modules.shop.render_quests import render_quests
    except Exception as e:
        logger.warning(f"render_quests import: {e}")
        render_quests = None

    clan = get_user_clan(user_id)
    quests = get_user_quests(user_id)

    # считаем reward_cut по правилу копилки
    for q in quests:
        q["reward_cut"] = clan_cut(q["reward"])

    # embed 1 — картинка шапки из clan/embeds/quests.json
    e1 = disnake.Embed(color=clan["color"] if clan else 6776679)
    data = load_json(os.path.join(EMBEDS_DIR, "quests.json"), {})
    for e in data.get("embeds", [])[:1]:
        try:
            e1 = disnake.Embed.from_dict(e)
        except Exception:
            pass

    # embed 2 — Pillow
    e2 = disnake.Embed(color=clan["color"] if clan else 6776679)
    file = None

    if render_quests is not None:
        try:
            buf = render_quests(user_id, quests)
            file = disnake.File(buf, filename=f"quests_{user_id}.png")
            e2.set_image(url=f"attachment://quests_{user_id}.png")
        except Exception as e:
            logger.warning(f"render_quests err: {e}")

    return [e1, e2], file


def format_quests_embed(user_id: int):
    """Обратная совместимость: возвращает только embeds."""
    embeds, _ = build_quests_embeds(user_id)
    return embeds


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
    if message.author.bot:
        return
    if not isinstance(message.channel, disnake.TextChannel):
        return
    user_id = message.author.id

    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return

    if message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        return
    if len((message.content or "").strip()) < CONFIG.get("MIN_MESSAGE_LENGTH", 3):
        return

    update_progress(user_id, "msg_50", delta=1)
    update_progress(user_id, "msg_1000", delta=1)


async def on_voice_quest_hook(user_id: int, seconds: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return
    if seconds <= 0:
        return
    update_progress(user_id, "voice_1h", delta=seconds)
    update_progress(user_id, "voice_10h", delta=seconds)


async def on_casino_quest_hook(user_id: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return
    update_progress(user_id, "casino_3", delta=1)
    update_progress(user_id, "casino_30", delta=1)


async def on_casino_win_hook(user_id: int, payout: int, bet: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return

    profit = max(payout - bet, 0)
    if profit > 0:
        update_progress(user_id, "win_3000", delta=profit)

    if profit >= 10000:
        update_progress(user_id, "jackpot", absolute=10000)


async def on_review_quest_hook(user_id: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return
    update_progress(user_id, "first_review", delta=1)


async def on_purchase_quest_hook(user_id: int, amount_dc: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return
    update_progress(user_id, "shop_buy", delta=1)
    update_progress(user_id, "shop_500", delta=amount_dc)


async def on_gift_quest_hook(sender_id: int, amount_dc: int):
    from clan.core import get_user_clan
    if not get_user_clan(sender_id):
        return
    update_progress(sender_id, "gift_500", delta=amount_dc)


async def on_panel_click_quest_hook(user_id: int):
    from clan.core import get_user_clan
    if not get_user_clan(user_id):
        return
    update_progress(user_id, "cmds_5", delta=1)
