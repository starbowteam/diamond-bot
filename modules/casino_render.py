# -*- coding: utf-8 -*-
"""
Pillow-рендер казино. 1800×1000, только FA-иконки.

Экспортирует:
  render_roulette_spin / render_roulette_win / render_roulette_lose
  render_blackjack_table / render_blackjack_result
  render_coinflip_choice / render_coinflip_win / render_coinflip_lose
"""
import io
import os
from typing import Optional, List, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, logger


FONT_BOLD = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_F_CACHE: dict = {}
_FA_CACHE: dict = {}


def _font(sz):
    if sz in _F_CACHE: return _F_CACHE[sz]
    try:    f = ImageFont.truetype(FONT_BOLD, sz)
    except Exception: f = ImageFont.load_default()
    _F_CACHE[sz] = f; return f


def _fa(sz):
    if sz in _FA_CACHE: return _FA_CACHE[sz]
    f = None
    if os.path.exists(FONT_FA):
        try: f = ImageFont.truetype(FONT_FA, sz)
        except Exception: pass
    _FA_CACHE[sz] = f; return f


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

SILVER      = (198, 208, 224)
SILVER_HI   = (224, 232, 245)
SILVER_DIM  = (120, 132, 155)

GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)
GOLD      = (247, 201, 145)

CARD_BRD  = (74, 74, 79)


# FA5/6 иконки (solid)
I_GEM        = 0xf3a5
I_COINS      = 0xf51e
I_TROPHY     = 0xf091
I_TREND_DOWN = 0xe097
I_SHIELD     = 0xf3ed
I_CLOCK      = 0xf017
I_ROTATE     = 0xf2ea
I_INFO       = 0xf05a
I_CHECK_C    = 0xf058
I_XMARK_C    = 0xf057
I_BOLT       = 0xf0e7
I_HANDSHAKE  = 0xf2b5
I_ROTATE_L   = 0xf2ea
I_HAND       = 0xf256
I_CROW       = 0xf520
I_CROWN      = 0xf521
I_USER       = 0xf007
I_USER_SEC   = 0xf21b
I_SPADE      = 0xf2f4
I_HEART      = 0xf004
I_DIAMOND    = 0xf219
I_CLUB       = 0xf327
I_QUESTION   = 0xf128
I_HAND_R     = 0xf0a4
I_PERCENT    = 0xf295
I_CIRCLE     = 0xf111
I_ARROW_DOWN = 0xf063


# Утилиты
def _tw(d, t, f):
    b = d.textbbox((0, 0), t, font=f); return b[2] - b[0]


def _icon(d, cx, cy, code, size, color):
    f = _fa(size)
    if f is None: return
    try: d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception: pass


def _alpha_fill(base, box, color, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if radius > 0:
        ld.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=color + (alpha,))
    else:
        ld.rectangle((0, 0, w - 1, h - 1), fill=color + (alpha,))
    base.paste(layer, (x1, y1), layer)


def _lighten(c, a=0.4):
    a = max(0.0, min(1.0, a))
    return (min(int(c[0] + (255 - c[0]) * a), 255),
            min(int(c[1] + (255 - c[1]) * a), 255),
            min(int(c[2] + (255 - c[2]) * a), 255))


# Каркас
W, H, M, PX, PY = 1800, 1000, 14, 40, 40


