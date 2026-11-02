# -*- coding: utf-8 -*-
"""
Система достижений и кейсов клан-лиги. Объединены UI, логика и рендеры.
"""
import io
import os
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict

import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption
from disnake.ui import View, Button, Select
from PIL import Image, ImageDraw

from core.utils import CONFIG, logger, db, cur, load_json, save_json, log_discord
from core.render import (
    _font, _icon, _tw, _ellipsis, _wrap, _fmt, _alpha_fill, _gradient_box,
    BG, CARD_TOP, STACK_BG, STACK_BRD, STACK_HDR, INNER_BG, INNER_BRD, TEXT, TEXT_SOFT, MUTED, DIM, DARK, SILVER, SILVER_HI, GREEN, RED, BLUE, GOLD, PURPLE, BRONZE, CARD_BRD, CANVAS_W, CANVAS_H, PAD_X, PAD_Y,
    I_GEM, I_STAR, I_CROWN, I_TROPHY, I_MEDAL, I_AWARD, I_COINS, I_SACK, I_MONEY, I_MONEY2, I_BAG, I_BRIEF, I_CHART, I_BANK, I_USERS, I_USER, I_USER_SEC, I_USER_TIE, I_HAND, I_HANDD, I_CLOCK, I_CALENDAR, I_CALC, I_LIST, I_LISTC, I_INFO, I_CHECK, I_XMARK, I_PERCENT, I_HISTORY, I_FIRE, I_GIFT, I_DICE, I_DICE5, I_DICE6, I_MESSAGE, I_COMMENT, I_COMMENTS, I_MIC, I_HEADPH, I_SCROLL, I_PEN, I_PEN_NIB, I_PENF, I_SEARCH, I_GAMEPAD, I_CUBE, I_GAUGE, I_SHIELD, I_BOLT, I_LOCK, I_SPADE, I_HEART, I_DIAMOND, I_CLUB, I_QUESTION, I_ROTATE, I_ROTATE_L, I_ARROW_L, I_ARROW_D, I_ELL, I_CIRCLE_M, I_PLUS, I_TRASH, I_EYE, I_IMAGE, I_PALETTE, I_MASKS, I_BULLHORN, I_TICKET, I_RECEIPT, I_BUILDING, I_MOBILE, I_CREDIT, I_BAN, I_HEAD, I_MOUSE, I_CART, I_BOX, I_CHECK_C, I_XMARK_C, I_HANDSHAKE, I_CROW, I_SEEDLING, I_GAVEL, I_BOOK, I_LAYERS, I_BEZIER, I_SMILE, base_canvas, draw_footer
)
from modules.cases import CASES, CASES_BY_NUM, get_case_stats, get_case_history, open_case
from modules.dc import get_user_balance
from core.ui_utils import btn_pad, btn_labels_total

CREATOR_USER_ID = 796293832751972352

CATEGORIES = [
    {"key": "base", "label": "Базовые", "icon": "fa-star", "color": "green"},
    {"key": "buyers", "label": "Покупатели", "icon": "fa-bag-shopping", "color": "silver"},
    {"key": "economy", "label": "Экономика", "icon": "fa-coins", "color": "gold"},
    {"key": "activity", "label": "Активность", "icon": "fa-comments", "color": "blue"},
    {"key": "clan", "label": "Кланы", "icon": "fa-shield-halved", "color": "purple"},
    {"key": "casino", "label": "Казино", "icon": "fa-dice", "color": "red"},
    {"key": "quests", "label": "Квесты", "icon": "fa-list-check", "color": "orange"},
    {"key": "staff", "label": "Персонал", "icon": "fa-briefcase", "color": "steel"},
]
CATEGORY_ORDER = [c["key"] for c in CATEGORIES]

