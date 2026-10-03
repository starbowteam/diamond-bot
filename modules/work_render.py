# -*- coding: utf-8 -*-
"""
Pillow-рендер панели «Кодекс магазина»:
  · render_work_salary  — Зарплата и аванс
  · render_work_top     — Топ Sales Manager
  · render_work_tickets — Правила по тикетам
Размер 1800×1000, стиль 1:1 с shop/render.py и clan/render.py.
Все суммы зарплат — увеличены ×2.5.
"""
import io
import os
from typing import List, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, logger


# ============================================================
# ШРИФТЫ
# ============================================================
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
SILVER_BG  = (34, 38, 48)

GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)
GOLD      = (247, 201, 145)
BRONZE    = (209, 146, 96)

GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)
GOLD_BG   = (40, 32, 21)

CARD_BRD  = (74, 74, 79)

EMBED_COLOR = 0x2b2d31


def _lighten(c, amount: float = 0.4):
    amount = max(0.0, min(1.0, amount))
    return (
        min(int(c[0] + (255 - c[0]) * amount), 255),
        min(int(c[1] + (255 - c[1]) * amount), 255),
        min(int(c[2] + (255 - c[2]) * amount), 255),
    )


# ============================================================
# FA5-ИКОНКИ
# ============================================================
I_GEM       = 0xf3a5
I_STAR      = 0xf005
I_CROWN     = 0xf521
I_TROPHY    = 0xf091
I_MEDAL     = 0xf5a2
I_COINS     = 0xf51e
I_USERS     = 0xf0c0
I_USER      = 0xf007
I_USER_TIE  = 0xf508
I_HAND      = 0xf4c0
I_CHART     = 0xf201
I_CLOCK     = 0xf017
I_LIST      = 0xf03a
I_INFO      = 0xf05a
I_CHECK     = 0xf00c
I_XMARK     = 0xf00d
I_PERCENT   = 0xf295
I_HISTORY   = 0xf1da
I_FIRE      = 0xf06d
I_GIFT      = 0xf06b
I_MESSAGE   = 0xf075
I_GAUGE     = 0xf624
I_SHIELD    = 0xf3ed
I_WARNING   = 0xf071
I_PEN       = 0xf304
I_SEARCH    = 0xf002
I_BRIEFCASE = 0xf0b1
I_CALENDAR  = 0xf133
I_BOOK      = 0xf02d
I_GAVEL     = 0xf0e3


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


def _wrap(d, text, font, max_w, max_lines=4):
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
                        outline=STACK_BRD + (255,), width=3)


# ============================================================
# КАРКАС 1800×1000
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
                        fill=(58, 58, 64) + (255,),
                        outline=(94, 94, 100) + (255,), width=2)
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


def _draw_footer(d, left_text: str, page: str):
    y = CANVAS_H - M - PAD_Y + 6
    d.line((PAD_X, y - 10, CANVAS_W - M - PAD_X, y - 10),
           fill=STACK_HDR + (255,), width=2)
    _draw_icon(d, PAD_X + 12, y + 10, I_INFO, 16, DIM)
    d.text((PAD_X + 38, y), left_text, font=_font(15), fill=DIM)
    pw = _tw(d, page, _font(15))
    d.text((CANVAS_W - M - PAD_X - pw, y), page, font=_font(15), fill=DIM)


def _draw_right_head(d, x1, y1, x2, title: str, sub: str):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 50), radius=3,
                        fill=SILVER + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(32), fill=TEXT)
    sub_w = _tw(d, sub.upper(), _font(15))
    d.text((x2 - sub_w, y1 + 20), sub.upper(), font=_font(15), fill=MUTED)
    d.line((x1, y1 + 66, x2, y1 + 66), fill=STACK_HDR + (255,), width=2)


