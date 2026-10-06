# -*- coding: utf-8 -*-
"""
Pillow-рендер казино. 1800×1000, flat-стиль, FA-иконки, без свечений.

Экспорт:
  render_roulette_spin / win / lose
  render_blackjack_table / result
  render_coinflip_choice / win / lose
"""
import io
import os
from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR

FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_F = {}
_FA = {}


def _font(sz):
    if sz in _F: return _F[sz]
    try:    f = ImageFont.truetype(FONT_BOLD, sz)
    except Exception: f = ImageFont.load_default()
    _F[sz] = f; return f


def _fa(sz):
    if sz in _FA: return _FA[sz]
    f = None
    if os.path.exists(FONT_FA):
        try: f = ImageFont.truetype(FONT_FA, sz)
        except Exception: pass
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
SILVER      = (198, 208, 224)
SILVER_HI   = (224, 232, 245)
GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)
GOLD      = (247, 201, 145)
CARD_BRD  = (74, 74, 79)

# FA5/6 solid
I_GEM        = 0xf3a5
I_COINS      = 0xf51e
I_TROPHY     = 0xf091
I_TREND_DOWN = 0xf063   # fa-arrow-down
I_SHIELD     = 0xf3ed   # fa-shield-halved / fa-shield-alt
I_CLOCK      = 0xf017
I_ROTATE     = 0xf2f1   # fa-rotate
I_ROTATE_L   = 0xf2ea   # fa-rotate-left
I_INFO       = 0xf05a
I_CHECK_C    = 0xf058
I_XMARK_C    = 0xf057
I_BOLT       = 0xf0e7
I_HANDSHAKE  = 0xf2b5
I_HAND       = 0xf256
I_HAND_R     = 0xf0a4
I_CROW       = 0xf520
I_CROWN      = 0xf521
I_USER       = 0xf007
I_USER_SEC   = 0xf21b
I_SPADE      = 0xf2f4
I_HEART      = 0xf004
I_DIAMOND    = 0xf219
I_CLUB       = 0xf327
I_QUESTION   = 0xf128
I_PERCENT    = 0xf295


W, H = 1800, 1000
M = 14
PX, PY = 50, 50


def _tw(d, t, f):
    b = d.textbbox((0, 0), t, font=f)
    return b[2] - b[0]


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
        ld.rounded_rectangle((0, 0, w-1, h-1), radius=radius, fill=color + (alpha,))
    else:
        ld.rectangle((0, 0, w-1, h-1), fill=color + (alpha,))
    base.paste(layer, (x1, y1), layer)


def _lighten(c, a=0.4):
    a = max(0.0, min(1.0, a))
    return (min(int(c[0] + (255-c[0])*a), 255),
            min(int(c[1] + (255-c[1])*a), 255),
            min(int(c[2] + (255-c[2])*a), 255))


# ═══════════════════════════════════════════════════
# КАРКАС
# ═══════════════════════════════════════════════════
def _canvas(status_label, status_color):
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((M, M, W-1-M, H-1-M), radius=28,
                        fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)

    hx, hy = PX, PY
    ls = 72
    d.rounded_rectangle((hx, hy, hx+ls, hy+ls), radius=18,
                        fill=(58, 58, 64, 255), outline=(94, 94, 100, 255), width=2)
    _icon(d, hx+ls//2, hy+ls//2+1, I_GEM, 32, SILVER_HI)

    bx = hx + ls + 22
    d.text((bx, hy+2), "DIAMOND", font=_font(38), fill=TEXT)
    d.text((bx+4, hy+50), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)

    _draw_header_tab(img, d, W - M - PX, hy, "казино", status_label, status_color)

    sep_y = hy + ls + 18
    d.line((PX, sep_y, W-M-PX, sep_y), fill=STACK_HDR + (255,), width=2)
    return img, d


def _draw_header_tab(img, d, x2, y1, label, value, color):
    lf = _font(13); vf = _font(24)
    lw = _tw(d, label.upper(), lf); vw = _tw(d, value.upper(), vf)
    inner_w = max(lw, vw)
    pad_x, pad_y = 26, 14
    tab_w = inner_w + pad_x * 2
    tab_h = 80
    x1 = x2 - tab_w
    y2 = y1 + tab_h

    _alpha_fill(img, (x1, y1, x2, y2), color, alpha=20, radius=14)
    d.rounded_rectangle((x1, y1, x2, y2), radius=14,
                        outline=color + (120,), width=2)
    d.text((x2 - pad_x - lw, y1 + pad_y), label.upper(), font=lf, fill=MUTED)
    d.text((x2 - pad_x - vw, y1 + pad_y + 20), value.upper(), font=vf, fill=color)


# ═══════════════════════════════════════════════════
# ПАНЕЛИ
# ═══════════════════════════════════════════════════
def _panel(d, box, radius=22):
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=3)


