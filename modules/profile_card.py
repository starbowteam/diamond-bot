# -*- coding: utf-8 -*-
"""Генерация карточки профиля 1800x1200 в стиле HTML-макета Diamond Shop."""
import io
import os
import re
from typing import Optional, List, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from core.utils import ADD_DIR, logger

FONT_BOLD     = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
FONT_FA_SOLID = os.path.join(ADD_DIR, "fa-solid-900.ttf")
FONT_FA_REG   = os.path.join(ADD_DIR, "fa-regular-400.ttf")

_FONT_CACHE = {}
_FA_CACHE   = {}

# ---- FontAwesome коды (совместимы с FA 5/6) ----
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

# ---- Палитра ----
BG_DARK          = (10, 10, 12)
CONTAINER_BG     = (14, 14, 18)
CONTAINER_BORDER = (58, 58, 63)
CARD_BG          = (20, 20, 26)
CARD_BORDER      = (42, 42, 47)
INNER_BG         = (15, 15, 20)
INNER_BORDER     = (26, 26, 31)
TEXT_WHITE       = (255, 255, 255)
TEXT_MUTED       = (136, 136, 136)
TEXT_HINT        = (187, 187, 187)
GREEN            = (46, 204, 113)
GOLD             = (247, 201, 145)
GOLD_DARK        = (174, 121, 17)
BLUE_ACCENT      = (20, 155, 208)
PURPLE           = (216, 142, 223)
RED_NEG          = (255, 107, 107)

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


# ---------- Утилиты ----------
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
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]

