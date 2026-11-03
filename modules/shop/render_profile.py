# -*- coding: utf-8 -*-
"""
Pillow-рендер для трёх разделов профиля:
  · Инвентарь DC
  · Кастомные роли
  · О валюте
Стиль общий с profile_card.py и shop-рендерами.
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
FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
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
SILVER_BG  = (34, 38, 48)

GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)
GOLD      = (247, 201, 145)

GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)

CARD_BRD  = (74, 74, 79)

EMBED_COLOR = 0x2b2d31


# ============================================================
# FA5 ИКОНКИ
# ============================================================
I_GEM       = 0xf3a5
I_STAR      = 0xf005
I_USER      = 0xf007
I_IMAGE     = 0xf03e
I_BEZIER    = 0xf55b
I_SMILE     = 0xf118
I_PEN_NIB   = 0xf5ad
I_LAYERS    = 0xf5fd
I_MASKS     = 0xf630
I_TAG       = 0xf02b
I_BULLHORN  = 0xf0a1
I_BOLT      = 0xf0e7
I_DICE      = 0xf522
I_GIFT      = 0xf06b
I_CART      = 0xf07a
I_BAG       = 0xf290
I_COINS     = 0xf51e
I_TICKET    = 0xf145
I_CLOCK     = 0xf017
I_INFO      = 0xf05a
I_CHECK     = 0xf00c
I_CROWN     = 0xf521
I_MIC       = 0xf130
I_COMMENT   = 0xf075
I_CHART     = 0xf201
I_BRIEFCASE = 0xf0b1
I_ELLIPSIS  = 0xf141
I_MONEY     = 0xf53a
I_CUBE      = 0xf1b2
I_TROPHY    = 0xf091
I_SHOP      = 0xf54f
I_ARROW_L   = 0xf060


# маппинг кастомного type → FA-иконка
TYPE_FA = {
    "design":    I_IMAGE,
    "ads":       I_BULLHORN,
    "roles":     I_MASKS,
    "discounts": I_TAG,
    "boosts":    I_BOLT,
    "casino":    I_DICE,
    "gifts":     I_GIFT,
    "custom":    I_CROWN,
    "Кастом":    I_CROWN,
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


def _draw_stack_panel(base, d, box, radius=18):
    x1, y1, x2, y2 = box
    _alpha_fill(base, (x1 + 11, y1 + 11, x2 + 11, y2 + 11),
                (46, 46, 52), alpha=110, radius=radius)
    _alpha_fill(base, (x1 + 5, y1 + 5, x2 + 5, y2 + 5),
                (46, 46, 52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius,
                        fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=2)


def _draw_dashed_rect(d, box, radius, color, dash=10, gap=7, width=2):
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


def _sanitize(text: str, fallback: str = "") -> str:
    """
    Оставляет: ASCII, кириллицу, латиницу с диакритикой,
    распространённые спецсимволы. Убирает эмодзи и нестандартные
    unicode-глифы, которые могут не отрендериться в нашем шрифте.
    """
    if not text:
        return fallback
    allowed_special = set("—–‑‒―“”«»„‘’…№·•▪●◆◇■□")
    out = []
    for ch in text:
        cp = ord(ch)
        if 0x20 <= cp <= 0x7E:
            out.append(ch)
            continue
        if 0x0400 <= cp <= 0x04FF:
            out.append(ch)
            continue
        if 0x00C0 <= cp <= 0x017F:
            out.append(ch)
            continue
        if ch in allowed_special:
            out.append(ch)
            continue
        # всё остальное (эмодзи, иконки, странные unicode) — выкидываем
    result = "".join(out).strip()
    while "  " in result:
        result = result.replace("  ", " ")
    if not result:
        return fallback
    return result


def _hex_to_rgb(h: int) -> Tuple[int, int, int]:
    return ((h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF)


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
    lbl = uid_label.upper()
    uid = f"UID · {user_id}"
    w1 = _tw(d, lbl, _font(15))
    w2 = _tw(d, uid, _font(24))
    d.text((meta_r - w1, hy + 14), lbl, font=_font(15), fill=MUTED)
    d.text((meta_r - w2, hy + 38), uid, font=_font(24), fill=TEXT)

    sep_y = hy + logo_size + 20
    d.line((PAD_X, sep_y, CANVAS_W - M - PAD_X, sep_y),
           fill=STACK_HDR + (255,), width=2)

    return img, d


def _draw_footer(d, left_text: str, right_text: str = ""):
    y = CANVAS_H - M - PAD_Y + 4
    d.line((PAD_X, y - 10, CANVAS_W - M - PAD_X, y - 10),
           fill=STACK_HDR + (255,), width=2)
    _draw_icon(d, PAD_X + 12, y + 10, I_INFO, 16, DIM)
    d.text((PAD_X + 38, y), left_text, font=_font(13), fill=DIM)
    if right_text:
        pw = _tw(d, right_text, _font(13))
        d.text((CANVAS_W - M - PAD_X - pw, y), right_text, font=_font(13),
               fill=SILVER)


def _draw_left_panel(img, d, box, balance, total_spent, extra_blocks=None):
    _draw_stack_panel(img, d, box, radius=18)
    x1, y1, x2, y2 = box
    pad = 24

    bal_icon_size = 72
    ib_x = x1 + pad
    ib_y = y1 + pad

    _gradient_box(img, (ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                  SILVER, SILVER_DIM, alpha=42, radius=18)
    d.rounded_rectangle((ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                        radius=18, outline=SILVER + (140,), width=3)
    _draw_icon(d, ib_x + bal_icon_size // 2, ib_y + bal_icon_size // 2 + 1,
               I_GEM, 30, SILVER_HI)

    lbl_x = ib_x + bal_icon_size + 16
    d.text((lbl_x, ib_y + 6), "ТВОЙ БАЛАНС", font=_font(13), fill=MUTED)

    bal_str = _fmt(balance)
    val_font = _font(40)
    max_w = x2 - pad - lbl_x - 16
    while _tw(d, bal_str + " DC", val_font) > max_w and val_font.size > 22:
        val_font = _font(val_font.size - 2)
    d.text((lbl_x, ib_y + 26), bal_str, font=val_font, fill=TEXT)
    bw = _tw(d, bal_str, val_font)
    d.text((lbl_x + bw + 6, ib_y + 26 + val_font.size - 22),
           "DC", font=_font(18), fill=SILVER)

    sep_y = ib_y + bal_icon_size + 22
    d.line((x1 + pad, sep_y, x2 - pad, sep_y),
           fill=STACK_HDR + (255,), width=2)

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
                       blk.get("icon", I_CIRCLE_M if False else I_INFO), 22, bcolor)

            tx = ib2_x + icon_size + 14
            d.text((tx, by1 + 12), blk.get("label", "").upper(),
                   font=_font(12), fill=bcolor)
            bv = blk.get("value", "—")
            val_font = _font(18)
            max_w2 = bx2 - 16 - tx
            bv_shown = _ellipsis(d, bv, val_font, max_w2)
            d.text((tx, by1 + 36), bv_shown, font=val_font, fill=bcolor)


def _draw_right_head(d, x1, y1, x2, title: str, sub: str):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 46), radius=3,
                        fill=SILVER + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(28), fill=TEXT)
    sub_w = _tw(d, sub.upper(), _font(14))
    d.text((x2 - sub_w, y1 + 18), sub.upper(), font=_font(14), fill=MUTED)
    d.line((x1, y1 + 60, x2, y1 + 60), fill=STACK_HDR + (255,), width=2)


# ============================================================
# ЭКРАН 1: ИНВЕНТАРЬ DC
# ============================================================
def render_inventory(user_id: int, balance: int, total_spent: int,
                     purchases: List[Dict]) -> io.BytesIO:
    """
    purchases = [{"type": str, "value": str, "date": int}, ...]
    """
    img, d = _base_canvas(user_id, "инвентарь dc")

    body_y = 130
    body_h = CANVAS_H - M - PAD_Y - body_y - 40

    left_w = 380
    gap = 26
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        balance, total_spent,
        extra_blocks=[
            {
                "label": "Активных товаров",
                "value": f"{len(purchases)} шт.",
                "icon": I_BAG,
                "color": SILVER,
            },
            {
                "label": "Всего потрачено",
                "value": f"{_fmt(total_spent)} DC",
                "icon": I_COINS,
                "color": GREEN,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=18)
    rx1 = right_x1 + 26
    rx2 = right_x2 - 26

    _draw_right_head(d, rx1, body_y + 20, rx2,
                     "Инвентарь", "купленные товары · оформи в тикет")

    grid_y1 = body_y + 100
    grid_y2 = body_y + body_h - 22
    grid_h = grid_y2 - grid_y1
    cell_gap = 14
    cols, rows = 3, 2
    cell_w = (rx2 - rx1 - cell_gap * (cols - 1)) // cols
    cell_h = (grid_h - cell_gap * (rows - 1)) // rows

    if not purchases:
        box = (rx1, grid_y1, rx2, grid_y2)
        _draw_dashed_rect(d, box, 18, (58, 58, 64), dash=12, gap=8, width=2)

        icon_cx = (rx1 + rx2) // 2
        icon_cy = (grid_y1 + grid_y2) // 2 - 50
        _alpha_fill(img, (icon_cx - 55, icon_cy - 55, icon_cx + 55, icon_cy + 55),
                    SILVER, alpha=25, radius=26)
        _draw_icon(d, icon_cx, icon_cy, I_BAG, 48, SILVER)

        d.text((icon_cx, icon_cy + 90), "У тебя пока нет активных покупок",
               font=_font(26), fill=TEXT, anchor="mm")
        d.text((icon_cx, icon_cy + 128),
               "Загляни в каталог — там есть из чего выбрать.",
               font=_font(16), fill=MUTED, anchor="mm")
        d.text((icon_cx, icon_cy + 158),
               "После покупки товар появится здесь и его можно оформить в тикет.",
               font=_font(14), fill=DIM, anchor="mm")
    else:
        for idx in range(cols * rows):
            r = idx // cols
            c = idx % cols
            cx = rx1 + c * (cell_w + cell_gap)
            cy = grid_y1 + r * (cell_h + cell_gap)

            if idx < len(purchases):
                _draw_inv_tile(d, img, cx, cy, cell_w, cell_h, purchases[idx])
            else:
                _draw_dashed_rect(d, (cx, cy, cx + cell_w, cy + cell_h), 18,
                                  (36, 36, 42), dash=12, gap=8, width=2)
                _draw_icon(d, cx + cell_w // 2, cy + cell_h // 2, I_ELLIPSIS, 28, DARK)

    _draw_footer(d,
                 "Выбери товар и открой тикет через «Купить» → Diamond Coins",
                 f"показано {min(len(purchases), 6)} / {len(purchases)}")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _draw_inv_tile(d, img, x, y, w, h, p: Dict):
    d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                        fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)

    pad = 18
    ptype = p.get("type", "—")
    pvalue = _sanitize(p.get("value", "—"), fallback="Товар")
    pdate = p.get("date", 0)

    # Иконка
    icon_size = 52
    ib_x = x + pad
    ib_y = y + pad

    color = SILVER
    if ptype == "design":    color = GOLD
    elif ptype == "ads":     color = RED
    elif ptype == "roles":   color = PURPLE
    elif ptype == "discounts": color = GREEN
    elif ptype == "boosts":  color = BLUE

    icon_code = TYPE_FA.get(ptype, I_CUBE)

    _gradient_box(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                  color, color, alpha=35, radius=13)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=13, outline=color + (140,), width=2)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               icon_code, 24, color)

    # Название справа от иконки
    name_x = ib_x + icon_size + 14
    name_w = w - (name_x - x) - pad
    name_font = _font(18)
    name_shown = _ellipsis(d, pvalue, name_font, name_w)
    d.text((name_x, ib_y + 2), name_shown, font=name_font, fill=TEXT)

    # Тип капсом
    type_str = ptype.upper()
    d.text((name_x, ib_y + 28), type_str, font=_font(11), fill=MUTED)

    # Описание
    desc_y = ib_y + icon_size + 14
    desc_font = _font(12)
    desc_text = _inv_desc_by_type(ptype, pvalue)
    desc_lines = _wrap(d, desc_text, desc_font, w - pad * 2, max_lines=3)
    for i, line in enumerate(desc_lines):
        d.text((x + pad, desc_y + i * 17), line, font=desc_font, fill=MUTED)

    # Футер: дата + бейдж
    foot_y = y + h - 44
    d.line((x + pad, foot_y - 10, x + w - pad, foot_y - 10),
           fill=INNER_BRD + (255,), width=1)

    try:
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(pdate, timezone.utc)
        date_str = dt.strftime("%d.%m.%Y")
    except Exception:
        date_str = "—"
    d.text((x + pad, foot_y + 6), date_str, font=_font(12), fill=DIM)

    badge_text = "ОФОРМИТЬ"
    bf = _font(11)
    btw = _tw(d, badge_text, bf)
    bpad = 12
    bx = x + w - pad - btw - bpad * 2
    by = foot_y + 2
    d.rounded_rectangle((bx, by, bx + btw + bpad * 2, by + 26),
                        radius=7, fill=GREEN_BG + (255,),
                        outline=GREEN + (170,), width=1)
    d.text((bx + bpad, by + 7), badge_text, font=bf, fill=GREEN)


def _inv_desc_by_type(ptype: str, name: str) -> str:
    m = {
        "design":    "Уникальный дизайн от команды Diamond. Стиль и композиция согласуются в тикете.",
        "ads":       "Реклама в каналах Diamond. Расскажем о тебе или твоём проекте.",
        "roles":     "Особая роль сервера. Даёт свой стиль и доступ.",
        "discounts": "Применяется в тикете — подставится в заказ автоматически.",
        "boosts":    "Усилитель DC-заработка. Активируется сразу после покупки.",
        "casino":    "Предмет для казино. Применяется в следующей партии.",
        "gifts":     "Подарок DC другому участнику.",
    }
    return m.get(ptype, f"Товар «{name}» из магазина Diamond.")


# ============================================================
# ЭКРАН 2: КАСТОМНЫЕ РОЛИ
# ============================================================
def render_custom_roles(user_id: int, balance: int, total_spent: int,
                        roles_list: List[Dict]) -> io.BytesIO:
    """
    roles_list = [{
        "id": int, "name": str, "color": int (0..0xFFFFFF),
        "position": int, "mention": str
    }, ...]
    """
    img, d = _base_canvas(user_id, "кастомные роли")

    body_y = 130
    body_h = CANVAS_H - M - PAD_Y - body_y - 40

    left_w = 380
    gap = 26
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    max_pos = 0
    if roles_list:
        try:
            max_pos = max(r.get("position", 0) for r in roles_list)
        except Exception:
            max_pos = 0

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        balance, total_spent,
        extra_blocks=[
            {
                "label": "Кастомных ролей",
                "value": f"{len(roles_list)} шт.",
                "icon": I_MASKS,
                "color": PURPLE,
            },
            {
                "label": "Макс. позиция",
                "value": f"#{max_pos}" if max_pos else "—",
                "icon": I_CROWN,
                "color": SILVER,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=18)
    rx1 = right_x1 + 26
    rx2 = right_x2 - 26

    _draw_right_head(d, rx1, body_y + 20, rx2,
                     "Кастомные роли", "твои уникальные роли на сервере")

    list_y1 = body_y + 100
    row_h = 74
    gap_row = 10

    if not roles_list:
        box = (rx1, list_y1, rx2, body_y + body_h - 22)
        _draw_dashed_rect(d, box, 18, (58, 58, 64), dash=12, gap=8, width=2)

        icon_cx = (rx1 + rx2) // 2
        icon_cy = (list_y1 + body_y + body_h - 22) // 2 - 50
        _alpha_fill(img, (icon_cx - 55, icon_cy - 55, icon_cx + 55, icon_cy + 55),
                    PURPLE, alpha=25, radius=26)
        _draw_icon(d, icon_cx, icon_cy, I_MASKS, 48, PURPLE)

        d.text((icon_cx, icon_cy + 90), "У тебя пока нет кастомных ролей",
               font=_font(26), fill=TEXT, anchor="mm")
        d.text((icon_cx, icon_cy + 128),
               "Приобрести кастомную роль можно в каталоге DC-магазина.",
               font=_font(16), fill=MUTED, anchor="mm")
        d.text((icon_cx, icon_cy + 158),
               "Раздел «Особые роли» → «Кастомная роль».",
               font=_font(14), fill=DIM, anchor="mm")
    else:
        for idx, r in enumerate(roles_list[:8]):
            ry = list_y1 + idx * (row_h + gap_row)
            _draw_role_row(d, img, rx1, ry, rx2 - rx1, row_h, r)

    _draw_footer(d,
                 "Кастомные роли покупаются в разделе «Особые роли»",
                 f"показано {min(len(roles_list), 8)} / {len(roles_list)}")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _draw_role_row(d, img, x, y, w, h, r: Dict):
    d.rounded_rectangle((x, y, x + w, y + h), radius=14,
                        fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)

    pad = 18

    # Цвет роли
    color_int = int(r.get("color", 0) or 0)
    if color_int == 0:
        role_color = SILVER  # роли без цвета — серые
    else:
        role_color = _hex_to_rgb(color_int)
        # если цвет почти белый/чёрный — тоже нормально, оставляем
    role_color = tuple(min(255, max(0, c)) for c in role_color)

    # Кружок с цветом + FA-иконка маски
    dot_size = 52
    cx = x + pad + dot_size // 2
    cy = y + h // 2

    # Заливка круга цветом роли (низкая прозрачность)
    _alpha_fill(img,
                (cx - dot_size // 2, cy - dot_size // 2,
                 cx + dot_size // 2, cy + dot_size // 2),
                role_color, alpha=55, radius=dot_size // 2)
    # Обводка
    d.ellipse((cx - dot_size // 2, cy - dot_size // 2,
               cx + dot_size // 2, cy + dot_size // 2),
              outline=role_color + (255,), width=3)
    # FA маски внутри
    _draw_icon(d, cx, cy + 1, I_MASKS, 22, role_color)

    # Название роли (санитизированное)
    name_x = cx + dot_size // 2 + 16
    name = _sanitize(r.get("name", ""), fallback=f"Роль #{r.get('id', 0)}")
    name_font = _font(20)
    max_name_w = w - (name_x - x) - 320
    name_shown = _ellipsis(d, name, name_font, max_name_w)
    name_y = y + h // 2 - 22
    d.text((name_x, name_y), name_shown, font=name_font, fill=TEXT)

    # Подпись снизу
    sub_y = name_y + 26
    pos = r.get("position", 0)
    sub_text = f"Позиция в иерархии: #{pos}" if pos else "Кастомная роль"
    d.text((name_x, sub_y), sub_text, font=_font(12), fill=MUTED)

    # Позиция (бейдж справа)
    pos_text = f"#{pos}" if pos else "—"
    pf = _font(16)
    pw = _tw(d, pos_text, pf)
    pos_pad = 12
    bx = x + w - pad - pw - pos_pad * 2 - 180
    by = y + h // 2 - 18
    d.rounded_rectangle((bx, by, bx + pw + pos_pad * 2, by + 36),
                        radius=8,
                        fill=SILVER_BG + (255,),
                        outline=SILVER + (150,), width=1)
    d.text((bx + pos_pad, by + 8), pos_text, font=pf, fill=SILVER_HI)

    # ID роли справа внизу
    rid = str(r.get("id", "—"))
    id_text = f"ID · {rid}"
    idf = _font(12)
    idw = _tw(d, id_text, idf)
    d.text((x + w - pad - idw, y + h // 2 + 6), id_text, font=idf, fill=DIM)


# ============================================================
# ЭКРАН 3: О ВАЛЮТЕ
# ============================================================
def render_about_coin(user_id: int, balance: int, total_spent: int) -> io.BytesIO:
    img, d = _base_canvas(user_id, "о валюте")

    body_y = 130
    body_h = CANVAS_H - M - PAD_Y - body_y - 40

    left_w = 380
    gap = 26
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        balance, total_spent,
        extra_blocks=[
            {
                "label": "Всего потрачено",
                "value": f"{_fmt(total_spent)} DC",
                "icon": I_COINS,
                "color": GREEN,
            },
            {
                "label": "Где купить",
                "value": "Каталог → DC",
                "icon": I_SHOP,
                "color": BLUE,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=18)
    rx1 = right_x1 + 26
    rx2 = right_x2 - 26

    _draw_right_head(d, rx1, body_y + 20, rx2,
                     "Diamond Coin", "внутренняя валюта сервера")

    # Верхний блок — большая иконка + что это
    top_y = body_y + 100
    big_icon = 96
    ix = rx1
    iy = top_y

    _gradient_box(img, (ix, iy, ix + big_icon, iy + big_icon),
                  SILVER, SILVER_DIM, alpha=40, radius=22)
    d.rounded_rectangle((ix, iy, ix + big_icon, iy + big_icon),
                        radius=22, outline=SILVER + (170,), width=3)
    _draw_icon(d, ix + big_icon // 2, iy + big_icon // 2 + 1, I_GEM, 42, SILVER_HI)

    tx = ix + big_icon + 24
    tx_max = rx2 - tx

    d.text((tx, iy + 4), "ЧТО ЭТО ТАКОЕ", font=_font(13), fill=SILVER)

    d.text((tx, iy + 26), "Diamond Coin",
           font=_font(32), fill=TEXT)

    desc = (
        "Внутренняя валюта сервера. Зарабатывай активностью и трать "
        "на товары в DC-магазине. Баланс, история и покупки — всё в твоём профиле."
    )
    desc_font = _font(15)
    desc_lines = _wrap(d, desc, desc_font, tx_max, max_lines=3)
    for i, line in enumerate(desc_lines):
        d.text((tx, iy + 70 + i * 22), line, font=desc_font, fill=TEXT_SOFT)

    # Сетка "как заработать"
    earn_y = top_y + big_icon + 34
    d.text((rx1, earn_y), "КАК ЗАРАБОТАТЬ", font=_font(14), fill=MUTED)
    d.line((rx1, earn_y + 26, rx2, earn_y + 26),
           fill=STACK_HDR + (255,), width=2)

    grid_y = earn_y + 38
    cell_gap = 12
    cols = 2
    cell_w = (rx2 - rx1 - cell_gap * (cols - 1)) // cols
    cell_h = 72

    cells = [
        ("Сообщения",       "1 DC за 10 сообщений · лимит 30 DC/день", I_COMMENT, GREEN),
        ("Голосовые каналы","3 DC за час · лимит 15 DC/день",          I_MIC,     BLUE),
        ("Отзывы",          "+15 DC за одобренный отзыв",               I_STAR,    GOLD),
        ("Ежедневный бонус","+3 DC каждый день с ролью «Клуб»",         I_GIFT,    PURPLE),
        ("Казино",          "Рулетка, блэкджек, монетка",               I_DICE,    GREEN),
        ("Работа в магазине","Зарплата и аванс 15 и 29 числа",          I_BRIEFCASE, BLUE),
    ]

    for i, (k, v, icon, color) in enumerate(cells):
        r = i // cols
        c = i % cols
        cx1 = rx1 + c * (cell_w + cell_gap)
        cy1 = grid_y + r * (cell_h + cell_gap)

        d.rounded_rectangle((cx1, cy1, cx1 + cell_w, cy1 + cell_h),
                            radius=12, fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)

        icon_size = 44
        ib_x = cx1 + 14
        ib_y = cy1 + (cell_h - icon_size) // 2

        _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                    color, alpha=45, radius=11)
        _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
                   icon, 22, color)

        txx = ib_x + icon_size + 12
        d.text((txx, cy1 + 14), k, font=_font(14), fill=TEXT)
        v_shown = _ellipsis(d, v, _font(11), cell_w - (txx - cx1) - 14)
        d.text((txx, cy1 + 38), v_shown, font=_font(11), fill=MUTED)

    # Нижняя плашка «Где потратить»
    spend_y = grid_y + cell_h * 3 + cell_gap * 2 + 16
    spend_h = 68

    _gradient_box(img, (rx1, spend_y, rx2, spend_y + spend_h),
                  SILVER, SILVER_DIM, alpha=15, radius=14)
    d.rounded_rectangle((rx1, spend_y, rx2, spend_y + spend_h),
                        radius=14, outline=SILVER + (140,), width=2)

    icon_size = 44
    ib_x = rx1 + 16
    ib_y = spend_y + (spend_h - icon_size) // 2
    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                SILVER, alpha=50, radius=11)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               I_CART, 22, SILVER_HI)

    txx = ib_x + icon_size + 14
    d.text((txx, spend_y + 12), "ГДЕ ПОТРАТИТЬ?",
           font=_font(12), fill=SILVER)
    spend_desc = (
        "Открой канал витрины, нажми «Каталог» → выбери «Diamond Coin». "
        "Там роли, дизайн, скидки, бусты, казино-предметы и подарки."
    )
    sd_lines = _wrap(d, spend_desc, _font(12), rx2 - txx - 20, max_lines=2)
    for i, line in enumerate(sd_lines):
        d.text((txx, spend_y + 34 + i * 16), line, font=_font(12), fill=MUTED)

    _draw_footer(d, "Все цены указаны в Diamond Coins", "каталог → Diamond Coin")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