def _draw_left_panel(img, d, box, balance, blocks):
    _panel(d, box)
    x1, y1, x2, y2 = box
    pad = 28

    bis = 104
    ibx = x1 + pad; iby = y1 + pad
    _alpha_fill(img, (ibx, iby, ibx+bis, iby+bis), SILVER, alpha=28, radius=26)
    d.rounded_rectangle((ibx, iby, ibx+bis, iby+bis), radius=26,
                        outline=SILVER + (140,), width=3)
    _icon(d, ibx+bis//2, iby+bis//2+1, I_GEM, 44, SILVER_HI)

    lx = ibx + bis + 22
    d.text((lx, iby + 6), "ТВОЙ БАЛАНС", font=_font(15), fill=MUTED)

    bs = f"{balance:,}".replace(",", " ")
    vf = _font(56)
    while _tw(d, bs + " DC", vf) > (x2 - pad - lx - 16) and vf.size > 32:
        vf = _font(vf.size - 2)
    d.text((lx, iby + 34), bs, font=vf, fill=TEXT)
    bw = _tw(d, bs, vf)
    d.text((lx+bw+8, iby + 34 + vf.size - 26), "DC", font=_font(26), fill=SILVER)

    sep_y = iby + bis + 20
    d.line((x1+pad, sep_y, x2-pad, sep_y), fill=STACK_HDR + (255,), width=2)

    by = sep_y + 20
    bh, gap = 100, 16
    for i, blk in enumerate(blocks):
        cy1 = by + i * (bh + gap)
        cy2 = cy1 + bh
        cx1, cx2 = x1 + pad, x2 - pad
        color = blk["color"]

        _alpha_fill(img, (cx1, cy1, cx2, cy2), color, alpha=22, radius=18)
        d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=18,
                            outline=_lighten(color, 0.15) + (180,), width=2)

        isz = 64
        ix = cx1 + 22
        iy = cy1 + (bh - isz) // 2
        _alpha_fill(img, (ix, iy, ix+isz, iy+isz), color, alpha=55, radius=16)
        d.rounded_rectangle((ix, iy, ix+isz, iy+isz), radius=16,
                            outline=_lighten(color, 0.2) + (200,), width=2)
        _icon(d, ix+isz//2, iy+isz//2+1, blk["icon"], 30, color)

        tx = ix + isz + 20
        d.text((tx, cy1 + 18), blk["label"].upper(), font=_font(14),
               fill=_lighten(color, 0.35))
        vf2 = _font(28)
        val = blk["value"]
        while _tw(d, val, vf2) > (cx2 - 20 - tx) and vf2.size > 16:
            vf2 = _font(vf2.size - 2)
        d.text((tx, cy1 + 50), val, font=vf2, fill=color)


# ═══════════════════════════════════════════════════
# ЧАСТИ ПРАВОЙ ПАНЕЛИ
# ═══════════════════════════════════════════════════
def _rhead(d, x1, y1, x2, title, sub):
    d.text((x1, y1), title.upper(), font=_font(40), fill=TEXT)
    sf = _font(16)
    sw = _tw(d, sub.upper(), sf)
    d.text((x2 - sw, y1 + 22), sub.upper(), font=sf, fill=MUTED)
    d.line((x1, y1 + 60, x2, y1 + 60), fill=STACK_HDR + (255,), width=2)


def _hero(img, d, box, color, icon_code, label, title, title_color=TEXT):
    x1, y1, x2, y2 = box
    _alpha_fill(img, (x1, y1, x2, y2), color, alpha=18, radius=22)
    d.rounded_rectangle((x1, y1, x2, y2), radius=22,
                        outline=color + (170,), width=3)

    isz = 180
    ix = x1 + 40
    iy = y1 + (y2 - y1 - isz) // 2
    _alpha_fill(img, (ix, iy, ix+isz, iy+isz), color, alpha=40, radius=36)
    d.rounded_rectangle((ix, iy, ix+isz, iy+isz), radius=36,
                        outline=color + (200,), width=3)
    _icon(d, ix+isz//2, iy+isz//2+1, icon_code, 80, color)

    tx = ix + isz + 40
    d.text((tx, y1 + 46), label.upper(), font=_font(18), fill=MUTED)
    tf = _font(64)
    while _tw(d, title, tf) > (x2 - 40 - tx) and tf.size > 32:
        tf = _font(tf.size - 4)
    d.text((tx, y1 + 78), title, font=tf, fill=title_color)


def _icells(d, img, box, cells, cols=2):
    x1, y1, x2, y2 = box
    gap = 16
    cw = (x2 - x1 - gap * (cols - 1)) // cols
    rows = (len(cells) + cols - 1) // cols
    ch = (y2 - y1 - gap * (rows - 1)) // rows

    for i, c in enumerate(cells):
        r, col = divmod(i, cols)
        cx1 = x1 + col * (cw + gap)
        cy1 = y1 + r * (ch + gap)
        cx2 = cx1 + cw
        cy2 = cy1 + ch

        d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=16,
                            fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        d.text((cx1 + 22, cy1 + 22), c["label"].upper(), font=_font(14), fill=MUTED)

        color = c.get("color", TEXT)
        vf = _font(32)
        val = c["value"]
        while _tw(d, val, vf) > (cw - 44) and vf.size > 18:
            vf = _font(vf.size - 2)
        d.text((cx1 + 22, cy2 - 22 - vf.size), val, font=vf, fill=color)


def _hint(d, x1, y1, x2, y2, color, icon_code, text, center=True):
    cy = (y1 + y2) // 2
    tf = _font(16)
    tw = _tw(d, text, tf)
    total_w = 18 + 12 + tw
    start_x = (x1 + x2 - total_w) // 2 if center else x1
    _icon(d, start_x + 9, cy, icon_code, 18, color)
    d.text((start_x + 30, cy), text, font=tf, fill=MUTED, anchor="lm")


# ═══════════════════════════════════════════════════
# КОЛЕСО / МОНЕТА / КАРТЫ
# ═══════════════════════════════════════════════════
def _draw_wheel(img, d, cx, cy, radius=150):
    d.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
              fill=(15, 15, 20, 255), outline=GOLD + (255,), width=8)
    inner_r = radius - 26
    d.ellipse((cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r),
              outline=(140, 115, 65, 180), width=3)
    _icon(d, cx, cy, I_ROTATE, 120, GOLD)


def _draw_coin(img, d, cx, cy, radius=130, state="default"):
    if state == "win":
        bg, border, ic = (61, 209, 119), (30, 138, 76), (13, 58, 31)
    elif state == "lose":
        bg, border, ic = (232, 90, 90), (160, 48, 48), (58, 15, 15)
    else:
        bg, border, ic = (232, 181, 101), (176, 122, 48), (90, 58, 16)

    d.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
              fill=bg + (255,), outline=border + (255,), width=10)
    inner_r = radius - 18
    d.ellipse((cx-inner_r, cy-inner_r, cx+inner_r, cy+inner_r),
              outline=border + (200,), width=3)
    _icon(d, cx, cy, I_COINS, 100, ic)


