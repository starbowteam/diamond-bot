# -*- coding: utf-8 -*-
"""
Pillow-рендеры панели питомцев.
4 экрана: каталог (2×3 крупные), мои питомцы (hero + сетка 3×2), карточка, топ (пьедестал + список).
"""
import io
import os
import time
from typing import List, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, logger
from pet.core import (
    CATALOG, RARITY_LABEL, RARITY_PALETTE,
    get_xp_progress, hourly_rate, max_pending, MAX_LEVEL,
)


# ============================================================
# ШРИФТЫ
# ============================================================
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


# ============================================================
# ПАЛИТРА
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
DARK      = (85, 85, 85)

SILVER    = (198, 208, 224)
SILVER_HI = (224, 232, 245)
GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)
GOLD      = (247, 201, 145)
BRONZE    = (209, 146, 96)
PINK      = (255, 77, 148)

GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)
GOLD_BG   = (40, 32, 21)

CARD_BRD  = (74, 74, 79)

# FA-коды
I_GEM      = 0xf3a5
I_USER     = 0xf007
I_INFO     = 0xf05a
I_COINS    = 0xf51e
I_CLOCK    = 0xf017
I_STAR     = 0xf005
I_CROWN    = 0xf521
I_TROPHY   = 0xf091
I_MEDAL    = 0xf5a2
I_PAW      = 0xf1b0
I_HAND     = 0xf4c0
I_CART     = 0xf07a
I_BOLT     = 0xf0e7
I_CHART    = 0xf201
I_FIRE     = 0xf06d
I_UTENSILS = 0xf2e7
I_CHECK    = 0xf00c
I_ELL      = 0xf141
I_PLUS     = 0xf067
I_LOCK     = 0xf023


# ============================================================
# УТИЛИТЫ
# ============================================================
def _tw(d, t, f):
    b = d.textbbox((0, 0), t, font=f); return b[2] - b[0]


def _th(d, t, f):
    b = d.textbbox((0, 0), t, font=f); return b[3] - b[1]


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
    _alpha(img, (x1 + 12, y1 + 12, x2 + 12, y2 + 12),
           (46, 46, 52), alpha=110, radius=radius)
    _alpha(img, (x1 + 6, y1 + 6, x2 + 6, y2 + 6),
           (46, 46, 52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=2)


def _lighten(c, a=0.4):
    a = max(0, min(1, a))
    return (min(int(c[0] + (255 - c[0]) * a), 255),
            min(int(c[1] + (255 - c[1]) * a), 255),
            min(int(c[2] + (255 - c[2]) * a), 255))


def _darken(c, a=0.4):
    a = max(0, min(1, a))
    return (max(int(c[0] * (1 - a)), 0),
            max(int(c[1] * (1 - a)), 0),
            max(int(c[2] * (1 - a)), 0))


def _fmt(n):
    try: return f"{int(n):,}".replace(",", " ")
    except: return str(n)


# ============================================================
# КАРКАС
# ============================================================
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
    d.text((PX + 38, y), left, font=_font(15), fill=DIM)
    pw = _tw(d, page, _font(15))
    d.text((W - M - PX - pw, y), page, font=_font(15), fill=DIM)


def _left_panel(img, d, box, balance, blocks):
    _panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 28

    bs = 84
    ibx = x1 + pad; iby = y1 + pad
    _grad(img, (ibx, iby, ibx + bs, iby + bs), SILVER, (120, 132, 155), alpha=42, radius=22)
    d.rounded_rectangle((ibx, iby, ibx + bs, iby + bs), radius=22,
                        outline=SILVER + (200,), width=3)
    _icon(d, ibx + bs // 2, iby + bs // 2 + 1, I_GEM, 34, SILVER_HI)

    lx = ibx + bs + 20
    d.text((lx, iby + 8), "ТВОЙ БАЛАНС", font=_font(14), fill=MUTED)
    bstr = _fmt(balance)
    vf = _font(46)
    max_w = x2 - pad - lx - 16
    while _tw(d, bstr + " DC", vf) > max_w and vf.size > 24:
        vf = _font(vf.size - 2)
    d.text((lx, iby + 30), bstr, font=vf, fill=TEXT)
    bvv = _tw(d, bstr, vf)
    d.text((lx + bvv + 8, iby + 30 + vf.size - 26), "DC", font=_font(22), fill=SILVER)

    sy = iby + bs + 26
    d.line((x1 + pad, sy, x2 - pad, sy), fill=STACK_HDR + (255,), width=2)

    if not blocks:
        return

    bb_h = 92
    bb_gap = 14
    top_y = sy + 26

    for i, blk in enumerate(blocks):
        by1 = top_y + i * (bb_h + bb_gap)
        if by1 + bb_h > y2 - pad:
            break
        by2 = by1 + bb_h
        bx1, bx2 = x1 + pad, x2 - pad
        color = blk["color"]
        light = _lighten(color, 0.4)
        border = _lighten(color, 0.25)

        _grad(img, (bx1, by1, bx2, by2), color, color, alpha=30, radius=15)
        d.rounded_rectangle((bx1, by1, bx2, by2), radius=15,
                            outline=border + (255,), width=3)
        d.rounded_rectangle((bx1 + 4, by1 + 12, bx1 + 8, by2 - 12),
                            radius=2, fill=color + (255,))

        ic_s = 50
        iic_x = bx1 + 20
        iic_y = by1 + (bb_h - ic_s) // 2
        _alpha(img, (iic_x, iic_y, iic_x + ic_s, iic_y + ic_s), color, alpha=70, radius=13)
        d.rounded_rectangle((iic_x, iic_y, iic_x + ic_s, iic_y + ic_s),
                            radius=13, outline=border + (200,), width=2)
        _icon(d, iic_x + ic_s // 2, iic_y + ic_s // 2 + 1,
              blk.get("icon", I_INFO), 24, color)

        tx = iic_x + ic_s + 16
        d.text((tx, by1 + 14), blk.get("label", "").upper(), font=_font(13), fill=light)
        bv = blk.get("value", "—")
        bvf = _font(22)
        bv_shown = _el(d, str(bv), bvf, bx2 - 18 - tx)
        d.text((tx, by1 + 42), bv_shown, font=bvf, fill=color)


def _right_head(d, x1, y1, x2, title, sub):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 50), radius=3, fill=SILVER + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(30), fill=TEXT)
    sw = _tw(d, sub.upper(), _font(14))
    d.text((x2 - sw, y1 + 20), sub.upper(), font=_font(14), fill=MUTED)
    d.line((x1, y1 + 66, x2, y1 + 66), fill=STACK_HDR + (255,), width=2)


