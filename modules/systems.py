# -*- coding: utf-8 -*-
"""
Единый модуль систем: Казино, Розыгрыши, Бусты, Достижения и Автозамена.
Объединяет:
  · actions (казино, рулетка, блэкджек, монетка)
  · casino_render (рендеры игр)
  · giveaways (розыгрыши)
  · others (бусты, акции, подарки, фикс ссылок)
  · achievements_panel (рендер панели достижений)
  · achievements_views (UI панели достижений)
"""
import os
import sys
import json
import time
import random
import asyncio
import math
import re
import ast
import io
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple, Set

import disnake
from disnake.ext import commands, tasks
from disnake.ui import View, Button, Select, Modal, TextInput
from disnake import ButtonStyle, SelectOption, PartialEmoji
from PIL import Image, ImageDraw, ImageFont

from core.utils import (
    BASE_DIR, DATA_DIR, ADD_DIR, CONFIG, FILES,
    logger, db, cur,
    load_json, save_json, now_ts,
    log_discord, get_dc_cache, save_dc_cache, sync_dc_to_json,
    get_item, get_active_items, activate_item, consume_use, clear_item,
)

from modules.dc import (
    add_dc, remove_dc, add_purchase,
    get_user_balance, get_user_purchases, remove_purchase,
    load_shop_catalog, get_daily_gift_status,
)

from clan.achievements import (
    ACHIEVEMENTS, CATEGORIES, CATEGORY_KEYS, CATEGORY_ORDER,
    get_category_progress, get_overall_progress,
    check_and_unlock, get_user_unlocked_set,
)

try:
    from clan.quests import on_casino_quest_hook, on_casino_win_hook, on_gift_quest_hook
except Exception:
    on_casino_quest_hook = None
    on_casino_win_hook = None
    on_gift_quest_hook = None

# ============================================================
# ОБЩИЕ КОНСТАНТЫ И УТИЛИТЫ ДЛЯ РЕНДЕРА
# ============================================================
FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_FONT_CACHE = {}
_FA_CACHE = {}

def _font(size: int):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        f = ImageFont.truetype(FONT_BOLD, size)
    except Exception:
        f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f

def _fa(size: int):
    if size in _FA_CACHE:
        return _FA_CACHE[size]
    f = None
    if os.path.exists(FONT_FA):
        try:
            f = ImageFont.truetype(FONT_FA, size)
        except Exception:
            pass
    _FA_CACHE[size] = f
    return f

def _tw(d, text, font):
    b = d.textbbox((0, 0), text, font=font)
    return b[2] - b[0]

def _ellipsis(d, text, font, max_w):
    if _tw(d, text, font) <= max_w:
        return text
    t = text
    while t and _tw(d, t + "…", font) > max_w:
        t = t[:-1]
    return t + "…"

def _wrap(d, text, font, max_w, max_lines=3):
    words = (text or "").split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if _tw(d, test, font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
                if len(lines) >= max_lines:
                    cur = ""
                    break
            cur = w
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines or [""]

def _fmt(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)

def _draw_icon(d, cx, cy, code, size, color):
    f = _fa(size)
    if f is None:
        return
    try:
        d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception:
        pass

def _alpha_fill(base, box, color, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if radius > 0:
        ld.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=color + (alpha,))
    else:
        ld.rectangle((0, 0, w - 1, h - 1), fill=color + (alpha,))
    base.paste(layer, (x1, y1), layer)

def _gradient_box(base, box, c1, c2, alpha=30, radius=0, horizontal=True):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    steps = w if horizontal else h
    for i in range(steps):
        t = i / max(steps - 1, 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        if horizontal:
            ld.line([(i, 0), (i, h)], fill=(r, g, b, alpha))
        else:
            ld.line([(0, i), (w, i)], fill=(r, g, b, alpha))
    if radius > 0:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        a = layer.split()[3]
        a = Image.composite(a, Image.new("L", (w, h), 0), mask)
        layer.putalpha(a)
    base.paste(layer, (x1, y1), layer)

def _lighten(c, a=0.4):
    a = max(0, min(1, a))
    return (min(int(c[0] + (255 - c[0]) * a), 255),
            min(int(c[1] + (255 - c[1]) * a), 255),
            min(int(c[2] + (255 - c[2]) * a), 255))

# ЦВЕТА
BG        = (10, 10, 12)
CARD_TOP  = (16, 16, 20)
STACK_BG  = (21, 21, 26)
STACK_BRD = (58, 58, 64)
STACK_HDR = (36, 36, 42)
INNER_BG  = (18, 18, 23)
INNER_BRD = (40, 40, 47)
TEXT      = (255, 255, 255)
TEXT_SOFT = (232, 232, 236)
MUTED     = (136, 136, 136)
DIM       = (102, 102, 102)
DARK      = (85, 85, 85)

SILVER      = (198, 208, 224)
SILVER_HI   = (224, 232, 245)
SILVER_DIM  = (120, 132, 155)
SILVER_BG   = (34, 38, 48)

GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)
GOLD      = (247, 201, 145)
BRONZE    = (209, 146, 96)
ORANGE    = (224, 140, 90)
STEEL     = (150, 180, 220)

GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)
GOLD_BG   = (40, 32, 21)

CARD_BRD  = (74, 74, 79)

CATEGORY_COLORS = {
    "green":  GREEN, "silver": SILVER, "gold":   GOLD, "blue":   BLUE,
    "purple": PURPLE, "red":    RED, "orange": ORANGE, "steel":  STEEL,
}

# FA ИКОНКИ
I_GEM=0xf3a5; I_STAR=0xf005; I_CART=0xf07a; I_BULLHORN=0xf0a1
I_BOLT=0xf0e7; I_GIFT=0xf06b; I_DICE=0xf522; I_USER=0xf007
I_ARROW_L=0xf060; I_FIRE=0xf06d; I_CHECK=0xf00c; I_XMARK=0xf00d
I_INFO=0xf05a; I_COINS=0xf51e; I_BAG=0xf290; I_CLOCK=0xf017
I_ELLIPSIS=0xf141; I_CIRCLE_M=0xf056; I_LIST=0xf03a; I_TROPHY=0xf091
I_HISTORY=0xf1da; I_PALETTE=0xf53f; I_TICKET=0xf145; I_CUBE=0xf1b2
I_SHOP=0xf54f; I_TAG=0xf02b; I_MASKS=0xf630; I_IMAGE=0xf03e
I_SMILE=0xf118; I_PEN_NIB=0xf5ad; I_LAYERS=0xf5fd; I_CLIPBOARD=0xf46d
I_HOURGLASS=0xf252; I_SACK=0xf81d; I_WALLET=0xf555; I_SEARCH=0xf002

I_LOCK=0xf023; I_AWARD=0xf559; I_SEEDLING=0xf4d8; I_COMMENT=0xf075
I_MIC=0xf130; I_PENF=0xf5ac; I_BRIEF=0xf0b1; I_DIA=0xf219
I_MONEY=0xf53a; I_CHART=0xf201; I_BANK=0xf19c; I_COMMS=0xf086
I_HEADPH=0xf025; I_SCROLL=0xf70e; I_HANDD=0xf4c0; I_SHIELD=0xf3ed
I_SPADE=0xf2f4; I_DICE5=0xf523; I_DICE6=0xf526; I_MONEY2=0xf53b
I_LISTC=0xf0ae; I_CALC=0xf274

FA_MAP = {
    "fa-crown": 0xf521, "fa-medal": 0xf5a2, "fa-award": I_AWARD,
    "fa-star": I_STAR, "fa-seedling": I_SEEDLING, "fa-comment": I_COMMENT,
    "fa-microphone": I_MIC, "fa-pen-fancy": I_PENF, "fa-cart-shopping": I_CART,
    "fa-gem": I_GEM, "fa-diamond": I_DIA, "fa-bag-shopping": I_BAG,
    "fa-briefcase": I_BRIEF, "fa-trophy": I_TROPHY, "fa-sack-dollar": I_SACK,
    "fa-coins": I_COINS, "fa-money-bill-wave": I_MONEY, "fa-gift": I_GIFT,
    "fa-chart-line": I_CHART, "fa-building-columns": I_BANK,
    "fa-comments": I_COMMS, "fa-bullhorn": I_BULLHORN, "fa-fire": I_FIRE,
    "fa-headphones": I_HEADPH, "fa-scroll": I_SCROLL,
    "fa-hand-holding-dollar": I_HANDD, "fa-shield-halved": I_SHIELD,
    "fa-spade": I_SPADE, "fa-dice": I_DICE, "fa-dice-five": I_DICE5,
    "fa-dice-six": I_DICE6, "fa-money-bill-1-wave": I_MONEY2,
    "fa-check": I_CHECK, "fa-list": I_LIST, "fa-list-check": I_LISTC,
    "fa-ticket": I_TICKET, "fa-calendar-check": I_CALC,
}

# ============================================================
# БЛОК 1: CASINO RENDER
# ============================================================
W, H = 1800, 1000
M = 14
PX, PY = 50, 50

def _canvas_casino(status_label, status_color):
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((M, M, W-1-M, H-1-M), radius=28, fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)
    hx, hy = PX, PY
    ls = 72
    d.rounded_rectangle((hx, hy, hx+ls, hy+ls), radius=18, fill=(58, 58, 64, 255), outline=(94, 94, 100, 255), width=2)
    _draw_icon(d, hx+ls//2, hy+ls//2+1, I_GEM, 32, SILVER_HI)
    bx = hx + ls + 22
    d.text((bx, hy+2), "DIAMOND", font=_font(38), fill=TEXT)
    d.text((bx+4, hy+50), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)
    _draw_header_tab(img, d, W - M - PX, hy, "казино", status_label, status_color)
    sep_y = hy + ls + 18
    d.line((PX, sep_y, W-M-PX, sep_y), fill=STACK_HDR + (255,), width=2)
    return img, d

def _draw_header_tab(img, d, x2, y1, label, value, color):
    lf = _font(13); vf = _font(24)
    lw = _tw(d, label.upper(), lf); vw = _tw(d, value.upper(), vf)
    inner_w = max(lw, vw)
    pad_x, pad_y = 26, 14
    tab_w = inner_w + pad_x * 2; tab_h = 80
    x1 = x2 - tab_w; y2 = y1 + tab_h
    _alpha_fill(img, (x1, y1, x2, y2), color, alpha=20, radius=14)
    d.rounded_rectangle((x1, y1, x2, y2), radius=14, outline=color + (120,), width=2)
    d.text((x2 - pad_x - lw, y1 + pad_y), label.upper(), font=lf, fill=MUTED)
    d.text((x2 - pad_x - vw, y1 + pad_y + 20), value.upper(), font=vf, fill=color)

def _panel(d, box, radius=22):
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=3)

def _draw_left_panel_casino(img, d, box, balance, blocks):
    _panel(d, box)
    x1, y1, x2, y2 = box
    pad = 28
    bis = 104; ibx = x1 + pad; iby = y1 + pad
    _alpha_fill(img, (ibx, iby, ibx+bis, iby+bis), SILVER, alpha=28, radius=26)
    d.rounded_rectangle((ibx, iby, ibx+bis, iby+bis), radius=26, outline=SILVER + (140,), width=3)
    _draw_icon(d, ibx+bis//2, iby+bis//2+1, I_GEM, 44, SILVER_HI)
    lx = ibx + bis + 22
    d.text((lx, iby + 6), "ТВОЙ БАЛАНС", font=_font(15), fill=MUTED)
    bs = f"{balance:,}".replace(",", " ")
    vf = _font(56)
    while _tw(d, bs + " DC", vf) > (x2 - pad - lx - 16) and vf.size > 32: vf = _font(vf.size - 2)
    d.text((lx, iby + 34), bs, font=vf, fill=TEXT)
    bw = _tw(d, bs, vf)
    d.text((lx+bw+8, iby + 34 + vf.size - 26), "DC", font=_font(26), fill=SILVER)
    sep_y = iby + bis + 20
    d.line((x1+pad, sep_y, x2-pad, sep_y), fill=STACK_HDR + (255,), width=2)
    by = sep_y + 20; bh, gap = 100, 16
    for i, blk in enumerate(blocks):
        cy1 = by + i * (bh + gap); cy2 = cy1 + bh
        cx1, cx2 = x1 + pad, x2 - pad
        color = blk["color"]
        _alpha_fill(img, (cx1, cy1, cx2, cy2), color, alpha=22, radius=18)
        d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=18, outline=_lighten(color, 0.15) + (180,), width=2)
        isz = 64; ix = cx1 + 22; iy = cy1 + (bh - isz) // 2
        _alpha_fill(img, (ix, iy, ix+isz, iy+isz), color, alpha=55, radius=16)
        d.rounded_rectangle((ix, iy, ix+isz, iy+isz), radius=16, outline=_lighten(color, 0.2) + (200,), width=2)
        _draw_icon(d, ix+isz//2, iy+isz//2+1, blk["icon"], 30, color)
        tx = ix + isz + 20
        d.text((tx, cy1 + 18), blk["label"].upper(), font=_font(14), fill=_lighten(color, 0.35))
        vf2 = _font(28); val = blk["value"]
        while _tw(d, val, vf2) > (cx2 - 20 - tx) and vf2.size > 16: vf2 = _font(vf2.size - 2)
        d.text((tx, cy1 + 50), val, font=vf2, fill=color)

def _rhead(d, x1, y1, x2, title, sub):
    d.text((x1, y1), title.upper(), font=_font(40), fill=TEXT)
    sf = _font(16); sw = _tw(d, sub.upper(), sf)
    d.text((x2 - sw, y1 + 22), sub.upper(), font=sf, fill=MUTED)
    d.line((x1, y1 + 60, x2, y1 + 60), fill=STACK_HDR + (255,), width=2)

def _hero(img, d, box, color, icon_code, label, title, title_color=TEXT):
    x1, y1, x2, y2 = box
    _alpha_fill(img, (x1, y1, x2, y2), color, alpha=18, radius=22)
    d.rounded_rectangle((x1, y1, x2, y2), radius=22, outline=color + (170,), width=3)
    isz = 180; ix = x1 + 40; iy = y1 + (y2 - y1 - isz) // 2
    _alpha_fill(img, (ix, iy, ix+isz, iy+isz), color, alpha=40, radius=36)
    d.rounded_rectangle((ix, iy, ix+isz, iy+isz), radius=36, outline=color + (200,), width=3)
    _draw_icon(d, ix+isz//2, iy+isz//2+1, icon_code, 80, color)
    tx = ix + isz + 40
    d.text((tx, y1 + 46), label.upper(), font=_font(18), fill=MUTED)
    tf = _font(64)
    while _tw(d, title, tf) > (x2 - 40 - tx) and tf.size > 32: tf = _font(tf.size - 4)
    d.text((tx, y1 + 78), title, font=tf, fill=title_color)

def _icells(d, img, box, cells, cols=2):
    x1, y1, x2, y2 = box
    gap = 16; cw = (x2 - x1 - gap * (cols - 1)) // cols
    rows = (len(cells) + cols - 1) // cols
    ch = (y2 - y1 - gap * (rows - 1)) // rows
    for i, c in enumerate(cells):
        r, col = divmod(i, cols)
        cx1 = x1 + col * (cw + gap); cy1 = y1 + r * (ch + gap)
        cx2 = cx1 + cw; cy2 = cy1 + ch
        d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=16, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        d.text((cx1 + 22, cy1 + 22), c["label"].upper(), font=_font(14), fill=MUTED)
        color = c.get("color", TEXT); vf = _font(32); val = c["value"]
        while _tw(d, val, vf) > (cw - 44) and vf.size > 18: vf = _font(vf.size - 2)
        d.text((cx1 + 22, cy2 - 22 - vf.size), val, font=vf, fill=color)

def _hint(d, x1, y1, x2, y2, color, icon_code, text, center=True):
    cy = (y1 + y2) // 2; tf = _font(16); tw = _tw(d, text, tf)
    total_w = 18 + 12 + tw
    start_x = (x1 + x2 - total_w) // 2 if center else x1
    _draw_icon(d, start_x + 9, cy, icon_code, 18, color)
    d.text((start_x + 30, cy), text, font=tf, fill=MUTED, anchor="lm")

def _draw_wheel(img, d, cx, cy, radius=150):
    d.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=(15, 15, 20, 255), outline=GOLD + (255,), width=8)
    inner_r = radius - 26
    d.ellipse((cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r), outline=(140, 115, 65, 180), width=3)
    _draw_icon(d, cx, cy, 0xf2f1, 120, GOLD)

def _draw_coin(img, d, cx, cy, radius=130, state="default"):
    if state == "win": bg, border, ic = (61, 209, 119), (30, 138, 76), (13, 58, 31)
    elif state == "lose": bg, border, ic = (232, 90, 90), (160, 48, 48), (58, 15, 15)
    else: bg, border, ic = (232, 181, 101), (176, 122, 48), (90, 58, 16)
    d.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), fill=bg + (255,), outline=border + (255,), width=10)
    inner_r = radius - 18
    d.ellipse((cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r), outline=border + (200,), width=3)
    _draw_icon(d, cx, cy, I_COINS, 100, ic)

