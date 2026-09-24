# -*- coding: utf-8 -*-
"""Рендер карточки профиля на PIL + FA."""
import io
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict

from PIL import Image, ImageDraw, ImageFont
from core.utils import ADD_DIR, logger

# 👇 Мягкий импорт — если клан-лига не загружена, карточка работает
try:
    from clan.core import get_user_clan
except Exception:
    get_user_clan = None

FONT_BOLD = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_FONT_CACHE = {}
_FA_CACHE = {}

I_USER    = 0xf007
I_CROWN   = 0xf521
I_THUMBS  = 0xf164
I_GEM     = 0xf3a5
I_CAL     = 0xf073
I_CLOCK   = 0xf017
I_TROPHY  = 0xf091
I_DICE    = 0xf522
I_STAR    = 0xf005
I_SACK    = 0xf81d
I_CART    = 0xf07a
I_ROTATE  = 0xf1da
I_PEOPLE  = 0xf0c0
I_COINS   = 0xf51e
I_SHIELD  = 0xf3ed

BG = (10, 10, 12)
CARD_TOP = (26, 26, 31)
CARD_BOT = (20, 20, 26)
BORDER = (74, 74, 79)
INNER = (15, 15, 20)
INNER_BORDER = (42, 42, 47)
OP_BG = (20, 20, 26)
OP_BORDER = (31, 31, 36)
TEXT = (255, 255, 255)
MUTED = (136, 136, 136)
DIM = (102, 102, 102)
GOLD = (247, 201, 145)
GREEN = (46, 204, 113)
RED = (255, 107, 107)


