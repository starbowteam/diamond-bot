# -*- coding: utf-8 -*-
"""
Pillow-рендеры питомцев.
"""
import io
import os
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, logger
from pet.core import (
    CATALOG, RARITY_LABEL, RARITY_PALETTE,
    get_xp_progress, hourly_rate, max_pending, MAX_LEVEL, gift_price,
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
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)
GOLD      = (247, 201, 145)
GOLD_DK   = (174, 121, 17)
BRONZE    = (209, 146, 96)
PINK      = (255, 77, 148)

GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)
GOLD_BG   = (40, 32, 21)

CARD_BRD  = (74, 74, 79)

I_GEM      = 0xf3a5
I_USER     = 0xf007
I_USERS    = 0xf0c0
I_INFO     = 0xf05a
I_COINS    = 0xf51e
I_CLOCK    = 0xf017
I_STAR     = 0xf005
I_CROWN    = 0xf521
I_TROPHY   = 0xf091
I_MEDAL    = 0xf5a2
I_PAW      = 0xf1b0
I_BOLT     = 0xf0e7
I_CHART    = 0xf201
I_CHECK    = 0xf00c
I_PLUS     = 0xf067
I_GIFT     = 0xf06b
I_FIRE     = 0xf06d
I_TARGET   = 0xf140


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
    steps = r
    for i in range(steps, 0, -1):
        t = i / steps
        rr = int(c1[0] * (1 - t) + c2[0] * t)
        gg = int(c1[1] * (1 - t) + c2[1] * t)
        bb = int(c1[2] * (1 - t) + c2[2] * t)
        ld.ellipse((r - i, r - i, r + i, r + i),
                   fill=(rr, gg, bb, alpha))
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


def _fmt_date(ts: int) -> str:
    if not ts or int(ts) <= 0:
        return "—"
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%d.%m.%Y")
    except Exception:
        return "—"


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
    d.rounded_rectangle((hx, hy, hx + ls, hy + ls), radius=16,
                        fill=(58, 58, 64) + (255,))
    _icon(d, hx + ls // 2, hy + ls // 2 + 1, I_GEM, 30, SILVER_HI)

    bx = hx + ls + 20
    d.text((bx, hy + 4), "DIAMOND", font=_font(34), fill=TEXT)
    d.text((bx + 4, hy + 46), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)

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


def _left_panel(img, d, box, balance, blocks):
    _panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 26

    bs = 80
    ibx = x1 + pad; iby = y1 + pad
    _grad(img, (ibx, iby, ibx + bs, iby + bs), SILVER, (120, 132, 155), alpha=42, radius=20)
    d.rounded_rectangle((ibx, iby, ibx + bs, iby + bs), radius=20,
                        outline=SILVER + (200,), width=3)
    _icon(d, ibx + bs // 2, iby + bs // 2 + 1, I_GEM, 32, SILVER_HI)

    lx = ibx + bs + 18
    d.text((lx, iby + 6), "ТВОЙ БАЛАНС", font=_font(13), fill=MUTED)
    bstr = _fmt(balance)
    vf = _font(40)
    max_w = x2 - pad - lx - 16
    while _tw(d, bstr + " DC", vf) > max_w and vf.size > 22:
        vf = _font(vf.size - 2)
    d.text((lx, iby + 26), bstr, font=vf, fill=TEXT)
    bvv = _tw(d, bstr, vf)
    d.text((lx + bvv + 8, iby + 26 + vf.size - 22), "DC", font=_font(20), fill=SILVER)

    sy = iby + bs + 24
    d.line((x1 + pad, sy, x2 - pad, sy), fill=STACK_HDR + (255,), width=2)

    if not blocks:
        return

    bb_h = 84
    bb_gap = 12
    top_y = sy + 24

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

        ic_s = 44
        iic_x = bx1 + 18
        iic_y = by1 + (bb_h - ic_s) // 2
        _alpha(img, (iic_x, iic_y, iic_x + ic_s, iic_y + ic_s), color, alpha=65, radius=11)
        d.rounded_rectangle((iic_x, iic_y, iic_x + ic_s, iic_y + ic_s),
                            radius=11, outline=border + (180,), width=1)
        _icon(d, iic_x + ic_s // 2, iic_y + ic_s // 2 + 1,
              blk.get("icon", I_INFO), 20, color)

        tx = iic_x + ic_s + 14
        d.text((tx, by1 + 12), blk.get("label", "").upper(), font=_font(11), fill=light)
        bv = blk.get("value", "—")
        bvf = _font(20)
        bv_shown = _el(d, str(bv), bvf, bx2 - 16 - tx)
        d.text((tx, by1 + 38), bv_shown, font=bvf, fill=color)


def _right_head(d, x1, y1, x2, title, sub):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 46), radius=3, fill=SILVER + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(28), fill=TEXT)
    sw = _tw(d, sub.upper(), _font(14))
    d.text((x2 - sw, y1 + 18), sub.upper(), font=_font(14), fill=MUTED)
    d.line((x1, y1 + 62, x2, y1 + 62), fill=STACK_HDR + (255,), width=2)


def _rarity_label_short(rarity: str) -> str:
    return RARITY_LABEL.get(rarity, "—").upper()


