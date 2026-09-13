# -*- coding: utf-8 -*-
import os
import io
import time
import random
from datetime import datetime, timezone
from typing import Optional, List, Dict

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, DATA_DIR, logger

# Путь к шрифту, который уже используется для баннера
FONT_BOLD_PATH = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")

# Кэш шрифтов, чтобы не грузить каждый раз
_FONT_CACHE = {}


def _get_font(size: int):
    """Загружает шрифт нужного размера (с кэшем)."""
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        font = ImageFont.truetype(FONT_BOLD_PATH, size)
    except Exception:
        # Если шрифта нет — берём дефолтный
        font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple:
    """Возвращает (width, height) текста."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def generate_receipt_png(
    manager_name: str,
    ticket_name: str,
    amount: int,
    discount: int = 0,
    order_id: Optional[str] = None,
) -> io.BytesIO:
    """
    Генерирует PNG-счёт через Pillow и возвращает BytesIO с изображением.

    Параметры:
    - manager_name: имя менеджера, ведущего тикет
    - ticket_name: название тикета (канала) — используется как название товара
    - amount: базовая сумма (₽)
    - discount: скидка (₽), 0 если нет
    """
    if order_id is None:
        order_id = f"D-{int(time.time())}-{random.randint(100, 999)}"

    date_str = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")
    total = max(amount - discount, 0)

    # Размеры картинки
    W, H = 800, 900
    BG = (14, 14, 16)            # фоновый тёмный
    CARD = (26, 26, 31)          # цвет карточек
    BORDER = (103, 103, 103)     # граница
    TEXT = (255, 255, 255)       # основной текст
    MUTED = (136, 136, 136)      # приглушённый текст
    GREEN = (46, 204, 113)       # зелёный для скидки
    LINE = (51, 51, 51)          # линии

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # ---- Фоновые декоративные круги ----
    # Большой справа сверху
    draw.ellipse((W - 250, -150, W + 150, 250), fill=(20, 20, 24))
    draw.ellipse((W - 200, -100, W + 100, 200), fill=(24, 24, 28))
    # Слева снизу
    draw.ellipse((-200, H - 250, 200, H + 150), fill=(18, 22, 20))

    # ---- Основная карточка ----
    CARD_MARGIN = 20
    draw.rounded_rectangle(
        (CARD_MARGIN, CARD_MARGIN, W - CARD_MARGIN, H - CARD_MARGIN),
        radius=24, fill=CARD, outline=BORDER, width=2
    )

    # ---- Заголовок с лого ----
    y = 60
    # Лого (квадрат с ромбом)
    draw.rounded_rectangle((60, y, 112, y + 52), radius=14, fill=(70, 70, 75))
    draw.text((74, y + 12), "◆", font=_get_font(26), fill=(230, 230, 230))

    # DIAMOND
    draw.text((130, y + 2), "DIAMOND", font=_get_font(26), fill=TEXT)
    draw.text((130, y + 34), "SHOP & ECOSYSTEM", font=_get_font(11), fill=MUTED)

    # Бейдж "СЧЁТ" справа
    badge_w, badge_h = 100, 36
    draw.rounded_rectangle(
        (W - 60 - badge_w, y + 8, W - 60, y + 8 + badge_h),
        radius=10, fill=(80, 80, 85)
    )
    draw.text((W - 60 - badge_w + 20, y + 16), "СЧЁТ", font=_get_font(14), fill=TEXT)

    # Линия под шапкой
    y += 90
    draw.line((60, y, W - 60, y), fill=LINE, width=1)

    # ---- Заголовок ----
    y += 30
    draw.text((60, y), "Счёт на оплату", font=_get_font(34), fill=TEXT)
    y += 50
    draw.text((60, y), f"Заказ №{order_id} от {date_str}", font=_get_font(14), fill=MUTED)

    # ---- Две карточки: Менеджер / Заказ ----
    y += 50
    card_y1 = y
    card_y2 = y + 80
    card_w = (W - 120 - 20) // 2  # с учётом отступов

    # Менеджер
    draw.rounded_rectangle((60, card_y1, 60 + card_w, card_y2), radius=14, fill=(20, 20, 25), outline=(42, 42, 47))
    draw.text((80, card_y1 + 14), "МЕНЕДЖЕР", font=_get_font(11), fill=MUTED)
    draw.text((80, card_y1 + 36), manager_name[:22], font=_get_font(17), fill=TEXT)

    # Заказ
    draw.rounded_rectangle((60 + card_w + 20, card_y1, W - 60, card_y2), radius=14, fill=(20, 20, 25), outline=(42, 42, 47))
    draw.text((80 + card_w + 20, card_y1 + 14), "ЗАКАЗ", font=_get_font(11), fill=MUTED)
    draw.text((80 + card_w + 20, card_y1 + 36), ticket_name[:22], font=_get_font(17), fill=TEXT)

    # ---- Таблица товаров ----
    y = card_y2 + 40
    draw.text((60, y), "ТОВАР / УСЛУГА", font=_get_font(11), fill=MUTED)
    draw.text((W - 60 - 100, y), "СУММА", font=_get_font(11), fill=MUTED)
    y += 25
    draw.line((60, y, W - 60, y), fill=LINE, width=1)

    # Строка с товаром
    y += 20
    draw.text((60, y), ticket_name[:38], font=_get_font(15), fill=TEXT)
    amount_text = f"{amount} ₽"
    aw, _ = _text_size(draw, amount_text, _get_font(15))
    draw.text((W - 60 - aw, y), amount_text, font=_get_font(15), fill=TEXT)
    y += 40
    draw.line((60, y, W - 60, y), fill=LINE, width=1)

    # Строка скидки (если есть)
    if discount > 0:
        y += 20
        draw.text((60, y), "Скидка", font=_get_font(15), fill=GREEN)
        disc_text = f"−{discount} ₽"
        dw, _ = _text_size(draw, disc_text, _get_font(15))
        draw.text((W - 60 - dw, y), disc_text, font=_get_font(15), fill=GREEN)
        y += 40
        draw.line((60, y, W - 60, y), fill=LINE, width=1)

    # ---- Итог ----
    y += 40
    total_card_h = 100
    draw.rounded_rectangle((60, y, W - 60, y + total_card_h), radius=14, fill=(20, 20, 25), outline=(42, 42, 47))
    draw.text((80, y + 30), "ИТОГО К ОПЛАТЕ", font=_get_font(14), fill=MUTED)
    total_text = f"{total} ₽"
    tw, _ = _text_size(draw, total_text, _get_font(34))
    draw.text((W - 80 - tw, y + 28), total_text, font=_get_font(34), fill=TEXT)
    y += total_card_h + 40

    # ---- Реквизиты ----
    draw.rounded_rectangle((60, y, W - 60, y + 200), radius=14, fill=(20, 20, 25), outline=(42, 42, 47))
    draw.text((80, y + 20), "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ", font=_get_font(14), fill=TEXT)

    req_lines = [
        ("Т-Банк", "2200 7020 8029 9345"),
        ("АльфаБанк", "2200 1545 6426 7465"),
        ("ОзонБанк", "2204 3204 4881 5151"),
        ("СБП", "+7 983 694 76 41 (Виктор А.)"),
    ]
    ly = y + 55
    for key, val in req_lines:
        draw.text((80, ly), key, font=_get_font(13), fill=MUTED)
        vw, _ = _text_size(draw, val, _get_font(13))
        draw.text((W - 80 - vw, ly), val, font=_get_font(13), fill=TEXT)
        ly += 33
        if ly < y + 200 - 10:
            draw.line((80, ly - 8, W - 80, ly - 8), fill=(35, 35, 40), width=1)

    # ---- Футер ----
    y = H - 130
    draw.line((60, y, W - 60, y), fill=LINE, width=1)
    y += 15
    draw.text((60, y), "ООО «Diamond Shop» · ИНН 0000000000", font=_get_font(11), fill=MUTED)
    draw.text((60, y + 18), "После оплаты отправьте чек в тикет.", font=_get_font(11), fill=MUTED)
    draw.text((60, y + 36), "Все проверяется. Обмануть не получится.", font=_get_font(11), fill=MUTED)

    # Штамп DIAMOND справа
    stamp_w = 140
    draw.rounded_rectangle(
        (W - 60 - stamp_w, y, W - 60, y + 50),
        radius=12, outline=BORDER, width=2
    )
    draw.text((W - 60 - stamp_w + 25, y + 17), "DIAMOND", font=_get_font(16), fill=MUTED)

    # ---- Сохраняем в BytesIO ----
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    logger.info(f"Счёт сгенерирован: {order_id}")
    return buf

    def generate_receipt_id() -> str:
    return f"D-{int(time.time())}-{random.randint(100, 999)}"

