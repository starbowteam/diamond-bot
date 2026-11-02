# -*- coding: utf-8 -*-
"""core/render.py — единые хелперы для всех рендеров и UI."""
import os
from typing import Optional, Tuple, List
from PIL import Image, ImageDraw, ImageFont
from core.utils import ADD_DIR

FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")
_FONT_CACHE, _FA_CACHE = {}, {}

def _font(size: int):
    if size in _FONT_CACHE: return _FONT_CACHE[size]
    try: f = ImageFont.truetype(FONT_BOLD, size)
    except Exception: f = ImageFont.load_default()
    _FONT_CACHE[size] = f; return f

def _fa(size: int):
    if size in _FA_CACHE: return _FA_CACHE[size]
    f = None
    if os.path.exists(FONT_FA):
        try: f = ImageFont.truetype(FONT_FA, size)
        except Exception: pass
    _FA_CACHE[size] = f; return f

# Палитра
BG, CARD_TOP = (10, 10, 12), (16, 16, 20)
STACK_BG, STACK_BRD, STACK_HDR = (21, 21, 26), (58, 58, 64), (36, 36, 42)
INNER_BG, INNER_BRD = (18, 18, 23), (40, 40, 47)
TEXT, TEXT_SOFT, MUTED, DIM, DARK = (255, 255, 255), (232, 232, 236), (136, 136, 136), (102, 102, 102), (85, 85, 85)
SILVER, SILVER_HI, SILVER_DIM, SILVER_BG = (198, 208, 224), (224, 232, 245), (120, 132, 155), (34, 38, 48)
GREEN, RED, BLUE, PURPLE, GOLD, BRONZE = (46, 204, 113), (255, 107, 107), (106, 155, 209), (179, 157, 219), (247, 201, 145), (209, 146, 96)
GREEN_BG, RED_BG, BLUE_BG, PURPLE_BG, GOLD_BG = (18, 44, 28), (44, 20, 20), (20, 30, 44), (32, 26, 48), (40, 32, 21)
CARD_BRD, EMBED_COLOR, COLOR_GREY = (74, 74, 79), 0x2b2d31, 0x676767

# Иконки FA5
I_GEM, I_STAR, I_CROWN, I_TROPHY = 0xf3a5, 0xf005, 0xf521, 0xf091
I_MEDAL, I_AWARD, I_COINS, I_SACK = 0xf5a2, 0xf559, 0xf51e, 0xf81d
I_MONEY, I_MONEY2, I_BAG, I_BRIEF = 0xf53a, 0xf53b, 0xf290, 0xf0b1
I_CHART, I_BANK, I_USERS, I_USER = 0xf201, 0xf19c, 0xf0c0, 0xf007
I_USER_SEC, I_USER_TIE, I_HAND, I_HANDD = 0xf21b, 0xf508, 0xf4c0, 0xf4c0
I_CLOCK, I_CALENDAR, I_CALC, I_LIST = 0xf017, 0xf133, 0xf274, 0xf03a
I_LISTC, I_INFO, I_CHECK, I_XMARK = 0xf0ae, 0xf05a, 0xf00c, 0xf00d
I_PERCENT, I_HISTORY, I_FIRE, I_GIFT = 0xf295, 0xf1da, 0xf06d, 0xf06b
I_DICE, I_DICE5, I_DICE6, I_MESSAGE = 0xf522, 0xf523, 0xf526, 0xf075
I_COMMENT, I_COMMENTS, I_MIC, I_HEADPH = 0xf075, 0xf086, 0xf130, 0xf025
I_SCROLL, I_PEN, I_PEN_NIB, I_PENF = 0xf70e, 0xf304, 0xf5ad, 0xf5ac
I_SEARCH, I_GAMEPAD, I_CUBE, I_GAUGE = 0xf002, 0xf11b, 0xf1b2, 0xf624
I_SHIELD, I_BOLT, I_LOCK, I_SPADE = 0xf3ed, 0xf0e7, 0xf023, 0xf2f4
I_HEART, I_DIAMOND, I_CLUB, I_QUESTION = 0xf004, 0xf219, 0xf327, 0xf128
I_ROTATE, I_ROTATE_L, I_ARROW_L, I_ARROW_D = 0xf2f1, 0xf2ea, 0xf060, 0xf063
I_ELL, I_CIRCLE_M, I_PLUS, I_TRASH = 0xf141, 0xf056, 0xf067, 0xf1f8
I_EYE, I_IMAGE, I_PALETTE, I_MASKS = 0xf06e, 0xf03e, 0xf53f, 0xf630
I_BULLHORN, I_TICKET, I_RECEIPT, I_BUILDING = 0xf0a1, 0xf145, 0xf543, 0xf19c
I_MOBILE, I_CREDIT, I_BAN, I_HEAD = 0xf3cd, 0xf09d, 0xf05e, 0xf590
I_MOUSE, I_CART, I_BOX, I_CHECK_C = 0xf8cc, 0xf07a, 0xf466, 0xf058
I_XMARK_C, I_HANDSHAKE, I_CROW, I_SEEDLING = 0xf057, 0xf2b5, 0xf520, 0xf4d8
I_GAVEL, I_BOOK, I_LAYERS, I_BEZIER = 0xf0e3, 0xf02d, 0xf5fd, 0xf55b
I_SMILE, I_BOOK_OPEN, I_PAINT = 0xf118, 0xf518, 0xf1fc