# ============================================================
# МЕЛКИЕ ЭЛЕМЕНТЫ
# ============================================================
def _rarity_badge(d, x, y, rarity, font_sz=11):
    color = RARITY_PALETTE.get(rarity, SILVER)
    border = _lighten(color, 0.25)
    label = RARITY_LABEL.get(rarity, "—").upper()
    f = _font(font_sz)
    w = _tw(d, label, f) + 20
    h = font_sz + 10
    _alpha(d._image, (x, y, x + w, y + h), color, alpha=55, radius=6)
    d.rounded_rectangle((x, y, x + w, y + h), radius=6, outline=border + (200,), width=1)
    d.text((x + 10, y + 3), label, font=f, fill=color)
    return w


def _xp_bar(d, img, x, y, w, h, pct, fill_c1=PURPLE, fill_c2=BLUE):
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=(28, 28, 34))
    fill_w = int(w * pct / 100)
    if fill_w > 0:
        _grad(img, (x, y, x + fill_w, y + h), fill_c1, fill_c2, alpha=255, radius=h // 2)


# ============================================================
# ЭКРАН 1: КАТАЛОГ (2×3 крупные карточки)
# ============================================================
def _catalog_card(img, d, x, y, w, h, key, cat, owned):
    color = RARITY_PALETTE.get(cat["rarity"], SILVER)
    border = _lighten(color, 0.2)

    if owned:
        d.rounded_rectangle((x, y, x + w, y + h), radius=20,
                            fill=INNER_BG + (255,),
                            outline=(255, 107, 107, 130), width=2)
    else:
        _grad(img, (x, y, x + w, y + h), color, color, alpha=10, radius=20)
        d.rounded_rectangle((x, y, x + w, y + h), radius=20,
                            outline=border + (200,), width=2)

    pad = 22

    # Бейдж "КУПЛЕНО" в углу
    if owned:
        bw = 110
        bh = 30
        bx = x + w - bw
        by = y
        d.rounded_rectangle((bx, by, bx + bw, by + bh),
                            radius=0, fill=(255, 107, 107, 200))
        d.rounded_rectangle((bx, by, bx + bw, by + bh),
                            corners=(0, 20, 0, 14), fill=(255, 107, 107, 210))
        d.text((bx + bw // 2, by + bh // 2), "КУПЛЕНО",
               font=_font(12), fill=(255, 255, 255), anchor="mm")

    # Emoji 100×100
    es = 100
    ex = x + pad
    ey = y + pad
    _alpha(img, (ex, ey, ex + es, ey + es), color, alpha=40, radius=22)
    d.rounded_rectangle((ex, ey, ex + es, ey + es), radius=22,
                        outline=color + (180,), width=3)
    _icon(d, ex + es // 2, ey + es // 2 + 2, cat["fa_code"], 48, color)

    # Редкость под emoji
    _rarity_badge(d, ex, ey + es + 10, cat["rarity"], font_sz=11)

    # Инфа справа от emoji
    tx = ex + es + 20
    tx_max = x + w - pad

    # Имя
    d.text((tx, ey + 4), cat["name"], font=_font(24), fill=TEXT)

    # Описание (2 строки)
    desc = cat.get("description", "")
    df = _font(13)
    lines = []
    cur = ""
    for word in desc.split():
        test = (cur + " " + word).strip()
        if _tw(d, test, df) <= tx_max - tx:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = word
            if len(lines) >= 2: break
    if cur and len(lines) < 2: lines.append(cur)
    for i, line in enumerate(lines):
        d.text((tx, ey + 40 + i * 18), line, font=df, fill=MUTED)

    # Цена справа вверху
    price_val = _fmt(cat["price_dc"])
    pv_f = _font(28)
    pl_f = _font(11)
    pw = _tw(d, price_val, pv_f)
    pw2 = _tw(d, " DC", _font(15))
    d.text((tx_max - pw - pw2, ey + 4), price_val, font=pv_f, fill=(74, 74, 82) if owned else SILVER_HI)
    d.text((tx_max - pw2 + 4, ey + 4 + pv_f.size - 20), " DC", font=_font(15), fill=MUTED)
    price_lbl = "ЦЕНА"
    plw = _tw(d, price_lbl, pl_f)
    d.text((tx_max - plw, ey + 4 + pv_f.size + 6), price_lbl, font=pl_f, fill=MUTED)

    # Окупится за
    if not owned:
        base = cat["passive_dc"]
        price = cat["price_dc"]
        days = int(price / (base * 24)) if base > 0 else 0
        pb_text = f"~{days} дн окупаемость"
        pbf = _font(11)
        pbw = _tw(d, pb_text, pbf)
        d.text((tx_max - pbw, ey + 4 + pv_f.size + 24), pb_text, font=pbf, fill=GREEN)

    # Статы внизу карточки
    stats_y = y + h - pad - 56
    d.line((x + pad, stats_y - 8, x + w - pad, stats_y - 8),
           fill=INNER_BRD + (255,), width=1)

    # 2 стат-блока
    base = cat["passive_dc"]
    max_rate = base * (1 + (MAX_LEVEL - 1) * 0.15)

    sb_w = (w - pad * 2 - 12) // 2
    sb_h = 56

    # блок 1 — доход базовый
    d.rounded_rectangle((x + pad, stats_y, x + pad + sb_w, stats_y + sb_h),
                        radius=10, fill=(10, 10, 14) + (255,),
                        outline=INNER_BRD + (255,), width=1)
    d.text((x + pad + 14, stats_y + 6), "ДОХОД",
           font=_font(10), fill=MUTED)
    d.text((x + pad + 14, stats_y + 22), f"{base} DC/ч",
           font=_font(17), fill=GREEN)

    # блок 2 — доход на максималке
    d.rounded_rectangle((x + pad + sb_w + 12, stats_y,
                         x + pad + sb_w * 2 + 12, stats_y + sb_h),
                        radius=10, fill=(10, 10, 14) + (255,),
                        outline=INNER_BRD + (255,), width=1)
    d.text((x + pad + sb_w + 26, stats_y + 6), "НА МАКС. УР.",
           font=_font(10), fill=MUTED)
    d.text((x + pad + sb_w + 26, stats_y + 22), f"{max_rate:.0f} DC/ч",
           font=_font(17), fill=GREEN)

    # Бонус (если есть) — на месте, где не хватает
    bt = cat.get("bonus_type", "none")
    if bt != "none":
        bnames = {
            "review_bonus": "к отзывам",
            "casino_luck": "к казино",
            "clan_contrib": "к копилке клана",
        }
        btext = f"✦ +{int(cat.get('bonus_value', 0) * 100)}% {bnames.get(bt, '')}"
        bf = _font(12)
        bw = _tw(d, btext, bf) + 20
        bx = x + pad
        by = stats_y - 6
        # рисуем бонус под описанием, над статами
        by2 = stats_y - 36
        _alpha(img, (bx, by2, bx + bw, by2 + 24), GOLD, alpha=25, radius=8)
        d.rounded_rectangle((bx, by2, bx + bw, by2 + 24), radius=8,
                            outline=GOLD + (180,), width=1)
        d.text((bx + 10, by2 + 5), btext, font=bf, fill=GOLD)


def render_catalog(user_id, balance, owned_keys, active_key=None):
    img, d = _canvas(user_id, "питомцы · каталог")
    d._image = img  # для _rarity_badge

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 450
    gap = 28
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    total = len(CATALOG)
    owned_count = len(owned_keys)

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "В каталоге", "value": f"{total} питомцев", "icon": I_PAW, "color": BLUE},
        {"label": "У тебя есть", "value": f"{owned_count} из {total}", "icon": I_CHECK, "color": GREEN},
        {"label": "Топ по доходу", "value": "Даймондик · 20 DC/ч", "icon": I_CROWN, "color": GOLD},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    sub_text = "все питомцы уже у тебя" if owned_count >= total else "выбери в меню ниже"
    _right_head(d, rpx1, body_y + 22, rpx2, "Каталог питомцев", sub_text)

    grid_y1 = body_y + 100
    grid_y2 = body_y + body_h - 22
    grid_h = grid_y2 - grid_y1

    cols, rows = 2, 3
    cgap = 14
    cw = (rpx2 - rpx1 - cgap * (cols - 1)) // cols
    ch = (grid_h - cgap * (rows - 1)) // rows

    for idx, (key, cat) in enumerate(CATALOG.items()):
        r = idx // cols
        c = idx % cols
        cx = rpx1 + c * (cw + cgap)
        cy = grid_y1 + r * (ch + cgap)
        _catalog_card(img, d, cx, cy, cw, ch, key, cat, key in owned_keys)

    footer_text = "Коллекция собрана — новых питомцев скоро добавят!" if owned_count >= total else "Выбери питомца в меню ниже чтобы купить"
    _footer(d, footer_text, "стр. 1 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 2: МОИ ПИТОМЦЫ (hero + сетка 3×2)
# ============================================================
def _hero_active(img, d, x, y, w, h, pet):
    """Hero — активный питомец."""
    cat = CATALOG.get(pet["pet_key"], {})
    color = RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER)

    # Фон
    _grad(img, (x, y, x + w, y + h), GOLD, GOLD, alpha=18, radius=22)
    d.rounded_rectangle((x, y, x + w, y + h), radius=22,
                        outline=GOLD + (180,), width=3)

    # Emoji слева
    es = 130
    ex = x + 30
    ey = y + (h - es) // 2
    _grad(img, (ex, ey, ex + es, ey + es), color, color, alpha=35, radius=28)
    d.rounded_rectangle((ex, ey, ex + es, ey + es), radius=28,
                        outline=color + (200,), width=3)
    _icon(d, ex + es // 2, ey + es // 2 + 2, cat.get("fa_code", I_PAW), 60, color)

    # Середина: label, name, теги, xp
    tx = ex + es + 26
    tx_max = x + w - 250  # 250 отступ для правой части

    d.text((tx, y + 26), "✦ АКТИВНЫЙ ПИТОМЕЦ",
           font=_font(12), fill=GOLD)

    name = cat.get("name", "—")
    name_f = _font(36)
    name_shown = _el(d, name, name_f, tx_max - tx)
    d.text((tx, y + 48), name_shown, font=name_f, fill=TEXT)

    # Теги
    tag_y = y + 108
    cur_x = tx

    # Редкость
    bw = _rarity_badge(d, cur_x, tag_y, cat.get("rarity", "common"), font_sz=11)
    cur_x += bw + 8

    # Уровень
    lvl_text = f"Ур. {pet['level']} / {MAX_LEVEL}"
    lf = _font(12)
    lw = _tw(d, lvl_text, lf) + 20
    _alpha(img, (cur_x, tag_y, cur_x + lw, tag_y + 21), SILVER, alpha=20, radius=6)
    d.rounded_rectangle((cur_x, tag_y, cur_x + lw, tag_y + 21), radius=6,
                        outline=SILVER + (80,), width=1)
    d.text((cur_x + 10, tag_y + 3), lvl_text, font=lf, fill=SILVER_HI)
    cur_x += lw + 8

    # Бонус (если есть)
    bt = cat.get("bonus_type", "none")
    if bt != "none":
        bnames = {"review_bonus": "к отзывам", "casino_luck": "к казино", "clan_contrib": "к клану"}
        btext = f"+{int(cat.get('bonus_value', 0) * 100)}% {bnames.get(bt, '')}"
        bw2 = _tw(d, btext, lf) + 20
        _alpha(img, (cur_x, tag_y, cur_x + bw2, tag_y + 21), GOLD, alpha=25, radius=6)
        d.rounded_rectangle((cur_x, tag_y, cur_x + bw2, tag_y + 21), radius=6,
                            outline=GOLD + (150,), width=1)
        d.text((cur_x + 10, tag_y + 3), btext, font=lf, fill=GOLD)

    # XP bar снизу
    cur_xp, need_xp, pct = get_xp_progress(pet)
    xp_y = y + h - 42
    xp_w = tx_max - tx
    d.text((tx, xp_y - 20), "Опыт", font=_font(12), fill=MUTED)
    pct_text = f"{cur_xp} / {need_xp} XP · {pct}%"
    ptw = _tw(d, pct_text, _font(12))
    d.text((tx + xp_w - ptw, xp_y - 20), pct_text, font=_font(12), fill=GOLD)

    _xp_bar(d, img, tx, xp_y, xp_w, 12, pct)

    # Правая часть: накоплено
    right_x = x + w - 30
    d.text((right_x, y + 38), "НАКОПЛЕНО",
           font=_font(11), fill=GOLD, anchor="rt")

    val = pet.get("pending_dc") or 0
    val_str = f"+{_fmt(val)}"
    vf = _font(46)
    vw = _tw(d, val_str, vf)
    d.text((right_x, y + 62), val_str, font=vf, fill=GREEN, anchor="rt")

    # DC рядом с цифрой
    dc_str = " DC"
    dcf = _font(20)
    dcw = _tw(d, dc_str, dcf)
    d.text((right_x - vw - 6, y + 62 + vf.size - 24), dc_str, font=dcf, fill=GREEN, anchor="rt")

    # Время копилось
    last = pet.get("last_income") or pet.get("purchased_at") or 0
    elapsed = max(int(time.time()) - last, 0) if last else 0
    h_el = elapsed // 3600
    m_el = (elapsed % 3600) // 60
    d.text((right_x, y + 128), f"{h_el}ч {m_el}м копилось",
           font=_font(13), fill=MUTED, anchor="rt")

    # Доход в час (пилюля)
    hr = hourly_rate(pet["pet_key"], pet["level"])
    pill_text = f"⚡ {hr:.0f} DC/час"
    pf = _font(13)
    pw = _tw(d, pill_text, pf) + 24
    pill_x = right_x - pw
    pill_y = y + h - 46
    _alpha(img, (pill_x, pill_y, pill_x + pw, pill_y + 30),
           GREEN, alpha=30, radius=15)
    d.rounded_rectangle((pill_x, pill_y, pill_x + pw, pill_y + 30),
                        radius=15, outline=GREEN + (180,), width=2)
    d.text((pill_x + pw // 2, pill_y + 15), pill_text,
           font=pf, fill=GREEN, anchor="mm")


def _my_pet_card(img, d, x, y, w, h, pet):
    """Карточка питомца в сетке (3 колонки)."""
    cat = CATALOG.get(pet["pet_key"], {})
    color = RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER)
    border = _lighten(color, 0.2)

    # Фон
    _grad(img, (x, y, x + w, y + h), color, color, alpha=8, radius=16)
    d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                        outline=border + (200,), width=2)

    pad = 16

    # Emoji слева + имя рядом
    es = 56
    ex = x + pad
    ey = y + pad
    _alpha(img, (ex, ey, ex + es, ey + es), color, alpha=45, radius=13)
    d.rounded_rectangle((ex, ey, ex + es, ey + es), radius=13,
                        outline=color + (180,), width=2)
    _icon(d, ex + es // 2, ey + es // 2 + 1, cat.get("fa_code", I_PAW), 26, color)

    tx = ex + es + 12
    name_max = x + w - pad - tx
    name = cat.get("name", "—")
    name_f = _font(16)
    d.text((tx, ey + 4), _el(d, name, name_f, name_max), font=name_f, fill=TEXT)

    # Редкость под именем
    _rarity_badge(d, tx, ey + 28, cat.get("rarity", "common"), font_sz=9)

    # Уровень
    lvl_text = f"Ур. {pet['level']} / {MAX_LEVEL}"
    d.text((tx, ey + 28), _el(d, lvl_text, _font(10), name_max),
           font=_font(10), fill=MUTED)
    # Правее редкости
    r_lbl = RARITY_LABEL.get(cat.get("rarity", "common"), "").upper()
    r_w = _tw(d, r_lbl, _font(9)) + 20
    d.text((tx + r_w + 8, ey + 28), lvl_text, font=_font(10), fill=MUTED)

    # XP bar
    xp_y = y + h - 74
    cur_xp, need_xp, pct = get_xp_progress(pet)
    _xp_bar(d, img, x + pad, xp_y, w - pad * 2, 8, pct)

    # Статы
    stats_y = y + h - pad - 40
    d.line((x + pad, stats_y - 6, x + w - pad, stats_y - 6),
           fill=INNER_BRD + (255,), width=1)

    hr = hourly_rate(pet["pet_key"], pet["level"])
    pending = pet.get("pending_dc") or 0

    d.text((x + pad, stats_y), "ДОХОД", font=_font(9), fill=MUTED)
    d.text((x + pad, stats_y + 14), f"{hr:.0f} DC/ч",
           font=_font(14), fill=GREEN)

    d.text((x + w - pad, stats_y), "НАКОПЛЕНО",
           font=_font(9), fill=MUTED, anchor="ra")
    val_str = f"+{_fmt(pending)} DC"
    vf = _font(14)
    vw = _tw(d, val_str, vf)
    d.text((x + w - pad, stats_y + 14), val_str, font=vf, fill=GREEN)


def _placeholder_card(img, d, x, y, w, h):
    """Пустой слот под покупку."""
    d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                        fill=(20, 20, 26) + (255,),
                        outline=INNER_BRD + (255,), width=2)

    # Пунктирная имитация
    for i in range(int(w) - 40):
        if i % 12 < 6:
            d.point((x + 20 + i, y + 6), fill=INNER_BRD)
            d.point((x + 20 + i, y + h - 7), fill=INNER_BRD)
    for i in range(int(h) - 40):
        if i % 12 < 6:
            d.point((x + 6, y + 20 + i), fill=INNER_BRD)
            d.point((x + w - 7, y + 20 + i), fill=INNER_BRD)

    # Плюс и текст
    cx = x + w // 2
    cy = y + h // 2 - 12
    _alpha(img, (cx - 22, cy - 22, cx + 22, cy + 22), SILVER, alpha=30, radius=12)
    _icon(d, cx, cy, I_PLUS, 24, SILVER)

    d.text((cx, cy + 36), "СВОБОДНЫЙ СЛОТ",
           font=_font(11), fill=MUTED, anchor="mm")
    d.text((cx, cy + 52), "Купи ещё питомца в каталоге",
           font=_font(10), fill=DIM, anchor="mm")


def render_my_pets(user_id, balance, pets, swap_cd_left=0):
    img, d = _canvas(user_id, "питомцы · мои")
    d._image = img

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

    cd_str = "готов"
    if swap_cd_left > 0:
        h = swap_cd_left // 3600
        m = (swap_cd_left % 3600) // 60
        cd_str = f"{h}ч {m}м"

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Активный питомец", "value": active_name, "icon": I_STAR, "color": GOLD},
        {"label": "Накоплено", "value": f"{_fmt(total_pending)} DC", "icon": I_COINS, "color": GREEN},
        {"label": "Смена активного", "value": cd_str, "icon": I_CLOCK,
         "color": PURPLE if cd_str != "готов" else GREEN},
        {"label": "Всего питомцев", "value": f"{len(pets)} из {len(CATALOG)}", "icon": I_PAW, "color": BLUE},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    if not pets:
        # Пустое состояние
        sub_text = "зоопарк пуст"
    else:
        sub_text = f"{len(pets)} питомцев · {_fmt(total_pending)} DC копится"

    _right_head(d, rpx1, body_y + 22, rpx2, "Мои питомцы", sub_text)

    content_y1 = body_y + 100
    content_y2 = body_y + body_h - 22
    content_h = content_y2 - content_y1

    if not pets:
        # Пусто — 6 плейсхолдеров в сетке 3×2
        list_title_y = content_y1
        d.text((rpx1, list_title_y), "СВОБОДНЫЕ СЛОТЫ",
               font=_font(12), fill=MUTED)
        d.text((rpx2, list_title_y), "0 / 6",
               font=_font(12), fill=SILVER, anchor="ra")

        grid_y1 = list_title_y + 30
        grid_y2 = content_y2

        cols, rows = 3, 2
        cgap = 14
        cw = (rpx2 - rpx1 - cgap * (cols - 1)) // cols
        ch = (grid_y2 - grid_y1 - cgap * (rows - 1)) // rows

        for i in range(6):
            r = i // cols
            c = i % cols
            cx = rpx1 + c * (cw + cgap)
            cy = grid_y1 + r * (ch + cgap)
            _placeholder_card(img, d, cx, cy, cw, ch)

        _footer(d, "Открой каталог, чтобы купить первого питомца", "стр. 2 / 4")
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        buf.seek(0)
        return buf

    # Hero
    hero_h = 210
    hero_y1 = content_y1
    hero_y2 = hero_y1 + hero_h

    _hero_active(img, d, rpx1, hero_y1, rpx2 - rpx1, hero_h, active)

    # Список остальных
    list_title_y = hero_y2 + 18
    others = [p for p in pets if not p.get("is_active")]
    other_count = len(others)

    d.text((rpx1, list_title_y), "ОСТАЛЬНЫЕ ПИТОМЦЫ" if other_count else "СВОБОДНЫЕ СЛОТЫ",
           font=_font(12), fill=MUTED)
    d.text((rpx2, list_title_y), f"{len(pets)} / {len(CATALOG)}",
           font=_font(12), fill=SILVER, anchor="ra")

    # Сетка 3 колонки × 2 ряда = 6 слотов
    grid_y1 = list_title_y + 30
    grid_y2 = content_y2

    cols, rows = 3, 2
    cgap = 14
    cw = (rpx2 - rpx1 - cgap * (cols - 1)) // cols
    ch = (grid_y2 - grid_y1 - cgap * (rows - 1)) // rows

    total_slots = cols * rows  # 6

    for i in range(total_slots):
        r = i // cols
        c = i % cols
        cx = rpx1 + c * (cw + cgap)
        cy = grid_y1 + r * (ch + cgap)

        if i < other_count:
            _my_pet_card(img, d, cx, cy, cw, ch, others[i])
        else:
            _placeholder_card(img, d, cx, cy, cw, ch)

    _footer(d, "Забрать DC и покормить — в меню ниже", "стр. 2 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 3: КАРТОЧКА ПИТОМЦА
# ============================================================
def render_pet_card(user_id, balance, pet: dict, place: int = None):
    img, d = _canvas(user_id, "питомцы · карточка")
    d._image = img

    cat = CATALOG.get(pet["pet_key"], {})
    color = RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER)

    body_y = 140
    body_h = H - M - PY - body_y - 26

    lw = 600
    gap = 28
    lx1 = PX
    lx2 = lx1 + lw
    rx1 = lx2 + gap
    rx2 = W - M - PX

    # Левая панель с большой иконкой
    _panel(img, d, (lx1, body_y, lx2, body_y + body_h), radius=22)
    cx = (lx1 + lx2) // 2

    ic_s = 200
    ic_x = cx - ic_s // 2
    ic_y = body_y + 50
    _grad(img, (ic_x, ic_y, ic_x + ic_s, ic_y + ic_s), color, color, alpha=30, radius=40)
    d.rounded_rectangle((ic_x, ic_y, ic_x + ic_s, ic_y + ic_s), radius=40,
                        outline=color + (200,), width=4)
    _icon(d, cx, ic_y + ic_s // 2 + 2, cat.get("fa_code", I_PAW), 90, color)

    d.text((cx, ic_y + ic_s + 30), cat.get("name", "—"),
           font=_font(36), fill=TEXT, anchor="mm")

    # Редкость
    rl = RARITY_LABEL.get(cat.get("rarity", "common"), "—").upper()
    rw = _tw(d, rl, _font(16)) + 30
    ry = ic_y + ic_s + 62
    _alpha(img, (cx - rw // 2, ry, cx + rw // 2, ry + 32), color, alpha=55, radius=10)
    d.rounded_rectangle((cx - rw // 2, ry, cx + rw // 2, ry + 32), radius=10,
                        outline=color + (200,), width=2)
    d.text((cx, ry + 16), rl, font=_font(16), fill=color, anchor="mm")

    # Активный
    if pet.get("is_active"):
        ay = ry + 46
        txt = "✦ АКТИВНЫЙ ПИТОМЕЦ"
        tw_ = _tw(d, txt, _font(15)) + 40
        _alpha(img, (cx - tw_ // 2, ay, cx + tw_ // 2, ay + 36), GOLD, alpha=40, radius=10)
        d.rounded_rectangle((cx - tw_ // 2, ay, cx + tw_ // 2, ay + 36), radius=10,
                            outline=GOLD + (220,), width=2)
        d.text((cx, ay + 18), txt, font=_font(15), fill=GOLD, anchor="mm")

    # Бонус внизу
    bt = cat.get("bonus_type", "none")
    if bt != "none":
        bnames = {"review_bonus": "к отзывам", "casino_luck": "к казино", "clan_contrib": "к копилке клана"}
        btext = f"+{int(cat.get('bonus_value', 0) * 100)}% {bnames.get(bt, '')}"
        by = body_y + body_h - 80
        bw = _tw(d, btext, _font(16)) + 40
        _alpha(img, (cx - bw // 2, by, cx + bw // 2, by + 40), GOLD, alpha=25, radius=12)
        d.rounded_rectangle((cx - bw // 2, by, cx + bw // 2, by + 40), radius=12,
                            outline=GOLD + (180,), width=2)
        d.text((cx, by + 20), btext, font=_font(16), fill=GOLD, anchor="mm")

    # Правая панель — инфо
    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    _right_head(d, rpx1, body_y + 22, rpx2, "Информация", f"УР. {pet['level']} / {MAX_LEVEL}")

    # Описание
    dy = body_y + 110
    d.rounded_rectangle((rpx1, dy, rpx2, dy + 130), radius=16,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    desc = cat.get("description", "")
    df = _font(17)
    lines = []
    cur = ""
    for word in desc.split():
        test = (cur + " " + word).strip()
        if _tw(d, test, df) <= rpx2 - rpx1 - 40:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = word
    if cur: lines.append(cur)
    for i, line in enumerate(lines[:4]):
        d.text((rpx1 + 20, dy + 20 + i * 24), line, font=df, fill=TEXT_SOFT)

    # Уровень и XP
    sy = dy + 150
    sh = 96
    d.rounded_rectangle((rpx1, sy, rpx2, sy + sh), radius=14,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    _alpha(img, (rpx1 + 20, sy + 22, rpx1 + 76, sy + sh - 22), PURPLE, alpha=45, radius=12)
    _icon(d, rpx1 + 48, sy + sh // 2, I_STAR, 26, PURPLE)
    d.text((rpx1 + 100, sy + 18), "УРОВЕНЬ И ОПЫТ", font=_font(12), fill=MUTED)
    d.text((rpx1 + 100, sy + 40), f"Ур. {pet['level']} · {_fmt(pet['xp'])} XP",
           font=_font(22), fill=TEXT)

    cur_xp, need_xp, pct = get_xp_progress(pet)
    bx1 = rpx1 + 100
    bx2 = rpx2 - 24
    by = sy + sh - 26
    _xp_bar(d, img, bx1, by, bx2 - bx1, 12, pct)
    if need_xp > 0:
        d.text((bx2, by - 20), f"{cur_xp} / {need_xp} XP · {pct}%",
               font=_font(12), fill=MUTED, anchor="rs")

    # Доход
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
    _alpha(img, (rpx1 + 20, sy + 22, rpx1 + 76, sy + sh - 22), GREEN, alpha=45, radius=12)
    _icon(d, rpx1 + 48, sy + sh // 2, I_COINS, 26, GREEN)
    d.text((rpx1 + 100, sy + 18), "ДОХОД", font=_font(12), fill=MUTED)
    d.text((rpx1 + 100, sy + 40), f"{hourly:.1f} DC/час · кап {_fmt(cap)} DC",
           font=_font(20), fill=GREEN)

    d.text((rpx2 - 24, sy + 22), f"+{_fmt(pending)} DC",
           font=_font(22), fill=GREEN, anchor="rt")
    d.text((rpx2 - 24, sy + 54), f"копилось {h_el}ч {m_el}м",
           font=_font(12), fill=MUTED, anchor="rt")

    # Место в топе + дата
    sy += sh + 12
    d.rounded_rectangle((rpx1, sy, rpx2, sy + 60), radius=14,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    _icon(d, rpx1 + 34, sy + 30, I_TROPHY, 20, GOLD)
    place_str = f"#{place}" if place else "—"
    d.text((rpx1 + 60, sy + 18), f"МЕСТО В ТОПЕ: {place_str}",
           font=_font(14), fill=GOLD)

    try:
        from datetime import datetime, timezone
        pdt = datetime.fromtimestamp(pet.get("purchased_at") or 0, timezone.utc)
        pdate = pdt.strftime("%d.%m.%Y")
    except Exception:
        pdate = "—"
    d.text((rpx2 - 24, sy + 30), f"куплен {pdate}",
           font=_font(14), fill=MUTED, anchor="rm")

    _footer(d, "Покормить и сделать активным — в меню ниже", "стр. 3 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 4: ТОП (пьедестал + список)
# ============================================================
def _podium_card(img, d, x, y, w, h, rank, entry):
    """Карточка пьедестала. rank = 1, 2, 3."""
    if rank == 1:
        medal = GOLD
        medal_bg = GOLD_BG
    elif rank == 2:
        medal = SILVER
        medal_bg = (34, 38, 48)
    else:
        medal = BRONZE
        medal_bg = (40, 28, 20)

    border = _lighten(medal, 0.2)

    # Фон
    _grad(img, (x, y, x + w, y + h), medal, medal,
          alpha=15 if rank > 1 else 25, radius=20)
    d.rounded_rectangle((x, y, x + w, y + h), radius=20,
                        outline=border + (200,), width=3)

    cx = x + w // 2

    # Emoji короны/медали сверху
    crown_y = y + 14
    if rank == 1:
        _icon(d, cx, crown_y + 12, I_CROWN, 28, GOLD)
    else:
        num_str = str(rank)
        nf = _font(24)
        nw = _tw(d, num_str, nf)
        d.text((cx - nw // 2, crown_y), num_str, font=nf, fill=medal)

    # Emoji питомца
    es = 100
    ex = cx - es // 2
    ey = y + 54
    cat = CATALOG.get(entry.get("pet_key") or "", {})
    _alpha(img, (ex, ey, ex + es, ey + es), medal, alpha=45, radius=22)
    d.rounded_rectangle((ex, ey, ex + es, ey + es), radius=22,
                        outline=border + (200,), width=2)
    _icon(d, cx, ey + es // 2 + 2, cat.get("fa_code", I_PAW), 48, medal)

    # Имя
    name = f"@{entry['user_id']}"
    name_f = _font(18)
    name_shown = _el(d, name, name_f, w - 40)
    nw = _tw(d, name_shown, name_f)
    d.text((cx - nw // 2, ey + es + 14), name_shown, font=name_f, fill=TEXT)

    # Питомец
    sub = cat.get("name", "—")
    sf = _font(12)
    sub_shown = _el(d, sub, sf, w - 40)
    sw = _tw(d, sub_shown, sf)
    d.text((cx - sw // 2, ey + es + 40), sub_shown, font=sf, fill=MUTED)

    # Уровень
    val = f"ур. {entry['best_level']}"
    vf = _font(28)
    vw = _tw(d, val, vf)
    d.text((cx - vw // 2, y + h - 50), val, font=vf, fill=medal)


def render_top(user_id, balance, top_list: List[dict], my_place: int = None,
               my_best_pet: Optional[dict] = None):
    img, d = _canvas(user_id, "питомцы · топ")
    d._image = img

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
         "icon": I_USER, "color": BLUE},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    sub_text = "зал славы" if top_list else "пусто"
    _right_head(d, rpx1, body_y + 22, rpx2, "Топ питомцеводов", sub_text)

    content_y1 = body_y + 100
    content_y2 = body_y + body_h - 22

    if not top_list:
        # Пусто
        cx = (rpx1 + rpx2) // 2
        cy = (content_y1 + content_y2) // 2 - 30
        _alpha(img, (cx - 60, cy - 60, cx + 60, cy + 60), SILVER, alpha=20, radius=30)
        _icon(d, cx, cy, I_TROPHY, 60, SILVER)
        d.text((cx, cy + 100), "Пока нет питомцеводов",
               font=_font(24), fill=TEXT, anchor="mm")
        d.text((cx, cy + 138), "Купи питомца — и займи первое место",
               font=_font(15), fill=MUTED, anchor="mm")

        _footer(d, "Топ обновляется каждый час", "стр. 4 / 4")
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        buf.seek(0)
        return buf

    # Топ-3 пьедестал
    top3 = top_list[:3]
    others = top_list[3:8]  # до 5 в списке

    podium_h = 260
    podium_y1 = content_y1
    podium_y2 = podium_y1 + podium_h

    # Расстановка: 2 слева, 1 в центре, 3 справа (визуально 2-1-3)
    podium_gap = 16
    podium_w = (rpx2 - rpx1 - podium_gap * 2) // 3

    # Порядок: 2 (слева), 1 (центр), 3 (справа)
    order = [(1, top3[1] if len(top3) > 1 else None),
             (0, top3[0] if len(top3) > 0 else None),
             (2, top3[2] if len(top3) > 2 else None)]

    for idx, (rank_idx, entry) in enumerate(order):
        if entry is None:
            continue
        # Центральная карточка (rank_idx=0) — приподнята
        px = rpx1 + idx * (podium_w + podium_gap)
        if rank_idx == 0:
            py = podium_y1 - 15
            ph = podium_h + 15
        else:
            py = podium_y1
            ph = podium_h - 20

        _podium_card(img, d, px, py, podium_w, ph, rank_idx + 1, entry)

    # Остальные — списком
    if others:
        list_y = podium_y2 + 20
        d.text((rpx1, list_y), "ОСТАЛЬНЫЕ УЧАСТНИКИ", font=_font(12), fill=MUTED)
        list_y += 24

        rows_area = content_y2 - list_y
        n = len(others)
        gap_row = 8
        row_h = min((rows_area - gap_row * (n - 1)) // max(n, 1), 74)
        row_h = max(row_h, 60)

        for i, entry in enumerate(others):
            cy = list_y + i * (row_h + gap_row)
            rank = i + 4
            is_me = entry["user_id"] == user_id

            if is_me:
                _grad(img, (rpx1, cy, rpx2, cy + row_h), BLUE, BLUE, alpha=12, radius=12)
                d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=12,
                                    outline=BLUE + (200,), width=2)
            else:
                d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=12,
                                    fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

            # Номер
            num_str = str(rank)
            nf = _font(20)
            nw = _tw(d, num_str, nf)
            d.text((rpx1 + 30 - nw // 2, cy + row_h // 2 - nf.size // 2 - 2),
                   num_str, font=nf, fill=DIM)

            # Emoji питомца
            cat = CATALOG.get(entry.get("pet_key") or "", {})
            es = 42
            ex = rpx1 + 56
            ey = cy + (row_h - es) // 2
            _alpha(img, (ex, ey, ex + es, ey + es), SILVER, alpha=25, radius=10)
            _icon(d, ex + es // 2, ey + es // 2 + 1, cat.get("fa_code", I_PAW), 18, SILVER)

            # Имя
            tx = ex + es + 16
            name = f"@{entry['user_id']}"
            if is_me:
                name += " (ты)"
            name_f = _font(16)
            name_shown = _el(d, name, name_f, rpx2 - tx - 200)
            d.text((tx, cy + row_h // 2 - 20), name_shown, font=name_f,
                   fill=BLUE if is_me else TEXT)

            # Питомец
            sub = cat.get("name", "—")
            d.text((tx, cy + row_h // 2 + 4), sub, font=_font(12), fill=MUTED)

            # Уровень
            val = f"ур. {entry['best_level']}"
            vf = _font(20)
            vw = _tw(d, val, vf)
            d.text((rpx2 - 24 - vw, cy + row_h // 2 - 14), val, font=vf,
                   fill=BLUE if is_me else SILVER_HI)

    _footer(d, "Топ обновляется каждый час", "стр. 4 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