def _draw_left_panel(img, d, box, extra_blocks=None, header_icon: int = I_GEM):
    _draw_stack_panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 28

    icon_size = 96
    ib_x = x1 + pad
    ib_y = y1 + pad

    _gradient_box(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                  SILVER, SILVER_DIM, alpha=42, radius=24)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=24, outline=SILVER + (200,), width=3)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               header_icon, 40, SILVER_HI)

    lbl_x = ib_x + icon_size + 22
    d.text((lbl_x, ib_y + 14), "КОДЕКС", font=_font(14), fill=MUTED)
    d.text((lbl_x, ib_y + 38), "МАГАЗИНА", font=_font(22), fill=TEXT)

    sep_y = ib_y + icon_size + 26
    d.line((x1 + pad, sep_y, x2 - pad, sep_y),
           fill=STACK_HDR + (255,), width=2)

    if extra_blocks:
        bb_h = 92
        bb_gap = 12
        top_y = sep_y + 26

        for i, blk in enumerate(extra_blocks):
            by1 = top_y + i * (bb_h + bb_gap)
            by2 = by1 + bb_h
            bx1 = x1 + pad
            bx2 = x2 - pad

            base_color = blk.get("color", SILVER)
            text_color = _lighten(base_color, 0.45)
            border_color = _lighten(base_color, 0.25)

            _gradient_box(img, (bx1, by1, bx2, by2),
                          base_color, base_color, alpha=30, radius=15)
            d.rounded_rectangle((bx1, by1, bx2, by2),
                                radius=15, outline=border_color + (255,), width=3)
            d.rounded_rectangle((bx1 + 4, by1 + 12, bx1 + 8, by2 - 12),
                                radius=2, fill=base_color + (255,))

            icon_size = 50
            ib2_x = bx1 + 20
            ib2_y = by1 + (bb_h - icon_size) // 2
            _alpha_fill(img, (ib2_x, ib2_y, ib2_x + icon_size, ib2_y + icon_size),
                        base_color, alpha=70, radius=13)
            d.rounded_rectangle((ib2_x, ib2_y, ib2_x + icon_size, ib2_y + icon_size),
                                radius=13, outline=border_color + (200,), width=2)
            _draw_icon(d, ib2_x + icon_size // 2, ib2_y + icon_size // 2 + 1,
                       blk.get("icon", I_INFO), 24, base_color)

            tx = ib2_x + icon_size + 16
            d.text((tx, by1 + 14), blk.get("label", "").upper(),
                   font=_font(13), fill=text_color)
            bv = blk.get("value", "—")
            val_font = _font(24)
            max_w2 = bx2 - 18 - tx
            bv_shown = _ellipsis(d, bv, val_font, max_w2)
            d.text((tx, by1 + 42), bv_shown, font=val_font, fill=base_color)


# ============================================================
# SCREEN 1: ЗАРПЛАТА
# ============================================================
# 👇 Все суммы ×2.5. Роли и цвета — реальные.
SALARY_ROLES = [
    {
        "role_id": 1471844291595731016,
        "name": "Control Diamond",
        "tag": "CONTROL",
        "advance": 750,
        "salary": 1750,
        "color": (0xcd, 0xce, 0xd1),
        "icon": I_CROWN,
    },
    {
        "role_id": 1513935883475226796,
        "name": "Assistant",
        "tag": "ASSIST",
        "advance": 550,
        "salary": 1250,
        "color": (0xbe, 0x85, 0x85),
        "icon": I_USER_TIE,
    },
    {
        "role_id": 1154757071330365490,
        "name": "Sales Manager",
        "tag": "SALES",
        "advance": 550,
        "salary": 1250,
        "color": (0x39, 0xf4, 0x7b),
        "icon": I_HAND,
    },
    {
        "role_id": 1471190371181789234,
        "name": "Employer",
        "tag": "EMPLOY",
        "advance": 450,
        "salary": 1000,
        "color": (0x5c, 0x5c, 0x5c),
        "icon": I_USERS,
    },
    {
        "role_id": 1457964854441672806,
        "name": "Advertiser",
        "tag": "ADVERT",
        "advance": 375,
        "salary": 875,
        "color": (0xb1, 0xc5, 0xf6),
        "icon": I_SEARCH,
    },
]


