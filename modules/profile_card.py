# -*- coding: utf-8 -*-
"""Рендер карточки профиля на PIL + FA. Дизайн 1800×1000 под Diamond Shop."""
import io
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont
from core.utils import ADD_DIR, logger

# Мягкий импорт — если клан-лига не загружена
try:
    from clan.core import get_user_clan
except Exception:
    get_user_clan = None

FONT_BOLD = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_FONT_CACHE = {}
_FA_CACHE = {}

# ============================================================
# ЦВЕТА
# ============================================================
BG        = (10, 10, 12)
CARD_TOP  = (16, 16, 20)          # #101014
STACK_BG  = (21, 21, 26)          # #15151a (панели)
STACK_BRD = (58, 58, 64)          # #3a3a40
STACK_HDR = (36, 36, 42)          # #24242a разделители
INNER_BG  = (15, 15, 20)          # #0f0f14 (внутренние плитки)
INNER_BRD = (36, 36, 42)          # #24242a
TEXT      = (255, 255, 255)
TEXT_SOFT = (232, 232, 236)
MUTED     = (136, 136, 136)
DIM       = (102, 102, 102)
DARK      = (85, 85, 85)

GOLD      = (247, 201, 145)
GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)

GOLD_BG   = (40, 32, 21)
GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)

CARD_BRD  = (74, 74, 79)

# ============================================================
# FA-иконки
# ============================================================
I_USERS   = 0xf0c0
I_CROWN   = 0xf521
I_GEM     = 0xf3a5
I_STAR    = 0xf005
I_CIRCLE_M= 0xf056   # circle-minus
I_CHART   = 0xf201   # chart-line
I_THUMBS  = 0xf164
I_CAL     = 0xf073
I_CLOCK   = 0xf017
I_ROTATE  = 0xf2ea
I_TROPHY  = 0xf091
I_CART    = 0xf07a
I_GIFT    = 0xf06b
I_DICE    = 0xf522
I_COINS   = 0xf51e
I_SACK    = 0xf81d

# ============================================================
# Инфо о ролях покупателя
# ============================================================
ROLE_INFO = {
    "none":      "Нет роли",
    "club":      "Клуб",
    "bronze":    "Bronze Buyer",
    "silver":    "Silver Buyer",
    "gold":      "Gold Buyer",
    "diamond":   "Diamond Buyer",
    "crystalis": "Crystalis Buyer",
    "pka":       "Покупатель Века",
}


# ============================================================
# Шрифты
# ============================================================
def _font(size: int):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        f = ImageFont.truetype(FONT_BOLD, size)
    except Exception:
        f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


def _fa(size: int):
    if size in _FA_CACHE:
        return _FA_CACHE[size]
    f = None
    if os.path.exists(FONT_FA):
        try:
            f = ImageFont.truetype(FONT_FA, size)
        except Exception:
            pass
    _FA_CACHE[size] = f
    return f


def _draw_icon(d, cx, cy, code, size, color):
    f = _fa(size)
    if f is None:
        return
    try:
        d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception:
        pass


def _tw(d, text, font):
    b = d.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def _ellipsis(d, text, font, max_w):
    if _tw(d, text, font) <= max_w:
        return text
    t = text
    while t and _tw(d, t + "…", font) > max_w:
        t = t[:-1]
    return t + "…"


def _fmt(n):
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


