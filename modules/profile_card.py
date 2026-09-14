# -*- coding: utf-8 -*-
"""
Генерация карточки профиля через Pillow.
Размер 1800×1200 (3:2) — Discord не обрезает.
"""
import io
import os
from typing import Optional, List, Dict, Tuple

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, logger

FONT_BOLD = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
FONT_FA_SOLID = os.path.join(ADD_DIR, "fa-solid-900.ttf")
FONT_FA_REG = os.path.join(ADD_DIR, "fa-regular-400.ttf")

_FONT_CACHE = {}
_FA_CACHE = {}

# ---- Font Awesome codepoints ----
IC_USERS = 0xf0c0
IC_CART = 0xf07a
IC_USER_TIE = 0xf508
IC_BOX_OPEN = 0xf49e
IC_GEM = 0xf3a5
IC_STAR = 0xf005
IC_FIRE = 0xf06d
IC_TROPHY = 0xf091
IC_THUMBS_UP = 0xf164
IC_CHECK = 0xf00c
IC_CHART = 0xf201
IC_CROWN = 0xf521
IC_TREND_UP = 0xe098
IC_CLOCK = 0xf1da
IC_PALETTE = 0xf53f
IC_USER_SLASH = 0xf506
IC_CIRCLE_CHECK = 0xf058
IC_ARROW_UP = 0xf062
IC_PERCENT = 0xf295
IC_GIFT = 0xf06b
IC_LOCK = 0xf023
IC_CIRCLE_PLUS = 0xf055
IC_BOLT = 0xf0e7
IC_MEDAL = 0xf5a2
IC_IMAGE = 0xf03e


# ---- Стили ролей ----
ROLE_STYLES = {
    "none":      {"name": "НЕТ РОЛИ",         "color": (136, 136, 136), "grad": [(136, 136, 136), (85, 85, 85)]},
    "bronze":    {"name": "BRONZE BUYER",     "color": (231, 143, 103), "grad": [(231, 143, 103), (209, 86, 64)]},
    "silver":    {"name": "SILVER BUYER",     "color": (224, 224, 224), "grad": [(255, 255, 255), (151, 151, 151)]},
    "gold":      {"name": "GOLD BUYER",       "color": (247, 201, 145), "grad": [(247, 201, 145), (174, 121, 17)]},
    "diamond":   {"name": "DIAMOND BUYER",    "color": (221, 240, 239), "grad": [(221, 240, 239), (20, 155, 208)]},
    "emerald":   {"name": "EMERALD BUYER",    "color": (239, 243, 211), "grad": [(239, 243, 211), (61, 158, 8)]},
    "amethyst":  {"name": "AMETHYST BUYER",   "color": (159, 193, 255), "grad": [(159, 193, 255), (216, 142, 223)]},
    "legendary": {"name": "LEGENDARY BUYER",  "color": (230, 133, 133), "grad": [(230, 133, 133), (197, 28, 178)]},
    "pka":       {"name": "ПОКУПАТЕЛЬ ВЕКА",  "color": (212, 191, 255), "grad": [(179, 217, 255), (212, 191, 255)]},
}


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


def _hex_to_rgb(c) -> Tuple[int, int, int]:
    if isinstance(c, tuple):
        return c
    if isinstance(c, int):
        return ((c >> 16) & 0xff, (c >> 8) & 0xff, c & 0xff)
    return (136, 136, 136)


def _blend(c1, c2, t):
    """t=0 → c1, t=1 → c2"""
    return (
        int(c1[0] * (1 - t) + c2[0] * t),
        int(c1[1] * (1 - t) + c2[1] * t),
        int(c1[2] * (1 - t) + c2[2] * t),
    )


def _gradient_bar(draw, x1, y1, x2, y2, c1, c2):
    """Горизонтальный градиент."""
    w = x2 - x1
    if w <= 0:
        return
    for i in range(w):
        t = i / max(w - 1, 1)
        c = _blend(c1, c2, t)
        draw.line((x1 + i, y1, x1 + i, y2), fill=c, width=1)


def _avatar_image(avatar_bytes: Optional[bytes], size: int) -> Optional[Image.Image]:
    if not avatar_bytes:
        return None
    try:
        img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        w, h = img.size
        s = min(w, h)
        img = img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
        img = img.resize((size, size), Image.LANCZOS)
        return img
    except Exception as e:
        logger.warning(f"Avatar load error: {e}")
        return None


