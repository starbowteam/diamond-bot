# -*- coding: utf-8 -*-
"""
Pillow-рендер витрины DC-Shop по макету.
Холодное серебро, FA5-иконки, плотная сетка.
"""
import io
import os
import math
from typing import Optional, List, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, logger


# ============================================================
# ШРИФТЫ
# ============================================================
FONT_BOLD = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}
_FA_CACHE:   dict[int, Optional[ImageFont.FreeTypeFont]] = {}


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

SILVER       = (198, 208, 224)
SILVER_HI    = (224, 232, 245)
SILVER_DIM   = (120, 132, 155)
SILVER_BG    = (34, 38, 48)

GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)

GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)

CARD_BRD  = (74, 74, 79)

EMBED_COLOR = 0x2b2d31


# ============================================================
# FA5 ИКОНКИ
# ============================================================
I_GEM        = 0xf3a5
I_STAR       = 0xf005
I_CART       = 0xf07a
I_BULLHORN   = 0xf0a1
I_BOLT       = 0xf0e7
I_GIFT       = 0xf06b
I_DICE       = 0xf522
I_USER       = 0xf007
I_ARROW_L    = 0xf060
I_FIRE       = 0xf06d
I_CHECK      = 0xf00c
I_XMARK      = 0xf00d
I_INFO       = 0xf05a
I_COINS      = 0xf51e
I_BAG        = 0xf290
I_CLOCK      = 0xf017
I_ELLIPSIS   = 0xf141
I_CIRCLE_M   = 0xf056
I_LIST       = 0xf03a
I_TROPHY     = 0xf091
I_HISTORY    = 0xf1da
I_PALETTE    = 0xf53f
I_TICKET     = 0xf145
I_CUBE       = 0xf1b2
I_SHOP       = 0xf54f
I_TAG        = 0xf02b
I_MASKS      = 0xf630
I_IMAGE      = 0xf03e
I_SMILE      = 0xf118
I_PEN_NIB    = 0xf5ad
I_LAYERS     = 0xf5fd
I_CLIPBOARD  = 0xf46d
I_HOURGLASS  = 0xf252
I_SACK       = 0xf81d
I_WALLET     = 0xf555
I_SEARCH     = 0xf002