def _canvas(status: str):
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((M, M, W - 1 - M, H - 1 - M), radius=28,
                        fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)

    hx, hy = PX, PY
    ls = 64
    d.rounded_rectangle((hx, hy, hx + ls, hy + ls), radius=16,
                        fill=(58, 58, 64, 255), outline=(94, 94, 100, 255), width=2)
    _icon(d, hx + ls // 2, hy + ls // 2 + 1, I_GEM, 30, SILVER_HI)

    bx = hx + ls + 20
    d.text((bx, hy + 4), "DIAMOND", font=_font(34), fill=TEXT)
    d.text((bx + 4, hy + 46), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)

    mr = W - M - PX
    lbl = "КАЗИНО"
    w1 = _tw(d, lbl, _font(15))
    w2 = _tw(d, status.upper(), _font(22))
    d.text((mr - w1, hy + 12), lbl, font=_font(15), fill=MUTED)
    d.text((mr - w2, hy + 36), status.upper(), font=_font(22), fill=TEXT)

    d.line((PX, hy + ls + 20, W - M - PX, hy + ls + 20), fill=STACK_HDR + (255,), width=2)
    return img, d


def _footer(d, left_text, right_text):
    y = H - M - PY + 6
    d.line((PX, y - 10, W - M - PX, y - 10), fill=STACK_HDR + (255,), width=2)
    d.text((PX, y), left_text, font=_font(15), fill=DIM)
    rw = _tw(d, right_text, _font(15))
    d.text((W - M - PX - rw, y), right_text, font=_font(15), fill=DIM)


def _panel(img, d, box, radius=22):
    x1, y1, x2, y2 = box
    _alpha_fill(img, (x1 + 12, y1 + 12, x2 + 12, y2 + 12), (46, 46, 52), alpha=110, radius=radius)
    _alpha_fill(img, (x1 + 6, y1 + 6, x2 + 6, y2 + 6), (46, 46, 52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=3)


def _left_panel(img, d, box, balance, blocks):
    _panel(img, d, box, 22)
    x1, y1, x2, y2 = box
    pad = 28

    # Баланс
    bis = 84
    ibx, iby = x1 + pad, y1 + pad
    _alpha_fill(img, (ibx, iby, ibx + bis, iby + bis), SILVER, alpha=35, radius=22)
    d.rounded_rectangle((ibx, iby, ibx + bis, iby + bis), radius=22,
                        outline=SILVER + (200,), width=3)
    _icon(d, ibx + bis // 2, iby + bis // 2 + 1, I_GEM, 34, SILVER_HI)

    lx = ibx + bis + 20
    d.text((lx, iby + 8), "ТВОЙ БАЛАНС", font=_font(14), fill=MUTED)
    bs = f"{balance:,}".replace(",", " ")
    vf = _font(46)
    while _tw(d, bs + " DC", vf) > (x2 - pad - lx - 16) and vf.size > 24:
        vf = _font(vf.size - 2)
    d.text((lx, iby + 30), bs, font=vf, fill=TEXT)
    bw = _tw(d, bs, vf)
    d.text((lx + bw + 8, iby + 30 + vf.size - 26), "DC", font=_font(22), fill=SILVER)

    sep = iby + bis + 26
    d.line((x1 + pad, sep, x2 - pad, sep), fill=STACK_HDR + (255,), width=2)

    # Инфо-блоки
    by = sep + 26
    bh = 92
    gap = 14
    for i, blk in enumerate(blocks):
        cy1 = by + i * (bh + gap)
        cy2 = cy1 + bh
        cx1, cx2 = x1 + pad, x2 - pad
        color = blk["color"]

        _alpha_fill(img, (cx1, cy1, cx2, cy2), color, alpha=25, radius=15)
        d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=15,
                            outline=_lighten(color, 0.25) + (255,), width=3)
        d.rounded_rectangle((cx1 + 4, cy1 + 12, cx1 + 8, cy2 - 12), radius=2, fill=color + (255,))

        isz = 50
        ix = cx1 + 20
        iy = cy1 + (bh - isz) // 2
        _alpha_fill(img, (ix, iy, ix + isz, iy + isz), color, alpha=70, radius=13)
        d.rounded_rectangle((ix, iy, ix + isz, iy + isz), radius=13,
                            outline=_lighten(color, 0.25) + (200,), width=2)
        _icon(d, ix + isz // 2, iy + isz // 2 + 1, blk["icon"], 24, color)

        tx = ix + isz + 16
        d.text((tx, cy1 + 14), blk["label"].upper(), font=_font(13), fill=_lighten(color, 0.45))
        d.text((tx, cy1 + 42), blk["value"], font=_font(24), fill=color)


def _right_head(d, x1, y1, x2, title, sub):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 50), radius=3, fill=SILVER + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(30), fill=TEXT)
    sw = _tw(d, sub.upper(), _font(15))
    d.text((x2 - sw, y1 + 20), sub.upper(), font=_font(15), fill=MUTED)
    d.line((x1, y1 + 66, x2, y1 + 66), fill=STACK_HDR + (255,), width=2)


def _hero(img, d, box, color, icon_code, label, title, title_color):
    x1, y1, x2, y2 = box
    _alpha_fill(img, (x1, y1, x2, y2), color, alpha=25, radius=20)
    d.rounded_rectangle((x1, y1, x2, y2), radius=20, outline=color + (200,), width=3)

    isz = 132
    ix = x1 + 36
    iy = y1 + (y2 - y1 - isz) // 2
    _alpha_fill(img, (ix, iy, ix + isz, iy + isz), color, alpha=45, radius=26)
    d.rounded_rectangle((ix, iy, ix + isz, iy + isz), radius=26, outline=color + (220,), width=3)
    _icon(d, ix + isz // 2, iy + isz // 2 + 1, icon_code, 60, color)

    tx = ix + isz + 34
    d.text((tx, y1 + 34), label.upper(), font=_font(14), fill=MUTED)
    d.text((tx, y1 + 62), title, font=_font(38), fill=title_color)


def _icells(d, img, box, cells, cols=2):
    x1, y1, x2, y2 = box
    gap = 14
    cw = (x2 - x1 - gap * (cols - 1)) // cols
    rows = (len(cells) + cols - 1) // cols
    ch = (y2 - y1 - gap * (rows - 1)) // rows
    for i, c in enumerate(cells):
        r, col = divmod(i, cols)
        cx = x1 + col * (cw + gap)
        cy = y1 + r * (ch + gap)
        d.rounded_rectangle((cx, cy, cx + cw, cy + ch), radius=14,
                            fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        d.text((cx + 18, cy + 16), c["label"].upper(), font=_font(12), fill=MUTED)

        val = c["value"]
        vf = _font(22)
        color = c.get("color", TEXT)
        shown = val
        while _tw(d, shown, vf) > cw - 36 and vf.size > 14:
            vf = _font(vf.size - 2)
        d.text((cx + 18, cy + ch - 46), shown, font=vf, fill=color)


def _hint(d, img, box, color, icon_code, text):
    x1, y1, x2, y2 = box
    _alpha_fill(img, (x1, y1, x2, y2), color, alpha=22, radius=14)
    d.rounded_rectangle((x1, y1, x2, y2), radius=14, outline=color + (150,), width=2)
    cy = (y1 + y2) // 2
    _icon(d, x1 + 28, cy, icon_code, 20, color)
    d.text((x1 + 56, cy), text, font=_font(15), fill=TEXT_SOFT, anchor="lm")


def _draw_card(d, img, x, y, w, h, rank, suit_code, color, is_back=False):
    if is_back:
        d.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=(26, 35, 126), outline=(40, 53, 147), width=2)
        # полоски
        for i in range(0, h, 12):
            d.line((x + 2, y + i, x + w - 2, y + i + 12), fill=(40, 53, 147), width=3)
        d.rounded_rectangle((x + 8, y + 8, x + w - 8, y + h - 8), radius=6, outline=(255, 255, 255, 60), width=2)
        _icon(d, x + w // 2, y + h // 2, I_QUESTION, 32, (200, 200, 220))
        return
    d.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=(240, 240, 245), outline=(210, 210, 220), width=2)
    rf = _font(34)
    rw = _tw(d, rank, rf)
    d.text((x + w // 2 - rw // 2, y + 22), rank, font=rf, fill=color)
    _icon(d, x + w // 2, y + 88, suit_code, 28, color)


# ════════════════════════════════════════════════════════════
# ЭКСПОРТ — Рулетка
# ════════════════════════════════════════════════════════════
def render_roulette_spin(user_id: int, balance: int, bet: int) -> io.BytesIO:
    img, d = _canvas("Прокрутка")
    body_y, body_h = 140, H - M - PY - 140 - 26
    lx1, lx2, rx1, rx2 = PX, PX + 460, PX + 490, W - M - PX

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": GOLD},
        {"label": "Прокрутка", "value": "≈ 2 сек", "icon": I_CLOCK, "color": SILVER},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), 22)
    rx1_, rx2_ = rx1 + 30, rx2 - 30
    _right_head(d, rx1_, body_y + 22, rx2_, "Прокрутка барабана", "ждём результат")

    cy = body_y + 130 + (body_h - 130 - 100) // 2 + 100
    cx = (rx1_ + rx2_) // 2

    # Колесо — статичный круг
    wheel_r = 150
    d.ellipse((cx - wheel_r, cy - wheel_r, cx + wheel_r, cy + wheel_r),
              fill=(15, 15, 20), outline=GOLD, width=6)
    d.ellipse((cx - wheel_r + 18, cy - wheel_r + 18, cx + wheel_r - 18, cy + wheel_r - 18),
              outline=(160, 130, 70), width=3)
    _icon(d, cx, cy, I_ROTATE, 96, GOLD)

    d.text((cx, cy + wheel_r + 40), "Подбираем слот", font=_font(26), fill=GOLD, anchor="mm")

    _hint(d, img, (rx1_, body_y + body_h - 92, rx2_, body_y + body_h - 22),
          GOLD, I_INFO, "Не закрывай сообщение — результат появится здесь же")

    _footer(d, "Рулетка монет · Diamond Shop", "DiamondBot")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


def render_roulette_win(user_id, balance, bet, result_name, mult, net, payout) -> io.BytesIO:
    img, d = _canvas("Выигрыш")
    body_y, body_h = 140, H - M - PY - 140 - 26
    lx1, lx2, rx1, rx2 = PX, PX + 460, PX + 490, W - M - PX

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "icon": I_TROPHY, "color": GREEN},
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), 22)
    rx1_, rx2_ = rx1 + 30, rx2 - 30
    _right_head(d, rx1_, body_y + 22, rx2_, "Рулетка монет", f"x{1+mult:.1f} · {result_name}")

    hero_y = body_y + 100
    _hero(img, d, (rx1_, hero_y, rx2_, hero_y + 200), GREEN, I_TROPHY,
          "выпало", f"{result_name} · x{1+mult:.1f}", TEXT)

    ic_y = hero_y + 220
    _icells(d, img, (rx1_, ic_y, rx2_, ic_y + 240), [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "color": SILVER_HI},
        {"label": "Возврат", "value": f"+{payout:,} DC".replace(",", " "), "color": GREEN},
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "color": GREEN},
        {"label": "Страховка", "value": "не было", "color": DIM},
    ])

    _hint(d, img, (rx1_, body_y + body_h - 92, rx2_, body_y + body_h - 22),
          GREEN, I_CHECK_C, "Удача на твоей стороне — попробуешь ещё?")

    _footer(d, "Рулетка монет · Diamond Shop", "DiamondBot")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


