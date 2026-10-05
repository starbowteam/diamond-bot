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

FONT_BOLD = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
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
    iy = y1