def _draw_card(d, img, x, y, w, h, rank, suit_code, suit_color, is_back=False):
    if is_back:
        d.rounded_rectangle((x, y, x+w, y+h), radius=14,
                            fill=(26, 35, 126, 255), outline=(40, 53, 147, 255), width=2)
        for i in range(0, h, 16):
            y2 = min(y+i+18, y+h-2)
            d.line((x+2, y+i, x+w-2, y2), fill=(40, 53, 147, 255), width=3)
        d.rounded_rectangle((x+14, y+14, x+w-14, y+h-14), radius=8,
                            outline=(255, 255, 255, 80), width=2)
        _icon(d, x+w//2, y+h//2, I_QUESTION, 46, (200, 200, 220))
        return

    d.rounded_rectangle((x, y, x+w, y+h), radius=14,
                        fill=(240, 240, 245, 255), outline=(210, 210, 220, 255), width=2)
    rf = _font(48)
    rw = _tw(d, rank, rf)
    d.text((x + w//2 - rw//2, y + 26), rank, font=rf, fill=suit_color)
    _icon(d, x + w//2, y + h - 56, suit_code, 44, suit_color)


def _draw_card_frame(img, d, box, label, label_icon, score, cards,
                     score_bad=False):
    x1, y1, x2, y2 = box
    d.rounded_rectangle((x1, y1, x2, y2), radius=18,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

    hx = x1 + 28
    hy = y1 + 30
    _icon(d, hx + 10, hy + 10, label_icon, 20, MUTED)
    d.text((hx + 32, hy), label.upper(), font=_font(17), fill=MUTED)

    sc_color = RED if score_bad else SILVER_HI
    d.text((hx, hy + 40), str(score), font=_font(52), fill=sc_color)

    cw, ch, gap = 130, 184, 18
    cx_start = x1 + 28 + 210 + 32
    cy = y1 + (y2 - y1 - ch) // 2

    for i, c in enumerate(cards):
        cx = cx_start + i * (cw + gap)
        if cx + cw > x2 - 28:
            break
        if c.get("back"):
            _draw_card(d, img, cx, cy, cw, ch, "", 0, (0, 0, 0), is_back=True)
        else:
            _draw_card(d, img, cx, cy, cw, ch, c["rank"], c["suit"], c["color"])


# ═══════════════════════════════════════════════════
# ROULETTE
# ═══════════════════════════════════════════════════
def render_roulette_spin(user_id, balance, bet):
    img, d = _canvas("Прокрутка", GOLD)
    b1, b2 = 158, 950

    _draw_left_panel(img, d, (50, b1, 490, b2), balance, [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "),
         "icon": I_COINS, "color": GOLD},
        {"label": "Прокрутка", "value": "≈ 2 сек",
         "icon": I_CLOCK, "color": SILVER},
    ])

    right_box = (512, b1, 1750, b2)
    _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box
    ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26

    _rhead(d, ix1, iy1, ix2, "Прокрутка барабана", "ждём результат")
    iy1 += 76

    hint_h = 30
    _hint(d, ix1, iy2 - hint_h, ix2, iy2, GOLD, I_INFO,
          "Не закрывай сообщение — результат появится здесь же")

    stage_y1 = iy1
    stage_y2 = iy2 - hint_h - 20
    cx = (ix1 + ix2) // 2
    cy = (stage_y1 + stage_y2) // 2 - 20
    _draw_wheel(img, d, cx, cy, 150)
    d.text((cx, cy + 150 + 40), "Подбираем слот",
           font=_font(32), fill=GOLD, anchor="mm")

    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


def render_roulette_win(user_id, balance, bet, result_name, mult, net, payout):
    img, d = _canvas("Выигрыш", GREEN)
    b1, b2 = 158, 950

    _draw_left_panel(img, d, (50, b1, 490, b2), balance, [
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "),
         "icon": I_TROPHY, "color": GREEN},
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "),
         "icon": I_COINS, "color": SILVER},
    ])

    right_box = (512, b1, 1750, b2)
    _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box
    ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26

    _rhead(d, ix1, iy1, ix2, "Рулетка монет", f"x{1+mult:.1f} · {result_name}")
    iy1 += 76

    hint_h = 30
    _hint(d, ix1, iy2 - hint_h, ix2, iy2, GREEN, I_CHECK_C,
          "Удача на твоей стороне — попробуешь ещё?")

    content_y1 = iy1
    content_y2 = iy2 - hint_h - 20
    total_h = content_y2 - content_y1
    gap = 16
    hero_h = int(total_h * 0.48)
    cells_h = total_h - hero_h - gap

    _hero(img, d, (ix1, content_y1, ix2, content_y1 + hero_h), GREEN, I_TROPHY,
          "выпало", f"{result_name} · x{1+mult:.1f}")

    cells_y1 = content_y1 + hero_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "color": SILVER_HI},
        {"label": "Возврат", "value": f"+{payout:,} DC".replace(",", " "), "color": GREEN},
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "color": GREEN},
        {"label": "Страховка", "value": "нет", "color": DIM},
    ], cols=4)

    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


