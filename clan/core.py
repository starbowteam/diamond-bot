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

CLUB_ROLE_ID    = 1284697274655576186     # Клуб покупателей
MIN_BALANCE     = 25                       # Мин. баланс для входа

CLAN_CYCLE_DAYS = 28                       # Длина цикла
PAYOUT_DAY      = 28                       # Число месяца финала
PAYOUT_HOUR_MSK = 20                       # Час МСК
PAYOUT_MINUTE   = 0

TAX_NORMAL      = 0.60                     # Налог в банк со всего (60%)
TAX_QUEST       = 1.00                     # Квесты — 100%
TAX_CASINO      = 0.60                     # Казино — 60% от выплаты

TOP_BONUSES = [1.75, 1.50, 1.30]           # Топ-3 множители

REPORT_DM_USER_ID = 796293832751972352     # Кому слать отчёт

IMG_STRIPE = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
              "1537851307757539390/image.png?ex=6ab5efe3&is=6ab49e63&"
              "hm=d1b48b6ea98c9662564b5a77012797024de47fbc9444922b72184d6d0a6d5a2a&")

EMBEDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embeds")

# 3 клана
CLANS_DATA = [
    {
        "id": 1,
        "name": "Окаменелости",
        "emoji": "🪨",
        "role_id": 1552707675257831525,
        "color": 0x8B7355,
        "fa_icon": "🪨",  # для profile_card
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
    """Заполняет таблицу clans при первом запуске."""
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


def assign_user_to_clan(user_id: int, guild: disnake.Guild) -> Optional[dict]:
    """
    Автораскид юзера в наименее заполненный клан.
    Возвращает данные клана или None если не подходит.
    """
    if get_user_clan(user_id):
        return None  # уже в клане

    member = guild.get_member(user_id)
    if not member:
        return None

    if not any(r.id == CLUB_ROLE_ID for r in member.roles):
        return None  # нет роли Клуб

    # Баланс ≥ 25
    from modules.dc import get_user_balance
    # Синхронная проверка через dc_cache
    row = cur.execute("SELECT balance FROM dc_cache WHERE user_id=?", (user_id,)).fetchone()
    balance = row["balance"] if row else 0
    if balance < MIN_BALANCE:
        return None

    # Считаем «вес» каждого клана: кол-во * 10_000 + сумма балансов
    stats = []
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
        score = count * 10_000 + total_bal
        stats.append((c, score))

    # Куда меньше score — туда идём
    stats.sort(key=lambda x: x[1])
    target_clan = stats[0][0]

    cycle = get_current_cycle()
    cycle_id = cycle["id"] if cycle else 0

    cur.execute(
        "INSERT OR REPLACE INTO clan_members (user_id, clan_id, joined_at, left_at, cycle_joined) "
        "VALUES (?, ?, ?, NULL, ?)",
        (user_id, target_clan["id"], int(time.time()), cycle_id)
    )
    db.commit()

    # Выдаём роль на сервере
    role = guild.get_role(target_clan["role_id"])
    if role and role not in member.roles:
        try:
            asyncio.create_task(member.add_roles(role, reason="Клановая лига: автораскид"))
        except Exception as e:
            logger.warning(f"assign role {role.id}: {e}")

    # ЛС приветствие
    asyncio.create_task(send_welcome_dm(member, target_clan))

    # Лог
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
    """Массовое распределение всех клубных без клана. Возвращает статистику."""
    assigned = 0
    skipped = 0
    for member in guild.members:
        if member.bot:
            continue
        if not any(r.id == CLUB_ROLE_ID for r in member.roles):
            continue
        if get_user_clan(member.id):
            skipped += 1
            continue
        result = assign_user_to_clan(member.id, guild)
        if result:
            assigned += 1
    return {"assigned": assigned, "skipped": skipped}


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
    """Возвращает ts ближайшего 28-го числа 20:00 МСК (если уже прошло — следующего месяца)."""
    now = from_dt or _msk_now()
    target = now.replace(day=PAYOUT_DAY, hour=PAYOUT_HOUR_MSK, minute=PAYOUT_MINUTE,
                         second=0, microsecond=0)
    if target <= now:
        # переносим на следующий месяц
        if now.month == 12:
            target = target.replace(year=now.year + 1, month=1)
        else:
            target = target.replace(month=now.month + 1)
    return int(target.timestamp())


def start_new_cycle(force_short: bool = False) -> dict:
    """
    Создаёт новый активный цикл.
    force_short=True — сразу короткий до ближайшего 28-го (для первого запуска).
    """
    now_ts = int(time.time())
    ends_at = _next_payout_ts()

    # Определяем номер
    last = get_any_last_cycle()
    number = (last["number"] + 1) if last else 1

    cur.execute(
        "INSERT INTO clan_cycle (number, started_at, ends_at, state) "
        "VALUES (?, ?, ?, 'active')",
        (number, now_ts, ends_at)
    )
    db.commit()

    cycle = get_current_cycle()
    logger.info(f"Клан-лига: старт цикла #{number} до {datetime.fromtimestamp(ends_at, MSK)}")
    return cycle


def close_cycle_and_pay(bot) -> bool:
    """
    Закрывает текущий цикл, начисляет выплаты, шлёт отчёт.
    Возвращает True если выплата прошла.
    """
    cycle = get_current_cycle()
    if not cycle:
        return False

    # Лочим
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

        # Участники клана
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

        # Считаем eff_i для каждого
        cycle_len_sec = max(cycle["ends_at"] - cycle["started_at"], 1)
        members_list = []
        for m in members:
            user_id = m["user_id"]
            joined_at = m["joined_at"]

            # Вклад юзера за цикл
            contrib_row = cur.execute(
                "SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions "
                "WHERE cycle_id=? AND user_id=?",
                (cycle_id, user_id)
            ).fetchone()
            contrib = contrib_row["s"] or 0

            # Вес по времени
            days_inside = max(cycle["ends_at"] - max(joined_at, cycle["started_at"]), 0)
            weight = days_inside / cycle_len_sec

            members_list.append({
                "user_id": user_id,
                "contrib": contrib,
                "weight": weight,
            })

        # Топ-3 по вкладу
        sorted_members = sorted(members_list, key=lambda x: -x["contrib"])
        top_ids = [m["user_id"] for m in sorted_members[:3]]

        # Присваиваем бонусы
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

        # Начисляем
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
                # Начисляем через add_dc с clan_share=0 (не уходит обратно в банк)
                try:
                    from modules.dc import add_dc
                    await_ = bot.loop.create_task(add_dc(
                        m["user_id"], payout,
                        f"Клановая лига: выплата за сезон #{cycle['number']}",
                        notify=True, log=False, clan_share=0.0
                    ))
                except Exception as e:
                    logger.exception(f"clan payout add_dc {m['user_id']}: {e}")

                # Сохраняем в историю
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

    # Обновляем цикл
    cur.execute("UPDATE clan_cycle SET state='finished', total_paid=? WHERE id=?",
                (total_paid, cycle_id))
    db.commit()

    # Отчёт в ЛС админу
    asyncio.create_task(send_payout_report_dm(bot, report))

    # Пост в канал копилки
    asyncio.create_task(post_payout_results(bot, report))

    # Лог
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

    # Автостарт нового цикла через 5 минут
    async def _delayed_start():
        await asyncio.sleep(300)
        start_new_cycle()
        # Обновляем эмбед копилки
        from clan.panels import update_clan_pool_embed
        await update_clan_pool_embed(bot)

    asyncio.create_task(_delayed_start())

    return True


# ============================================================
# ВКЛАДЫ
# ============================================================
async def add_clan_contribution(user_id: int, amount: int, reason: str):
    """
    Добавляет вклад в банк клана юзера.
    Возвращает True если удалось (юзер в клане, активный цикл есть).
    """
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

    # ЛС о вкладе (тихо, без спама — опционально)
    # Раскомментируй если хочешь:
    # asyncio.create_task(_notify_contribution(user_id, clan, amount, reason))

    return True


async def _notify_contribution(user_id: int, clan: dict, amount: int, reason: str):
    try:
        from core.bot import bot
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if not user:
            return
        embed = disnake.Embed(
            title=f"{clan['emoji']} Вклад в копилку клана",
            description=(
                f"> **Клан:** {clan['emoji']} **{clan['name']}**\n"
                f"> **Вклад:** `+{amount} DC`\n"
                f"> **За что:** {reason}"
            ),
            color=clan["color"]
        )
        embed.set_image(url=IMG_STRIPE)
        await user.send(embed=embed)
    except Exception:
        pass


async def send_welcome_dm(member: disnake.Member, clan: dict):
    """ЛС приветствие при вступлении в клан."""
    try:
        data = load_json(os.path.join(EMBEDS_DIR, "welcome.json"), {})
        embeds = []
        for e in data.get("embeds", []):
            embeds.append(disnake.Embed.from_dict(e))

        # embed2 — текст
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
                f"> 🎮 Игры и квесты — <#1552700973753827509>\n\n"
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
    """Большой отчёт в ЛС админу."""
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
    """Пост итогов в канал копилки."""
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
    """▰▰▰▱▱▱▱▱▱▱"""
    percent = max(0.0, min(1.0, percent))
    filled = int(round(percent * length))
    return "▰" * filled + "▱" * (length - filled)


def clan_status_emoji(bank: int) -> str:
    if bank >= 5000:
        return "🔥"
    if bank >= 2000:
        return "⚡"
    return "💤"
