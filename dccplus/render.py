# -*- coding: utf-8 -*-
"""
Pillow-рендеры DCC+.
6 экранов: главная, мои активы, стейк, купить/продать, топ, история.
"""
import io
import os
import time
import math
from datetime import datetime, timezone
from typing import List, Dict, Optional

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, logger
from dccplus.core import (
    BASE_PRICE, MIN_PRICE, MAX_PRICE, MAX_SUPPLY,
    SELL_COMMISSION, MIN_BUY_DC, MAX_BUY_DC_DAY,
    MAX_SELL_DCC_HOUR, STAKE_MIN, STAKE_MAX_ONE, STAKE_MAX_ACTIVE,
    STAKE_PLANS, get_price, get_supply, get_wallet,
    get_active_stakes, get_top_holders, get_user_place,
    get_holders_count, get_price_history, get_recent_transactions,
    get_stats_24h,
)


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
GREEN_DK  = (26, 138, 74)
RED       = (255, 107, 107)
RED_DK    = (198, 40, 40)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)
GOLD      = (247, 201, 145)
GOLD_DK   = (174, 121, 17)
BRONZE    = (209, 146, 96)
PINK      = (255, 77, 148)
TEAL      = (77, 208, 225)
TEAL_DK   = (2, 136, 209)
TEAL_BG   = (12, 44, 56)

GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)
GOLD_BG   = (40, 32, 21)

CARD_BRD  = (74, 74, 79)

I_GEM        = 0xf3a5
I_CHART_LINE = 0xf201
I_WALLET     = 0xf555
I_LOCK       = 0xf023
I_UNLOCK     = 0xf09c
I_TROPHY     = 0xf091
I_CROWN      = 0xf521
I_MEDAL      = 0xf5a2
I_COIN       = 0xf51e
I_COINS      = 0xf51e
I_ARROW_UP   = 0xf062
I_ARROW_DOWN = 0xf063
I_ARROW_EX   = 0xf31e
I_EXCHANGE   = 0xf362
I_HAND       = 0xf4c0
I_USER       = 0xf007
I_USERS      = 0xf0c0
I_INFO       = 0xf05a
I_CHECK      = 0xf00c
I_XMARK      = 0xf00d
I_CLOCK      = 0xf017
I_FIRE       = 0xf06d
I_BOLT       = 0xf0e7
I_STAR       = 0xf005
I_PLUS       = 0xf067


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


def _grad_radial_circle(img, cx, cy, r, c1, c2, alpha=255):
    layer = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i in range(r, 0, -1):
        t = i / r
        rr = int(c1[0] * (1 - t) + c2[0] * t)
        gg = int(c1[1] * (1 - t) + c2[1] * t)
        bb = int(c1[2] * (1 - t) + c2[2] * t)
        ld.ellipse((r - i, r - i, r + i, r + i), fill=(rr, gg, bb, alpha))
    img.paste(layer, (cx - r, cy - r), layer)


def _panel(img, d, box, radius=22):
    x1, y1, x2, y2 = box
    _alpha(img, (x1 + 10, y1 + 10, x2 + 10, y2 + 10),
           (46, 46, 52), alpha=110, radius=radius)
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=2)


def _lighten(c, a=0.4):
    a = max(0, min(1, a))
    return (min(int(c[0] + (255 - c[0]) * a), 255),
            min(int(c[1] + (255 - c[1]) * a), 255),
            min(int(c[2] + (255 - c[2]) * a), 255))


def _fmt(n):
    try: return f"{int(n):,}".replace(",", " ")
    except: return str(n)


def _fmt_f(n, dp=2):
    try: return f"{float(n):,.{dp}f}".replace(",", " ")
    except: return str(n)


def _fmt_time(ts: int) -> str:
    if not ts: return "—"
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%d.%m %H:%M")
    except Exception:
        return "—"


# ─────────────── Каркас ───────────────
W, H = 1800, 1000
M = 14
PX, PY = 40, 40


def _canvas(user_id, subtitle):
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((M, M, W - 1 - M, H - 1 - M), radius=28,
                        fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)

    hx, hy = PX, PY
    ls = 64
    _grad(img, (hx, hy, hx + ls, hy + ls), TEAL, TEAL_DK, alpha=255, radius=16)
    d.rounded_rectangle((hx, hy, hx + ls, hy + ls), radius=16,
                        outline=TEAL + (220,), width=2)
    _icon(d, hx + ls // 2, hy + ls // 2 + 1, I_CHART_LINE, 30, (255, 255, 255))

    # ─── DCC + (плюс выровнен по вертикальному центру «DCC») ───
    bx = hx + ls + 20
    dcc_font = _font(34)
    dcc_text = "DCC"
    dcc_y = hy + 4

    # рисуем «DCC»
    d.text((bx, dcc_y), dcc_text, font=dcc_font, fill=TEXT)

    # замеряем bbox «DCC» — берём реальный вертикальный центр глифов
    bb = d.textbbox((bx, dcc_y), dcc_text, font=dcc_font)
    dcc_cy = (bb[1] + bb[3]) // 2
    dcc_w = bb[2] - bb[0]

    # рисуем «+» с anchor="lm" — левый край по X, середина по Y
    # получится ровно по центру «DCC», не ниже и не выше
    d.text((bx + dcc_w + 14, dcc_cy), "+",
           font=dcc_font, fill=TEAL, anchor="lm")

    d.text((bx + 4, hy + 46), "DIAMOND CRYPTO", font=_font(15), fill=MUTED)

    meta_r = W - M - PX
    w1 = _tw(d, subtitle.upper(), _font(15))
    w2 = _tw(d, f"UID · {user_id}", _font(24))
    d.text((meta_r - w1, hy + 14), subtitle.upper(), font=_font(15), fill=MUTED)
    d.text((meta_r - w2, hy + 38), f"UID · {user_id}", font=_font(24), fill=TEXT)

    sy = hy + ls + 20
    d.line((PX, sy, W - M - PX, sy), fill=STACK_HDR + (255,), width=2)
    return img, d


def _footer(d, left, page):
    y = H - M - PY + 6
    d.line((PX, y - 10, W - M - PX, y - 10), fill=STACK_HDR + (255,), width=2)
    _icon(d, PX + 12, y + 10, I_INFO, 16, DIM)
    d.text((PX + 38, y), left, font=_font(14), fill=DIM)
    pw = _tw(d, page, _font(14))
    d.text((W - M - PX - pw, y), page, font=_font(14), fill=DIM)


def _right_head(d, x1, y1, x2, title, sub):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 46), radius=3, fill=TEAL + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(28), fill=TEXT)
    sw = _tw(d, sub.upper(), _font(14))
    d.text((x2 - sw, y1 + 18), sub.upper(), font=_font(14), fill=MUTED)
    d.line((x1, y1 + 62, x2, y1 + 62), fill=STACK_HDR + (255,), width=2)