def render_roulette_lose(user_id, balance, bet, refund, result_name) -> io.BytesIO:
    img, d = _canvas("Проигрыш")
    body_y, body_h = 140, H - M - PY - 140 - 26
    lx1, lx2, rx1, rx2 = PX, PX + 460, PX + 490, W - M - PX

    lost = bet - refund
    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "icon": I_TREND_DOWN, "color": RED},
        {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "icon": I_SHIELD, "color": (GREEN if refund else DIM)},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), 22)
    rx1_, rx2_ = rx1 + 30, rx2 - 30
    _right_head(d, rx1_, body_y + 22, rx2_, "Рулетка монет", "проигрыш")

    hero_y = body_y + 100
    _hero(img, d, (rx1_, hero_y, rx2_, hero_y + 200), RED, I_XMARK_C,
          "выпало", f"{result_name} · x0", TEXT)

    ic_y = hero_y + 220
    _icells(d, img, (rx1_, ic_y, rx2_, ic_y + 240), [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "color": SILVER_HI},
        {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "color": (GREEN if refund else DIM)},
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "color": RED},
        {"label": "Баланс", "value": f"{balance:,} DC".replace(",", " "), "color": SILVER_HI},
    ])

    _hint(d, img, (rx1_, body_y + body_h - 92, rx2_, body_y + body_h - 22),
          RED, I_XMARK_C, "Не расстраивайся — повезёт в следующий раз")

    _footer(d, "Рулетка монет · Diamond Shop", "DiamondBot")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


