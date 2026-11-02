# -*- coding: utf-8 -*-
"""Казино Diamond: рулетка, блэкджек, монетка + Кейсы. Всё с рендерами."""
import os
import io
import time
import json
import math
import random
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional

import disnake
from disnake import PartialEmoji, ButtonStyle
from disnake.ui import View, Button, Modal, TextInput

from core.utils import (
    BASE_DIR, DATA_DIR, CONFIG, logger, log_discord,
    load_json, save_json, cur, db,
)
from core.render import *
from modules.dc import (
    load_shop_catalog, get_user_balance, remove_dc, add_dc, get_user_purchases, add_purchase,
)
from modules.others import apply_casino_win, try_insurance

try:
    from clan.quests import on_casino_quest_hook, on_casino_win_hook
except Exception:
    on_casino_quest_hook = None
    on_casino_win_hook = None

ACTIONS_DIR = os.path.join(BASE_DIR, "actions")
DAILY_DEAL_FILE = os.path.join(DATA_DIR, "daily_deal.json")
ROULETTE_STATS_FILE = os.path.join(DATA_DIR, "roulette_stats.json")

DAILY_DEAL_REFRESH_HOURS = 5
DAILY_DEAL_DISCOUNT = 30
DAILY_DEALS_PER_CYCLE = 5

CASINO_MIN_BET = 20
CASINO_MAX_BET = 4000
P = "\u3164"

# ============================================================
# КЕЙСЫ (из cases.py)
# ============================================================
CASES: List[dict] = [
    {"num": 1, "key": "luck", "price": 100, "name": "Попробуй удачу", "icon": "fa-gift", "color": "blue", "desc": "Лёгкий вход. Много мелких призов и шанс на хороший куш.", "prizes": [{"type": "dc", "value": 8, "chance": 15.0}, {"type": "dc", "value": 20, "chance": 20.0}, {"type": "dc", "value": 40, "chance": 20.0}, {"type": "dc", "value": 60, "chance": 15.0}, {"type": "dc", "value": 80, "chance": 12.0}, {"type": "dc", "value": 120, "chance": 8.0}, {"type": "dc", "value": 200, "chance": 5.0}, {"type": "dc", "value": 360, "chance": 3.0}, {"type": "dc", "value": 640, "chance": 1.5}, {"type": "dc", "value": 1400, "chance": 0.5}]},
    {"num": 2, "key": "fast", "price": 300, "name": "Быстрый куш", "icon": "fa-coins", "color": "green", "desc": "Много средних DC, плюс редкий шанс на буст и роль.", "prizes": [{"type": "dc", "value": 25, "chance": 15.0}, {"type": "dc", "value": 60, "chance": 20.0}, {"type": "dc", "value": 120, "chance": 20.0}, {"type": "dc", "value": 180, "chance": 15.0}, {"type": "dc", "value": 240, "chance": 11.5}, {"type": "dc", "value": 360, "chance": 8.0}, {"type": "dc", "value": 600, "chance": 5.0}, {"type": "dc", "value": 1080, "chance": 3.0}, {"type": "dc", "value": 1920, "chance": 1.5}, {"type": "dc", "value": 4200, "chance": 0.5}, {"type": "boost", "key": "boost_messages_x2", "chance": 0.3}, {"type": "boost", "key": "boost_all_x2", "chance": 0.1}, {"type": "role", "key": "role_helper", "days": 7, "chance": 0.1}]},
    {"num": 3, "key": "serious", "price": 500, "name": "Серьёзный куш", "icon": "fa-gem", "color": "gold", "desc": "Средний азарт. Ловит бусты, скидки и крупные суммы.", "prizes": [{"type": "dc", "value": 40, "chance": 15.0}, {"type": "dc", "value": 100, "chance": 20.0}, {"type": "dc", "value": 200, "chance": 20.0}, {"type": "dc", "value": 300, "chance": 15.0}, {"type": "dc", "value": 400, "chance": 11.3}, {"type": "dc", "value": 600, "chance": 8.0}, {"type": "dc", "value": 1000, "chance": 5.0}, {"type": "dc", "value": 1800, "chance": 3.0}, {"type": "dc", "value": 3200, "chance": 1.5}, {"type": "dc", "value": 7000, "chance": 0.5}, {"type": "boost", "key": "boost_all_x2", "chance": 0.2}, {"type": "discount", "key": "5", "chance": 0.2}, {"type": "role", "key": "role_helper", "days": 7, "chance": 0.1}]},
    {"num": 4, "key": "royal", "price": 1000, "name": "Королевский куш", "icon": "fa-crown", "color": "purple", "desc": "Для серьёзного шага. Роли, бусты и шанс вытащить 14 000 DC.", "prizes": [{"type": "dc", "value": 80, "chance": 15.0}, {"type": "dc", "value": 200, "chance": 20.0}, {"type": "dc", "value": 400, "chance": 20.0}, {"type": "dc", "value": 600, "chance": 15.0}, {"type": "dc", "value": 800, "chance": 11.4}, {"type": "dc", "value": 1200, "chance": 8.0}, {"type": "dc", "value": 2000, "chance": 5.0}, {"type": "dc", "value": 3600, "chance": 3.0}, {"type": "dc", "value": 6400, "chance": 1.5}, {"type": "dc", "value": 14000, "chance": 0.5}, {"type": "boost", "key": "boost_review_x2", "chance": 0.2}, {"type": "discount", "key": "5", "chance": 0.2}, {"type": "role", "key": "role_legend", "days": 0, "chance": 0.1}, {"type": "role", "key": "role_dc_magnate", "days": 0, "chance": 0.1}]},
    {"num": 5, "key": "mythic", "price": 2000, "name": "Мифический куш", "icon": "fa-trophy", "color": "red", "desc": "Максимум азарта. Крупные DC, дорогие роли и джекпот — 28 000 DC.", "prizes": [{"type": "dc", "value": 160, "chance": 15.0}, {"type": "dc", "value": 400, "chance": 20.0}, {"type": "dc", "value": 800, "chance": 20.0}, {"type": "dc", "value": 1200, "chance": 15.0}, {"type": "dc", "value": 1600, "chance": 11.3}, {"type": "dc", "value": 2400, "chance": 8.0}, {"type": "dc", "value": 4000, "chance": 5.0}, {"type": "dc", "value": 7200, "chance": 3.0}, {"type": "dc", "value": 12800, "chance": 1.5}, {"type": "dc", "value": 28000, "chance": 0.5}, {"type": "boost", "key": "boost_review_x2", "chance": 0.2}, {"type": "discount", "key": "7", "chance": 0.2}, {"type": "role", "key": "role_dc_magnate", "days": 0, "chance": 0.15}, {"type": "role", "key": "role_legend", "days": 0, "chance": 0.1}, {"type": "role", "key": "role_helper", "days": 0, "chance": 0.05}]}
]
CASES_BY_NUM = {c["num"]: c for c in CASES}

def init_cases_tables():
    cur.executescript("CREATE TABLE IF NOT EXISTS bonus_case_opens (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, case_num INTEGER, price INTEGER, prize_type TEXT, prize_value TEXT, prize_desc TEXT, opened_at INTEGER); CREATE INDEX IF NOT EXISTS idx_case_opens_user ON bonus_case_opens (user_id);")
    db.commit()

def _load_case_catalog() -> dict:
    try: return load_shop_catalog()
    except Exception: return {}

def _roll_case(case_num: int):
    case = CASES_BY_NUM.get(case_num)
    if not case: return None
    r = random.uniform(0, sum(p["chance"] for p in case["prizes"])); cum = 0.0
    for p in case["prizes"]:
        cum += p["chance"]
        if r <= cum: return dict(p)
    return dict(case["prizes"][-1])