CATEGORY_FA = {
    "discounts": I_TAG,
    "design":    I_PALETTE,
    "ads":       I_BULLHORN,
    "roles":     I_MASKS,
    "boosts":    I_BOLT,
    "casino":    I_DICE,
    "gifts":     I_GIFT,
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
                    cur = ""
                    break
            cur = w
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines or [""]


def _fmt(n: int) -> str:
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
    if w <= 0 or h <= 0:
        return
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
    if w <= 0 or h <= 0:
        return
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
        alpha_ch = layer.split()[3]
        alpha_ch = Image.composite(alpha_ch, Image.new("L", (w, h), 0), mask)
        layer.putalpha(alpha_ch)
    base.paste(layer, (x1, y1), layer)


def _draw_stack_panel(base, d, box, radius=22):
    x1, y1, x2, y2 = box
    _alpha_fill(base, (x1 + 12, y1 + 12, x2 + 12, y2 + 12),
                (46, 46, 52), alpha=110, radius=radius)
    _alpha_fill(base, (x1 + 6, y1 + 6, x2 + 6, y2 + 6),
                (46, 46, 52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius,
                        fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=2)


def _draw_dashed_rect(d, box, radius, color, dash=8, gap=6, width=2):
    x1, y1, x2, y2 = box
    r = radius

    def dash_line(p1, p2):
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return
        ux, uy = dx / length, dy / length
        pos = 0.0
        while pos < length:
            seg_end = min(pos + dash, length)
            a = (p1[0] + ux * pos, p1[1] + uy * pos)
            b = (p1[0] + ux * seg_end, p1[1] + uy * seg_end)
            d.line([a, b], fill=color, width=width)
            pos = seg_end + gap

    dash_line((x1 + r, y1), (x2 - r, y1))
    dash_line((x2 - r, y2), (x1 + r, y2))
    dash_line((x1, y1 + r), (x1, y2 - r))
    dash_line((x2, y1 + r), (x2, y2 - r))
    d.arc((x1, y1, x1 + 2 * r, y1 + 2 * r), 180, 270, fill=color, width=width)
    d.arc((x2 - 2 * r, y1, x2, y1 + 2 * r), 270, 360, fill=color, width=width)
    d.arc((x1, y2 - 2 * r, x1 + 2 * r, y2), 90, 180, fill=color, width=width)
    d.arc((x2 - 2 * r, y2 - 2 * r, x2, y2), 0, 90, fill=color, width=width)


# ============================================================
# КАРКАС
# ============================================================
CANVAS_W, CANVAS_H = 1800, 1000
M = 14
PAD_X = 40
PAD_Y = 40


def _base_canvas(user_id: int, uid_label: str):
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (M, M, CANVAS_W - 1 - M, CANVAS_H - 1 - M),
        radius=26, fill=CARD_TOP + (255,),
        outline=CARD_BRD + (255,), width=3,
    )

    hx = PAD_X
    hy = PAD_Y

    logo_size = 60
    d.rounded_rectangle((hx, hy, hx + logo_size, hy + logo_size), radius=16,
                        fill=(58, 58, 64) + (255,))
    _draw_icon(d, hx + logo_size // 2, hy + logo_size // 2 + 1, I_GEM, 28, SILVER_HI)

    brand_x = hx + logo_size + 18
    d.text((brand_x, hy + 4), "DIAMOND", font=_font(30), fill=TEXT)
    d.text((brand_x + 2, hy + 42), "SHOP & ECOSYSTEM", font=_font(13), fill=MUTED)

    meta_r = CANVAS_W - M - PAD_X
    lbl = uid_label.upper()
    uid = f"UID · {user_id}"
    w1 = _tw(d, lbl, _font(13))
    w2 = _tw(d, uid, _font(22))
    d.text((meta_r - w1, hy + 12), lbl, font=_font(13), fill=MUTED)
    d.text((meta_r - w2, hy + 34), uid, font=_font(22), fill=TEXT)

    sep_y = hy + logo_size + 18
    d.line((PAD_X, sep_y, CANVAS_W - M - PAD_X, sep_y),
           fill=STACK_HDR + (255,), width=2)

    return img, d


def _draw_footer(d, left_text: str, page: str):
    y = CANVAS_H - M - PAD_Y + 4
    d.line((PAD_X, y - 10, CANVAS_W - M - PAD_X, y - 10),
           fill=STACK_HDR + (255,), width=2)
    _draw_icon(d, PAD_X + 10, y + 8, I_INFO, 14, DIM)
    d.text((PAD_X + 32, y), left_text, font=_font(13), fill=DIM)
    pw = _tw(d, page, _font(13))
    d.text((CANVAS_W - M - PAD_X - pw, y), page, font=_font(13), fill=DIM)


# ============================================================
# ЛЕВАЯ ПАНЕЛЬ
# ============================================================
def _draw_left_panel(img, d, box, user_id, balance, total_spent,
                     extra_blocks: List[Dict] = None):
    _draw_stack_panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 26

    # Баланс
    bal_icon_size = 72
    ib_x = x1 + pad
    ib_y = y1 + pad

    _gradient_box(img, (ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                  SILVER, SILVER_DIM, alpha=42, radius=20)
    d.rounded_rectangle((ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                        radius=20, outline=SILVER + (140,), width=2)
    _draw_icon(d, ib_x + bal_icon_size // 2, ib_y + bal_icon_size // 2 + 1,
               I_GEM, 30, SILVER_HI)

    lbl_x = ib_x + bal_icon_size + 18
    d.text((lbl_x, ib_y + 4), "ТВОЙ БАЛАНС", font=_font(12), fill=MUTED)

    bal_str = _fmt(balance)
    val_font = _font(40)
    max_w = x2 - pad - lbl_x - 16
    while _tw(d, bal_str + " DC", val_font) > max_w and val_font.size > 22:
        val_font = _font(val_font.size - 2)
    d.text((lbl_x, ib_y + 26), bal_str, font=val_font, fill=TEXT)
    bw = _tw(d, bal_str, val_font)
    d.text((lbl_x + bw + 5, ib_y + 26 + val_font.size - 22),
           "DC", font=_font(18), fill=SILVER)

    sep_y = ib_y + bal_icon_size + 24
    d.line((x1 + pad, sep_y, x2 - pad, sep_y),
           fill=STACK_HDR + (255,), width=2)

    # Всего потрачено
    sp_icon_size = 58
    sp_x = x1 + pad
    sp_y = sep_y + 24
    _gradient_box(img, (sp_x, sp_y, sp_x + sp_icon_size, sp_y + sp_icon_size),
                  GREEN, GREEN, alpha=26, radius=16)
    d.rounded_rectangle((sp_x, sp_y, sp_x + sp_icon_size, sp_y + sp_icon_size),
                        radius=16, outline=GREEN + (100,), width=2)
    _draw_icon(d, sp_x + sp_icon_size // 2, sp_y + sp_icon_size // 2 + 1,
               I_COINS, 24, GREEN)

    sp_lbl_x = sp_x + sp_icon_size + 16
    d.text((sp_lbl_x, sp_y + 4), "ВСЕГО ПОТРАЧЕНО", font=_font(12), fill=MUTED)
    sp_str = f"{_fmt(total_spent)} DC"
    sp_font = _font(22)
    while _tw(d, sp_str, sp_font) > x2 - pad - sp_lbl_x - 10 and sp_font.size > 14:
        sp_font = _font(sp_font.size - 2)
    d.text((sp_lbl_x, sp_y + 26), sp_str, font=sp_font, fill=GREEN)

    # Нижние блоки
    if extra_blocks:
        bb_h = 84
        bb_gap = 10
        bottom_y = y2 - pad - bb_h

        for i, blk in enumerate(reversed(extra_blocks)):
            by1 = bottom_y - i * (bb_h + bb_gap)
            by2 = by1 + bb_h
            bx1 = x1 + pad
            bx2 = x2 - pad

            bcolor = blk.get("color", SILVER)
            _gradient_box(img, (bx1, by1, bx2, by2),
                          bcolor, bcolor, alpha=18, radius=14)
            d.rounded_rectangle((bx1, by1, bx2, by2),
                                radius=14, outline=bcolor + (150,), width=2)

            icon_size = 46
            ib2_x = bx1 + 14
            ib2_y = by1 + (bb_h - icon_size) // 2
            _alpha_fill(img, (ib2_x, ib2_y, ib2_x + icon_size, ib2_y + icon_size),
                        bcolor, alpha=50, radius=12)
            _draw_icon(d, ib2_x + icon_size // 2, ib2_y + icon_size // 2 + 1,
                       blk.get("icon", I_CIRCLE_M), 22, bcolor)

            tx = ib2_x + icon_size + 14
            d.text((tx, by1 + 14), blk.get("label", "").upper(),
                   font=_font(11), fill=bcolor)
            bv = blk.get("value", "—")
            val_font = _font(18)
            max_w2 = bx2 - 16 - tx
            bv_shown = _ellipsis(d, bv, val_font, max_w2)
            d.text((tx, by1 + 38), bv_shown, font=val_font, fill=bcolor)


# ============================================================
# ПРАВЫЙ ЗАГОЛОВОК
# ============================================================
def _draw_right_head(d, x1, y1, x2, title: str, sub: str):
    d.rounded_rectangle((x1, y1 + 4, x1 + 5, y1 + 44), radius=3,
                        fill=SILVER + (255,))
    d.text((x1 + 18, y1 + 2), title.upper(), font=_font(26), fill=TEXT)
    sub_w = _tw(d, sub.upper(), _font(13))
    d.text((x2 - sub_w, y1 + 16), sub.upper(), font=_font(13), fill=MUTED)
    d.line((x1, y1 + 58, x2, y1 + 58), fill=STACK_HDR + (255,), width=2)


# ============================================================
# ПЛИТКА КАТЕГОРИИ
# ============================================================
def _draw_category_tile(d, img, x, y, w, h,
                        cat_key, label, count, min_price, description,
                        active=False):
    if active:
        _gradient_box(img, (x, y, x + w, y + h), SILVER, SILVER_DIM, alpha=18, radius=18)
        d.rounded_rectangle((x, y, x + w, y + h), radius=18,
                            outline=SILVER + (200,), width=2)
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=18,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)

    pad = 20
    icon_size = 60
    ib_x = x + pad
    ib_y = y + pad

    icon_code = CATEGORY_FA.get(cat_key, I_CUBE)
    if active:
        _gradient_box(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                      SILVER, SILVER_DIM, alpha=60, radius=14)
        d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                            radius=14, outline=SILVER + (180,), width=2)
        _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
                   icon_code, 28, SILVER_HI)
    else:
        _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                    SILVER, alpha=25, radius=14)
        d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                            radius=14, outline=SILVER + (100,), width=2)
        _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
                   icon_code, 28, SILVER)

    name_x = ib_x + icon_size + 14
    name_w = w - (name_x - x) - pad
    name_font = _font(22)
    name_shown = _ellipsis(d, label, name_font, name_w)
    d.text((name_x, ib_y + 4), name_shown, font=name_font,
           fill=SILVER_HI if active else TEXT)

    cnt_str = f"{count} {'товар' if count == 1 else 'товара' if 2 <= count <= 4 else 'товаров'}"
    d.text((name_x, ib_y + 32), cnt_str, font=_font(13), fill=MUTED)

    desc_y = ib_y + icon_size + 18
    desc_font = _font(14)
    max_desc_w = w - pad * 2
    lines = _wrap(d, description or "Категория товаров", desc_font, max_desc_w, max_lines=4)
    for i, line in enumerate(lines):
        d.text((x + pad, desc_y + i * 20), line, font=desc_font, fill=MUTED)

    foot_y = y + h - 38
    d.line((x + pad, foot_y - 10, x + w - pad, foot_y - 10),
           fill=INNER_BRD + (255,), width=1)

    if min_price > 0:
        d.text((x + pad, foot_y), "от", font=_font(13), fill=DIM)
        w_ot = _tw(d, "от ", _font(13))
        price_str = _fmt(min_price)
        pf = _font(22)
        d.text((x + pad + w_ot + 4, foot_y - 5), price_str, font=pf,
               fill=SILVER_HI if active else SILVER)
        pw = _tw(d, price_str, pf)
        d.text((x + pad + w_ot + pw + 6, foot_y + 1), "DC", font=_font(12), fill=SILVER)
    else:
        d.text((x + pad, foot_y), "Пусто", font=_font(13), fill=DIM)

    _draw_icon(d, x + w - pad - 8, foot_y + 8, I_ARROW_L, 14, DIM)