# ════════════════════════════════════════════════════════════
# Экспорт — Блэкджек
# ════════════════════════════════════════════════════════════
def _cards_block(d, img, x, y, w, label_icon, label_text, score, cards, score_bad=False):
    d.text((x, y), "", font=_font(10), fill=MUTED)
    _icon(d, x + 8, y + 10, label_icon, 14, MUTED)
    d.text((x + 24, y), label_text.upper(), font=_font(13), fill=MUTED)
    # score pill
    sf = _font(14)
    sw = _tw(d, str(score), sf)
    px = x + 24 + _tw(d, label_text.upper(), _font(13)) + 12
    pill_color = (RED if score_bad else SILVER_HI)
    _alpha_fill(img, (px, y + 1, px + sw + 24, y + 30), pill_color, alpha=40, radius=8)
    d.rounded_rectangle((px, y + 1, px + sw + 24, y + 30), radius=8, outline=pill_color + (150,), width=1)
    d.text((px + 12, y + 8), str(score), font=sf, fill=pill_color)

    # Карты
    cy = y + 40
    cw, ch, gap = 90, 130, 14
    for i, c in enumerate(cards):
        cx = x + i * (cw + gap)
        if c.get("back"):
            _draw_card(d, img, cx, cy, cw, ch, "", 0, (0, 0, 0), is_back=True)
        else:
            _draw_card(d, img, cx, cy, cw, ch, c["rank"], c["suit"], c["color"])
    return cy + ch


