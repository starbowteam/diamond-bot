# -*- coding: utf-8 -*-
"""Ядро клановой лиги: БД, налог, вход, распределение, выплата, отчёт."""
import os
import time
import math
import asyncio
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple

import disnake

from core.utils import (
    CONFIG, DATA_DIR, ADD_DIR, FILES, logger, db, cur,
    load_json, save_json, log_discord, now_ts,
    get_dc_cache, save_dc_cache, update_user_roles,
)

# ============================================================
# КОНСТАНТЫ ЛИГИ
# ============================================================
MSK = timezone(timedelta(hours=3))

CLUB_ROLE_ID    = 1284697274655576186

# 👇 Минимальный баланс DC для входа В КЛАН (Окаменелости / Сияние /
# Кристализация). Меньше 50 DC — клан не даётся.
# Роль «Клуб» тут НИ ПРИ ЧЁМ: это обычная роль покупателя за отзыв.
MIN_BALANCE     = 50

# ============================================================
# 🔒 ЖЁСТКОЕ ИСКЛЮЧЕНИЕ
# ============================================================
HARD_EXCLUDED_USERS = {
    1124040555240898631,
    796293832751972352,
}

EXCLUDE_FROM_CLAN = HARD_EXCLUDED_USERS

CLAN_CYCLE_DAYS = 28
PAYOUT_DAY      = 28
PAYOUT_HOUR_MSK = 20
PAYOUT_MINUTE   = 0

# ============================================================
# 👇 ПРАВИЛО КОПИЛКИ КЛАНА
# ============================================================
# Пользователь ВСЕГДА получает 100% начисления — вклад в копилку
# идёт СВЕРХУ и никогда не списывается с его баланса.
#
# В копилку клана уходит:
#   · начисление до 100 DC включительно — вся сумма (100%)
#   · начисление больше 100 DC          — 40% от суммы
CLAN_POOL_THRESHOLD = 100
CLAN_POOL_SMALL     = 1.00
CLAN_POOL_BIG       = 0.40


def clan_cut(amount: int) -> int:
    """
    Сколько DC уходит в копилку клана с начисления `amount`.

    До 100 DC включительно — вся сумма.
    Больше 100 DC — 40%.
    Нулевые и отрицательные начисления в копилку ничего не дают.
    """
    if amount <= 0:
        return 0
    if amount <= CLAN_POOL_THRESHOLD:
        return int(amount * CLAN_POOL_SMALL)
    return int(amount * CLAN_POOL_BIG)

# 👇 Бонусы топ-3 по вкладу (было 1.75 / 1.50 / 1.30)
TOP_BONUSES = [3.00, 2.00, 1.50]

# ============================================================
# 👇 ПРАВИЛО ВЫПЛАТЫ ПО ИТОГАМ СЕЗОНА
# ============================================================
# Кто за сезон внёс в копилку меньше MIN_CONTRIB_FOR_PAYOUT DC —
# выплату НЕ получает вообще. Банк делится только между теми,
# кто внёс достаточно. Каждому в ЛС уходит причина.
MIN_CONTRIB_FOR_PAYOUT = 50

REPORT_DM_USER_ID = 796293832751972352

# ============================================================
# 👇 ЛИМИТ ВКЛАДА В БАНК — 1000 DC/СУТКИ
# ============================================================
DAILY_CLAN_LIMIT = 1000

IMG_STRIPE = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
              "1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&"
              "hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&")

EMBEDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embeds")


# ============================================================
# 🏷 НАЗВАНИЯ СЕЗОНОВ
# ============================================================
SEASON_NAMES = {
    1: "Начало",
    2: "Стихия проклятья",
    3: "Неутопание кристалла",
    4: "Сияние богачей",
    5: "Кристализация магазина",
    6: "Предновогодний дроп",
    7: "27 Карат",
    8: "Февральская потеха",
    9: "Магнитуда сияния",
}


def get_season_name(number: int) -> str:
    if number in SEASON_NAMES:
        return SEASON_NAMES[number]
    return f"Сезон #{number}"


def get_season_title(number: int) -> str:
    if number in SEASON_NAMES:
        return f"Сезон {number} — {SEASON_NAMES[number]}"
    return f"Сезон #{number}"


