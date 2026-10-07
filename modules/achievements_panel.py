# -*- coding: utf-8 -*-
"""
Pillow-рендер панели достижений.
1800×1000. Одна страница = одна категория. 6 карточек в сетке 3×2.
Левая панель: счётчик + список категорий с прогрессом.
Правая панель: заголовок + 6 карточек + индикатор страницы.
"""
import io
import os
from typing import List, Dict, Set

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, logger
from clan.achievements import (
    ACHIEVEMENTS, CATEGORIES, CATEGORY_KEYS, CATEGORY_ORDER,
    get_category_progress, get_overall_progress,
)


# ============================================================
# ШРИФТЫ
# ============================================================
FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_FONT_CACHE, _FA_CACHE = {}, {}


def _font(size):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        f = ImageFont.truetype(FONT_BOLD, size)
    except Exception:
        f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


def _fa(size):
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
INNER_BG  = (15, 15, 20)
INNER_BRD = (36, 36, 42)
TEXT      = (255, 255, 255)
TEXT_SOFT = (232, 232, 236)
MUTED     = (136, 136, 136)
DIM       = (102, 102, 102)

SILVER = (198, 208, 224)
GOLD   = (247, 201, 145)
GREEN  = (46, 204, 113)
RED    = (255, 107, 107)
BLUE   = (106, 155, 209)
PURPLE = (179, 157, 219)
ORANGE = (224, 140, 90)
STEEL  = (150, 180, 220)

CARD_BRD = (74, 74, 79)

# Цвета категорий (по ключу из CATEGORIES[i]["color"])
CATEGORY_COLORS = {
    "green":  GREEN,
    "silver": SILVER,
    "gold":   GOLD,
    "blue":   BLUE,
    "purple": PURPLE,
    "red":    RED,
    "orange": ORANGE,
    "steel":  STEEL,
}


# ============================================================
# FA-ИКОНКИ
# ============================================================
I_GEM=0xf3a5;        I_TROPHY=0xf091;   I_LOCK=0xf023
I_CHECK=0xf00c;      I_STAR=0xf005;     I_CROWN=0xf521
I_MEDAL=0xf5a2;      I_AWARD=0xf559;    I_SEEDLING=0xf4d8
I_COMMENT=0xf075;    I_MIC=0xf130;      I_PENF=0xf5ac
I_CART=0xf07a;       I_BAG=0xf290;      I_BRIEF=0xf0b1
I_DIA=0xf219;        I_SACK=0xf81d;     I_COINS=0xf51e
I_MONEY=0xf53a;      I_GIFT=0xf06b;     I_CHART=0xf201
I_BANK=0xf19c;       I_COMMS=0xf086;    I_BULL=0xf0a1
I_FIRE=0xf06d;       I_HEADPH=0xf025;   I_SCROLL=0xf70e
I_HANDD=0xf4c0;      I_SHIELD=0xf3ed;   I_SPADE=0xf2f4
I_DICE=0xf522;       I_DICE5=0xf523;    I_DICE6=0xf526
I_MONEY2=0xf53b;     I_LIST=0xf03a;     I_LISTC=0xf0ae
I_TICKET=0xf145;     I_CALC=0xf274;     I_ELL=0xf141


