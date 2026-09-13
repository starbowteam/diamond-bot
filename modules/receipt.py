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


def _draw_cart(draw, cx, cy, size, color, width=3):
    """Рисует векторную корзину (как fa-cart-shopping)."""
    s = size
    # Ручка
    handle_x1 = cx - s * 0.55
    handle_x2 = cx - s * 0.32
    handle_y = cy - s * 0.42
    basket_top_y = cy - s * 0.18
    draw.line(
        [(handle_x1, handle_y), (handle_x2, handle_y), (cx - s * 0.35, basket_top_y)],
        fill=color, width=width, joint="curve"
    )
    # Корзина — трапеция
    bt_y = cy - s * 0.18
    bb_y = cy + s * 0.22
    bl_t = cx - s * 0.35
    br_t = cx + s * 0.38
    bl_b = cx - s * 0.27
    br_b = cx + s * 0.30
    draw.line(
        [(bl_t, bt_y), (br_t, bt_y), (br_b, bb_y), (bl_b, bb_y), (bl_t, bt_y)],
        fill=color, width=width, joint="curve"
    )
    # Колёса
    wr = max(2, int(s * 0.07))
    w1x = cx - s * 0.22
    w2x = cx + s * 0.24
    wy = cy + s * 0.40
    draw.ellipse((w1x - wr, wy - wr, w1x + wr, wy + wr), outline=color, width=width)
    draw.ellipse((w2x - wr, wy - wr, w2x + wr, wy + wr), outline=color, width=width)


def _draw_divider(draw, y, PAD, W, color):
    """Горизонтальная линия с маленькой корзиной по центру."""
    cx = W // 2
    # линии
    line_color = (58, 58, 63)
    draw.line((PAD, y, cx - 20, y), fill=line_color, width=1)
    draw.line((cx + 20, y, W - PAD, y), fill=line_color, width=1)
    # маленькая корзина
    _draw_cart(draw, cx, y, 14, (74, 74, 79), width=1)


