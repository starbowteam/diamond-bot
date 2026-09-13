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


def _text_center(draw, x1, y1, x2, y2, text, font, fill):
    tw, th = _text_size(draw, text, font)
    cx = x1 + (x2 - x1 - tw) // 2
    cy = y1 + (y2 - y1 - th) // 2
    draw.text((cx, cy), text, font=font, fill=fill)


def _draw_diamond_logo(draw, cx, cy, size, color):
    """Рисует векторный ромб (логотип)."""
    half = size // 2
    points = [
        (cx, cy - half),
        (cx + half, cy),
        (cx, cy + half),
        (cx - half, cy),
    ]
    draw.polygon(points, fill=color)
    # Грани для огранки
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
    if order_id is None:
        order_id = f"D-{int(time.time())}-{random.randint(100, 999)}"

    date_str = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")
    discount_rub = int(amount * discount_percent / 100)
    total = max(amount - discount_rub, 0)

    # 3:2 — идеально для Discord-эмбеда, не обрезается
    W, H = 1200, 800

    BG = (14, 14, 16)
    CARD = (26, 26, 31)
    INNER = (20, 20, 26)
    INNER_BORDER = (42, 42, 47)
    BORDER = (74, 74, 79)
    TEXT = (255, 255, 255)
    MUTED = (136, 136, 136)
    GREEN = (46, 204, 113)
    LOGO_BG = (74, 74, 79)
    DIAMOND_GRAY = (200, 200, 200)

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Внешняя карточка
    M = 25
    draw.rounded_rectangle(
        (M, M, W - M, H - M),
        radius=28, fill=CARD, outline=BORDER, width=2
    )

    PAD = 55
    y = 55

    # ======== ВЕРХ: лого слева, дата справа ========
    logo_box = 76
    draw.rounded_rectangle((PAD, y, PAD + logo_box, y + logo_box), radius=18, fill=LOGO_BG)
    _draw_diamond_logo(
        draw,
        cx=PAD + logo_box // 2,
        cy=y + logo_box // 2,
        size=int(logo_box * 0.5),
        color=DIAMOND_GRAY
    )

    draw.text((PAD + logo_box + 22, y + 6), "DIAMOND", font=_get_font(34), fill=TEXT)
    draw.text((PAD + logo_box + 24, y + 48), "SHOP & ECOSYSTEM", font=_get_font(14), fill=MUTED)

    # Дата справа
    date_label = "Заказ"
    date_num = f"№{order_id}"
    date_str_short = date_str
    dw1, dh1 = _text_size(draw, f"{date_label} {date_num}", _get_font(16))
    dw2, _ = _text_size(draw, date_str_short, _get_font(14))
    draw.text((W - PAD - dw1, y + 8), f"{date_label} ", font=_get_font(16), fill=MUTED)
    draw.text((W - PAD - dw1 + _text_size(draw, f"{date_label} ", _get_font(16))[0], y + 8), date_num, font=_get_font(16), fill=TEXT)
    draw.text((W - PAD - dw2, y + 36), date_str_short, font=_get_font(14), fill=MUTED)

    # ======== ГЛАВНОЕ: огромная сумма ========
    y += 130
    big_title = "ИТОГО К ОПЛАТЕ"
    draw.text((PAD, y), big_title, font=_get_font(22), fill=MUTED)
    y += 38

    total_text = f"{total} Р"
    # Размер шрифта подбираем так, чтобы помещалось
    font_size = 110
    tw, _ = _text_size(draw, total_text, _get_font(font_size))
    while tw > W - PAD * 2 and font_size > 40:
        font_size -= 4
        tw, _ = _text_size(draw, total_text, _get_font(font_size))
    draw.text((PAD, y), total_text, font=_get_font(font_size), fill=TEXT)
    y += font_size + 20

    # Плашка со скидкой (только если есть)
    if discount_percent > 0:
        badge_text = f"Скидка {discount_percent}%  ·  −{discount_rub} Р"
        bw, bh = _text_size(draw, badge_text, _get_font(18))
        pad_badge_x, pad_badge_y = 22, 12
        draw.rounded_rectangle(
            (PAD, y, PAD + bw + pad_badge_x * 2, y + bh + pad_badge_y * 2),
            radius=12, fill=(22, 44, 30)
        )
        draw.text((PAD + pad_badge_x, y + pad_badge_y), badge_text, font=_get_font(18), fill=GREEN)
        y += bh + pad_badge_y * 2 + 20
    else:
        y += 20

    # ======== Разделитель ========
    y += 10
    draw.line((PAD, y, W - PAD, y), fill=(51, 51, 51), width=1)
    y += 30

    # ======== Meta: менеджер / заказ ========
    meta_y = y
    card_w = (W - PAD * 2 - 30) // 2

    # Менеджер
    draw.text((PAD, meta_y), "МЕНЕДЖЕР", font=_get_font(13), fill=MUTED)
    draw.text((PAD, meta_y + 22), manager_name[:26], font=_get_font(22), fill=TEXT)

    # Заказ
    cx = PAD + card_w + 30
    draw.text((cx, meta_y), "ЗАКАЗ", font=_get_font(13), fill=MUTED)
    draw.text((cx, meta_y + 22), ticket_name[:26], font=_get_font(22), fill=TEXT)

    # ======== Реквизиты (карточка снизу) ========
    y = meta_y + 80
    req_h = H - y - PAD - 20

    draw.rounded_rectangle(
        (PAD, y, W - PAD, y + req_h),
        radius=20, fill=INNER, outline=INNER_BORDER, width=1
    )

    # Заголовок
    draw.text((PAD + 30, y + 20), "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ", font=_get_font(16), fill=TEXT)

    # 4 реквизита в 2 колонки
    req_data = [
        ("Т-Банк", "2200 7020 8029 9345"),
        ("АльфаБанк", "2200 1545 6426 7465"),
        ("ОзонБанк", "2204 3204 4881 5151"),
        ("СБП", "+7 983 694 76 41"),
    ]

    col_w = (W - PAD * 2 - 60) // 2
    for i, (key, val) in enumerate(req_data):
        col = i % 2
        row = i // 2
        item_x = PAD + 30 + col * (col_w + 10)
        item_y = y + 60 + row * 70

        draw.text((item_x, item_y), key.upper(), font=_get_font(12), fill=MUTED)
        draw.text((item_x, item_y + 22), val, font=_get_font(18), fill=TEXT)

    # Сохраняем
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    logger.info(f"Счёт сгенерирован: {order_id}")
    return buf


def generate_receipt_id() -> str:
    return f"D-{int(time.time())}-{random.randint(100, 999)}"