CANVAS_W, CANVAS_H, M, PAD_X, PAD_Y = 1800, 1000, 14, 40, 40

def _tw(d, text, font):
    b = d.textbbox((0, 0), text, font=font); return b[2] - b[0]

def _ellipsis(d, text, font, max_w):
    if _tw(d, text, font) <= max_w: return text
    t = text
    while t and _tw(d, t + "…", font) > max_w: t = t[:-1]
    return t + "…"

def _wrap(d, text, font, max_w, max_lines=3):
    words = (text or "").split(); lines = []; cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if _tw(d, test, font) <= max_w: cur = test
        else:
            if cur: lines.append(cur)
            if len(lines) >= max_lines: return lines
            cur = w
    if cur and len(lines) < max_lines: lines.append(cur)
    return lines or [""]

def _fmt(n) -> str:
    try: return f"{int(n):,}".replace(",", " ")
    except Exception: return str(n)

def _icon(d, cx, cy, code, size, color):
    f = _fa(size)
    if f is None: return
    try: d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception: pass

def _lighten(c, amount: float = 0.4):
    return tuple(min(int(c[i] + (255 - c[i]) * amount), 255) for i in range(3))

def _darken(c, amount: float = 0.4):
    return tuple(max(int(c[i] * (1 - amount)), 0) for i in range(3))

def _alpha_fill(base, box, color, alpha=30, radius=0):
    x1, y1, x2, y2 = box; w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
    if radius > 0: ld.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=color + (alpha,))
    else: ld.rectangle((0, 0, w - 1, h - 1), fill=color + (alpha,))
    base.paste(layer, (x1, y1), layer)

def _gradient_box(base, box, c1, c2, alpha=30, radius=0, horizontal=True):
    x1, y1, x2, y2 = box; w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
    steps = w if horizontal else h
    for i in range(steps):
        t = i / max(steps - 1, 1)
        r = int(c1[0] * (1 - t) + c2[0] * t); g = int(c1[1] * (1 - t) + c2[1] * t); b = int(c1[2] * (1 - t) + c2[2] * t)
        if horizontal: ld.line([(i, 0), (i, h)], fill=(r, g, b, alpha))
        else: ld.line([(0, i), (w, i)], fill=(r, g, b, alpha))
    if radius > 0:
        mask = Image.new("L", (w, h), 0); ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        a = Image.composite(layer.split()[3], Image.new("L", (w, h), 0), mask); layer.putalpha(a)
    base.paste(layer, (x1, y1), layer)

def _draw_stack_panel(base, d, box, radius=22):
    x1, y1, x2, y2 = box
    _alpha_fill(base, (x1 + 12, y1 + 12, x2 + 12, y2 + 12), (46, 46, 52), alpha=110, radius=radius)
    _alpha_fill(base, (x1 + 6, y1 + 6, x2 + 6, y2 + 6), (46, 46, 52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)

def _draw_dashed_rect(d, box, radius, color, dash=10, gap=7, width=2):
    x1, y1, x2, y2 = box; r = radius
    def dash_line(p1, p2):
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]; length = (dx * dx + dy * dy) ** 0.5
        if length == 0: return
        ux, uy = dx / length, dy / length; pos = 0.0
        while pos < length:
            seg_end = min(pos + dash, length)
            d.line([(p1[0] + ux * pos, p1[1] + uy * pos), (p1[0] + ux * seg_end, p1[1] + uy * seg_end)], fill=color, width=width)
            pos = seg_end + gap
    dash_line((x1 + r, y1), (x2 - r, y1)); dash_line((x2 - r, y2), (x1 + r, y2))
    dash_line((x1, y1 + r), (x1, y2 - r)); dash_line((x2, y1 + r), (x2, y2 - r))
    d.arc((x1, y1, x1 + 2 * r, y1 + 2 * r), 180, 270, fill=color, width=width)
    d.arc((x2 - 2 * r, y1, x2, y1 + 2 * r), 270, 360, fill=color, width=width)
    d.arc((x1, y2 - 2 * r, x1 + 2 * r, y2), 90, 180, fill=color, width=width)
    d.arc((x2 - 2 * r, y2 - 2 * r, x2, y2), 0, 90, fill=color, width=width)