def _xp_bar(d, img, x, y, w, h, pct):
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=(28, 28, 34))
    fill_w = int(w * pct / 100)
    if fill_w > 0:
        _grad(img, (x, y, x + fill_w, y + h), PURPLE, BLUE, alpha=255, radius=h // 2)


# ============================================================
# КАТАЛОГ
# ============================================================
def _catalog_row(img, d, x, y, w, h, key, cat, selected=False):
    color = RARITY_PALETTE.get(cat["rarity"], SILVER)
    border = _lighten(color, 0.25)

    if selected:
        _grad(img, (x, y, x + w, y + h), color, color, alpha=18, radius=14)
        d.rounded_rectangle((x, y, x + w, y + h), radius=14,
                            outline=color + (230,), width=3)
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=14,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)

    pad = 16
    es = 72
    ex = x + pad
    ey = y + (h - es) // 2
    _alpha(img, (ex, ey, ex + es, ey + es), color, alpha=40, radius=16)
    d.rounded_rectangle((ex, ey, ex + es, ey + es), radius=16,
                        outline=color + (170,), width=2)
    _icon(d, ex + es // 2, ey + es // 2 + 2, cat["fa_code"], 32, color)

    tx = ex + es + 18
    tx_max = x + w - pad - 260

    name_f = _font(21)
    name_shown = _el(d, cat["name"], name_f, tx_max - tx)
    d.text((tx, y + 14), name_shown, font=name_f, fill=TEXT)

    rl = _rarity_label_short(cat["rarity"])
    rlf = _font(10)
    rlw = _tw(d, rl, rlf) + 16
    rl_y = y + 44
    _alpha(img, (tx, rl_y, tx + rlw, rl_y + 20), color, alpha=55, radius=5)
    d.rounded_rectangle((tx, rl_y, tx + rlw, rl_y + 20), radius=5,
                        outline=border + (200,), width=1)
    d.text((tx + 8, rl_y + 3), rl, font=rlf, fill=color)

    desc_x = tx + rlw + 12
    desc_max = tx_max - desc_x
    if desc_max > 80:
        desc_f = _font(12)
        desc_shown = _el(d, cat.get("description", ""), desc_f, desc_max)
        d.text((desc_x, rl_y + 4), desc_shown, font=desc_f, fill=MUTED)

    stats_y = y + h - 34
    base = cat["passive_dc"]
    max_rate = base * (1 + (MAX_LEVEL - 1) * 0.15)

    d.text((tx, stats_y - 4), "ДОХОД", font=_font(9), fill=MUTED)
    d.text((tx, stats_y + 10), f"{base} DC/ч", font=_font(15), fill=GREEN)

    bx2_x = tx + 120
    d.text((bx2_x, stats_y - 4), "МАКС. УР.", font=_font(9), fill=MUTED)
    d.text((bx2_x, stats_y + 10), f"{max_rate:.0f} DC/ч", font=_font(15), fill=GREEN)

    bt = cat.get("bonus_type", "none")
    if bt != "none":
        bnames = {"review_bonus": "к отзывам", "casino_luck": "к казино", "clan_contrib": "к клану"}
        btext = f"+{int(cat.get('bonus_value', 0) * 100)}% {bnames.get(bt, '')}"
        bf = _font(11)
        bw = _tw(d, btext, bf) + 16
        bx = bx2_x + 120
        if bx + bw < tx_max:
            _alpha(img, (bx, stats_y + 6, bx + bw, stats_y + 28), GOLD, alpha=25, radius=6)
            d.rounded_rectangle((bx, stats_y + 6, bx + bw, stats_y + 28), radius=6,
                                outline=GOLD + (150,), width=1)
            d.text((bx + 8, stats_y + 9), btext, font=bf, fill=GOLD)

    right_x = x + w - pad
    price_str = _fmt(cat["price_dc"])
    pf = _font(26)
    pw = _tw(d, price_str, pf)
    d.text((right_x - pw - 30, y + 18), price_str, font=pf, fill=SILVER_HI)
    d.text((right_x - 24, y + 18 + pf.size - 18), "DC",
           font=_font(14), fill=MUTED)

    if base > 0:
        days = max(int(cat["price_dc"] / (base * 24)), 1)
        pb_text = f"~{days} дн окупаемость"
        pbf = _font(11)
        pbw = _tw(d, pb_text, pbf)
        d.text((right_x - pbw, y + 52), pb_text, font=pbf, fill=GREEN)


def render_catalog(user_id, balance, available_pets, selected_key=None):
    img, d = _canvas(user_id, "питомцы · каталог")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 450
    gap = 28
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    total = len(CATALOG)
    available_count = len(available_pets)
    owned_count = total - available_count

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "В каталоге", "value": f"{total} питомцев", "icon": I_PAW, "color": BLUE},
        {"label": "У тебя есть", "value": f"{owned_count} из {total}", "icon": I_CHECK, "color": GREEN},
        {"label": "Топ по доходу", "value": "Даймондик · 20 DC/ч", "icon": I_CROWN, "color": GOLD},
        {"label": "Комиссия подарка", "value": "+10% к цене", "icon": I_GIFT, "color": PURPLE},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 26
    rpx2 = rx2 - 26

    if not available_pets:
        sub_text = "всё куплено — новых скоро добавят"
    else:
        sub_text = "выбери в меню ниже чтобы купить"

    _right_head(d, rpx1, body_y + 22, rpx2, "Каталог питомцев", sub_text)

    list_y1 = body_y + 90
    list_y2 = body_y + body_h - 22

    if not available_pets:
        cx = (rpx1 + rpx2) // 2
        cy = (list_y1 + list_y2) // 2 - 30
        _alpha(img, (cx - 60, cy - 60, cx + 60, cy + 60), SILVER, alpha=20, radius=30)
        _icon(d, cx, cy, I_CHECK, 56, SILVER)
        d.text((cx, cy + 100), "Все питомцы уже у тебя",
               font=_font(22), fill=TEXT, anchor="mm")
        d.text((cx, cy + 136), "Следи за новостями — скоро добавят новых",
               font=_font(14), fill=MUTED, anchor="mm")

        _footer(d, "Каталог пуст — всё куплено", "стр. 1 / 4")
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        buf.seek(0)
        return buf

    rows = min(len(available_pets), 6)
    gap_row = 8
    row_h = (list_y2 - list_y1 - gap_row * (rows - 1)) // rows
    row_h = min(row_h, 118)

    for idx, (key, cat) in enumerate(available_pets[:rows]):
        cy = list_y1 + idx * (row_h + gap_row)
        if cy + row_h > list_y2:
            break
        _catalog_row(img, d, rpx1, cy, rpx2 - rpx1, row_h, key, cat,
                     selected=(key == selected_key))

    _footer(d, "Выбери питомца в меню ниже", "стр. 1 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# КАРТОЧКА ТОВАРА
# ============================================================
def render_item_card(user_id, balance, pet_key: str):
    img, d = _canvas(user_id, "питомцы · товар")

    cat = CATALOG.get(pet_key, {})
    color = RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER)

    body_y = 140
    body_h = H - M - PY - body_y - 26

    lw = 450
    gap = 28
    lx1 = PX
    lx2 = lx1 + lw
    rx1 = lx2 + gap
    rx2 = W - M - PX

    total = len(CATALOG)
    price = cat.get("price_dc", 0)
    gp = gift_price(pet_key)
    base = cat.get("passive_dc", 0)
    max_rate = base * (1 + (MAX_LEVEL - 1) * 0.15)
    days = max(int(price / (base * 24)), 1) if base > 0 else 0

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Категория", "value": "Питомцы", "icon": I_PAW, "color": BLUE},
        {"label": "Редкость", "value": RARITY_LABEL.get(cat.get("rarity", ""), "—"),
         "icon": I_STAR, "color": color},
        {"label": "Цена покупки", "value": f"{_fmt(price)} DC", "icon": I_COINS, "color": GREEN},
        {"label": "Цена подарка", "value": f"{_fmt(gp)} DC (+10%)", "icon": I_GIFT, "color": PURPLE},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 26
    rpx2 = rx2 - 26

    _right_head(d, rpx1, body_y + 22, rpx2, cat.get("name", "—").upper(), "товар · питомец")

    content_y1 = body_y + 96

    header_h = 180
    header_x1 = rpx1
    header_x2 = rpx2
    header_y1 = content_y1
    header_y2 = header_y1 + header_h

    _grad(img, (header_x1, header_y1, header_x2, header_y2), GOLD, GOLD, alpha=12, radius=18)
    d.rounded_rectangle((header_x1, header_y1, header_x2, header_y2), radius=18,
                        outline=GOLD + (140,), width=2)

    es = 130
    ex = header_x1 + 24
    ey = header_y1 + (header_h - es) // 2
    _alpha(img, (ex, ey, ex + es, ey + es), color, alpha=45, radius=28)
    d.rounded_rectangle((ex, ey, ex + es, ey + es), radius=28,
                        outline=color + (180,), width=3)
    _icon(d, ex + es // 2, ey + es // 2 + 2, cat.get("fa_code", I_PAW), 60, color)

    tx = ex + es + 24
    tx_max = header_x2 - 24

    name_f = _font(30)
    d.text((tx, ey + 4), _el(d, cat.get("name", "—"), name_f, tx_max - tx),
           font=name_f, fill=TEXT)

    desc_f = _font(15)
    desc_lines = []
    cur = ""
    for word in cat.get("description", "").split():
        test = (cur + " " + word).strip()
        if _tw(d, test, desc_f) <= tx_max - tx:
            cur = test
        else:
            if cur: desc_lines.append(cur)
            cur = word
            if len(desc_lines) >= 2: break
    if cur and len(desc_lines) < 2: desc_lines.append(cur)
    for i, line in enumerate(desc_lines):
        d.text((tx, ey + 46 + i * 20), line, font=desc_f, fill=MUTED)

    tag_y = ey + 96
    cur_x = tx
    rl = _rarity_label_short(cat.get("rarity", "common"))
    rlf = _font(12)
    rlw = _tw(d, rl, rlf) + 20
    _alpha(img, (cur_x, tag_y, cur_x + rlw, tag_y + 26), color, alpha=55, radius=7)
    d.rounded_rectangle((cur_x, tag_y, cur_x + rlw, tag_y + 26), radius=7,
                        outline=color + (200,), width=1)
    d.text((cur_x + 10, tag_y + 4), rl, font=rlf, fill=color)
    cur_x += rlw + 8

    if cat.get("bonus_type", "none") != "none":
        bnames = {"review_bonus": "отзывы", "casino_luck": "казино", "clan_contrib": "клан"}
        btext = f"+{int(cat.get('bonus_value', 0) * 100)}% · {bnames.get(cat['bonus_type'], '')}"
        bw = _tw(d, btext, rlf) + 20
        _alpha(img, (cur_x, tag_y, cur_x + bw, tag_y + 26), GOLD, alpha=25, radius=7)
        d.rounded_rectangle((cur_x, tag_y, cur_x + bw, tag_y + 26), radius=7,
                            outline=GOLD + (150,), width=1)
        d.text((cur_x + 10, tag_y + 4), btext, font=rlf, fill=GOLD)

    stats_h = 110
    stats_y1 = header_y2 + 14
    stats_y2 = stats_y1 + stats_h

    stats_data = [
        ("ДОХОД", f"{base} DC/ч", GREEN, I_BOLT),
        ("НА МАКС. УР.", f"{max_rate:.0f} DC/ч", GREEN, I_TARGET),
        ("КАП КОПИЛКИ", f"{int(base * 24)} DC", SILVER, I_COINS),
        ("ОКУПАЕМОСТЬ", f"~{days} дн", GOLD, I_FIRE),
    ]

    gap_col = 12
    col_w = (rpx2 - rpx1 - gap_col * 3) // 4

    for i, (lbl, val, col, ic) in enumerate(stats_data):
        cx1 = rpx1 + i * (col_w + gap_col)
        cx2 = cx1 + col_w

        d.rounded_rectangle((cx1, stats_y1, cx2, stats_y2), radius=14,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)
        _alpha(img, (cx1 + 18, stats_y1 + 18, cx1 + 18 + 44, stats_y1 + 18 + 44),
               col, alpha=35, radius=11)
        _icon(d, cx1 + 40, stats_y1 + 40, ic, 22, col)

        d.text((cx1 + 74, stats_y1 + 22), lbl, font=_font(10), fill=MUTED)
        vf = _font(20)
        d.text((cx1 + 74, stats_y1 + 44), _el(d, val, vf, cx2 - cx1 - 88),
               font=vf, fill=col)

    bonus_y1 = stats_y2 + 14
    bonus_h = 68
    bonus_y2 = bonus_y1 + bonus_h

    bt = cat.get("bonus_type", "none")
    if bt != "none":
        bnames = {
            "review_bonus": "к награде за отзывы",
            "casino_luck": "к выигрышу в казино",
            "clan_contrib": "к вкладу в копилку клана",
        }
        bonus_text = f"+{int(cat.get('bonus_value', 0) * 100)}% {bnames.get(bt, '')}"

        _grad(img, (rpx1, bonus_y1, rpx2, bonus_y2), GOLD, GOLD, alpha=18, radius=14)
        d.rounded_rectangle((rpx1, bonus_y1, rpx2, bonus_y2), radius=14,
                            outline=GOLD + (170,), width=2)

        _alpha(img, (rpx1 + 16, bonus_y1 + 12, rpx1 + 16 + 44, bonus_y1 + 12 + 44),
               GOLD, alpha=45, radius=11)
        _icon(d, rpx1 + 38, bonus_y1 + 34, I_STAR, 22, GOLD)

        d.text((rpx1 + 76, bonus_y1 + 12), "БОНУС РЕДКОСТИ",
               font=_font(10), fill=GOLD)
        d.text((rpx1 + 76, bonus_y1 + 30), bonus_text,
               font=_font(18), fill=GOLD)
    else:
        _grad(img, (rpx1, bonus_y1, rpx2, bonus_y2), SILVER, SILVER, alpha=10, radius=14)
        d.rounded_rectangle((rpx1, bonus_y1, rpx2, bonus_y2), radius=14,
                            outline=INNER_BRD + (255,), width=2)
        _icon(d, rpx1 + 38, bonus_y1 + 34, I_INFO, 22, SILVER)
        d.text((rpx1 + 76, bonus_y1 + 22), "БОНУСОВ НЕТ — обычный питомец",
               font=_font(15), fill=SILVER)

    # 2 ЦЕНЫ — приподняты, чтобы не налезали
    price_h = 130
    price_y2 = body_y + body_h - 22
    price_y1 = price_y2 - price_h

    gap_price = 14
    half_w = (rpx2 - rpx1 - gap_price) // 2

    # Купить себе
    buy_x1 = rpx1
    buy_x2 = buy_x1 + half_w
    _grad(img, (buy_x1, price_y1, buy_x2, price_y2), GREEN, GREEN, alpha=22, radius=18)
    d.rounded_rectangle((buy_x1, price_y1, buy_x2, price_y2), radius=18,
                        outline=GREEN + (190,), width=3)

    _alpha(img, (buy_x1 + 20, price_y1 + 34, buy_x1 + 20 + 62, price_y1 + 34 + 62),
           GREEN, alpha=45, radius=15)
    _icon(d, buy_x1 + 51, price_y1 + 65, I_GEM, 28, GREEN)

    d.text((buy_x1 + 98, price_y1 + 24), "КУПИТЬ СЕБЕ",
           font=_font(12), fill=GREEN)

    price_str = f"{_fmt(price)}"
    pv_f = _font(38)
    pv_w = _tw(d, price_str, pv_f)
    d.text((buy_x1 + 98, price_y1 + 48), price_str, font=pv_f, fill=GREEN)
    d.text((buy_x1 + 98 + pv_w + 8, price_y1 + 48 + pv_f.size - 22),
           "DC", font=_font(18), fill=GREEN)

    d.text((buy_x1 + 98, price_y1 + 96), "добавится в коллекцию",
           font=_font(12), fill=MUTED)

    # Подарить
    gift_x1 = buy_x2 + gap_price
    gift_x2 = gift_x1 + half_w
    _grad(img, (gift_x1, price_y1, gift_x2, price_y2), PURPLE, PURPLE, alpha=22, radius=18)
    d.rounded_rectangle((gift_x1, price_y1, gift_x2, price_y2), radius=18,
                        outline=PURPLE + (190,), width=3)

    _alpha(img, (gift_x1 + 20, price_y1 + 34, gift_x1 + 20 + 62, price_y1 + 34 + 62),
           PURPLE, alpha=45, radius=15)
    _icon(d, gift_x1 + 51, price_y1 + 65, I_GIFT, 28, PURPLE)

    d.text((gift_x1 + 98, price_y1 + 24), "ПОДАРИТЬ · КОМИССИЯ +10%",
           font=_font(12), fill=PURPLE)

    gp_str = f"{_fmt(gp)}"
    gp_w = _tw(d, gp_str, pv_f)
    d.text((gift_x1 + 98, price_y1 + 48), gp_str, font=pv_f, fill=PURPLE)
    d.text((gift_x1 + 98 + gp_w + 8, price_y1 + 48 + pv_f.size - 22),
           "DC", font=_font(18), fill=PURPLE)

    d.text((gift_x1 + 98, price_y1 + 96), "получателю придёт в ЛС",
           font=_font(12), fill=MUTED)

    _footer(d, "Выбери действие в селекте ниже", "стр. 3 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# МОИ ПИТОМЦЫ
# ============================================================
def _hero_active(img, d, x, y, w, h, pet):
    cat = CATALOG.get(pet["pet_key"], {})
    color = RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER)

    _grad(img, (x, y, x + w, y + h), GOLD, GOLD, alpha=18, radius=20)
    d.rounded_rectangle((x, y, x + w, y + h), radius=20,
                        outline=GOLD + (170,), width=3)

    es = 110
    ex = x + 24
    ey = y + (h - es) // 2
    _grad(img, (ex, ey, ex + es, ey + es), color, color, alpha=35, radius=24)
    d.rounded_rectangle((ex, ey, ex + es, ey + es), radius=24,
                        outline=color + (200,), width=3)
    _icon(d, ex + es // 2, ey + es // 2 + 2, cat.get("fa_code", I_PAW), 50, color)

    tx = ex + es + 22
    tx_max = x + w - 260

    d.text((tx, y + 20), "✦ АКТИВНЫЙ ПИТОМЕЦ", font=_font(11), fill=GOLD)

    name_f = _font(30)
    d.text((tx, y + 40), _el(d, cat.get("name", "—"), name_f, tx_max - tx),
           font=name_f, fill=TEXT)

    tag_y = y + 82
    cur_x = tx

    rl = _rarity_label_short(cat.get("rarity", "common"))
    rlf = _font(11)
    rlw = _tw(d, rl, rlf) + 18
    _alpha(img, (cur_x, tag_y, cur_x + rlw, tag_y + 22), color, alpha=55, radius=6)
    d.rounded_rectangle((cur_x, tag_y, cur_x + rlw, tag_y + 22), radius=6,
                        outline=color + (200,), width=1)
    d.text((cur_x + 9, tag_y + 3), rl, font=rlf, fill=color)
    cur_x += rlw + 8

    lvl_text = f"Ур. {pet['level']} / {MAX_LEVEL}"
    lf = _font(11)
    lw = _tw(d, lvl_text, lf) + 18
    _alpha(img, (cur_x, tag_y, cur_x + lw, tag_y + 22), SILVER, alpha=20, radius=6)
    d.rounded_rectangle((cur_x, tag_y, cur_x + lw, tag_y + 22), radius=6,
                        outline=SILVER + (100,), width=1)
    d.text((cur_x + 9, tag_y + 3), lvl_text, font=lf, fill=SILVER_HI)

    cur_xp, need_xp, pct = get_xp_progress(pet)
    xp_y = y + h - 32
    xp_w = tx_max - tx
    d.text((tx, xp_y - 20), "ОПЫТ", font=_font(10), fill=MUTED)
    pct_text = f"{cur_xp} / {need_xp} XP · {pct}%"
    ptw = _tw(d, pct_text, _font(10))
    d.text((tx + xp_w - ptw, xp_y - 20), pct_text, font=_font(10), fill=GOLD)
    _xp_bar(d, img, tx, xp_y, xp_w, 10, pct)

    right_edge = x + w - 24
    d.text((right_edge, y + 24), "НАКОПЛЕНО", font=_font(10), fill=GOLD, anchor="rt")

    val = pet.get("pending_dc") or 0
    val_full = f"+{_fmt(val)} DC"
    vf = _font(38)
    while _tw(d, val_full, vf) > 240 and vf.size > 22:
        vf = _font(vf.size - 2)
    vw = _tw(d, val_full, vf)
    d.text((right_edge - vw, y + 46), val_full, font=vf, fill=GREEN)

    last = pet.get("last_income") or pet.get("purchased_at") or 0
    elapsed = max(int(time.time()) - last, 0) if last else 0
    h_el = elapsed // 3600
    m_el = (elapsed % 3600) // 60
    time_text = f"{h_el}ч {m_el}м копилось"
    tf = _font(12)
    tw_ = _tw(d, time_text, tf)
    d.text((right_edge - tw_, y + 96), time_text, font=tf, fill=MUTED)

    hr = hourly_rate(pet["pet_key"], pet["level"])
    pill_text = f"⚡ {hr:.0f} DC/час"
    pf = _font(12)
    pw = _tw(d, pill_text, pf) + 22
    pill_x = right_edge - pw
    pill_y = y + h - 42
    _alpha(img, (pill_x, pill_y, pill_x + pw, pill_y + 26),
           GREEN, alpha=30, radius=13)
    d.rounded_rectangle((pill_x, pill_y, pill_x + pw, pill_y + 26),
                        radius=13, outline=GREEN + (180,), width=1)
    d.text((pill_x + pw // 2, pill_y + 13), pill_text,
           font=pf, fill=GREEN, anchor="mm")


def _my_pet_row(img, d, x, y, w, h, pet):
    cat = CATALOG.get(pet["pet_key"], {})
    color = RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER)

    d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                        fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)

    pad = 14
    es = 60
    ex = x + pad
    ey = y + (h - es) // 2
    _alpha(img, (ex, ey, ex + es, ey + es), color, alpha=40, radius=13)
    d.rounded_rectangle((ex, ey, ex + es, ey + es), radius=13,
                        outline=color + (170,), width=2)
    _icon(d, ex + es // 2, ey + es // 2 + 1, cat.get("fa_code", I_PAW), 26, color)

    tx = ex + es + 14
    tx_max = x + w - 240

    name_f = _font(17)
    d.text((tx, y + 14), _el(d, cat.get("name", "—"), name_f, tx_max - tx),
           font=name_f, fill=TEXT)

    hr = hourly_rate(pet["pet_key"], pet["level"])
    stat_text = f"Ур. {pet['level']} · {hr:.0f} DC/ч · {pet.get('xp', 0)} XP"
    d.text((tx, y + 38), _el(d, stat_text, _font(12), tx_max - tx),
           font=_font(12), fill=MUTED)

    cur_xp, need_xp, pct = get_xp_progress(pet)
    xp_y = y + h - 18
    xp_w = tx_max - tx
    _xp_bar(d, img, tx, xp_y, xp_w, 8, pct)

    right_x = x + w - pad
    pending = pet.get("pending_dc") or 0
    val_str = f"+{_fmt(pending)}"
    vf = _font(20)
    vw = _tw(d, val_str, vf)
    d.text((right_x - vw, y + 14), val_str, font=vf, fill=GREEN)
    d.text((right_x - 10, y + 14 + vf.size - 12), "DC",
           font=_font(11), fill=GREEN)


def _placeholder_row(img, d, x, y, w, h):
    """Пустой слот — плюс и текст центрированы вместе."""
    d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                        fill=(20, 20, 26) + (255,),
                        outline=INNER_BRD + (255,), width=2)

    # Пунктирная имитация по верхнему и нижнему краю
    for i in range(int(w) - 40):
        if i % 14 < 7:
            d.point((x + 20 + i, y + 5), fill=INNER_BRD)
            d.point((x + 20 + i, y + h - 6), fill=INNER_BRD)

    # Композиция "плюс + текст" — центрируем целиком
    text = "Свободный слот — купи в каталоге"
    tf = _font(13)
    tw_ = _tw(d, text, tf)

    plus_size = 36
    gap = 14
    total_w = plus_size + gap + tw_

    cx_start = x + (w - total_w) // 2
    cy = y + h // 2

    # Плюс
    _alpha(img, (cx_start, cy - plus_size // 2,
                 cx_start + plus_size, cy + plus_size // 2),
           SILVER, alpha=30, radius=10)
    _icon(d, cx_start + plus_size // 2, cy, I_PLUS, 18, SILVER)

    # Текст по центру справа от плюса
    d.text((cx_start + plus_size + gap, cy - tf.size // 2 - 3),
           text, font=tf, fill=MUTED)


def render_my_pets(user_id, balance, pets):
    img, d = _canvas(user_id, "питомцы · мои")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 450
    gap = 28
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    total_pending = sum((p.get("pending_dc") or 0) for p in pets)

    active = next((p for p in pets if p.get("is_active")), None)
    active_name = "—"
    if active:
        cat = CATALOG.get(active["pet_key"], {})
        active_name = f"{cat.get('name', '—')} · ур. {active['level']}"

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Активный питомец", "value": active_name, "icon": I_STAR, "color": GOLD},
        {"label": "Накоплено", "value": f"{_fmt(total_pending)} DC", "icon": I_COINS, "color": GREEN},
        {"label": "Всего питомцев", "value": f"{len(pets)} из {len(CATALOG)}", "icon": I_PAW, "color": BLUE},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 26
    rpx2 = rx2 - 26

    if not pets:
        sub_text = "питомцев пока нет"
    else:
        sub_text = f"{len(pets)} питомцев · {_fmt(total_pending)} DC копится"

    _right_head(d, rpx1, body_y + 22, rpx2, "Мои питомцы", sub_text)

    content_y1 = body_y + 90
    content_y2 = body_y + body_h - 22

    if not pets:
        rows = 6
        gap_row = 8
        row_h = (content_y2 - content_y1 - gap_row * (rows - 1)) // rows
        row_h = min(row_h, 100)

        for i in range(rows):
            cy = content_y1 + i * (row_h + gap_row)
            _placeholder_row(img, d, rpx1, cy, rpx2 - rpx1, row_h)

        _footer(d, "Открой каталог, чтобы купить первого питомца", "стр. 2 / 4")
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        buf.seek(0)
        return buf

    hero_h = 170
    hero_y1 = content_y1
    _hero_active(img, d, rpx1, hero_y1, rpx2 - rpx1, hero_h, active)

    others = [p for p in pets if not p.get("is_active")]
    other_count = len(others)

    list_title_y = hero_y1 + hero_h + 16
    d.text((rpx1, list_title_y),
           "ОСТАЛЬНЫЕ ПИТОМЦЫ" if other_count else "СВОБОДНЫЕ СЛОТЫ",
           font=_font(11), fill=MUTED)
    d.text((rpx2, list_title_y), f"{len(pets)} / {len(CATALOG)}",
           font=_font(11), fill=SILVER, anchor="ra")

    list_y1 = list_title_y + 26
    list_y2 = content_y2

    total_slots = 5
    gap_row = 8
    row_h = (list_y2 - list_y1 - gap_row * (total_slots - 1)) // total_slots
    row_h = min(row_h, 90)

    for i in range(total_slots):
        cy = list_y1 + i * (row_h + gap_row)
        if cy + row_h > list_y2:
            break
        if i < other_count:
            _my_pet_row(img, d, rpx1, cy, rpx2 - rpx1, row_h, others[i])
        else:
            _placeholder_row(img, d, rpx1, cy, rpx2 - rpx1, row_h)

    _footer(d, "Забрать накопленное и покормить питомца — в меню ниже", "стр. 2 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# КАРТОЧКА СВОЕГО ПИТОМЦА
# ============================================================
def render_pet_card(user_id, balance, pet: dict, place: int = None):
    img, d = _canvas(user_id, "питомцы · карточка")

    cat = CATALOG.get(pet["pet_key"], {})
    color = RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER)

    body_y = 140
    body_h = H - M - PY - body_y - 26

    lw = 560
    gap = 28
    lx1 = PX
    lx2 = lx1 + lw
    rx1 = lx2 + gap
    rx2 = W - M - PX

    _panel(img, d, (lx1, body_y, lx2, body_y + body_h), radius=22)
    cx = (lx1 + lx2) // 2

    ic_s = 180
    ic_x = cx - ic_s // 2
    ic_y = body_y + 50
    _grad(img, (ic_x, ic_y, ic_x + ic_s, ic_y + ic_s), color, color, alpha=30, radius=36)
    d.rounded_rectangle((ic_x, ic_y, ic_x + ic_s, ic_y + ic_s), radius=36,
                        outline=color + (200,), width=4)
    _icon(d, cx, ic_y + ic_s // 2 + 2, cat.get("fa_code", I_PAW), 82, color)

    name = cat.get("name", "—")
    nf = _font(32)
    name_shown = _el(d, name, nf, lx2 - lx1 - 60)
    nw = _tw(d, name_shown, nf)
    d.text((cx - nw // 2, ic_y + ic_s + 24), name_shown, font=nf, fill=TEXT)

    rl = _rarity_label_short(cat.get("rarity", "common"))
    rlf = _font(15)
    rlw = _tw(d, rl, rlf) + 28
    ry = ic_y + ic_s + 68
    _alpha(img, (cx - rlw // 2, ry, cx + rlw // 2, ry + 30), color, alpha=55, radius=8)
    d.rounded_rectangle((cx - rlw // 2, ry, cx + rlw // 2, ry + 30), radius=8,
                        outline=color + (200,), width=2)
    d.text((cx, ry + 15), rl, font=rlf, fill=color, anchor="mm")

    if pet.get("is_active"):
        ay = ry + 42
        txt = "✦ АКТИВНЫЙ"
        tf = _font(14)
        tw_ = _tw(d, txt, tf) + 32
        _alpha(img, (cx - tw_ // 2, ay, cx + tw_ // 2, ay + 34), GOLD, alpha=40, radius=10)
        d.rounded_rectangle((cx - tw_ // 2, ay, cx + tw_ // 2, ay + 34), radius=10,
                            outline=GOLD + (220,), width=2)
        d.text((cx, ay + 17), txt, font=tf, fill=GOLD, anchor="mm")

    bt = cat.get("bonus_type", "none")
    if bt != "none":
        bnames = {"review_bonus": "к отзывам", "casino_luck": "к казино", "clan_contrib": "к копилке клана"}
        btext = f"+{int(cat.get('bonus_value', 0) * 100)}% {bnames.get(bt, '')}"
        bf = _font(14)
        bw = _tw(d, btext, bf) + 36
        by = body_y + body_h - 70
        _alpha(img, (cx - bw // 2, by, cx + bw // 2, by + 38), GOLD, alpha=25, radius=12)
        d.rounded_rectangle((cx - bw // 2, by, cx + bw // 2, by + 38), radius=12,
                            outline=GOLD + (180,), width=2)
        d.text((cx, by + 19), btext, font=bf, fill=GOLD, anchor="mm")

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 26
    rpx2 = rx2 - 26

    _right_head(d, rpx1, body_y + 22, rpx2, "Информация",
                f"УР. {pet['level']} / {MAX_LEVEL}")

    dy = body_y + 100
    desc_h = 110
    d.rounded_rectangle((rpx1, dy, rpx2, dy + desc_h), radius=14,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    desc = cat.get("description", "")
    df = _font(16)
    lines = []
    cur = ""
    for word in desc.split():
        test = (cur + " " + word).strip()
        if _tw(d, test, df) <= rpx2 - rpx1 - 36:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = word
    if cur: lines.append(cur)
    for i, line in enumerate(lines[:3]):
        d.text((rpx1 + 18, dy + 18 + i * 22), line, font=df, fill=TEXT_SOFT)

    sy = dy + desc_h + 14
    sh = 100

    d.rounded_rectangle((rpx1, sy, rpx2, sy + sh), radius=14,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    _alpha(img, (rpx1 + 18, sy + 24, rpx1 + 70, sy + 76), PURPLE, alpha=45, radius=12)
    _icon(d, rpx1 + 44, sy + 50, I_STAR, 24, PURPLE)
    d.text((rpx1 + 92, sy + 18), "УРОВЕНЬ И ОПЫТ", font=_font(11), fill=MUTED)
    d.text((rpx1 + 92, sy + 38), f"Ур. {pet['level']} · {_fmt(pet['xp'])} XP",
           font=_font(20), fill=TEXT)

    cur_xp, need_xp, pct = get_xp_progress(pet)
    bx1 = rpx1 + 92
    bx2 = rpx2 - 24
    by = sy + sh - 24
    _xp_bar(d, img, bx1, by, bx2 - bx1, 10, pct)
    if need_xp > 0:
        d.text((bx2, by - 18), f"{cur_xp} / {need_xp} · {pct}%",
               font=_font(11), fill=MUTED, anchor="rs")

    sy += sh + 12
    hourly = hourly_rate(pet["pet_key"], pet["level"])
    cap = max_pending(pet["pet_key"], pet["level"])
    pending = pet.get("pending_dc") or 0
    last = pet.get("last_income") or pet.get("purchased_at") or 0
    elapsed = max(int(time.time()) - last, 0) if last else 0
    h_el = elapsed // 3600
    m_el = (elapsed % 3600) // 60

    d.rounded_rectangle((rpx1, sy, rpx2, sy + sh), radius=14,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    _alpha(img, (rpx1 + 18, sy + 24, rpx1 + 70, sy + 76), GREEN, alpha=45, radius=12)
    _icon(d, rpx1 + 44, sy + 50, I_COINS, 24, GREEN)
    d.text((rpx1 + 92, sy + 18), "ДОХОД И НАКОПЛЕНИЯ", font=_font(11), fill=MUTED)
    d.text((rpx1 + 92, sy + 38), f"{hourly:.1f} DC/час · кап {_fmt(cap)} DC",
           font=_font(18), fill=GREEN)

    d.text((rpx2 - 24, sy + 18), f"+{_fmt(pending)} DC",
           font=_font(22), fill=GREEN, anchor="rt")
    d.text((rpx2 - 24, sy + 50), f"копилось {h_el}ч {m_el}м",
           font=_font(11), fill=MUTED, anchor="rt")

    sy += sh + 12
    d.rounded_rectangle((rpx1, sy, rpx2, sy + 58), radius=14,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

    _icon(d, rpx1 + 32, sy + 29, I_TROPHY, 20, GOLD)
    place_str = f"#{place}" if place else "—"
    d.text((rpx1 + 58, sy + 16), f"МЕСТО В ТОПЕ: {place_str}",
           font=_font(13), fill=GOLD)

    _icon(d, rpx1 + 260, sy + 29, I_CLOCK, 16, MUTED)
    d.text((rpx1 + 284, sy + 20), f"КУПЛЕН: {_fmt_date(pet.get('purchased_at'))}",
           font=_font(13), fill=MUTED)

    _footer(d, "Покормить и сделать активным — в меню ниже", "стр. 3 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# УСПЕХ ПОКУПКИ
# ============================================================
def render_success_buy(user_id, balance, pet_key: str, price: int):
    img, d = _canvas(user_id, "питомцы · покупка")

    cat = CATALOG.get(pet_key, {})

    body_y = 140
    body_h = H - M - PY - body_y - 26

    lw = 450
    gap = 28
    lx1 = PX
    lx2 = lx1 + lw
    rx1 = lx2 + gap
    rx2 = W - M - PX

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Списано", "value": f"{_fmt(price)} DC", "icon": I_COINS, "color": GREEN},
        {"label": "Питомец", "value": cat.get("name", "—"), "icon": I_PAW, "color": GOLD},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 26
    rpx2 = rx2 - 26

    _right_head(d, rpx1, body_y + 22, rpx2, "Покупка", "успешно")

    cx = (rpx1 + rpx2) // 2
    cy_start = body_y + 130

    circle_r = 110
    circle_cy = cy_start + circle_r
    _grad_radial_circle(img, cx, circle_cy, circle_r, GREEN, GREEN_DK, alpha=255)

    d.ellipse((cx - circle_r - 6, circle_cy - circle_r - 6,
               cx + circle_r + 6, circle_cy + circle_r + 6),
              outline=GREEN + (30,), width=12)
    d.ellipse((cx - circle_r, circle_cy - circle_r,
               cx + circle_r, circle_cy + circle_r),
              outline=GREEN + (180,), width=4)

    _icon(d, cx, circle_cy, I_CHECK, 110, (255, 255, 255))

    title_y = circle_cy + circle_r + 40
    title = "Питомец куплен!"
    tf = _font(48)
    tw_ = _tw(d, title, tf)
    d.text((cx - tw_ // 2, title_y), title, font=tf, fill=GREEN)

    sub_y = title_y + 70
    sub = "Теперь он у тебя в коллекции и начнёт приносить DC уже сейчас"
    sf = _font(17)
    sw = _tw(d, sub, sf)
    d.text((cx - sw // 2, sub_y), sub, font=sf, fill=MUTED)

    item_y = sub_y + 50
    item_h = 70
    name = cat.get("name", "—")
    nf = _font(30)
    nw = _tw(d, name, nf)

    icon_size = 52
    gap_inner = 16
    total_w = icon_size + gap_inner + nw
    px_w = total_w + 60
    px_x = cx - px_w // 2

    d.rounded_rectangle((px_x, item_y, px_x + px_w, item_y + item_h),
                        radius=16, fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)

    _alpha(img, (px_x + 20, item_y + 9, px_x + 20 + icon_size, item_y + 9 + icon_size),
           RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER), alpha=40, radius=13)
    _icon(d, px_x + 20 + icon_size // 2, item_y + 9 + icon_size // 2 + 1,
          cat.get("fa_code", I_PAW), 26,
          RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER))

    d.text((px_x + 20 + icon_size + gap_inner,
            item_y + (item_h - nf.size) // 2 - 2),
           name, font=nf, fill=TEXT)

    price_y = item_y + item_h + 24
    price_text = f"−{_fmt(price)} DC"
    pf = _font(28)
    pw = _tw(d, price_text, pf)
    d.text((cx - pw // 2, price_y), price_text, font=pf, fill=GREEN)

    _footer(d, "Открой «Мои питомцы» чтобы забрать DC", "стр. 3 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# УСПЕХ ПОДАРКА
# ============================================================
def render_success_gift(user_id, balance, pet_key: str, price: int,
                        base_price: int, recipient_id: int):
    img, d = _canvas(user_id, "питомцы · подарок")

    cat = CATALOG.get(pet_key, {})

    body_y = 140
    body_h = H - M - PY - body_y - 26

    lw = 450
    gap = 28
    lx1 = PX
    lx2 = lx1 + lw
    rx1 = lx2 + gap
    rx2 = W - M - PX

    commission = price - base_price

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Списано", "value": f"{_fmt(price)} DC", "icon": I_COINS, "color": GOLD},
        {"label": "Комиссия", "value": f"{_fmt(commission)} DC (10%)", "icon": I_GIFT, "color": PURPLE},
        {"label": "Питомец", "value": cat.get("name", "—"), "icon": I_PAW, "color": GOLD},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 26
    rpx2 = rx2 - 26

    _right_head(d, rpx1, body_y + 22, rpx2, "Подарок", "доставлен")

    cx = (rpx1 + rpx2) // 2
    cy_start = body_y + 110

    circle_r = 110
    circle_cy = cy_start + circle_r
    _grad_radial_circle(img, cx, circle_cy, circle_r, GOLD, GOLD_DK, alpha=255)

    d.ellipse((cx - circle_r - 6, circle_cy - circle_r - 6,
               cx + circle_r + 6, circle_cy + circle_r + 6),
              outline=GOLD + (30,), width=12)
    d.ellipse((cx - circle_r, circle_cy - circle_r,
               cx + circle_r, circle_cy + circle_r),
              outline=GOLD + (180,), width=4)

    _icon(d, cx, circle_cy, I_GIFT, 100, (26, 18, 6))

    title_y = circle_cy + circle_r + 32
    title = "Подарок отправлен!"
    tf = _font(46)
    tw_ = _tw(d, title, tf)
    d.text((cx - tw_ // 2, title_y), title, font=tf, fill=GOLD)

    who_lbl_y = title_y + 64
    who_lbl = "ПОЛУЧАТЕЛЬ"
    wlf = _font(12)
    wlw = _tw(d, who_lbl, wlf)
    d.text((cx - wlw // 2, who_lbl_y), who_lbl, font=wlf, fill=MUTED)

    who_y = who_lbl_y + 22
    who = f"@{recipient_id}"
    wf = _font(28)
    ww = _tw(d, who, wf)
    d.text((cx - ww // 2, who_y), who, font=wf, fill=TEXT)

    item_y = who_y + 56
    item_h = 66
    name = cat.get("name", "—")
    nf = _font(26)
    nw = _tw(d, name, nf)

    icon_size = 46
    gap_inner = 14
    total_w = icon_size + gap_inner + nw
    px_w = total_w + 56
    px_x = cx - px_w // 2

    _grad(img, (px_x, item_y, px_x + px_w, item_y + item_h),
          GOLD, GOLD, alpha=18, radius=14)
    d.rounded_rectangle((px_x, item_y, px_x + px_w, item_y + item_h),
                        radius=14, outline=GOLD + (170,), width=2)

    _alpha(img, (px_x + 18, item_y + 10, px_x + 18 + icon_size, item_y + 10 + icon_size),
           GOLD, alpha=45, radius=11)
    _icon(d, px_x + 18 + icon_size // 2, item_y + 10 + icon_size // 2 + 1,
          cat.get("fa_code", I_PAW), 24, GOLD)

    d.text((px_x + 18 + icon_size + gap_inner,
            item_y + (item_h - nf.size) // 2 - 2),
           name, font=nf, fill=GOLD)

    price_y = item_y + item_h + 20
    price_text = f"Списано: −{_fmt(price)} DC (комиссия {_fmt(commission)})"
    pf = _font(17)
    pw = _tw(d, price_text, pf)
    d.text((cx - pw // 2, price_y), price_text, font=pf, fill=MUTED)

    _footer(d, "Получатель уже получил уведомление в ЛС", "стр. 3 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# ТОП
# ============================================================
def _top_row(img, d, x, y, w, h, rank, entry, is_me):
    if rank == 1:
        medal = GOLD
    elif rank == 2:
        medal = SILVER
    elif rank == 3:
        medal = BRONZE
    else:
        medal = DIM

    if is_me:
        _grad(img, (x, y, x + w, y + h), BLUE, BLUE, alpha=12, radius=12)
        d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                            outline=BLUE + (200,), width=2)
    elif rank <= 3:
        _grad(img, (x, y, x + w, y + h), medal, medal, alpha=12, radius=12)
        d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                            outline=medal + (180,), width=2)
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                            fill=INNER_BG + (255,),
                            outline=INNER_BRD + (255,), width=2)

    pad = 16
    bs = 44
    bx = x + pad
    by = y + (h - bs) // 2
    _alpha(img, (bx, by, bx + bs, by + bs), medal, alpha=55, radius=11)
    d.rounded_rectangle((bx, by, bx + bs, by + bs), radius=11,
                        outline=medal + (200,), width=2)
    if rank <= 3:
        _icon(d, bx + bs // 2, by + bs // 2 + 1,
              I_CROWN if rank == 1 else I_MEDAL, 20, medal)
    else:
        nstr = str(rank)
        nf = _font(18)
        nw = _tw(d, nstr, nf)
        d.text((bx + bs // 2 - nw // 2, by + bs // 2 - nf.size // 2 - 2),
               nstr, font=nf, fill=medal)

    cat = CATALOG.get(entry.get("pet_key") or "", {})
    color = RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER)

    es = 56
    ex = bx + bs + 14
    ey = y + (h - es) // 2
    _alpha(img, (ex, ey, ex + es, ey + es), color, alpha=40, radius=12)
    d.rounded_rectangle((ex, ey, ex + es, ey + es), radius=12,
                        outline=color + (170,), width=2)
    _icon(d, ex + es // 2, ey + es // 2 + 1, cat.get("fa_code", I_PAW), 24, color)

    tx = ex + es + 16
    tx_max = x + w - 200

    name = f"@{entry['user_id']}"
    if is_me:
        name += " · это ты"
    name_f = _font(17)
    name_shown = _el(d, name, name_f, tx_max - tx)
    d.text((tx, y + 14), name_shown, font=name_f,
           fill=BLUE if is_me else TEXT)

    pet_name = cat.get("name", "—")
    pets_count = entry.get("pets_count", 0)
    sub_text = f"Лучший: {pet_name} · {pets_count} питомцев"
    d.text((tx, y + 38), _el(d, sub_text, _font(12), tx_max - tx),
           font=_font(12), fill=MUTED)

    val = f"ур. {entry['best_level']}"
    vf = _font(22)
    vw = _tw(d, val, vf)
    d.text((x + w - pad - vw, y + h // 2 - 14), val, font=vf,
           fill=BLUE if is_me else (medal if rank <= 3 else SILVER_HI))


def render_top(user_id, balance, top_list: List[dict], my_place: int = None,
               my_best_pet: Optional[dict] = None):
    img, d = _canvas(user_id, "питомцы · топ")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 450
    gap = 28
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    my_best = "—"
    if my_best_pet:
        my_best = f"{my_best_pet['name']} · ур. {my_best_pet['level']}"

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Твоё место", "value": f"#{my_place}" if my_place else "—",
         "icon": I_TROPHY, "color": GOLD},
        {"label": "Лучший питомец", "value": my_best,
         "icon": I_STAR, "color": PURPLE},
        {"label": "Всего участников", "value": f"{len(top_list)}",
         "icon": I_USERS, "color": BLUE},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 26
    rpx2 = rx2 - 26

    sub_text = "топ-8 питомцеводов" if top_list else "пока пусто"
    _right_head(d, rpx1, body_y + 22, rpx2, "Топ питомцеводов", sub_text)

    list_y1 = body_y + 90
    list_y2 = body_y + body_h - 22

    if not top_list:
        cx = (rpx1 + rpx2) // 2
        cy = (list_y1 + list_y2) // 2 - 30

        _alpha(img, (cx - 60, cy - 60, cx + 60, cy + 60), SILVER, alpha=20, radius=30)
        _icon(d, cx, cy, I_TROPHY, 56, SILVER)

        d.text((cx, cy + 100), "Пока нет питомцеводов",
               font=_font(22), fill=TEXT, anchor="mm")
        d.text((cx, cy + 136), "Купи питомца — и займи первое место",
               font=_font(14), fill=MUTED, anchor="mm")

        _footer(d, "Топ обновляется каждый час", "стр. 4 / 4")
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        buf.seek(0)
        return buf

    rows = min(len(top_list), 8)
    gap_row = 8
    row_h = (list_y2 - list_y1 - gap_row * (rows - 1)) // rows
    row_h = min(row_h, 82)

    for i, entry in enumerate(top_list[:rows]):
        cy = list_y1 + i * (row_h + gap_row)
        if cy + row_h > list_y2:
            break
        _top_row(img, d, rpx1, cy, rpx2 - rpx1, row_h, i + 1, entry,
                 entry["user_id"] == user_id)

    _footer(d, "Топ обновляется каждый час", "стр. 4 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
