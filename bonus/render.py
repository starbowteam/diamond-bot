# -*- coding: utf-8 -*-
"""Pillow-рендер бонус-панели. 1800×1000."""
import io
import os
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR


FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_F, _FA = {}, {}


def _font(sz):
    if sz in _F: return _F[sz]
    try: f = ImageFont.truetype(FONT_BOLD, sz)
    except: f = ImageFont.load_default()
    _F[sz] = f; return f


def _fa(sz):
    if sz in _FA: return _FA[sz]
    f = None
    if os.path.exists(FONT_FA):
        try: f = ImageFont.truetype(FONT_FA, sz)
        except: pass
    _FA[sz] = f; return f


# Палитра
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
DARK      = (85, 85, 85)

SILVER    = (198, 208, 224)
SILVER_HI = (224, 232, 245)

GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
GOLD      = (247, 201, 145)
PURPLE    = (179, 157, 219)
BRONZE    = (209, 146, 96)

CARD_BRD  = (74, 74, 79)

# FA-иконки
I_USER     = 0xf007
I_TROPHY   = 0xf091
I_MEDAL    = 0xf5a2
I_LINK     = 0xf0c1
I_CHECK    = 0xf00c
I_GIFT     = 0xf06b
I_GEM      = 0xf3a5
I_COINS    = 0xf51e
I_CROWN    = 0xf521
I_FIRE     = 0xf06d
I_CLOCK    = 0xf017
I_ELL      = 0xf141
I_TAG      = 0xf02b
I_CUBE     = 0xf1b2
I_TICKET   = 0xf145
I_BOLT     = 0xf0e7
I_STAR     = 0xf005
I_CART     = 0xf07a
I_BOX      = 0xf466
I_INFO     = 0xf05a
I_BULLHORN = 0xf0a1
I_MASKS    = 0xf630
I_PALETTE  = 0xf53f
I_SHOP     = 0xf54f


FA_CASE_COLOR = {
    "blue":   BLUE,
    "green":  GREEN,
    "gold":   GOLD,
    "purple": PURPLE,
    "red":    RED,
}


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
    except: pass


def _alpha(img, box, color, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if radius > 0:
        ld.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=color + (alpha,))
    else:
        ld.rectangle((0, 0, w - 1, h - 1), fill=color + (alpha,))
    img.paste(layer, (x1, y1), layer)