def _left_panel(img, d, box, blocks):
    """Левый блок без баланса DC — сразу инфоблоки."""
    _panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 26
    bb_h = 100
    bb_gap = 12
    top_y = y1 + pad

    for i, blk in enumerate(blocks):
        by1 = top_y + i * (bb_h + bb_gap)
        if by1 + bb_h > y2 - pad:
            break
        by2 = by1 + bb_h
        bx1, bx2 = x1 + pad, x2 - pad
        color = blk["color"]
        light = _lighten(color, 0.4)
        border = _lighten(color, 0.25)

        _grad(img, (bx1, by1, bx2, by2), color, color, alpha=28, radius=14)
        d.rounded_rectangle((bx1, by1, bx2, by2), radius=14,
                            outline=border + (230,), width=2)
        d.rounded_rectangle((bx1 + 4, by1 + 10, bx1 + 7, by2 - 10),
                            radius=2, fill=color + (255,))

        ic_s = 52
        iic_x = bx1 + 20
        iic_y = by1 + (bb_h - ic_s) // 2
        _alpha(img, (iic_x, iic_y, iic_x + ic_s, iic_y + ic_s), color, alpha=65, radius=13)
        d.rounded_rectangle((iic_x, iic_y, iic_x + ic_s, iic_y + ic_s),
                            radius=13, outline=border + (180,), width=2)
        _icon(d, iic_x + ic_s // 2, iic_y + ic_s // 2 + 1,
              blk.get("icon", I_INFO), 24, color)

        tx = iic_x + ic_s + 16
        d.text((tx, by1 + 16), blk.get("label", "").upper(), font=_font(12), fill=light)
        bv = blk.get("value", "—")
        bvf = _font(22)
        bv_shown = _el(d, str(bv), bvf, bx2 - 18 - tx)
        d.text((tx, by1 + 44), bv_shown, font=bvf, fill=color)


def _draw_chart(d, img, box, prices: List[float], color=TEAL, fill_alpha=60):
    """Рисует линейный график."""
    if not prices or len(prices) < 2:
        return

    x1, y1, x2, y2 = box
    pad_x = 20
    pad_y = 24
    ix1 = x1 + pad_x
    ix2 = x2 - pad_x
    iy1 = y1 + pad_y
    iy2 = y2 - pad_y

    w = ix2 - ix1
    h = iy2 - iy1

    minp = min(prices)
    maxp = max(prices)
    if maxp == minp:
        maxp = minp + 1.0

    coords = []
    n = len(prices)
    for i, p in enumerate(prices):
        px = ix1 + int(i * w / (n - 1))
        norm = (p - minp) / (maxp - minp)
        py = iy2 - int(norm * h)
        coords.append((px, py))

    # Полигон для заливки
    poly = coords + [(ix2, iy2), (ix1, iy2)]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.polygon(poly, fill=color + (fill_alpha,))

    # Градиент сверху → вниз внутри полигона
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)
    grad_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad_layer)
    for yy in range(int(iy1), int(iy2) + 1):
        t = (yy - iy1) / max(h, 1)
        a = int(fill_alpha * (1 - t))
        gd.line([(ix1, yy), (ix2, yy)], fill=color + (a,))
    grad_layer.putalpha(Image.composite(grad_layer.split()[3], Image.new("L", (W, H), 0), mask))
    img.paste(grad_layer, (0, 0), grad_layer)

    # Линия
    for i in range(len(coords) - 1):
        d.line([coords[i], coords[i + 1]], fill=color, width=3)

    # Точка на конце
    last = coords[-1]
    _alpha(img, (last[0] - 10, last[1] - 10, last[0] + 10, last[1] + 10),
           color, alpha=90, radius=10)
    d.ellipse((last[0] - 5, last[1] - 5, last[0] + 5, last[1] + 5), fill=color)

    # Min/Max подписи
    d.text((ix1, iy1 - 4), f"{_fmt_f(maxp, 1)}", font=_font(12), fill=MUTED, anchor="ls")
    d.text((ix1, iy2 + 4), f"{_fmt_f(minp, 1)}", font=_font(12), fill=MUTED, anchor="lt")