def _draw_salary_card(img, d, x, y, w, h, role_data: dict):
    color = role_data["color"]
    light = _lighten(color, 0.4)
    border = _lighten(color, 0.2)

    d.rounded_rectangle((x - 3, y - 3, x + w + 3, y + h + 3),
                        radius=19, fill=(8, 8, 10) + (255,))
    _gradient_box(img, (x, y, x + w, y + h), color, color, alpha=28, radius=16)
    d.rounded_rectangle((x, y, x + w, y + h),
                        radius=16, outline=border + (220,), width=3)

    d.rounded_rectangle((x + 6, y + 14, x + 11, y + h - 14),
                        radius=2, fill=color + (255,))

    icon_size = 60
    ib_x = x + 26
    ib_y = y + (h - icon_size) // 2

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                color, alpha=75, radius=15)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=15, outline=light + (230,), width=3)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               role_data["icon"], 28, light)

    tx = ib_x + icon_size + 20

    d.text((tx, y + h // 2 - 26), role_data["name"].upper(),
           font=_font(24), fill=light)

    tag = role_data["tag"]
    tag_font = _font(11)
    tag_w = _tw(d, tag, tag_font)
    tag_h = 20
    tag_x = tx
    tag_y = y + h // 2 + 6
    _alpha_fill(img, (tag_x, tag_y, tag_x + tag_w + 20, tag_y + tag_h),
                color, alpha=80, radius=6)
    d.rounded_rectangle((tag_x, tag_y, tag_x + tag_w + 20, tag_y + tag_h),
                        radius=6, outline=light + (200,), width=1)
    d.text((tag_x + 10, tag_y + 4), tag, font=tag_font, fill=light)

    right_x2 = x + w - 24
    box_w = 220
    box_h = 62
    gap_inner = 20

    adv_x1 = right_x2 - 2 * box_w - gap_inner
    adv_y1 = y + (h - box_h) // 2
    adv_x2 = adv_x1 + box_w

    sal_x1 = adv_x2 + gap_inner
    sal_x2 = right_x2

    # Аванс
    _alpha_fill(img, (adv_x1, adv_y1, adv_x2, adv_y1 + box_h),
                BLUE, alpha=40, radius=12)
    d.rounded_rectangle((adv_x1, adv_y1, adv_x2, adv_y1 + box_h),
                        radius=12, outline=BLUE + (200,), width=2)

    d.text((adv_x1 + 14, adv_y1 + 8), "АВАНС",
           font=_font(11), fill=_lighten(BLUE, 0.4))

    adv_str = _fmt(role_data["advance"])
    adv_font = _font(28)
    d.text((adv_x1 + 14, adv_y1 + 26), adv_str,
           font=adv_font, fill=SILVER_HI)
    aw = _tw(d, adv_str, adv_font)
    d.text((adv_x1 + 14 + aw + 6, adv_y1 + 26 + 28 - 18),
           "DC", font=_font(14), fill=BLUE)

    # Зарплата
    _alpha_fill(img, (sal_x1, adv_y1, sal_x2, adv_y1 + box_h),
                GREEN, alpha=45, radius=12)
    d.rounded_rectangle((sal_x1, adv_y1, sal_x2, adv_y1 + box_h),
                        radius=12, outline=GREEN + (200,), width=2)

    d.text((sal_x1 + 14, adv_y1 + 8), "ЗАРПЛАТА",
           font=_font(11), fill=_lighten(GREEN, 0.4))

    sal_str = _fmt(role_data["salary"])
    sal_font = _font(28)
    d.text((sal_x1 + 14, adv_y1 + 26), sal_str,
           font=sal_font, fill=SILVER_HI)
    sw = _tw(d, sal_str, sal_font)
    d.text((sal_x1 + 14 + sw + 6, adv_y1 + 26 + 28 - 18),
           "DC", font=_font(14), fill=GREEN)


def render_work_salary(user_id: int) -> io.BytesIO:
    img, d = _base_canvas(user_id, "кодекс · зарплата")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        extra_blocks=[
            {
                "label": "Дата аванса",
                "value": "15 число",
                "icon": I_CALENDAR,
                "color": BLUE,
            },
            {
                "label": "Дата зарплаты",
                "value": "29 число",
                "icon": I_CALENDAR,
                "color": GREEN,
            },
            {
                "label": "Ролей в системе",
                "value": f"{len(SALARY_ROLES)}",
                "icon": I_USERS,
                "color": SILVER,
            },
        ],
        header_icon=I_COINS,
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Зарплата и аванс",
                     "выплаты дважды в месяц")

    list_y = body_y + 118
    list_bottom = body_y + body_h - 22
    gap_card = 12

    n = max(len(SALARY_ROLES), 1)
    card_h = (list_bottom - list_y - gap_card * (n - 1)) // n
    card_h = max(card_h, 100)

    for i, role in enumerate(SALARY_ROLES):
        cy = list_y + i * (card_h + gap_card)
        _draw_salary_card(img, d, rx1, cy, rx2 - rx1, card_h, role)

    _draw_footer(d, "Зарплата начисляется в Diamond Coins", "стр. 1 / 3")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# SCREEN 2: ТОП SALES MANAGER
