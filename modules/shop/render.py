# -*- coding: utf-8 -*-
"""
Pillow-рендер панели квестов.
3 колонки: Ежедневные / Недельные / Разовые. По 4 квеста в каждой.
Крупные карточки с читаемыми описаниями.
"""
import io
import os
import math
from typing import List, Dict

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR


FONT_BOLD = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_FONT_CACHE: dict = {}
_FA_CACHE: dict = {}


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


# ============================================================
# ПАЛИТРА
# ============================================================
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

SILVER     = (198, 208, 224)
SILVER_HI  = (224, 232, 245)
SILVER_DIM = (120, 132, 155)

GREEN = (46, 204, 113)
RED   = (255, 107, 107)
BLUE  = (106, 155, 209)
PURPLE = (179, 157, 219)

BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)
SILVER_BG = (34, 38, 48)
GREEN_BG  = (18, 44, 28)

CARD_BRD = (74, 74, 79)

EMBED_COLOR = 0x2b2d31

# FA5
I_GEM      = 0xf3a5
I_CLOCK    = 0xf017
I_CALENDAR = 0xf133
I_STAR     = 0xf005
I_CHECK    = 0xf00c
I_COMMENT  = 0xf075
I_MIC      = 0xf130
I_DICE     = 0xf522
I_MOUSE    = 0xf8cc
I_CART     = 0xf07a
I_COMMENTS = 0xf086
I_HEADSET  = 0xf025
I_DICE5    = 0xf523
I_SACK     = 0xf81d
I_TROPHY   = 0xf091
I_GIFT     = 0xf06b
I_FIRE     = 0xf06d
I_CROWN    = 0xf521
I_MONEY    = 0xf53a


FA_MAP = {
    "fa-comment":       I_COMMENT,
    "fa-microphone":    I_MIC,
    "fa-dice":          I_DICE,
    "fa-computer-mouse": I_MOUSE,
    "fa-cart-shopping": I_CART,
    "fa-comments":      I_COMMENTS,
    "fa-headphones":    I_HEADSET,
    "fa-dice-five":     I_DICE5,
    "fa-sack-dollar":   I_SACK,
    "fa-trophy":        I_TROPHY,
    "fa-star":          I_STAR,
    "fa-gift":          I_GIFT,
    "fa-fire":          I_FIRE,
    "fa-crown":         I_CROWN,
    "fa-money-bill-wave": I_MONEY,
}

COL_ICON = {
    "daily":  I_CLOCK,
    "weekly": I_CALENDAR,
    "once":   I_STAR,
}

COL_COLOR = {
    "daily":  BLUE,
    "weekly": SILVER,
    "once":   PURPLE,
}

COL_BG = {
    "daily":  BLUE_BG,
    "weekly": SILVER_BG,
    "once":   PURPLE_BG,
}

COL_TITLE = {
    "daily":  "Ежедневные",
    "weekly": "Недельные",
    "once":   "Разовые",
}

COL_SUB = {
    "daily":  "СБРОС 00:00 МСК",
    "weekly": "СБРОС ПН 00:00 МСК",
    "once":   "НА ВЕСЬ СЕЗОН",
}


# ============================================================
# УТИЛИТЫ
# ============================================================
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
    if w <= 0 or h <= 0:
        return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if radius > 0:
        ld.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=color + (alpha,))
    else:
        ld.rectangle((0, 0, w - 1, h - 1), fill=color + (alpha,))
    base.paste(layer, (x1, y1), layer)


# ============================================================
# КАРКАС
# ============================================================
CANVAS_W, CANVAS_H = 1800, 1000
M = 14
PAD_X = 40
PAD_Y = 40