def render_roulette_lose(user_id, balance, bet, refund, result_name):
    lost = bet - refund
    img, d = _canvas("Проигрыш", RED)
    b1, b2 = 158, 950

    _draw_left_panel(img, d, (50, b1, 490, b2), balance, [
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "),
         "icon": I_TREND_DOWN, "color": RED},
        {"label": "Страховка",
         "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"),
         "icon": I_SHIELD, "color": (GREEN if refund else DIM)},
    ])

    right_box = (512, b1, 1750, b2)
    _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box
    ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26

    _rhead(d, ix1, iy1, ix2, "Рулетка монет", "проигрыш")
    iy1 += 76

    hint_h = 30
    _hint(d, ix1, iy2 - hint_h, ix2, iy2, RED, I_XMARK_C,
          "Не расстраивайся — повезёт в следующий раз")

    content_y1 = iy1
    content_y2 = iy2 - hint_h - 20
    total_h = content_y2 - content_y1
    gap = 16
    hero_h = int(total_h * 0.48)
    cells_h = total_h - hero_h - gap

    _hero(img, d, (ix1, content_y1, ix2, content_y1 + hero_h), RED, I_XMARK_C,
          "выпало", f"{result_name} · x0")

    cells_y1 = content_y1 + hero_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "), "color": SILVER_HI},
        {"label": "Страховка",
         "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"),
         "color": (GREEN if refund else DIM)},
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "color": RED},
        {"label": "Баланс", "value": f"{balance:,} DC".replace(",", " "), "color": SILVER_HI},
    ], cols=4)

    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


