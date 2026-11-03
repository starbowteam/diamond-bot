# -*- coding: utf-8 -*-
"""Рендер карточки профиля на PIL + FA. Дизайн 1800×1000 под Diamond Shop."""
import io
import os
import math
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont
from core.utils import ADD_DIR, logger, EXEMPT_USERS

try:
    from clan.core import get_user_clan, CLANS_DATA
except Exception:
    get_user_clan = None
    CLANS_DATA = []

FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_FONT_CACHE = {}
_FA_CACHE = {}

# ============================================================
# ЦВЕТА
# ============================================================
BG        = (10, 10, 12)
CARD_TOP  = (16, 16, 20)
STACK_BG  = (21, 21, 26)
STACK_BRD = (58, 58, 64)
STACK_HDR = (36, 36, 42)
INNER_BG  = (15, 15, 20)
INNER_BRD = (36, 36, 42)
TEXT      = (255, 255, 255)
TEXT_SOFT = (232, 232, 236)
MUTED     = (136, 136, 136)
DIM       = (102, 102, 102)
DARK      = (85, 85, 85)

SILVER    = (198, 208, 224)
GOLD      = (247, 201, 145)
GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)

GOLD_BG   = (40, 32, 21)
GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)

CARD_BRD  = (74, 74, 79)

# ============================================================
# ГРАДИЕНТЫ РОЛЕЙ
# ============================================================
ROLE_GRADIENTS = {
    "bronze":    ((0xe7, 0x8f, 0x67), (0xd1, 0x56, 0x40)),
    "silver":    ((0xff, 0xff, 0xff), (0x97, 0x97, 0x97)),
    "gold":      ((0xf7, 0xc9, 0x91), (0xae, 0x79, 0x11)),
    "diamond":   ((0xdd, 0xf0, 0xef), (0x14, 0x9b, 0xd0)),
    "crystalis": ((0x9f, 0xc1, 0xff), (0xd8, 0x8e, 0xdf)),
    "pka":       ((0xad, 0xad, 0xad), (0x69, 0x69, 0x69)),
    "club":      ((0xf7, 0xc9, 0x91), (0xae, 0x79, 0x11)),
    "none":      ((0x66, 0x66, 0x66), (0x44, 0x44, 0x44)),
}

# ============================================================
# FA-ИКОНКИ
# ============================================================
I_USERS   = 0xf0c0
I_CROWN   = 0xf521
I_GEM     = 0xf3a5
I_STAR    = 0xf005
I_CIRCLE_M= 0xf056
I_CHART   = 0xf201
I_THUMBS  = 0xf164
I_CLOCK   = 0xf017
I_ROTATE  = 0xf2ea
I_TROPHY  = 0xf091
I_CART    = 0xf07a
I_GIFT    = 0xf06b
I_DICE    = 0xf522
I_COINS   = 0xf51e
I_SACK    = 0xf81d
I_SHIELD  = 0xf3ed


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
# САНИТАЙЗЕР НИКА
# ============================================================
def _sanitize_name(text: str, fallback: str = "Пользователь") -> str:
    if not text:
        return fallback

    allowed_special = set("—–‑‒―“”«»„‘’…№")
    out_chars = []
    for ch in text:
        cp = ord(ch)
        if 0x20 <= cp <= 0x7E:
            out_chars.append(ch)
            continue
        if 0x0400 <= cp <= 0x04FF:
            out_chars.append(ch)
            continue
        if 0x00C0 <= cp <= 0x017F:
            out_chars.append(ch)
            continue
        if ch in allowed_special:
            out_chars.append(ch)
            continue

    result = "".join(out_chars).strip()
    while "  " in result:
        result = result.replace("  ", " ")
    if not result:
        return fallback
    return result