def _draw_card(d, img, x, y, w, h, rank, suit_code, suit_color, is_back=False):
    if is_back:
        d.rounded_rectangle((x, y, x+w, y+h), radius=14, fill=(26, 35, 126, 255), outline=(40, 53, 147, 255), width=2)
        for i in range(0, h, 16):
            y2 = min(y+i+18, y+h-2)
            d.line((x+2, y+i, x+w-2, y2), fill=(40, 53, 147, 255), width=3)
        d.rounded_rectangle((x+14, y+14, x+w-14, y+h-14), radius=8, outline=(255, 255, 255, 80), width=2)
        _draw_icon(d, x+w//2, y+h//2, 0xf128, 46, (200, 200, 220))
        return
    d.rounded_rectangle((x, y, x+w, y+h), radius=14, fill=(240, 240, 245, 255), outline=(210, 210, 220, 255), width=2)
    rf = _font(48); rw = _tw(d, rank, rf)
    d.text((x + w//2 - rw//2, y + 26), rank, font=rf, fill=suit_color)
    _draw_icon(d, x + w//2, y + h - 56, suit_code, 44, suit_color)

def _draw_card_frame(img, d, box, label, label_icon, score, cards, score_bad=False):
    x1, y1, x2, y2 = box
    d.rounded_rectangle((x1, y1, x2, y2), radius=18, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    hx = x1 + 28; hy = y1 + 30
    _draw_icon(d, hx + 10, hy + 10, label_icon, 20, MUTED)
    d.text((hx + 32, hy), label.upper(), font=_font(17), fill=MUTED)
    sc_color = RED if score_bad else SILVER_HI
    d.text((hx, hy + 40), str(score), font=_font(52), fill=sc_color)
    cw, ch, gap = 130, 184, 18
    cx_start = x1 + 28 + 210 + 32; cy = y1 + (y2 - y1 - ch) // 2
    for i, c in enumerate(cards):
        cx = cx_start + i * (cw + gap)
        if cx + cw > x2 - 28: break
        if c.get("back"): _draw_card(d, img, cx, cy, cw, ch, "", 0, (0, 0, 0), is_back=True)
        else: _draw_card(d, img, cx, cy, cw, ch, c["rank"], c["suit"], c["color"])

def render_roulette_spin(user_id, balance, bet):
    img, d = _canvas_casino("Прокрутка", GOLD)
    b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": GOLD},
        {"label": "Прокрутка", "value": "≈ 2 сек", "icon": I_CLOCK, "color": SILVER},
    ])
    right_box = (512, b1, 1750, b2); _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, "Прокрутка барабана", "ждём результат"); iy1 += 76
    hint_h = 30; _hint(d, ix1, iy2 - hint_h, ix2, iy2, GOLD, I_INFO, "Не закрывай сообщение — результат появится здесь же")
    stage_y1 = iy1; stage_y2 = iy2 - hint_h - 20
    cx = (ix1 + ix2) // 2; cy = (stage_y1 + stage_y2) // 2 - 20
    _draw_wheel(img, d, cx, cy, 150)
    d.text((cx, cy + 150 + 40), "Подбираем слот", font=_font(32), fill=GOLD, anchor="mm")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_roulette_win(user_id, balance, bet, result_name, mult, net, payout):
    img, d = _canvas_casino("Выигрыш", GREEN)
    b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "icon": I_TROPHY, "color": GREEN},
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER},
    ])
    right_box = (512, b1, 1750, b2); _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, "Рулетка монет", f"x{1+mult:.1f} · {result_name}"); iy1 += 76
    hint_h = 30; _hint(d, ix1, iy2 - hint_h, ix2, iy2, GREEN, I_CHECK, "Удача на твоей стороне — попробуешь ещё?")
    content_y1 = iy1; content_y2 = iy2 - hint_h - 20
    total_h = content_y2 - content_y1; gap = 16
    hero_h = int(total_h * 0.48); cells_h = total_h - hero_h - gap
    _hero(img, d, (ix1, content_y1, ix2, content_y1 + hero_h), GREEN, I_TROPHY, "выпало", f"{result_name} · x{1+mult:.1f}")
    cells_y1 = content_y1 + hero_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "color": SILVER_HI},
        {"label": "Возврат", "value": f"+{payout:,} DC".replace(",", " "), "color": GREEN},
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "color": GREEN},
        {"label": "Страховка", "value": "нет", "color": DIM},
    ], cols=4)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_roulette_lose(user_id, balance, bet, refund, result_name):
    lost = bet - refund
    img, d = _canvas_casino("Проигрыш", RED)
    b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "icon": 0xf063, "color": RED},
        {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "icon": I_SHIELD, "color": (GREEN if refund else DIM)},
    ])
    right_box = (512, b1, 1750, b2); _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, "Рулетка монет", "проигрыш"); iy1 += 76
    hint_h = 30; _hint(d, ix1, iy2 - hint_h, ix2, iy2, RED, I_XMARK, "Не расстраивайся — повезёт в следующий раз")
    content_y1 = iy1; content_y2 = iy2 - hint_h - 20
    total_h = content_y2 - content_y1; gap = 16
    hero_h = int(total_h * 0.48); cells_h = total_h - hero_h - gap
    _hero(img, d, (ix1, content_y1, ix2, content_y1 + hero_h), RED, I_XMARK, "выпало", f"{result_name} · x0")
    cells_y1 = content_y1 + hero_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "color": SILVER_HI},
        {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "color": (GREEN if refund else DIM)},
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "color": RED},
        {"label": "Баланс", "value": f"{balance:,} DC".replace(",", " "), "color": SILVER_HI},
    ], cols=4)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_blackjack_table(user_id, balance, bet, dealer_cards, player_cards, player_score, dealer_first_card):
    img, d = _canvas_casino("Твой ход", GOLD)
    b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": GOLD},
        {"label": "Действие", "value": "взять / хватит", "icon": 0xf256, "color": BLUE},
    ])
    right_box = (512, b1, 1750, b2); _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, "Блэкджек", f"стол · {bet:,} DC".replace(",", " ")); iy1 += 76
    hint_h = 30; _hint(d, ix1, iy2 - hint_h, ix2, iy2, GOLD, 0xf0a4, "Взять карту или остановиться? Кнопки под сообщением")
    content_y1 = iy1; content_y2 = iy2 - hint_h - 20
    gap = 16; frame_h = (content_y2 - content_y1 - gap) // 2
    _draw_card_frame(img, d, (ix1, content_y1, ix2, content_y1 + frame_h), "Дилер", 0xf21b, "?", dealer_cards)
    py = content_y1 + frame_h + gap
    _draw_card_frame(img, d, (ix1, py, ix2, py + frame_h), "Ты", I_USER, player_score, player_cards)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_blackjack_result(user_id, balance, bet, total_bet, payout, net, dealer_cards, player_cards, dealer_score, player_score, outcome):
    STATUS = {
        "win":       ("Победа",   GREEN,  I_TROPHY,   "Победа · x2",            "блэкджек"),
        "blackjack": ("Блэкджек", GOLD,   I_TROPHY,   "Блэкджек · x2.5",        "блэкджек"),
        "push":      ("Ничья",    SILVER, 0xf2b5,     "Ничья · равные очки",    "возврат ставки"),
        "lose":      ("Проигрыш", RED,    I_XMARK,    "Проигрыш",               "блэкджек"),
        "bust":      ("Перебор",  RED,    I_BOLT,     f"Перебор · {player_score}", "блэкджек"),
    }
    status, color, hero_icon, hero_title, sub = STATUS.get(outcome, STATUS["lose"])
    img, d = _canvas_casino(status, color)
    b1, b2 = 158, 950
    if outcome in ("win", "blackjack"):
        blocks = [
            {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "icon": I_TROPHY, "color": GREEN},
            {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER},
        ]
    elif outcome == "push":
        blocks = [
            {"label": "Возврат", "value": f"+{payout:,} DC".replace(",", " "), "icon": 0xf2ea, "color": GOLD},
            {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER},
        ]
    else:
        blocks = [
            {"label": "Потеряно", "value": f"−{total_bet:,} DC".replace(",", " "), "icon": 0xf063, "color": RED},
            {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER},
        ]
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, blocks)
    right_box = (512, b1, 1750, b2); _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, hero_title, sub); iy1 += 76
    content_y1 = iy1; content_y2 = iy2
    gap = 16; frame_h = (content_y2 - content_y1 - gap) // 2
    _draw_card_frame(img, d, (ix1, content_y1, ix2, content_y1 + frame_h), "Дилер", 0xf21b, dealer_score, dealer_cards, score_bad=(dealer_score > 21))
    py = content_y1 + frame_h + gap
    _draw_card_frame(img, d, (ix1, py, ix2, py + frame_h), "Ты", I_USER, player_score, player_cards, score_bad=(player_score > 21))
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_coinflip_choice(user_id, balance, bet):
    img, d = _canvas_casino("Выбор стороны", GOLD)
    b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": GOLD},
        {"label": "Выплата", "value": "x1.9", "icon": 0xf295, "color": GREEN},
    ])
    right_box = (512, b1, 1750, b2); _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, "Монетка", "орёл или решка"); iy1 += 76
    hint_h = 30; _hint(d, ix1, iy2 - hint_h, ix2, iy2, GOLD, I_CLOCK, "У тебя 60 секунд на выбор — кнопки под сообщением")
    choice_h = 80; choices_y1 = iy2 - hint_h - 20 - choice_h
    stage_y1 = iy1; stage_y2 = choices_y1 - 16
    cx = (ix1 + ix2) // 2; cy = (stage_y1 + stage_y2) // 2
    _draw_coin(img, d, cx, cy, 130, "default")
    ch_w, gap = 260, 22; total_w = ch_w * 2 + gap; ch_start = cx - total_w // 2
    for i, (label, icon) in enumerate([("Орёл", 0xf520), ("Решка", 0xf521)]):
        bx = ch_start + i * (ch_w + gap); by = choices_y1
        d.rounded_rectangle((bx, by, bx + ch_w, by + choice_h), radius=16, fill=STACK_HDR + (255,), outline=STACK_BRD + (255,), width=3)
        _draw_icon(d, bx + 48, by + choice_h // 2, icon, 30, GOLD)
        d.text((bx + 90, by + choice_h // 2), label, font=_font(28), fill=SILVER_HI, anchor="lm")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_coinflip_win(user_id, balance, bet, payout, net, result_side, user_choice):
    img, d = _canvas_casino("Победа", GREEN)
    b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "icon": I_TROPHY, "color": GREEN},
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER},
    ])
    right_box = (512, b1, 1750, b2); _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, f"{result_side} · x1.9", "победа"); iy1 += 76
    content_y1 = iy1; content_y2 = iy2
    total_h = content_y2 - content_y1; gap = 16
    coin_h = int(total_h * 0.52); cells_h = total_h - coin_h - gap
    cx = (ix1 + ix2) // 2; cy = content_y1 + coin_h // 2
    _draw_coin(img, d, cx, cy, 130, "win")
    cells_y1 = content_y1 + coin_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [
        {"label": "Твой выбор", "value": user_choice, "color": SILVER_HI},
        {"label": "Выпало", "value": result_side, "color": GREEN},
        {"label": "Выплата", "value": f"+{payout:,} DC".replace(",", " "), "color": GREEN},
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "color": GREEN},
    ], cols=2)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_coinflip_lose(user_id, balance, bet, refund, result_side, user_choice):
    lost = bet - refund
    img, d = _canvas_casino("Мимо", RED)
    b1, b2 = 158, 950
    _draw_left_panel_casino(img, d, (50, b1, 490, b2), balance, [
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "icon": 0xf063, "color": RED},
        {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "icon": I_SHIELD, "color": (GREEN if refund else DIM)},
    ])
    right_box = (512, b1, 1750, b2); _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box; ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26
    _rhead(d, ix1, iy1, ix2, f"{result_side} · мимо", "проигрыш"); iy1 += 76
    content_y1 = iy1; content_y2 = iy2
    total_h = content_y2 - content_y1; gap = 16
    coin_h = int(total_h * 0.52); cells_h = total_h - coin_h - gap
    cx = (ix1 + ix2) // 2; cy = content_y1 + coin_h // 2
    _draw_coin(img, d, cx, cy, 130, "lose")
    cells_y1 = content_y1 + coin_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [
        {"label": "Твой выбор", "value": user_choice, "color": SILVER_HI},
        {"label": "Выпало", "value": result_side, "color": RED},
        {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "color": (GREEN if refund else DIM)},
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "color": RED},
    ], cols=2)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


# ============================================================
# БЛОК 2: ACTIONS (казино и игры)
# ============================================================
ACTIONS_DIR = os.path.join(BASE_DIR, "actions")
DAILY_DEAL_FILE = os.path.join(DATA_DIR, "daily_deal.json")
ROULETTE_STATS_FILE = os.path.join(DATA_DIR, "roulette_stats.json")

DAILY_DEAL_REFRESH_HOURS = 5
DAILY_DEAL_DISCOUNT = 30
DAILY_DEALS_PER_CYCLE = 5

CASINO_MIN_BET = 20
CASINO_MAX_BET = 4000

P = "\u3164"

def load_daily_deal(): return load_json(DAILY_DEAL_FILE, {})
def save_daily_deal(d): save_json(DAILY_DEAL_FILE, d)

def generate_random_deal(discount):
    catalog = load_shop_catalog()
    items = []
    for cat_key, cat_data in catalog.items():
        if cat_key in ("boosts", "casino", "gifts"): continue
        for item_key, item_data in cat_data.get("items", {}).items():
            items.append((cat_key, item_key, item_data))
    if not items: return None
    cat_key, item_key, item_data = random.choice(items)
    orig = item_data["price"]
    new = max(int(orig * (100 - discount) / 100), 1)
    return {
        "cat_key": cat_key, "item_key": item_key, "item_data": item_data,
        "original_price": orig, "discount": discount, "new_price": new,
        "category_label": catalog[cat_key]["label"],
    }

