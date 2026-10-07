# -*- coding: utf-8 -*-
"""
Pillow-рендер 3 экранов инвайт-панели адвайтера.
1800×1000, стиль 1:1 с modules/profile_card.py.
"""
import io
import os
from datetime import datetime, timezone
from typing import Dict

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR


FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_F, _FA = {}, {}


def _font(sz):
    if sz in _F:
        return _F[sz]
    try:
        f = ImageFont.truetype(FONT_BOLD, sz)
    except Exception:
        f = ImageFont.load_default()
    _F[sz] = f
    return f


def _fa(sz):
    if sz in _FA:
        return _FA[sz]
    f = None
    if os.path.exists(FONT_FA):
        try:
            f = ImageFont.truetype(FONT_FA, sz)
        except Exception:
            pass
    _FA[sz] = f
    return f


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
BRONZE    = (209, 146, 96)

CARD_BRD  = (74, 74, 79)

I_USER     = 0xf007
I_TROPHY   = 0xf091
I_MEDAL    = 0xf5a2
I_LINK     = 0xf0c1
I_CHECK    = 0xf00c
I_BULLHORN = 0xf0a1
I_ELL      = 0xf141


def _tw(d, t, f):
    b = d.textbbox((0, 0), t, font=f)
    return b[2] - b[0]


def _el(d, t, f, w):
    if _tw(d, t, f) <= w:
        return t
    while t and _tw(d, t + "…", f) > w:
        t = t[:-1]
    return t + "…"


def _icon(d, cx, cy, code, sz, color):
    f = _fa(sz)
    if f is None:
        return
    try:
        d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception:
        pass


def _alpha(img, box, color, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return
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
    if w <= 0 or h <= 0:
        return
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
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1),
                                                radius=radius, fill=255)
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
    return (
        min(int(c[0] + (255 - c[0]) * a), 255),
        min(int(c[1] + (255 - c[1]) * a), 255),
        min(int(c[2] + (255 - c[2]) * a), 255),
    )


W, H = 1800, 1000
PAD_X, PAD_Y = 56, 44
BODY_Y = 138
BODY_H = H - PAD_Y - BODY_Y


def _canvas(user_id, subtitle):
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=30,
                        fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)

    hx, hy = PAD_X, PAD_Y
    d.rounded_rectangle((hx, hy, hx + 54, hy + 54), radius=14, fill=(58, 58, 64) + (255,))
    _icon(d, hx + 27, hy + 28, I_BULLHORN, 26, BLUE)

    bx = hx + 54 + 18
    d.text((bx, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx + 2, hy + 38), "ADVERTISER PANEL", font=_font(11), fill=MUTED)

    meta_r = W - PAD_X
    w1 = _tw(d, subtitle.upper(), _font(11))
    w2 = _tw(d, f"#{user_id}", _font(20))
    d.text((meta_r - w1, hy + 12), subtitle.upper(), font=_font(11), fill=MUTED)
    d.text((meta_r - w2, hy + 32), f"#{user_id}", font=_font(20), fill=TEXT)

    sy = hy + 54 + 16
    d.line((PAD_X, sy, W - PAD_X, sy), fill=STACK_HDR + (255,), width=2)
    return img, d


