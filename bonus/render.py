# -*- coding: utf-8 -*-
"""Pillow-рендер бонус-панели. 1800×1000."""
import io
import os
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
RED_DEEP  = (199, 62, 62)
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
I_CART     = 0xf07a
I_BOX      = 0xf466
I_INFO     = 0xf05a
I_BULLHORN = 0xf0a1
I_MASKS    = 0xf630
I_PALETTE  = 0xf53f
I_SHOP     = 0xf54f

CAT_ICON_MAP = {
    "discounts": I_TAG,
    "design":    I_PALETTE,
    "ads":       I_BULLHORN,
    "roles":     I_MASKS,
    "boosts":    I_BOLT,
    "casino":    I_COINS,
    "gifts":     I_GIFT,
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

    meta_r = W - PAD_X
    tl = "ОБНОВИТСЯ ЧЕРЕЗ"
    tw_ = _tw(d, tl, _font(11))
    d.text((meta_r - tw_, PAD_Y + 6), tl, font=_font(11), fill=MUTED)
    tv = f"{hours_left} ч."
    tvw = _tw(d, tv, _font(22))
    d.text((meta_r - tvw, PAD_Y + 26), tv, font=_font(22), fill=GOLD)

    if deal:
        cat = deal.get("category_label", "—")
        name = deal.get("item_data", {}).get("name", "—")
        desc = deal.get("item_data", {}).get("description", "") or ""
        orig = deal.get("original_price", 0)
        new = deal.get("new_price", 0)
        disc = deal.get("discount", 0)
        cat_key = deal.get("cat_key", "")
        icon_code = CAT_ICON_MAP.get(cat_key, I_CUBE)
        color = RED_DEEP
    else:
        cat = "—"; name = "Сегодня акции нет"; desc = ""
        orig = new = disc = 0; cat_key = ""
        icon_code = I_FIRE
        color = DIM

    banner_x1 = 60; banner_y1 = 180; banner_x2 = W - 60; banner_y2 = 460
    banner_h = banner_y2 - banner_y1

    _grad(img, (banner_x1, banner_y1, banner_x2, banner_y2), color, color, alpha=235, radius=24)
    d.rounded_rectangle((banner_x1, banner_y1, banner_x2, banner_y2),
                        radius=24, outline=_lighten(color, 0.25) + (255,), width=3)

    disc_str = f"−{disc}%"
    disc_font = _font(180)
    dw = _tw(d, disc_str, disc_font)
    d.text((banner_x1 + 60, banner_y1 + (banner_h - disc_font.size) // 2 - 22),
           disc_str, font=disc_font, fill=TEXT)

    text_x = banner_x1 + 60 + dw + 70
    if text_x < banner_x2 - 200:
        d.text((text_x, banner_y1 + 60), f"🔥 {cat.upper()}", font=_font(18), fill=TEXT)
        name_font = _font(62)
        name_shown = _el(d, name, name_font, banner_x2 - 60 - text_x)
        d.text((text_x, banner_y1 + 100), name_shown, font=name_font, fill=TEXT)

    body_y1 = 500; body_y2 = 880; body_h = body_y2 - body_y1
    icon_card_x1 = 60; icon_card_x2 = 540
    info_card_x1 = 580; info_card_x2 = W - 60

    d.rounded_rectangle((icon_card_x1, body_y1, icon_card_x2, body_y2),
                        radius=24, fill=INNER_BG + (255,), outline=STACK_BRD + (255,), width=3)
    _alpha(img, (icon_card_x1 + 8, body_y1 + 8, icon_card_x2 - 8, body_y2 - 8), color, alpha=25, radius=20)

    cx_icon = (icon_card_x1 + icon_card_x2) // 2
    cy_icon = (body_y1 + body_y2) // 2
    for i, a in enumerate([45, 60, 75]):
        gs = 300 - i * 30
        _alpha(img, (cx_icon - gs // 2, cy_icon - gs // 2, cx_icon + gs // 2, cy_icon + gs // 2), color, alpha=a, radius=gs // 2)
    _icon(d, cx_icon, cy_icon, icon_code, 180, _lighten(color, 0.55))

    d.rounded_rectangle((info_card_x1, body_y1, info_card_x2, body_y2),
                        radius=24, fill=INNER_BG + (255,), outline=STACK_BRD + (255,), width=3)

    text_x = info_card_x1 + 60
    text_max = info_card_x2 - 60

    if desc:
        desc_font = _font(22)
        lines = _wrap(d, desc, desc_font, text_max - text_x, max_lines=4)
        for i, line in enumerate(lines):
            d.text((text_x, body_y1 + 60 + i * 32), line, font=desc_font, fill=TEXT_SOFT)
    else:
        d.text((text_x, body_y1 + 60), "Акция обновляется каждые 5 часов — заходи позже.", font=_font(22), fill=MUTED)

    price_y = body_y2 - 190

    if orig > 0:
        orig_str = f"{orig} DC"
        old_font = _font(42)
        ow = _tw(d, orig_str, old_font)
        d.text((text_x, price_y), orig_str, font=old_font, fill=DIM)
        d.line((text_x, price_y + 26, text_x + ow, price_y + 26), fill=DIM, width=3)
        next_x = text_x + ow + 55
    else:
        next_x = text_x

    if new > 0:
        d.text((next_x, price_y + 4), "→", font=_font(42), fill=DIM)
        next_x += 80
        new_str = str(new)
        new_font = _font(100)
        d.text((next_x, price_y - 20), new_str, font=new_font, fill=GREEN)
        nw = _tw(d, new_str, new_font)
        d.text((next_x + nw + 14, price_y - 20 + new_font.size - 48), "DC", font=_font(38), fill=GREEN)

    foot_y = H - PAD_Y - 20
    d.line((PAD_X, foot_y - 12, W - PAD_X, foot_y - 12), fill=STACK_HDR + (255,), width=2)
    _icon(d, PAD_X + 12, foot_y + 10, I_INFO, 16, DIM)
    d.text((PAD_X + 38, foot_y), "Товар дня обновляется каждые 5 часов", font=_font(15), fill=DIM)
    page = "АКЦИЯ ДНЯ"
    pw = _tw(d, page, _font(15))
    d.text((W - PAD_X - pw, foot_y), page, font=_font(15), fill=DIM)

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
    d.ellipse((cx - r - 2, av_cy - r - 2, cx + r + 2, av_cy + r + 2), outline=GREEN + (255,), width=5)
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
        d.rounded_rectangle((cx1, cy1, cx1 + cw, cy1 + ch_), radius=16, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        d.text((cx1 + 18, cy1 + 16), lbl, font=_font(11), fill=MUTED)
        vf = _font(28)
        v = str(val)
        while _tw(d, v, vf) > cw - 36 and vf.size > 16:
            vf = _font(vf.size - 2)
        d.text((cx1 + 18, cy1 + 44), v, font=vf, fill=color)

    hint_y = BODY_Y + BODY_H - 12 - pad - 150
    _grad(img, (x1 + pad, hint_y, x2 - pad, hint_y + 150), GREEN, GREEN, alpha=15, radius=16)
    d.rounded_rectangle((x1 + pad, hint_y, x2 - pad, hint_y + 150), radius=16, outline=GREEN + (200,), width=2)

    # Белая иконка
    _icon(d, x1 + pad + 32, hint_y + 30, I_GIFT, 20, TEXT)
    d.text((x1 + pad + 54, hint_y + 20), "КАК ЗАРАБОТАТЬ", font=_font(12), fill=TEXT)

    for i, ln in enumerate([
        "50 DC на баланс за друга",
        "50 DC в копилку клана",
        "Порог зачёта — 1 час",
    ]):
        dy = hint_y + 60 + i * 26
        # Белые точки
        d.ellipse((x1 + pad + 24, dy + 6, x1 + pad + 32, dy + 14), fill=(255, 255, 255, 255))
        d.text((x1 + pad + 44, dy), ln, font=_font(15), fill=SILVER_HI)

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
            on_review = (not rewarded and row.get("left_at") and (row["left_at"] - row["joined_at"]) < 3600)

            d.rounded_rectangle((rpx1, ry, rpx2, ry + row_h), radius=14, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

            av_x = col_x[0] + 18
            d.ellipse((av_x, ry + row_h // 2 - 26, av_x + 52, ry + row_h // 2 + 26), fill=(58, 58, 64))
            _icon(d, av_x + 26, ry + row_h // 2 + 1, I_USER, 22, SILVER_HI)

            d.text((col_x[1], ry + row_h // 2 - 24), f"ID {row['member_id']}", font=_font(17), fill=TEXT)
            d.text((col_x[1], ry + row_h // 2 + 4), "участник", font=_font(12), fill=MUTED)

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
            _alpha(img, (bx, ry + row_h // 2 - 16, bx + tw_ + 28, ry + row_h // 2 + 16), color, alpha=30, radius=9)
            d.rounded_rectangle((bx, ry + row_h // 2 - 16, bx + tw_ + 28, ry + row_h // 2 + 16), radius=9, outline=color + (220,), width=2)
            d.text((bx + 14, ry + row_h // 2 - 10), txt, font=_font(13), fill=color)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf

# ═══════════════════════════════════════════════════
# ЭКРАН 3: ТОПЫ (НОВЫЙ МАКЕТ)
# ═══════════════════════════════════════════════════
def render_ref_top(user_id, username, top_list, is_advertiser=False):
    img, d = _canvas("топ адвайтеров" if is_advertiser else "топ рефералов")
    
    color = GOLD if is_advertiser else GREEN
    title = "ТОП АДВАЙТЕРОВ" if is_advertiser else "ТОП РЕФЕРАЛОВ"
    
    cx = W // 2
    d.text((cx, 150), title, font=_font(48), fill=color, anchor="mm")
    
    # Шапка таблицы
    head_y = 230
    col_w = 1000
    start_x = cx - col_w // 2
    
    d.line((start_x, head_y + 40, start_x + col_w, head_y + 40), fill=STACK_HDR + (255,), width=2)
    
    d.text((start_x + 70, head_y), "МЕСТО", font=_font(14), fill=MUTED)
    d.text((start_x + 180, head_y), "ПОЛЬЗОВАТЕЛЬ", font=_font(14), fill=MUTED)
    d.text((start_x + 550, head_y), "ВСЕГО", font=_font(14), fill=MUTED)
    d.text((start_x + 750, head_y), "ЗАРАБОТАНО", font=_font(14), fill=MUTED)
    
    list_y = head_y + 60
    row_h = 75
    gap = 12
    
    if not top_list:
        _icon(d, cx, 500, I_ELL, 60, DIM)
        d.text((cx, 580), "Пока нет данных", font=_font(24), fill=DIM, anchor="mm")
    else:
        for i, entry in enumerate(top_list[:10]):
            ry = list_y + i * (row_h + gap)
            if ry + row_h > H - PAD_Y - 40: break
            
            if i == 0: medal = GOLD
            elif i == 1: medal = SILVER
            elif i == 2: medal = BRONZE
            else: medal = DIM
            
            d.rounded_rectangle((start_x, ry, start_x + col_w, ry + row_h), radius=16,
                                fill=INNER_BG + (255,), outline=medal + (150,), width=2)
            
            # Место
            _icon(d, start_x + 60, ry + row_h//2, I_MEDAL, 26, medal)
            d.text((start_x + 90, ry + row_h//2), f"#{i+1}", font=_font(24), fill=medal, anchor="lm")
            
            # Имя
            d.text((start_x + 180, ry + row_h//2), entry['username'], font=_font(22), fill=TEXT, anchor="lm")
            
            # Всего
            d.text((start_x + 550, ry + row_h//2), f"{entry['total']} чел.", font=_font(20), fill=SILVER_HI, anchor="lm")
            
            # Заработано
            d.text((start_x + 750, ry + row_h//2), f"+{entry['earned']} DC", font=_font(24), fill=GREEN, anchor="lm")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
