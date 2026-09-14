# -*- coding: utf-8 -*-
"""Карточка профиля 1800x1200 — точная копия HTML-макета Diamond Shop."""

import io
import os
import re
import random
from typing import Optional, List, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from core.utils import ADD_DIR, logger

FONT_BOLD     = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
FONT_FA_SOLID = os.path.join(ADD_DIR, "fa-solid-900.ttf")
FONT_FA_REG   = os.path.join(ADD_DIR, "fa-regular-400.ttf")

_FONT_CACHE = {}
_FA_CACHE   = {}

# ================== FontAwesome коды ==================
IC_USERS        = 0xf0c0
IC_GEM          = 0xf3a5
IC_TROPHY       = 0xf091
IC_STAR         = 0xf005
IC_FIRE         = 0xf06d
IC_CROWN        = 0xf521
IC_ARROW_UP     = 0xf062
IC_CART         = 0xf07a
IC_BOX_OPEN     = 0xf49e
IC_USER_TIE     = 0xf508
IC_PERCENT      = 0xf295
IC_GIFT         = 0xf06b
IC_CLOCK        = 0xf1da
IC_CHECK        = 0xf00c
IC_THUMBS_UP    = 0xf164
IC_PALETTE      = 0xf53f
IC_CIRCLE_CHECK = 0xf058
IC_CIRCLE_PLUS  = 0xf055
IC_USER_SLASH   = 0xf506
IC_CHART        = 0xf201
IC_LOCK         = 0xf023
IC_MEDAL        = 0xf5a2
IC_IMAGE        = 0xf03e
IC_BOLT         = 0xf0e7
IC_ARROW_TREND  = 0xf201

# Пул иконок для рандомной FA-иконки кастомных ролей
ROLE_ICON_POOL = [
    0xf005,  # star
    0xf004,  # heart
    0xf521,  # crown
    0xf3a5,  # gem
    0xf0e7,  # bolt
    0xf06d,  # fire
    0xf135,  # rocket
    0xf544,  # robot
    0xf1b0,  # paw
    0xf6d5,  # dragon
    0xf6be,  # cat
    0xf4ba,  # dove
    0xf52e,  # frog
    0xf4fb,  # user-astronaut
    0xf504,  # user-ninja
    0xf21b,  # user-secret
    0xf6e8,  # hat-wizard
    0xf0d0,  # magic
    0xf810,  # ice-cream
    0xf805,  # hamburger
    0xf4e3,  # wine-glass
    0xf0e9,  # umbrella
    0xf13d,  # anchor
    0xf072,  # plane
    0xf1e2,  # bomb
    0xf52d,  # feather
    0xf54c,  # skull
    0xf186,  # moon
    0xf185,  # sun
    0xf2dc,  # snowflake
    0xf06c,  # leaf
    0xf132,  # shield
    0xf6e2,  # ghost
    0xf1b9,  # car
    0xf21c,  # motorcycle
    0xf206,  # bicycle
    0xf439,  # chess
    0xf43f,  # chess-king
    0xf445,  # chess-queen
    0xf578,  # fish
    0xf6f0,  # horse
]


def _pick_role_icon(role_id: int) -> int:
    """Стабильный рандом: одна и та же роль → одна и та же иконка."""
    return random.Random(int(role_id) & 0xFFFFFFFF).choice(ROLE_ICON_POOL)


# ================== Палитра ==================
BG_DARK          = (10, 10, 12)
PROFILE_BORDER   = (74, 74, 79)
LEFT_BG          = (20, 20, 26)
LEFT_BORDER      = (42, 42, 47)
CARD_LINE        = (34, 34, 34)
INNER_BG         = (15, 15, 20)
INNER_BORDER     = (26, 26, 31)
INNER_BORDER_2   = (42, 42, 47)
TEXT_WHITE       = (255, 255, 255)
TEXT_MUTED       = (136, 136, 136)
TEXT_HINT        = (187, 187, 187)
TEXT_SOFT        = (170, 170, 170)
GREEN            = (46, 204, 113)
GOLD             = (247, 201, 145)
GOLD_DARK        = (174, 121, 17)
BLUE_ACCENT      = (20, 155, 208)
PURPLE           = (216, 142, 223)
RED_NEG          = (255, 107, 107)
EMPTY_TEXT       = (58, 58, 66)
EMPTY_SUB        = (42, 42, 50)

