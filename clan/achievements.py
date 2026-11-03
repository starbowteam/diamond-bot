# -*- coding: utf-8 -*-
"""
Система достижений клан-лиги.

48 достижений, 8 категорий по 6 штук.
Категории = страницы в панели достижений (см. modules/achievements_panel.py).
"""
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict

import disnake

from core.utils import (
    CONFIG, logger, db, cur, load_json, save_json, log_discord,
)

from clan.core import get_current_cycle


# ============================================================
# КОНСТАНТЫ
# ============================================================
CREATOR_USER_ID = 796293832751972352  # 👑 основатель


# ============================================================
# КАТЕГОРИИ — порядок = порядок страниц в панели
# ============================================================
CATEGORIES: List[dict] = [
    {
        "key": "base",
        "label": "Базовые",
        "icon": "fa-star",
        "color": "green",
    },
    {
        "key": "buyers",
        "label": "Покупатели",
        "icon": "fa-bag-shopping",
        "color": "silver",
    },
    {
        "key": "economy",
        "label": "Экономика",
        "icon": "fa-coins",
        "color": "gold",
    },
    {
        "key": "activity",
        "label": "Активность",
        "icon": "fa-comments",
        "color": "blue",
    },
    {
        "key": "clan",
        "label": "Кланы",
        "icon": "fa-shield-halved",
        "color": "purple",
    },
    {
        "key": "casino",
        "label": "Казино",
        "icon": "fa-dice",
        "color": "red",
    },
    {
        "key": "quests",
        "label": "Квесты",
        "icon": "fa-list-check",
        "color": "orange",
    },
    {
        "key": "staff",
        "label": "Персонал",
        "icon": "fa-briefcase",
        "color": "steel",
    },
]

CATEGORY_ORDER: List[str] = [c["key"] for c in CATEGORIES]


