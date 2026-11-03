# -*- coding: utf-8 -*-
"""
Автозаказ — полная система с Pillow-рендером на каждом шаге.
Один файл. Всё внутри.
"""
import io
import os
import math
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict

import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption
from disnake.ui import Button, Select, View, Modal, TextInput
from PIL import Image, ImageDraw, ImageFont

from core.utils import (
    CONFIG, ADD_DIR, logger, db, cur,
    now_ts, log_discord, add_ticket_owner,
)

# ============================================================
# КОНСТАНТЫ
# ============================================================
AUTOORDER_CHANNEL_ID = 1565412940281024512
AUTOORDER_TICKET_CATEGORY = 1470779295650549885
LOG_CHANNEL_ID = 1530453871581855744
SESSION_TIMEOUT = 300

IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"
COLOR_GREY = 0x676767
P = "\u3164"

# ============================================================
# ПАЛИТРА (Pillow)
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
GREY      = (103, 103, 103)
GREY_DARK = (74, 74, 82)
GREY_LIGHT = (150, 150, 158)
SILVER    = (212, 218, 230)
GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
GOLD      = (247, 201, 145)

FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")
_F, _FA = {}, {}

def _font(sz):
    if sz in _F: return _F[sz]
    try: f = ImageFont.truetype(FONT_BOLD, sz)
    except Exception: f = ImageFont.load_default()
    _F[sz] = f; return f

def _fa(sz):
    if sz in _FA: return _FA[sz]
    f = None
    if os.path.exists(FONT_FA):
        try: f = ImageFont.truetype(FONT_FA, sz)
        except Exception: pass
    _FA[sz] = f; return f

def _tw(d, t, f):
    b = d.textbbox((0, 0), t, font=f); return b[2] - b[0]

def _el(d, t, f, w):
    if _tw(d, t, f) <= w: return t
    while t and _tw(d, t + "…", f) > w: t = t[:-1]
    return t + "…"

def _icon(d, cx, cy, code, sz, color):
    f = _fa(sz)
    if f is None: return
    try: d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception: pass

def _alpha(img, box, color, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if radius > 0:
        ld.rounded_rectangle((0, 0, w-1, h-1), radius=radius, fill=color + (alpha,))
    else:
        ld.rectangle((0, 0, w-1, h-1), fill=color + (alpha,))
    img.paste(layer, (x1, y1), layer)

def _grad(img, box, c1, c2, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i in range(w):
        t = i / max(w-1, 1)
        r = int(c1[0]*(1-t) + c2[0]*t)
        g = int(c1[1]*(1-t) + c2[1]*t)
        b = int(c1[2]*(1-t) + c2[2]*t)
        ld.line([(i, 0), (i, h)], fill=(r, g, b, alpha))
    if radius > 0:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w-1, h-1), radius=radius, fill=255)
        a = layer.split()[3]
        a = Image.composite(a, Image.new("L", (w, h), 0), mask)
        layer.putalpha(a)
    img.paste(layer, (x1, y1), layer)

def _stripe(d, x1, y1, x2, color=SILVER):
    """Декоративная серая полоса"""
    d.rounded_rectangle((x1, y1, x2, y1+2), radius=1, fill=color + (200,))

# FA icons
I_GEM       = 0xf3a5
I_BOLT      = 0xf0e7
I_CART      = 0xf07a
I_CHECK     = 0xf00c
I_TAG       = 0xf02b
I_CARD      = 0xf09d
I_SHIELD    = 0xf3ed
I_STAR      = 0xf005
I_INFO      = 0xf05a
I_BOX       = 0xf466
I_CLOCK     = 0xf017
I_ARROW     = 0xf061
I_TIMES     = 0xf00d
I_PLUS      = 0xf067

# ============================================================
# PILLOW-РЕНДЕРЫ
# ============================================================
CANVAS_W, CANVAS_H = 1800, 1000
M = 14
PAD_X, PAD_Y = 40, 40