ROLE_STYLES = {
    "none":      {"name": "НЕТ РОЛИ",        "grad": [(136,136,136),(85,85,85)],    "color": (136,136,136)},
    "bronze":    {"name": "BRONZE BUYER",    "grad": [(231,143,103),(209,86,64)],   "color": (231,143,103)},
    "silver":    {"name": "SILVER BUYER",    "grad": [(255,255,255),(151,151,151)], "color": (224,224,224)},
    "gold":      {"name": "GOLD BUYER",      "grad": [(247,201,145),(174,121,17)],  "color": (247,201,145)},
    "diamond":   {"name": "DIAMOND BUYER",   "grad": [(221,240,239),(20,155,208)],  "color": (221,240,239)},
    "emerald":   {"name": "EMERALD BUYER",   "grad": [(239,243,211),(61,158,8)],    "color": (239,243,211)},
    "amethyst":  {"name": "AMETHYST BUYER",  "grad": [(159,193,255),(216,142,223)], "color": (159,193,255)},
    "legendary": {"name": "LEGENDARY BUYER", "grad": [(230,133,133),(197,28,178)],  "color": (230,133,133)},
    "pka":       {"name": "ПОКУПАТЕЛЬ ВЕКА", "grad": [(179,217,255),(212,191,255)], "color": (212,191,255)},
}

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF\U0001F300-\U0001F5FF\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF\U00002700-\U000027BF\U0001F000-\U0001F0FF"
    "\uFE0F\u200D"
    "]+",
    flags=re.UNICODE,
)


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub('', text).strip()


# ================== Утилиты ==================
def _font(size: int):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        f = ImageFont.truetype(FONT_BOLD, size)
    except Exception:
        f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


def _fa(size: int, regular: bool = False):
    key = (size, regular)
    if key in _FA_CACHE:
        return _FA_CACHE[key]
    path = FONT_FA_REG if regular else FONT_FA_SOLID
    f = None
    if os.path.exists(path):
        try:
            f = ImageFont.truetype(path, size)
        except Exception as e:
            logger.warning(f"FA-шрифт {path}: {e}")
    _FA_CACHE[key] = f
    return f


def _icon(draw, cx, cy, code, size, color, regular=False):
    f = _fa(size, regular)
    if f is None:
        return
    try:
        draw.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception:
        pass


def _tw(draw, text, font):
    if not text:
        return 0, 0
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


