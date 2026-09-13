# -*- coding: utf-8 -*-
import os
import io
import time
import random
from datetime import datetime, timezone, timedelta
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, DATA_DIR, logger

FONT_BOLD_PATH = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")

_FONT_CACHE = {}


def _get_font(size: int):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        font = ImageFont.truetype(FONT_BOLD_PATH, size)
    except Exception:
        font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


def _text_size(draw, text, font) -> tuple:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_centered(draw, cx, y, text, font, fill):
    tw, _ = _text_size(draw, text, font)
    draw.text((cx - tw // 2, y), text, font=font, fill=fill)
    return tw


# ============================================================
# ВЕКТОРНЫЕ ИКОНКИ (аналог Font Awesome)
# ============================================================
def _draw_cart(draw, cx, cy, size, color, width=2):
    """Корзина."""
    s = size
    hx1 = cx - s * 0.55
    hx2 = cx - s * 0.30
    hy = cy - s * 0.42
    bt_y = cy - s * 0.18
    bb_y = cy + s * 0.22
    bl_t = cx - s * 0.35
    br_t = cx + s * 0.38
    bl_b = cx - s * 0.27
    br_b = cx + s * 0.30
    draw.line([(hx1, hy), (hx2, hy), (cx - s * 0.35, bt_y)], fill=color, width=width, joint="curve")
    draw.line([(bl_t, bt_y), (br_t, bt_y), (br_b, bb_y), (bl_b, bb_y), (bl_t, bt_y)],
              fill=color, width=width, joint="curve")
    wr = max(2, int(s * 0.07))
    w1x = cx - s * 0.22
    w2x = cx + s * 0.24
    wy = cy + s * 0.42
    draw.ellipse((w1x - wr, wy - wr, w1x + wr, wy + wr), outline=color, width=width)
    draw.ellipse((w2x - wr, wy - wr, w2x + wr, wy + wr), outline=color, width=width)


def _draw_user(draw, cx, cy, size, color, width=1):
    """Юзер (голова + плечи)."""
    head_r = size * 0.20
    head_cy = cy - size * 0.22
    draw.ellipse((cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r),
                 outline=color, width=width)
    body_w = size * 0.38
    body_top = cy + size * 0.05
    body_bottom = cy + size * 0.42
    draw.arc((cx - body_w, body_top, cx + body_w, body_bottom),
             start=180, end=360, fill=color, width=width)


def _draw_box(draw, cx, cy, size, color, width=1):
    """Коробка (изометрия)."""
    w = size * 0.42
    h = size * 0.42
    # Верх крышки
    draw.line((cx - w, cy - h * 0.35, cx, cy - h), fill=color, width=width)
    draw.line((cx, cy - h, cx + w, cy - h * 0.35), fill=color, width=width)
    # Боковые грани
    draw.line((cx - w, cy - h * 0.35, cx - w, cy + h * 0.55), fill=color, width=width)
    draw.line((cx + w, cy - h * 0.35, cx + w, cy + h * 0.55), fill=color, width=width)
    # Низ
    draw.line((cx - w, cy + h * 0.55, cx, cy + h), fill=color, width=width)
    draw.line((cx + w, cy + h * 0.55, cx, cy + h), fill=color, width=width)
    # Центральный шов
    draw.line((cx, cy - h, cx, cy + h), fill=color, width=width)


def _draw_credit_card(draw, cx, cy, size, color, width=1):
    """Карта оплаты."""
    w = size * 0.5
    h = size * 0.35
    draw.rounded_rectangle(
        (cx - w, cy - h, cx + w, cy + h),
        radius=2, outline=color, width=width
    )
    # Магнитная полоска
    draw.line((cx - w, cy - h * 0.35, cx + w, cy - h * 0.35), fill=color, width=width)


def _draw_clock(draw, cx, cy, size, color, width=1):
    """Часы."""
    r = size * 0.42
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=width)
    draw.line((cx, cy, cx, cy - r * 0.6), fill=color, width=width)
    draw.line((cx, cy, cx + r * 0.55, cy), fill=color, width=width)


def _draw_divider(draw, y, PAD, W):
    """Линия с маленькой корзиной по центру."""
    cx = W // 2
    line_color = (58, 58, 63)
    draw.line((PAD, y, cx - 20, y), fill=line_color, width=1)
    draw.line((cx + 20, y, W - PAD, y), fill=line_color, width=1)
    _draw_cart(draw, cx, y, 14, (74, 74, 79), width=1)


# ============================================================
# ГЕНЕРАЦИЯ ЧЕКА
# ============================================================
def generate_receipt_png(
    manager_name: str,
    ticket_name: str,
    amount: int,
    discount_percent: int = 0,
    order_id: Optional[str] = None,
) -> io.BytesIO:
    """1200×800 (3:2). Дизайн — 1-в-1 по HTML-макету."""
    if order_id is None:
        order_id = f"D-{int(time.time())}-{random.randint(100, 999)}"

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%d.%m.%Y · %H:%M")
    deadline_str = (now + timedelta(hours=1)).strftime("%d.%m.%Y · %H:%M")

    discount_rub = int(amount * discount_percent / 100)
    total = max(amount - discount_rub, 0)

    W, H = 1200, 800
    M = 15
    PAD = 40

    # Цвета
    BG = (10, 10, 12)
    CARD_TOP = (26, 26, 31)
    CARD_BOT = (20, 20, 26)
    INNER = (20, 20, 26)
    INNER_BORDER = (42, 42, 47)
    BORDER = (74, 74, 79)
    TEXT = (255, 255, 255)
    MUTED = (136, 136, 136)
    GREEN = (46, 204, 113)
    GREEN_BG = (18, 44, 28)
    LOGO_BG = (74, 74, 79)
    LOGO_ICON = (224, 224, 224)
    LINE = (42, 42, 47)
    DASH = (34, 34, 34)
    STEPS_OFF = (42, 42, 47)

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Мягкий фон
    draw.ellipse((W - 380, -180, W + 80, 280), fill=(16, 16, 20))
    draw.ellipse((-140, H - 260, 220, H + 100), fill=(14, 22, 18))

    # Внешняя карточка
    draw.rounded_rectangle((M, M, W - M, H - M), radius=22, fill=CARD_BOT, outline=BORDER, width=2)
    draw.rounded_rectangle((M + 1, M + 1, W - M - 1, H // 2), radius=22, fill=CARD_TOP)

    # ============ 1. ШАПКА ============
    y = M + 30
    logo_box = 54
    draw.rounded_rectangle((PAD, y, PAD + logo_box, y + logo_box), radius=14, fill=LOGO_BG)
    _draw_cart(draw, PAD + logo_box // 2, y + logo_box // 2, 28, LOGO_ICON, width=2)

    draw.text((PAD + logo_box + 16, y + 2), "DIAMOND", font=_get_font(26), fill=TEXT)
    draw.text((PAD + logo_box + 18, y + 38), "SHOP & ECOSYSTEM", font=_get_font(11), fill=MUTED)

    lbl_text = "Заказ "
    num_text = f"№{order_id}"
    lbl_font = _get_font(13)
    num_font = _get_font(15)
    date_font = _get_font(13)
    lw, _ = _text_size(draw, lbl_text, lbl_font)
    nw, _ = _text_size(draw, num_text, num_font)
    dx = W - PAD - (lw + nw)
    draw.text((dx, y + 10), lbl_text, font=lbl_font, fill=MUTED)
    draw.text((dx + lw, y + 8), num_text, font=num_font, fill=TEXT)
    dw, _ = _text_size(draw, date_str, date_font)
    draw.text((W - PAD - dw, y + 34), date_str, font=date_font, fill=MUTED)

    y += logo_box + 20  # = 119

    # ============ 2. ГЕРОЙ ============
    cx = W // 2
    _draw_centered(draw, cx, y, "ИТОГО К ОПЛАТЕ", _get_font(14), MUTED)
    y += 26

    total_text = f"{total} Р"
    font_size = 72
    tw, _ = _text_size(draw, total_text, _get_font(font_size))
    while tw > W - PAD * 2 - 200 and font_size > 40:
        font_size -= 4
        tw, _ = _text_size(draw, total_text, _get_font(font_size))
    _draw_centered(draw, cx, y, total_text, _get_font(font_size), TEXT)
    y += font_size + 6

    if discount_percent > 0:
        badge_text = f"Скидка {discount_percent}%  ·  −{discount_rub} Р"
        bf = _get_font(14)
        bw, bh = _text_size(draw, badge_text, bf)
        pad_bx, pad_by = 18, 7
        badge_w = bw + pad_bx * 2
        badge_h = bh + pad_by * 2
        bx = cx - badge_w // 2
        draw.rounded_rectangle((bx, y, bx + badge_w, y + badge_h),
                               radius=10, fill=GREEN_BG, outline=GREEN, width=1)
        draw.text((bx + pad_bx, y + pad_by), badge_text, font=bf, fill=GREEN)
        y += badge_h

    # ============ 3. РАЗДЕЛИТЕЛЬ ============
    y += 22
    _draw_divider(draw, y, PAD, W)
    y += 18

    # ============ 4. МЕНЕДЖЕР / ЗАКАЗ ============
    meta_h = 66
    gap_x = 14
    card_w = (W - PAD * 2 - gap_x) // 2

    # Менеджер — зелёная
    draw.rounded_rectangle((PAD, y, PAD + card_w, y + meta_h),
                           radius=14, fill=GREEN_BG, outline=GREEN, width=2)
    _draw_user(draw, PAD + 26, y + meta_h // 2, 16, GREEN, width=2)
    draw.text((PAD + 46, y + 12), "МЕНЕДЖЕР", font=_get_font(10), fill=GREEN)
    draw.text((PAD + 46, y + 32), manager_name[:24], font=_get_font(19), fill=TEXT)

    # Заказ — серая
    cx2 = PAD + card_w + gap_x
    draw.rounded_rectangle((cx2, y, cx2 + card_w, y + meta_h),
                           radius=14, fill=INNER, outline=BORDER, width=2)
    _draw_box(draw, cx2 + 26, y + meta_h // 2, 16, MUTED, width=1)
    draw.text((cx2 + 46, y + 12), "ЗАКАЗ", font=_get_font(10), fill=MUTED)
    draw.text((cx2 + 46, y + 32), ticket_name[:24], font=_get_font(19), fill=TEXT)

    y += meta_h + 14

    # ============ 5. ТАБЛИЦА ============
    items_top = y
    rows = 1 + (1 if discount_percent > 0 else 0) + 1
    items_h = 30 + rows * 26 + 12

    draw.rounded_rectangle((PAD, items_top, W - PAD, items_top + items_h),
                           radius=14, fill=INNER, outline=INNER_BORDER, width=1)

    ip = 18
    draw.text((PAD + ip, items_top + 8), "ТОВАР / УСЛУГА", font=_get_font(10), fill=MUTED)
    hdr = "СУММА"
    hw, _ = _text_size(draw, hdr, _get_font(10))
    draw.text((W - PAD - ip - hw, items_top + 8), hdr, font=_get_font(10), fill=MUTED)
    draw.line((PAD + ip, items_top + 26, W - PAD - ip, items_top + 26), fill=LINE, width=1)

    row_y = items_top + 32
    item_font = _get_font(14)
    draw.text((PAD + ip, row_y), ticket_name[:40], font=item_font, fill=TEXT)
    amt_str = f"{amount} Р"
    aw, _ = _text_size(draw, amt_str, item_font)
    draw.text((W - PAD - ip - aw, row_y), amt_str, font=item_font, fill=TEXT)
    row_y += 24

    if discount_percent > 0:
        disc_font = _get_font(14)
        draw.text((PAD + ip, row_y), f"Скидка ({discount_percent}%)", font=disc_font, fill=GREEN)
        ds = f"−{discount_rub} Р"
        dw_, _ = _text_size(draw, ds, disc_font)
        draw.text((W - PAD - ip - dw_, row_y), ds, font=disc_font, fill=GREEN)
        row_y += 24

    draw.line((PAD + ip, row_y + 2, W - PAD - ip, row_y + 2), fill=GREEN, width=2)
    row_y += 8
    tf = _get_font(18)
    draw.text((PAD + ip, row_y), "Итого к оплате", font=tf, fill=TEXT)
    ts = f"{total} Р"
    tw_, _ = _text_size(draw, ts, tf)
    draw.text((W - PAD - ip - tw_, row_y), ts, font=tf, fill=GREEN)

    y = items_top + items_h + 12

    # ============ 6. РЕКВИЗИТЫ (растягиваем на всё оставшееся место) ============
    # Нижняя область (срок + шаги + отступы) = 80px
    bottom_area_h = 80
    content_bottom = H - M - 30
    req_top = y
    req_h = content_bottom - req_top - bottom_area_h
    if req_h < 160:
        req_h = 160

    draw.rounded_rectangle((PAD, req_top, W - PAD, req_top + req_h),
                           radius=14, fill=INNER, outline=INNER_BORDER, width=1)

    # Заголовок с иконкой карты
    _draw_credit_card(draw, PAD + 24, req_top + 22, 16, MUTED, width=1)
    draw.text((PAD + 42, req_top + 15), "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ", font=_get_font(11), fill=MUTED)

    req_data = [
        ("Т-Банк", "2200 7020 8029 9345"),
        ("АльфаБанк", "2200 1545 6426 7465"),
        ("ОзонБанк", "2204 3204 4881 5151"),
        ("СБП", "+7 983 694 76 41"),
    ]

    # Внутренние отступы
    inner_top = req_top + 50
    inner_bottom = req_top + req_h - 15
    available = inner_bottom - inner_top
    row_h = available // 2

    col_gap = 40
    inner_side = 24
    col_w = (W - PAD * 2 - inner_side * 2 - col_gap) // 2

    k_font = _get_font(10)
    v_font = _get_font(16)

    for i, (key, val) in enumerate(req_data):
        col = i % 2
        row = i // 2
        item_x = PAD + inner_side + col * (col_w + col_gap)
        row_y_start = inner_top + row * row_h
        row_y_center = row_y_start + row_h // 2

        # Разделитель после первой строки (по обеим колонкам)
        if row == 0:
            sep_y = inner_top + row_h
            draw.line((PAD + inner_side, sep_y, W - PAD - inner_side, sep_y),
                      fill=DASH, width=1)

        # key (label сверху)
        draw.text((item_x, row_y_center - 20), key.upper(), font=k_font, fill=MUTED)
        # value
        vw, _ = _text_size(draw, val, v_font)
        draw.text((item_x + col_w - vw, row_y_center - 4), val, font=v_font, fill=TEXT)

    y = req_top + req_h + 14

    # ============ 7. НИЗ (срок + шаги) ============
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)
    y += 14

    # Срок
    _draw_clock(draw, PAD + 10, y + 10, 16, MUTED, width=1)
    dfont = _get_font(12)
    draw.text((PAD + 24, y + 3), "Оплатить до:", font=dfont, fill=MUTED)
    lw_, _ = _text_size(draw, "Оплатить до: ", dfont)
    draw.text((PAD + 24 + lw_, y + 1), deadline_str, font=_get_font(13), fill=TEXT)

    # Шаги
    steps = ["Оплата", "Чек", "Проверка", "Готово"]
    step_font = _get_font(11)
    n_font = _get_font(10)
    step_gap = 14
    step_widths = []
    for name in steps:
        tw_, _ = _text_size(draw, name, step_font)
        step_widths.append(18 + 6 + tw_)
    total_steps_w = sum(step_widths) + step_gap * (len(steps) - 1)

    sx = W - PAD - total_steps_w
    for i, name in enumerate(steps):
        w = step_widths[i]
        circle_x = sx
        circle_y = y + 4
        circle_size = 18
        is_active = (i == 0)
        draw.ellipse((circle_x, circle_y, circle_x + circle_size, circle_y + circle_size),
                     fill=GREEN if is_active else STEPS_OFF)
        num_str = str(i + 1)
        nw_, nh_ = _text_size(draw, num_str, n_font)
        draw.text((circle_x + (circle_size - nw_) // 2,
                   circle_y + (circle_size - nh_) // 2 - 2),
                  num_str, font=n_font,
                  fill=(0, 0, 0) if is_active else TEXT)
        draw.text((circle_x + circle_size + 6, y + 6), name, font=step_font,
                  fill=TEXT if is_active else MUTED)
        sx += w + step_gap

    # Сохраняем
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    logger.info(f"Счёт сгенерирован: {order_id}")
    return buf


def generate_receipt_id() -> str:
    return f"D-{int(time.time())}-{random.randint(100, 999)}"