FA_MAP = {
    "fa-crown": I_CROWN, "fa-medal": I_MEDAL, "fa-award": I_AWARD,
    "fa-star": I_STAR, "fa-seedling": I_SEEDLING, "fa-comment": I_COMMENT,
    "fa-microphone": I_MIC, "fa-pen-fancy": I_PENF, "fa-cart-shopping": I_CART,
    "fa-gem": I_GEM, "fa-diamond": I_DIA, "fa-bag-shopping": I_BAG,
    "fa-briefcase": I_BRIEF, "fa-trophy": I_TROPHY, "fa-sack-dollar": I_SACK,
    "fa-coins": I_COINS, "fa-money-bill-wave": I_MONEY, "fa-gift": I_GIFT,
    "fa-chart-line": I_CHART, "fa-building-columns": I_BANK,
    "fa-comments": I_COMMS, "fa-bullhorn": I_BULL, "fa-fire": I_FIRE,
    "fa-headphones": I_HEADPH, "fa-scroll": I_SCROLL,
    "fa-hand-holding-dollar": I_HANDD, "fa-shield-halved": I_SHIELD,
    "fa-spade": I_SPADE, "fa-dice": I_DICE, "fa-dice-five": I_DICE5,
    "fa-dice-six": I_DICE6, "fa-money-bill-1-wave": I_MONEY2,
    "fa-check": I_CHECK, "fa-list": I_LIST, "fa-list-check": I_LISTC,
    "fa-ticket": I_TICKET, "fa-calendar-check": I_CALC,
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


def _wrap(d, text, font, max_w, max_lines=2):
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
                    return lines
            cur = w
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines or [""]


def _icon(d, cx, cy, code, size, color):
    f = _fa(size)
    if f is None:
        return
    try:
        d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception:
        pass


def _alpha(base, box, color, alpha=30, radius=0):
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


def _grad(base, box, c1, c2, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i in range(w):
        t = i / max(w - 1, 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        ld.line([(i, 0), (i, h)], fill=(r, g, b, alpha))
    if radius > 0:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1),
                                                radius=radius, fill=255)
        a = layer.split()[3]
        a = Image.composite(a, Image.new("L", (w, h), 0), mask)
        layer.putalpha(a)
    base.paste(layer, (x1, y1), layer)


def _stack_panel(base, d, box, radius=22):
    x1, y1, x2, y2 = box
    _alpha(base, (x1 + 12, y1 + 12, x2 + 12, y2 + 12),
           (46, 46, 52), alpha=110, radius=radius)
    _alpha(base, (x1 + 6, y1 + 6, x2 + 6, y2 + 6),
           (46, 46, 52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=2)


def _dashed(d, box, radius, color, dash=8, gap=6, width=2):
    x1, y1, x2, y2 = box
    r = radius

    def dl(p1, p2):
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        L = (dx * dx + dy * dy) ** 0.5
        if L == 0:
            return
        ux, uy = dx / L, dy / L
        pos = 0.0
        while pos < L:
            e = min(pos + dash, L)
            d.line([(p1[0] + ux * pos, p1[1] + uy * pos),
                    (p1[0] + ux * e, p1[1] + uy * e)], fill=color, width=width)
            pos = e + gap

    dl((x1 + r, y1), (x2 - r, y1))
    dl((x2 - r, y2), (x1 + r, y2))
    dl((x1, y1 + r), (x1, y2 - r))
    dl((x2, y1 + r), (x2, y2 - r))
    d.arc((x1, y1, x1 + 2 * r, y1 + 2 * r), 180, 270, fill=color, width=width)
    d.arc((x2 - 2 * r, y1, x2, y1 + 2 * r), 270, 360, fill=color, width=width)
    d.arc((x1, y2 - 2 * r, x1 + 2 * r, y2), 90, 180, fill=color, width=width)
    d.arc((x2 - 2 * r, y2 - 2 * r, x2, y2), 0, 90, fill=color, width=width)


def _lighten(c, a=0.4):
    a = max(0, min(1, a))
    return (
        min(int(c[0] + (255 - c[0]) * a), 255),
        min(int(c[1] + (255 - c[1]) * a), 255),
        min(int(c[2] + (255 - c[2]) * a), 255),
    )


# ============================================================
# КАРКАС
# ============================================================
CANVAS_W, CANVAS_H = 1800, 1000
PAD_X, PAD_Y = 56, 44


def _base_canvas(user_id):
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, CANVAS_W - 1, CANVAS_H - 1), radius=30,
                        fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)

    hx, hy = PAD_X, PAD_Y
    d.rounded_rectangle((hx, hy, hx + 54, hy + 54), radius=14, fill=(58, 58, 64) + (255,))
    _icon(d, hx + 27, hy + 28, I_TROPHY, 26, GOLD)

    bx = hx + 54 + 18
    d.text((bx, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx + 2, hy + 38), "SHOP & ECOSYSTEM", font=_font(11), fill=MUTED)

    meta_r = CANVAS_W - PAD_X
    lbl = "ДОСТИЖЕНИЯ"
    uid = f"#{user_id}"
    w1 = _tw(d, lbl, _font(11))
    w2 = _tw(d, uid, _font(20))
    d.text((meta_r - w1, hy + 12), lbl, font=_font(11), fill=MUTED)
    d.text((meta_r - w2, hy + 32), uid, font=_font(20), fill=TEXT)

    sy = hy + 54 + 16
    d.line((PAD_X, sy, CANVAS_W - PAD_X, sy), fill=STACK_HDR + (255,), width=2)

    return img, d


