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
    """Центрирует текст внутри прямоугольника (x1,y1,x2,y2)."""
    tw, th = _text_size(draw, text, font)
    cx = x1 + (x2 - x1 - tw) // 2
    cy = y1 + (y2 - y1 - th) // 2
    draw.text((cx, cy), text, font=font, fill=fill)


def _draw_diamond_logo(draw, cx, cy, size, color, outline=None):
    """Рисует ромбовидный логотип векторно."""
    half = size // 2
    # Сам ромб
    points = [
        (cx, cy - half),           # верх
        (cx + half, cy),           # право
        (cx, cy + half),           # низ
        (cx - half, cy),           # лево
    ]
    draw.polygon(points, fill=color, outline=outline)
    # Внутренние грани для объёма (эффект огранки)
    inner = int(half * 0.45)
    # верхняя грань
    draw.line([(cx, cy - half), (cx, cy - inner)], fill=outline or color, width=1)
    # нижняя грань
    draw.line([(cx, cy + inner), (cx, cy + half)], fill=outline or color, width=1)
    # левая
    draw.line([(cx - half, cy), (cx - inner, cy)], fill=outline or color, width=1)
    # правая
    draw.line([(cx + inner, cy), (cx + half, cy)], fill=outline or color, width=1)
    # диагонали огранки
    draw.line([(cx - inner, cy - inner), (cx - half, cy)], fill=outline or color, width=1)
    draw.line([(cx - inner, cy - inner), (cx, cy - half)], fill=outline or color, width=1)
    draw.line([(cx + inner, cy - inner), (cx + half, cy)], fill=outline or color, width=1)
    draw.line([(cx + inner, cy - inner), (cx, cy - half)], fill=outline or color, width=1)
    draw.line([(cx - inner, cy + inner), (cx - half, cy)], fill=outline or color, width=1)
    draw.line([(cx - inner, cy + inner), (cx, cy + half)], fill=outline or color, width=1)
    draw.line([(cx + inner, cy + inner), (cx + half, cy)], fill=outline or color, width=1)
    draw.line([(cx + inner, cy + inner), (cx, cy + half)], fill=outline or color, width=1)