def _base_canvas(user_id: int):
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (M, M, CANVAS_W - 1 - M, CANVAS_H - 1 - M),
        radius=28, fill=CARD_TOP + (255,),
        outline=CARD_BRD + (255,), width=3,
    )

    hx = PAD_X
    hy = PAD_Y

    logo_size = 64
    d.rounded_rectangle((hx, hy, hx + logo_size, hy + logo_size), radius=16,
                        fill=(58, 58, 64) + (255,))
    _draw_icon(d, hx + logo_size // 2, hy + logo_size // 2 + 1, I_GEM, 30, SILVER_HI)

    brand_x = hx + logo_size + 20
    d.text((brand_x, hy + 4), "DIAMOND", font=_font(34), fill=TEXT)
    d.text((brand_x + 4, hy + 46), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)

    meta_r = CANVAS_W - M - PAD_X
    lbl = "ТВОИ КВЕСТЫ"
    uid = f"UID · {user_id}"
    w1 = _tw(d, lbl, _font(15))
    w2 = _tw(d, uid, _font(24))
    d.text((meta_r - w1, hy + 14), lbl, font=_font(15), fill=MUTED)
    d.text((meta_r - w2, hy + 38), uid, font=_font(24), fill=TEXT)

    sep_y = hy + logo_size + 20
    d.line((PAD_X, sep_y, CANVAS_W - M - PAD_X, sep_y),
           fill=STACK_HDR + (255,), width=2)

    return img, d


# ============================================================
# ГЛАВНАЯ
# ============================================================
def render_quests(user_id: int, quests: List[Dict]) -> io.BytesIO:
    img, d = _base_canvas(user_id)

    # ---- Заголовок секции + общий прогресс ----
    title_y = 130
    d.rounded_rectangle((PAD_X, title_y + 6, PAD_X + 6, title_y + 48),
                        radius=3, fill=SILVER + (255,))
    d.text((PAD_X + 22, title_y), "КВЕСТЫ КЛУБА", font=_font(30), fill=TEXT)
    d.text((PAD_X + 22, title_y + 40),
           "выполняй задания · получай dc в копилку",
           font=_font(15), fill=MUTED)

    total_done = sum(1 for q in quests if q.get("completed"))
    total_all = len(quests) or 1

    meta_r = CANVAS_W - M - PAD_X
    lbl = "ВЫПОЛНЕНО"
    val = f"{total_done} / {total_all}"
    w1 = _tw(d, lbl, _font(15))
    w2 = _tw(d, val, _font(30))
    d.text((meta_r - w1, title_y + 8), lbl, font=_font(15), fill=MUTED)
    d.text((meta_r - w2, title_y + 30), val, font=_font(30), fill=SILVER_HI)

    d.line((PAD_X, title_y + 60, CANVAS_W - M - PAD_X, title_y + 60),
           fill=STACK_HDR + (255,), width=2)

    # ---- 3 колонки ----
    body_y = title_y + 76
    body_h = CANVAS_H - M - PAD_Y - body_y - 40

    gap = 16
    col_w = (CANVAS_W - M * 2 - PAD_X * 2 - gap * 2) // 3

    buckets = {"daily": [], "weekly": [], "once": []}
    for q in quests:
        t = q.get("type", "daily")
        if t in buckets:
            buckets[t].append(q)

    for idx, t in enumerate(["daily", "weekly", "once"]):
        x1 = PAD_X + idx * (col_w + gap)
        x2 = x1 + col_w
        _draw_column(d, img, x1, body_y, col_w, body_h, t, buckets[t])

    # ---- Футер ----
    foot_y = CANVAS_H - M - PAD_Y + 4
    d.line((PAD_X, foot_y - 10, CANVAS_W - M - PAD_X, foot_y - 10),
           fill=STACK_HDR + (255,), width=2)
    d.text((PAD_X, foot_y),
           "Квесты сбрасываются автоматически · daily 00:00 МСК · weekly пн 00:00 МСК",
           font=_font(13), fill=DIM)

    right_txt = "НАГРАДА ИДЁТ В КОПИЛКУ КЛАНА"
    rw = _tw(d, right_txt, _font(13))
    d.text((CANVAS_W - M - PAD_X - rw, foot_y), right_txt, font=_font(13),
           fill=SILVER)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# КОЛОНКА
# ============================================================
def _draw_column(d, img, x, y, w, h, kind: str, quests: List[Dict]):
    color = COL_COLOR[kind]

    d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                        fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=2)

    pad = 16

    # ---- Заголовок колонки ----
    head_h = 68
    icon_size = 44
    ix = x + pad
    iy = y + pad

    _alpha_fill(img, (ix, iy, ix + icon_size, iy + icon_size), color, alpha=50, radius=12)
    _draw_icon(d, ix + icon_size // 2, iy + icon_size // 2 + 1,
               COL_ICON[kind], 22, color)

    d.text((ix + icon_size + 14, iy + 2),
           COL_TITLE[kind].upper(), font=_font(20), fill=TEXT)
    d.text((ix + icon_size + 14, iy + 26),
           COL_SUB[kind], font=_font(11), fill=MUTED)

    d.line((x + pad, y + pad + head_h - 10, x + w - pad, y + pad + head_h - 10),
           fill=STACK_HDR + (255,), width=2)

    # ---- Квесты ----
    q_y = y + pad + head_h
    q_gap = 12

    available = h - pad * 2 - head_h - 4
    n = max(len(quests), 1)
    q_h = (available - q_gap * (n - 1)) // n
    q_h = max(q_h, 90)

    for i, q in enumerate(quests):
        cy = q_y + i * (q_h + q_gap)
        _draw_quest_card(d, img, x + pad, cy, w - pad * 2, q_h, q, kind)


