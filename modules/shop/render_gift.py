# -*- coding: utf-8 -*-
"""
Pillow-рендер ежедневного подарка (DC).
Размер 1800×1000, стиль 1:1 с render_profile.py.
2 состояния: забрано (зелёный) / кулдаун (золотой).
"""
import io
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List, Dict

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
GOLD_BG   = (40, 32, 21)

CARD_BRD  = (74, 74, 79)

EMBED_COLOR = 0x2b2d31


# ============================================================
# FA5-ИКОНКИ
# ============================================================
I_GEM        = 0xf3a5
I_GIFT       = 0xf06b
I_CLOCK      = 0xf017
I_HOURGLASS  = 0xf252
I_CALENDAR   = 0xf133
I_CHECK      = 0xf00c
I_FIRE       = 0xf06d
I_INFO       = 0xf05a
I_SPARKLES   = 0xf890
I_BOX        = 0xf466


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


# ============================================================
# КАРКАС
# ============================================================
CANVAS_W, CANVAS_H = 1800, 1000
M = 14
PAD_X = 40
PAD_Y = 40


def _base_canvas(user_id: int, uid_label: str, status_label: str):
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
    w1 = _tw(d, lbl, _font(15))
    w2 = _tw(d, status_label.upper(), _font(24))
    d.text((meta_r - w1, hy + 14), lbl, font=_font(15), fill=MUTED)
    d.text((meta_r - w2, hy + 38), status_label.upper(), font=_font(24), fill=TEXT)

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


# ============================================================
# ЛЕВАЯ ПАНЕЛЬ
# ============================================================
def _draw_left_block(img, d, x, y, w, h, base_color, icon_code, label, value):
    light = tuple(min(int(c + (255 - c) * 0.4), 255) for c in base_color)
    border = tuple(min(int(c + (255 - c) * 0.25), 255) for c in base_color)

    _gradient_box(img, (x, y, x + w, y + h), base_color, base_color, alpha=30, radius=15)
    d.rounded_rectangle((x, y, x + w, y + h),
                        radius=15, outline=border + (255,), width=3)
    d.rounded_rectangle((x + 4, y + 12, x + 8, y + h - 12),
                        radius=2, fill=base_color + (255,))

    icon_size = 54
    ib_x = x + 20
    ib_y = y + (h - icon_size) // 2

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                base_color, alpha=70, radius=14)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=14, outline=border + (200,), width=2)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               icon_code, 24, base_color)

    tx = ib_x + icon_size + 16
    d.text((tx, y + 16), label.upper(), font=_font(13), fill=light)
    val_font = _font(22)
    max_w = x + w - 18 - tx
    val_shown = _ellipsis(d, value, val_font, max_w)
    d.text((tx, y + 44), val_shown, font=val_font, fill=base_color)


def _draw_left_panel(img, d, box, balance, blocks: List[Dict]):
    _draw_stack_panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 28

    # Баланс
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

    # Инфо-блоки
    if blocks:
        bb_h = 92
        bb_gap = 14
        top_y = sep_y + 26

        for i, blk in enumerate(blocks):
            by1 = top_y + i * (bb_h + bb_gap)
            _draw_left_block(
                img, d, x1 + pad, by1, (x2 - pad) - (x1 + pad), bb_h,
                blk["color"], blk["icon"], blk["label"], blk["value"],
            )


# ============================================================
# ПРАВАЯ ПАНЕЛЬ — ЗАГОЛОВОК
# ============================================================
def _draw_right_head(d, x1, y1, x2, title: str, sub: str):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 50), radius=3,
                        fill=SILVER + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(32), fill=TEXT)
    sub_w = _tw(d, sub.upper(), _font(15))
    d.text((x2 - sub_w, y1 + 20), sub.upper(), font=_font(15), fill=MUTED)
    d.line((x1, y1 + 66, x2, y1 + 66), fill=STACK_HDR + (255,), width=2)