ROLE_INFO = {
    "none":      ("Клуб",            GOLD),
    "bronze":    ("Bronze Buyer",    (231, 143, 103)),
    "silver":    ("Silver Buyer",    (224, 224, 224)),
    "gold":      ("Gold Buyer",      GOLD),
    "diamond":   ("Diamond Buyer",   (221, 240, 239)),
    "crystalis": ("Crystalis Buyer", (216, 142, 223)),
    "pka":       ("Покупатель Века", (212, 191, 255)),
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
        return "—"
    d = (datetime.now(timezone.utc) - dt).days
    if d < 0:
        d = 0
    last = d % 10
    last2 = d % 100
    if last == 1 and last2 != 11:
        suf = "день"
    elif 2 <= last <= 4 and not (12 <= last2 <= 14):
        suf = "дня"
    else:
        suf = "дней"
    return f"{d} {suf}"


def _op_icon(reason: str):
    r = reason.lower()
    if "рулетк" in r: return I_TROPHY
    if "блэкдж" in r: return I_DICE
    if "монет" in r: return I_COINS
    if "отзыв" in r: return I_STAR
    if "зарплат" in r or "аванс" in r: return I_SACK
    if "покупк" in r: return I_CART
    if "акци" in r: return I_TROPHY
    if "подарок" in r: return I_STAR
    if "клан" in r or "копилк" in r: return I_SHIELD
    return I_COINS


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
    M = 20
    PX = 48
    PY = 36

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.rounded_rectangle((M, M, W - M, H - M), radius=30, fill=CARD_BOT, outline=BORDER, width=3)
    d.rounded_rectangle((M + 1, M + 1, W - M - 1, H // 2), radius=30, fill=CARD_TOP)

    # ---------------- ШАПКА ----------------
    cy_top = M + PY
    logo_size = 76
    d.rounded_rectangle((M + PX, cy_top, M + PX + logo_size, cy_top + logo_size),
                        radius=20, fill=(74, 74, 79))
    _draw_icon(d, M + PX + logo_size // 2, cy_top + logo_size // 2 + 2,
               I_PEOPLE, 36, (224, 224, 224))

    d.text((M + PX + logo_size + 20, cy_top + 2), "DIAMOND", font=_font(38), fill=TEXT)
    d.text((M + PX + logo_size + 22, cy_top + 50), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)

    lbl = "ПРОФИЛЬ ПОКУПАТЕЛЯ"
    id_str = f"#{user_id}"
    w1 = _tw(d, lbl, _font(16))
    w2 = _tw(d, id_str, _font(26))
    d.text((W - M - PX - w1, cy_top + 12), lbl, font=_font(16), fill=MUTED)
    d.text((W - M - PX - w2, cy_top + 38), id_str, font=_font(26), fill=TEXT)

    yline = cy_top + logo_size + 24
    d.line((M + PX, yline, W - M - PX, yline), fill=INNER_BORDER, width=2)

    # ---------------- BODY ----------------
    body_y = yline + 30
    body_x1 = M + PX
    body_x2 = W - M - PX
    gap = 32
    total_w = body_x2 - body_x1
    left_w = int((total_w - gap) / 2.3)
    right_w = (total_w - gap) - left_w
    left_x1 = body_x1
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = right_x1 + right_w

    # --- USER ROW ---
    ur_h = 210  # 👈 увеличено под 2 бейджа
    d.rounded_rectangle((left_x1, body_y, left_x2, body_y + ur_h),
                        radius=22, fill=INNER, outline=INNER_BORDER, width=2)

    av_size = 130
    av_x = left_x1 + 26
    av_y = body_y + 22
    av_img = _avatar_img(avatar_bytes, av_size) if avatar_bytes else None
    if av_img:
        img.paste(av_img, (av_x, av_y), av_img)
    else:
        d.ellipse((av_x, av_y, av_x + av_size, av_y + av_size), fill=(60, 60, 66))
        _draw_icon(d, av_x + av_size // 2, av_y + av_size // 2 + 2, I_USER, 56, MUTED)
    d.ellipse((av_x - 2, av_y - 2, av_x + av_size + 2, av_y + av_size + 2),
              outline=GOLD, width=4)
    od_cx = av_x + av_size - 16
    od_cy = av_y + av_size - 16
    d.ellipse((od_cx - 13, od_cy - 13, od_cx + 13, od_cy + 13),
              fill=GREEN, outline=INNER, width=4)

    un_x = av_x + av_size + 26
    un_y = body_y + 26
    uname = user_name
    max_w = left_x2 - un_x - 20
    if _tw(d, uname, _font(42)) > max_w:
        while uname and _tw(d, uname + "…", _font(42)) > max_w:
            uname = uname[:-1]
        uname += "…"
    d.text((un_x, un_y), uname, font=_font(42), fill=TEXT)

    rn, rc = ROLE_INFO.get(role_key, ROLE_INFO["none"])
    rn_up = rn.upper()
    rn_f = _font(17)
    rn_w = _tw(d, rn_up, rn_f)
    badge_h = 44
    badge_w = 40 + rn_w + 22
    badge_x = un_x
    badge_y = un_y + 60
    badge_cy = badge_y + badge_h // 2

    d.rounded_rectangle((badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
                        radius=14, fill=(40, 32, 22), outline=GOLD, width=2)
    _draw_icon(d, badge_x + 22, badge_cy + 1, I_CROWN, 18, GOLD)
    d.text((badge_x + 40, badge_cy), rn_up, font=rn_f, fill=GOLD, anchor="lm")

    # 👇 Бейдж клана (под бейджем роли)
    clan = None
    if get_user_clan:
        try:
            clan = get_user_clan(user_id)
        except Exception:
            clan = None

    if clan:
        clan_y = badge_y + badge_h + 8
        clan_emoji = clan.get("emoji", "🛡")
        clan_name = clan.get("name", "—").upper()
        clan_txt = f"{clan_emoji} {clan_name}"
        clan_f = _font(15)
        clan_w = _tw(d, clan_txt, clan_f)
        clan_badge_w = 20 + clan_w + 20
        clan_badge_h = 36
        clan_color = clan.get("color", 0xF7C991)
        clan_r = (clan_color >> 16) & 0xFF
        clan_g = (clan_color >> 8) & 0xFF
        clan_b = clan_color & 0xFF
        d.rounded_rectangle((badge_x, clan_y, badge_x + clan_badge_w, clan_y + clan_badge_h),
                            radius=12, fill=(28, 24, 40),
                            outline=(clan_r, clan_g, clan_b), width=2)
        d.text((badge_x + 16, clan_y + clan_badge_h // 2), clan_txt,
               font=clan_f, fill=(clan_r, clan_g, clan_b), anchor="lm")

    # --- METRICS ---
    metrics_y = body_y + ur_h + 20
    metrics_h = 98
    m_w = (left_w - 16) // 2
    icon_box = 54

    m1x1 = left_x1
    m1x2 = m1x1 + m_w
    d.rounded_rectangle((m1x1, metrics_y, m1x2, metrics_y + metrics_h),
                        radius=20, fill=INNER, outline=INNER_BORDER, width=2)

    ibx = m1x1 + 26
    iby = metrics_y + (metrics_h - icon_box) // 2
    d.rounded_rectangle((ibx, iby, ibx + icon_box, iby + icon_box), radius=15, fill=(40, 32, 18))
    _draw_icon(d, ibx + icon_box // 2, iby + icon_box // 2 + 1, I_THUMBS, 26, GOLD)

    text_x = ibx + icon_box + 18
    lbl_y = metrics_y + 16
    val_y = metrics_y + 36
    d.text((text_x, lbl_y), "ОТЗЫВОВ", font=_font(14), fill=MUTED)
    d.text((text_x, val_y), str(reviews), font=_font(44), fill=GOLD)

    m2x1 = m1x2 + 16
    m2x2 = left_x2
    d.rounded_rectangle((m2x1, metrics_y, m2x2, metrics_y + metrics_h),
                        radius=20, fill=INNER, outline=INNER_BORDER, width=2)

    ibx2 = m2x1 + 26
    d.rounded_rectangle((ibx2, iby, ibx2 + icon_box, iby + icon_box), radius=15, fill=(18, 44, 28))
    _draw_icon(d, ibx2 + icon_box // 2, iby + icon_box // 2 + 1, I_GEM, 26, GREEN)

    text2_x = ibx2 + icon_box + 18
    d.text((text2_x, lbl_y), "БАЛАНС", font=_font(14), fill=MUTED)
    bal_str = _fmt(balance)
    d.text((text2_x, val_y), bal_str, font=_font(44), fill=GREEN)
    bw = _tw(d, bal_str, _font(44))
    d.text((text2_x + bw + 10, val_y + 22), "DC", font=_font(20), fill=DIM)

    # --- SINCE ---
    since_y1 = metrics_y + metrics_h + 20
    since_y2 = H - M - PY
    d.rounded_rectangle((left_x1, since_y1, left_x2, since_y2),
                        radius=20, fill=INNER, outline=INNER_BORDER, width=2)

    big_box = 100
    bb_x = left_x1 + 34
    bb_y = (since_y1 + since_y2 - big_box) // 2
    d.rounded_rectangle((bb_x, bb_y, bb_x + big_box, bb_y + big_box),
                        radius=22, fill=(24, 24, 30), outline=(40, 40, 48), width=2)
    _draw_icon(d, bb_x + big_box // 2, bb_y + big_box // 2 + 2, I_CAL, 46, (200, 200, 208))

    tx = bb_x + big_box + 32
    ty = bb_y + 4
    d.text((tx, ty), "В DIAMOND С", font=_font(16), fill=(106, 106, 114))
    date_str = joined_at.strftime("%d.%m.%Y") if joined_at else "—"
    d.text((tx, ty + 34), date_str, font=_font(42), fill=(240, 240, 245))

    days_str = _since_days(joined_at)
    dp_w = 52 + _tw(d, days_str, _font(20))
    dp_h = 42
    dp_x = tx
    dp_y = ty + 90
    d.rounded_rectangle((dp_x, dp_y, dp_x + dp_w, dp_y + dp_h),
                        radius=12, fill=(28, 28, 34), outline=(40, 40, 48), width=2)
    _draw_icon(d, dp_x + 22, dp_y + dp_h // 2 + 1, I_CLOCK, 20, (160, 160, 168))
    d.text((dp_x + 40, dp_y + dp_h // 2), days_str, font=_font(20), fill=(200, 200, 208), anchor="lm")

    # --- HISTORY COL ---
    hist_h = since_y2 - body_y
    d.rounded_rectangle((right_x1, body_y, right_x2, body_y + hist_h),
                        radius=22, fill=INNER, outline=INNER_BORDER, width=2)

    inner_px = 28
    ih_x1 = right_x1 + inner_px
    ih_x2 = right_x2 - inner_px
    header_y = body_y + 24
    _draw_icon(d, ih_x1 + 12, header_y + 16, I_ROTATE, 22, GOLD)
    d.text((ih_x1 + 34, header_y + 4), "ПОСЛЕДНИЕ ОПЕРАЦИИ", font=_font(18), fill=MUTED)

    sep_y = header_y + 46
    d.line((ih_x1, sep_y, ih_x2, sep_y), fill=INNER_BORDER, width=2)

    list_y1 = sep_y + 18
    list_y2 = body_y + hist_h - 24
    list_h = list_y2 - list_y1

    ops = (history or [])[-5:]
    if not ops:
        _draw_icon(d, (ih_x1 + ih_x2) // 2, (list_y1 + list_y2) // 2 - 20,
                   I_ROTATE, 72, (37, 37, 48))
        t = "НЕТ ОПЕРАЦИЙ"
        tw = _tw(d, t, _font(22))
        d.text(((ih_x1 + ih_x2) // 2 - tw // 2, (list_y1 + list_y2) // 2 + 30),
               t, font=_font(22), fill=(51, 51, 56))
    else:
        n = len(ops)
        gap_op = 12
        op_h = (list_h - (n - 1) * gap_op) // n
        op_y = list_y1
        for op in ops:
            amt = op.get("amount", 0)
            reason_full = op.get("reason", "—") or "—"
            ts = op.get("date", 0)
            try:
                dstr = datetime.fromtimestamp(ts).strftime("%d.%m.%Y · %H:%M")
            except Exception:
                dstr = "—"

            is_plus = amt >= 0
            accent = GREEN if is_plus else RED
            accent_bg = (18, 44, 28) if is_plus else (44, 20, 20)
            sign = "+" if is_plus else "−"

            d.rounded_rectangle((ih_x1, op_y, ih_x2, op_y + op_h),
                                radius=14, fill=OP_BG, outline=OP_BORDER, width=2)

            op_icon_size = 48
            ob_x = ih_x1 + 22
            ob_y = op_y + (op_h - op_icon_size) // 2
            d.rounded_rectangle((ob_x, ob_y, ob_x + op_icon_size, ob_y + op_icon_size),
                                radius=13, fill=accent_bg)
            _draw_icon(d, ob_x + op_icon_size // 2, ob_y + op_icon_size // 2 + 1,
                       _op_icon(reason_full), 22, accent)

            reason_x = ob_x + op_icon_size + 18
            reason_y = op_y + (op_h // 2) - 22

            amt_str = f"{sign}{abs(int(amt))} DC"
            amt_w = _tw(d, amt_str, _font(28))
            max_reason_w = ih_x2 - 22 - amt_w - 30 - reason_x

            reason_font_size = 22
            reason_shown = reason_full
            while reason_font_size >= 16:
                f = _font(reason_font_size)
                if _tw(d, reason_full, f) <= max_reason_w:
                    reason_shown = reason_full
                    break
                reason_font_size -= 2
            else:
                f = _font(reason_font_size)
                reason_shown = _ellipsis(d, reason_full, f, max_reason_w)

            reason_font = _font(reason_font_size)
            d.text((reason_x, reason_y), reason_shown, font=reason_font, fill=TEXT)
            d.text((reason_x, reason_y + 34), dstr, font=_font(16), fill=DIM)

            d.text((ih_x2 - 22 - amt_w, op_y + (op_h // 2) - 14),
                   amt_str, font=_font(28), fill=accent)

            op_y += op_h + gap_op

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