ACHIEVEMENTS = {
    "newbie": {"name": "Новичок", "desc": "Зайти на сервер впервые", "icon": "fa-seedling", "category": "base", "rare": False},
    "first_message": {"name": "Первое слово", "desc": "Написать первое сообщение в чате", "icon": "fa-comment", "category": "base"},
    "first_voice": {"name": "Голос", "desc": "Зайти в голосовой канал впервые", "icon": "fa-microphone", "category": "base"},
    "first_review": {"name": "Первый отзыв", "desc": "Оставить первый отзыв в канале", "icon": "fa-pen-fancy", "category": "base"},
    "first_purchase": {"name": "Первая покупка", "desc": "Купить товар в магазине за DC", "icon": "fa-cart-shopping", "category": "base"},
    "creator": {"name": "Создатель Diamond", "desc": "Основать Diamond Shop", "icon": "fa-crown", "category": "base", "rare": True},
    "role_bronze": {"name": "Бронза", "desc": "Получить роль Bronze Buyer (1-5 отзывов)", "icon": "fa-medal", "category": "buyers"},
    "role_silver": {"name": "Серебро", "desc": "Получить роль Silver Buyer (6-10 отзывов)", "icon": "fa-award", "category": "buyers"},
    "role_gold": {"name": "Золото", "desc": "Получить роль Gold Buyer (11-15 отзывов)", "icon": "fa-trophy", "category": "buyers"},
    "role_diamond": {"name": "Алмаз", "desc": "Получить роль Diamond Buyer (16-20 отзывов)", "icon": "fa-gem", "category": "buyers"},
    "role_crystalis": {"name": "Кристалис", "desc": "Получить роль Crystalis Buyer (21-25 отзывов)", "icon": "fa-diamond", "category": "buyers"},
    "role_pka": {"name": "Покупатель Века", "desc": "Получить роль PKA (26+ отзывов)", "icon": "fa-crown", "category": "buyers"},
    "rich_10k": {"name": "Богач", "desc": "10 000 DC на балансе", "icon": "fa-coins", "category": "economy"},
    "rich_100k": {"name": "Сотня", "desc": "100 000 DC на балансе", "icon": "fa-sack-dollar", "category": "economy"},
    "rich_1m": {"name": "Миллионер", "desc": "1 000 000 DC на балансе", "icon": "fa-money-bill-wave", "category": "economy"},
    "investor_5k": {"name": "Инвестор", "desc": "Потратить 5 000 DC в магазине", "icon": "fa-chart-line", "category": "economy"},
    "investor_100k": {"name": "Банкир", "desc": "Потратить 100 000 DC в магазине", "icon": "fa-building-columns", "category": "economy"},
    "generous_10k": {"name": "Щедрый", "desc": "Подарить 10 000 DC другим", "icon": "fa-gift", "category": "economy"},
    "talker_1k": {"name": "Болтун", "desc": "1 000 сообщений в чате", "icon": "fa-comments", "category": "activity"},
    "talker_10k": {"name": "Спамер", "desc": "10 000 сообщений в чате", "icon": "fa-bullhorn", "category": "activity"},
    "talker_100k": {"name": "Легенда чата", "desc": "100 000 сообщений в чате", "icon": "fa-fire", "category": "activity"},
    "voice_100h": {"name": "Голос комьюнити", "desc": "100 часов в голосовых каналах", "icon": "fa-microphone", "category": "activity"},
    "voice_500h": {"name": "Голосовой маньяк", "desc": "500 часов в голосовых каналах", "icon": "fa-headphones", "category": "activity"},
    "reviewer_100": {"name": "Критик", "desc": "100 отзывов оставлено", "icon": "fa-scroll", "category": "activity"},
    "clan_first_deposit": {"name": "Первый вклад", "desc": "Внести DC в копилку клана", "icon": "fa-hand-holding-dollar", "category": "clan"},
    "clan_1k": {"name": "Тысячник", "desc": "1 000 DC вклада за сезон", "icon": "fa-coins", "category": "clan"},
    "clan_10k": {"name": "Мега-вклад", "desc": "10 000 DC вклада за сезон", "icon": "fa-gem", "category": "clan"},
    "clan_50k": {"name": "Клан-магнат", "desc": "50 000 DC вклада за сезон", "icon": "fa-crown", "category": "clan"},
    "clan_champion": {"name": "Чемпион", "desc": "Выиграть сезон вместе с кланом", "icon": "fa-trophy", "category": "clan"},
    "clan_faithful": {"name": "Верный", "desc": "3 сезона в одном клане", "icon": "fa-shield-halved", "category": "clan"},
    "casino_coin": {"name": "Орёл или решка", "desc": "Сыграть в монетку", "icon": "fa-coins", "category": "casino"},
    "casino_bj21": {"name": "Двадцать одно", "desc": "Блэкджек с двух карт", "icon": "fa-spade", "category": "casino"},
    "casino_jackpot": {"name": "Джекпот", "desc": "Мега-джекпот в рулетке", "icon": "fa-dice", "category": "casino"},
    "casino_100": {"name": "Азартный", "desc": "100 партий в казино", "icon": "fa-dice-five", "category": "casino"},
    "casino_1000": {"name": "Казино-магнат", "desc": "1 000 партий в казино", "icon": "fa-dice-six", "category": "casino"},
    "casino_highroller": {"name": "Хайроллер", "desc": "Ставка 10 000 DC за раз", "icon": "fa-money-bill-1-wave", "category": "casino"},
    "quest_first": {"name": "Первый квест", "desc": "Выполнить первый квест", "icon": "fa-check", "category": "quests"},
    "quest_10": {"name": "Новичок-охотник", "desc": "10 квестов выполнено", "icon": "fa-list", "category": "quests"},
    "quest_50": {"name": "Квест-охотник", "desc": "50 квестов выполнено", "icon": "fa-list-check", "category": "quests"},
    "quest_100": {"name": "Мастер квестов", "desc": "100 квестов выполнено", "icon": "fa-medal", "category": "quests"},
    "quest_200": {"name": "Гуру квестов", "desc": "200 квестов выполнено", "icon": "fa-star", "category": "quests"},
    "quest_500": {"name": "Легенда квестов", "desc": "500 квестов выполнено", "icon": "fa-trophy", "category": "quests"},
    "staff_first_ticket": {"name": "Первый тикет", "desc": "Закрыть первый тикет", "icon": "fa-ticket", "category": "staff"},
    "staff_10_tickets": {"name": "Менеджер", "desc": "10 закрытых тикетов", "icon": "fa-briefcase", "category": "staff"},
    "staff_100_tickets": {"name": "Топ-менеджер", "desc": "100 закрытых тикетов", "icon": "fa-trophy", "category": "staff"},
    "staff_perfect": {"name": "Идеальный сервис", "desc": "10 оценок 5/5 от покупателей", "icon": "fa-star", "category": "staff"},
    "staff_first_salary": {"name": "Первая зарплата", "desc": "Получить первую зарплату", "icon": "fa-sack-dollar", "category": "staff"},
    "staff_year": {"name": "Годовщина", "desc": "12 зарплат подряд", "icon": "fa-calendar-check", "category": "staff"},
}