def render_blackjack_table(user_id, balance, bet, dealer_cards, player_cards, player_score, dealer_first_card) -> io.BytesIO:
    """dealer_cards: 1 карта видна + рубашка. player_cards: открытые."""
    img, d = _canvas("Твой ход")
    body_y, body_h = 140, H - M - PY - 140 - 26
    lx1, lx2, rx1, rx2 = PX, PX + 460, PX + 490, W - M - PX

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": GOLD},
        {"label": "Действие", "value": "взять / хватит", "icon": I_HAND, "color": BLUE},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), 22)
    rx1_, rx2_ = rx1 + 30, rx2 - 30
    _right_head(d, rx1_, body_y + 22, rx2_, "Блэкджек", f"стол · {bet:,} DC".replace(",", " "))

    y1 = body_y + 100
    y_after_dealer = _cards_block(d, img, rx1_, y1, rx2_ - rx1_, I_USER_SEC, "Дилер", "?", dealer_cards)

    y2 = y_after_dealer + 30
    y_after_player = _cards_block(d, img, rx1_, y2, rx2_ - rx1_, I_USER, "Ты", player_score, player_cards)

    _hint(d, img, (rx1_, body_y + body_h - 92, rx2_, body_y + body_h - 22),
          GOLD, I_HAND_R, "Взять карту или остановиться? Кнопки под сообщением")

    _footer(d, "Блэкджек · Diamond Shop", "DiamondBot")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


