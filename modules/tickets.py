# -*- coding: utf-8 -*-
"""
Единый модуль тикетов и счётов.
Объединяет:
  · генерацию счёта на оплату (Pillow, 1800×1000)
  · Discord-View с селектом реквизитов
  · Pillow-рендеры политики
  · Pillow-рендеры «Кодекса магазина» (зарплата / правила)
"""
import asyncio
import io
import os
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption
from disnake.ui import View, Button, Modal, Select, TextInput

from PIL import Image, ImageDraw, ImageFont

from core.utils import (
    ADD_DIR, CONFIG, logger, log_discord,
    get_ticket_owner,
    remove_ticket_owner,
    cur, db,
)

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
BRONZE    = (209, 146, 96)

GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)
GOLD_BG   = (40, 32, 21)

CARD_BRD  = (74, 74, 79)

# Внешняя ссылка-страйп (используется в ReceiptSelect)
IMG_STRIPE = (
    "https://cdn.discordapp.com/attachments/1527006158282555412/"
    "1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&"
    "hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"
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
I_USER_TIE   = 0xf508
I_HAND       = 0xf4c0
I_CHART      = 0xf201
I_CLOCK      = 0xf017
I_LIST       = 0xf03a
I_INFO       = 0xf05a
I_CHECK      = 0xf00c
I_XMARK      = 0xf00d
I_PERCENT    = 0xf295
I_HISTORY    = 0xf1da
I_FIRE       = 0xf06d
I_GIFT       = 0xf06b
I_MESSAGE    = 0xf075
I_COMMENT    = 0xf075
I_GAUGE      = 0xf624
I_SHIELD     = 0xf3ed
I_WARNING    = 0xf071
I_PEN        = 0xf304
I_SEARCH     = 0xf002
I_BRIEFCASE  = 0xf0b1
I_CALENDAR   = 0xf133
I_BOOK       = 0xf02d
I_GAVEL      = 0xf0e3
I_RECEIPT    = 0xf543
I_BUILDING   = 0xf19c
I_MOBILE     = 0xf3cd
I_CREDIT     = 0xf09d
I_BAN        = 0xf05e
I_ROTATE     = 0xf2ea
I_BOX        = 0xf466
I_HEAD       = 0xf590
I_COMMENTS   = 0xf086
I_MIC        = 0xf130
I_DICE       = 0xf522
I_MOUSE      = 0xf8cc
I_CART       = 0xf07a
I_HEADSET    = 0xf025
I_DICE5      = 0xf523
I_SACK       = 0xf81d
I_MONEY      = 0xf53a

# ============================================================
# ОБЩИЕ УТИЛИТЫ
# ============================================================
MSK = timezone(timedelta(hours=3))

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

def _lighten(c, amount: float = 0.4):
    amount = max(0.0, min(1.0, amount))
    return (
        min(int(c[0] + (255 - c[0]) * amount), 255),
        min(int(c[1] + (255 - c[1]) * amount), 255),
        min(int(c[2] + (255 - c[2]) * amount), 255),
    )

_ALLOWED_SPECIAL = set("—–‑‒―“”«»„‘’…№·•▪●◆◇■□")

def _sanitize(text: str, fallback: str = "") -> str:
    if not text:
        return fallback
    out = []
    for ch in text:
        cp = ord(ch)
        if 0x20 <= cp <= 0x7E:
            out.append(ch); continue
        if 0x0400 <= cp <= 0x04FF:
            out.append(ch); continue
        if 0x00C0 <= cp <= 0x017F:
            out.append(ch); continue
        if ch in _ALLOWED_SPECIAL:
            out.append(ch); continue
    result = "".join(out).strip()
    while "  " in result:
        result = result.replace("  ", " ")
    return result or fallback

def _now_msk_str() -> str:
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M")

# ============================================================
# КАРКАС
# ============================================================
CANVAS_W, CANVAS_H = 1800, 1000
M = 14
PAD_X = 40
PAD_Y = 40

def _base_canvas(user_id: int, uid_label: str, status_label: Optional[str] = None):
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
    d.text((meta_r - w1, hy + 12), lbl, font=_font(15), fill=MUTED)

    if status_label is None:
        meta_text = f"UID · {user_id}"
        meta_font = _font(24)
        w2 = _tw(d, meta_text, meta_font)
        d.text((meta_r - w2, hy + 38), meta_text, font=meta_font, fill=TEXT)
    else:
        meta_text = status_label.upper()
        meta_font = _font(22)
        w2 = _tw(d, meta_text, meta_font)
        d.text((meta_r - w2, hy + 36), meta_text, font=meta_font, fill=TEXT)

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

# ============================================================
# БЛОК 1: СЧЁТ (Pillow)
# ============================================================
REQUISITES = [
    ("Т-Банк",     "2200 7020 8029 9345", I_BUILDING),
    ("АльфаБанк",  "2200 1545 6426 7465", I_BUILDING),
    ("ОзонБанк",   "2204 3204 4881 5151", I_BUILDING),
    ("СБП",        "+7 983 694 76 41",    I_MOBILE),
]

def generate_receipt_png(
    manager_name: str,
    customer_name: str,
    product_name: str,
    amount: int,
    discount_percent: int = 0,
    order_id: Optional[str] = None,
) -> io.BytesIO:
    """1800×1000 · Premium-дизайн счёта."""
    manager_name  = _sanitize(manager_name,  fallback="Менеджер")
    customer_name = _sanitize(customer_name, fallback="Заказчик")
    product_name  = _sanitize(product_name,  fallback="Товар")

    if order_id is None:
        order_id = f"D-{int(time.time())}-{random.randint(100, 999)}"

    now = datetime.now(MSK)
    deadline = now + timedelta(hours=1)
    deadline_str = deadline.strftime("%d.%m.%Y · %H:%M МСК")

    discount_rub = int(amount * discount_percent / 100)
    total = max(amount - discount_rub, 0)

    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle(
        (M, M, CANVAS_W - 1 - M, CANVAS_H - 1 - M),
        radius=28, fill=CARD_TOP + (255,),
        outline=CARD_BRD + (255,), width=3,
    )

    # ── HEADER ──
    hx = PAD_X
    hy = PAD_Y
    logo_size = 68

    _gradient_box(img, (hx, hy, hx + logo_size, hy + logo_size),
                  (74, 74, 82), (42, 42, 48), alpha=255, radius=18)
    d.rounded_rectangle((hx, hy, hx + logo_size, hy + logo_size),
                        radius=18, outline=(90, 90, 98) + (255,), width=2)
    _draw_icon(d, hx + logo_size // 2, hy + logo_size // 2 + 1,
               I_RECEIPT, 32, SILVER_HI)

    bx = hx + logo_size + 20
    d.text((bx, hy + 6), "DIAMOND", font=_font(34), fill=TEXT)
    d.text((bx + 4, hy + 48), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)

    meta_r = CANVAS_W - M - PAD_X
    lbl = "СЧЁТ НА ОПЛАТУ"
    lbl_w = _tw(d, lbl, _font(14))
    d.text((meta_r - lbl_w, hy + 8), lbl, font=_font(14), fill=MUTED)

    num_str = f"№ {order_id}"
    num_w = _tw(d, num_str, _font(24))
    d.text((meta_r - num_w, hy + 34), num_str, font=_font(24), fill=TEXT)

    sep_y = hy + logo_size + 22
    d.line((PAD_X, sep_y, CANVAS_W - M - PAD_X, sep_y),
           fill=STACK_HDR + (255,), width=2)

    # ── HERO + INFO ──
    body_y = sep_y + 10
    body_h = CANVAS_H - PAD_Y - body_y - 32

    top_h = 200
    info_w = 500
    gap_top = 24

    top_y1 = body_y
    top_y2 = top_y1 + top_h

    hero_x1 = PAD_X
    hero_x2 = CANVAS_W - PAD_X - info_w - gap_top
    info_x1 = hero_x2 + gap_top
    info_x2 = CANVAS_W - PAD_X

    _gradient_box(img, (hero_x1, top_y1, hero_x2, top_y2),
                  GREEN, GREEN, alpha=18, radius=22)
    d.rounded_rectangle((hero_x1, top_y1, hero_x2, top_y2),
                        radius=22, outline=GREEN + (160,), width=3)

    icon_size = 110
    icon_x1 = hero_x1 + 40
    icon_y1 = top_y1 + (top_h - icon_size) // 2
    icon_x2 = icon_x1 + icon_size
    icon_y2 = icon_y1 + icon_size

    for i, a in enumerate([35, 50, 65]):
        gs = icon_size + 30 - i * 10
        _alpha_fill(img,
                    (icon_x1 + icon_size // 2 - gs // 2,
                     icon_y1 + icon_size // 2 - gs // 2,
                     icon_x1 + icon_size // 2 + gs // 2,
                     icon_y1 + icon_size // 2 + gs // 2),
                    GREEN, alpha=a, radius=gs // 2)

    _alpha_fill(img, (icon_x1, icon_y1, icon_x2, icon_y2),
                GREEN, alpha=70, radius=26)
    d.rounded_rectangle((icon_x1, icon_y1, icon_x2, icon_y2),
                        radius=26, outline=GREEN + (230,), width=3)
    _draw_icon(d, (icon_x1 + icon_x2) // 2, (icon_y1 + icon_y2) // 2 + 1,
               I_CHECK, 52, GREEN)

    tx = icon_x2 + 34
    d.text((tx, top_y1 + 40), "ИТОГО К ОПЛАТЕ",
           font=_font(15), fill=GREEN)

    sum_str = _fmt(total)
    sum_font = _font(90)
    sum_w = _tw(d, sum_str, sum_font)
    d.text((tx, top_y1 + 68), sum_str, font=sum_font, fill=TEXT)
    d.text((tx + sum_w + 16, top_y1 + 68 + 90 - 48),
           "Р", font=_font(36), fill=SILVER)

    _gradient_box(img, (info_x1, top_y1, info_x2, top_y2),
                  SILVER, SILVER, alpha=10, radius=22)
    d.rounded_rectangle((info_x1, top_y1, info_x2, top_y2),
                        radius=22, outline=INNER_BRD + (255,), width=2)

    pad_in = 22
    info_in_x1 = info_x1 + pad_in + 6
    info_in_x2 = info_x2 - pad_in - 6

    row_h = 30
    cur_y = top_y1 + 16

    def _info_row(label, value, value_color=TEXT):
        nonlocal cur_y
        d.text((info_in_x1, cur_y), label.upper(),
               font=_font(11), fill=MUTED)
        val_w = _tw(d, value, _font(15))
        d.text((info_in_x2 - val_w, cur_y - 2), value,
               font=_font(15), fill=value_color)
        cur_y += row_h

    _info_row("Статус", "Заказ оформляется", GREEN)
    _info_row("Заказчик", f"@{customer_name}")

    d.line((info_in_x1, cur_y + 2, info_in_x2, cur_y + 2),
           fill=INNER_BRD + (255,), width=1)
    cur_y += 12

    prod_shown = product_name
    if _tw(d, prod_shown, _font(15)) > (info_in_x2 - info_in_x1) - 100:
        while prod_shown and _tw(d, prod_shown + "…", _font(15)) > (info_in_x2 - info_in_x1) - 100:
            prod_shown = prod_shown[:-1]
        prod_shown += "…"

    _info_row("Товар", prod_shown, SILVER_HI)
    _info_row("Сумма", f"{_fmt(amount)} Р", SILVER_HI)

    if discount_percent > 0:
        _info_row("Скидка", f"−{discount_percent}%", GREEN)
    else:
        _info_row("Скидка", "—", DIM)

    # ── РЕКВИЗИТЫ 2×2 ──
    req_y1 = top_y2 + 20
    req_y2 = req_y1 + 434
    req_x1 = PAD_X
    req_x2 = CANVAS_W - M - PAD_X

    _gradient_box(img, (req_x1, req_y1, req_x2, req_y2),
                  SILVER, SILVER, alpha=6, radius=22)
    d.rounded_rectangle((req_x1, req_y1, req_x2, req_y2),
                        radius=22, outline=INNER_BRD + (255,), width=2)

    pad_req = 30
    h3_y = req_y1 + 26
    _draw_icon(d, req_x1 + pad_req + 12, h3_y + 9,
               I_CREDIT, 20, SILVER)
    d.text((req_x1 + pad_req + 38, h3_y),
           "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ",
           font=_font(16), fill=SILVER)

    grid_x1 = req_x1 + pad_req
    grid_x2 = req_x2 - pad_req
    grid_w = grid_x2 - grid_x1

    cell_gap = 16
    cell_w = (grid_w - cell_gap) // 2
    cell_h = 130

    grid_total_h = cell_h * 2 + cell_gap
    grid_y1 = h3_y + 30 + 20
    grid_y2 = req_y2 - pad_req

    free_h = grid_y2 - grid_y1
    if free_h > grid_total_h:
        grid_y1 += (free_h - grid_total_h) // 2

    for i, (bank_name, bank_num, bank_icon) in enumerate(REQUISITES):
        col = i % 2
        row = i // 2
        cx1 = grid_x1 + col * (cell_w + cell_gap)
        cy1 = grid_y1 + row * (cell_h + cell_gap)
        cx2 = cx1 + cell_w
        cy2 = cy1 + cell_h

        d.rounded_rectangle((cx1, cy1, cx2, cy2),
                            radius=16, fill=(24, 24, 32) + (255,),
                            outline=(40, 40, 47) + (255,), width=2)

        logo_size = 54
        lx = cx1 + 24
        ly = cy1 + (cell_h - logo_size) // 2

        _gradient_box(img, (lx, ly, lx + logo_size, ly + logo_size),
                      SILVER, SILVER, alpha=22, radius=14)
        d.rounded_rectangle((lx, ly, lx + logo_size, ly + logo_size),
                            radius=14, outline=SILVER + (130,), width=2)
        _draw_icon(d, lx + logo_size // 2, ly + logo_size // 2 + 1,
                   bank_icon, 24, SILVER_HI)

        info_x = lx + logo_size + 20
        info_cy = cy1 + cell_h // 2

        d.text((info_x, info_cy - 26),
               bank_name.upper(), font=_font(13), fill=MUTED)
        d.text((info_x, info_cy - 2),
               bank_num, font=_font(20), fill=TEXT)

    # ── BOTTOM BAR ──
    bot_y1 = req_y2 + 20
    bot_y2 = bot_y1 + 100
    bot_x1 = PAD_X
    bot_x2 = CANVAS_W - M - PAD_X

    _alpha_fill(img, (bot_x1, bot_y1, bot_x2, bot_y2),
                GOLD, alpha=22, radius=14)
    d.rounded_rectangle((bot_x1, bot_y1, bot_x2, bot_y2),
                        radius=14, outline=GOLD + (140,), width=2)

    bot_cy = (bot_y1 + bot_y2) // 2

    clock_cx = bot_x1 + 34
    _draw_icon(d, clock_cx, bot_cy, I_CLOCK, 22, GOLD)

    deadline_text = f"Оплатить до: {deadline_str} · после оплаты пришлите чек в тикет"
    d.text((clock_cx + 28, bot_cy), deadline_text,
           font=_font(15), fill=TEXT_SOFT, anchor="lm")

    steps = ["Оплата", "Чек", "Проверка", "Готово"]
    step_num_size = 26
    step_text_gap = 8
    step_gap = 18

    step_font = _font(13)
    num_font = _font(12)

    step_widths = []
    for name in steps:
        tw = _tw(d, name, step_font)
        step_widths.append(step_num_size + step_text_gap + tw)

    total_steps_w = sum(step_widths) + step_gap * (len(steps) - 1)
    cur_x = bot_x2 - 28 - total_steps_w

    for i, name in enumerate(steps):
        is_active = (i == 0)

        circle_x1 = cur_x
        circle_y1 = bot_cy - step_num_size // 2
        circle_x2 = circle_x1 + step_num_size
        circle_y2 = circle_y1 + step_num_size

        if is_active:
            _alpha_fill(img, (circle_x1, circle_y1, circle_x2, circle_y2),
                        GREEN, alpha=65, radius=step_num_size // 2)
            d.rounded_rectangle((circle_x1, circle_y1, circle_x2, circle_y2),
                                radius=step_num_size // 2,
                                outline=GREEN + (230,), width=2)
            num_color = GREEN
        else:
            d.rounded_rectangle((circle_x1, circle_y1, circle_x2, circle_y2),
                                radius=step_num_size // 2,
                                fill=(40, 40, 47) + (255,))
            num_color = (184, 188, 200)

        num_str = str(i + 1)
        nw = _tw(d, num_str, num_font)
        d.text((circle_x1 + step_num_size // 2 - nw // 2,
                circle_y1 + step_num_size // 2 - num_font.size // 2 - 2),
               num_str, font=num_font, fill=num_color)

        text_x = circle_x2 + step_text_gap
        text_color = GREEN if is_active else MUTED
        d.text((text_x, bot_cy), name, font=step_font,
               fill=text_color, anchor="lm")

        cur_x += step_widths[i] + step_gap

    # ── FOOTER ──
    footer_y = CANVAS_H - PAD_Y + 6
    d.line((PAD_X, footer_y - 12, CANVAS_W - M - PAD_X, footer_y - 12),
           fill=STACK_HDR + (255,), width=2)
    d.text((PAD_X, footer_y),
           "Счёт сгенерирован автоматически · Diamond Shop",
           font=_font(13), fill=DIM)
    right_f = "Шаг 1 · Оплата"
    rw = _tw(d, right_f, _font(13))
    d.text((CANVAS_W - M - PAD_X - rw, footer_y),
           right_f, font=_font(13), fill=DIM)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    logger.info(f"Счёт сгенерирован: {order_id} · {total} Р")
    return buf

def generate_receipt_id() -> str:
    return f"D-{int(time.time())}-{random.randint(100, 999)}"

# ============================================================
# БЛОК 2: VIEW СЧЁТА
# ============================================================
EMOJI_BANKS = PartialEmoji(name="banks", id=1556311895106003075)
EMOJI_PHONE = PartialEmoji(name="phone", id=1556311870627905657)

REQ_OPTIONS = {
    "tbank": {
        "label": "Т-Банк",
        "description": "Перевод на карту Т-Банк",
        "emoji": EMOJI_BANKS,
        "title": "Т-Банк",
        "value": "2200 7020 8029 9345",
        "type": "Карта",
    },
    "sbp": {
        "label": "СБП",
        "description": "Система быстрых платежей · телефон",
        "emoji": EMOJI_PHONE,
        "title": "СБП (Система быстрых платежей)",
        "value": "+7 983 694 76 41",
        "type": "Телефон",
    },
    "ozon": {
        "label": "ОзонБанк",
        "description": "Перевод на карту ОзонБанк",
        "emoji": EMOJI_BANKS,
        "title": "ОзонБанк",
        "value": "2204 3204 4881 5151",
        "type": "Карта",
    },
    "alfa": {
        "label": "АльфаБанк",
        "description": "Перевод на карту АльфаБанк",
        "emoji": EMOJI_BANKS,
        "title": "АльфаБанк",
        "value": "2200 1545 6426 7465",
        "type": "Карта",
    },
}

class ReceiptSelect(Select):
    def __init__(self):
        options = [
            SelectOption(
                label=data["label"],
                description=data["description"],
                emoji=data["emoji"],
                value=key,
            )
            for key, data in REQ_OPTIONS.items()
        ]
        super().__init__(
            placeholder="Выберите банк для оплаты...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="receipt:req_select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        key = inter.data.values[0]
        data = REQ_OPTIONS.get(key)
        if not data:
            return await inter.response.send_message(
                "❌ Реквизит не найден.", ephemeral=True,
            )
        try:
            e1 = disnake.Embed(color=6776679)
            e1.set_image(url=IMG_STRIPE)

            e2 = disnake.Embed(
                title=f"{data['title']} · {data['type']}",
                description=(
                    f"> **Номер для перевода:**\n"
                    f"> `{data['value']}`\n\n"
                    f"> Нажми на номер — он скопируется."
                ),
                color=6776679,
            )
            e2.set_image(url=IMG_STRIPE)
            e2.set_footer(text="Нажми на номер — он скопируется")

            await inter.response.send_message(
                embeds=[e1, e2],
                ephemeral=True,
            )
        except Exception as e:
            logger.warning(f"ReceiptSelect send req {key}: {e}")

class ReceiptView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ReceiptSelect())

# ============================================================
# БЛОК 3: РЕНДЕРЫ ТИКЕТОВ (Политика)
# ============================================================
REVIEW_CHANNEL_NAME = "отзывы"

def _draw_policy_block(img, d, x, y, w, h, color, icon_code, title, text):
    border = tuple(min(int(c + (255 - c) * 0.25), 255) for c in color)
    d.rounded_rectangle((x, y, x + w, y + h), radius=14,
                        fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)
    d.rounded_rectangle((x, y + 10, x + 5, y + h - 10), radius=2,
                        fill=color + (255,))

    icon_size = 52
    ib_x = x + 22
    ib_y = y + 18

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                color, alpha=65, radius=13)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=13, outline=color + (210,), width=2)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               icon_code, 24, color)

    tx = ib_x + icon_size + 18
    d.text((tx, ib_y + 4), title.upper(), font=_font(16), fill=color)

    text_font = _font(14)
    max_w = x + w - 24 - tx
    lines = _wrap(d, text, text_font, max_w, max_lines=3)
    text_y = ib_y + 30
    for i, line in enumerate(lines):
        d.text((tx, text_y + i * 22), line, font=text_font, fill=TEXT_SOFT)

def _draw_left_block(img, d, x, y, w, h, color, icon_code, label, value):
    border = tuple(min(int(c + (255 - c) * 0.25), 255) for c in color)
    light = tuple(min(int(c + (255 - c) * 0.45), 255) for c in color)

    _gradient_box(img, (x, y, x + w, y + h), color, color, alpha=30, radius=15)
    d.rounded_rectangle((x, y, x + w, y + h),
                        radius=15, outline=border + (255,), width=3)
    d.rounded_rectangle((x + 4, y + 12, x + 8, y + h - 12),
                        radius=2, fill=color + (255,))

    icon_size = 54
    ib_x = x + 20
    ib_y = y + (h - icon_size) // 2

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                color, alpha=70, radius=14)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=14, outline=border + (200,), width=2)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               icon_code, 24, color)

    tx = ib_x + icon_size + 16
    d.text((tx, y + 16), label.upper(), font=_font(13), fill=light)
    val_font = _font(22)
    max_w = x + w - 18 - tx
    val_shown = _ellipsis(d, value, val_font, max_w)
    d.text((tx, y + 44), val_shown, font=val_font, fill=color)

