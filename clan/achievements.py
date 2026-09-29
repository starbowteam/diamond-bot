# -*- coding: utf-8 -*-
"""Система достижений клан-лиги."""
import os
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict

import disnake

from core.utils import (
    CONFIG, logger, db, cur, load_json, save_json, log_discord,
)

from clan.core import (
    get_user_clan, get_user_contribution, get_current_cycle,
    get_clan_top, HARD_EXCLUDED_USERS,
)

# ============================================================
# КОНСТАНТЫ
# ============================================================
CREATOR_USER_ID = 796293832751972352  # 👑 только ты

# ============================================================
# ВСЕ ДОСТИЖЕНИЯ
# Порядок ВАЖЕН — топ-3 всегда в квадратах
# priority: чем меньше — тем выше в квадратах
# ============================================================
ACHIEVEMENTS: Dict[str, dict] = {
    # === 👑 СОЗДАТЕЛЬ ===
    "creator": {
        "name": "Создатель Diamond",
        "desc": "Основать Diamond Shop",
        "icon": "fa-crown",
        "color": "gold",
        "priority": 1,
        "rare": True,
    },

    # === 🏛 КЛАН-ТОПЫ ===
    "king": {
        "name": "Король сезона",
        "desc": "Топ-1 клана по итогам сезона",
        "icon": "fa-medal",
        "color": "gold",
        "priority": 2,
    },
    "legend": {
        "name": "Легенда",
        "desc": "Топ-1 в трёх сезонах подряд",
        "icon": "fa-star",
        "color": "purple",
        "priority": 3,
    },

    # === 🏁 БАЗОВЫЕ ===
    "newbie": {
        "name": "Новичок",
        "desc": "Зайти на сервер",
        "icon": "fa-seedling",
        "color": "green",
        "priority": 10,
    },
    "first_message": {
        "name": "Первое слово",
        "desc": "Первое сообщение в чате",
        "icon": "fa-comment",
        "color": "blue",
        "priority": 11,
    },
    "first_voice": {
        "name": "Голос",
        "desc": "Первый заход в голосовой канал",
        "icon": "fa-microphone",
        "color": "green",
        "priority": 12,
    },
    "first_review": {
        "name": "Первый отзыв",
        "desc": "Оставить первый отзыв",
        "icon": "fa-pen",
        "color": "gold",
        "priority": 13,
    },
    "first_purchase": {
        "name": "Первая покупка",
        "desc": "Купить что-то в магазине",
        "icon": "fa-cart-shopping",
        "color": "green",
        "priority": 14,
    },

    # === 🛍 ПОКУПАТЕЛИ ===
    "role_bronze": {
        "name": "Бронза",
        "desc": "Получить роль Bronze Buyer",
        "icon": "fa-medal",
        "color": "gold",
        "priority": 20,
    },
    "role_silver": {
        "name": "Серебро",
        "desc": "Получить роль Silver Buyer",
        "icon": "fa-medal",
        "color": "blue",
        "priority": 21,
    },
    "role_gold": {
        "name": "Золото",
        "desc": "Получить роль Gold Buyer",
        "icon": "fa-medal",
        "color": "gold",
        "priority": 22,
    },
    "role_diamond": {
        "name": "Алмаз",
        "desc": "Получить роль Diamond Buyer",
        "icon": "fa-gem",
        "color": "blue",
        "priority": 23,
    },
    "role_crystalis": {
        "name": "Кристалис",
        "desc": "Получить роль Crystalis Buyer",
        "icon": "fa-gem",
        "color": "purple",
        "priority": 24,
    },
    "role_pka": {
        "name": "Покупатель Века",
        "desc": "Получить роль PKA",
        "icon": "fa-crown",
        "color": "gold",
        "priority": 25,
    },
    "buyer_5": {
        "name": "Постоянный клиент",
        "desc": "5 покупок в магазине",
        "icon": "fa-bag-shopping",
        "color": "green",
        "priority": 26,
    },
    "buyer_25": {
        "name": "Опытный покупатель",
        "desc": "25 покупок в магазине",
        "icon": "fa-briefcase",
        "color": "blue",
        "priority": 27,
    },
    "buyer_100": {
        "name": "Мастер покупок",
        "desc": "100 покупок в магазине",
        "icon": "fa-trophy",
        "color": "gold",
        "priority": 28,
    },
    "buyer_500": {
        "name": "Легенда магазина",
        "desc": "500 покупок в магазине",
        "icon": "fa-diamond",
        "color": "purple",
        "priority": 29,
    },

    # === 💰 ЭКОНОМИКА ===
    "rich_10k": {
        "name": "Богач",
        "desc": "10 000 DC на балансе",
        "icon": "fa-sack-dollar",
        "color": "green",
        "priority": 30,
    },
    "rich_500k": {
        "name": "Полумиллионер",
        "desc": "500 000 DC на балансе",
        "icon": "fa-coins",
        "color": "gold",
        "priority": 31,
    },
    "rich_1m": {
        "name": "Миллионер",
        "desc": "1 000 000 DC на балансе",
        "icon": "fa-money-bill-wave",
        "color": "gold",
        "priority": 32,
    },
    "generous_10k": {
        "name": "Щедрый",
        "desc": "Подарить 10 000 DC другим",
        "icon": "fa-gift",
        "color": "red",
        "priority": 33,
    },
    "investor_5k": {
        "name": "Инвестор",
        "desc": "Потратить 5 000 DC в магазине",
        "icon": "fa-chart-line",
        "color": "blue",
        "priority": 34,
    },
    "investor_500k": {
        "name": "Банкир",
        "desc": "Потратить 500 000 DC в магазине",
        "icon": "fa-building-columns",
        "color": "gold",
        "priority": 35,
    },

    # === 💬 АКТИВНОСТЬ ===
    "talker_1k": {
        "name": "Болтун",
        "desc": "1 000 сообщений в чате",
        "icon": "fa-comments",
        "color": "blue",
        "priority": 40,
    },
    "talker_10k": {
        "name": "Спамер",
        "desc": "10 000 сообщений в чате",
        "icon": "fa-bullhorn",
        "color": "green",
        "priority": 41,
    },
    "talker_100k": {
        "name": "Легенда чата",
        "desc": "100 000 сообщений в чате",
        "icon": "fa-fire",
        "color": "red",
        "priority": 42,
    },
    "voice_100h": {
        "name": "Голос комьюнити",
        "desc": "100 часов в голосовых каналах",
        "icon": "fa-microphone",
        "color": "green",
        "priority": 43,
    },
    "voice_500h": {
        "name": "Голосовой маньяк",
        "desc": "500 часов в голосовых каналах",
        "icon": "fa-headphones",
        "color": "blue",
        "priority": 44,
    },
    "reviewer_50": {
        "name": "Рецензент",
        "desc": "50 отзывов оставлено",
        "icon": "fa-pen-fancy",
        "color": "gold",
        "priority": 45,
    },
    "reviewer_100": {
        "name": "Критик",
        "desc": "100 отзывов оставлено",
        "icon": "fa-scroll",
        "color": "purple",
        "priority": 46,
    },
    "reviewer_500": {
        "name": "Энциклопедия",
        "desc": "500 отзывов оставлено",
        "icon": "fa-book",
        "color": "gold",
        "priority": 47,
    },

    # === 🏛 КЛАНЫ ===
    "clan_first_deposit": {
        "name": "Первый вклад",
        "desc": "Внести первый DC в копилку",
        "icon": "fa-hand-holding-dollar",
        "color": "gold",
        "priority": 50,
    },
    "clan_1k": {
        "name": "Тысячник",
        "desc": "1 000 DC вклада за сезон",
        "icon": "fa-coins",
        "color": "green",
        "priority": 51,
    },
    "clan_5k": {
        "name": "Мега-вклад",
        "desc": "5 000 DC вклада за сезон",
        "icon": "fa-gem",
        "color": "blue",
        "priority": 52,
    },
    "clan_50k": {
        "name": "Клан-магнат",
        "desc": "50 000 DC вклада за сезон",
        "icon": "fa-crown",
        "color": "gold",
        "priority": 53,
    },
    "clan_loyal": {
        "name": "Лояльный",
        "desc": "7 дней подряд с вкладом",
        "icon": "fa-fire",
        "color": "red",
        "priority": 54,
    },
    "clan_hunter": {
        "name": "Охотник",
        "desc": "Обогнать 5 участников клана",
        "icon": "fa-crosshairs",
        "color": "green",
        "priority": 55,
    },
    "clan_sniper": {
        "name": "Снайпер",
        "desc": "Обогнать топ-1 в последние 24ч",
        "icon": "fa-bullseye",
        "color": "red",
        "priority": 56,
    },
    "clan_champion": {
        "name": "Чемпион",
        "desc": "Выиграть сезон вместе с кланом",
        "icon": "fa-trophy",
        "color": "gold",
        "priority": 57,
    },
    "clan_faithful": {
        "name": "Верный",
        "desc": "3 сезона в одном клане",
        "icon": "fa-shield-halved",
        "color": "blue",
        "priority": 58,
    },

    # === 🎰 КАЗИНО ===
    "casino_coin": {
        "name": "Орёл или решка",
        "desc": "Сыграть в монетку",
        "icon": "fa-coins",
        "color": "gold",
        "priority": 60,
    },
    "casino_bj21": {
        "name": "Двадцать одно",
        "desc": "Блэкджек с двух карт",
        "icon": "fa-spade",
        "color": "green",
        "priority": 61,
    },
    "casino_jackpot": {
        "name": "Джекпот",
        "desc": "Мега-джекпот в рулетке",
        "icon": "fa-dice",
        "color": "gold",
        "priority": 62,
    },
    "casino_100": {
        "name": "Азартный",
        "desc": "100 партий в казино",
        "icon": "fa-dice-five",
        "color": "red",
        "priority": 63,
    },
    "casino_1000": {
        "name": "Казино-магнат",
        "desc": "1 000 партий в казино",
        "icon": "fa-dice-six",
        "color": "purple",
        "priority": 64,
    },
    "casino_highroller": {
        "name": "Хайроллер",
        "desc": "Ставка 10 000 DC",
        "icon": "fa-money-bill-1-wave",
        "color": "gold",
        "priority": 65,
    },
    "casino_lucky": {
        "name": "Мистер Удача",
        "desc": "Выиграть 100 000 DC в казино",
        "icon": "fa-clover",
        "color": "green",
        "priority": 66,
    },

    # === 🎯 КВЕСТЫ ===
    "quest_first": {
        "name": "Первый квест",
        "desc": "Выполнить первый квест",
        "icon": "fa-check",
        "color": "green",
        "priority": 70,
    },
    "quest_50": {
        "name": "Квест-охотник",
        "desc": "50 квестов выполнено",
        "icon": "fa-list-check",
        "color": "blue",
        "priority": 71,
    },
    "quest_200": {
        "name": "Мастер квестов",
        "desc": "200 квестов выполнено",
        "icon": "fa-medal",
        "color": "gold",
        "priority": 72,
    },

    # === 👔 ПЕРСОНАЛ ===
    "staff_first_ticket": {
        "name": "Первый тикет",
        "desc": "Закрыть первый тикет",
        "icon": "fa-ticket",
        "color": "green",
        "priority": 80,
    },
    "staff_10_tickets": {
        "name": "Менеджер",
        "desc": "10 закрытых тикетов",
        "icon": "fa-briefcase",
        "color": "blue",
        "priority": 81,
    },
    "staff_100_tickets": {
        "name": "Топ-менеджер",
        "desc": "100 закрытых тикетов",
        "icon": "fa-trophy",
        "color": "gold",
        "priority": 82,
    },
    "staff_perfect": {
        "name": "Идеальный сервис",
        "desc": "10 тикетов с оценкой 5",
        "icon": "fa-star",
        "color": "gold",
        "priority": 83,
    },
    "staff_hr_5": {
        "name": "HR",
        "desc": "Привлечь 5 человек на сервер",
        "icon": "fa-user-plus",
        "color": "green",
        "priority": 84,
    },
    "staff_hr_50": {
        "name": "HR-легенда",
        "desc": "Привлечь 50 человек на сервер",
        "icon": "fa-users",
        "color": "purple",
        "priority": 85,
    },
    "staff_first_salary": {
        "name": "Первая зарплата",
        "desc": "Получить первую зарплату",
        "icon": "fa-sack-dollar",
        "color": "green",
        "priority": 86,
    },
    "staff_year": {
        "name": "Годовщина работы",
        "desc": "12 зарплат подряд",
        "icon": "fa-calendar-check",
        "color": "gold",
        "priority": 87,
    },
}


