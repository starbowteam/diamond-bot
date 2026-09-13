# -*- coding: utf-8 -*-
import os
import io
import time
import random
from datetime import datetime, timezone
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


def _draw_centered_text(draw, cx, y, text, font, fill):
    """Рисует текст с центрированием по X."""
    tw, _ = _text_size(draw, text, font)
    draw.text((cx - tw // 2, y), text, font=font, fill=fill)
    return tw


def _draw_diamond_logo(draw, cx, cy, size, color):
    half = size // 2
    points = [
        (cx, cy - half),
        (cx + half, cy),
        (cx, cy + half),
        (cx - half, cy),
    ]
    draw.polygon(points, fill=color)
    inner = int(half * 0.45)
    line_color = (90, 90, 95)
    draw.line([(cx, cy - half), (cx, cy - inner)], fill=line_color, width=2)
    draw.line([(cx, cy + inner), (cx, cy + half)], fill=line_color, width=2)
    draw.line([(cx - half, cy), (cx - inner, cy)], fill=line_color, width=2)
    draw.line([(cx + inner, cy), (cx + half, cy)], fill=line_color, width=2)
    draw.line([(cx - inner, cy - inner), (cx - half, cy)], fill=line_color, width=1)
    draw.line([(cx - inner, cy - inner), (cx, cy - half)], fill=line_color, width=1)
    draw.line([(cx + inner, cy - inner), (cx + half, cy)], fill=line_color, width=1)
    draw.line([(cx + inner, cy - inner), (cx, cy - half)], fill=line_color, width=1)
    draw.line([(cx - inner, cy + inner), (cx - half, cy)], fill=line_color, width=1)
    draw.line([(cx - inner, cy + inner), (cx, cy + half)], fill=line_color, width=1)
    draw.line([(cx + inner, cy + inner), (cx + half, cy)], fill=line_color, width=1)
    draw.line([(cx + inner, cy + inner), (cx, cy + half)], fill=line_color, width=1)


def generate_receipt_png(
    manager_name: str,
    ticket_name: str,
    amount: int,
    discount_percent: int = 0,
    order_id: Optional[str] = None,
) -> io.BytesIO:
    """Генерирует PNG-счёт 1200×800 (3:2) — не обрезается в Discord-эмбеде."""
    if order_id is None:
        order_id = f"D-{int(time.time())}-{random.randint(100, 999)}"

    date_str = datetime.now(timezone.utc).strftime("%d.%m.%Y · %H:%M")
    discount_rub = int(amount * discount_percent / 100)
    total = max(amount - discount_rub, 0)

    W, H = 1200, 800

    BG = (14, 14, 16)
    CARD = (26, 26, 31)
    INNER = (20, 20, 26)
    INNER_BORDER = (42, 42, 47)
    BORDER = (74, 74, 79)
    TEXT = (255, 255, 255)
    MUTED = (136, 136, 136)
    GREEN = (46, 204, 113)
    GREEN_BG = (22, 44, 30)
    LOGO_BG = (74, 74, 79)
    DIAMOND_GRAY = (200, 200, 200)
    LINE = (51, 51, 51)

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Внешняя карточка
    M = 20
    draw.rounded_rectangle(
        (M, M, W - M, H - M),
        radius=24, fill=CARD, outline=BORDER, width=2
    )

    PAD = 45
    y = 35

    # ======== ШАПКА: ЛОГО + ДАТА ========
    logo_box = 60
    draw.rounded_rectangle((PAD, y, PAD + logo_box, y + logo_box), radius=14, fill=LOGO_BG)
    _draw_diamond_logo(
        draw,
        cx=PAD + logo_box // 2,
        cy=y + logo_box // 2,
        size=int(logo_box * 0.5),
        color=DIAMOND_GRAY
    )

    draw.text((PAD + logo_box + 16, y + 4), "DIAMOND", font=_get_font(26), fill=TEXT)
    draw.text((PAD + logo_box + 18, y + 38), "SHOP & ECOSYSTEM", font=_get_font(11), fill=MUTED)

    # Дата справа
    date_lbl_font = _get_font(13)
    date_num_font = _get_font(15)
    date_font = _get_font(13)

    lbl_text = "Заказ "
    num_text = f"№{order_id}"
    lw, _ = _text_size(draw, lbl_text, date_lbl_font)
    nw, _ = _text_size(draw, num_text, date_num_font)
    total_w = lw + nw

    dx = W - PAD - total_w
    draw.text((dx, y + 10), lbl_text, font=date_lbl_font, fill=MUTED)
    draw.text((dx + lw, y + 8), num_text, font=date_num_font, fill=TEXT)

    dw, _ = _text_size(draw, date_str, date_font)
    draw.text((W - PAD - dw, y + 34), date_str, font=date_font, fill=MUTED)

    # ======== ГЕРОЙ: ИТОГО ПО ЦЕНТРУ ========
    y = 120
    cx = W // 2

    # "ИТОГО К ОПЛАТЕ" по центру
    _draw_centered_text(draw, cx, y, "ИТОГО К ОПЛАТЕ", _get_font(16), MUTED)
    y += 30

    # Огромная сумма — подбираем размер, чтобы влезала
    total_text = f"{total} Р"
    font_size = 88
    tw, _ = _text_size(draw, total_text, _get_font(font_size))
    while tw > W - PAD * 2 - 100 and font_size > 40:
        font_size -= 4
        tw, _ = _text_size(draw, total_text, _get_font(font_size))
    _draw_centered_text(draw, cx, y, total_text, _get_font(font_size), TEXT)
    y += font_size + 10

    # Бейдж скидки (только если есть)
    if discount_percent > 0:
        badge_text = f"Скидка {discount_percent}%  ·  −{discount_rub} Р"
        bf = _get_font(15)
        bw, bh = _text_size(draw, badge_text, bf)
        pad_bx, pad_by = 22, 9
        badge_w = bw + pad_bx * 2
        badge_h = bh + pad_by * 2
        badge_x1 = cx - badge_w // 2
        badge_y1 = y
        draw.rounded_rectangle(
            (badge_x1, badge_y1, badge_x1 + badge_w, badge_y1 + badge_h),
            radius=10, fill=GREEN_BG, outline=(46, 204, 113), width=1
        )
        draw.text((badge_x1 + pad_bx, badge_y1 + pad_by), badge_text, font=bf, fill=GREEN)
        y += badge_h + 12

    # ======== РАЗДЕЛИТЕЛЬ ========
    y += 4
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)
    y += 18

    # ======== МЕНЕДЖЕР / ЗАКАЗ ========
    meta_h = 70
    gap = 16
    card_w = (W - PAD * 2 - gap) // 2

    # Менеджер — зелёная рамка
    draw.rounded_rectangle(
        (PAD, y, PAD + card_w, y + meta_h),
        radius=14, fill=GREEN_BG, outline=GREEN, width=2
    )
    draw.text((PAD + 20, y + 12), "МЕНЕДЖЕР", font=_get_font(11), fill=GREEN)
    draw.text((PAD + 20, y + 32), manager_name[:24], font=_get_font(20), fill=TEXT)

    # Заказ — серая рамка
    cx2 = PAD + card_w + gap
    draw.rounded_rectangle(
        (cx2, y, cx2 + card_w, y + meta_h),
        radius=14, fill=(20, 20, 26), outline=BORDER, width=2
    )
    draw.text((cx2 + 20, y + 12), "ЗАКАЗ", font=_get_font(11), fill=MUTED)
    draw.text((cx2 + 20, y + 32), ticket_name[:24], font=_get_font(20), fill=TEXT)

    y += meta_h + 18

    # ======== РЕКВИЗИТЫ (влезает точно) ========
    req_h = H - y - 35
    draw.rounded_rectangle(
        (PAD, y, W - PAD, y + req_h),
        radius=16, fill=INNER, outline=INNER_BORDER, width=1
    )

    draw.text((PAD + 26, y + 16), "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ", font=_get_font(12), fill=MUTED)

    req_data = [
        ("Т-Банк", "2200 7020 8029 9345"),
        ("АльфаБанк", "2200 1545 6426 7465"),
        ("ОзонБанк", "2204 3204 4881 5151"),
        ("СБП", "+7 983 694 76 41"),
    ]

    col_w = (W - PAD * 2 - 52 - 30) // 2  # между колонками 30px
    row_h = 42
    start_y = y + 46

    for i, (key, val) in enumerate(req_data):
        col = i % 2
        row = i // 2
        item_x = PAD + 26 + col * (col_w + 30)
        item_y = start_y + row * row_h

        draw.text((item_x, item_y), key.upper(), font=_get_font(10), fill=MUTED)
        draw.text((item_x, item_y + 16), val, font=_get_font(16), fill=TEXT)

    # Сохраняем
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    logger.info(f"Счёт сгенерирован: {order_id}")
    return buf


def generate_receipt_id() -> str:
    return f"D-{int(time.time())}-{random.randint(100, 999)}"