# ============================================================
def _draw_staff_row(img, d, x, y, w, h, rank: int,
                    name: str, closed: int, avg_rating: float,
                    has_rating: bool):
    if rank == 1:
        medal_color = GOLD
    elif rank == 2:
        medal_color = SILVER
    elif rank == 3:
        medal_color = BRONZE
    else:
        medal_color = DIM

    _gradient_box(img, (x, y, x + w, y + h), medal_color, medal_color,
                  alpha=15 if rank > 3 else 25, radius=14)
    d.rounded_rectangle((x, y, x + w, y + h),
                        radius=14, outline=medal_color + (170,), width=2)

    badge_size = 52
    bx = x + 18
    by = y + (h - badge_size) // 2

    _alpha_fill(img, (bx, by, bx + badge_size, by + badge_size),
                medal_color, alpha=70, radius=14)
    d.rounded_rectangle((bx, by, bx + badge_size, by + badge_size),
                        radius=14, outline=medal_color + (220,), width=2)

    if rank <= 3:
        _draw_icon(d, bx + badge_size // 2, by + badge_size // 2 + 1,
                   I_MEDAL, 26, medal_color)
    else:
        num_str = str(rank)
        num_font = _font(22)
        nw = _tw(d, num_str, num_font)
        d.text((bx + badge_size // 2 - nw // 2,
                by + badge_size // 2 - num_font.size // 2 - 2),
               num_str, font=num_font, fill=medal_color)

    tx = bx + badge_size + 18
    name_str = f"@{name}"
    name_font = _font(24)
    max_name_w = (x + w - 30) - tx - 460
    name_shown = _ellipsis(d, name_str, name_font, max_name_w)
    d.text((tx, y + h // 2 - 18), name_shown, font=name_font, fill=TEXT)

    closed_x = x + w - 470
    d.text((closed_x, y + h // 2 - 30), "ЗАКРЫТО",
           font=_font(11), fill=MUTED)
    closed_str = str(closed)
    d.text((closed_x, y + h // 2 - 10), closed_str,
           font=_font(26), fill=medal_color if rank <= 3 else SILVER_HI)

    rating_x = x + w - 240
    d.text((rating_x, y + h // 2 - 30), "РЕЙТИНГ",
           font=_font(11), fill=MUTED)

    if has_rating:
        rating_str = f"{avg_rating:.1f}"
        rating_color = GOLD if avg_rating >= 4.5 else (
            GREEN if avg_rating >= 3.5 else (
                BLUE if avg_rating >= 2.5 else RED
            )
        )
        d.text((rating_x, y + h // 2 - 10), rating_str,
               font=_font(26), fill=rating_color)
        rw = _tw(d, rating_str, _font(26))
        _draw_icon(d, rating_x + rw + 18, y + h // 2 + 4,
                   I_STAR, 16, rating_color)
    else:
        d.text((rating_x, y + h // 2 - 10), "—",
               font=_font(26), fill=DIM)


def render_work_top(user_id: int, staff_list: List[Dict]) -> io.BytesIO:
    img, d = _base_canvas(user_id, "кодекс · топ")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    total = len(staff_list)
    best_name = "—"
    if staff_list:
        best = staff_list[0]
        best_name = f"@{best.get('user_name', '—')}"

    with_rating = [s for s in staff_list if s.get("ratings_count", 0) > 0]
    avg_all = 0.0
    if with_rating:
        avg_all = sum(s["total_rating"] / s["ratings_count"]
                      for s in with_rating) / len(with_rating)

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        extra_blocks=[
            {
                "label": "Менеджеров",
                "value": f"{total}",
                "icon": I_USERS,
                "color": SILVER,
            },
            {
                "label": "Работник недели",
                "value": best_name,
                "icon": I_CROWN,
                "color": GOLD,
            },
            {
                "label": "Средний рейтинг",
                "value": f"{avg_all:.1f}" if avg_all else "—",
                "icon": I_STAR,
                "color": GREEN if avg_all >= 4 else BLUE,
            },
        ],
        header_icon=I_TROPHY,
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Топ Sales Manager",
                     "живой рейтинг · закрытые заказы")

    list_y = body_y + 118
    list_bottom = body_y + body_h - 22
    gap_row = 10

    rows = 8
    row_h = (list_bottom - list_y - gap_row * (rows - 1)) // rows
    row_h = max(row_h, 60)

    if not staff_list:
        # Заглушка — БЕЗ ошибочного импорта
        box = (rx1, list_y, rx2, list_bottom)
        d.rounded_rectangle(box, radius=16,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)

        icon_cx = (rx1 + rx2) // 2
        icon_cy = (list_y + list_bottom) // 2 - 40
        _alpha_fill(img, (icon_cx - 50, icon_cy - 50, icon_cx + 50, icon_cy + 50),
                    SILVER, alpha=25, radius=22)
        _draw_icon(d, icon_cx, icon_cy, I_TROPHY, 44, SILVER)
        d.text((icon_cx, list_y + (list_bottom - list_y) // 2 + 50),
               "Пока нет данных", font=_font(26), fill=TEXT, anchor="mm")
        d.text((icon_cx, list_y + (list_bottom - list_y) // 2 + 88),
               "Как только менеджеры начнут закрывать заказы — появятся здесь.",
               font=_font(15), fill=MUTED, anchor="mm")
    else:
        for i, s in enumerate(staff_list[:rows]):
            cy = list_y + i * (row_h + gap_row)

            closed = s.get("closed_tickets", 0)
            tr = s.get("total_rating", 0)
            rc = s.get("ratings_count", 0)
            avg = tr / rc if rc else 0.0

            _draw_staff_row(
                img, d, rx1, cy, rx2 - rx1, row_h,
                rank=i + 1,
                name=s.get("user_name", s.get("user_id", "—")),
                closed=closed,
                avg_rating=avg,
                has_rating=(rc > 0),
            )

    _draw_footer(d, "Сортировка: закрытые заказы → рейтинг", "стр. 2 / 3")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# SCREEN 3: ПРАВИЛА ПО ТИКЕТАМ
# ============================================================
def _draw_rule_card(img, d, x, y, w, h, rule: dict):
    color = rule["color"]
    light = _lighten(color, 0.4)
    border = _lighten(color, 0.2)

    d.rounded_rectangle((x - 3, y - 3, x + w + 3, y + h + 3),
                        radius=19, fill=(8, 8, 10) + (255,))
    _gradient_box(img, (x, y, x + w, y + h), color, color, alpha=18, radius=16)
    d.rounded_rectangle((x, y, x + w, y + h),
                        radius=16, outline=border + (220,), width=3)

    icon_size = 60
    ib_x = x + 24
    ib_y = y + 22

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                color, alpha=75, radius=15)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=15, outline=light + (230,), width=3)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               rule["icon"], 28, light)

    tx = ib_x + icon_size + 20
    d.text((tx, y + 26), rule["title"].upper(),
           font=_font(22), fill=light)

    d.text((tx, y + 58), rule.get("subtitle", "").upper(),
           font=_font(12), fill=MUTED)

    text_font = _font(16)
    lines = _wrap(d, rule["text"], text_font, w - 48, max_lines=4)
    text_y = y + 100
    for i, line in enumerate(lines):
        d.text((x + 24, text_y + i * 24), line, font=text_font, fill=TEXT_SOFT)

    # 👇 Пример — теперь в цвете карточки (без оранжевого)
    example = rule.get("example")
    if example:
        ex_y = text_y + len(lines) * 24 + 12
        ex_font = _font(15)
        ex_w = _tw(d, example, ex_font) + 60
        ex_h = 36

        # фон — в цвете правила, приглушённый
        _alpha_fill(img, (x + 24, ex_y, x + 24 + ex_w, ex_y + ex_h),
                    color, alpha=45, radius=9)
        d.rounded_rectangle((x + 24, ex_y, x + 24 + ex_w, ex_y + ex_h),
                            radius=9, outline=light + (200,), width=2)

        # иконка «инфо» в цвете правила
        _draw_icon(d, x + 24 + 16, ex_y + ex_h // 2, I_INFO, 14, light)
        d.text((x + 24 + 34, ex_y + 9), example, font=ex_font, fill=light)


def render_work_tickets(user_id: int) -> io.BytesIO:
    img, d = _base_canvas(user_id, "кодекс · правила")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        extra_blocks=[
            {
                "label": "Строго для",
                "value": "Sales Manager",
                "icon": I_USER_TIE,
                "color": BLUE,
            },
            {
                "label": "Нарушение",
                "value": "выговор",
                "icon": I_WARNING,
                "color": RED,
            },
            {
                "label": "Обязательно",
                "value": "к прочтению",
                "icon": I_CHECK,
                "color": GREEN,
            },
        ],
        header_icon=I_BOOK,
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Правила по тикетам",
                     "регламент для sales manager")

    items_y = body_y + 118
    items_bottom = body_y + body_h - 22
    n = 4
    gap_item = 12
    item_h = (items_bottom - items_y - gap_item * (n - 1)) // n
    item_h = max(item_h, 140)

    rules = [
        {
            "icon": I_HAND,
            "title": "Вежливость и споры",
            "subtitle": "правило №1",
            "text": (
                "Отвечаем вежливо, спорные ситуации решаем через "
                "главного администратора. Адекватность в тикетах "
                "должна быть всегда — если покупатель неадекватен, "
                "сообщить об этом старшему."
            ),
            "color": GREEN,
        },
        {
            "icon": I_PEN,
            "title": "Название тикета",
            "subtitle": "правило №2",
            "text": (
                "Название должно полностью отображать товар. "
                "Указываем по схеме Категория-Подкатегория-Подкатегория. "
                "Иные названия караются выговором."
            ),
            "color": SILVER,
            "example": "Например: Дискорд-нитро-1м",
        },
        {
            "icon": I_CHECK,
            "title": "Кнопка «Оплата»",
            "subtitle": "правило №3",
            "text": (
                "Кнопкой «Оплата» можно пользоваться только после "
                "фактического подтверждения оплаты покупателем. "
                "До подтверждения — кнопка не нажимается."
            ),
            "color": BLUE,
        },
        {
            "icon": I_WARNING,
            "title": "Ответственность",
            "subtitle": "правило №4",
            "text": (
                "За нарушение любого из пунктов выше — выговор. "
                "Систематические нарушения ведут к снятию "
                "с должности Sales Manager."
            ),
            "color": RED,
        },
    ]

    for i, rule in enumerate(rules):
        cy = items_y + i * (item_h + gap_item)
        _draw_rule_card(img, d, rx1, cy, rx2 - rx1, item_h, rule)

    _draw_footer(d, "Обязательно к прочтению каждым менеджером", "стр. 3 / 3")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