# ============================================================
# СОРТИРОВКА ПО ПРИОРИТЕТУ
# ============================================================
def _sorted_keys() -> List[str]:
    return sorted(ACHIEVEMENTS.keys(), key=lambda k: ACHIEVEMENTS[k].get("priority", 999))


# ============================================================
# РАБОТА С БД
# ============================================================
def has_achievement(user_id: int, ach_key: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM clan_achievements WHERE user_id=? AND ach_key=?",
        (user_id, ach_key)
    ).fetchone()
    return bool(row)


def get_user_achievements(user_id: int) -> List[str]:
    rows = cur.execute(
        "SELECT ach_key FROM clan_achievements WHERE user_id=? ORDER BY unlocked_at DESC",
        (user_id,)
    ).fetchall()
    return [r["ach_key"] for r in rows]


def get_user_achievements_sorted(user_id: int) -> List[str]:
    """Возвращает ключи достижений юзера, отсортированные по priority."""
    unlocked = set(get_user_achievements(user_id))
    return [k for k in _sorted_keys() if k in unlocked]


async def unlock_achievement(user_id: int, ach_key: str, bot=None, notify: bool = True) -> bool:
    """Выдаёт достижение, шлёт ЛС, логирует. Возвращает True если выдал."""
    if ach_key not in ACHIEVEMENTS:
        return False
    if has_achievement(user_id, ach_key):
        return False

    ach = ACHIEVEMENTS[ach_key]
    cycle = get_current_cycle()
    cycle_id = cycle["id"] if cycle else 0

    cur.execute(
        "INSERT INTO clan_achievements (user_id, ach_key, unlocked_at, season_id) "
        "VALUES (?, ?, ?, ?)",
        (user_id, ach_key, int(time.time()), cycle_id)
    )
    db.commit()

    logger.info(f"🏆 Достижение выдано: {user_id} → {ach['name']}")

    if notify and bot:
        asyncio.create_task(_send_achievement_dm(bot, user_id, ach_key))
        asyncio.create_task(log_discord(
            title="🏆 Достижение разблокировано",
            description=(
                f"> **Пользователь:** <@{user_id}>\n"
                f"> **Достижение:** {ach['name']}\n"
                f"> **Описание:** {ach['desc']}"
            ),
            color=0xffaa00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        ))

    return True


