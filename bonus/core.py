# -*- coding: utf-8 -*-
"""
Ядро бонус-панели: акция дня, реферальная система (обычные + адвайтеры).
"""
import os
import json
import time
import random
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

import disnake
from disnake.ext import tasks

from core.utils import (
    CONFIG, DATA_DIR, CATALOG_DIR, ADD_DIR,
    logger, db, cur, load_json, save_json,
    log_discord, get_dc_cache, activate_item,
)
from modules.dc import add_dc, remove_dc, get_user_balance, add_purchase

# ============================================================
# КОНСТАНТЫ
# ============================================================
BONUS_CHANNEL_ID       = 1557590012667891774   # канал Бонусы
REF_INVITE_CHANNEL_ID  = 1552700701128400979   # канал для реф-ссылок
CLUB_ROLE_ID           = 1284697274655576186   # роль «Клуб»
ADVERTISER_ROLE_ID     = 1457964854441672806   # роль «Адвайтер»
SUPREME_USER_ID        = 796293832751972352    # доступ без роли

REF_MIN_ALIVE_SECONDS  = 3600                  # 1 час — порог зачёта
REF_REWARD_BALANCE     = 50                    # 50 DC юзеру за приглашённого
REF_COOLDOWN_MIN       = 15                    # таск каждые 15 мин

