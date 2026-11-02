# -*- coding: utf-8 -*-
"""Ядро кланового питомца ("Душа клана")."""
import time
from typing import List
from disnake.ext import tasks
from core.utils import CONFIG, logger, db, cur
from modules.dc import remove_dc
from clan.core import get_user_clan, get_current_cycle

MAX_LEVEL = 10
FEED_COST = 1
XP_PER_FEED = 1
BONUS_PER_LEVEL = 0.03
BASE_INCOME = 30.0
PAYOUT_INTERVAL = 86400
CASINO_BONUS_BY_LEVEL, CLAN_BONUS_BY_LEVEL, REVIEW_BONUS_BY_LEVEL = 1.05, 1.10, 1.15
CASINO_BONUS_MIN_LEVEL, CLAN_BONUS_MIN_LEVEL, REVIEW_BONUS_MIN_LEVEL = 5, 7, 9
CLAN_PETS = {1: {"name": "Грифон", "fa": 0xf520}, 2: {"name": "Ночная Сова", "fa": 0xf4ba}, 3: {"name": "Кристальный Дракон", "fa": 0xf3a5}}

def init_pet_tables():
    cur.executescript("CREATE TABLE IF NOT EXISTS clan_pets (clan_id INTEGER PRIMARY KEY, level INTEGER DEFAULT 1, xp INTEGER DEFAULT 0, total_fed INTEGER DEFAULT 0, last_tick INTEGER DEFAULT 0); CREATE TABLE IF NOT EXISTS clan_pet_feedings (id INTEGER PRIMARY KEY AUTOINCREMENT, clan_id INTEGER, user_id INTEGER, amount INTEGER, ts INTEGER); CREATE INDEX IF NOT EXISTS idx_cp_feed_clan ON clan_pet_feedings (clan_id);")
    db.commit()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(clan_pets)").fetchall()]
    if "last_tick" not in cols:
        try: cur.execute("ALTER TABLE clan_pets ADD COLUMN last_tick INTEGER DEFAULT 0"); db.commit()
        except Exception as e: logger.error(f"Ошибка миграции last_tick: {e}")
    for cid in CLAN_PETS.keys(): cur.execute("INSERT OR IGNORE INTO clan_pets (clan_id, last_tick) VALUES (?, ?)", (cid, int(time.time())))
    db.commit()

def get_clan_pet(clan_id: int) -> dict:
    row = cur.execute("SELECT * FROM clan_pets WHERE clan_id=?", (clan_id,)).fetchone()
    if not row:
        cur.execute("INSERT OR IGNORE INTO clan_pets (clan_id, last_tick) VALUES (?, ?)", (clan_id, int(time.time()))); db.commit()
        row = cur.execute("SELECT * FROM clan_pets WHERE clan_id=?", (clan_id,)).fetchone()
    return dict(row)

def get_pet_name(clan_id: int) -> str: return CLAN_PETS.get(clan_id, {}).get("name", "Неизвестный")
def get_pet_fa(clan_id: int) -> int: return CLAN_PETS.get(clan_id, {}).get("fa", 0xf3a5)
def get_pet_bonus(level: int) -> float: return 0.0 if level <= 1 else (level - 1) * BONUS_PER_LEVEL
def get_pet_hourly_income(level: int) -> float: return BASE_INCOME * (1.5 ** (level - 1))
def get_xp_for_next(level: int) -> int: return 0 if level >= MAX_LEVEL else 300 + (level - 1) * 200
def get_xp_progress(xp: int, level: int) -> tuple: return (100, 100, 100) if level >= MAX_LEVEL else (xp, get_xp_for_next(level), min(int((xp / get_xp_for_next(level)) * 100), 100))
def get_time_to_payout(clan_id: int) -> int: return max(PAYOUT_INTERVAL - (int(time.time()) - (get_clan_pet(clan_id).get("last_tick") or int(time.time()))), 0)

def get_casino_bonus(user_id: int) -> float:
    try: return CASINO_BONUS_BY_LEVEL if get_clan_pet(get_user_clan(user_id)["id"])["level"] >= CASINO_BONUS_MIN_LEVEL else 1.0
    except Exception: return 1.0
def get_clan_bonus(user_id: int) -> float:
    try: return CLAN_BONUS_BY_LEVEL if get_clan_pet(get_user_clan(user_id)["id"])["level"] >= CLAN_BONUS_MIN_LEVEL else 1.0
    except Exception: return 1.0
