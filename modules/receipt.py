# -*- coding: utf-8 -*-
"""
Pillow-рендер счёта на оплату (Premium).
Дизайн: акцент на реквизитах, крупные цифры, шаги оплаты.
Размер 1800×1000, стиль 1:1 с остальными рендерами.
"""
import io
import os
import time
import random
from datetime import datetime, timezone, timedelta
from typing import Optional

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

GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
GOLD      = (247, 201, 145)

CARD_BRD  = (74, 74, 79)


# ============================================================
# FA5-ИКОНКИ
# ============================================================
I_GEM        = 0xf3a5
I_RECEIPT    = 0xf543
I_CHECK      = 0xf00c
I_BUILDING   = 0xf19c
I_MOBILE     = 0xf3cd
I_CLOCK      = 0xf017
I_CREDIT     = 0xf09d


# ============================================================
# SANITIZE — убираем эмодзи и нестандартные юникоды
# ============================================================
_ALLOWED_SPECIAL = set("—–‑‒―“”«»„‘’…№·•▪●◆◇■□")


def _sanitize(text: str, fallback: str = "") -> str:
    """
    Оставляет: ASCII, кириллицу, латиницу с диакритикой,
    распространённые спецсимволы. Убирает эмодзи и нестандартные
    unicode-глифы, которые могут не отрендериться в нашем шрифте.
    """
    if not text:
        return fallback

    out = []
    for ch in text:
        cp = ord(ch)
        # ASCII printable
        if 0x20 <= cp <= 0x7E:
            out.append(ch)
            continue
        # Кириллица
        if 0x0400 <= cp <= 0x04FF:
            out.append(ch)
            continue
        # Латиница Extended
        if 0x00C0 <= cp <= 0x017F:
            out.append(ch)
            continue
        # Разрешённые спецсимволы
        if ch in _ALLOWED_SPECIAL:
            out.append(ch)
            continue
        # всё остальное (эмодзи, иконки, странные юникоды) — выкидываем

    result = "".join(out).strip()
    while "  " in result:
        result = result.replace("  ", " ")
    if not result:
        return fallback
    return result


# ============================================================
# УТИЛИТЫ
# ============================================================
def _tw(d, text, font):
    b = d.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


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


# ============================================================
# КАРКАС
# ============================================================
CANVAS_W, CANVAS_H = 1800, 1000
M = 14
PAD_X = 40
PAD_Y = 40

MSK = timezone(timedelta(hours=3))


# ============================================================
# РЕКВИЗИТЫ
# ============================================================
REQUISITES = [
    ("Т-Банк",     "2200 7020 8029 9345", I_BUILDING),
    ("АльфаБанк",  "2200 1545 6426 7465", I_BUILDING),
    ("ОзонБанк",   "2204 3204 4881 5151", I_BUILDING),
    ("СБП",        "+7 983 694 76 41",    I_MOBILE),
]


# ============================================================
# ГЛАВНАЯ
# ============================================================
def generate_receipt_png(
    manager_name: str,
    customer_name: str,
    product_name: str,
    amount: int,
    discount_percent: int = 0,
    order_id: Optional[str] = None,
) -> io.BytesIO:
    """1800×1000 · Premium-дизайн счёта."""

    # ── Sanitize всех входных строк ──
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

    # ── Холст ──
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,))
    d = ImageDraw.Draw(img)

    # ── Внешний card ──
    d.rounded_rectangle(
        (M, M, CANVAS_W - 1 - M, CANVAS_H - 1 - M),
        radius=28, fill=CARD_TOP + (255,),
        outline=CARD_BRD + (255,), width=3,
    )

    # ═════════════════════════════════════════════════════════
    # 1. HEADER
    # ═════════════════════════════════════════════════════════
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

    # ═════════════════════════════════════════════════════════
    # 2. HERO + INFO
    # ═════════════════════════════════════════════════════════
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

    # ── HERO ──
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

    # ── INFO ──
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

    _info_row("Менеджер", f"@{manager_name}")
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

    # ═════════════════════════════════════════════════════════
    # 3. РЕКВИЗИТЫ 2×2
    # ═════════════════════════════════════════════════════════
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

    # ═════════════════════════════════════════════════════════
    # 4. BOTTOM BAR
    # ═════════════════════════════════════════════════════════
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

    # ═════════════════════════════════════════════════════════
    # 5. FOOTER
    # ═════════════════════════════════════════════════════════
    footer_y = CANVAS_H - PAD_Y + 6
    d.line((PAD_X, footer_y - 12, CANVAS_W - M - PAD_X, footer_y - 12),
           fill=STACK_HDR + (255,), width=2)

    left_f = "Счёт сгенерирован автоматически · Diamond Shop"
    d.text((PAD_X, footer_y), left_f, font=_font(13), fill=DIM)

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
