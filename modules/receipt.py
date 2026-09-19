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
FONT_FA_SOLID = os.path.join(ADD_DIR, "fa-solid-900.ttf")
FONT_FA_REGULAR = os.path.join(ADD_DIR, "fa-regular-400.ttf")

_FONT_CACHE = {}
_FA_CACHE = {}

ICON_CART        = 0xf07a
ICON_USER_TIE    = 0xf508
ICON_BOX         = 0xf466
ICON_CREDIT_CARD = 0xf09d
ICON_CLOCK       = 0xf017
ICON_USER        = 0xf007


def _get_font(size: int):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        font = ImageFont.truetype(FONT_BOLD_PATH, size)
    except Exception:
        font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


def _get_fa_icon_font(size: int, solid: bool = True):
    key = (size, solid)
    if key in _FA_CACHE:
        return _FA_CACHE[key]
    path = FONT_FA_SOLID if solid else FONT_FA_REGULAR
    font = None
    if os.path.exists(path):
        try:
            font = ImageFont.truetype(path, size)
        except Exception as e:
            logger.warning(f"Ошибка загрузки FA-шрифта {path}: {e}")
    _FA_CACHE[key] = font
    return font


def _draw_icon(draw, cx, cy, code, size, color, solid=True):
    font = _get_fa_icon_font(size, solid)
    if font is None:
        return False
    try:
        draw.text((cx, cy), chr(code), font=font, fill=color, anchor="mm")
        return True
    except Exception:
        return False


