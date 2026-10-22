# -*- coding: utf-8 -*-
"""Логика кейсов (перенесено из bonus)."""
import json
import time
import random
import os
from typing import List, Dict

from core.utils import DATA_DIR, CATALOG_DIR, logger, db, cur, log_discord, CONFIG
from modules.dc import add_dc, remove_dc, get_user_balance, add_purchase

CASES: List[dict] = [
    {
        "num": 1, "key": "luck", "price": 100,
        "name": "Попробуй удачу", "icon": "fa-gift", "color": "blue",
        "desc": "Лёгкий вход. Много мелких призов и шанс на хороший куш.",
        "prizes": [
            {"type": "dc", "value": 8, "chance": 15.0}, {"type": "dc", "value": 20, "chance": 20.0},
            {"type": "dc", "value": 40, "chance": 20.0}, {"type": "dc", "value": 60, "chance": 15.0},
            {"type": "dc", "value": 80, "chance": 12.0}, {"type": "dc", "value": 120, "chance": 8.0},
            {"type": "dc", "value": 200, "chance": 5.0}, {"type": "dc", "value": 360, "chance": 3.0},
            {"type": "dc", "value": 640, "chance": 1.5}, {"type": "dc", "value": 1400, "chance": 0.5},
        ],
    },
    {
        "num": 2, "key": "fast", "price": 300,
        "name": "Быстрый куш", "icon": "fa-coins", "color": "green",
        "desc": "Много средних DC, плюс редкий шанс на буст и роль.",
        "prizes": [
            {"type": "dc", "value": 25, "chance": 15.0}, {"type": "dc", "value": 60, "chance": 20.0},
            {"type": "dc", "value": 120, "chance": 20.0}, {"type": "dc", "value": 180, "chance": 15.0},
            {"type": "dc", "value": 240, "chance": 11.5}, {"type": "dc", "value": 360, "chance": 8.0},
            {"type": "dc", "value": 600, "chance": 5.0}, {"type": "dc", "value": 1080, "chance": 3.0},
            {"type": "dc", "value": 1920, "chance": 1.5}, {"type": "dc", "value": 4200, "chance": 0.5},
            {"type": "boost", "key": "boost_messages_x2", "chance": 0.3},
            {"type": "boost", "key": "boost_all_x2", "chance": 0.1},
            {"type": "role", "key": "role_helper", "days": 7, "chance": 0.1},
        ],
    },
    {
        "num": 3, "key": "serious", "price": 500,
        "name": "Серьёзный куш", "icon": "fa-gem", "color": "gold",
        "desc": "Средний азарт. Ловит бусты, скидки и крупные суммы.",
        "prizes": [
            {"type": "dc", "value": 40, "chance": 15.0}, {"type": "dc", "value": 100, "chance": 20.0},
            {"type": "dc", "value": 200, "chance": 20.0}, {"type": "dc", "value": 300, "chance": 15.0},
            {"type": "dc", "value": 400, "chance": 11.3}, {"type": "dc", "value": 600, "chance": 8.0},
            {"type": "dc", "value": 1000, "chance": 5.0}, {"type": "dc", "value": 1800, "chance": 3.0},
            {"type": "dc", "value": 3200, "chance": 1.5}, {"type": "dc", "value": 7000, "chance": 0.5},
            {"type": "boost", "key": "boost_all_x2", "chance": 0.2},
            {"type": "discount", "key": "5", "chance": 0.2},
            {"type": "role", "key": "role_helper", "days": 7, "chance": 0.1},
        ],
    },
    {
        "num": 4, "key": "royal", "price": 1000,
        "name": "Королевский куш", "icon": "fa-crown", "color": "purple",
        "desc": "Для серьёзного шага. Роли, бусты и шанс вытащить 14 000 DC.",
        "prizes": [
            {"type": "dc", "value": 80, "chance": 15.0}, {"type": "dc", "value": 200, "chance": 20.0},
            {"type": "dc", "value": 400, "chance": 20.0}, {"type": "dc", "value": 600, "chance": 15.0},
            {"type": "dc", "value": 800, "chance": 11.4}, {"type": "dc", "value": 1200, "chance": 8.0},
            {"type": "dc", "value": 2000, "chance": 5.0}, {"type": "dc", "value": 3600, "chance": 3.0},
            {"type": "dc", "value": 6400, "chance": 1.5}, {"type": "dc", "value": 14000, "chance": 0.5},
            {"type": "boost", "key": "boost_review_x2", "chance": 0.2},
            {"type": "discount", "key": "5", "chance": 0.2},
            {"type": "role", "key": "role_legend", "days": 0, "chance": 0.1},
            {"type": "role", "key": "role_dc_magnate", "days": 0, "chance": 0.1},
        ],
    },
    {
        "num": 5, "key": "mythic", "price": 2000,
        "name": "Мифический куш", "icon": "fa-trophy", "color": "red",
        "desc": "Максимум азарта. Крупные DC, дорогие роли и джекпот — 28 000 DC.",
        "prizes": [
            {"type": "dc", "value": 160, "chance": 15.0}, {"type": "dc", "value": 400, "chance": 20.0},
            {"type": "dc", "value": 800, "chance": 20.0}, {"type": "dc", "value": 1200, "chance": 15.0},
            {"type": "dc", "value": 1600, "chance": 11.3}, {"type": "dc", "value": 2400, "chance": 8.0},
            {"type": "dc", "value": 4000, "chance": 5.0}, {"type": "dc", "value": 7200, "chance": 3.0},
            {"type": "dc", "value": 12800, "chance": 1.5}, {"type": "dc", "value": 28000, "chance": 0.5},
            {"type": "boost", "key": "boost_review_x2", "chance": 0.2},
            {"type": "discount", "key": "7", "chance": 0.2},
            {"type": "role", "key": "role_dc_magnate", "days": 0, "chance": 0.15},
            {"type": "role", "key": "role_legend", "days": 0, "chance": 0.1},
            {"type": "role", "key": "role_helper", "days": 0, "chance": 0.05},
        ],
    },
]
CASES_BY_NUM = {c["num"]: c for c in CASES}

def init_cases_tables():
    cur.executescript("""
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

def _roll_case(case_num: int):
    case = CASES_BY_NUM.get(case_num)
    if not case: return None
    total = sum(p["chance"] for p in case["prizes"])
    r = random.uniform(0, total)
    cum = 0.0
    for p in case["prizes"]:
        cum += p["chance"]
        if r <= cum: return dict(p)
    return dict(case["prizes"][-1])

def _load_shop_catalog() -> dict:
    path = os.path.join(CATALOG_DIR, "shop_catalog.json")
    if not os.path.exists(path): return {}
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception as e:
        logger.warning(f"load_shop_catalog: {e}")
        return {}

def _prize_description(prize: dict) -> str:
    t = prize.get("type")
    if t == "dc": return f"{prize['value']} DC"
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
    if t == "discount": return f"Скидка {prize['key']}%"
    return "—"

async def apply_prize(bot, user_id: int, prize: dict) -> str:
    t = prize.get("type")
    cat = _load_shop_catalog()

    if t == "dc":
        amount = int(prize["value"])
        await add_dc(user_id, amount, f"Выигрыш в кейсе", notify=False, log=False, to_clan_pool=False)
        return f"+{amount} DC на баланс"

    if t == "boost":
        item = cat.get("boosts", {}).get("items", {}).get(prize["key"], {})
        try:
            from core.utils import activate_item
            activate_item(
                user_id=user_id, item_key=prize["key"], item_type="boosts",
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
        if not role_id: return "Роль (ошибка выдачи)"
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild: return "Роль (ошибка сервера)"
        member = guild.get_member(user_id)
        role = guild.get_role(int(role_id))
        if not member or not role: return "Роль (ошибка)"
        try:
            await member.add_roles(role, reason="Выигрыш в кейсе")
        except Exception as e:
            logger.warning(f"apply role: {e}")
            return "Роль (ошибка выдачи)"
        if days > 0: return f"Роль «{role.name}» на {days} дн."
        return f"Роль «{role.name}» навсегда"

    return "Приз"

async def open_case(bot, user_id: int, case_num: int) -> dict:
    case = CASES_BY_NUM.get(case_num)
    if not case: return {"ok": False, "error": "Кейс не найден"}

    balance = await get_user_balance(user_id)
    if balance < case["price"]:
        return {"ok": False, "error": f"Недостаточно DC. Нужно {case['price']}, у тебя {balance}"}

    ok = await remove_dc(user_id, case["price"], f"Открытие кейса «{case['name']}»")
    if not ok: return {"ok": False, "error": "Не удалось списать DC"}

    prize = _roll_case(case_num)
    desc = _prize_description(prize)

    try:
        await apply_prize(bot, user_id, prize)
    except Exception as e:
        logger.exception(f"open_case apply: {e}")

    cur.execute(
        "INSERT INTO bonus_case_opens (user_id, case_num, price, prize_type, prize_value, prize_desc, opened_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, case_num, case["price"], prize.get("type", ""), json.dumps(prize, ensure_ascii=False), desc, int(time.time()))
    )
    db.commit()

    await log_discord(
        title="🎰 Кейс открыт",
        description=f"> **Юзер:** <@{user_id}>\n> **Кейс:** {case['name']} · `{case['price']} DC`\n> **Выпало:** {desc}",
        color=0xffaa00,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return {"ok": True, "prize": prize, "desc": desc, "case": case}

def get_case_history(user_id: int, limit: int = 8) -> List[dict]:
    rows = cur.execute(
        "SELECT * FROM bonus_case_opens WHERE user_id=? ORDER BY opened_at DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]

def get_case_stats(user_id: int) -> dict:
    row = cur.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(price), 0) AS s FROM bonus_case_opens WHERE user_id=?",
        (user_id,)
    ).fetchone()
    total = row["c"] or 0
    spent = row["s"] or 0

    best = 0
    for r in cur.execute("SELECT prize_type, prize_value FROM bonus_case_opens WHERE user_id=?", (user_id,)).fetchall():
        if r["prize_type"] == "dc":
            try:
                v = int(json.loads(r["prize_value"]).get("value", 0))
                if v > best: best = v
            except Exception:
                pass

    return {"opened": total, "spent": spent, "best": best}