# ============================================================
# ЛЕВАЯ ПАНЕЛЬ
# ============================================================
def _draw_left_panel(img, d, box, user_id, active_key):
    _stack_panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 22

    overall = get_overall_progress(user_id)
    total_unlocked = overall["unlocked"]
    total_all = overall["total"]

    # Счётчик
    tot_y1 = y1 + pad
    tot_y2 = tot_y1 + 150
    tx1, tx2 = x1 + pad, x2 - pad

    _grad(img, (tx1, tot_y1, tx2, tot_y2), GOLD, GOLD, alpha=22, radius=16)
    d.rounded_rectangle((tx1, tot_y1, tx2, tot_y2), radius=16,
                        outline=GOLD + (200,), width=2)

    ic_size = 46
    ib_x = (tx1 + tx2) // 2 - ic_size // 2
    ib_y = tot_y1 + 16
    _alpha(img, (ib_x, ib_y, ib_x + ic_size, ib_y + ic_size), GOLD, alpha=70, radius=12)
    d.rounded_rectangle((ib_x, ib_y, ib_x + ic_size, ib_y + ic_size),
                        radius=12, outline=GOLD + (230,), width=2)
    _icon(d, ib_x + ic_size // 2, ib_y + ic_size // 2 + 1, I_TROPHY, 22, GOLD)

    d.text(((tx1 + tx2) // 2, tot_y1 + 74), "ОТКРЫТО",
           font=_font(11), fill=MUTED, anchor="mm")

    vw = _tw(d, str(total_unlocked), _font(46))
    ow = _tw(d, f" / {total_all}", _font(20))
    sx = (tx1 + tx2 - vw - ow) // 2
    d.text((sx, tot_y1 + 92), str(total_unlocked), font=_font(46), fill=GOLD)
    d.text((sx + vw + 4, tot_y1 + 92 + 22), f" / {total_all}",
           font=_font(20), fill=DIM)

    # Список категорий
    tt_y = tot_y2 + 18
    d.text((x1 + pad, tt_y), "КАТЕГОРИИ", font=_font(11), fill=MUTED)

    list_y = tt_y + 24
    list_bottom = y2 - pad
    n = len(CATEGORIES)
    gap = 6
    rh = (list_bottom - list_y - gap * (n - 1)) // n
    rh = max(rh, 44)

    progress = get_category_progress(user_id)

    for i, cat in enumerate(CATEGORIES):
        cy = list_y + i * (rh + gap)
        _draw_cat_row(img, d, x1 + pad, cy, (x2 - pad) - (x1 + pad), rh,
                      cat, progress.get(cat["key"], {}), cat["key"] == active_key)


def _draw_cat_row(img, d, x, y, w, h, cat, prog, active):
    color = CATEGORY_COLORS.get(cat["color"], SILVER)
    is_act = active
    cnt = prog.get("unlocked", 0)
    total = prog.get("total", 0)

    if is_act:
        _grad(img, (x, y, x + w, y + h), color, color, alpha=28, radius=12)
        d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                            outline=color + (220,), width=2)
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)

    ic_size = 34
    ib_x = x + 10
    ib_y = y + (h - ic_size) // 2
    _alpha(img, (ib_x, ib_y, ib_x + ic_size, ib_y + ic_size), color, alpha=55, radius=9)

    fa = FA_MAP.get(cat.get("icon", "fa-star"), I_STAR)
    _icon(d, ib_x + ic_size // 2, ib_y + ic_size // 2 + 1, fa, 15, color)

    tx = ib_x + ic_size + 12
    d.text((tx, y + h // 2 - 10), cat["label"], font=_font(14),
           fill=TEXT if is_act else TEXT_SOFT)

    val = f"{cnt} / {total}"
    vf = _font(14)
    vw = _tw(d, val, vf)
    vc = GREEN if cnt == total and total > 0 else (GOLD if cnt > 0 else DIM)
    d.text((x + w - 12 - vw, y + h // 2 - 10), val, font=vf, fill=vc)


# ============================================================
# ПРАВАЯ ПАНЕЛЬ — КАРТОЧКА
# ============================================================
def _draw_ach_card(img, d, x, y, w, h, ach, unlocked, cat_color):
    if ach and unlocked:
        color = cat_color
        border = _lighten(color, 0.15)

        _grad(img, (x, y, x + w, y + h), color, color, alpha=18, radius=16)
        d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                            outline=color + (220,), width=2)

        ic_size = 58
        ib_x = x + 18
        ib_y = y + 18
        _alpha(img, (ib_x, ib_y, ib_x + ic_size, ib_y + ic_size),
               color, alpha=70, radius=14)
        d.rounded_rectangle((ib_x, ib_y, ib_x + ic_size, ib_y + ic_size),
                            radius=14, outline=color + (230,), width=2)

        fa = FA_MAP.get(ach.get("icon", "fa-star"), I_STAR)
        _icon(d, ib_x + ic_size // 2, ib_y + ic_size // 2 + 1, fa, 26, color)

        tx = ib_x + ic_size + 16
        name_f = _font(17)
        name_shown = _ellipsis(d, ach.get("name", "—"), name_f, x + w - 18 - tx)
        d.text((tx, ib_y + ic_size // 2 - 12), name_shown,
               font=name_f, fill=TEXT)

        desc_y = ib_y + ic_size + 14
        for i, line in enumerate(_wrap(d, ach.get("desc", ""),
                                       _font(13), w - 36, 2)):
            d.text((x + 18, desc_y + i * 20), line, font=_font(13), fill=MUTED)

        sy = y + h - 30
        d.line((x + 18, sy - 10, x + w - 18, sy - 10), fill=color + (60,), width=1)
        _icon(d, x + 26, sy + 8, I_CHECK, 13, color)
        d.text((x + 46, sy), "ПОЛУЧЕНО", font=_font(11), fill=color)

    elif ach:
        d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                            fill=INNER_BG + (255,),
                            outline=(42, 42, 48) + (255,), width=2)
        _dashed(d, (x, y, x + w, y + h), 16, (42, 42, 48),
                dash=8, gap=6, width=2)

        ic_size = 58
        ib_x = x + 18
        ib_y = y + 18
        d.rounded_rectangle((ib_x, ib_y, ib_x + ic_size, ib_y + ic_size),
                            radius=14, fill=(26, 26, 32) + (255,))
        _icon(d, ib_x + ic_size // 2, ib_y + ic_size // 2 + 1, I_LOCK, 24, (58, 58, 64))

        tx = ib_x + ic_size + 16
        name_f = _font(17)
        name_shown = _ellipsis(d, ach.get("name", "—"), name_f, x + w - 18 - tx)
        d.text((tx, ib_y + ic_size // 2 - 12), name_shown,
               font=name_f, fill=(90, 90, 96))

        desc_y = ib_y + ic_size + 14
        for i, line in enumerate(_wrap(d, ach.get("desc", ""),
                                       _font(13), w - 36, 2)):
            d.text((x + 18, desc_y + i * 20), line, font=_font(13), fill=(70, 70, 76))

        sy = y + h - 30
        d.line((x + 18, sy - 10, x + w - 18, sy - 10),
               fill=(42, 42, 48) + (255,), width=1)
        d.text((x + 18, sy), "НЕ ПОЛУЧЕНО", font=_font(11), fill=(70, 70, 76))

    else:
        # Пустой слот (не должно быть при 6 картах, но на всякий)
        d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                            fill=(12, 12, 16) + (255,),
                            outline=(28, 28, 34) + (255,), width=2)
        _dashed(d, (x, y, x + w, y + h), 16, (28, 28, 34),
                dash=8, gap=6, width=2)
        _icon(d, x + w // 2, y + h // 2, I_ELL, 26, (46, 46, 52))


# ============================================================
# ГЛАВНАЯ
# ============================================================
def generate_achievements_panel(user_id: int, active_key: str = "base") -> io.BytesIO:
    """
    Рендерит панель достижений для выбранной категории.
    Одна страница = одна категория, 6 карточек, сетка 3×2.
    """
    if active_key not in CATEGORY_ORDER:
        active_key = CATEGORY_ORDER[0]

    cat = next((c for c in CATEGORIES if c["key"] == active_key), CATEGORIES[0])
    cat_color = CATEGORY_COLORS.get(cat["color"], SILVER)

    unlocked = _get_unlocked_set(user_id)

    img, d = _base_canvas(user_id)

    body_y = 138
    body_h = CANVAS_H - PAD_Y - body_y

    left_w = 448
    gap = 30
    lx1 = PAD_X
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = CANVAS_W - PAD_X

    # Левая панель
    _draw_left_panel(img, d, (lx1, body_y, lx2 - 12, body_y + body_h - 12),
                     user_id, active_key)

    # Правая панель
    _stack_panel(img, d, (rx1, body_y, rx2 - 12, body_y + body_h - 12), radius=22)
    rpx1 = rx1 + 28
    rpx2 = rx2 - 12 - 28
    rpy = body_y + 22

    # Заголовок: иконка категории + название
    fa_head = FA_MAP.get(cat.get("icon", "fa-star"), I_STAR)
    head_icon_size = 42
    d.rounded_rectangle((rpx1, rpy + 2, rpx1 + 6, rpy + 48), radius=3,
                        fill=cat_color + (255,))
    _alpha(img, (rpx1 + 20, rpy, rpx1 + 20 + head_icon_size, rpy + head_icon_size),
           cat_color, alpha=65, radius=11)
    _icon(d, rpx1 + 20 + head_icon_size // 2, rpy + head_icon_size // 2 + 1,
          fa_head, 20, cat_color)

    d.text((rpx1 + 20 + head_icon_size + 16, rpy + 6),
           cat["label"].upper(), font=_font(24), fill=TEXT)

    keys = CATEGORY_KEYS.get(active_key, [])
    cnt = sum(1 for k in keys if k in unlocked)
    total = len(keys)
    page_idx = CATEGORY_ORDER.index(active_key)
    sub = f"страница {page_idx + 1} / {len(CATEGORY_ORDER)} · {cnt} / {total} открыто"
    sw = _tw(d, sub, _font(14))
    d.text((rpx2 - sw, rpy + 12), sub, font=_font(14), fill=MUTED)

    sep_y = rpy + 56
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)

    # Сетка 3×2 = 6 карточек
    grid_y = sep_y + 16
    grid_bottom = body_y + body_h - 12 - 26
    grid_h = grid_bottom - grid_y

    cell_gap = 14
    cols, rows = 3, 2
    cell_w = (rpx2 - rpx1 - cell_gap * (cols - 1)) // cols
    cell_h = (grid_h - cell_gap * (rows - 1)) // rows

    slots = cols * rows  # 6

    for idx in range(slots):
        r = idx // cols
        c = idx % cols
        cx = rpx1 + c * (cell_w + cell_gap)
        cy = grid_y + r * (cell_h + cell_gap)

        if idx < len(keys):
            key = keys[idx]
            ach = ACHIEVEMENTS.get(key)
            _draw_ach_card(img, d, cx, cy, cell_w, cell_h, ach,
                           key in unlocked, cat_color)
        else:
            _draw_ach_card(img, d, cx, cy, cell_w, cell_h, None, False, cat_color)

    # Индикатор страницы снизу
    page_text = f"стр. {page_idx + 1} / {len(CATEGORY_ORDER)}"
    pw = _tw(d, page_text, _font(12))
    d.text(((rpx1 + rpx2 - pw) // 2, grid_bottom + 6), page_text,
           font=_font(12), fill=DIM)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _get_unlocked_set(user_id: int) -> set:
    from clan.achievements import get_user_unlocked_set
    return get_user_unlocked_set(user_id)