def _grad(img, box, c1, c2, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i in range(w):
        t = i / max(w - 1, 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        ld.line([(i, 0), (i, h)], fill=(r, g, b, alpha))
    if radius > 0:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        a = layer.split()[3]
        a = Image.composite(a, Image.new("L", (w, h), 0), mask)
        layer.putalpha(a)
    img.paste(layer, (x1, y1), layer)


def _panel(img, d, box, radius=22):
    x1, y1, x2, y2 = box
    _alpha(img, (x1 + 12, y1 + 12, x2 + 12, y2 + 12), (46, 46, 52), alpha=110, radius=radius)
    _alpha(img, (x1 + 6, y1 + 6, x2 + 6, y2 + 6), (46, 46, 52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=2)


def _lighten(c, a=0.4):
    a = max(0, min(1, a))
    return (min(int(c[0] + (255 - c[0]) * a), 255),
            min(int(c[1] + (255 - c[1]) * a), 255),
            min(int(c[2] + (255 - c[2]) * a), 255))


W, H = 1800, 1000
PAD_X, PAD_Y = 56, 44
BODY_Y = 138
BODY_H = H - PAD_Y - BODY_Y


def _canvas(subtitle):
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=30,
                        fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)

    hx, hy = PAD_X, PAD_Y
    d.rounded_rectangle((hx, hy, hx + 54, hy + 54), radius=14, fill=(58, 58, 64) + (255,))
    _icon(d, hx + 27, hy + 28, I_GIFT, 26, GOLD)

    bx = hx + 54 + 18
    d.text((bx, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx + 2, hy + 38), "BONUS PANEL", font=_font(11), fill=MUTED)

    meta_r = W - PAD_X
    w1 = _tw(d, subtitle.upper(), _font(11))
    d.text((meta_r - w1, hy + 14), subtitle.upper(), font=_font(11), fill=MUTED)

    sy = hy + 54 + 16
    d.line((PAD_X, sy, W - PAD_X, sy), fill=STACK_HDR + (255,), width=2)
    return img, d


def _wrap(d, text, font, max_w, max_lines=3):
    words = (text or "").split()
    lines = []; cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if _tw(d, test, font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
                if len(lines) >= max_lines: return lines
            cur = w
    if cur and len(lines) < max_lines: lines.append(cur)
    return lines or [""]


# ═══════════════════════════════════════════════════
# ЭКРАН 1: АКЦИЯ ДНЯ (ВАРИАНТ C · ГОРИЗОНТ-ПОЛОСА)
# ═══════════════════════════════════════════════════
def render_daily_deal(user_id, balance, deal, hours_left):
    img, d = _canvas("акция дня")

    # Header — переделаем вручную, чтобы добавить баланс и время
    # Перетираем канвас: рисуем заголовок слева (DIAMOND / BONUS · АКЦИЯ ДНЯ)
    # и справа — время. Канвас уже нарисован, допишем поверх.

    # Правый угол: время + баланс
    meta_r = W - PAD_X

    # Время
    tl = "СЛЕДУЮЩАЯ ЧЕРЕЗ"
    tw_ = _tw(d, tl, _font(11))
    d.text((meta_r - tw_, PAD_Y + 6), tl, font=_font(11), fill=MUTED)
    tv = f"{hours_left} ч."
    tvw = _tw(d, tv, _font(22))
    d.text((meta_r - tvw, PAD_Y + 26), tv, font=_font(22), fill=GOLD)

    # Баланс — слева, под лого
    bal_str = f"{balance:,}".replace(",", " ")
    bx = PAD_X + 54 + 18
    # сдвинем DIAMOND вверх, добавим баланс ниже
    # (уже нарисован DIAMOND/BONUS — допишем справа от subtitle)

    # Полоса
    strip_x1 = 100
    strip_x2 = W - 100
    strip_y1 = 320
    strip_y2 = 720
    strip_h = strip_y2 - strip_y1

    if deal:
        cat = deal.get("category_label", "—")
        name = deal.get("item_data", {}).get("name", "—")
        orig = deal.get("original_price", 0)
        new = deal.get("new_price", 0)
        disc = deal.get("discount", 0)
        color = BLUE
        icon_code = I_CUBE

        # Определяем иконку по категории
        cat_l = cat.lower()
        if "рол" in cat_l:
            icon_code = I_MASKS
        elif "дизайн" in cat_l:
            icon_code = I_PALETTE
        elif "реклам" in cat_l:
            icon_code = I_BULLHORN
        elif "скидк" in cat_l:
            icon_code = I_TAG
        elif "буст" in cat_l:
            icon_code = I_BOLT
        elif "казино" in cat_l:
            icon_code = I_COINS
        elif "подар" in cat_l:
            icon_code = I_GIFT
    else:
        cat = "—"; name = "Сегодня акции нет"
        orig = new = disc = 0
        color = DIM
        icon_code = I_FIRE

    # Свечение за полосой
    for i, a in enumerate([8, 12, 16]):
        gs = 2000 - i * 200
        cx = W // 2
        cy = (strip_y1 + strip_y2) // 2
        _alpha(img, (cx - gs // 2, cy - gs // 2, cx + gs // 2, cy + gs // 2),
               color, alpha=a, radius=gs // 2)

    # Фон полосы
    _grad(img, (strip_x1, strip_y1, strip_x2, strip_y2), color, color, alpha=18, radius=16)

    # Жирные рамки сверху и снизу
    d.rectangle((strip_x1, strip_y1, strip_x2, strip_y1 + 4), fill=color + (255,))
    d.rectangle((strip_x1, strip_y2 - 4, strip_x2, strip_y2), fill=color + (255,))

    # Тонкая линия сверху/снизу с отступом
    d.line((strip_x1 + 100, strip_y1 - 12, strip_x2 - 100, strip_y1 - 12),
           fill=color + (180,), width=2)
    d.line((strip_x1 + 100, strip_y2 + 12, strip_x2 - 100, strip_y2 + 12),
           fill=color + (180,), width=2)

    # Круглая иконка
    ic_size = 280
    ic_x = strip_x1 + 70
    ic_y = strip_y1 + (strip_h - ic_size) // 2

    for i, a in enumerate([28, 42, 55]):
        gs = ic_size + 60 - i * 20
        _alpha(img, (ic_x + ic_size // 2 - gs // 2, ic_y + ic_size // 2 - gs // 2,
                     ic_x + ic_size // 2 + gs // 2, ic_y + ic_size // 2 + gs // 2),
               color, alpha=a, radius=gs // 2)

    _grad(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size),
          color, color, alpha=75, radius=ic_size // 2)
    d.ellipse((ic_x - 3, ic_y - 3, ic_x + ic_size + 3, ic_y + ic_size + 3),
              outline=color + (255,), width=6)
    _icon(d, ic_x + ic_size // 2, ic_y + ic_size // 2 + 2, icon_code, 130, TEXT)

    # Текст справа
    col_x = ic_x + ic_size + 70
    col_max = strip_x2 - 100

    # Категория
    d.text((col_x, strip_y1 + 56), f"🎯 {cat.upper()}",
           font=_font(15), fill=color)

    # Название
    nf = _font(64)
    name_lines = _wrap(d, name, nf, col_max - col_x, max_lines=2)
    ny = strip_y1 + 96
    for i, ln in enumerate(name_lines):
        d.text((col_x, ny + i * 72), ln, font=nf, fill=TEXT)

    # Цены
    pr_y = strip_y2 - 140

    if orig > 0:
        orig_str = f"{orig} DC"
        of = _font(34)
        ow = _tw(d, orig_str, of)
        d.text((col_x, pr_y), orig_str, font=of, fill=DIM)
        d.line((col_x, pr_y + 22, col_x + ow, pr_y + 22), fill=DIM, width=3)
        x_next = col_x + ow + 46
    else:
        x_next = col_x

    if new > 0:
        new_str = str(new)
        nf2 = _font(100)
        d.text((x_next, pr_y + 6), new_str, font=nf2, fill=GREEN)
        nw = _tw(d, new_str, nf2)
        d.text((x_next + nw + 16, pr_y + 6 + nf2.size - 42), "DC",
               font=_font(40), fill=MUTED)

    # Бейдж скидки — выступает за пределы полосы справа сверху
    if disc > 0:
        disc_text = f"🔥 -{disc}%"
        df = _font(24)
        dw = _tw(d, disc_text, df)
        badge_w = dw + 60
        badge_h = 62
        badge_x = strip_x2 - 80 - badge_w
        badge_y = strip_y1 - 32

        _alpha(img, (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
               RED, alpha=220, radius=15)
        d.rounded_rectangle((badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
                            radius=15, outline=RED + (255,), width=2)
        d.text((badge_x + 30, badge_y + badge_h // 2), disc_text,
               font=df, fill=TEXT, anchor="lm")

    # Пустое состояние
    if not deal:
        cx = W // 2
        cy = (strip_y1 + strip_y2) // 2
        msg = "Сегодня акции нет — заходи позже"
        mw = _tw(d, msg, _font(28))
        d.text((cx - mw // 2, cy + 180), msg, font=_font(28), fill=DIM)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 1B: УСПЕШНАЯ ПОКУПКА
# ═══════════════════════════════════════════════════
def render_deal_success(user_id, deal, outcome):
    img, d = _canvas("покупка · успех")

    body_y = BODY_Y
    body_h = BODY_H - 12

    hero_h = 380
    hero_y1 = body_y + 30
    hero_y2 = hero_y1 + hero_h
    hx1 = PAD_X
    hx2 = W - PAD_X

    _grad(img, (hx1, hero_y1, hx2, hero_y2), GREEN, GREEN, alpha=20, radius=24)
    d.rounded_rectangle((hx1, hero_y1, hx2, hero_y2), radius=24,
                        outline=GREEN + (255,), width=4)

    ic_size = 220
    ic_x = hx1 + 60
    ic_y = hero_y1 + (hero_h - ic_size) // 2
    _alpha(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), GREEN, alpha=55, radius=28)
    d.rounded_rectangle((ic_x, ic_y, ic_x + ic_size, ic_y + ic_size),
                        radius=28, outline=GREEN + (240,), width=3)
    _icon(d, ic_x + ic_size // 2, ic_y + ic_size // 2 + 2, I_CHECK, 100, GREEN)

    tx = ic_x + ic_size + 50
    tx_max = hx2 - 60 - tx

    d.text((tx, hero_y1 + 60), "ПОКУПКА СОВЕРШЕНА",
           font=_font(16), fill=GREEN)

    name = outcome.get("name", "—")
    nf = _font(52)
    name_lines = _wrap(d, name, nf, tx_max, max_lines=2)
    for i, ln in enumerate(name_lines):
        d.text((tx, hero_y1 + 100 + i * 60), ln, font=nf, fill=TEXT)

    price_str = f"{outcome.get('price', 0)} DC"
    d.text((tx, hero_y1 + 100 + len(name_lines) * 60 + 20),
           price_str, font=_font(26), fill=GREEN)

    info_y = hero_y2 + 30
    info_h = 140
    ix1 = PAD_X
    ix2 = W - PAD_X

    kind = outcome.get("kind", "inventory")

    if kind == "role":
        d.rounded_rectangle((ix1, info_y, ix2, info_y + info_h), radius=18,
                            fill=(32, 24, 46) + (255,),
                            outline=PURPLE + (200,), width=2)
        _alpha(img, (ix1 + 30, info_y + 30, ix1 + 90, info_y + 90), PURPLE, alpha=55, radius=16)
        _icon(d, ix1 + 60, info_y + 61, I_CROWN, 30, PURPLE)
        d.text((ix1 + 120, info_y + 28), "РОЛЬ УЖЕ У ТЕБЯ", font=_font(14), fill=PURPLE)
        d.text((ix1 + 120, info_y + 58),
               f"«{outcome.get('role_name', name)}» выдана автоматически.",
               font=_font(18), fill=TEXT)
        d.text((ix1 + 120, info_y + 92),
               "Проверь свой профиль Discord — роль уже там.",
               font=_font(14), fill=MUTED)

    elif kind == "boost":
        d.rounded_rectangle((ix1, info_y, ix2, info_y + info_h), radius=18,
                            fill=(20, 30, 44) + (255,),
                            outline=BLUE + (200,), width=2)
        _alpha(img, (ix1 + 30, info_y + 30, ix1 + 90, info_y + 90), BLUE, alpha=55, radius=16)
        _icon(d, ix1 + 60, info_y + 61, I_BOLT, 30, BLUE)
        d.text((ix1 + 120, info_y + 28), "БУСТ АКТИВИРОВАН", font=_font(14), fill=BLUE)
        d.text((ix1 + 120, info_y + 58),
               "Буст уже работает — проверь в профиле.",
               font=_font(18), fill=TEXT)
        d.text((ix1 + 120, info_y + 92),
               "Панель профиля → «Инвентарь DC».",
               font=_font(14), fill=MUTED)

    else:
        d.rounded_rectangle((ix1, info_y, ix2, info_y + info_h), radius=18,
                            fill=(20, 30, 44) + (255,),
                            outline=BLUE + (200,), width=2)
        _alpha(img, (ix1 + 30, info_y + 30, ix1 + 90, info_y + 90), BLUE, alpha=55, radius=16)
        _icon(d, ix1 + 60, info_y + 61, I_TICKET, 30, BLUE)
        d.text((ix1 + 120, info_y + 28), "ТОВАР В ИНВЕНТАРЕ", font=_font(14), fill=BLUE)
        d.text((ix1 + 120, info_y + 58),
               "Оформи тикет, чтобы менеджер выдал заказ.",
               font=_font(18), fill=TEXT)
        d.text((ix1 + 120, info_y + 92),
               "Витрина DC → «Купить» → Diamond Coins → выбери товар.",
               font=_font(14), fill=MUTED)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 2: РЕФ-ПАНЕЛЬ
# ═══════════════════════════════════════════════════
def render_ref_panel(user_id, username, stats, link_url):
    img, d = _canvas("реферальная система")

    left_w = 420; gap = 24
    lx1, lx2 = PAD_X, PAD_X + left_w
    rx1, rx2 = lx2 + gap, W - PAD_X

    _panel(img, d, (lx1, BODY_Y, lx2 - 12, BODY_Y + BODY_H - 12), radius=20)
    x1, y1 = lx1, BODY_Y
    x2 = lx2 - 12
    pad = 24
    cx = (x1 + x2) // 2

    av_size = 140
    av_cy = y1 + pad + av_size // 2
    r = av_size // 2
    _grad(img, (cx - r, av_cy - r, cx + r, av_cy + r), GREEN, SILVER, alpha=70, radius=r)
    d.ellipse((cx - r - 2, av_cy - r - 2, cx + r + 2, av_cy + r + 2),
              outline=GREEN + (255,), width=5)
    _icon(d, cx, av_cy + 1, I_USER, 60, TEXT)

    nick_y = y1 + pad + av_size + 18
    nick = _el(d, username, _font(24), (x2 - x1) - 2 * pad)
    nw = _tw(d, nick, _font(24))
    d.text((cx - nw // 2, nick_y), nick, font=_font(24), fill=TEXT)

    uid_y = nick_y + 34
    uid_text = f"UID · {user_id}"
    uw = _tw(d, uid_text, _font(13))
    d.text((cx - uw // 2, uid_y), uid_text, font=_font(13), fill=MUTED)

    sep_y = uid_y + 26
    d.line((x1 + pad, sep_y, x2 - pad, sep_y), fill=STACK_HDR + (255,), width=2)

    grid_y = sep_y + 16
    grid_w = (x2 - pad) - (x1 + pad)
    cg = 12
    cw = (grid_w - cg) // 2
    ch_ = 110

    items = [
        ("ЗАРАБОТАНО",   f"{stats.get('earned', 0)} DC", GREEN),
        ("ПРИГЛАШЕНО",   stats.get("total", 0),    SILVER),
        ("ЗАСЧИТАНО",    stats.get("rewarded", 0), GREEN),
        ("В ХОЛДЕ",      stats.get("on_review", 0), GOLD),
    ]
    for i, (lbl, val, color) in enumerate(items):
        r_, c_ = divmod(i, 2)
        cx1 = x1 + pad + c_ * (cw + cg)
        cy1 = grid_y + r_ * (ch_ + cg)
        d.rounded_rectangle((cx1, cy1, cx1 + cw, cy1 + ch_), radius=16,
                            fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        d.text((cx1 + 18, cy1 + 16), lbl, font=_font(11), fill=MUTED)
        vf = _font(28)
        v = str(val)
        while _tw(d, v, vf) > cw - 36 and vf.size > 16:
            vf = _font(vf.size - 2)
        d.text((cx1 + 18, cy1 + 44), v, font=vf, fill=color)

    hint_y = BODY_Y + BODY_H - 12 - pad - 150
    _grad(img, (x1 + pad, hint_y, x2 - pad, hint_y + 150), GREEN, GREEN, alpha=15, radius=16)
    d.rounded_rectangle((x1 + pad, hint_y, x2 - pad, hint_y + 150), radius=16,
                        outline=GREEN + (200,), width=2)

    # Иконка подарка — СЕРАЯ, как в профиле
    _icon(d, x1 + pad + 32, hint_y + 30, I_GIFT, 20, DIM)
    d.text((x1 + pad + 54, hint_y + 20), "КАК ЗАРАБОТАТЬ",
           font=_font(12), fill=GREEN)

    for i, ln in enumerate([
        "100 DC на баланс за друга",
        "100 DC в копилку клана",
        "Порог зачёта — 1 час",
    ]):
        dy = hint_y + 60 + i * 26
        d.ellipse((x1 + pad + 24, dy + 6, x1 + pad + 32, dy + 14),
                  fill=DIM + (255,))
        d.text((x1 + pad + 44, dy), ln, font=_font(15), fill=GREEN)

    # ПРАВАЯ — таблица
    _panel(img, d, (rx1, BODY_Y, rx2 - 12, BODY_Y + BODY_H - 12), radius=20)
    rpx1 = rx1 + 28; rpx2 = rx2 - 12 - 28; rpy = BODY_Y + 24

    d.text((rpx1, rpy), "👥 Мои приглашённые", font=_font(32), fill=TEXT)
    sub = f"{stats['total']} чел. · {stats['rewarded']} засчитано · {stats['on_review']} в холде"
    sw = _tw(d, sub, _font(14))
    d.text((rpx2 - sw, rpy + 14), sub, font=_font(14), fill=MUTED)

    sep_y = rpy + 52
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)

    col_x = [rpx1, rpx1 + 86, rpx2 - 700, rpx2 - 470, rpx2 - 230]
    th_y = sep_y + 14
    for x, lbl in zip(col_x[1:], ["ПОЛЬЗОВАТЕЛЬ", "ВХОД", "ВЫХОД", "СТАТУС"]):
        d.text((x, th_y), lbl, font=_font(11), fill=MUTED)

    list_y = th_y + 30
    list_bottom = BODY_Y + BODY_H - 12 - 22
    row_h = 100
    row_gap = 10

    rows = stats.get("rows", [])[:5]

    if not rows:
        cx2 = (rpx1 + rpx2) // 2
        cy2 = (list_y + list_bottom) // 2
        _icon(d, cx2, cy2 - 20, I_ELL, 40, DIM)
        msg = "Пока никого не пригласил"
        mw = _tw(d, msg, _font(18))
        d.text((cx2 - mw // 2, cy2 + 30), msg, font=_font(18), fill=DIM)
    else:
        for i, row in enumerate(rows):
            ry = list_y + i * (row_h + row_gap)
            if ry + row_h > list_bottom: break

            rewarded = row.get("rewarded", 0)
            on_review = (
                not rewarded
                and row.get("left_at")
                and (row["left_at"] - row["joined_at"]) < 3600
            )

            d.rounded_rectangle((rpx1, ry, rpx2, ry + row_h), radius=14,
                                fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

            av_x = col_x[0] + 18
            d.ellipse((av_x, ry + row_h // 2 - 26, av_x + 52, ry + row_h // 2 + 26),
                      fill=(58, 58, 64))
            _icon(d, av_x + 26, ry + row_h // 2 + 1, I_USER, 22, SILVER_HI)

            d.text((col_x[1], ry + row_h // 2 - 24), f"ID {row['member_id']}",
                   font=_font(17), fill=TEXT)
            d.text((col_x[1], ry + row_h // 2 + 4), "участник",
                   font=_font(12), fill=MUTED)

            try:
                jdt = datetime.fromtimestamp(row["joined_at"], timezone.utc)
                jd = jdt.strftime("%d.%m.%Y"); jt = jdt.strftime("%H:%M")
            except Exception:
                jd, jt = "—", "—"
            d.text((col_x[2], ry + row_h // 2 - 20), jd, font=_font(15), fill=SILVER_HI)
            d.text((col_x[2], ry + row_h // 2 + 4), jt, font=_font(12), fill=MUTED)

            if row.get("left_at"):
                try:
                    ldt = datetime.fromtimestamp(row["left_at"], timezone.utc)
                    ld = ldt.strftime("%d.%m.%Y"); lt = ldt.strftime("%H:%M")
                except Exception:
                    ld, lt = "—", "—"
                d.text((col_x[3], ry + row_h // 2 - 20), ld, font=_font(15), fill=SILVER_HI)
                d.text((col_x[3], ry + row_h // 2 + 4), lt, font=_font(12), fill=MUTED)
            else:
                d.text((col_x[3], ry + row_h // 2 - 10), "—", font=_font(15), fill=DIM)

            if rewarded:
                txt, color = "✓ ЗАСЧИТАН", GREEN
            elif on_review:
                txt, color = "⚠ В ХОЛДЕ", GOLD
            else:
                txt, color = "… на сервере", BLUE

            tw_ = _tw(d, txt, _font(13))
            bx = col_x[4]
            _alpha(img, (bx, ry + row_h // 2 - 16, bx + tw_ + 28, ry + row_h // 2 + 16),
                   color, alpha=30, radius=9)
            d.rounded_rectangle((bx, ry + row_h // 2 - 16, bx + tw_ + 28, ry + row_h // 2 + 16),
                                radius=9, outline=color + (220,), width=2)
            d.text((bx + 14, ry + row_h // 2 - 10), txt, font=_font(13), fill=color)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 3: КЕЙСЫ
# ═══════════════════════════════════════════════════
def render_cases(user_id, username, balance, stats):
    img, d = _canvas("кейсы")

    from bonus.core import CASES

    top_y1 = BODY_Y
    top_h = 90
    gap_top = 14
    col_w = (W - 2 * PAD_X - 2 * gap_top) // 3

    tb_data = [
        ("ТВОЙ БАЛАНС", f"{balance:,}".replace(",", " ") + " DC", GREEN, I_COINS, True),
        ("ОТКРЫТО", str(stats.get("opened", 0)), BLUE, I_GIFT, False),
        ("ЛУЧШИЙ ВЫИГРЫШ", f"{stats.get('best', 0)} DC", GOLD, I_TROPHY, False),
    ]

    for i, (lbl, val, color, ic_code, is_green) in enumerate(tb_data):
        bx1 = PAD_X + i * (col_w + gap_top)
        bx2 = bx1 + col_w
        by1 = top_y1
        by2 = top_y1 + top_h

        _grad(img, (bx1, by1, bx2, by2), color, color, alpha=18 if is_green else 10, radius=16)
        d.rounded_rectangle((bx1, by1, bx2, by2), radius=16,
                            outline=color + (200,), width=2)

        _alpha(img, (bx1 + 16, by1 + 22, bx1 + 62, by1 + 68), color, alpha=45, radius=12)
        _icon(d, bx1 + 39, by1 + 45, ic_code, 22, color)

        d.text((bx1 + 78, by1 + 20), lbl, font=_font(11), fill=MUTED)
        vf = _font(24)
        v = _el(d, val, vf, bx2 - 90)
        d.text((bx1 + 78, by1 + 42), v, font=vf, fill=color)

    head_y = top_y1 + top_h + 22
    d.text((PAD_X, head_y), "🎰 Кейсы", font=_font(32), fill=TEXT)
    sw = _tw(d, "выбери свою удачу", _font(15))
    d.text((W - PAD_X - sw, head_y + 14), "выбери свою удачу",
           font=_font(15), fill=MUTED)
    d.line((PAD_X, head_y + 56, W - PAD_X, head_y + 56),
           fill=STACK_HDR + (255,), width=2)

    grid_y = head_y + 70
    grid_bottom = H - PAD_Y - 20
    grid_h = grid_bottom - grid_y

    gap = 18
    cols = 5
    cell_w = (W - 2 * PAD_X - gap * (cols - 1)) // cols
    cell_h = min(grid_h, int(cell_w * 1.15))

    for i, case in enumerate(CASES):
        cx1 = PAD_X + i * (cell_w + gap)
        cy1 = grid_y
        cy2 = cy1 + cell_h
        cx2 = cx1 + cell_w
        color = FA_CASE_COLOR.get(case["color"], SILVER)

        _grad(img, (cx1, cy1, cx2, cy2), color, color, alpha=20, radius=24)
        d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=24,
                            outline=color + (230,), width=3)

        if case["num"] == 5:
            bw_ = 64
            bx1 = cx2 - bw_ - 18
            by1 = cy1 + 16
            d.rounded_rectangle((bx1, by1, bx1 + bw_, by1 + 28), radius=8, fill=RED + (255,))
            d.text((bx1 + 10, by1 + 6), "TOP", font=_font(12), fill=TEXT)

        ic_size = 130
        ic_x = cx1 + (cell_w - ic_size) // 2
        ic_y = cy1 + 34
        _alpha(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size),
               color, alpha=50, radius=28)
        d.rounded_rectangle((ic_x, ic_y, ic_x + ic_size, ic_y + ic_size),
                            radius=28, outline=color + (220,), width=3)
        icon_code = {1: I_GIFT, 2: I_COINS, 3: I_GEM, 4: I_CROWN, 5: I_TROPHY}.get(case["num"], I_GIFT)
        _icon(d, ic_x + ic_size // 2, ic_y + ic_size // 2 + 1, icon_code, 58, color)

        nf = _font(20)
        name_lines = _wrap(d, case["name"], nf, cell_w - 30, max_lines=2)
        ny = ic_y + ic_size + 22
        for j, ln in enumerate(name_lines):
            lw = _tw(d, ln, nf)
            d.text((cx1 + (cell_w - lw) // 2, ny + j * 26), ln, font=nf, fill=color)

        price_str = str(case["price"])
        pf = _font(44)
        pw = _tw(d, price_str, pf)
        uf = _font(18)
        uw = _tw(d, " DC", uf)
        total = pw + uw
        px = cx1 + (cell_w - total) // 2
        py = cy2 - 70
        d.text((px, py), price_str, font=pf, fill=color)
        d.text((px + pw + 6, py + pf.size - 22), " DC", font=uf, fill=MUTED)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 4: КРУТКА (поднято выше)
# ═══════════════════════════════════════════════════
def render_spin(case):
    img, d = _canvas("крутка кейса")

    color = FA_CASE_COLOR.get(case["color"], GOLD)

    cx = W // 2
    cy = 380            # было 510 → подняли выше

    circle_size = 420   # чуть меньше, чтобы не уходило за края

    circle_x = cx - circle_size // 2
    circle_y = cy - circle_size // 2

    for i, a in enumerate([12, 18, 24]):
        gs = circle_size + 100 - i * 30
        _alpha(img, (cx - gs // 2, cy - gs // 2, cx + gs // 2, cy + gs // 2),
               color, alpha=a, radius=gs // 2)

    _grad(img, (circle_x, circle_y, circle_x + circle_size, circle_y + circle_size),
          color, color, alpha=30, radius=circle_size // 2)
    d.ellipse((circle_x - 5, circle_y - 5, circle_x + circle_size + 5, circle_y + circle_size + 5),
              outline=color + (255,), width=10)
    d.ellipse((circle_x + 26, circle_y + 26,
               circle_x + circle_size - 26, circle_y + circle_size - 26),
              outline=color + (140,), width=4)

    _icon(d, cx, cy + 2, I_GIFT, 180, color)

    title = "КРУТИМ БАРАБАН..."
    tf = _font(56)
    tw_ = _tw(d, title, tf)
    d.text((cx - tw_ // 2, circle_y + circle_size + 40), title, font=tf, fill=color)

    sub = f"{case['name']} · {case['price']} DC списано"
    sf = _font(22)
    sw = _tw(d, sub, sf)
    d.text((cx - sw // 2, circle_y + circle_size + 120), sub, font=sf, fill=MUTED)

    hint = "результат через пару секунд..."
    hf = _font(16)
    hw = _tw(d, hint, hf)
    d.text((cx - hw // 2, circle_y + circle_size + 158), hint, font=hf, fill=DIM)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 5: РЕЗУЛЬТАТ — переписан чисто, без падений
# ═══════════════════════════════════════════════════
def render_result(case, prize, desc, user_balance):
    # Определяем цвет/тег
    ptype = (prize or {}).get("type", "dc")

    try:
        case_price = int(case.get("price", 0) or 0)
    except Exception:
        case_price = 0

    try:
        prize_value = int((prize or {}).get("value", 0) or 0)
    except Exception:
        prize_value = 0

    if ptype == "dc":
        if case_price > 0 and prize_value >= case_price * 3:
            color = GOLD
            tag = "ПОЗДРАВЛЯЕМ, ДЖЕКПОТ"
        elif case_price > 0 and prize_value >= case_price:
            color = GREEN
            tag = "ПОЗДРАВЛЯЕМ, ВЫПАЛО"
        else:
            color = BLUE
            tag = "ВЫПАЛО"
    elif ptype == "role":
        color = PURPLE
        tag = "ПОЗДРАВЛЯЕМ, РОЛЬ"
    elif ptype == "boost":
        color = BLUE
        tag = "ВЫПАЛ БУСТ"
    elif ptype == "discount":
        color = GOLD
        tag = "ВЫПАЛА СКИДКА"
    else:
        color = SILVER
        tag = "ВЫПАЛО"

    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=30,
                        fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)

    cx = W // 2

    # Свечение
    for i, a in enumerate([6, 10, 14, 18]):
        gs = 1600 - i * 200
        _alpha(img, (cx - gs // 2, H // 2 - gs // 2,
                     cx + gs // 2, H // 2 + gs // 2),
               color, alpha=a, radius=gs // 2)

    # Звёзды
    for sx, sy, sz in [(180, 150, 44), (W - 200, 180, 52),
                       (200, H - 260, 36), (W - 220, H - 240, 40),
                       (120, 440, 32), (W - 140, 420, 36)]:
        _icon(d, sx, sy, I_STAR, sz, GOLD)

    # Header
    hx, hy = PAD_X, PAD_Y
    d.rounded_rectangle((hx, hy, hx + 54, hy + 54), radius=14, fill=(58, 58, 64) + (255,))
    _icon(d, hx + 27, hy + 28, I_TROPHY, 26, GOLD)
    bx = hx + 54 + 18
    d.text((bx, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx + 2, hy + 38), "BONUS · ВЫИГРЫШ", font=_font(11), fill=MUTED)

    meta_r = W - PAD_X
    mtext = f"КЕЙС {case.get('num', '?')}"
    w1 = _tw(d, mtext, _font(11))
    d.text((meta_r - w1, hy + 14), mtext, font=_font(11), fill=MUTED)

    d.line((PAD_X, hy + 54 + 16, W - PAD_X, hy + 54 + 16),
           fill=STACK_HDR + (255,), width=2)

    # TAG
    tag_text = tag
    txf = _font(16)
    txw = _tw(d, tag_text, txf)
    pad_tx = 36
    tag_w = txw + pad_tx * 2
    tag_h = 50
    tag_x = cx - tag_w // 2
    tag_y = 180

    _alpha(img, (tag_x, tag_y, tag_x + tag_w, tag_y + tag_h),
           color, alpha=60, radius=tag_h // 2)
    d.rounded_rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + tag_h),
                        radius=tag_h // 2, outline=color + (230,), width=3)
    d.text((cx - txw // 2, tag_y + 12), tag_text, font=txf, fill=color)

    # ИКОНКА
    ic_size = 240
    ic_x = cx - ic_size // 2
    ic_y = tag_y + tag_h + 30

    for i, a in enumerate([28, 42, 55]):
        gs = ic_size + 60 - i * 20
        _alpha(img, (cx - gs // 2, ic_y + ic_size // 2 - gs // 2,
                     cx + gs // 2, ic_y + ic_size // 2 + gs // 2),
               color, alpha=a, radius=gs // 2)

    _alpha(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size),
           color, alpha=55, radius=ic_size // 2)
    d.ellipse((ic_x - 4, ic_y - 4, ic_x + ic_size + 4, ic_y + ic_size + 4),
              outline=color + (255,), width=6)
    _icon(d, cx, ic_y + ic_size // 2 + 2, I_TROPHY, 110, color)

    # ЦИФРА
    num_y = ic_y + ic_size + 30
    num_str = str(desc or "—")
    nf = _font(140)
    while _tw(d, num_str, nf) > W - 200 and nf.size > 60:
        nf = _font(nf.size - 6)
    nw = _tw(d, num_str, nf)
    d.text((cx - nw // 2, num_y), num_str, font=nf, fill=color)

    # Подпись
    sub_y = num_y + nf.size + 16
    sub = f"Кейс «{case.get('name', '—')}» · {case_price} DC"
    sf = _font(15)
    sw = _tw(d, sub, sf)
    d.text((cx - sw // 2, sub_y), sub, font=sf, fill=MUTED)

    # INFO снизу
    info_y = H - PAD_Y - 130
    info_h = 130
    ix1 = PAD_X
    ix2 = W - PAD_X

    d.rounded_rectangle((ix1, info_y, ix2, info_y + info_h), radius=20,
                        fill=(20, 20, 28) + (255,),
                        outline=color + (200,), width=2)

    mid_x = (ix1 + ix2) // 2

    # Левая половина
    _icon(d, ix1 + 70, info_y + info_h // 2,
          I_COINS if ptype == "dc" else I_GIFT, 46, color)

    if ptype == "dc":
        d.text((ix1 + 116, info_y + 26), "ЗАЧИСЛЕНО НА БАЛАНС",
               font=_font(12), fill=color)
        d.text((ix1 + 116, info_y + 50), f"+{prize_value} DC",
               font=_font(38), fill=TEXT)
        if case_price > 0:
            mult = prize_value / case_price
            mult_str = f"×{mult:.1f} от ставки"
        else:
            mult_str = ""
        d.text((ix1 + 116, info_y + 98), mult_str,
               font=_font(14), fill=MUTED)
    elif ptype == "role":
        d.text((ix1 + 116, info_y + 30), "РОЛЬ ВЫДАНА",
               font=_font(12), fill=color)
        d.text((ix1 + 116, info_y + 54), str(desc or "—"),
               font=_font(30), fill=TEXT)
        d.text((ix1 + 116, info_y + 98), "проверь профиль",
               font=_font(14), fill=MUTED)
    elif ptype == "boost":
        d.text((ix1 + 116, info_y + 30), "БУСТ АКТИВИРОВАН",
               font=_font(12), fill=color)
        d.text((ix1 + 116, info_y + 54), "уже работает",
               font=_font(30), fill=TEXT)
        d.text((ix1 + 116, info_y + 98), "смотри в профиле",
               font=_font(14), fill=MUTED)
    elif ptype == "discount":
        d.text((ix1 + 116, info_y + 30), "СКИДКА В ИНВЕНТАРЕ",
               font=_font(12), fill=color)
        d.text((ix1 + 116, info_y + 54), str(desc or "—"),
               font=_font(30), fill=TEXT)
        d.text((ix1 + 116, info_y + 98), "примени в тикете",
               font=_font(14), fill=MUTED)

    # Разделитель
    d.rectangle((mid_x - 1, info_y + 24, mid_x + 1, info_y + info_h - 24),
                fill=(60, 60, 68) + (255,))

    # Правая половина
    _icon(d, mid_x + 60, info_y + info_h // 2, I_GEM, 46, GREEN)
    d.text((mid_x + 106, info_y + 26), "ТЕКУЩИЙ БАЛАНС",
           font=_font(12), fill=GREEN)
    bal_str = f"{int(user_balance):,}".replace(",", " ") + " DC"
    d.text((mid_x + 106, info_y + 50), bal_str,
           font=_font(38), fill=TEXT)
    d.text((mid_x + 106, info_y + 98), "готов к новому кейсу",
           font=_font(14), fill=MUTED)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 6: МОИ КЕЙСЫ
# ═══════════════════════════════════════════════════
def render_my_cases(user_id, username, stats, history):
    img, d = _canvas("мои кейсы")

    left_w = 420; gap = 24
    lx1, lx2 = PAD_X, PAD_X + left_w
    rx1, rx2 = lx2 + gap, W - PAD_X

    _panel(img, d, (lx1, BODY_Y, lx2 - 12, BODY_Y + BODY_H - 12), radius=20)
    x1, y1 = lx1, BODY_Y
    x2 = lx2 - 12
    pad = 24
    cx = (x1 + x2) // 2

    av_size = 140
    av_cy = y1 + pad + av_size // 2
    r = av_size // 2
    _grad(img, (cx - r, av_cy - r, cx + r, av_cy + r), GOLD, PURPLE, alpha=70, radius=r)
    d.ellipse((cx - r - 2, av_cy - r - 2, cx + r + 2, av_cy + r + 2),
              outline=GOLD + (255,), width=5)
    _icon(d, cx, av_cy + 1, I_TROPHY, 60, TEXT)

    nick_y = y1 + pad + av_size + 18
    nick = _el(d, username, _font(24), (x2 - x1) - 2 * pad)
    nw = _tw(d, nick, _font(24))
    d.text((cx - nw // 2, nick_y), nick, font=_font(24), fill=TEXT)

    uid_y = nick_y + 34
    uid_text = f"UID · {user_id}"
    uw = _tw(d, uid_text, _font(13))
    d.text((cx - uw // 2, uid_y), uid_text, font=_font(13), fill=MUTED)

    sep_y = uid_y + 26
    d.line((x1 + pad, sep_y, x2 - pad, sep_y), fill=STACK_HDR + (255,), width=2)

    grid_y = sep_y + 16
    grid_w = (x2 - pad) - (x1 + pad)
    cg = 12
    cw = (grid_w - cg) // 2
    ch_ = 110

    items = [
        ("ОТКРЫТО",   stats.get("opened", 0),    BLUE),
        ("ПОТРАЧЕНО", f"{stats.get('spent', 0)} DC", RED),
        ("ЛУЧШИЙ",    f"{stats.get('best', 0)} DC", GOLD),
        ("СРЕДНИЙ",   f"{stats.get('spent', 0) // max(stats.get('opened', 1), 1)} DC", SILVER),
    ]
    for i, (lbl, val, color) in enumerate(items):
        r_, c_ = divmod(i, 2)
        cx1 = x1 + pad + c_ * (cw + cg)
        cy1 = grid_y + r_ * (ch_ + cg)
        d.rounded_rectangle((cx1, cy1, cx1 + cw, cy1 + ch_), radius=16,
                            fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        d.text((cx1 + 18, cy1 + 16), lbl, font=_font(11), fill=MUTED)
        vf = _font(24)
        v = str(val)
        while _tw(d, v, vf) > cw - 36 and vf.size > 14:
            vf = _font(vf.size - 2)
        d.text((cx1 + 18, cy1 + 44), v, font=vf, fill=color)

    _panel(img, d, (rx1, BODY_Y, rx2 - 12, BODY_Y + BODY_H - 12), radius=20)
    rpx1 = rx1 + 28; rpx2 = rx2 - 12 - 28; rpy = BODY_Y + 24

    d.text((rpx1, rpy), "🎒 Мои кейсы", font=_font(32), fill=TEXT)
    sub = f"последние {min(len(history), 6)} открытий"
    sw = _tw(d, sub, _font(14))
    d.text((rpx2 - sw, rpy + 14), sub, font=_font(14), fill=MUTED)

    sep_y = rpy + 52
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)

    list_y = sep_y + 16
    list_bottom = BODY_Y + BODY_H - 12 - 22
    row_h = 100
    row_gap = 10

    if not history:
        cx2 = (rpx1 + rpx2) // 2
        cy2 = (list_y + list_bottom) // 2
        _icon(d, cx2, cy2 - 20, I_ELL, 40, DIM)
        msg = "Ты ещё не открывал кейсы"
        mw = _tw(d, msg, _font(18))
        d.text((cx2 - mw // 2, cy2 + 30), msg, font=_font(18), fill=DIM)
    else:
        for i, row in enumerate(history[:6]):
            ry = list_y + i * (row_h + row_gap)
            if ry + row_h > list_bottom: break

            ptype = row.get("prize_type", "")
            if ptype == "dc":
                color, icon_code = GREEN, I_COINS
            elif ptype == "role":
                color, icon_code = PURPLE, I_CROWN
            elif ptype == "boost":
                color, icon_code = BLUE, I_BOLT
            elif ptype == "discount":
                color, icon_code = GOLD, I_TAG
            else:
                color, icon_code = SILVER, I_GIFT

            d.rounded_rectangle((rpx1, ry, rpx2, ry + row_h), radius=14,
                                fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
            d.rounded_rectangle((rpx1, ry + 12, rpx1 + 5, ry + row_h - 12),
                                radius=3, fill=color + (255,))

            ib_size = 56
            ibx = rpx1 + 20
            iby = ry + (row_h - ib_size) // 2
            _alpha(img, (ibx, iby, ibx + ib_size, iby + ib_size), color, alpha=50, radius=14)
            _icon(d, ibx + ib_size // 2, iby + ib_size // 2 + 1, icon_code, 26, color)

            tx = ibx + ib_size + 20
            try:
                from bonus.core import CASES_BY_NUM
                case_name = CASES_BY_NUM.get(row["case_num"], {}).get("name", "")
            except Exception:
                case_name = ""
            d.text((tx, ry + row_h // 2 - 22),
                   f"Кейс {row['case_num']} · {case_name}",
                   font=_font(17), fill=TEXT)

            try:
                dt = datetime.fromtimestamp(row["opened_at"], timezone.utc).strftime("%d.%m.%Y · %H:%M")
            except Exception:
                dt = "—"
            d.text((tx, ry + row_h // 2 + 4), dt, font=_font(12), fill=MUTED)

            prize = row.get("prize_desc", "—")
            pf = _font(22)
            while _tw(d, prize, pf) > 340 and pf.size > 14:
                pf = _font(pf.size - 1)
            pw = _tw(d, prize, pf)
            d.text((rpx2 - 24 - pw, ry + row_h // 2 - 14), prize, font=pf, fill=color)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
