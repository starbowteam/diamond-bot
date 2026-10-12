# -*- coding: utf-8 -*-
"""
Питомцы Diamond — ядро.
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


MSK = timezone(timedelta(hours=3))

MAX_LEVEL = 10
CACHE_CAP_HOURS = 24
FEED_COST = 200
FEED_XP = 100
FEED_COOLDOWN = 4 * 3600
FEED_STREAK_BONUS = 500
ACTIVE_SWAP_COOLDOWN = 6 * 3600
GIFT_COMMISSION = 0.10

# 👇 Юзеры, которых НЕ показываем в топе питомцеводов
TOP_EXCLUDED_USERS = {
    796293832751972352,
}

XP_THRESHOLDS = [
    0, 100, 350, 850, 1850, 3850, 7350, 12850, 20850, 32850,
]


CATALOG: Dict[str, dict] = {
    "cat_ginger": {
        "name": "Рыжий Кот",
        "rarity": "common",
        "price_dc": 300,
        "passive_dc": 1,
        "bonus_type": "none",
        "bonus_value": 0.0,
        "description": "Обычный дворовый кот. Спит 20 часов в сутки, но DC приносит исправно.",
        "fa_code": 0xf6be,
    },
    "fox": {
        "name": "Хитрая Лиса",
        "rarity": "rare",
        "price_dc": 600,
        "passive_dc": 2,
        "bonus_type": "none",
        "bonus_value": 0.0,
        "description": "Хитрая и умная. Всегда найдёт, где взять лишнюю монетку.",
        "fa_code": 0xf6d3,
    },
    "owl": {
        "name": "Ночная Сова",
        "rarity": "rare",
        "price_dc": 900,
        "passive_dc": 3,
        "bonus_type": "none",
        "bonus_value": 0.0,
        "description": "Не спит по ночам — считает DC, которые ты не тратишь.",
        "fa_code": 0xf4ba,
    },
    "griffin": {
        "name": "Грифон",
        "rarity": "epic",
        "price_dc": 1200,
        "passive_dc": 4,
        "bonus_type": "review_bonus",
        "bonus_value": 0.03,
        "description": "Царь птиц. Охраняет твои отзывы и щедро награждает за них.",
        "fa_code": 0xf520,
    },
    "dragon": {
        "name": "Дракончик",
        "rarity": "legendary",
        "price_dc": 2000,
        "passive_dc": 7,
        "bonus_type": "casino_luck",
        "bonus_value": 0.05,
        "description": "Ещё маленький, но уже дышит огнём. Приносит удачу в казино.",
        "fa_code": 0xf6d5,
    },
    "diamond_pet": {
        "name": "Даймондик",
        "rarity": "mythic",
        "price_dc": 5000,
        "passive_dc": 20,
        "bonus_type": "clan_contrib",
        "bonus_value": 0.10,
        "description": "Легенда Diamond. Сделан из чистой валюты сервера, знает толк в кланах.",
        "fa_code": 0xf3a5,
    },
}

RARITY_LABEL = {
    "common": "Common", "rare": "Rare", "epic": "Epic",
    "legendary": "Legendary", "mythic": "Mythic",
}

RARITY_ORDER = {
    "common": 1, "rare": 2, "epic": 3, "legendary": 4, "mythic": 5,
}

RARITY_PALETTE = {
    "common":    (198, 208, 224),
    "rare":      (106, 155, 209),
    "epic":      (179, 157, 219),
    "legendary": (247, 201, 145),
    "mythic":    (255, 77,  148),
}


def get_pet(pet_key: str) -> Optional[dict]:
    return CATALOG.get(pet_key)


def get_all_pets() -> List[Tuple[str, dict]]:
    return list(CATALOG.items())


def gift_price(pet_key: str) -> int:
    cat = CATALOG.get(pet_key)
    if not cat:
        return 0
    return int(cat["price_dc"] * (1 + GIFT_COMMISSION))


def _ensure_column(table: str, column: str, ddl: str):
    try:
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()]
        if column not in cols:
            cur.execute(f'ALTER TABLE "{table}" ADD COLUMN {ddl}')
            db.commit()
            logger.info(f"🐾 Миграция {table}.{column} добавлена")
    except Exception as e:
        logger.error(f"🐾 Миграция {table}.{column}: {e}")


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
    CREATE INDEX IF NOT EXISTS idx_user_pets_user ON user_pets (user_id);

    CREATE TABLE IF NOT EXISTS pet_purchases (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER,
        pet_key      TEXT,
        price        INTEGER,
        is_gift      INTEGER DEFAULT 0,
        from_user_id INTEGER DEFAULT NULL,
        ts           INTEGER
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

    _ensure_column("pet_purchases", "is_gift", "is_gift INTEGER DEFAULT 0")
    _ensure_column("pet_purchases", "from_user_id", "from_user_id INTEGER DEFAULT NULL")


def get_user_pets(user_id: int) -> List[dict]:
    rows = cur.execute(
        "SELECT * FROM user_pets WHERE user_id=? ORDER BY is_active DESC, id ASC",
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


def get_xp_threshold(level: int) -> int:
    if level <= 1: return 0
    if level > MAX_LEVEL: return XP_THRESHOLDS[-1]
    return XP_THRESHOLDS[level - 1]


def get_xp_for_next(level: int) -> int:
    if level >= MAX_LEVEL: return 0
    return get_xp_threshold(level + 1) - get_xp_threshold(level)


def get_xp_progress(pet: dict) -> Tuple[int, int, int]:
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
    cat = CATALOG.get(pet_key)
    if not cat:
        return 0.0
    base = cat["passive_dc"]
    lvl_mult = 1 + (level - 1) * 0.15
    return base * lvl_mult


def max_pending(pet_key: str, level: int) -> int:
    return int(hourly_rate(pet_key, level) * CACHE_CAP_HOURS)


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

    active = get_active_pet(user_id)
    if not active:
        cur.execute(
            "UPDATE user_pets SET is_active=1 WHERE user_id=? AND pet_key=?",
            (user_id, pet_key)
        )

    cur.execute(
        "INSERT INTO pet_purchases (user_id, pet_key, price, is_gift, ts) "
        "VALUES (?, ?, ?, 0, ?)",
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


async def gift_pet(bot, sender_id: int, recipient_id: int, pet_key: str) -> dict:
    cat = CATALOG.get(pet_key)
    if not cat:
        return {"ok": False, "error": "Питомец не найден"}

    if sender_id == recipient_id:
        return {"ok": False, "error": "Нельзя подарить самому себе"}

    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        return {"ok": False, "error": "Сервер недоступен"}

    member = guild.get_member(recipient_id)
    if not member:
        return {"ok": False, "error": "Получатель не найден на сервере"}
    if member.bot:
        return {"ok": False, "error": "Нельзя дарить ботам"}

    if has_pet(recipient_id, pet_key):
        return {"ok": False, "error": f"У получателя уже есть этот питомец"}

    price = gift_price(pet_key)
    balance = get_dc_cache(sender_id).get("balance", 0)
    if balance < price:
        need = price - balance
        return {"ok": False, "error": f"Не хватает {need} DC (нужно {price} с комиссией)"}

    from modules.dc import remove_dc
    reason = f"Подарок питомца: {cat['name']} для {recipient_id}"
    ok = await remove_dc(sender_id, price, reason)
    if not ok:
        return {"ok": False, "error": "Не удалось списать DC"}

    now = int(time.time())

    cur.execute("""
        INSERT INTO user_pets (user_id, pet_key, purchased_at, last_income)
        VALUES (?, ?, ?, ?)
    """, (recipient_id, pet_key, now, now))

    rec_active = get_active_pet(recipient_id)
    if not rec_active:
        cur.execute(
            "UPDATE user_pets SET is_active=1 WHERE user_id=? AND pet_key=?",
            (recipient_id, pet_key)
        )

    cur.execute(
        "INSERT INTO pet_purchases (user_id, pet_key, price, is_gift, from_user_id, ts) "
        "VALUES (?, ?, ?, 1, ?, ?)",
        (recipient_id, pet_key, price, sender_id, now)
    )
    db.commit()

    try:
        await member.send(
            f"🎁 **Тебе подарили питомца!**\n"
            f"> **Питомец:** {cat['name']} ({RARITY_LABEL[cat['rarity']]})\n"
            f"> **От:** <@{sender_id}>\n"
            f"> **Доход:** {cat['passive_dc']} DC/час на ур.1"
        )
    except Exception as e:
        logger.debug(f"gift DM to {recipient_id}: {e}")

    await log_discord(
        title="🎁 Питомец подарен",
        description=(
            f"> **От:** <@{sender_id}>\n"
            f"> **Кому:** <@{recipient_id}>\n"
            f"> **Питомец:** {cat['name']} ({RARITY_LABEL[cat['rarity']]})\n"
            f"> **Списано:** `{price} DC` (включая комиссию 10%)"
        ),
        color=0xffaa00,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return {"ok": True, "pet_key": pet_key, "price": price}


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


def add_pet_xp_sync(user_id: int, pet_key: str, amount: int) -> bool:
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
# ТОП — исключаем заданных юзеров
# ============================================================
def get_top_users(limit: int = 10) -> List[dict]:
    """
    Топ по максимальному уровню питомца.
    Юзеры из TOP_EXCLUDED_USERS не показываются.
    """
    # Собираем всех с их лучшим уровнем
    rows = cur.execute("""
        SELECT user_id, MAX(level) AS best_level
        FROM user_pets
        GROUP BY user_id
        ORDER BY best_level DESC, user_id ASC
    """).fetchall()

    result = []
    for r in rows:
        uid = r["user_id"]

        # 👇 Пропускаем исключённых
        if uid in TOP_EXCLUDED_USERS:
            continue

        best = cur.execute("""
            SELECT pet_key, level FROM user_pets
            WHERE user_id=? ORDER BY level DESC LIMIT 1
        """, (uid,)).fetchone()
        cnt = cur.execute(
            "SELECT COUNT(*) AS c FROM user_pets WHERE user_id=?",
            (uid,)
        ).fetchone()

        result.append({
            "user_id": uid,
            "best_level": r["best_level"],
            "pet_key": best["pet_key"] if best else None,
            "pets_count": int(cnt["c"]) if cnt else 0,
        })

        if len(result) >= limit:
            break

    return result


def get_user_place(user_id: int) -> Optional[int]:
    """Место юзера в топе. Если он в исключениях — None."""
    if user_id in TOP_EXCLUDED_USERS:
        return None

    top = get_top_users(limit=1000)
    for i, t in enumerate(top, 1):
        if t["user_id"] == user_id:
            return i
    return None


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
                cur.execute("UPDATE user_pets SET last_income=? WHERE id=?", (now, r["id"]))
                continue

            earned = int(hourly * elapsed / 3600)
            if earned <= 0:
                cur.execute("UPDATE user_pets SET last_income=? WHERE id=?", (now, r["id"]))
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


def install_hooks(bot):
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