# ============================================================
# Утилиты рисования
# ============================================================
def _hex_to_rgb(h: int) -> Tuple[int, int, int]:
    return ((h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF)


def _lerp_color(c1, c2, t):
    return (
        int(c1[0] * (1 - t) + c2[0] * t),
        int(c1[1] * (1 - t) + c2[1] * t),
        int(c1[2] * (1 - t) + c2[2] * t),
    )


def _alpha_fill(base_img: Image.Image, box, color, alpha=30, radius=0):
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
        alpha_ch = layer.split()[3]
        alpha_ch = Image.composite(alpha_ch, Image.new("L", (w, h), 0), mask)
        layer.putalpha(alpha_ch)
    base_img.paste(layer, (x1, y1), layer)


def _draw_gradient_ring(d, cx, cy, r, width, c1, c2, steps=180):
    for i in range(steps):
        t = i / steps
        a1 = -90 + (i * 360 / steps)
        a2 = -90 + ((i + 1) * 360 / steps)
        col = _lerp_color(c1, c2, t)
        d.arc((cx - r, cy - r, cx + r, cy + r), a1, a2, fill=col, width=width)


def _draw_gradient_border_rect(d, x1, y1, x2, y2, radius, c1, c2, width=2):
    w = x2 - x1
    h = y2 - y1

    for i in range(radius, w - radius):
        t = i / max(w - 1, 1)
        col = _lerp_color(c1, c2, t)
        d.line([(x1 + i, y1), (x1 + i, y1 + width)], fill=col)
        d.line([(x1 + i, y2 - width), (x1 + i, y2)], fill=col)

    for i in range(radius, h - radius):
        d.line([(x1, y1 + i), (x1 + width, y1 + i)], fill=c1)
        d.line([(x2 - width, y1 + i), (x2, y1 + i)], fill=c2)

    d.arc((x1, y1, x1 + 2 * radius, y1 + 2 * radius), 180, 270, fill=c1, width=width)
    d.arc((x2 - 2 * radius, y1, x2, y1 + 2 * radius), 270, 360,
          fill=_lerp_color(c1, c2, 0.95), width=width)
    d.arc((x1, y2 - 2 * radius, x1 + 2 * radius, y2), 90, 180, fill=c1, width=width)
    d.arc((x2 - 2 * radius, y2 - 2 * radius, x2, y2), 0, 90,
          fill=_lerp_color(c1, c2, 0.95), width=width)


def _dashed_rounded_rect(draw, box, radius, color, dash=8, gap=6, width=2):
    x1, y1, x2, y2 = box
    r = radius

    def dash_line(p1, p2):
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

    dash_line((x1 + r, y1), (x2 - r, y1))
    dash_line((x2 - r, y2), (x1 + r, y2))
    dash_line((x1, y1 + r), (x1, y2 - r))
    dash_line((x2, y1 + r), (x2, y2 - r))
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
# РИСОВАЛКИ ЭЛЕМЕНТОВ
# ============================================================
def _draw_stack_panel(img, d, box, radius=24):
    x1, y1, x2, y2 = box
    _alpha_fill(img, (x1 + 12, y1 + 12, x2 + 12, y2 + 12),
                (46, 46, 52), alpha=110, radius=radius)
    _alpha_fill(img, (x1 + 6, y1 + 6, x2 + 6, y2 + 6),
                (46, 46, 52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=2)


def _draw_role_badge(d, img, x, y, w, h, role_key: str):
    has_role = role_key not in ("none", "")
    c1, c2 = ROLE_GRADIENTS.get(role_key, ROLE_GRADIENTS["none"])
    label = ROLE_INFO.get(role_key, ROLE_INFO["none"]).upper()

    if has_role:
        _gradient_box(img, (x, y, x + w, y + h), c1, c2, alpha=25, radius=11)
        _draw_gradient_border_rect(d, x, y, x + w, y + h, 11, c1, c2, width=2)
        text_color = _lerp_color(c1, c2, 0.5)
        icon_code = I_CROWN
    else:
        _dashed_rounded_rect(d, (x, y, x + w, y + h), 11, (51, 51, 51),
                             dash=8, gap=5, width=2)
        text_color = DARK
        icon_code = I_CIRCLE_M

    icon_size = 14
    gap = 9
    tw_ = _tw(d, label, _font(11))
    total_w = icon_size + gap + tw_
    start_x = x + (w - total_w) // 2
    cy = y + h // 2

    _draw_icon(d, start_x + icon_size // 2, cy + 1, icon_code, 13, text_color)
    d.text((start_x + icon_size + gap, cy), label, font=_font(11),
           fill=text_color, anchor="lm")


def _draw_clan_badge(d, img, x, y, w, h, clan: Optional[dict]):
    if not clan:
        _dashed_rounded_rect(d, (x, y, x + w, y + h), 11, (51, 51, 51),
                             dash=8, gap=5, width=2)
        label = "БЕЗ КЛАНА"
        icon_code = I_CIRCLE_M
        text_color = DARK
        icon_size = 14
        gap = 9
        tw_ = _tw(d, label, _font(11))
        total_w = icon_size + gap + tw_
        start_x = x + (w - total_w) // 2
        cy = y + h // 2
        _draw_icon(d, start_x + icon_size // 2, cy + 1, icon_code, 13, text_color)
        d.text((start_x + icon_size + gap, cy), label, font=_font(11),
               fill=text_color, anchor="lm")
        return

    clan_data = next((c for c in CLANS_DATA if c["id"] == clan["id"]), None)

    if clan_data:
        c1 = _hex_to_rgb(clan_data.get("color", 0xb3e1b9))
        c2 = _hex_to_rgb(clan_data.get("color_dark", clan_data.get("color", 0xb3e1b9)))
        _clan_name = clan_data.get("name", "")
        if _clan_name == "Сияние":
            clan_icon = I_STAR
        elif _clan_name == "Мультяшности":
            clan_icon = 0xf11b
        elif _clan_name == "Кристализация":
            clan_icon = I_GEM
        else:
            clan_icon = I_GEM
    else:
        c1 = _hex_to_rgb(clan.get("color", 0xb3e1b9))
        c2 = c1
        clan_icon = I_GEM

    label = clan["name"].upper()

    _gradient_box(img, (x, y, x + w, y + h), c1, c2, alpha=30, radius=11)
    _draw_gradient_border_rect(d, x, y, x + w, y + h, 11, c1, c2, width=2)

    text_color = _lerp_color(c1, c2, 0.5)

    icon_size = 14
    gap = 9
    tw_ = _tw(d, label, _font(11))
    total_w = icon_size + gap + tw_
    start_x = x + (w - total_w) // 2
    cy = y + h // 2

    _draw_icon(d, start_x + icon_size // 2, cy + 1, clan_icon, 13, text_color)
    d.text((start_x + icon_size + gap, cy), label, font=_font(11),
           fill=text_color, anchor="lm")


def _draw_stat(d, x, y, w, h, icon_code, icon_bg, icon_color,
               lbl, val, val_color, val_suffix=None):
    d.rounded_rectangle((x, y, x + w, y + h), radius=16,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

    ib_size = 44
    ib_x = x + 18
    ib_y = y + 16
    d.rounded_rectangle((ib_x, ib_y, ib_x + ib_size, ib_y + ib_size),
                        radius=12, fill=icon_bg + (255,))
    _draw_icon(d, ib_x + ib_size // 2, ib_y + ib_size // 2 + 1,
               icon_code, 19, icon_color)

    lbl_y = ib_y + ib_size + 10
    d.text((x + 18, lbl_y), lbl, font=_font(10), fill=MUTED)

    val_y = lbl_y + 15
    val_f = _font(30)
    val_str = val
    max_val_w = w - 36 - 40
    while _tw(d, val_str, val_f) > max_val_w and val_f.size > 18:
        val_f = _font(val_f.size - 2)
    d.text((x + 18, val_y), val_str, font=val_f, fill=val_color)

    if val_suffix:
        vw = _tw(d, val_str, val_f)
        suffix_y = val_y + val_f.size - 19
        d.text((x + 18 + vw + 7, suffix_y), val_suffix, font=_font(14), fill=MUTED)


def _draw_operation_row(d, x, y, w, h, op: Optional[dict]):
    d.rounded_rectangle((x, y, x + w, y + h), radius=12,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)

    if not op:
        _draw_icon(d, x + 44, y + h // 2, I_CIRCLE_M, 20, DARK)
        d.text((x + 44 + 30, y + h // 2), "—", font=_font(16),
               fill=DARK, anchor="lm")
        return

    amt = op.get("amount", 0)
    reason = op.get("reason", "—") or "—"
    ts = op.get("date", 0)

    is_plus = amt >= 0
    accent = GREEN if is_plus else RED
    accent_bg = GREEN_BG if is_plus else RED_BG
    sign = "+" if is_plus else "−"

    d.rounded_rectangle((x, y, x + 4, y + h), radius=4, fill=accent + (255,))

    op_icon_size = 44
    ib_x = x + 14
    ib_y = y + (h - op_icon_size) // 2
    d.rounded_rectangle((ib_x, ib_y, ib_x + op_icon_size, ib_y + op_icon_size),
                        radius=11, fill=accent_bg + (255,))
    _draw_icon(d, ib_x + op_icon_size // 2, ib_y + op_icon_size // 2 + 1,
               _op_icon(reason), 18, accent)

    text_x = ib_x + op_icon_size + 14
    name_f = _font(15)
    time_f = _font(11)

    amt_str = f"{sign}{abs(int(amt))} DC"
    amt_f = _font(18)
    amt_w = _tw(d, amt_str, amt_f)
    tag_str = "ДОХОД" if is_plus else "РАСХОД"
    tag_f = _font(9)
    tag_w = _tw(d, tag_str, tag_f)
    right_block_w = max(amt_w, tag_w)
    right_x = x + w - 18 - right_block_w

    max_name_w = right_x - 16 - text_x
    name_shown = _ellipsis(d, reason, name_f, max_name_w)
    name_y = y + h // 2 - 18
    d.text((text_x, name_y), name_shown, font=name_f, fill=TEXT_SOFT)

    time_str = _op_time_str(ts).upper()
    d.text((text_x, name_y + 20), time_str, font=time_f, fill=DIM)

    amt_y = y + h // 2 - 20
    d.text((x + w - 18 - amt_w, amt_y), amt_str, font=amt_f, fill=accent)

    tag_color_dim = (accent[0] // 2 + 20, accent[1] // 2 + 20, accent[2] // 2 + 20)
    d.text((x + w - 18 - tag_w, amt_y + 26), tag_str, font=tag_f, fill=tag_color_dim)


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
    if user_id in EXEMPT_USERS:
        role_key = "pka"

    user_name = _sanitize_name(user_name, fallback=f"User {user_id}")

    c1, c2 = ROLE_GRADIENTS.get(role_key, ROLE_GRADIENTS["none"])

    W, H = 1800, 1000
    PAD_X = 56
    PAD_Y = 44

    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=30, fill=CARD_TOP + (255,),
                        outline=CARD_BRD + (255,), width=3)

    # ─── HEADER ───
    hx = PAD_X
    hy = PAD_Y

    logo_size = 54
    d.rounded_rectangle((hx, hy, hx + logo_size, hy + logo_size), radius=14,
                        fill=(58, 58, 64) + (255,))
    _draw_icon(d, hx + logo_size // 2, hy + logo_size // 2 + 1, I_USERS, 26, (232, 232, 236))

    brand_x = hx + logo_size + 18
    d.text((brand_x, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((brand_x + 2, hy + 38), "SHOP & ECOSYSTEM", font=_font(11), fill=MUTED)

    meta_r = W - PAD_X
    lbl = "ПРОФИЛЬ ПОКУПАТЕЛЯ"
    id_str = f"#{user_id}"
    w1 = _tw(d, lbl, _font(11))
    w2 = _tw(d, id_str, _font(20))
    d.text((meta_r - w1, hy + 12), lbl, font=_font(11), fill=MUTED)
    d.text((meta_r - w2, hy + 32), id_str, font=_font(20), fill=TEXT)

    sep_y = hy + logo_size + 16
    d.line((PAD_X, sep_y, W - PAD_X, sep_y), fill=STACK_HDR + (255,), width=2)

    # ─── BODY ───
    body_y = sep_y + 24
    body_h = H - PAD_Y - body_y
    left_w = 400
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = W - PAD_X

    # ═══════════════════════════════════════════════════════
    # ЛЕВАЯ ПАНЕЛЬ
    # ═══════════════════════════════════════════════════════
    _draw_stack_panel(img, d,
                      (left_x1, body_y, left_x2 - 12, body_y + body_h - 12),
                      radius=22)
    lp_x1, lp_y1 = left_x1, body_y
    lp_x2, lp_y2 = left_x2 - 12, body_y + body_h - 12
    lp_cx = (lp_x1 + lp_x2) // 2

    # Заголовок панели
    d.text((lp_cx, lp_y1 + 24), "ПРОФИЛЬ",
           font=_font(11), fill=DIM, anchor="mm")

    # Размеры
    av_size = 150
    ring_width = 5
    badge_w = 290
    badge_h = 42
    badge_gap = 8
    uid_h = 16

    # Высота группы: ава + 2 бейджа + UID
    group_h = av_size + 14 + badge_h + badge_gap + badge_h + 12 + uid_h

    # Группа центрируется в панели (с учётом заголовка сверху)
    avail_top = lp_y1 + 54
    avail_bottom = lp_y2 - 26
    avail_h = avail_bottom - avail_top

    group_start_y = avail_top + max((avail_h - group_h) // 2, 0)

    # --- Аватар ---
    av_x = lp_cx - av_size // 2
    av_y = group_start_y

    av_img = _avatar_img(avatar_bytes, av_size) if avatar_bytes else None
    if av_img:
        _draw_gradient_ring(d, lp_cx, av_y + av_size // 2,
                            av_size // 2 + ring_width // 2,
                            ring_width, c1, c2, steps=240)
        img.paste(av_img, (av_x, av_y), av_img)
    else:
        d.ellipse((av_x, av_y, av_x + av_size, av_y + av_size), fill=(60, 60, 66))
        _draw_icon(d, lp_cx, av_y + av_size // 2 + 2, I_USERS, 60, MUTED)
        _draw_gradient_ring(d, lp_cx, av_y + av_size // 2,
                            av_size // 2 + ring_width // 2,
                            ring_width, c1, c2, steps=240)

    # --- Бейджи ---
    badge_x = lp_cx - badge_w // 2
    role_y = av_y + av_size + 14
    _draw_role_badge(d, img, badge_x, role_y, badge_w, badge_h, role_key)

    clan_y = role_y + badge_h + badge_gap
    clan = None
    if get_user_clan:
        try:
            clan = get_user_clan(user_id)
        except Exception:
            clan = None
    _draw_clan_badge(d, img, badge_x, clan_y, badge_w, badge_h, clan)

    # --- UID ---
    uid_text = f"UID · {user_id}"
    uid_f = _font(11)
    uid_w = _tw(d, uid_text, uid_f)
    uid_y = clan_y + badge_h + 12
    d.text((lp_cx - uid_w // 2, uid_y), uid_text, font=uid_f, fill=MUTED)

    # ═══════════════════════════════════════════════════════
    # ПРАВАЯ ПАНЕЛЬ
    # ═══════════════════════════════════════════════════════
    _draw_stack_panel(img, d,
                      (right_x1, body_y, right_x2 - 12, body_y + body_h - 12),
                      radius=22)
    rp_x1 = right_x1 + 28
    rp_x2 = right_x2 - 12 - 28
    rp_y = body_y + 22

    # Ник
    uname = user_name
    max_w = rp_x2 - rp_x1
    if _tw(d, uname, _font(42)) > max_w:
        uname = _ellipsis(d, uname, _font(42), max_w)
    d.text((rp_x1, rp_y), uname, font=_font(42), fill=TEXT)

    sep2_y = rp_y + 56
    d.line((rp_x1 - 28, sep2_y, rp_x2 + 28, sep2_y),
           fill=STACK_HDR + (255,), width=2)

    # ── Статистика ──
    st_y = sep2_y + 18
    _draw_icon(d, rp_x1 + 6, st_y + 7, I_CHART, 12, SILVER)
    d.text((rp_x1 + 20, st_y), "СТАТИСТИКА", font=_font(10), fill=MUTED)

    stats_y = st_y + 28
    stat_h = 128
    stat_gap = 14
    stat_w = (rp_x2 - rp_x1 - stat_gap * 2) // 3

    days_n = _since_days(joined_at) if joined_at else 0

    _draw_stat(d, rp_x1, stats_y, stat_w, stat_h,
               I_THUMBS, GOLD_BG, GOLD,
               "ОТЗЫВОВ", str(reviews), TEXT)
    _draw_stat(d, rp_x1 + stat_w + stat_gap, stats_y, stat_w, stat_h,
               I_GEM, GREEN_BG, GREEN,
               "БАЛАНС", _fmt(balance), GREEN, val_suffix="DC")
    _draw_stat(d, rp_x1 + (stat_w + stat_gap) * 2, stats_y, stat_w, stat_h,
               I_CLOCK, BLUE_BG, BLUE,
               "ДНЕЙ В КОМЬЮНИТИ", str(days_n), TEXT,
               val_suffix=_fmt_days(days_n).split(" ", 1)[1] if days_n else "")

    # ── Прогресс в клане ──
    cp_title_y = stats_y + stat_h + 18
    _draw_icon(d, rp_x1 + 6, cp_title_y + 7, I_SHIELD, 12, SILVER)
    d.text((rp_x1 + 20, cp_title_y), "ПРОГРЕСС В КЛАНЕ", font=_font(10), fill=MUTED)

    cp_y = cp_title_y + 28
    cp_h = 78

    clan_color = (179, 157, 219)
    if clan:
        clan_data = next((c for c in CLANS_DATA if c["id"] == clan["id"]), None)
        if clan_data:
            clan_color = _hex_to_rgb(clan_data.get("color", 0xb3e1b9))

    d.rounded_rectangle((rp_x1, cp_y, rp_x2, cp_y + cp_h), radius=14,
                        fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    d.rounded_rectangle((rp_x1, cp_y, rp_x1 + 4, cp_y + cp_h), radius=4,
                        fill=clan_color + (255,))

    my_rank = None
    my_contrib = 0
    to_top3 = 0

    if clan:
        try:
            from clan.core import get_clan_top, get_user_contribution
            top_full = get_clan_top(clan["id"], limit=1000)
            my_contrib = get_user_contribution(user_id)
            for idx, t in enumerate(top_full, 1):
                if t["user_id"] == user_id:
                    my_rank = idx
                    break
            if top_full and len(top_full) >= 3 and my_rank and my_rank > 3:
                third_place = top_full[2]["total"]
                to_top3 = max(third_place - my_contrib + 1, 0)
        except Exception as e:
            logger.warning(f"clan progress err: {e}")

    cell_w = (rp_x2 - rp_x1) // 3
    cp_items = [
        ("МЕСТО В КЛАНЕ", f"#{my_rank}" if my_rank else "—", SILVER),
        ("ВКЛАД ЗА СЕЗОН", f"{my_contrib} DC", GREEN),
        ("ДО ТОП-3", f"{to_top3} DC" if to_top3 else "—", BLUE),
    ]

    for idx, (lbl, val, color) in enumerate(cp_items):
        cx = rp_x1 + 16 + idx * cell_w
        cy = cp_y + 14
        d.text((cx, cy), lbl, font=_font(9), fill=MUTED)
        d.text((cx, cy + 16), val, font=_font(20), fill=color)

    # ── Операции ──
    op_title_y = cp_y + cp_h + 18
    _draw_icon(d, rp_x1 + 6, op_title_y + 7, I_ROTATE, 12, SILVER)
    d.text((rp_x1 + 20, op_title_y), "ПОСЛЕДНИЕ ОПЕРАЦИИ", font=_font(10), fill=MUTED)

    ops_y = op_title_y + 28
    ops_bottom = lp_y2 - 22
    ops_area_h = ops_bottom - ops_y
    ops_gap = 8
    op_h = (ops_area_h - ops_gap * 3) // 4

    ops = list((history or [])[-4:])
    while len(ops) < 4:
        ops.insert(0, None)

    for i, op in enumerate(ops[-4:]):
        oy = ops_y + i * (op_h + ops_gap)
        _draw_operation_row(d, rp_x1, oy, rp_x2 - rp_x1, op_h, op)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
