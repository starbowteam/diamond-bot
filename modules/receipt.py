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


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_centered(draw, box, text, font, fill):
    """Рисует текст, центрированный внутри прямоугольника box=(x1,y1,x2,y2)."""
    x1, y1, x2, y2 = box
    tw, th = _text_size(draw, text, font)
    cx = x1 + (x2 - x1 - tw) // 2
    cy = y1 + (y2 - y1 - th) // 2
    draw.text((cx, cy), text, font=font, fill=fill)


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

    # Большая широкая картинка
    W, H = 1400, 1700

    BG = (14, 14, 16)
    CARD = (26, 26, 31)
    BORDER = (103, 103, 103)
    TEXT = (255, 255, 255)
    MUTED = (136, 136, 136)
    GREEN = (46, 204, 113)
    LINE = (51, 51, 51)

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Декор
    draw.ellipse((W - 500, -250, W + 300, 500), fill=(20, 20, 24))
    draw.ellipse((W - 400, -150, W + 200, 400), fill=(24, 24, 28))
    draw.ellipse((-350, H - 450, 350, H + 250), fill=(18, 22, 20))

    # Внешняя карточка
    M = 40
    draw.rounded_rectangle(
        (M, M, W - M, H - M),
        radius=40, fill=CARD, outline=BORDER, width=3
    )

    PAD = 110
    y = 140

    # --- Шапка ---
    logo_size = 110
    draw.rounded_rectangle((PAD, y, PAD + logo_size, y + logo_size), radius=24, fill=(70, 70, 75))
    _draw_centered(draw, (PAD, y, PAD + logo_size, y + logo_size), "◆", _get_font(56), (230, 230, 230))

    draw.text((PAD + logo_size + 30, y + 10), "DIAMOND", font=_get_font(56), fill=TEXT)
    draw.text((PAD + logo_size + 30, y + 78), "SHOP & ECOSYSTEM", font=_get_font(22), fill=MUTED)

    # Бейдж "СЧЁТ"
    badge_w, badge_h = 200, 70
    bx = W - PAD - badge_w
    by = y + 20
    draw.rounded_rectangle((bx, by, bx + badge_w, by + badge_h), radius=18, fill=(80, 80, 85))
    _draw_centered(draw, (bx, by, bx + badge_w, by + badge_h), "СЧЁТ", _get_font(28), TEXT)

    # Разделитель
    y += logo_size + 70
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=2)

    # --- Заголовок ---
    y += 60
    draw.text((PAD, y), "Счёт на оплату", font=_get_font(72), fill=TEXT)
    y += 100
    draw.text((PAD, y), f"Заказ №{order_id} от {date_str}", font=_get_font(26), fill=MUTED)

    # --- Менеджер / Заказ ---
    y += 80
    card_h = 180
    gap = 40
    card_w = (W - PAD * 2 - gap) // 2

    draw.rounded_rectangle((PAD, y, PAD + card_w, y + card_h), radius=24, fill=(20, 20, 25), outline=(42, 42, 47), width=2)
    draw.text((PAD + 40, y + 34), "МЕНЕДЖЕР", font=_get_font(22), fill=MUTED)
    draw.text((PAD + 40, y + 82), manager_name[:26], font=_get_font(38), fill=TEXT)

    cx = PAD + card_w + gap
    draw.rounded_rectangle((cx, y, cx + card_w, y + card_h), radius=24, fill=(20, 20, 25), outline=(42, 42, 47), width=2)
    draw.text((cx + 40, y + 34), "ЗАКАЗ", font=_get_font(22), fill=MUTED)
    draw.text((cx + 40, y + 82), ticket_name[:26], font=_get_font(38), fill=TEXT)

    # --- Таблица ---
    y += card_h + 90
    draw.text((PAD, y), "ТОВАР / УСЛУГА", font=_get_font(22), fill=MUTED)
    right_label = "СУММА"
    rw, _ = _text_size(draw, right_label, _get_font(22))
    draw.text((W - PAD - rw, y), right_label, font=_get_font(22), fill=MUTED)
    y += 50
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=2)

    y += 40
    draw.text((PAD, y), ticket_name[:48], font=_get_font(34), fill=TEXT)
    amount_text = f"{amount} Р"
    aw, _ = _text_size(draw, amount_text, _get_font(34))
    draw.text((W - PAD - aw, y), amount_text, font=_get_font(34), fill=TEXT)
    y += 80
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=2)

    if discount_percent > 0:
        y += 40
        draw.text((PAD, y), f"Скидка ({discount_percent}%)", font=_get_font(34), fill=GREEN)
        disc_text = f"−{discount_rub} Р"
        dw, _ = _text_size(draw, disc_text, _get_font(34))
        draw.text((W - PAD - dw, y), disc_text, font=_get_font(34), fill=GREEN)
        y += 80
        draw.line((PAD, y, W - PAD, y), fill=LINE, width=2)

    # --- Итого ---
    y += 80
    total_h = 200
    draw.rounded_rectangle((PAD, y, W - PAD, y + total_h), radius=24, fill=(20, 20, 25), outline=(42, 42, 47), width=2)
    draw.text((PAD + 50, y + 60), "ИТОГО К ОПЛАТЕ", font=_get_font(30), fill=MUTED)
    total_text = f"{total} Р"
    tw, _ = _text_size(draw, total_text, _get_font(90))
    draw.text((W - PAD - 50 - tw, y + 50), total_text, font=_get_font(90), fill=TEXT)

    # --- Реквизиты ---
    y += total_h + 80
    req_h = 400
    draw.rounded_rectangle((PAD, y, W - PAD, y + req_h), radius=24, fill=(20, 20, 25), outline=(42, 42, 47), width=2)
    draw.text((PAD + 50, y + 40), "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ", font=_get_font(30), fill=TEXT)

    req_lines = [
        ("Т-Банк", "2200 7020 8029 9345"),
        ("АльфаБанк", "2200 1545 6426 7465"),
        ("ОзонБанк", "2204 3204 4881 5151"),
        ("СБП", "+7 983 694 76 41 (Виктор А.)"),
    ]
    ly = y + 120
    for key, val in req_lines:
        draw.text((PAD + 50, ly), key, font=_get_font(28), fill=MUTED)
        vw, _ = _text_size(draw, val, _get_font(28))
        draw.text((W - PAD - 50 - vw, ly), val, font=_get_font(28), fill=TEXT)
        ly += 70
        if ly < y + req_h - 20:
            draw.line((PAD + 50, ly - 20, W - PAD - 50, ly - 20), fill=(35, 35, 40), width=2)

    # --- Футер: только DIAMOND без рамки ---
    y += req_h + 80
    draw.text((PAD, y), "DIAMOND", font=_get_font(28), fill=MUTED)

    # Сохраняем
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    logger.info(f"Счёт сгенерирован: {order_id}")
    return buf


def generate_receipt_id() -> str:
    return f"D-{int(time.time())}-{random.randint(100, 999)}"