P = "\u3164"
def btn_pad(text: str, total: int) -> str:
    extra = max(0, total - len(text)); left = extra // 2
    return f"{P * left}{text}{P * (extra - left)}"

def btn_labels_total(labels: List[str], total: int) -> List[str]:
    extra = max(0, total - sum(len(s) for s in labels)); n = len(labels)
    if n == 0: return labels
    per, rem = extra // n, extra % n
    res = []
    for i, s in enumerate(labels):
        pad = per + (1 if i < rem else 0); left = pad // 2
        res.append(f"{P * left}{s}{P * (pad - left)}")
    return res

def L(text: str) -> str: return f"{P}{text}{P}"

_ALLOWED_SPECIAL = set("—–‑‒―“”«»„‘’…№·•▪●◆◇■□")
def sanitize(text: str, fallback: str = "") -> str:
    if not text: return fallback
    out = [ch for ch in text if 0x20 <= ord(ch) <= 0x7E or 0x0400 <= ord(ch) <= 0x04FF or 0x00C0 <= ord(ch) <= 0x017F or ch in _ALLOWED_SPECIAL]
    res = "".join(out).strip()
    while "  " in res: res = res.replace("  ", " ")
    return res or fallback

def base_canvas(uid_label: str = "", uid_value: Optional[int] = None, status_label: Optional[str] = None, logo_icon: int = I_GEM) -> Tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,)); d = ImageDraw.Draw(img)
    d.rounded_rectangle((M, M, CANVAS_W - 1 - M, CANVAS_H - 1 - M), radius=28, fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)
    d.rounded_rectangle((PAD_X, PAD_Y, PAD_X + 64, PAD_Y + 64), radius=16, fill=(58, 58, 64) + (255,), outline=(94, 94, 100) + (255,), width=2)
    _icon(d, PAD_X + 32, PAD_Y + 33, logo_icon, 30, SILVER_HI)
    d.text((PAD_X + 84, PAD_Y + 4), "DIAMOND", font=_font(34), fill=TEXT)
    d.text((PAD_X + 88, PAD_Y + 46), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)
    meta_r = CANVAS_W - M - PAD_X
    if uid_label:
        w1 = _tw(d, uid_label.upper(), _font(15)); d.text((meta_r - w1, PAD_Y + 12), uid_label.upper(), font=_font(15), fill=MUTED)
    if status_label is not None:
        w2 = _tw(d, status_label.upper(), _font(22)); d.text((meta_r - w2, PAD_Y + 36), status_label.upper(), font=_font(22), fill=TEXT)
    elif uid_value is not None:
        w2 = _tw(d, f"UID · {uid_value}", _font(24)); d.text((meta_r - w2, PAD_Y + 38), f"UID · {uid_value}", font=_font(24), fill=TEXT)
    sy = PAD_Y + 64 + 20; d.line((PAD_X, sy, CANVAS_W - M - PAD_X, sy), fill=STACK_HDR + (255,), width=2)
    return img, d

def draw_footer(d, left_text: str, right_text: str = ""):
    y = CANVAS_H - M - PAD_Y + 4; d.line((PAD_X, y - 10, CANVAS_W - M - PAD_X, y - 10), fill=STACK_HDR + (255,), width=2)
    _icon(d, PAD_X + 12, y + 10, I_INFO, 16, DIM); d.text((PAD_X + 38, y), left_text, font=_font(13), fill=DIM)
    if right_text:
        pw = _tw(d, right_text, _font(13)); d.text((CANVAS_W - M - PAD_X - pw, y), right_text, font=_font(13), fill=SILVER)

def draw_right_head(d, x1, y1, x2, title: str, sub: str = ""):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 50), radius=3, fill=SILVER + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(30), fill=TEXT)
    if sub:
        sub_w = _tw(d, sub.upper(), _font(15)); d.text((x2 - sub_w, y1 + 18), sub.upper(), font=_font(15), fill=MUTED)
    d.line((x1, y1 + 64, x2, y1 + 64), fill=STACK_HDR + (255,), width=2)