def render_blackjack_result(user_id, balance, bet, total_bet, payout, net,
                            dealer_cards, player_cards, dealer_score, player_score,
                            outcome) -> io.BytesIO:
    """outcome: 'win' | 'lose' | 'push' | 'bust' | 'blackjack'"""
    STATUS = {
        "win":       ("Победа",  GREEN,  I_TROPHY,   "Победа · x2",       f"x{2.0:.1f} победа"),
        "blackjack": ("Блэкджек", GOLD,  I_TROPHY,   "Блэкджек · x2.5",   "x2.5 блэкджек"),
        "push":      ("Ничья",   SILVER, I_HANDSHAKE,"Ничья · равные очки", "ничья · возврат"),
        "lose":      ("Проигрыш",RED,    I_XMARK_C,  "Проигрыш",          "проигрыш"),
        "bust":      ("Перебор", RED,    I_BOLT,     f"Перебор · {player_score}", "перебор"),
    }
    status, color, hero_icon, hero_title, sub = STATUS.get(outcome, STATUS["lose"])

    img, d = _canvas(status)
    body_y, body_h = 140, H - M - PY - 140 - 26
    lx1, lx2, rx1, rx2 = PX, PX + 460, PX + 490, W - M - PX

    # Левые инфо-блоки
    if outcome in ("win", "blackjack"):
        bl = [
            {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "icon": I_TROPHY, "color": GREEN},
            {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER},
        ]
    elif outcome == "push":
        bl = [
            {"label": "Возврат", "value": f"+{payout:,} DC".replace(",", " "), "icon": I_ROTATE_L, "color": GOLD},
            {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER},
        ]
    else:
        bl = [
            {"label": "Потеряно", "value": f"−{total_bet:,} DC".replace(",", " "), "icon": I_TREND_DOWN, "color": RED},
            {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER},
        ]

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, bl)

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), 22)
    rx1_, rx2_ = rx1 + 30, rx2 - 30
    _right_head(d, rx1_, body_y + 22, rx2_, "Блэкджек", sub)

    hero_y = body_y + 100
    _hero(img, d, (rx1_, hero_y, rx2_, hero_y + 200), color, hero_icon, "результат", hero_title, TEXT)

    # Карты дилера и игрока
    y1 = hero_y + 220
    y_after_dealer = _cards_block(d, img, rx1_, y1, rx2_ - rx1_, I_USER_SEC, "Дилер",
                                  dealer_score, dealer_cards, score_bad=(dealer_score > 21))
    y2 = y_after_dealer + 30
    y_after_player = _cards_block(d, img, rx1_, y2, rx2_ - rx1_, I_USER, "Ты",
                                  player_score, player_cards, score_bad=(player_score > 21))

    # хинт
    hint_color = color
    hint_icon = {
        "win": I_CHECK_C, "blackjack": I_CHECK_C, "push": I_HANDSHAKE,
        "lose": I_XMARK_C, "bust": I_XMARK_C,
    }.get(outcome, I_INFO)
    hint_text = {
        "win": "Удача на твоей стороне — попробуешь ещё?",
        "blackjack": "Блэкджек! Повезло по-крупному",
        "push": "Ставка возвращена — попробуй ещё раз",
        "lose": "Не расстраивайся — в следующий раз повезёт",
        "bust": "Перебор — попробуй ещё раз, удача рядом",
    }.get(outcome, "Попробуешь ещё?")
    _hint(d, img, (rx1_, body_y + body_h - 92, rx2_, body_y + body_h - 22), hint_color, hint_icon, hint_text)

    _footer(d, "Блэкджек · Diamond Shop", "DiamondBot")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