CATEGORY_MAP = {c["key"]: c for c in CATEGORIES}
CATEGORY_KEYS = {c["key"]: [] for c in CATEGORIES}
for _k, _v in ACHIEVEMENTS.items():
    cat = _v.get("category")
    if cat in CATEGORY_KEYS: CATEGORY_KEYS[cat].append(_k)

def get_category_of(ach_key: str) -> Optional[str]: return ACHIEVEMENTS.get(ach_key, {}).get("category")
def get_achievements_in_category(cat_key: str) -> List[str]: return CATEGORY_KEYS.get(cat_key, [])

def has_achievement(user_id: int, ach_key: str) -> bool: return bool(cur.execute("SELECT 1 FROM clan_achievements WHERE user_id=? AND ach_key=?", (user_id, ach_key)).fetchone())
def get_user_achievements(user_id: int) -> List[str]: return [r["ach_key"] for r in cur.execute("SELECT ach_key FROM clan_achievements WHERE user_id=? ORDER BY unlocked_at DESC", (user_id,)).fetchall()]
def get_user_unlocked_set(user_id: int) -> set: return set(get_user_achievements(user_id))

def get_category_progress(user_id: int) -> Dict[str, dict]:
    unlocked = get_user_unlocked_set(user_id); result = {}
    for c in CATEGORIES:
        keys = CATEGORY_KEYS[c["key"]]; done = sum(1 for k in keys if k in unlocked); result[c["key"]] = {"unlocked": done, "total": len(keys)}
    return result

def get_overall_progress(user_id: int) -> Dict[str, int]:
    unlocked = get_user_unlocked_set(user_id)
    return {"unlocked": sum(1 for k in ACHIEVEMENTS if k in unlocked), "total": len(ACHIEVEMENTS)}

async def unlock_achievement(user_id: int, ach_key: str, bot=None, notify: bool = True) -> bool:
    if ach_key not in ACHIEVEMENTS or has_achievement(user_id, ach_key): return False
    from clan.core import get_current_cycle
    cycle = get_current_cycle(); cycle_id = cycle["id"] if cycle else 0
    cur.execute("INSERT INTO clan_achievements (user_id, ach_key, unlocked_at, season_id) VALUES (?, ?, ?, ?)", (user_id, ach_key, int(time.time()), cycle_id))
    db.commit()
    ach = ACHIEVEMENTS[ach_key]
    logger.info(f"🏆 Достижение выдано: {user_id} → {ach['name']}")
    if notify and bot:
        asyncio.create_task(_send_achievement_dm(bot, user_id, ach_key))
        asyncio.create_task(log_discord(title="🏆 Достижение разблокировано", description=f"> **Пользователь:** <@{user_id}>\n> **Достижение:** {ach['name']}\n> **Описание:** {ach['desc']}", color=0xffaa00, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]))
    return True

async def _send_achievement_dm(bot, user_id: int, ach_key: str):
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if not user: return
        ach = ACHIEVEMENTS[ach_key]; cat_key = ach.get("category"); cat_label = CATEGORY_MAP.get(cat_key, {}).get("label", "")
        color_map = {"gold": 0xf7c991, "green": 0x2ecc71, "blue": 0x6a9bd1, "purple": 0xb39ddb, "red": 0xff6b6b, "silver": 0xc6d0e0, "orange": 0xe08c5a, "steel": 0x96b4dc}
        color = color_map.get(CATEGORY_MAP.get(cat_key, {}).get("color", "gold"), 0xf7c991)
        embed = disnake.Embed(title="🏆 Достижение разблокировано!", description=f"**{ach['name']}**\n> {ach['desc']}\n\n> Категория: **{cat_label}**\nПродолжай в том же духе! 💎", color=color, timestamp=datetime.now(timezone.utc)).set_footer(text="Все достижения — в профиле")
        await user.send(embed=embed)
    except Exception: pass