# ============================================================
# ДОСТИЖЕНИЯ — 48 штук
# Порядок в словаре = порядок в сетке внутри категории.
# Иконки — fa-solid (900.ttf).
# ============================================================
ACHIEVEMENTS: Dict[str, dict] = {

    # ─────────── 🏁 БАЗОВЫЕ ───────────
    "newbie": {
        "name": "Новичок",
        "desc": "Зайти на сервер впервые",
        "icon": "fa-seedling",
        "category": "base",
        "rare": False,
    },
    "first_message": {
        "name": "Первое слово",
        "desc": "Написать первое сообщение в чате",
        "icon": "fa-comment",
        "category": "base",
    },
    "first_voice": {
        "name": "Голос",
        "desc": "Зайти в голосовой канал впервые",
        "icon": "fa-microphone",
        "category": "base",
    },
    "first_review": {
        "name": "Первый отзыв",
        "desc": "Оставить первый отзыв в канале",
        "icon": "fa-pen-fancy",
        "category": "base",
    },
    "first_purchase": {
        "name": "Первая покупка",
        "desc": "Купить товар в магазине за DC",
        "icon": "fa-cart-shopping",
        "category": "base",
    },
    "creator": {
        "name": "Создатель Diamond",
        "desc": "Основать Diamond Shop",
        "icon": "fa-crown",
        "category": "base",
        "rare": True,
    },

    # ─────────── 🛍 ПОКУПАТЕЛИ ───────────
    "role_bronze": {
        "name": "Бронза",
        "desc": "Получить роль Bronze Buyer (1-5 отзывов)",
        "icon": "fa-medal",
        "category": "buyers",
    },
    "role_silver": {
        "name": "Серебро",
        "desc": "Получить роль Silver Buyer (6-10 отзывов)",
        "icon": "fa-award",
        "category": "buyers",
    },
    "role_gold": {
        "name": "Золото",
        "desc": "Получить роль Gold Buyer (11-15 отзывов)",
        "icon": "fa-trophy",
        "category": "buyers",
    },
    "role_diamond": {
        "name": "Алмаз",
        "desc": "Получить роль Diamond Buyer (16-20 отзывов)",
        "icon": "fa-gem",
        "category": "buyers",
    },
    "role_crystalis": {
        "name": "Кристалис",
        "desc": "Получить роль Crystalis Buyer (21-25 отзывов)",
        "icon": "fa-diamond",
        "category": "buyers",
    },
    "role_pka": {
        "name": "Покупатель Века",
        "desc": "Получить роль PKA (26+ отзывов)",
        "icon": "fa-crown",
        "category": "buyers",
    },

    # ─────────── 💰 ЭКОНОМИКА ───────────
    "rich_10k": {
        "name": "Богач",
        "desc": "10 000 DC на балансе",
        "icon": "fa-coins",
        "category": "economy",
    },
    "rich_100k": {
        "name": "Сотня",
        "desc": "100 000 DC на балансе",
        "icon": "fa-sack-dollar",
        "category": "economy",
    },
    "rich_1m": {
        "name": "Миллионер",
        "desc": "1 000 000 DC на балансе",
        "icon": "fa-money-bill-wave",
        "category": "economy",
    },
    "investor_5k": {
        "name": "Инвестор",
        "desc": "Потратить 5 000 DC в магазине",
        "icon": "fa-chart-line",
        "category": "economy",
    },
    "investor_100k": {
        "name": "Банкир",
        "desc": "Потратить 100 000 DC в магазине",
        "icon": "fa-building-columns",
        "category": "economy",
    },
    "generous_10k": {
        "name": "Щедрый",
        "desc": "Подарить 10 000 DC другим",
        "icon": "fa-gift",
        "category": "economy",
    },

    # ─────────── 💬 АКТИВНОСТЬ ───────────
    "talker_1k": {
        "name": "Болтун",
        "desc": "1 000 сообщений в чате",
        "icon": "fa-comments",
        "category": "activity",
    },
    "talker_10k": {
        "name": "Спамер",
        "desc": "10 000 сообщений в чате",
        "icon": "fa-bullhorn",
        "category": "activity",
    },
    "talker_100k": {
        "name": "Легенда чата",
        "desc": "100 000 сообщений в чате",
        "icon": "fa-fire",
        "category": "activity",
    },
    "voice_100h": {
        "name": "Голос комьюнити",
        "desc": "100 часов в голосовых каналах",
        "icon": "fa-microphone",
        "category": "activity",
    },
    "voice_500h": {
        "name": "Голосовой маньяк",
        "desc": "500 часов в голосовых каналах",
        "icon": "fa-headphones",
        "category": "activity",
    },
    "reviewer_100": {
        "name": "Критик",
        "desc": "100 отзывов оставлено",
        "icon": "fa-scroll",
        "category": "activity",
    },

    # ─────────── 🏛 КЛАНЫ ───────────
    "clan_first_deposit": {
        "name": "Первый вклад",
        "desc": "Внести DC в копилку клана",
        "icon": "fa-hand-holding-dollar",
        "category": "clan",
    },
    "clan_1k": {
        "name": "Тысячник",
        "desc": "1 000 DC вклада за сезон",
        "icon": "fa-coins",
        "category": "clan",
    },
    "clan_10k": {
        "name": "Мега-вклад",
        "desc": "10 000 DC вклада за сезон",
        "icon": "fa-gem",
        "category": "clan",
    },
    "clan_50k": {
        "name": "Клан-магнат",
        "desc": "50 000 DC вклада за сезон",
        "icon": "fa-crown",
        "category": "clan",
    },
    "clan_champion": {
        "name": "Чемпион",
        "desc": "Выиграть сезон вместе с кланом",
        "icon": "fa-trophy",
        "category": "clan",
    },
    "clan_faithful": {
        "name": "Верный",
        "desc": "3 сезона в одном клане",
        "icon": "fa-shield-halved",
        "category": "clan",
    },

    # ─────────── 🎰 КАЗИНО ───────────
    "casino_coin": {
        "name": "Орёл или решка",
        "desc": "Сыграть в монетку",
        "icon": "fa-coins",
        "category": "casino",
    },
    "casino_bj21": {
        "name": "Двадцать одно",
        "desc": "Блэкджек с двух карт",
        "icon": "fa-spade",
        "category": "casino",
    },
    "casino_jackpot": {
        "name": "Джекпот",
        "desc": "Мега-джекпот в рулетке",
        "icon": "fa-dice",
        "category": "casino",
    },
    "casino_100": {
        "name": "Азартный",
        "desc": "100 партий в казино",
        "icon": "fa-dice-five",
        "category": "casino",
    },
    "casino_1000": {
        "name": "Казино-магнат",
        "desc": "1 000 партий в казино",
        "icon": "fa-dice-six",
        "category": "casino",
    },
    "casino_highroller": {
        "name": "Хайроллер",
        "desc": "Ставка 10 000 DC за раз",
        "icon": "fa-money-bill-1-wave",
        "category": "casino",
    },

    # ─────────── 🎯 КВЕСТЫ ───────────
    "quest_first": {
        "name": "Первый квест",
        "desc": "Выполнить первый квест",
        "icon": "fa-check",
        "category": "quests",
    },
    "quest_10": {
        "name": "Новичок-охотник",
        "desc": "10 квестов выполнено",
        "icon": "fa-list",
        "category": "quests",
    },
    "quest_50": {
        "name": "Квест-охотник",
        "desc": "50 квестов выполнено",
        "icon": "fa-list-check",
        "category": "quests",
    },
    "quest_100": {
        "name": "Мастер квестов",
        "desc": "100 квестов выполнено",
        "icon": "fa-medal",
        "category": "quests",
    },
    "quest_200": {
        "name": "Гуру квестов",
        "desc": "200 квестов выполнено",
        "icon": "fa-star",
        "category": "quests",
    },
    "quest_500": {
        "name": "Легенда квестов",
        "desc": "500 квестов выполнено",
        "icon": "fa-trophy",
        "category": "quests",
    },

    # ─────────── 👔 ПЕРСОНАЛ ───────────
    "staff_first_ticket": {
        "name": "Первый тикет",
        "desc": "Закрыть первый тикет",
        "icon": "fa-ticket",
        "category": "staff",
    },
    "staff_10_tickets": {
        "name": "Менеджер",
        "desc": "10 закрытых тикетов",
        "icon": "fa-briefcase",
        "category": "staff",
    },
    "staff_100_tickets": {
        "name": "Топ-менеджер",
        "desc": "100 закрытых тикетов",
        "icon": "fa-trophy",
        "category": "staff",
    },
    "staff_perfect": {
        "name": "Идеальный сервис",
        "desc": "10 оценок 5/5 от покупателей",
        "icon": "fa-star",
        "category": "staff",
    },
    "staff_first_salary": {
        "name": "Первая зарплата",
        "desc": "Получить первую зарплату",
        "icon": "fa-sack-dollar",
        "category": "staff",
    },
    "staff_year": {
        "name": "Годовщина",
        "desc": "12 зарплат подряд",
        "icon": "fa-calendar-check",
        "category": "staff",
    },
}