# ═══════════════════════════════════════════════════
# BLACKJACK
# ═══════════════════════════════════════════════════
def render_blackjack_table(user_id, balance, bet, dealer_cards, player_cards,
                           player_score, dealer_first_card):
    img, d = _canvas("Твой ход", GOLD)
    b1, b2 = 158, 950

    _draw_left_panel(img, d, (50, b1, 490, b2), balance, [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "),
         "icon": I_COINS, "color": GOLD},
        {"label": "Действие", "value": "взять / хватит",
         "icon": I_HAND, "color": BLUE},
    ])

    right_box = (512, b1, 1750, b2)
    _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box
    ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26

    _rhead(d, ix1, iy1, ix2, "Блэкджек", f"стол · {bet:,} DC".replace(",", " "))
    iy1 += 76

    hint_h = 30
    _hint(d, ix1, iy2 - hint_h, ix2, iy2, GOLD, I_HAND_R,
          "Взять карту или остановиться? Кнопки под сообщением")

    content_y1 = iy1
    content_y2 = iy2 - hint_h - 20
    gap = 16
    frame_h = (content_y2 - content_y1 - gap) // 2

    _draw_card_frame(img, d, (ix1, content_y1, ix2, content_y1 + frame_h),
                     "Дилер", I_USER_SEC, "?", dealer_cards)
    py = content_y1 + frame_h + gap
    _draw_card_frame(img, d, (ix1, py, ix2, py + frame_h),
                     "Ты", I_USER, player_score, player_cards)

    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