async def check_and_unlock(user_id: int, trigger: str, value: int = 0, bot=None, **kwargs) -> List[str]:
    unlocked = []
    def _try(key):
        if key in ACHIEVEMENTS and not has_achievement(user_id, key): unlocked.append(key)
    if trigger == "first_message": _try("first_message")
    elif trigger == "first_voice": _try("first_voice")
    elif trigger == "first_purchase": _try("first_purchase")
    elif trigger == "first_review": _try("first_review")
    elif trigger == "creator" and user_id == CREATOR_USER_ID: _try("creator")
    elif trigger == "buyer_count":
        if value >= 1: _try("role_bronze")
        if value >= 6: _try("role_silver")
        if value >= 11: _try("role_gold")
        if value >= 16: _try("role_diamond")
        if value >= 21: _try("role_crystalis")
        if value >= 26: _try("role_pka")
    elif trigger == "balance":
        if value >= 10000: _try("rich_10k")
        if value >= 100000: _try("rich_100k")
        if value >= 1000000: _try("rich_1m")
    elif trigger == "messages":
        if value >= 1000: _try("talker_1k")
        if value >= 10000: _try("talker_10k")
        if value >= 100000: _try("talker_100k")
    elif trigger == "voice_hours":
        if value >= 100: _try("voice_100h")
        if value >= 500: _try("voice_500h")
    elif trigger == "reviews":
        if value >= 1: _try("first_review")
        if value >= 100: _try("reviewer_100")
    elif trigger == "clan_deposit":
        if value >= 1: _try("clan_first_deposit")
        if value >= 1000: _try("clan_1k")
        if value >= 10000: _try("clan_10k")
        if value >= 50000: _try("clan_50k")
    elif trigger == "casino_games":
        if value >= 1: _try("casino_coin")
        if value >= 100: _try("casino_100")
        if value >= 1000: _try("casino_1000")
    elif trigger == "casino_bet":
        if value >= 10000: _try("casino_highroller")
    elif trigger == "gift_total":
        if value >= 10000: _try("generous_10k")
    elif trigger == "shop_spent":
        if value >= 5000: _try("investor_5k")
        if value >= 100000: _try("investor_100k")
    elif trigger == "quests":
        if value >= 1: _try("quest_first")
        if value >= 10: _try("quest_10")
        if value >= 50: _try("quest_50")
        if value >= 100: _try("quest_100")
        if value >= 200: _try("quest_200")
        if value >= 500: _try("quest_500")
    elif trigger == "role":
        role_key = kwargs.get("role_key")
        role_map = {"bronze": "role_bronze", "silver": "role_silver", "gold": "role_gold", "diamond": "role_diamond", "crystalis": "role_crystalis", "pka": "role_pka"}
        if role_key in role_map: _try(role_map[role_key])
    elif trigger == "staff_tickets":
        if value >= 1: _try("staff_first_ticket")
        if value >= 10: _try("staff_10_tickets")
        if value >= 100: _try("staff_100_tickets")
    elif trigger == "staff_salary": _try("staff_first_salary")
    for key in unlocked: await unlock_achievement(user_id, key, bot=bot)
    return unlocked

async def recalculate_all_achievements(bot) -> Dict[str, int]:
    from clan.core import get_user_clan, get_user_contribution
    from modules.dc import get_dc_cache
    stats = {"checked": 0, "errors": 0}
    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild: return stats
    review_counts = load_json("data/review_counts.json", {})
    for member in guild.members:
        if member.bot: continue
        stats["checked"] += 1; uid = member.id
        try:
            if member.id == CREATOR_USER_ID: await unlock_achievement(uid, "creator", bot=bot, notify=False)
            role_ids = CONFIG["ROLE_IDS"]
            for role_key, ach_key in [("bronze", "role_bronze"), ("silver", "role_silver"), ("gold", "role_gold"), ("diamond", "role_diamond"), ("crystalis", "role_crystalis"), ("pka", "role_pka")]:
                if role_ids.get(role_key) and member.get_role(role_ids.get(role_key)): await unlock_achievement(uid, ach_key, bot=bot, notify=False)
            dc_data = get_dc_cache(uid); await check_and_unlock(uid, "balance", value=dc_data.get("balance", 0), bot=bot)
            if dc_data.get("purchases"): await unlock_achievement(uid, "first_purchase", bot=bot, notify=False)
            review_count = int(review_counts.get(str(uid), 0) or 0); await check_and_unlock(uid, "reviews", value=review_count, bot=bot); await check_and_unlock(uid, "buyer_count", value=review_count, bot=bot)
            user_clan = get_user_clan(uid)
            if user_clan: await check_and_unlock(uid, "clan_deposit", value=get_user_contribution(uid), bot=bot)
        except Exception as e: logger.exception(f"recalculate {uid}: {e}"); stats["errors"] += 1
    return stats

def init_achievements(): pass

# ============================================================
# КЕЙСЫ: РЕНДЕРЫ
# ============================================================
FA_CASE_COLOR = {"blue": BLUE, "green": GREEN, "gold": GOLD, "purple": PURPLE, "red": RED}

