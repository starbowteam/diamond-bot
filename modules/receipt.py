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


def generate_receipt_png(
    manager_name: str,
    ticket_name: str,
    amount: int,
    discount_percent: int = 0,
    order_id: Optional[str] = None,
) -> io.BytesIO:
    """
    Генерирует PNG-счёт через Pillow.
    Высокая вертикальная картинка, всё аккуратно разнесено.
    """
    if order_id is None:
        order_id = f"D-{int(time.time())}-{random.randint(100, 999)}"

    date_str = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")

    discount_rub = int(amount * discount_percent / 100)
    total = max(amount - discount_rub, 0)

    # Габариты: выше, чтобы всё влезло
    W, H = 900, 1400
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
    draw.ellipse((W - 300, -180, W + 200, 300), fill=(20, 20, 24))
    draw.ellipse((W - 240, -120, W + 140, 240), fill=(24, 24, 28))
    draw.ellipse((-250, H - 300, 250, H + 200), fill=(18, 22, 20))

    # Внешняя карточка
    M = 24
    draw.rounded_rectangle(
        (M, M, W - M, H - M),
        radius=28, fill=CARD, outline=BORDER, width=2
    )

    PAD = 70  # левый/правый отступ
    y = 90

    # --- Шапка ---
    # Лого
    draw.rounded_rectangle((PAD, y, PAD + 64, y + 64), radius=16, fill=(70, 70, 75))
    draw.text((PAD + 16, y + 16), "◆", font=_get_font(32), fill=(230, 230, 230))

    draw.text((PAD + 84, y + 4), "DIAMOND", font=_get_font(32), fill=TEXT)
    draw.text((PAD + 84, y + 44), "SHOP & ECOSYSTEM", font=_get_font(13), fill=MUTED)

    # Бейдж "СЧЁТ"
    badge_w, badge_h = 120, 44
    bx = W - PAD - badge_w
    draw.rounded_rectangle((bx, y + 10, bx + badge_w, y + 10 + badge_h), radius=12, fill=(80, 80, 85))
    draw.text((bx + 22, y + 20), "СЧЁТ", font=_get_font(18), fill=TEXT)

    # Разделитель
    y += 100
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)

    # --- Заголовок ---
    y += 40
    draw.text((PAD, y), "Счёт на оплату", font=_get_font(42), fill=TEXT)
    y += 62
    draw.text((PAD, y), f"Заказ №{order_id} от {date_str}", font=_get_font(16), fill=MUTED)

    # --- Менеджер / Заказ (две карточки) ---
    y += 60
    card_h = 110
    gap = 24
    card_w = (W - PAD * 2 - gap) // 2

    # Менеджер
    draw.rounded_rectangle((PAD, y, PAD + card_w, y + card_h), radius=16, fill=(20, 20, 25), outline=(42, 42, 47))
    draw.text((PAD + 24, y + 20), "МЕНЕДЖЕР", font=_get_font(13), fill=MUTED)
    draw.text((PAD + 24, y + 52), manager_name[:24], font=_get_font(22), fill=TEXT)

    # Заказ
    cx = PAD + card_w + gap
    draw.rounded_rectangle((cx, y, cx + card_w, y + card_h), radius=16, fill=(20, 20, 25), outline=(42, 42, 47))
    draw.text((cx + 24, y + 20), "ЗАКАЗ", font=_get_font(13), fill=MUTED)
    draw.text((cx + 24, y + 52), ticket_name[:24], font=_get_font(22), fill=TEXT)

    # --- Таблица ---
    y += card_h + 60
    draw.text((PAD, y), "ТОВАР / УСЛУГА", font=_get_font(13), fill=MUTED)
    draw.text((W - PAD - 120, y), "СУММА", font=_get_font(13), fill=MUTED)
    y += 32
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)

    y += 26
    draw.text((PAD, y), ticket_name[:46], font=_get_font(20), fill=TEXT)
    amount_text = f"{amount} ₽"
    aw, _ = _text_size(draw, amount_text, _get_font(20))
    draw.text((W - PAD - aw, y), amount_text, font=_get_font(20), fill=TEXT)
    y += 56
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)

    # Скидка
    if discount_percent > 0:
        y += 26
        draw.text((PAD, y), f"Скидка ({discount_percent}%)", font=_get_font(20), fill=GREEN)
        disc_text = f"−{discount_rub} ₽"
        dw, _ = _text_size(draw, disc_text, _get_font(20))
        draw.text((W - PAD - dw, y), disc_text, font=_get_font(20), fill=GREEN)
        y += 56
        draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)

    # --- Итого ---
    y += 60
    total_h = 140
    draw.rounded_rectangle((PAD, y, W - PAD, y + total_h), radius=18, fill=(20, 20, 25), outline=(42, 42, 47))
    draw.text((PAD + 32, y + 40), "ИТОГО К ОПЛАТЕ", font=_get_font(18), fill=MUTED)
    total_text = f"{total} ₽"
    tw, _ = _text_size(draw, total_text, _get_font(52))
    draw.text((W - PAD - 32 - tw, y + 40), total_text, font=_get_font(52), fill=TEXT)

    # --- Реквизиты (отдельный большой блок) ---
    y += total_h + 60
    req_h = 300
    draw.rounded_rectangle((PAD, y, W - PAD, y + req_h), radius=18, fill=(20, 20, 25), outline=(42, 42, 47))
    draw.text((PAD + 32, y + 30), "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ", font=_get_font(18), fill=TEXT)

    req_lines = [
        ("Т-Банк", "2200 7020 8029 9345"),
        ("АльфаБанк", "2200 1545 6426 7465"),
        ("ОзонБанк", "2204 3204 4881 5151"),
        ("СБП", "+7 983 694 76 41 (Виктор А.)"),
    ]
    ly = y + 80
    for key, val in req_lines:
        draw.text((PAD + 32, ly), key, font=_get_font(17), fill=MUTED)
        vw, _ = _text_size(draw, val, _get_font(17))
        draw.text((W - PAD - 32 - vw, ly), val, font=_get_font(17), fill=TEXT)
        ly += 48
        if ly < y + req_h - 20:
            draw.line((PAD + 32, ly - 14, W - PAD - 32, ly - 14), fill=(35, 35, 40), width=1)

    # --- Футер: только штамп DIAMOND, без ООО/ИНН ---
    y += req_h + 60
    stamp_w, stamp_h = 180, 70
    draw.rounded_rectangle(
        (W - PAD - stamp_w, y, W - PAD, y + stamp_h),
        radius=14, outline=BORDER, width=2
    )
    draw.text((W - PAD - stamp_w + 32, y + 24), "DIAMOND", font=_get_font(22), fill=MUTED)

    # Маленькая подпись под штампом
    draw.text((PAD, y + 20), "Оплата подтверждается менеджером.", font=_get_font(13), fill=MUTED)
    draw.text((PAD, y + 42), "После оплаты чек — в тикет.", font=_get_font(13), fill=MUTED)

    # Сохраняем
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    logger.info(f"Счёт сгенерирован: {order_id}")
    return buf


def generate_receipt_id() -> str:
    return f"D-{int(time.time())}-{random.randint(100, 999)}"