def get_review_bonus(user_id: int) -> float:
    try: return REVIEW_BONUS_BY_LEVEL if get_clan_pet(get_user_clan(user_id)["id"])["level"] >= REVIEW_BONUS_MIN_LEVEL else 1.0
    except Exception: return 1.0

async def add_pet_xp(user_id: int, amount: int, source: str = "action") -> bool:
    try:
        clan = get_user_clan(user_id)
        if not clan or amount <= 0: return False
        cur.execute("UPDATE clan_pets SET xp = xp + ? WHERE clan_id = ?", (amount, clan["id"])); db.commit()
        pet = get_clan_pet(clan["id"])
        while pet["level"] < MAX_LEVEL and pet["xp"] >= get_xp_for_next(pet["level"]):
            cur.execute("UPDATE clan_pets SET level = level + 1 WHERE clan_id=?", (clan["id"],)); db.commit(); pet = get_clan_pet(clan["id"])
        return True
    except Exception as e: logger.warning(f"add_pet_xp {user_id}: {e}"); return False

@tasks.loop(minutes=1)
async def pet_daily_payout_task(bot):
    await bot.wait_until_ready(); now = int(time.time())
    try:
        cycle = get_current_cycle(); cycle_id = cycle["id"] if cycle else 0
        if not cycle_id: return
        for r in cur.execute("SELECT * FROM clan_pets").fetchall():
            elapsed = now - (r["last_tick"] or now)
            if elapsed >= PAYOUT_INTERVAL:
                earned = int(get_pet_hourly_income(r["level"]) * (min(elapsed, PAYOUT_INTERVAL * 2) / 3600.0))
                if earned > 0:
                    cur.execute("INSERT INTO clan_contributions (cycle_id, clan_id, user_id, amount, reason, ts) VALUES (?, ?, ?, ?, ?, ?)", (cycle_id, r["clan_id"], 0, earned, "Доход питомца", now))
                cur.execute("UPDATE clan_pets SET last_tick = ? WHERE clan_id = ?", (now, r["clan_id"]))
        db.commit()
    except Exception as e: logger.exception(f"pet_daily: {e}")

async def feed_clan_pet(user_id: int, amount_dc: int) -> dict:
    clan = get_user_clan(user_id)
    if not clan: return {"ok": False, "error": "Ты не в клане."}
    from core.utils import get_dc_cache
    if get_dc_cache(user_id).get("balance", 0) < amount_dc: return {"ok": False, "error": "Не хватает DC."}
    if not await remove_dc(user_id, amount_dc, f"Кормление питомца {clan['name']}"): return {"ok": False, "error": "Ошибка списания."}
    
    xp_to_add = int(amount_dc * XP_PER_FEED)
    cur.execute("UPDATE clan_pets SET xp = xp + ?, total_fed = total_fed + ? WHERE clan_id = ?", (xp_to_add, amount_dc, clan["id"]))
    cur.execute("INSERT INTO clan_pet_feedings (clan_id, user_id, amount, ts) VALUES (?, ?, ?, ?)", (clan["id"], user_id, amount_dc, int(time.time()))); db.commit()
    
    pet, leveled_up = get_clan_pet(clan["id"]), False
    while pet["level"] < MAX_LEVEL and pet["xp"] >= get_xp_for_next(pet["level"]):
        cur.execute("UPDATE clan_pets SET level = level + 1 WHERE clan_id=?", (clan["id"],)); db.commit(); pet = get_clan_pet(clan["id"]); leveled_up = True
    return {"ok": True, "xp_added": xp_to_add, "leveled_up": leveled_up, "new_level": pet["level"]}

def get_clan_pet_top(clan_id: int) -> List[dict]:
    from core.bot import bot; guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    return [{"user_id": r["user_id"], "username": (guild.get_member(r["user_id"]).display_name if guild and guild.get_member(r["user_id"]) else f"@{r['user_id']}"), "total": r["total"]} for r in cur.execute("SELECT user_id, SUM(amount) as total FROM clan_pet_feedings WHERE clan_id = ? GROUP BY user_id ORDER BY total DESC LIMIT 5", (clan_id,)).fetchall()]

def start_pet_tasks(bot):
    if not pet_daily_payout_task.is_running(): pet_daily_payout_task.start(bot)
