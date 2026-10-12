# -*- coding: utf-8 -*-
"""Pillow-рендеры панели питомцев. 4 экрана, 1800×1000."""
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
I_CAT      = 0xf6be
I_PAW      = 0xf1b0
I_HAND     = 0xf4c0
I_CART     = 0xf07a
I_BOLT     = 0xf0e7
I_CHART    = 0xf201
I_ARROW_L  = 0xf060
I_FIRE     = 0xf06d
I_UTENSILS = 0xf2e7
I_HOURGLASS= 0xf252
I_CHECK    = 0xf00c
I_ELL      = 0xf141


# ============================================================
# УТИЛИТЫ
# ============================================================
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
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(32), fill=TEXT)
    sw = _tw(d, sub.upper(), _font(15))
    d.text((x2 - sw, y1 + 20), sub.upper(), font=_font(15), fill=MUTED)
    d.line((x1, y1 + 66, x2, y1 + 66), fill=STACK_HDR + (255,), width=2)


# ============================================================
# ЭКРАН 1: КАТАЛОГ
# ============================================================
def _pet_card_catalog(d, img, x, y, w, h, key, cat, owned):
    color = RARITY_PALETTE.get(cat["rarity"], SILVER)
    border = _lighten(color, 0.2)

    if owned:
        _grad(img, (x, y, x + w, y + h), RED, RED, alpha=6, radius=18)
        d.rounded_rectangle((x, y, x + w, y + h), radius=18,
                            outline=RED + (150,), width=3)
    else:
        _grad(img, (x, y, x + w, y + h), color, color, alpha=10, radius=18)
        d.rounded_rectangle((x, y, x + w, y + h), radius=18,
                            outline=border + (200,), width=3)

    pad = 20

    ic_s = 64
    ix = x + pad
    iy = y + pad
    _alpha(img, (ix, iy, ix + ic_s, iy + ic_s), color, alpha=60, radius=15)
    d.rounded_rectangle((ix, iy, ix + ic_s, iy + ic_s), radius=15,
                        outline=border + (200,), width=2)
    _icon(d, ix + ic_s // 2, iy + ic_s // 2 + 1, cat["fa_code"], 30, color)

    tx = ix + ic_s + 14
    d.text((tx, iy + 4), cat["name"], font=_font(20), fill=TEXT)

    rl = RARITY_LABEL.get(cat["rarity"], "—").upper()
    rw = _tw(d, rl, _font(11)) + 16
    ry = iy + 30
    _alpha(img, (tx, ry, tx + rw, ry + 20), color, alpha=55, radius=6)
    d.rounded_rectangle((tx, ry, tx + rw, ry + 20), radius=6,
                        outline=border + (200,), width=1)
    d.text((tx + 8, ry + 3), rl, font=_font(11), fill=color)

    desc_y = iy + ic_s + 14
    df = _font(13)
    desc = cat.get("description", "")
    lines = []
    cur = ""
    for word in desc.split():
        test = (cur + " " + word).strip()
        if _tw(d, test, df) <= w - pad * 2:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = word
            if len(lines) >= 2: break
    if cur and len(lines) < 2: lines.append(cur)
    for i, line in enumerate(lines):
        d.text((x + pad, desc_y + i * 18), line, font=df, fill=MUTED)

    sy = y + h - 80
    d.line((x + pad, sy - 8, x + w - pad, sy - 8), fill=INNER_BRD + (255,), width=1)

    lbl_y = sy + 6
    d.text((x + pad, lbl_y), "ЦЕНА", font=_font(11), fill=MUTED)
    d.text((x + pad, lbl_y + 18), f"{_fmt(cat['price_dc'])} DC",
           font=_font(20), fill=(74, 74, 82) if owned else SILVER_HI)

    inc_str = f"{cat['passive_dc']} DC/ч"
    iw = _tw(d, inc_str, _font(20))
    d.text((x + w - pad - iw, lbl_y + 18), inc_str, font=_font(20), fill=GREEN)

    if cat.get("bonus_type") and cat["bonus_type"] != "none":
        bt = cat["bonus_type"]
        bnames = {
            "review_bonus": "отзывы",
            "casino_luck": "казино",
            "clan_contrib": "копилка клана",
        }
        btext = f"+{int(cat['bonus_value'] * 100)}% к {bnames.get(bt, '')}"
        bw = _tw(d, btext, _font(11)) + 16
        bx = x + pad
        by = y + h - 28
        _alpha(img, (bx, by, bx + bw, by + 20), GOLD, alpha=30, radius=6)
        d.rounded_rectangle((bx, by, bx + bw, by + 20), radius=6,
                            outline=GOLD + (180,), width=1)
        d.text((bx + 8, by + 3), btext, font=_font(11), fill=GOLD)


def render_catalog(user_id, balance, owned_keys, active_key=None):
    img, d = _canvas(user_id, "питомцы · каталог")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 460
    gap = 30
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    total = len(CATALOG)
    owned_count = len(owned_keys)

    _left_panel(img, d, (lx1, body_y, lx2, body_y + body_h), balance, [
        {"label": "Питомцев в каталоге", "value": f"{total}", "icon": I_PAW, "color": SILVER},
        {"label": "У тебя уже есть", "value": f"{owned_count} из {total}", "icon": I_CHECK, "color": GREEN},
        {"label": "Самый дорогой", "value": "Даймондик · 5 000 DC", "icon": I_CROWN, "color": GOLD},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    _right_head(d, rpx1, body_y + 22, rpx2, "Каталог питомцев", "выбери в меню ниже")

    grid_y1 = body_y + 110
    grid_y2 = body_y + body_h - 22
    grid_h = grid_y2 - grid_y1

    cols, rows = 3, 2
    cgap = 14
    cw = (rpx2 - rpx1 - cgap * (cols - 1)) // cols
    ch = (grid_h - cgap * (rows - 1)) // rows

    for idx, (key, cat) in enumerate(CATALOG.items()):
        r = idx // cols
        c = idx % cols
        cx = rpx1 + c * (cw + cgap)
        cy = grid_y1 + r * (ch + cgap)
        _pet_card_catalog(d, img, cx, cy, cw, ch, key, cat, key in owned_keys)

    _footer(d, "Выбери питомца в меню ниже чтобы купить", "стр. 1 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 2: МОИ ПИТОМЦЫ
# ============================================================
def render_my_pets(user_id, balance, pets: List[dict], swap_cd_left: int = 0):
    img, d = _canvas(user_id, "питомцы · зоопарк")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 460
    gap = 30
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
        {"label": "Накоплено у питомцев", "value": f"{_fmt(total_pending)} DC", "icon": I_COINS, "color": GREEN},
        {"label": "Смена активного", "value": cd_str, "icon": I_CLOCK, "color": PURPLE if cd_str != "готов" else GREEN},
    ])

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    _right_head(d, rpx1, body_y + 22, rpx2, "Мой зоопарк",
                f"{len(pets)} питомцев · жми в меню ниже")

    list_y = body_y + 110
    list_bottom = body_y + body_h - 22
    gap_r = 10
    n = max(len(pets), 1)
    row_h = (list_bottom - list_y - gap_r * (n - 1)) // n
    row_h = max(row_h, 90)

    if not pets:
        _alpha(img, (rpx1, list_y, rpx2, list_bottom), SILVER, alpha=15, radius=18)
        cx = (rpx1 + rpx2) // 2
        cy = (list_y + list_bottom) // 2
        _icon(d, cx, cy - 40, I_PAW, 60, SILVER)
        d.text((cx, cy + 40), "У тебя пока нет питомцев", font=_font(26),
               fill=TEXT, anchor="mm")
        d.text((cx, cy + 78), "Загляни в каталог — там есть из чего выбрать.",
               font=_font(16), fill=MUTED, anchor="mm")
    else:
        for i, pet in enumerate(pets[:6]):
            cy = list_y + i * (row_h + gap_r)
            cat = CATALOG.get(pet["pet_key"], {})
            color = RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER)

            if pet.get("is_active"):
                _grad(img, (rpx1, cy, rpx2, cy + row_h), GOLD, GOLD, alpha=15, radius=14)
                d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=14,
                                    outline=GOLD + (200,), width=2)
            else:
                d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=14,
                                    fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

            ic_s = 56
            ix = rpx1 + 18
            iy = cy + (row_h - ic_s) // 2
            _alpha(img, (ix, iy, ix + ic_s, iy + ic_s), color, alpha=50, radius=13)
            d.rounded_rectangle((ix, iy, ix + ic_s, iy + ic_s), radius=13,
                                outline=color + (180,), width=2)
            _icon(d, ix + ic_s // 2, iy + ic_s // 2 + 1, cat.get("fa_code", I_PAW), 24, color)

            tx = ix + ic_s + 16
            name = cat.get("name", "—")
            if pet.get("is_active"):
                name += " · АКТИВНЫЙ"
            d.text((tx, cy + 12), name, font=_font(18), fill=GOLD if pet.get("is_active") else TEXT)

            hourly = hourly_rate(pet["pet_key"], pet["level"])
            line2 = f"Ур. {pet['level']} · {hourly:.1f} DC/ч"
            d.text((tx, cy + 38), line2, font=_font(14), fill=MUTED)

            cur_xp, need_xp, pct = get_xp_progress(pet)
            bar_y = cy + row_h - 20
            bar_w = 260
            bx1 = tx
            bx2 = bx1 + bar_w
            d.rounded_rectangle((bx1, bar_y, bx2, bar_y + 8), radius=4, fill=(28, 28, 34))
            fill_w = int(bar_w * pct / 100)
            if fill_w > 0:
                _grad(img, (bx1, bar_y, bx1 + fill_w, bar_y + 8), PURPLE, BLUE, alpha=255, radius=4)

            pending = pet.get("pending_dc") or 0
            last = pet.get("last_income") or pet.get("purchased_at") or 0
            elapsed = max(int(time.time()) - last, 0) if last else 0
            h = elapsed // 3600
            m = (elapsed % 3600) // 60
            right_x = rpx2 - 22
            pend_str = f"+{_fmt(pending)} DC"
            pw = _tw(d, pend_str, _font(20))
            d.text((right_x - pw, cy + 12), pend_str, font=_font(20), fill=GREEN)
            time_str = f"{h}ч {m}м копилось"
            tw_ = _tw(d, time_str, _font(12))
            d.text((right_x - tw_, cy + 40), time_str, font=_font(12), fill=MUTED)

    _footer(d, "Забрать доход и покормить можно в меню ниже", "стр. 2 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 3: КАРТОЧКА ПИТОМЦА
# ============================================================
def render_pet_card(user_id, balance, pet: dict, place: int = None):
    img, d = _canvas(user_id, "питомцы · карточка")

    cat = CATALOG.get(pet["pet_key"], {})
    color = RARITY_PALETTE.get(cat.get("rarity", "common"), SILVER)

    body_y = 140
    body_h = H - M - PY - body_y - 26

    lw = 600
    gap = 30
    lx1 = PX
    lx2 = lx1 + lw
    rx1 = lx2 + gap
    rx2 = W - M - PX

    _panel(img, d, (lx1, body_y, lx2, body_y + body_h), radius=22)
    cx = (lx1 + lx2) // 2

    ic_s = 200
    ic_x = cx - ic_s // 2
    ic_y = body_y + 40
    _grad(img, (ic_x, ic_y, ic_x + ic_s, ic_y + ic_s), color, color, alpha=30, radius=40)
    d.rounded_rectangle((ic_x, ic_y, ic_x + ic_s, ic_y + ic_s), radius=40,
                        outline=color + (200,), width=4)
    _icon(d, cx, ic_y + ic_s // 2 + 2, cat.get("fa_code", I_PAW), 90, color)

    d.text((cx, ic_y + ic_s + 30), cat.get("name", "—"),
           font=_font(36), fill=TEXT, anchor="mm")

    rl = RARITY_LABEL.get(cat.get("rarity", "common"), "—").upper()
    rw = _tw(d, rl, _font(16)) + 30
    ry = ic_y + ic_s + 60
    _alpha(img, (cx - rw // 2, ry, cx + rw // 2, ry + 32), color, alpha=55, radius=10)
    d.rounded_rectangle((cx - rw // 2, ry, cx + rw // 2, ry + 32), radius=10,
                        outline=color + (200,), width=2)
    d.text((cx, ry + 16), rl, font=_font(16), fill=color, anchor="mm")

    if pet.get("is_active"):
        ay = ry + 50
        txt = "✦ АКТИВНЫЙ ПИТОМЕЦ"
        tw_ = _tw(d, txt, _font(15)) + 40
        _alpha(img, (cx - tw_ // 2, ay, cx + tw_ // 2, ay + 36), GOLD, alpha=40, radius=10)
        d.rounded_rectangle((cx - tw_ // 2, ay, cx + tw_ // 2, ay + 36), radius=10,
                            outline=GOLD + (220,), width=2)
        d.text((cx, ay + 18), txt, font=_font(15), fill=GOLD, anchor="mm")

    bt = cat.get("bonus_type", "none")
    if bt != "none":
        bnames = {
            "review_bonus": "к отзывам",
            "casino_luck": "к казино",
            "clan_contrib": "к копилке клана",
        }
        btext = f"+{int(cat.get('bonus_value', 0) * 100)}% {bnames.get(bt, '')}"
        by = body_y + body_h - 80
        bw = _tw(d, btext, _font(16)) + 40
        _alpha(img, (cx - bw // 2, by, cx + bw // 2, by + 40), GOLD, alpha=25, radius=12)
        d.rounded_rectangle((cx - bw // 2, by, cx + bw // 2, by + 40), radius=12,
                            outline=GOLD + (180,), width=2)
        d.text((cx, by + 20), btext, font=_font(16), fill=GOLD, anchor="mm")

    _panel(img, d, (rx1, body_y, rx2, body_y + body_h), radius=22)
    rpx1 = rx1 + 30
    rpx2 = rx2 - 30

    _right_head(d, rpx1, body_y + 22, rpx2, "Информация",
                f"УР. {pet['level']} / {MAX_LEVEL}")

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
    d.rounded_rectangle((bx1, by, bx2, by + 12), radius=6, fill=(28, 28, 34))
    fill_w = int((bx2 - bx1) * pct / 100)
    if fill_w > 0:
        _grad(img, (bx1, by, bx1 + fill_w, by + 12), PURPLE, BLUE, alpha=255, radius=6)
    if need_xp > 0:
        d.text((bx2, by - 20), f"{cur_xp} / {need_xp} XP · {pct}%",
               font=_font(12), fill=MUTED, anchor="rs")

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

    _footer(d, "Покормить и сделать активным можно в меню ниже", "стр. 3 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 4: ТОП
# ============================================================
def render_top(user_id, balance, top_list: List[dict], my_place: int = None,
               my_best_pet: Optional[dict] = None):
    img, d = _canvas(user_id, "питомцы · топ")

    body_y = 140
    body_h = H - M - PY - body_y - 26

    left_w = 460
    gap = 30
    lx1 = PX
    lx2 = lx1 + left_w
    rx1 = lx2 + gap
    rx2 = W - M - PX

    # 👇 Берём лучшего питомца из параметра (без обращения к БД)
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

    _right_head(d, rpx1, body_y + 22, rpx2, "Топ питомцеводов",
                "по уровню лучшего питомца")

    list_y = body_y + 110
    list_bottom = body_y + body_h - 22
    gap_r = 8
    rows = 8
    row_h = (list_bottom - list_y - gap_r * (rows - 1)) // rows

    if not top_list:
        cx = (rpx1 + rpx2) // 2
        cy = (list_y + list_bottom) // 2
        _icon(d, cx, cy - 40, I_TROPHY, 60, SILVER)
        d.text((cx, cy + 40), "Пока нет питомцеводов", font=_font(24),
               fill=TEXT, anchor="mm")
    else:
        for i, t in enumerate(top_list[:rows]):
            cy = list_y + i * (row_h + gap_r)
            rank = i + 1
            if rank == 1:   medal = GOLD
            elif rank == 2: medal = SILVER
            elif rank == 3: medal = BRONZE
            else:           medal = DIM

            is_me = t["user_id"] == user_id

            if is_me:
                _grad(img, (rpx1, cy, rpx2, cy + row_h), BLUE, BLUE, alpha=15, radius=12)
                d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=12,
                                    outline=BLUE + (200,), width=2)
            elif rank <= 3:
                _grad(img, (rpx1, cy, rpx2, cy + row_h), medal, medal, alpha=15, radius=12)
                d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=12,
                                    outline=medal + (170,), width=2)
            else:
                d.rounded_rectangle((rpx1, cy, rpx2, cy + row_h), radius=12,
                                    fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

            bd_s = 46
            bx = rpx1 + 16
            by = cy + (row_h - bd_s) // 2
            _alpha(img, (bx, by, bx + bd_s, by + bd_s), medal, alpha=55, radius=12)
            d.rounded_rectangle((bx, by, bx + bd_s, by + bd_s), radius=12,
                                outline=medal + (200,), width=2)
            if rank <= 3:
                _icon(d, bx + bd_s // 2, by + bd_s // 2 + 1, I_MEDAL, 22, medal)
            else:
                nstr = str(rank)
                nf = _font(20)
                nw = _tw(d, nstr, nf)
                d.text((bx + bd_s // 2 - nw // 2, by + bd_s // 2 - nf.size // 2 - 2),
                       nstr, font=nf, fill=medal)

            tx = bx + bd_s + 16
            name = f"@{t['user_id']}"
            if is_me:
                name += " (ты)"
            d.text((tx, cy + row_h // 2 - 16), name, font=_font(19), fill=TEXT)

            cat = CATALOG.get(t.get("pet_key") or "", {})
            sub = cat.get("name", "—")
            d.text((tx, cy + row_h // 2 + 6), sub, font=_font(13), fill=MUTED)

            val = f"ур. {t['best_level']}"
            vw = _tw(d, val, _font(22))
            d.text((rpx2 - 24 - vw, cy + row_h // 2 - 14), val, font=_font(22),
                   fill=medal if rank <= 3 else SILVER_HI)

    _footer(d, "Топ обновляется каждый час", "стр. 4 / 4")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
