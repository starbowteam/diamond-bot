# -*- coding: utf-8 -*-
"""Общий модуль каталога Автозаказа. Автосоздаёт файл если его нет."""
import os
import json
from typing import Dict

from core.utils import DATA_DIR, logger, db, cur

CATALOG_PATH = os.path.join(DATA_DIR, "autoorder_catalog.json")

DEFAULT_CATALOG = {
    "discord": {
        "label": "Discord",
        "items": [
            {"id": "discord_nitro_1m", "name": "Nitro 1 Month", "price": 460, "unit": None, "min": 1, "max": 1},
            {"id": "discord_nitro_12m", "name": "Nitro 12 Month", "price": 4410, "unit": None, "min": 1, "max": 1},
            {"id": "discord_nitro_basic_1m", "name": "Nitro Basic 1 Month", "price": 300, "unit": None, "min": 1, "max": 1},
            {"id": "discord_nitro_basic_12m", "name": "Nitro Basic 12 Month", "price": 1550, "unit": None, "min": 1, "max": 1},
            {"id": "discord_nitro_gift_basic", "name": "Nitro Gift Basic", "price": 590, "unit": None, "min": 1, "max": 1},
            {"id": "discord_nitro_gift_full", "name": "Nitro Gift Full", "price": 790, "unit": None, "min": 1, "max": 1},
            {"id": "discord_nitro_trial_1m", "name": "Nitro Trial 1 Month", "price": 160, "unit": None, "min": 1, "max": 1},
            {"id": "discord_nitro_trial_3m", "name": "Nitro Trial 3 Month", "price": 260, "unit": None, "min": 1, "max": 1},
            {"id": "discord_nitro_activation", "name": "Nitro Activation", "price": 100, "unit": None, "min": 1, "max": 1},
            {"id": "discord_boosts_1w", "name": "Boosts 1 Week", "price": 35, "unit": "шт", "min": 1, "max": 14},
            {"id": "discord_boosts_1m", "name": "Boosts 1 Month", "price": 45, "unit": "шт", "min": 1, "max": 14},
            {"id": "discord_boosts_3m", "name": "Boosts 3 Month", "price": 90, "unit": "шт", "min": 1, "max": 14},
        ]
    },
    "steam": {
        "label": "Steam",
        "items": [
            {"id": "steam_rub", "name": "Пополнение Steam (RUB)", "price": 1.1, "unit": "₽", "min": 100, "max": 50000},
            {"id": "steam_kzt", "name": "Пополнение Steam (KZT)", "price": 0.298, "unit": "₸", "min": 100, "max": 50000},
            {"id": "steam_uah", "name": "Пополнение Steam (UAH)", "price": 2.5, "unit": "₴", "min": 100, "max": 50000},
            {"id": "steam_region_250", "name": "Смена региона (старый)", "price": 250, "unit": None, "min": 1, "max": 1},
            {"id": "steam_region_200", "name": "Смена региона (новый)", "price": 200, "unit": None, "min": 1, "max": 1},
        ]
    },
    "telegram": {
        "label": "Telegram",
        "items": [
            {"id": "tg_stars", "name": "Звёзды Telegram", "price": 1.58, "unit": "шт", "min": 50, "max": 3000},
            {"id": "tg_acc_clean", "name": "Аккаунт (без спама)", "price": 250, "unit": None, "min": 1, "max": 1},
            {"id": "tg_acc_spam", "name": "Аккаунт (спам-блок)", "price": 190, "unit": None, "min": 1, "max": 1},
        ]
    },
    "roblox": {
        "label": "Roblox",
        "items": [
            {"id": "roblox_robux", "name": "Robux", "price": 0.82, "unit": "шт", "min": 100, "max": 10000},
            {"id": "roblox_plus_trial", "name": "Roblox Plus Trial", "price": 90, "unit": None, "min": 1, "max": 1},
            {"id": "roblox_plus_500", "name": "Roblox Plus +500", "price": 1300, "unit": None, "min": 1, "max": 1},
            {"id": "roblox_plus_1000", "name": "Roblox Plus +1000", "price": 1700, "unit": None, "min": 1, "max": 1},
        ]
    },
    "spotify": {
        "label": "Spotify",
        "items": [
            {"id": "spotify_individual", "name": "Spotify Individual", "price": 270, "unit": None, "min": 1, "max": 1},
        ]
    },
    "decoration": {
        "label": "Украшения Discord",
        "items": [
            {"id": "decor_profile", "name": "Украшение профиля", "price": 200, "unit": None, "min": 1, "max": 1},
            {"id": "decor_sets", "name": "Наборы Discord", "price": 420, "unit": None, "min": 1, "max": 1},
            {"id": "decor_badges", "name": "Бейджики Discord", "price": 200, "unit": None, "min": 1, "max": 1},
        ]
    },
}


def ensure_catalog_file() -> bool:
    """Создаёт autoorder_catalog.json с дефолтными товарами если его нет."""
    if os.path.exists(CATALOG_PATH):
        return True
    try:
        with open(CATALOG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CATALOG, f, ensure_ascii=False, indent=2)
        logger.info(f"📦 Создан дефолтный каталог: {CATALOG_PATH}")
        return True
    except Exception as e:
        logger.exception(f"ensure_catalog_file: {e}")
        return False


def load_catalog_from_db() -> Dict[str, dict]:
    rows = cur.execute(
        "SELECT * FROM autoorder_catalog ORDER BY category, name"
    ).fetchall()
    result: Dict[str, dict] = {}
    for r in rows:
        cat = r["category"]
        if cat not in result:
            result[cat] = {"label": cat, "items": []}
        result[cat]["items"].append({
            "id": r["id"], "name": r["name"], "price": r["price"],
            "unit": r["unit"], "min": r["min_qty"], "max": r["max_qty"],
        })
    return result


def reload_catalog_from_json() -> int:
    """Читает autoorder_catalog.json → пишет в БД. Возвращает кол-во товаров."""
    ensure_catalog_file()

    if not os.path.exists(CATALOG_PATH):
        logger.warning(f"Каталог не найден: {CATALOG_PATH}")
        return 0

    try:
        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.exception(f"Ошибка чтения каталога: {e}")
        return 0

    cur.execute("DELETE FROM autoorder_catalog")
    count = 0
    for cat_key, cat in data.items():
        label = cat.get("label", cat_key)
        for item in cat.get("items", []):
            cur.execute(
                "INSERT INTO autoorder_catalog (id, category, name, price, unit, min_qty, max_qty) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item["id"], label, item["name"], float(item["price"]),
                 item.get("unit"), int(item.get("min", 1)), int(item.get("max", 1))),
            )
            count += 1
    db.commit()
    logger.info(f"📦 Каталог загружен: {count} товаров в {len(data)} категориях")
    return count


def auto_init():
    """Полная инициализация: создать файл (если нет) + загрузить в БД."""
    ensure_catalog_file()
    existing = cur.execute("SELECT COUNT(*) as c FROM autoorder_catalog").fetchone()
    if not existing or existing["c"] == 0:
        return reload_catalog_from_json()
    return existing["c"]