async def _send_achievement_dm(bot, user_id: int, ach_key: str):
    """ЛС о разблокировке достижения."""
    try:
        ach = ACHIEVEMENTS.get(ach_key)
        if not ach:
            return

        user = bot.get_user(user_id)
        if not user:
            try:
                user = await bot.fetch_user(user_id)
            except Exception:
                return
        if not user:
            return

        # Цвет эмбеда в зависимости от color
        color_map = {
            "gold":   0xf7c991,
            "green":  0x2ecc71,
            "blue":   0x6a9bd1,
            "purple": 0xb39ddb,
            "red":    0xff6b6b,
        }
        color = color_map.get(ach.get("color", "gold"), 0xf7c991)

        embed = disnake.Embed(
            title="🏆 Достижение разблокировано!",
            description=(
                f"**{ach['name']}**\n"
                f"> {ach['desc']}\n\n"
                f"Продолжай в том же духе! 💎"
            ),
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Посмотреть все достижения — в профиле")

        await user.send(embed=embed)
    except disnake.Forbidden:
        logger.debug(f"ЛС закрыты у {user_id}")
    except Exception as e:
        logger.warning(f"_send_achievement_dm {user_id}: {e}")


# ============================================================
# ВЫДАЧА ПО УСЛОВИЯМ
# ============================================================
async def check_and_unlock(user_id: int, trigger: str, value: int = 0, bot=None, **kwargs) -> List[str]:
    """
    Проверяет условия и выдаёт достижения.
    trigger — тип события: message, voice, purchase, review, deposit, casino, quest, salary...
    value — числовое значение (например, общее число сообщений)
    Возвращает список выданных ключей.
    """
    unlocked = []

    def _try(key):
        if key in ACHIEVEMENTS and not has_achievement(user_id, key):
            unlocked.append(key)

    if trigger == "first_message":
        _try("first_message")
    elif trigger == "first_voice":
        _try("first_voice")
    elif trigger == "first_purchase":
        _try("first_purchase")
    elif trigger == "first_review":
        _try("first_review")
    elif trigger == "creator" and user_id == CREATOR_USER_ID:
        _try("creator")

    # Числовые триггеры
    elif trigger == "buyer_count":
        if value >= 5:   _try("buyer_5")
        if value >= 25:  _try("buyer_25")
        if value >= 100: _try("buyer_100")
        if value >= 500: _try("buyer_500")
    elif trigger == "balance":
        if value >= 10_000:    _try("rich_10k")
        if value >= 500_000:   _try("rich_500k")
        if value >= 1_000_000: _try("rich_1m")
    elif trigger == "messages":
        if value >= 1_000:   _try("talker_1k")
        if value >= 10_000:  _try("talker_10k")
        if value >= 100_000: _try("talker_100k")
    elif trigger == "voice_hours":
        if value >= 100: _try("voice_100h")
        if value >= 500: _try("voice_500h")
    elif trigger == "reviews":
        if value >= 1:   _try("first_review")
        if value >= 50:  _try("reviewer_50")
        if value >= 100: _try("reviewer_100")
        if value >= 500: _try("reviewer_500")
    elif trigger == "clan_deposit":
        if value >= 1:      _try("clan_first_deposit")
        if value >= 1_000:  _try("clan_1k")
        if value >= 5_000:  _try("clan_5k")
        if value >= 50_000: _try("clan_50k")
    elif trigger == "casino_games":
        if value >= 1:    _try("casino_coin")
        if value >= 100:  _try("casino_100")
        if value >= 1000: _try("casino_1000")
    elif trigger == "casino_bet":
        if value >= 10_000: _try("casino_highroller")
    elif trigger == "casino_win_total":
        if value >= 100_000: _try("casino_lucky")
    elif trigger == "gift_total":
        if value >= 10_000: _try("generous_10k")
    elif trigger == "shop_spent":
        if value >= 5_000:   _try("investor_5k")
        if value >= 500_000: _try("investor_500k")
    elif trigger == "quests":
        if value >= 1:   _try("quest_first")
        if value >= 50:  _try("quest_50")
        if value >= 200: _try("quest_200")
    elif trigger == "role":
        role_key = kwargs.get("role_key")
        role_map = {
            "bronze":    "role_bronze",
            "silver":    "role_silver",
            "gold":      "role_gold",
            "diamond":   "role_diamond",
            "crystalis": "role_crystalis",
            "pka":       "role_pka",
        }
        if role_key in role_map:
            _try(role_map[role_key])
    elif trigger == "staff_tickets":
        if value >= 1:   _try("staff_first_ticket")
        if value >= 10:  _try("staff_10_tickets")
        if value >= 100: _try("staff_100_tickets")
    elif trigger == "staff_salary":
        _try("staff_first_salary")

    # Выдаём всё что нашли
    for key in unlocked:
        await unlock_achievement(user_id, key, bot=bot)

    return unlocked


# ============================================================
# ФОРМАТИРОВАНИЕ ДЛЯ ПРОФИЛЯ
# ============================================================
def get_profile_slots(user_id: int, total_slots: int = 6) -> Dict:
    """
    Возвращает данные для профиля:
      - squares: топ-3 ключа (разблокированные приоритетно, добор заблокированными)
      - rows: 3 ключа для строк
      - more_count: сколько ещё скрыто
      - total_unlocked: всего разблокировано
      - total_all: всего достижений
    """
    unlocked_set = set(get_user_achievements(user_id))
    sorted_all = _sorted_keys()

    unlocked_sorted = [k for k in sorted_all if k in unlocked_set]
    locked_sorted = [k for k in sorted_all if k not in unlocked_set]

    # Формируем 6 слотов: сначала все разблокированные, потом заблокированные
    slots = unlocked_sorted[:total_slots]
    if len(slots) < total_slots:
        slots += locked_sorted[:total_slots - len(slots)]

    squares = slots[:3]
    rows = slots[3:6]

    more_count = max(0, len(unlocked_sorted) - total_slots)

    return {
        "squares": squares,
        "rows": rows,
        "more_count": more_count,
        "total_unlocked": len(unlocked_sorted),
        "total_all": len(ACHIEVEMENTS),
        "unlocked_set": unlocked_set,
    }


# ============================================================
# ПЕРЕСЧЁТ ВСЕХ
# ============================================================
async def recalculate_all_achievements(bot) -> Dict[str, int]:
    """
    Прогоняет всех юзеров сервера, проверяет условия, выдаёт недостающие.
    Возвращает статистику.
    """
    from clan.core import (
        get_clan, get_all_clans, get_user_clan,
    )
    from modules.dc import get_dc_cache

    stats = {
        "checked": 0,
        "new_unlocked": 0,
        "errors": 0,
    }

    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        logger.warning("recalculate_all_achievements: guild not found")
        return stats

    # Загружаем вспомогательные данные
    review_counts = load_json("data/review_counts.json", {})
    catalog = load_json("data/shop_catalog.json", {})

    # Собираем статистику по каждому юзеру
    for member in guild.members:
        if member.bot:
            continue
        if member.id in HARD_EXCLUDED_USERS and member.id != CREATOR_USER_ID:
            continue

        stats["checked"] += 1
        uid = member.id

        try:
            # --- БАЗОВЫЕ ---
            if member.id == CREATOR_USER_ID:
                await unlock_achievement(uid, "creator", bot=bot, notify=False)

            # --- РОЛИ ПОКУПАТЕЛЯ ---
            from core.utils import CONFIG as CFG
            role_ids = CFG["ROLE_IDS"]
            if member.get_role(role_ids["bronze"]):
                await unlock_achievement(uid, "role_bronze", bot=bot, notify=False)
            if member.get_role(role_ids["silver"]):
                await unlock_achievement(uid, "role_silver", bot=bot, notify=False)
            if member.get_role(role_ids["gold"]):
                await unlock_achievement(uid, "role_gold", bot=bot, notify=False)
            if member.get_role(role_ids["diamond"]):
                await unlock_achievement(uid, "role_diamond", bot=bot, notify=False)
            if member.get_role(role_ids["crystalis"]):
                await unlock_achievement(uid, "role_crystalis", bot=bot, notify=False)
            if member.get_role(role_ids["pka"]):
                await unlock_achievement(uid, "role_pka", bot=bot, notify=False)

            # --- БАЛАНС ---
            dc_data = get_dc_cache(uid)
            balance = dc_data.get("balance", 0)
            await check_and_unlock(uid, "balance", value=balance, bot=bot)

            # --- ПОКУПКИ ---
            purchases = dc_data.get("purchases", [])
            if purchases:
                await unlock_achievement(uid, "first_purchase", bot=bot, notify=False)
            await check_and_unlock(uid, "buyer_count", value=len(purchases), bot=bot)

            # --- ОТЗЫВЫ ---
            review_count = review_counts.get(str(uid), 0)
            await check_and_unlock(uid, "reviews", value=review_count, bot=bot)

            # --- КЛАН ---
            user_clan = get_user_clan(uid)
            if user_clan:
                contrib = get_user_contribution(uid)
                await check_and_unlock(uid, "clan_deposit", value=contrib, bot=bot)

        except Exception as e:
            logger.exception(f"recalculate {uid}: {e}")
            stats["errors"] += 1
            continue

    # Считаем сколько новых выдано
    for member in guild.members:
        if member.bot:
            continue
        cnt = len(get_user_achievements(member.id))
        stats["new_unlocked"] += cnt

    logger.info(f"🏆 Пересчёт достижений: {stats}")

    # Одна итоговая ЛС не нужна — каждое достижение само шлёт ЛС

    return stats


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
def init_achievements():
    """Заглушка для симметрии."""
    pass