# ============================================================
# Утилиты
# ============================================================
def _hex_to_rgb(h: int) -> Tuple[int, int, int]:
    return ((h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF)


def _mix(c1, c2, t):
    return (
        int(c1[0] * (1 - t) + c2[0] * t),
        int(c1[1] * (1 - t) + c2[1] * t),
        int(c1[2] * (1 - t) + c2[2] * t),
    )


def _alpha_fill(base_img: Image.Image, box, color, alpha=30, radius=0):
    """Накладывает полупрозрачный цвет на box."""
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
    base_img.paste(layer, (x1, y1), layer)


def _gradient_box(base_img, box, c1, c2, alpha=30, radius=0):
    """Горизонтальный градиент между c1 и c2 с прозрачностью."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for x in range(w):
        t = x / max(w - 1, 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        ld.line([(x, 0), (x, h)], fill=(r, g, b, alpha))
    if radius > 0:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        layer.putalpha(Image.composite(layer.split()[3], Image.new("L", (w, h), 0), mask))
    base_img.paste(layer, (x1, y1), layer)


def _dashed_rounded_rect(draw, box, radius, color, dash=8, gap=6, width=2):
    """Пунктирный скруглённый прямоугольник (упрощённо — прямые участки)."""
    x1, y1, x2, y2 = box
    r = radius

    def dash_line(p1, p2):
        import math
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return
        ux, uy = dx / length, dy / length
        pos = 0.0
        while pos < length:
            seg_end = min(pos + dash, length)
            a = (p1[0] + ux * pos, p1[1] + uy * pos)
            b = (p1[0] + ux * seg_end, p1[1] + uy * seg_end)
            draw.line([a, b], fill=color, width=width)
            pos = seg_end + gap

    # Прямые участки
    dash_line((x1 + r, y1), (x2 - r, y1))
    dash_line((x2 - r, y2), (x1 + r, y2))
    dash_line((x1, y1 + r), (x1, y2 - r))
    dash_line((x2, y1 + r), (x2, y2 - r))
    # Углы
    draw.arc((x1, y1, x1 + 2 * r, y1 + 2 * r), 180, 270, fill=color, width=width)
    draw.arc((x2 - 2 * r, y1, x2, y1 + 2 * r), 270, 360, fill=color, width=width)
    draw.arc((x1, y2 - 2 * r, x1 + 2 * r, y2), 90, 180, fill=color, width=width)
    draw.arc((x2 - 2 * r, y2 - 2 * r, x2, y2), 0, 90, fill=color, width=width)


def _avatar_img(ab, size):
    try:
        img = Image.open(io.BytesIO(ab)).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask)
        return out
    except Exception as e:
        logger.warning(f"Avatar err: {e}")
        return None


def _since_days(dt):
    if not dt:
        return 0
    d = (datetime.now(timezone.utc) - dt).days
    return max(d, 0)


def _fmt_days(n):
    """194 дня / 5 дней"""
    last = n % 10
    last2 = n % 100
    if last == 1 and last2 != 11:
        suf = "день"
    elif 2 <= last <= 4 and not (12 <= last2 <= 14):
        suf = "дня"
    else:
        suf = "дней"
    return f"{n} {suf}"


def _op_icon(reason: str) -> int:
    r = reason.lower()
    if "рулетк" in r: return I_TROPHY
    if "блэкдж" in r: return I_DICE
    if "монет" in r: return I_COINS
    if "отзыв" in r: return I_STAR
    if "зарплат" in r or "аванс" in r: return I_SACK
    if "покупк" in r: return I_CART
    if "акци" in r: return I_TROPHY
    if "подарок" in r or "ежеднев" in r: return I_GIFT
    if "клан" in r or "копилк" in r: return I_GEM
    return I_COINS


def _op_time_str(ts: int) -> str:
    """Сегодня · 14:32 / Вчера · 09:00 / 12.03 · 18:40"""
    if not ts:
        return "—"
    try:
        dt = datetime.fromtimestamp(ts, timezone.utc)
    except Exception:
        return "—"
    now = datetime.now(timezone.utc)
    today = now.date()
    d = dt.date()
    hm = dt.strftime("%H:%M")
    if d == today:
        return f"Сегодня · {hm}"
    if (today - d).days == 1:
        return f"Вчера · {hm}"
    return dt.strftime("%d.%m · %H:%M")


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================
def generate_profile_card(
    user_name: str,
    user_id: int,
    avatar_bytes: Optional[bytes],
    role_key: str,
    reviews: int,
    balance: int,
    joined_at: Optional[datetime],
    history: List[Dict],
) -> io.BytesIO:

    W, H = 1800, 1000
    M = 0
    PAD_X = 56
    PAD_Y = 44

    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)

    # ============================================================
    # КАРТОЧКА (внешний бокс)
    # ============================================================
    d.rounded_rectangle((M, M, W - 1, H - 1), radius=30, fill=CARD_TOP + (255,),
                        outline=CARD_BRD + (255,), width=3)

    # ============================================================
    # HEADER
    # ============================================================
    hx = PAD_X
    hy = PAD_Y

    # Логотип
    logo_size = 54
    d.rounded_rectangle((hx, hy, hx + logo_size, hy + logo_size), radius=14,
                        fill=(58, 58, 64) + (255,))
    _draw_icon(d, hx + logo_size // 2, hy + logo_size // 2 + 1, I_USERS, 26, (232, 232, 236))

    # Бренд
    brand_x = hx + logo_size + 18
    d.text((brand_x, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((brand_x + 2, hy + 38), "SHOP & ECOSYSTEM", font=_font(11), fill=MUTED)

    # Правая мета
    meta_r = W - PAD_X
    lbl = "ПРОФИЛЬ ПОКУПАТЕЛЯ"
    id_str = f"#{user_id}"
    w1 = _tw(d, lbl, _font(11))
    w2 = _tw(d, id_str, _font(20))
    d.text((meta_r - w1, hy + 12), lbl, font=_font(11), fill=MUTED)
    d.text((meta_r - w2, hy + 32), id_str, font=_font(20), fill=TEXT)

    # Разделитель
    sep_y = hy + logo_size + 16
    d.line((PAD_X, sep_y, W - PAD_X, sep_y), fill=STACK_HDR + (255,), width=2)

    # ============================================================
    # BODY GRID: 380 | 34 gap | rest
    # ============================================================
    body_y = sep_y + 24
    body_h = H - PAD_Y - body_y
    left_w = 380
    gap = 34
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = W - PAD_X

    # ============================================================
    # ЛЕВАЯ СТОПКА (профиль)
    # ============================================================
    _draw_stack_panel(
        img, d,
        (left_x1, body_y, left_x2 - 14, body_y + body_h - 14),
        radius=24,
    )

    # Внутренний бокс левой панели
    lp_x1, lp_y1 = left_x1, body_y
    lp_x2, lp_y2 = left_x2 - 14, body_y + body_h - 14

    # --- Аватар с glow ---
    av_size = 230
    av_cx = (lp_x1 + lp_x2) // 2
    av_cy = lp_y1 + 60 + av_size // 2
    av_x = av_cx - av_size // 2
    av_y = av_cy - av_size // 2

    # Glow
    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    for r in range(40, 0, -4):
        alpha = int(10 + (40 - r) * 0.6)
        gd.ellipse((av_x - r, av_y - r, av_x + av_size + r, av_y + av_size + r),
                   fill=GOLD + (max(0, alpha),))
    img.alpha_composite(glow_layer)
    d = ImageDraw.Draw(img)

    # Аватар
    av_img = _avatar_img(avatar_bytes, av_size) if avatar_bytes else None
    if av_img:
        # Рисуем бордер
        d.ellipse((av_x - 5, av_y - 5, av_x + av_size + 5, av_y + av_size + 5),
                  outline=GOLD + (255,), width=5)
        img.paste(av_img, (av_x, av_y), av_img)
    else:
        d.ellipse((av_x, av_y, av_x + av_size, av_y + av_size), fill=(60, 60, 66))
        _draw_icon(d, av_cx, av_cy + 2, I_USERS, 90, MUTED)
        d.ellipse((av_x - 5, av_y - 5, av_x + av_size + 5, av_y + av_size + 5),
                  outline=GOLD + (255,), width=5)

    # --- Бейджи ---
    badge_w = 280
    badge_h = 50
    badge_x = (lp_x1 + lp_x2) // 2 - badge_w // 2
    badges_y = av_y + av_size + 36

    # ROLE BADGE
    role_label = ROLE_INFO.get(role_key, ROLE_INFO["none"]).upper()
    has_role = role_key != "none" and role_key != ""

    _draw_badge(
        d, img,
        x=badge_x, y=badges_y, w=badge_w, h=badge_h,
        icon=I_CROWN if has_role else I_CIRCLE_M,
        text=role_label,
        c1=GOLD, c2=GOLD,  # одноцветный
        text_color=GOLD if has_role else DARK,
        border_color=GOLD if has_role else (51, 51, 51),
        dashed=not has_role,
    )

    # CLAN BADGE
    clan = None
    if get_user_clan:
        try:
            clan = get_user_clan(user_id)
        except Exception:
            clan = None

    clan_y = badges_y + badge_h + 12
    if clan:
        c1 = _hex_to_rgb(clan.get("color", 0xb3e1b9))
        c2 = _hex_to_rgb(clan.get("color_dark", clan.get("color", 0xb3e1b9)))
        _draw_badge(
            d, img,
            x=badge_x, y=clan_y, w=badge_w, h=badge_h,
            icon=I_GEM if clan["name"] != "Сияние" else I_STAR,
            text=clan["name"].upper(),
            c1=c1, c2=c2,
            text_color=c1,
            border_color=c1,
            bg_gradient=(c1, c2),
            dashed=False,
        )
    else:
        _draw_badge(
            d, img,
            x=badge_x, y=clan_y, w=badge_w, h=badge_h,
            icon=I_CIRCLE_M,
            text="БЕЗ КЛАНА",
            c1=DARK, c2=DARK,
            text_color=DARK,
            border_color=(51, 51, 51),
            dashed=True,
        )

    # UID
    uid_text = f"UID · {user_id}"
    uid_f = _font(13)
    uid_w = _tw(d, uid_text, uid_f)
    d.text(((lp_x1 + lp_x2) // 2 - uid_w // 2, clan_y + badge_h + 22),
           uid_text, font=uid_f, fill=MUTED)

    # ============================================================
    # ПРАВАЯ СТОПКА (ник + статы + операции)
    # ============================================================
    _draw_stack_panel(
        img, d,
        (right_x1, body_y, right_x2 - 14, body_y + body_h - 14),
        radius=24,
    )
    rp_x1 = right_x1 + 32
    rp_x2 = right_x2 - 14 - 32
    rp_y = body_y + 28

    # --- Ник ---
    uname = user_name
    max_w = rp_x2 - rp_x1
    if _tw(d, uname, _font(44)) > max_w:
        uname = _ellipsis(d, uname, _font(44), max_w)
    d.text((rp_x1, rp_y), uname, font=_font(44), fill=TEXT)

    # Подпись «В Diamond с … · N дней»
    sub_y = rp_y + 58
    days_n = _since_days(joined_at) if joined_at else 0
    joined_str = joined_at.strftime("%d.%m.%Y") if joined_at else "—"
    part1 = "В DIAMOND С "
    part2 = joined_str
    part3 = f" · {_fmt_days(days_n).upper()}" if joined_at else ""
    sub_f = _font(14)
    x_cursor = rp_x1
    d.text((x_cursor, sub_y), part1, font=sub_f, fill=MUTED)
    x_cursor += _tw(d, part1, sub_f)
    d.text((x_cursor, sub_y), part2, font=_font(16), fill=GOLD)
    x_cursor += _tw(d, part2, _font(16))
    d.text((x_cursor, sub_y), part3, font=sub_f, fill=MUTED)

    # Разделитель после ника
    sep2_y = sub_y + 40
    d.line((rp_x1 - 32, sep2_y, rp_x2 + 32, sep2_y), fill=STACK_HDR + (255,), width=2)

    # --- Section title: Статистика ---
    st_y = sep2_y + 22
    _draw_icon(d, rp_x1 + 7, st_y + 8, I_CHART, 14, GOLD)
    d.text((rp_x1 + 22, st_y), "СТАТИСТИКА", font=_font(11), fill=MUTED)

    # --- Stats 3 в ряд ---
    stats_y = st_y + 34
    stat_h = 130
    stat_gap = 16
    stat_w = (rp_x2 - rp_x1 - stat_gap * 2) // 3

    _draw_stat(
        d,
        x=rp_x1, y=stats_y, w=stat_w, h=stat_h,
        icon_code=I_THUMBS, icon_bg=GOLD_BG, icon_color=GOLD,
        lbl="ОТЗЫВОВ", val=str(reviews), val_color=TEXT,
    )
    _draw_stat(
        d,
        x=rp_x1 + stat_w + stat_gap, y=stats_y, w=stat_w, h=stat_h,
        icon_code=I_GEM, icon_bg=GREEN_BG, icon_color=GREEN,
        lbl="БАЛАНС", val=_fmt(balance), val_color=GREEN, val_suffix="DC",
    )
    _draw_stat(
        d,
        x=rp_x1 + (stat_w + stat_gap) * 2, y=stats_y, w=stat_w, h=stat_h,
        icon_code=I_CLOCK, icon_bg=BLUE_BG, icon_color=BLUE,
        lbl="ДНЕЙ В КОМЬЮНИТИ", val=str(days_n), val_color=TEXT, val_suffix="дня",
    )

    # --- Section title: Операции ---
    op_st_y = stats_y + stat_h + 24
    _draw_icon(d, rp_x1 + 7, op_st_y + 8, I_ROTATE, 14, GOLD)
    d.text((rp_x1 + 22, op_st_y), "ПОСЛЕДНИЕ ОПЕРАЦИИ", font=_font(11), fill=MUTED)

    # --- Операции (5 штук) ---
    ops_y = op_st_y + 34
    ops_area_h = (body_y + body_h - 14) - 28 - ops_y
    ops_gap = 10
    op_h = (ops_area_h - ops_gap * 4) // 5

    ops = (history or [])[-5:]
    # Если меньше 5 — добиваем пустыми
    while len(ops) < 5:
        ops.insert(0, None)

    for i, op in enumerate(ops[-5:]):
        oy = ops_y + i * (op_h + ops_gap)
        _draw_operation_row(
            d, rp_x1, oy, rp_x2 - rp_x1, op_h, op
        )

    # ============================================================
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ РИСОВАЛКИ
# ============================================================
def _draw_stack_panel(img, d, box, radius=24):
    """Стеклянная панель с 2 подложками позади."""
    x1, y1, x2, y2 = box

    # Подложка 1 (дальняя) — translate(12,12)
    _alpha_fill(img, (x1 + 12, y1 + 12, x2 + 12, y2 + 12),
                (46, 46, 52), alpha=110, radius=radius)
    # Подложка 2 (ближняя) — translate(6,6)
    _alpha_fill(img, (x1 + 6, y1 + 6, x2 + 6, y2 + 6),
                (46, 46, 52), alpha=180, radius=radius)
    # Основная панель
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=2)


def _draw_badge(d, img, x, y, w, h, icon, text,
                c1, c2, text_color, border_color,
                bg_gradient=None, dashed=False):
    """Один бейдж."""
    # Фон
    if bg_gradient:
        _gradient_box(img, (x, y, x + w, y + h),
                      bg_gradient[0], bg_gradient[1], alpha=30, radius=14)
    else:
        _alpha_fill(img, (x, y, x + w, y + h), c1, alpha=22, radius=14)

    # Бордер
    if dashed:
        _dashed_rounded_rect(d, (x, y, x + w, y + h), 14, border_color, dash=8, gap=5, width=2)
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=14,
                            outline=border_color + (255,), width=2)

    # Иконка + текст по центру
    icon_x = x + 22
    _draw_icon(d, icon_x, y + h // 2 + 1, icon, 18, text_color)
    # Текст
    text_w = _tw(d, text, _font(13))
    # Центрируем «иконка + текст» относительно центра
    total_w = 22 + 10 + text_w  # icon + gap + text
    start_x = x + (w - total_w) // 2
    _draw_icon(d, start_x + 8, y + h // 2 + 1, icon, 15, text_color)
    d.text((start_x + 24, y + h // 2), text, font=_font(13), fill=text_color, anchor="lm")


def _draw_stat(d, x, y, w, h, icon_code, icon_bg, icon_color,
               lbl, val, val_color, val_suffix=None):
    # Фон
    d.rounded_rectangle((x, y, x + w, y + h), radius=18,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

    # Иконка (сверху-слева)
    ib_size = 48
    ib_x = x + 22
    ib_y = y + 20
    d.rounded_rectangle((ib_x, ib_y, ib_x + ib_size, ib_y + ib_size),
                        radius=13, fill=icon_bg + (255,))
    _draw_icon(d, ib_x + ib_size // 2, ib_y + ib_size // 2 + 1, icon_code, 22, icon_color)

    # Label
    d.text((x + 22, ib_y + ib_size + 12), lbl, font=_font(10), fill=MUTED)

    # Value
    val_f = _font(36)
    val_str = val
    # Если value длинное — уменьшаем
    max_val_w = w - 44
    while _tw(d, val_str, val_f) > max_val_w and val_f.size > 18:
        val_f = _font(val_f.size - 2)

    val_y = y + h - 22 - val_f.size
    d.text((x + 22, val_y), val_str, font=val_f, fill=val_color)

    # Суффикс
    if val_suffix:
        vw = _tw(d, val_str, val_f)
        d.text((x + 22 + vw + 8, val_y + val_f.size - 22),
               val_suffix, font=_font(15), fill=MUTED)


def _draw_operation_row(d, x, y, w, h, op: Optional[dict]):
    """Одна операция. Если op=None — пустой слот."""
    # Фон
    d.rounded_rectangle((x, y, x + w, y + h), radius=14,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

    if not op:
        # Пустой слот
        _draw_icon(d, x + 22 + 26, y + h // 2, I_CIRCLE_M, 22, DARK)
        d.text((x + 22 + 26 + 30, y + h // 2), "—", font=_font(17),
               fill=DARK, anchor="lm")
        return

    amt = op.get("amount", 0)
    reason = op.get("reason", "—") or "—"
    ts = op.get("date", 0)

    is_plus = amt >= 0
    accent = GREEN if is_plus else RED
    accent_bg = GREEN_BG if is_plus else RED_BG
    sign = "+" if is_plus else "−"

    # Левый бордер
    d.rounded_rectangle((x, y, x + 4, y + h), radius=4, fill=accent + (255,))

    # Иконка
    op_icon_size = 52
    ib_x = x + 18
    ib_y = y + (h - op_icon_size) // 2
    d.rounded_rectangle((ib_x, ib_y, ib_x + op_icon_size, ib_y + op_icon_size),
                        radius=13, fill=accent_bg + (255,))
    _draw_icon(d, ib_x + op_icon_size // 2, ib_y + op_icon_size // 2 + 1,
               _op_icon(reason), 22, accent)

    # Название + время
    text_x = ib_x + op_icon_size + 18
    name_f = _font(17)
    time_f = _font(12)

    # Правый блок (сумма + тэг)
    amt_str = f"{sign}{abs(int(amt))} DC"
    amt_f = _font(22)
    amt_w = _tw(d, amt_str, amt_f)
    tag_str = "ДОХОД" if is_plus else "РАСХОД"
    tag_f = _font(10)
    tag_w = _tw(d, tag_str, tag_f)

    right_block_w = max(amt_w, tag_w)
    right_x = x + w - 22 - right_block_w

    # Имя
    max_name_w = right_x - 20 - text_x
    name_shown = _ellipsis(d, reason, name_f, max_name_w)
    name_y = y + h // 2 - 20
    d.text((text_x, name_y), name_shown, font=name_f, fill=TEXT_SOFT)

    # Время
    time_str = _op_time_str(ts).upper()
    d.text((text_x, name_y + 22), time_str, font=time_f, fill=DIM)

    # Сумма
    amt_y = y + h // 2 - 22
    d.text((x + w - 22 - amt_w, amt_y), amt_str, font=amt_f, fill=accent)

    # Тег
    tag_color = (int(GREEN[0]), int(GREEN[1]), int(GREEN[2])) if is_plus else RED
    tag_color_dim = (tag_color[0] // 2 + 20, tag_color[1] // 2 + 20, tag_color[2] // 2 + 20)
    d.text((x + w - 22 - tag_w, amt_y + 30), tag_str, font=tag_f, fill=tag_color_dim)