def _blend(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return (int(c1[0]*(1-t) + c2[0]*t),
            int(c1[1]*(1-t) + c2[1]*t),
            int(c1[2]*(1-t) + c2[2]*t))


def _diag_gradient_3stop(W: int, H: int,
                          c_a, c_b, c_c,
                          stop1: float = 0.0,
                          stop2: float = 0.6,
                          stop3: float = 1.0) -> Image.Image:
    """Диагональный 135° градиент (как linear-gradient(135deg, ...))."""
    SW, SH = 120, 80
    small = Image.new('RGB', (SW, SH))
    spx = small.load()
    denom = (SW + SH - 2) if (SW + SH - 2) > 0 else 1
    for y in range(SH):
        for x in range(SW):
            t = (x + y) / denom
            if t <= stop2:
                tt = (t - stop1) / max(stop2 - stop1, 1e-6)
                c = _blend(c_a, c_b, tt)
            else:
                tt = (t - stop2) / max(stop3 - stop2, 1e-6)
                c = _blend(c_b, c_c, tt)
            spx[x, y] = c
    return small.resize((W, H), Image.BILINEAR)


def _linear_gradient(width: int, height: int, c1, c2, horizontal=True) -> Image.Image:
    if width <= 0 or height <= 0:
        return Image.new('RGB', (max(width, 1), max(height, 1)), c1)
    if horizontal:
        grad = Image.new('RGB', (max(width, 1), 1))
        px = grad.load()
        for x in range(max(width, 1)):
            t = x / max(width - 1, 1)
            px[x, 0] = _blend(c1, c2, t)
        return grad.resize((width, height), Image.NEAREST)
    else:
        grad = Image.new('RGB', (1, max(height, 1)))
        px = grad.load()
        for y in range(max(height, 1)):
            t = y / max(height - 1, 1)
            px[0, y] = _blend(c1, c2, t)
        return grad.resize((width, height), Image.NEAREST)


def _paste_gradient_rect(base, box, radius, c1, c2, horizontal=True):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return
    grad = _linear_gradient(w, h, c1, c2, horizontal)
    if radius > 0:
        mask = Image.new('L', (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w-1, h-1), radius=radius, fill=255)
    else:
        mask = Image.new('L', (w, h), 255)
    base.paste(grad, (x1, y1), mask)


def _radial_glow(base: Image.Image, cx: int, cy: int, radius: int,
                 color: Tuple[int, int, int], max_alpha: int = 50):
    if radius <= 0:
        return
    scale = 4
    small = max(radius * 2 // scale, 8)
    overlay = Image.new('RGBA', (small, small), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    steps = 24
    c = small // 2
    for i in range(steps):
        r = int(c * (1 - i / steps))
        if r <= 0:
            break
        t = i / steps
        alpha = int(max_alpha * (t ** 2))
        od.ellipse((c - r, c - r, c + r, c + r), fill=(*color, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(4))
    overlay = overlay.resize((radius * 2, radius * 2), Image.BILINEAR)
    base.alpha_composite(overlay, (cx - radius, cy - radius))


def _avatar_circle(avatar_bytes: Optional[bytes], size: int) -> Optional[Image.Image]:
    if not avatar_bytes:
        return None
    try:
        src = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        w, h = src.size
        s = min(w, h)
        src = src.crop(((w-s)//2, (h-s)//2, (w+s)//2, (h+s)//2))
        return src.resize((size, size), Image.LANCZOS)
    except Exception as e:
        logger.warning(f"Avatar: {e}")
        return None


def _paste_avatar(base, avatar, x, y, size, border_color, border_w=5):
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size-1, size-1), fill=255)
    if avatar is not None:
        base.paste(avatar, (x, y), mask)
    else:
        tmp = Image.new('RGBA', (size, size), (50, 50, 55, 255))
        base.paste(tmp, (x, y), mask)
    d = ImageDraw.Draw(base)
    d.ellipse((x, y, x + size - 1, y + size - 1), outline=border_color, width=border_w)


def _dashed_rect(draw, box, radius, color, width=1, dash=10, gap=8):
    """Пунктирный rounded-rect — рисует по краям, без радиусов (упрощённо)."""
    x1, y1, x2, y2 = box
    # верх
    x = x1
    while x < x2:
        draw.line([(x, y1), (min(x + dash, x2), y1)], fill=color, width=width)
        x += dash + gap
    # низ
    x = x1
    while x < x2:
        draw.line([(x, y2), (min(x + dash, x2), y2)], fill=color, width=width)
        x += dash + gap
    # лево
    y = y1
    while y < y2:
        draw.line([(x1, y), (x1, min(y + dash, y2))], fill=color, width=width)
        y += dash + gap
    # право
    y = y1
    while y < y2:
        draw.line([(x2, y), (x2, min(y + dash, y2))], fill=color, width=width)
        y += dash + gap


# ============================================================
# ОСНОВНАЯ ГЕНЕРАЦИЯ
# ============================================================
def generate_profile_card(
    user_name: str,
    user_id: int,
    avatar_bytes: Optional[bytes],
    role_key: str,
    reviews: int,
    next_role_name: str,
    progress_pct: int,
    progress_text: str,
    balance: int,
    total_earned: int,
    earned_month: int,
    spent_month: int,
    purchases_count: int,
    streak: int,
    inventory: List[Dict],
    history: List[Dict],
    custom_roles: List[Dict],
) -> io.BytesIO:

    W, H = 1800, 1200
    style = ROLE_STYLES.get(role_key, ROLE_STYLES["none"])
    role_color = style["color"]
    grad_c1, grad_c2 = style["grad"]

    # ============ ФОН 135° ============
    bg = _diag_gradient_3stop(W, H, (26, 26, 31), (14, 14, 16), (20, 20, 26), 0.0, 0.6, 1.0)
    bg = bg.convert("RGBA")

    # Внешний радиальный glow (role-glow)
    _radial_glow(bg, int(W * 0.83), int(H * 0.20), 630, role_color, max_alpha=45)
    _radial_glow(bg, int(W * 0.18), int(H * 0.83), 570, (46, 204, 113), max_alpha=20)

    draw = ImageDraw.Draw(bg)

    # ============ КОНТЕЙНЕР PROFILE (весь кадр) ============
    M = 8
    PROF_R = 27
    PROF_BORDER = 3
    PROF_PAD_X = 27
    PROF_PAD_Y = 21

    draw.rounded_rectangle(
        (M, M, W - M, H - M),
        radius=PROF_R,
        outline=PROFILE_BORDER + (255,),
        width=PROF_BORDER
    )
    draw = ImageDraw.Draw(bg)

    # Внутренняя область
    PX1 = M + PROF_BORDER + PROF_PAD_X
    PY1 = M + PROF_BORDER + PROF_PAD_Y
    PX2 = W - M - PROF_BORDER - PROF_PAD_X
    PY2 = H - M - PROF_BORDER - PROF_PAD_Y

    # ============ HEADER ============
    HP = 0
    # logo-icon 78×78
    LOGO_S = 78
    logo_x = PX1
    logo_y = PY1
    draw.rounded_rectangle(
        (logo_x, logo_y, logo_x + LOGO_S, logo_y + LOGO_S),
        radius=18, fill=(74, 74, 79, 255)
    )
    _icon(draw, logo_x + LOGO_S // 2, logo_y + LOGO_S // 2 + 2, IC_USERS, 42, (224, 224, 224))

    # logo-text
    lt_x = logo_x + LOGO_S + 21
    draw.text((lt_x, logo_y + 6), "DIAMOND", font=_font(40), fill=TEXT_WHITE)
    draw.text((lt_x, logo_y + 56), "SHOP & ECOSYSTEM", font=_font(16), fill=TEXT_MUTED)

    # Правый блок
    lbl_txt = "ПРОФИЛЬ ПОКУПАТЕЛЯ"
    lbl_w, _ = _tw(draw, lbl_txt, _font(18))
    draw.text((PX2 - lbl_w, logo_y + 14), lbl_txt, font=_font(18), fill=TEXT_MUTED)
    role_name_top = style["name"]
    rv_w, _ = _tw(draw, role_name_top, _font(26))
    draw.text((PX2 - rv_w, logo_y + 44), role_name_top, font=_font(26), fill=TEXT_WHITE)

    # ============ MAIN GRID ============
    MAIN_Y1 = logo_y + LOGO_S + 18
    MAIN_Y2 = PY2
    MAIN_X1 = PX1
    MAIN_X2 = PX2

    MAIN_W = MAIN_X2 - MAIN_X1
    GAP = 15
    # ratio 1 : 1.5
    unit = (MAIN_W - GAP) / 2.5
    LEFT_W = int(unit)
    RIGHT_W = MAIN_W - GAP - LEFT_W

    LEFT_X1 = MAIN_X1
    LEFT_X2 = LEFT_X1 + LEFT_W
    RIGHT_X1 = LEFT_X2 + GAP
    RIGHT_X2 = MAIN_X2

    # =====================================================
    # LEFT COLUMN
    # =====================================================
    L_R = 24
    L_BORDER = 2
    L_PAD_X = 24
    L_PAD_Y = 18
    L_GAP = 15

    draw.rounded_rectangle(
        (LEFT_X1, MAIN_Y1, LEFT_X2, MAIN_Y2), radius=L_R,
        fill=LEFT_BG + (255,), outline=LEFT_BORDER + (255,), width=L_BORDER
    )
    # Верхняя градиентная полоса (role-gradient)
    _paste_gradient_rect(bg,
        (LEFT_X1 + L_BORDER, MAIN_Y1 + L_BORDER,
         LEFT_X2 - L_BORDER, MAIN_Y1 + L_BORDER + 6),
        3, grad_c1, grad_c2)
    draw = ImageDraw.Draw(bg)

    LX1 = LEFT_X1 + L_PAD_X
    LX2 = LEFT_X2 - L_PAD_X
    LY = MAIN_Y1 + L_PAD_Y

    # ---- profile-top ----
    AV_SIZE = 144
    _paste_avatar(bg, _avatar_circle(avatar_bytes, AV_SIZE), LX1, LY + 12, AV_SIZE,
                  role_color, border_w=5)

    # online dot
    dot = 30
    dx_ = LX1 + AV_SIZE - dot + 8
    dy_ = LY + 12 + AV_SIZE - dot + 8
    draw.ellipse((dx_, dy_, dx_ + dot, dy_ + dot),
                 fill=GREEN + (255,), outline=LEFT_BG + (255,), width=5)

    # Инфо справа от аватара
    IX = LX1 + AV_SIZE + 21
    # username
    draw.text((IX, LY + 18), user_name[:22], font=_font(39), fill=TEXT_WHITE)
    # user-tag
    draw.text((IX, LY + 74), f"ID: {user_id}", font=_font(21), fill=TEXT_MUTED)

    # role-badge
    badge_text = style["name"]
    bw, bh = _tw(draw, badge_text, _font(20))
    bx1 = IX
    by1 = LY + 118
    by2 = by1 + 42
    bx2 = bx1 + bw + 42
    badge_bg = (*_blend(role_color, LEFT_BG, 0.85), 255)
    draw.rounded_rectangle((bx1, by1, bx2, by2), radius=14,
                           fill=badge_bg, outline=role_color + (255,), width=2)
    draw.text((bx1 + 21, by1 + 10), badge_text, font=_font(20), fill=role_color)

    # Разделитель под profile-top
    DIV_Y = LY + 12 + AV_SIZE + 15
    draw.line((LX1, DIV_Y, LX2, DIV_Y), fill=CARD_LINE + (255,), width=2)

    LY = DIV_Y + L_GAP

    # ---- progress block ----
    draw.text((LX1, LY), f"До {next_role_name}", font=_font(21), fill=TEXT_MUTED)
    pct_str = f"{progress_pct}%"
    pw, _ = _tw(draw, pct_str, _font(21))
    draw.text((LX2 - pw, LY), pct_str, font=_font(21), fill=TEXT_WHITE)

    PT_Y = LY + 32
    PT_H = 26
    # track
    draw.rounded_rectangle((LX1, PT_Y, LX2, PT_Y + PT_H), radius=13,
                           fill=(22, 22, 26, 255),
                           outline=(255, 255, 255, 20), width=2)
    if progress_pct > 0:
        fill_w = int((LX2 - LX1 - 6) * progress_pct / 100)
        fill_w = max(fill_w, 6)
        _paste_gradient_rect(bg,
            (LX1 + 3, PT_Y + 3, LX1 + 3 + fill_w, PT_Y + PT_H - 3),
            11, grad_c1, grad_c2)
        draw = ImageDraw.Draw(bg)

    # hint
    _icon(draw, LX1 + 12, PT_Y + PT_H + 24, IC_ARROW_UP, 20, TEXT_MUTED)
    draw.text((LX1 + 34, PT_Y + PT_H + 12), progress_text, font=_font(21), fill=TEXT_HINT)

    LY = PT_Y + PT_H + 46

    # ---- section-label: КАСТОМНЫЕ РОЛИ ----
    _icon(draw, LX1 + 12, LY + 12, IC_PALETTE, 20, TEXT_MUTED)
    draw.text((LX1 + 34, LY), "КАСТОМНЫЕ РОЛИ", font=_font(21), fill=TEXT_MUTED)
    count_str = str(len(custom_roles))
    cw, _ = _tw(draw, count_str, _font(21))
    draw.text((LX2 - cw, LY), count_str, font=_font(21), fill=BLUE_ACCENT)

    LY += 32

    # ---- ms-grid резерв (2 карточки снизу) ----
    MS_H = 108
    MS_Y1 = MAIN_Y2 - L_PAD_Y - MS_H
    ROLES_BOTTOM = MS_Y1 - L_GAP

    # ---- custom roles list ----
    if custom_roles:
        row_h = 58
        row_gap = 9
        avail_h = ROLES_BOTTOM - LY
        max_rows = max(avail_h // (row_h + row_gap), 1)
        shown = custom_roles[:max_rows]

        for i, r in enumerate(shown):
            ry1 = LY + i * (row_h + row_gap)
            ry2 = ry1 + row_h
            rc = r.get("color", (20, 155, 208))
            draw.rounded_rectangle((LX1, ry1, LX2, ry2), radius=15,
                                   fill=INNER_BG + (255,),
                                   outline=LEFT_BORDER + (255,), width=2)
            # цветная полоса слева (::before)
            draw.rectangle((LX1 + 2, ry1 + 4, LX1 + 8, ry2 - 4), fill=rc)

            # FA-иконка (рандомная, стабильная)
            role_id = r.get("id", 0)
            icon_code = _pick_role_icon(role_id)
            icon_box_size = 30
            ibx = LX1 + 22
            iby = ry1 + row_h // 2 - icon_box_size // 2
            draw.rounded_rectangle(
                (ibx, iby, ibx + icon_box_size, iby + icon_box_size),
                radius=6, fill=(26, 26, 32, 255)
            )
            _icon(draw, ibx + icon_box_size // 2, iby + icon_box_size // 2 + 1,
                  icon_code, 20, rc)

            # name
            rname = _strip_emoji(r.get("name", ""))[:26] or "—"
            draw.text((ibx + icon_box_size + 14, ry1 + row_h // 2 - 12),
                      rname, font=_font(24), fill=TEXT_WHITE)

            # pos
            pos_str = r.get("pos", "")
            if pos_str:
                pw2, _ = _tw(draw, pos_str, _font(23))
                draw.text((LX2 - 18 - pw2, ry1 + row_h // 2 - 12),
                          pos_str, font=_font(23), fill=TEXT_MUTED)
    else:
        eh = ROLES_BOTTOM - LY
        if eh > 80:
            _dashed_rect(draw, (LX1, LY, LX2, LY + eh), 18,
                         (34, 34, 34, 255), width=2, dash=14, gap=10)
            ecx = (LX1 + LX2) // 2
            ecy = LY + eh // 2 - 30
            _icon(draw, ecx, ecy, IC_USER_SLASH, 72, (42, 42, 47))
            et = "НЕТУ КАСТОМНЫХ РОЛЕЙ"
            etw, _ = _tw(draw, et, _font(24))
            draw.text((ecx - etw // 2, ecy + 52), et, font=_font(24), fill=EMPTY_TEXT)
            sub = "Приобретите в магазине"
            stw, _ = _tw(draw, sub, _font(20))
            draw.text((ecx - stw // 2, ecy + 88), sub, font=_font(20), fill=EMPTY_SUB)

    # ---- ms-grid (2 карточки) ----
    ms_gap = 12
    ms_w = (LX2 - LX1 - ms_gap) // 2

    # Отзывы
    mx1 = LX1
    mx2 = mx1 + ms_w
    draw.rounded_rectangle((mx1, MS_Y1, mx2, MS_Y1 + MS_H), radius=18,
                           fill=INNER_BG + (255,),
                           outline=LEFT_BORDER + (255,), width=2)
    _icon(draw, mx1 + 24, MS_Y1 + 36, IC_THUMBS_UP, 22, TEXT_MUTED)
    draw.text((mx1 + 50, MS_Y1 + 24), "ОТЗЫВЫ", font=_font(18), fill=TEXT_MUTED)
    draw.text((mx1 + 24, MS_Y1 + 54), str(reviews), font=_font(42), fill=BLUE_ACCENT)

    # Покупки
    mx1 = mx2 + ms_gap
    mx2 = LX2
    draw.rounded_rectangle((mx1, MS_Y1, mx2, MS_Y1 + MS_H), radius=18,
                           fill=INNER_BG + (255,),
                           outline=LEFT_BORDER + (255,), width=2)
    _icon(draw, mx1 + 24, MS_Y1 + 36, IC_CHECK, 22, TEXT_MUTED)
    draw.text((mx1 + 50, MS_Y1 + 24), "ПОКУПКИ", font=_font(18), fill=TEXT_MUTED)
    draw.text((mx1 + 24, MS_Y1 + 54), str(purchases_count), font=_font(42), fill=GREEN)

    # =====================================================
    # RIGHT COLUMN
    # =====================================================
    R_PAD_X = 24
    R_PAD_Y = 18
    RX1 = RIGHT_X1 + R_PAD_X
    RX2 = RIGHT_X2 - R_PAD_X
    RY = MAIN_Y1 + R_PAD_Y

    # ---- Рассчитываем высоты ----
    # inventory: title + 3 ячейки
    INV_ROW_H = 96
    INV_H = 17 + 33 + INV_ROW_H + 17   # ~163
    # history: title + 3 строки
    HIST_ROW_H = 36
    HIST_H = 17 + 33 + HIST_ROW_H * 3 + 17  # ~175
    GAP_R = 12

    TOTAL_INNER_H = MAIN_Y2 - R_PAD_Y - RY
    PDC_H = TOTAL_INNER_H - INV_H - HIST_H - 2 * GAP_R

    # ---------- personal-dc ----------
    # градиент 135° от #14141a к #0f0f14
    pdc_bg = _diag_gradient_3stop(RX2 - RX1, PDC_H,
                                   (20, 20, 26), (15, 15, 20), (20, 20, 26),
                                   0.0, 0.55, 1.0)
    pdc_bg = pdc_bg.convert("RGBA")
    # маска rounded
    pdc_mask = Image.new('L', (RX2 - RX1, PDC_H), 0)
    ImageDraw.Draw(pdc_mask).rounded_rectangle(
        (0, 0, RX2 - RX1 - 1, PDC_H - 1), radius=24, fill=255)
    bg.paste(pdc_bg, (RX1, RY), pdc_mask)
    draw = ImageDraw.Draw(bg)
    # обводка
    draw.rounded_rectangle((RX1, RY, RX2, RY + PDC_H), radius=24,
                           outline=LEFT_BORDER + (255,), width=2)
    # gold-top полоса
    _paste_gradient_rect(bg, (RX1 + 3, RY + 3, RX2 - 3, RY + 9),
                         3, GOLD, GOLD_DARK)
    draw = ImageDraw.Draw(bg)

    # top-title
    px_l = RX1 + 24
    px_r = RX2 - 24
    ph_y = RY + 18
    _icon(draw, px_l + 12, ph_y + 12, IC_CHART, 22, TEXT_MUTED)
    draw.text((px_l + 36, ph_y), "СТАТИСТИКА DC", font=_font(21), fill=TEXT_MUTED)
    sub_str = f"@{user_name}"
    sw_, _ = _tw(draw, sub_str, _font(21))
    draw.text((px_r - sw_, ph_y), sub_str, font=_font(21), fill=GOLD)

    # 4 строки
    rows_y1 = ph_y + 40
    rows_y2 = RY + PDC_H - 20
    rh = (rows_y2 - rows_y1) // 4
    row_data = [
        ("Заработано за всё время", f"{total_earned}", "DC", IC_CROWN, True),
        ("Текущий баланс",         f"{balance}",      "DC", IC_GEM,   False),
        ("Заработано за месяц",    f"{earned_month}", "DC", IC_ARROW_TREND, False),
        ("Потрачено за месяц",     f"{spent_month}",  "DC", IC_CART,  False),
    ]
    for i, (lbl, val, unit, code, is_top) in enumerate(row_data):
        ry_1 = rows_y1 + i * (rh + 9)
        ry_2 = ry_1 + rh
        if is_top:
            row_bg = (26, 24, 20, 255)
            row_br = (95, 78, 35, 255)
        else:
            row_bg = INNER_BG + (255,)
            row_br = INNER_BORDER + (255,)
        draw.rounded_rectangle((px_l, ry_1, px_r, ry_2), radius=18,
                               fill=row_bg, outline=row_br, width=2)

        icon_box = 54
        ibx = px_l + 21
        iby = ry_1 + (rh - icon_box) // 2
        if is_top:
            _paste_gradient_rect(bg, (ibx, iby, ibx + icon_box, iby + icon_box),
                                 15, GOLD, GOLD_DARK)
            draw = ImageDraw.Draw(bg)
            _icon(draw, ibx + icon_box // 2, iby + icon_box // 2 + 1,
                  code, 28, (0, 0, 0))
        else:
            draw.rounded_rectangle((ibx, iby, ibx + icon_box, iby + icon_box),
                                   radius=15,
                                   fill=(26, 26, 32, 255),
                                   outline=(60, 48, 20, 255), width=2)
            _icon(draw, ibx + icon_box // 2, iby + icon_box // 2 + 1,
                  code, 28, GOLD)

        lbl_col = TEXT_WHITE if is_top else TEXT_SOFT
        draw.text((ibx + icon_box + 18, ry_1 + (rh - 24) // 2 - 2),
                  lbl, font=_font(24), fill=lbl_col)

        val_str = f"{val} {unit}".strip()
        vfont = _font(36) if is_top else _font(32)
        vw, _ = _tw(draw, val_str, vfont)
        v_col = TEXT_WHITE if is_top else GOLD
        draw.text((px_r - 21 - vw, ry_1 + (rh - 32) // 2 - 2),
                  val_str, font=vfont, fill=v_col)

    RY += PDC_H + GAP_R

    # ---------- inventory ----------
    draw.rounded_rectangle((RX1, RY, RX2, RY + INV_H), radius=24,
                           fill=LEFT_BG + (255,),
                           outline=LEFT_BORDER + (255,), width=2)

    ix_l = RX1 + 24
    ix_r = RX2 - 24
    ih_y = RY + 17
    _icon(draw, ix_l + 12, ih_y + 12, IC_BOX_OPEN, 22, TEXT_MUTED)
    draw.text((ix_l + 36, ih_y), "ИНВЕНТАРЬ", font=_font(21), fill=TEXT_MUTED)

    inv_total = len(inventory)
    if inv_total > 3:
        extra = f"+{inv_total - 3} ещё"
        ew, _ = _tw(draw, extra, _font(21))
        _icon(draw, ix_r - ew - 26, ih_y + 12, IC_CIRCLE_PLUS, 20, GREEN)
        draw.text((ix_r - ew, ih_y), extra, font=_font(21), fill=GREEN)
    elif inv_total > 0:
        t = f"всего {inv_total}"
        tw2, _ = _tw(draw, t, _font(21))
        draw.text((ix_r - tw2, ih_y), t, font=_font(21), fill=GREEN)

    shown_inv = inventory[:3]
    ic_y1 = ih_y + 33
    ic_y2 = RY + INV_H - 17
    inv_gap = 12
    inv_w = (ix_r - ix_l - 2 * inv_gap) // 3
    for i in range(3):
        cx1 = ix_l + i * (inv_w + inv_gap)
        cx2 = cx1 + inv_w
        filled = i < len(shown_inv)
        if filled:
            item = shown_inv[i]
            accent = item.get("accent", BLUE_ACCENT)
            draw.rounded_rectangle((cx1, ic_y1, cx2, ic_y2), radius=17,
                                   fill=(13, 15, 14, 255),
                                   outline=(40, 70, 50, 255), width=2)
        else:
            draw.rounded_rectangle((cx1, ic_y1, cx2, ic_y2), radius=17,
                                   fill=INNER_BG + (255,),
                                   outline=LEFT_BORDER + (255,), width=2)

        if filled:
            item = shown_inv[i]
            accent = item.get("accent", BLUE_ACCENT)
            icon_box = 66
            ibx = cx1 + 21
            iby = ic_y1 + (ic_y2 - ic_y1 - icon_box) // 2
            draw.rounded_rectangle((ibx, iby, ibx + icon_box, iby + icon_box),
                                   radius=17,
                                   fill=(255, 255, 255, 10),
                                   outline=(255, 255, 255, 16), width=2)
            _icon(draw, ibx + icon_box // 2, iby + icon_box // 2 + 1,
                  item.get("icon", IC_GEM), 30, accent)

            iname = _strip_emoji(item.get("name", ""))[:16]
            bx = ibx + icon_box + 18
            draw.text((bx, ic_y1 + 26), iname, font=_font(24), fill=TEXT_WHITE)
            iq = item.get("qty", "")
            if iq:
                draw.text((bx, ic_y1 + 56), iq, font=_font(18), fill=TEXT_MUTED)

    RY += INV_H + GAP_R

    # ---------- history ----------
    draw.rounded_rectangle((RX1, RY, RX2, RY + HIST_H), radius=24,
                           fill=LEFT_BG + (255,),
                           outline=LEFT_BORDER + (255,), width=2)

    hx_l = RX1 + 24
    hx_r = RX2 - 24
    hh_y = RY + 17
    _icon(draw, hx_l + 12, hh_y + 12, IC_CLOCK, 22, TEXT_MUTED)
    draw.text((hx_l + 36, hh_y), "ПОСЛЕДНИЕ ОПЕРАЦИИ", font=_font(21), fill=TEXT_MUTED)

    hist_shown = history[:6]
    col_w = (hx_r - hx_l - 33) // 2
    row_start = hh_y + 42
    row_h = HIST_ROW_H

    for i, h in enumerate(hist_shown):
        col = i % 2
        row = i // 2
        hx1 = hx_l + col * (col_w + 33)
        hy_1 = row_start + row * row_h

        draw.text((hx1, hy_1 + row_h // 2 - 14), h.get("date", ""),
                  font=_font(23), fill=TEXT_MUTED)

        amt = h.get("amount", 0)
        if amt >= 0:
            amt_str = f"+{amt} DC"
            colr = GREEN
        else:
            amt_str = f"−{abs(amt)} DC"
            colr = RED_NEG
        aw2, _ = _tw(draw, amt_str, _font(24))
        draw.text((hx1 + col_w - aw2, hy_1 + row_h // 2 - 14),
                  amt_str, font=_font(24), fill=colr)
        if row < 2:
            draw.line((hx1, hy_1 + row_h - 4, hx1 + col_w, hy_1 + row_h - 4),
                      fill=(26, 26, 31, 255), width=2)

    # ---------- Финал ----------
    final = bg.convert("RGB")
    buf = io.BytesIO()
    final.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    logger.info("Profile card generated for user %s", user_id)
    return buf


def generate_profile_id() -> str:
    import time
    return f"P-{int(time.time())}-{random.randint(100, 999)}"