# ============================================================
# HERO — БОЛЬШОЙ БЛОК В ЦЕНТРЕ (ИСПРАВЛЕНО)
# ============================================================
def _draw_hero(img, d, box, is_success: bool,
               amount: int, hours_str: str, next_ts: int):
    """
    is_success=True  — зелёный, +N DC
    is_success=False — золотой, HH:MM ч

    Layout (сверху вниз):
      [TAG-бейдж]  ← маленький, с FA-иконкой
      [Иконка+glow] ← 110px
      [Заголовок]
      [ОГРОМНАЯ ЦИФРА]
      [Подпись]
    Всё центрируется вертикально внутри hero.
    """
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    cx = (x1 + x2) // 2

    # ─── Параметры в зависимости от состояния ───
    if is_success:
        main_color = GREEN
        tag_icon = I_CHECK
        tag_text = "ПОДАРОК ЗАБРАН"
        hero_icon = I_GIFT
        title_text = "Тебе выпало"
        big_str = f"+{amount}"
        unit_str = " DC"
    else:
        main_color = GOLD
        tag_icon = I_HOURGLASS
        tag_text = "УЖЕ ЗАБРАЛ СЕГОДНЯ"
        hero_icon = I_HOURGLASS
        title_text = "Ты уже забрал подарок"
        big_str = hours_str
        unit_str = " ч"

    border_light = tuple(min(int(c + (255 - c) * 0.30), 255) for c in main_color)

    # ─── ФОН HERO ───
    _gradient_box(img, (x1, y1, x2, y2), main_color, main_color, alpha=22, radius=22)
    d.rounded_rectangle((x1, y1, x2, y2),
                        radius=22, outline=main_color + (220,), width=3)

    # ─── Размеры всех элементов ───
    TAG_H = 34
    TAG_PAD = 20
    TAG_ICON_GAP = 10
    ICON_SIZE = 110
    GLOW_SIZE = 130

    TAG_FONT_SIZE = 14
    TITLE_FONT_SIZE = 22
    BIG_FONT_SIZE = 82
    UNIT_FONT_SIZE = 30
    SUB_FONT_SIZE = 15

    GAP_TAG_ICON   = 24   # между тегом и иконкой
    GAP_ICON_TITLE = 20   # между иконкой и заголовком
    GAP_TITLE_BIG  = 36   # между заголовком и большой цифрой
    GAP_BIG_SUB    = 12   # между большой цифрой и подписью

    # ─── Предварительный расчёт ───
    tag_font = _font(TAG_FONT_SIZE)
    title_font = _font(TITLE_FONT_SIZE)
    sub_font = _font(SUB_FONT_SIZE)
    unit_font = _font(UNIT_FONT_SIZE)

    tag_text_w = _tw(d, tag_text, tag_font)
    tag_w = tag_text_w + TAG_PAD * 2 + 18 + TAG_ICON_GAP   # место под иконку

    title_h = title_font.size

    big_font = _font(BIG_FONT_SIZE)
    # Ужимаем если не влезает
    while _tw(d, big_str + unit_str, big_font) > w - 100 and big_font.size > 50:
        big_font = _font(big_font.size - 4)

    big_h = big_font.size
    sub_h = sub_font.size

    # Полная высота контента
    total_h = (
        TAG_H + GAP_TAG_ICON
        + ICON_SIZE + GAP_ICON_TITLE
        + title_h + GAP_TITLE_BIG
        + big_h + GAP_BIG_SUB
        + sub_h
    )

    # Стартуем так, чтобы контент был отцентрирован, но минимум 26px от верха
    start_y = y1 + max((h - total_h) // 2, 26)

    # ═══════════════════════════════════════════════════════
    # 1. TAG-БЕЙДЖ
    # ═══════════════════════════════════════════════════════
    tag_x1 = cx - tag_w // 2
    tag_y1 = start_y
    tag_y2 = tag_y1 + TAG_H

    _alpha_fill(img,
                (tag_x1, tag_y1, tag_x1 + tag_w, tag_y2),
                main_color, alpha=55, radius=TAG_H // 2)
    d.rounded_rectangle((tag_x1, tag_y1, tag_x1 + tag_w, tag_y2),
                        radius=TAG_H // 2,
                        outline=main_color + (180,), width=2)

    # FA-иконка в теге
    icon_cx = tag_x1 + TAG_PAD + 7
    icon_cy = tag_y1 + TAG_H // 2
    _draw_icon(d, icon_cx, icon_cy, tag_icon, TAG_FONT_SIZE, main_color)

    # Текст тега
    tag_text_x = icon_cx + 14 + TAG_ICON_GAP
    d.text((tag_text_x, icon_cy), tag_text,
           font=tag_font, fill=main_color, anchor="lm")

    # ═══════════════════════════════════════════════════════
    # 2. ИКОНКА В ГЛОУ
    # ═══════════════════════════════════════════════════════
    icon_top = tag_y2 + GAP_TAG_ICON
    icon_cy = icon_top + ICON_SIZE // 2

    # Мягкое свечение (3 слоя, центрированы строго на иконке)
    for i, a in enumerate([30, 45, 60]):
        gs = GLOW_SIZE - i * 10
        _alpha_fill(
            img,
            (cx - gs // 2, icon_cy - gs // 2, cx + gs // 2, icon_cy + gs // 2),
            main_color, alpha=a, radius=gs // 2,
        )

    # Квадрат с иконкой
    ib_x = cx - ICON_SIZE // 2
    ib_y = icon_cy - ICON_SIZE // 2
    _alpha_fill(img, (ib_x, ib_y, ib_x + ICON_SIZE, ib_y + ICON_SIZE),
                main_color, alpha=65, radius=28)
    d.rounded_rectangle((ib_x, ib_y, ib_x + ICON_SIZE, ib_y + ICON_SIZE),
                        radius=28,
                        outline=border_light + (240,), width=3)
    _draw_icon(d, cx, icon_cy + 1, hero_icon, 52, main_color)

    # ═══════════════════════════════════════════════════════
    # 3. ЗАГОЛОВОК
    # ═══════════════════════════════════════════════════════
    title_y = ib_y + ICON_SIZE + GAP_ICON_TITLE
    title_w = _tw(d, title_text, title_font)
    d.text((cx - title_w // 2, title_y),
           title_text, font=title_font, fill=TEXT_SOFT)

    # ═══════════════════════════════════════════════════════
    # 4. ОГРОМНАЯ ЦИФРА
    # ═══════════════════════════════════════════════════════
    big_y = title_y + title_h + GAP_TITLE_BIG

    bw_big = _tw(d, big_str, big_font)
    bw_unit = _tw(d, unit_str, unit_font)

    total_bw = bw_big + bw_unit + 10
    big_x = cx - total_bw // 2

    d.text((big_x, big_y), big_str, font=big_font, fill=main_color)
    d.text((big_x + bw_big + 10, big_y + big_font.size - 38),
           unit_str, font=unit_font, fill=main_color)

    # ═══════════════════════════════════════════════════════
    # 5. ПОДПИСЬ
    # ═══════════════════════════════════════════════════════
    sub_y = big_y + big_h + GAP_BIG_SUB

    if is_success:
        sub_text = "Зачислено на баланс · возвращайся завтра"
    else:
        dt = datetime.fromtimestamp(next_ts, timezone.utc)
        sub_text = f"Следующий подарок — {dt.strftime('%d.%m в %H:%M')}"

    sub_w = _tw(d, sub_text, sub_font)
    # Если подпись не влезает — ужимаем
    if sub_w > w - 60:
        sub_text = f"Следующий — {datetime.fromtimestamp(next_ts, timezone.utc).strftime('%d.%m %H:%M')}"
        sub_w = _tw(d, sub_text, sub_font)

    d.text((cx - sub_w // 2, sub_y), sub_text,
           font=sub_font, fill=MUTED)


# ============================================================
# NEXT-CARD
# ============================================================
def _draw_next_card(img, d, box, is_success: bool, next_ts: int, hours: int, minutes: int):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1

    if is_success:
        main_color = BLUE
        label = "СЛЕДУЮЩИЙ ПОДАРОК ЧЕРЕЗ"
        val = f"{hours}ч {minutes}м"
        sub = "ровно 24 часа с момента получения"
        icon_code = I_CLOCK
    else:
        main_color = PURPLE
        label = "ДОСТУПЕН С"
        dt = datetime.fromtimestamp(next_ts, timezone.utc)
        val = dt.strftime("%d.%m.%Y · %H:%M МСК")
        sub = "ровно 24 часа с момента получения"
        icon_code = I_CALENDAR

    border = tuple(min(int(c + (255 - c) * 0.25), 255) for c in main_color)

    d.rounded_rectangle((x1, y1, x2, y2), radius=16,
                        fill=INNER_BG + (255,),
                        outline=border + (200,), width=3)

    d.rounded_rectangle((x1 + 4, y1 + 12, x1 + 8, y2 - 12), radius=2,
                        fill=main_color + (255,))

    icon_size = 54
    ib_x = x1 + 24
    ib_y = y1 + (h - icon_size) // 2

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                main_color, alpha=60, radius=14)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=14, outline=main_color + (200,), width=2)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               icon_code, 24, main_color)

    tx = ib_x + icon_size + 20

    d.text((tx, y1 + 16), label, font=_font(12), fill=main_color)

    val_font = _font(24)
    max_val_w = x2 - 24 - tx
    val_shown = _ellipsis(d, val, val_font, max_val_w)
    d.text((tx, y1 + 38), val_shown, font=val_font, fill=TEXT)

    sub_font = _font(13)
    d.text((tx, y1 + 68), sub, font=sub_font, fill=DIM)


# ============================================================
# HINT — ПЛАШКА ВНИЗУ
# ============================================================
def _draw_hint(img, d, box, text: str):
    x1, y1, x2, y2 = box
    h = y2 - y1

    _alpha_fill(img, (x1, y1, x2, y2), GOLD, alpha=22, radius=12)
    d.rounded_rectangle((x1, y1, x2, y2),
                        radius=12, outline=GOLD + (140,), width=2)

    icon_size = 40
    ib_x = x1 + 18
    ib_y = y1 + (h - icon_size) // 2

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                GOLD, alpha=45, radius=11)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               I_INFO, 20, GOLD)

    tx = ib_x + icon_size + 16
    font = _font(15)
    max_w = x2 - 20 - tx
    txt = _ellipsis(d, text, font, max_w)
    d.text((tx, y1 + h // 2 - 9), txt, font=font, fill=TEXT_SOFT)


# ============================================================
# ГЛАВНАЯ
# ============================================================
def render_daily_gift(
    user_id: int,
    balance: int,
    result: dict,
    daily_count: int = 0,
    daily_total: int = 0,
) -> io.BytesIO:
    """
    result = {
        "ok": bool,       # True — успешно забран
        "amount": int,    # сколько выдало (при ok=True)
        "next_ts": int,   # unixtime когда следующий доступен
    }
    daily_count  — сколько раз юзер забирал подарок (по истории)
    daily_total  — суммарно DC получено с подарков (по истории)
    """
    ok = result.get("ok", False)
    amount = result.get("amount", 0)
    next_ts = result.get("next_ts", 0)

    # Считаем часы:минуты до следующего
    now_ts = int(datetime.now(timezone.utc).timestamp())
    diff = max(next_ts - now_ts, 0)
    hours = diff // 3600
    minutes = (diff % 3600) // 60

    if hours > 0:
        hours_str = f"{hours}:{minutes:02d}"
    else:
        hours_str = f"0:{minutes:02d}"

    # Заголовки канваса
    if ok:
        status_label = "ЗАБРАН · СЕГОДНЯ"
    else:
        status_label = "КУЛДАУН · ЖДИ"

    img, d = _base_canvas(user_id, "профиль · подарок", status_label)

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    # Левая панель — 3 блока
    if ok:
        status_block = {
            "color": GREEN,
            "icon": I_CHECK,
            "label": "Статус",
            "value": "Получено сегодня",
        }
    else:
        status_block = {
            "color": GOLD,
            "icon": I_HOURGLASS,
            "label": "Статус",
            "value": "Кулдаун активен",
        }

    blocks = [
        status_block,
        {
            "color": SILVER,
            "icon": I_GIFT,
            "label": "Всего подарков",
            "value": f"{daily_count} раз" if daily_count else "—",
        },
        {
            "color": PURPLE,
            "icon": I_BOX,
            "label": "Всего получено",
            "value": f"{_fmt(daily_total)} DC" if daily_total else "—",
        },
    ]

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        balance, blocks,
    )

    # Правая панель
    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    sub_title = "ЗАБРАН · 24Ч КУЛДАУН" if ok else "ЕЩЁ НЕ ЗАБРАН · ЖДИ"
    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Ежедневный подарок", sub_title)

    # Считаем зоны
    content_y1 = body_y + 118
    content_y2 = body_y + body_h - 22
    content_h = content_y2 - content_y1

    hint_h = 68
    next_h = 100
    gap_h = 14

    hero_h = content_h - next_h - hint_h - gap_h * 2

    hero_y1 = content_y1
    hero_y2 = hero_y1 + hero_h

    next_y1 = hero_y2 + gap_h
    next_y2 = next_y1 + next_h

    hint_y1 = next_y2 + gap_h
    hint_y2 = hint_y1 + hint_h

    _draw_hero(
        img, d, (rx1, hero_y1, rx2, hero_y2),
        ok, amount, hours_str, next_ts,
    )
    _draw_next_card(
        img, d, (rx1, next_y1, rx2, next_y2),
        ok, next_ts, hours, minutes,
    )
    _draw_hint(
        img, d, (rx1, hint_y1, rx2, hint_y2),
        "Кулдаун у каждого свой — ровно 24 часа с момента получения",
    )

    # Footer
    from datetime import datetime as _dt
    now_msk = _dt.now(timezone(timedelta(hours=3)))
    stamp = now_msk.strftime("%d.%m.%Y %H:%M")
    _draw_footer(d, f"Ежедневный подарок · данные на {stamp} МСК", "подарок дня")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