def _current_deal_slot(): return int(time.time() // (DAILY_DEAL_REFRESH_HOURS * 3600))

def refresh_daily_deal(force=False):
    slot = _current_deal_slot()
    data = load_daily_deal()
    saved = data.get("item")
    if saved and saved.get("discount") != DAILY_DEAL_DISCOUNT: force = True
    if not force and data.get("slot") == slot: return saved
    counter = data.get("counter", 0)
    old = data.get("item")
    if counter >= DAILY_DEALS_PER_CYCLE:
        save_daily_deal({"slot": slot, "item": old, "counter": 0, "updated_at": int(time.time())})
        return old
    counter += 1
    deal = generate_random_deal(DAILY_DEAL_DISCOUNT)
    if not deal: return None
    save_daily_deal({"slot": slot, "item": deal, "counter": counter, "updated_at": int(time.time())})
    return deal

def load_roulette_stats():
    return load_json(ROULETTE_STATS_FILE, {"total_bets": 0, "total_won": 0, "total_lost": 0, "rolls": 0})

def save_roulette_stats(data): save_json(ROULETTE_STATS_FILE, data)

ROULETTE_ROLLS = [
    {"name": "Проигрыш",        "mult": -1.0, "chance": 55.0, "color": 0xed4245},
    {"name": "Малый выигрыш",   "mult":  0.2, "chance": 20.0, "color": 0x95a5a6},
    {"name": "Средний выигрыш", "mult":  0.5, "chance": 12.0, "color": 0x149bd0},
    {"name": "Двойной",         "mult":  1.0, "chance":  8.0, "color": 0x2ecc71},
    {"name": "Тройной",         "mult":  2.0, "chance":  3.0, "color": 0xf7c991},
    {"name": "JACKPOT",         "mult":  4.0, "chance":  1.5, "color": 0xffaa00},
    {"name": "MEGA JACKPOT",    "mult":  9.0, "chance":  0.5, "color": 0xff00aa},
]

def roll_roulette():
    total = sum(r["chance"] for r in ROULETTE_ROLLS)
    r = random.uniform(0, total)
    cur = 0
    for roll in ROULETTE_ROLLS:
        cur += roll["chance"]
        if r <= cur: return roll
    return ROULETTE_ROLLS[0]

async def _edit_msg(inter, **kwargs):
    try:
        if inter.response.is_done(): await inter.edit_original_response(**kwargs)
        else: await inter.response.edit_message(**kwargs)
    except disnake.InteractionResponded:
        try: await inter.edit_original_response(**kwargs)
        except Exception as e: logger.warning(f"_edit_msg fallback: {e}")
    except disnake.NotFound: logger.warning("_edit_msg: interaction expired")

async def _send_game_screen(inter, buf, fname, view=None):
    file = disnake.File(buf, filename=fname)
    e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{fname}")
    await _edit_msg(inter, content=None, embed=e, file=file, attachments=[], view=view)

def _suit_code(suit: str) -> int:
    return {"♠️": 0xf2f4, "♥️": 0xf004, "♦️": 0xf219, "♣️": 0xf327}.get(suit, 0xf2f4)

def _suit_color(suit: str): return (211, 47, 47) if suit in ("♥️", "♦️") else (26, 26, 30)

def _cards_for_render(cards):
    return [{"rank": c[0], "suit": _suit_code(c[1]), "color": _suit_color(c[1])} for c in cards]

async def _check_casino_achievements(user_id, bet=0, profit=0):
    try:
        from core.bot import bot
        stats = load_roulette_stats()
        await check_and_unlock(user_id, "casino_games", value=stats.get("rolls", 0), bot=bot)
        if bet >= 1000: await check_and_unlock(user_id, "casino_bet", value=bet, bot=bot)
        if profit >= 10000: await check_and_unlock(user_id, "casino_lucky", value=profit, bot=bot)
    except Exception as e: logger.warning(f"casino ach: {e}")

async def _check_pet_xp(user_id: int, source: str = "casino"):
    try:
        from pet.core import add_pet_xp
        await add_pet_xp(user_id, 3, source)
    except Exception as e: logger.debug(f"pet xp casino: {e}")

async def _roulette_play(inter, bet, reason="Ставка в рулетке монет"):
    user_id = inter.author.id
    if bet < CASINO_MIN_BET: return await inter.response.send_message(f"❌ Минимум — **{CASINO_MIN_BET} DC**.", ephemeral=True)
    if bet > CASINO_MAX_BET: return await inter.response.send_message(f"❌ Максимум — **{CASINO_MAX_BET} DC**.", ephemeral=True)
    balance = await get_user_balance(user_id)
    if bet > balance: return await inter.response.send_message(f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`\n> **Ставка:** `{bet} DC`", ephemeral=True)
    if not inter.response.is_done(): await inter.response.defer(ephemeral=True)
    if not await remove_dc(user_id, bet, reason): return await inter.edit_original_response(content="❌ Не удалось списать DC.")
    try: await _send_game_screen(inter, render_roulette_spin(user_id, balance, bet), f"roulette_spin_{user_id}.png")
    except Exception as e:
        logger.exception(f"roulette spin: {e}"); await inter.edit_original_response(content="🎰 Крутим барабан...")
    await asyncio.sleep(2.2)
    result = roll_roulette(); mult = result["mult"]
    if on_casino_quest_hook:
        try: await on_casino_quest_hook(user_id)
        except Exception: pass
    await _check_casino_achievements(user_id, bet=bet)
    await _check_pet_xp(user_id, "roulette")
    if mult > 0:
        payout = bet + int(bet * mult)
        payout, pet_mult = apply_pet_casino_bonus_internal(user_id, payout)
        payout, used = apply_casino_win(user_id, payout)
        net = payout - bet
        r_reason = f"Выигрыш в рулетке: {result['name']}"
        if pet_mult > 1.0: r_reason += f" (питомец ×{pet_mult:.2f})"
        if used: r_reason += f" ({', '.join(used)})"
        await add_dc(user_id, payout, r_reason, to_clan_pool=True)
        if on_casino_win_hook:
            try: await on_casino_win_hook(user_id, payout, bet)
            except Exception as e: logger.warning(f"casino_win_hook roulette: {e}")
        new_balance = await get_user_balance(user_id)
        try: await _send_game_screen(inter, render_roulette_win(user_id, new_balance, bet, result["name"], mult, net, payout), f"roulette_win_{user_id}.png", view=RouletteRetryView(bet))
        except Exception as e: logger.exception(f"render_roulette_win: {e}")
        if net >= 10000: await _check_casino_achievements(user_id, profit=net)
        st = load_roulette_stats(); st["total_bets"] += bet; st["total_won"] += net; st["rolls"] += 1; save_roulette_stats(st)
        asyncio.create_task(log_discord(title=f"🎰 Рулетка: {result['name']}", description=(f"> **Юзер:** {inter.author.mention}\n> **Ставка:** `{bet} DC`\n> **Множитель:** `x{1 + mult:.1f}`\n" + (f"> **Бонус питомца:** `×{pet_mult:.2f}`\n" if pet_mult > 1.0 else "") + f"> **Профит:** `+{net} DC`\n> **Баланс:** `{new_balance} DC`"), color=result["color"]))
    else:
        refund = try_insurance(user_id, bet)
        if refund > 0: await add_dc(user_id, refund, "Страховка ставки (рулетка)")
        new_balance = await get_user_balance(user_id)
        try: await _send_game_screen(inter, render_roulette_lose(user_id, new_balance, bet, refund, result["name"]), f"roulette_lose_{user_id}.png", view=RouletteRetryView(bet))
        except Exception as e: logger.exception(f"render_roulette_lose: {e}")
        st = load_roulette_stats(); st["total_bets"] += bet; st["total_lost"] += (bet - refund); st["rolls"] += 1; save_roulette_stats(st)
        asyncio.create_task(log_discord(title="🎰 Рулетка: проигрыш", description=(f"> **Юзер:** {inter.author.mention}\n> **Ставка:** `{bet} DC`\n> **Страховка:** `+{refund} DC`\n> **Баланс:** `{new_balance} DC`"), color=0xed4245))

class RouletteModal(Modal):
    def __init__(self):
        super().__init__(title="🎰 Рулетка монет", components=[TextInput(label=f"Ставка ({CASINO_MIN_BET}-{CASINO_MAX_BET} DC)", placeholder=f"От {CASINO_MIN_BET} до {CASINO_MAX_BET}", custom_id="bet", min_length=1, max_length=10)])
    async def callback(self, inter):
        s = inter.text_values["bet"].strip()
        if not s.isdigit(): return await inter.response.send_message("❌ Целое число.", ephemeral=True)
        await _roulette_play(inter, int(s), reason="Ставка в рулетке монет")

class RouletteRetryView(View):
    def __init__(self, last_bet):
        super().__init__(timeout=300); self.last_bet = last_bet
        for label, cid, emoji_data, style, cb in [
            ("Играть ещё", "roulette_retry", ("image", 1555994370933653544), ButtonStyle.gray, self.replay),
            ("Повтор ставки", "roulette_repeat", ("povtor", 1555993533629071360), ButtonStyle.gray, self.repeat),
            ("Двойная ставка", "roulette_double", ("flas", 1551289202279325756), ButtonStyle.danger, self.double),
        ]:
            b = Button(label=label, style=style, custom_id=cid, emoji=PartialEmoji(name=emoji_data[0], id=emoji_data[1]), row=0)
            b.callback = cb; self.add_item(b)
    async def replay(self, inter): await inter.response.send_modal(RouletteModal())
    async def repeat(self, inter): await _roulette_play(inter, self.last_bet, reason="Повтор ставки в рулетке")
    async def double(self, inter):
        nb = self.last_bet * 2
        if nb > CASINO_MAX_BET: return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET} DC.", ephemeral=True)
        await _roulette_play(inter, nb, reason="Двойная ставка в рулетке")

BLACKJACK_MIN_BET = CASINO_MIN_BET
BLACKJACK_MAX_BET = CASINO_MAX_BET
BLACKJACK_BLACKJACK_MULT = 2.5
BLACKJACK_WIN_MULT = 2.0
BLACKJACK_DEALER_STAND = 17
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠️", "♥️", "♦️", "♣️"]

def _new_deck():
    d = [(r, s) for r in RANKS for s in SUITS]; random.shuffle(d); return d

def _hand_value(hand):
    total = 0; aces = 0
    for r, s in hand:
        if r == "A": aces += 1; total += 11
        elif r in ("J", "Q", "K"): total += 10
        else: total += int(r)
    while total > 21 and aces > 0: total -= 10; aces -= 1
    return total

def _dealer_play(game):
    while _hand_value(game["dealer"]) < BLACKJACK_DEALER_STAND: game["dealer"].append(game["deck"].pop())

async def _bj_finalize(inter, game, outcome):
    user_id = game["user_id"]; bet = game["bet"]; total_bet = bet * 2 if game.get("doubled") else bet
    if outcome == "blackjack": payout = int(total_bet * BLACKJACK_BLACKJACK_MULT); reason = "Блэкджек (x2.5)"
    elif outcome == "win": payout = int(total_bet * BLACKJACK_WIN_MULT); reason = "Победа в блэкджеке (x2)"
    elif outcome == "push": payout = total_bet; reason = "Ничья в блэкджеке (возврат)"
    else: payout = 0; reason = "Проигрыш в блэкджеке"
    pet_mult = 1.0
    if payout > 0:
        payout, pet_mult = apply_pet_casino_bonus_internal(user_id, payout)
        payout, used = apply_casino_win(user_id, payout)
        if pet_mult > 1.0: reason += f" (питомец ×{pet_mult:.2f})"
        if used: reason += f" ({', '.join(used)})"
        await add_dc(user_id, payout, reason, to_clan_pool=True)
        if on_casino_win_hook:
            try: await on_casino_win_hook(user_id, payout, total_bet)
            except Exception as e: logger.warning(f"casino_win_hook bj: {e}")
        if outcome == "blackjack":
            try:
                from core.bot import bot
                await check_and_unlock(user_id, "casino_bj21", bot=bot)
            except Exception as e: logger.warning(f"bj21 ach: {e}")
        net = payout - total_bet
        if net >= 10000: await _check_casino_achievements(user_id, profit=net)
    else:
        refund = try_insurance(user_id, total_bet)
        if refund > 0: await add_dc(user_id, refund, "Страховка ставки (блэкджек)"); payout = refund
    new_balance = await get_user_balance(user_id); net = payout - total_bet
    asyncio.create_task(log_discord(
        title=f"🃏 Блэкджек: {outcome}",
        description=(f"> **Юзер:** <@{user_id}>\n> **Ставка:** `{total_bet} DC`\n" + (f"> **Бонус питомца:** `×{pet_mult:.2f}`\n" if pet_mult > 1.0 else "") + f"> **Выплата:** `{payout} DC`\n> **Профит:** `{'+' if net >= 0 else ''}{net} DC`\n> **Баланс:** `{new_balance} DC`"),
        color=0x2ecc71 if payout > 0 else 0xed4245))
    dealer_cards = _cards_for_render(game["dealer"]); player_cards = _cards_for_render(game["player"])
    try:
        buf = render_blackjack_result(user_id, new_balance, bet, total_bet, payout, net, dealer_cards, player_cards, _hand_value(game["dealer"]), _hand_value(game["player"]), outcome)
        file = disnake.File(buf, filename=f"bj_res_{user_id}.png")
        e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{file.filename}")
        await _edit_msg(inter, content=None, embed=e, file=file, attachments=[], view=BlackjackRetryView(bet))
    except Exception as e: logger.exception(f"render_blackjack_result: {e}")

async def _blackjack_play(inter, bet, reason="Ставка в блэкджеке"):
    user_id = inter.author.id
    if bet < BLACKJACK_MIN_BET: return await inter.response.send_message(f"❌ Минимум — **{BLACKJACK_MIN_BET} DC**.", ephemeral=True)
    if bet > BLACKJACK_MAX_BET: return await inter.response.send_message(f"❌ Максимум — **{BLACKJACK_MAX_BET} DC**.", ephemeral=True)
    balance = await get_user_balance(user_id)
    if bet > balance: return await inter.response.send_message(f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`", ephemeral=True)
    if not inter.response.is_done(): await inter.response.defer(ephemeral=True)
    if not await remove_dc(user_id, bet, reason): return await inter.edit_original_response(content="❌ Не удалось списать DC.")
    deck = _new_deck()
    game = {"user_id": user_id, "bet": bet, "deck": deck, "player": [deck.pop(), deck.pop()], "dealer": [deck.pop(), deck.pop()], "doubled": False, "finished": False}
    if on_casino_quest_hook:
        try: await on_casino_quest_hook(user_id)
        except Exception: pass
    await _check_casino_achievements(user_id, bet=bet)
    await _check_pet_xp(user_id, "blackjack")
    dealer_first = game["dealer"][0]
    dealer_cards = [{"rank": dealer_first[0], "suit": _suit_code(dealer_first[1]), "color": _suit_color(dealer_first[1])}, {"back": True}]
    player_cards = _cards_for_render(game["player"])
    try:
        buf = render_blackjack_table(user_id, balance - bet, bet, dealer_cards, player_cards, _hand_value(game["player"]), dealer_first)
        await _send_game_screen(inter, buf, f"bj_{user_id}.png", view=BlackjackView(game))
    except Exception as e:
        logger.exception(f"render_blackjack_table: {e}"); await inter.edit_original_response(content="🃏 Раздача карт...")
    if _hand_value(game["player"]) == 21:
        _dealer_play(game); game["finished"] = True
        dealer_val = _hand_value(game["dealer"])
        outcome = "push" if (dealer_val == 21 and len(game["dealer"]) == 2) else "blackjack"
        await _bj_finalize(inter, game, outcome)

class BlackjackBetModal(Modal):
    def __init__(self):
        super().__init__(title="Блэкджек — ставка", components=[TextInput(label=f"Ставка ({BLACKJACK_MIN_BET}-{BLACKJACK_MAX_BET} DC)", placeholder=f"От {BLACKJACK_MIN_BET} до {BLACKJACK_MAX_BET}", custom_id="bet", min_length=1, max_length=10)])
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
        dealer_first = self.game["dealer"][0]
        dealer_cards = [{"rank": dealer_first[0], "suit": _suit_code(dealer_first[1]), "color": _suit_color(dealer_first[1])}, {"back": True}]
        player_cards = _cards_for_render(self.game["player"])
        try:
            buf = render_blackjack_table(self.game["user_id"], 0, self.game["bet"], dealer_cards, player_cards, _hand_value(self.game["player"]), dealer_first)
            file = disnake.File(buf, filename=f"bj_{self.game['user_id']}.png")
            e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{file.filename}")
            await _edit_msg(inter, content=None, embed=e, file=file, attachments=[], view=self)
        except Exception as e: logger.exception(f"bj redraw: {e}")
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
        _dealer_play(self.game); self.game["finished"] = True
        pv = _hand_value(self.game["player"]); dv = _hand_value(self.game["dealer"])
        if dv > 21 or pv > dv: outcome = "win"
        elif pv == dv: outcome = "push"
        else: outcome = "lose"
        await _bj_finalize(inter, self.game, outcome)
    async def double(self, inter):
        if not await self._check(inter): return
        if self.game.get("doubled"): return await inter.response.send_message("⛔ Уже удвоено.", ephemeral=True)
        if len(self.game["player"]) != 2: return await inter.response.send_message("⛔ Только на первых двух.", ephemeral=True)
        uid = self.game["user_id"]; bet = self.game["bet"]
        if bet * 2 > CASINO_MAX_BET: return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET}.", ephemeral=True)
        if (await get_user_balance(uid)) < bet: return await inter.response.send_message(f"❌ Нужно ещё `{bet} DC`.", ephemeral=True)
        if not await remove_dc(uid, bet, "Удвоение в блэкджеке"): return await inter.response.send_message("❌ Ошибка списания.", ephemeral=True)
        self.game["doubled"] = True; self.game["player"].append(self.game["deck"].pop()); await self._stand_logic(inter)

class BlackjackRetryView(View):
    def __init__(self, last_bet):
        super().__init__(timeout=300); self.last_bet = last_bet
        for label, cid, emoji_data, style, cb in [
            ("Играть ещё", "bj_retry", ("image", 1555994370933653544), ButtonStyle.gray, self.replay),
            ("Повтор ставки", "bj_repeat", ("povtor", 1555993533629071360), ButtonStyle.gray, self.repeat),
            ("Двойная ставка", "bj_double_next", ("flas", 1551289202279325756), ButtonStyle.danger, self.double),
        ]:
            b = Button(label=label, style=style, custom_id=cid, emoji=PartialEmoji(name=emoji_data[0], id=emoji_data[1]), row=0); b.callback = cb; self.add_item(b)
    async def replay(self, inter): await inter.response.send_modal(BlackjackBetModal())
    async def repeat(self, inter): await _blackjack_play(inter, self.last_bet, reason="Повтор в блэкджеке")
    async def double(self, inter):
        nb = self.last_bet * 2
        if nb > CASINO_MAX_BET: return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET} DC.", ephemeral=True)
        await _blackjack_play(inter, nb, reason="Двойная в блэкджеке")