# ═══════════════════════════════════════════
# ЭКРАН 1: ГЛАВНАЯ
# ═══════════════════════════════════════════
def render_main(user_id: int) -> io.BytesIO:
    img, d = _canvas(user_id, "DCC+ · Главная")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 460
    gap = 28
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    price = get_price()
    supply = get_supply()
    holders = get_holders_count()
    wallet = get_wallet(user_id)

    balance_dcc = float(wallet["balance"])
    value_dc = balance_dcc * price

    history = get_price_history(hours=24, points=40)
    if len(history) >= 2:
        old = history[0]
        change_pct = ((price - old) / old * 100) if old else 0.0
    else:
        change_pct = 0.0

    change_color = GREEN if change_pct >= 0 else RED

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), [
        {"label": "Твой DCC+", "value": f"{_fmt_f(balance_dcc, 4)}", "icon": I_GEM, "color": TEAL},
        {"label": "В DC по курсу", "value": f"{_fmt(int(value_dc))} DC", "icon": I_COIN, "color": GREEN},
        {"label": "Всего холдеров", "value": f"{_fmt(holders)}", "icon": I_USERS, "color": BLUE},
        {"label": "В стейке", "value": f"{_fmt_f(sum(float(s['amount']) for s in get_active_stakes(user_id)), 4)} DCC+",
         "icon": I_LOCK, "color": GOLD},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    _right_head(d, rpx1, body_y + 22, rpx2, "Diamond Crypto+", "live курс")

    # ── КУРС ──
    rate_y = body_y + 100
    rate_h = 130

    _grad(img, (rpx1, rate_y, rpx2, rate_y + rate_h), TEAL, TEAL, alpha=15, radius=18)
    d.rounded_rectangle((rpx1, rate_y, rpx2, rate_y + rate_h), radius=18,
                        outline=TEAL + (200,), width=3)

    d.text((rpx1 + 24, rate_y + 20), "ТЕКУЩИЙ КУРС", font=_font(12), fill=TEAL)
    d.text((rpx1 + 24, rate_y + 42), f"{_fmt_f(price, 2)}", font=_font(52), fill=TEXT)
    pw = _tw(d, f"{_fmt_f(price, 2)}", _font(52))
    d.text((rpx1 + 24 + pw + 12, rate_y + 42 + 52 - 24),
           "DC / 1 DCC+", font=_font(20), fill=MUTED)

    # Изменение
    ch_x = rpx2 - 200
    _alpha(img, (ch_x, rate_y + 40, rpx2 - 24, rate_y + 90), change_color, alpha=40, radius=12)
    d.rounded_rectangle((ch_x, rate_y + 40, rpx2 - 24, rate_y + 90), radius=12,
                        outline=change_color + (180,), width=2)
    arrow = I_ARROW_UP if change_pct >= 0 else I_ARROW_DOWN
    _icon(d, ch_x + 30, rate_y + 65, arrow, 18, change_color)
    ch_text = f"{change_pct:+.2f}%"
    d.text((ch_x + 52, rate_y + 65), ch_text, font=_font(22), fill=change_color, anchor="lm")
    d.text((rpx2 - 24, rate_y + 100), "за 24 часа", font=_font(12), fill=MUTED, anchor="rt")

    # ── ГРАФИК ──
    chart_y = rate_y + rate_h + 20
    chart_h = 280

    _panel(img, d, (rpx1, chart_y, rpx2, chart_y + chart_h), radius=16)
    d.text((rpx1 + 24, chart_y + 20), "КУРС ЗА 24 ЧАСА",
           font=_font(13), fill=MUTED)

    _draw_chart(d, img, (rpx1 + 20, chart_y + 50, rpx2 - 20, chart_y + chart_h - 20),
                history, color=TEAL, fill_alpha=70)

    # ── СТАТИСТИКА ──
    stats_y = chart_y + chart_h + 20
    stat_h = 96
    stat_gap = 14
    cols = 3
    col_w = (rpx2 - rpx1 - stat_gap * (cols - 1)) // cols

    stats_data = [
        ("ЭМИССИЯ", f"{_fmt_f(supply, 0)} / {_fmt_f(MAX_SUPPLY, 0)}", TEAL),
        ("КОМИССИЯ ПРОДАЖИ", f"{int(SELL_COMMISSION * 100)}%", RED),
        ("ХОЛДЕРОВ", f"{_fmt(holders)}", BLUE),
    ]

    for i, (lbl, val, color) in enumerate(stats_data):
        cx1 = rpx1 + i * (col_w + stat_gap)
        cx2 = cx1 + col_w
        d.rounded_rectangle((cx1, stats_y, cx2, stats_y + stat_h), radius=14,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)
        d.text((cx1 + 18, stats_y + 16), lbl, font=_font(10), fill=MUTED)
        vf = _font(24)
        v_shown = _el(d, val, vf, cx2 - cx1 - 36)
        d.text((cx1 + 18, stats_y + 44), v_shown, font=vf, fill=color)

    _footer(d, "Курс обновляется каждые 15 минут", "стр. 1 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════
# ЭКРАН 2: МОИ АКТИВЫ
# ═══════════════════════════════════════════
def render_my_assets(user_id: int) -> io.BytesIO:
    img, d = _canvas(user_id, "DCC+ · Мои активы")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 460
    gap = 28
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    price = get_price()
    wallet = get_wallet(user_id)
    balance = float(wallet["balance"])
    invested = float(wallet["total_invested"] or 0)
    returned = float(wallet["total_returned"] or 0)
    active = get_active_stakes(user_id)
    staked = sum(float(s["amount"]) for s in active)
    total_dcc = balance + staked
    total_value = total_dcc * price

    # PnL от входа
    if invested > 0:
        pnl_dc = total_value - invested
        pnl_pct = (pnl_dc / invested * 100)
    else:
        pnl_dc = 0.0
        pnl_pct = 0.0

    pnl_color = GREEN if pnl_dc >= 0 else RED

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), [
        {"label": "Средняя цена входа", "value": f"{_fmt_f(invested / wallet['total_bought'], 2) if wallet['total_bought'] else '—'} DC",
         "icon": I_CHART_LINE, "color": TEAL},
        {"label": "Всего куплено", "value": f"{_fmt_f(wallet['total_bought'] or 0, 4)} DCC+", "icon": I_COIN, "color": BLUE},
        {"label": "Всего продано", "value": f"{_fmt_f(wallet['total_sold'] or 0, 4)} DCC+", "icon": I_HAND, "color": GOLD},
        {"label": "Активных стейков", "value": f"{len(active)} / {STAKE_MAX_ACTIVE}", "icon": I_LOCK, "color": PURPLE},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    _right_head(d, rpx1, body_y + 22, rpx2, "Мои активы", "портфель · PnL · стейки")

    # HERO
    hero_y = body_y + 100
    hero_h = 150

    _grad(img, (rpx1, hero_y, rpx2, hero_y + hero_h), TEAL, TEAL_DK, alpha=22, radius=18)
    d.rounded_rectangle((rpx1, hero_y, rpx2, hero_y + hero_h), radius=18,
                        outline=TEAL + (200,), width=3)

    # Иконка
    es = 100
    ex = rpx1 + 24
    ey = hero_y + (hero_h - es) // 2
    _grad_radial_circle(img, ex + es // 2, ey + es // 2, es // 2, TEAL, TEAL_DK, alpha=255)
    d.ellipse((ex, ey, ex + es, ey + es), outline=(255, 255, 255, 80), width=2)
    _icon(d, ex + es // 2, ey + es // 2 + 2, I_GEM, 44, (255, 255, 255))

    tx = ex + es + 24
    d.text((tx, hero_y + 24), "ВСЕГО DCC+", font=_font(12), fill=TEAL)
    d.text((tx, hero_y + 44), f"{_fmt_f(total_dcc, 4)}", font=_font(46), fill=TEXT)
    d.text((tx, hero_y + 106), f"Свободно: {_fmt_f(balance, 4)} · В стейке: {_fmt_f(staked, 4)}",
           font=_font(13), fill=MUTED)

    # Правая часть — стоимость
    rx_right = rpx2 - 24
    d.text((rx_right, hero_y + 24), "В DC ПО КУРСУ", font=_font(12), fill=TEAL, anchor="rt")
    d.text((rx_right, hero_y + 44), f"{_fmt(int(total_value))} DC",
           font=_font(34), fill=TEXT, anchor="rt")

    # PnL
    pnl_y = hero_y + 96
    _alpha(img, (rx_right - 220, pnl_y, rx_right, pnl_y + 38),
           pnl_color, alpha=35, radius=10)
    d.rounded_rectangle((rx_right - 220, pnl_y, rx_right, pnl_y + 38), radius=10,
                        outline=pnl_color + (180,), width=2)
    arr = I_ARROW_UP if pnl_dc >= 0 else I_ARROW_DOWN
    _icon(d, rx_right - 200, pnl_y + 19, arr, 16, pnl_color)
    d.text((rx_right - 180, pnl_y + 19), f"{pnl_pct:+.2f}% · {_fmt(int(pnl_dc))} DC",
           font=_font(16), fill=pnl_color, anchor="lm")

    # ── СТЕЙКИ ──
    stakes_y = hero_y + hero_h + 20
    d.text((rpx1, stakes_y), "🔒 АКТИВНЫЕ СТЕЙКИ",
           font=_font(13), fill=MUTED)
    stakes_list_y = stakes_y + 30

    stakes_bottom = body_y + body_h - 22
    max_stakes = 3
    row_h = 100
    row_gap = 10

    for i in range(max_stakes):
        cy = stakes_list_y + i * (row_h + row_gap)
        if cy + row_h > stakes_bottom:
            break

        if i < len(active):
            s = active[i]
            amount = float(s["amount"])
            days = int(s["days"])
            pct = float(s["profit_pct"])
            unlock = int(s["unlock_at"])
            started = int(s["started_at"])
            now = int(time.time())
            total_dur = unlock - started
            progress = min(max((now - started) / max(total_dur, 1), 0), 1)
            profit = amount * pct
            left = unlock - now
            h = left // 3600
            m = (left % 3600) // 60

            _grad(img, (rpx1, cy, rpx2, cy + row_h), TEAL, TEAL, alpha=10, radius=14)
            d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=14,
                                outline=TEAL + (170,), width=2)

            _alpha(img, (rpx1 + 18, cy + 22, rpx1 + 70, cy + 74), TEAL, alpha=45, radius=13)
            _icon(d, rpx1 + 44, cy + 48, I_LOCK, 26, TEAL)

            tx = rpx1 + 88
            d.text((tx, cy + 18), f"Стейк на {days} дней · +{int(pct*100)}%",
                   font=_font(16), fill=TEXT)
            d.text((tx, cy + 42), f"Застейкано {_fmt_f(amount, 4)} DCC+ · разлоч {_fmt_time(unlock)}",
                   font=_font(12), fill=MUTED)

            # Прогресс-бар
            bar_y = cy + 70
            bar_x1 = tx
            bar_x2 = tx + 380
            bar_h = 10
            d.rounded_rectangle((bar_x1, bar_y, bar_x2, bar_y + bar_h),
                                radius=bar_h // 2, fill=(28, 28, 34))
            fill_w = int((bar_x2 - bar_x1) * progress)
            if fill_w > 0:
                _grad(img, (bar_x1, bar_y, bar_x1 + fill_w, bar_y + bar_h),
                      TEAL, TEAL_DK, alpha=255, radius=bar_h // 2)

            # Профит справа
            rx = rpx2 - 24
            d.text((rx, cy + 20), f"+{_fmt_f(profit, 4)} DCC+",
                   font=_font(20), fill=GREEN, anchor="rt")
            d.text((rx, cy + 48), f"осталось {h}ч {m}м",
                   font=_font(12), fill=MUTED, anchor="rt")
        else:
            d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=14,
                                fill=(20, 20, 26) + (255,),
                                outline=INNER_BRD + (255,), width=2)
            for j in range(int(rpx2 - rpx1) - 40):
                if j % 14 < 7:
                    d.point((rpx1 + 20 + j, cy + 5), fill=INNER_BRD)
                    d.point((rpx1 + 20 + j, cy + row_h - 6), fill=INNER_BRD)

            _alpha(img, (rpx1 + 18, cy + 22, rpx1 + 70, cy + 74),
                   SILVER, alpha=20, radius=13)
            _icon(d, rpx1 + 44, cy + 48, I_PLUS, 26, SILVER)
            d.text((rpx1 + 88, cy + 34), "Свободный слот для стейка",
                   font=_font(16), fill=MUTED)
            d.text((rpx1 + 88, cy + 58), "Открой через кнопку «Стейк»",
                   font=_font(12), fill=DIM)

    _footer(d, "Данные обновляются автоматически", "стр. 2 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════
# ЭКРАН 3: СТЕЙК
# ═══════════════════════════════════════════
def render_stake(user_id: int) -> io.BytesIO:
    img, d = _canvas(user_id, "DCC+ · Стейкинг")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    price = get_price()
    wallet = get_wallet(user_id)
    balance = float(wallet["balance"])

    # Заголовок сверху
    title_h = 90
    _grad(img, (PX, body_y, W - M - PX, body_y + title_h), TEAL, TEAL, alpha=12, radius=18)
    d.rounded_rectangle((PX, body_y, W - M - PX, body_y + title_h), radius=18,
                        outline=TEAL + (180,), width=2)

    d.text((PX + 30, body_y + 22), "🔒 ВЫБЕРИ СРОК СТЕЙКА",
           font=_font(22), fill=TEXT)
    d.text((PX + 30, body_y + 54),
           f"В кошельке: {_fmt_f(balance, 4)} DCC+ · курс {_fmt_f(price, 2)} DC",
           font=_font(14), fill=MUTED)

    d.text((W - M - PX - 30, body_y + 30), f"Минимум: {STAKE_MIN} DCC+",
           font=_font(13), fill=MUTED, anchor="rt")
    d.text((W - M - PX - 30, body_y + 52), f"Макс: {STAKE_MAX_ONE} DCC+ · до {STAKE_MAX_ACTIVE} стейков",
           font=_font(13), fill=MUTED, anchor="rt")

    # 3 карточки
    cards_y = body_y + title_h + 24
    cards_bottom = body_y + body_h - 22
    cards_h = cards_bottom - cards_y

    gap = 20
    col_w = (W - M * 2 - PX * 2 - gap * 2) // 3

    plans = [(7, STAKE_PLANS[7]), (14, STAKE_PLANS[14]), (30, STAKE_PLANS[30])]
    popular = 14

    for i, (days, pct) in enumerate(plans):
        cx1 = PX + i * (col_w + gap)
        cx2 = cx1 + col_w

        is_pop = (days == popular)
        color = GOLD if is_pop else TEAL
        light = _lighten(color, 0.4)
        border = _lighten(color, 0.25)

        _grad(img, (cx1, cards_y, cx2, cards_y + cards_h), color, color, alpha=15, radius=22)
        d.rounded_rectangle((cx1, cards_y, cx2, cards_y + cards_h), radius=22,
                            outline=border + (200,), width=3)

        if is_pop:
            d.rounded_rectangle((cx1, cards_y, cx2, cards_y + 42), radius=0,
                                fill=color + (230,))
            d.rounded_rectangle((cx1, cards_y, cx2, cards_y + 42), corners=(22, 22, 0, 0),
                                fill=color + (230,))
            d.text(((cx1 + cx2) // 2, cards_y + 21), "★ ПОПУЛЯРНО",
                   font=_font(14), fill=(0, 0, 0), anchor="mm")

        # Иконка
        ic_cy = cards_y + 130
        _grad_radial_circle(img, (cx1 + cx2) // 2, ic_cy, 60, color, color, alpha=90)
        d.ellipse(((cx1 + cx2) // 2 - 60, ic_cy - 60,
                   (cx1 + cx2) // 2 + 60, ic_cy + 60),
                  outline=border + (255,), width=3)
        _icon(d, (cx1 + cx2) // 2, ic_cy + 2, I_LOCK, 52, light)

        # Дни
        days_text = f"{days} ДНЕЙ"
        dw = _tw(d, days_text, _font(16))
        d.text(((cx1 + cx2) // 2 - dw // 2, cards_y + 210),
               days_text, font=_font(16), fill=MUTED)

        # Большое число дней
        num_f = _font(64)
        nw = _tw(d, str(days), num_f)
        d.text(((cx1 + cx2) // 2 - nw // 2, cards_y + 232),
               str(days), font=num_f, fill=TEXT)

        # Процент
        d.text(((cx1 + cx2) // 2, cards_y + 320),
               "ПРОФИТ", font=_font(12), fill=MUTED, anchor="mm")
        pct_f = _font(52)
        pct_text = f"+{int(pct*100)}%"
        pw = _tw(d, pct_text, pct_f)
        d.text(((cx1 + cx2) // 2 - pw // 2, cards_y + 342),
               pct_text, font=pct_f, fill=GREEN)

        # Пример
        example_y = cards_y + cards_h - 180
        d.rounded_rectangle((cx1 + 24, example_y, cx2 - 24, example_y + 160),
                            radius=14, fill=(0, 0, 0, 60))
        d.rounded_rectangle((cx1 + 24, example_y, cx2 - 24, example_y + 160),
                            radius=14, outline=INNER_BRD + (255,), width=2)

        ex_texts = [
            ("Вкладываешь:", "100 DCC+", TEXT),
            (f"Через {days} дн:", f"{100 + int(100 * pct)} DCC+", GREEN),
            ("Прибыль в DC:", f"+{int(100 * pct * price)} DC", GREEN),
        ]
        for j, (lbl, val, col) in enumerate(ex_texts):
            y = example_y + 22 + j * 42
            d.text((cx1 + 44, y), lbl, font=_font(13), fill=MUTED)
            vf = _font(18)
            vw = _tw(d, val, vf)
            d.text((cx2 - 44 - vw, y - 2), val, font=vf, fill=col)

    _footer(d, "Досрочное снятие — штраф 10% от тела стейка", "стр. 3 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════
# ЭКРАН 4: ОБМЕН (купить / продать)
# ═══════════════════════════════════════════
def render_trade(user_id: int, mode: str = "buy",
                 preview_dc: int = 0, preview_dcc: float = 0.0) -> io.BytesIO:
    """
    mode: 'buy' | 'sell'
    Для buy: preview_dc — сколько юзер хочет потратить DC
    Для sell: preview_dcc — сколько юзер хочет продать DCC+
    """
    img, d = _canvas(user_id, f"DCC+ · {'Купить' if mode == 'buy' else 'Продать'}")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 460
    gap = 28
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    price = get_price()
    wallet = get_wallet(user_id)
    balance_dcc = float(wallet["balance"])

    from core.utils import get_dc_cache
    balance_dc = get_dc_cache(user_id).get("balance", 0)

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), [
        {"label": "Твой DC", "value": f"{_fmt(balance_dc)} DC", "icon": I_COIN, "color": GREEN},
        {"label": "Твой DCC+", "value": f"{_fmt_f(balance_dcc, 4)}", "icon": I_GEM, "color": TEAL},
        {"label": "Курс", "value": f"{_fmt_f(price, 2)} DC", "icon": I_CHART_LINE, "color": BLUE},
        {"label": "Комиссия продажи", "value": f"{int(SELL_COMMISSION * 100)}%", "icon": I_HAND, "color": RED},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    title = "КУПИТЬ DCC+" if mode == "buy" else "ПРОДАТЬ DCC+"
    sub = "обмен DC → DCC+" if mode == "buy" else "обмен DCC+ → DC"
    _right_head(d, rpx1, body_y + 22, rpx2, title, sub)

    # Таб
    tabs_y = body_y + 100
    tab_w = 200
    tab_h = 48

    for i, (lbl, m) in enumerate([("💎 Купить", "buy"), ("💰 Продать", "sell")]):
        tb_x = rpx1 + i * (tab_w + 10)
        active = (m == mode)
        if active:
            _alpha(img, (tb_x, tabs_y, tb_x + tab_w, tabs_y + tab_h),
                   TEAL if m == "buy" else RED, alpha=40, radius=12)
            d.rounded_rectangle((tb_x, tabs_y, tb_x + tab_w, tabs_y + tab_h),
                                radius=12,
                                outline=(TEAL if m == "buy" else RED) + (200,), width=2)
            col = TEAL if m == "buy" else RED
        else:
            d.rounded_rectangle((tb_x, tabs_y, tb_x + tab_w, tabs_y + tab_h),
                                radius=12, fill=INNER_BG + (255,),
                                outline=INNER_BRD + (255,), width=2)
            col = MUTED
        tw_ = _tw(d, lbl, _font(16))
        d.text((tb_x + tab_w // 2 - tw_ // 2, tabs_y + 14),
               lbl, font=_font(16), fill=col)

    # Поля обмена
    field_y = tabs_y + tab_h + 20
    field_h = 110
    field_gap = 20

    if mode == "buy":
        dcc_received = preview_dc / price if price > 0 else 0.0

        # from DC
        _grad(img, (rpx1, field_y, rpx2, field_y + field_h), GREEN, GREEN, alpha=10, radius=16)
        d.rounded_rectangle((rpx1, field_y, rpx2, field_y + field_h), radius=16,
                            outline=GREEN + (170,), width=2)
        d.text((rpx1 + 24, field_y + 20), "ТЫ ОТДАЁШЬ",
               font=_font(13), fill=GREEN)
        d.text((rpx1 + 24, field_y + 44),
               f"{_fmt(preview_dc) if preview_dc > 0 else '—'}",
               font=_font(42), fill=TEXT)
        d.text((rpx2 - 24, field_y + 44), "DC",
               font=_font(24), fill=GREEN, anchor="rt")
        d.text((rpx2 - 24, field_y + 76), f"Баланс: {_fmt(balance_dc)} DC",
               font=_font(13), fill=MUTED, anchor="rt")

        # arrow
        arr_y = field_y + field_h + 10
        _alpha(img, ((rpx1 + rpx2) // 2 - 30, arr_y,
                     (rpx1 + rpx2) // 2 + 30, arr_y + 40),
               TEAL, alpha=40, radius=20)
        _icon(d, (rpx1 + rpx2) // 2, arr_y + 20, I_ARROW_DOWN, 22, TEAL)

        # to DCC
        field2_y = arr_y + 50
        _grad(img, (rpx1, field2_y, rpx2, field2_y + field_h), TEAL, TEAL, alpha=15, radius=16)
        d.rounded_rectangle((rpx1, field2_y, rpx2, field2_y + field_h), radius=16,
                            outline=TEAL + (200,), width=2)
        d.text((rpx1 + 24, field2_y + 20), "ТЫ ПОЛУЧАЕШЬ",
               font=_font(13), fill=TEAL)
        d.text((rpx1 + 24, field2_y + 44),
               f"{_fmt_f(dcc_received, 4) if dcc_received > 0 else '—'}",
               font=_font(42), fill=TEAL)
        d.text((rpx2 - 24, field2_y + 44), "DCC+",
               font=_font(24), fill=TEAL, anchor="rt")
        d.text((rpx2 - 24, field2_y + 76), f"по курсу {_fmt_f(price, 2)} DC",
               font=_font(13), fill=MUTED, anchor="rt")

        info_y = field2_y + field_h + 24
    else:
        dc_received_gross = preview_dcc * price
        fee = dc_received_gross * SELL_COMMISSION
        dc_received_net = dc_received_gross - fee

        # from DCC
        _grad(img, (rpx1, field_y, rpx2, field_y + field_h), TEAL, TEAL, alpha=10, radius=16)
        d.rounded_rectangle((rpx1, field_y, rpx2, field_y + field_h), radius=16,
                            outline=TEAL + (170,), width=2)
        d.text((rpx1 + 24, field_y + 20), "ТЫ ОТДАЁШЬ",
               font=_font(13), fill=TEAL)
        d.text((rpx1 + 24, field_y + 44),
               f"{_fmt_f(preview_dcc, 4) if preview_dcc > 0 else '—'}",
               font=_font(42), fill=TEXT)
        d.text((rpx2 - 24, field_y + 44), "DCC+",
               font=_font(24), fill=TEAL, anchor="rt")
        d.text((rpx2 - 24, field_y + 76), f"Кошелёк: {_fmt_f(balance_dcc, 4)}",
               font=_font(13), fill=MUTED, anchor="rt")

        arr_y = field_y + field_h + 10
        _alpha(img, ((rpx1 + rpx2) // 2 - 30, arr_y,
                     (rpx1 + rpx2) // 2 + 30, arr_y + 40),
               RED, alpha=40, radius=20)
        _icon(d, (rpx1 + rpx2) // 2, arr_y + 20, I_ARROW_DOWN, 22, RED)

        field2_y = arr_y + 50
        _grad(img, (rpx1, field2_y, rpx2, field2_y + field_h), GREEN, GREEN, alpha=15, radius=16)
        d.rounded_rectangle((rpx1, field2_y, rpx2, field2_y + field_h), radius=16,
                            outline=GREEN + (200,), width=2)
        d.text((rpx1 + 24, field2_y + 20), "ТЫ ПОЛУЧАЕШЬ",
               font=_font(13), fill=GREEN)
        d.text((rpx1 + 24, field2_y + 44),
               f"{_fmt(int(dc_received_net)) if preview_dcc > 0 else '—'}",
               font=_font(42), fill=GREEN)
        d.text((rpx2 - 24, field2_y + 44), "DC",
               font=_font(24), fill=GREEN, anchor="rt")
        d.text((rpx2 - 24, field2_y + 76),
               f"−{int(fee)} комиссия (3%)",
               font=_font(13), fill=RED, anchor="rt")

        info_y = field2_y + field_h + 24

    # Инфо
    if info_y + 130 <= body_y + body_h - 22:
        d.rounded_rectangle((rpx1, info_y, rpx2, info_y + 120),
                            radius=14, fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)
        d.text((rpx1 + 22, info_y + 16), "ЛИМИТЫ И ПРАВИЛА",
               font=_font(12), fill=MUTED)

        rows = [
            ("Мин. покупка", f"{MIN_BUY_DC} DC"),
            ("Макс. покупка в день", f"{_fmt(MAX_BUY_DC_DAY)} DC"),
            ("Макс. продажа в час", f"{int(MAX_SELL_DCC_HOUR)} DCC+"),
            ("Кулдаун между сделками", "60 сек"),
        ]
        for i, (lbl, val) in enumerate(rows):
            y = info_y + 42 + i * 20
            d.text((rpx1 + 22, y), lbl, font=_font(12), fill=MUTED)
            vw = _tw(d, val, _font(12))
            d.text((rpx2 - 22 - vw, y), val, font=_font(12), fill=TEXT_SOFT)

    _footer(d, "Используй селект внизу чтобы выбрать действие", "стр. 4 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════
# ЭКРАН 5: ТОП ХОЛДЕРОВ
# ═══════════════════════════════════════════
def render_top(user_id: int) -> io.BytesIO:
    img, d = _canvas(user_id, "DCC+ · Топ холдеров")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 460
    gap = 28
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    price = get_price()
    holders = get_holders_count()
    my_place = get_user_place(user_id)
    my_wallet = get_wallet(user_id)
    my_balance = float(my_wallet["balance"])
    my_invested = float(my_wallet["total_invested"] or 0)
    my_value = my_balance * price
    my_pnl_pct = ((my_value - my_invested) / my_invested * 100) if my_invested > 0 else 0.0

    top = get_top_holders(limit=8)

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), [
        {"label": "Твоё место", "value": f"#{my_place}" if my_place else "—",
         "icon": I_TROPHY, "color": GOLD},
        {"label": "Твой DCC+", "value": f"{_fmt_f(my_balance, 4)}", "icon": I_GEM, "color": TEAL},
        {"label": "Твой PnL", "value": f"{my_pnl_pct:+.2f}%" if my_invested > 0 else "—",
         "icon": I_CHART_LINE, "color": GREEN if my_pnl_pct >= 0 else RED},
        {"label": "Всего холдеров", "value": f"{_fmt(holders)}", "icon": I_USERS, "color": BLUE},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    _right_head(d, rpx1, body_y + 22, rpx2, "Топ холдеров", "по DCC+ на кошельке")

    # Header с инфой
    head_y = body_y + 100
    head_h = 70

    _grad(img, (rpx1, head_y, rpx2, head_y + head_h), TEAL, TEAL, alpha=12, radius=14)
    d.rounded_rectangle((rpx1, head_y, rpx2, head_y + head_h), radius=14,
                        outline=TEAL + (170,), width=2)

    d.text((rpx1 + 24, head_y + 16), "🏆 ТОП ПО КОЛИЧЕСТВУ DCC+",
           font=_font(15), fill=TEAL)
    d.text((rpx1 + 24, head_y + 40), f"Всего холдеров: {_fmt(holders)}",
           font=_font(13), fill=MUTED)

    if my_place:
        d.text((rpx2 - 24, head_y + 16), "ТВОЁ МЕСТО",
               font=_font(12), fill=MUTED, anchor="rt")
        d.text((rpx2 - 24, head_y + 32), f"#{my_place}",
               font=_font(24), fill=GOLD, anchor="rt")

    # Список
    list_y = head_y + head_h + 16
    list_bottom = body_y + body_h - 22

    if not top:
        cx = (rpx1 + rpx2) // 2
        cy = (list_y + list_bottom) // 2
        _alpha(img, (cx - 60, cy - 60, cx + 60, cy + 60), TEAL, alpha=20, radius=30)
        _icon(d, cx, cy - 30, I_TROPHY, 52, TEAL)
        d.text((cx, cy + 70), "Пока нет холдеров",
               font=_font(22), fill=TEXT, anchor="mm")
        d.text((cx, cy + 106), "Купи первый DCC+ — займи топ-1",
               font=_font(14), fill=MUTED, anchor="mm")
    else:
        rows = min(len(top), 8)
        row_gap = 8
        row_h = (list_bottom - list_y - row_gap * (rows - 1)) // rows
        row_h = min(row_h, 80)

        for i, entry in enumerate(top):
            cy = list_y + i * (row_h + row_gap)
            if cy + row_h > list_bottom:
                break

            rank = i + 1
            is_me = entry["user_id"] == user_id

            if rank == 1:
                medal = GOLD
            elif rank == 2:
                medal = SILVER
            elif rank == 3:
                medal = BRONZE
            else:
                medal = DIM

            if is_me:
                _grad(img, (rpx1, cy, rpx2, cy + row_h), BLUE, BLUE, alpha=12, radius=12)
                d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=12,
                                    outline=BLUE + (200,), width=2)
            elif rank <= 3:
                _grad(img, (rpx1, cy, rpx2, cy + row_h), medal, medal, alpha=12, radius=12)
                d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=12,
                                    outline=medal + (180,), width=2)
            else:
                d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=12,
                                    fill=INNER_BG + (255,),
                                    outline=INNER_BRD + (255,), width=2)

            # Медаль
            bs = 44
            bx = rpx1 + 16
            by = cy + (row_h - bs) // 2
            _alpha(img, (bx, by, bx + bs, by + bs), medal, alpha=55, radius=11)
            d.rounded_rectangle((bx, by, bx + bs, by + bs), radius=11,
                                outline=medal + (200,), width=2)
            if rank <= 3:
                _icon(d, bx + bs // 2, by + bs // 2 + 1,
                      I_CROWN if rank == 1 else I_MEDAL, 20, medal)
            else:
                num_str = str(rank)
                nf = _font(18)
                nw = _tw(d, num_str, nf)
                d.text((bx + bs // 2 - nw // 2, by + bs // 2 - nf.size // 2 - 2),
                       num_str, font=nf, fill=medal)

            # Имя
            tx = bx + bs + 16
            name = f"@{entry['user_id']}"
            if is_me:
                name += " · это ты"
            name_f = _font(17)
            max_w = rpx2 - tx - 420
            name_shown = _el(d, name, name_f, max_w)
            d.text((tx, cy + 14), name_shown, font=name_f,
                   fill=BLUE if is_me else TEXT)
            d.text((tx, cy + 38), f"Инвестировано: {_fmt(int(entry['invested']))} DC",
                   font=_font(12), fill=MUTED)

            # Стоимость
            val_str = f"{_fmt_f(entry['balance'], 4)} DCC+"
            vw = _tw(d, val_str, _font(20))
            d.text((rpx2 - 200 - vw, cy + 14), val_str,
                   font=_font(20), fill=TEAL)
            d.text((rpx2 - 200, cy + 14), f"≈ {_fmt(int(entry['current_value']))} DC",
                   font=_font(14), fill=MUTED, anchor="rt")

            # PnL
            pnl = entry["pnl_pct"]
            pnl_c = GREEN if pnl >= 0 else RED
            pnl_str = f"{pnl:+.2f}%"
            pnl_f = _font(18)
            pw = _tw(d, pnl_str, pnl_f)
            d.text((rpx2 - 24 - pw, cy + 14), pnl_str, font=pnl_f, fill=pnl_c)

    _footer(d, "Топ обновляется автоматически", "стр. 5 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════
# ЭКРАН 6: ИСТОРИЯ КУРСА
# ═══════════════════════════════════════════
def render_history(user_id: int) -> io.BytesIO:
    img, d = _canvas(user_id, "DCC+ · История курса")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 460
    gap = 28
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    price = get_price()
    supply = get_supply()
    stats = get_stats_24h()
    recent = get_recent_transactions(limit=5)

    # История за 7 дней
    history_7d = get_price_history(hours=24 * 7, points=80)

    if history_7d:
        old = history_7d[0]
        ch_pct = ((price - old) / old * 100) if old else 0
        min_p = min(history_7d)
        max_p = max(history_7d)
    else:
        old = price
        ch_pct = 0
        min_p = price
        max_p = price

    ch_color = GREEN if ch_pct >= 0 else RED

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), [
        {"label": "Курс сейчас", "value": f"{_fmt_f(price, 2)} DC", "icon": I_CHART_LINE, "color": TEAL},
        {"label": "За 7 дней", "value": f"{ch_pct:+.2f}%", "icon": I_ARROW_UP if ch_pct >= 0 else I_ARROW_DOWN,
         "color": ch_color},
        {"label": "Мин / Макс", "value": f"{_fmt_f(min_p,1)} / {_fmt_f(max_p,1)}", "icon": I_BOLT, "color": BLUE},
        {"label": "Эмиссия", "value": f"{_fmt_f(supply,0)} / {_fmt_f(MAX_SUPPLY,0)}", "icon": I_GEM, "color": GOLD},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    _right_head(d, rpx1, body_y + 22, rpx2, "История курса", "7 дней · сделки · статистика")

    # График
    chart_y = body_y + 100
    chart_h = 380

    _panel(img, d, (rpx1, chart_y, rpx2, chart_y + chart_h), radius=16)
    d.text((rpx1 + 24, chart_y + 20), "📈 DCC+ / DC ЗА 7 ДНЕЙ",
           font=_font(15), fill=TEXT)
    d.text((rpx2 - 24, chart_y + 20), f"{ch_pct:+.2f}% за период",
           font=_font(14), fill=ch_color, anchor="rt")

    _draw_chart(d, img, (rpx1 + 20, chart_y + 50, rpx2 - 20, chart_y + chart_h - 20),
                history_7d, color=TEAL, fill_alpha=80)

    # Мини-статы под графиком
    stats_y = chart_y + chart_h + 20
    stats_h = 100
    stat_gap = 14
    cols = 4
    col_w = (rpx2 - rpx1 - stat_gap * (cols - 1)) // cols

    stat_items = [
        ("СТАРТ 7Д", f"{_fmt_f(old, 2)} DC", SILVER),
        ("МИНИМУМ", f"{_fmt_f(min_p, 2)} DC", RED),
        ("МАКСИМУМ", f"{_fmt_f(max_p, 2)} DC", GREEN),
        ("СЕЙЧАС", f"{_fmt_f(price, 2)} DC", TEAL),
    ]

    for i, (lbl, val, color) in enumerate(stat_items):
        cx1 = rpx1 + i * (col_w + stat_gap)
        cx2 = cx1 + col_w
        d.rounded_rectangle((cx1, stats_y, cx2, stats_y + stats_h),
                            radius=14, fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)
        d.text((cx1 + 16, stats_y + 16), lbl, font=_font(10), fill=MUTED)
        vf = _font(20)
        v_shown = _el(d, val, vf, cx2 - cx1 - 32)
        d.text((cx1 + 16, stats_y + 40), v_shown, font=vf, fill=color)

        # Нижняя подпись
        if lbl == "СЕЙЧАС":
            d.text((cx1 + 16, stats_y + 70), f"{ch_pct:+.2f}%",
                   font=_font(13), fill=ch_color)
        elif lbl == "СТАРТ 7Д":
            d.text((cx1 + 16, stats_y + 70), "начало",
                   font=_font(12), fill=MUTED)
        elif lbl == "МИНИМУМ":
            d.text((cx1 + 16, stats_y + 70), "за 7 дней",
                   font=_font(12), fill=MUTED)
        elif lbl == "МАКСИМУМ":
            d.text((cx1 + 16, stats_y + 70), "за 7 дней",
                   font=_font(12), fill=MUTED)

    # Статистика 24ч + последние сделки
    info_y = stats_y + stats_h + 20
    info_bottom = body_y + body_h - 22

    if info_y + 160 <= info_bottom:
        # Делю на 2 части
        half_w = (rpx2 - rpx1 - 20) // 2

        # Левая — статистика 24ч
        d.rounded_rectangle((rpx1, info_y, rpx1 + half_w, info_bottom),
                            radius=14, fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)
        d.text((rpx1 + 20, info_y + 16), "📊 СТАТИСТИКА 24Ч",
               font=_font(13), fill=MUTED)

        stats_rows = [
            ("Куплено DCC+", f"{_fmt_f(stats['buys'], 2)}", GREEN),
            ("Продано DCC+", f"{_fmt_f(stats['sells'], 2)}", RED),
            ("Чистый поток", f"{stats['net_flow']:+.2f}", GREEN if stats['net_flow'] >= 0 else RED),
            ("Объём в DC", f"{_fmt(int(stats['volume_dc']))} DC", TEXT_SOFT),
            ("Сожжено комиссий", f"{_fmt_f(stats['fee_burned'], 2)} DCC+", GOLD),
        ]

        for i, (lbl, val, col) in enumerate(stats_rows):
            y = info_y + 48 + i * 26
            if y > info_bottom - 22:
                break
            d.text((rpx1 + 20, y), lbl, font=_font(12), fill=MUTED)
            vw = _tw(d, val, _font(13))
            d.text((rpx1 + half_w - 20 - vw, y), val, font=_font(13), fill=col)

        # Правая — последние сделки
        d.rounded_rectangle((rpx1 + half_w + 20, info_y, rpx2, info_bottom),
                            radius=14, fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)
        d.text((rpx1 + half_w + 40, info_y + 16), "💰 ПОСЛЕДНИЕ СДЕЛКИ",
               font=_font(13), fill=MUTED)

        type_map = {
            "buy": (I_GEM, GREEN, "купил"),
            "sell": (I_HAND, RED, "продал"),
            "stake": (I_LOCK, TEAL, "стейкнул"),
        }

        for i, tx in enumerate(recent[:5]):
            y = info_y + 48 + i * 26
            if y > info_bottom - 22:
                break

            icon, col, label = type_map.get(tx["type"], (I_GEM, SILVER, tx["type"]))
            _alpha(img, (rpx1 + half_w + 40, y - 2, rpx1 + half_w + 66, y + 24),
                   col, alpha=45, radius=7)
            _icon(d, rpx1 + half_w + 53, y + 11, icon, 12, col)

            d.text((rpx1 + half_w + 76, y), f"@{tx['user_id']} · {label}",
                   font=_font(12), fill=TEXT_SOFT)

            val = f"{_fmt_f(tx['amount'], 2)} DCC+"
            vw = _tw(d, val, _font(13))
            d.text((rpx2 - 20 - vw, y), val, font=_font(13), fill=col)

    _footer(d, "Все сделки логируются · обновление раз в час", "стр. 6 / 6")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