DEAL_PING_ROLE_ID      = 1127428607606796290   # пинг в анонсе акции
DEAL_SLOT_SECONDS      = 5 * 3600


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
def init_bonus_tables():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS user_ref_links (
        user_id     INTEGER PRIMARY KEY,
        invite_code TEXT UNIQUE,
        invite_url  TEXT,
        created_at  INTEGER
    );
    """)
    db.commit()

    for col, ddl in [
        ("ref_user_id", "ref_user_id INTEGER DEFAULT NULL"),
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
# РОЛИ И ДОСТУП
# ============================================================
def has_club_role(member) -> bool:
    if member is None:
        return False
    try:
        return any(r.id == CLUB_ROLE_ID for r in member.roles)
    except Exception:
        return False

def has_advertiser_role(member) -> bool:
    if member is None:
        return False
    try:
        return any(r.id == ADVERTISER_ROLE_ID for r in member.roles)
    except Exception:
        return False

def has_bonus_access(member) -> bool:
    if member is None:
        return False
    if member.id == SUPREME_USER_ID:
        return True
    return has_club_role(member) or has_advertiser_role(member)


# ============================================================
# РЕФ-ССЫЛКИ
# ============================================================
def get_user_ref_link(user_id: int) -> Optional[dict]:
    row = cur.execute(
        "SELECT * FROM user_ref_links WHERE user_id=?", (user_id,)
    ).fetchone()
    return dict(row) if row else None

def get_user_by_ref_code(code: str) -> Optional[int]:
    if not code:
        return None
    row = cur.execute(
        "SELECT user_id FROM user_ref_links WHERE invite_code=?", (code,)
    ).fetchone()
    return row["user_id"] if row else None

async def ensure_user_ref_link(bot, user_id: int) -> Optional[dict]:
    existing = get_user_ref_link(user_id)
    if existing:
        return existing

    channel = bot.get_channel(REF_INVITE_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(REF_INVITE_CHANNEL_ID)
        except Exception as e:
            logger.error(f"ensure_user_ref_link: канал {REF_INVITE_CHANNEL_ID} не найден: {e}")
            return None

    if not isinstance(channel, disnake.TextChannel):
        logger.error(f"ensure_user_ref_link: канал не текстовый")
        return None

    try:
        invite = await channel.create_invite(
            max_age=0, max_uses=0, unique=True,
            reason=f"user-ref:{user_id}",
        )
    except Exception as e:
        logger.exception(f"ensure_user_ref_link create_invite: {e}")
        return None

    now = int(time.time())
    cur.execute(
        "INSERT OR REPLACE INTO user_ref_links "
        "(user_id, invite_code, invite_url, created_at) "
        "VALUES (?, ?, ?, ?)",
        (user_id, invite.code, invite.url, now)
    )
    db.commit()

    logger.info(f"👥 Юзер-реф ссылка создана: {user_id} → {invite.url}")
    return get_user_ref_link(user_id)


# ============================================================
# ПОДСЧЁТ РЕФ-СТАТИСТИКИ
# ============================================================
def _is_alive(row) -> bool:
    return row["left_at"] is None

def _is_valid(row) -> bool:
    joined_at = row["joined_at"] or 0
    left_at = row["left_at"]
    now = int(time.time())
    if left_at:
        return (left_at - joined_at) >= REF_MIN_ALIVE_SECONDS
    return (now - joined_at) >= REF_MIN_ALIVE_SECONDS

def _is_on_review(row) -> bool:
    joined_at = row["joined_at"] or 0
    left_at = row["left_at"]
    if not left_at:
        return False
    return (left_at - joined_at) < REF_MIN_ALIVE_SECONDS

def get_user_ref_stats(user_id: int) -> dict:
    rows = cur.execute(
        "SELECT * FROM invites WHERE ref_user_id=? AND is_bot=0 AND is_fake=0 "
        "ORDER BY joined_at DESC",
        (user_id,)
    ).fetchall()

    total = len(rows)
    rewarded = sum(1 for r in rows if r["rewarded"])
    on_review = sum(1 for r in rows if not r["rewarded"] and _is_on_review(r))
    alive = sum(1 for r in rows if _is_alive(r))

    return {
        "rows": [dict(r) for r in rows],
        "total": total,
        "rewarded": rewarded,
        "on_review": on_review,
        "alive": alive,
        "earned": rewarded * REF_REWARD_BALANCE,
    }


# ============================================================
# ТОПЫ
# ============================================================
def get_top_referrals(is_advertiser: bool = False, limit: int = 10) -> List[dict]:
    """Возвращает топ по количеству засчитанных приглашений из таблицы invites."""
    rows = cur.execute("""
        SELECT ref_user_id, 
               COUNT(id) as total, 
               SUM(CASE WHEN rewarded=1 THEN 1 ELSE 0 END) as rewarded
        FROM invites 
        WHERE ref_user_id IS NOT NULL AND is_bot=0 AND is_fake=0
        GROUP BY ref_user_id
    """).fetchall()
    
    result = []
    guild = None
    try:
        from core.bot import bot
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    except Exception:
        pass

    for r in rows:
        uid = r["ref_user_id"]
        
        # Фильтруем по роли (если передан флаг)
        if guild:
            member = guild.get_member(uid)
            if is_advertiser and not has_advertiser_role(member):
                continue
            if not is_advertiser and has_advertiser_role(member):
                continue
                
        total = r["total"]
        if total > 0:
            rewarded = r["rewarded"]
            result.append({
                "user_id": uid,
                "username": _resolve_username(guild, uid),
                "rewarded": rewarded,
                "total": total,
                "earned": rewarded * REF_REWARD_BALANCE,
            })

    result.sort(key=lambda x: (-x["rewarded"], -x["total"]))
    return result[:limit]

def _resolve_username(guild, user_id: int) -> str:
    if guild is None:
        return f"@{user_id}"
    try:
        m = guild.get_member(user_id)
        if m is not None:
            return m.display_name
    except Exception:
        pass
    return f"@{user_id}"


# ============================================================
# НАЧИСЛЕНИЕ РЕФ-НАГРАД
# ============================================================
async def _pay_ref_rewards(bot):
    now = int(time.time())
    threshold = now - REF_MIN_ALIVE_SECONDS

    rows = cur.execute(
        "SELECT id, member_id, ref_user_id, joined_at, left_at FROM invites "
        "WHERE ref_user_id IS NOT NULL AND rewarded=0 AND is_bot=0 AND is_fake=0"
    ).fetchall()

    paid = 0
    for r in rows:
        joined_at = r["joined_at"] or 0
        left_at = r["left_at"]

        eligible = False
        if left_at:
            if (left_at - joined_at) >= REF_MIN_ALIVE_SECONDS:
                eligible = True
        else:
            if joined_at <= threshold:
                eligible = True

        if not eligible:
            continue

        uid = r["ref_user_id"]
        try:
            await add_dc(
                uid, REF_REWARD_BALANCE,
                f"Реф-награда за #{r['member_id']}",
                notify=True, log=False,
                to_clan_pool=False,
            )

            try:
                from clan.core import add_clan_contribution
                await add_clan_contribution(uid, REF_REWARD_BALANCE, f"Реф: {r['member_id']}")
            except Exception as e:
                logger.warning(f"ref clan contribution: {e}")

            cur.execute("UPDATE invites SET rewarded=1 WHERE id=?", (r["id"],))
            db.commit()
            paid += 1

            await log_discord(
                title="👥 Реф-награда",
                description=(
                    f"> **Юзер:** <@{uid}>\n"
                    f"> **Приглашённый:** <@{r['member_id']}>\n"
                    f"> **Баланс:** `+{REF_REWARD_BALANCE} DC`\n"
                    f"> **В копилку:** `+{REF_REWARD_BALANCE} DC`"
                ),
                color=0x2ecc71,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        except Exception as e:
            logger.warning(f"_pay_ref_rewards {uid}: {e}")

    if paid:
        logger.info(f"👥 Реф-награды: {paid} × {REF_REWARD_BALANCE} DC")


@tasks.loop(minutes=REF_COOLDOWN_MIN)
async def ref_reward_task(bot):
    await bot.wait_until_ready()
    try:
        await _pay_ref_rewards(bot)
    except Exception as e:
        logger.exception(f"ref_reward_task: {e}")


# ============================================================
# АНОНС АКЦИИ ДНЯ
# ============================================================
DEAL_ANNOUNCE_STATE = os.path.join(DATA_DIR, "bonus_deal_announce.json")

DEAL_ANNOUNCE_IMG = (
    "https://cdn.discordapp.com/attachments/1527006158282555412/"
    "1537851307757539390/image.png?ex=6ac864e3&is=6ac71363&"
    "hm=8fc2a4970e9d4a67c7031812597700fbd32286d0919ee5aa1a460ec0a5316ad6&"
)

def _load_announce_state() -> dict:
    return load_json(DEAL_ANNOUNCE_STATE, {"slot": 0, "message_id": 0})

def _save_announce_state(state: dict):
    save_json(DEAL_ANNOUNCE_STATE, state)

async def announce_deal_change(bot, deal: dict):
    state = _load_announce_state()
    slot = int(time.time() // DEAL_SLOT_SECONDS)

    if state.get("slot") == slot:
        return

    ch = bot.get_channel(BONUS_CHANNEL_ID)
    if not ch:
        try:
            ch = await bot.fetch_channel(BONUS_CHANNEL_ID)
        except Exception as e:
            logger.warning(f"announce_deal_change channel: {e}")
            return

    old_id = state.get("message_id")
    if old_id:
        try:
            old = await ch.fetch_message(old_id)
            await old.delete()
        except Exception:
            pass

    if not deal:
        state["slot"] = slot
        state["message_id"] = 0
        _save_announce_state(state)
        logger.info(f"🔥 Анонс акции: слот {slot} — товара нет")
        return

    item = deal.get("item_data", {})
    name = item.get("name", "—")

    embed = disnake.Embed(
        title="Новая скидка на товар!",
        description=(
            f"> Сейчас проходит ссылка на товар - **{name}**.\n"
            f"> Хочешь узнать о скидке больше? Выбери в панели - **Акция дня**.\n\n"
            f"`Следующее обновление акции через 5ч`"
        ),
        color=6776679,
    )
    embed.set_image(url=DEAL_ANNOUNCE_IMG)

    try:
        msg = await ch.send(
            content=f"|| <@&{DEAL_PING_ROLE_ID}> ||",
            embed=embed,
            allowed_mentions=disnake.AllowedMentions(roles=True),
        )
    except Exception as e:
        logger.warning(f"announce_deal_change send: {e}")
        return

    state["slot"] = slot
    state["message_id"] = msg.id
    _save_announce_state(state)
    logger.info(f"🔥 Анонс акции: {name} · слот {slot}")


# ============================================================
# ЗАПУСК ТАСКОВ
# ============================================================
def start_bonus_tasks(bot):
    if not ref_reward_task.is_running():
        ref_reward_task.start(bot)