def _text_size(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_centered(draw, cx, y, text, font, fill):
    tw, _ = _text_size(draw, text, font)
    draw.text((cx - tw // 2, y), text, font=font, fill=fill)
    return tw


def generate_receipt_png(
    manager_name: str,
    customer_name: str,
    product_name: str,
    amount: int,
    discount_percent: int = 0,
    order_id: Optional[str] = None,
) -> io.BytesIO:
    """1800×1200 (3:2). Реквизиты растянуты, шрифт крупнее, низ прижат к нижнему краю."""
    if order_id is None:
        order_id = f"D-{int(time.time())}-{random.randint(100, 999)}"

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%d.%m.%Y · %H:%M")
    deadline_str = (now + timedelta(hours=1)).strftime("%d.%m.%Y · %H:%M")

    discount_rub = int(amount * discount_percent / 100)
    total = max(amount - discount_rub, 0)

    W, H = 1800, 1200
    M = 22
    PAD = 60

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

    draw.ellipse((W - 570, -270, W + 120, 420), fill=(16, 16, 20))
    draw.ellipse((-210, H - 390, 330, H + 150), fill=(14, 22, 18))

    draw.rounded_rectangle((M, M, W - M, H - M), radius=33, fill=CARD_BOT, outline=BORDER, width=3)
    draw.rounded_rectangle((M + 1, M + 1, W - M - 1, H // 2), radius=33, fill=CARD_TOP)

    # 1. ШАПКА
    y = M + 45
    logo_box = 81
    draw.rounded_rectangle((PAD, y, PAD + logo_box, y + logo_box), radius=21, fill=LOGO_BG)
    _draw_icon(draw, PAD + logo_box // 2, y + logo_box // 2 + 2, ICON_CART, 48, LOGO_ICON, solid=True)

    draw.text((PAD + logo_box + 24, y + 3), "DIAMOND", font=_get_font(39), fill=TEXT)
    draw.text((PAD + logo_box + 27, y + 57), "SHOP & ECOSYSTEM", font=_get_font(16), fill=MUTED)

    lbl_font = _get_font(20)
    num_font = _get_font(22)
    date_font = _get_font(20)
    lbl_text = "Заказ "
    num_text = f"№{order_id}"
    lw, _ = _text_size(draw, lbl_text, lbl_font)
    nw, _ = _text_size(draw, num_text, num_font)
    dx = W - PAD - (lw + nw)
    draw.text((dx, y + 15), lbl_text, font=lbl_font, fill=MUTED)
    draw.text((dx + lw, y + 12), num_text, font=num_font, fill=TEXT)
    dw, _ = _text_size(draw, date_str, date_font)
    draw.text((W - PAD - dw, y + 51), date_str, font=date_font, fill=MUTED)

    y += logo_box + 30

    # 2. ГЕРОЙ
    cx = W // 2
    _draw_centered(draw, cx, y, "ИТОГО К ОПЛАТЕ", _get_font(21), MUTED)
    y += 39
    total_text = f"{total} Р"
    font_size = 108
    tw, _ = _text_size(draw, total_text, _get_font(font_size))
    while tw > W - PAD * 2 - 300 and font_size > 60:
        font_size -= 6
        tw, _ = _text_size(draw, total_text, _get_font(font_size))
    _draw_centered(draw, cx, y, total_text, _get_font(font_size), TEXT)
    y += font_size + 9

    if discount_percent > 0:
        badge_text = f"Скидка {discount_percent}%  ·  −{discount_rub} Р"
        bf = _get_font(21)
        bw, bh = _text_size(draw, badge_text, bf)
        pad_bx, pad_by = 27, 10
        badge_w = bw + pad_bx * 2
        badge_h = bh + pad_by * 2
        bx = cx - badge_w // 2
        draw.rounded_rectangle((bx, y, bx + badge_w, y + badge_h),
                               radius=15, fill=GREEN_BG, outline=GREEN, width=2)
        draw.text((bx + pad_bx, y + pad_by), badge_text, font=bf, fill=GREEN)
        y += badge_h

    # 3. РАЗДЕЛИТЕЛЬ
    y += 33
    cx_ = W // 2
    line_color = (58, 58, 63)
    draw.line((PAD, y, cx_ - 30, y), fill=line_color, width=2)
    draw.line((cx_ + 30, y, W - PAD, y), fill=line_color, width=2)
    _draw_icon(draw, cx_, y, ICON_CART, 22, (74, 74, 79), solid=True)
    y += 27

    # 4. МЕНЕДЖЕР / ЗАКАЗЧИК
    meta_h = 99
    gap_x = 21
    card_w = (W - PAD * 2 - gap_x) // 2

    draw.rounded_rectangle((PAD, y, PAD + card_w, y + meta_h),
                           radius=21, fill=GREEN_BG, outline=GREEN, width=3)
    _draw_icon(draw, PAD + 39, y + meta_h // 2, ICON_USER_TIE, 24, GREEN, solid=True)
    draw.text((PAD + 69, y + 18), "МЕНЕДЖЕР", font=_get_font(15), fill=GREEN)
    draw.text((PAD + 69, y + 48), manager_name[:24], font=_get_font(28), fill=TEXT)

    cx2 = PAD + card_w + gap_x
    draw.rounded_rectangle((cx2, y, cx2 + card_w, y + meta_h),
                           radius=21, fill=INNER, outline=BORDER, width=3)
    _draw_icon(draw, cx2 + 39, y + meta_h // 2, ICON_USER, 24, MUTED, solid=True)
    draw.text((cx2 + 69, y + 18), "ЗАКАЗЧИК", font=_get_font(15), fill=MUTED)
    draw.text((cx2 + 69, y + 48), customer_name[:24], font=_get_font(28), fill=TEXT)

    y += meta_h + 21

    # 5. ТАБЛИЦА
    items_top = y
    rows = 1 + (1 if discount_percent > 0 else 0) + 1
    items_h = 45 + rows * 39 + 18

    draw.rounded_rectangle((PAD, items_top, W - PAD, items_top + items_h),
                           radius=21, fill=INNER, outline=INNER_BORDER, width=2)

    ip = 27
    draw.text((PAD + ip, items_top + 12), "ТОВАР / УСЛУГА", font=_get_font(15), fill=MUTED)
    hdr = "СУММА"
    hw, _ = _text_size(draw, hdr, _get_font(15))
    draw.text((W - PAD - ip - hw, items_top + 12), hdr, font=_get_font(15), fill=MUTED)
    draw.line((PAD + ip, items_top + 39, W - PAD - ip, items_top + 39), fill=LINE, width=2)

    row_y = items_top + 48
    item_font = _get_font(21)
    draw.text((PAD + ip, row_y), product_name[:40], font=item_font, fill=TEXT)
    amt_str = f"{amount} Р"
    aw, _ = _text_size(draw, amt_str, item_font)
    draw.text((W - PAD - ip - aw, row_y), amt_str, font=item_font, fill=TEXT)
    row_y += 36

    if discount_percent > 0:
        disc_font = _get_font(21)
        draw.text((PAD + ip, row_y), f"Скидка ({discount_percent}%)", font=disc_font, fill=GREEN)
        ds = f"−{discount_rub} Р"
        dw_, _ = _text_size(draw, ds, disc_font)
        draw.text((W - PAD - ip - dw_, row_y), ds, font=disc_font, fill=GREEN)
        row_y += 36

    draw.line((PAD + ip, row_y + 3, W - PAD - ip, row_y + 3), fill=GREEN, width=3)
    row_y += 12
    tf = _get_font(27)
    draw.text((PAD + ip, row_y), "Итого к оплате", font=tf, fill=TEXT)
    ts = f"{total} Р"
    tw_, _ = _text_size(draw, ts, tf)
    draw.text((W - PAD - ip - tw_, row_y), ts, font=tf, fill=GREEN)

    y = items_top + items_h + 18

    # 6. РЕКВИЗИТЫ
    bottom_block_h = 110
    content_bottom = H - M - 30
    req_top = y
    req_h = content_bottom - req_top - bottom_block_h

    draw.rounded_rectangle((PAD, req_top, W - PAD, req_top + req_h),
                           radius=21, fill=INNER, outline=INNER_BORDER, width=2)

    _draw_icon(draw, PAD + 36, req_top + 33, ICON_CREDIT_CARD, 24, MUTED, solid=True)
    draw.text((PAD + 63, req_top + 22), "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ", font=_get_font(16), fill=MUTED)

    req_data = [
        ("Т-Банк", "2200 7020 8029 9345"),
        ("АльфаБанк", "2200 1545 6426 7465"),
        ("ОзонБанк", "2204 3204 4881 5151"),
        ("СБП", "+7 983 694 76 41"),
    ]

    inner_top = req_top + 75
    inner_bottom = req_top + req_h - 22
    available = inner_bottom - inner_top
    row_h = available // 2

    col_gap = 60
    inner_side = 36
    col_w = (W - PAD * 2 - inner_side * 2 - col_gap) // 2

    k_font = _get_font(17)
    v_font = _get_font(28)

    for i, (key, val) in enumerate(req_data):
        col = i % 2
        row = i // 2
        item_x = PAD + inner_side + col * (col_w + col_gap)
        row_y_start = inner_top + row * row_h
        row_y_center = row_y_start + row_h // 2

        if row == 0:
            sep_y = inner_top + row_h
            draw.line((PAD + inner_side, sep_y, W - PAD - inner_side, sep_y), fill=DASH, width=2)

        draw.text((item_x, row_y_center - 32), key.upper(), font=k_font, fill=MUTED)
        vw, _ = _text_size(draw, val, v_font)
        draw.text((item_x + col_w - vw, row_y_center - 6), val, font=v_font, fill=TEXT)

    # 7. НИЗ
    y = req_top + req_h + 25
    draw.line((PAD, y, W - PAD, y), fill=LINE, width=2)
    y += 24

    _draw_icon(draw, PAD + 15, y + 15, ICON_CLOCK, 24, MUTED, solid=False)
    dfont = _get_font(18)
    draw.text((PAD + 36, y + 5), "Оплатить до:", font=dfont, fill=MUTED)
    lw_, _ = _text_size(draw, "Оплатить до: ", dfont)
    draw.text((PAD + 36 + lw_, y + 3), deadline_str, font=_get_font(20), fill=TEXT)

    steps = ["Оплата", "Чек", "Проверка", "Готово"]
    step_font = _get_font(16)
    n_font = _get_font(15)
    step_gap = 21
    step_widths = []
    for name in steps:
        tw_, _ = _text_size(draw, name, step_font)
        step_widths.append(27 + 9 + tw_)
    total_steps_w = sum(step_widths) + step_gap * (len(steps) - 1)

    sx = W - PAD - total_steps_w
    for i, name in enumerate(steps):
        w = step_widths[i]
        circle_x = sx
        circle_y = y + 6
        circle_size = 27
        is_active = (i == 0)
        draw.ellipse((circle_x, circle_y, circle_x + circle_size, circle_y + circle_size),
                     fill=GREEN if is_active else STEPS_OFF)
        num_str = str(i + 1)
        nw_, nh_ = _text_size(draw, num_str, n_font)
        draw.text((circle_x + (circle_size - nw_) // 2,
                   circle_y + (circle_size - nh_) // 2 - 3),
                  num_str, font=n_font,
                  fill=(0, 0, 0) if is_active else TEXT)
        draw.text((circle_x + circle_size + 9, y + 9), name, font=step_font,
                  fill=TEXT if is_active else MUTED)
        sx += w + step_gap

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    logger.info(f"Счёт сгенерирован: {order_id}")
    return buf


def generate_receipt_id() -> str:
    return f"D-{int(time.time())}-{random.randint(100, 999)}"
