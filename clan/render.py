# clan/render.py
# -*- coding: utf-8 -*-
"""
Pillow-рендер 6 панелей клановой лиги Diamond.
Стиль 1:1 с modules/shop/render.py — стек-панели, FA-иконки, палитра Diamond.
"""
import io
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple

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


# ============================================================
# ЦВЕТА КЛАНОВ (жёстко, независимо от БД)
# ============================================================
CLAN_COLORS_DARK = {
    1: (0x74, 0x94, 0x72),   # Окаменелости — тёмно-зелёный
    2: (0xaa, 0x8a, 0xe7),   # Сияние — фиолетовый
    3: (0x87, 0x99, 0xae),   # Кристализация — светло-голубой
}

CLAN_COLORS_LIGHT = {
    1: (0xb3, 0xe1, 0xb9),   # Окаменелости — светлый зелёный
    2: (0xcb, 0xb8, 0xf0),   # Сияние — светлый фиолетовый
    3: (0xa8, 0xc4, 0xd8),   # Кристализация — светлый голубой
}


def _clan_color(clan: Optional[dict]) -> Tuple[int, int, int]:
    """Тёмный акцентный цвет клана."""
    if not clan:
        return SILVER
    cid = int(clan.get("id", 0))
    return CLAN_COLORS_DARK.get(cid, SILVER)


def _clan_light(clan: Optional[dict]) -> Tuple[int, int, int]:
    """Светлый цвет клана — для текста."""
    if not clan:
        return SILVER_HI
    cid = int(clan.get("id", 0))
    return CLAN_COLORS_LIGHT.get(cid, SILVER_HI)


def _lighten(c, amount: float = 0.4):
    amount = max(0.0, min(1.0, amount))
    return (
        min(int(c[0] + (255 - c[0]) * amount), 255),
        min(int(c[1] + (255 - c[1]) * amount), 255),
        min(int(c[2] + (255 - c[2]) * amount), 255),
    )


def _darken(c, amount: float = 0.4):
    amount = max(0.0, min(1.0, amount))
    return (
        max(int(c[0] * (1 - amount)), 0),
        max(int(c[1] * (1 - amount)), 0),
        max(int(c[2] * (1 - amount)), 0),
    )


# ============================================================
# FA5-ИКОНКИ
# ============================================================
I_GEM        = 0xf3a5
I_STAR       = 0xf005
I_CROWN      = 0xf521
I_TROPHY     = 0xf091
I_MEDAL      = 0xf5a2
I_COINS      = 0xf51e
I_USERS      = 0xf0c0
I_USER       = 0xf007
I_HAND       = 0xf4c0
I_CHART      = 0xf201
I_CLOCK      = 0xf017
I_LIST       = 0xf03a
I_INFO       = 0xf05a
I_CHECK      = 0xf00c
I_PERCENT    = 0xf295
I_HISTORY    = 0xf1da
I_FIRE       = 0xf06d
I_GIFT       = 0xf06b
I_DICE       = 0xf522
I_MESSAGE    = 0xf075
I_GAUGE      = 0xf624
I_MOUNTAIN   = 0xf6fc
I_CUBE       = 0xf1b2
I_CALENDAR   = 0xf133
I_SHIELD     = 0xf3ed
I_BOLT       = 0xf0e7
I_LOCK       = 0xf023


REASON_FA = [
    ("рулетк",    I_TROPHY),
    ("блэкдж",    I_DICE),
    ("монет",     I_COINS),
    ("квест",     I_STAR),
    ("отзыв",     I_STAR),
    ("зарплат",   I_HAND),
    ("аванс",     I_HAND),
    ("покупк",    I_GIFT),
    ("акци",      I_FIRE),
    ("подарок",   I_GIFT),
    ("ежеднев",   I_GIFT),
    ("клан",      I_GEM),
    ("копилк",    I_GEM),
    ("сообщен",   I_MESSAGE),
    ("голос",     I_MESSAGE),
    ("актив",     I_MESSAGE),
]


def _reason_icon(reason: str) -> int:
    r = (reason or "").lower()
    for key, code in REASON_FA:
        if key in r:
            return code
    return I_COINS


CLAN_FA = {
    1: I_MOUNTAIN,
    2: I_STAR,
    3: I_GEM,
}


def _clan_icon(clan: Optional[dict]) -> int:
    if not clan:
        return I_GEM
    return CLAN_FA.get(int(clan.get("id", 0)), I_GEM)


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


def _draw_dashed_rect(d, box, radius, color, dash=10, gap=8, width=2):
    x1, y1, x2, y2 = box
    r = radius

    def dash_line(p1, p2):
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = (dx * dx + dy * dy) ** 0.5
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