# ============================================================
# КЛАНЫ
# ============================================================
CLANS_DATA = [
    {
        "id": 1,
        "name": "Окаменелости",
        "emoji": "🪨",
        "role_id": 1552707675257831525,
        "color": 0xb3e1b9,
        "color_dark": 0x749472,
        "fa_icon": "fa-gem",
        "description": "Стойкие, как камень. Непоколебимая воля и вековая мудрость.",
    },
    {
        "id": 2,
        "name": "Сияние",
        "emoji": "✨",
        "role_id": 1552707025723465838,
        "color": 0xaa8ae7,
        "color_dark": 0x582189,
        "fa_icon": "fa-star",
        "description": "Свет звёзд в ночи. Яркие, амбициозные, недосягаемые.",
    },
    {
        "id": 3,
        "name": "Кристализация",
        "emoji": "💎",
        "role_id": 1551280425312194650,
        "color": 0x8799ae,
        "color_dark": 0xf1f7ff,
        "fa_icon": "fa-gem",
        "description": "Чистота формы и холодный расчёт. Всё по полочкам.",
    },
]


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
def init_clan_core():
    for c in CLANS_DATA:
        cur.execute(
            "INSERT OR IGNORE INTO clans (id, name, emoji, role_id, color, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (c["id"], c["name"], c["emoji"], c["role_id"], c["color"], c["description"])
        )
    # Создаём таблицу дневного лимита
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clan_daily_limit (
            user_id  INTEGER,
            date     TEXT,
            amount   INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date)
        )
    """)
    db.commit()
    cleanup_excluded_users()


def cleanup_excluded_users() -> dict:
    """Жёстко вычищает исключённых."""
    if not HARD_EXCLUDED_USERS:
        return {}

    report = {}

    for uid in HARD_EXCLUDED_USERS:
        contrib_rows = cur.execute(
            "SELECT cycle_id, clan_id, amount FROM clan_contributions WHERE user_id=?",
            (uid,)
        ).fetchall()

        if contrib_rows:
            total = sum(r["amount"] for r in contrib_rows)
            count = len(contrib_rows)
            cycles = sorted(set(r["cycle_id"] for r in contrib_rows))
            clans = sorted(set(r["clan_id"] for r in contrib_rows))
            report[uid] = {
                "sum": total,
                "count": count,
                "cycles": cycles,
                "clans": clans,
            }

        cur.execute("DELETE FROM clan_contributions WHERE user_id=?", (uid,))
        cur.execute("DELETE FROM clan_payouts WHERE user_id=?", (uid,))
        cur.execute(
            "UPDATE clan_members SET left_at=? WHERE user_id=? AND left_at IS NULL",
            (int(time.time()), uid)
        )

    db.commit()

    for uid, data in report.items():
        clan_names = []
        for cid in data["clans"]:
            c = get_clan(cid)
            if c:
                clan_names.append(f"{c['emoji']} {c['name']}")
        logger.warning(
            f"🧹 Cleanup user {uid}: удалено вкладов на {data['sum']} DC "
            f"({data['count']} шт.) из кланов: {', '.join(clan_names) or '—'}"
        )

    return report


def is_hard_excluded(user_id: int) -> bool:
    return user_id in HARD_EXCLUDED_USERS


def cleanup_specific_user(user_id: int) -> dict:
    """Очищает одного юзера."""
    contrib_rows = cur.execute(
        "SELECT cycle_id, clan_id, amount, reason, ts FROM clan_contributions WHERE user_id=?",
        (user_id,)
    ).fetchall()

    total = sum(r["amount"] for r in contrib_rows) if contrib_rows else 0
    count = len(contrib_rows)

    by_clan = {}
    by_cycle = {}
    for r in contrib_rows:
        by_clan[r["clan_id"]] = by_clan.get(r["clan_id"], 0) + r["amount"]
        by_cycle[r["cycle_id"]] = by_cycle.get(r["cycle_id"], 0) + r["amount"]

    cur.execute("DELETE FROM clan_contributions WHERE user_id=?", (user_id,))
    cur.execute("DELETE FROM clan_payouts WHERE user_id=?", (user_id,))
    cur.execute(
        "UPDATE clan_members SET left_at=? WHERE user_id=? AND left_at IS NULL",
        (int(time.time()), user_id)
    )
    db.commit()

    clan_stats = []
    for cid, amount in by_clan.items():
        c = get_clan(cid)
        if c:
            clan_stats.append({
                "clan": f"{c['emoji']} {c['name']}",
                "amount": amount,
            })

    cycle_stats = []
    for cyc_id, amount in by_cycle.items():
        cycle_row = cur.execute("SELECT number FROM clan_cycle WHERE id=?", (cyc_id,)).fetchone()
        cycle_num = cycle_row["number"] if cycle_row else "?"
        cycle_stats.append({
            "cycle": f"Сезон #{cycle_num}",
            "amount": amount,
        })

    return {
        "user_id": user_id,
        "total": total,
        "count": count,
        "by_clan": clan_stats,
        "by_cycle": cycle_stats,
    }


# ============================================================
# ДНЕВНОЙ ЛИМИТ ВКЛАДА
# ============================================================
def _get_today_str() -> str:
    """YYYY-MM-DD по МСК."""
    return datetime.now(MSK).strftime("%Y-%m-%d")


def _get_daily_contributed(user_id: int) -> int:
    """Сколько юзер уже внёс сегодня."""
    row = cur.execute(
        "SELECT amount FROM clan_daily_limit WHERE user_id=? AND date=?",
        (user_id, _get_today_str())
    ).fetchone()
    return row["amount"] if row else 0


def _add_daily_contributed(user_id: int, amount: int):
    """Увеличивает счётчик дня."""
    today = _get_today_str()
    cur.execute("""
        INSERT INTO clan_daily_limit (user_id, date, amount)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET amount = amount + ?
    """, (user_id, today, amount, amount))
    db.commit()


def get_remaining_daily_limit(user_id: int) -> int:
    """Остаток лимита на сегодня."""
    already = _get_daily_contributed(user_id)
    return max(DAILY_CLAN_LIMIT - already, 0)


# ============================================================
# КЛАНЫ — доступ
# ============================================================
def get_clan(clan_id: int) -> Optional[dict]:
    row = cur.execute("SELECT * FROM clans WHERE id=?", (clan_id,)).fetchone()
    return dict(row) if row else None


def get_clan_by_role(role_id: int) -> Optional[dict]:
    row = cur.execute("SELECT * FROM clans WHERE role_id=?", (role_id,)).fetchone()
    return dict(row) if row else None


def get_all_clans() -> List[dict]:
    rows = cur.execute("SELECT * FROM clans ORDER BY id").fetchall()
    return [dict(r) for r in rows]


# ============================================================
# СОСТАВ КЛАНА
# ============================================================
def get_user_clan(user_id: int) -> Optional[dict]:
    if is_hard_excluded(user_id):
        return None

    row = cur.execute(
        "SELECT clan_id FROM clan_members WHERE user_id=? AND left_at IS NULL",
        (user_id,)
    ).fetchone()
    if not row:
        return None
    return get_clan(row["clan_id"])


def is_club_member(guild: disnake.Guild, user_id: int) -> bool:
    member = guild.get_member(user_id)
    if not member:
        return False
    return any(r.id == CLUB_ROLE_ID for r in member.roles)


def _get_clan_stats() -> List[Tuple[dict, int, int]]:
    result = []
    for c in get_all_clans():
        members = cur.execute(
            "SELECT user_id FROM clan_members WHERE clan_id=? AND left_at IS NULL",
            (c["id"],)
        ).fetchall()
        filtered = [m for m in members if not is_hard_excluded(m["user_id"])]
        count = len(filtered)
        total_bal = 0
        for m in filtered:
            b = cur.execute("SELECT balance FROM dc_cache WHERE user_id=?", (m["user_id"],)).fetchone()
            if b:
                total_bal += b["balance"]
        result.append((c, count, total_bal))
    return result


def assign_user_to_clan(user_id: int, guild: disnake.Guild) -> Optional[dict]:
    if is_hard_excluded(user_id):
        return None

    if get_user_clan(user_id):
        return None

    member = guild.get_member(user_id)
    if not member:
        return None

    if not any(r.id == CLUB_ROLE_ID for r in member.roles):
        return None

    row = cur.execute("SELECT balance FROM dc_cache WHERE user_id=?", (user_id,)).fetchone()
    balance = row["balance"] if row else 0
    if balance < MIN_BALANCE:
        return None

    stats = _get_clan_stats()
    stats.sort(key=lambda x: (x[1], x[2]))
    target_clan = stats[0][0]

    cycle = get_current_cycle()
    cycle_id = cycle["id"] if cycle else 0

    cur.execute(
        "INSERT OR REPLACE INTO clan_members (user_id, clan_id, joined_at, left_at, cycle_joined) "
        "VALUES (?, ?, ?, NULL, ?)",
        (user_id, target_clan["id"], int(time.time()), cycle_id)
    )
    db.commit()

    role = guild.get_role(target_clan["role_id"])
    if role and role not in member.roles:
        try:
            asyncio.create_task(member.add_roles(role, reason="Клановая лига: автораскид"))
        except Exception as e:
            logger.warning(f"assign role {role.id}: {e}")

    asyncio.create_task(send_welcome_dm(member, target_clan))

    asyncio.create_task(log_discord(
        title=f"{target_clan['emoji']} Новый участник клана",
        description=(
            f"> **Клан:** {target_clan['emoji']} **{target_clan['name']}**\n"
            f"> **Участник:** {member.mention} (`{member.id}`)"
        ),
        color=target_clan["color"],
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    ))

    return target_clan


def distribute_all_club_members(guild: disnake.Guild) -> Dict[str, int]:
    assigned = 0
    skipped = 0
    excluded = 0

    cleanup_excluded_users()

    for member in guild.members:
        if member.bot:
            continue
        if not any(r.id == CLUB_ROLE_ID for r in member.roles):
            continue
        if is_hard_excluded(member.id):
            excluded += 1
            continue
        if get_user_clan(member.id):
            skipped += 1
            continue
        result = assign_user_to_clan(member.id, guild)
        if result:
            assigned += 1

    max_iter = 500
    while max_iter > 0:
        max_iter -= 1
        stats = _get_clan_stats()
        stats.sort(key=lambda x: x[1])
        smallest = stats[0]
        largest = stats[-1]
        diff = largest[1] - smallest[1]
        if diff <= 1:
            break

        members_big = cur.execute(
            "SELECT user_id FROM clan_members WHERE clan_id=? AND left_at IS NULL "
            "ORDER BY joined_at DESC LIMIT 1",
            (largest[0]["id"],)
        ).fetchone()
        if not members_big:
            break
        moved_uid = members_big["user_id"]

        if is_hard_excluded(moved_uid):
            break

        cur.execute(
            "UPDATE clan_members SET clan_id=? WHERE user_id=?",
            (smallest[0]["id"], moved_uid)
        )
        db.commit()

        moved_member = guild.get_member(moved_uid)
        if moved_member:
            for c in get_all_clans():
                r = guild.get_role(c["role_id"])
                if r and r in moved_member.roles:
                    try:
                        asyncio.create_task(moved_member.remove_roles(r, reason="Клан-лига: ребаланс"))
                    except Exception:
                        pass
            new_role = guild.get_role(smallest[0]["role_id"])
            if new_role:
                try:
                    asyncio.create_task(moved_member.add_roles(new_role, reason="Клан-лига: ребаланс"))
                except Exception:
                    pass

        assigned += 1

    logger.info(f"Распределение кланов: assigned={assigned}, skipped={skipped}, excluded={excluded}")
    return {"assigned": assigned, "skipped": skipped, "excluded": excluded}


# ============================================================
# 👇 АВТООЧИСТКА КЛАНА
# ============================================================
# Исключаем ТОЛЬКО если выполнены ОБА условия:
#   1. месяц без действий (ни сообщений, ни покупок, ни игр, ни квестов)
#   2. баланс меньше INACTIVE_MAX_BALANCE DC
# Кто сидит молча, но с деньгами — остаётся в клане.
# Вклад при исключении остаётся в банке клана.
INACTIVE_DAYS_LIMIT  = 30   # месяц
INACTIVE_MAX_BALANCE = 50   # порог баланса: меньше — кандидат на выход


async def cleanup_inactive_clan_members(
    guild: disnake.Guild,
    days: int = INACTIVE_DAYS_LIMIT,
    max_balance: int = INACTIVE_MAX_BALANCE,
) -> dict:
    """
    Убирает из клана мёртвые аккаунты.

    Условия исключения (оба сразу):
      · нет действий `days` дней (сообщения, голос, покупки, ставки, квесты)
      · баланс меньше `max_balance` DC

    Роль клана снимается, вклад остаётся в банке (left_at).

    Защита от массового вылета: если отметки активности ещё нет
    (первый прогон после обновления) — ставим её на сейчас и не трогаем юзера.
    """
    now = int(time.time())
    threshold = now - days * 86400

    checked = 0
    removed = []
    seeded = 0
    kept_rich = 0

    for c in get_all_clans():
        rows = cur.execute(
            "SELECT user_id, joined_at FROM clan_members WHERE clan_id=? AND left_at IS NULL",
            (c["id"],)
        ).fetchall()

        for r in rows:
            uid = r["user_id"]
            if is_hard_excluded(uid):
                continue

            checked += 1

            row = cur.execute(
                "SELECT user_id, last_active_ts, balance FROM dc_cache WHERE user_id=?",
                (uid,)
            ).fetchone()

            last_active = (row["last_active_ts"] or 0) if row else 0
            balance = (row["balance"] or 0) if row else 0

            # 👇 Первый прогон: отметки ещё нет — даём отсчёт с этого момента,
            # чтобы разом не вычистить весь клан.
            if last_active <= 0:
                d = get_dc_cache(uid)
                d["last_active_ts"] = now
                save_dc_cache(uid, d)
                seeded += 1
                continue

            # Ещё активен — оставляем
            if last_active >= threshold:
                continue

            # 👇 Молчит месяц, но с деньгами — НЕ трогаем
            if balance >= max_balance:
                kept_rich += 1
                continue

            cur.execute(
                "UPDATE clan_members SET left_at=? WHERE user_id=? AND left_at IS NULL",
                (now, uid)
            )
            db.commit()

            member = guild.get_member(uid)
            role = guild.get_role(c["role_id"])
            if role and member and role in member.roles:
                try:
                    await member.remove_roles(role, reason=f"Клан-лига: нет активности {days} дней")
                except Exception as e:
                    logger.warning(f"cleanup_inactive remove role {uid}: {e}")

            days_afk = max((now - last_active) // 86400, 1)
            removed.append({
                "user_id": uid,
                "clan": c["name"],
                "days": days_afk,
                "balance": balance,
            })

            asyncio.create_task(log_discord(
                title="🧹 Исключён из клана (неактивность)",
                description=(
                    f"> **Участник:** <@{uid}> (`{uid}`)\n"
                    f"> **Клан:** {c['emoji']} **{c['name']}**\n"
                    f"> **Без действий:** `{days_afk}` дн.\n"
                    f"> **Баланс:** `{balance} DC`\n"
                    f"> Вклад остаётся в банке клана."
                ),
                color=0xff6600,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            ))

            await asyncio.sleep(0.3)

    if seeded:
        logger.info(f"Автоочистка клана: {seeded} юзерам проставлен старт отсчёта активности")

    logger.info(
        f"Автоочистка клана: проверено {checked}, исключено {len(removed)}, "
        f"оставлено с балансом >= {max_balance} DC: {kept_rich} (порог {days} дн.)"
    )

    return {
        "checked": checked,
        "removed": len(removed),
        "seeded": seeded,
        "kept_rich": kept_rich,
        "users": removed,
    }


# ============================================================
# 👇 ПОЛНЫЙ ПЕРЕСЧЁТ КЛАНОВ (кнопка в панели)
# ============================================================
# Снимать ли клан у тех, у кого баланс ниже MIN_BALANCE.
# Поставь False — тогда пересчёт только ВЫДАЁТ кланы, но не забирает.
CLAN_RECALC_REVOKE_LOW_BALANCE = True


async def remove_low_balance_clan_members(guild: disnake.Guild) -> dict:
    """
    Снимает клан (членство + роль) у тех, у кого баланс меньше MIN_BALANCE.
    Вклад при этом остаётся в банке клана.
    """
    removed = []
    checked = 0

    for c in get_all_clans():
        rows = cur.execute(
            "SELECT user_id FROM clan_members WHERE clan_id=? AND left_at IS NULL",
            (c["id"],)
        ).fetchall()

        for r in rows:
            uid = r["user_id"]
            if is_hard_excluded(uid):
                continue
            checked += 1

            row = cur.execute(
                "SELECT balance FROM dc_cache WHERE user_id=?", (uid,)
            ).fetchone()
            balance = (row["balance"] or 0) if row else 0

            if balance >= MIN_BALANCE:
                continue

            cur.execute(
                "UPDATE clan_members SET left_at=? WHERE user_id=? AND left_at IS NULL",
                (int(time.time()), uid)
            )
            db.commit()

            member = guild.get_member(uid)
            role = guild.get_role(c["role_id"])
            if role and member and role in member.roles:
                try:
                    await member.remove_roles(
                        role, reason=f"Клан-лига: баланс меньше {MIN_BALANCE} DC"
                    )
                except Exception as e:
                    logger.warning(f"remove_low_balance role {uid}: {e}")

            removed.append({"user_id": uid, "clan": c["name"], "balance": balance})

            asyncio.create_task(log_discord(
                title="🚪 Снят клан (мало DC)",
                description=(
                    f"> **Участник:** <@{uid}> (`{uid}`)\n"
                    f"> **Клан:** {c['emoji']} **{c['name']}**\n"
                    f"> **Баланс:** `{balance} DC` (нужно минимум {MIN_BALANCE})\n"
                    f"> Вклад остаётся в банке клана."
                ),
                color=0xff6600,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            ))

            await asyncio.sleep(0.2)

    logger.info(
        f"Снятие кланов за низкий баланс: проверено {checked}, снято {len(removed)}"
    )
    return {"checked": checked, "removed": len(removed), "users": removed}


async def recalculate_clan_league(guild: disnake.Guild) -> dict:
    """
    Полный пересчёт клановой лиги — то, что делает кнопка в панели.

      1. Роли покупателей по отзывам. Роль «Клуб» — просто за отзыв,
         никаких условий по балансу (это базовая роль покупателя).
      2. Снять клан у тех, у кого баланс меньше MIN_BALANCE.
      3. Раскидать по кланам тех, кто имеет право, но остался без клана.
    """
    counts = load_json(FILES["review_counts"], {}) or {}

    stats = {
        "roles_checked": 0,          # кому пересчитали роли (есть отзыв)
        "roles_errors": 0,
        "low_balance_removed": 0,    # снят клан за низкий баланс
        "members_checked": 0,        # всего проверено участников кланов
        "assigned": 0,               # выдано кланов
        "skipped": 0,                # уже были в клане
        "excluded": 0,               # жёсткие исключения
    }

    # ---- 1) Роли покупателей по отзывам ----
    for member in guild.members:
        if member.bot:
            continue
        cnt = int(counts.get(str(member.id), 0) or 0)
        if cnt <= 0:
            continue
        try:
            await update_user_roles(member, cnt, keep_pka=True)
            stats["roles_checked"] += 1
        except Exception as e:
            stats["roles_errors"] += 1
            logger.warning(f"recalculate_clan_league roles {member.id}: {e}")
        await asyncio.sleep(0.15)

    # ---- 2) Снять клан у тех, кто не дотягивает по балансу ----
    if CLAN_RECALC_REVOKE_LOW_BALANCE:
        low = await remove_low_balance_clan_members(guild)
        stats["low_balance_removed"] = low["removed"]
        stats["members_checked"] = low["checked"]

    # ---- 3) Раскидать по кланам ----
    dist = distribute_all_club_members(guild)
    stats["assigned"] = dist["assigned"]
    stats["skipped"] = dist["skipped"]
    stats["excluded"] = dist.get("excluded", 0)

    logger.info(f"Пересчёт клановой лиги: {stats}")
    return stats


# ============================================================
# ЦИКЛ
# ============================================================
def get_current_cycle() -> Optional[dict]:
    row = cur.execute(
        "SELECT * FROM clan_cycle WHERE state='active' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def get_any_last_cycle() -> Optional[dict]:
    row = cur.execute("SELECT * FROM clan_cycle ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def _msk_now() -> datetime:
    return datetime.now(MSK)


def _next_payout_ts(from_dt: Optional[datetime] = None) -> int:
    now = from_dt or _msk_now()
    target = now.replace(day=PAYOUT_DAY, hour=PAYOUT_HOUR_MSK, minute=PAYOUT_MINUTE,
                         second=0, microsecond=0)
    if target <= now:
        if now.month == 12:
            target = target.replace(year=now.year + 1, month=1)
        else:
            target = target.replace(month=now.month + 1)
    return int(target.timestamp())


def start_new_cycle(force_short: bool = False) -> dict:
    now_ts_val = int(time.time())
    ends_at = _next_payout_ts()

    last = get_any_last_cycle()
    number = (last["number"] + 1) if last else 1

    cur.execute(
        "INSERT INTO clan_cycle (number, started_at, ends_at, state) "
        "VALUES (?, ?, ?, 'active')",
        (number, now_ts_val, ends_at)
    )
    db.commit()

    cycle = get_current_cycle()
    logger.info(f"Клан-лига: старт {get_season_title(number)} до {datetime.fromtimestamp(ends_at, MSK)}")
    return cycle


def close_cycle_and_pay(bot) -> bool:
    cycle = get_current_cycle()
    if not cycle:
        return False

    cleanup_excluded_users()

    cur.execute("UPDATE clan_cycle SET state='payout' WHERE id=?", (cycle["id"],))
    db.commit()

    cycle_id = cycle["id"]
    all_clans = get_all_clans()

    report = {"cycle": cycle, "clans": [], "total": 0, "payouts": []}
    payouts_dm = report["payouts"]   # 👈 сюда собираем данные для личных ЛС
    total_paid = 0

    for c in all_clans:
        bank_row = cur.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions WHERE cycle_id=? AND clan_id=?",
            (cycle_id, c["id"])
        ).fetchone()
        bank = bank_row["s"] or 0

        members = cur.execute(
            "SELECT user_id, joined_at FROM clan_members WHERE clan_id=? AND left_at IS NULL",
            (c["id"],)
        ).fetchall()

        members = [m for m in members if not is_hard_excluded(m["user_id"])]

        if not members or bank <= 0:
            report["clans"].append({
                "clan": c, "bank": bank, "members": len(members),
                "top": [], "paid": 0
            })
            continue

        cycle_len_sec = max(cycle["ends_at"] - cycle["started_at"], 1)
        members_list = []
        for m in members:
            user_id = m["user_id"]
            joined_at = m["joined_at"]

            contrib_row = cur.execute(
                "SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions "
                "WHERE cycle_id=? AND user_id=?",
                (cycle_id, user_id)
            ).fetchone()
            contrib = contrib_row["s"] or 0

            days_inside = max(cycle["ends_at"] - max(joined_at, cycle["started_at"]), 0)
            weight = days_inside / cycle_len_sec

            members_list.append({
                "user_id": user_id,
                "contrib": contrib,
                "weight": weight,
            })

        sorted_members = sorted(members_list, key=lambda x: -x["contrib"])
        top_ids = [m["user_id"] for m in sorted_members[:3]]

        for m in members_list:
            # 👇 Право на выплату: вклад не меньше MIN_CONTRIB_FOR_PAYOUT
            m["eligible"] = m["contrib"] >= MIN_CONTRIB_FOR_PAYOUT

            if m["user_id"] in top_ids and m["eligible"]:
                idx = top_ids.index(m["user_id"])
                m["bonus"] = TOP_BONUSES[idx]
                m["place"] = idx + 1
            else:
                m["bonus"] = 1.0
                m["place"] = None

            # Не прошёл по вкладу — в делении не участвует
            m["eff"] = (m["weight"] * m["bonus"]) if m["eligible"] else 0.0

        total_eff = sum(m["eff"] for m in members_list)

        clan_paid = 0
        top_report = []
        for m in members_list:
            if m["eligible"] and total_eff > 0:
                payout = math.floor(bank * m["eff"] / total_eff)
            else:
                payout = 0
            m["payout"] = payout
            clan_paid += payout

            # 👇 Причина для ЛС: получил или нет
            if payout > 0:
                m["reason"] = None
            elif not m["eligible"]:
                m["reason"] = f"вклад в копилку меньше {MIN_CONTRIB_FOR_PAYOUT} DC"
            elif bank <= 0:
                m["reason"] = "банк клана пуст"
            else:
                m["reason"] = "доля вышла меньше 1 DC"

            if payout > 0:
                try:
                    from modules.dc import add_dc
                    # notify=False: причину и сумму сообщим своим красивым ЛС
                    bot.loop.create_task(add_dc(
                        m["user_id"], payout,
                        f"Клановая лига: выплата за {get_season_title(cycle['number'])}",
                        notify=False, log=False, clan_share=0.0
                    ))
                except Exception as e:
                    logger.exception(f"clan payout add_dc {m['user_id']}: {e}")

                cur.execute(
                    "INSERT INTO clan_payouts (cycle_id, clan_id, user_id, weight, bonus_mult, final_amount, paid_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (cycle_id, c["id"], m["user_id"], m["weight"], m["bonus"], payout, int(time.time()))
                )

            if m["place"]:
                top_report.append({
                    "user_id": m["user_id"],
                    "place": m["place"],
                    "contrib": m["contrib"],
                    "bonus": m["bonus"],
                    "payout": payout,
                })

            # 👇 Данные для личного ЛС каждому участнику
            payouts_dm.append({
                "user_id": m["user_id"],
                "clan_name": c["name"],
                "clan_emoji": c["emoji"],
                "clan_color": c["color"],
                "season": get_season_title(cycle["number"]),
                "contrib": m["contrib"],
                "place": m["place"],
                "bonus": m["bonus"],
                "payout": payout,
                "reason": m["reason"],
                "bank": bank,
                "eligible": m["eligible"],
            })

        db.commit()
        total_paid += clan_paid

        report["clans"].append({
            "clan": c,
            "bank": bank,
            "members": len(members_list),
            "top": top_report,
            "paid": clan_paid,
            "not_eligible": sum(1 for m in members_list if not m["eligible"]),
        })

    report["total"] = total_paid

    cur.execute("UPDATE clan_cycle SET state='finished', total_paid=? WHERE id=?",
                (total_paid, cycle_id))
    db.commit()

    # Достижения по итогам сезона
    try:
        from clan.achievements import unlock_achievement
        top_clan_data = max(report["clans"], key=lambda x: x["bank"]) if report["clans"] else None
        if top_clan_data:
            for member_row in cur.execute(
                "SELECT user_id FROM clan_members WHERE clan_id=? AND left_at IS NULL",
                (top_clan_data["clan"]["id"],)
            ).fetchall():
                uid = member_row["user_id"]
                if not is_hard_excluded(uid):
                    bot.loop.create_task(unlock_achievement(uid, "clan_champion", bot=bot))
            if top_clan_data["top"]:
                winner_id = top_clan_data["top"][0]["user_id"]
                bot.loop.create_task(unlock_achievement(winner_id, "king", bot=bot))
    except Exception as e:
        logger.warning(f"clan season achievements: {e}")

    asyncio.create_task(send_payout_report_dm(bot, report))
    asyncio.create_task(post_payout_results(bot, report))
    # 👇 Личное ЛС каждому участнику: получил выплату или нет и почему
    asyncio.create_task(send_payout_dms(bot, report))

    try:
        from clan.panels import post_news_season_end
        asyncio.create_task(post_news_season_end(bot, report))
    except Exception as e:
        logger.warning(f"post_news_season_end: {e}")

    asyncio.create_task(log_discord(
        title=f"🏁 Клановая лига: {get_season_title(cycle['number'])} завершён",
        description=(
            f"> **Общий банк:** `{sum(c['bank'] for c in report['clans'])} DC`\n"
            f"> **Выплачено:** `{total_paid} DC`\n"
            f"> **Кланов:** `{len(report['clans'])}`"
        ),
        color=0xFFD700,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    ))

    logger.info(f"Клан-лига: {get_season_title(cycle['number'])} закрыт, выплачено {total_paid} DC")

    async def _delayed_start():
        await asyncio.sleep(300)
        start_new_cycle()
        from clan.panels import (
            update_clan_pool_embed,
            post_news_season_start,
        )
        await update_clan_pool_embed(bot)
        try:
            await post_news_season_start(bot)
        except Exception as e:
            logger.warning(f"post_news_season_start delayed: {e}")

    asyncio.create_task(_delayed_start())

    return True


# ============================================================
# ВКЛАДЫ — С ЛИМИТОМ 1000 DC/ДЕНЬ
# ============================================================
async def add_clan_contribution(user_id: int, amount: int, reason: str):
    """
    Добавляет вклад в банк клана.
    👇 Лимит 1000 DC/сутки с юзера. Сверх лимита — НЕ идёт в банк.
    """
    if is_hard_excluded(user_id):
        return False

    if amount <= 0:
        return False

    clan = get_user_clan(user_id)
    if not clan:
        return False

    cycle = get_current_cycle()
    if not cycle:
        return False

    # 👇 Проверяем дневной лимит
    already = _get_daily_contributed(user_id)
    remaining = max(DAILY_CLAN_LIMIT - already, 0)

    if remaining <= 0:
        logger.info(f"👤 {user_id}: дневной лимит вклада исчерпан ({already}/{DAILY_CLAN_LIMIT}), {amount} DC в банк не ушло")
        return False

    actual_amount = min(amount, remaining)

    cur.execute(
        "INSERT INTO clan_contributions (cycle_id, clan_id, user_id, amount, reason, ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (cycle["id"], clan["id"], user_id, actual_amount, reason, int(time.time()))
    )
    db.commit()

    # 👇 Записываем в счётчик дня
    _add_daily_contributed(user_id, actual_amount)

    # Достижения
    try:
        from clan.achievements import check_and_unlock, get_user_contribution
        from core.bot import bot
        total = get_user_contribution(user_id)
        asyncio.create_task(check_and_unlock(user_id, "clan_deposit", value=total, bot=bot))
    except Exception as e:
        logger.warning(f"clan deposit achievements: {e}")

    return True


async def send_welcome_dm(member: disnake.Member, clan: dict):
    try:
        data = load_json(os.path.join(EMBEDS_DIR, "welcome.json"), {})
        embeds = []
        for e in data.get("embeds", []):
            embeds.append(disnake.Embed.from_dict(e))

        e2 = disnake.Embed(
            title=f"Добро пожаловать в клан {clan['emoji']} {clan['name']}!",
            description=(
                f"> Ты теперь часть команды, {member.mention}!\n\n"
                f"**Как играть:**\n"
                f"> • Зарабатывай DC — до 100 DC вся сумма в копилку, больше — 40%\n"
                f"> • Выполняй квесты в <#1552700973753827509> — **100%** в копилку\n"
                f"> • Топ-3 по вкладу получат бонус ×3.00 / ×2.00 / ×1.50\n"
                f"> • В конце цикла банк делится между всеми участниками\n"
                f"> • Дневной лимит вклада — **1000 DC**\n\n"
                f"**Где смотреть:**\n"
                f"> 📊 Копилка — <#1552700960474800128>\n"
                f"> 📊 Сезон — <#1552700989465956403>\n"
                f"> 🎮 Игры и квесты — <#1552700973753827509>\n"
                f"> 📰 Новости — <#1552700701128400979>\n\n"
                f"> Удачи, воин!"
            ),
            color=clan["color"]
        )
        e2.set_image(url=IMG_STRIPE)
        embeds.append(e2)
        await member.send(embeds=embeds)
    except Exception as e:
        logger.warning(f"welcome DM {member.id}: {e}")


# ============================================================
# ТОПЫ / СТАТИСТИКА
# ============================================================
def get_clan_bank(clan_id: int, cycle_id: Optional[int] = None) -> int:
    if cycle_id is None:
        cycle = get_current_cycle()
        cycle_id = cycle["id"] if cycle else 0

    if HARD_EXCLUDED_USERS:
        ids = list(HARD_EXCLUDED_USERS)
        placeholders = ",".join("?" * len(ids))
        row = cur.execute(
            f"SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions "
            f"WHERE cycle_id=? AND clan_id=? AND user_id NOT IN ({placeholders})",
            (cycle_id, clan_id, *ids)
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions "
            "WHERE cycle_id=? AND clan_id=?",
            (cycle_id, clan_id)
        ).fetchone()
    return row["s"] or 0


def get_clan_top(clan_id: int, cycle_id: Optional[int] = None, limit: int = 10) -> List[dict]:
    if cycle_id is None:
        cycle = get_current_cycle()
        cycle_id = cycle["id"] if cycle else 0

    if HARD_EXCLUDED_USERS:
        ids = list(HARD_EXCLUDED_USERS)
        placeholders = ",".join("?" * len(ids))
        rows = cur.execute(
            f"SELECT user_id, COALESCE(SUM(amount), 0) AS total "
            f"FROM clan_contributions WHERE cycle_id=? AND clan_id=? "
            f"AND user_id NOT IN ({placeholders}) "
            f"GROUP BY user_id ORDER BY total DESC LIMIT ?",
            (cycle_id, clan_id, *ids, limit)
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT user_id, COALESCE(SUM(amount), 0) AS total "
            "FROM clan_contributions WHERE cycle_id=? AND clan_id=? "
            "GROUP BY user_id ORDER BY total DESC LIMIT ?",
            (cycle_id, clan_id, limit)
        ).fetchall()
    return [{"user_id": r["user_id"], "total": r["total"]} for r in rows]


def get_clan_members_count(clan_id: int) -> int:
    rows = cur.execute(
        "SELECT user_id FROM clan_members WHERE clan_id=? AND left_at IS NULL",
        (clan_id,)
    ).fetchall()
    return sum(1 for r in rows if not is_hard_excluded(r["user_id"]))


def get_user_contribution(user_id: int, cycle_id: Optional[int] = None) -> int:
    if is_hard_excluded(user_id):
        return 0

    if cycle_id is None:
        cycle = get_current_cycle()
        cycle_id = cycle["id"] if cycle else 0
    row = cur.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions "
        "WHERE cycle_id=? AND user_id=?",
        (cycle_id, user_id)
    ).fetchone()
    return row["s"] or 0


def get_last_contributions(clan_id: int, limit: int = 5) -> List[dict]:
    if HARD_EXCLUDED_USERS:
        ids = list(HARD_EXCLUDED_USERS)
        placeholders = ",".join("?" * len(ids))
        rows = cur.execute(
            f"SELECT user_id, amount, reason, ts FROM clan_contributions "
            f"WHERE clan_id=? AND user_id NOT IN ({placeholders}) "
            f"ORDER BY ts DESC LIMIT ?",
            (clan_id, *ids, limit)
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT user_id, amount, reason, ts FROM clan_contributions "
            "WHERE clan_id=? ORDER BY ts DESC LIMIT ?",
            (clan_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_contributions_all(limit: int = 5) -> List[dict]:
    if HARD_EXCLUDED_USERS:
        ids = list(HARD_EXCLUDED_USERS)
        placeholders = ",".join("?" * len(ids))
        rows = cur.execute(
            f"SELECT user_id, amount, reason, ts, clan_id FROM clan_contributions "
            f"WHERE user_id NOT IN ({placeholders}) "
            f"ORDER BY ts DESC LIMIT ?",
            (*ids, limit)
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT user_id, amount, reason, ts, clan_id FROM clan_contributions "
            "ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ============================================================
# ОТЧЁТЫ
# ============================================================
async def send_payout_report_dm(bot, report: dict):
    try:
        user = bot.get_user(REPORT_DM_USER_ID)
        if not user:
            user = await bot.fetch_user(REPORT_DM_USER_ID)

        cycle = report["cycle"]
        lines = []
        for c_data in report["clans"]:
            c = c_data["clan"]
            lines.append(
                f"\n**{c['emoji']} {c['name'].upper()}** — {c_data['members']} чел., банк `{c_data['bank']} DC`"
            )
            for t in c_data["top"]:
                medal = ["🥇", "🥈", "🥉"][t["place"] - 1]
                lines.append(
                    f"> {medal} <@{t['user_id']}> — {t['contrib']} DC (×{t['bonus']}) → **{t['payout']} DC**"
                )
            lines.append(f"> ─── Итого выплачено: `{c_data['paid']} DC`")
            if c_data.get("not_eligible"):
                lines.append(
                    f"> ─── Без выплаты (вклад < {MIN_CONTRIB_FOR_PAYOUT} DC): "
                    f"`{c_data['not_eligible']}` чел."
                )

        top_clan = max(report["clans"], key=lambda x: x["bank"]) if report["clans"] else None

        e1 = disnake.Embed(color=0xFFD700)
        e1.set_image(url=IMG_STRIPE)
        e2 = disnake.Embed(
            title=f"📊 ОТЧЁТ ПО КЛАНОВОЙ ЛИГЕ — {get_season_title(cycle['number']).upper()}",
            description="".join(lines) + (
                f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 **Общий оборот:** `{sum(c['bank'] for c in report['clans'])} DC`\n"
                f"💸 **Выплачено:** `{report['total']} DC`\n"
                + (f"🏆 **Победитель сезона:** {top_clan['clan']['emoji']} "
                   f"**{top_clan['clan']['name'].upper()}**" if top_clan else "")
            ),
            color=0xFFD700
        )
        e2.set_image(url=IMG_STRIPE)
        await user.send(embeds=[e1, e2])
        logger.info(f"Отчёт по клан-лиге отправлен {REPORT_DM_USER_ID}")
    except Exception as e:
        logger.exception(f"send_payout_report_dm: {e}")


async def send_payout_dms(bot, report: dict):
    """
    Личное ЛС каждому участнику сезона: получил выплату или нет — и почему.

    Эмбед стилизованный: блоки-цитаты, разделители, поля. Без изображений.
    """
    season = get_season_title(report["cycle"]["number"])
    payouts = report.get("payouts", [])
    sent = 0
    skipped = 0

    for p in payouts:
        try:
            user = bot.get_user(p["user_id"])
            if user is None:
                try:
                    user = await bot.fetch_user(p["user_id"])
                except Exception:
                    skipped += 1
                    continue
            if user is None:
                skipped += 1
                continue

            got = p["payout"] > 0
            color = (p["clan_color"] or 0x2ecc71) if got else 0x2f3136

            lines = [
                f"> Сезон **«{season}»** завершён.",
                f"> Клан: {p['clan_emoji']} **{p['clan_name'].upper()}**",
                "",
                "**Твой итог за сезон**",
                f"> Вклад в копилку: `{p['contrib']} DC`",
                f"> Банк клана: `{p['bank']} DC`",
            ]
            if p["place"]:
                lines.append(f"> Место по вкладу: `#{p['place']}`")
                lines.append(f"> Множитель: `×{p['bonus']:.2f}`")

            lines += ["", "────────────────────"]

            if got:
                lines += [
                    f"**💎 Получено: `{p['payout']} DC`**",
                    "",
                    "> Выплата уже на балансе.",
                    "> Спасибо, что держал копилку клана!",
                ]
            else:
                lines += ["**Выплата не начислена**", ""]
                lines.append(f"> Причина: {p['reason']}.")
                if not p.get("eligible", True):
                    lines += [
                        f"> Для выплаты нужно внести минимум `{MIN_CONTRIB_FOR_PAYOUT} DC` за сезон.",
                        "> В следующем сезоне всё в твоих руках.",
                    ]

            e = disnake.Embed(
                title="💎 Клановая лига — итоги сезона",
                description="\n".join(lines),
                color=color
            )
            e.set_footer(text="Diamond Shop · Клановая лига")

            await user.send(embed=e)
            sent += 1
            await asyncio.sleep(0.5)
        except disnake.Forbidden:
            skipped += 1
            continue
        except Exception as e:
            logger.warning(f"send_payout_dms {p['user_id']}: {e}")

    logger.info(
        f"send_payout_dms: отправлено {sent} ЛС, пропущено {skipped} "
        f"(всего участников: {len(payouts)})"
    )


async def post_payout_results(bot, report: dict):
    try:
        ch = bot.get_channel(CONFIG["CLAN_POOL_CHANNEL_ID"])
        if not ch:
            ch = await bot.fetch_channel(CONFIG["CLAN_POOL_CHANNEL_ID"])

        cycle = report["cycle"]
        lines = []
        for c_data in report["clans"]:
            c = c_data["clan"]
            lines.append(f"**{c['emoji']} {c['name'].upper()}** — банк `{c_data['bank']} DC`, "
                         f"выплачено `{c_data['paid']} DC` ({c_data['members']} чел.)")
            for t in c_data["top"]:
                medal = ["🥇", "🥈", "🥉"][t["place"] - 1]
                lines.append(f"> {medal} <@{t['user_id']}> — вклад `{t['contrib']} DC` (×{t['bonus']})")

        top_clan = max(report["clans"], key=lambda x: x["bank"]) if report["clans"] else None

        e1 = disnake.Embed(color=0xFFD700)
        e1.set_image(url=IMG_STRIPE)
        e2 = disnake.Embed(
            title=f"🏆 {get_season_title(cycle['number']).upper()} ЗАВЕРШЁН!",
            description="".join(lines) + (
                f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 **Общий оборот:** `{sum(c['bank'] for c in report['clans'])} DC`\n"
                + (f"🏆 **Победитель:** {top_clan['clan']['emoji']} "
                   f"**{top_clan['clan']['name'].upper()}**" if top_clan else "") +
                f"\n\n> Новый сезон стартует через **5 минут**!"
            ),
            color=0xFFD700
        )
        e2.set_image(url=IMG_STRIPE)
        await ch.send(embeds=[e1, e2])
    except Exception as e:
        logger.exception(f"post_payout_results: {e}")


# ============================================================
# ВСПОМОГАТЕЛЬНОЕ
# ============================================================
def make_progress_bar(percent: float, length: int = 10) -> str:
    percent = max(0.0, min(1.0, percent))
    filled = int(round(percent * length))
    return "▰" * filled + "▱" * (length - filled)


def clan_status_emoji(bank: int) -> str:
    if bank >= 5000:
        return "🔥"
    if bank >= 2000:
        return "⚡"
    return "💤"
