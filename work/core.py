# -*- coding: utf-8 -*-
"""
Ядро инвайт-панели адвайтеров.
БД, генерация реферальных ссылок, подсчёт, начисление наград.
"""
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

import disnake
from disnake.ext import tasks

from core.utils import (
    CONFIG, logger, db, cur, log_discord,
)

# ============================================================
# КОНСТАНТЫ
# ============================================================
REF_INVITE_CHANNEL_ID = 1552700701128400979   # ← ЗАМЕНИ при необходимости

ADVERTISER_ROLE_ID = 1457964854441672806
REWARD_AMOUNT = 20
MIN_ALIVE_SECONDS = 12 * 3600
PANEL_CHANNEL_ID = 1557405478890373210

MSK = timezone(timedelta(hours=3))


# ============================================================
# ИНИЦИАЛИЗАЦИЯ ТАБЛИЦ
# ============================================================
def init_advertiser_tables():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS advertiser_links (
        advertiser_id INTEGER PRIMARY KEY,
        invite_code   TEXT UNIQUE,
        invite_url    TEXT,
        created_at    INTEGER,
        total_uses    INTEGER DEFAULT 0
    );
    """)
    db.commit()

    for col, ddl in [
        ("invite_code",   "invite_code TEXT DEFAULT NULL"),
        ("advertiser_id", "advertiser_id INTEGER DEFAULT NULL"),
        ("rewarded",      "rewarded INTEGER DEFAULT 0"),
    ]:
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(invites)").fetchall()]
            if col not in cols:
                cur.execute(f"ALTER TABLE invites ADD COLUMN {ddl}")
                db.commit()
                logger.info(f"Миграция invites.{col} добавлена")
        except Exception as e:
            logger.warning(f"Миграция invites.{col}: {e}")


# ============================================================
# РОЛЬ
# ============================================================
def has_advertiser_role(member) -> bool:
    if member is None:
        return False
    try:
        return any(r.id == ADVERTISER_ROLE_ID for r in member.roles)
    except Exception:
        return False


def reset_advertiser(advertiser_id: int):
    """
    Стирает всё у адвайтера: ссылку и привязки в invites.
    Вызывается при снятии роли ADVERTISER_ROLE_ID.
    """
    try:
        # Удаляем ссылку
        cur.execute("DELETE FROM advertiser_links WHERE advertiser_id=?", (advertiser_id,))

        # Отвязываем все инвайты — при возврате роли начнёт с нуля
        cur.execute(
            "UPDATE invites SET advertiser_id=NULL WHERE advertiser_id=?",
            (advertiser_id,)
        )
        db.commit()
        logger.info(f"🧹 Адвайтер {advertiser_id} сброшен (роль снята)")
    except Exception as e:
        logger.exception(f"reset_advertiser({advertiser_id}): {e}")


# ============================================================
# РЕФЕРАЛЬНЫЕ ССЫЛКИ
# ============================================================
def get_advertiser_link(advertiser_id: int) -> Optional[dict]:
    row = cur.execute(
        "SELECT * FROM advertiser_links WHERE advertiser_id=?",
        (advertiser_id,)
    ).fetchone()
    return dict(row) if row else None


async def ensure_advertiser_link(bot, advertiser_id: int) -> Optional[dict]:
    existing = get_advertiser_link(advertiser_id)
    if existing:
        return existing

    channel = bot.get_channel(REF_INVITE_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(REF_INVITE_CHANNEL_ID)
        except Exception as e:
            logger.error(f"ensure_advertiser_link: канал {REF_INVITE_CHANNEL_ID} не найден: {e}")
            return None

    if not isinstance(channel, disnake.TextChannel):
        logger.error(f"ensure_advertiser_link: канал {REF_INVITE_CHANNEL_ID} не текстовый")
        return None

    try:
        invite = await channel.create_invite(
            max_age=0,
            max_uses=0,
            unique=True,
            reason=f"ref:{advertiser_id}",
        )
    except Exception as e:
        logger.exception(f"ensure_advertiser_link create_invite: {e}")
        return None

    now = int(time.time())
    cur.execute(
        "INSERT OR REPLACE INTO advertiser_links "
        "(advertiser_id, invite_code, invite_url, created_at, total_uses) "
        "VALUES (?, ?, ?, ?, 0)",
        (advertiser_id, invite.code, invite.url, now)
    )
    db.commit()

    logger.info(f"📨 Реферальная ссылка создана: {advertiser_id} → {invite.url}")

    await log_discord(
        title="📨 Новая реферальная ссылка",
        description=(
            f"> **Адвайтер:** <@{advertiser_id}> (`{advertiser_id}`)\n"
            f"> **Ссылка:** `{invite.url}`\n"
            f"> **Код:** `{invite.code}`"
        ),
        color=0x6a9bd1,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return get_advertiser_link(advertiser_id)


def get_advertiser_by_code(invite_code: str) -> Optional[int]:
    if not invite_code:
        return None
    row = cur.execute(
        "SELECT advertiser_id FROM advertiser_links WHERE invite_code=?",
        (invite_code,)
    ).fetchone()
    return row["advertiser_id"] if row else None


# ============================================================
# ЗАПИСЬ СОБЫТИЙ
# ============================================================
def register_invite_leave(member_id: int, guild_id: int):
    try:
        cur.execute(
            "UPDATE invites SET left_at=? "
            "WHERE guild_id=? AND member_id=? AND left_at IS NULL",
            (int(time.time()), guild_id, member_id)
        )
        db.commit()
    except Exception as e:
        logger.warning(f"register_invite_leave: {e}")


# ============================================================
# ПОДСЧЁТ
# ============================================================
def is_valid(invite_row) -> bool:
    joined_at = invite_row["joined_at"] or 0
    left_at = invite_row["left_at"]
    now = int(time.time())
    if left_at:
        return (left_at - joined_at) >= MIN_ALIVE_SECONDS
    return (now - joined_at) >= MIN_ALIVE_SECONDS


def is_on_review(invite_row) -> bool:
    joined_at = invite_row["joined_at"] or 0
    left_at = invite_row["left_at"]
    if not left_at:
        return False
    return (left_at - joined_at) < MIN_ALIVE_SECONDS


def is_alive(invite_row) -> bool:
    return invite_row["left_at"] is None


def get_advertiser_stats(advertiser_id: int) -> dict:
    rows = cur.execute(
        "SELECT * FROM invites WHERE advertiser_id=? AND is_bot=0 AND is_fake=0 "
        "ORDER BY joined_at DESC",
        (advertiser_id,)
    ).fetchall()

    total = len(rows)
    rewarded = sum(1 for r in rows if r["rewarded"])
    on_review = sum(1 for r in rows if not r["rewarded"] and is_on_review(r))
    alive = sum(1 for r in rows if is_alive(r))

    return {
        "rows": [dict(r) for r in rows],
        "total": total,
        "rewarded": rewarded,
        "on_review": on_review,
        "alive": alive,
    }


def _resolve_username(guild, user_id: int) -> str:
    """Тянет display_name из гильдии. Иначе @id."""
    if guild is None:
        return f"@{user_id}"
    try:
        m = guild.get_member(user_id)
        if m is not None:
            return m.display_name
    except Exception:
        pass
    return f"@{user_id}"


def get_advertiser_top(guild, limit: int = 20) -> List[dict]:
    """
    Возвращает топ только по тем, у кого есть роль ADVERTISER_ROLE_ID.
    Пропускает тех, кто ушёл с сервера или потерял роль.
    """
    rows = cur.execute("SELECT advertiser_id FROM advertiser_links").fetchall()

    result = []
    for r in rows:
        aid = r["advertiser_id"]

        # Проверка роли
        if guild is not None:
            member = guild.get_member(aid)
            if member is None or not has_advertiser_role(member):
                continue

        stats = get_advertiser_stats(aid)
        result.append({
            "advertiser_id": aid,
            "username": _resolve_username(guild, aid),
            "rewarded": stats["rewarded"],
            "on_review": stats["on_review"],
            "total": stats["total"],
        })

    result.sort(key=lambda x: (-x["rewarded"], -x["on_review"], -x["total"]))
    return result[:limit]


def get_my_place_in_top(guild, advertiser_id: int) -> Optional[int]:
    top = get_advertiser_top(guild, limit=1000)
    for i, entry in enumerate(top, 1):
        if entry["advertiser_id"] == advertiser_id:
            return i
    return None


def get_reward_history(advertiser_id: int, limit: int = 15) -> List[dict]:
    rows = cur.execute(
        "SELECT * FROM invites WHERE advertiser_id=? AND rewarded=1 "
        "ORDER BY joined_at DESC LIMIT ?",
        (advertiser_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def get_total_rewarded_dc(advertiser_id: int) -> int:
    row = cur.execute(
        "SELECT COUNT(*) AS c FROM invites WHERE advertiser_id=? AND rewarded=1",
        (advertiser_id,)
    ).fetchone()
    return (row["c"] or 0) * REWARD_AMOUNT


def get_hold_dc(advertiser_id: int) -> int:
    stats = get_advertiser_stats(advertiser_id)
    return stats["on_review"] * REWARD_AMOUNT


# ============================================================
# НАЧИСЛЕНИЕ НАГРАД
# ============================================================
async def _pay_rewards(bot):
    now = int(time.time())
    threshold = now - MIN_ALIVE_SECONDS

    rows = cur.execute(
        "SELECT id, member_id, advertiser_id, joined_at, left_at FROM invites "
        "WHERE advertiser_id IS NOT NULL AND rewarded=0 AND is_bot=0 AND is_fake=0"
    ).fetchall()

    from modules.dc import add_dc

    paid = 0
    for r in rows:
        joined_at = r["joined_at"] or 0
        left_at = r["left_at"]

        eligible = False
        if left_at:
            if (left_at - joined_at) >= MIN_ALIVE_SECONDS:
                eligible = True
        else:
            if joined_at <= threshold:
                eligible = True

        if not eligible:
            continue

        aid = r["advertiser_id"]
        try:
            await add_dc(
                aid, REWARD_AMOUNT,
                f"Награда за приглашённого #{r['member_id']}",
                notify=True, log=False,
            )
            cur.execute("UPDATE invites SET rewarded=1 WHERE id=?", (r["id"],))
            db.commit()
            paid += 1

            await log_discord(
                title="💰 Награда адвайстеру",
                description=(
                    f"> **Адвайтер:** <@{aid}>\n"
                    f"> **Приглашённый:** <@{r['member_id']}>\n"
                    f"> **Сумма:** `+{REWARD_AMOUNT} DC`"
                ),
                color=0x2ecc71,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        except Exception as e:
            logger.warning(f"_pay_rewards {aid}: {e}")

    if paid:
        logger.info(f"💰 Награды: {paid} × {REWARD_AMOUNT} DC")


@tasks.loop(minutes=30)
async def reward_check_task(bot):
    await bot.wait_until_ready()
    try:
        await _pay_rewards(bot)
    except Exception as e:
        logger.exception(f"reward_check_task: {e}")


def start_advertiser_tasks(bot):
    if not reward_check_task.is_running():
        reward_check_task.start(bot)