def _blend(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return (int(c1[0]*(1-t) + c2[0]*t),
            int(c1[1]*(1-t) + c2[1]*t),
            int(c1[2]*(1-t) + c2[2]*t))

def _linear_gradient(width: int, height: int, c1, c2, horizontal=True) -> Image.Image:
    if width <= 0 or height <= 0:
        return Image.new('RGB', (max(width, 1), max(height, 1)), c1)
    if horizontal:
        grad = Image.new('RGB', (width, 1))
        px = grad.load()
        for x in range(width):
            t = x / max(width - 1, 1)
            px[x, 0] = _blend(c1, c2, t)
        return grad.resize((width, height), Image.NEAREST)
    else:
        grad = Image.new('RGB', (1, height))
        px = grad.load()
        for y in range(height):
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
                 color: Tuple[int,int,int], max_alpha: int = 50):
    if radius <= 0:
        return
    scale = 4
    small = max(radius * 2 // scale, 8)
    overlay = Image.new('RGBA', (small, small), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    steps = 30
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

    # ---- Фон ----
    bg = Image.new("RGBA", (W, H), (*BG_DARK, 255))
    _radial_glow(bg, W - 320, 180, 520, role_color, max_alpha=48)
    _radial_glow(bg, 260, H - 200, 420, (46, 204, 113), max_alpha=22)

    draw = ImageDraw.Draw(bg)

    # ---- Контейнер ----
    M = 14
    draw.rounded_rectangle((M, M, W-M, H-M), radius=27,
                           fill=CONTAINER_BG + (255,),
                           outline=CONTAINER_BORDER + (255,), width=3)

    # ---- HEADER ----
    HP = 38
    logo_box = 78
    draw.rounded_rectangle((HP, HP, HP + logo_box, HP + logo_box),
                           radius=18, fill=(74, 74, 79, 255))
    _icon(draw, HP + logo_box // 2, HP + logo_box // 2 + 2, IC_USERS, 42, (224, 224, 224))
    draw.text((HP + logo_box + 22, HP + 6), "DIAMOND", font=_font(40), fill=TEXT_WHITE)
    draw.text((HP + logo_box + 24, HP + 54), "SHOP & ECOSYSTEM", font=_font(16), fill=TEXT_MUTED)

    # Правая часть header
    lbl = "ПРОФИЛЬ ПОКУПАТЕЛЯ"
    lw, _ = _tw(draw, lbl, _font(18))
    draw.text((W - HP - lw, HP + 14), lbl, font=_font(18), fill=TEXT_MUTED)
    rv = style["name"]
    rvw, _ = _tw(draw, rv, _font(26))
    draw.text((W - HP - rvw, HP + 44), rv, font=_font(26), fill=TEXT_WHITE)

    # ---- MAIN GRID ----
    MAIN_Y1 = HP + logo_box + 20   # ~136
    MAIN_Y2 = H - HP               # ~1162
    MAIN_X1 = HP
    MAIN_X2 = W - HP
    MAIN_W  = MAIN_X2 - MAIN_X1

    GAP = 16
    LEFT_W  = int((MAIN_W - GAP) * 0.40)
    RIGHT_W = MAIN_W - GAP - LEFT_W

    LEFT_X1  = MAIN_X1
    LEFT_X2  = LEFT_X1 + LEFT_W
    RIGHT_X1 = LEFT_X2 + GAP
    RIGHT_X2 = MAIN_X2

    # ============ LEFT COLUMN ============
    draw.rounded_rectangle((LEFT_X1, MAIN_Y1, LEFT_X2, MAIN_Y2), radius=24,
                           fill=CARD_BG + (255,), outline=CARD_BORDER + (255,), width=2)
    # Верхняя цветная полоса
    _paste_gradient_rect(bg, (LEFT_X1 + 3, MAIN_Y1 + 3, LEFT_X2 - 3, MAIN_Y1 + 10),
                         3, grad_c1, grad_c2)
    draw = ImageDraw.Draw(bg)

    LP = 26
    LX1 = LEFT_X1 + LP
    LX2 = LEFT_X2 - LP
    LY  = MAIN_Y1 + 22

    # --- Profile Top ---
    AV_SIZE = 144
    _paste_avatar(bg, _avatar_circle(avatar_bytes, AV_SIZE), LX1, LY, AV_SIZE,
                  role_color, border_w=5)

    # Online dot
    dot = 30
    dx_ = LX1 + AV_SIZE - dot + 8
    dy_ = LY + AV_SIZE - dot + 8
    draw.ellipse((dx_, dy_, dx_ + dot, dy_ + dot), fill=GREEN + (255,),
                 outline=INNER_BG + (255,), width=5)

    # Инфо справа
    IX = LX1 + AV_SIZE + 24
    u_name = user_name[:22]
    draw.text((IX, LY + 6), u_name, font=_font(40), fill=TEXT_WHITE)
    draw.text((IX, LY + 60), f"ID: {user_id}", font=_font(21), fill=TEXT_MUTED)

    # Badge
    badge_text = style["name"]
    bw, bh = _tw(draw, badge_text, _font(20))
    bx1 = IX
    by1 = LY + 106
    by2 = by1 + 42
    bx2 = bx1 + bw + 40
    badge_bg = (*_blend(role_color, INNER_BG, 0.85), 255)
    draw.rounded_rectangle((bx1, by1, bx2, by2), radius=12,
                           fill=badge_bg, outline=role_color + (255,), width=2)
    draw.text((bx1 + 20, by1 + 10), badge_text, font=_font(20), fill=role_color)

    LY = MAIN_Y1 + 22 + AV_SIZE + 22

    # --- Progress ---
    draw.text((LX1, LY), f"До {next_role_name}", font=_font(20), fill=TEXT_MUTED)
    pct_str = f"{progress_pct}%"
    pw, _ = _tw(draw, pct_str, _font(20))
    draw.text((LX2 - pw, LY), pct_str, font=_font(20), fill=TEXT_WHITE)

    PT_Y = LY + 34
    PT_H = 24
    draw.rounded_rectangle((LX1, PT_Y, LX2, PT_Y + PT_H), radius=12,
                           fill=(22, 22, 26, 255), outline=INNER_BORDER + (255,), width=1)

    if progress_pct > 0:
        fill_w = int((LX2 - LX1 - 4) * progress_pct / 100)
        fill_w = max(fill_w, 4)
        _paste_gradient_rect(bg, (LX1 + 2, PT_Y + 2, LX1 + 2 + fill_w, PT_Y + PT_H - 2),
                             10, grad_c1, grad_c2)
        draw = ImageDraw.Draw(bg)

    _icon(draw, LX1 + 12, PT_Y + PT_H + 22, IC_ARROW_UP, 20, TEXT_MUTED)
    draw.text((LX1 + 32, PT_Y + PT_H + 10), progress_text, font=_font(20), fill=TEXT_HINT)

    LY = PT_Y + PT_H + 44

    # --- Custom Roles ---
    _icon(draw, LX1 + 12, LY + 10, IC_PALETTE, 20, TEXT_MUTED)
    draw.text((LX1 + 32, LY), "КАСТОМНЫЕ РОЛИ", font=_font(18), fill=TEXT_MUTED)
    count_str = str(len(custom_roles))
    cw, _ = _tw(draw, count_str, _font(20))
    draw.text((LX2 - cw, LY - 2), count_str, font=_font(20), fill=BLUE_ACCENT)

    LY += 34

    # Резерв под мини-статы снизу
    MS_H = 108
    MS_Y1 = MAIN_Y2 - 22 - MS_H
    ROLES_BOTTOM = MS_Y1 - 18

    if custom_roles:
        row_h = 58
        row_gap = 8
        max_rows = max((ROLES_BOTTOM - LY) // (row_h + row_gap), 1)
        shown = custom_roles[:max_rows]
        for i, r in enumerate(shown):
            ry1 = LY + i * (row_h + row_gap)
            ry2 = ry1 + row_h
            rc = r.get("color", (20, 155, 208))
            draw.rounded_rectangle((LX1, ry1, LX2, ry2), radius=12,
                                   fill=INNER_BG + (255,),
                                   outline=INNER_BORDER + (255,), width=1)
            # Цветная полоса слева
            draw.rectangle((LX1 + 1, ry1 + 4, LX1 + 5, ry2 - 4), fill=rc)
            # Точка
            dot_y = ry1 + row_h // 2
            draw.ellipse((LX1 + 20, dot_y - 8, LX1 + 36, dot_y + 8), fill=rc)
            # Имя (эмодзи убраны)
            rname = _strip_emoji(r.get("name", ""))[:32] or "—"
            draw.text((LX1 + 52, ry1 + row_h // 2 - 12), rname, font=_font(23), fill=TEXT_WHITE)
            # Позиция
            pos_str = r.get("pos", "")
            if pos_str:
                pw2, _ = _tw(draw, pos_str, _font(21))
                draw.text((LX2 - 16 - pw2, ry1 + row_h // 2 - 11),
                          pos_str, font=_font(21), fill=TEXT_MUTED)
    else:
        eh = ROLES_BOTTOM - LY
        if eh > 60:
            draw.rounded_rectangle((LX1, LY, LX2, LY + eh), radius=16,
                                   fill=INNER_BG + (255,),
                                   outline=(34, 34, 34, 255), width=2)
            ecx = (LX1 + LX2) // 2
            ecy = LY + eh // 2 - 20
            _icon(draw, ecx, ecy, IC_USER_SLASH, 68, (42, 42, 47))
            et = "НЕТУ КАСТОМНЫХ РОЛЕЙ"
            etw, _ = _tw(draw, et, _font(23))
            draw.text((ecx - etw // 2, ecy + 50), et, font=_font(23), fill=(58, 58, 66))
            sub = "Приобретите в магазине, чтобы они появились здесь"
            stw, _ = _tw(draw, sub, _font(17))
            draw.text((ecx - stw // 2, ecy + 82), sub, font=_font(17), fill=(42, 42, 50))

    # --- Mini stats (2 шт.) ---
    gap = 12
    card_w = (LX2 - LX1 - gap) // 2

    # Отзывы
    c1x1 = LX1
    c1x2 = c1x1 + card_w
    draw.rounded_rectangle((c1x1, MS_Y1, c1x2, MS_Y1 + MS_H), radius=14,
                           fill=INNER_BG + (255,), outline=INNER_BORDER + (255,), width=1)
    _icon(draw, c1x1 + 22, MS_Y1 + 32, IC_THUMBS_UP, 20, TEXT_MUTED)
    draw.text((c1x1 + 42, MS_Y1 + 22), "ОТЗЫВЫ", font=_font(16), fill=TEXT_MUTED)
    draw.text((c1x1 + 22, MS_Y1 + 52), str(reviews), font=_font(44), fill=BLUE_ACCENT)

    # Покупки
    c2x1 = c1x2 + gap
    c2x2 = LX2
    draw.rounded_rectangle((c2x1, MS_Y1, c2x2, MS_Y1 + MS_H), radius=14,
                           fill=INNER_BG + (255,), outline=INNER_BORDER + (255,), width=1)
    _icon(draw, c2x1 + 22, MS_Y1 + 32, IC_CHECK, 20, TEXT_MUTED)
    draw.text((c2x1 + 42, MS_Y1 + 22), "ПОКУПКИ", font=_font(16), fill=TEXT_MUTED)
    draw.text((c2x1 + 22, MS_Y1 + 52), str(purchases_count), font=_font(44), fill=GREEN)

    # ============ RIGHT COLUMN ============
    RP = 24
    RX1 = RIGHT_X1 + RP
    RX2 = RIGHT_X2 - RP
    RY  = MAIN_Y1 + 22

    # --- Stats row (4 карточки) ---
    sw_gap = 12
    sw = (RX2 - RX1 - 3 * sw_gap) // 4
    SH = 108

    stats_data = [
        ("БАЛАНС",   f"{balance}",       "DC",  GREEN,   IC_GEM),
        ("ВСЕГО",    f"{total_earned}",  "",    GOLD,    IC_TROPHY),
        ("ОТЗЫВОВ",  f"{reviews}",       "",    GOLD,    IC_STAR),
        ("СТРИК",    f"{streak}",        "дн",  PURPLE,  IC_FIRE),
    ]
    for i, (lbl, val, unit, accent, code) in enumerate(stats_data):
        sx1 = RX1 + i * (sw + sw_gap)
        sx2 = sx1 + sw
        draw.rounded_rectangle((sx1, RY, sx2, RY + SH), radius=16,
                               fill=CARD_BG + (255,),
                               outline=CARD_BORDER + (255,), width=1)
        # accent line
        draw.rectangle((sx1 + 4, RY + 4, sx2 - 4, RY + 7), fill=accent)
        _icon(draw, sx1 + 22, RY + 30, code, 20, TEXT_MUTED)
        draw.text((sx1 + 44, RY + 20), lbl, font=_font(14), fill=TEXT_MUTED)
        vfont = _font(38)
        draw.text((sx1 + 22, RY + 54), val, font=vfont, fill=TEXT_WHITE)
        if unit:
            vw, _ = _tw(draw, val, vfont)
            draw.text((sx1 + 22 + vw + 6, RY + 70), unit, font=_font(18), fill=TEXT_MUTED)

    RY += SH + 14

    # --- Personal DC ---
    # резервируем место снизу под inventory (240) и history (230)
    INV_H = 240
    HIST_H = 230
    GAP_R = 14
    PDC_H = MAIN_Y2 - 22 - RY - INV_H - HIST_H - 2 * GAP_R

    draw.rounded_rectangle((RX1, RY, RX2, RY + PDC_H), radius=20,
                           fill=INNER_BG + (255,), outline=INNER_BORDER + (255,), width=1)
    _paste_gradient_rect(bg, (RX1 + 3, RY + 3, RX2 - 3, RY + 9), 3, GOLD, GOLD_DARK)
    draw = ImageDraw.Draw(bg)

    PX = RX1 + 26
    PX_R = RX2 - 26
    PH_Y = RY + 22
    _icon(draw, PX + 12, PH_Y + 11, IC_CHART, 20, TEXT_MUTED)
    draw.text((PX + 34, PH_Y), "СТАТИСТИКА DC", font=_font(18), fill=TEXT_MUTED)
    uname_str = f"@{user_name}"
    uw, _ = _tw(draw, uname_str, _font(18))
    draw.text((PX_R - uw, PH_Y), uname_str, font=_font(18), fill=GOLD)

    rows_y1 = PH_Y + 46
    rows_y2 = RY + PDC_H - 20
    rh = (rows_y2 - rows_y1) // 4
    row_data = [
        ("Заработано за всё время", f"{total_earned}", "DC", IC_CROWN, True),
        ("Текущий баланс",         f"{balance}",      "DC", IC_GEM,   False),
        ("Заработано за месяц",    f"{earned_month}", "DC", IC_ARROW_UP, False),
        ("Потрачено за месяц",     f"{spent_month}",  "DC", IC_CART,  False),
    ]
    for i, (lbl, val, unit, code, is_top) in enumerate(row_data):
        ry_1 = rows_y1 + i * rh
        ry_2 = ry_1 + rh - 8
        row_bg = (24, 22, 18, 255) if is_top else INNER_BG + (255,)
        row_br = (95, 78, 35, 255) if is_top else INNER_BORDER + (255,)
        draw.rounded_rectangle((PX, ry_1, PX_R, ry_2), radius=14,
                               fill=row_bg, outline=row_br, width=1)

        icon_bg = GOLD if is_top else (26, 26, 32)
        icon_col = (0, 0, 0) if is_top else GOLD
        ibx = PX + 16
        iby = ry_1 + (rh - 8) // 2 - 22
        draw.rounded_rectangle((ibx, iby, ibx + 46, iby + 46), radius=11,
                               fill=icon_bg, outline=icon_bg if is_top else (36, 36, 42), width=1)
        _icon(draw, ibx + 23, iby + 23, code, 22, icon_col)

        draw.text((ibx + 62, ry_1 + (rh - 8) // 2 - 13), lbl,
                  font=_font(23), fill=TEXT_WHITE if is_top else (170, 170, 170))

        val_str = f"{val} {unit}".strip()
        vfont = _font(30) if is_top else _font(26)
        vw, _ = _tw(draw, val_str, vfont)
        draw.text((PX_R - 22 - vw, ry_1 + (rh - 8) // 2 - 15), val_str,
                  font=vfont, fill=TEXT_WHITE if is_top else GOLD)

    RY += PDC_H + GAP_R

    # --- Inventory ---
    draw.rounded_rectangle((RX1, RY, RX2, RY + INV_H), radius=20,
                           fill=INNER_BG + (255,), outline=INNER_BORDER + (255,), width=1)

    IX = RX1 + 26
    IX_R = RX2 - 26
    IH_Y = RY + 22
    _icon(draw, IX + 12, IH_Y + 11, IC_BOX_OPEN, 20, TEXT_MUTED)
    draw.text((IX + 34, IH_Y), "ИНВЕНТАРЬ", font=_font(18), fill=TEXT_MUTED)

    inv_total = len(inventory)
    if inv_total > 3:
        extra = f"+{inv_total - 3} ещё"
        ew, _ = _tw(draw, extra, _font(18))
        _icon(draw, IX_R - ew - 24, IH_Y + 11, IC_CIRCLE_PLUS, 18, GREEN)
        draw.text((IX_R - ew, IH_Y), extra, font=_font(18), fill=GREEN)
    elif inv_total > 0:
        t = f"всего {inv_total}"
        tw2, _ = _tw(draw, t, _font(18))
        draw.text((IX_R - tw2, IH_Y), t, font=_font(18), fill=GREEN)

    shown_inv = inventory[:3]
    cards_y1 = IH_Y + 40
    cards_y2 = RY + INV_H - 22
    inv_w = (IX_R - IX - 2 * 12) // 3
    for i in range(3):
        cx1 = IX + i * (inv_w + 12)
        cx2 = cx1 + inv_w
        draw.rounded_rectangle((cx1, cards_y1, cx2, cards_y2), radius=14,
                               fill=INNER_BG + (255,),
                               outline=INNER_BORDER + (255,), width=1)
        if i < len(shown_inv):
            it = shown_inv[i]
            accent = it.get("accent", BLUE_ACCENT)
            draw.rectangle((cx1 + 4, cards_y1 + 4, cx1 + 7, cards_y2 - 4), fill=accent)
            icx = cx1 + 22
            icy = cards_y1 + (cards_y2 - cards_y1) // 2 - 22
            draw.rounded_rectangle((icx, icy, icx + 44, icy + 44), radius=11,
                                   fill=(26, 26, 32, 255), outline=(36, 36, 42, 255), width=1)
            _icon(draw, icx + 22, icy + 22, it.get("icon", IC_GEM), 20, accent)
            iname = _strip_emoji(it.get("name", ""))[:18]
            draw.text((icx + 58, cards_y1 + (cards_y2 - cards_y1) // 2 - 22),
                      iname, font=_font(21), fill=TEXT_WHITE)
            iq = it.get("qty", "")
            if iq:
                draw.text((icx + 58, cards_y1 + (cards_y2 - cards_y1) // 2 + 8),
                          iq, font=_font(17), fill=TEXT_MUTED)

    RY += INV_H + GAP_R

    # --- History ---
    draw.rounded_rectangle((RX1, RY, RX2, RY + HIST_H), radius=20,
                           fill=INNER_BG + (255,), outline=INNER_BORDER + (255,), width=1)

    HX = RX1 + 26
    HX_R = RX2 - 26
    HH_Y = RY + 22
    _icon(draw, HX + 12, HH_Y + 11, IC_CLOCK, 20, TEXT_MUTED)
    draw.text((HX + 34, HH_Y), "ПОСЛЕДНИЕ ОПЕРАЦИИ", font=_font(18), fill=TEXT_MUTED)

    hist_shown = history[:6]
    col_w = (HX_R - HX - 40) // 2
    row_start = HH_Y + 42
    row_bottom = RY + HIST_H - 18
    row_h = (row_bottom - row_start) // 3

    for i, h in enumerate(hist_shown):
        col = i % 2
        row = i // 2
        hx1 = HX + col * (col_w + 40)
        hy_1 = row_start + row * row_h
        draw.text((hx1, hy_1 + row_h // 2 - 13), h.get("date", ""),
                  font=_font(21), fill=TEXT_MUTED)
        amt = h.get("amount", 0)
        if amt >= 0:
            amt_str = f"+{amt} DC"
            colr = GREEN
        else:
            amt_str = f"−{abs(amt)} DC"
            colr = RED_NEG
        aw2, _ = _tw(draw, amt_str, _font(23))
        draw.text((hx1 + col_w - aw2, hy_1 + row_h // 2 - 14),
                  amt_str, font=_font(23), fill=colr)
        if row < 2:
            draw.line((hx1, hy_1 + row_h - 4, hx1 + col_w, hy_1 + row_h - 4),
                      fill=(26, 26, 26, 255), width=1)

    # --- Финальный вывод ---
    final = bg.convert("RGB")
    buf = io.BytesIO()
    final.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    logger.info("Profile card generated for user %s", user_id)
    return buf