# ============================================================
# СОРТИРОВКА И УТИЛИТЫ
# ============================================================
CATEGORY_MAP = {c["key"]: c for c in CATEGORIES}

# Порядок ключей в каждой категории — как в словаре ACHIEVEMENTS
CATEGORY_KEYS: Dict[str, List[str]] = {c["key"]: [] for c in CATEGORIES}
for _k, _v in ACHIEVEMENTS.items():
    cat = _v.get("category")
    if cat in CATEGORY_KEYS:
        CATEGORY_KEYS[cat].append(_k)


def get_category_of(ach_key: str) -> Optional[str]:
    ach = ACHIEVEMENTS.get(ach_key)
    return ach.get("category") if ach else None


def get_achievements_in_category(cat_key: str) -> List[str]:
    return CATEGORY_KEYS.get(cat_key, [])


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


def get_user_unlocked_set(user_id: int) -> set:
    """Возвращает set() разблокированных ключей — быстрее чем list."""
    return set(get_user_achievements(user_id))


def get_category_progress(user_id: int) -> Dict[str, dict]:
    """
    Возвращает {cat_key: {"unlocked": int, "total": int}} для всех категорий.
    """
    unlocked = get_user_unlocked_set(user_id)
    result = {}
    for c in CATEGORIES:
        keys = CATEGORY_KEYS[c["key"]]
        done = sum(1 for k in keys if k in unlocked)
        result[c["key"]] = {"unlocked": done, "total": len(keys)}
    return result


def get_overall_progress(user_id: int) -> Dict[str, int]:
    unlocked = get_user_unlocked_set(user_id)
    return {
        "unlocked": sum(1 for k in ACHIEVEMENTS if k in unlocked),
        "total": len(ACHIEVEMENTS),
    }