def render_blackjack_result(user_id, balance, bet, total_bet, payout, net,
                            dealer_cards, player_cards, dealer_score,
                            player_score, outcome):
    STATUS = {
        "win":       ("Победа",   GREEN,  I_TROPHY,   "Победа · x2",            "блэкджек"),
        "blackjack": ("Блэкджек", GOLD,   I_TROPHY,   "Блэкджек · x2.5",        "блэкджек"),
        "push":      ("Ничья",    SILVER, I_HANDSHAKE,"Ничья · равные очки",    "возврат ставки"),
        "lose":      ("Проигрыш", RED,    I_XMARK_C,  "Проигрыш",               "блэкджек"),
        "bust":      ("Перебор",  RED,    I_BOLT,     f"Перебор · {player_score}", "блэкджек"),
    }
    status, color, hero_icon, hero_title, sub = STATUS.get(outcome, STATUS["lose"])

    img, d = _canvas(status, color)
    b1, b2 = 158, 950

    if outcome in ("win", "blackjack"):
        blocks = [
            {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "),
             "icon": I_TROPHY, "color": GREEN},
            {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "),
             "icon": I_COINS, "color": SILVER},
        ]
    elif outcome == "push":
        blocks = [
            {"label": "Возврат", "value": f"+{payout:,} DC".replace(",", " "),
             "icon": I_ROTATE_L, "color": GOLD},
            {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "),
             "icon": I_COINS, "color": SILVER},
        ]
    else:
        blocks = [
            {"label": "Потеряно", "value": f"−{total_bet:,} DC".replace(",", " "),
             "icon": I_TREND_DOWN, "color": RED},
            {"label": "Ставка", "value": f"{total_bet:,} DC".replace(",", " "),
             "icon": I_COINS, "color": SILVER},
        ]

    _draw_left_panel(img, d, (50, b1, 490, b2), balance, blocks)

    right_box = (512, b1, 1750, b2)
    _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box
    ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26

    _rhead(d, ix1, iy1, ix2, hero_title, sub)
    iy1 += 76

    content_y1 = iy1
    content_y2 = iy2
    gap = 16
    frame_h = (content_y2 - content_y1 - gap) // 2

    _draw_card_frame(img, d, (ix1, content_y1, ix2, content_y1 + frame_h),
                     "Дилер", I_USER_SEC, dealer_score, dealer_cards,
                     score_bad=(dealer_score > 21))
    py = content_y1 + frame_h + gap
    _draw_card_frame(img, d, (ix1, py, ix2, py + frame_h),
                     "Ты", I_USER, player_score, player_cards,
                     score_bad=(player_score > 21))

    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