def _draw_left_panel_rating(img, d, box, top_icon, top_label, top_value, blocks):
    _draw_stack_panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 28

    bal_icon_size = 84
    ib_x = x1 + pad
    ib_y = y1 + pad

    _gradient_box(img, (ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                  SILVER, SILVER_DIM, alpha=42, radius=22)
    d.rounded_rectangle((ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                        radius=22, outline=SILVER + (200,), width=3)
    _draw_icon(d, ib_x + bal_icon_size // 2, ib_y + bal_icon_size // 2 + 1,
               top_icon, 34, SILVER_HI)

    lbl_x = ib_x + bal_icon_size + 20
    d.text((lbl_x, ib_y + 8), top_label.upper(), font=_font(14), fill=MUTED)

    top_str = str(top_value)
    val_font = _font(34)
    max_w = x2 - pad - lbl_x - 16
    while _tw(d, top_str, val_font) > max_w and val_font.size > 20:
        val_font = _font(val_font.size - 2)
    d.text((lbl_x, ib_y + 32), top_str, font=val_font, fill=TEXT)

    sep_y = ib_y + bal_icon_size + 26
    d.line((x1 + pad, sep_y, x2 - pad, sep_y),
           fill=STACK_HDR + (255,), width=2)

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

def render_policy(user_id: int) -> io.BytesIO:
    img, d = _base_canvas(user_id, "политика магазина", "действует с 26.07.26")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel_rating(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        top_icon=I_RECEIPT, top_label="Документ", top_value="Политика",
        blocks=[
            {"color": BLUE,  "icon": I_CLOCK,   "label": "Срок обработки", "value": "до 2 дней"},
            {"color": RED,   "icon": I_ROTATE,  "label": "Возврат",        "value": "60% от суммы"},
            {"color": GREEN, "icon": I_SHIELD,  "label": "Гарантия",       "value": "100% выдача"},
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Политика покупки", "читай внимательно")

    items_y = body_y + 118
    items_bottom = body_y + body_h - 22 - 60
    n = 4
    gap_item = 12
    item_h = (items_bottom - items_y - gap_item * (n - 1)) // n

    rules = [
        {"color": BLUE,  "icon": I_CLOCK,  "title": "Сроки обработки заказа",
         "text": "Максимальный срок — 2 рабочих дня с момента подтверждения оплаты. "
                 "В большинстве случаев товар выдаётся в течение 3 часов. "
                 "Часовой пояс продавца — МСК+5 (UTC+8)."},
        {"color": RED,   "icon": I_ROTATE, "title": "Возврат средств",
         "text": "Если вы отказываетесь после оплаты — возврат 60% от суммы. "
                 "40% удерживаются для покрытия комиссий платёжных систем и обработки."},
        {"color": GOLD,  "icon": I_BAN,    "title": "Стоп-лист",
         "text": "Массовые пинги персонала, продавца или менеджеров, "
                 "а также агрессивное поведение переводят тикет в «стоп-лист». "
                 "Такие заказы обрабатываются в последнюю очередь."},
        {"color": GREEN, "icon": I_CHECK,  "title": "Подтверждение оплаты",
         "text": "Для подтверждения необходимо прикрепить чек оплаты и указать, "
                 "куда перевод был сделан. После проверки менеджер подтвердит оплату — "
                 "и продавец начнёт работу."},
    ]

    for i, rule in enumerate(rules):
        cy = items_y + i * (item_h + gap_item)
        _draw_policy_block(img, d, rx1, cy, rx2 - rx1, item_h,
                           rule["color"], rule["icon"], rule["title"], rule["text"])

    hint_h = 48
    hint_y = items_bottom + 12
    _alpha_fill(img, (rx1, hint_y, rx2, hint_y + hint_h), GOLD, alpha=22, radius=11)
    d.rounded_rectangle((rx1, hint_y, rx2, hint_y + hint_h),
                        radius=11, outline=GOLD + (150,), width=2)
    _draw_icon(d, rx1 + 24, hint_y + hint_h // 2, I_INFO, 18, GOLD)
    d.text((rx1 + 48, hint_y + hint_h // 2 - 9),
           "Незнание политики не освобождает от ответственности. Действует с 26.07.26",
           font=_font(14), fill=TEXT_SOFT)

    _draw_footer(d, f"Политика магазина · данные на {_now_msk_str()} МСК", "политика · v1.0")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf

async def show_policy(inter: disnake.MessageInteraction):
    if not inter.response.is_done():
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

    try:
        buf = await asyncio.to_thread(render_policy, inter.author.id)
        fname = f"policy_{inter.author.id}.png"
        file = disnake.File(buf, filename=fname)
        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{fname}")
        await inter.followup.send(embed=embed, file=file, ephemeral=True)
    except Exception as e:
        logger.exception(f"show_policy: {e}")
        try:
            if inter.response.is_done():
                await inter.followup.send(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
            else:
                await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
        except Exception:
            pass

# ============================================================
# БЛОК 4: КОДЕКС МАГАЗИНА
# ============================================================
# 👇 Employer (1471190371181789234) УДАЛЕН
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
        "role_id": 1457964854441672806,
        "name": "Advertiser",
        "tag": "ADVERT",
        "advance": 375,
        "salary": 875,
        "color": (0xb1, 0xc5, 0xf6),
        "icon": I_SEARCH,
    },
]

def _draw_left_panel_work(img, d, box, extra_blocks=None, header_icon=I_GEM):
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

            icon_s = 50
            ib2_x = bx1 + 20
            ib2_y = by1 + (bb_h - icon_s) // 2
            _alpha_fill(img, (ib2_x, ib2_y, ib2_x + icon_s, ib2_y + icon_s),
                        base_color, alpha=70, radius=13)
            d.rounded_rectangle((ib2_x, ib2_y, ib2_x + icon_s, ib2_y + icon_s),
                                radius=13, outline=border_color + (200,), width=2)
            _draw_icon(d, ib2_x + icon_s // 2, ib2_y + icon_s // 2 + 1,
                       blk.get("icon", I_INFO), 24, base_color)

            tx = ib2_x + icon_s + 16
            d.text((tx, by1 + 14), blk.get("label", "").upper(),
                   font=_font(13), fill=text_color)
            bv = blk.get("value", "—")
            val_font = _font(24)
            max_w2 = bx2 - 18 - tx
            bv_shown = _ellipsis(d, bv, val_font, max_w2)
            d.text((tx, by1 + 42), bv_shown, font=val_font, fill=base_color)

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

    _draw_left_panel_work(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        extra_blocks=[
            {"label": "Дата аванса", "value": "15 число",
             "icon": I_CALENDAR, "color": BLUE},
            {"label": "Дата зарплаты", "value": "29 число",
             "icon": I_CALENDAR, "color": GREEN},
            {"label": "Ролей в системе", "value": f"{len(SALARY_ROLES)}",
             "icon": I_USERS, "color": SILVER},
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

    _draw_footer(d, "Зарплата начисляется в Diamond Coins", "стр. 1 / 2")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf

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

    example = rule.get("example")
    if example:
        ex_y = text_y + len(lines) * 24 + 12
        ex_font = _font(15)
        ex_w = _tw(d, example, ex_font) + 60
        ex_h = 36

        _alpha_fill(img, (x + 24, ex_y, x + 24 + ex_w, ex_y + ex_h),
                    color, alpha=45, radius=9)
        d.rounded_rectangle((x + 24, ex_y, x + 24 + ex_w, ex_y + ex_h),
                            radius=9, outline=light + (200,), width=2)

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

    _draw_left_panel_work(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        extra_blocks=[
            {"label": "Строго для", "value": "Sales Manager",
             "icon": I_USER_TIE, "color": BLUE},
            {"label": "Нарушение", "value": "выговор",
             "icon": I_WARNING, "color": RED},
            {"label": "Обязательно", "value": "к прочтению",
             "icon": I_CHECK, "color": GREEN},
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
        {"icon": I_HAND, "title": "Вежливость и споры", "subtitle": "правило №1",
         "text": ("Отвечаем вежливо, спорные ситуации решаем через "
                  "главного администратора. Адекватность в тикетах "
                  "должна быть всегда — если покупатель неадекватен, "
                  "сообщить об этом старшему."),
         "color": GREEN},
        {"icon": I_PEN, "title": "Название тикета", "subtitle": "правило №2",
         "text": ("Название должно полностью отображать товар. "
                  "Указываем по схеме Категория-Подкатегория-Подкатегория. "
                  "Иные названия караются выговором."),
         "color": SILVER,
         "example": "Например: Дискорд-нитро-1м"},
        {"icon": I_CHECK, "title": "Кнопка «Оплата»", "subtitle": "правило №3",
         "text": ("Кнопкой «Оплата» можно пользоваться только после "
                  "фактического подтверждения оплаты покупателем. "
                  "До подтверждения — кнопка не нажимается."),
         "color": BLUE},
        {"icon": I_WARNING, "title": "Ответственность", "subtitle": "правило №4",
         "text": ("За нарушение любого из пунктов выше — выговор. "
                  "Систематические нарушения ведут к снятию "
                  "с должности Sales Manager."),
         "color": RED},
    ]

    for i, rule in enumerate(rules):
        cy = items_y + i * (item_h + gap_item)
        _draw_rule_card(img, d, rx1, cy, rx2 - rx1, item_h, rule)

    _draw_footer(d, "Обязательно к прочтению каждым менеджером", "стр. 2 / 2")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