# ============================================================
# ПЛИТКА ТОВАРА
# ============================================================
def _draw_item_tile(d, img, x, y, w, h, item, balance, active=False):
    pad = 20

    if active:
        _gradient_box(img, (x, y, x + w, y + h), SILVER, SILVER_DIM, alpha=14, radius=18)
        d.rounded_rectangle((x, y, x + w, y + h), radius=18,
                            outline=SILVER + (180,), width=2)
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=18,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)

    icon_size = 64
    ib_x = x + pad
    ib_y = y + pad

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                SILVER, alpha=25, radius=16)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=16, outline=SILVER + (110,), width=2)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               item.get("fa", I_CUBE), 30, SILVER)

    name_x = ib_x + icon_size + 16
    name_w = w - (name_x - x) - pad
    name_font = _font(21)
    name_shown = _ellipsis(d, item["name"], name_font, name_w)
    d.text((name_x, ib_y + 8), name_shown, font=name_font, fill=TEXT)

    desc_y = ib_y + icon_size + 18
    desc_font = _font(14)
    max_w = w - pad * 2
    desc = item.get("description") or "Описание товара появится здесь."
    lines = _wrap(d, desc, desc_font, max_w, max_lines=3)
    for i, line in enumerate(lines):
        d.text((x + pad, desc_y + i * 20), line, font=desc_font, fill=MUTED)

    foot_y = y + h - 46
    d.line((x + pad, foot_y - 10, x + w - pad, foot_y - 10),
           fill=INNER_BRD + (255,), width=1)

    price = item["price"]
    price_str = f"{_fmt(price)}"
    pf = _font(30)
    d.text((x + pad, foot_y + 2), price_str, font=pf, fill=SILVER_HI)
    pw = _tw(d, price_str, pf)
    d.text((x + pad + pw + 6, foot_y + 2 + pf.size - 20),
           "DC", font=_font(14), fill=SILVER)

    can_afford = balance >= price
    badge_text = "КУПИТЬ" if can_afford else "НЕ ХВАТАЕТ"
    badge_color = GREEN if can_afford else RED
    badge_bg = GREEN_BG if can_afford else RED_BG
    bf = _font(11)
    btw = _tw(d, badge_text, bf)
    bpad = 12
    bx = x + w - pad - btw - bpad * 2
    by = foot_y + 8
    d.rounded_rectangle((bx, by, bx + btw + bpad * 2, by + 26),
                        radius=7, fill=badge_bg + (255,),
                        outline=badge_color + (180,), width=1)
    d.text((bx + bpad, by + 7), badge_text, font=bf, fill=badge_color)