# ════════════════════════════════════════════════════════════
# Экспорт — Монетка
# ════════════════════════════════════════════════════════════
def render_coinflip_choice(user_id, balance, bet) -> io.BytesIO:
    img, d = _canvas("Выбор стороны")
    body_y, body_h = 140, H - M - PY - 140 - 26
    lx1, lx2, rx1, rx2 = PX, PX + 460, PX + 490, W - M - PX

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": GOLD},
        {"label": "Выплата", "value": "x1.9", "icon": I_PERCENT, "color": GREEN},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), 22)
    rx1_, rx2_ = rx1 + 30, rx2 - 30
    _right_head(d, rx1_, body_y + 22, rx2_, "Монетка", "орёл или решка")

    cx = (rx1_ + rx2_) // 2
    cy = body_y + 130 + (body_h - 130 - 200) // 2 + 60

    # Монета
    r = 150
    d.ellipse((cx - r, cy - r, cx + r, cy + r),
              fill=(90, 55, 20), outline=GOLD, width=6)
    d.ellipse((cx - r + 12, cy - r + 12, cx + r - 12, cy + r - 12),
              outline=(160, 130, 70), width=3)
    _icon(d, cx, cy, I_COINS, 130, GOLD)

    # Выбор
    y_choice = cy + r + 40
    for i, (label, icon) in enumerate([("Орёл", I_CROW), ("Решка", I_CROWN)]):
        bw, bh = 260, 80
        bx = cx - bw - 15 if i == 0 else cx + 15
        by = y_choice
        d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=16,
                            fill=STACK_HDR + (255,), outline=STACK_BRD + (255,), width=3)
        _icon(d, bx + 50, by + bh // 2, icon, 32, GOLD)
        d.text((bx + 90, by + bh // 2), label, font=_font(26), fill=SILVER_HI, anchor="lm")

    _hint(d, img, (rx1_, body_y + body_h - 92, rx2_, body_y + body_h - 22),
          GOLD, I_CLOCK, "У тебя 60 секунд на выбор — кнопки под сообщением")

    _footer(d, "Монетка · Diamond Shop", "DiamondBot")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


def render_coinflip_win(user_id, balance, bet, payout, net, result_side, user_choice) -> io.BytesIO:
    img, d = _canvas("Победа")
    body_y, body_h = 140, H - M - PY - 140 - 26
    lx1, lx2, rx1, rx2 = PX, PX + 460, PX + 490, W - M - PX

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "icon": I_TROPHY, "color": GREEN},
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "icon": I_COINS, "color": SILVER},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), 22)
    rx1_, rx2_ = rx1 + 30, rx2 - 30
    _right_head(d, rx1_, body_y + 22, rx2_, "Монетка", f"{result_side} · победа")

    hero_y = body_y + 100
    _hero(img, d, (rx1_, hero_y, rx2_, hero_y + 200), GREEN, I_CROW if result_side == "Орёл" else I_CROWN,
          "выпало", f"{result_side} · x1.9", TEXT)

    ic_y = hero_y + 220
    _icells(d, img, (rx1_, ic_y, rx2_, ic_y + 240), [
        {"label": "Твой выбор", "value": user_choice, "color": SILVER_HI},
        {"label": "Выпало", "value": result_side, "color": GREEN},
        {"label": "Выплата", "value": f"+{payout:,} DC".replace(",", " "), "color": GREEN},
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "color": GREEN},
    ])

    _hint(d, img, (rx1_, body_y + body_h - 92, rx2_, body_y + body_h - 22),
          GREEN, I_CHECK_C, "Монетка на твоей стороне — попробуешь ещё?")

    _footer(d, "Монетка · Diamond Shop", "DiamondBot")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


def render_coinflip_lose(user_id, balance, bet, refund, result_side, user_choice) -> io.BytesIO:
    img, d = _canvas("Мимо")
    body_y, body_h = 140, H - M - PY - 140 - 26
    lx1, lx2, rx1, rx2 = PX, PX + 460, PX + 490, W - M - PX

    lost = bet - refund
    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "icon": I_TREND_DOWN, "color": RED},
        {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "icon": I_SHIELD, "color": (GREEN if refund else DIM)},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), 22)
    rx1_, rx2_ = rx1 + 30, rx2 - 30
    _right_head(d, rx1_, body_y + 22, rx2_, "Монетка", f"{result_side} · мимо")

    hero_y = body_y + 100
    _hero(img, d, (rx1_, hero_y, rx2_, hero_y + 200), RED,
          I_CROW if result_side == "Орёл" else I_CROWN,
          "выпало", f"{result_side} · мимо", TEXT)

    ic_y = hero_y + 220
    _icells(d, img, (rx1_, ic_y, rx2_, ic_y + 240), [
        {"label": "Твой выбор", "value": user_choice, "color": SILVER_HI},
        {"label": "Выпало", "value": result_side, "color": RED},
        {"label": "Страховка", "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"), "color": (GREEN if refund else DIM)},
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "color": RED},
    ])

    _hint(d, img, (rx1_, body_y + body_h - 92, rx2_, body_y + body_h - 22),
          RED, I_XMARK_C, "Страховка спасла половину — в следующий раз повезёт")

    _footer(d, "Монетка · Diamond Shop", "DiamondBot")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf
