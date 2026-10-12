# -*- coding: utf-8 -*-
"""
Питомцы Diamond — ядро.

Каталог, БД, покупка, XP, накопление, бонусы.
"""
import os
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple

from disnake.ext import tasks

from core.utils import (
    CONFIG, logger, db, cur, log_discord,
    get_dc_cache,
)


# ============================================================
# КОНСТАНТЫ
# ============================================================
MSK = timezone(timedelta(hours=3))

MAX_LEVEL = 10
CACHE_CAP_HOURS = 24
FEED_COST = 200
FEED_XP = 100
FEED_COOLDOWN = 4 * 3600
FEED_STREAK_BONUS = 500
ACTIVE_SWAP_COOLDOWN = 6 * 3600

# XP-пороги (суммарно чтобы достичь уровня N)
# index 0 → уровень 1 (0 XP), index 9 → уровень 10 (32850 XP)
XP_THRESHOLDS = [
    0,      # L1
    100,    # L2
    350,    # L3
    850,    # L4
    1850,   # L5
    3850,   # L6
    7350,   # L7
    12850,  # L8
    20850,  # L9
    32850,  # L10
]


# ============================================================
# КАТАЛОГ ПИТОМЦЕВ
# ============================================================
CATALOG: Dict[str, dict] = {
    "cat_ginger": {
        "name": "Рыжий Кот",
        "rarity": "common",
        "price_dc": 300,
        "passive_dc": 1,
        "bonus_type": "none",
        "bonus_value": 0.0,
        "description": "Обычный дворовый кот. Спит 20 часов в сутки, но DC приносит исправно.",
        "fa_code": 0xf6be,   # fa-cat
    },
    "fox": {
        "name": "Хитрая Лиса",
        "rarity": "rare",
        "price_dc": 600,
        "passive_dc": 2,
        "bonus_type": "none",
        "bonus_value": 0.0,
        "description": "Хитрая и умная. Всегда найдёт, где взять лишнюю монетку.",
        "fa_code": 0xf6d3,   # fa-dog (аналог)
    },
    "owl": {
        "name": "Ночная Сова",
        "rarity": "rare",
        "price_dc": 900,
        "passive_dc": 3,
        "bonus_type": "none",
        "bonus_value": 0.0,
        "description": "Не спит по ночам — считает DC, которые ты не тратишь.",
        "fa_code": 0xf4ba,   # fa-dove
    },
    "griffin": {
        "name": "Грифон",
        "rarity": "epic",
        "price_dc": 1200,
        "passive_dc": 4,
        "bonus_type": "review_bonus",
        "bonus_value": 0.03,
        "description": "Царь птиц. Охраняет твои отзывы и щедро награждает за них.",
        "fa_code": 0xf520,   # fa-crow
    },
    "dragon": {
        "name": "Дракончик",
        "rarity": "legendary",
        "price_dc": 2000,
        "passive_dc": 7,
        "bonus_type": "casino_luck",
        "bonus_value": 0.05,
        "description": "Ещё маленький, но уже дышит огнём. Приносит удачу в казино.",
        "fa_code": 0xf6d5,   # fa-dragon
    },
    "diamond_pet": {
        "name": "Даймондик",
        "rarity": "mythic",
        "price_dc": 5000,
        "passive_dc": 20,
        "bonus_type": "clan_contrib",
        "bonus_value": 0.10,
        "description": "Легенда Diamond. Сделан из чистой валюты сервера, знает толк в кланах.",
        "fa_code": 0xf3a5,   # fa-gem
    },
}

RARITY_LABEL = {
    "common":    "Common",
    "rare":      "Rare",
    "epic":      "Epic",
    "legendary": "Legendary",
    "mythic":    "Mythic",
}

RARITY_ORDER = {
    "common":    1,
    "rare":      2,
    "epic":      3,
    "legendary": 4,
    "mythic":    5,
}

RARITY_PALETTE = {
    "common":    (198, 208, 224),   # silver
    "rare":      (106, 155, 209),   # blue
    "epic":      (179, 157, 219),   # purple
    "legendary": (247, 201, 145),   # gold
    "mythic":    (255, 77,  148),   # pink
}


def get_pet(pet_key: str) -> Optional[dict]:
    return CATALOG.get(pet_key)


def get_all_pets() -> List[Tuple[str, dict]]:
    return list(CATALOG.items())


# ============================================================
# БД
# ============================================================
def init_pet_tables():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS user_pets (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        pet_key       TEXT NOT NULL,
        level         INTEGER DEFAULT 1,
        xp            INTEGER DEFAULT 0,
        pending_dc    INTEGER DEFAULT 0,
        last_income   INTEGER DEFAULT 0,
        purchased_at  INTEGER,
        is_active     INTEGER DEFAULT 0,
        last_fed      INTEGER DEFAULT 0,
        feed_streak   INTEGER DEFAULT 0,
        last_feed_day TEXT DEFAULT NULL,
        UNIQUE(user_id, pet_key)
    );
    CREATE INDEX IF NOT EXISTS idx_user_pets_user
        ON user_pets (user_id);

    CREATE TABLE IF NOT EXISTS pet_purchases (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id  INTEGER,
        pet_key  TEXT,
        price    INTEGER,
        ts       INTEGER
    );

    CREATE TABLE IF NOT EXISTS pet_active_cooldown (
        user_id    INTEGER PRIMARY KEY,
        last_swap  INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS pet_xp_log (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id  INTEGER,
        source   TEXT,
        amount   INTEGER,
        ts       INTEGER
    );
    """)
    db.commit()


# ============================================================
# ГЕТТЕРЫ
# ============================================================
def get_user_pets(user_id: int) -> List[dict]:
    rows = cur.execute(
        "SELECT * FROM user_pets WHERE user_id=? "
        "ORDER BY is_active DESC, id ASC",
        (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_pet_by_key(user_id: int, pet_key: str) -> Optional[dict]:
    row = cur.execute(
        "SELECT * FROM user_pets WHERE user_id=? AND pet_key=?",
        (user_id, pet_key)
    ).fetchone()
    return dict(row) if row else None


def get_active_pet(user_id: int) -> Optional[dict]:
    row = cur.execute(
        "SELECT * FROM user_pets WHERE user_id=? AND is_active=1 LIMIT 1",
        (user_id,)
    ).fetchone()
    return dict(row) if row else None


def has_pet(user_id: int, pet_key: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM user_pets WHERE user_id=? AND pet_key=?",
        (user_id, pet_key)
    ).fetchone()
    return bool(row)


def get_user_best_pet(user_id: int) -> Optional[dict]:
    """
    Возвращает лучшего питомца юзера (по уровню, затем по xp)
    с дополнительными cat-данными. Используется в render_top.
    """
    row = cur.execute(
        "SELECT pet_key, level FROM user_pets WHERE user_id=? "
        "ORDER BY level DESC, xp DESC LIMIT 1",
        (user_id,)
    ).fetchone()
    if not row:
        return None
    cat = CATALOG.get(row["pet_key"], {})
    return {
        "pet_key": row["pet_key"],
        "level": row["level"],
        "name": cat.get("name", "—"),
        "rarity": cat.get("rarity", "common"),
    }


# ============================================================
# МАТЕМАТИКА
# ============================================================
def get_xp_threshold(level: int) -> int:
    """Сколько всего XP нужно чтобы быть на этом уровне."""
    if level <= 1:
        return 0
    if level > MAX_LEVEL:
        return XP_THRESHOLDS[-1]
    return XP_THRESHOLDS[level - 1]


def get_xp_for_next(level: int) -> int:
    """Сколько XP нужно набрать чтобы поднять уровень."""
    if level >= MAX_LEVEL:
        return 0
    return get_xp_threshold(level + 1) - get_xp_threshold(level)


def get_xp_progress(pet: dict) -> Tuple[int, int, int]:
    """Возвращает (current_xp_in_level, xp_needed_for_next, percent 0-100)."""
    level = pet["level"]
    xp = pet["xp"]

    if level >= MAX_LEVEL:
        return (xp - get_xp_threshold(MAX_LEVEL), 0, 100)

    level_start = get_xp_threshold(level)
    level_end = get_xp_threshold(level + 1)
    need = level_end - level_start
    cur_xp = xp - level_start
    percent = min(int((cur_xp / need) * 100), 100)
    return (cur_xp, need, percent)


def hourly_rate(pet_key: str, level: int) -> float:
    """DC/час для питомца на данном уровне."""
    cat = CATALOG.get(pet_key)
    if not cat:
        return 0.0
    base = cat["passive_dc"]
    lvl_mult = 1 + (level - 1) * 0.15
    return base * lvl_mult


def max_pending(pet_key: str, level: int) -> int:
    """Сколько максимум может накопиться."""
    return int(hourly_rate(pet_key, level) * CACHE_CAP_HOURS)


# ============================================================
# ПОКУПКА
# ============================================================
async def buy_pet(bot, user_id: int, pet_key: str) -> dict:
    cat = CATALOG.get(pet_key)
    if not cat:
        return {"ok": False, "error": "Питомец не найден"}

    if has_pet(user_id, pet_key):
        return {"ok": False, "error": "У тебя уже есть этот питомец"}

    price = cat["price_dc"]
    balance = get_dc_cache(user_id).get("balance", 0)
    if balance < price:
        return {"ok": False, "error": f"Не хватает {price - balance} DC"}

    from modules.dc import remove_dc
    ok = await remove_dc(user_id, price, f"Покупка питомца: {cat['name']}")
    if not ok:
        return {"ok": False, "error": "Не удалось списать DC"}

    now = int(time.time())
    cur.execute("""
        INSERT INTO user_pets (user_id, pet_key, purchased_at, last_income)
        VALUES (?, ?, ?, ?)
    """, (user_id, pet_key, now, now))

    # Если нет активного — этот станет активным
    active = get_active_pet(user_id)
    if not active:
        cur.execute(
            "UPDATE user_pets SET is_active=1 WHERE user_id=? AND pet_key=?",
            (user_id, pet_key)
        )

    cur.execute(
        "INSERT INTO pet_purchases (user_id, pet_key, price, ts) VALUES (?, ?, ?, ?)",
        (user_id, pet_key, price, now)
    )
    db.commit()

    await log_discord(
        title="🐾 Куплен питомец",
        description=(
            f"> **Юзер:** <@{user_id}>\n"
            f"> **Питомец:** {cat['name']} ({RARITY_LABEL[cat['rarity']]})\n"
            f"> **Цена:** `{price} DC`\n"
            f"> **Доход:** `{cat['passive_dc']} DC/час` на ур.1"
        ),
        color=0x00aaff,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return {"ok": True, "pet_key": pet_key}


# ============================================================
# СМЕНА АКТИВНОГО
# ============================================================
def set_active_pet(user_id: int, pet_key: str) -> dict:
    pet = get_pet_by_key(user_id, pet_key)
    if not pet:
        return {"ok": False, "error": "У тебя нет этого питомца"}
    if pet.get("is_active"):
        return {"ok": False, "error": "Этот питомец уже активен"}

    now = int(time.time())
    row = cur.execute(
        "SELECT last_swap FROM pet_active_cooldown WHERE user_id=?",
        (user_id,)
    ).fetchone()
    if row and row["last_swap"]:
        left = row["last_swap"] + ACTIVE_SWAP_COOLDOWN - now
        if left > 0:
            h = left // 3600
            m = (left % 3600) // 60
            return {"ok": False, "error": f"Кулдаун смены: {h}ч {m}м"}

    cur.execute("UPDATE user_pets SET is_active=0 WHERE user_id=?", (user_id,))
    cur.execute(
        "UPDATE user_pets SET is_active=1 WHERE user_id=? AND pet_key=?",
        (user_id, pet_key)
    )
    cur.execute("""
        INSERT OR REPLACE INTO pet_active_cooldown (user_id, last_swap)
        VALUES (?, ?)
    """, (user_id, now))
    db.commit()
    return {"ok": True}


def get_swap_cooldown_left(user_id: int) -> int:
    row = cur.execute(
        "SELECT last_swap FROM pet_active_cooldown WHERE user_id=?",
        (user_id,)
    ).fetchone()
    if not row or not row["last_swap"]:
        return 0
    left = row["last_swap"] + ACTIVE_SWAP_COOLDOWN - int(time.time())
    return max(left, 0)


# ============================================================
# ЗАБРАТЬ ДОХОД
# ============================================================
async def claim_income(user_id: int) -> int:
    pets = get_user_pets(user_id)
    total = sum((p.get("pending_dc") or 0) for p in pets)
    if total <= 0:
        return 0

    now = int(time.time())
    cur.execute(
        "UPDATE user_pets SET pending_dc=0, last_income=? WHERE user_id=?",
        (now, user_id)
    )
    db.commit()

    from modules.dc import add_dc
    await add_dc(user_id, total, "Доход от питомцев", notify=False, log=False)

    await log_discord(
        title="💰 Забран доход питомцев",
        description=f"> **Юзер:** <@{user_id}>\n> **Сумма:** `+{total} DC`",
        color=0x2ecc71,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return total


# ============================================================
# КОРМЛЕНИЕ
# ============================================================
async def feed_active_pet(user_id: int) -> dict:
    pet = get_active_pet(user_id)
    if not pet:
        return {"ok": False, "error": "Нет активного питомца"}

    if pet["level"] >= MAX_LEVEL:
        return {"ok": False, "error": "Питомец уже максимального уровня"}

    now = int(time.time())
    last_fed = pet.get("last_fed") or 0
    left = last_fed + FEED_COOLDOWN - now
    if left > 0:
        h = left // 3600
        m = (left % 3600) // 60
        return {"ok": False, "error": f"Кормить можно через {h}ч {m}м"}

    balance = get_dc_cache(user_id).get("balance", 0)
    if balance < FEED_COST:
        return {"ok": False, "error": f"Нужно {FEED_COST} DC"}

    from modules.dc import remove_dc
    ok = await remove_dc(user_id, FEED_COST, "Кормление питомца")
    if not ok:
        return {"ok": False, "error": "Не удалось списать DC"}

    # Streak
    today = datetime.now(MSK).strftime("%Y-%m-%d")
    streak = pet.get("feed_streak") or 0
    last_day = pet.get("last_feed_day")

    if last_day:
        try:
            d1 = datetime.strptime(last_day, "%Y-%m-%d").date()
            d2 = datetime.strptime(today, "%Y-%m-%d").date()
            diff = (d2 - d1).days
            if diff == 1:
                streak += 1
            elif diff > 1:
                streak = 1
            # если diff == 0, не меняем
        except Exception:
            streak = 1
    else:
        streak = 1

    xp_gain = FEED_XP
    bonus_xp = 0
    if streak >= 7 and streak % 7 == 0:
        bonus_xp = FEED_STREAK_BONUS
        xp_gain += bonus_xp

    add_pet_xp_sync(user_id, pet["pet_key"], xp_gain)

    cur.execute("""
        UPDATE user_pets SET last_fed=?, feed_streak=?, last_feed_day=?
        WHERE user_id=? AND pet_key=?
    """, (now, streak, today, user_id, pet["pet_key"]))
    db.commit()

    return {"ok": True, "xp": xp_gain, "bonus_xp": bonus_xp, "streak": streak}


# ============================================================
# XP
# ============================================================
def add_pet_xp_sync(user_id: int, pet_key: str, amount: int) -> bool:
    """Синхронно начисляет XP питомцу. Возвращает True если уровень апнулся."""
    pet = get_pet_by_key(user_id, pet_key)
    if not pet:
        return False
    if pet["level"] >= MAX_LEVEL:
        return False
    if amount <= 0:
        return False

    new_xp = pet["xp"] + amount
    new_level = pet["level"]
    leveled = False

    while new_level < MAX_LEVEL and new_xp >= get_xp_threshold(new_level + 1):
        new_level += 1
        leveled = True

    cur.execute("""
        UPDATE user_pets SET xp=?, level=? WHERE user_id=? AND pet_key=?
    """, (new_xp, new_level, user_id, pet_key))
    db.commit()
    return leveled


async def add_pet_xp(user_id: int, amount: int, source: str = "misc"):
    """
    Публичный хук: активный питомец получает 100%, остальные — 25% (только если amount >= 10).
    """
    pets = get_user_pets(user_id)
    if not pets:
        return

    active = None
    others = []
    for p in pets:
        if p["is_active"]:
            active = p
        else:
            others.append(p)

    if active:
        add_pet_xp_sync(user_id, active["pet_key"], amount)

    if amount >= 10 and others:
        rest = max(amount // 4, 1)
        for p in others:
            add_pet_xp_sync(user_id, p["pet_key"], rest)


# ============================================================
# БОНУСЫ АКТИВНОГО ПИТОМЦА
# ============================================================
def _get_active_bonus(user_id: int, bonus_type: str) -> float:
    active = get_active_pet(user_id)
    if not active:
        return 1.0
    cat = CATALOG.get(active["pet_key"])
    if not cat:
        return 1.0
    if cat.get("bonus_type") != bonus_type:
        return 1.0
    return 1.0 + float(cat.get("bonus_value") or 0.0)


def get_review_bonus(user_id: int) -> float:
    return _get_active_bonus(user_id, "review_bonus")


def get_casino_bonus(user_id: int) -> float:
    return _get_active_bonus(user_id, "casino_luck")


def get_clan_bonus(user_id: int) -> float:
    return _get_active_bonus(user_id, "clan_contrib")


# ============================================================
# ТОП
# ============================================================
def get_top_users(limit: int = 10) -> List[dict]:
    """Топ по максимальному уровню питомца."""
    rows = cur.execute("""
        SELECT user_id, MAX(level) AS best_level
        FROM user_pets
        GROUP BY user_id
        ORDER BY best_level DESC, user_id ASC
        LIMIT ?
    """, (limit,)).fetchall()

    result = []
    for r in rows:
        uid = r["user_id"]
        best = cur.execute("""
            SELECT pet_key, level FROM user_pets
            WHERE user_id=? ORDER BY level DESC LIMIT 1
        """, (uid,)).fetchone()
        result.append({
            "user_id": uid,
            "best_level": r["best_level"],
            "pet_key": best["pet_key"] if best else None,
        })
    return result


def get_user_place(user_id: int) -> Optional[int]:
    top = get_top_users(limit=1000)
    for i, t in enumerate(top, 1):
        if t["user_id"] == user_id:
            return i
    return None


# ============================================================
# ТАСК НАКОПЛЕНИЯ
# ============================================================
@tasks.loop(minutes=15)
async def pets_income_task(bot):
    await bot.wait_until_ready()
    try:
        now = int(time.time())
        rows = cur.execute("SELECT * FROM user_pets").fetchall()
        changed = 0

        for r in rows:
            last = r["last_income"] or r["purchased_at"] or now
            elapsed = now - last
            if elapsed <= 0:
                continue

            hourly = hourly_rate(r["pet_key"], r["level"])
            cap = int(hourly * CACHE_CAP_HOURS)
            current = r["pending_dc"] or 0

            if current >= cap:
                cur.execute(
                    "UPDATE user_pets SET last_income=? WHERE id=?",
                    (now, r["id"])
                )
                continue

            earned = int(hourly * elapsed / 3600)
            if earned <= 0:
                cur.execute(
                    "UPDATE user_pets SET last_income=? WHERE id=?",
                    (now, r["id"])
                )
                continue

            new_pending = min(current + earned, cap)
            cur.execute(
                "UPDATE user_pets SET pending_dc=?, last_income=? WHERE id=?",
                (new_pending, now, r["id"])
            )
            changed += 1

        db.commit()
        if changed:
            logger.debug(f"pet income task: обновлено {changed}")
    except Exception as e:
        logger.exception(f"pets_income_task: {e}")


# ============================================================
# ХУКИ НА СОБЫТИЯ
# ============================================================
def install_hooks(bot):
    """Подписывается на события бота и раздаёт XP питомцам."""

    @bot.listen("on_message")
    async def _pet_on_message(message):
        try:
            if message.author.bot:
                return
            import disnake
            if not isinstance(message.channel, disnake.TextChannel):
                return
            if len((message.content or "").strip()) < 3:
                return
            if message.channel.id == CONFIG.get("REVIEW_COUNT_CHANNEL"):
                return
            await add_pet_xp(message.author.id, 1, "message")
        except Exception as e:
            logger.debug(f"pet hook message: {e}")