# ============================================================
# СТРОКА ОПЕРАЦИИ (история)
# ============================================================
def _draw_operation_row(d, img, x, y, w, h, op):
    d.rounded_rectangle((x, y, x + w, y + h), radius=14,
                        fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)

    if not op:
        _draw_icon(d, x + 48, y + h // 2, I_CIRCLE_M, 20, DARK)
        d.text((x + 80, y + h // 2), "—", font=_font(16),
               fill=DARK, anchor="lm")
        return

    amt = op.get("amount", 0)
    reason = (op.get("reason", "") or "—")[:90]
    is_plus = amt >= 0
    accent = GREEN if is_plus else RED
    sign = "+" if is_plus else "−"

    d.rounded_rectangle((x, y, x + 5, y + h), radius=5, fill=accent + (255,))

    op_icon_size = 44
    ib_x = x + 20
    ib_y = y + (h - op_icon_size) // 2
    _alpha_fill(img, (ib_x, ib_y, ib_x + op_icon_size, ib_y + op_icon_size),
                accent, alpha=40, radius=12)
    _draw_icon(d, ib_x + op_icon_size // 2, ib_y + op_icon_size // 2 + 1,
               I_CART, 19, accent)

    tx = ib_x + op_icon_size + 16
    name_f = _font(16)
    time_f = _font(11)

    amt_str = f"{sign}{abs(int(amt))} DC"
    amt_f = _font(22)
    amt_w = _tw(d, amt_str, amt_f)
    rx = x + w - 24 - amt_w

    max_name_w = rx - 20 - tx
    name_shown = _ellipsis(d, reason, name_f, max_name_w)
    name_y = y + h // 2 - 16
    d.text((tx, name_y), name_shown, font=name_f, fill=TEXT_SOFT)

    try:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(op.get("date", 0), timezone.utc)
        now = datetime.now(timezone.utc)
        if dt.date() == now.date():
            time_str = f"Сегодня · {dt.strftime('%H:%M')}"
        elif (now.date() - dt.date()).days == 1:
            time_str = f"Вчера · {dt.strftime('%H:%M')}"
        else:
            time_str = dt.strftime("%d.%m.%Y · %H:%M")
    except Exception:
        time_str = "—"
    d.text((tx, name_y + 22), time_str.upper(), font=time_f, fill=DIM)

    d.text((rx, y + h // 2 - 14), amt_str, font=amt_f, fill=accent)


# ============================================================
# СТРОКА ПОКУПКИ
# ============================================================
def _draw_purchase_row(d, img, x, y, w, h, p):
    d.rounded_rectangle((x, y, x + w, y + h), radius=14,
                        fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)

    icon_size = 44
    ib_x = x + 20
    ib_y = y + (h - icon_size) // 2
    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                SILVER, alpha=32, radius=12)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               I_TICKET, 19, SILVER)

    ptype = p.get("type", "—")
    pval = p.get("value", "—")
    tx = ib_x + icon_size + 16
    max_w = w - (tx - x) - 240
    name_shown = _ellipsis(d, pval, _font(17), max_w)
    d.text((tx, y + h // 2 - 16), name_shown, font=_font(17), fill=TEXT)

    try:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(p.get("date", 0), timezone.utc)
        date_str = dt.strftime("%d.%m.%Y · %H:%M")
    except Exception:
        date_str = "—"
    d.text((tx, y + h // 2 + 6), f"{ptype.upper()} · {date_str}",
           font=_font(11), fill=DIM)

    badge_text = "ОФОРМИТЬ ТИКЕТ"
    bf = _font(11)
    btw = _tw(d, badge_text, bf)
    bx = x + w - 24 - btw - 28
    by = y + h // 2 - 13
    d.rounded_rectangle((bx, by, bx + btw + 28, by + 26),
                        radius=7, fill=GREEN_BG + (255,),
                        outline=GREEN + (170,), width=1)
    d.text((bx + 14, by + 7), badge_text, font=bf, fill=GREEN)


# ============================================================
# ЭКРАН 1: КАТЕГОРИИ
# ============================================================
def render_categories(user_id, balance, total_spent, categories, total_items=0):
    img, d = _base_canvas(user_id, "витрина · dc")

    body_y = 130
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 442
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        user_id, balance, total_spent,
        extra_blocks=[
            {
                "label": "Категорий в магазине",
                "value": f"{len(categories)} шт.",
                "icon": I_LIST,
                "color": SILVER,
            },
            {
                "label": "Всего товаров",
                "value": f"{total_items} позиций",
                "icon": I_BAG,
                "color": BLUE,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Каталог магазина",
                     "выбери категорию в меню ниже")

    grid_y1 = body_y + 100
    grid_y2 = body_y + body_h - 22
    grid_h = grid_y2 - grid_y1
    cell_gap = 14
    cols, rows = 4, 2
    cell_w = (rx2 - rx1 - cell_gap * (cols - 1)) // cols
    cell_h = (grid_h - cell_gap * (rows - 1)) // rows

    for idx in range(cols * rows):
        r = idx // cols
        c = idx % cols
        cx = rx1 + c * (cell_w + cell_gap)
        cy = grid_y1 + r * (cell_h + cell_gap)
        if idx < len(categories):
            cat = categories[idx]
            _draw_category_tile(
                d, img, cx, cy, cell_w, cell_h,
                cat["key"], cat["label"], cat["count"],
                cat.get("min_price", 0),
                cat.get("description", ""),
                active=(idx == 0),
            )
        else:
            _draw_dashed_rect(d, (cx, cy, cx + cell_w, cy + cell_h), 18,
                              (36, 36, 42), dash=12, gap=8, width=2)
            _draw_icon(d, cx + cell_w // 2, cy + cell_h // 2, I_ELLIPSIS, 24, DARK)

    _draw_footer(d, "Выбери категорию в меню ниже", "стр. 1 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 2: ТОВАРЫ
# ============================================================
def render_products(user_id, balance, total_spent,
                    category_key, category_label, items):
    img, d = _base_canvas(user_id, "витрина · dc")

    body_y = 130
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 442
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    affordable = sum(1 for it in items if balance >= it["price"])
    min_price = min((it["price"] for it in items), default=0)

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        user_id, balance, total_spent,
        extra_blocks=[
            {
                "label": "Доступно тебе",
                "value": f"{affordable} из {len(items)}",
                "icon": I_CHECK,
                "color": GREEN,
            },
            {
                "label": "Мин. цена",
                "value": f"{_fmt(min_price)} DC",
                "icon": I_TAG,
                "color": SILVER,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     f"{category_label} · товары",
                     f"{len(items)} позиций · выбери в меню ниже")

    grid_y1 = body_y + 100
    grid_y2 = body_y + body_h - 22
    grid_h = grid_y2 - grid_y1
    cell_gap = 14
    cols, rows = 3, 2
    cell_w = (rx2 - rx1 - cell_gap * (cols - 1)) // cols
    cell_h = (grid_h - cell_gap * (rows - 1)) // rows

    for idx in range(cols * rows):
        r = idx // cols
        c = idx % cols
        cx = rx1 + c * (cell_w + cell_gap)
        cy = grid_y1 + r * (cell_h + cell_gap)
        if idx < len(items):
            _draw_item_tile(d, img, cx, cy, cell_w, cell_h,
                            items[idx], balance, active=False)
        else:
            _draw_dashed_rect(d, (cx, cy, cx + cell_w, cy + cell_h), 18,
                              (36, 36, 42), dash=12, gap=8, width=2)
            _draw_icon(d, cx + cell_w // 2, cy + cell_h // 2, I_ELLIPSIS, 24, DARK)

    _draw_footer(d, "Выбери товар в меню ниже", "стр. 2 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 3: КАРТОЧКА ТОВАРА
# ============================================================
def render_detail(user_id, balance, total_spent,
                  category_key, category_label, item):
    img, d = _base_canvas(user_id, "витрина · dc")

    body_y = 130
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 442
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    price = item["price"]
    can_afford = balance >= price
    missing = max(price - balance, 0)

    blocks = [
        {
            "label": "Навигация",
            "value": "← К товарам",
            "icon": I_ARROW_L,
            "color": BLUE,
        },
    ]
    if not can_afford:
        blocks.append({
            "label": "Не хватает",
            "value": f"{_fmt(missing)} DC",
            "icon": I_COINS,
            "color": RED,
        })

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        user_id, balance, total_spent, extra_blocks=blocks,
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Информация о товаре",
                     "готов к покупке" if can_afford else "недостаточно dc")

    # Hero блок
    top_y = body_y + 100
    icon_size = 200
    ix = rx1
    iy = top_y

    _gradient_box(img, (ix, iy, ix + icon_size, iy + icon_size),
                  SILVER, SILVER_DIM, alpha=38, radius=20)
    d.rounded_rectangle((ix, iy, ix + icon_size, iy + icon_size),
                        radius=20, outline=SILVER + (170,), width=3)
    _draw_icon(d, ix + icon_size // 2, iy + icon_size // 2 + 1,
               item.get("fa", I_CUBE), 80, SILVER_HI)

    tx = ix + icon_size + 30
    tx_max = rx2 - tx

    d.text((tx, iy + 4), category_label.upper(), font=_font(13), fill=SILVER)

    name = item["name"]
    name_font = _font(42)
    while _tw(d, name, name_font) > tx_max and name_font.size > 22:
        name_font = _font(name_font.size - 2)
    d.text((tx, iy + 28), name, font=name_font, fill=TEXT)

    desc = item.get("description") or "Описание не указано."
    desc_font = _font(15)
    lines = _wrap(d, desc, desc_font, tx_max, max_lines=5)
    for i, line in enumerate(lines):
        d.text((tx, iy + 90 + i * 22), line, font=desc_font, fill=TEXT_SOFT)

    # Spec-панель
    spec_y = iy + icon_size + 26
    spec_h = 100
    spec_x1 = rx1
    spec_x2 = rx2
    d.rounded_rectangle((spec_x1, spec_y, spec_x2, spec_y + spec_h),
                        radius=14, fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)

    cols_count = 3
    cell_w = (spec_x2 - spec_x1) // cols_count

    specs = [
        ("ЦЕНА", f"{_fmt(price)} DC", SILVER_HI),
        ("НАЛИЧИЕ",
         "Хватает DC" if can_afford else f"Не хватает {_fmt(missing)}",
         GREEN if can_afford else RED),
        ("СРОК", "до 2 дней", BLUE),
    ]
    for i, (k, v, color) in enumerate(specs):
        cx = spec_x1 + 30 + i * cell_w
        d.text((cx, spec_y + 18), k, font=_font(12), fill=MUTED)
        d.text((cx, spec_y + 40), v, font=_font(22), fill=color)
        if i < cols_count - 1:
            d.line((spec_x1 + (i + 1) * cell_w, spec_y + 22,
                    spec_x1 + (i + 1) * cell_w, spec_y + spec_h - 22),
                   fill=INNER_BRD + (255,), width=2)

    # Статус
    foot_y = spec_y + spec_h + 22
    foot_h = body_y + body_h - 30 - foot_y
    if foot_h < 70:
        foot_h = 70

    if can_afford:
        d.rounded_rectangle((rx1, foot_y, rx2, foot_y + foot_h),
                            radius=14, fill=GREEN_BG + (200,),
                            outline=GREEN + (170,), width=2)
        _draw_icon(d, rx1 + 34, foot_y + foot_h // 2, I_CHECK, 22, GREEN)
        d.text((rx1 + 64, foot_y + foot_h // 2 - 18),
               "Товар доступен для покупки", font=_font(17), fill=GREEN)
        d.text((rx1 + 64, foot_y + foot_h // 2 + 6),
               "Нажми «Купить» в меню ниже — товар появится в инвентаре, оформишь в тикете",
               font=_font(12), fill=GREEN)
    else:
        d.rounded_rectangle((rx1, foot_y, rx2, foot_y + foot_h),
                            radius=14, fill=RED_BG + (200,),
                            outline=RED + (170,), width=2)
        _draw_icon(d, rx1 + 34, foot_y + foot_h // 2, I_XMARK, 22, RED)
        d.text((rx1 + 64, foot_y + foot_h // 2 - 18),
               f"Не хватает {_fmt(missing)} DC для покупки",
               font=_font(17), fill=RED)
        d.text((rx1 + 64, foot_y + foot_h // 2 + 6),
               "Заработай DC активностью или выбери другой товар",
               font=_font(12), fill=RED)

    _draw_footer(d, "Нажми «Купить» в меню ниже", "стр. 3 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 4: МОИ ПОКУПКИ
# ============================================================
def render_purchases(user_id, balance, total_spent, purchases):
    img, d = _base_canvas(user_id, "витрина · dc")

    body_y = 130
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 442
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        user_id, balance, total_spent,
        extra_blocks=[
            {
                "label": "Активных покупок",
                "value": f"{len(purchases)} шт.",
                "icon": I_BAG,
                "color": GREEN,
            },
            {
                "label": "Что дальше",
                "value": "Оформить тикет",
                "icon": I_TICKET,
                "color": BLUE,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Мои покупки",
                     "активные · можно оформить в тикет")

    list_y = body_y + 100
    row_h = 68
    gap_row = 8

    if not purchases:
        box = (rx1, list_y, rx2, list_y + 260)
        _draw_dashed_rect(d, box, 18, (58, 58, 64), dash=12, gap=8, width=2)

        icon_cx = (rx1 + rx2) // 2
        icon_cy = list_y + 70
        _alpha_fill(img, (icon_cx - 40, icon_cy - 40, icon_cx + 40, icon_cy + 40),
                    SILVER, alpha=25, radius=20)
        _draw_icon(d, icon_cx, icon_cy, I_BAG, 36, SILVER)

        d.text((icon_cx, list_y + 145), "У тебя пока нет активных покупок",
               font=_font(20), fill=TEXT, anchor="mm")
        d.text((icon_cx, list_y + 178),
               "Загляни в каталог — там есть из чего выбрать.",
               font=_font(14), fill=MUTED, anchor="mm")
        d.text((icon_cx, list_y + 210),
               "После покупки товар появится здесь и его можно оформить в тикет.",
               font=_font(12), fill=DIM, anchor="mm")
    else:
        for idx, p in enumerate(purchases[:8]):
            y = list_y + idx * (row_h + gap_row)
            _draw_purchase_row(d, img, rx1, y, rx2 - rx1, row_h, p)

    _draw_footer(d, "Выбери покупку чтобы оформить тикет", "стр. 4 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 5: АКЦИЯ ДНЯ
# ============================================================
def render_daily_deal(user_id, balance, total_spent, deal, hours_left):
    img, d = _base_canvas(user_id, "акция дня")

    body_y = 130
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 442
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        user_id, balance, total_spent,
        extra_blocks=[
            {
                "label": "Обновится через",
                "value": f"{hours_left} ч.",
                "icon": I_CLOCK,
                "color": RED,
            },
            {
                "label": "Скидка сегодня",
                "value": f"{deal.get('discount', 0)}%" if deal else "—",
                "icon": I_TAG,
                "color": SILVER,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Акция дня",
                     "сегодня только · обновляется ежедневно")

    if not deal:
        box = (rx1, body_y + 100, rx2, body_y + body_h - 24)
        _draw_dashed_rect(d, box, 18, (58, 58, 64), dash=12, gap=8, width=2)

        icon_cx = (rx1 + rx2) // 2
        icon_cy = box[1] + 90
        _alpha_fill(img, (icon_cx - 48, icon_cy - 48, icon_cx + 48, icon_cy + 48),
                    RED, alpha=25, radius=24)
        _draw_icon(d, icon_cx, icon_cy, I_FIRE, 42, RED)

        d.text((icon_cx, box[1] + 175), "Акции сегодня пока нет",
               font=_font(24), fill=TEXT, anchor="mm")
        d.text((icon_cx, box[1] + 208),
               "Каждый день мы выбираем один товар и даём скидку до 30%.",
               font=_font(14), fill=MUTED, anchor="mm")
        d.text((icon_cx, box[1] + 232),
               "Следующее обновление автоматическое — заходи позже.",
               font=_font(14), fill=MUTED, anchor="mm")

        info_y = box[1] + 280
        info_h = 90
        cols = 3
        cell_w = (rx2 - rx1 - 20 * (cols - 1)) // cols
        infos = [
            ("ОБНОВЛЕНИЕ", "Каждый день", I_CLOCK, BLUE),
            ("СКИДКА ДО", "30%", I_TAG, SILVER),
            ("ОДИН ТОВАР", "На выбор", I_CUBE, PURPLE),
        ]
        for i, (k, v, icon, color) in enumerate(infos):
            cx1 = rx1 + i * (cell_w + 20)
            cx2 = cx1 + cell_w
            _alpha_fill(img, (cx1, info_y, cx2, info_y + info_h), color, alpha=18, radius=14)
            d.rounded_rectangle((cx1, info_y, cx2, info_y + info_h),
                                radius=14, outline=color + (140,), width=2)
            _draw_icon(d, cx1 + 32, info_y + info_h // 2, icon, 24, color)
            d.text((cx1 + 64, info_y + 22), k, font=_font(11), fill=color)
            d.text((cx1 + 64, info_y + 42), v, font=_font(20), fill=TEXT)
    else:
        _draw_deal_card(d, img, rx1, body_y + 100,
                        rx2 - rx1, body_h - 140, deal, balance)

    _draw_footer(d, "Нажми «Купить» чтобы забрать по акции", "стр. 5 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _draw_deal_card(d, img, x, y, w, h, deal, balance):
    item_data = deal.get("item_data", {})
    name = item_data.get("name", "—")
    cat_label = deal.get("category_label", "—")
    orig = deal.get("original_price", 0)
    new = deal.get("new_price", 0)
    discount = deal.get("discount", 0)
    cat_key = deal.get("cat_key", "misc")

    d.rounded_rectangle((x, y, x + w, y + h), radius=18,
                        fill=INNER_BG + (255,),
                        outline=RED + (140,), width=2)

    badge_h = 40
    _gradient_box(img, (x, y, x + w, y + badge_h), RED, RED,
                  alpha=220, radius=18)
    d.rectangle((x, y + badge_h - 18, x + w, y + badge_h), fill=RED + (220,))
    _draw_icon(d, x + 28, y + badge_h // 2, I_FIRE, 18, (255, 255, 255))
    d.text((x + 52, y + badge_h // 2 - 12),
           f"СКИДКА {discount}% · ТОЛЬКО СЕГОДНЯ",
           font=_font(15), fill=(255, 255, 255))

    icon_size = 200
    ix = x + 32
    iy = y + badge_h + 26
    _gradient_box(img, (ix, iy, ix + icon_size, iy + icon_size),
                  SILVER, SILVER_DIM, alpha=35, radius=20)
    d.rounded_rectangle((ix, iy, ix + icon_size, iy + icon_size),
                        radius=20, outline=SILVER + (160,), width=3)
    _draw_icon(d, ix + icon_size // 2, iy + icon_size // 2 + 1,
               CATEGORY_FA.get(cat_key, I_CUBE), 80, SILVER_HI)

    tx = ix + icon_size + 34
    tx_max = x + w - 34 - tx

    d.text((tx, iy + 6), cat_label.upper(), font=_font(13), fill=SILVER)

    name_font = _font(38)
    while _tw(d, name, name_font) > tx_max and name_font.size > 22:
        name_font = _font(name_font.size - 2)
    d.text((tx, iy + 30), name, font=name_font, fill=TEXT)

    desc = item_data.get("description") or "Товар по акции со скидкой."
    desc_font = _font(14)
    lines = _wrap(d, desc, desc_font, tx_max, max_lines=3)
    for i, line in enumerate(lines):
        d.text((tx, iy + 82 + i * 20), line, font=desc_font, fill=MUTED)

    orig_str = f"{_fmt(orig)} DC"
    of = _font(17)
    ow = _tw(d, orig_str, of)
    d.text((tx, iy + 146), orig_str, font=of, fill=DIM)
    d.line((tx, iy + 158, tx + ow, iy + 158), fill=DIM, width=2)

    new_str = _fmt(new)
    nf = _font(48)
    d.text((tx, iy + 170), new_str, font=nf, fill=RED)
    nw = _tw(d, new_str, nf)
    d.text((tx + nw + 8, iy + 170 + nf.size - 24), "DC",
           font=_font(20), fill=RED)

    can_afford = balance >= new
    status_color = GREEN if can_afford else RED
    status_text = "ХВАТАЕТ DC" if can_afford else f"НЕ ХВАТАЕТ {_fmt(new - balance)} DC"
    sf = _font(13)
    stw = _tw(d, status_text, sf)
    sx = x + w - 34 - stw - 28
    sy = iy + 200
    d.ellipse((sx, sy + 6, sx + 11, sy + 17), fill=status_color + (255,))
    d.text((sx + 22, sy + 4), status_text, font=sf, fill=status_color)

    hint_y = y + h - 38
    d.line((x + 34, hint_y - 12, x + w - 34, hint_y - 12),
           fill=INNER_BRD + (255,), width=2)
    _draw_icon(d, x + 46, hint_y + 8, I_INFO, 14, DIM)
    d.text((x + 66, hint_y),
           "Акционный товар нельзя вернуть — проверь перед покупкой.",
           font=_font(12), fill=DIM)


# ============================================================
# ЭКРАН 6: ИСТОРИЯ ПОКУПОК
# ============================================================
def render_history(user_id, balance, total_spent, history):
    img, d = _base_canvas(user_id, "история dc")

    body_y = 130
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 442
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    spent_total = sum(-o["amount"] for o in history if o and o.get("amount", 0) < 0)

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        user_id, balance, total_spent,
        extra_blocks=[
            {
                "label": "Всего покупок",
                "value": f"{len(history)}",
                "icon": I_HISTORY,
                "color": SILVER,
            },
            {
                "label": "Потрачено",
                "value": f"{_fmt(spent_total)} DC",
                "icon": I_COINS,
                "color": RED,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "История покупок",
                     "последние операции за dc")

    list_y = body_y + 100
    rows = 8
    row_h = 60
    gap_row = 8

    ops = list(history[:rows])

    if not ops:
        box = (rx1, list_y, rx2, list_y + 260)
        _draw_dashed_rect(d, box, 18, (58, 58, 64), dash=12, gap=8, width=2)
        icon_cx = (rx1 + rx2) // 2
        icon_cy = list_y + 70
        _alpha_fill(img, (icon_cx - 40, icon_cy - 40, icon_cx + 40, icon_cy + 40),
                    SILVER, alpha=25, radius=20)
        _draw_icon(d, icon_cx, icon_cy, I_HISTORY, 36, SILVER)
        d.text((icon_cx, list_y + 155), "Покупок пока не было",
               font=_font(20), fill=TEXT, anchor="mm")
        d.text((icon_cx, list_y + 188),
               "После первой покупки здесь появится история операций.",
               font=_font(14), fill=MUTED, anchor="mm")
    else:
        while len(ops) < rows:
            ops.append(None)
        for idx, op in enumerate(ops):
            y = list_y + idx * (row_h + gap_row)
            _draw_operation_row(d, img, rx1, y, rx2 - rx1, row_h, op)

    _draw_footer(d, "Показаны последние покупки за DC", "стр. 6 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 7: УСПЕШНАЯ ПОКУПКА
# ============================================================
def render_success(user_id, balance, total_spent, outcome):
    img, d = _base_canvas(user_id, outcome.get("uid_label", "покупка"))

    body_y = 130
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 442
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        user_id, balance, total_spent,
        extra_blocks=outcome.get("left_blocks", []),
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    accent = outcome.get("color", GREEN)

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     outcome.get("head_title", "Покупка совершена"),
                     outcome.get("head_sub", "что дальше"))

    # Hero
    top_y = body_y + 100
    icon_size = 140
    ix = rx1 + 6
    iy = top_y + 8

    _gradient_box(img, (ix, iy, ix + icon_size, iy + icon_size),
                  accent, accent, alpha=38, radius=22)
    d.rounded_rectangle((ix, iy, ix + icon_size, iy + icon_size),
                        radius=22, outline=accent + (200,), width=3)
    _draw_icon(d, ix + icon_size // 2, iy + icon_size // 2 + 1,
               outcome.get("icon", I_CHECK), 62, accent)

    tx = ix + icon_size + 28
    tx_max = rx2 - tx

    title = outcome.get("title", "Покупка совершена")
    tfont = _font(30)
    while _tw(d, title, tfont) > tx_max and tfont.size > 18:
        tfont = _font(tfont.size - 2)
    d.text((tx, iy + 12), title, font=tfont, fill=TEXT)

    subtitle = outcome.get("subtitle", "")
    sfont = _font(14)
    sub_lines = _wrap(d, subtitle, sfont, tx_max, max_lines=4)
    for i, line in enumerate(sub_lines):
        d.text((tx, iy + 54 + i * 20), line, font=sfont, fill=TEXT_SOFT)

    item_line = outcome.get("item_line", "")
    if item_line:
        d.text((tx, iy + icon_size - 22), item_line, font=_font(15), fill=accent)

    # Шаги
    steps_y = top_y + icon_size + 44
    steps = outcome.get("steps", [])
    if steps:
        d.text((rx1, steps_y), "ЧТО ДАЛЬШЕ", font=_font(13), fill=MUTED)
        d.line((rx1, steps_y + 24, rx2, steps_y + 24),
               fill=STACK_HDR + (255,), width=2)

        step_h = 56
        step_gap = 8
        max_steps = 4
        for i, step in enumerate(steps[:max_steps]):
            sy = steps_y + 38 + i * (step_h + step_gap)
            d.rounded_rectangle((rx1, sy, rx2, sy + step_h),
                                radius=12, fill=INNER_BG + (255,),
                                outline=INNER_BRD + (255,), width=2)

            num_cx = rx1 + 34
            num_cy = sy + step_h // 2
            d.ellipse((num_cx - 16, num_cy - 16, num_cx + 16, num_cy + 16),
                      fill=accent + (45,), outline=accent + (200,), width=2)
            d.text((num_cx, num_cy), str(i + 1), font=_font(15),
                   fill=accent, anchor="mm")

            txf = _font(14)
            step_shown = _ellipsis(d, step, txf, rx2 - rx1 - 100)
            d.text((rx1 + 68, num_cy), step_shown, font=txf,
                   fill=TEXT_SOFT, anchor="lm")

    hint_y = body_y + body_h - 30
    d.line((rx1, hint_y - 12, rx2, hint_y - 12),
           fill=STACK_HDR + (255,), width=2)
    _draw_icon(d, rx1 + 12, hint_y + 8, I_INFO, 13, DIM)
    d.text((rx1 + 32, hint_y),
           outcome.get("hint", "Используй кнопки внизу"),
           font=_font(12), fill=DIM)

    _draw_footer(d, "Покупка завершена", "готово")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