COINFLIP_MIN_BET = CASINO_MIN_BET
COINFLIP_MAX_BET = CASINO_MAX_BET
COINFLIP_WIN_MULT = 1.9

async def _coinflip_play(inter, bet, reason="Ставка в монетке"):
    user_id = inter.author.id
    if bet < COINFLIP_MIN_BET: return await inter.response.send_message(f"❌ Минимум — **{COINFLIP_MIN_BET} DC**.", ephemeral=True)
    if bet > COINFLIP_MAX_BET: return await inter.response.send_message(f"❌ Максимум — **{COINFLIP_MAX_BET} DC**.", ephemeral=True)
    balance = await get_user_balance(user_id)
    if bet > balance: return await inter.response.send_message(f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`", ephemeral=True)
    if not inter.response.is_done(): await inter.response.defer(ephemeral=True)
    if not await remove_dc(user_id, bet, reason): return await inter.edit_original_response(content="❌ Не удалось списать DC.")
    await _check_casino_achievements(user_id, bet=bet)
    await _check_pet_xp(user_id, "coinflip")
    try: await _send_game_screen(inter, render_coinflip_choice(user_id, balance, bet), f"coin_choice_{user_id}.png", view=CoinflipChoiceView(bet))
    except Exception as e: logger.exception(f"render_coinflip_choice: {e}")

class CoinflipBetModal(Modal):
    def __init__(self):
        super().__init__(title="Монетка — ставка", components=[TextInput(label=f"Ставка ({COINFLIP_MIN_BET}-{COINFLIP_MAX_BET} DC)", placeholder=f"От {COINFLIP_MIN_BET} до {COINFLIP_MAX_BET}", custom_id="bet", min_length=1, max_length=10)])
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
        result_side = random.choice(["heads", "tails"]); won = (result_side == user_choice)
        user_id = inter.author.id; bet = self.bet; payout = 0; refund = 0; pet_mult = 1.0
        if on_casino_quest_hook:
            try: await on_casino_quest_hook(user_id)
            except Exception: pass
        if won:
            payout = int(bet * COINFLIP_WIN_MULT)
            payout, pet_mult = apply_pet_casino_bonus_internal(user_id, payout)
            payout, used = apply_casino_win(user_id, payout)
            reason = f"Монетка ({result_side})"
            if pet_mult > 1.0: reason += f" (питомец ×{pet_mult:.2f})"
            if used: reason += f" ({', '.join(used)})"
            await add_dc(user_id, payout, reason, to_clan_pool=True)
            if on_casino_win_hook:
                try: await on_casino_win_hook(user_id, payout, bet)
                except Exception as e: logger.warning(f"casino_win_hook coin: {e}")
            net = payout - bet
            if net >= 10000: await _check_casino_achievements(user_id, profit=net)
        else:
            refund = try_insurance(user_id, bet)
            if refund > 0: await add_dc(user_id, refund, "Страховка (монетка)")
            net = -bet + refund
        new_balance = await get_user_balance(user_id)
        side_ru = "Орёл" if result_side == "heads" else "Решка"; choice_ru = "Орёл" if user_choice == "heads" else "Решка"
        try:
            if won: buf = render_coinflip_win(user_id, new_balance, bet, payout, payout - bet, side_ru, choice_ru)
            else: buf = render_coinflip_lose(user_id, new_balance, bet, refund, side_ru, choice_ru)
            file = disnake.File(buf, filename=f"coin_res_{user_id}.png")
            e = disnake.Embed(color=6776679); e.set_image(url=f"attachment://{file.filename}")
            await _edit_msg(inter, content=None, embed=e, file=file, attachments=[], view=CoinflipRetryView(bet))
        except Exception as e: logger.exception(f"coin result: {e}")
        asyncio.create_task(log_discord(
            title=f"🪙 Монетка: {'победа' if won else 'проигрыш'}",
            description=(f"> **Юзер:** <@{user_id}>\n> **Ставка:** `{bet} DC`\n> **Выбор:** `{user_choice}` → `{result_side}`\n" + (f"> **Бонус питомца:** `×{pet_mult:.2f}`\n" if pet_mult > 1.0 else "") + f"> **Выплата:** `{payout} DC`\n> **Страховка:** `{refund} DC`\n> **Баланс:** `{new_balance} DC`"),
            color=0x2ecc71 if won else 0xed4245))
    async def heads(self, inter): await self._play(inter, "heads")
    async def tails(self, inter): await self._play(inter, "tails")

class CoinflipRetryView(View):
    def __init__(self, last_bet):
        super().__init__(timeout=300); self.last_bet = last_bet
        for label, cid, emoji_data, style, cb in [
            ("Играть ещё", "coin_retry", ("image", 1555994370933653544), ButtonStyle.gray, self.replay),
            ("Повтор ставки", "coin_repeat", ("povtor", 1555993533629071360), ButtonStyle.gray, self.repeat),
            ("Двойная ставка", "coin_double", ("flas", 1551289202279325756), ButtonStyle.danger, self.double),
        ]:
            b = Button(label=label, style=style, custom_id=cid, emoji=PartialEmoji(name=emoji_data[0], id=emoji_data[1]), row=0); b.callback = cb; self.add_item(b)
    async def replay(self, inter): await inter.response.send_modal(CoinflipBetModal())
    async def repeat(self, inter): await _coinflip_play(inter, self.last_bet, reason="Повтор в монетке")
    async def double(self, inter):
        nb = self.last_bet * 2
        if nb > CASINO_MAX_BET: return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET} DC.", ephemeral=True)
        await _coinflip_play(inter, nb, reason="Двойная в монетке")


# ============================================================
# БЛОК 3: OTHERS (модули бустов, акций, подарков)
# ============================================================
def format_remaining(seconds: int) -> str:
    if seconds <= 0: return "истёк"
    h = seconds // 3600; m = (seconds % 3600) // 60; s = seconds % 60
    if h > 0: return f"{h}ч {m}м"
    if m > 0: return f"{m}м"
    return f"{s}с"

def get_multiplier(user_id: int, kind: str) -> float:
    m_all = 1.0; m_spec = 1.0
    item_all = get_item(user_id, "boost_all_x2")
    if item_all: m_all = float(item_all["value"] or 1.0)
    key_map = {"messages": "boost_messages_x2", "voice": "boost_voice_x2", "review": "boost_review_x2"}
    key = key_map.get(kind)
    if key:
        item_spec = get_item(user_id, key)
        if item_spec: m_spec = float(item_spec["value"] or 1.0)
    return max(m_all, m_spec)

def apply_boost(user_id: int, kind: str, base: int) -> int:
    mult = get_multiplier(user_id, kind)
    return int(base * mult)

def get_review_cooldown(user_id: int) -> int:
    item = get_item(user_id, "boost_cooldown_half")
    if item and item["value"]:
        try: return int(item["value"])
        except Exception: pass
    return 120

def can_activate(user_id: int, item_key: str) -> tuple[bool, str]:
    existing = get_item(user_id, item_key)
    if existing:
        if existing["expires_at"] > 0:
            left = existing["expires_at"] - int(time.time())
            if left > 0: return False, f"⏱ У вас уже активен **{existing['item_key']}**. Осталось: **{format_remaining(left)}**"
        elif existing["uses_left"] > 0: return False, f"⏱ У вас уже есть **{existing['item_key']}** ({existing['uses_left']} исп.)"
    return True, ""

async def do_activate(user_id: int, item_key: str, item: dict) -> str:
    if item_key == "boost_daily_reset":
        data = get_dc_cache(user_id)
        data["messages_today"] = 0; data["voice_time_today"] = 0; data["last_voice_dc"] = 0
        save_dc_cache(user_id, data); sync_dc_to_json()
        return "✅ Лимит сообщений и войса **обнулён на сегодня**!"
    duration = int(item.get("duration_hours", 0) or 0); uses = int(item.get("uses", -1))
    activate_item(
        user_id=user_id, item_key=item_key, item_type=item.get("_category", "boosts"),
        value=float(item.get("value", 0) or 0), duration_hours=duration, uses=uses,
    )
    if duration > 0: return f"✅ Активирован на **{duration}ч** — применяется сразу."
    if uses > 0: return f"✅ Активирован (**{uses}** исп.) — применяется сразу."
    return "✅ Активирован — применяется сразу."

def apply_casino_win(user_id: int, base_payout: int) -> tuple[int, list]:
    used = []; payout = base_payout
    lh = get_item(user_id, "casino_lucky_hour")
    if lh and lh["value"]: payout = int(payout * float(lh["value"])); used.append("удачный час")
    nm = get_item(user_id, "casino_boost_x2")
    if nm and nm["value"]: payout = int(payout * float(nm["value"])); consume_use(user_id, "casino_boost_x2"); used.append("x2 к выигрышу")
    return payout, used

def try_insurance(user_id: int, bet: int) -> int:
    ins = get_item(user_id, "casino_insurance")
    if not ins: return 0
    refund = int(bet * float(ins["value"] or 0.5))
    consume_use(user_id, "casino_insurance")
    return refund

def apply_pet_casino_bonus_internal(user_id: int, payout: int) -> tuple[int, float]:
    try:
        from pet.core import get_casino_bonus
        mult = get_casino_bonus(user_id)
        if mult > 1.0: return int(payout * mult), mult
    except Exception as e: logger.debug(f"pet casino bonus: {e}")
    return payout, 1.0

ANNOUNCE_CHANNEL_ID = 1462136361711829053
PING_ROLE_ID = 1127428607606796290
STATE_FILE = os.path.join(DATA_DIR, "deal_announce.json")
ANNOUNCE_LIFETIME = 3600

def _load_state() -> dict: return load_json(STATE_FILE, {"slot": 0, "message_id": 0, "sent_at": 0, "channel_id": 0})
def _save_state(state: dict): save_json(STATE_FILE, state)

async def _delete_announce(bot, state: dict):
    mid = state.get("message_id"); cid = state.get("channel_id") or ANNOUNCE_CHANNEL_ID
    if not mid: return
    try:
        ch = bot.get_channel(cid)
        if not ch: ch = await bot.fetch_channel(cid)
        msg = await ch.fetch_message(mid); await msg.delete()
        logger.info(f"Deal announce deleted: msg={mid}")
    except disnake.NotFound: pass
    except Exception as e: logger.warning(f"deal_announce delete: {e}")
    state["message_id"] = 0; state["sent_at"] = 0; _save_state(state)

def _build_deal_text(deal: dict) -> str:
    item_data = deal.get("item_data", {}); name = item_data.get("name", "—")
    orig = deal.get("original_price", 0); new = deal.get("new_price", 0); discount = deal.get("discount", 0)
    return (
        f"<@&{PING_ROLE_ID}> — **новая акция за DC!**\n\n"
        f"Скидка **{discount}%** на **«{name}»** — сейчас "
        f"**{new} DC** вместо ~~{orig} DC~~.\n\n"
        f"**Как забрать:**\n"
        f"> **Каталог** → **Diamond Coins** → **Акция дня**\n"
        f"Успей — товар дня меняется каждые несколько часов."
    )

async def announce_deal(bot, deal: dict, slot: int):
    ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if not ch:
        try: ch = await bot.fetch_channel(ANNOUNCE_CHANNEL_ID)
        except Exception as e: logger.warning(f"deal_announce channel fetch: {e}"); return
    text = _build_deal_text(deal)
    try: msg = await ch.send(text)
    except Exception as e: logger.warning(f"deal_announce send: {e}"); return
    state = {"slot": slot, "message_id": msg.id, "sent_at": int(time.time()), "channel_id": ch.id}
    _save_state(state); logger.info(f"Deal announce sent: slot={slot} msg={msg.id}")

async def process_deal_announce(bot):
    try:
        deal_data = load_json(DAILY_DEAL_FILE, {}); cur_slot = deal_data.get("slot", 0)
        cur_deal = deal_data.get("item"); updated_at = deal_data.get("updated_at", 0)
        state = _load_state(); now = time.time()
        if state.get("message_id") and state.get("sent_at"):
            if now - state["sent_at"] > ANNOUNCE_LIFETIME: await _delete_announce(bot, state)
        if cur_deal and cur_slot and cur_slot != state.get("slot"):
            if (now - updated_at) < ANNOUNCE_LIFETIME:
                if state.get("message_id"): await _delete_announce(bot, state)
                await announce_deal(bot, cur_deal, cur_slot)
            else:
                state["slot"] = cur_slot; _save_state(state)
    except Exception as e: logger.exception(f"process_deal_announce: {e}")

GIFT_FEE_PERCENT = 5

async def process_gift_dc(sender: disnake.Member, recipient_id: int, amount: int, price_paid: int) -> tuple[bool, str]:
    guild = sender.guild; recipient = guild.get_member(recipient_id)
    if not recipient: await add_dc(sender.id, price_paid, "Возврат — получатель не найден"); return False, "Получатель не найден на сервере"
    if recipient.bot: await add_dc(sender.id, price_paid, "Возврат — получатель бот"); return False, "Нельзя дарить ботам"
    if recipient.id == sender.id: await add_dc(sender.id, price_paid, "Возврат — сам себе"); return False, "Нельзя подарить самому себе"
    try: await add_dc(recipient.id, amount, f"Подарок от {sender.display_name}")
    except Exception as e:
        logger.exception(f"gift: add_dc error: {e}"); await add_dc(sender.id, price_paid, "Возврат — ошибка начисления"); return False, f"Ошибка начисления: {e}"
    if on_gift_quest_hook:
        try: await on_gift_quest_hook(sender.id, amount)
        except Exception as e: logger.warning(f"clan gift hook: {e}")
    try:
        from core.bot import bot
        data = get_dc_cache(sender.id); total_gifted = 0
        for h in data.get("history", []):
            if h.get("reason", "").startswith("Подарок от") and h.get("amount", 0) > 0: total_gifted += h.get("amount", 0)
        total_gifted += amount
        await check_and_unlock(sender.id, "gift_total", value=total_gifted, bot=bot)
    except Exception as e: logger.warning(f"gift ach: {e}")
    try:
        dm_embed = disnake.Embed(
            title="🎁 Вам подарили Diamond Coins!",
            description=(f"> **Отправитель:** {sender.display_name}\n> **Получено:** `+{amount} DC`\n\n> Спасибо за то, что вы с нами! Оставить отзыв можно в <#1462074763437543435>."),
            color=0x2ecc71, timestamp=datetime.now(timezone.utc)
        )
        dm_embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&")
        await recipient.send(embed=dm_embed)
    except Exception as e: logger.warning(f"gift: не удалось отправить ЛС получателю {recipient.id}: {e}")
    await log_discord(
        title="🎁 Подарок DC",
        description=(f"> **Отправитель:** {sender.mention}\n> **Получатель:** {recipient.mention}\n> **Сумма:** `{amount} DC`\n> **Комиссия:** `{price_paid - amount} DC`"),
        color=0x00ff00, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )
    return True, f"Подарок отправлен! Получатель: {recipient.mention}"

NEW_URL = (
    "https://cdn.discordapp.com/attachments/1527006158282555412/"
    "1537851307757539390/image.png"
    "?ex=6aba8d23&is=6ab93ba3&"
    "hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"
)
STRIPE_URL_RE = re.compile(
    r"https://cdn\.discordapp\.com/attachments/1527006158282555412/"
    r"1537851307757539390/image\.png\?[^\s\"'\)\]]+"
)
BASE_DIR_FIX = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "node_modules", ".backup_stripe", ".idea", ".vscode"}
VALID_EXTS = {".py", ".json", ".txt", ".md"}

def should_skip(path) -> bool:
    for part in path.parts:
        if part in EXCLUDE_DIRS: return True
    return path.suffix.lower() not in VALID_EXTS

def fix_content(content: str) -> tuple[str, int]:
    matches = STRIPE_URL_RE.findall(content); count = len(matches)
    if count == 0: return content, 0
    new_content = STRIPE_URL_RE.sub(NEW_URL, content)
    return new_content, count

def run_fix(verbose: bool = True) -> dict:
    stats = {"scanned": 0, "changed": 0, "total_replacements": 0, "files": []}
    for root, dirs, files in os.walk(BASE_DIR_FIX):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in files:
            path = Path(root) / fname
            if should_skip(path): continue
            stats["scanned"] += 1
            try:
                with open(path, "r", encoding="utf-8") as f: content = f.read()
            except (UnicodeDecodeError, PermissionError, IsADirectoryError): continue
            new_content, count = fix_content(content)
            if count == 0: continue
            try:
                with open(path, "w", encoding="utf-8") as f: f.write(new_content)
                stats["changed"] += 1; stats["total_replacements"] += count
                rel = str(path.relative_to(BASE_DIR_FIX))
                stats["files"].append((rel, count))
                if verbose: print(f"  ✅ {rel} — {count} замен")
            except Exception as e:
                if verbose: print(f"  ❌ {path}: {e}")
    return stats


# ============================================================
# БЛОК 4: GIVEAWAYS (розыгрыши)
# ============================================================
LOG_CHANNEL_ID = 1530453871581855744
GIVEAWAY_CHANNEL_ID = 1462390938851741923
STAFF_PANEL_CHANNEL_ID = 1551276116679860314
REPORT_DM_USER_ID = 796293832751972352
REVIEW_CHANNEL_ID = 1462074763437543435
GIVEAWAY_FULL_ROLES = [1530823425764098058, 1530822331188903966, 1127428607606796294, 1471844291595731016]
MSK = timezone(timedelta(hours=3))

GIVEAWAY_TEMPLATES = {
    "100":  {"prize": "100 DC",  "amount": 100,  "winners": 1, "description": "🎉 Быстрый розыгрыш 100 Diamond Coins! Небольшой приз — хороший шанс испытать удачу. Жми участвовать!"},
    "150":  {"prize": "150 DC",  "amount": 150,  "winners": 1, "description": "🎉 Стандартный розыгрыш 150 DC для всех! Отличный стартовый приз на любые нужды магазина. Заходи и участвуй!"},
    "350":  {"prize": "350 DC",  "amount": 350,  "winners": 1, "description": "🎉 Розыгрыш 350 DC — средний куш для настоящих ценителей! Хорошая сумма для любых покупок. Не упусти свой шанс!"},
    "400":  {"prize": "400 DC",  "amount": 400,  "winners": 2, "description": "🎉 Розыгрыш 400 DC на двоих победителей! Двойной шанс сорвать куш. Участвуй — удача может улыбнуться именно тебе!"},
    "450":  {"prize": "450 DC",  "amount": 450,  "winners": 2, "description": "🎉 Розыгрыш 450 DC на двоих победителей! Щедрый приз для любителей адреналина. Жми участвовать и не упусти свой шанс!"},
    "600":  {"prize": "600 DC",  "amount": 600,  "winners": 3, "description": "🎉 Розыгрыш 600 DC на троих победителей! Тройной шанс на хороший куш. Собирайся с мыслями — и вперёд!"},
    "700":  {"prize": "700 DC",  "amount": 700,  "winners": 3, "description": "🎉 Розыгрыш 700 DC на троих победителей! Большие призы для активных ребят. Удача любит смелых!"},
    "1000": {"prize": "1000 DC", "amount": 1000, "winners": 5, "description": "👑 Большой розыгрыш 1000 DC на пятерых победителей! Крупный куш для настоящих везунчиков. Испытай судьбу — она может быть на твоей стороне!"},
    "1400": {"prize": "1400 DC", "amount": 1400, "winners": 7, "description": "🔥 Розыгрыш 1400 DC на семерых победителей! Огромная сумма — и множество шансов. Не упусти свой момент!"},
    "1800": {"prize": "1800 DC", "amount": 1800, "winners": 9, "description": "🔥 Розыгрыш 1800 DC на девятерых победителей! Щедрый куш для многих участников. Присоединяйся к борьбе за приз!"},
    "2400": {"prize": "2400 DC", "amount": 2400, "winners": 12, "description": "💎 Розыгрыш 2400 DC на двенадцать победителей! Массовый праздник щедрости для всех. Присоединяйся — весело и прибыльно!"},
    "3000": {"prize": "3000 DC", "amount": 3000, "winners": 15, "description": "💎 Розыгрыш 3000 DC на пятнадцать победителей! Большой призовой фонд для всех. Участвуй — и забери своё!"},
    "3600": {"prize": "3600 DC", "amount": 3600, "winners": 18, "description": "👑 Огромный розыгрыш 3600 DC на восемнадцать победителей! Максимум призов и возможностей. Докажи, что ты достоин!"},
    "4000": {"prize": "4000 DC", "amount": 4000, "winners": 20, "description": "👑 Мега-розыгрыш 4000 DC на двадцать победителей! Королевский куш и море победителей. Сражайся за свой шанс прямо сейчас!"},
}

def _ensure_col(table: str, column: str, ddl: str):
    try:
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()]
        if column not in cols: cur.execute(f'ALTER TABLE "{table}" ADD COLUMN {ddl}'); db.commit()
    except Exception as e: logger.warning(f"[giveaways] миграция {table}.{column}: {e}")

def _init_tables():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS giveaways (
        giveaway_id        INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, message_id INTEGER, host_id INTEGER,
        prize TEXT, description TEXT, winners_count INTEGER, end_time INTEGER, created_at INTEGER,
        required_invites INTEGER DEFAULT 0, participants TEXT, winners TEXT, status TEXT, valid_participants TEXT,
        final_embed_id INTEGER, auto_payout INTEGER DEFAULT 0, payout_done INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS giveaway_pending_payouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, giveaway_id INTEGER, user_id INTEGER, amount INTEGER,
        dm_message_id INTEGER DEFAULT 0, created_at INTEGER, paid_at INTEGER DEFAULT 0
    );
    """)
    db.commit()
    _ensure_col("giveaway_pending_payouts", "giveaway_id", "giveaway_id INTEGER")
    _ensure_col("giveaway_pending_payouts", "user_id", "user_id INTEGER")
    _ensure_col("giveaway_pending_payouts", "amount", "amount INTEGER DEFAULT 0")
    _ensure_col("giveaway_pending_payouts", "dm_message_id", "dm_message_id INTEGER DEFAULT 0")
    _ensure_col("giveaway_pending_payouts", "created_at", "created_at INTEGER DEFAULT 0")
    _ensure_col("giveaway_pending_payouts", "paid_at", "paid_at INTEGER DEFAULT 0")
    _ensure_col("giveaways", "auto_payout", "auto_payout INTEGER DEFAULT 0")
    _ensure_col("giveaways", "payout_done", "payout_done INTEGER DEFAULT 0")
    try:
        cur.executescript("""
        CREATE INDEX IF NOT EXISTS idx_giveaways_message ON giveaways(message_id);
        CREATE INDEX IF NOT EXISTS idx_giveaways_status  ON giveaways(status);
        CREATE INDEX IF NOT EXISTS idx_gpp_user          ON giveaway_pending_payouts (user_id, paid_at);
        CREATE INDEX IF NOT EXISTS idx_gpp_giveaway      ON giveaway_pending_payouts (giveaway_id, paid_at);
        """)
        db.commit()
    except Exception as e: logger.warning(f"[giveaways] idx create: {e}")

_bot = None
_setup_done = False

def list_from_str(data):
    if not data: return []
    try: return ast.literal_eval(data)
    except Exception: return []

def str_from_list(data): return str(data)

def parse_duration(duration_str: str):
    match = re.fullmatch(r'(\d+)\s*([mhd])', duration_str.strip().lower())
    if not match: return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == 'm': return timedelta(minutes=value)
    if unit == 'h': return timedelta(hours=value)
    if unit == 'd': return timedelta(days=value)

def is_giveaway_staff(member: disnake.Member) -> bool:
    return any(r.id in GIVEAWAY_FULL_ROLES for r in member.roles)

def _parse_dc_amount(prize: str) -> int:
    if not prize: return 0
    m = re.search(r"(\d+)", prize)
    if not m: return 0
    try: return int(m.group(1))
    except Exception: return 0

async def log_discord_giveaway(title: str, description: str, color: int = 0x00ff00, fields: list = None):
    if _bot is None: return
    try:
        channel = _bot.get_channel(LOG_CHANNEL_ID) or await _bot.fetch_channel(LOG_CHANNEL_ID)
        if not channel: return
        embed = disnake.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
        if fields:
            for name, value, inline in fields: embed.add_field(name=name, value=value, inline=inline)
        await channel.send(embed=embed)
    except Exception as e: logger.warning(f"[giveaways.log] {e}")

IMG_BANNER_GW  = "https://cdn.discordapp.com/attachments/1527006158282555412/1556735389618798632/image.png?backend=b2&ex=6ac53e4f&is=6ac3eccf&hm=ed4085879047dc6da3c00fc5a55edf0fe24d334f55f7086339380e0364a0ee09&"
IMG_STRIPE_GW  = "https://cdn.discordapp.com/attachments/1527006158282555412/1530795801268453447/pisk.png?ex=6a66e02f&is=6a658eaf&hm=79e41273327d2e1048ba42df62868cbb88f5b06b112ca864de2c7a02326523e9&"
IMG_BANNER_FIN = "https://cdn.discordapp.com/attachments/1527006158282555412/1556735391875203082/image.png?backend=b2&ex=6ac53e50&is=6ac3ecd0&hm=b331ed1665f81621e08ee916aaabaf5bb78430e86de1d7a51c0ce7072ec175f9&"
COLOR_GW = 6776679

def build_giveaway_embeds(prize, description, winners_count, participants_count, end_dt):
    end_ts = int(end_dt.timestamp())
    desc_text = (description or "").strip() or "Проводим розыгрыш — стоит нажать на кнопку участвовать, и больше условий нет!"
    embed_banner = disnake.Embed(color=COLOR_GW); embed_banner.set_image(url=IMG_BANNER_GW)
    embed_main = disnake.Embed(title=f"Розыгрыш на {prize} ! 🎁", description=f"> {desc_text}\n\nВремя окончания: <t:{end_ts}:R>", color=COLOR_GW)
    embed_main.set_image(url=IMG_STRIPE_GW)
    embed_main.add_field(name="> **Участвуют:**", value=f"```{participants_count}```", inline=True)
    embed_main.add_field(name="> **Победителей:**", value=f"```{winners_count}```", inline=True)
    return [embed_banner, embed_main]

def build_finished_giveaway_embed(prize, description, participants_count, winners_mentions, end_dt):
    end_ts = int(end_dt.timestamp())
    date_str = datetime.fromtimestamp(end_ts, MSK).strftime("%d.%m.%Y")
    desc_text = (description or "").strip() or "Розыгрыш завершён."
    embed_banner = disnake.Embed(color=COLOR_GW); embed_banner.set_image(url=IMG_BANNER_FIN)
    embed_main = disnake.Embed(title=f"Розыгрыш на {prize} завершён! 🏆", description=f"> {desc_text}\n\n> **Победитель(и):** {winners_mentions}\n\n> Спасибо за участие в розыгрышах! Ожидайте последующие розыгрыши!", color=COLOR_GW)
    embed_main.set_image(url=IMG_STRIPE_GW)
    embed_main.add_field(name="> **Участвовали:**", value=f"```{participants_count}```", inline=True)
    embed_main.add_field(name="> **Завершён:**", value=f"```{date_str}```", inline=True)
    return [embed_banner, embed_main]

class JoinButton(disnake.ui.Button):
    def __init__(self):
        super().__init__(label="ㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤ🎉 Участвоватьㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤ", style=disnake.ButtonStyle.secondary, custom_id="giveaway_join")
    async def callback(self, inter: disnake.MessageInteraction):
        try:
            row = cur.execute("SELECT * FROM giveaways WHERE message_id=? AND status='active'", (inter.message.id,)).fetchone()
            if not row: return await inter.response.send_message("❌ Розыгрыш не найден или завершён.", ephemeral=True)
            gid = row["giveaway_id"]; participants = list_from_str(row["participants"]); user_id = inter.user.id
            if user_id in participants: return await inter.response.send_message("🎊 Вы уже участвуете в розыгрыше!", ephemeral=True)
            participants.append(user_id)
            cur.execute("UPDATE giveaways SET participants=? WHERE giveaway_id=?", (str_from_list(participants), gid)); db.commit()
            end_dt = datetime.fromtimestamp(row["end_time"], timezone.utc)
            embeds = build_giveaway_embeds(row["prize"], row["description"], row["winners_count"], len(participants), end_dt)
            try: await inter.message.edit(embeds=embeds)
            except Exception: pass
            await inter.response.send_message("✅ Ты успешно присоединился к розыгрышу!", ephemeral=True)
            embed_dm = disnake.Embed(title="✅ Ты участвуешь в розыгрыше!", description=f"> **Приз:** {row['prize']}\n> **ID розыгрыша:** `{gid}`\n> **Участников:** {len(participants)}", color=0x00ff00)
            try: await inter.user.send(embed=embed_dm)
            except Exception: pass
        except Exception as e: logger.warning(f"[JoinButton] {e}")

class GiveawayView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None); self.add_item(JoinButton())

class GiveawaySelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="・Начать розыгрыш", description="Создать розыгрыш вручную", emoji="<:__:1538399607699021895>", value="create"),
            disnake.SelectOption(label="・Шаблонные розыгрыши", description="Готовые шаблоны DC-розыгрышей", emoji="<:cakleb:1553236134316875846>", value="templates"),
            disnake.SelectOption(label="・Лист розыгрышей", description="Все существующие розыгрыши", emoji="<:banne1:1538551829246513312>", value="list"),
            disnake.SelectOption(label="・Завершить принудительно", description="Принудительно завершить розыгрыш", emoji="<:clear:1538561439491686410>", value="end"),
            disnake.SelectOption(label="・Перевыбрать победителя", description="Перевыбрать победителя", emoji="<:restart:1553231421190049813>", value="reroll"),
        ]
        super().__init__(placeholder="Выберите нужный пункт", min_values=1, max_values=1, options=options, custom_id="giveaway_select")
    async def callback(self, inter: disnake.MessageInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await log_discord_giveaway(title="🎮 Выбор в панели розыгрышей", description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`", color=0x00aaff)
        value = inter.data.values[0]
        if value == "create": await inter.response.send_modal(GiveawayModal())
        elif value == "templates": await show_templates_panel(inter)
        elif value == "list":
            await inter.response.defer(ephemeral=True)
            await list_giveaways(inter)
        elif value == "end": await inter.response.send_modal(EndGiveawayModal())
        elif value == "reroll": await inter.response.send_modal(RerollModal())

class GiveawayPanelView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None); self.add_item(GiveawaySelect())