def generate_receipt_png(
    manager_name: str,
    ticket_name: str,
    amount: int,
    discount_percent: int = 0,
    order_id: Optional[str] = None,
) -> io.BytesIO:
    """
    Генерирует PNG-счёт 1200×800 (3:2) — Discord не обрезает.
    """
    if order_id is None:
        order_id = f"D-{int(time.time())}-{random.randint(100, 999)}"

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%d.%m.%Y · %H:%M")
    deadline_str = (now + timedelta(hours=1)).strftime("%d.%m.%Y · %H:%M")

    discount_rub = int(amount * discount_percent / 100)
    total = max(amount - discount_rub, 0)

    W, H = 1200, 800

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

    # Фон
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Декоративные круги
    # (нельзя сделать радиальный градиент в Pillow без костылей, сделаем чуть темнее круги)
    draw.ellipse((W - 380, -180, W + 80, 280), fill=(16, 16, 20))
    draw.ellipse((-140, H - 260, 220, H + 100), fill=(14, 22, 18))

    # Внешняя карточка с градиентом (имитация: верхний слой темнее)
    M = 15
    draw.rounded_rectangle((M, M, W - M, H - M), radius=22, fill=CARD_BOT, outline=BORDER, width=2)
    draw.rounded_rectangle((M + 1, M + 1, W - M - 1, (H // 2)), radius=22, fill=CARD_TOP)

    PAD = 40

    # ============ 1. TOP ============
    y_top = 30
    logo_box = 54
    draw.rounded_rectangle(
        (PAD, y_top, PAD + logo_box, y_top + logo_box),
        radius=14, fill=LOGO_BG
    )
    _draw_cart(
        draw,
        cx=PAD + logo_box // 2,
        cy=y_top + logo_box // 2,
        size=28,
        color=LOGO_ICON,
        width=2
    )

    # DIAMOND
    draw.text((PAD + logo_box + 16, y_top + 2), "DIAMOND", font=_get_font(26), fill=TEXT)
    draw.text((PAD + logo_box + 18, y_top + 38), "SHOP & ECOSYSTEM", font=_get_font(11), fill=MUTED)

    # Дата справа
    lbl_text = "Заказ "
    num_text = f"№{order_id}"
    lbl_font = _get_font(13)
    num_font = _get_font(15)
    date_font = _get_font(13)

    lw, _ = _text_size(draw, lbl_text, lbl_font)
    nw, _ = _text_size(draw, num_text, num_font)
    total_w = lw + nw

    dx = W - PAD - total_w
    draw.text((dx, y_top + 10), lbl_text, font=lbl_font, fill=MUTED)
    draw.text((dx + lw, y_top + 8), num_text, font=num_font, fill=TEXT)

    dw, _ = _text_size(draw, date_str, date_font)
    draw.text((W - PAD - dw, y_top + 34), date_str, font=date_font, fill=MUTED)

    # ============ 2. HERO ============
    y = 120
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
        draw.rounded_rectangle(
            (bx, y, bx + badge_w, y + badge_h),
            radius=10, fill=GREEN_BG, outline=GREEN, width=1
        )
        draw.text((bx + pad_bx, y + pad_by), badge_text, font=bf, fill=GREEN)
        y += badge_h

    # ============ 3. DIVIDER ============
    y += 22
    _draw_divider(draw, y, PAD, W, BORDER)
    y += 18

    # ============ 4. META (менеджер / заказ) ============
    meta_h = 66
    gap_x = 14
    card_w = (W - PAD * 2 - gap_x) // 2

    # Менеджер — зелёная
    draw.rounded_rectangle(
        (PAD, y, PAD + card_w, y + meta_h),
        radius=14, fill=GREEN_BG, outline=GREEN, width=2
    )
    draw.text((PAD + 18, y + 10), "МЕНЕДЖЕР", font=_get_font(10), fill=GREEN)
    draw.text((PAD + 18, y + 30), manager_name[:26], font=_get_font(19), fill=TEXT)

    # Заказ — серая
    cx2 = PAD + card_w + gap_x
    draw.rounded_rectangle(
        (cx2, y, cx2 + card_w, y + meta_h),
        radius=14, fill=INNER, outline=BORDER, width=2
    )
    draw.text((cx2 + 18, y + 10), "ЗАКАЗ", font=_get_font(10), fill=MUTED)
    draw.text((cx2 + 18, y + 30), ticket_name[:26], font=_get_font(19), fill=TEXT)

    y += meta_h + 14

    # ============ 5. ITEMS ============
    items_x1 = PAD
    items_x2 = W - PAD
    items_top = y
    # посчитаем высоту: заголовок + 1 товар + 1 скидка + итог
    rows = 1  # товар
    if discount_percent > 0:
        rows += 1
    rows += 1  # итог
    items_h = 30 + rows * 26 + 12
    draw.rounded_rectangle(
        (items_x1, items_top, items_x2, items_top + items_h),
        radius=14, fill=INNER, outline=INNER_BORDER, width=1
    )

    inner_pad = 18
    # Заголовок
    draw.text((items_x1 + inner_pad, items_top + 8), "ТОВАР / УСЛУГА", font=_get_font(10), fill=MUTED)
    hdr_right = "СУММА"
    hw, _ = _text_size(draw, hdr_right, _get_font(10))
    draw.text((items_x2 - inner_pad - hw, items_top + 8), hdr_right, font=_get_font(10), fill=MUTED)
    draw.line((items_x1 + inner_pad, items_top + 26, items_x2 - inner_pad, items_top + 26), fill=LINE, width=1)

    # Товар
    row_y = items_top + 32
    item_font = _get_font(14)
    draw.text((items_x1 + inner_pad, row_y), ticket_name[:40], font=item_font, fill=TEXT)
    amount_str = f"{amount} Р"
    aw, _ = _text_size(draw, amount_str, item_font)
    draw.text((items_x2 - inner_pad - aw, row_y), amount_str, font=item_font, fill=TEXT)
    row_y += 24

    # Скидка
    if discount_percent > 0:
        disc_font = _get_font(14)
        draw.text((items_x1 + inner_pad, row_y), f"Скидка ({discount_percent}%)", font=disc_font, fill=GREEN)
        disc_str = f"−{discount_rub} Р"
        dw_, _ = _text_size(draw, disc_str, disc_font)
        draw.text((items_x2 - inner_pad - dw_, row_y), disc_str, font=disc_font, fill=GREEN)
        row_y += 24

    # Разделитель + итог
    draw.line((items_x1 + inner_pad, row_y + 2, items_x2 - inner_pad, row_y + 2), fill=GREEN, width=2)
    row_y += 8
    total_font = _get_font(18)
    draw.text((items_x1 + inner_pad, row_y), "Итого к оплате", font=total_font, fill=TEXT)
    tot_str = f"{total} Р"
    tw_, _ = _text_size(draw, tot_str, total_font)
    draw.text((items_x2 - inner_pad - tw_, row_y), tot_str, font=total_font, fill=GREEN)

    y = items_top + items_h + 12

    # ============ 6. РЕКВИЗИТЫ ============
    req_h = 175
    draw.rounded_rectangle(
        (PAD, y, W - PAD, y + req_h),
        radius=14, fill=INNER, outline=INNER_BORDER, width=1
    )

    # Маленькая корзина перед заголовком
    _draw_cart(draw, PAD + 28, y + 22, 12, MUTED, width=1)
    draw.text((PAD + 46, y + 14), "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ", font=_get_font(11), fill=MUTED)

    req_data = [
        ("Т-Банк", "2200 7020 8029 9345"),
        ("АльфаБанк", "2200 1545 6426 7465"),
        ("ОзонБанк", "2204 3204 4881 5151"),
        ("СБП", "+7 983 694 76 41"),
    ]

    col_w = (W - PAD * 2 - 36 - 30) // 2
    row_h = 42
    start_y = y + 44

    k_font = _get_font(10)
    v_font = _get_font(15)

    for i, (key, val) in enumerate(req_data):
        col = i % 2
        row = i // 2
        item_x = PAD + 18 + col * (col_w + 30)
        item_y = start_y + row * row_h

        # разделительная линия между строками (кроме первой)
        if row > 0:
            draw.line((item_x, item_y - 6, item_x + col_w, item_y - 6), fill=DASH, width=1)

        draw.text((item_x, item_y), key.upper(), font=k_font, fill=MUTED)
        vw, _ = _text_size(draw, val, v_font)
        draw.text((item_x + col_w - vw, item_y - 2), val, font=v_font, fill=TEXT)

    y += req_h + 12

    # ============ 7. BOTTOM (срок + шаги) ============
    bottom_h = 50
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)
    y += 14

    # Срок
    deadline_font = _get_font(12)
    draw.text((PAD, y + 6), "Оплатить до:", font=deadline_font, fill=MUTED)
    lw_, _ = _text_size(draw, "Оплатить до: ", deadline_font)
    draw.text((PAD + lw_, y + 4), deadline_str, font=_get_font(14), fill=TEXT)

    # Шаги
    steps = ["Оплата", "Чек", "Проверка", "Готово"]
    step_font = _get_font(11)
    n_font = _get_font(10)

    # Считаем общую ширину
    step_gap = 14
    total_steps_w = 0
    step_widths = []
    for i, name in enumerate(steps):
        tw_, _ = _text_size(draw, name, step_font)
        w = 18 + 6 + tw_
        step_widths.append(w)
        total_steps_w += w
    total_steps_w += step_gap * (len(steps) - 1)

    sx = W - PAD - total_steps_w
    for i, name in enumerate(steps):
        w = step_widths[i]
        # круг с номером
        circle_size = 18
        circle_x = sx
        circle_y = y + 4
        if i == 0:
            # активный
            draw.ellipse(
                (circle_x, circle_y, circle_x + circle_size, circle_y + circle_size),
                fill=GREEN
            )
            nw_, nh_ = _text_size(draw, str(i + 1), n_font)
            draw.text(
                (circle_x + (circle_size - nw_) // 2, circle_y + (circle_size - nh_) // 2 - 2),
                str(i + 1), font=n_font, fill=(0, 0, 0)
            )
            draw.text((circle_x + circle_size + 6, y + 6), name, font=step_font, fill=TEXT)
        else:
            draw.ellipse(
                (circle_x, circle_y, circle_x + circle_size, circle_y + circle_size),
                fill=STEPS_OFF
            )
            nw_, nh_ = _text_size(draw, str(i + 1), n_font)
            draw.text(
                (circle_x + (circle_size - nw_) // 2, circle_y + (circle_size - nh_) // 2 - 2),
                str(i + 1), font=n_font, fill=TEXT
            )
            draw.text((circle_x + circle_size + 6, y + 6), name, font=step_font, fill=MUTED)
        sx += w + step_gap

    # Сохраняем
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    logger.info(f"Счёт сгенерирован: {order_id}")
    return buf


def generate_receipt_id() -> str:
    return f"D-{int(time.time())}-{random.randint(100, 999)}"
