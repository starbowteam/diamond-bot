# -*- coding: utf-8 -*-
"""
Pillow-рендер бонус-панели: акция дня, реф-панель, кейсы, крутка, результат.
1800×1000.
"""
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

SILVER    = (198, 208, 224)
SILVER_HI = (224, 232, 245)

GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
GOLD      = (247, 201, 145)
PURPLE    = (179, 157, 219)
BRONZE    = (209, 146, 96)

CARD_BRD  = (74, 74, 79)

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
# ЭКРАН 1: АКЦИЯ ДНЯ
# ═══════════════════════════════════════════════════
def render_daily_deal(user_id, balance, deal, hours_left):
    img, d = _canvas("акция дня")

    left_w = 400; gap = 36
    lx1, lx2 = PAD_X, PAD_X + left_w
    rx1, rx2 = lx2 + gap, W - PAD_X

    # ─── ЛЕВАЯ ───
    _panel(img, d, (lx1, BODY_Y, lx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    x1, y1 = lx1, BODY_Y
    x2 = lx2 - 12
    pad = 26

    # баланс
    bal_y1 = y1 + pad
    bal_y2 = bal_y1 + 110
    _grad(img, (x1 + pad, bal_y1, x2 - pad, bal_y2), GREEN, GREEN, alpha=20, radius=16)
    d.rounded_rectangle((x1 + pad, bal_y1, x2 - pad, bal_y2), radius=16,
                        outline=GREEN + (200,), width=2)
    lbl = "ТВОЙ БАЛАНС"
    lw = _tw(d, lbl, _font(11))
    d.text(((x1 + x2) // 2 - lw // 2, bal_y1 + 16), lbl, font=_font(11), fill=GREEN)

    bal_str = f"{balance:,}".replace(",", " ")
    bf = _font(38)
    while _tw(d, bal_str + " DC", bf) > (x2 - x1) - 2 * pad - 20 and bf.size > 20:
        bf = _font(bf.size - 2)
    bw = _tw(d, bal_str, bf)
    uw = _tw(d, " DC", _font(18))
    start_x = (x1 + x2) // 2 - (bw + uw) // 2
    d.text((start_x, bal_y1 + 44), bal_str, font=bf, fill=GREEN)
    d.text((start_x + bw + 6, bal_y1 + 44 + bf.size - 22), " DC",
           font=_font(18), fill=MUTED)

    # инфо-плашки
    def _info(bx_y, icon_code, lbl, val, color):
        bx1 = x1 + pad
        bx2 = x2 - pad
        bh = 76
        d.rounded_rectangle((bx1, bx_y, bx2, bx_y + bh), radius=14,
                            fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        _alpha(img, (bx1 + 16, bx_y + (bh - 44) // 2, bx1 + 60, bx_y + (bh - 44) // 2 + 44),
               color, alpha=45, radius=11)
        _icon(d, bx1 + 38, bx_y + bh // 2 + 1, icon_code, 20, color)
        tx = bx1 + 76
        d.text((tx, bx_y + 14), lbl, font=_font(10), fill=MUTED)
        vf = _font(20)
        v = _el(d, val, vf, bx2 - 16 - tx)
        d.text((tx, bx_y + 32), v, font=vf, fill=color)

    cat_label = deal.get("category_label", "—") if deal else "—"
    discount = deal.get("discount", 0) if deal else 0

    _info(bal_y2 + 16, I_TAG, "СКИДКА ДНЯ", f"{discount}%", GOLD)
    _info(bal_y2 + 16 + 76 + 12, I_CUBE, "КАТЕГОРИЯ", cat_label, BLUE)

    # таймер снизу
    tm_y = y1 + (BODY_Y + BODY_H - 12) - pad - 90
    tm_y1 = tm_y; tm_y2 = tm_y + 90
    _grad(img, (x1 + pad, tm_y1, x2 - pad, tm_y2), GOLD, GOLD, alpha=15, radius=14)
    d.rounded_rectangle((x1 + pad, tm_y1, x2 - pad, tm_y2), radius=14,
                        outline=GOLD + (180,), width=2)
    _icon(d, x1 + pad + 30, tm_y1 + 45, I_CLOCK, 22, GOLD)
    d.text((x1 + pad + 58, tm_y1 + 18), "СЛЕДУЮЩАЯ ЧЕРЕЗ",
           font=_font(10), fill=GOLD)
    tv = f"{hours_left} ч."
    d.text((x1 + pad + 58, tm_y1 + 38), tv, font=_font(24), fill=GOLD)

    # ─── ПРАВАЯ ───
    _panel(img, d, (rx1, BODY_Y, rx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    rpx1 = rx1 + 28; rpx2 = rx2 - 12 - 28; rpy = BODY_Y + 22

    d.text((rpx1, rpy), "🔥 Акция дня", font=_font(30), fill=TEXT)
    sw = _tw(d, "только сегодня", _font(14))
    d.text((rpx2 - sw, rpy + 12), "только сегодня", font=_font(14), fill=MUTED)

    sep_y = rpy + 48
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)

    if not deal:
        cx = (rpx1 + rpx2) // 2
        cy = (sep_y + BODY_Y + BODY_H - 12 - 22) // 2
        _icon(d, cx, cy - 30, I_FIRE, 48, DIM)
        msg = "Сегодня акции нет"
        mw = _tw(d, msg, _font(22))
        d.text((cx - mw // 2, cy + 30), msg, font=_font(22), fill=DIM)
    else:
        # Крупная карточка товара
        hero_y1 = sep_y + 20
        hero_h = 380
        hero_y2 = hero_y1 + hero_h

        _grad(img, (rpx1, hero_y1, rpx2, hero_y2), RED, RED, alpha=12, radius=22)
        d.rounded_rectangle((rpx1, hero_y1, rpx2, hero_y2), radius=22,
                            outline=RED + (200,), width=3)

        # иконка категории
        ic_size = 200
        ic_x = rpx1 + 40
        ic_y = hero_y1 + (hero_h - ic_size) // 2
        _grad(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size),
              BLUE, SILVER, alpha=45, radius=26)
        d.rounded_rectangle((ic_x, ic_y, ic_x + ic_size, ic_y + ic_size),
                            radius=26, outline=BLUE + (200,), width=3)
        _icon(d, ic_x + ic_size // 2, ic_y + ic_size // 2 + 2, I_CUBE, 90, SILVER_HI)

        # текст
        tx = ic_x + ic_size + 40
        tx_max = rpx2 - 40 - tx

        cat_line = f"🎯 {cat_label.upper()} · СКИДКА {discount}%"
        d.text((tx, hero_y1 + 40), cat_line, font=_font(15), fill=RED)

        name = deal.get("item_data", {}).get("name", "—")
        nf = _font(42)
        name_lines = _wrap(d, name, nf, tx_max, max_lines=2)
        for i, ln in enumerate(name_lines):
            d.text((tx, hero_y1 + 80 + i * 52), ln, font=nf, fill=TEXT)

        desc = deal.get("item_data", {}).get("description", "") or "Товар дня со скидкой."
        df = _font(15)
        desc_lines = _wrap(d, desc, df, tx_max, max_lines=2)
        desc_y = hero_y1 + 80 + len(name_lines) * 52 + 10
        for i, ln in enumerate(desc_lines):
            d.text((tx, desc_y + i * 22), ln, font=df, fill=MUTED)

        # цены
        prices_y = hero_y2 - 100
        orig = deal.get("original_price", 0)
        new = deal.get("new_price", 0)

        orig_str = f"{orig} DC"
        of = _font(26)
        ow = _tw(d, orig_str, of)
        d.text((tx, prices_y), orig_str, font=of, fill=DIM)
        d.line((tx, prices_y + 16, tx + ow, prices_y + 16), fill=DIM, width=2)

        new_str = f"{new}"
        nf2 = _font(62)
        d.text((tx, prices_y + 30), new_str, font=nf2, fill=GREEN)
        nw = _tw(d, new_str, nf2)
        d.text((tx + nw + 12, prices_y + 30 + nf2.size - 26), "DC",
               font=_font(24), fill=MUTED)

        # hint
        hint_y = hero_y2 + 24
        hint_h = BODY_Y + BODY_H - 12 - 24 - hint_y
        if hint_h > 70:
            d.rounded_rectangle((rpx1, hint_y, rpx2, hint_y + hint_h), radius=14,
                                fill=(20, 30, 44) + (255,),
                                outline=BLUE + (180,), width=2)
            _icon(d, rpx1 + 30, hint_y + hint_h // 2, 0xf05a, 22, BLUE)
            hint_lines = _wrap(
                d,
                "Если товар — попадёт в инвентарь, оформишь в тикете через витрину DC. "
                "Если роль — выдастся сразу.",
                _font(14), rpx2 - rpx1 - 80, max_lines=2
            )
            for i, ln in enumerate(hint_lines):
                d.text((rpx1 + 60, hint_y + 20 + i * 20), ln, font=_font(14), fill=BLUE)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 2: РЕФ-ПАНЕЛЬ
# ═══════════════════════════════════════════════════
def render_ref_panel(user_id, username, stats, link_url):
    img, d = _canvas("реферальная система")

    left_w = 460; gap = 36
    lx1, lx2 = PAD_X, PAD_X + left_w
    rx1, rx2 = lx2 + gap, W - PAD_X

    # ─── ЛЕВАЯ ───
    _panel(img, d, (lx1, BODY_Y, lx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    x1, y1 = lx1, BODY_Y
    x2 = lx2 - 12
    pad = 26
    cx = (x1 + x2) // 2

    # Аватарка
    av_size = 120
    av_cy = y1 + pad + av_size // 2
    r = av_size // 2
    _grad(img, (cx - r, av_cy - r, cx + r, av_cy + r), GREEN, SILVER, alpha=70, radius=r)
    d.ellipse((cx - r - 2, av_cy - r - 2, cx + r + 2, av_cy + r + 2),
              outline=GREEN + (255,), width=4)
    _icon(d, cx, av_cy + 1, I_USER, 52, TEXT)

    nick_y = y1 + pad + av_size + 20
    nick = _el(d, username, _font(20), (x2 - x1) - 2 * pad)
    nw = _tw(d, nick, _font(20))
    d.text((cx - nw // 2, nick_y), nick, font=_font(20), fill=TEXT)

    uid_y = nick_y + 30
    uid_text = f"UID · {user_id}"
    uw = _tw(d, uid_text, _font(12))
    d.text((cx - uw // 2, uid_y), uid_text, font=_font(12), fill=MUTED)

    sep_y = uid_y + 26
    d.line((x1 + pad, sep_y, x2 - pad, sep_y), fill=STACK_HDR + (255,), width=2)

    # сетка 2×2
    grid_y = sep_y + 20
    grid_w = (x2 - pad) - (x1 + pad)
    cell_gap = 12
    cell_w = (grid_w - cell_gap) // 2
    cell_h = 96

    items = [
        ("ЗАРАБОТАНО",   stats.get("earned", 0),   GREEN),
        ("ПРИГЛАШЕНО",   stats.get("total", 0),    SILVER),
        ("ЗАСЧИТАНО",    stats.get("rewarded", 0), GREEN),
        ("В ХОЛДЕ",      stats.get("on_review", 0), GOLD),
    ]
    for i, (lbl, val, color) in enumerate(items):
        r_, c_ = divmod(i, 2)
        cx1 = x1 + pad + c_ * (cell_w + cell_gap)
        cy1 = grid_y + r_ * (cell_h + cell_gap)
        d.rounded_rectangle((cx1, cy1, cx1 + cell_w, cy1 + cell_h), radius=14,
                            fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        d.text((cx1 + 16, cy1 + 14), lbl, font=_font(10), fill=MUTED)
        d.text((cx1 + 16, cy1 + 40), str(val), font=_font(32), fill=color)

    # hint
    hint_y = BODY_Y + BODY_H - 12 - pad - 90
    _grad(img, (x1 + pad, hint_y, x2 - pad, hint_y + 90), GREEN, GREEN, alpha=15, radius=14)
    d.rounded_rectangle((x1 + pad, hint_y, x2 - pad, hint_y + 90), radius=14,
                        outline=GREEN + (180,), width=2)
    _icon(d, x1 + pad + 26, hint_y + 45, I_GIFT, 22, GREEN)
    lines = [
        "10 DC за друга + 10 DC в копилку клана",
        "Порог зачёта — 1 час",
    ]
    for i, ln in enumerate(lines):
        d.text((x1 + pad + 52, hint_y + 20 + i * 24), ln,
               font=_font(13), fill=GREEN)

    # ─── ПРАВАЯ ───
    _panel(img, d, (rx1, BODY_Y, rx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    rpx1 = rx1 + 28; rpx2 = rx2 - 12 - 28; rpy = BODY_Y + 22

    d.text((rpx1, rpy), "👥 Мои приглашённые", font=_font(28), fill=TEXT)
    sub = f"{stats['total']} чел. · {stats['rewarded']} засчитано · {stats['on_review']} на проверке"
    sw = _tw(d, sub, _font(13))
    d.text((rpx2 - sw, rpy + 12), sub, font=_font(13), fill=MUTED)

    sep_y = rpy + 44
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)

    # Заголовки
    col_x = [rpx1, rpx1 + 80, rpx2 - 660, rpx2 - 440, rpx2 - 220]
    th_y = sep_y + 14
    for x, lbl in zip(col_x[1:], ["ПОЛЬЗОВАТЕЛЬ", "ВХОД", "ВЫХОД", "СТАТУС"]):
        d.text((x, th_y), lbl, font=_font(10), fill=MUTED)

    list_y = th_y + 30
    list_bottom = BODY_Y + BODY_H - 12 - 22
    row_h = 76
    row_gap = 6

    rows = stats.get("rows", [])[:7]

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

            d.rounded_rectangle((rpx1, ry, rpx2, ry + row_h), radius=12,
                                fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

            av_x = col_x[0] + 14
            d.ellipse((av_x, ry + row_h // 2 - 22, av_x + 44, ry + row_h // 2 + 22),
                      fill=(58, 58, 64))
            _icon(d, av_x + 22, ry + row_h // 2 + 1, I_USER, 18, SILVER_HI)

            d.text((col_x[1], ry + row_h // 2 - 20), f"ID {row['member_id']}",
                   font=_font(14), fill=TEXT)
            d.text((col_x[1], ry + row_h // 2 + 2), "участник",
                   font=_font(11), fill=MUTED)

            try:
                jdt = datetime.fromtimestamp(row["joined_at"], timezone.utc)
                jd = jdt.strftime("%d.%m.%Y"); jt = jdt.strftime("%H:%M")
            except Exception:
                jd, jt = "—", "—"
            d.text((col_x[2], ry + row_h // 2 - 16), jd, font=_font(13), fill=SILVER_HI)
            d.text((col_x[2], ry + row_h // 2 + 2), jt, font=_font(10), fill=MUTED)

            if row.get("left_at"):
                try:
                    ldt = datetime.fromtimestamp(row["left_at"], timezone.utc)
                    ld = ldt.strftime("%d.%m.%Y"); lt = ldt.strftime("%H:%M")
                except Exception:
                    ld, lt = "—", "—"
                d.text((col_x[3], ry + row_h // 2 - 16), ld, font=_font(13), fill=SILVER_HI)
                d.text((col_x[3], ry + row_h // 2 + 2), lt, font=_font(10), fill=MUTED)
            else:
                d.text((col_x[3], ry + row_h // 2 - 8), "—", font=_font(13), fill=DIM)

            if rewarded:
                txt, color = "✓ ЗАСЧИТАН", GREEN
            elif on_review:
                txt, color = "⚠ НА ПРОВЕРКЕ", GOLD
            else:
                txt, color = "… на сервере", BLUE

            tw_ = _tw(d, txt, _font(11))
            bx = col_x[4]
            _alpha(img, (bx, ry + row_h // 2 - 12, bx + tw_ + 20, ry + row_h // 2 + 12),
                   color, alpha=30, radius=8)
            d.rounded_rectangle((bx, ry + row_h // 2 - 12, bx + tw_ + 20, ry + row_h // 2 + 12),
                                radius=8, outline=color + (200,), width=1)
            d.text((bx + 10, ry + row_h // 2 - 7), txt, font=_font(11), fill=color)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 3: ВЫБОР КЕЙСА
# ═══════════════════════════════════════════════════
def render_cases(user_id, username, balance, stats):
    img, d = _canvas("кейсы")

    left_w = 400; gap = 36
    lx1, lx2 = PAD_X, PAD_X + left_w
    rx1, rx2 = lx2 + gap, W - PAD_X

    # ─── ЛЕВАЯ ───
    _panel(img, d, (lx1, BODY_Y, lx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    x1, y1 = lx1, BODY_Y
    x2 = lx2 - 12
    pad = 26

    # баланс
    bal_y1 = y1 + pad
    bal_y2 = bal_y1 + 110
    _grad(img, (x1 + pad, bal_y1, x2 - pad, bal_y2), GREEN, GREEN, alpha=20, radius=16)
    d.rounded_rectangle((x1 + pad, bal_y1, x2 - pad, bal_y2), radius=16,
                        outline=GREEN + (200,), width=2)
    lbl = "ТВОЙ БАЛАНС"
    lw = _tw(d, lbl, _font(11))
    d.text(((x1 + x2) // 2 - lw // 2, bal_y1 + 16), lbl, font=_font(11), fill=GREEN)
    bal_str = f"{balance:,}".replace(",", " ")
    bf = _font(38)
    while _tw(d, bal_str + " DC", bf) > (x2 - x1) - 2 * pad - 20 and bf.size > 20:
        bf = _font(bf.size - 2)
    bw = _tw(d, bal_str, bf)
    uw = _tw(d, " DC", _font(18))
    sx = (x1 + x2) // 2 - (bw + uw) // 2
    d.text((sx, bal_y1 + 44), bal_str, font=bf, fill=GREEN)
    d.text((sx + bw + 6, bal_y1 + 44 + bf.size - 22), " DC", font=_font(18), fill=MUTED)

    # инфо-плашки
    def _info(bx_y, icon_code, lbl, val, color):
        bx1 = x1 + pad; bx2 = x2 - pad; bh = 76
        d.rounded_rectangle((bx1, bx_y, bx2, bx_y + bh), radius=14,
                            fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        _alpha(img, (bx1 + 16, bx_y + 16, bx1 + 60, bx_y + 60), color, alpha=45, radius=11)
        _icon(d, bx1 + 38, bx_y + bh // 2 + 1, icon_code, 20, color)
        tx = bx1 + 76
        d.text((tx, bx_y + 14), lbl, font=_font(10), fill=MUTED)
        d.text((tx, bx_y + 32), val, font=_font(20), fill=color)

    _info(bal_y2 + 14, I_GIFT, "ОТКРЫТО", str(stats.get("opened", 0)), SILVER)
    _info(bal_y2 + 14 + 76 + 10, I_TROPHY, "ЛУЧШИЙ",
          f"{stats.get('best', 0)} DC", GOLD)

    # hint снизу
    hint_y = BODY_Y + BODY_H - 12 - pad - 80
    _grad(img, (x1 + pad, hint_y, x2 - pad, hint_y + 80), BLUE, BLUE, alpha=15, radius=14)
    d.rounded_rectangle((x1 + pad, hint_y, x2 - pad, hint_y + 80), radius=14,
                        outline=BLUE + (180,), width=2)
    _icon(d, x1 + pad + 24, hint_y + 40, 0xf05a, 20, BLUE)
    d.text((x1 + pad + 50, hint_y + 20), "ГАРАНТИЯ",
           font=_font(10), fill=BLUE)
    d.text((x1 + pad + 50, hint_y + 38), "минимум 30% возврата",
           font=_font(13), fill=BLUE)

    # ─── ПРАВАЯ ───
    _panel(img, d, (rx1, BODY_Y, rx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    rpx1 = rx1 + 28; rpx2 = rx2 - 12 - 28; rpy = BODY_Y + 22

    d.text((rpx1, rpy), "🎰 Кейсы", font=_font(30), fill=TEXT)
    sw = _tw(d, "выбери свою удачу", _font(14))
    d.text((rpx2 - sw, rpy + 12), "выбери свою удачу", font=_font(14), fill=MUTED)

    sep_y = rpy + 48
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)

    # Сетка 5 карточек
    from bonus.core import CASES
    grid_y = sep_y + 20
    grid_bottom = BODY_Y + BODY_H - 12 - 22
    grid_h = grid_bottom - grid_y

    gap = 16
    cols = 5
    cell_w = (rpx2 - rpx1 - gap * (cols - 1)) // cols
    cell_h = grid_h

    for i, case in enumerate(CASES):
        cx1 = rpx1 + i * (cell_w + gap)
        cy1 = grid_y
        color = FA_CASE_COLOR.get(case["color"], SILVER)

        # фон
        _grad(img, (cx1, cy1, cx1 + cell_w, cy1 + cell_h), color, color,
              alpha=18, radius=18)
        d.rounded_rectangle((cx1, cy1, cx1 + cell_w, cy1 + cell_h), radius=18,
                            outline=color + (220,), width=2)

        # бейдж "топ" для 5-го
        if case["num"] == 5:
            bw_ = 60
            bx1 = cx1 + cell_w - bw_ - 14
            by1 = cy1 + 14
            d.rounded_rectangle((bx1, by1, bx1 + bw_, by1 + 24), radius=8, fill=RED + (255,))
            d.text((bx1 + 10, by1 + 5), "TOP", font=_font(10), fill=TEXT)

        # иконка
        ic_size = 88
        ic_x = cx1 + (cell_w - ic_size) // 2
        ic_y = cy1 + 34
        _alpha(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size),
               color, alpha=50, radius=20)
        d.rounded_rectangle((ic_x, ic_y, ic_x + ic_size, ic_y + ic_size),
                            radius=20, outline=color + (200,), width=2)
        from bonus.render import _fa as _fa2
        icon_code = {
            1: I_GIFT, 2: I_COINS, 3: I_GEM, 4: I_CROWN, 5: I_TROPHY,
        }.get(case["num"], I_GIFT)
        _icon(d, ic_x + ic_size // 2, ic_y + ic_size // 2 + 1, icon_code, 40, color)

        # название
        nf = _font(19)
        name_lines = _wrap(d, case["name"], nf, cell_w - 24, max_lines=2)
        ny = ic_y + ic_size + 20
        for j, ln in enumerate(name_lines):
            lw = _tw(d, ln, nf)
            d.text((cx1 + (cell_w - lw) // 2, ny + j * 24), ln, font=nf, fill=TEXT)

        # цена
        price_str = str(case["price"])
        pf = _font(32)
        pw = _tw(d, price_str, pf)
        unit_f = _font(15)
        uw = _tw(d, " DC", unit_f)
        total = pw + uw
        px = cx1 + (cell_w - total) // 2
        py = cy1 + cell_h - 110
        d.text((px, py), price_str, font=pf, fill=color)
        d.text((px + pw + 4, py + pf.size - 18), " DC", font=unit_f, fill=MUTED)

        # описание
        df = _font(11)
        desc_lines = _wrap(d, case["desc"], df, cell_w - 24, max_lines=4)
        desc_y = cy1 + cell_h - 70
        for j, ln in enumerate(desc_lines):
            lw = _tw(d, ln, df)
            d.text((cx1 + (cell_w - lw) // 2, desc_y + j * 16), ln, font=df, fill=MUTED)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 4: КРУТКА
# ═══════════════════════════════════════════════════
def render_spin(case):
    img, d = _canvas("крутка кейса")

    from bonus.render import _fa as _fa2
    color = FA_CASE_COLOR.get(case["color"], GOLD)

    cx = W // 2
    cy = H // 2 + 20

    # Большой круг
    circle_size = 320
    circle_x = cx - circle_size // 2
    circle_y = cy - circle_size // 2

    _grad(img, (circle_x, circle_y, circle_x + circle_size, circle_y + circle_size),
          color, color, alpha=25, radius=circle_size // 2)
    d.ellipse((circle_x - 4, circle_y - 4, circle_x + circle_size + 4, circle_y + circle_size + 4),
              outline=color + (255,), width=8)
    d.ellipse((circle_x + 20, circle_y + 20, circle_x + circle_size - 20, circle_y + circle_size - 20),
              outline=color + (140,), width=3)

    _icon(d, cx, cy + 2, I_GIFT, 120, color)

    # Заголовок
    title = "КРУТИМ БАРАБАН..."
    tf = _font(48)
    tw_ = _tw(d, title, tf)
    d.text((cx - tw_ // 2, cy + circle_size // 2 + 50), title, font=tf, fill=color)

    sub = f"{case['name']} · {case['price']} DC списано"
    sf = _font(18)
    sw = _tw(d, sub, sf)
    d.text((cx - sw // 2, cy + circle_size // 2 + 120), sub, font=sf, fill=MUTED)

    hint = "Результат появится через пару секунд..."
    hf = _font(15)
    hw = _tw(d, hint, hf)
    d.text((cx - hw // 2, cy + circle_size // 2 + 158), hint, font=hf, fill=DIM)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 5: РЕЗУЛЬТАТ
# ═══════════════════════════════════════════════════
def render_result(case, prize, desc, user_balance):
    img, d = _canvas("выигрыш")

    # цвет по типу приза
    ptype = prize.get("type", "dc")
    if ptype == "dc":
        amount = int(prize.get("value", 0))
        if amount >= case["price"] * 3:
            color = GOLD
            tag = "ПОЗДРАВЛЯЕМ, ДЖЕКПОТ"
        elif amount >= case["price"]:
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

    body_y = BODY_Y
    body_h = BODY_H - 12

    # HERO
    hero_h = 380
    hero_y1 = body_y + 40
    hero_y2 = hero_y1 + hero_h
    hx1 = PAD_X
    hx2 = W - PAD_X

    _grad(img, (hx1, hero_y1, hx2, hero_y2), color, color, alpha=22, radius=26)
    d.rounded_rectangle((hx1, hero_y1, hx2, hero_y2), radius=26,
                        outline=color + (255,), width=4)

    # иконка
    ic_size = 220
    ic_x = hx1 + 60
    ic_y = hero_y1 + (hero_h - ic_size) // 2
    _alpha(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), color, alpha=70, radius=28)
    d.rounded_rectangle((ic_x, ic_y, ic_x + ic_size, ic_y + ic_size),
                        radius=28, outline=color + (255,), width=3)
    _icon(d, ic_x + ic_size // 2, ic_y + ic_size // 2 + 2, I_TROPHY, 96, color)

    # текст
    tx = ic_x + ic_size + 50
    tx_max = hx2 - 60 - tx

    d.text((tx, hero_y1 + 50), tag, font=_font(16), fill=color)

    # крупный текст приза
    nf = _font(72)
    while _tw(d, desc, nf) > tx_max and nf.size > 32:
        nf = _font(nf.size - 4)
    d.text((tx, hero_y1 + 88), desc, font=nf, fill=color)

    # подпись
    sub = f"Кейс «{case['name']}» · {case['price']} DC"
    sf = _font(17)
    d.text((tx, hero_y1 + 88 + nf.size + 20), sub, font=sf, fill=MUTED)

    # инфо снизу
    info_y = hero_y2 + 30
    info_h = 100
    ix1 = PAD_X
    ix2 = W - PAD_X

    d.rounded_rectangle((ix1, info_y, ix2, info_y + info_h), radius=16,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

    if ptype == "dc":
        _icon(d, ix1 + 40, info_y + info_h // 2, I_COINS, 28, color)
        d.text((ix1 + 76, info_y + 24), "ЗАЧИСЛЕНО НА БАЛАНС",
               font=_font(12), fill=MUTED)
        d.text((ix1 + 76, info_y + 46), f"+{prize.get('value', 0)} DC · текущий: {user_balance} DC",
               font=_font(18), fill=color)
    elif ptype == "role":
        _icon(d, ix1 + 40, info_y + info_h // 2, I_CROWN, 28, color)
        d.text((ix1 + 76, info_y + 24), "РОЛЬ ВЫДАНА АВТОМАТИЧЕСКИ",
               font=_font(12), fill=MUTED)
        d.text((ix1 + 76, info_y + 46), desc, font=_font(18), fill=color)
    elif ptype == "boost":
        _icon(d, ix1 + 40, info_y + info_h // 2, I_BOLT, 28, color)
        d.text((ix1 + 76, info_y + 24), "БУСТ АКТИВИРОВАН",
               font=_font(12), fill=MUTED)
        d.text((ix1 + 76, info_y + 46), "Уже работает — проверь активные бусты",
               font=_font(18), fill=color)
    elif ptype == "discount":
        _icon(d, ix1 + 40, info_y + info_h // 2, I_TAG, 28, color)
        d.text((ix1 + 76, info_y + 24), "СКИДКА В ИНВЕНТАРЕ",
               font=_font(12), fill=MUTED)
        d.text((ix1 + 76, info_y + 46), "Примени в тикете через «Скидки»",
               font=_font(18), fill=color)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════
# ЭКРАН 6: МОИ КЕЙСЫ
# ═══════════════════════════════════════════════════
def render_my_cases(user_id, username, stats, history):
    img, d = _canvas("мои кейсы")

    left_w = 460; gap = 36
    lx1, lx2 = PAD_X, PAD_X + left_w
    rx1, rx2 = lx2 + gap, W - PAD_X

    # ─── ЛЕВАЯ ───
    _panel(img, d, (lx1, BODY_Y, lx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    x1, y1 = lx1, BODY_Y
    x2 = lx2 - 12
    pad = 26
    cx = (x1 + x2) // 2

    av_size = 120
    av_cy = y1 + pad + av_size // 2
    r = av_size // 2
    _grad(img, (cx - r, av_cy - r, cx + r, av_cy + r), GOLD, PURPLE, alpha=70, radius=r)
    d.ellipse((cx - r - 2, av_cy - r - 2, cx + r + 2, av_cy + r + 2),
              outline=GOLD + (255,), width=4)
    _icon(d, cx, av_cy + 1, I_TROPHY, 52, TEXT)

    nick_y = y1 + pad + av_size + 20
    nick = _el(d, username, _font(20), (x2 - x1) - 2 * pad)
    nw = _tw(d, nick, _font(20))
    d.text((cx - nw // 2, nick_y), nick, font=_font(20), fill=TEXT)

    uid_y = nick_y + 30
    uid_text = f"UID · {user_id}"
    uw = _tw(d, uid_text, _font(12))
    d.text((cx - uw // 2, uid_y), uid_text, font=_font(12), fill=MUTED)

    sep_y = uid_y + 26
    d.line((x1 + pad, sep_y, x2 - pad, sep_y), fill=STACK_HDR + (255,), width=2)

    grid_y = sep_y + 20
    grid_w = (x2 - pad) - (x1 + pad)
    cg = 12
    cw = (grid_w - cg) // 2
    ch_ = 96

    items = [
        ("ОТКРЫТО",    stats.get("opened", 0),   BLUE),
        ("ПОТРАЧЕНО",  stats.get("spent", 0),    RED),
        ("ЛУЧШИЙ",     f"{stats.get('best', 0)} DC", GOLD),
        ("СРЕДНИЙ",    f"{(stats.get('spent', 0) // max(stats.get('opened', 1), 1))} DC", SILVER),
    ]
    for i, (lbl, val, color) in enumerate(items):
        r_, c_ = divmod(i, 2)
        cx1 = x1 + pad + c_ * (cw + cg)
        cy1 = grid_y + r_ * (ch_ + cg)
        d.rounded_rectangle((cx1, cy1, cx1 + cw, cy1 + ch_), radius=14,
                            fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        d.text((cx1 + 16, cy1 + 14), lbl, font=_font(10), fill=MUTED)
        vf = _font(26)
        if _tw(d, str(val), vf) > cw - 32:
            vf = _font(20)
        d.text((cx1 + 16, cy1 + 40), str(val), font=vf, fill=color)

    # ─── ПРАВАЯ ───
    _panel(img, d, (rx1, BODY_Y, rx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    rpx1 = rx1 + 28; rpx2 = rx2 - 12 - 28; rpy = BODY_Y + 22

    d.text((rpx1, rpy), "🎒 Мои кейсы", font=_font(28), fill=TEXT)
    sub = f"последние {min(len(history), 8)}"
    sw = _tw(d, sub, _font(13))
    d.text((rpx2 - sw, rpy + 12), sub, font=_font(13), fill=MUTED)

    sep_y = rpy + 44
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)

    list_y = sep_y + 14
    list_bottom = BODY_Y + BODY_H - 12 - 22
    row_h = 68
    row_gap = 6

    if not history:
        cx2 = (rpx1 + rpx2) // 2
        cy2 = (list_y + list_bottom) // 2
        _icon(d, cx2, cy2 - 20, I_ELL, 40, DIM)
        msg = "Ты ещё не открывал кейсы"
        mw = _tw(d, msg, _font(18))
        d.text((cx2 - mw // 2, cy2 + 30), msg, font=_font(18), fill=DIM)
    else:
        for i, row in enumerate(history[:8]):
            ry = list_y + i * (row_h + row_gap)
            if ry + row_h > list_bottom: break

            ptype = row.get("prize_type", "")
            if ptype == "dc":
                color = GREEN
                icon_code = I_COINS
            elif ptype == "role":
                color = PURPLE
                icon_code = I_CROWN
            elif ptype == "boost":
                color = BLUE
                icon_code = I_BOLT
            elif ptype == "discount":
                color = GOLD
                icon_code = I_TAG
            else:
                color = SILVER
                icon_code = I_GIFT

            d.rounded_rectangle((rpx1, ry, rpx2, ry + row_h), radius=12,
                                fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
            d.rounded_rectangle((rpx1, ry + 8, rpx1 + 4, ry + row_h - 8),
                                radius=4, fill=color + (255,))

            ib_size = 42
            ibx = rpx1 + 16
            iby = ry + (row_h - ib_size) // 2
            _alpha(img, (ibx, iby, ibx + ib_size, iby + ib_size), color, alpha=45, radius=11)
            _icon(d, ibx + ib_size // 2, iby + ib_size // 2 + 1, icon_code, 18, color)

            tx = ibx + ib_size + 14
            case_name = ""
            try:
                from bonus.core import CASES_BY_NUM
                case_name = CASES_BY_NUM.get(row["case_num"], {}).get("name", "")
            except Exception:
                pass
            d.text((tx, ry + row_h // 2 - 16), f"Кейс {row['case_num']} · {case_name}",
                   font=_font(14), fill=TEXT)

            try:
                dt = datetime.fromtimestamp(row["opened_at"], timezone.utc).strftime("%d.%m.%Y %H:%M")
            except Exception:
                dt = "—"
            d.text((tx, ry + row_h // 2 + 2), dt, font=_font(11), fill=MUTED)

            prize = row.get("prize_desc", "—")
            pf = _font(18)
            while _tw(d, prize, pf) > 300 and pf.size > 12:
                pf = _font(pf.size - 1)
            pw = _tw(d, prize, pf)
            d.text((rpx2 - 20 - pw, ry + row_h // 2 - 12), prize, font=pf, fill=color)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