class GiveawayModal(disnake.ui.Modal):
    def __init__(self):
        super().__init__(title="Создание розыгрыша", components=[
            disnake.ui.TextInput(label="Приз", custom_id="prize", max_length=256),
            disnake.ui.TextInput(label="Описание", custom_id="description", style=disnake.TextInputStyle.paragraph, max_length=1024),
            disnake.ui.TextInput(label="Победителей (число)", custom_id="winners", max_length=3),
            disnake.ui.TextInput(label="Длительность (10m, 2h, 1d)", custom_id="duration", max_length=10, placeholder="Например: 30m, 2h, 7d"),
        ])
    async def callback(self, inter: disnake.ModalInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав на создание розыгрышей.", ephemeral=True)
        prize = inter.text_values["prize"].strip(); description = inter.text_values["description"].strip()
        try:
            winners_count = int(inter.text_values["winners"].strip())
            if winners_count < 1: raise ValueError
        except ValueError: return await inter.response.send_message("❌ Поле 'Победителей' должно быть целым числом ≥ 1.", ephemeral=True)
        duration_td = parse_duration(inter.text_values["duration"])
        if duration_td is None: return await inter.response.send_message("❌ Неверный формат длительности. Примеры: `30m`, `2h`, `7d`", ephemeral=True)
        end_dt = datetime.now(MSK) + duration_td; end_dt_utc = end_dt.astimezone(timezone.utc); end_time = int(end_dt_utc.timestamp()); created_at = now_ts()
        embeds = build_giveaway_embeds(prize, description, winners_count, 0, end_dt_utc)
        await inter.response.send_message("⏳ Создаю розыгрыш...", ephemeral=True)
        channel = _bot.get_channel(GIVEAWAY_CHANNEL_ID)
        if not channel: return await inter.edit_original_message(content="❌ Канал для розыгрышей не найден.")
        msg = await channel.send(content="|| @everyone ||", embeds=embeds, view=GiveawayView())
        cur.execute("""INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, description, winners_count, end_time, created_at, required_invites, participants, winners, status, auto_payout, payout_done) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (inter.guild.id, channel.id, msg.id, inter.author.id, prize, description, winners_count, end_time, created_at, 0, "[]", "[]", "active", 0, 0))
        db.commit(); gid = cur.lastrowid
        asyncio.create_task(schedule_end(gid))
        await inter.edit_original_message(content=f"✅ Розыгрыш создан! **ID: `{gid}`** (ручной — приз вручается вручную)")

async def get_valid_participants(gid: int, guild: disnake.Guild):
    row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
    if not row: return []
    participants = list_from_str(row["participants"]); valid = []
    for uid in participants:
        member = guild.get_member(uid)
        if not member or member.bot: continue
        valid.append(uid)
    return list(set(valid))

async def schedule_end(gid: int):
    row = cur.execute("SELECT end_time FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
    if not row: return
    delay = row["end_time"] - now_ts()
    if delay > 0: await asyncio.sleep(delay)
    await finish_giveaway(gid)

async def _queue_pending_payouts(gid: int, row, winners: List[int]) -> int:
    auto_payout = row["auto_payout"]
    if not auto_payout: return 0
    if not winners: cur.execute("UPDATE giveaways SET payout_done=1 WHERE giveaway_id=?", (gid,)); db.commit(); return 0
    total_amount = _parse_dc_amount(row["prize"])
    if total_amount <= 0: return 0
    share = total_amount // len(winners)
    if share <= 0: return 0
    now = now_ts()
    for uid in winners:
        cur.execute("INSERT INTO giveaway_pending_payouts (giveaway_id, user_id, amount, dm_message_id, created_at, paid_at) VALUES (?, ?, ?, 0, ?, 0)", (gid, uid, share, now))
    cur.execute("UPDATE giveaways SET payout_done=1 WHERE giveaway_id=?", (gid,)); db.commit()
    return share

async def process_pending_payouts(bot, user_id: int) -> int:
    rows = cur.execute("SELECT id, giveaway_id, amount, dm_message_id FROM giveaway_pending_payouts WHERE user_id=? AND paid_at=0", (user_id,)).fetchall()
    if not rows:
        try:
            won_giveaways = cur.execute("SELECT giveaway_id, prize, winners FROM giveaways WHERE status='finished' AND auto_payout=1").fetchall()
            for g in won_giveaways:
                winners = list_from_str(g["winners"])
                if user_id not in winners: continue
                exists = cur.execute("SELECT paid_at FROM giveaway_pending_payouts WHERE giveaway_id=? AND user_id=?", (g["giveaway_id"], user_id)).fetchone()
                if exists and exists["paid_at"]: continue
                if exists: continue
                amount = _parse_dc_amount(g["prize"]) // max(len(winners), 1)
                if amount <= 0: continue
                cur.execute("INSERT INTO giveaway_pending_payouts (giveaway_id, user_id, amount, dm_message_id, created_at, paid_at) VALUES (?, ?, ?, 0, ?, 0)", (g["giveaway_id"], user_id, amount, now_ts()))
            db.commit()
            rows = cur.execute("SELECT id, giveaway_id, amount, dm_message_id FROM giveaway_pending_payouts WHERE user_id=? AND paid_at=0", (user_id,)).fetchall()
        except Exception as e: logger.exception(f"[giveaways] fallback scan error: {e}")
    if not rows: return 0
    total_paid = 0
    for r in rows:
        pid = r["id"]; gid = r["giveaway_id"]; amount = r["amount"]; dm_mid = r["dm_message_id"]
        try:
            await add_dc(user_id, amount, f"Победа в розыгрыше #{gid} (после отзыва)", notify=False, log=False, to_clan_pool=True)
            cur.execute("UPDATE giveaway_pending_payouts SET paid_at=? WHERE id=?", (now_ts(), pid)); db.commit()
            total_paid += amount
            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                dm_channel = user.dm_channel or await user.create_dm()
                new_embeds = _build_paid_winner_dm(gid=gid, amount=amount)
                edited = False
                if dm_mid:
                    try: msg = await dm_channel.fetch_message(dm_mid); await msg.edit(embeds=new_embeds); edited = True
                    except Exception as e: logger.warning(f"[giveaways] не отредактировать DM {dm_mid}: {e}")
                if not edited:
                    try: await dm_channel.send(embeds=new_embeds)
                    except Exception as e: logger.warning(f"[giveaways] не отправить DM {user_id}: {e}")
            except Exception as e: logger.warning(f"[giveaways] DM payout {user_id}: {e}")
            await log_discord_giveaway(title="💎 Приз за розыгрыш выдан", description=f"> **Победитель:** <@{user_id}>\n> **Розыгрыш:** `#{gid}`\n> **Сумма:** `+{amount} DC`\n> **Условие:** отзыв написан", color=0x00ff88)
        except Exception as e: logger.exception(f"[giveaways] process_pending_payouts id={pid}: {e}")
    return total_paid

async def finish_giveaway(gid: int):
    try:
        row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
        if not row or row["status"] != "active": return
        guild = _bot.get_guild(row["guild_id"])
        if not guild: return
        channel = guild.get_channel(row["channel_id"]) or _bot.get_channel(row["channel_id"])
        if not channel: return
        valid_participants = await get_valid_participants(gid, guild); participants = list_from_str(row["participants"]); winners_count = row["winners_count"]
        pool = valid_participants.copy(); random.shuffle(pool); winners = pool[:winners_count] if pool else []
        cur.execute("UPDATE giveaways SET winners=?, status='finished', valid_participants=? WHERE giveaway_id=?", (str_from_list(winners), str_from_list(valid_participants), gid)); db.commit()
        try: msg = await channel.fetch_message(row["message_id"]); await msg.delete()
        except Exception: pass
        winners_mentions = " ".join(f"<@{u}>" for u in winners) if winners else "Нет победителей 😔"
        end_dt = datetime.fromtimestamp(row["end_time"], timezone.utc)
        finished_embeds = build_finished_giveaway_embed(row["prize"], row["description"], len(participants), winners_mentions, end_dt)
        try:
            embed_msg = await channel.send(embeds=finished_embeds)
            cur.execute("UPDATE giveaways SET final_embed_id=? WHERE giveaway_id=?", (embed_msg.id, gid)); db.commit()
        except Exception as e: logger.exception(f"[giveaways] финальный embed: {e}")
        share = await _queue_pending_payouts(gid, row, winners)
        await send_giveaway_report(gid=gid, prize=row["prize"], winners=winners, share=share, is_auto=bool(row["auto_payout"]))
        prize_name = row["prize"]; is_auto = bool(row["auto_payout"]); winner_ids = set(winners)
        fallback_share = _parse_dc_amount(prize_name) // max(len(winners), 1) if winners else 0
        for uid in participants:
            try:
                member = guild.get_member(uid)
                if not member: continue
                if uid in winner_ids: dm = _build_template_winner_dm(gid, prize_name, share if share > 0 else fallback_share) if is_auto else _build_manual_winner_dm(gid, prize_name)
                else: dm = _build_loser_dm(gid, prize_name)
                sent = await member.send(embeds=dm)
                if is_auto and uid in winner_ids and sent:
                    cur.execute("UPDATE giveaway_pending_payouts SET dm_message_id=? WHERE giveaway_id=? AND user_id=? AND paid_at=0", (sent.id, gid, uid)); db.commit()
            except disnake.Forbidden: pass
            except Exception as e: logger.warning(f"[giveaways] DM {uid}: {e}")
    except Exception as e: logger.exception(f"[giveaways] finish_giveaway CRITICAL: {e}")

def _build_manual_winner_dm(gid: int, prize: str) -> list:
    e1 = disnake.Embed(color=0xffaa00); e1.set_image(url=IMG_STRIPE_GW)
    e2 = disnake.Embed(title="🏆 Ты победил в розыгрыше!", description=f"> **Приз:** {prize}\n> **ID розыгрыша:** `#{gid}`\n\n> 📩 **Что делать:**\n> Отпиши в ЛС <@{REPORT_DM_USER_ID}> в течение **24 часов**,\n> иначе приз уйдёт следующему участнику.", color=0xffaa00); e2.set_image(url=IMG_STRIPE_GW)
    return [e1, e2]

def _build_template_winner_dm(gid: int, prize: str, share: int) -> list:
    e1 = disnake.Embed(color=0xffaa00); e1.set_image(url=IMG_STRIPE_GW)
    e2 = disnake.Embed(title="🏆 Ты выиграл в розыгрыше!", description=f"> **Приз:** {prize}\n> **Твоя доля:** `+{share} DC`\n> **ID розыгрыша:** `#{gid}`\n\n> ⏳ **Как забрать?**\n> Напиши **новый отзыв** в <#{REVIEW_CHANNEL_ID}> — и `{share} DC` автоматически упадут тебе на баланс.\n\n> ❗ Если ты уже писал отзыв раньше — нужно написать **ещё один** (кулдаун 2 минуты).\n\n> ✨ _После отзыва это сообщение обновится._", color=0xffaa00); e2.set_image(url=IMG_STRIPE_GW)
    return [e1, e2]

def _build_paid_winner_dm(gid: int, amount: int) -> list:
    e1 = disnake.Embed(color=0x00ff88); e1.set_image(url=IMG_STRIPE_GW)
    e2 = disnake.Embed(title="💎 Приз зачислен на баланс!", description=f"> **Сумма:** `+{amount} DC`\n> **ID розыгрыша:** `#{gid}`\n\n> ✨ DC уже у тебя на балансе. Спасибо за отзыв!", color=0x00ff88); e2.set_image(url=IMG_STRIPE_GW)
    return [e1, e2]

def _build_loser_dm(gid: int, prize: str) -> list:
    e1 = disnake.Embed(color=0x808080); e1.set_image(url=IMG_STRIPE_GW)
    e2 = disnake.Embed(title="🎲 Розыгрыш завершён", description=f"> **Приз:** {prize}\n> **ID розыгрыша:** `#{gid}`\n\n> **Результат:**\n> Ты не занял призовое место. Постарайся в следующий раз! 🍀", color=0x808080); e2.set_image(url=IMG_STRIPE_GW)
    return [e1, e2]

async def send_giveaway_report(gid: int, prize: str, winners: list, share: int = 0, is_auto: bool = False):
    try:
        if _bot is None: return
        user = _bot.get_user(REPORT_DM_USER_ID) or await _bot.fetch_user(REPORT_DM_USER_ID)
        if not user or not winners: return
        file_data = io.BytesIO("\n".join(str(uid) for uid in winners).encode("utf-8"))
        file = disnake.File(file_data, filename=f"winners_{gid}.txt")
        winners_mentions = " ".join(f"<@{u}>" for u in winners)
        type_label = "💎 Шаблонный (после отзыва)" if is_auto else "📩 Ручной"
        e1 = disnake.Embed(color=6776679); e1.set_image(url=IMG_STRIPE_GW)
        extra = f"> **Каждому:** `+{share} DC`\n> **Всего:** `{share * len(winners)} DC`\n> ⏳ **Ждут нового отзыва в <#{REVIEW_CHANNEL_ID}>**\n> После отзыва DC упадут автоматически\n\n" if is_auto and share > 0 else "> ⏳ **Ждём отписи в ЛС** от каждого победителя\n> (в течение 24ч, иначе приз уйдёт следующему)\n\n"
        e2 = disnake.Embed(title=f"📊 Победители розыгрыша #{gid}", description=f"> **Приз:** {prize}\n> **Тип:** {type_label}\n> **Победителей:** `{len(winners)}`\n\n{extra}> 🏆 **Список победителей:**\n> {winners_mentions}", color=6776679)
        e2.set_image(url=IMG_STRIPE_GW)
        await user.send(embeds=[e1, e2], file=file)
    except Exception as e: logger.exception(f"[giveaways] send_giveaway_report: {e}")

async def reroll_giveaway(inter, gid: int):
    row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
    if not row: return await inter.edit_original_message(content="❌ Розыгрыш не найден.")
    if row["status"] == "active": return await inter.edit_original_message(content="❌ Розыгрыш ещё не завершён.")
    guild = _bot.get_guild(row["guild_id"]); channel = guild.get_channel(row["channel_id"]) or _bot.get_channel(row["channel_id"])
    valid_participants = await get_valid_participants(gid, guild)
    if not valid_participants: return await inter.edit_original_message(content="❌ Нет валидных участников для перевыбора.")
    old_winners = list_from_str(row["winners"]); pool = [u for u in valid_participants if u not in old_winners]
    if not pool: return await inter.edit_original_message(content="❌ Нет участников для перевыбора.")
    winners_count = row["winners_count"]; random.shuffle(pool); new_winners = pool[:winners_count] if pool else []
    cur.execute("UPDATE giveaways SET winners=? WHERE giveaway_id=?", (str_from_list(new_winners), gid)); db.commit()
    try:
        if row["final_embed_id"]: msg = await channel.fetch_message(row["final_embed_id"]); await msg.delete()
    except Exception: pass
    winners_mentions = " ".join(f"<@{u}>" for u in new_winners) if new_winners else "Нет победителей 😔"
    end_dt = datetime.fromtimestamp(row["end_time"], timezone.utc)
    embed_msg = await channel.send(embeds=build_finished_giveaway_embed(row["prize"], row["description"] or "", len(list_from_str(row["participants"])), winners_mentions, end_dt))
    cur.execute("UPDATE giveaways SET final_embed_id=? WHERE giveaway_id=?", (embed_msg.id, gid)); db.commit()
    is_auto = bool(row["auto_payout"]); share = 0
    if is_auto and new_winners:
        share = _parse_dc_amount(row["prize"]) // len(new_winners) if new_winners else 0
        for old_uid in old_winners:
            if old_uid in new_winners: continue
            cur.execute("DELETE FROM giveaway_pending_payouts WHERE giveaway_id=? AND user_id=? AND paid_at=0", (gid, old_uid))
        for uid in new_winners:
            exists = cur.execute("SELECT id FROM giveaway_pending_payouts WHERE giveaway_id=? AND user_id=?", (gid, uid)).fetchone()
            if not exists: cur.execute("INSERT INTO giveaway_pending_payouts (giveaway_id, user_id, amount, dm_message_id, created_at, paid_at) VALUES (?, ?, ?, 0, ?, 0)", (gid, uid, share, now_ts()))
        db.commit()
    if is_auto and new_winners:
        for uid in new_winners:
            try:
                member = guild.get_member(uid)
                if not member: continue
                sent = await member.send(embeds=_build_template_winner_dm(gid, row["prize"], share))
                if sent: cur.execute("UPDATE giveaway_pending_payouts SET dm_message_id=? WHERE giveaway_id=? AND user_id=? AND paid_at=0", (sent.id, gid, uid)); db.commit()
            except Exception as e: logger.warning(f"[giveaways] reroll DM {uid}: {e}")
    await send_giveaway_report(gid=gid, prize=row["prize"], winners=new_winners, share=share, is_auto=is_auto)
    await inter.edit_original_message(content=f"✅ Перевыбор выполнен для розыгрыша #{gid}")

class EndGiveawayModal(disnake.ui.Modal):
    def __init__(self):
        super().__init__(title="Принудительное завершение", components=[disnake.ui.TextInput(label="ID розыгрыша", custom_id="giveaway_id", max_length=10, placeholder="Введите числовой ID")])
    async def callback(self, inter: disnake.ModalInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        try: gid = int(inter.text_values["giveaway_id"].strip())
        except ValueError: return await inter.response.send_message("❌ ID должен быть числом.", ephemeral=True)
        row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=? AND status='active'", (gid,)).fetchone()
        if not row: return await inter.response.send_message("❌ Активный розыгрыш не найден.", ephemeral=True)
        await inter.response.send_message("⏳ Завершаю...", ephemeral=True)
        await finish_giveaway(gid)
        await inter.edit_original_message(content=f"✅ Розыгрыш #{gid} завершён.")

class RerollModal(disnake.ui.Modal):
    def __init__(self):
        super().__init__(title="Перевыбор победителя", components=[disnake.ui.TextInput(label="ID розыгрыша", custom_id="giveaway_id", max_length=10, placeholder="Введите числовой ID")])
    async def callback(self, inter: disnake.ModalInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        try: gid = int(inter.text_values["giveaway_id"].strip())
        except ValueError: return await inter.response.send_message("❌ ID должен быть числом.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        await reroll_giveaway(inter, gid)

async def show_templates_panel(inter: disnake.MessageInteraction):
    e = disnake.Embed(title="💎 Шаблонные розыгрыши", description=f"> Выберите тип ниже — розыгрыш стартует сразу.\n\n> ⏱ **Длительность:** 1 день\n> 💰 **Выдача:** после отзыва в <#{REVIEW_CHANNEL_ID}>\n> ⭐ **Бонус:** за отзыв ещё начислят DC\n\n**Доступные шаблоны:** от **100** до **4000 DC**", color=6776679)
    e.set_image(url=IMG_STRIPE_GW)
    await inter.response.send_message(embed=e, view=TemplateStartView(), ephemeral=True)

class TemplateSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="100 DC · 1 победитель", description="Быстрый розыгрыш", value="100"),
            disnake.SelectOption(label="150 DC · 1 победитель", description="Стандартный розыгрыш", value="150"),
            disnake.SelectOption(label="350 DC · 1 победитель", description="Средний розыгрыш", value="350"),
            disnake.SelectOption(label="400 DC · 2 победителя", description="Розыгрыш на двоих", value="400"),
            disnake.SelectOption(label="450 DC · 2 победителя", description="Розыгрыш на двоих", value="450"),
            disnake.SelectOption(label="600 DC · 3 победителя", description="Розыгрыш на троих", value="600"),
            disnake.SelectOption(label="700 DC · 3 победителя", description="Розыгрыш на троих", value="700"),
            disnake.SelectOption(label="1000 DC · 5 победителей", description="Большой розыгрыш", value="1000"),
            disnake.SelectOption(label="1400 DC · 7 победителей", description="Средний розыгрыш", value="1400"),
            disnake.SelectOption(label="1800 DC · 9 победителей", description="Расширенный розыгрыш", value="1800"),
            disnake.SelectOption(label="2400 DC · 12 победителей", description="Массовый розыгрыш", value="2400"),
            disnake.SelectOption(label="3000 DC · 15 победителей", description="Большой массовый розыгрыш", value="3000"),
            disnake.SelectOption(label="3600 DC · 18 победителей", description="Огромный розыгрыш", value="3600"),
            disnake.SelectOption(label="4000 DC · 20 победителей", description="Мега-розыгрыш", value="4000"),
        ]
        super().__init__(placeholder="Выберите шаблон розыгрыша...", min_values=1, max_values=1, options=options, custom_id="giveaway_template_select")
    async def callback(self, inter: disnake.MessageInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        key = inter.data.values[0]
        if key not in GIVEAWAY_TEMPLATES: return await inter.response.send_message("❌ Шаблон не найден.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        tpl = GIVEAWAY_TEMPLATES[key]; prize = tpl["prize"]; winners_count = tpl["winners"]; description = tpl["description"]
        end_dt = datetime.now(MSK) + timedelta(days=1); end_dt_utc = end_dt.astimezone(timezone.utc); end_time = int(end_dt_utc.timestamp()); created_at = now_ts()
        channel = _bot.get_channel(GIVEAWAY_CHANNEL_ID)
        if not channel: return await inter.edit_original_response(content="❌ Канал не найден.")
        embeds = build_giveaway_embeds(prize, description, winners_count, 0, end_dt_utc)
        msg = await channel.send(content="|| @everyone ||", embeds=embeds, view=GiveawayView())
        cur.execute("""INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, description, winners_count, end_time, created_at, required_invites, participants, winners, status, auto_payout, payout_done) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (inter.guild.id, channel.id, msg.id, inter.author.id, prize, description, winners_count, end_time, created_at, 0, "[]", "[]", "active", 1, 0))
        db.commit(); gid = cur.lastrowid
        asyncio.create_task(schedule_end(gid))
        await inter.edit_original_response(content=(f"✅ Шаблонный розыгрыш **{prize}** создан! ID: `{gid}`\n> 💰 DC начислятся победителям после нового отзыва ({winners_count} чел.)"), embeds=[], view=None)

