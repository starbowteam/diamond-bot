# -*- coding: utf-8 -*-
"""
Ядро кланового питомца ("Душа клана").
Включает миграцию старых личных питомцев с выплатой компенсации.
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
FEED_COST = 100# 1000 DC = 100 XP
XP_PER_FEED = 100
FEED_COOLDOWN = 0 # Пока без кулдауна на кормление, можно спамить если есть DC

# Бонус за уровень (например, 3% за каждый уровень выше 1-го)
BONUS_PER_LEVEL = 0.03 

CLAN_PETS = {
    1: {"name": "Грифон", "fa": 0xf520},       # Мультяшности
    2: {"name": "Ночная Сова", "fa": 0xf4ba},  # Сияние
    3: {"name": "Кристальный Дракон", "fa": 0xf3a5} # Кристализация
}

# ============================================================
# ИНИЦИАЛИЗАЦИЯ И МИГРАЦИЯ
# ============================================================
def init_pet_tables():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS clan_pets (
        clan_id    INTEGER PRIMARY KEY,
        level      INTEGER DEFAULT 1,
        xp         INTEGER DEFAULT 0,
        total_fed  INTEGER DEFAULT 0
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
    
    # Создаем питомцев для всех кланов, если их нет
    for cid in CLAN_PETS.keys():
        cur.execute("INSERT OR IGNORE INTO clan_pets (clan_id) VALUES (?)", (cid,))
    db.commit()

async def migrate_old_pets():
    """Одноразовая миграция: выдача компенсации за старых питомцев и их удаление."""
    try:
        # Проверяем, существует ли старая таблица
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_pets'")
        if not cur.fetchone():
            return # Миграция уже проведена или таблицы не было
            
        rows = cur.execute("SELECT user_id, pet_key FROM user_pets").fetchall()
        if not rows:
            cur.execute("DROP TABLE user_pets")
            db.commit()
            return

        PRICES = {
            "cat_ginger": 300, "hamster": 450, "fox": 600, "raccoon": 750, "owl": 900, "penguin": 1050,
            "griffin": 1200, "wolf": 1600, "dragon": 2000, "phoenix": 3000, "diamond_pet": 5000, "crystal_dragon": 7500
        }
        
        user_pets_map = {}
        for r in rows:
            uid = r["user_id"]
            if uid not in user_pets_map:
                user_pets_map[uid] = []
            user_pets_map[uid].append(r["pet_key"])
            
        logger.info(f"🐾 Начинаю миграцию питомцев: найдено {len(user_pets_map)} юзеров со старыми питомцами.")
        
        for uid, pets in user_pets_map.items():
            # Считаем сколько потрачено на кормление из истории
            hist = get_dc_cache(uid).get("history", [])
            total_fed = sum(abs(h["amount"]) for h in hist if "Кормление" in h.get("reason", ""))
            
            total_comp = 0
            for p_key in pets:
                price = PRICES.get(p_key, 0)
                total_comp += price + 50 # 50 DC за удаление каждого
            
            total_comp += total_fed
            
            if total_comp > 0:
                await add_dc(
                    uid, total_comp,
                    "Компенсация за удаление личных питомцев (цена + кормление + 50 DC)",
                    notify=True, log=False
                )
                
                # Уведомление в ЛС
                try:
                    from core.bot import bot
                    user = bot.get_user(uid) or await bot.fetch_user(uid)
                    if user:
                        await user.send(
                            f"🐾 **Твои личные питомцы были удалены.**\n"
                            f"В связи с переходом на новую систему «Душа Клана», "
                            f"тебе начислена компенсация: **+{total_comp} DC**.\n"
                            f"> Формула: цена питомцев + затраты на кормление + 50 DC за удаление."
                        )
                except Exception as e:
                    logger.debug(f"migrate DM: {e}")
                    
            await asyncio.sleep(0.2)

        # Удаляем старую таблицу
        cur.execute("DROP TABLE user_pets")
        cur.execute("DROP TABLE IF EXISTS pet_xp_log")
        cur.execute("DROP TABLE IF EXISTS pet_purchases")
        cur.execute("DROP TABLE IF EXISTS pet_active_cooldown")
        db.commit()
        logger.info("🐾 Миграция личных питомцев успешно завершена. Таблицы удалены.")
        
    except Exception as e:
        logger.exception(f"migrate_old_pets: {e}")

# ============================================================
# ЛОГИКА КЛАНОВОГО ПИТОМЦА
# ============================================================
def get_clan_pet(clan_id: int) -> dict:
    row = cur.execute("SELECT * FROM clan_pets WHERE clan_id=?", (clan_id,)).fetchone()
    if not row:
        cur.execute("INSERT OR IGNORE INTO clan_pets (clan_id) VALUES (?)", (clan_id,))
        db.commit()
        row = cur.execute("SELECT * FROM clan_pets WHERE clan_id=?", (clan_id,)).fetchone()
    return dict(row)

def get_pet_name(clan_id: int) -> str:
    return CLAN_PETS.get(clan_id, {}).get("name", "Неизвестный")

def get_pet_fa(clan_id: int) -> int:
    return CLAN_PETS.get(clan_id, {}).get("fa", 0xf3a5)

def get_pet_bonus(level: int) -> float:
    if level <= 1:
        return 0.0
    return (level - 1) * BONUS_PER_LEVEL

def get_xp_for_next(level: int) -> int:
    if level >= MAX_LEVEL:
        return 0
    return level * 5000

def get_xp_progress(xp: int, level: int) -> tuple:
    if level >= MAX_LEVEL:
        return (100, 100, 100)
    need = get_xp_for_next(level)
    percent = min(int((xp / need) * 100), 100)
    return (xp, need, percent)

async def feed_clan_pet(user_id: int, amount_dc: int) -> dict:
    """Кормление кланового питомца."""
    clan = get_user_clan(user_id)
    if not clan:
        return {"ok": False, "error": "Ты не в клане."}
        
    if amount_dc < FEED_COST:
        return {"ok": False, "error": f"Минимум {FEED_COST} DC."}

    balance = get_dc_cache(user_id).get("balance", 0)
    if balance < amount_dc:
        return {"ok": False, "error": f"Не хватает DC. У тебя {balance}."}
        
    # Списываем
    ok = await remove_dc(user_id, amount_dc, f"Кормление питомца клана {clan['name']}")
    if not ok:
        return {"ok": False, "error": "Ошибка списания."}

    xp_to_add = int((amount_dc / FEED_COST) * XP_PER_FEED)
    
    # Начисляем
    cur.execute("""
        UPDATE clan_pets 
        SET xp = xp + ?, total_fed = total_fed + ? 
        WHERE clan_id = ?
    """, (xp_to_add, amount_dc, clan["id"]))
    
    cur.execute("""
        INSERT INTO clan_pet_feedings (clan_id, user_id, amount, ts)
        VALUES (?, ?, ?, ?)
    """, (clan["id"], user_id, amount_dc, int(time.time())))
    db.commit()

    # Проверка левел-апа
    pet = get_clan_pet(clan["id"])
    leveled_up = False
    while pet["level"] < MAX_LEVEL and pet["xp"] >= get_xp_for_next(pet["level"]):
        cur.execute("UPDATE clan_pets SET level = level + 1 WHERE clan_id=?", (clan["id"],))
        db.commit()
        pet = get_clan_pet(clan["id"])
        leveled_up = True

    await log_discord(
        title="🍖 Кормление питомца",
        description=f"> **Юзер:** <@{user_id}>\n> **Клан:** {clan['name']}\n> **Сумма:** `{amount_dc} DC`\n> **XP:** `+{xp_to_add}`",
        color=0xffaa00,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return {"ok": True, "xp_added": xp_to_add, "leveled_up": leveled_up, "new_level": pet["level"]}

def get_clan_pet_top(clan_id: int) -> List[dict]:
    """Топ кормильцев для конкретного клана."""
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
            
        result.append({
            "user_id": uid,
            "username": name,
            "total": r["total"]
        })
    return result