def _draw_left_panel(img, d, box, user_id, username, stats: Dict[str, int]):
    _panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 26
    cx = (x1 + x2) // 2

    av_size = 120
    av_cy = y1 + pad + av_size // 2
    r = av_size // 2
    _grad(img, (cx - r, av_cy - r, cx + r, av_cy + r),
          BLUE, SILVER, alpha=80, radius=r)
    d.ellipse((cx - r - 2, av_cy - r - 2, cx + r + 2, av_cy + r + 2),
              outline=BLUE + (255,), width=4)
    _icon(d, cx, av_cy + 1, I_USER, 52, TEXT)

    nick_y = y1 + pad + av_size + 20
    nick = _el(d, username, _font(20), (x2 - x1) - 2 * pad)
    nw = _tw(d, nick, _font(20))
    d.text((cx - nw // 2, nick_y), nick, font=_font(20), fill=TEXT)

    uid_y = nick_y + 30
    uid_text = f"UID · {user_id}"
    uid_w = _tw(d, uid_text, _font(12))
    d.text((cx - uid_w // 2, uid_y), uid_text, font=_font(12), fill=MUTED)

    sep_y = uid_y + 26
    d.line((x1 + pad, sep_y, x2 - pad, sep_y), fill=STACK_HDR + (255,), width=2)

    grid_y = sep_y + 20
    grid_w = (x2 - pad) - (x1 + pad)
    gap = 12
    cell_w = (grid_w - gap) // 2
    cell_h = 96

    items = [
        ("ЗАСЧИТАНО",   stats.get("rewarded", 0),  GREEN),
        ("НА ПРОВЕРКЕ", stats.get("on_review", 0), GOLD),
        ("НА СЕРВЕРЕ",  stats.get("alive", 0),     BLUE),
        ("ВСЕГО",       stats.get("total", 0),     SILVER),
    ]

    for i, (lbl, val, color) in enumerate(items):
        r_, c_ = divmod(i, 2)
        cx1 = x1 + pad + c_ * (cell_w + gap)
        cy1 = grid_y + r_ * (cell_h + gap)
        d.rounded_rectangle((cx1, cy1, cx1 + cell_w, cy1 + cell_h), radius=14,
                            fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        d.text((cx1 + 16, cy1 + 14), lbl, font=_font(10), fill=MUTED)
        d.text((cx1 + 16, cy1 + 40), str(val), font=_font(32), fill=color)


def _draw_invite_row(img, d, x1, y, w, h, row, col_x):
    rewarded = row.get("rewarded", 0)
    on_review = (
        not rewarded
        and row.get("left_at")
        and (row["left_at"] - row["joined_at"]) < 12 * 3600
    )

    d.rounded_rectangle((x1, y, x1 + w, y + h), radius=12,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

    av_x = col_x[0] + 14
    d.ellipse((av_x, y + h // 2 - 24, av_x + 48, y + h // 2 + 24),
              fill=(58, 58, 64))
    _icon(d, av_x + 24, y + h // 2 + 1, I_USER, 20, SILVER_HI)

    d.text((col_x[1], y + h // 2 - 22), f"ID {row['member_id']}",
           font=_font(15), fill=TEXT)
    d.text((col_x[1], y + h // 2 + 2), "участник",
           font=_font(11), fill=MUTED)

    try:
        jdt = datetime.fromtimestamp(row["joined_at"], timezone.utc)
        jd = jdt.strftime("%d.%m.%Y")
        jt = jdt.strftime("%H:%M")
    except Exception:
        jd, jt = "—", "—"
    d.text((col_x[2], y + h // 2 - 18), jd, font=_font(14), fill=SILVER_HI)
    d.text((col_x[2], y + h // 2 + 2), jt, font=_font(11), fill=MUTED)

    if row.get("left_at"):
        try:
            ldt = datetime.fromtimestamp(row["left_at"], timezone.utc)
            ld = ldt.strftime("%d.%m.%Y")
            lt = ldt.strftime("%H:%M")
        except Exception:
            ld, lt = "—", "—"
        d.text((col_x[3], y + h // 2 - 18), ld, font=_font(14), fill=SILVER_HI)
        d.text((col_x[3], y + h // 2 + 2), lt, font=_font(11), fill=MUTED)
    else:
        d.text((col_x[3], y + h // 2 - 8), "—", font=_font(14), fill=DIM)

    if rewarded:
        txt, color = "✓ ЗАСЧИТАН", GREEN
    elif on_review:
        txt, color = "⚠ НА ПРОВЕРКЕ", GOLD
    else:
        txt, color = "… на сервере", BLUE

    tw_ = _tw(d, txt, _font(12))
    bx = col_x[4]
    _alpha(img, (bx, y + h // 2 - 14, bx + tw_ + 22, y + h // 2 + 14),
           color, alpha=30, radius=9)
    d.rounded_rectangle((bx, y + h // 2 - 14, bx + tw_ + 22, y + h // 2 + 14),
                        radius=9, outline=color + (200,), width=1)
    d.text((bx + 11, y + h // 2 - 8), txt, font=_font(12), fill=color)


# ============================================================
# ЭКРАН 1: ЛИЧНАЯ СТАТИСТИКА
# ============================================================
def render_personal(user_id, username, stats, link_url, created_at):
    img, d = _canvas(user_id, "личная статистика")

    left_w = 460
    gap = 36
    lx1, lx2 = PAD_X, PAD_X + left_w
    rx1, rx2 = lx2 + gap, W - PAD_X

    _draw_left_panel(img, d, (lx1, BODY_Y, lx2 - 12, BODY_Y + BODY_H - 12),
                     user_id, username, stats)

    lp_y2 = BODY_Y + BODY_H - 12
    link_h = 96
    link_y = lp_y2 - 22 - link_h
    ip_x1 = lx1 + 26
    ip_x2 = lx2 - 12 - 26

    _grad(img, (ip_x1, link_y, ip_x2, link_y + link_h),
          BLUE, BLUE, alpha=18, radius=14)
    d.rounded_rectangle((ip_x1, link_y, ip_x2, link_y + link_h),
                        radius=14, outline=BLUE + (200,), width=2)
    _icon(d, ip_x1 + 22, link_y + 24, I_LINK, 14, _lighten(BLUE, .4))
    d.text((ip_x1 + 44, link_y + 18), "РЕФЕРАЛЬНАЯ ССЫЛКА",
           font=_font(10), fill=_lighten(BLUE, .4))

    url = link_url or "— нажми кнопку —"
    url_shown = _el(d, url, _font(15), ip_x2 - ip_x1 - 30)
    d.text((ip_x1 + 16, link_y + 42), url_shown, font=_font(15), fill=BLUE)

    if created_at:
        try:
            dt = datetime.fromtimestamp(created_at, timezone.utc).strftime("%d.%m.%Y")
            d.text((ip_x1 + 16, link_y + 68), f"создана {dt}",
                   font=_font(11), fill=DIM)
        except Exception:
            pass

    _panel(img, d, (rx1, BODY_Y, rx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    rpx1 = rx1 + 28
    rpx2 = rx2 - 12 - 28
    rpy = BODY_Y + 22

    d.text((rpx1, rpy), "📨 Мои приглашённые", font=_font(28), fill=TEXT)
    sub = f"{stats['total']} чел. · {stats['rewarded']} засчитано · {stats['on_review']} на проверке"
    sw = _tw(d, sub, _font(13))
    d.text((rpx2 - sw, rpy + 12), sub, font=_font(13), fill=MUTED)

    sep_y = rpy + 44
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)

    col_x = [rpx1, rpx1 + 80, rpx2 - 660, rpx2 - 440, rpx2 - 220]
    th_y = sep_y + 14
    for x, lbl in zip(col_x[1:], ["ПОЛЬЗОВАТЕЛЬ", "ВХОД", "ВЫХОД", "СТАТУС"]):
        d.text((x, th_y), lbl, font=_font(10), fill=MUTED)

    list_y = th_y + 30
    list_bottom = BODY_Y + BODY_H - 12 - 22
    row_h = 84
    row_gap = 6

    rows = stats.get("rows", [])[:6]

    if not rows:
        cx = (rpx1 + rpx2) // 2
        cy = (list_y + list_bottom) // 2
        _icon(d, cx, cy - 20, I_ELL, 40, DIM)
        msg = "Пока никого не пригласил"
        mw = _tw(d, msg, _font(18))
        d.text((cx - mw // 2, cy + 30), msg, font=_font(18), fill=DIM)
    else:
        for i, row in enumerate(rows):
            ry = list_y + i * (row_h + row_gap)
            if ry + row_h > list_bottom:
                break
            _draw_invite_row(img, d, rpx1, ry, rpx2 - rpx1, row_h, row, col_x)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 2: ОБЩИЙ ТОП
# ============================================================
def render_top(user_id, username, stats, my_place, my_diff_1, my_diff_3, top_list):
    img, d = _canvas(user_id, "общий топ")

    left_w = 460
    gap = 36
    lx1, lx2 = PAD_X, PAD_X + left_w
    rx1, rx2 = lx2 + gap, W - PAD_X

    _draw_left_panel(img, d, (lx1, BODY_Y, lx2 - 12, BODY_Y + BODY_H - 12),
                     user_id, username, stats)

    lp_y2 = BODY_Y + BODY_H - 12
    info_h = 96
    info_y = lp_y2 - 22 - info_h
    ip_x1 = lx1 + 26
    ip_x2 = lx2 - 12 - 26

    _grad(img, (ip_x1, info_y, ip_x2, info_y + info_h),
          GOLD, GOLD, alpha=18, radius=14)
    d.rounded_rectangle((ip_x1, info_y, ip_x2, info_y + info_h),
                        radius=14, outline=GOLD + (200,), width=2)
    _icon(d, ip_x1 + 22, info_y + 24, I_TROPHY, 14, _lighten(GOLD, .4))
    d.text((ip_x1 + 44, info_y + 18), "ТВОЁ МЕСТО",
           font=_font(10), fill=_lighten(GOLD, .4))
    place_str = f"#{my_place}" if my_place else "—"
    d.text((ip_x1 + 16, info_y + 40), place_str, font=_font(30), fill=GOLD)
    diff_str = f"до #1: -{my_diff_1}" if my_diff_1 else "ты в топе!"
    d.text((ip_x1 + 16, info_y + 74), diff_str, font=_font(11), fill=MUTED)

    _panel(img, d, (rx1, BODY_Y, rx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    rpx1 = rx1 + 28
    rpx2 = rx2 - 12 - 28
    rpy = BODY_Y + 22

    d.text((rpx1, rpy), "🏆 Топ адвайтеров", font=_font(28), fill=TEXT)
    sub = f"{len(top_list)} сотрудников · по засчитанным"
    sw = _tw(d, sub, _font(13))
    d.text((rpx2 - sw, rpy + 12), sub, font=_font(13), fill=MUTED)

    sep_y = rpy + 44
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)

    list_y = sep_y + 14
    list_bottom = BODY_Y + BODY_H - 12 - 22
    row_h = 118
    row_gap = 10

    if not top_list:
        cx = (rpx1 + rpx2) // 2
        cy = (list_y + list_bottom) // 2
        _icon(d, cx, cy - 20, I_ELL, 40, DIM)
        msg = "Пока никого в топе"
        mw = _tw(d, msg, _font(18))
        d.text((cx - mw // 2, cy + 30), msg, font=_font(18), fill=DIM)
    else:
        for i, entry in enumerate(top_list[:5]):
            ry = list_y + i * (row_h + row_gap)
            if ry + row_h > list_bottom:
                break

            aid = entry["advertiser_id"]
            name = entry.get("username") or f"@{aid}"
            rewarded = entry["rewarded"]
            on_review = entry["on_review"]
            total = entry["total"]
            is_me = (aid == user_id)

            if i == 0:
                border, fill_alpha, icon_c = GOLD, 30, GOLD
            elif i == 1:
                border, fill_alpha, icon_c = SILVER, 30, SILVER
            elif i == 2:
                border, fill_alpha, icon_c = BRONZE, 30, BRONZE
            elif is_me:
                border, fill_alpha, icon_c = BLUE, 25, BLUE
            else:
                border, fill_alpha, icon_c = STACK_HDR, 20, DIM

            _grad(img, (rpx1, ry, rpx2, ry + row_h),
                  border, border, alpha=fill_alpha, radius=14)
            d.rounded_rectangle((rpx1, ry, rpx2, ry + row_h), radius=14,
                                outline=border + (220,), width=2)

            m_size = 54
            mx = rpx1 + 18
            my = ry + row_h // 2 - m_size // 2
            _alpha(img, (mx, my, mx + m_size, my + m_size),
                   border, alpha=80, radius=14)
            d.rounded_rectangle((mx, my, mx + m_size, my + m_size), radius=14,
                                outline=border + (200,), width=2)
            if i < 3:
                _icon(d, mx + m_size // 2, my + m_size // 2 + 1, I_MEDAL, 24, icon_c)
            else:
                num = str(i + 1)
                nw = _tw(d, num, _font(22))
                d.text((mx + m_size // 2 - nw // 2, my + m_size // 2 - 13),
                       num, font=_font(22), fill=icon_c)

            av_size = 54
            avx = mx + m_size + 16
            avy = ry + row_h // 2 - av_size // 2
            d.ellipse((avx, avy, avx + av_size, avy + av_size), fill=(58, 58, 64))
            _icon(d, avx + av_size // 2, avy + av_size // 2 + 1, I_USER, 22, TEXT)

            name_x = avx + av_size + 18
            name_max = (rpx2 - 500) - name_x - 10
            name_shown = _el(d, name, _font(17), max(name_max, 60))
            d.text((name_x, ry + row_h // 2 - 22), name_shown, font=_font(17), fill=TEXT)
            if is_me:
                nw = _tw(d, name_shown, _font(17))
                d.text((name_x + nw + 8, ry + row_h // 2 - 22), "(ты)",
                       font=_font(13), fill=BLUE)
            d.text((name_x, ry + row_h // 2 + 4), f"ID: {aid}",
                   font=_font(11), fill=DIM)

            col_start = rpx2 - 500
            col_w = 165
            items = [
                ("ЗАСЧИТАНО", str(rewarded), GREEN),
                ("ПРОВЕРКА",  str(on_review), GOLD),
                ("ВСЕГО",     str(total),     SILVER_HI),
            ]
            for j, (lbl, val, color) in enumerate(items):
                cx = col_start + j * col_w
                lw = _tw(d, lbl, _font(10))
                d.text((cx + col_w // 2 - lw // 2, ry + row_h // 2 - 26),
                       lbl, font=_font(10), fill=MUTED)
                vw = _tw(d, val, _font(28))
                d.text((cx + col_w // 2 - vw // 2, ry + row_h // 2 - 4),
                       val, font=_font(28), fill=color)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 3: МОИ НАГРАДЫ
# ============================================================
def render_rewards(user_id, username, stats, total_dc, hold_dc, history):
    from work.core import REWARD_AMOUNT

    img, d = _canvas(user_id, "мои награды")

    left_w = 460
    gap = 36
    lx1, lx2 = PAD_X, PAD_X + left_w
    rx1, rx2 = lx2 + gap, W - PAD_X

    _draw_left_panel(img, d, (lx1, BODY_Y, lx2 - 12, BODY_Y + BODY_H - 12),
                     user_id, username, stats)

    lp_y2 = BODY_Y + BODY_H - 12
    hero_h = 130
    hero_y = lp_y2 - 22 - hero_h
    hx1 = lx1 + 26
    hx2 = lx2 - 12 - 26

    _grad(img, (hx1, hero_y, hx2, hero_y + hero_h),
          GREEN, GREEN, alpha=22, radius=16)
    d.rounded_rectangle((hx1, hero_y, hx2, hero_y + hero_h),
                        radius=16, outline=GREEN + (220,), width=2)

    cx_mid = (hx1 + hx2) // 2

    lbl = "ЗАРАБОТАНО ВСЕГО"
    lw = _tw(d, lbl, _font(12))
    d.text((cx_mid - lw // 2, hero_y + 18), lbl, font=_font(12), fill=GREEN)

    total_str = str(total_dc)
    tf = _font(50)
    tw_ = _tw(d, total_str, tf)
    uw = _tw(d, " DC", _font(22))
    start_x = cx_mid - (tw_ + uw + 8) // 2
    d.text((start_x, hero_y + 44), total_str, font=tf, fill=GREEN)
    d.text((start_x + tw_ + 8, hero_y + 44 + 50 - 24), "DC",
           font=_font(22), fill=MUTED)

    hold = f"в холде: {hold_dc} DC"
    hw = _tw(d, hold, _font(12))
    d.text((cx_mid - hw // 2, hero_y + 102), hold, font=_font(12), fill=GOLD)

    _panel(img, d, (rx1, BODY_Y, rx2 - 12, BODY_Y + BODY_H - 12), radius=22)
    rpx1 = rx1 + 28
    rpx2 = rx2 - 12 - 28
    rpy = BODY_Y + 22

    d.text((rpx1, rpy), "💰 История начислений", font=_font(28), fill=TEXT)
    sub = f"последние {min(len(history), 8)} · всего: {total_dc} DC"
    sw = _tw(d, sub, _font(13))
    d.text((rpx2 - sw, rpy + 12), sub, font=_font(13), fill=MUTED)

    sep_y = rpy + 44
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2)

    list_y = sep_y + 14
    list_bottom = BODY_Y + BODY_H - 12 - 22
    row_h = 74
    row_gap = 6

    if not history:
        cx = (rpx1 + rpx2) // 2
        cy = (list_y + list_bottom) // 2
        _icon(d, cx, cy - 20, I_ELL, 40, DIM)
        msg = "Начислений пока нет"
        mw = _tw(d, msg, _font(18))
        d.text((cx - mw // 2, cy + 30), msg, font=_font(18), fill=DIM)
    else:
        for i, row in enumerate(history[:8]):
            ry = list_y + i * (row_h + row_gap)
            if ry + row_h > list_bottom:
                break

            d.rounded_rectangle((rpx1, ry, rpx2, ry + row_h), radius=12,
                                fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
            d.rounded_rectangle((rpx1, ry + 8, rpx1 + 4, ry + row_h - 8),
                                radius=4, fill=GREEN + (255,))

            ib_size = 42
            ibx = rpx1 + 16
            iby = ry + (row_h - ib_size) // 2
            _alpha(img, (ibx, iby, ibx + ib_size, iby + ib_size),
                   GREEN, alpha=40, radius=11)
            _icon(d, ibx + ib_size // 2, iby + ib_size // 2 + 1, I_CHECK, 18, GREEN)

            tx = ibx + ib_size + 16
            d.text((tx, ry + row_h // 2 - 16), f"Приглашён ID {row['member_id']}",
                   font=_font(14), fill=TEXT)

            try:
                jdt = datetime.fromtimestamp(row["joined_at"], timezone.utc).strftime("%d.%m.%Y")
                ldt = datetime.fromtimestamp(row["left_at"], timezone.utc).strftime("%d.%m.%Y") \
                    if row.get("left_at") else "—"
                sub_t = f"{jdt} → {ldt}"
            except Exception:
                sub_t = "—"
            d.text((tx, ry + row_h // 2 + 4), sub_t, font=_font(11), fill=MUTED)

            amt = f"+{REWARD_AMOUNT} DC"
            aw = _tw(d, amt, _font(20))
            d.text((rpx2 - 20 - aw, ry + row_h // 2 - 14), amt,
                   font=_font(20), fill=GREEN)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