# ============================================================
# ВЫДАЧА ДОСТИЖЕНИЙ
# ============================================================
async def unlock_achievement(user_id: int, ach_key: str,
                             bot=None, notify: bool = True) -> bool:
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

        color_map = {
            "gold":   0xf7c991,
            "green":  0x2ecc71,
            "blue":   0x6a9bd1,
            "purple": 0xb39ddb,
            "red":    0xff6b6b,
            "silver": 0xc6d0e0,
            "orange": 0xe08c5a,
            "steel":  0x96b4dc,
        }
        cat_key = ach.get("category")
        cat_color = CATEGORY_MAP.get(cat_key, {}).get("color", "gold")
        color = color_map.get(cat_color, 0xf7c991)

        cat_label = CATEGORY_MAP.get(cat_key, {}).get("label", "")

        embed = disnake.Embed(
            title="🏆 Достижение разблокировано!",
            description=(
                f"**{ach['name']}**\n"
                f"> {ach['desc']}\n\n"
                f"> Категория: **{cat_label}**\n"
                f"Продолжай в том же духе! 💎"
            ),
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Все достижения — в профиле")

        await user.send(embed=embed)
    except disnake.Forbidden:
        logger.debug(f"ЛС закрыты у {user_id}")
    except Exception as e:
        logger.warning(f"_send_achievement_dm {user_id}: {e}")


# ============================================================
# ТРИГГЕРЫ
# ============================================================
async def check_and_unlock(user_id: int, trigger: str, value: int = 0,
                           bot=None, **kwargs) -> List[str]:
    """
    Проверяет условия и выдаёт достижения.
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
        if value >= 1:  _try("role_bronze")
        if value >= 6:  _try("role_silver")
        if value >= 11: _try("role_gold")
        if value >= 16: _try("role_diamond")
        if value >= 21: _try("role_crystalis")
        if value >= 26: _try("role_pka")

    elif trigger == "balance":
        if value >= 10_000:    _try("rich_10k")
        if value >= 100_000:   _try("rich_100k")
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
        if value >= 100: _try("reviewer_100")

    elif trigger == "clan_deposit":
        if value >= 1:      _try("clan_first_deposit")
        if value >= 1_000:  _try("clan_1k")
        if value >= 10_000: _try("clan_10k")
        if value >= 50_000: _try("clan_50k")

    elif trigger == "casino_games":
        if value >= 1:    _try("casino_coin")
        if value >= 100:  _try("casino_100")
        if value >= 1000: _try("casino_1000")

    elif trigger == "casino_bet":
        if value >= 10_000: _try("casino_highroller")

    elif trigger == "gift_total":
        if value >= 10_000: _try("generous_10k")

    elif trigger == "shop_spent":
        if value >= 5_000:   _try("investor_5k")
        if value >= 100_000: _try("investor_100k")

    elif trigger == "quests":
        if value >= 1:   _try("quest_first")
        if value >= 10:  _try("quest_10")
        if value >= 50:  _try("quest_50")
        if value >= 100: _try("quest_100")
        if value >= 200: _try("quest_200")
        if value >= 500: _try("quest_500")

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

    for key in unlocked:
        await unlock_achievement(user_id, key, bot=bot)

    return unlocked


# ============================================================
# ПЕРЕСЧЁТ ВСЕХ
# ============================================================
async def recalculate_all_achievements(bot) -> Dict[str, int]:
    from clan.core import get_user_clan, get_user_contribution
    from modules.dc import get_dc_cache

    stats = {"checked": 0, "errors": 0}

    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        logger.warning("recalculate_all_achievements: guild not found")
        return stats

    review_counts = load_json("data/review_counts.json", {})

    for member in guild.members:
        if member.bot:
            continue

        stats["checked"] += 1
        uid = member.id

        try:
            if member.id == CREATOR_USER_ID:
                await unlock_achievement(uid, "creator", bot=bot, notify=False)

            role_ids = CONFIG["ROLE_IDS"]
            role_pairs = [
                ("bronze", "role_bronze"),
                ("silver", "role_silver"),
                ("gold", "role_gold"),
                ("diamond", "role_diamond"),
                ("crystalis", "role_crystalis"),
                ("pka", "role_pka"),
            ]
            for role_key, ach_key in role_pairs:
                role_id = role_ids.get(role_key)
                if role_id and member.get_role(role_id):
                    await unlock_achievement(uid, ach_key, bot=bot, notify=False)

            dc_data = get_dc_cache(uid)
            balance = dc_data.get("balance", 0)
            await check_and_unlock(uid, "balance", value=balance, bot=bot)

            purchases = dc_data.get("purchases", [])
            if purchases:
                await unlock_achievement(uid, "first_purchase", bot=bot, notify=False)

            review_count = int(review_counts.get(str(uid), 0) or 0)
            await check_and_unlock(uid, "reviews", value=review_count, bot=bot)
            await check_and_unlock(uid, "buyer_count", value=review_count, bot=bot)

            user_clan = get_user_clan(uid)
            if user_clan:
                contrib = get_user_contribution(uid)
                await check_and_unlock(uid, "clan_deposit", value=contrib, bot=bot)

        except Exception as e:
            logger.exception(f"recalculate {uid}: {e}")
            stats["errors"] += 1
            continue

    logger.info(f"🏆 Пересчёт достижений: {stats}")
    return stats


# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
def init_achievements():
    """Заглушка для симметрии."""
    pass