def render_cases(user_id, username, balance, stats):
    img, d = base_canvas(uid_label="кейсы", uid_value=user_id, logo_icon=I_GIFT)
    top_y1, top_h, gap_top = PAD_Y + 80, 90, 14
    col_w = (CANVAS_W - 2 * PAD_X - 2 * gap_top) // 3
    tb_data = [("ТВОЙ БАЛАНС", f"{_fmt(balance)} DC", GREEN, I_COINS, True), ("ОТКРЫТО", str(stats.get("opened", 0)), BLUE, I_GIFT, False), ("ЛУЧШИЙ ВЫИГРЫШ", f"{stats.get('best', 0)} DC", GOLD, I_TROPHY, False)]
    for i, (lbl, val, color, ic_code, is_green) in enumerate(tb_data):
        bx1, bx2, by1, by2 = PAD_X + i * (col_w + gap_top), PAD_X + i * (col_w + gap_top) + col_w, top_y1, top_y1 + top_h
        _gradient_box(img, (bx1, by1, bx2, by2), color, color, alpha=18 if is_green else 10, radius=16)
        d.rounded_rectangle((bx1, by1, bx2, by2), radius=16, outline=color + (200,), width=2)
        _alpha_fill(img, (bx1 + 16, by1 + 22, bx1 + 62, by1 + 68), color, alpha=45, radius=12); _icon(d, bx1 + 39, by1 + 45, ic_code, 22, color)
        d.text((bx1 + 78, by1 + 20), lbl, font=_font(11), fill=MUTED); d.text((bx1 + 78, by1 + 42), _ellipsis(d, val, _font(24), bx2 - 90), font=_font(24), fill=color)
    head_y = top_y1 + top_h + 22
    d.text((PAD_X, head_y), "🎰 Кейсы", font=_font(32), fill=TEXT)
    sw = _tw(d, "выбери свою удачу", _font(15)); d.text((CANVAS_W - PAD_X - sw, head_y + 14), "выбери свою удачу", font=_font(15), fill=MUTED)
    d.line((PAD_X, head_y + 56, CANVAS_W - PAD_X, head_y + 56), fill=STACK_HDR + (255,), width=2)
    grid_y, grid_bottom = head_y + 70, CANVAS_H - PAD_Y - 20
    gap, cols = 18, 5
    cell_w = (CANVAS_W - 2 * PAD_X - gap * (cols - 1)) // cols
    cell_h = min(grid_bottom - grid_y, int(cell_w * 1.15))
    for i, case in enumerate(CASES):
        cx1, cy1 = PAD_X + i * (cell_w + gap), grid_y
        cy2, cx2 = cy1 + cell_h, cx1 + cell_w
        color = FA_CASE_COLOR.get(case["color"], SILVER)
        _gradient_box(img, (cx1, cy1, cx2, cy2), color, color, alpha=20, radius=24); d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=24, outline=color + (230,), width=3)
        if case["num"] == 5:
            d.rounded_rectangle((cx2 - 82, cy1 + 16, cx2 - 18, cy1 + 44), radius=8, fill=RED + (255,)); d.text((cx2 - 72, cy1 + 22), "TOP", font=_font(12), fill=TEXT)
        ic_size = 130; ic_x, ic_y = cx1 + (cell_w - ic_size) // 2, cy1 + 34
        _alpha_fill(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), color, alpha=50, radius=28); d.rounded_rectangle((ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), radius=28, outline=color + (220,), width=3)
        _icon(d, ic_x + ic_size // 2, ic_y + ic_size // 2 + 1, {1: I_GIFT, 2: I_COINS, 3: I_GEM, 4: I_CROWN, 5: I_TROPHY}.get(case["num"], I_GIFT), 58, color)
        ny = ic_y + ic_size + 22
        for j, ln in enumerate(_wrap(d, case["name"], _font(20), cell_w - 30, max_lines=2)): d.text((cx1 + (cell_w - _tw(d, ln, _font(20))) // 2, ny + j * 26), ln, font=_font(20), fill=color)
        pf = _font(44); pw = _tw(d, str(case["price"]), pf); uf = _font(18); uw = _tw(d, " DC", uf)
        d.text((cx1 + (cell_w - (pw + uw)) // 2, cy2 - 70), str(case["price"]), font=pf, fill=color); d.text((cx1 + (cell_w - (pw + uw)) // 2 + pw + 6, cy2 - 70 + pf.size - 22), " DC", font=uf, fill=MUTED)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_spin(case):
    img, d = base_canvas(uid_label="крутка кейса", logo_icon=I_GIFT)
    color = FA_CASE_COLOR.get(case["color"], GOLD); cx = CANVAS_W // 2; circle_size, cy = 420, 460
    circle_x, circle_y = cx - circle_size // 2, cy - circle_size // 2
    _gradient_box(img, (circle_x, circle_y, circle_x + circle_size, circle_y + circle_size), color, color, alpha=35, radius=circle_size // 2)
    d.ellipse((circle_x - 5, circle_y - 5, circle_x + circle_size + 5, circle_y + circle_size + 5), outline=color + (255,), width=10)
    d.ellipse((circle_x + 26, circle_y + 26, circle_x + circle_size - 26, circle_y + circle_size - 26), outline=color + (140,), width=4)
    _icon(d, cx, cy + 2, I_GIFT, 180, color)
    title = "КРУТИМ БАРАБАН..."; tf = _font(56); tw_ = _tw(d, title, tf); title_y = circle_y + circle_size + 40
    d.text((cx - tw_ // 2, title_y), title, font=tf, fill=color)
    sub = f"{case['name']} · {case['price']} DC списано"; sf = _font(22); sw = _tw(d, sub, sf); sub_y = title_y + 56 + 24
    d.text((cx - sw // 2, sub_y), sub, font=sf, fill=MUTED)
    hint = "результат через пару секунд..."; hf = _font(16); hw = _tw(d, hint, hf); hint_y = sub_y + 22 + 16
    d.text((cx - hw // 2, hint_y), hint, font=hf, fill=DIM)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_result(case, prize, desc, user_balance):
    ptype = (prize or {}).get("type", "dc"); case_price = int(case.get("price", 0) or 0); prize_value = int((prize or {}).get("value", 0) or 0)
    tag = "ПОЗДРАВЛЯЕМ, ДЖЕКПОТ" if ptype == "dc" and case_price > 0 and prize_value >= case_price * 3 else "ПОЗДРАВЛЯЕМ, ВЫПАЛО" if ptype == "dc" and case_price > 0 and prize_value >= case_price else "ВЫПАЛО" if ptype == "dc" else "ПОЗДРАВЛЯЕМ, РОЛЬ" if ptype == "role" else "ВЫПАЛ БУСТ" if ptype == "boost" else "ВЫПАЛА СКИДКА" if ptype == "discount" else "ВЫПАЛО"
    img, d = base_canvas(uid_label="bonus · выигрыш", status_label=f"КЕЙС {case.get('num', '?')}", logo_icon=I_TROPHY); cx = CANVAS_W // 2
    for sx, sy, sz in [(180, 150, 44), (CANVAS_W - 200, 180, 52), (200, CANVAS_H - 260, 36), (CANVAS_W - 220, CANVAS_H - 240, 40), (120, 440, 32), (CANVAS_W - 140, 420, 36)]: _icon(d, sx, sy, I_STAR, sz, SILVER)
    txf = _font(16); txw = _tw(d, tag, txf); tag_w, tag_h = txw + 72, 50; tag_x, tag_y = cx - tag_w // 2, 180
    _alpha_fill(img, (tag_x, tag_y, tag_x + tag_w, tag_y + tag_h), SILVER, alpha=40, radius=tag_h // 2); d.rounded_rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + tag_h), radius=tag_h // 2, outline=SILVER + (230,), width=3); d.text((cx - txw // 2, tag_y + 12), tag, font=txf, fill=SILVER)
    ic_size = 240; ic_x, ic_y = cx - ic_size // 2, tag_y + tag_h + 30
    _alpha_fill(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), SILVER, alpha=50, radius=ic_size // 2); d.ellipse((ic_x - 4, ic_y - 4, ic_x + ic_size + 4, ic_y + ic_size + 4), outline=SILVER + (255,), width=6); _icon(d, cx, ic_y + ic_size // 2 + 2, I_TROPHY, 110, SILVER)
    num_y = ic_y + ic_size + 30; num_str = str(desc or "—"); nf = _font(140)
    while _tw(d, num_str, nf) > CANVAS_W - 200 and nf.size > 60: nf = _font(nf.size - 6)
    d.text((cx - _tw(d, num_str, nf) // 2, num_y), num_str, font=nf, fill=SILVER)
    sub = f"Кейс «{case.get('name', '—')}» · {case_price} DC"; sf = _font(15); sw = _tw(d, sub, sf); d.text((cx - sw // 2, num_y + nf.size + 16), sub, font=sf, fill=MUTED)
    info_y, info_h = CANVAS_H - PAD_Y - 130, 130; ix1, ix2 = PAD_X, CANVAS_W - PAD_X
    d.rounded_rectangle((ix1, info_y, ix2, info_y + info_h), radius=20, fill=(20, 20, 28) + (255,), outline=SILVER + (200,), width=2); mid_x = (ix1 + ix2) // 2
    _icon(d, ix1 + 70, info_y + info_h // 2, I_COINS if ptype == "dc" else I_GIFT, 46, SILVER)
    if ptype == "dc":
        d.text((ix1 + 116, info_y + 26), "ЗАЧИСЛЕНО НА БАЛАНС", font=_font(12), fill=SILVER); d.text((ix1 + 116, info_y + 50), f"+{prize_value} DC", font=_font(38), fill=TEXT)
        d.text((ix1 + 116, info_y + 98), f"×{prize_value / case_price:.1f} от ставки" if case_price > 0 else "", font=_font(14), fill=MUTED)
    elif ptype == "role":
        d.text((ix1 + 116, info_y + 30), "РОЛЬ ВЫДАНА", font=_font(12), fill=SILVER); d.text((ix1 + 116, info_y + 54), str(desc or "—"), font=_font(30), fill=TEXT); d.text((ix1 + 116, info_y + 98), "проверь профиль", font=_font(14), fill=MUTED)
    elif ptype == "boost":
        d.text((ix1 + 116, info_y + 30), "БУСТ АКТИВИРОВАН", font=_font(12), fill=SILVER); d.text((ix1 + 116, info_y + 54), "уже работает", font=_font(30), fill=TEXT); d.text((ix1 + 116, info_y + 98), "смотри в профиле", font=_font(14), fill=MUTED)
    elif ptype == "discount":
        d.text((ix1 + 116, info_y + 30), "СКИДКА В ИНВЕНТАРЕ", font=_font(12), fill=SILVER); d.text((ix1 + 116, info_y + 54), str(desc or "—"), font=_font(30), fill=TEXT); d.text((ix1 + 116, info_y + 98), "примени в тикете", font=_font(14), fill=MUTED)
    d.rectangle((mid_x - 1, info_y + 24, mid_x + 1, info_y + info_h - 24), fill=(60, 60, 68) + (255,)); _icon(d, mid_x + 60, info_y + info_h // 2, I_GEM, 46, SILVER)
    d.text((mid_x + 106, info_y + 26), "ТЕКУЩИЙ БАЛАНС", font=_font(12), fill=SILVER); d.text((mid_x + 106, info_y + 50), f"{_fmt(user_balance)} DC", font=_font(38), fill=TEXT); d.text((mid_x + 106, info_y + 98), "готов к новому кейсу", font=_font(14), fill=MUTED)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_my_cases(user_id, username, stats, history):
    img, d = base_canvas(uid_label="мои кейсы", uid_value=user_id, logo_icon=I_HISTORY)
    body_y, body_h = 138, CANVAS_H - PAD_Y - 138 - 26
    left_w, gap = 420, 26; left_x1, left_x2 = PAD_X, PAD_X + left_w; right_x1, right_x2 = left_x2 + gap, CANVAS_W - PAD_X
    d.rounded_rectangle((left_x1, body_y, left_x2, body_y + body_h), radius=22, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)
    d.text((left_x1 + 24, body_y + 20), "СТАТИСТИКА", font=_font(14), fill=MUTED); d.line((left_x1 + 24, body_y + 44, left_x2 - 24, body_y + 44), fill=STACK_HDR + (255,), width=2)
    card_y, card_h, card_gap = body_y + 60, 120, 14
    for lbl, val, icon, color in [("ОТКРЫТО", f"{stats.get('opened', 0)}", I_GIFT, BLUE), ("ПОТРАЧЕНО", f"{_fmt(stats.get('spent', 0))} DC", I_COINS, GOLD), ("ЛУЧШИЙ", f"{_fmt(stats.get('best', 0))} DC", I_TROPHY, GREEN)]:
        _gradient_box(img, (left_x1 + 24, card_y, left_x2 - 24, card_y + card_h), color, color, alpha=18, radius=14); d.rounded_rectangle((left_x1 + 24, card_y, left_x2 - 24, card_y + card_h), radius=14, outline=color + (180,), width=2)
        _alpha_fill(img, (left_x1 + 40, card_y + 30, left_x1 + 100, card_y + 90), color, alpha=45, radius=14); _icon(d, left_x1 + 70, card_y + 60, icon, 26, color)
        d.text((left_x1 + 120, card_y + 30), lbl, font=_font(12), fill=MUTED); d.text((left_x1 + 120, card_y + 52), val, font=_font(28), fill=color)
        card_y += card_h + card_gap
    d.rounded_rectangle((right_x1, body_y, right_x2, body_y + body_h), radius=22, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)
    d.rounded_rectangle((right_x1 + 24, body_y + 24, right_x1 + 30, body_y + 60), radius=3, fill=SILVER + (255,)); d.text((right_x1 + 44, body_y + 20), "ПОСЛЕДНИЕ ОТКРЫТИЯ", font=_font(28), fill=TEXT)
    sw = _tw(d, f"{len(history)} из {stats.get('opened', 0)}", _font(15)); d.text((right_x2 - 24 - sw, body_y + 34), f"{len(history)} из {stats.get('opened', 0)}", font=_font(15), fill=MUTED); d.line((right_x1 + 24, body_y + 74, right_x2 - 24, body_y + 74), fill=STACK_HDR + (255,), width=2)
    list_y, list_bottom = body_y + 100, body_y + body_h - 24
    if not history:
        d.text(((right_x1 + right_x2) // 2, (list_y + list_bottom) // 2), "Ты ещё не открывал кейсы", font=_font(24), fill=DIM, anchor="mm"); d.text(((right_x1 + right_x2) // 2, (list_y + list_bottom) // 2 + 40), "Попробуй удачу — выбери кейс в панели выше", font=_font(15), fill=MUTED, anchor="mm")
    else:
        row_h, row_gap = 76, 10; n = len(history[:8]); start_y = list_y + max(0, (list_bottom - list_y - row_h * n - row_gap * (n - 1)) // 2)
        for i, h in enumerate(history[:8]):
            ry = start_y + i * (row_h + row_gap); case = next((c for c in CASES if c["num"] == h.get("case_num")), None); color = FA_CASE_COLOR.get(case["color"], SILVER) if case else SILVER
            _gradient_box(img, (right_x1 + 24, ry, right_x2 - 24, ry + row_h), color, color, alpha=10, radius=12); d.rounded_rectangle((right_x1 + 24, ry, right_x2 - 24, ry + row_h), radius=12, outline=color + (150,), width=2)
            d.rounded_rectangle((right_x1 + 24, ry + 12, right_x1 + 30, ry + row_h - 12), radius=3, fill=color + (255,)); _alpha_fill(img, (right_x1 + 46, ry + 14, right_x1 + 104, ry + 62), color, alpha=45, radius=12); _icon(d, right_x1 + 75, ry + 38, I_GIFT, 22, color)
            d.text((right_x1 + 120, ry + 16), case.get("name", "—") if case else f"Кейс #{h.get('case_num')}", font=_font(18), fill=TEXT); d.text((right_x1 + 120, ry + 42), _ellipsis(d, h.get("prize_desc", "—"), _font(14), 400), font=_font(14), fill=MUTED)
            try: date_str = datetime.fromtimestamp(h.get("opened_at", 0), timezone.utc).strftime("%d.%m.%Y · %H:%M")
            except: date_str = "—"
            dw = _tw(d, date_str, _font(13)); d.text((right_x2 - 46 - dw, ry + 30), date_str, font=_font(13), fill=DIM)
    draw_footer(d, "Все открытия · свежие сверху", "кейсы · история")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

# ============================================================
# КЕЙСЫ: UI
# ============================================================
E_SHOP  = PartialEmoji(name="shop1", id=1555654407776112750)
E_PRIZE = PartialEmoji(name="prize", id=1539657202170859561)
E_CASE_1 = PartialEmoji(name="odin", id=1557754584158441574)
E_CASE_2 = PartialEmoji(name="dva", id=1557754603389583370)
E_CASE_3 = PartialEmoji(name="tri", id=1557754619252179066)
E_CASE_4 = PartialEmoji(name="chetiry", id=1557754636100833340)
E_CASE_5 = PartialEmoji(name="puiat", id=1557754652316139592)
CASE_EMOJI = {1: E_CASE_1, 2: E_CASE_2, 3: E_CASE_3, 4: E_CASE_4, 5: E_CASE_5}

_L_AGAIN, _L_MYCASES = btn_labels_total(["Купить ещё", "Мои кейсы"], 32)

class CaseSelect(Select):
    def __init__(self):
        options = []
        for case in CASES:
            desc = (case.get("desc") or "").strip()
            if len(desc) > 95: desc = desc[:92] + "..."
            options.append(SelectOption(label=f"{case['name']} · {case['price']} DC", description=desc or f"Кейс за {case['price']} DC", emoji=CASE_EMOJI.get(case["num"]), value=str(case["num"])))
        super().__init__(placeholder="Выбери кейс для открытия...", min_values=1, max_values=1, options=options, custom_id="clan_case_select")
    async def callback(self, inter: disnake.MessageInteraction):
        try: case_num = int(inter.data.values[0])
        except Exception: return
        await _open_case(inter, case_num)

class CasesSelectView(View):
    def __init__(self): super().__init__(timeout=300); self.add_item(CaseSelect())

class CaseAfterView(View):
    def __init__(self):
        super().__init__(timeout=300)
        btn_again = Button(label=_L_AGAIN, style=ButtonStyle.secondary, custom_id="clan_after:again", emoji=E_SHOP, row=0)
        btn_again.callback = self._again; self.add_item(btn_again)
        btn_my = Button(label=_L_MYCASES, style=ButtonStyle.secondary, custom_id="clan_after:mycases", emoji=E_PRIZE, row=0)
        btn_my.callback = self._mycases; self.add_item(btn_my)
    async def _again(self, inter): await _switch_to_cases(inter)
    async def _mycases(self, inter): await _switch_to_mycases(inter)

class MyCasesBackView(View):
    def __init__(self):
        super().__init__(timeout=300)
        btn = Button(label=btn_pad("К кейсам", 33), style=ButtonStyle.secondary, custom_id="clan_mycases:back", row=0)
        btn.callback = self._back; self.add_item(btn)
    async def _back(self, inter): await _switch_to_cases(inter)

async def show_cases_screen(inter: disnake.MessageInteraction):
    try: await inter.response.defer(ephemeral=True)
    except Exception: pass
    user_id = inter.author.id; balance = await get_user_balance(user_id); stats = get_case_stats(user_id)
    buf = await asyncio.to_thread(render_cases, user_id, inter.author.display_name, balance, stats)
    fname = f"cases_{user_id}.png"; file = disnake.File(buf, filename=fname); e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{fname}")
    try: await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=CasesSelectView())
    except Exception: await inter.followup.send(embeds=[e], file=file, view=CasesSelectView(), ephemeral=True)

async def _switch_to_cases(inter: disnake.MessageInteraction):
    try: await inter.response.defer(ephemeral=True)
    except Exception: pass
    user_id = inter.author.id; balance = await get_user_balance(user_id); stats = get_case_stats(user_id)
    buf = await asyncio.to_thread(render_cases, user_id, inter.author.display_name, balance, stats)
    fname = f"cases_{user_id}.png"; file = disnake.File(buf, filename=fname); e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{fname}")
    await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=CasesSelectView())

async def _switch_to_mycases(inter: disnake.MessageInteraction):
    try: await inter.response.defer(ephemeral=True)
    except Exception: pass
    user_id = inter.author.id; stats = get_case_stats(user_id); history = get_case_history(user_id, limit=8)
    buf = await asyncio.to_thread(render_my_cases, user_id, inter.author.display_name, stats, history)
    fname = f"mycases_{user_id}.png"; file = disnake.File(buf, filename=fname); e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{fname}")
    await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=MyCasesBackView())

async def _open_case(inter: disnake.MessageInteraction, case_num: int):
    try: await inter.response.defer(ephemeral=True)
    except Exception: pass
    case = CASES_BY_NUM.get(case_num)
    if not case: return await inter.followup.send("❌ Кейс не найден", ephemeral=True)
    balance = await get_user_balance(inter.author.id)
    if balance < case["price"]: return await inter.followup.send(f"❌ Нужно **{case['price']} DC**, у тебя **{balance} DC**.", ephemeral=True)
    try:
        buf = await asyncio.to_thread(render_spin, case)
        fname = f"spin_{inter.author.id}.png"; file = disnake.File(buf, filename=fname); e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{fname}")
        await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=None)
    except Exception as e: logger.exception(f"spin render: {e}")
    await asyncio.sleep(2.0)
    result = await open_case(inter.bot, inter.author.id, case_num)
    if not result["ok"]: return await inter.followup.send(f"❌ {result.get('error', 'Ошибка')}", ephemeral=True)
    new_balance = await get_user_balance(inter.author.id)
    try:
        buf = await asyncio.to_thread(render_result, case, result["prize"], result["desc"], new_balance)
        fname = f"result_{inter.author.id}.png"; file = disnake.File(buf, filename=fname); e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{fname}")
        await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=CaseAfterView())
    except Exception as e:
        logger.exception(f"result render: {e}"); await inter.followup.send(f"🎉 Выпало: **{result['desc']}**", ephemeral=True)