def _paste_circle_avatar(base, av, x, y, size, border_color, border_w=3):
    draw = ImageDraw.Draw(base)
    if av is not None:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        base.paste(av, (x, y), mask)
    else:
        draw.ellipse((x, y, x + size, y + size), fill=(50, 50, 55))
    draw.ellipse((x, y, x + size, y + size), outline=border_color, width=border_w)


# ============================================================
# ГЕНЕРАЦИЯ КАРТОЧКИ
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
    BG = (10, 10, 12)
    CARD_TOP = (26, 26, 31)
    CARD_BOT = (20, 20, 26)
    INNER = (20, 20, 26)
    INNER_BORDER = (42, 42, 47)
    BORDER = (74, 74, 79)
    TEXT = (255, 255, 255)
    MUTED = (136, 136, 136)
    GREEN = (46, 204, 113)
    GOLD = (247, 201, 145)
    ROW_BG = (15, 15, 20)
    ROW_BORDER = (26, 26, 31)
    LINE = (34, 34, 34)

    style = ROLE_STYLES.get(role_key, ROLE_STYLES["none"])
    role_color = style["color"]
    grad_c1, grad_c2 = style["grad"]

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Внешний фон (мягкие круги)
    draw.ellipse((W - 520, -280, W + 200, 440), fill=(16, 16, 20))
    draw.ellipse((-280, H - 420, 320, H + 160), fill=(14, 22, 18))

    # Контейнер
    M = 14
    draw.rounded_rectangle((M, M, W - M, H - M), radius=27, fill=CARD_BOT, outline=BORDER, width=3)
    draw.rounded_rectangle((M + 1, M + 1, W - M - 1, H // 2), radius=27, fill=CARD_TOP)

    PAD = 27
    CX_L = M + PAD  # 41
    CX_R = W - M - PAD  # 1759

    # ============ HEADER ============
    hy = M + 21
    logo_size = 78
    draw.rounded_rectangle((CX_L, hy, CX_L + logo_size, hy + logo_size), radius=16, fill=(74, 74, 79))
    _icon(draw, CX_L + logo_size // 2, hy + logo_size // 2 + 2, IC_USERS, 38, (224, 224, 224))

    draw.text((CX_L + logo_size + 18, hy + 4), "DIAMOND", font=_font(36), fill=TEXT)
    draw.text((CX_L + logo_size + 20, hy + 52), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)

    lbl = "ПРОФИЛЬ ПОКУПАТЕЛЯ"
    lw, _ = _tw(draw, lbl, _font(17))
    draw.text((CX_R - lw, hy + 12), lbl, font=_font(17), fill=MUTED)
    rv = style["name"]
    rvw, _ = _tw(draw, rv, _font(24))
    draw.text((CX_R - rvw, hy + 40), rv, font=_font(24), fill=TEXT)

    # ============ MAIN AREA ============
    MAIN_Y = hy + logo_size + 15  # ~ 152
    MAIN_BOTTOM = H - M - PAD  # 1165

    left_x1 = CX_L
    left_x2 = left_x1 + 716
    right_x1 = left_x2 + 15
    right_x2 = CX_R

    # ============ LEFT COLUMN ============
    draw.rounded_rectangle((left_x1, MAIN_Y, left_x2, MAIN_BOTTOM), radius=21, fill=INNER, outline=INNER_BORDER, width=2)

    # Top accent — цветная полоса
    _gradient_bar(draw, left_x1 + 2, MAIN_Y + 2, left_x2 - 2, MAIN_Y + 7, grad_c1, grad_c2)

    LP = 22
    lx = left_x1 + LP
    lx_r = left_x2 - LP
    ly = MAIN_Y + 20

    # --- Profile top ---
    av_size = 144
    av_x = lx
    av_y = ly

    _paste_circle_avatar(img, _avatar_image(avatar_bytes, av_size), av_x, av_y, av_size, role_color, border_w=3)

    # Online dot
    dot_size = 30
    dot_x = av_x + av_size - dot_size + 6
    dot_y = av_y + av_size - dot_size + 6
    draw.ellipse((dot_x, dot_y, dot_x + dot_size, dot_size + dot_y), fill=GREEN, outline=INNER, width=5)

    # Инфо справа от аватара
    ix = av_x + av_size + 22
    draw.text((ix, av_y + 6), user_name[:22], font=_font(38), fill=TEXT)
    draw.text((ix, av_y + 58), f"ID: {user_id}", font=_font(20), fill=MUTED)

    # Бейдж роли
    badge_text = style["name"]
    bw, bh = _tw(draw, badge_text, _font(20))
    bx1 = ix
    by1 = av_y + 100
    by2 = by1 + 40
    bx2 = bx1 + bw + 36
    badge_bg = _blend(role_color, INNER, 0.85)
    draw.rounded_rectangle((bx1, by1, bx2, by2), radius=12, fill=badge_bg, outline=role_color, width=1)
    draw.text((bx1 + 18, by1 + 9), badge_text, font=_font(20), fill=role_color)

    ly = av_y + av_size + 20  # под аватаром

    # --- Progress block ---
    draw.text((lx, ly), f"До {next_role_name}", font=_font(19), fill=MUTED)
    pct_str = f"{progress_pct}%"
    pw, _ = _tw(draw, pct_str, _font(19))
    draw.text((lx_r - pw, ly), pct_str, font=_font(19), fill=TEXT)

    # Track
    pt_y = ly + 32
    pt_h = 26
    draw.rounded_rectangle((lx, pt_y, lx_r, pt_y + pt_h), radius=13, fill=(22, 22, 26), outline=INNER_BORDER, width=1)
    if progress_pct > 0:
        fill_w = int((lx_r - lx - 4) * progress_pct / 100)
        # Градиентная заливка внутри трека
        # Создаём градиент через отдельный слой
        track_img = Image.new("RGB", (max(fill_w, 1), pt_h - 4), grad_c1)
        tdraw = ImageDraw.Draw(track_img)
        for i in range(max(fill_w, 1)):
            t = i / max(fill_w - 1, 1)
            tdraw.line((i, 0, i, pt_h - 4), fill=_blend(grad_c1, grad_c2, t))
        # маска
        mask = Image.new("L", track_img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, track_img.size[0] - 1, track_img.size[1] - 1), radius=11, fill=255)
        img.paste(track_img, (lx + 2, pt_y + 2), mask)
        draw = ImageDraw.Draw(img)

    # Hint
    _icon(draw, lx + 10, pt_y + pt_h + 18, IC_ARROW_UP, 18, MUTED)
    draw.text((lx + 26, pt_y + pt_h + 8), progress_text, font=_font(18), fill=(187, 187, 187))

    ly = pt_y + pt_h + 40

    # --- Custom roles ---
    _icon(draw, lx + 10, ly + 10, IC_PALETTE, 18, MUTED)
    draw.text((lx + 26, ly), "КАСТОМНЫЕ РОЛИ", font=_font(18), fill=MUTED)
    count_str = str(len(custom_roles))
    cw, _ = _tw(draw, count_str, _font(18))
    draw.text((lx_r - cw, ly), count_str, font=_font(18), fill=(20, 155, 208))

    ly += 32

    # Reservce space for mini-stats at bottom (104) + gap (20)
    mini_stats_h = 104
    mini_stats_gap = 20
    custom_roles_bottom = MAIN_BOTTOM - 22 - mini_stats_h - mini_stats_gap

    if custom_roles:
        # Список ролей
        row_h = 60
        row_gap = 6
        max_rows = (custom_roles_bottom - ly) // (row_h + row_gap)
        shown = custom_roles[:max_rows]
        for i, r in enumerate(shown):
            ry1 = ly + i * (row_h + row_gap)
            ry2 = ry1 + row_h
            rcolor = r.get("color", (20, 155, 208))
            draw.rounded_rectangle((lx, ry1, lx_r, ry2), radius=12, fill=ROW_BG, outline=ROW_BORDER, width=1)
            # Цветная полоса слева
            draw.rectangle((lx, ry1 + 4, lx + 5, ry2 - 4), fill=rcolor)
            # Точка
            draw.ellipse((lx + 20, ry1 + row_h // 2 - 8, lx + 36, ry1 + row_h // 2 + 8), fill=rcolor)
            # Название
            rname = r.get("name", "")[:30]
            draw.text((lx + 50, ry1 + row_h // 2 - 12), rname, font=_font(22), fill=TEXT)
            # Позиция справа
            pos_str = r.get("pos", "")
            if pos_str:
                pw2, _ = _tw(draw, pos_str, _font(20))
                draw.text((lx_r - 16 - pw2, ry1 + row_h // 2 - 11), pos_str, font=_font(20), fill=MUTED)
    else:
        # Пустое состояние
        empty_h = custom_roles_bottom - ly
        draw.rounded_rectangle((lx, ly, lx_r, ly + empty_h), radius=16, fill=ROW_BG, outline=(34, 34, 34), width=1)
        # dash effect проще не делать
        # Иконка
        empty_cx = (lx + lx_r) // 2
        empty_cy = ly + empty_h // 2 - 20
        _icon(draw, empty_cx, empty_cy, IC_USER_SLASH, 72, (42, 42, 47))
        # Текст
        empty_text = "НЕТУ КАСТОМНЫХ РОЛЕЙ"
        etw, _ = _tw(draw, empty_text, _font(24))
        draw.text((empty_cx - etw // 2, empty_cy + 50), empty_text, font=_font(24), fill=(58, 58, 66))
        # Подсказка
        sub = "Приобретите в магазине, чтобы они появились здесь"
        stw, _ = _tw(draw, sub, _font(18))
        draw.text((empty_cx - stw // 2, empty_cy + 84), sub, font=_font(18), fill=(42, 42, 50))

    # --- Mini stats ---
    ms_y1 = MAIN_BOTTOM - 22 - mini_stats_h
    gap = 12
    card_w = (lx_r - lx - gap) // 2

    # Card 1 — Отзывы
    c1x1 = lx
    c1x2 = c1x1 + card_w
    draw.rounded_rectangle((c1x1, ms_y1, c1x2, ms_y1 + mini_stats_h), radius=14, fill=ROW_BG, outline=ROW_BORDER, width=1)
    _icon(draw, c1x1 + 22, ms_y1 + 30, IC_THUMBS_UP, 20, MUTED)
    draw.text((c1x1 + 40, ms_y1 + 20), "ОТЗЫВЫ", font=_font(17), fill=MUTED)
    draw.text((c1x1 + 22, ms_y1 + 52), str(reviews), font=_font(42), fill=(20, 155, 208))

    # Card 2 — Покупки
    c2x1 = c1x2 + gap
    c2x2 = lx_r
    draw.rounded_rectangle((c2x1, ms_y1, c2x2, ms_y1 + mini_stats_h), radius=14, fill=ROW_BG, outline=ROW_BORDER, width=1)
    _icon(draw, c2x1 + 22, ms_y1 + 30, IC_CHECK, 20, MUTED)
    draw.text((c2x1 + 40, ms_y1 + 20), "ПОКУПКИ", font=_font(17), fill=MUTED)
    draw.text((c2x1 + 22, ms_y1 + 52), str(purchases_count), font=_font(42), fill=GREEN)

    # ============ RIGHT COLUMN ============
    ry1 = MAIN_Y
    ry2 = MAIN_BOTTOM
    r_total = ry2 - ry1

    # Пропорции
    stats_h = 105
    gap_r = 15
    personal_h = 420
    inv_h = 220
    hist_h = r_total - stats_h - personal_h - inv_h - 3 * gap_r

    # --- Stats row (4 cards) ---
    sw = (right_x2 - right_x1 - 3 * 12) // 4

    # Card 1 — Баланс
    x1 = right_x1
    _draw_stat_card(draw, x1, ry1, x1 + sw, ry1 + stats_h, "БАЛАНС", f"{balance}", "DC", (46, 204, 113), IC_GEM)
    # Card 2 — Всего
    x1 += sw + 12
    _draw_stat_card(draw, x1, ry1, x1 + sw, ry1 + stats_h, "ВСЕГО DC", f"{total_earned}", "", (247, 201, 145), IC_TROPHY)
    # Card 3 — Отзывов
    x1 += sw + 12
    _draw_stat_card(draw, x1, ry1, x1 + sw, ry1 + stats_h, "ОТЗЫВОВ", f"{reviews}", "", (247, 201, 145), IC_STAR)
    # Card 4 — Стрик
    x1 += sw + 12
    _draw_stat_card(draw, x1, ry1, x1 + sw, ry1 + stats_h, "СТРИК", f"{streak}", "дн", (216, 142, 223), IC_FIRE)

    # --- Personal DC block ---
    py1 = ry1 + stats_h + gap_r
    py2 = py1 + personal_h
    draw.rounded_rectangle((right_x1, py1, right_x2, py2), radius=21, fill=ROW_BG, outline=ROW_BORDER, width=1)
    _gradient_bar(draw, right_x1 + 2, py1 + 2, right_x2 - 2, py1 + 8, GOLD, (174, 121, 17))

    px = right_x1 + 24
    px_r = right_x2 - 24
    ph_y = py1 + 22
    _icon(draw, px + 12, ph_y + 11, IC_CHART, 20, MUTED)
    draw.text((px + 32, ph_y), "СТАТИСТИКА DC", font=_font(18), fill=MUTED)
    uname_str = f"@{user_name}"
    uw, _ = _tw(draw, uname_str, _font(18))
    draw.text((px_r - uw, ph_y), uname_str, font=_font(18), fill=GOLD)

    # 4 строки
    rows_y1 = ph_y + 42
    rows_y2 = py2 - 20
    rh = (rows_y2 - rows_y1) // 4
    row_data = [
        ("Заработано за всё время", f"{total_earned}", "DC", IC_CROWN, True),
        ("Текущий баланс", f"{balance}", "DC", IC_GEM, False),
        ("Заработано за месяц", f"{earned_month}", "DC", IC_TREND_UP, False),
        ("Потрачено за месяц", f"{spent_month}", "DC", IC_CART, False),
    ]
    for i, (lbl, val, unit, code, is_top) in enumerate(row_data):
        ry_1 = rows_y1 + i * rh
        ry_2 = ry_1 + rh - 8
        row_bg = ROW_BG if not is_top else (24, 22, 18)
        row_br = ROW_BORDER if not is_top else (95, 78, 35)
        draw.rounded_rectangle((px, ry_1, px_r, ry_2), radius=14, fill=row_bg, outline=row_br, width=1)

        icon_bg = GOLD if is_top else (26, 26, 32)
        icon_col = (0, 0, 0) if is_top else GOLD
        ibx = px + 16
        iby = ry_1 + (rh - 8) // 2 - 22
        draw.rounded_rectangle((ibx, iby, ibx + 44, iby + 44), radius=11, fill=icon_bg, outline=icon_col if not is_top else GOLD, width=1)
        _icon(draw, ibx + 22, iby + 22, code, 20, icon_col)

        draw.text((ibx + 58, ry_1 + (rh - 8) // 2 - 12), lbl, font=_font(22), fill=(TEXT if is_top else (170, 170, 170)))

        val_str = f"{val} {unit}".strip()
        vfont = _font(30 if is_top else 26)
        vw, _ = _tw(draw, val_str, vfont)
        draw.text((px_r - 20 - vw, ry_1 + (rh - 8) // 2 - 15), val_str, font=vfont, fill=(TEXT if is_top else GOLD))

    # --- Inventory ---
    iy1 = py2 + gap_r
    iy2 = iy1 + inv_h
    draw.rounded_rectangle((right_x1, iy1, right_x2, iy2), radius=21, fill=ROW_BG, outline=ROW_BORDER, width=1)

    ix = right_x1 + 24
    ix_r = right_x2 - 24
    ih_y = iy1 + 18
    _icon(draw, ix + 12, ih_y + 11, IC_BOX_OPEN, 20, MUTED)
    draw.text((ix + 32, ih_y), "ИНВЕНТАРЬ", font=_font(18), fill=MUTED)

    inv_total_shown = len(inventory)
    if inv_total_shown > 3:
        extra_str = f"+{inv_total_shown - 3} ещё"
        ew, _ = _tw(draw, extra_str, _font(18))
        _icon(draw, ix_r - ew - 22, ih_y + 11, IC_CIRCLE_PLUS, 18, GREEN)
        draw.text((ix_r - ew, ih_y), extra_str, font=_font(18), fill=GREEN)
    elif inv_total_shown > 0:
        total_str = f"всего {inv_total_shown}"
        tw2, _ = _tw(draw, total_str, _font(18))
        draw.text((ix_r - tw2, ih_y), total_str, font=_font(18), fill=GREEN)

    shown = inventory[:3]
    cards_y1 = ih_y + 34
    cards_y2 = iy2 - 18
    cw2 = (ix_r - ix - 2 * 12) // 3
    for i in range(3):
        cx1 = ix + i * (cw2 + 12)
        cx2 = cx1 + cw2
        draw.rounded_rectangle((cx1, cards_y1, cx2, cards_y2), radius=14, fill=ROW_BG, outline=ROW_BORDER, width=1)
        if i < len(shown):
            item = shown[i]
            # accent line
            draw.rectangle((cx1 + 4, cards_y1 + 4, cx1 + 7, cards_y2 - 4), fill=item.get("accent", (20, 155, 208)))

            icx = cx1 + 22
            icy = cards_y1 + (cards_y2 - cards_y1) // 2 - 22
            draw.rounded_rectangle((icx, icy, icx + 44, icy + 44), radius=11, fill=(26, 26, 32), outline=(36, 36, 42), width=1)
            _icon(draw, icx + 22, icy + 22, item.get("icon", IC_GEM), 20, item.get("accent", (20, 155, 208)))

            iname = item.get("name", "")[:16]
            draw.text((icx + 56, cards_y1 + (cards_y2 - cards_y1) // 2 - 22), iname, font=_font(20), fill=TEXT)
            iqty = item.get("qty", "")
            if iqty:
                draw.text((icx + 56, cards_y1 + (cards_y2 - cards_y1) // 2 + 8), iqty, font=_font(16), fill=MUTED)

    # --- History ---
    hy1 = iy2 + gap_r
    hy2 = ry2
    draw.rounded_rectangle((right_x1, hy1, right_x2, hy2), radius=21, fill=ROW_BG, outline=ROW_BORDER, width=1)

    hx = right_x1 + 24
    hx_r = right_x2 - 24
    hh_y = hy1 + 16
    _icon(draw, hx + 12, hh_y + 11, IC_CLOCK, 20, MUTED)
    draw.text((hx + 32, hh_y), "ПОСЛЕДНИЕ ОПЕРАЦИИ", font=_font(18), fill=MUTED)

    hist_shown = history[:6]
    col_w = (hx_r - hx - 30) // 2
    row_start = hh_y + 36
    row_bottom = hy2 - 16
    row_h = (row_bottom - row_start) // 3

    for i, h in enumerate(hist_shown):
        col = i % 2
        row = i // 2
        hx1 = hx + col * (col_w + 30)
        hy_1 = row_start + row * row_h
        hy_2 = hy_1 + row_h - 6
        # date
        draw.text((hx1, hy_1 + row_h // 2 - 12), h.get("date", ""), font=_font(20), fill=MUTED)
        # amount
        amt = h.get("amount", 0)
        if amt >= 0:
            amt_str = f"+{amt} DC"
            color = GREEN
        else:
            amt_str = f"−{abs(amt)} DC"
            color = (255, 107, 107)
        aw2, _ = _tw(draw, amt_str, _font(22))
        draw.text((hx1 + col_w - aw2, hy_1 + row_h // 2 - 13), amt_str, font=_font(22), fill=color)
        # divider
        if row < 2:
            draw.line((hx1, hy_2 + 3, hx1 + col_w, hy_2 + 3), fill=(26, 26, 26), width=1)

    # --- Сохраняем ---
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    logger.info("Profile card generated for user %s", user_id)
    return buf


def _draw_stat_card(draw, x1, y1, x2, y2, label, value, unit, accent, icon_code):
    ROW_BG = (20, 20, 26)
    INNER_BORDER = (42, 42, 47)
    MUTED = (136, 136, 136)
    TEXT = (255, 255, 255)

    draw.rounded_rectangle((x1, y1, x2, y2), radius=16, fill=ROW_BG, outline=INNER_BORDER, width=1)
    # accent line
    draw.rectangle((x1 + 4, y1 + 3, x2 - 4, y1 + 6), fill=accent)

    # label
    _icon(draw, x1 + 20, y1 + 26, icon_code, 18, MUTED)
    draw.text((x1 + 38, y1 + 16), label, font=_font(17), fill=MUTED)

    # value
    val_font = _font(44)
    vw, _ = _tw(draw, value, val_font)
    draw.text((x1 + 20, y1 + 44), value, font=val_font, fill=TEXT)
    if unit:
        uw2, _ = _tw(draw, unit, _font(20))
        draw.text((x1 + 20 + vw + 6, y1 + 66), unit, font=_font(20), fill=MUTED)


def generate_profile_id() -> str:
    import time, random
    return f"P-{int(time.time())}-{random.randint(100, 999)}"