def _draw_left_panel(img, d, box, balance, extra_blocks=None):
    _draw_stack_panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 28

    # ── БАЛАНС ──
    bal_icon_size = 84
    ib_x = x1 + pad
    ib_y = y1 + pad

    _gradient_box(img, (ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                  SILVER, SILVER_DIM, alpha=42, radius=22)
    d.rounded_rectangle((ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                        radius=22, outline=SILVER + (200,), width=3)
    _draw_icon(d, ib_x + bal_icon_size // 2, ib_y + bal_icon_size // 2 + 1,
               I_GEM, 34, SILVER_HI)

    lbl_x = ib_x + bal_icon_size + 20
    d.text((lbl_x, ib_y + 8), "ТВОЙ БАЛАНС", font=_font(14), fill=MUTED)

    bal_str = _fmt(balance)
    val_font = _font(46)
    max_w = x2 - pad - lbl_x - 16
    while _tw(d, bal_str + " DC", val_font) > max_w and val_font.size > 24:
        val_font = _font(val_font.size - 2)
    d.text((lbl_x, ib_y + 30), bal_str, font=val_font, fill=TEXT)
    bw = _tw(d, bal_str, val_font)
    d.text((lbl_x + bw + 8, ib_y + 30 + val_font.size - 26),
           "DC", font=_font(22), fill=SILVER)

    sep_y = ib_y + bal_icon_size + 26
    d.line((x1 + pad, sep_y, x2 - pad, sep_y),
           fill=STACK_HDR + (255,), width=2)

    if extra_blocks:
        bb_h = 92
        bb_gap = 12
        bottom_y = y2 - pad - bb_h

        for i, blk in enumerate(reversed(extra_blocks)):
            by1 = bottom_y - i * (bb_h + bb_gap)
            by2 = by1 + bb_h
            bx1 = x1 + pad
            bx2 = x2 - pad

            base_color = blk.get("color", SILVER)
            text_color = blk.get("text_color", _lighten(base_color, 0.45))
            border_color = _lighten(base_color, 0.25)

            # фон
            _gradient_box(img, (bx1, by1, bx2, by2),
                          base_color, base_color, alpha=30, radius=15)

            # жирная рамка
            d.rounded_rectangle((bx1, by1, bx2, by2),
                                radius=15, outline=border_color + (255,), width=3)

            # цветная полоса слева
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


def _draw_right_head(d, x1, y1, x2, title: str, sub: str):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 50), radius=3,
                        fill=SILVER + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(32), fill=TEXT)
    sub_w = _tw(d, sub.upper(), _font(15))
    d.text((x2 - sub_w, y1 + 20), sub.upper(), font=_font(15), fill=MUTED)
    d.line((x1, y1 + 66, x2, y1 + 66), fill=STACK_HDR + (255,), width=2)


