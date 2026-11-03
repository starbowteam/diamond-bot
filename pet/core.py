# -*- coding: utf-8 -*-
"""
Ядро кланового питомца ("Душа клана"). Доход капает раз в 24 часа напрямую в копилку.
"""
import os
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

from disnake.ext import tasks

from core.utils import (
    CONFIG, logger, db, cur, log_discord,
    get_dc_cache, save_dc_cache
)
from modules.dc import add_dc, remove_dc
from clan.core import get_user_clan, get_clan, get_current_cycle

# ============================================================
# КОНСТАНТЫ
# ============================================================
MAX_LEVEL = 10
FEED_COST = 1     # 1 DC = 1 XP
XP_PER_FEED = 1   
FEED_COOLDOWN = 0 

BONUS_PER_LEVEL = 0.03 
BASE_INCOME = 30.0 # 30 DC/ч на 1 уровне
PAYOUT_INTERVAL = 86400 # 24 часа

CLAN_PETS = {
    1: {"name": "Грифон", "fa": 0xf520},
    2: {"name": "Ночная Сова", "fa": 0xf4ba},
    3: {"name": "Кристальный Дракон", "fa": 0xf3a5}
}

# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
def init_pet_tables():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS clan_pets (
        clan_id    INTEGER PRIMARY KEY,
        level      INTEGER DEFAULT 1,
        xp         INTEGER DEFAULT 0,
        total_fed  INTEGER DEFAULT 0,
        last_tick  INTEGER DEFAULT 0
    );
    
    CREATE TABLE IF NOT EXISTS clan_pet_feedings (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        clan_id    INTEGER,
        user_id    INTEGER,
        amount     INTEGER,
        ts         INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_cp_feed_clan ON clan_pet_feedings (clan_id);
    """)
    db.commit()
    
    # Миграция: добавляем last_tick, если его нет
    cols = [r[1] for r in cur.execute("PRAGMA table_info(clan_pets)").fetchall()]
    
    if "last_tick" not in cols:
        try:
            cur.execute("ALTER TABLE clan_pets ADD COLUMN last_tick INTEGER DEFAULT 0")
            db.commit()
            logger.info("✅ Миграция clan_pets.last_tick добавлена")
        except Exception as e:
            logger.error(f"❌ Ошибка миграции last_tick: {e}")
    
    for cid in CLAN_PETS.keys():
        cur.execute("INSERT OR IGNORE INTO clan_pets (clan_id, last_tick) VALUES (?, ?)", (cid, int(time.time())))
    db.commit()

# ============================================================
# ЛОГИКА ПИТОМЦА
# ============================================================
def get_clan_pet(clan_id: int) -> dict:
    row = cur.execute("SELECT * FROM clan_pets WHERE clan_id=?", (clan_id,)).fetchone()
    if not row:
        cur.execute("INSERT OR IGNORE INTO clan_pets (clan_id, last_tick) VALUES (?, ?)", (clan_id, int(time.time())))
        db.commit()
        row = cur.execute("SELECT * FROM clan_pets WHERE clan_id=?", (clan_id,)).fetchone()
    return dict(row)

def get_pet_name(clan_id: int) -> str:
    return CLAN_PETS.get(clan_id, {}).get("name", "Неизвестный")

def get_pet_fa(clan_id: int) -> int:
    return CLAN_PETS.get(clan_id, {}).get("fa", 0xf3a5)

def get_pet_bonus(level: int) -> float:
    if level <= 1: return 0.0
    return (level - 1) * BONUS_PER_LEVEL

def get_pet_hourly_income(level: int) -> float:
    return BASE_INCOME * (1.5 ** (level - 1))

def get_xp_for_next(level: int) -> int:
    if level >= MAX_LEVEL: return 0
    return 300 + (level - 1) * 200

def get_xp_progress(xp: int, level: int) -> tuple:
    if level >= MAX_LEVEL: return (100, 100, 100)
    need = get_xp_for_next(level)
    percent = min(int((xp / need) * 100), 100)
    return (xp, need, percent)

def get_time_to_payout(clan_id: int) -> int:
    """Возвращает секунды до следующего начисления."""
    pet = get_clan_pet(clan_id)
    last = pet.get("last_tick") or int(time.time())
    elapsed = int(time.time()) - last
    left = PAYOUT_INTERVAL - elapsed
    return max(left, 0)

@tasks.loop(minutes=1)
async def pet_daily_payout_task(bot):
    """Раз в сутки начисляет доход питомца напрямую в копилку клана."""
    await bot.wait_until_ready()
    now = int(time.time())
    
    try:
        cycle = get_current_cycle()
        cycle_id = cycle["id"] if cycle else 0
        if not cycle_id:
            return # Нет активного сезона — не начисляем
            
        rows = cur.execute("SELECT * FROM clan_pets").fetchall()
        for r in rows:
            last = r["last_tick"] or now
            elapsed = now - last
            
            if elapsed >= PAYOUT_INTERVAL:
                # Защита от бесконечного накопления, если бот лежал неделю
                capped_elapsed = min(elapsed, PAYOUT_INTERVAL * 2) 
                hourly = get_pet_hourly_income(r["level"])
                earned = int(hourly * (capped_elapsed / 3600.0))
                
                if earned > 0:
                    cur.execute(
                        "INSERT INTO clan_contributions (cycle_id, clan_id, user_id, amount, reason, ts) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (cycle_id, r["clan_id"], 0, earned, "Ежедневный доход питомца", now)
                    )
                    logger.info(f"🐾 Питомец клана {r['clan_id']} накопил {earned} DC и отправил в копилку.")
                
                cur.execute("UPDATE clan_pets SET last_tick = ? WHERE clan_id = ?", (now, r["clan_id"]))
            
        db.commit()
    except Exception as e:
        logger.exception(f"pet_daily_payout_task: {e}")

async def feed_clan_pet(user_id: int, amount_dc: int) -> dict:
    clan = get_user_clan(user_id)
    if not clan: return {"ok": False, "error": "Ты не в клане."}
    if amount_dc < FEED_COST: return {"ok": False, "error": f"Минимум {FEED_COST} DC."}

    balance = get_dc_cache(user_id).get("balance", 0)
    if balance < amount_dc: return {"ok": False, "error": f"Не хватает DC. У тебя {balance}."}
        
    ok = await remove_dc(user_id, amount_dc, f"Кормление питомца клана {clan['name']}")
    if not ok: return {"ok": False, "error": "Ошибка списания."}

    xp_to_add = int((amount_dc / FEED_COST) * XP_PER_FEED)
    
    cur.execute("UPDATE clan_pets SET xp = xp + ?, total_fed = total_fed + ? WHERE clan_id = ?", (xp_to_add, amount_dc, clan["id"]))
    cur.execute("INSERT INTO clan_pet_feedings (clan_id, user_id, amount, ts) VALUES (?, ?, ?, ?)", (clan["id"], user_id, amount_dc, int(time.time())))
    db.commit()

    pet = get_clan_pet(clan["id"])
    leveled_up = False
    while pet["level"] < MAX_LEVEL and pet["xp"] >= get_xp_for_next(pet["level"]):
        cur.execute("UPDATE clan_pets SET level = level + 1 WHERE clan_id=?", (clan["id"],))
        db.commit()
        pet = get_clan_pet(clan["id"])
        leveled_up = True

    return {"ok": True, "xp_added": xp_to_add, "leveled_up": leveled_up, "new_level": pet["level"]}

def get_clan_pet_top(clan_id: int) -> List[dict]:
    rows = cur.execute("""
        SELECT user_id, SUM(amount) as total 
        FROM clan_pet_feedings 
        WHERE clan_id = ? 
        GROUP BY user_id 
        ORDER BY total DESC 
        LIMIT 5
    """, (clan_id,)).fetchall()
    
    from core.bot import bot
    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    
    result = []
    for r in rows:
        uid = r["user_id"]
        name = f"@{uid}"
        if guild:
            m = guild.get_member(uid)
            if m: name = m.display_name
        result.append({"user_id": uid, "username": name, "total": r["total"]})
    return result

def start_pet_tasks(bot):
    if not pet_daily_payout_task.is_running():
        pet_daily_payout_task.start(bot)