class TemplateStartView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=180); self.add_item(TemplateSelect())

async def list_giveaways(inter: disnake.MessageInteraction):
    rows = cur.execute("SELECT * FROM giveaways WHERE guild_id=? ORDER BY giveaway_id DESC LIMIT 20", (inter.guild.id,)).fetchall()
    if not rows: return await inter.edit_original_response(content="Розыгрышей не найдено.")
    lines = []
    for r in rows:
        status_icon = "🟢" if r["status"] == "active" else "🔴"
        participants_count = len(list_from_str(r["participants"])); winners = list_from_str(r["winners"])
        time_str = f"Конец: <t:{r['end_time']}:R>" if r["status"] == "active" else f"Закончился: <t:{r['end_time']}:d>"
        winners_str = " | Победители: " + ", ".join(f"<@{w}>" for w in winners) if r["status"] == "finished" and winners else ""
        auto_str = " 💎" if r["auto_payout"] else " 📩"
        lines.append(f"{status_icon} **ID {r['giveaway_id']}**{auto_str} — {r['prize']}\n> Участников: **{participants_count}** | {time_str}{winners_str}")
    embed = disnake.Embed(title="📋 Список розыгрышей (последние 20)", description="\n\n".join(lines), color=6776679)
    embed.set_footer(text="💎 = шаблонный (после отзыва) · 📩 = ручной")
    await inter.followup.send(embed=embed, ephemeral=True)