# ============================================================
# SCREEN 1: ВКЛАДЫ
# ============================================================
def _draw_clan_card(img, d, x, y, w, h, clan: dict,
                    bank: int, members: int, leader: str,
                    max_bank: int = 1):
    dark = _clan_color(clan)
    light = _clan_light(clan)
    border = _lighten(dark, 0.3)

    # Общий фон карточки
    d.rounded_rectangle((x, y, x + w, y + h), radius=18,
                        fill=INNER_BG + (255,),
                        outline=border + (200,), width=3)

    # Внутренний градиент — тонкий, чтобы дать глубину
    _gradient_box(img, (x + 2, y + 2, x + w - 2, y + h - 2),
                  dark, dark, alpha=22, radius=17)

    # Цветная полоса слева (толстая)
    d.rounded_rectangle((x + 4, y + 16, x + 10, y + h - 16), radius=3,
                        fill=dark + (255,))

    pad = 22
    icon_size = 62
    ib_x = x + pad + 14
    ib_y = y + pad

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                dark, alpha=70, radius=15)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=15, outline=light + (220,), width=3)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               _clan_icon(clan), 28, light)

    # Название клана
    name_x = ib_x + icon_size + 18
    name_max_w = x + w - pad - name_x - 140
    name_font = _font(30)
    name_shown = _ellipsis(d, clan.get("name", "—").upper(),
                           name_font, name_max_w)
    d.text((name_x, ib_y + 6), name_shown, font=name_font, fill=light)

    # Участников справа — в плашке
    members_text = f"{members} чел."
    members_font = _font(17)
    mw = _tw(d, members_text, members_font)
    mpl_w = mw + 24
    mpl_h = 32
    mpl_x = x + w - pad - mpl_w
    mpl_y = ib_y + 12
    _alpha_fill(img, (mpl_x, mpl_y, mpl_x + mpl_w, mpl_y + mpl_h),
                SILVER, alpha=40, radius=10)
    d.rounded_rectangle((mpl_x, mpl_y, mpl_x + mpl_w, mpl_y + mpl_h),
                        radius=10, outline=SILVER + (140,), width=2)
    d.text((mpl_x + 12, mpl_y + 8), members_text,
           font=members_font, fill=SILVER_HI)

    # Банк
    stats_y = ib_y + icon_size + 16

    d.text((x + pad + 14, stats_y), "БАНК КЛАНА",
           font=_font(12), fill=_lighten(dark, 0.35))

    bank_str = _fmt(bank)
    bank_font = _font(44)
    d.text((x + pad + 14, stats_y + 22), bank_str,
           font=bank_font, fill=light)
    bvw = _tw(d, bank_str, bank_font)
    d.text((x + pad + 14 + bvw + 8, stats_y + 22 + 44 - 22), "DC",
           font=_font(18), fill=SILVER)

    # Лидер — в правом нижнем углу
    ldr_x = x + w - pad - 14
    ldr_lbl = "ЛИДЕР ВКЛАДА"
    llbl_w = _tw(d, ldr_lbl, _font(11))
    d.text((ldr_x - llbl_w, stats_y + 6), ldr_lbl,
           font=_font(11), fill=MUTED)
    leader_font = _font(19)
    leader_shown = _ellipsis(d, leader, leader_font, 300)
    lw = _tw(d, leader_shown, leader_font)
    d.text((ldr_x - lw, stats_y + 26), leader_shown,
           font=leader_font, fill=TEXT_SOFT)

    # Прогресс-бар — с явной рамкой
    bar_y = y + h - pad - 14
    bar_x1 = x + pad + 14
    bar_x2 = x + w - pad - 14
    bar_h = 12

    d.rounded_rectangle((bar_x1 - 2, bar_y - 2, bar_x2 + 2, bar_y + bar_h + 2),
                        radius=(bar_h + 4) // 2, fill=(10, 10, 12) + (255,))
    d.rounded_rectangle((bar_x1, bar_y, bar_x2, bar_y + bar_h),
                        radius=bar_h // 2, fill=(32, 32, 38) + (255,))

    if max_bank > 0 and bank > 0:
        ratio = min(bank / max_bank, 1.0)
        fill_w = int((bar_x2 - bar_x1) * ratio)
        if fill_w > 0:
            d.rounded_rectangle((bar_x1, bar_y, bar_x1 + fill_w, bar_y + bar_h),
                                radius=bar_h // 2, fill=dark + (255,))
            d.rounded_rectangle((bar_x1, bar_y, bar_x1 + fill_w, bar_y + bar_h),
                                radius=bar_h // 2, outline=light + (150,), width=1)


def render_clan_deposits(
    user_id: int, balance: int,
    clans_data: List[Dict],
) -> io.BytesIO:
    img, d = _base_canvas(user_id, "кланы · вклады")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    total_bank = sum(c["bank"] for c in clans_data)
    total_members = sum(c["members"] for c in clans_data)

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        balance,
        extra_blocks=[
            {
                "label": "Кланов в лиге",
                "value": f"{len(clans_data)}",
                "icon": I_SHIELD,
                "color": SILVER,
            },
            {
                "label": "Участников",
                "value": f"{total_members}",
                "icon": I_USERS,
                "color": BLUE,
            },
            {
                "label": "Общий банк",
                "value": f"{_fmt(total_bank)} DC",
                "icon": I_COINS,
                "color": GREEN,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Вклады кланов",
                     "3 клана · идёт сезон")

    list_y = body_y + 118
    list_bottom = body_y + body_h - 22
    gap_card = 16

    n = max(len(clans_data), 1)
    card_h = (list_bottom - list_y - gap_card * (n - 1)) // n
    card_h = max(card_h, 110)

    max_bank = max((c["bank"] for c in clans_data), default=1)

    for i, cdata in enumerate(clans_data):
        cy = list_y + i * (card_h + gap_card)
        _draw_clan_card(
            img, d, rx1, cy, rx2 - rx1, card_h,
            cdata["clan"], cdata["bank"], cdata["members"], cdata["leader"],
            max_bank=max_bank,
        )

    _draw_footer(d, "Данные обновляются в реальном времени", "стр. 1 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# SCREEN 2: ПОСЛЕДНЕЕ
# ============================================================
def _draw_feed_row(img, d, x, y, w, h, item: dict):
    amount = item.get("amount", 0)
    reason = item.get("reason", "—") or "—"
    time_str = item.get("time_str", "—")
    clan = item.get("clan")
    user_id = item.get("user_id", 0)

    is_plus = amount >= 0
    accent = GREEN if is_plus else RED
    sign = "+" if is_plus else "−"

    d.rounded_rectangle((x, y, x + w, y + h), radius=14,
                        fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)

    d.rounded_rectangle((x, y + 10, x + 5, y + h - 10), radius=3,
                        fill=accent + (255,))

    ic_size = 52
    ib_x = x + 20
    ib_y = y + (h - ic_size) // 2

    _alpha_fill(img, (ib_x, ib_y, ib_x + ic_size, ib_y + ic_size),
                accent, alpha=70, radius=13)
    d.rounded_rectangle((ib_x, ib_y, ib_x + ic_size, ib_y + ic_size),
                        radius=13, outline=accent + (200,), width=2)
    _draw_icon(d, ib_x + ic_size // 2, ib_y + ic_size // 2 + 1,
               _reason_icon(reason), 24, accent)

    tx = ib_x + ic_size + 18

    user_text = f"@{item.get('user_name', user_id)}"
    user_font = _font(21)
    max_user_w = w - (tx - x) - 260
    user_shown = _ellipsis(d, user_text, user_font, max_user_w)
    d.text((tx, y + h // 2 - 26), user_shown, font=user_font, fill=TEXT)

    clan_name = clan.get("name", "") if clan else ""
    sub_text = f"{clan_name}  ·  {time_str}" if clan_name else time_str
    sub_font = _font(14)
    sub_shown = _ellipsis(d, sub_text, sub_font, max_user_w)
    d.text((tx, y + h // 2 + 4), sub_shown, font=sub_font, fill=MUTED)

    amt_str = f"{sign}{_fmt(abs(amount))} DC"
    amt_font = _font(30)
    aw = _tw(d, amt_str, amt_font)
    d.text((x + w - 22 - aw, y + h // 2 - 18), amt_str,
           font=amt_font, fill=accent)

    tag = item.get("tag", "")
    if tag:
        tag_font = _font(11)
        tag_w = _tw(d, tag, tag_font)
        d.text((x + w - 22 - tag_w, y + h // 2 + 12),
               tag, font=tag_font, fill=_darken(accent, 0.2))


def render_clan_last(
    user_id: int, balance: int,
    feed: List[Dict],
    today_count: int = 0,
    today_sum: int = 0,
    daily_limit: int = 2500,
    daily_used: int = 0,
) -> io.BytesIO:
    img, d = _base_canvas(user_id, "кланы · лента")

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
        balance,
        extra_blocks=[
            {
                "label": "Вкладов сегодня",
                "value": f"{today_count}",
                "icon": I_HISTORY,
                "color": SILVER,
            },
            {
                "label": "Сумма за сегодня",
                "value": f"{_fmt(today_sum)} DC",
                "icon": I_COINS,
                "color": GREEN,
            },
            {
                "label": "Лимит вклада",
                "value": f"{_fmt(daily_used)} / {_fmt(daily_limit)}",
                "icon": I_GAUGE,
                "color": BLUE,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Последние вклады",
                     "обновляется в реальном времени")

    list_y = body_y + 118
    list_bottom = body_y + body_h - 22
    gap_row = 10

    rows = 5
    row_h = (list_bottom - list_y - gap_row * (rows - 1)) // rows
    row_h = max(row_h, 68)

    if not feed:
        box = (rx1, list_y, rx2, list_bottom)
        _draw_dashed_rect(d, box, 16, (58, 58, 64), dash=12, gap=8, width=2)

        icon_cx = (rx1 + rx2) // 2
        icon_cy = (list_y + list_bottom) // 2 - 40
        _alpha_fill(img, (icon_cx - 50, icon_cy - 50, icon_cx + 50, icon_cy + 50),
                    SILVER, alpha=25, radius=22)
        _draw_icon(d, icon_cx, icon_cy, I_HISTORY, 44, SILVER)
        d.text((icon_cx, list_y + (list_bottom - list_y) // 2 + 50),
               "Пока нет вкладов", font=_font(26), fill=TEXT, anchor="mm")
        d.text((icon_cx, list_y + (list_bottom - list_y) // 2 + 88),
               "Как только кто-то внесёт DC в копилку — появится здесь.",
               font=_font(15), fill=MUTED, anchor="mm")
    else:
        for i, item in enumerate(feed[:rows]):
            cy = list_y + i * (row_h + gap_row)
            _draw_feed_row(img, d, rx1, cy, rx2 - rx1, row_h, item)

    _draw_footer(d, f"Показаны последние {min(len(feed), rows)} вкладов", "стр. 2 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# SCREEN 3: ОБЩИЙ ПУЛ (ФИКС)
# ============================================================
def render_clan_total_pool(
    user_id: int, balance: int,
    total_bank: int,
    clans_data: List[Dict],
    total_members: int = 0,
    top_clan: Optional[dict] = None,
) -> io.BytesIO:
    img, d = _base_canvas(user_id, "кланы · общий пул")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    avg_contrib = total_bank // max(total_members, 1)

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        balance,
        extra_blocks=[
            {
                "label": "Лидирует",
                "value": top_clan.get("name", "—") if top_clan else "—",
                "icon": I_CROWN,
                "color": _clan_color(top_clan) if top_clan else SILVER,
            },
            {
                "label": "Участников",
                "value": f"{total_members}",
                "icon": I_USERS,
                "color": BLUE,
            },
            {
                "label": "Средний вклад",
                "value": f"{_fmt(avg_contrib)} DC",
                "icon": I_CHART,
                "color": GREEN,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Общий пул кланов",
                     "все кланы · текущий сезон")

    # ── HERO ──
    hero_y = body_y + 118
    hero_h = 280

    # Двойной фон: внешний тёмный + цветная обводка
    d.rounded_rectangle((rx1 - 3, hero_y - 3, rx2 + 3, hero_y + hero_h + 3),
                        radius=23, fill=(8, 8, 10) + (255,))

    _gradient_box(img, (rx1, hero_y, rx2, hero_y + hero_h),
                  SILVER, SILVER_DIM, alpha=22, radius=20)
    d.rounded_rectangle((rx1, hero_y, rx2, hero_y + hero_h),
                        radius=20, outline=SILVER + (200,), width=3)

    # Заголовок
    d.text((rx1 + (rx2 - rx1) // 2, hero_y + 34),
           "СУММАРНЫЙ ПУЛ ВСЕХ КЛАНОВ",
           font=_font(17), fill=SILVER, anchor="mm")

    # Разделитель под заголовком
    sep_hdr_y = hero_y + 60
    d.line((rx1 + 100, sep_hdr_y, rx2 - 100, sep_hdr_y),
           fill=SILVER_DIM + (150,), width=2)

    # Цифра
    total_str = _fmt(total_bank)
    tf = _font(108)
    while _tw(d, total_str, tf) > (rx2 - rx1) - 280 and tf.size > 60:
        tf = _font(tf.size - 4)

    ts_w = _tw(d, total_str, tf)
    unit_w = _tw(d, " DC", _font(42))
    total_full_w = ts_w + unit_w
    start_x = (rx1 + rx2 - total_full_w) // 2

    num_y = hero_y + 88
    d.text((start_x, num_y), total_str, font=tf, fill=SILVER_HI)
    d.text((start_x + ts_w + 12, num_y + tf.size - 48),
           "DC", font=_font(42), fill=SILVER)

    # Плашка с датой — отдельный блок снизу
    badge_h = 44
    badge_y = hero_y + hero_h - badge_h - 20
    badge_text = "распределится 28 числа в 20:00 МСК"
    badge_font = _font(16)
    badge_w = _tw(d, badge_text, badge_font) + 60
    badge_x = rx1 + (rx2 - rx1 - badge_w) // 2

    _alpha_fill(img, (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
                GREEN, alpha=50, radius=12)
    d.rounded_rectangle((badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
                        radius=12, outline=GREEN + (200,), width=2)
    _draw_icon(d, badge_x + 24, badge_y + badge_h // 2, I_CLOCK, 18, GREEN)
    d.text((badge_x + 44, badge_y + badge_h // 2), badge_text,
           font=badge_font, fill=GREEN, anchor="lm")

    # ── ДОЛИ КЛАНОВ ──
    shares_y = hero_y + hero_h + 30
    d.text((rx1, shares_y), "ДОЛИ КЛАНОВ В ПУЛЕ",
           font=_font(15), fill=MUTED)
    d.line((rx1, shares_y + 30, rx2, shares_y + 30),
           fill=STACK_HDR + (255,), width=2)

    row_y = shares_y + 48
    rows_bottom = body_y + body_h - 22
    n = max(len(clans_data), 1)
    row_gap = 14
    row_h = (rows_bottom - row_y - row_gap * (n - 1)) // n
    row_h = max(row_h, 60)

    max_bank = max((c["bank"] for c in clans_data), default=1)

    for i, cdata in enumerate(clans_data):
        clan = cdata["clan"]
        bank = cdata["bank"]
        cy = row_y + i * (row_h + row_gap)

        dark = _clan_color(clan)
        light = _clan_light(clan)
        border = _lighten(dark, 0.3)

        # Фоновая плашка строки с рамкой
        d.rounded_rectangle((rx1 - 4, cy - 4, rx2 + 4, cy + row_h + 4),
                            radius=14, fill=(8, 8, 10) + (255,))
        _gradient_box(img, (rx1, cy, rx2, cy + row_h),
                      dark, dark, alpha=28, radius=10)
        d.rounded_rectangle((rx1, cy, rx2, cy + row_h),
                            radius=10, outline=border + (200,), width=2)

        # Цветная полоса слева
        d.rounded_rectangle((rx1 + 4, cy + 10, rx1 + 9, cy + row_h - 10),
                            radius=2, fill=dark + (255,))

        # Имя клана
        name_x = rx1 + 22
        d.text((name_x, cy + row_h // 2), clan.get("name", "—").upper(),
               font=_font(20), fill=light, anchor="lm")

        # Бар
        bar_x1 = rx1 + 300
        bar_x2 = rx2 - 240
        bar_y = cy + (row_h - 18) // 2
        bar_h = 18

        d.rounded_rectangle((bar_x1 - 2, bar_y - 2, bar_x2 + 2, bar_y + bar_h + 2),
                            radius=(bar_h + 4) // 2, fill=(8, 8, 10) + (255,))
        d.rounded_rectangle((bar_x1, bar_y, bar_x2, bar_y + bar_h),
                            radius=bar_h // 2, fill=(32, 32, 38) + (255,))

        ratio = min(bank / max_bank, 1.0) if max_bank > 0 else 0
        fill_w = int((bar_x2 - bar_x1) * ratio)
        if fill_w > 0:
            d.rounded_rectangle((bar_x1, bar_y, bar_x1 + fill_w, bar_y + bar_h),
                                radius=bar_h // 2, fill=dark + (255,))

        # Сумма
        amt_str = f"{_fmt(bank)} DC"
        amt_font = _font(24)
        aw = _tw(d, amt_str, amt_font)
        d.text((rx2 - 22 - aw, cy + row_h // 2), amt_str,
               font=amt_font, fill=light, anchor="lm")

    _draw_footer(d, "Общий пул обновляется в реальном времени", "стр. 3 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# SCREEN 4: БАНК КЛАНА
# ============================================================
def render_clan_bank(
    user_id: int, balance: int,
    clan: dict,
    bank: int,
    members: int,
    my_contrib: int,
    my_rank: Optional[int],
    to_top3: int,
    top3: List[Dict],
) -> io.BytesIO:
    img, d = _base_canvas(user_id, "клан · банк")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    dark = _clan_color(clan)
    light = _clan_light(clan)
    border = _lighten(dark, 0.3)

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        balance,
        extra_blocks=[
            {
                "label": "Твой вклад",
                "value": f"{_fmt(my_contrib)} DC",
                "icon": I_HAND,
                "color": GREEN,
            },
            {
                "label": "Твоё место",
                "value": f"#{my_rank}" if my_rank else "—",
                "icon": I_TROPHY,
                "color": SILVER,
            },
            {
                "label": "До топ-3",
                "value": f"+{_fmt(to_top3)} DC" if to_top3 else "уже в топ-3",
                "icon": I_CHART,
                "color": BLUE if to_top3 else GOLD,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Банк клана",
                     "твой клан · текущий сезон")

    # ── HERO ──
    hero_y = body_y + 118
    hero_h = 200

    d.rounded_rectangle((rx1 - 3, hero_y - 3, rx2 + 3, hero_y + hero_h + 3),
                        radius=23, fill=(8, 8, 10) + (255,))
    _gradient_box(img, (rx1, hero_y, rx2, hero_y + hero_h),
                  dark, dark, alpha=38, radius=20)
    d.rounded_rectangle((rx1, hero_y, rx2, hero_y + hero_h),
                        radius=20, outline=border + (255,), width=3)

    icon_size = 110
    ib_x = rx1 + 28
    ib_y = hero_y + (hero_h - icon_size) // 2

    _gradient_box(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                  dark, dark, alpha=90, radius=24)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=24, outline=light + (255,), width=3)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               _clan_icon(clan), 52, light)

    tx = ib_x + icon_size + 26
    d.text((tx, hero_y + 26), clan.get("name", "—").upper(),
           font=_font(36), fill=light)

    desc = clan.get("description", "") or ""
    if desc:
        desc_font = _font(14)
        max_dw = rx2 - 28 - tx
        desc_shown = _ellipsis(d, desc, desc_font, max_dw)
        d.text((tx, hero_y + 76), desc_shown, font=desc_font, fill=MUTED)

    bank_str = _fmt(bank)
    bank_font = _font(56)
    while _tw(d, bank_str + " DC", bank_font) > (rx2 - 28 - tx) and bank_font.size > 30:
        bank_font = _font(bank_font.size - 2)

    d.text((tx, hero_y + 108), bank_str, font=bank_font, fill=SILVER_HI)
    bw = _tw(d, bank_str, bank_font)
    d.text((tx + bw + 10, hero_y + 108 + bank_font.size - 30),
           "DC", font=_font(24), fill=SILVER)

    # ── MINI-STATS ──
    stats_y = hero_y + hero_h + 26
    stats_h = 96

    cols = 3
    col_gap = 14
    col_w = (rx2 - rx1 - col_gap * (cols - 1)) // cols

    stats = [
        ("УЧАСТНИКОВ",    f"{members}",                            I_USERS,  SILVER,  SILVER_BG),
        ("СРЕДНИЙ ВКЛАД", f"{_fmt(bank // max(members, 1))} DC",   I_CHART,  GREEN,   GREEN_BG),
        ("ДО КОНЦА",      "28.10 · 20:00",                         I_CLOCK,  BLUE,    BLUE_BG),
    ]

    for i, (lbl, val, icon, color, bg) in enumerate(stats):
        cx1 = rx1 + i * (col_w + col_gap)
        cx2 = cx1 + col_w

        _gradient_box(img, (cx1, stats_y, cx2, stats_y + stats_h),
                      color, color, alpha=15, radius=14)
        d.rounded_rectangle((cx1, stats_y, cx2, stats_y + stats_h),
                            radius=14, outline=color + (180,), width=3)

        icon_size = 42
        ib_x = cx1 + 16
        ib_y = stats_y + (stats_h - icon_size) // 2
        _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                    color, alpha=70, radius=11)
        d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                            radius=11, outline=color + (200,), width=2)
        _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
                   icon, 20, color)

        tx2 = ib_x + icon_size + 14
        d.text((tx2, stats_y + 16), lbl, font=_font(11), fill=MUTED)
        val_font = _font(22)
        max_w = cx2 - 14 - tx2
        val_shown = _ellipsis(d, val, val_font, max_w)
        d.text((tx2, stats_y + 42), val_shown, font=val_font, fill=color)

    # ── ТОП-3 ──
    top_y = stats_y + stats_h + 24
    top_bottom = body_y + body_h - 22

    d.rounded_rectangle((rx1 - 3, top_y - 3, rx2 + 3, top_bottom + 3),
                        radius=19, fill=(8, 8, 10) + (255,))
    _gradient_box(img, (rx1, top_y, rx2, top_bottom),
                  SILVER, SILVER, alpha=10, radius=16)
    d.rounded_rectangle((rx1, top_y, rx2, top_bottom),
                        radius=16, outline=SILVER_DIM + (140,), width=2)

    d.text((rx1 + 24, top_y + 16), "ТОП-3 КЛАНА ПО ВКЛАДУ",
           font=_font(14), fill=SILVER)
    d.line((rx1 + 24, top_y + 44, rx2 - 24, top_y + 44),
           fill=STACK_HDR + (255,), width=2)

    medals = [
        (GOLD,   GOLD_BG),
        (SILVER, SILVER_BG),
        (BRONZE, (40, 28, 20)),
    ]

    row_y = top_y + 60
    row_h = 52
    row_gap = 10

    if not top3:
        d.text((rx1 + (rx2 - rx1) // 2, top_y + (top_bottom - top_y) // 2),
               "Пока никто не внёс вклад в копилку",
               font=_font(18), fill=DIM, anchor="mm")
    else:
        for i, t in enumerate(top3[:3]):
            cy = row_y + i * (row_h + row_gap)
            if cy + row_h > top_bottom - 14:
                break

            medal_color, medal_bg = medals[i]
            is_me = (t.get("user_id") == user_id)

            if is_me:
                d.rounded_rectangle((rx1 + 16, cy - 2, rx2 - 16, cy + row_h + 2),
                                    radius=14, fill=(8, 8, 10) + (255,))
                _gradient_box(img, (rx1 + 18, cy, rx2 - 18, cy + row_h),
                              SILVER, SILVER, alpha=30, radius=12)
                d.rounded_rectangle((rx1 + 18, cy, rx2 - 18, cy + row_h),
                                    radius=12, outline=SILVER + (220,), width=3)
            else:
                _gradient_box(img, (rx1 + 18, cy, rx2 - 18, cy + row_h),
                              medal_color, medal_color, alpha=15, radius=12)
                d.rounded_rectangle((rx1 + 18, cy, rx2 - 18, cy + row_h),
                                    radius=12, outline=medal_color + (140,), width=2)

            badge_size = 40
            bx = rx1 + 30
            by = cy + (row_h - badge_size) // 2

            _alpha_fill(img, (bx, by, bx + badge_size, by + badge_size),
                        medal_color, alpha=80, radius=12)
            d.rounded_rectangle((bx, by, bx + badge_size, by + badge_size),
                                radius=12, outline=medal_color + (220,), width=2)
            _draw_icon(d, bx + badge_size // 2, by + badge_size // 2 + 1,
                       I_MEDAL, 20, medal_color)

            tx2 = bx + badge_size + 16
            name_str = f"@{t.get('user_name', t.get('user_id', '—'))}"
            name_font = _font(19)
            max_name_w = (rx2 - 30) - tx2 - 160
            name_shown = _ellipsis(d, name_str, name_font, max_name_w)
            d.text((tx2, cy + row_h // 2 - 14), name_shown,
                   font=name_font, fill=SILVER_HI if is_me else TEXT)

            amt_str = f"{_fmt(t.get('total', 0))} DC"
            amt_font = _font(22)
            aw = _tw(d, amt_str, amt_font)
            d.text((rx2 - 30 - aw, cy + row_h // 2 - 16), amt_str,
                   font=amt_font, fill=medal_color)

    _draw_footer(d, "Банк клана · данные в реальном времени", "стр. 4 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# SCREEN 5: ТОП
# ============================================================
def _draw_top_row(img, d, x, y, w, h, rank: int, name: str, amount: int,
                  is_me: bool = False):
    if rank == 1:
        medal_color = GOLD
        medal_bg = GOLD_BG
    elif rank == 2:
        medal_color = SILVER
        medal_bg = SILVER_BG
    elif rank == 3:
        medal_color = BRONZE
        medal_bg = (40, 28, 20)
    else:
        medal_color = DIM
        medal_bg = (28, 28, 34)

    if is_me:
        d.rounded_rectangle((x - 3, y - 3, x + w + 3, y + h + 3),
                            radius=17, fill=(8, 8, 10) + (255,))
        _gradient_box(img, (x, y, x + w, y + h), SILVER, SILVER, alpha=28, radius=14)
        d.rounded_rectangle((x, y, x + w, y + h),
                            radius=14, outline=SILVER_HI + (255,), width=3)
    else:
        _gradient_box(img, (x, y, x + w, y + h), medal_color, medal_color,
                      alpha=12, radius=14)
        d.rounded_rectangle((x, y, x + w, y + h),
                            radius=14, outline=medal_color + (140,), width=2)

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
    max_name_w = (x + w - 30) - tx - 200
    name_shown = _ellipsis(d, name_str, name_font, max_name_w)
    d.text((tx, y + h // 2 - 18), name_shown, font=name_font,
           fill=SILVER_HI if is_me else TEXT)

    if is_me:
        you_str = "ТЫ"
        you_font = _font(13)
        yw = _tw(d, you_str, you_font)
        yx = tx
        yy = y + h // 2 + 12
        _alpha_fill(img, (yx, yy, yx + yw + 20, yy + 24),
                    SILVER, alpha=90, radius=8)
        d.rounded_rectangle((yx, yy, yx + yw + 20, yy + 24),
                            radius=8, outline=SILVER_HI + (200,), width=1)
        d.text((yx + 10, yy + 5), you_str, font=you_font, fill=SILVER_HI)

    amt_str = f"{_fmt(amount)} DC"
    amt_font = _font(26)
    aw = _tw(d, amt_str, amt_font)
    d.text((x + w - 22 - aw, y + h // 2 - 18), amt_str,
           font=amt_font, fill=medal_color if rank <= 3 else SILVER_HI)


def render_clan_top(
    user_id: int, balance: int,
    clan: dict,
    top_list: List[Dict],
    my_rank: Optional[int],
    my_contrib: int,
    to_first: int,
) -> io.BytesIO:
    img, d = _base_canvas(user_id, "клан · топ")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    dark = _clan_color(clan)
    light = _clan_light(clan)

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        balance,
        extra_blocks=[
            {
                "label": "Твоё место",
                "value": f"#{my_rank}" if my_rank else "—",
                "icon": I_TROPHY,
                "color": SILVER,
            },
            {
                "label": "Твой вклад",
                "value": f"{_fmt(my_contrib)} DC",
                "icon": I_HAND,
                "color": GREEN,
            },
            {
                "label": "До 1-го места",
                "value": f"+{_fmt(to_first)} DC" if to_first else "ты в топ-1!",
                "icon": I_FIRE,
                "color": GOLD,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     f"Топ клана · {clan.get('name', '—')}",
                     f"{len(top_list)} участников · живой рейтинг")

    list_y = body_y + 118
    list_bottom = body_y + body_h - 22
    gap_row = 10

    rows = 8
    row_h = (list_bottom - list_y - gap_row * (rows - 1)) // rows
    row_h = max(row_h, 60)

    if not top_list:
        box = (rx1, list_y, rx2, list_bottom)
        _draw_dashed_rect(d, box, 16, (58, 58, 64), dash=12, gap=8, width=2)
        icon_cx = (rx1 + rx2) // 2
        icon_cy = (list_y + list_bottom) // 2 - 40
        _alpha_fill(img, (icon_cx - 50, icon_cy - 50, icon_cx + 50, icon_cy + 50),
                    SILVER, alpha=25, radius=22)
        _draw_icon(d, icon_cx, icon_cy, I_TROPHY, 44, SILVER)
        d.text((icon_cx, list_y + (list_bottom - list_y) // 2 + 50),
               "Топ пока пуст", font=_font(26), fill=TEXT, anchor="mm")
        d.text((icon_cx, list_y + (list_bottom - list_y) // 2 + 88),
               "Внеси первый вклад — и появишься здесь.",
               font=_font(15), fill=MUTED, anchor="mm")
    else:
        for i, t in enumerate(top_list[:rows]):
            cy = list_y + i * (row_h + gap_row)
            is_me = (t.get("user_id") == user_id)
            _draw_top_row(
                img, d, rx1, cy, rx2 - rx1, row_h,
                rank=i + 1,
                name=t.get("user_name", t.get("user_id", "—")),
                amount=t.get("total", 0),
                is_me=is_me,
            )

    _draw_footer(d, "Обновляется после каждого вклада", "стр. 5 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# SCREEN 6: КАК ЭТО РАБОТАЕТ
# ============================================================
def render_clan_howto(
    user_id: int, balance: int,
    daily_limit: int = 2500,
    min_contrib: int = 50,
    inactivity_days: int = 30,
    min_balance: int = 45,
) -> io.BytesIO:
    img, d = _base_canvas(user_id, "клан · правила")

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
        balance,
        extra_blocks=[
            {
                "label": "До 100 DC",
                "value": "100% в копилку",
                "icon": I_CHECK,
                "color": GREEN,
            },
            {
                "label": "Свыше 100 DC",
                "value": "40% в копилку",
                "icon": I_PERCENT,
                "color": BLUE,
            },
            {
                "label": "Дневной лимит",
                "value": f"{_fmt(daily_limit)} DC",
                "icon": I_GAUGE,
                "color": GOLD,
            },
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Как это работает",
                     "сезон · 28 дней · выплата 28 числа")

    items_y = body_y + 118
    items_bottom = body_y + body_h - 22
    n = 4
    gap_item = 12
    item_h = (items_bottom - items_y - gap_item * (n - 1)) // n
    item_h = max(item_h, 130)

    rules = [
        {
            "num": 1,
            "title": "Как копится банк клана",
            "text": (
                "До 100 DC за раз — вся сумма идёт в копилку клана. "
                "Больше 100 DC — 40% уходит в копилку. "
                "Себе при этом всегда остаётся 100% заработанного."
            ),
            "color": GREEN,
            "icon": I_HAND,
        },
        {
            "num": 2,
            "title": "Как делится пул в конце сезона",
            "text": (
                "Весь банк клана делится между всеми участниками. "
                "Вес участника = время в клане × бонус. "
                "Топ-3 по вкладу получают бонусы ×3.00 / ×2.00 / ×1.50."
            ),
            "color": SILVER,
            "icon": I_TROPHY,
        },
        {
            "num": 3,
            "title": "Квесты и задания",
            "text": (
                "Ежедневные — сброс в 00:00 МСК. "
                "Недельные — сброс в понедельник в 00:00 МСК. "
                "Разовые — на весь сезон. Награда идёт в копилку по тому же правилу."
            ),
            "color": BLUE,
            "icon": I_STAR,
        },
        {
            "num": 4,
            "title": "Условия нахождения в клане",
            "text": (
                f"Баланс не меньше {min_balance} DC, есть роль покупателя, "
                f"активность за последние {inactivity_days} дней. "
                f"Провалил любое условие — исключение и вклад уходит из копилки."
            ),
            "color": GOLD,
            "icon": I_SHIELD,
        },
    ]

    for i, rule in enumerate(rules):
        cy = items_y + i * (item_h + gap_item)
        color = rule["color"]
        light = _lighten(color, 0.35)
        border = _lighten(color, 0.2)

        _gradient_box(img, (rx1, cy, rx2, cy + item_h),
                      color, color, alpha=15, radius=14)
        d.rounded_rectangle((rx1, cy, rx2, cy + item_h),
                            radius=14, outline=border + (200,), width=3)

        num_size = 52
        nx = rx1 + 22
        ny = cy + (item_h - num_size) // 2

        _gradient_box(img, (nx, ny, nx + num_size, ny + num_size),
                      color, color, alpha=80, radius=14)
        d.rounded_rectangle((nx, ny, nx + num_size, ny + num_size),
                            radius=14, outline=light + (230,), width=2)
        _draw_icon(d, nx + num_size // 2, ny + num_size // 2 + 1,
                   rule["icon"], 24, light)

        tx = nx + num_size + 22
        tx_max = rx2 - 30 - tx

        d.text((tx, cy + 22), rule["title"].upper(),
               font=_font(19), fill=light)

        text_font = _font(15)
        words = rule["text"].split()
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if _tw(d, test, text_font) <= tx_max:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)

        text_y = cy + 58
        for j, line in enumerate(lines[:4]):
            d.text((tx, text_y + j * 22), line, font=text_font, fill=TEXT_SOFT)

    _draw_footer(d, "Правила действуют весь сезон", "стр. 6 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