def generate_receipt_png(
    manager_name: str,
    ticket_name: str,
    amount: int,
    discount_percent: int = 0,
    order_id: Optional[str] = None,
) -> io.BytesIO:
    """
    Генерирует PNG-счёт. Пропорции 3:2 (широкий), влезает в Discord-эмбед целиком.
    """
    if order_id is None:
        order_id = f"D-{int(time.time())}-{random.randint(100, 999)}"

    date_str = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")

    discount_rub = int(amount * discount_percent / 100)
    total = max(amount - discount_rub, 0)

    # Пропорции 3:2 → Discord показывает целиком
    W, H = 1500, 1000

    BG = (14, 14, 16)
    CARD = (26, 26, 31)
    INNER = (20, 20, 25)
    BORDER = (80, 80, 85)
    INNER_BORDER = (42, 42, 47)
    TEXT = (255, 255, 255)
    MUTED = (136, 136, 136)
    GREEN = (46, 204, 113)
    LINE = (51, 51, 51)
    DIAMOND_GRAY = (180, 180, 180)

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Декоративные круги (мягкий фон)
    draw.ellipse((W - 500, -300, W + 200, 400), fill=(20, 20, 24))
    draw.ellipse((W - 380, -200, W + 100, 320), fill=(24, 24, 28))
    draw.ellipse((-300, H - 400, 300, H + 200), fill=(18, 22, 20))

    # Внешняя карточка
    M = 30
    draw.rounded_rectangle(
        (M, M, W - M, H - M),
        radius=32, fill=CARD, outline=BORDER, width=2
    )

    PAD = 70
    y = 70

    # ========= ШАПКА =========
    # Логотип (вектор)
    logo_box = 90
    draw.rounded_rectangle((PAD, y, PAD + logo_box, y + logo_box), radius=20, fill=(45, 45, 50))
    _draw_diamond_logo(
        draw,
        cx=PAD + logo_box // 2,
        cy=y + logo_box // 2,
        size=int(logo_box * 0.55),
        color=DIAMOND_GRAY,
        outline=(90, 90, 95)
    )

    draw.text((PAD + logo_box + 24, y + 8), "DIAMOND", font=_get_font(42), fill=TEXT)
    draw.text((PAD + logo_box + 26, y + 58), "SHOP & ECOSYSTEM", font=_get_font(16), fill=MUTED)

    # Бейдж СЧЁТ (справа)
    badge_w, badge_h = 150, 56
    bx = W - PAD - badge_w
    by = y + 17
    draw.rounded_rectangle((bx, by, bx + badge_w, by + badge_h), radius=14, fill=(70, 70, 75))
    _text_center(draw, bx, by, bx + badge_w, by + badge_h, "СЧЁТ", _get_font(22), TEXT)

    # Разделитель
    y += logo_box + 40
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)

    # ========= ЗАГОЛОВОК =========
    y += 30
    draw.text((PAD, y), "Счёт на оплату", font=_get_font(52), fill=TEXT)
    y += 68
    draw.text((PAD, y), f"Заказ №{order_id} от {date_str}", font=_get_font(18), fill=MUTED)

    # ========= МЕНЕДЖЕР / ЗАКАЗ =========
    y += 40
    card_h = 110
    gap = 30
    card_w = (W - PAD * 2 - gap) // 2

    draw.rounded_rectangle((PAD, y, PAD + card_w, y + card_h), radius=18, fill=INNER, outline=INNER_BORDER, width=1)
    draw.text((PAD + 28, y + 22), "МЕНЕДЖЕР", font=_get_font(14), fill=MUTED)
    draw.text((PAD + 28, y + 52), manager_name[:26], font=_get_font(26), fill=TEXT)

    cx = PAD + card_w + gap
    draw.rounded_rectangle((cx, y, cx + card_w, y + card_h), radius=18, fill=INNER, outline=INNER_BORDER, width=1)
    draw.text((cx + 28, y + 22), "ЗАКАЗ", font=_get_font(14), fill=MUTED)
    draw.text((cx + 28, y + 52), ticket_name[:26], font=_get_font(26), fill=TEXT)

    # ========= ТАБЛИЦА =========
    y += card_h + 45
    draw.text((PAD, y), "ТОВАР / УСЛУГА", font=_get_font(14), fill=MUTED)
    rw, _ = _text_size(draw, "СУММА", _get_font(14))
    draw.text((W - PAD - rw, y), "СУММА", font=_get_font(14), fill=MUTED)
    y += 30
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)

    y += 24
    draw.text((PAD, y), ticket_name[:50], font=_get_font(22), fill=TEXT)
    amount_text = f"{amount} Р"
    aw, _ = _text_size(draw, amount_text, _get_font(22))
    draw.text((W - PAD - aw, y), amount_text, font=_get_font(22), fill=TEXT)
    y += 50
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)

    if discount_percent > 0:
        y += 24
        draw.text((PAD, y), f"Скидка ({discount_percent}%)", font=_get_font(22), fill=GREEN)
        disc_text = f"−{discount_rub} Р"
        dw, _ = _text_size(draw, disc_text, _get_font(22))
        draw.text((W - PAD - dw, y), disc_text, font=_get_font(22), fill=GREEN)
        y += 50
        draw.line((PAD, y, W - PAD, y), fill=LINE, width=1)

    # ========= ИТОГО =========
    y += 45
    total_h = 130
    draw.rounded_rectangle((PAD, y, W - PAD, y + total_h), radius=18, fill=INNER, outline=INNER_BORDER, width=1)
    draw.text((PAD + 34, y + 46), "ИТОГО К ОПЛАТЕ", font=_get_font(20), fill=MUTED)
    total_text = f"{total} Р"
    tw, _ = _text_size(draw, total_text, _get_font(56))
    draw.text((W - PAD - 34 - tw, y + 38), total_text, font=_get_font(56), fill=TEXT)

    # ========= РЕКВИЗИТЫ =========
    y += total_h + 45
    req_h = 240
    draw.rounded_rectangle((PAD, y, W - PAD, y + req_h), radius=18, fill=INNER, outline=INNER_BORDER, width=1)
    draw.text((PAD + 34, y + 26), "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ", font=_get_font(20), fill=TEXT)

    req_lines = [
        ("Т-Банк", "2200 7020 8029 9345"),
        ("АльфаБанк", "2200 1545 6426 7465"),
        ("ОзонБанк", "2204 3204 4881 5151"),
        ("СБП", "+7 983 694 76 41 (Виктор А.)"),
    ]
    ly = y + 80
    for key, val in req_lines:
        draw.text((PAD + 34, ly), key, font=_get_font(18), fill=MUTED)
        vw, _ = _text_size(draw, val, _get_font(18))
        draw.text((W - PAD - 34 - vw, ly), val, font=_get_font(18), fill=TEXT)
        ly += 38
        if ly < y + req_h - 15:
            draw.line((PAD + 34, ly - 12, W - PAD - 34, ly - 12), fill=(35, 35, 40), width=1)

    # ========= ФУТЕР: только DIAMOND =========
    y += req_h + 30
    draw.text((PAD, y), "DIAMOND", font=_get_font(20), fill=MUTED)

    # Сохраняем
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    logger.info(f"Счёт сгенерирован: {order_id}")
    return buf


def generate_receipt_id() -> str:
    return f"D-{int(time.time())}-{random.randint(100, 999)}"
