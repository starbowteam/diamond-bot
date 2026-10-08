# -*- coding: utf-8 -*-
"""
Ядро бонус-панели: акция дня, реферальная система, кейсы.
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
REF_INVITE_CHANNEL_ID  = 1552700701128400979   # канал для реф-ссылок (тот же что у адвайтров)
CLUB_ROLE_ID           = 1284697274655576186   # роль «Клуб» — доступ к рефам
SUPREME_USER_ID        = 796293832751972352    # тебе — доступ без роли

REF_MIN_ALIVE_SECONDS  = 3600                  # 1 час — порог зачёта
REF_REWARD_BALANCE     = 100                   # DC юзеру за приглашённого
REF_REWARD_CLAN        = 100                   # DC в копилку клана
REF_COOLDOWN_MIN       = 15                    # таск каждые 15 мин

CASES: List[dict] = [
    {
        "num": 1, "key": "luck",   "price": 100,
        "name": "Попробуй удачу",
        "icon": "fa-gift",
        "color": "blue",
        "desc": "Лёгкий вход. Шанс на хороший приз без больших затрат.",
        "prizes": [
            {"type": "dc",       "value": 30,   "chance": 30.0},
            {"type": "dc",       "value": 60,   "chance": 25.0},
            {"type": "dc",       "value": 100,  "chance": 20.0},
            {"type": "dc",       "value": 150,  "chance": 15.0},
            {"type": "dc",       "value": 250,  "chance": 8.0},
            {"type": "role",     "key": "role_active", "days": 7, "chance": 1.5},
            {"type": "role",     "key": "role_helper", "days": 3, "chance": 0.5},
        ],
    },
    {
        "num": 2, "key": "fast",   "price": 300,
        "name": "Быстрый куш",
        "icon": "fa-coins",
        "color": "green",
        "desc": "Для тех кто не любит ждать. Внутри бусты и роль Помощник.",
        "prizes": [
            {"type": "dc",       "value": 100,  "chance": 25.0},
            {"type": "dc",       "value": 200,  "chance": 25.0},
            {"type": "dc",       "value": 350,  "chance": 20.0},
            {"type": "dc",       "value": 500,  "chance": 15.0},
            {"type": "dc",       "value": 750,  "chance": 10.0},
            {"type": "boost",    "key": "boost_messages_x2", "chance": 3.0},
            {"type": "role",     "key": "role_helper", "days": 7, "chance": 1.5},
            {"type": "discount", "key": "3",  "chance": 0.5},
        ],
    },
    {
        "num": 3, "key": "serious", "price": 500,
        "name": "Серьёзный куш",
        "icon": "fa-gem",
        "color": "gold",
        "desc": "Средний уровень азарта. Ловит скидки и крупные суммы.",
        "prizes": [
            {"type": "dc",       "value": 200,  "chance": 20.0},
            {"type": "dc",       "value": 400,  "chance": 25.0},
            {"type": "dc",       "value": 700,  "chance": 25.0},
            {"type": "dc",       "value": 1000, "chance": 15.0},
            {"type": "dc",       "value": 1500, "chance": 10.0},
            {"type": "boost",    "key": "boost_all_x2", "chance": 3.0},
            {"type": "discount", "key": "3",    "chance": 1.0},
            {"type": "discount", "key": "5",    "chance": 0.8},
            {"type": "role",     "key": "role_helper", "days": 0, "chance": 0.2},
        ],
    },
    {
        "num": 4, "key": "royal",  "price": 1000,
        "name": "Королевский куш",
        "icon": "fa-crown",
        "color": "purple",
        "desc": "Для тех кто готов на серьёзный шаг. Шанс вытащить 3000 DC.",
        "prizes": [
            {"type": "dc",       "value": 500,  "chance": 20.0},
            {"type": "dc",       "value": 900,  "chance": 25.0},
            {"type": "dc",       "value": 1400, "chance": 25.0},
            {"type": "dc",       "value": 2000, "chance": 15.0},
            {"type": "dc",       "value": 3000, "chance": 10.0},
            {"type": "boost",    "key": "boost_review_x2", "chance": 3.0},
            {"type": "discount", "key": "5",    "chance": 1.5},
            {"type": "role",     "key": "role_legend", "days": 0, "chance": 0.5},
        ],
    },
    {
        "num": 5, "key": "mythic", "price": 2000,
        "name": "Мифический куш",
        "icon": "fa-trophy",
        "color": "red",
        "desc": "Максимум азарта. Джекпот — 8000 DC.",
        "prizes": [
            {"type": "dc",       "value": 1000, "chance": 15.0},
            {"type": "dc",       "value": 1800, "chance": 20.0},
            {"type": "dc",       "value": 2800, "chance": 25.0},
            {"type": "dc",       "value": 4000, "chance": 20.0},
            {"type": "dc",       "value": 6000, "chance": 12.0},
            {"type": "discount", "key": "7",    "chance": 4.0},
            {"type": "discount", "key": "10",   "chance": 2.0},
            {"type": "role",     "key": "role_dc_magnate", "days": 0, "chance": 1.5},
            {"type": "dc",       "value": 8000, "chance": 0.5},
        ],
    },
]

CASES_BY_NUM = {c["num"]: c for c in CASES}


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
    CREATE TABLE IF NOT EXISTS bonus_case_opens (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        case_num    INTEGER,
        price       INTEGER,
        prize_type  TEXT,
        prize_value TEXT,
        prize_desc  TEXT,
        opened_at   INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_case_opens_user ON bonus_case_opens (user_id);
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
# РОЛЬ И ДОСТУП
# ============================================================
def has_club_role(member) -> bool:
    if member is None:
        return False
    try:
        return any(r.id == CLUB_ROLE_ID for r in member.roles)
    except Exception:
        return False


def has_bonus_access(member) -> bool:
    if member is None:
        return False
    if member.id == SUPREME_USER_ID:
        return True
    return has_club_role(member)


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
                await add_clan_contribution(uid, REF_REWARD_CLAN, f"Реф: {r['member_id']}")
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
                    f"> **В копилку:** `+{REF_REWARD_CLAN} DC`"
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
# КЕЙСЫ
# ============================================================
def _roll_case(case_num: int) -> Optional[dict]:
    case = CASES_BY_NUM.get(case_num)
    if not case:
        return None
    total = sum(p["chance"] for p in case["prizes"])
    r = random.uniform(0, total)
    cum = 0.0
    for p in case["prizes"]:
        cum += p["chance"]
        if r <= cum:
            return dict(p)
    return dict(case["prizes"][-1])


def _load_shop_catalog() -> dict:
    path = os.path.join(CATALOG_DIR, "shop_catalog.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"load_shop_catalog: {e}")
        return {}


def _prize_description(prize: dict) -> str:
    t = prize.get("type")
    if t == "dc":
        return f"{prize['value']} DC"
    if t == "role":
        cat = _load_shop_catalog()
        item = cat.get("roles", {}).get("items", {}).get(prize["key"], {})
        name = item.get("name", "Роль")
        days = prize.get("days", 0)
        return f"{name}" + (f" на {days} дн." if days else " навсегда")
    if t == "boost":
        cat = _load_shop_catalog()
        item = cat.get("boosts", {}).get("items", {}).get(prize["key"], {})
        return item.get("name", "Буст")
    if t == "discount":
        return f"Скидка {prize['key']}%"
    return "—"


async def apply_prize(bot, user_id: int, prize: dict) -> str:
    """Выдаёт приз. Возвращает текстовое описание."""
    t = prize.get("type")
    cat = _load_shop_catalog()

    if t == "dc":
        amount = int(prize["value"])
        await add_dc(user_id, amount, f"Выигрыш в кейсе", notify=False, log=False, to_clan_pool=False)
        return f"+{amount} DC на баланс"

    if t == "boost":
        item = cat.get("boosts", {}).get("items", {}).get(prize["key"], {})
        try:
            activate_item(
                user_id=user_id,
                item_key=prize["key"],
                item_type="boosts",
                value=float(item.get("value", 0) or 0),
                duration_hours=int(item.get("duration_hours", 0) or 0),
                uses=int(item.get("uses", -1)),
            )
            return f"Буст «{item.get('name', prize['key'])}» активирован"
        except Exception as e:
            logger.warning(f"apply boost: {e}")
            return "Буст активирован"

    if t == "discount":
        try:
            await add_purchase(user_id, "discounts", f"Скидка {prize['key']}%")
            return f"Скидка {prize['key']}% в инвентаре"
        except Exception as e:
            logger.warning(f"apply discount: {e}")
            return f"Скидка {prize['key']}%"

    if t == "role":
        item = cat.get("roles", {}).get("items", {}).get(prize["key"], {})
        role_id = item.get("role_id")
        days = int(prize.get("days", 0) or 0)
        if not role_id:
            return "Роль (ошибка выдачи)"
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild:
            return "Роль (ошибка сервера)"
        member = guild.get_member(user_id)
        role = guild.get_role(int(role_id))
        if not member or not role:
            return "Роль (ошибка)"
        try:
            await member.add_roles(role, reason="Выигрыш в кейсе")
        except Exception as e:
            logger.warning(f"apply role: {e}")
            return "Роль (ошибка выдачи)"
        if days > 0:
            return f"Роль «{role.name}» на {days} дн."
        return f"Роль «{role.name}» навсегда"

    return "Приз"


async def open_case(bot, user_id: int, case_num: int) -> dict:
    """
    Открывает кейс: списывает DC, роллит приз, выдаёт, пишет в лог.
    Возвращает {"ok": bool, "error": str, "prize": dict, "desc": str}
    """
    case = CASES_BY_NUM.get(case_num)
    if not case:
        return {"ok": False, "error": "Кейс не найден"}

    balance = await get_user_balance(user_id)
    if balance < case["price"]:
        return {"ok": False, "error": f"Недостаточно DC. Нужно {case['price']}, у тебя {balance}"}

    ok = await remove_dc(user_id, case["price"], f"Открытие кейса «{case['name']}»")
    if not ok:
        return {"ok": False, "error": "Не удалось списать DC"}

    prize = _roll_case(case_num)
    desc = _prize_description(prize)

    try:
        await apply_prize(bot, user_id, prize)
    except Exception as e:
        logger.exception(f"open_case apply: {e}")

    cur.execute(
        "INSERT INTO bonus_case_opens "
        "(user_id, case_num, price, prize_type, prize_value, prize_desc, opened_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, case_num, case["price"], prize.get("type", ""),
         json.dumps(prize, ensure_ascii=False), desc, int(time.time()))
    )
    db.commit()

    await log_discord(
        title="🎰 Кейс открыт",
        description=(
            f"> **Юзер:** <@{user_id}>\n"
            f"> **Кейс:** {case['name']} · `{case['price']} DC`\n"
            f"> **Выпало:** {desc}"
        ),
        color=0xffaa00,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return {"ok": True, "prize": prize, "desc": desc, "case": case}


def get_case_history(user_id: int, limit: int = 8) -> List[dict]:
    rows = cur.execute(
        "SELECT * FROM bonus_case_opens WHERE user_id=? "
        "ORDER BY opened_at DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def get_case_stats(user_id: int) -> dict:
    row = cur.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(price), 0) AS s "
        "FROM bonus_case_opens WHERE user_id=?",
        (user_id,)
    ).fetchone()
    total = row["c"] or 0
    spent = row["s"] or 0

    best = 0
    for r in cur.execute(
        "SELECT prize_type, prize_value FROM bonus_case_opens WHERE user_id=?",
        (user_id,)
    ).fetchall():
        if r["prize_type"] == "dc":
            try:
                v = int(json.loads(r["prize_value"]).get("value", 0))
                if v > best:
                    best = v
            except Exception:
                pass

    return {"opened": total, "spent": spent, "best": best}


# ============================================================
# АНОНС АКЦИИ ДНЯ
# ============================================================
DEAL_ANNOUNCE_STATE = os.path.join(DATA_DIR, "bonus_deal_announce.json")


def _load_announce_state() -> dict:
    return load_json(DEAL_ANNOUNCE_STATE, {"slot": 0, "message_id": 0})


def _save_announce_state(state: dict):
    save_json(DEAL_ANNOUNCE_STATE, state)


async def announce_deal_change(bot, deal: dict):
    """
    Постит анонс новой акции дня в канал Бонусы.
    Удаляет старый анонс, если был.
    """
    state = _load_announce_state()
    slot = int(time.time() // (5 * 3600))

    if state.get("slot") == slot:
        return

    ch = bot.get_channel(BONUS_CHANNEL_ID)
    if not ch:
        try:
            ch = await bot.fetch_channel(BONUS_CHANNEL_ID)
        except Exception as e:
            logger.warning(f"announce_deal_change channel: {e}")
            return

    # удаляем старое сообщение
    old_id = state.get("message_id")
    if old_id:
        try:
            old = await ch.fetch_message(old_id)
            await old.delete()
        except Exception:
            pass

    item = deal.get("item_data", {})
    name = item.get("name", "—")
    orig = deal.get("original_price", 0)
    new = deal.get("new_price", 0)
    discount = deal.get("discount", 0)
    cat_label = deal.get("category_label", "—")

    text = (
        f"@everyone\n"
        f"> **Новая акция дня!** 🔥\n\n"
        f"> Скидка **{discount}%** на **«{name}»** — "
        f"**{new} DC** вместо ~~{orig} DC~~.\n\n"
        f"> Забрать: **панель Бонусы** → **Акция дня**."
    )

    try:
        msg = await ch.send(
            content=text,
            allowed_mentions=disnake.AllowedMentions(everyone=True),
        )
    except Exception as e:
        logger.warning(f"announce_deal_change send: {e}")
        return

    state["slot"] = slot
    state["message_id"] = msg.id
    _save_announce_state(state)

    logger.info(f"🔥 Анонс акции: {name} · {discount}% · {new} DC")


# ============================================================
# ЗАПУСК ТАСКОВ
# ============================================================
def start_bonus_tasks(bot):
    if not ref_reward_task.is_running():
        ref_reward_task.start(bot)