def _canvas(title_subtitle: str = "автозаказ"):
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((M, M, CANVAS_W-1-M, CANVAS_H-1-M),
                        radius=28, fill=CARD_TOP + (255,),
                        outline=STACK_BRD + (255,), width=3)

    hx, hy = PAD_X, PAD_Y
    logo_size = 54
    d.rounded_rectangle((hx, hy, hx+logo_size, hy+logo_size), radius=14,
                        fill=(58, 58, 64, 255))
    _icon(d, hx+logo_size//2, hy+logo_size//2+1, I_BOLT, 26, SILVER)

    bx = hx + logo_size + 18
    d.text((bx, hy+4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx+2, hy+38), "AUTOORDER SYSTEM", font=_font(11), fill=MUTED)

    meta_r = CANVAS_W - M - PAD_X
    w1 = _tw(d, title_subtitle.upper(), _font(14))
    d.text((meta_r-w1, hy+20), title_subtitle.upper(), font=_font(14), fill=GREY_LIGHT)

    sep_y = hy + logo_size + 20
    d.line((PAD_X, sep_y, CANVAS_W-M-PAD_X, sep_y), fill=STACK_HDR + (255,), width=2)
    return img, d

def _footer(d, left_text: str, right_text: str = "v1.0"):
    y = CANVAS_H - M - PAD_Y + 6
    d.line((PAD_X, y-10, CANVAS_W-M-PAD_X, y-10), fill=STACK_HDR + (255,), width=2)
    _icon(d, PAD_X+12, y+10, I_INFO, 16, DIM)
    d.text((PAD_X+38, y), left_text, font=_font(15), fill=DIM)
    rw = _tw(d, right_text, _font(15))
    d.text((CANVAS_W-M-PAD_X-rw, y), right_text, font=_font(15), fill=GREY_LIGHT)


def render_panel() -> io.BytesIO:
    img, d = _canvas("панель")
    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    # LEFT — заголовок
    left_x1 = PAD_X
    left_x2 = PAD_X + 920

    title_y = body_y + 20
    _grad(img, (left_x1, title_y, left_x1+720, title_y+130),
          GREY_LIGHT, GREY_DARK, alpha=200, radius=24)
    d.text((left_x1+40, title_y+20), "АВТОЗАКАЗ",
           font=_font(88), fill=(20, 20, 24))
    d.text((left_x1+42, title_y+128), "AUTO · SHOP · SYSTEM",
           font=_font(13), fill=(20, 20, 24))

    _stripe(d, left_x1, title_y+160, left_x1+720, SILVER)

    sub_y = title_y + 180
    d.text((left_x1, sub_y),
           "Новая система покупок Diamond Shop",
           font=_font(22), fill=SILVER)

    desc_y = sub_y + 44
    for i, line in enumerate([
        "Забудь про ожидание менеджера. Собирай корзину, применяй",
        "скидки и оплачивай заказ в один клик. Менеджер подключится",
        "только к подтверждению оплаты.",
    ]):
        d.text((left_x1, desc_y + i*26), line, font=_font(16), fill=TEXT_SOFT)

    steps_y = desc_y + 110
    steps = [
        ("1", "Категория", "7 разделов"),
        ("2", "Корзина", "С количеством"),
        ("3", "Скидки", "Промо / 10%"),
        ("4", "Оплата", "Т-Банк · СБП · Озон"),
        ("5", "Чек", "Фото или PDF"),
    ]
    step_w, step_h, step_gap = 172, 108, 12
    for i, (num, title, sub) in enumerate(steps):
        sx1 = left_x1 + i * (step_w + step_gap)
        sx2 = sx1 + step_w
        sy1 = steps_y
        sy2 = sy1 + step_h

        _grad(img, (sx1, sy1, sx2, sy2), GREY, GREY_DARK, alpha=25, radius=14)
        d.rounded_rectangle((sx1, sy1, sx2, sy2), radius=14,
                            outline=GREY + (180,), width=2)
        d.text((sx1+20, sy1+12), num, font=_font(30), fill=GREY_LIGHT)
        d.text((sx1+20, sy1+54), title, font=_font(15), fill=TEXT)
        d.text((sx1+20, sy1+78), sub, font=_font(11), fill=MUTED)

    # RIGHT — фичи
    right_x1 = left_x2 + 40
    right_x2 = CANVAS_W - M - PAD_X
    feats_y = body_y + 20
    feat_h = 200
    feat_gap = 16
    features = [
        (I_BOLT,   "Быстро",    "Оформление за 2 минуты",  "Без ожидания менеджера"),
        (I_SHIELD, "Безопасно", "Скрытые тикеты",          "Юзер видит канал после оплаты"),
        (I_STAR,   "Удобно",    "Всё в одном окне",        "Категории, корзина, скидки, чек"),
    ]
    for i, (icon, title, sub, desc) in enumerate(features):
        fy1 = feats_y + i * (feat_h + feat_gap)
        fy2 = fy1 + feat_h
        _grad(img, (right_x1, fy1, right_x2, fy2), GREY, GREY_DARK, alpha=30, radius=20)
        d.rounded_rectangle((right_x1, fy1, right_x2, fy2), radius=20,
                            outline=GREY + (180,), width=2)
        icon_size = 72
        ib_x = right_x1 + 24
        ib_y = fy1 + (feat_h - icon_size)//2
        _alpha(img, (ib_x, ib_y, ib_x+icon_size, ib_y+icon_size), GREY, alpha=60, radius=18)
        d.rounded_rectangle((ib_x, ib_y, ib_x+icon_size, ib_y+icon_size),
                            radius=18, outline=SILVER + (150,), width=2)
        _icon(d, ib_x+icon_size//2, ib_y+icon_size//2+1, icon, 32, SILVER)
        tx = ib_x + icon_size + 24
        ty = fy1 + 42
        d.text((tx, ty), title, font=_font(28), fill=SILVER)
        d.text((tx, ty+40), sub, font=_font(14), fill=TEXT_SOFT)
        d.text((tx, ty+66), desc, font=_font(12), fill=MUTED)

    _footer(d, "Нажми «Открыть Автозаказ» — чтобы начать")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


def render_categories() -> io.BytesIO:
    img, d = _canvas("категории")
    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    d.text((PAD_X, body_y), "Выберите категорию", font=_font(44), fill=TEXT)
    d.text((PAD_X, body_y+56), "7 разделов · товары за реальные деньги", font=_font(16), fill=MUTED)
    _stripe(d, PAD_X, body_y+90, CANVAS_W-M-PAD_X, SILVER)

    cats = [
        ("Discord", "Нитро, Бусты, Гифты", I_GEM),
        ("Telegram", "Звёзды, Аккаунты, Прокси", I_BOLT),
        ("Steam", "Пополнение, Смена региона", I_CARD),
        ("Roblox", "Robux, Plus, Подарочные", I_BOX),
        ("Spotify", "Индивидуальная подписка", I_STAR),
        ("Боты и Дизайн", "Разработка, оформление", I_TAG),
        ("Украшения", "Профили, Бейджи, Наборы", I_SHIELD),
    ]

    grid_y = body_y + 120
    grid_bottom = CANVAS_H - M - PAD_Y - 26
    gap = 16
    cols = 3
    cell_w = (CANVAS_W - 2*PAD_X - gap*(cols-1)) // cols
    rows = math.ceil(len(cats)/cols)
    cell_h = (grid_bottom - grid_y - gap*(rows-1)) // rows
    cell_h = min(cell_h, 180)

    for i, (title, sub, icon) in enumerate(cats):
        r, c = divmod(i, cols)
        cx1 = PAD_X + c*(cell_w+gap)
        cy1 = grid_y + r*(cell_h+gap)
        cx2 = cx1 + cell_w
        cy2 = cy1 + cell_h

        _grad(img, (cx1, cy1, cx2, cy2), GREY, GREY_DARK, alpha=20, radius=18)
        d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=18,
                            outline=GREY + (180,), width=2)

        icon_size = 64
        ib_x = cx1 + 24
        ib_y = cy1 + (cell_h-icon_size)//2
        _alpha(img, (ib_x, ib_y, ib_x+icon_size, ib_y+icon_size), GREY, alpha=55, radius=16)
        d.rounded_rectangle((ib_x, ib_y, ib_x+icon_size, ib_y+icon_size),
                            radius=16, outline=SILVER + (180,), width=2)
        _icon(d, ib_x+icon_size//2, ib_y+icon_size//2+1, icon, 28, SILVER)

        tx = ib_x + icon_size + 18
        d.text((tx, cy1+24), title, font=_font(22), fill=TEXT)
        d.text((tx, cy1+56), sub, font=_font(13), fill=MUTED)

    _footer(d, "Нажмите на селект ниже — чтобы выбрать категорию")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


def render_products(cat_title: str, items: list, page: int, total_pages: int) -> io.BytesIO:
    img, d = _canvas("товары")
    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    d.text((PAD_X, body_y), cat_title, font=_font(40), fill=TEXT)
    d.text((PAD_X, body_y+52), f"Страница {page} из {total_pages}", font=_font(16), fill=MUTED)
    _stripe(d, PAD_X, body_y+84, CANVAS_W-M-PAD_X, SILVER)

    list_y = body_y + 110
    list_bottom = CANVAS_H - M - PAD_Y - 26
    n = max(len(items), 1)
    row_h = min(110, (list_bottom - list_y - (n-1)*12) // n)
    gap = 12

    for i, item in enumerate(items):
        ry1 = list_y + i*(row_h+gap)
        ry2 = ry1 + row_h
        _grad(img, (PAD_X, ry1, CANVAS_W-M-PAD_X, ry2), GREY, GREY_DARK, alpha=15, radius=14)
        d.rounded_rectangle((PAD_X, ry1, CANVAS_W-M-PAD_X, ry2), radius=14,
                            outline=GREY + (150,), width=2)

        d.rounded_rectangle((PAD_X+8, ry1+12, PAD_X+12, ry2-12), radius=2, fill=GREY)

        tx = PAD_X + 36
        d.text((tx, ry1+20), item["name"], font=_font(24), fill=TEXT)
        d.text((tx, ry1+54), item["desc"], font=_font(14), fill=MUTED)

        price = item["price"]
        unit = item.get("unit", "шт")
        price_str = f"{price} ₽" + ("" if item["fixed"] else f" / {unit}")
        pf = _font(28)
        pw = _tw(d, price_str, pf)
        d.text((CANVAS_W-M-PAD_X-36-pw, ry1+row_h//2-16), price_str, font=pf, fill=SILVER)

        if not item["fixed"]:
            d.text((CANVAS_W-M-PAD_X-36-pw, ry1+row_h//2+20), "количество — через модалку",
                   font=_font(11), fill=GREY_LIGHT)

    _footer(d, "Выберите товар в селекте ниже")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


def render_cart(cart: dict) -> io.BytesIO:
    img, d = _canvas("корзина")
    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    d.text((PAD_X, body_y), "Корзина", font=_font(44), fill=TEXT)
    d.text((PAD_X, body_y+56), "Товары для оформления", font=_font(16), fill=MUTED)
    _stripe(d, PAD_X, body_y+90, CANVAS_W-M-PAD_X, SILVER)

    list_y = body_y + 110
    list_bottom = CANVAS_H - M - PAD_Y - 120

    items = cart["items"]
    if not items:
        d.text((CANVAS_W//2, (list_y+list_bottom)//2), "Корзина пуста",
               font=_font(32), fill=DIM, anchor="mm")
    else:
        n = min(len(items), 5)
        row_h = min(90, (list_bottom - list_y - (n-1)*10)//n)
        for i, it in enumerate(items[:5]):
            ry1 = list_y + i*(row_h+10)
            ry2 = ry1 + row_h
            _grad(img, (PAD_X, ry1, CANVAS_W-M-PAD_X, ry2), GREY, GREY_DARK, alpha=15, radius=12)
            d.rounded_rectangle((PAD_X, ry1, CANVAS_W-M-PAD_X, ry2), radius=12,
                                outline=GREY + (150,), width=2)

            d.text((PAD_X+24, ry1+row_h//2-14), it["name"], font=_font(20), fill=TEXT)
            d.text((PAD_X+24, ry1+row_h//2+12), f"× {it['qty']} {it.get('unit','шт')}",
                   font=_font(13), fill=GREY_LIGHT)

            total = math.ceil(it["price"]*it["qty"])
            tf = _font(24)
            tw = _tw(d, f"{total} ₽", tf)
            d.text((CANVAS_W-M-PAD_X-24-tw, ry1+row_h//2-12),
                   f"{total} ₽", font=tf, fill=SILVER)

    # Итог
    total = math.ceil(sum(i["price"]*i["qty"] for i in items))
    sum_y = list_bottom + 20
    _grad(img, (PAD_X, sum_y, CANVAS_W-M-PAD_X, sum_y+80), GREY, GREY_DARK, alpha=25, radius=14)
    d.rounded_rectangle((PAD_X, sum_y, CANVAS_W-M-PAD_X, sum_y+80), radius=14,
                        outline=SILVER + (200,), width=2)
    d.text((PAD_X+24, sum_y+26), "ИТОГО:", font=_font(20), fill=SILVER)
    tf = _font(40)
    total_str = f"{total} ₽"
    tw = _tw(d, total_str, tf)
    d.text((CANVAS_W-M-PAD_X-24-tw, sum_y+18), total_str, font=tf, fill=SILVER)

    _footer(d, "Проверьте товары и нажмите «Оформить»")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


def render_checkout(cart: dict) -> io.BytesIO:
    img, d = _canvas("оплата")
    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    d.text((PAD_X, body_y), "Оплата заказа", font=_font(44), fill=TEXT)
    d.text((PAD_X, body_y+56), "Реквизиты и итоговая сумма", font=_font(16), fill=MUTED)
    _stripe(d, PAD_X, body_y+90, CANVAS_W-M-PAD_X, SILVER)

    total = math.ceil(sum(i["price"]*i["qty"] for i in cart["items"]))
    final = math.ceil(total - math.floor(total*cart["discount"]/100))

    # Сумма
    sum_y = body_y + 120
    _grad(img, (PAD_X, sum_y, CANVAS_W-M-PAD_X, sum_y+160), GREY, GREY_DARK, alpha=30, radius=20)
    d.rounded_rectangle((PAD_X, sum_y, CANVAS_W-M-PAD_X, sum_y+160), radius=20,
                        outline=SILVER + (200,), width=3)
    d.text((CANVAS_W//2, sum_y+30), "ИТОГО К ОПЛАТЕ", font=_font(16), fill=SILVER, anchor="mm")
    tf = _font(80)
    tw = _tw(d, f"{final} ₽", tf)
    d.text(((CANVAS_W-tw)//2, sum_y+60), f"{final} ₽", font=tf, fill=TEXT)

    if cart["discount"] > 0:
        d.text((CANVAS_W//2, sum_y+140), f"Скидка {cart['discount']}% применена",
               font=_font(16), fill=GREEN, anchor="mm")

    # Реквизиты
    req_y = sum_y + 200
    d.text((PAD_X, req_y), "РЕКВИЗИТЫ", font=_font(18), fill=GREY_LIGHT)
    _stripe(d, PAD_X, req_y+30, PAD_X+400, GREY_LIGHT)

    banks = {
        "tbank": ("Т-Банк", "+7 900 000-00-00", "Тимофей Д."),
        "sbp": ("СБП", "+7 900 000-00-00", "Тимофей Д."),
        "ozon": ("ОзонБанк", "2204 3204 4881 5151", "Тимофей Д."),
    }
    bank = banks[cart["bank"]]
    rows = [
        ("Банк", bank[0]),
        ("Номер", bank[1]),
        ("Получатель", bank[2]),
    ]
    for i, (k, v) in enumerate(rows):
        ry = req_y + 50 + i*40
        d.text((PAD_X, ry), k, font=_font(16), fill=MUTED)
        d.text((PAD_X+250, ry), v, font=_font(20), fill=TEXT)

    _footer(d, "Переведите сумму → нажмите «Я оплатил»")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


def render_receipt() -> io.BytesIO:
    img, d = _canvas("чек")
    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    d.text((PAD_X, body_y), "Пришлите чек", font=_font(44), fill=TEXT)
    d.text((PAD_X, body_y+56), "Фото или PDF — следующим сообщением", font=_font(16), fill=MUTED)
    _stripe(d, PAD_X, body_y+90, CANVAS_W-M-PAD_X, SILVER)

    zone_y1 = body_y + 140
    zone_y2 = zone_y1 + 400

    # Рамка загрузки (пунктирная имитация)
    d.rounded_rectangle((PAD_X+100, zone_y1, CANVAS_W-M-PAD_X-100, zone_y2),
                        radius=24, outline=GREY_LIGHT + (200,), width=3)
    _alpha(img, (PAD_X+100, zone_y1, CANVAS_W-M-PAD_X-100, zone_y2),
           GREY, alpha=10, radius=24)

    _icon(d, CANVAS_W//2, zone_y1+140, 0xf574, 80, SILVER)
    d.text((CANVAS_W//2, zone_y1+240), "Отправьте файл в этот канал",
           font=_font(32), fill=TEXT, anchor="mm")
    d.text((CANVAS_W//2, zone_y1+290), "PNG · JPG · PDF · до 8 МБ",
           font=_font(18), fill=GREY_LIGHT, anchor="mm")

    d.text((CANVAS_W//2, zone_y2+40), "Бот сам поймает ваш файл и создаст тикет",
           font=_font(16), fill=MUTED, anchor="mm")

    _footer(d, "Просто киньте чек в канал ниже")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


def render_success() -> io.BytesIO:
    img, d = _canvas("успех")
    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    cy = body_y + body_h//2 - 100

    _alpha(img, (CANVAS_W//2-120, cy-120, CANVAS_W//2+120, cy+120),
           GREEN, alpha=30, radius=200)
    _icon(d, CANVAS_W//2, cy, I_CHECK, 120, GREEN)

    d.text((CANVAS_W//2, cy+180), "Заказ оформлен!",
           font=_font(52), fill=GREEN, anchor="mm")
    d.text((CANVAS_W//2, cy+240), "Чек отправлен на проверку",
           font=_font(22), fill=TEXT_SOFT, anchor="mm")
    d.text((CANVAS_W//2, cy+280), "Менеджер подтвердит оплату — вы получите доступ к тикету",
           font=_font(16), fill=MUTED, anchor="mm")

    _footer(d, "Спасибо за покупку в Diamond Shop")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


def render_ticket(cart: dict, user_name: str, receipt_url: str) -> io.BytesIO:
    img, d = _canvas("тикет")
    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    d.text((PAD_X, body_y), "🧾 Новый заказ", font=_font(44), fill=TEXT)
    d.text((PAD_X, body_y+56), f"От: {user_name}", font=_font(16), fill=MUTED)
    _stripe(d, PAD_X, body_y+90, CANVAS_W-M-PAD_X, SILVER)

    # Товары
    list_y = body_y + 120
    for i, it in enumerate(cart["items"][:6]):
        ry = list_y + i*50
        d.text((PAD_X, ry), f"• {it['name']}", font=_font(22), fill=TEXT)
        total = math.ceil(it["price"]*it["qty"])
        d.text((PAD_X+700, ry), f"× {it['qty']} = {total} ₽",
               font=_font(20), fill=SILVER)

    # Итог
    total = math.ceil(sum(i["price"]*i["qty"] for i in cart["items"]))
    final = math.ceil(total - math.floor(total*cart["discount"]/100))

    sum_y = list_y + 400
    _grad(img, (PAD_X, sum_y, CANVAS_W-M-PAD_X, sum_y+120), GREY, GREY_DARK, alpha=30, radius=16)
    d.rounded_rectangle((PAD_X, sum_y, CANVAS_W-M-PAD_X, sum_y+120), radius=16,
                        outline=SILVER + (200,), width=2)
    d.text((PAD_X+30, sum_y+30), "ИТОГО:", font=_font(24), fill=SILVER)
    tf = _font(48)
    final_str = f"{final} ₽"
    tw = _tw(d, final_str, tf)
    d.text((CANVAS_W-M-PAD_X-30-tw, sum_y+30), final_str, font=tf, fill=TEXT)
    if cart["discount"] > 0:
        d.text((PAD_X+30, sum_y+80), f"Скидка: {cart['discount']}%",
               font=_font(16), fill=GREEN)

    _footer(d, "Одобрите оплату кнопкой ниже")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf

# ============================================================
# КАТАЛОГ
# ============================================================
CATALOG = {
    "discord": {"title": "Discord", "emoji": "<:Discord:1464831837300854936>", "items": [
        {"id": "d_n1", "name": "Discord Nitro 1 Month", "desc": "Полная подписка", "price": 460, "fixed": True},
        {"id": "d_n12", "name": "Discord Nitro 12 Month", "desc": "Годовая подписка", "price": 4410, "fixed": True},
        {"id": "d_nb", "name": "Nitro Basic", "desc": "Базовый на месяц", "price": 300, "fixed": True},
        {"id": "d_ng", "name": "Nitro Gift", "desc": "Подарочная подписка", "price": 790, "fixed": True},
        {"id": "d_b", "name": "Boosts", "desc": "Улучшение сервера", "price": 35, "fixed": False, "unit": "шт"},
    ]},
    "steam": {"title": "Steam", "emoji": "<:Steam:1464833200416100402>", "items": [
        {"id": "s_rub", "name": "Пополнение Steam", "desc": "Мин. 100 ₽", "price": 1.1, "fixed": False, "unit": "₽"},
        {"id": "s_reg", "name": "Смена региона", "desc": "Любой регион", "price": 250, "fixed": True},
    ]},
    "telegram": {"title": "Telegram", "emoji": "<:Telegram:1465720888677896314>", "items": [
        {"id": "t_star", "name": "Звёзды Telegram", "desc": "Валюта", "price": 1.58, "fixed": False, "unit": "шт"},
        {"id": "t_acc", "name": "Аккаунт Telegram", "desc": "Без спама", "price": 250, "fixed": True},
        {"id": "t_acc2", "name": "Аккаунт (спам-блок)", "desc": "С огранич.", "price": 190, "fixed": True},
        {"id": "t_prox", "name": "Прокси Telegram", "desc": "Рабочие", "price": 100, "fixed": True},
    ]},
    "roblox": {"title": "Roblox", "emoji": "<:Roblox:1465752155251150911>", "items": [
        {"id": "r_bux", "name": "Robux", "desc": "Валюта Roblox", "price": 0.82, "fixed": False, "unit": "шт"},
        {"id": "r_plus", "name": "Roblox Plus", "desc": "Подписка", "price": 90, "fixed": True},
    ]},
    "spotify": {"title": "Spotify", "emoji": "<:Spotify:1465770796411785330>", "items": [
        {"id": "sp_1", "name": "Spotify Individual", "desc": "На месяц", "price": 270, "fixed": True},
    ]},
    "bodesign": {"title": "Боты и Дизайн", "emoji": "<:Design:1465771436580012106>", "items": [
        {"id": "bd_bot", "name": "Разработка бота", "desc": "Индивидуально", "price": 500, "fixed": True},
        {"id": "bd_design", "name": "Дизайн сервера", "desc": "Под ключ", "price": 150, "fixed": True},
    ]},
    "decor": {"title": "Украшения", "emoji": "<:Decoration:1465729329290936403>", "items": [
        {"id": "dec_1", "name": "Украшение профиля", "desc": "Эффекты и рамки", "price": 200, "fixed": True},
        {"id": "dec_2", "name": "Наборы Discord", "desc": "Полный комплект", "price": 420, "fixed": True},
    ]},
}

PER_PAGE = 5
CARTS: Dict[int, dict] = {}

def _get_cart(uid: int) -> dict:
    if uid not in CARTS:
        CARTS[uid] = {
            "items": [], "discount": 0, "promo": "", "bank": "tbank",
            "category": None, "page": 1, "receipt": False,
            "created_at": time.time(), "msg": None,
        }
    return CARTS[uid]

def _reset_cart(uid: int):
    CARTS.pop(uid, None)

def _cart_total(cart: dict) -> int:
    return math.ceil(sum(i["price"]*i["qty"] for i in cart["items"]))

def _cart_final(cart: dict) -> int:
    total = _cart_total(cart)
    return math.ceil(total - math.floor(total*cart["discount"]/100))

# ============================================================
# VIEWS
# ============================================================
class AutoOrderOpenView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="Открыть Автозаказ",
        style=ButtonStyle.secondary,
        custom_id="autoorder:open",
        emoji=PartialEmoji(name="avtio1", id=1565386600219676702),
    )
    async def open_btn(self, button, inter):
        _reset_cart(inter.author.id)
        _get_cart(inter.author.id)
        try:
            buf = await asyncio.to_thread(render_categories)
            file = disnake.File(buf, filename="categories.png")
            embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://categories.png")
            await inter.response.send_message(
                embed=embed, file=file, view=CategoriesView(), ephemeral=True
            )
        except Exception as e:
            logger.exception(f"open_btn: {e}")
            await inter.response.send_message(f"❌ {e}", ephemeral=True)


class CategorySelect(Select):
    def __init__(self):
        opts = [SelectOption(label=c["title"], value=k,
                             emoji=PartialEmoji.from_str(c["emoji"]))
                for k, c in CATALOG.items()]
        super().__init__(placeholder="Выберите категорию...", min_values=1, max_values=1,
                         options=opts, custom_id="autoorder:cat")

    async def callback(self, inter):
        cart = _get_cart(inter.author.id)
        cart["category"] = self.values[0]
        cart["page"] = 1
        await _show_products(inter, self.values[0], 1)


class CategoriesView(View):
    def __init__(self):
        super().__init__(timeout=SESSION_TIMEOUT)
        self.add_item(CategorySelect())


async def _show_products(inter, cat_key, page):
    cat = CATALOG[cat_key]
    total = len(cat["items"])
    total_pages = (total + PER_PAGE - 1) // PER_PAGE
    page = max(1, min(page, total_pages))
    start = (page-1) * PER_PAGE
    items = cat["items"][start:start+PER_PAGE]

    buf = await asyncio.to_thread(render_products, cat["title"], items, page, total_pages)
    file = disnake.File(buf, filename="products.png")
    embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://products.png")

    try:
        await inter.response.edit_message(
            embed=embed, file=file, attachments=[], view=ProductsView(cat_key, page)
        )
    except disnake.InteractionResponded:
        await inter.edit_original_response(
            embed=embed, file=file, attachments=[], view=ProductsView(cat_key, page)
        )


class ProductSelect(Select):
    def __init__(self, cat_key, page):
        cat = CATALOG[cat_key]
        start = (page-1) * PER_PAGE
        items = cat["items"][start:start+PER_PAGE]
        opts = []
        for it in items:
            price = it["price"]
            unit = it.get("unit", "шт")
            price_str = f"{price} ₽" + ("" if it["fixed"] else f" / {unit}")
            opts.append(SelectOption(
                label=it["name"][:80],
                description=f"{price_str} · {it['desc']}"[:100],
                value=it["id"],
            ))
        super().__init__(placeholder=f"Товары · стр. {page}",
                         min_values=1, max_values=1, options=opts,
                         custom_id=f"autoorder:prod:{cat_key}:{page}")

    async def callback(self, inter):
        parts = self.custom_id.split(":")
        cat_key = parts[2]
        item_id = self.values[0]
        item = next((i for i in CATALOG[cat_key]["items"] if i["id"] == item_id), None)
        if not item:
            return await inter.response.send_message("❌ Не найден", ephemeral=True)

        cart = _get_cart(inter.author.id)
        if item["fixed"]:
            existing = next((i for i in cart["items"] if i["id"] == item_id), None)
            if existing:
                existing["qty"] += 1
            else:
                cart["items"].append({
                    "id": item_id, "name": item["name"], "price": item["price"],
                    "qty": 1, "unit": "шт",
                })
            await inter.response.send_message(f"✅ `{item['name']}` в корзине", ephemeral=True)
        else:
            await inter.response.send_modal(QtyModal(cat_key, item))


class QtyModal(Modal):
    def __init__(self, cat_key, item):
        self.cat_key = cat_key
        self.item = item
        super().__init__(
            title=f"Количество: {item['name'][:40]}",
            components=[TextInput(
                label=f"Сколько {item.get('unit','шт')}?",
                placeholder="Введите число",
                custom_id="qty", min_length=1, max_length=6,
            )],
        )

    async def callback(self, inter):
        try:
            qty = int(self.text_values["qty"])
            if qty <= 0: raise ValueError
        except Exception:
            return await inter.response.send_message("❌ Число > 0", ephemeral=True)

        cart = _get_cart(inter.author.id)
        existing = next((i for i in cart["items"] if i["id"] == self.item["id"]), None)
        if existing:
            existing["qty"] += qty
        else:
            cart["items"].append({
                "id": self.item["id"], "name": self.item["name"],
                "price": self.item["price"], "qty": qty,
                "unit": self.item.get("unit", "шт"),
            })
        await inter.response.send_message(
            f"✅ `{self.item['name']}` × {qty} добавлен", ephemeral=True
        )


class ProductsView(View):
    def __init__(self, cat_key, page):
        super().__init__(timeout=SESSION_TIMEOUT)
        self.cat_key = cat_key
        self.page = page
        self.add_item(ProductSelect(cat_key, page))

        total = len(CATALOG[cat_key]["items"])
        total_pages = (total + PER_PAGE - 1) // PER_PAGE

        if total_pages > 1:
            if page > 1:
                prev = Button(label="← Назад", style=ButtonStyle.secondary,
                              custom_id=f"autoorder:prev:{cat_key}:{page}")
                prev.callback = self._prev
                self.add_item(prev)
            if page < total_pages:
                nxt = Button(label="Далее →", style=ButtonStyle.secondary,
                             custom_id=f"autoorder:next:{cat_key}:{page}")
                nxt.callback = self._next
                self.add_item(nxt)

        back = Button(label="Категории", style=ButtonStyle.secondary,
                      custom_id="autoorder:back_cat")
        back.callback = self._back
        self.add_item(back)

        to_cart = Button(label="Корзина", style=ButtonStyle.secondary,
                         custom_id="autoorder:to_cart")
        to_cart.callback = self._to_cart
        self.add_item(to_cart)

    async def _prev(self, inter):
        await _show_products(inter, self.cat_key, self.page-1)

    async def _next(self, inter):
        await _show_products(inter, self.cat_key, self.page+1)

    async def _back(self, inter):
        buf = await asyncio.to_thread(render_categories)
        file = disnake.File(buf, filename="categories.png")
        embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://categories.png")
        await inter.response.edit_message(
            embed=embed, file=file, attachments=[], view=CategoriesView()
        )

    async def _to_cart(self, inter):
        cart = _get_cart(inter.author.id)
        if not cart["items"]:
            return await inter.response.send_message("❌ Корзина пуста", ephemeral=True)
        buf = await asyncio.to_thread(render_cart, cart)
        file = disnake.File(buf, filename="cart.png")
        embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://cart.png")
        await inter.response.edit_message(
            embed=embed, file=file, attachments=[], view=CartView()
        )


class CartView(View):
    def __init__(self):
        super().__init__(timeout=SESSION_TIMEOUT)

        back = Button(label="Добавить ещё", style=ButtonStyle.secondary,
                      custom_id="autoorder:add_more")
        back.callback = self._add_more
        self.add_item(back)

        clear = Button(label="Очистить", style=ButtonStyle.secondary,
                       custom_id="autoorder:clear")
        clear.callback = self._clear
        self.add_item(clear)

        checkout = Button(label="Оформить заказ", style=ButtonStyle.secondary,
                          custom_id="autoorder:checkout")
        checkout.callback = self._checkout
        self.add_item(checkout)

    async def _add_more(self, inter):
        buf = await asyncio.to_thread(render_categories)
        file = disnake.File(buf, filename="categories.png")
        embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://categories.png")
        await inter.response.edit_message(
            embed=embed, file=file, attachments=[], view=CategoriesView()
        )

    async def _clear(self, inter):
        _reset_cart(inter.author.id)
        _get_cart(inter.author.id)
        buf = await asyncio.to_thread(render_categories)
        file = disnake.File(buf, filename="categories.png")
        embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://categories.png")
        await inter.response.edit_message(
            embed=embed, file=file, attachments=[], view=CategoriesView()
        )

    async def _checkout(self, inter):
        cart = _get_cart(inter.author.id)
        if not cart["items"]:
            return await inter.response.send_message("❌ Корзина пуста", ephemeral=True)
        buf = await asyncio.to_thread(render_checkout, cart)
        file = disnake.File(buf, filename="checkout.png")
        embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://checkout.png")
        await inter.response.edit_message(
            embed=embed, file=file, attachments=[], view=CheckoutView()
        )


class CheckoutView(View):
    def __init__(self):
        super().__init__(timeout=SESSION_TIMEOUT)

        promo = Button(label="Промокод", style=ButtonStyle.secondary,
                       custom_id="autoorder:promo")
        promo.callback = self._promo
        self.add_item(promo)

        disc = Button(label="Скидка 10% из инвентаря", style=ButtonStyle.secondary,
                      custom_id="autoorder:disc10")
        disc.callback = self._disc10
        self.add_item(disc)

        bank = Button(label="Сменить банк", style=ButtonStyle.secondary,
                      custom_id="autoorder:bank")
        bank.callback = self._bank
        self.add_item(bank)

        paid = Button(label="Я оплатил", style=ButtonStyle.secondary,
                      custom_id="autoorder:paid")
        paid.callback = self._paid
        self.add_item(paid)

    async def _promo(self, inter):
        cart = _get_cart(inter.author.id)
        if cart["discount"] > 0:
            return await inter.response.send_message("❌ Скидка уже применена", ephemeral=True)
        await inter.response.send_modal(PromoModal())

    async def _disc10(self, inter):
        cart = _get_cart(inter.author.id)
        if cart["discount"] > 0:
            return await inter.response.send_message("❌ Скидка уже применена", ephemeral=True)
        cart["discount"] = 10
        buf = await asyncio.to_thread(render_checkout, cart)
        file = disnake.File(buf, filename="checkout.png")
        embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://checkout.png")
        await inter.response.edit_message(
            embed=embed, file=file, attachments=[], view=CheckoutView()
        )

    async def _bank(self, inter):
        cart = _get_cart(inter.author.id)
        banks = ["tbank", "sbp", "ozon"]
        cart["bank"] = banks[(banks.index(cart["bank"]) + 1) % 3]
        buf = await asyncio.to_thread(render_checkout, cart)
        file = disnake.File(buf, filename="checkout.png")
        embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://checkout.png")
        await inter.response.edit_message(
            embed=embed, file=file, attachments=[], view=CheckoutView()
        )

    async def _paid(self, inter):
        buf = await asyncio.to_thread(render_receipt)
        file = disnake.File(buf, filename="receipt.png")
        embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://receipt.png")
        await inter.response.edit_message(
            embed=embed, file=file, attachments=[], view=None
        )


class PromoModal(Modal):
    def __init__(self):
        super().__init__(
            title="Ввод промокода",
            components=[TextInput(
                label="Промокод", placeholder="Например: DIAMOND15",
                custom_id="promo", min_length=1, max_length=32,
            )],
        )

    async def callback(self, inter):
        code = self.text_values["promo"].strip().upper()
        cart = _get_cart(inter.author.id)
        if code == "DIAMOND15":
            cart["discount"] = 15
            cart["promo"] = code
            buf = await asyncio.to_thread(render_checkout, cart)
            file = disnake.File(buf, filename="checkout.png")
            embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://checkout.png")
            await inter.response.edit_message(
                embed=embed, file=file, attachments=[], view=CheckoutView()
            )
        else:
            await inter.response.send_message("❌ Промокод не найден", ephemeral=True)


# ============================================================
# ФИНАЛИЗАЦИЯ ЗАКАЗА
# ============================================================
async def finalize_order(bot, user, cart, receipt_url):
    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        logger.warning("[autoorder] гильдия не найдена")
        return

    cat = guild.get_channel(AUTOORDER_TICKET_CATEGORY)
    if not cat:
        logger.warning(f"[autoorder] категория {AUTOORDER_TICKET_CATEGORY} не найдена")
        return

    raw = user.display_name.lower().replace(" ", "-")
    raw = "".join(c for c in raw if c.isalnum() or c in "-_")[:80] or f"auto-{user.id}"

    overwrites = {
        guild.default_role: disnake.PermissionOverwrite(view_channel=False),
        user: disnake.PermissionOverwrite(view_channel=False),
    }
    for rid in CONFIG.get("TICKET_MANAGE_ROLES", []):
        role = guild.get_role(rid)
        if role:
            overwrites[role] = disnake.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

    try:
        ticket = await cat.create_text_channel(name=raw, overwrites=overwrites)
        logger.info(f"[autoorder] тикет создан: {ticket.name}")
    except Exception as e:
        logger.exception(f"[autoorder] create_ticket: {e}")
        return

    # Pillow-карточка заказа
    try:
        buf = await asyncio.to_thread(render_ticket, cart, user.display_name, receipt_url)
        file = disnake.File(buf, filename="order.png")
        embed = disnake.Embed(
            title=f"🧾 Новый заказ — {user.mention}",
            description=(
                f"> **Пользователь:** {user.mention} (`{user.id}`)\n"
                f"> **Банк:** `{cart['bank'].upper()}`\n"
                f"> **Чек:** [открыть]({receipt_url})"
            ),
            color=COLOR_GREY,
        ).set_image(url="attachment://order.png")
    except Exception as e:
        logger.exception(f"[autoorder] render_ticket: {e}")
        file = None
        embed = disnake.Embed(title="🧾 Новый заказ", color=COLOR_GREY)

    view = View(timeout=None)
    approve = Button(label="✅ Одобрить оплату", style=ButtonStyle.success,
                     custom_id="autoorder:approve")
    reject = Button(label="❌ Отклонить", style=ButtonStyle.danger,
                    custom_id="autoorder:reject")

    async def on_approve(inter2):
        await inter2.response.defer(ephemeral=True)
        try:
            await ticket.set_permissions(user, view_channel=True, send_messages=True,
                                          read_message_history=True)
            add_ticket_owner(ticket.id, user.id, cat.id)
        except Exception as e:
            logger.warning(f"approve perms: {e}")

        await ticket.send(f"> ✅ {user.mention}, оплата подтверждена! Менеджер приступит к заказу.")
        await inter2.followup.send("✅ Оплата одобрена", ephemeral=True)

        try:
            await user.send(f"✅ **Оплата подтверждена**\n> Заказ на **{_cart_final(cart)} ₽** принят.\n> Тикет: {ticket.mention}")
        except Exception:
            pass

        approve.disabled = True
        reject.disabled = True
        try:
            await inter2.message.edit(view=view)
        except Exception:
            pass

    async def on_reject(inter2):
        await inter2.response.send_message("❌ Отклонено", ephemeral=True)
        try:
            await user.send("❌ **Заказ отклонён**\n> Чек не подтверждён. Свяжитесь с менеджером.")
        except Exception:
            pass
        try:
            await ticket.delete()
        except Exception:
            pass

    approve.callback = on_approve
    reject.callback = on_reject
    view.add_item(approve)
    view.add_item(reject)

    kwargs = {"embed": embed, "view": view}
    if file:
        kwargs["file"] = file
    await ticket.send(**kwargs)

    await log_discord(
        title="🧾 Автозаказ — создан",
        description=(
            f"> **Юзер:** {user.mention}\n"
            f"> **Сумма:** `{_cart_final(cart)} ₽`\n"
            f"> **Тикет:** {ticket.mention}"
        ),
        color=COLOR_GREY,
        channel_id=LOG_CHANNEL_ID,
    )

    try:
        await user.send(
            f"✅ **Заказ оформлен**\n"
            f"> Сумма: **{_cart_final(cart)} ₽**\n"
            f"> Ожидайте подтверждения оплаты."
        )
    except Exception:
        pass


# ============================================================
# ЛОВИМ ЧЕК
# ============================================================
async def _handle_receipt(bot, message):
    if message.author.bot: return
    if message.channel.id != AUTOORDER_CHANNEL_ID: return
    if not message.attachments: return

    cart = CARTS.get(message.author.id)
    if not cart or not cart["items"]: return
    if cart.get("receipt"): return

    att = message.attachments[0]
    name_low = att.filename.lower()
    if not any(name_low.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".pdf")):
        return

    cart["receipt"] = True
    logger.info(f"[autoorder] получен чек от {message.author.id}")

    try:
        await finalize_order(bot, message.author, cart, att.url)
    except Exception as e:
        logger.exception(f"[autoorder] finalize: {e}")

    try:
        await message.delete()
    except Exception:
        pass

    _reset_cart(message.author.id)


# ============================================================
# ОТПРАВКА ПАНЕЛИ
# ============================================================
async def send_autoorder_panel(bot):
    await bot.wait_until_ready()
    await asyncio.sleep(5)

    ch = bot.get_channel(AUTOORDER_CHANNEL_ID)
    if not ch:
        try:
            ch = await bot.fetch_channel(AUTOORDER_CHANNEL_ID)
        except Exception as e:
            logger.warning(f"[autoorder] канал {AUTOORDER_CHANNEL_ID} не найден: {e}")
            return

    try:
        async for m in ch.history(limit=20):
            if m.author == bot.user:
                try: await m.delete()
                except Exception: pass
    except Exception:
        pass

    try:
        buf = await asyncio.to_thread(render_panel)
        file = disnake.File(buf, filename="panel.png")
        embed = disnake.Embed(color=COLOR_GREY).set_image(url="attachment://panel.png")
        await ch.send(embed=embed, file=file, view=AutoOrderOpenView())
        logger.info("[autoorder] ✅ панель отправлена")
    except Exception as e:
        logger.exception(f"[autoorder] send_panel: {e}")


# ============================================================
# SETUP
# ============================================================
def setup_autoorder(bot):
    try:
        bot.add_view(AutoOrderOpenView())
        bot.loop.create_task(send_autoorder_panel(bot))

        @bot.listen("on_message")
        async def _on_message(message):
            await _handle_receipt(bot, message)

        logger.info("[autoorder] ✅ модуль подключён")
    except Exception as e:
        logger.exception(f"[autoorder] setup: {e}")
