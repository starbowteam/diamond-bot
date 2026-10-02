# -*- coding: utf-8 -*-
"""
Pillow-рендер витрины DC-Shop.
Стиль 1-в-1 из profile_card.py, но палитра — холодное серебро.
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


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        f = ImageFont.truetype(FONT_BOLD, size)
    except Exception:
        f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


def _fa(size: int) -> Optional[ImageFont.FreeTypeFont]:
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
# ПАЛИТРА (серебро)
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
DARK      = (85, 85, 85)

# 👇 ХОЛОДНОЕ СЕРЕБРО вместо золота
SILVER       = (198, 208, 224)   # светлое серебро
SILVER_HI    = (224, 232, 245)   # почти белый блик
SILVER_MID   = (152, 164, 186)   # середина
SILVER_DIM   = (100, 112, 138)   # глубокое серебро
SILVER_BG    = (34, 38, 48)      # фон акцентных плашек

GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)

GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)

CARD_BRD  = (74, 74, 79)

# Цвет Discord-эмбеда для shop (нейтральный)
EMBED_COLOR = 0x2b2d31


# ============================================================
# FA-ИКОНКИ
# ============================================================
I_GEM        = 0xf3a5
I_STAR       = 0xf005
I_CART       = 0xf07a
I_PALETTE    = 0xf53f
I_BULLHORN   = 0xf0a1
I_MASKS      = 0xf630
I_BOLT       = 0xf0e7
I_GIFT       = 0xf06b
I_DICE       = 0xf522
I_USER       = 0xf007
I_IMAGE      = 0xf03e
I_BEZIER     = 0xf55b
I_SMILE      = 0xf118
I_LAYERS     = 0xf5fd
I_PEN_NIB    = 0xf5ad
I_ARROW_L    = 0xf060
I_FIRE       = 0xf06d
I_HISTORY    = 0xf1da
I_CHECK      = 0xf00c
I_XMARK      = 0xf00d
I_INFO       = 0xf05a
I_COINS      = 0xf51e
I_SACK       = 0xf81d
I_HOURGLASS  = 0xf252
I_CLIPBOARD  = 0xf46d
I_TAG        = 0xf02b
I_LIST       = 0xf03a
I_BAG        = 0xf290
I_TICKET     = 0xf145
I_CUBE       = 0xf1b2
I_SHOP       = 0xf54f
I_BOX_OPEN   = 0xf49e
I_SEARCH     = 0xf002
I_WALLET     = 0xf555
I_TROPHY     = 0xf091
I_MONEY      = 0xf0d6
I_CLOCK      = 0xf017
I_SHIELD     = 0xf3ed
I_ELLIPSIS   = 0xf141
I_CIRCLE_M   = 0xf056


CATEGORY_FA = {
    "discounts": I_CART,
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


def _lerp_color(c1, c2, t):
    return (
        int(c1[0] * (1 - t) + c2[0] * t),
        int(c1[1] * (1 - t) + c2[1] * t),
        int(c1[2] * (1 - t) + c2[2] * t),
    )


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
PAD_X = 56
PAD_Y = 44


def _base_canvas(user_id: int, uid_label: str):
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (M, M, CANVAS_W - 1 - M, CANVAS_H - 1 - M),
        radius=30, fill=CARD_TOP + (255,),
        outline=CARD_BRD + (255,), width=3,
    )

    hx = PAD_X
    hy = PAD_Y

    logo_size = 54
    d.rounded_rectangle((hx, hy, hx + logo_size, hy + logo_size), radius=14,
                        fill=(58, 58, 64) + (255,))
    _draw_icon(d, hx + logo_size // 2, hy + logo_size // 2 + 1, I_GEM, 26, SILVER)

    brand_x = hx + logo_size + 18
    d.text((brand_x, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((brand_x + 2, hy + 38), "SHOP & ECOSYSTEM", font=_font(11), fill=MUTED)

    meta_r = CANVAS_W - M - PAD_X
    lbl = uid_label.upper()
    uid = f"UID · {user_id}"
    w1 = _tw(d, lbl, _font(11))
    w2 = _tw(d, uid, _font(20))
    d.text((meta_r - w1, hy + 12), lbl, font=_font(11), fill=MUTED)
    d.text((meta_r - w2, hy + 32), uid, font=_font(20), fill=TEXT)

    sep_y = hy + logo_size + 16
    d.line((PAD_X, sep_y, CANVAS_W - M - PAD_X, sep_y),
           fill=STACK_HDR + (255,), width=2)

    return img, d


def _draw_footer(d, left_text: str, page: str):
    y = CANVAS_H - M - PAD_Y + 6
    d.line((PAD_X, y - 12, CANVAS_W - M - PAD_X, y - 12),
           fill=STACK_HDR + (255,), width=2)
    _draw_icon(d, PAD_X + 8, y + 6, I_INFO, 12, DIM)
    d.text((PAD_X + 26, y), left_text, font=_font(11), fill=DIM)
    pw = _tw(d, page, _font(11))
    d.text((CANVAS_W - M - PAD_X - pw, y), page, font=_font(11), fill=DIM)


# ============================================================
# ЛЕВАЯ ПАНЕЛЬ
# ============================================================
def _draw_left_panel(img, d, box, user_id, balance, total_spent, bottom_block=None):
    _draw_stack_panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 28

    # Баланс
    bal_icon_size = 68
    ib_x = x1 + pad
    ib_y = y1 + pad
    _gradient_box(img, (ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                  SILVER, SILVER_DIM, alpha=32, radius=18)
    d.rounded_rectangle((ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                        radius=18, outline=SILVER + (120,), width=2)
    _draw_icon(d, ib_x + bal_icon_size // 2, ib_y + bal_icon_size // 2 + 1,
               I_GEM, 28, SILVER_HI)

    lbl_x = ib_x + bal_icon_size + 18
    d.text((lbl_x, ib_y + 4), "ТВОЙ БАЛАНС", font=_font(10), fill=MUTED)

    bal_str = _fmt(balance)
    val_font = _font(38)
    max_w = x2 - pad - lbl_x - 20
    while _tw(d, bal_str + " DC", val_font) > max_w and val_font.size > 20:
        val_font = _font(val_font.size - 2)
    d.text((lbl_x, ib_y + 24), bal_str, font=val_font, fill=TEXT)
    bw = _tw(d, bal_str, val_font)
    d.text((lbl_x + bw + 6, ib_y + 24 + val_font.size - 22),
           "DC", font=_font(18), fill=SILVER)

    # Разделитель
    sep_y = ib_y + bal_icon_size + 26
    d.line((x1 + pad, sep_y, x2 - pad, sep_y),
           fill=STACK_HDR + (255,), width=2)

    # Всего потрачено
    sp_icon_size = 56
    sp_x = x1 + pad
    sp_y = sep_y + 24
    _gradient_box(img, (sp_x, sp_y, sp_x + sp_icon_size, sp_y + sp_icon_size),
                  GREEN, GREEN, alpha=22, radius=15)
    d.rounded_rectangle((sp_x, sp_y, sp_x + sp_icon_size, sp_y + sp_icon_size),
                        radius=15, outline=GREEN + (85,), width=2)
    _draw_icon(d, sp_x + sp_icon_size // 2, sp_y + sp_icon_size // 2 + 1,
               I_COINS, 22, GREEN)

    sp_lbl_x = sp_x + sp_icon_size + 16
    d.text((sp_lbl_x, sp_y + 2), "ВСЕГО ПОТРАЧЕНО", font=_font(10), fill=MUTED)
    sp_str = f"{_fmt(total_spent)} DC"
    sp_font = _font(22)
    while _tw(d, sp_str, sp_font) > x2 - pad - sp_lbl_x - 12 and sp_font.size > 14:
        sp_font = _font(sp_font.size - 2)
    d.text((sp_lbl_x, sp_y + 22), sp_str, font=sp_font, fill=GREEN)

    # Нижний блок
    if bottom_block:
        bb_h = 92
        bb_x1 = x1 + pad
        bb_y1 = y2 - pad - bb_h
        bb_x2 = x2 - pad
        bb_y2 = y2 - pad

        bcolor = bottom_block.get("color", SILVER)
        bg_map = {
            SILVER: SILVER_BG,
            GREEN: GREEN_BG,
            BLUE: BLUE_BG,
            PURPLE: PURPLE_BG,
            RED: RED_BG,
        }
        bbg = bg_map.get(bcolor, SILVER_BG)

        _gradient_box(img, (bb_x1, bb_y1, bb_x2, bb_y2),
                      bcolor, bcolor, alpha=18, radius=14)
        d.rounded_rectangle((bb_x1, bb_y1, bb_x2, bb_y2),
                            radius=14, outline=bcolor + (140,), width=2)

        icon_size = 44
        ib2_x = bb_x1 + 16
        ib2_y = bb_y1 + (bb_h - icon_size) // 2
        _alpha_fill(img, (ib2_x, ib2_y, ib2_x + icon_size, ib2_y + icon_size),
                    bcolor, alpha=45, radius=11)
        _draw_icon(d, ib2_x + icon_size // 2, ib2_y + icon_size // 2 + 1,
                   bottom_block.get("icon", I_CIRCLE_M), 20, bcolor)

        tx = ib2_x + icon_size + 14
        d.text((tx, bb_y1 + 18), bottom_block.get("label", "").upper(),
               font=_font(10), fill=bcolor)
        bv = bottom_block.get("value", "—")
        val_font = _font(17)
        max_w2 = bb_x2 - 20 - tx
        bv_shown = _ellipsis(d, bv, val_font, max_w2)
        d.text((tx, bb_y1 + 38), bv_shown, font=val_font, fill=bcolor)


# ============================================================
# ПРАВЫЙ ЗАГОЛОВОК
# ============================================================
def _draw_right_head(d, x1, y1, x2, title: str, sub: str):
    d.text((x1, y1), title.upper(), font=_font(22), fill=TEXT)
    sub_w = _tw(d, sub.upper(), _font(11))
    d.text((x2 - sub_w, y1 + 10), sub.upper(), font=_font(11), fill=MUTED)
    d.line((x1, y1 + 44, x2, y1 + 44), fill=STACK_HDR + (255,), width=2)


# ============================================================
# ПЛИТКИ
# ============================================================
def _draw_category_tile(d, img, x, y, w, h, cat_key, label, count, active=False):
    if active:
        _gradient_box(img, (x, y, x + w, y + h), SILVER, SILVER_DIM, alpha=18, radius=16)
        d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                            outline=SILVER + (200,), width=2)
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)

    icon_size = 46
    ib_x = x + 20
    ib_y = y + 20

    icon_code = CATEGORY_FA.get(cat_key, I_CUBE)
    if active:
        _gradient_box(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                      SILVER, SILVER_DIM, alpha=45, radius=13)
        d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                            radius=13, outline=SILVER + (160,), width=2)
        _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
                   icon_code, 22, SILVER_HI)
    else:
        _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                    SILVER, alpha=22, radius=13)
        d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                            radius=13, outline=SILVER + (85,), width=2)
        _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
                   icon_code, 22, SILVER)

    name_y = ib_y + icon_size + 18
    name_font = _font(17)
    name_shown = _ellipsis(d, label, name_font, w - 40)
    d.text((x + 20, name_y), name_shown, font=name_font,
           fill=SILVER_HI if active else TEXT)

    cnt_str = f"{count} {'товар' if count == 1 else 'товара' if 2 <= count <= 4 else 'товаров'}"
    d.text((x + 20, y + h - 30), cnt_str, font=_font(10),
           fill=SILVER if active else DIM)


def _draw_item_tile(d, img, x, y, w, h, item, balance, active=False):
    if active:
        _gradient_box(img, (x, y, x + w, y + h), SILVER, SILVER_DIM, alpha=14, radius=16)
        d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                            outline=SILVER + (180,), width=2)
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)

    icon_size = 46
    ib_x = x + 20
    ib_y = y + 20
    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                SILVER, alpha=22, radius=13)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=13, outline=SILVER + (95,), width=2)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               item.get("fa", I_CUBE), 22, SILVER)

    name_y = ib_y + icon_size + 16
    name_font = _font(16)
    name_shown = _ellipsis(d, item["name"], name_font, w - 40)
    d.text((x + 20, name_y), name_shown, font=name_font, fill=TEXT)

    footer_y = y + h - 42
    price = item["price"]
    price_str = f"{_fmt(price)}"
    pf = _font(24)
    d.text((x + 20, footer_y), price_str, font=pf, fill=SILVER_HI)
    pw = _tw(d, price_str, pf)
    d.text((x + 20 + pw + 4, footer_y + pf.size - 18),
           "DC", font=_font(12), fill=SILVER)

    can_afford = balance >= price
    badge_text = "КУПИТЬ" if can_afford else "НЕ ХВАТАЕТ"
    badge_color = GREEN if can_afford else RED
    badge_bg = GREEN_BG if can_afford else RED_BG
    bf = _font(10)
    btw = _tw(d, badge_text, bf)
    bpad = 12
    bx = x + w - 20 - btw - bpad * 2
    by = footer_y + 2
    d.rounded_rectangle((bx, by, bx + btw + bpad * 2, by + 24),
                        radius=6, fill=badge_bg + (255,),
                        outline=badge_color + (180,), width=1)
    d.text((bx + bpad, by + 7), badge_text, font=bf, fill=badge_color)


def _draw_operation_row(d, img, x, y, w, h, op):
    d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                        fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)

    if not op:
        _draw_icon(d, x + 44, y + h // 2, I_CIRCLE_M, 18, DARK)
        d.text((x + 72, y + h // 2), "—", font=_font(16),
               fill=DARK, anchor="lm")
        return

    amt = op.get("amount", 0)
    reason = (op.get("reason", "") or "—")[:90]
    is_plus = amt >= 0
    accent = GREEN if is_plus else RED
    sign = "+" if is_plus else "−"

    d.rounded_rectangle((x, y, x + 4, y + h), radius=4, fill=accent + (255,))

    op_icon_size = 44
    ib_x = x + 16
    ib_y = y + (h - op_icon_size) // 2
    _alpha_fill(img, (ib_x, ib_y, ib_x + op_icon_size, ib_y + op_icon_size),
                accent, alpha=35, radius=11)
    _draw_icon(d, ib_x + op_icon_size // 2, ib_y + op_icon_size // 2 + 1,
               I_COINS if is_plus else I_CART, 18, accent)

    tx = ib_x + op_icon_size + 14
    name_f = _font(15)
    time_f = _font(11)

    amt_str = f"{sign}{abs(int(amt))} DC"
    amt_f = _font(20)
    amt_w = _tw(d, amt_str, amt_f)
    rx = x + w - 20 - amt_w

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
    d.text((tx, name_y + 20), time_str.upper(), font=time_f, fill=DIM)

    d.text((rx, y + h // 2 - 14), amt_str, font=amt_f, fill=accent)


# ============================================================
# ЭКРАН 1: КАТЕГОРИИ
# ============================================================
def render_categories(user_id, balance, total_spent, categories):
    img, d = _base_canvas(user_id, "витрина · dc")

    body_y = 158
    body_h = CANVAS_H - M - PAD_Y - body_y - 30

    left_w = 360
    gap = 28
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(img, d, (left_x1, body_y, left_x2, body_y + body_h),
                     user_id, balance, total_spent, bottom_block=None)

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 26, rx2, "Каталог магазина", "выбери категорию")

    grid_y1 = body_y + 90
    grid_y2 = body_y + body_h - 24
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
        if idx < len(categories):
            cat = categories[idx]
            _draw_category_tile(d, img, cx, cy, cell_w, cell_h,
                                cat["key"], cat["label"], cat["count"], active=(idx == 0))
        else:
            _draw_dashed_rect(d, (cx, cy, cx + cell_w, cy + cell_h), 16,
                              (36, 36, 42), dash=10, gap=7, width=2)
            _draw_icon(d, cx + cell_w // 2, cy + cell_h // 2, I_ELLIPSIS, 24, DARK)

    _draw_footer(d, "Выбери категорию в меню ниже", "стр. 1 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 2: ТОВАРЫ
# ============================================================
def render_products(user_id, balance, total_spent, category_key, category_label, items):
    img, d = _base_canvas(user_id, "витрина · dc")

    body_y = 158
    body_h = CANVAS_H - M - PAD_Y - body_y - 30

    left_w = 360
    gap = 28
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(img, d, (left_x1, body_y, left_x2, body_y + body_h),
                     user_id, balance, total_spent,
                     bottom_block={
                         "label": "Текущая категория",
                         "value": category_label,
                         "icon": CATEGORY_FA.get(category_key, I_CUBE),
                         "color": SILVER,
                     })

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 26, rx2,
                     f"{category_label} · товары", f"{len(items)} позиций")

    grid_y1 = body_y + 90
    grid_y2 = body_y + body_h - 24
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
            _draw_item_tile(d, img, cx, cy, cell_w, cell_h, items[idx], balance, active=False)
        else:
            _draw_dashed_rect(d, (cx, cy, cx + cell_w, cy + cell_h), 16,
                              (36, 36, 42), dash=10, gap=7, width=2)
            _draw_icon(d, cx + cell_w // 2, cy + cell_h // 2, I_ELLIPSIS, 24, DARK)

    _draw_footer(d, "Выбери товар в меню ниже", "стр. 2 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 3: КАРТОЧКА
# ============================================================
def render_detail(user_id, balance, total_spent, category_key, category_label, item):
    img, d = _base_canvas(user_id, "витрина · dc")

    body_y = 158
    body_h = CANVAS_H - M - PAD_Y - body_y - 30

    left_w = 360
    gap = 28
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(img, d, (left_x1, body_y, left_x2, body_y + body_h),
                     user_id, balance, total_spent,
                     bottom_block={
                         "label": "Навигация",
                         "value": "← К товарам",
                         "icon": I_ARROW_L,
                         "color": BLUE,
                     })

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 26, rx2, "Информация о товаре", "готов к покупке")

    icon_size = 260
    ix = rx1 + 40
    iy = body_y + 110
    _gradient_box(img, (ix, iy, ix + icon_size, iy + icon_size),
                  SILVER, SILVER_DIM, alpha=32, radius=24)
    d.rounded_rectangle((ix, iy, ix + icon_size, iy + icon_size),
                        radius=24, outline=SILVER + (160,), width=3)
    _draw_icon(d, ix + icon_size // 2, iy + icon_size // 2 + 1,
               item.get("fa", I_CUBE), 100, SILVER_HI)

    tx = ix + icon_size + 46
    tx_max = rx2 - tx

    d.text((tx, iy + 6), category_label.upper(), font=_font(11), fill=SILVER)
    name = item["name"]
    name_font = _font(46)
    while _tw(d, name, name_font) > tx_max and name_font.size > 22:
        name_font = _font(name_font.size - 2)
    d.text((tx, iy + 32), name, font=name_font, fill=TEXT)

    desc = item.get("description", "") or "—"
    d.text((tx, iy + 110), desc, font=_font(14), fill=MUTED)

    fy = iy + icon_size - 30
    d.line((tx, fy - 30, rx2, fy - 30), fill=STACK_HDR + (255,), width=2)

    price = item["price"]
    price_str = _fmt(price)
    pf = _font(48)
    d.text((tx, fy), price_str, font=pf, fill=SILVER_HI)
    pw = _tw(d, price_str, pf)
    d.text((tx + pw + 8, fy + pf.size - 26), "DC", font=_font(20), fill=SILVER)

    can_afford = balance >= price
    status_color = GREEN if can_afford else RED
    status_text = "ХВАТАЕТ DC" if can_afford else "НЕ ХВАТАЕТ DC"
    sf = _font(13)
    stw = _tw(d, status_text, sf)
    sx = rx2 - stw - 30
    d.ellipse((sx, fy + 20, sx + 10, fy + 30), fill=status_color + (255,))
    d.text((sx + 20, fy + 18), status_text, font=sf, fill=status_color)

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

    body_y = 158
    body_h = CANVAS_H - M - PAD_Y - body_y - 30

    left_w = 360
    gap = 28
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(img, d, (left_x1, body_y, left_x2, body_y + body_h),
                     user_id, balance, total_spent,
                     bottom_block={
                         "label": "Активных покупок",
                         "value": f"{len(purchases)} шт.",
                         "icon": I_BAG,
                         "color": GREEN,
                     })

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 26, rx2, "Мои покупки", "активные · можно в тикет")

    list_y = body_y + 90
    row_h = 70
    gap_row = 10

    if not purchases:
        d.text((rx1, list_y + 40), "У тебя пока нет активных покупок.",
               font=_font(16), fill=DIM)
        d.text((rx1, list_y + 72),
               "Загляни в каталог — выбери что-нибудь по вкусу.",
               font=_font(13), fill=DARK)
    else:
        for idx, p in enumerate(purchases[:8]):
            y = list_y + idx * (row_h + gap_row)
            _draw_purchase_row(d, img, rx1, y, rx2 - rx1, row_h, p)

    _draw_footer(d, "Выбери покупку чтобы оформить тикет", "стр. 4 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _draw_purchase_row(d, img, x, y, w, h, p):
    d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                        fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)

    icon_size = 44
    ib_x = x + 16
    ib_y = y + (h - icon_size) // 2
    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                SILVER, alpha=25, radius=11)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               I_TICKET, 18, SILVER)

    ptype = p.get("type", "—")
    pval = p.get("value", "—")
    tx = ib_x + icon_size + 14
    max_w = w - (tx - x) - 20
    name_shown = _ellipsis(d, pval, _font(16), max_w)
    d.text((tx, y + h // 2 - 16), name_shown, font=_font(16), fill=TEXT)

    try:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(p.get("date", 0), timezone.utc)
        date_str = dt.strftime("%d.%m.%Y · %H:%M")
    except Exception:
        date_str = "—"
    d.text((tx, y + h // 2 + 6), f"{ptype} · {date_str}".upper(),
           font=_font(10), fill=DIM)

    badge_text = "ОФОРМИТЬ"
    bf = _font(10)
    btw = _tw(d, badge_text, bf)
    bx = x + w - 20 - btw - 20
    by = y + h // 2 - 11
    d.rounded_rectangle((bx, by, bx + btw + 20, by + 22),
                        radius=6, fill=GREEN_BG + (255,),
                        outline=GREEN + (170,), width=1)
    d.text((bx + 10, by + 6), badge_text, font=bf, fill=GREEN)


# ============================================================
# ЭКРАН 5: АКЦИЯ ДНЯ
# ============================================================
def render_daily_deal(user_id, balance, total_spent, deal, hours_left):
    img, d = _base_canvas(user_id, "акция дня")

    body_y = 158
    body_h = CANVAS_H - M - PAD_Y - body_y - 30

    left_w = 360
    gap = 28
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(img, d, (left_x1, body_y, left_x2, body_y + body_h),
                     user_id, balance, total_spent,
                     bottom_block={
                         "label": "Обновится через",
                         "value": f"{hours_left} ч.",
                         "icon": I_HOURGLASS,
                         "color": RED,
                     })

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 26, rx2, "Акция дня", "сегодня только")

    if not deal:
        d.text((rx1, body_y + 200), "Сейчас активной акции нет.",
               font=_font(18), fill=DIM)
        d.text((rx1, body_y + 240), "Загляни позже — акция обновляется каждый день.",
               font=_font(13), fill=DARK)
    else:
        _draw_deal_card(d, img, rx1, body_y + 90, rx2 - rx1, body_h - 130, deal, balance)

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

    icon_size = 240
    ix = x + 20
    iy = y + (h - icon_size) // 2
    _gradient_box(img, (ix, iy, ix + icon_size, iy + icon_size),
                  RED, RED, alpha=28, radius=22)
    d.rounded_rectangle((ix, iy, ix + icon_size, iy + icon_size),
                        radius=22, outline=RED + (140,), width=3)
    _draw_icon(d, ix + icon_size // 2, iy + icon_size // 2 + 1,
               CATEGORY_FA.get(cat_key, I_CUBE), 92, RED)

    badge_text = f"−{discount}%"
    bf = _font(16)
    btw = _tw(d, badge_text, bf)
    bx = ix + icon_size - 90
    by = iy + 14
    d.rounded_rectangle((bx, by, bx + 74, by + 34),
                        radius=8, fill=RED + (255,))
    d.text((bx + (74 - btw) // 2, by + 8), badge_text, font=bf, fill=(255, 255, 255))

    tx = ix + icon_size + 40
    tx_max = x + w - 40 - tx

    d.text((tx, iy + 10), cat_label.upper(), font=_font(11), fill=RED)
    name_font = _font(40)
    while _tw(d, name, name_font) > tx_max and name_font.size > 20:
        name_font = _font(name_font.size - 2)
    d.text((tx, iy + 34), name, font=name_font, fill=TEXT)

    orig_str = f"{_fmt(orig)} DC"
    of = _font(18)
    ow = _tw(d, orig_str, of)
    d.text((tx, iy + 90), orig_str, font=of, fill=DIM)
    d.line((tx, iy + 102, tx + ow, iy + 102), fill=DIM, width=2)

    new_str = _fmt(new)
    nf = _font(48)
    d.text((tx, iy + 122), new_str, font=nf, fill=RED)
    nw = _tw(d, new_str, nf)
    d.text((tx + nw + 8, iy + 122 + nf.size - 26), "DC",
           font=_font(20), fill=RED)

    can_afford = balance >= new
    status_color = GREEN if can_afford else RED
    status_text = "ХВАТАЕТ DC" if can_afford else "НЕ ХВАТАЕТ DC"
    sf = _font(13)
    stw = _tw(d, status_text, sf)
    sx = x + w - 40 - stw - 30
    sy = iy + 140
    d.ellipse((sx, sy + 6, sx + 10, sy + 16), fill=status_color + (255,))
    d.text((sx + 20, sy + 4), status_text, font=sf, fill=status_color)

    warn = "ОГРАНИЧЕНО · ОБНОВЛЯЕТСЯ ЕЖЕДНЕВНО"
    wf = _font(10)
    ww = _tw(d, warn, wf)
    d.text((x + w - 40 - ww, y - 24), warn, font=wf, fill=DIM)


# ============================================================
# ЭКРАН 6: ИСТОРИЯ
# ============================================================
def render_history(user_id, balance, total_spent, history):
    img, d = _base_canvas(user_id, "история dc")

    body_y = 158
    body_h = CANVAS_H - M - PAD_Y - body_y - 30

    left_w = 360
    gap = 28
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(img, d, (left_x1, body_y, left_x2, body_y + body_h),
                     user_id, balance, total_spent,
                     bottom_block={
                         "label": "Всего записей",
                         "value": f"{len(history)}",
                         "icon": I_CLIPBOARD,
                         "color": BLUE,
                     })

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 28
    rx2 = right_x2 - 28

    _draw_right_head(d, rx1, body_y + 26, rx2, "История операций", "последние записи")

    list_y = body_y + 90
    rows = 8
    row_h = 62
    gap_row = 8

    ops = list(history[:rows])
    while len(ops) < rows:
        ops.append(None)

    for idx, op in enumerate(ops):
        y = list_y + idx * (row_h + gap_row)
        _draw_operation_row(d, img, rx1, y, rx2 - rx1, row_h, op)

    _draw_footer(d, "Показаны последние операции по DC", "стр. 6 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