async def send_giveaway_panel():
    try:
        ch = _bot.get_channel(STAFF_PANEL_CHANNEL_ID) or await _bot.fetch_channel(STAFF_PANEL_CHANNEL_ID)
        if not ch: return
        try:
            async for msg in ch.history(limit=50):
                if msg.author == _bot.user and msg.embeds:
                    for e in msg.embeds:
                        if e.title and "розыгрыш" in e.title.lower():
                            try: await msg.delete()
                            except Exception: pass
                            break
        except Exception: pass
        e1 = disnake.Embed(title="Управление розыгрышами", description="> Панель для управления всеми розыгрышами сервера.\n\n> **Начать розыгрыш** — создать вручную с настройками.\n> **Шаблонные розыгрыши** — готовые DC-розыгрыши (выдача после отзыва).\n> **Лист розыгрышей** — все текущие и завершённые.\n> **Завершить принудительно** — закрыть досрочно.\n> **Перевыбрать победителя** — реролл после завершения.", color=6776679)
        e1.set_image(url=IMG_STRIPE_GW)
        await ch.send(embed=e1, view=GiveawayPanelView())
    except Exception as e: logger.warning(f"[giveaways] send_giveaway_panel: {e}")

async def _delayed_init_and_panel():
    try:
        await _bot.wait_until_ready(); await asyncio.sleep(8)
        try:
            active_rows = cur.execute("SELECT giveaway_id, end_time FROM giveaways WHERE status='active'").fetchall()
            for r in active_rows:
                gid = r["giveaway_id"]
                if r["end_time"] <= now_ts(): asyncio.create_task(finish_giveaway(gid))
                else: asyncio.create_task(schedule_end(gid))
        except Exception as e: logger.exception(f"[giveaways] restore timers: {e}")
        await send_giveaway_panel()
    except Exception as e: logger.exception(f"[giveaways] _delayed_init_and_panel: {e}")

def setup_giveaways(bot_instance):
    global _bot, _setup_done
    if _setup_done: return
    _setup_done = True; _bot = bot_instance
    _init_tables()
    bot_instance.add_view(GiveawayView()); bot_instance.add_view(GiveawayPanelView())
    try: bot_instance.loop.create_task(_delayed_init_and_panel())
    except Exception as e: logger.warning(f"[giveaways] не удалось запустить init task: {e}")
    logger.info("[giveaways] ✅ модуль розыгрышей подключён")


# ============================================================
# БЛОК 5: ACHIEVEMENTS PANEL (достижения)
# ============================================================
CANVAS_W, CANVAS_H = 1800, 1000
PAD_X, PAD_Y = 56, 44

def _ach_base_canvas(user_id):
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, CANVAS_W - 1, CANVAS_H - 1), radius=30, fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)
    hx, hy = PAD_X, PAD_Y
    d.rounded_rectangle((hx, hy, hx + 54, hy + 54), radius=14, fill=(58, 58, 64) + (255,))
    _draw_icon(d, hx + 27, hy + 28, I_TROPHY, 26, GOLD)
    bx = hx + 54 + 18
    d.text((bx, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx + 2, hy + 38), "SHOP & ECOSYSTEM", font=_font(11), fill=MUTED)
    meta_r = CANVAS_W - PAD_X
    lbl = "ДОСТИЖЕНИЯ"; uid = f"#{user_id}"
    w1 = _tw(d, lbl, _font(11)); w2 = _tw(d, uid, _font(20))
    d.text((meta_r - w1, hy + 12), lbl, font=_font(11), fill=MUTED)
    d.text((meta_r - w2, hy + 32), uid, font=_font(20), fill=TEXT)
    sy = hy + 54 + 16
    d.line((PAD_X, sy, CANVAS_W - PAD_X, sy), fill=STACK_HDR + (255,), width=2)
    return img, d

