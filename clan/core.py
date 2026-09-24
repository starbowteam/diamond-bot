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
    CONFIG, DATA_DIR, ADD_DIR, logger, db, cur,
    load_json, save_json, log_discord, now_ts,
)

# ============================================================
# КОНСТАНТЫ ЛИГИ
# ============================================================
MSK = timezone(timedelta(hours=3))

CLUB_ROLE_ID    = 1284697274655576186
MIN_BALANCE     = 0

EXCLUDE_FROM_CLAN = {
    1124040555240898631,
    796293832751972352,
}

CLAN_CYCLE_DAYS = 28
PAYOUT_DAY      = 28
PAYOUT_HOUR_MSK = 20
PAYOUT_MINUTE   = 0

TAX_NORMAL      = 0.60
TAX_QUEST       = 1.00
TAX_CASINO      = 0.60

TOP_BONUSES = [1.75, 1.50, 1.30]

REPORT_DM_USER_ID = 796293832751972352

IMG_STRIPE = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
              "1537851307757539390/image.png?ex=6ab5efe3&is=6ab49e63&"
              "hm=d1b48b6ea98c9662564b5a77012797024de47fbc9444922b72184d6d0a6d5a2a&")

EMBEDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embeds")

CLANS_DATA = [
    {
        "id": 1,
        "name": "Окаменелости",
        "emoji": "🪨",
        "role_id": 1552707675257831525,
        "color": 0x8B7355,
        "fa_icon": "🪨",
        "description": "Стойкие, как камень. Непоколебимая воля и вековая мудрость.",
    },
    {
        "id": 2,
        "name": "Сияние",
        "emoji": "✨",
        "role_id": 1552707025723465838,
        "color": 0xFFD700,
        "fa_icon": "✨",
        "description": "Свет звёзд в ночи. Яркие, амбициозные, недосягаемые.",
    },
    {
        "id": 3,
        "name": "Кристализация",
        "emoji": "💎",
        "role_id": 1551280425312194650,
        "color": 0xB39DDB,
        "fa_icon": "💎",
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
    db.commit()


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
        count = len(members)
        total_bal = 0
        for m in members:
            b = cur.execute("SELECT balance FROM dc_cache WHERE user_id=?", (m["user_id"],)).fetchone()
            if b:
                total_bal += b["balance"]
        result.append((c, count, total_bal))
    return result


def assign_user_to_clan(user_id: int, guild: disnake.Guild) -> Optional[dict]:
    if user_id in EXCLUDE_FROM_CLAN:
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

    # Проход 1: раскидываем тех, кого нет в клане
    for member in guild.members:
        if member.bot:
            continue
        if not any(r.id == CLUB_ROLE_ID for r in member.roles):
            continue
        if member.id in EXCLUDE_FROM_CLAN:
            excluded += 1
            continue
        if get_user_clan(member.id):
            skipped += 1
            continue
        result = assign_user_to_clan(member.id, guild)
        if result:
            assigned += 1

    # Проход 2: РЕБАЛАНС — перекидываем из больших кланов в маленькие
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
    logger.info(f"Клан-лига: старт цикла #{number} до {datetime.fromtimestamp(ends_at, MSK)}")
    return cycle


def close_cycle_and_pay(bot) -> bool:
    cycle = get_current_cycle()
    if not cycle:
        return False

    cur.execute("UPDATE clan_cycle SET state='payout' WHERE id=?", (cycle["id"],))
    db.commit()

    cycle_id = cycle["id"]
    all_clans = get_all_clans()

    report = {"cycle": cycle, "clans": [], "total": 0}
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
            if m["user_id"] in top_ids:
                idx = top_ids.index(m["user_id"])
                m["bonus"] = TOP_BONUSES[idx]
                m["place"] = idx + 1
            else:
                m["bonus"] = 1.0
                m["place"] = None
            m["eff"] = m["weight"] * m["bonus"]

        total_eff = sum(m["eff"] for m in members_list)

        clan_paid = 0
        top_report = []
        for m in members_list:
            if total_eff > 0:
                payout = math.floor(bank * m["eff"] / total_eff)
            else:
                payout = 0
            m["payout"] = payout
            clan_paid += payout

            if payout > 0:
                try:
                    from modules.dc import add_dc
                    bot.loop.create_task(add_dc(
                        m["user_id"], payout,
                        f"Клановая лига: выплата за сезон #{cycle['number']}",
                        notify=True, log=False, clan_share=0.0
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

        db.commit()
        total_paid += clan_paid

        report["clans"].append({
            "clan": c,
            "bank": bank,
            "members": len(members_list),
            "top": top_report,
            "paid": clan_paid,
        })

    report["total"] = total_paid

    cur.execute("UPDATE clan_cycle SET state='finished', total_paid=? WHERE id=?",
                (total_paid, cycle_id))
    db.commit()

    # Отчёт в ЛС админу
    asyncio.create_task(send_payout_report_dm(bot, report))
    # Пост в канал копилки
    asyncio.create_task(post_payout_results(bot, report))

    # 👇 НОВОСТЬ в канал новостей
    try:
        from clan.panels import post_news_season_end
        asyncio.create_task(post_news_season_end(bot, report))
    except Exception as e:
        logger.warning(f"post_news_season_end: {e}")

    asyncio.create_task(log_discord(
        title=f"🏁 Клановая лига: сезон #{cycle['number']} завершён",
        description=(
            f"> **Общий банк:** `{sum(c['bank'] for c in report['clans'])} DC`\n"
            f"> **Выплачено:** `{total_paid} DC`\n"
            f"> **Кланов:** `{len(report['clans'])}`"
        ),
        color=0xFFD700,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    ))

    logger.info(f"Клан-лига: цикл #{cycle['number']} закрыт, выплачено {total_paid} DC")

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
# ВКЛАДЫ
# ============================================================
async def add_clan_contribution(user_id: int, amount: int, reason: str):
    if amount <= 0:
        return False

    clan = get_user_clan(user_id)
    if not clan:
        return False

    cycle = get_current_cycle()
    if not cycle:
        return False

    cur.execute(
        "INSERT INTO clan_contributions (cycle_id, clan_id, user_id, amount, reason, ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (cycle["id"], clan["id"], user_id, amount, reason, int(time.time()))
    )
    db.commit()
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
                f"> • Зарабатывай DC — **60%** идёт в копилку клана\n"
                f"> • Выполняй квесты в <#1552700973753827509> — **100%** в копилку\n"
                f"> • Топ-3 по вкладу получат бонус ×1.75 / ×1.50 / ×1.30\n"
                f"> • В конце цикла банк делится между всеми участниками\n\n"
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
    rows = cur.execute(
        "SELECT user_id, COALESCE(SUM(amount), 0) AS total "
        "FROM clan_contributions WHERE cycle_id=? AND clan_id=? "
        "GROUP BY user_id ORDER BY total DESC LIMIT ?",
        (cycle_id, clan_id, limit)
    ).fetchall()
    return [{"user_id": r["user_id"], "total": r["total"]} for r in rows]


def get_clan_members_count(clan_id: int) -> int:
    row = cur.execute(
        "SELECT COUNT(*) AS c FROM clan_members WHERE clan_id=? AND left_at IS NULL",
        (clan_id,)
    ).fetchone()
    return row["c"] if row else 0


def get_user_contribution(user_id: int, cycle_id: Optional[int] = None) -> int:
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
    rows = cur.execute(
        "SELECT user_id, amount, reason, ts FROM clan_contributions "
        "WHERE clan_id=? ORDER BY ts DESC LIMIT ?",
        (clan_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_contributions_all(limit: int = 5) -> List[dict]:
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

        top_clan = max(report["clans"], key=lambda x: x["bank"]) if report["clans"] else None

        e1 = disnake.Embed(color=0xFFD700)
        e1.set_image(url=IMG_STRIPE)
        e2 = disnake.Embed(
            title=f"📊 ОТЧЁТ ПО КЛАНОВОЙ ЛИГЕ — СЕЗОН #{cycle['number']}",
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
            title=f"🏆 СЕЗОН #{cycle['number']} ЗАВЕРШЁН!",
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