def _prize_description(prize: dict) -> str:
    t = prize.get("type")
    if t == "dc": return f"{prize['value']} DC"
    if t == "role":
        item = _load_case_catalog().get("roles", {}).get("items", {}).get(prize["key"], {})
        return f"{item.get('name', 'Роль')}" + (f" на {prize.get('days', 0)} дн." if prize.get("days", 0) else " навсегда")
    if t == "boost": return _load_case_catalog().get("boosts", {}).get("items", {}).get(prize["key"], {}).get("name", "Буст")
    if t == "discount": return f"Скидка {prize['key']}%"
    return "—"

async def apply_case_prize(bot, user_id: int, prize: dict) -> str:
    t = prize.get("type"); cat = _load_case_catalog()
    if t == "dc":
        await add_dc(user_id, int(prize["value"]), "Выигрыш в кейсе", notify=False, log=False, to_clan_pool=False)
        return f"+{prize['value']} DC на баланс"
    if t == "boost":
        item = cat.get("boosts", {}).get("items", {}).get(prize["key"], {})
        try:
            from core.utils import activate_item
            activate_item(user_id=user_id, item_key=prize["key"], item_type="boosts", value=float(item.get("value", 0) or 0), duration_hours=int(item.get("duration_hours", 0) or 0), uses=int(item.get("uses", -1)))
            return f"Буст «{item.get('name', prize['key'])}» активирован"
        except Exception: return "Буст активирован"
    if t == "discount":
        try:
            await add_purchase(user_id, "discounts", f"Скидка {prize['key']}%")
            return f"Скидка {prize['key']}% в инвентаре"
        except Exception: return f"Скидка {prize['key']}%"
    if t == "role":
        item = cat.get("roles", {}).get("items", {}).get(prize["key"], {}); role_id = item.get("role_id"); days = int(prize.get("days", 0) or 0)
        if not role_id: return "Роль (ошибка выдачи)"
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild: return "Роль (ошибка сервера)"
        member, role = guild.get_member(user_id), guild.get_role(int(role_id))
        if not member or not role: return "Роль (ошибка)"
        try: await member.add_roles(role, reason="Выигрыш в кейсе")
        except Exception: return "Роль (ошибка выдачи)"
        return f"Роль «{role.name}» на {days} дн." if days > 0 else f"Роль «{role.name}» навсегда"
    return "Приз"

async def open_case(bot, user_id: int, case_num: int) -> dict:
    case = CASES_BY_NUM.get(case_num)
    if not case: return {"ok": False, "error": "Кейс не найден"}
    balance = await get_user_balance(user_id)
    if balance < case["price"]: return {"ok": False, "error": f"Недостаточно DC. Нужно {case['price']}, у тебя {balance}"}
    if not await remove_dc(user_id, case["price"], f"Открытие кейса «{case['name']}»"): return {"ok": False, "error": "Не удалось списать DC"}
    prize = _roll_case(case_num); desc = _prize_description(prize)
    try: await apply_case_prize(bot, user_id, prize)
    except Exception as e: logger.exception(f"open_case apply: {e}")
    cur.execute("INSERT INTO bonus_case_opens (user_id, case_num, price, prize_type, prize_value, prize_desc, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (user_id, case_num, case["price"], prize.get("type", ""), json.dumps(prize, ensure_ascii=False), desc, int(time.time())))
    db.commit()
    await log_discord(title="🎰 Кейс открыт", description=f"> **Юзер:** <@{user_id}>\n> **Кейс:** {case['name']} · `{case['price']} DC`\n> **Выпало:** {desc}", color=0xffaa00, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"])
    return {"ok": True, "prize": prize, "desc": desc, "case": case}

def get_case_history(user_id: int, limit: int = 8) -> List[dict]:
    return [dict(r) for r in cur.execute("SELECT * FROM bonus_case_opens WHERE user_id=? ORDER BY opened_at DESC LIMIT ?", (user_id, limit)).fetchall()]

def get_case_stats(user_id: int) -> dict:
    row = cur.execute("SELECT COUNT(*) AS c, COALESCE(SUM(price), 0) AS s FROM bonus_case_opens WHERE user_id=?", (user_id,)).fetchone()
    best = 0
    for r in cur.execute("SELECT prize_type, prize_value FROM bonus_case_opens WHERE user_id=?", (user_id,)).fetchall():
        if r["prize_type"] == "dc":
            try:
                v = int(json.loads(r["prize_value"]).get("value", 0))
                if v > best: best = v
            except Exception: pass
    return {"opened": row["c"] or 0, "spent": row["s"] or 0, "best": best}

# ============================================================
# РЕНДЕРЫ КЕЙСОВ (из cases_render.py)
# ============================================================
FA_CASE_COLOR = {"blue": BLUE, "green": GREEN, "gold": GOLD, "purple": PURPLE, "red": RED}

def render_cases(user_id, username, balance, stats):
    img, d = base_canvas(uid_label="кейсы", uid_value=user_id, logo_icon=I_GIFT)
    top_y1, top_h, gap_top = PAD_Y + 80, 90, 14
    col_w = (CANVAS_W - 2 * PAD_X - 2 * gap_top) // 3
    tb_data = [("ТВОЙ БАЛАНС", f"{_fmt(balance)} DC", GREEN, I_COINS, True), ("ОТКРЫТО", str(stats.get("opened", 0)), BLUE, I_GIFT, False), ("ЛУЧШИЙ ВЫИГРЫШ", f"{stats.get('best', 0)} DC", GOLD, I_TROPHY, False)]
    for i, (lbl, val, color, ic_code, is_green) in enumerate(tb_data):
        bx1, bx2, by1, by2 = PAD_X + i * (col_w + gap_top), PAD_X + i * (col_w + gap_top) + col_w, top_y1, top_y1 + top_h
        _gradient_box(img, (bx1, by1, bx2, by2), color, color, alpha=18 if is_green else 10, radius=16); d.rounded_rectangle((bx1, by1, bx2, by2), radius=16, outline=color + (200,), width=2)
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
# РЕНДЕРЫ КАЗИНО (из casino_render.py)
# ============================================================
I_ROTATE = 0xf2f1; I_ROTATE_L = 0xf2ea; I_TREND_DOWN = 0xf063; I_HAND_R = 0xf0a4; I_CROW = 0xf520; I_HANDSHAKE = 0xf2b5

def _draw_header_tab(img, d, x2, y1, label, value, color):
    lf = _font(13); vf = _font(24); lw = _tw(d, label.upper(), lf); vw = _tw(d, value.upper(), vf); inner_w = max(lw, vw); pad_x, pad_y = 26, 14; tab_w = inner_w + pad_x * 2; tab_h = 80; x1 = x2 - tab_w; y2 = y1 + tab_h
    _alpha_fill(img, (x1, y1, x2, y2), color, alpha=20, radius=14); d.rounded_rectangle((x1, y1, x2, y2), radius=14, outline=color + (120,), width=2); d.text((x2 - pad_x - lw, y1 + pad_y), label.upper(), font=lf, fill=MUTED); d.text((x2 - pad_x - vw, y1 + pad_y + 20), value.upper(), font=vf, fill=color)

def _draw_left_panel_casino(img, d, box, balance, blocks):
    _draw_stack_panel(img, d, box, radius=22); x1, y1, x2, y2 = box; pad = 28
    _gradient_box(img, (x1 + pad, y1 + pad, x1 + pad + 104, y1 + pad + 104), SILVER, SILVER_DIM, alpha=42, radius=26); d.rounded_rectangle((x1 + pad, y1 + pad, x1 + pad + 104, y1 + pad + 104), radius=26, outline=SILVER + (200,), width=3); _icon(d, x1 + pad + 52, y1 + pad + 53, I_GEM, 44, SILVER_HI)
    lx = x1 + pad + 104 + 22; d.text((lx, y1 + pad + 6), "ТВОЙ БАЛАНС", font=_font(15), fill=MUTED); bs = f"{balance:,}".replace(",", " "); vf = _font(56)
    while _tw(d, bs + " DC", vf) > (x2 - pad - lx - 16) and vf.size > 32: vf = _font(vf.size - 2)
    d.text((lx, y1 + pad + 34), bs, font=vf, fill=TEXT); bw = _tw(d, bs, vf); d.text((lx + bw + 8, y1 + pad + 34 + vf.size - 26), "DC", font=_font(26), fill=SILVER)
    sep_y = y1 + pad + 104 + 20; d.line((x1 + pad, sep_y, x2 - pad, sep_y), fill=STACK_HDR + (255,), width=2)
    for i, blk in enumerate(blocks):
        cy1 = sep_y + 20 + i * (116); cy2 = cy1 + 100; cx1, cx2 = x1 + pad, x2 - pad; color = blk["color"]
        _alpha_fill(img, (cx1, cy1, cx2, cy2), color, alpha=22, radius=18); d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=18, outline=_lighten(color, 0.15) + (180,), width=2)
        isz = 64; ix, iy = cx1 + 22, cy1 + (100 - 64) // 2; _alpha_fill(img, (ix, iy, ix + isz, iy + isz), color, alpha=55, radius=16); d.rounded_rectangle((ix, iy, ix + isz, iy + isz), radius=16, outline=_lighten(color, 0.2) + (200,), width=2); _icon(d, ix + isz // 2, iy + isz // 2 + 1, blk["icon"], 30, color)
        tx = ix + isz + 20; d.text((tx, cy1 + 18), blk["label"].upper(), font=_font(14), fill=_lighten(color, 0.35)); vf2 = _font(28); val = blk["value"]
        while _tw(d, val, vf2) > (cx2 - 20 - tx) and vf2.size > 16: vf2 = _font(vf2.size - 2)
        d.text((tx, cy1 + 50), val, font=vf2, fill=color)

def _rhead(d, x1, y1, x2, title, sub):
    d.text((x1, y1), title.upper(), font=_font(40), fill=TEXT); sf = _font(16); sw = _tw(d, sub.upper(), sf); d.text((x2 - sw, y1 + 22), sub.upper(), font=sf, fill=MUTED); d.line((x1, y1 + 60, x2, y1 + 60), fill=STACK_HDR + (255,), width=2)

def _hero(img, d, box, color, icon_code, label, title, title_color=TEXT):
    x1, y1, x2, y2 = box; _alpha_fill(img, (x1, y1, x2, y2), color, alpha=18, radius=22); d.rounded_rectangle((x1, y1, x2, y2), radius=22, outline=color + (170,), width=3)
    isz = 180; ix, iy = x1 + 40, y1 + (y2 - y1 - 180) // 2; _alpha_fill(img, (ix, iy, ix + isz, iy + isz), color, alpha=40, radius=36); d.rounded_rectangle((ix, iy, ix + isz, iy + isz), radius=36, outline=color + (200,), width=3); _icon(d, ix + isz // 2, iy + isz // 2 + 1, icon_code, 80, color)
    tx = ix + isz + 40; d.text((tx, y1 + 46), label.upper(), font=_font(18), fill=MUTED); tf = _font(64)
    while _tw(d, title, tf) > (x2 - 40 - tx) and tf.size > 32: tf = _font(tf.size - 4)
    d.text((tx, y1 + 78), title, font=tf, fill=title_color)

def _icells(d, img, box, cells, cols=2):
    x1, y1, x2, y2 = box; gap = 16; cw = (x2 - x1 - gap * (cols - 1)) // cols; rows = (len(cells) + cols - 1) // cols; ch = (y2 - y1 - gap * (rows - 1)) // rows
    for i, c in enumerate(cells):
        r, col = divmod(i, cols); cx1 = x1 + col * (cw + gap); cy1 = y1 + r * (ch + gap); cx2 = cx1 + cw; cy2 = cy1 + ch
        d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=16, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2); d.text((cx1 + 22, cy1 + 22), c["label"].upper(), font=_font(14), fill=MUTED)
        color = c.get("color", TEXT); vf = _font(32); val = c["value"]
        while _tw(d, val, vf) > (cw - 44) and vf.size > 18: vf = _font(vf.size - 2)
        d.text((cx1 + 22, cy2 - 22 - vf.size), val, font=vf, fill=color)

def _hint(d, x1, y1, x2, y2, color, icon_code, text, center=True):
    cy = (y1 + y2) // 2; tf = _font(16); tw = _tw(d, text, tf); total_w = 18 + 12 + tw; start_x = (x1 + x2 - total_w) // 2 if center else x1
    _icon(d, start_x + 9, cy, icon_code, 18, color); d.text((start_x + 30, cy), text, font=tf, fill=MUTED, anchor="lm")

def _draw_wheel(img, d, cx, cy, radius=150):
    d.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=(15, 15, 20, 255), outline=GOLD + (255,), width=8); inner_r = radius - 26; d.ellipse((cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r), outline=(140, 115, 65, 180), width=3); _icon(d, cx, cy, I_ROTATE, 120, GOLD)

def _draw_coin(img, d, cx, cy, radius=130, state="default"):
    if state == "win": bg, border, ic = (61, 209, 119), (30, 138, 76), (13, 58, 31)
    elif state == "lose": bg, border, ic = (232, 90, 90), (160, 48, 48), (58, 15, 15)
    else: bg, border, ic = (232, 181, 101), (176, 122, 48), (90, 58, 16)
    d.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=bg + (255,), outline=border + (255,), width=10); inner_r = radius - 18; d.ellipse((cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r), outline=border + (200,), width=3); _icon(d, cx, cy, I_COINS, 100, ic)

def _draw_card(d, img, x, y, w, h, rank, suit_code, suit_color, is_back=False):
    if is_back:
        d.rounded_rectangle((x, y, x+w, y+h), radius=14, fill=(26, 35, 126, 255), outline=(40, 53, 147, 255), width=2)
        for i in range(0, h, 16): d.line((x+2, y+i, x+w-2, min(y+i+18, y+h-2)), fill=(40, 53, 147, 255), width=3)
        d.rounded_rectangle((x+14, y+14, x+w-14, y+h-14), radius=8, outline=(255, 255, 255, 80), width=2); _icon(d, x+w//2, y+h//2, I_QUESTION, 46, (200, 200, 220)); return
    d.rounded_rectangle((x, y, x+w, y+h), radius=14, fill=(240, 240, 245, 255), outline=(210, 210, 220, 255), width=2); rf = _font(48); rw = _tw(d, rank, rf); d.text((x + w//2 - rw//2, y + 26), rank, font=rf, fill=suit_color); _icon(d, x + w//2, y + h - 56, suit_code, 44, suit_color)

def _draw_card_frame(img, d, box, label, label_icon, score, cards, score_bad=False):
    x1, y1, x2, y2 = box; d.rounded_rectangle((x1, y1, x2, y2), radius=18, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    hx, hy = x1 + 28, y1 + 30; _icon(d, hx + 10, hy + 10, label_icon, 20, MUTED); d.text((hx + 32, hy), label.upper(), font=_font(17), fill=MUTED)
    sc_color = RED if score_bad else SILVER_HI; d.text((hx, hy + 40), str(score), font=_font(52), fill=sc_color)
    cw, ch, gap = 130, 184, 18; cx_start = x1 + 28 + 210 + 32; cy = y1 + (y2 - y1 - ch) // 2
    for i, c in enumerate(cards):
        cx = cx_start + i * (cw + gap)
        if cx + cw > x2 - 28: break
        if c.get("back"): _draw_card(d, img, cx, cy, cw, ch, "", 0, (0, 0, 0), is_back=True)
        else: _draw_card(d, img, cx, cy, cw, ch, c["rank"], c["suit"], c["color"])

def render_roulette_spin(user_id, balance, bet):
    img, d = base_canvas(uid_label="рулетка", status_label="Прокрутка", logo_icon=I_GEM); b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [{"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": GOLD}, {"label": "Прокрутка", "value": "≈ 2 сек", "icon": I_CLOCK, "color": SILVER}])
    right_box = (512, b1, 1750, b2); _draw_stack_panel(img, d, right_box, radius=22); ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, "Прокрутка барабана", "ждём результат"); iy1 += 76
    _hint(d, ix1, iy2 - 30, ix2, iy2, GOLD, I_INFO, "Не закрывай сообщение — результат появится здесь же")
    stage_y1, stage_y2 = iy1, iy2 - 50; cx = (ix1 + ix2) // 2; cy = (stage_y1 + stage_y2) // 2 - 20
    _draw_wheel(img, d, cx, cy, 150); d.text((cx, cy + 190), "Подбираем слот", font=_font(32), fill=GOLD, anchor="mm")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_roulette_win(user_id, balance, bet, result_name, mult, net, payout):
    img, d = base_canvas(uid_label="рулетка", status_label="Выигрыш", logo_icon=I_TROPHY); b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [{"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "icon": I_TROPHY, "color": GREEN}, {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER}])
    right_box = (512, b1, 1750, b2); _draw_stack_panel(img, d, right_box, radius=22); ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, "Рулетка монет", f"x{1+mult:.1f} · {result_name}"); iy1 += 76
    _hint(d, ix1, iy2 - 30, ix2, iy2, GREEN, I_CHECK_C, "Удача на твоей стороне — попробуешь ещё?")
    content_y1, content_y2 = iy1, iy2 - 50; total_h = content_y2 - content_y1; gap = 16; hero_h = int(total_h * 0.48); cells_h = total_h - hero_h - gap
    _hero(img, d, (ix1, content_y1, ix2, content_y1 + hero_h), GREEN, I_TROPHY, "выпало", f"{result_name} · x{1+mult:.1f}")
    cells_y1 = content_y1 + hero_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [{"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "color": SILVER_HI}, {"label": "Возврат", "value": f"+{payout:,} DC".replace(",", " "), "color": GREEN}, {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "color": GREEN}, {"label": "Страховка", "value": "нет", "color": DIM}], cols=4)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_roulette_lose(user_id, balance, bet, refund, result_name):
    lost = bet - refund; img, d = base_canvas(uid_label="рулетка", status_label="Проигрыш", logo_icon=I_XMARK); b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [{"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "icon": I_TREND_DOWN, "color": RED}, {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "icon": I_SHIELD, "color": (GREEN if refund else DIM)}])
    right_box = (512, b1, 1750, b2); _draw_stack_panel(img, d, right_box, radius=22); ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, "Рулетка монет", "проигрыш"); iy1 += 76
    _hint(d, ix1, iy2 - 30, ix2, iy2, RED, I_XMARK_C, "Не расстраивайся — повезёт в следующий раз")
    content_y1, content_y2 = iy1, iy2 - 50; total_h = content_y2 - content_y1; gap = 16; hero_h = int(total_h * 0.48); cells_h = total_h - hero_h - gap
    _hero(img, d, (ix1, content_y1, ix2, content_y1 + hero_h), RED, I_XMARK_C, "выпало", f"{result_name} · x0")
    cells_y1 = content_y1 + hero_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [{"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "color": SILVER_HI}, {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "color": (GREEN if refund else DIM)}, {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "color": RED}, {"label": "Баланс", "value": f"{balance:,} DC".replace(",", " "), "color": SILVER_HI}], cols=4)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_blackjack_table(user_id, balance, bet, dealer_cards, player_cards, player_score, dealer_first_card):
    img, d = base_canvas(uid_label="блэкджек", status_label="Твой ход", logo_icon=I_DICE); b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [{"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": GOLD}, {"label": "Действие", "value": "взять / хватит", "icon": I_HAND, "color": BLUE}])
    right_box = (512, b1, 1750, b2); _draw_stack_panel(img, d, right_box, radius=22); ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, "Блэкджек", f"стол · {bet:,} DC".replace(",", " ")); iy1 += 76
    _hint(d, ix1, iy2 - 30, ix2, iy2, GOLD, I_HAND_R, "Взять карту или остановиться? Кнопки под сообщением")
    content_y1, content_y2 = iy1, iy2 - 50; gap = 16; frame_h = (content_y2 - content_y1 - gap) // 2
    _draw_card_frame(img, d, (ix1, content_y1, ix2, content_y1 + frame_h), "Дилер", I_USER_SEC, "?", dealer_cards)
    py = content_y1 + frame_h + gap; _draw_card_frame(img, d, (ix1, py, ix2, py + frame_h), "Ты", I_USER, player_score, player_cards)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_blackjack_result(user_id, balance, bet, total_bet, payout, net, dealer_cards, player_cards, dealer_score, player_score, outcome):
    STATUS = {"win": ("Победа", GREEN, I_TROPHY, "Победа · x2", "блэкджек"), "blackjack": ("Блэкджек", GOLD, I_TROPHY, "Блэкджек · x2.5", "блэкджек"), "push": ("Ничья", SILVER, I_HANDSHAKE, "Ничья · равные очки", "возврат ставки"), "lose": ("Проигрыш", RED, I_XMARK_C, "Проигрыш", "блэкджек"), "bust": ("Перебор", RED, I_BOLT, f"Перебор · {player_score}", "блэкджек")}
    status, color, hero_icon, hero_title, sub = STATUS.get(outcome, STATUS["lose"]); img, d = base_canvas(uid_label="блэкджек", status_label=status, logo_icon=hero_icon); b1, b2 = 158, 950
    if outcome in ("win", "blackjack"): blocks = [{"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "icon": I_TROPHY, "color": GREEN}, {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER}]
    elif outcome == "push": blocks = [{"label": "Возврат", "value": f"+{payout:,} DC".replace(",", " "), "icon": I_ROTATE_L, "color": GOLD}, {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER}]
    else: blocks = [{"label": "Потеряно", "value": f"−{total_bet:,} DC".replace(",", " "), "icon": I_TREND_DOWN, "color": RED}, {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER}]
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, blocks)
    right_box = (512, b1, 1750, b2); _draw_stack_panel(img, d, right_box, radius=22); ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, hero_title, sub); iy1 += 76
    content_y1, content_y2 = iy1, iy2; gap = 16; frame_h = (content_y2 - content_y1 - gap) // 2
    _draw_card_frame(img, d, (ix1, content_y1, ix2, content_y1 + frame_h), "Дилер", I_USER_SEC, dealer_score, dealer_cards, score_bad=(dealer_score > 21))
    py = content_y1 + frame_h + gap; _draw_card_frame(img, d, (ix1, py, ix2, py + frame_h), "Ты", I_USER, player_score, player_cards, score_bad=(player_score > 21))
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_coinflip_choice(user_id, balance, bet):
    img, d = base_canvas(uid_label="монетка", status_label="Выбор стороны", logo_icon=I_COINS); b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [{"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": GOLD}, {"label": "Выплата", "value": "x1.9", "icon": I_PERCENT, "color": GREEN}])
    right_box = (512, b1, 1750, b2); _draw_stack_panel(img, d, right_box, radius=22); ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, "Монетка", "орёл или решка"); iy1 += 76
    _hint(d, ix1, iy2 - 30, ix2, iy2, GOLD, I_CLOCK, "У тебя 60 секунд на выбор — кнопки под сообщением")
    choice_h = 80; choices_y1 = iy2 - 30 - 20 - choice_h; stage_y1, stage_y2 = iy1, choices_y1 - 16; cx = (ix1 + ix2) // 2; cy = (stage_y1 + stage_y2) // 2
    _draw_coin(img, d, cx, cy, 130, "default"); ch_w, gap = 260, 22; total_w = ch_w * 2 + gap; ch_start = cx - total_w // 2
    for i, (label, icon) in enumerate([("Орёл", I_CROW), ("Решка", I_CROWN)]):
        bx, by = ch_start + i * (ch_w + gap), choices_y1; d.rounded_rectangle((bx, by, bx + ch_w, by + choice_h), radius=16, fill=STACK_HDR + (255,), outline=STACK_BRD + (255,), width=3); _icon(d, bx + 48, by + choice_h // 2, icon, 30, GOLD); d.text((bx + 90, by + choice_h // 2), label, font=_font(28), fill=SILVER_HI, anchor="lm")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_coinflip_win(user_id, balance, bet, payout, net, result_side, user_choice):
    img, d = base_canvas(uid_label="монетка", status_label="Победа", logo_icon=I_TROPHY); b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [{"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "icon": I_TROPHY, "color": GREEN}, {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER}])
    right_box = (512, b1, 1750, b2); _draw_stack_panel(img, d, right_box, radius=22); ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, f"{result_side} · x1.9", "победа"); iy1 += 76
    content_y1, content_y2 = iy1, iy2; total_h = content_y2 - content_y1; gap = 16; coin_h = int(total_h * 0.52); cells_h = total_h - coin_h - gap
    cx = (ix1 + ix2) // 2; cy = content_y1 + coin_h // 2; _draw_coin(img, d, cx, cy, 130, "win"); cells_y1 = content_y1 + coin_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [{"label": "Твой выбор", "value": user_choice, "color": SILVER_HI}, {"label": "Выпало", "value": result_side, "color": GREEN}, {"label": "Выплата", "value": f"+{payout:,} DC".replace(",", " "), "color": GREEN}, {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "color": GREEN}], cols=2)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_coinflip_lose(user_id, balance, bet, refund, result_side, user_choice):
    lost = bet - refund; img, d = base_canvas(uid_label="монетка", status_label="Мимо", logo_icon=I_XMARK_C); b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [{"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "icon": I_TREND_DOWN, "color": RED}, {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "icon": I_SHIELD, "color": (GREEN if refund else DIM)}])
    right_box = (512, b1, 1750, b2); _draw_stack_panel(img, d, right_box, radius=22); ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, f"{result_side} · мимо", "проигрыш"); iy1 += 76
    content_y1, content_y2 = iy1, iy2; total_h = content_y2 - content_y1; gap = 16; coin_h = int(total_h * 0.52); cells_h = total_h - coin_h - gap
    cx = (ix1 + ix2) // 2; cy = content_y1 + coin_h // 2; _draw_coin(img, d, cx, cy, 130, "lose"); cells_y1 = content_y1 + coin_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [{"label": "Твой выбор", "value": user_choice, "color": SILVER_HI}, {"label": "Выпало", "value": result_side, "color": RED}, {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "color": (GREEN if refund else DIM)}, {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "color": RED}], cols=2)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

# ============================================================
# ЛОГИКА КАЗИНО (Рулетка, Блэкджек, Монетка)
# ============================================================
def _apply_pet_casino_bonus(user_id: int, payout: int) -> tuple[int, float]:
    try:
        from pet.core import get_casino_bonus
        mult = get_casino_bonus(user_id)
        return (int(payout * mult), mult) if mult > 1.0 else (payout, 1.0)
    except Exception: return payout, 1.0

async def _edit_msg(inter, **kwargs):
    try:
        if inter.response.is_done(): await inter.edit_original_response(**kwargs)
        else: await inter.response.edit_message(**kwargs)
    except disnake.InteractionResponded:
        try: await inter.edit_original_response(**kwargs)
        except Exception: pass
    except disnake.NotFound: pass

async def _send_game_screen(inter, buf, fname, view=None):
    file = disnake.File(buf, filename=fname); e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{fname}")
    await _edit_msg(inter, content=None, embed=e, file=file, attachments=[], view=view)

def _suit_code(suit: str) -> int: return {"♠️": 0xf2f4, "♥️": 0xf004, "♦️": 0xf219, "♣️": 0xf327}.get(suit, 0xf2f4)
def _suit_color(suit: str): return (211, 47, 47) if suit in ("♥️", "♦️") else (26, 26, 30)
def _cards_for_render(cards): return [{"rank": c[0], "suit": _suit_code(c[1]), "color": _suit_color(c[1])} for c in cards]

async def _check_casino_achievements(user_id, bet=0, profit=0):
    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot
        stats = load_roulette_stats(); await check_and_unlock(user_id, "casino_games", value=stats.get("rolls", 0), bot=bot)
        if bet >= 1000: await check_and_unlock(user_id, "casino_bet", value=bet, bot=bot)
        if profit >= 10000: await check_and_unlock(user_id, "casino_lucky", value=profit, bot=bot)
    except Exception: pass

async def _check_pet_xp(user_id: int, source: str = "casino"):
    try:
        from pet.core import add_pet_xp
        await add_pet_xp(user_id, 3, source)
    except Exception: pass

def load_daily_deal(): return load_json(DAILY_DEAL_FILE, {})
def save_daily_deal(d): save_json(DAILY_DEAL_FILE, d)

def generate_random_deal(discount):
    catalog = load_shop_catalog(); items = []
    for cat_key, cat_data in catalog.items():
        if cat_key in ("boosts", "casino", "gifts"): continue
        for item_key, item_data in cat_data.get("items", {}).items(): items.append((cat_key, item_key, item_data))
    if not items: return None
    cat_key, item_key, item_data = random.choice(items); orig = item_data["price"]; new = max(int(orig * (100 - discount) / 100), 1)
    return {"cat_key": cat_key, "item_key": item_key, "item_data": item_data, "original_price": orig, "discount": discount, "new_price": new, "category_label": catalog[cat_key]["label"]}

def _current_deal_slot(): return int(time.time() // (DAILY_DEAL_REFRESH_HOURS * 3600))

def refresh_daily_deal(force=False):
    slot = _current_deal_slot(); data = load_daily_deal(); saved = data.get("item")
    if saved and saved.get("discount") != DAILY_DEAL_DISCOUNT: force = True
    if not force and data.get("slot") == slot: return saved
    counter, old = data.get("counter", 0), data.get("item")
    if counter >= DAILY_DEALS_PER_CYCLE: save_daily_deal({"slot": slot, "item": old, "counter": 0, "updated_at": int(time.time())}); return old
    deal = generate_random_deal(DAILY_DEAL_DISCOUNT)
    if not deal: return None
    save_daily_deal({"slot": slot, "item": deal, "counter": counter + 1, "updated_at": int(time.time())}); return deal

def load_roulette_stats(): return load_json(ROULETTE_STATS_FILE, {"total_bets": 0, "total_won": 0, "total_lost": 0, "rolls": 0})
def save_roulette_stats(data): save_json(ROULETTE_STATS_FILE, data)

ROULETTE_ROLLS = [{"name": "Проигрыш", "mult": -1.0, "chance": 55.0, "color": 0xed4245}, {"name": "Малый выигрыш", "mult": 0.2, "chance": 20.0, "color": 0x95a5a6}, {"name": "Средний выигрыш", "mult": 0.5, "chance": 12.0, "color": 0x149bd0}, {"name": "Двойной", "mult": 1.0, "chance": 8.0, "color": 0x2ecc71}, {"name": "Тройной", "mult": 2.0, "chance": 3.0, "color": 0xf7c991}, {"name": "JACKPOT", "mult": 4.0, "chance": 1.5, "color": 0xffaa00}, {"name": "MEGA JACKPOT", "mult": 9.0, "chance": 0.5, "color": 0xff00aa}]

def roll_roulette():
    r = random.uniform(0, sum(roll["chance"] for roll in ROULETTE_ROLLS)); cur = 0
    for roll in ROULETTE_ROLLS:
        cur += roll["chance"]
        if r <= cur: return roll
    return ROULETTE_ROLLS[0]

async def _roulette_play(inter, bet, reason="Ставка в рулетке монет"):
    user_id = inter.author.id
    if bet < CASINO_MIN_BET: return await inter.response.send_message(f"❌ Минимум — **{CASINO_MIN_BET} DC**.", ephemeral=True)
    if bet > CASINO_MAX_BET: return await inter.response.send_message(f"❌ Максимум — **{CASINO_MAX_BET} DC**.", ephemeral=True)
    balance = await get_user_balance(user_id)
    if bet > balance: return await inter.response.send_message(f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`\n> **Ставка:** `{bet} DC`", ephemeral=True)
    if not inter.response.is_done(): await inter.response.defer(ephemeral=True)
    if not await remove_dc(user_id, bet, reason): return await inter.edit_original_response(content="❌ Не удалось списать DC.")
    try: await _send_game_screen(inter, render_roulette_spin(user_id, balance, bet), f"roulette_spin_{user_id}.png")
    except Exception as e: await inter.edit_original_response(content="🎰 Крутим барабан...")
    await asyncio.sleep(2.2); result = roll_roulette(); mult = result["mult"]
    if on_casino_quest_hook:
        try: await on_casino_quest_hook(user_id)
        except Exception: pass
    await _check_casino_achievements(user_id, bet=bet); await _check_pet_xp(user_id, "roulette")
    if mult > 0:
        payout = bet + int(bet * mult); payout, pet_mult = _apply_pet_casino_bonus(user_id, payout); payout, used = apply_casino_win(user_id, payout); net = payout - bet; r_reason = f"Выигрыш в рулетке: {result['name']}"
        if pet_mult > 1.0: r_reason += f" (питомец ×{pet_mult:.2f})"
        if used: r_reason += f" ({', '.join(used)})"
        await add_dc(user_id, payout, r_reason, to_clan_pool=True)
        if on_casino_win_hook:
            try: await on_casino_win_hook(user_id, payout, bet)
            except Exception: pass
        new_balance = await get_user_balance(user_id)
        try: await _send_game_screen(inter, render_roulette_win(user_id, new_balance, bet, result["name"], mult, net, payout), f"roulette_win_{user_id}.png", view=RouletteRetryView(bet))
        except Exception: pass
        if net >= 10000: await _check_casino_achievements(user_id, profit=net)
        st = load_roulette_stats(); st["total_bets"] += bet; st["total_won"] += net; st["rolls"] += 1; save_roulette_stats(st)
        asyncio.create_task(log_discord(title=f"🎰 Рулетка: {result['name']}", description=f"> **Юзер:** {inter.author.mention}\n> **Ставка:** `{bet} DC`\n> **Множитель:** `x{1 + mult:.1f}`\n" + (f"> **Бонус питомца:** `×{pet_mult:.2f}`\n" if pet_mult > 1.0 else "") + f"> **Профит:** `+{net} DC`\n> **Баланс:** `{new_balance} DC`", color=result["color"]))
    else:
        refund = try_insurance(user_id, bet)
        if refund > 0: await add_dc(user_id, refund, "Страховка ставки (рулетка)")
        new_balance = await get_user_balance(user_id)
        try: await _send_game_screen(inter, render_roulette_lose(user_id, new_balance, bet, refund, result["name"]), f"roulette_lose_{user_id}.png", view=RouletteRetryView(bet))
        except Exception: pass
        st = load_roulette_stats(); st["total_bets"] += bet; st["total_lost"] += (bet - refund); st["rolls"] += 1; save_roulette_stats(st)
        asyncio.create_task(log_discord(title="🎰 Рулетка: проигрыш", description=f"> **Юзер:** {inter.author.mention}\n> **Ставка:** `{bet} DC`\n> **Страховка:** `+{refund} DC`\n> **Баланс:** `{new_balance} DC`", color=0xed4245))

class RouletteModal(Modal):
    def __init__(self): super().__init__(title="🎰 Рулетка монет", components=[TextInput(label=f"Ставка ({CASINO_MIN_BET}-{CASINO_MAX_BET} DC)", placeholder=f"От {CASINO_MIN_BET} до {CASINO_MAX_BET}", custom_id="bet", min_length=1, max_length=10)])
    async def callback(self, inter):
        s = inter.text_values["bet"].strip()
        if not s.isdigit(): return await inter.response.send_message("❌ Целое число.", ephemeral=True)
        await _roulette_play(inter, int(s), reason="Ставка в рулетке монет")

class RouletteRetryView(View):
    def __init__(self, last_bet):
        super().__init__(timeout=300); self.last_bet = last_bet
        for label, cid, emoji_data, style, cb in [("Играть ещё", "roulette_retry", ("image", 1555994370933653544), ButtonStyle.gray, self.replay), ("Повтор ставки", "roulette_repeat", ("povtor", 1555993533629071360), ButtonStyle.gray, self.repeat), ("Двойная ставка", "roulette_double", ("flas", 1551289202279325756), ButtonStyle.danger, self.double)]:
            b = Button(label=label, style=style, custom_id=cid, emoji=PartialEmoji(name=emoji_data[0], id=emoji_data[1]), row=0); b.callback = cb; self.add_item(b)
    async def replay(self, inter): await inter.response.send_modal(RouletteModal())
    async def repeat(self, inter): await _roulette_play(inter, self.last_bet, reason="Повтор ставки в рулетке")
    async def double(self, inter):
        nb = self.last_bet * 2
        if nb > CASINO_MAX_BET: return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET} DC.", ephemeral=True)
        await _roulette_play(inter, nb, reason="Двойная ставка в рулетке")

BLACKJACK_MIN_BET, BLACKJACK_MAX_BET, BLACKJACK_BLACKJACK_MULT, BLACKJACK_WIN_MULT, BLACKJACK_DEALER_STAND = CASINO_MIN_BET, CASINO_MAX_BET, 2.5, 2.0, 17
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]; SUITS = ["♠️", "♥️", "♦️", "♣️"]

def _new_deck(): d = [(r, s) for r in RANKS for s in SUITS]; random.shuffle(d); return d
def _hand_value(hand):
    total, aces = 0, 0
    for r, s in hand:
        if r == "A": aces += 1; total += 11
        elif r in ("J", "Q", "K"): total += 10
        else: total += int(r)
    while total > 21 and aces > 0: total -= 10; aces -= 1
    return total
def _dealer_play(game):
    while _hand_value(game["dealer"]) < BLACKJACK_DEALER_STAND: game["dealer"].append(game["deck"].pop())

async def _bj_finalize(inter, game, outcome):
    user_id, bet = game["user_id"], game["bet"]; total_bet = bet * 2 if game.get("doubled") else bet
    if outcome == "blackjack": payout, reason = int(total_bet * BLACKJACK_BLACKJACK_MULT), "Блэкджек (x2.5)"
    elif outcome == "win": payout, reason = int(total_bet * BLACKJACK_WIN_MULT), "Победа в блэкджеке (x2)"
    elif outcome == "push": payout, reason = total_bet, "Ничья в блэкджеке (возврат)"
    else: payout, reason = 0, "Проигрыш в блэкджеке"
    pet_mult = 1.0
    if payout > 0:
        payout, pet_mult = _apply_pet_casino_bonus(user_id, payout); payout, used = apply_casino_win(user_id, payout)
        if pet_mult > 1.0: reason += f" (питомец ×{pet_mult:.2f})"
        if used: reason += f" ({', '.join(used)})"
        await add_dc(user_id, payout, reason, to_clan_pool=True)
        if on_casino_win_hook:
            try: await on_casino_win_hook(user_id, payout, total_bet)
            except Exception: pass
        if outcome == "blackjack":
            try:
                from clan.achievements import unlock_achievement
                from core.bot import bot
                await unlock_achievement(user_id, "casino_bj21", bot=bot)
            except Exception: pass
        net = payout - total_bet
        if net >= 10000: await _check_casino_achievements(user_id, profit=net)
    else:
        refund = try_insurance(user_id, total_bet)
        if refund > 0: await add_dc(user_id, refund, "Страховка ставки (блэкджек)"); payout = refund
    new_balance = await get_user_balance(user_id); net = payout - total_bet
    asyncio.create_task(log_discord(title=f"🃏 Блэкджек: {outcome}", description=f"> **Юзер:** <@{user_id}>\n> **Ставка:** `{total_bet} DC`\n" + (f"> **Бонус питомца:** `×{pet_mult:.2f}`\n" if pet_mult > 1.0 else "") + f"> **Выплата:** `{payout} DC`\n> **Профит:** `{'+' if net >= 0 else ''}{net} DC`\n> **Баланс:** `{new_balance} DC`", color=0x2ecc71 if payout > 0 else 0xed4245))
    dealer_cards, player_cards = _cards_for_render(game["dealer"]), _cards_for_render(game["player"])
    try:
        buf = render_blackjack_result(user_id, new_balance, bet, total_bet, payout, net, dealer_cards, player_cards, _hand_value(game["dealer"]), _hand_value(game["player"]), outcome)
        file = disnake.File(buf, filename=f"bj_res_{user_id}.png"); e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{file.filename}")
        await _edit_msg(inter, content=None, embed=e, file=file, attachments=[], view=BlackjackRetryView(bet))
    except Exception: pass

async def _blackjack_play(inter, bet, reason="Ставка в блэкджеке"):
    user_id = inter.author.id
    if bet < BLACKJACK_MIN_BET: return await inter.response.send_message(f"❌ Минимум — **{BLACKJACK_MIN_BET} DC**.", ephemeral=True)
    if bet > BLACKJACK_MAX_BET: return await inter.response.send_message(f"❌ Максимум — **{BLACKJACK_MAX_BET} DC**.", ephemeral=True)
    balance = await get_user_balance(user_id)
    if bet > balance: return await inter.response.send_message(f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`", ephemeral=True)
    if not inter.response.is_done(): await inter.response.defer(ephemeral=True)
    if not await remove_dc(user_id, bet, reason): return await inter.edit_original_response(content="❌ Не удалось списать DC.")
    deck = _new_deck(); game = {"user_id": user_id, "bet": bet, "deck": deck, "player": [deck.pop(), deck.pop()], "dealer": [deck.pop(), deck.pop()], "doubled": False, "finished": False}
    if on_casino_quest_hook:
        try: await on_casino_quest_hook(user_id)
        except Exception: pass
    await _check_casino_achievements(user_id, bet=bet); await _check_pet_xp(user_id, "blackjack")
    dealer_first = game["dealer"][0]; dealer_cards = [{"rank": dealer_first[0], "suit": _suit_code(dealer_first[1]), "color": _suit_color(dealer_first[1])}, {"back": True}]; player_cards = _cards_for_render(game["player"])
    try:
        buf = render_blackjack_table(user_id, balance - bet, bet, dealer_cards, player_cards, _hand_value(game["player"]), dealer_first)
        await _send_game_screen(inter, buf, f"bj_{user_id}.png", view=BlackjackView(game))
    except Exception: await inter.edit_original_response(content="🃏 Раздача карт...")
    if _hand_value(game["player"]) == 21:
        _dealer_play(game); game["finished"] = True; outcome = "push" if _hand_value(game["dealer"]) == 21 and len(game["dealer"]) == 2 else "blackjack"
        await _bj_finalize(inter, game, outcome)

class BlackjackBetModal(Modal):
    def __init__(self): super().__init__(title="Блэкджек — ставка", components=[TextInput(label=f"Ставка ({BLACKJACK_MIN_BET}-{BLACKJACK_MAX_BET} DC)", placeholder=f"От {BLACKJACK_MIN_BET} до {BLACKJACK_MAX_BET}", custom_id="bet", min_length=1, max_length=10)])
    async def callback(self, inter):
        s = inter.text_values["bet"].strip()
        if not s.isdigit(): return await inter.response.send_message("❌ Целое число.", ephemeral=True)
        await _blackjack_play(inter, int(s), reason="Ставка в блэкджеке")

class BlackjackView(View):
    def __init__(self, game):
        super().__init__(timeout=300); self.game = game
        b1 = Button(label=f"{P}{P}Взять{P}{P}", style=ButtonStyle.gray, custom_id="bj_hit", emoji=PartialEmoji(name="adde", id=1551288309240696954), row=0); b1.callback = self.hit; self.add_item(b1)
        b2 = Button(label=f"{P}{P}Хватит{P}{P}", style=ButtonStyle.gray, custom_id="bj_stand", emoji=PartialEmoji(name="PAM", id=1551288362822795434), row=0); b2.callback = self.stand; self.add_item(b2)
        b3 = Button(label=f"{P}{P}Удвоить{P}{P}", style=ButtonStyle.danger, custom_id="bj_double", emoji=PartialEmoji(name="flas", id=1551289202279325756), row=0); b3.callback = self.double; self.add_item(b3)
    async def _check(self, inter):
        if inter.author.id != self.game["user_id"]: await inter.response.send_message("⛔ Не ваша игра.", ephemeral=True); return False
        if self.game["finished"]: await inter.response.send_message("⛔ Завершена.", ephemeral=True); return False
        return True
    async def _redraw(self, inter):
        dealer_first = self.game["dealer"][0]; dealer_cards = [{"rank": dealer_first[0], "suit": _suit_code(dealer_first[1]), "color": _suit_color(dealer_first[1])}, {"back": True}]
        try:
            buf = render_blackjack_table(self.game["user_id"], 0, self.game["bet"], dealer_cards, _cards_for_render(self.game["player"]), _hand_value(self.game["player"]), dealer_first)
            file = disnake.File(buf, filename=f"bj_{self.game['user_id']}.png"); e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{file.filename}")
            await _edit_msg(inter, content=None, embed=e, file=file, attachments=[], view=self)
        except Exception: pass
    async def hit(self, inter):
        if not await self._check(inter): return
        self.game["player"].append(self.game["deck"].pop()); v = _hand_value(self.game["player"])
        if v > 21: self.game["finished"] = True; await _bj_finalize(inter, self.game, "bust")
        elif v == 21: await self._stand_logic(inter)
        else: await self._redraw(inter)
    async def stand(self, inter):
        if not await self._check(inter): return
        await self._stand_logic(inter)
    async def _stand_logic(self, inter):
        _dealer_play(self.game); self.game["finished"] = True; pv, dv = _hand_value(self.game["player"]), _hand_value(self.game["dealer"])
        outcome = "win" if dv > 21 or pv > dv else "push" if pv == dv else "lose"
        await _bj_finalize(inter, self.game, outcome)
    async def double(self, inter):
        if not await self._check(inter): return
        if self.game.get("doubled"): return await inter.response.send_message("⛔ Уже удвоено.", ephemeral=True)
        if len(self.game["player"]) != 2: return await inter.response.send_message("⛔ Только на первых двух.", ephemeral=True)
        uid, bet = self.game["user_id"], self.game["bet"]
        if bet * 2 > CASINO_MAX_BET: return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET}.", ephemeral=True)
        if (await get_user_balance(uid)) < bet: return await inter.response.send_message(f"❌ Нужно ещё `{bet} DC`.", ephemeral=True)
        if not await remove_dc(uid, bet, "Удвоение в блэкджеке"): return await inter.response.send_message("❌ Ошибка списания.", ephemeral=True)
        self.game["doubled"] = True; self.game["player"].append(self.game["deck"].pop()); await self._stand_logic(inter)

class BlackjackRetryView(View):
    def __init__(self, last_bet):
        super().__init__(timeout=300); self.last_bet = last_bet
        for label, cid, emoji_data, style, cb in [("Играть ещё", "bj_retry", ("image", 1555994370933653544), ButtonStyle.gray, self.replay), ("Повтор ставки", "bj_repeat", ("povtor", 1555993533629071360), ButtonStyle.gray, self.repeat), ("Двойная ставка", "bj_double_next", ("flas", 1551289202279325756), ButtonStyle.danger, self.double)]:
            b = Button(label=label, style=style, custom_id=cid, emoji=PartialEmoji(name=emoji_data[0], id=emoji_data[1]), row=0); b.callback = cb; self.add_item(b)
    async def replay(self, inter): await inter.response.send_modal(BlackjackBetModal())
    async def repeat(self, inter): await _blackjack_play(inter, self.last_bet, reason="Повтор в блэкджеке")
    async def double(self, inter):
        nb = self.last_bet * 2
        if nb > CASINO_MAX_BET: return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET} DC.", ephemeral=True)
        await _blackjack_play(inter, nb, reason="Двойная в блэкджеке")

COINFLIP_MIN_BET, COINFLIP_MAX_BET, COINFLIP_WIN_MULT = CASINO_MIN_BET, CASINO_MAX_BET, 1.9

async def _coinflip_play(inter, bet, reason="Ставка в монетке"):
    user_id = inter.author.id
    if bet < COINFLIP_MIN_BET: return await inter.response.send_message(f"❌ Минимум — **{COINFLIP_MIN_BET} DC**.", ephemeral=True)
    if bet > COINFLIP_MAX_BET: return await inter.response.send_message(f"❌ Максимум — **{COINFLIP_MAX_BET} DC**.", ephemeral=True)
    balance = await get_user_balance(user_id)
    if bet > balance: return await inter.response.send_message(f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`", ephemeral=True)
    if not inter.response.is_done(): await inter.response.defer(ephemeral=True)
    if not await remove_dc(user_id, bet, reason): return await inter.edit_original_response(content="❌ Не удалось списать DC.")
    await _check_casino_achievements(user_id, bet=bet); await _check_pet_xp(user_id, "coinflip")
    try: await _send_game_screen(inter, render_coinflip_choice(user_id, balance, bet), f"coin_choice_{user_id}.png", view=CoinflipChoiceView(bet))
    except Exception: pass

class CoinflipBetModal(Modal):
    def __init__(self): super().__init__(title="Монетка — ставка", components=[TextInput(label=f"Ставка ({COINFLIP_MIN_BET}-{COINFLIP_MAX_BET} DC)", placeholder=f"От {COINFLIP_MIN_BET} до {COINFLIP_MAX_BET}", custom_id="bet", min_length=1, max_length=10)])
    async def callback(self, inter):
        s = inter.text_values["bet"].strip()
        if not s.isdigit(): return await inter.response.send_message("❌ Целое число.", ephemeral=True)
        await _coinflip_play(inter, int(s), reason="Ставка в монетке")

class CoinflipChoiceView(View):
    def __init__(self, bet):
        super().__init__(timeout=60); self.bet = bet
        b1 = Button(label=f"{P}{P}{P}{P}Орёл{P}{P}{P}{P}", style=ButtonStyle.gray, custom_id="coin_heads", emoji=PartialEmoji(name="image", id=1551296060729725019), row=0); b1.callback = self.heads; self.add_item(b1)
        b2 = Button(label=f"{P}{P}{P}{P}Решка{P}{P}{P}{P}", style=ButtonStyle.gray, custom_id="coin_tails", emoji=PartialEmoji(name="2313", id=1551296094468575366), row=0); b2.callback = self.tails; self.add_item(b2)
    async def _play(self, inter, user_choice):
        result_side = random.choice(["heads", "tails"]); won = (result_side == user_choice); user_id, bet = inter.author.id, self.bet; payout, refund, pet_mult = 0, 0, 1.0
        if on_casino_quest_hook:
            try: await on_casino_quest_hook(user_id)
            except Exception: pass
        if won:
            payout = int(bet * COINFLIP_WIN_MULT); payout, pet_mult = _apply_pet_casino_bonus(user_id, payout); payout, used = apply_casino_win(user_id, payout); reason = f"Монетка ({result_side})"
            if pet_mult > 1.0: reason += f" (питомец ×{pet_mult:.2f})"
            if used: reason += f" ({', '.join(used)})"
            await add_dc(user_id, payout, reason, to_clan_pool=True)
            if on_casino_win_hook:
                try: await on_casino_win_hook(user_id, payout, bet)
                except Exception: pass
            net = payout - bet
            if net >= 10000: await _check_casino_achievements(user_id, profit=net)
        else:
            refund = try_insurance(user_id, bet)
            if refund > 0: await add_dc(user_id, refund, "Страховка (монетка)")
            net = -bet + refund
        new_balance = await get_user_balance(user_id); side_ru, choice_ru = ("Орёл" if result_side == "heads" else "Решка"), ("Орёл" if user_choice == "heads" else "Решка")
        try:
            if won: buf = render_coinflip_win(user_id, new_balance, bet, payout, payout - bet, side_ru, choice_ru)
            else: buf = render_coinflip_lose(user_id, new_balance, bet, refund, side_ru, choice_ru)
            file = disnake.File(buf, filename=f"coin_res_{user_id}.png"); e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{file.filename}")
            await _edit_msg(inter, content=None, embed=e, file=file, attachments=[], view=CoinflipRetryView(bet))
        except Exception: pass
        asyncio.create_task(log_discord(title=f"🪙 Монетка: {'победа' if won else 'проигрыш'}", description=f"> **Юзер:** <@{user_id}>\n> **Ставка:** `{bet} DC`\n> **Выбор:** `{user_choice}` → `{result_side}`\n" + (f"> **Бонус питомца:** `×{pet_mult:.2f}`\n" if pet_mult > 1.0 else "") + f"> **Выплата:** `{payout} DC`\n> **Страховка:** `{refund} DC`\n> **Баланс:** `{new_balance} DC`", color=0x2ecc71 if won else 0xed4245))
    async def heads(self, inter): await self._play(inter, "heads")
    async def tails(self, inter): await self._play(inter, "tails")

class CoinflipRetryView(View):
    def __init__(self, last_bet):
        super().__init__(timeout=300); self.last_bet = last_bet
        for label, cid, emoji_data, style, cb in [("Играть ещё", "coin_retry", ("image", 1555994370933653544), ButtonStyle.gray, self.replay), ("Повтор ставки", "coin_repeat", ("povtor", 1555993533629071360), ButtonStyle.gray, self.repeat), ("Двойная ставка", "coin_double", ("flas", 1551289202279325756), ButtonStyle.danger, self.double)]:
            b = Button(label=label, style=style, custom_id=cid, emoji=PartialEmoji(name=emoji_data[0], id=emoji_data[1]), row=0); b.callback = cb; self.add_item(b)
    async def replay(self, inter): await inter.response.send_modal(CoinflipBetModal())
    async def repeat(self, inter): await _coinflip_play(inter, self.last_bet, reason="Повтор в монетке")
    async def double(self, inter):
        nb = self.last_bet * 2
        if nb > CASINO_MAX_BET: return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET} DC.", ephemeral=True)
        await _coinflip_play(inter, nb, reason="Двойная в монетке")