def _stack_panel_ach(base, d, box, radius=22):
    x1, y1, x2, y2 = box
    _alpha_fill(base, (x1 + 12, y1 + 12, x2 + 12, y2 + 12), (46, 46, 52), alpha=110, radius=radius)
    _alpha_fill(base, (x1 + 6, y1 + 6, x2 + 6, y2 + 6), (46, 46, 52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)

def _dashed(d, box, radius, color, dash=8, gap=6, width=2):
    x1, y1, x2, y2 = box; r = radius
    def dl(p1, p2):
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        L = (dx * dx + dy * dy) ** 0.5
        if L == 0: return
        ux, uy = dx / L, dy / L; pos = 0.0
        while pos < L:
            e = min(pos + dash, L)
            d.line([(p1[0] + ux * pos, p1[1] + uy * pos), (p1[0] + ux * e, p1[1] + uy * e)], fill=color, width=width)
            pos = e + gap
    dl((x1 + r, y1), (x2 - r, y1)); dl((x2 - r, y2), (x1 + r, y2))
    dl((x1, y1 + r), (x1, y2 - r)); dl((x2, y1 + r), (x2, y2 - r))
    d.arc((x1, y1, x1 + 2 * r, y1 + 2 * r), 180, 270, fill=color, width=width)
    d.arc((x2 - 2 * r, y1, x2, y1 + 2 * r), 270, 360, fill=color, width=width)
    d.arc((x1, y2 - 2 * r, x1 + 2 * r, y2), 90, 180, fill=color, width=width)
    d.arc((x2 - 2 * r, y2 - 2 * r, x2, y2), 0, 90, fill=color, width=width)

def _draw_ach_left_panel(img, d, box, user_id, active_key):
    _stack_panel_ach(img, d, box, radius=22)
    x1, y1, x2, y2 = box; pad = 22
    overall = get_overall_progress(user_id); total_unlocked = overall["unlocked"]; total_all = overall["total"]
    tot_y1 = y1 + pad; tot_y2 = tot_y1 + 150
    tx1, tx2 = x1 + pad, x2 - pad
    _gradient_box(img, (tx1, tot_y1, tx2, tot_y2), GOLD, GOLD, alpha=22, radius=16)
    d.rounded_rectangle((tx1, tot_y1, tx2, tot_y2), radius=16, outline=GOLD + (200,), width=2)
    ic_size = 46; ib_x = (tx1 + tx2) // 2 - ic_size // 2; ib_y = tot_y1 + 16
    _alpha_fill(img, (ib_x, ib_y, ib_x + ic_size, ib_y + ic_size), GOLD, alpha=70, radius=12)
    d.rounded_rectangle((ib_x, ib_y, ib_x + ic_size, ib_y + ic_size), radius=12, outline=GOLD + (230,), width=2)
    _draw_icon(d, ib_x + ic_size // 2, ib_y + ic_size // 2 + 1, I_TROPHY, 22, GOLD)
    d.text(((tx1 + tx2) // 2, tot_y1 + 74), "ОТКРЫТО", font=_font(11), fill=MUTED, anchor="mm")
    vw = _tw(d, str(total_unlocked), _font(46)); ow = _tw(d, f" / {total_all}", _font(20))
    sx = (tx1 + tx2 - vw - ow) // 2
    d.text((sx, tot_y1 + 92), str(total_unlocked), font=_font(46), fill=GOLD)
    d.text((sx + vw + 4, tot_y1 + 92 + 22), f" / {total_all}", font=_font(20), fill=DIM)
    tt_y = tot_y2 + 18; d.text((x1 + pad, tt_y), "КАТЕГОРИИ", font=_font(11), fill=MUTED)
    list_y = tt_y + 24; list_bottom = y2 - pad; n = len(CATEGORIES); gap = 6
    rh = (list_bottom - list_y - gap * (n - 1)) // n; rh = max(rh, 44)
    progress = get_category_progress(user_id)
    for i, cat in enumerate(CATEGORIES):
        cy = list_y + i * (rh + gap)
        _draw_cat_row(img, d, x1 + pad, cy, (x2 - pad) - (x1 + pad), rh, cat, progress.get(cat["key"], {}), cat["key"] == active_key)

def _draw_cat_row(img, d, x, y, w, h, cat, prog, active):
    color = CATEGORY_COLORS.get(cat["color"], SILVER); is_act = active
    cnt = prog.get("unlocked", 0); total = prog.get("total", 0)
    if is_act:
        _gradient_box(img, (x, y, x + w, y + h), color, color, alpha=28, radius=12)
        d.rounded_rectangle((x, y, x + w, y + h), radius=12, outline=color + (220,), width=2)
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    ic_size = 34; ib_x = x + 10; ib_y = y + (h - ic_size) // 2
    _alpha_fill(img, (ib_x, ib_y, ib_x + ic_size, ib_y + ic_size), color, alpha=55, radius=9)
    fa = FA_MAP.get(cat.get("icon", "fa-star"), I_STAR)
    _draw_icon(d, ib_x + ic_size // 2, ib_y + ic_size // 2 + 1, fa, 15, color)
    tx = ib_x + ic_size + 12
    d.text((tx, y + h // 2 - 10), cat["label"], font=_font(14), fill=TEXT if is_act else TEXT_SOFT)
    val = f"{cnt} / {total}"; vf = _font(14); vw = _tw(d, val, vf)
    vc = GREEN if cnt == total and total > 0 else (GOLD if cnt > 0 else DIM)
    d.text((x + w - 12 - vw, y + h // 2 - 10), val, font=vf, fill=vc)

def _draw_ach_card(img, d, x, y, w, h, ach, unlocked, cat_color):
    if ach and unlocked:
        color = cat_color; border = _lighten(color, 0.15)
        _gradient_box(img, (x, y, x + w, y + h), color, color, alpha=18, radius=16)
        d.rounded_rectangle((x, y, x + w, y + h), radius=16, outline=color + (220,), width=2)
        ic_size = 58; ib_x = x + 18; ib_y = y + 18
        _alpha_fill(img, (ib_x, ib_y, ib_x + ic_size, ib_y + ic_size), color, alpha=70, radius=14)
        d.rounded_rectangle((ib_x, ib_y, ib_x + ic_size, ib_y + ic_size), radius=14, outline=color + (230,), width=2)
        fa = FA_MAP.get(ach.get("icon", "fa-star"), I_STAR)
        _draw_icon(d, ib_x + ic_size // 2, ib_y + ic_size // 2 + 1, fa, 26, color)
        tx = ib_x + ic_size + 16; name_f = _font(17)
        name_shown = _ellipsis(d, ach.get("name", "—"), name_f, x + w - 18 - tx)
        d.text((tx, ib_y + ic_size // 2 - 12), name_shown, font=name_f, fill=TEXT)
        desc_y = ib_y + ic_size + 14
        for i, line in enumerate(_wrap(d, ach.get("desc", ""), _font(13), w - 36, 2)):
            d.text((x + 18, desc_y + i * 20), line, font=_font(13), fill=MUTED)
        sy = y + h - 30
        d.line((x + 18, sy - 10, x + w - 18, sy - 10), fill=color + (60,), width=1)
        _draw_icon(d, x + 26, sy + 8, I_CHECK, 13, color)
        d.text((x + 46, sy), "ПОЛУЧЕНО", font=_font(11), fill=color)
    elif ach:
        d.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=INNER_BG + (255,), outline=(42, 42, 48) + (255,), width=2)
        _dashed(d, (x, y, x + w, y + h), 16, (42, 42, 48), dash=8, gap=6, width=2)
        ic_size = 58; ib_x = x + 18; ib_y = y + 18
        d.rounded_rectangle((ib_x, ib_y, ib_x + ic_size, ib_y + ic_size), radius=14, fill=(26, 26, 32) + (255,))
        _draw_icon(d, ib_x + ic_size // 2, ib_y + ic_size // 2 + 1, I_LOCK, 24, (58, 58, 64))
        tx = ib_x + ic_size + 16; name_f = _font(17)
        name_shown = _ellipsis(d, ach.get("name", "—"), name_f, x + w - 18 - tx)
        d.text((tx, ib_y + ic_size // 2 - 12), name_shown, font=name_f, fill=(90, 90, 96))
        desc_y = ib_y + ic_size + 14
        for i, line in enumerate(_wrap(d, ach.get("desc", ""), _font(13), w - 36, 2)):
            d.text((x + 18, desc_y + i * 20), line, font=_font(13), fill=(70, 70, 76))
        sy = y + h - 30
        d.line((x + 18, sy - 10, x + w - 18, sy - 10), fill=(42, 42, 48) + (255,), width=1)
        d.text((x + 18, sy), "НЕ ПОЛУЧЕНО", font=_font(11), fill=(70, 70, 76))
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=(12, 12, 16) + (255,), outline=(28, 28, 34) + (255,), width=2)
        _dashed(d, (x, y, x + w, y + h), 16, (28, 28, 34), dash=8, gap=6, width=2)
        _draw_icon(d, x + w // 2, y + h // 2, I_ELLIPSIS, 26, (46, 46, 52))

def generate_achievements_panel(user_id: int, active_key: str = "base") -> io.BytesIO:
    if active_key not in CATEGORY_ORDER: active_key = CATEGORY_ORDER[0]
    cat = next((c for c in CATEGORIES if c["key"] == active_key), CATEGORIES[0])
    cat_color = CATEGORY_COLORS.get(cat["color"], SILVER); unlocked = get_user_unlocked_set(user_id)
    img, d = _ach_base_canvas(user_id)
    body_y = 138; body_h = CANVAS_H - PAD_Y - body_y; left_w = 448; gap = 30
    lx1 = PAD_X; lx2 = lx1 + left_w; rx1 = lx2 + gap; rx2 = CANVAS_W - PAD_X
    _draw_ach_left_panel(img, d, (lx1, body_y, lx2 - 12, body_y + body_h - 12), user_id, active_key)
    _stack_panel_ach(img, d, (rx1, body_y, rx2 - 12, body_y + body_h - 12), radius=22)
    rpx1 = rx1 + 28; rpx2 = rx2 - 12 - 28; rpy = body_y + 22
    fa_head = FA_MAP.get(cat.get("icon", "fa-star"), I_STAR); head_icon_size = 42
    d.rounded_rectangle((rpx1, rpy + 2, rpx1 + 6, rpy + 48), radius=3, fill=cat_color + (255,))
    _alpha_fill(img, (rpx1 + 20, rpy, rpx1 + 20 + head_icon_size, rpy + head_icon_size), cat_color, alpha=65, radius=11)
    _draw_icon(d, rpx1 + 20 + head_icon_size // 2, rpy + head_icon_size // 2 + 1, fa_head, 20, cat_color)
    d.text((rpx1 + 20 + head_icon_size + 16, rpy + 6), cat["label"].upper(), font=_font(24), fill=TEXT)
    keys = CATEGORY_KEYS.get(active_key, []); cnt = sum(1 for k in keys if k in unlocked); total = len(keys)
    page_idx = CATEGORY_ORDER.index(active_key)
    sub = f"страница {page_idx + 1} / {len(CATEGORY_ORDER)} · {cnt} / {total} открыто"
    sw = _tw(d, sub, _font(14)); d.text((rpx2 - sw, rpy + 12), sub, font=_font(14), fill=MUTED)
    sep_y = rpy + 56; d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)
    grid_y = sep_y + 16; grid_bottom = body_y + body_h - 12 - 26; grid_h = grid_bottom - grid_y
    cell_gap = 14; cols, rows = 3, 2
    cell_w = (rpx2 - rpx1 - cell_gap * (cols - 1)) // cols; cell_h = (grid_h - cell_gap * (rows - 1)) // rows
    slots = cols * rows
    for idx in range(slots):
        r = idx // cols; c = idx % cols; cx = rpx1 + c * (cell_w + cell_gap); cy = grid_y + r * (cell_h + cell_gap)
        if idx < len(keys):
            key = keys[idx]; ach = ACHIEVEMENTS.get(key)
            _draw_ach_card(img, d, cx, cy, cell_w, cell_h, ach, key in unlocked, cat_color)
        else: _draw_ach_card(img, d, cx, cy, cell_w, cell_h, None, False, cat_color)
    page_text = f"стр. {page_idx + 1} / {len(CATEGORY_ORDER)}"; pw = _tw(d, page_text, _font(12))
    d.text(((rpx1 + rpx2 - pw) // 2, grid_bottom + 6), page_text, font=_font(12), fill=DIM)
    buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf


# ============================================================
# БЛОК 6: ACHIEVEMENTS VIEWS (UI достижений)
# ============================================================
BTN_LABEL_TOTAL = 29

def _btn_labels_total_ach(labels, total=BTN_LABEL_TOTAL):
    base = sum(len(s) for s in labels); extra = max(0, total - base); n = len(labels)
    if n == 0: return labels
    per = extra // n; rem = extra % n; result = []
    for i, s in enumerate(labels):
        pad = per + (1 if i < rem else 0); left = pad // 2; right = pad - left
        result.append(f"{P * left}{s}{P * right}")
    return result

_L_BACK_ACH, _L_FWD_ACH = _btn_labels_total_ach(["Назад", "Вперёд"])
EMOJI_BACK_ACH = PartialEmoji(name="baa1", id=1557224983539749004)
EMOJI_FWD_ACH  = PartialEmoji(name="rid1", id=1557225020265332816)

async def _catchup_for_user(user_id: int):
    try:
        dc = get_dc_cache(user_id); bal = dc.get("balance", 0) or 0
        if bal > 0: await check_and_unlock(user_id, "balance", value=bal)
        if dc.get("purchases"): await check_and_unlock(user_id, "first_purchase", value=1)
    except Exception as e: logger.debug(f"catchup balance {user_id}: {e}")
    try:
        counts = load_json(FILES["review_counts"], {}); rc = int(counts.get(str(user_id), 0) or 0)
        if rc > 0:
            await check_and_unlock(user_id, "reviews", value=rc)
            await check_and_unlock(user_id, "buyer_count", value=rc)
            await check_and_unlock(user_id, "first_review", value=1)
    except Exception as e: logger.debug(f"catchup reviews {user_id}: {e}")
    try:
        from clan.core import get_user_clan, get_user_contribution
        if get_user_clan(user_id): await check_and_unlock(user_id, "clan_deposit", value=get_user_contribution(user_id))
    except Exception as e: logger.debug(f"catchup clan {user_id}: {e}")
    try:
        st = load_roulette_stats(); rolls = int(st.get("rolls", 0) or 0)
        if rolls > 0: await check_and_unlock(user_id, "casino_games", value=rolls)
    except Exception as e: logger.debug(f"catchup casino {user_id}: {e}")
    try:
        row = cur.execute("SELECT COUNT(*) AS c FROM quest_progress WHERE user_id=? AND completed_at IS NOT NULL", (user_id,)).fetchone()
        qc = row["c"] if row else 0
        if qc > 0: await check_and_unlock(user_id, "quests", value=qc)
    except Exception as e: logger.debug(f"catchup quests {user_id}: {e}")

async def render_category(inter: disnake.MessageInteraction, category_key: str):
    if category_key not in CATEGORY_ORDER: category_key = CATEGORY_ORDER[0]
    try: await _catchup_for_user(inter.author.id)
    except Exception as e: logger.warning(f"ach catchup: {e}")
    try:
        buf = await asyncio.to_thread(generate_achievements_panel, inter.author.id, category_key)
        fname = f"ach_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
        file = disnake.File(buf, filename=fname)
        embed = disnake.Embed(color=6776679); embed.set_image(url=f"attachment://{fname}")
        view = AchievementsPanelView(category_key)
        kwargs = dict(embed=embed, file=file, attachments=[], view=view)
        if inter.response.is_done(): await inter.edit_original_response(**kwargs)
        else: await inter.response.edit_message(**kwargs)
    except Exception as e:
        logger.exception(f"render_category: {e}")
        try:
            if inter.response.is_done(): await inter.followup.send(f"❌ {str(e)[:200]}", ephemeral=True)
            else: await inter.response.send_message(f"❌ {str(e)[:200]}", ephemeral=True)
        except Exception: pass

async def _return_to_profile(inter: disnake.MessageInteraction):
    try:
        from modules.commands_profile import render_profile_into_interaction, ProfileCardView
        await render_profile_into_interaction(inter, inter.author, ProfileCardView())
    except Exception as e: logger.exception(f"_return_to_profile: {e}")

class AchievementsPanelView(View):
    def __init__(self, category_key: str = "base"):
        super().__init__(timeout=300); self.category_key = category_key
        idx = CATEGORY_ORDER.index(category_key) if category_key in CATEGORY_ORDER else 0
        self._idx = idx
        b_back = Button(label=_L_BACK_ACH, style=ButtonStyle.gray, custom_id="ach_panel:back", emoji=EMOJI_BACK_ACH, row=0); b_back.callback = self._on_back; self.add_item(b_back)
        b_fwd = Button(label=_L_FWD_ACH, style=ButtonStyle.gray, custom_id="ach_panel:fwd", emoji=EMOJI_FWD_ACH, row=0); b_fwd.callback = self._on_fwd; self.add_item(b_fwd)
    async def _on_back(self, inter: disnake.MessageInteraction):
        try: await inter.response.defer(ephemeral=True)
        except Exception: pass
        if self._idx <= 0: await _return_to_profile(inter); return
        await render_category(inter, CATEGORY_ORDER[self._idx - 1])
    async def _on_fwd(self, inter: disnake.MessageInteraction):
        try: await inter.response.defer(ephemeral=True)
        except Exception: pass
        new_key = CATEGORY_ORDER[0] if self._idx >= len(CATEGORY_ORDER) - 1 else CATEGORY_ORDER[self._idx + 1]
        await render_category(inter, new_key)