# ============================================================
# КАРТОЧКА КВЕСТА
# ============================================================
def _draw_quest_card(d, img, x, y, w, h, q: Dict, kind: str):
    color = COL_COLOR[kind]
    done = q.get("completed", False)

    if done:
        d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                            fill=GREEN_BG + (255,),
                            outline=GREEN + (150,), width=2)
        accent = GREEN
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)
        accent = color

    pad_x = 16
    pad_y = 14

    # ---- Иконка ----
    ic_size = 46
    ix = x + pad_x
    iy = y + pad_y

    if done:
        _alpha_fill(img, (ix, iy, ix + ic_size, iy + ic_size), GREEN, alpha=50, radius=12)
        _draw_icon(d, ix + ic_size // 2, iy + ic_size // 2 + 1, I_CHECK, 22, GREEN)
    else:
        _alpha_fill(img, (ix, iy, ix + ic_size, iy + ic_size), color, alpha=45, radius=12)
        icon_code = FA_MAP.get(q.get("icon", "fa-star"), I_STAR)
        _draw_icon(d, ix + ic_size // 2, iy + ic_size // 2 + 1, icon_code, 22, color)

    # ---- Награда справа ----
    reward_cut = q.get("reward_cut", q.get("reward", 0))
    rw_txt = f"{reward_cut}"
    rwf = _font(22)
    unit_f = _font(13)
    rw_w = _tw(d, rw_txt, rwf) + _tw(d, " DC", unit_f) + 4

    reward_color = GREEN if done else SILVER_HI
    rw_x = x + w - pad_x - rw_w
    d.text((rw_x, iy + 6), rw_txt, font=rwf, fill=reward_color)
    w1 = _tw(d, rw_txt, rwf)
    d.text((rw_x + w1 + 4, iy + 14), "DC", font=unit_f, fill=reward_color)

    if done:
        cw = _tw(d, "выполнено", _font(11))
        d.text((x + w - pad_x - cw, iy + 34), "выполнено",
               font=_font(11), fill=GREEN)

    # ---- Название ----
    tx = ix + ic_size + 14
    tx_max = rw_x - 10

    name_font = _font(20)
    name = _ellipsis(d, q.get("title", "—"), name_font, tx_max - tx)
    d.text((tx, iy + 2), name, font=name_font,
           fill=GREEN if done else TEXT)

    # ---- Описание ----
    desc_font = _font(14)
    desc = _ellipsis(d, q.get("desc", ""), desc_font, w - pad_x * 2)
    d.text((x + pad_x, iy + ic_size + 12), desc, font=desc_font, fill=MUTED)

    # ---- Прогресс-бар ----
    bar_y = y + h - pad_y - 10
    bar_x1 = x + pad_x
    bar_x2 = x + w - pad_x - 90
    bar_h = 10

    if bar_x2 < bar_x1 + 60:
        bar_x2 = bar_x1 + 60

    d.rounded_rectangle((bar_x1, bar_y, bar_x2, bar_y + bar_h),
                        radius=bar_h // 2, fill=(28, 28, 34) + (255,))

    goal = q.get("goal", 1) or 1
    prog = min(q.get("progress", 0), goal)
    ratio = prog / goal

    fill_w = int((bar_x2 - bar_x1) * ratio)
    if fill_w > 0:
        if done:
            d.rounded_rectangle((bar_x1, bar_y, bar_x1 + fill_w, bar_y + bar_h),
                                radius=bar_h // 2, fill=GREEN + (255,))
        else:
            d.rounded_rectangle((bar_x1, bar_y, bar_x1 + fill_w, bar_y + bar_h),
                                radius=bar_h // 2, fill=color + (255,))

    if done:
        prog_txt = f"{goal} / {goal}"
    else:
        prog_txt = f"{prog} / {goal}"

    if goal >= 1000:
        def shorten(v):
            if v >= 1000:
                return f"{v // 1000}k"
            return str(v)
        prog_txt = f"{shorten(prog)} / {shorten(goal)}"

    pf = _font(12)
    pw = _tw(d, prog_txt, pf)
    d.text((x + w - pad_x - pw, bar_y - 3), prog_txt, font=pf,
           fill=GREEN if done else MUTED)