# ═══════════════════════════════════════════════════
# COINFLIP
# ═══════════════════════════════════════════════════
def render_coinflip_choice(user_id, balance, bet):
    img, d = _canvas("Выбор стороны", GOLD)
    b1, b2 = 158, 950

    _draw_left_panel(img, d, (50, b1, 490, b2), balance, [
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "),
         "icon": I_COINS, "color": GOLD},
        {"label": "Выплата", "value": "x1.9",
         "icon": I_PERCENT, "color": GREEN},
    ])

    right_box = (512, b1, 1750, b2)
    _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box
    ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26

    _rhead(d, ix1, iy1, ix2, "Монетка", "орёл или решка")
    iy1 += 76

    hint_h = 30
    _hint(d, ix1, iy2 - hint_h, ix2, iy2, GOLD, I_CLOCK,
          "У тебя 60 секунд на выбор — кнопки под сообщением")

    choice_h = 80
    choices_y1 = iy2 - hint_h - 20 - choice_h
    stage_y1 = iy1
    stage_y2 = choices_y1 - 16
    cx = (ix1 + ix2) // 2
    cy = (stage_y1 + stage_y2) // 2
    _draw_coin(img, d, cx, cy, 130, "default")

    ch_w, gap = 260, 22
    total_w = ch_w * 2 + gap
    ch_start = cx - total_w // 2

    for i, (label, icon) in enumerate([("Орёл", I_CROW), ("Решка", I_CROWN)]):
        bx = ch_start + i * (ch_w + gap)
        by = choices_y1
        d.rounded_rectangle((bx, by, bx + ch_w, by + choice_h), radius=16,
                            fill=STACK_HDR + (255,), outline=STACK_BRD + (255,), width=3)
        _icon(d, bx + 48, by + choice_h // 2, icon, 30, GOLD)
        d.text((bx + 90, by + choice_h // 2), label, font=_font(28),
               fill=SILVER_HI, anchor="lm")

    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


def render_coinflip_win(user_id, balance, bet, payout, net, result_side, user_choice):
    img, d = _canvas("Победа", GREEN)
    b1, b2 = 158, 950

    _draw_left_panel(img, d, (50, b1, 490, b2), balance, [
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "),
         "icon": I_TROPHY, "color": GREEN},
        {"label": "Ставка", "value": f"{bet:,} DC".replace(",", " "),
         "icon": I_COINS, "color": SILVER},
    ])

    right_box = (512, b1, 1750, b2)
    _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box
    ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26

    _rhead(d, ix1, iy1, ix2, f"{result_side} · x1.9", "победа")
    iy1 += 76

    content_y1 = iy1
    content_y2 = iy2
    total_h = content_y2 - content_y1
    gap = 16
    coin_h = int(total_h * 0.52)
    cells_h = total_h - coin_h - gap

    cx = (ix1 + ix2) // 2
    cy = content_y1 + coin_h // 2
    _draw_coin(img, d, cx, cy, 130, "win")

    cells_y1 = content_y1 + coin_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [
        {"label": "Твой выбор", "value": user_choice, "color": SILVER_HI},
        {"label": "Выпало", "value": result_side, "color": GREEN},
        {"label": "Выплата", "value": f"+{payout:,} DC".replace(",", " "), "color": GREEN},
        {"label": "Профит", "value": f"+{net:,} DC".replace(",", " "), "color": GREEN},
    ], cols=2)

    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf


def render_coinflip_lose(user_id, balance, bet, refund, result_side, user_choice):
    lost = bet - refund
    img, d = _canvas("Мимо", RED)
    b1, b2 = 158, 950

    _draw_left_panel(img, d, (50, b1, 490, b2), balance, [
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "),
         "icon": I_TREND_DOWN, "color": RED},
        {"label": "Страховка",
         "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"),
         "icon": I_SHIELD, "color": (GREEN if refund else DIM)},
    ])

    right_box = (512, b1, 1750, b2)
    _panel(d, right_box)
    ix1, iy1, ix2, iy2 = right_box
    ix1 += 28; iy1 += 26; ix2 -= 28; iy2 -= 26

    _rhead(d, ix1, iy1, ix2, f"{result_side} · мимо", "проигрыш")
    iy1 += 76

    content_y1 = iy1
    content_y2 = iy2
    total_h = content_y2 - content_y1
    gap = 16
    coin_h = int(total_h * 0.52)
    cells_h = total_h - coin_h - gap

    cx = (ix1 + ix2) // 2
    cy = content_y1 + coin_h // 2
    _draw_coin(img, d, cx, cy, 130, "lose")

    cells_y1 = content_y1 + coin_h + gap
    _icells(d, img, (ix1, cells_y1, ix2, cells_y1 + cells_h), [
        {"label": "Твой выбор", "value": user_choice, "color": SILVER_HI},
        {"label": "Выпало", "value": result_side, "color": RED},
        {"label": "Страховка",
         "value": (f"+{refund:,} DC".replace(",", " ") if refund else "не было"),
         "color": (GREEN if refund else DIM)},
        {"label": "Потеряно", "value": f"−{lost:,} DC".replace(",", " "), "color": RED},
    ], cols=2)

    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf
