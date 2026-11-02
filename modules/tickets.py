# -*- coding: utf-8 -*-
"""Единый модуль тикетов, счётов и рендера карточек профиля."""
import asyncio
import io
import os
import random
import time
import math
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple

import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption
from disnake.ui import View, Button, Modal, Select, TextInput
from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, CONFIG, logger, log_discord, get_ticket_owner, remove_ticket_owner, cur, db, EXEMPT_USERS
from core.render import *

try:
    from clan.core import get_user_clan, CLANS_DATA
except Exception:
    get_user_clan = None
    CLANS_DATA = []

IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"
MSK = timezone(timedelta(hours=3))

def _now_msk_str() -> str: return datetime.now(MSK).strftime("%d.%m.%Y %H:%M")

# ============================================================
# РЕНДЕР: КАРТОЧКА ПРОФИЛЯ (из profile_card.py)
# ============================================================
ROLE_GRADIENTS = {
    "bronze": ((0xe7, 0x8f, 0x67), (0xd1, 0x56, 0x40)),
    "silver": ((0xff, 0xff, 0xff), (0x97, 0x97, 0x97)),
    "gold": ((0xf7, 0xc9, 0x91), (0xae, 0x79, 0x11)),
    "diamond": ((0xdd, 0xf0, 0xef), (0x14, 0x9b, 0xd0)),
    "crystalis": ((0x9f, 0xc1, 0xff), (0xd8, 0x8e, 0xdf)),
    "pka": ((0xad, 0xad, 0xad), (0x69, 0x69, 0x69)),
    "club": ((0xf7, 0xc9, 0x91), (0xae, 0x79, 0x11)),
    "none": ((0x66, 0x66, 0x66), (0x44, 0x44, 0x44)),
}
ROLE_INFO = {"none": "Нет роли", "club": "Клуб", "bronze": "Bronze Buyer", "silver": "Silver Buyer", "gold": "Gold Buyer", "diamond": "Diamond Buyer", "crystalis": "Crystalis Buyer", "pka": "Покупатель Века"}

def _hex_to_rgb(h: int) -> Tuple[int, int, int]: return ((h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF)

def _lerp_color(c1, c2, t):
    return (int(c1[0] * (1 - t) + c2[0] * t), int(c1[1] * (1 - t) + c2[1] * t), int(c1[2] * (1 - t) + c2[2] * t))

def _draw_gradient_ring(d, cx, cy, r, width, c1, c2, steps=180):
    for i in range(steps):
        t = i / steps; a1 = -90 + (i * 360 / steps); a2 = -90 + ((i + 1) * 360 / steps); col = _lerp_color(c1, c2, t)
        d.arc((cx - r, cy - r, cx + r, cy + r), a1, a2, fill=col, width=width)

def _draw_gradient_border_rect(d, x1, y1, x2, y2, radius, c1, c2, width=2):
    w = x2 - x1; h = y2 - y1
    for i in range(radius, w - radius):
        t = i / max(w - 1, 1); col = _lerp_color(c1, c2, t)
        d.line([(x1 + i, y1), (x1 + i, y1 + width)], fill=col); d.line([(x1 + i, y2 - width), (x1 + i, y2)], fill=col)
    for i in range(radius, h - radius):
        d.line([(x1, y1 + i), (x1 + width, y1 + i)], fill=c1); d.line([(x2 - width, y1 + i), (x2, y1 + i)], fill=c2)
    d.arc((x1, y1, x1 + 2 * radius, y1 + 2 * radius), 180, 270, fill=c1, width=width)
    d.arc((x2 - 2 * radius, y1, x2, y1 + 2 * radius), 270, 360, fill=_lerp_color(c1, c2, 0.95), width=width)
    d.arc((x1, y2 - 2 * radius, x1 + 2 * radius, y2), 90, 180, fill=c1, width=width)
    d.arc((x2 - 2 * radius, y2 - 2 * radius, x2, y2), 0, 90, fill=_lerp_color(c1, c2, 0.95), width=width)

def _avatar_img(ab, size):
    try:
        img = Image.open(io.BytesIO(ab)).convert("RGBA").resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0); ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0)); out.paste(img, (0, 0), mask); return out
    except Exception: return None

def _since_days(dt): return max((datetime.now(timezone.utc) - dt).days, 0) if dt else 0
def _fmt_days(n):
    last, last2 = n % 10, n % 100
    if last == 1 and last2 != 11: suf = "день"
    elif 2 <= last <= 4 and not (12 <= last2 <= 14): suf = "дня"
    else: suf = "дней"
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
    if not ts: return "—"
    try: dt = datetime.fromtimestamp(ts, timezone.utc)
    except Exception: return "—"
    now = datetime.now(timezone.utc); today = now.date(); d = dt.date(); hm = dt.strftime("%H:%M")
    if d == today: return f"Сегодня · {hm}"
    if (today - d).days == 1: return f"Вчера · {hm}"
    return dt.strftime("%d.%m · %H:%M")

def _draw_role_badge(d, img, x, y, w, h, role_key: str):
    has_role = role_key not in ("none", ""); c1, c2 = ROLE_GRADIENTS.get(role_key, ROLE_GRADIENTS["none"]); label = ROLE_INFO.get(role_key, ROLE_INFO["none"]).upper()
    if has_role:
        _gradient_box(img, (x, y, x + w, y + h), c1, c2, alpha=25, radius=11); _draw_gradient_border_rect(d, x, y, x + w, y + h, 11, c1, c2, width=2)
        text_color = _lerp_color(c1, c2, 0.5); icon_code = I_CROWN
    else:
        _draw_dashed_rect(d, (x, y, x + w, y + h), 11, (51, 51, 51), dash=8, gap=5, width=2); text_color = DARK; icon_code = I_CIRCLE_M
    icon_size, gap = 14, 9; tw_ = _tw(d, label, _font(11)); start_x = x + (w - (icon_size + gap + tw_)) // 2; cy = y + h // 2
    _icon(d, start_x + icon_size // 2, cy + 1, icon_code, 13, text_color); d.text((start_x + icon_size + gap, cy), label, font=_font(11), fill=text_color, anchor="lm")

def _draw_clan_badge(d, img, x, y, w, h, clan: Optional[dict]):
    if not clan:
        _draw_dashed_rect(d, (x, y, x + w, y + h), 11, (51, 51, 51), dash=8, gap=5, width=2); label = "БЕЗ КЛАНА"; icon_code = I_CIRCLE_M; text_color = DARK; icon_size, gap = 14, 9
        tw_ = _tw(d, label, _font(11)); start_x = x + (w - (icon_size + gap + tw_)) // 2; cy = y + h // 2
        _icon(d, start_x + icon_size // 2, cy + 1, icon_code, 13, text_color); d.text((start_x + icon_size + gap, cy), label, font=_font(11), fill=text_color, anchor="lm")
        return
    clan_data = next((c for c in CLANS_DATA if c["id"] == clan["id"]), None)
    if clan_data:
        c1, c2 = _hex_to_rgb(clan_data.get("color", 0xb3e1b9)), _hex_to_rgb(clan_data.get("color_dark", clan_data.get("color", 0xb3e1b9))); _clan_name = clan_data.get("name", "")
        clan_icon = I_STAR if _clan_name == "Сияние" else 0xf11b if _clan_name == "Мультяшности" else I_GEM
    else: c1 = _hex_to_rgb(clan.get("color", 0xb3e1b9)); c2 = c1; clan_icon = I_GEM
    label = clan["name"].upper()
    _gradient_box(img, (x, y, x + w, y + h), c1, c2, alpha=30, radius=11); _draw_gradient_border_rect(d, x, y, x + w, y + h, 11, c1, c2, width=2)
    text_color = _lerp_color(c1, c2, 0.5); icon_size, gap = 14, 9; tw_ = _tw(d, label, _font(11)); start_x = x + (w - (icon_size + gap + tw_)) // 2; cy = y + h // 2
    _icon(d, start_x + icon_size // 2, cy + 1, clan_icon, 13, text_color); d.text((start_x + icon_size + gap, cy), label, font=_font(11), fill=text_color, anchor="lm")

def _draw_stat(d, x, y, w, h, icon_code, icon_bg, icon_color, lbl, val, val_color, val_suffix=None):
    d.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    ib_size, ib_x, ib_y = 44, x + 18, y + 16; d.rounded_rectangle((ib_x, ib_y, ib_x + ib_size, ib_y + ib_size), radius=12, fill=icon_bg + (255,))
    _icon(d, ib_x + ib_size // 2, ib_y + ib_size // 2 + 1, icon_code, 19, icon_color)
    lbl_y = ib_y + ib_size + 10; d.text((x + 18, lbl_y), lbl, font=_font(10), fill=MUTED)
    val_y = lbl_y + 15; val_f = _font(30); val_str = val
    while _tw(d, val_str, val_f) > w - 36 - 40 and val_f.size > 18: val_f = _font(val_f.size - 2)
    d.text((x + 18, val_y), val_str, font=val_f, fill=val_color)
    if val_suffix: vw = _tw(d, val_str, val_f); d.text((x + 18 + vw + 7, val_y + val_f.size - 19), val_suffix, font=_font(14), fill=MUTED)

def _draw_operation_row(d, x, y, w, h, op: Optional[dict]):
    d.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    if not op:
        _icon(d, x + 44, y + h // 2, I_CIRCLE_M, 20, DARK); d.text((x + 44 + 30, y + h // 2), "—", font=_font(16), fill=DARK, anchor="lm"); return
    amt = op.get("amount", 0); reason = op.get("reason", "—") or "—"; ts = op.get("date", 0)
    is_plus = amt >= 0; accent = GREEN if is_plus else RED; accent_bg = GREEN_BG if is_plus else RED_BG; sign = "+" if is_plus else "−"
    d.rounded_rectangle((x, y, x + 4, y + h), radius=4, fill=accent + (255,))
    op_icon_size = 44; ib_x = x + 14; ib_y = y + (h - op_icon_size) // 2
    d.rounded_rectangle((ib_x, ib_y, ib_x + op_icon_size, ib_y + op_icon_size), radius=11, fill=accent_bg + (255,)); _icon(d, ib_x + op_icon_size // 2, ib_y + op_icon_size // 2 + 1, _op_icon(reason), 18, accent)
    text_x = ib_x + op_icon_size + 14; name_f, time_f = _font(15), _font(11)
    amt_str = f"{sign}{abs(int(amt))} DC"; amt_f = _font(18); amt_w = _tw(d, amt_str, amt_f); tag_str = "ДОХОД" if is_plus else "РАСХОД"; tag_f = _font(9); tag_w = _tw(d, tag_str, tag_f)
    right_block_w = max(amt_w, tag_w); right_x = x + w - 18 - right_block_w
    name_shown = _ellipsis(d, reason, name_f, right_x - 16 - text_x); name_y = y + h // 2 - 18; d.text((text_x, name_y), name_shown, font=name_f, fill=TEXT_SOFT)
    d.text((text_x, name_y + 20), _op_time_str(ts).upper(), font=time_f, fill=DIM)
    amt_y = y + h // 2 - 20; d.text((x + w - 18 - amt_w, amt_y), amt_str, font=amt_f, fill=accent); d.text((x + w - 18 - tag_w, amt_y + 26), tag_str, font=tag_f, fill=(accent[0] // 2 + 20, accent[1] // 2 + 20, accent[2] // 2 + 20))

def generate_profile_card(user_name: str, user_id: int, avatar_bytes: Optional[bytes], role_key: str, reviews: int, balance: int, joined_at: Optional[datetime], history: List[Dict]) -> io.BytesIO:
    if user_id in EXEMPT_USERS: role_key = "pka"
    user_name = sanitize(user_name, fallback=f"User {user_id}"); c1, c2 = ROLE_GRADIENTS.get(role_key, ROLE_GRADIENTS["none"])
    W, H, PAD_X, PAD_Y = 1800, 1000, 56, 44
    img = Image.new("RGBA", (W, H), BG + (255,)); d = ImageDraw.Draw(img); d.rounded_rectangle((0, 0, W - 1, H - 1), radius=30, fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)
    hx, hy, logo_size = PAD_X, PAD_Y, 54
    d.rounded_rectangle((hx, hy, hx + logo_size, hy + logo_size), radius=14, fill=(58, 58, 64) + (255,)); _icon(d, hx + logo_size // 2, hy + logo_size // 2 + 1, I_USERS, 26, (232, 232, 236))
    brand_x = hx + logo_size + 18; d.text((brand_x, hy + 4), "DIAMOND", font=_font(26), fill=TEXT); d.text((brand_x + 2, hy + 38), "SHOP & ECOSYSTEM", font=_font(11), fill=MUTED)
    meta_r = W - PAD_X; lbl, id_str = "ПРОФИЛЬ ПОКУПАТЕЛЯ", f"#{user_id}"; w1, w2 = _tw(d, lbl, _font(11)), _tw(d, id_str, _font(20))
    d.text((meta_r - w1, hy + 12), lbl, font=_font(11), fill=MUTED); d.text((meta_r - w2, hy + 32), id_str, font=_font(20), fill=TEXT)
    sep_y = hy + logo_size + 16; d.line((PAD_X, sep_y, W - PAD_X, sep_y), fill=STACK_HDR + (255,), width=2)
    body_y = sep_y + 24; body_h = H - PAD_Y - body_y; left_w, gap = 400, 30; left_x1, left_x2 = PAD_X, left_x1 + left_w; right_x1, right_x2 = left_x2 + gap, W - PAD_X
    _draw_stack_panel(img, d, (left_x1, body_y, left_x2 - 12, body_y + body_h - 12), radius=22)
    lp_x1, lp_y1, lp_x2, lp_y2 = left_x1, body_y, left_x2 - 12, body_y + body_h - 12; lp_cx = (lp_x1 + lp_x2) // 2
    d.text((lp_cx, lp_y1 + 24), "ПРОФИЛЬ", font=_font(11), fill=DIM, anchor="mm")
    av_size, ring_width, badge_w, badge_h, badge_gap, uid_h = 150, 5, 290, 42, 8, 16
    group_h = av_size + 14 + badge_h + badge_gap + badge_h + 12 + uid_h; avail_top, avail_bottom = lp_y1 + 54, lp_y2 - 26; group_start_y = avail_top + max(((avail_bottom - avail_top) - group_h) // 2, 0)
    av_x, av_y = lp_cx - av_size // 2, group_start_y; av_img = _avatar_img(avatar_bytes, av_size) if avatar_bytes else None
    if av_img: _draw_gradient_ring(d, lp_cx, av_y + av_size // 2, av_size // 2 + ring_width // 2, ring_width, c1, c2, steps=240); img.paste(av_img, (av_x, av_y), av_img)
    else: d.ellipse((av_x, av_y, av_x + av_size, av_y + av_size), fill=(60, 60, 66)); _icon(d, lp_cx, av_y + av_size // 2 + 2, I_USERS, 60, MUTED); _draw_gradient_ring(d, lp_cx, av_y + av_size // 2, av_size // 2 + ring_width // 2, ring_width, c1, c2, steps=240)
    badge_x = lp_cx - badge_w // 2; role_y = av_y + av_size + 14; _draw_role_badge(d, img, badge_x, role_y, badge_w, badge_h, role_key)
    clan_y = role_y + badge_h + badge_gap; clan = get_user_clan(user_id) if get_user_clan else None; _draw_clan_badge(d, img, badge_x, clan_y, badge_w, badge_h, clan)
    uid_text, uid_f = f"UID · {user_id}", _font(11); uid_w = _tw(d, uid_text, uid_f); uid_y = clan_y + badge_h + 12; d.text((lp_cx - uid_w // 2, uid_y), uid_text, font=uid_f, fill=MUTED)
    _draw_stack_panel(img, d, (right_x1, body_y, right_x2 - 12, body_y + body_h - 12), radius=22)
    rp_x1, rp_x2, rp_y = right_x1 + 28, right_x2 - 12 - 28, body_y + 22
    uname = _ellipsis(d, user_name, _font(42), rp_x2 - rp_x1); d.text((rp_x1, rp_y), uname, font=_font(42), fill=TEXT)
    sep2_y = rp_y + 56; d.line((rp_x1 - 28, sep2_y, rp_x2 + 28, sep2_y), fill=STACK_HDR + (255,), width=2)
    st_y = sep2_y + 18; _icon(d, rp_x1 + 6, st_y + 7, I_CHART, 12, SILVER); d.text((rp_x1 + 20, st_y), "СТАТИСТИКА", font=_font(10), fill=MUTED)
    stats_y, stat_h, stat_gap = st_y + 28, 128, 14; stat_w = (rp_x2 - rp_x1 - stat_gap * 2) // 3; days_n = _since_days(joined_at) if joined_at else 0
    _draw_stat(d, rp_x1, stats_y, stat_w, stat_h, I_THUMBS, GOLD_BG, GOLD, "ОТЗЫВОВ", str(reviews), TEXT)
    _draw_stat(d, rp_x1 + stat_w + stat_gap, stats_y, stat_w, stat_h, I_GEM, GREEN_BG, GREEN, "БАЛАНС", _fmt(balance), GREEN, val_suffix="DC")
    _draw_stat(d, rp_x1 + (stat_w + stat_gap) * 2, stats_y, stat_w, stat_h, I_CLOCK, BLUE_BG, BLUE, "ДНЕЙ В КОМЬЮНИТИ", str(days_n), TEXT, val_suffix=_fmt_days(days_n).split(" ", 1)[1] if days_n else "")
    cp_title_y = stats_y + stat_h + 18; _icon(d, rp_x1 + 6, cp_title_y + 7, I_SHIELD, 12, SILVER); d.text((rp_x1 + 20, cp_title_y), "ПРОГРЕСС В КЛАНЕ", font=_font(10), fill=MUTED)
    cp_y, cp_h = cp_title_y + 28, 78; clan_color = (179, 157, 219)
    if clan:
        clan_data = next((c for c in CLANS_DATA if c["id"] == clan["id"]), None)
        if clan_data: clan_color = _hex_to_rgb(clan_data.get("color", 0xb3e1b9))
    d.rounded_rectangle((rp_x1, cp_y, rp_x2, cp_y + cp_h), radius=14, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2); d.rounded_rectangle((rp_x1, cp_y, rp_x1 + 4, cp_y + cp_h), radius=4, fill=clan_color + (255,))
    my_rank, my_contrib, to_top3 = None, 0, 0
    if clan:
        try:
            from clan.core import get_clan_top, get_user_contribution
            top_full = get_clan_top(clan["id"], limit=1000); my_contrib = get_user_contribution(user_id)
            for idx, t in enumerate(top_full, 1):
                if t["user_id"] == user_id: my_rank = idx; break
            if top_full and len(top_full) >= 3 and my_rank and my_rank > 3: to_top3 = max(top_full[2]["total"] - my_contrib + 1, 0)
        except Exception: pass
    cell_w = (rp_x2 - rp_x1) // 3
    for idx, (lbl, val, color) in enumerate([("МЕСТО В КЛАНЕ", f"#{my_rank}" if my_rank else "—", SILVER), ("ВКЛАД ЗА СЕЗОН", f"{my_contrib} DC", GREEN), ("ДО ТОП-3", f"{to_top3} DC" if to_top3 else "—", BLUE)]):
        cx, cy = rp_x1 + 16 + idx * cell_w, cp_y + 14; d.text((cx, cy), lbl, font=_font(9), fill=MUTED); d.text((cx, cy + 16), val, font=_font(20), fill=color)
    op_title_y = cp_y + cp_h + 18; _icon(d, rp_x1 + 6, op_title_y + 7, I_ROTATE, 12, SILVER); d.text((rp_x1 + 20, op_title_y), "ПОСЛЕДНИЕ ОПЕРАЦИИ", font=_font(10), fill=MUTED)
    ops_y, ops_bottom = op_title_y + 28, lp_y2 - 22; ops_area_h = ops_bottom - ops_y; ops_gap = 8; op_h = (ops_area_h - ops_gap * 3) // 4
    ops = list((history or [])[-4:])
    while len(ops) < 4: ops.insert(0, None)
    for i, op in enumerate(ops[-4:]): _draw_operation_row(d, rp_x1, ops_y + i * (op_h + ops_gap), rp_x2 - rp_x1, op_h, op)
    buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf

# ============================================================
# РЕНДЕР: СЧЁТ (из tickets.py)
# ============================================================
REQUISITES = [("Т-Банк", "2200 7020 8029 9345", I_BUILDING), ("АльфаБанк", "2200 1545 6426 7465", I_BUILDING), ("ОзонБанк", "2204 3204 4881 5151", I_BUILDING), ("СБП", "+7 983 694 76 41", I_MOBILE)]

def generate_receipt_png(manager_name: str, customer_name: str, product_name: str, amount: int, discount_percent: int = 0, order_id: Optional[str] = None) -> io.BytesIO:
    manager_name, customer_name, product_name = sanitize(manager_name, "Менеджер"), sanitize(customer_name, "Заказчик"), sanitize(product_name, "Товар")
    if order_id is None: order_id = f"D-{int(time.time())}-{random.randint(100, 999)}"
    deadline_str = (datetime.now(MSK) + timedelta(hours=1)).strftime("%d.%m.%Y · %H:%M МСК"); total = max(amount - int(amount * discount_percent / 100), 0)
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,)); d = ImageDraw.Draw(img); d.rounded_rectangle((M, M, CANVAS_W - 1 - M, CANVAS_H - 1 - M), radius=28, fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)
    hx, hy, logo_size = PAD_X, PAD_Y, 68
    _gradient_box(img, (hx, hy, hx + logo_size, hy + logo_size), (74, 74, 82), (42, 42, 48), alpha=255, radius=18); d.rounded_rectangle((hx, hy, hx + logo_size, hy + logo_size), radius=18, outline=(90, 90, 98) + (255,), width=2); _icon(d, hx + logo_size // 2, hy + logo_size // 2 + 1, I_RECEIPT, 32, SILVER_HI)
    bx = hx + logo_size + 20; d.text((bx, hy + 6), "DIAMOND", font=_font(34), fill=TEXT); d.text((bx + 4, hy + 48), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)
    meta_r = CANVAS_W - M - PAD_X; lbl_w = _tw(d, "СЧЁТ НА ОПЛАТУ", _font(14)); d.text((meta_r - lbl_w, hy + 8), "СЧЁТ НА ОПЛАТУ", font=_font(14), fill=MUTED)
    num_w = _tw(d, f"№ {order_id}", _font(24)); d.text((meta_r - num_w, hy + 34), f"№ {order_id}", font=_font(24), fill=TEXT)
    sep_y = hy + logo_size + 22; d.line((PAD_X, sep_y, CANVAS_W - M - PAD_X, sep_y), fill=STACK_HDR + (255,), width=2)
    body_y = sep_y + 10; top_h, info_w, gap_top = 200, 500, 24; top_y1, top_y2 = body_y, body_y + top_h; hero_x1, hero_x2 = PAD_X, CANVAS_W - PAD_X - info_w - gap_top; info_x1, info_x2 = hero_x2 + gap_top, CANVAS_W - PAD_X
    _gradient_box(img, (hero_x1, top_y1, hero_x2, top_y2), GREEN, GREEN, alpha=18, radius=22); d.rounded_rectangle((hero_x1, top_y1, hero_x2, top_y2), radius=22, outline=GREEN + (160,), width=3)
    icon_size, icon_x1, icon_y1 = 110, hero_x1 + 40, top_y1 + (top_h - 110) // 2
    for i, a in enumerate([35, 50, 65]): _alpha_fill(img, (icon_x1 + icon_size // 2 - (icon_size + 30 - i * 10) // 2, icon_y1 + icon_size // 2 - (icon_size + 30 - i * 10) // 2, icon_x1 + icon_size // 2 + (icon_size + 30 - i * 10) // 2, icon_y1 + icon_size // 2 + (icon_size + 30 - i * 10) // 2), GREEN, alpha=a, radius=(icon_size + 30 - i * 10) // 2)
    _alpha_fill(img, (icon_x1, icon_y1, icon_x1 + icon_size, icon_y1 + icon_size), GREEN, alpha=70, radius=26); d.rounded_rectangle((icon_x1, icon_y1, icon_x1 + icon_size, icon_y1 + icon_size), radius=26, outline=GREEN + (230,), width=3); _icon(d, icon_x1 + icon_size // 2, icon_y1 + icon_size // 2 + 1, I_CHECK, 52, GREEN)
    tx = icon_x1 + icon_size + 34; d.text((tx, top_y1 + 40), "ИТОГО К ОПЛАТЕ", font=_font(15), fill=GREEN)
    sum_str, sum_font = _fmt(total), _font(90); sum_w = _tw(d, sum_str, sum_font); d.text((tx, top_y1 + 68), sum_str, font=sum_font, fill=TEXT); d.text((tx + sum_w + 16, top_y1 + 68 + 90 - 48), "Р", font=_font(36), fill=SILVER)
    _gradient_box(img, (info_x1, top_y1, info_x2, top_y2), SILVER, SILVER, alpha=10, radius=22); d.rounded_rectangle((info_x1, top_y1, info_x2, top_y2), radius=22, outline=INNER_BRD + (255,), width=2)
    pad_in = 22; info_in_x1, info_in_x2 = info_x1 + pad_in + 6, info_x2 - pad_in - 6; cur_y = top_y1 + 16
    def _info_row(label, value, value_color=TEXT):
        nonlocal cur_y; d.text((info_in_x1, cur_y), label.upper(), font=_font(11), fill=MUTED); val_w = _tw(d, value, _font(15)); d.text((info_in_x2 - val_w, cur_y - 2), value, font=_font(15), fill=value_color); cur_y += 30
    _info_row("Статус", "Заказ оформляется", GREEN); _info_row("Заказчик", f"@{customer_name}"); d.line((info_in_x1, cur_y + 2, info_in_x2, cur_y + 2), fill=INNER_BRD + (255,), width=1); cur_y += 12
    prod_shown = product_name
    if _tw(d, prod_shown, _font(15)) > (info_in_x2 - info_in_x1) - 100:
        while prod_shown and _tw(d, prod_shown + "…", _font(15)) > (info_in_x2 - info_in_x1) - 100: prod_shown = prod_shown[:-1]
        prod_shown += "…"
    _info_row("Товар", prod_shown, SILVER_HI); _info_row("Сумма", f"{_fmt(amount)} Р", SILVER_HI); _info_row("Скидка", f"−{discount_percent}%" if discount_percent > 0 else "—", GREEN if discount_percent > 0 else DIM)
    req_y1, req_y2 = top_y2 + 20, top_y2 + 20 + 434; req_x1, req_x2 = PAD_X, CANVAS_W - M - PAD_X
    _gradient_box(img, (req_x1, req_y1, req_x2, req_y2), SILVER, SILVER, alpha=6, radius=22); d.rounded_rectangle((req_x1, req_y1, req_x2, req_y2), radius=22, outline=INNER_BRD + (255,), width=2)
    h3_y = req_y1 + 26; _icon(d, req_x1 + 30 + 12, h3_y + 9, I_CREDIT, 20, SILVER); d.text((req_x1 + 30 + 38, h3_y), "РЕКВИЗИТЫ ДЛЯ ОПЛАТЫ", font=_font(16), fill=SILVER)
    grid_x1, grid_x2 = req_x1 + 30, req_x2 - 30; cell_gap, cell_w, cell_h = 16, (grid_x2 - grid_x1 - 16) // 2, 130; grid_y1, grid_y2 = h3_y + 50, req_y2 - 30
    if grid_y2 - grid_y1 > cell_h * 2 + cell_gap: grid_y1 += ((grid_y2 - grid_y1) - (cell_h * 2 + cell_gap)) // 2
    for i, (bank_name, bank_num, bank_icon) in enumerate(REQUISITES):
        cx1, cy1 = grid_x1 + (i % 2) * (cell_w + cell_gap), grid_y1 + (i // 2) * (cell_h + cell_gap); cx2, cy2 = cx1 + cell_w, cy1 + cell_h
        d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=16, fill=(24, 24, 32) + (255,), outline=(40, 40, 47) + (255,), width=2)
        lx, ly = cx1 + 24, cy1 + (cell_h - 54) // 2; _gradient_box(img, (lx, ly, lx + 54, ly + 54), SILVER, SILVER, alpha=22, radius=14); d.rounded_rectangle((lx, ly, lx + 54, ly + 54), radius=14, outline=SILVER + (130,), width=2); _icon(d, lx + 27, ly + 27 + 1, bank_icon, 24, SILVER_HI)
        info_x, info_cy = lx + 54 + 20, cy1 + cell_h // 2; d.text((info_x, info_cy - 26), bank_name.upper(), font=_font(13), fill=MUTED); d.text((info_x, info_cy - 2), bank_num, font=_font(20), fill=TEXT)
    bot_y1, bot_y2 = req_y2 + 20, req_y2 + 120; bot_x1, bot_x2 = PAD_X, CANVAS_W - M - PAD_X
    _alpha_fill(img, (bot_x1, bot_y1, bot_x2, bot_y2), GOLD, alpha=22, radius=14); d.rounded_rectangle((bot_x1, bot_y1, bot_x2, bot_y2), radius=14, outline=GOLD + (140,), width=2)
    bot_cy = (bot_y1 + bot_y2) // 2; _icon(d, bot_x1 + 34, bot_cy, I_CLOCK, 22, GOLD); d.text((bot_x1 + 34 + 28, bot_cy), f"Оплатить до: {deadline_str} · после оплаты пришлите чек в тикет", font=_font(15), fill=TEXT_SOFT, anchor="lm")
    steps = ["Оплата", "Чек", "Проверка", "Готово"]; step_widths = [26 + 8 + _tw(d, name, _font(13)) for name in steps]; total_steps_w = sum(step_widths) + 18 * 3; cur_x = bot_x2 - 28 - total_steps_w
    for i, name in enumerate(steps):
        is_active = (i == 0); _alpha_fill(img, (cur_x, bot_cy - 13, cur_x + 26, bot_cy + 13), GREEN, alpha=65, radius=13) if is_active else d.rounded_rectangle((cur_x, bot_cy - 13, cur_x + 26, bot_cy + 13), radius=13, fill=(40, 40, 47) + (255,))
        d.rounded_rectangle((cur_x, bot_cy - 13, cur_x + 26, bot_cy + 13), radius=13, outline=GREEN + (230,) if is_active else (40, 40, 47) + (255,), width=2)
        num_str = str(i + 1); nw = _tw(d, num_str, _font(12)); d.text((cur_x + 13 - nw // 2, bot_cy - 12 + 12 - 7), num_str, font=_font(12), fill=GREEN if is_active else (184, 188, 200))
        d.text((cur_x + 26 + 8, bot_cy), name, font=_font(13), fill=GREEN if is_active else MUTED, anchor="lm"); cur_x += step_widths[i] + 18
    footer_y = CANVAS_H - PAD_Y + 6; d.line((PAD_X, footer_y - 12, CANVAS_W - M - PAD_X, footer_y - 12), fill=STACK_HDR + (255,), width=2)
    d.text((PAD_X, footer_y), "Счёт сгенерирован автоматически · Diamond Shop", font=_font(13), fill=DIM); rw = _tw(d, "Шаг 1 · Оплата", _font(13)); d.text((CANVAS_W - M - PAD_X - rw, footer_y), "Шаг 1 · Оплата", font=_font(13), fill=DIM)
    buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf

def generate_receipt_id() -> str: return f"D-{int(time.time())}-{random.randint(100, 999)}"

# ============================================================
# ВЬЮ И МОДАЛКИ (из tickets.py)
# ============================================================
EMOJI_BANKS, EMOJI_PHONE = PartialEmoji(name="banks", id=1556311895106003075), PartialEmoji(name="phone", id=1556311870627905657)
REQ_OPTIONS = {
    "tbank": {"label": "Т-Банк", "description": "Перевод на карту Т-Банк", "emoji": EMOJI_BANKS, "title": "Т-Банк", "value": "2200 7020 8029 9345", "type": "Карта"},
    "sbp": {"label": "СБП", "description": "Система быстрых платежей · телефон", "emoji": EMOJI_PHONE, "title": "СБП", "value": "+7 983 694 76 41", "type": "Телефон"},
    "ozon": {"label": "ОзонБанк", "description": "Перевод на карту ОзонБанк", "emoji": EMOJI_BANKS, "title": "ОзонБанк", "value": "2204 3204 4881 5151", "type": "Карта"},
    "alfa": {"label": "АльфаБанк", "description": "Перевод на карту АльфаБанк", "emoji": EMOJI_BANKS, "title": "АльфаБанк", "value": "2200 1545 6426 7465", "type": "Карта"},
}

class ReceiptSelect(Select):
    def __init__(self):
        super().__init__(placeholder="Выберите банк для оплаты...", min_values=1, max_values=1, options=[SelectOption(label=data["label"], description=data["description"], emoji=data["emoji"], value=key) for key, data in REQ_OPTIONS.items()], custom_id="receipt:req_select")
    async def callback(self, inter: disnake.MessageInteraction):
        key = inter.data.values[0]; data = REQ_OPTIONS.get(key)
        if not data: return await inter.response.send_message("❌ Реквизит не найден.", ephemeral=True)
        try:
            e1 = disnake.Embed(color=6776679).set_image(url=IMG_STRIPE)
            e2 = disnake.Embed(title=f"{data['title']} · {data['type']}", description=f"> **Номер для перевода:**\n> `{data['value']}`\n\n> Нажми на номер — он скопируется.", color=6776679).set_image(url=IMG_STRIPE).set_footer(text="Нажми на номер — он скопируется")
            await inter.response.send_message(embeds=[e1, e2], ephemeral=True)
        except Exception as e: logger.warning(f"ReceiptSelect: {e}")

class ReceiptView(View):
    def __init__(self): super().__init__(timeout=None); self.add_item(ReceiptSelect())

def _draw_policy_block(img, d, x, y, w, h, color, icon_code, title, text):
    border = tuple(min(int(c + (255 - c) * 0.25), 255) for c in color); d.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2); d.rounded_rectangle((x, y + 10, x + 5, y + h - 10), radius=2, fill=color + (255,))
    _alpha_fill(img, (x + 22, y + 18, x + 74, y + 70), color, alpha=65, radius=13); d.rounded_rectangle((x + 22, y + 18, x + 74, y + 70), radius=13, outline=color + (210,), width=2); _icon(d, x + 48, y + 45, icon_code, 24, color)
    tx = x + 74 + 18; d.text((tx, y + 22), title.upper(), font=_font(16), fill=color); lines = _wrap(d, text, _font(14), x + w - 24 - tx, max_lines=3)
    for i, line in enumerate(lines): d.text((tx, y + 48 + i * 22), line, font=_font(14), fill=TEXT_SOFT)

def _draw_left_block(img, d, x, y, w, h, color, icon_code, label, value):
    border = tuple(min(int(c + (255 - c) * 0.25), 255) for c in color); light = tuple(min(int(c + (255 - c) * 0.45), 255) for c in color)
    _gradient_box(img, (x, y, x + w, y + h), color, color, alpha=30, radius=15); d.rounded_rectangle((x, y, x + w, y + h), radius=15, outline=border + (255,), width=3); d.rounded_rectangle((x + 4, y + 12, x + 8, y + h - 12), radius=2, fill=color + (255,))
    _alpha_fill(img, (x + 20, y + (h - 54)//2, x + 74, y + (h + 54)//2), color, alpha=70, radius=14); d.rounded_rectangle((x + 20, y + (h - 54)//2, x + 74, y + (h + 54)//2), radius=14, outline=border + (200,), width=2); _icon(d, x + 47, y + h//2, icon_code, 24, color)
    tx = x + 74 + 16; d.text((tx, y + 16), label.upper(), font=_font(13), fill=light); d.text((tx, y + 44), _ellipsis(d, value, _font(22), x + w - 18 - tx), font=_font(22), fill=color)

def _draw_left_panel_rating(img, d, box, top_icon, top_label, top_value, blocks):
    _draw_stack_panel(img, d, box, radius=22); x1, y1, x2, y2 = box; pad = 28
    _gradient_box(img, (x1 + pad, y1 + pad, x1 + pad + 84, y1 + pad + 84), SILVER, SILVER_DIM, alpha=42, radius=22); d.rounded_rectangle((x1 + pad, y1 + pad, x1 + pad + 84, y1 + pad + 84), radius=22, outline=SILVER + (200,), width=3); _icon(d, x1 + pad + 42, y1 + pad + 43, top_icon, 34, SILVER_HI)
    lbl_x = x1 + pad + 84 + 20; d.text((lbl_x, y1 + pad + 8), top_label.upper(), font=_font(14), fill=MUTED); val_font = _font(34)
    while _tw(d, str(top_value), val_font) > x2 - pad - lbl_x - 16 and val_font.size > 20: val_font = _font(val_font.size - 2)
    d.text((lbl_x, y1 + pad + 32), str(top_value), font=val_font, fill=TEXT)
    sep_y = y1 + pad + 84 + 26; d.line((x1 + pad, sep_y, x2 - pad, sep_y), fill=STACK_HDR + (255,), width=2)
    if blocks:
        for i, blk in enumerate(blocks): _draw_left_block(img, d, x1 + pad, sep_y + 26 + i * (92 + 14), (x2 - pad) - (x1 + pad), 92, blk["color"], blk["icon"], blk["label"], blk["value"])

def render_policy(user_id: int) -> io.BytesIO:
    img, d = base_canvas(uid_label="политика магазина", status_label="действует с 26.07.26", logo_icon=I_GEM)
    body_y, body_h = 140, CANVAS_H - M - PAD_Y - 140 - 26; left_w, gap = 460, 30; left_x1, left_x2 = PAD_X, PAD_X + left_w; right_x1, right_x2 = left_x2 + gap, CANVAS_W - M - PAD_X
    _draw_left_panel_rating(img, d, (left_x1, body_y, left_x2, body_y + body_h), top_icon=I_RECEIPT, top_label="Документ", top_value="Политика", blocks=[{"color": BLUE, "icon": I_CLOCK, "label": "Срок обработки", "value": "до 2 дней"}, {"color": RED, "icon": I_ROTATE, "label": "Возврат", "value": "50% от суммы"}, {"color": GREEN, "icon": I_SHIELD, "label": "Гарантия", "value": "100% выдача"}])
    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22); rx1, rx2 = right_x1 + 30, right_x2 - 30; draw_right_head(d, rx1, body_y + 22, rx2, "Политика покупки", "читай внимательно")
    items_y, items_bottom, n, gap_item = body_y + 118, body_y + body_h - 22 - 60, 4, 12; item_h = (items_bottom - items_y - gap_item * (n - 1)) // n
    rules = [{"color": BLUE, "icon": I_CLOCK, "title": "Сроки обработки заказа", "text": "Максимальный срок — 2 рабочих дня с момента подтверждения оплаты. В большинстве случаев товар выдаётся в течение 3 часов. Часовой пояс продавца — МСК+5 (UTC+8)."}, {"color": RED, "icon": I_ROTATE, "title": "Возврат средств", "text": "Если вы отказываетесь после оплаты — возврат 50% от суммы. 50% удерживаются для покрытия комиссий платёжных систем и обработки."}, {"color": GOLD, "icon": I_BAN, "title": "Стоп-лист", "text": "Массовые пинги персонала, продавца или менеджеров, а также агрессивное поведение переводят тикет в «стоп-лист». Такие заказы обрабатываются в последнюю очередь."}, {"color": GREEN, "icon": I_CHECK, "title": "Подтверждение оплаты", "text": "Для подтверждения необходимо прикрепить чек оплаты и указать, куда перевод был сделан. После проверки менеджер подтвердит оплату — и продавец начнёт работу."}]
    for i, rule in enumerate(rules): _draw_policy_block(img, d, rx1, items_y + i * (item_h + gap_item), rx2 - rx1, item_h, rule["color"], rule["icon"], rule["title"], rule["text"])
    hint_h, hint_y = 48, items_bottom + 12; _alpha_fill(img, (rx1, hint_y, rx2, hint_y + hint_h), GOLD, alpha=22, radius=11); d.rounded_rectangle((rx1, hint_y, rx2, hint_y + hint_h), radius=11, outline=GOLD + (150,), width=2); _icon(d, rx1 + 24, hint_y + hint_h // 2, I_INFO, 18, GOLD); d.text((rx1 + 48, hint_y + hint_h // 2 - 9), "Незнание политики не освобождает от ответственности. Действует с 26.07.26", font=_font(14), fill=TEXT_SOFT)
    draw_footer(d, f"Политика магазина · данные на {_now_msk_str()} МСК", "политика · v1.0")
    buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf

async def show_policy(inter: disnake.MessageInteraction):
    if not inter.response.is_done():
        try: await inter.response.defer(ephemeral=True)
        except Exception: pass
    try:
        buf = await asyncio.to_thread(render_policy, inter.author.id); fname = f"policy_{inter.author.id}.png"; file = disnake.File(buf, filename=fname); embed = disnake.Embed(color=6776679); embed.set_image(url=f"attachment://{fname}")
        await inter.followup.send(embed=embed, file=file, ephemeral=True)
    except Exception as e:
        try: await inter.followup.send(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
        except Exception: pass

# ============================================================
# БЛОК 4: КОДЕКС МАГАЗИНА
# ============================================================
SALARY_ROLES = [{"role_id": 1471844291595731016, "name": "Control Diamond", "tag": "CONTROL", "advance": 750, "salary": 1750, "color": (0xcd, 0xce, 0xd1), "icon": I_CROWN}, {"role_id": 1513935883475226796, "name": "Assistant", "tag": "ASSIST", "advance": 550, "salary": 1250, "color": (0xbe, 0x85, 0x85), "icon": I_USER_TIE}, {"role_id": 1154757071330365490, "name": "Sales Manager", "tag": "SALES", "advance": 550, "salary": 1250, "color": (0x39, 0xf4, 0x7b), "icon": I_HAND}, {"role_id": 1457964854441672806, "name": "Advertiser", "tag": "ADVERT", "advance": 375, "salary": 875, "color": (0xb1, 0xc5, 0xf6), "icon": I_SEARCH}]

def _draw_left_panel_work(img, d, box, extra_blocks=None, header_icon=I_GEM):
    _draw_stack_panel(img, d, box, radius=22); x1, y1, x2, y2 = box; pad = 28
    _gradient_box(img, (x1 + pad, y1 + pad, x1 + pad + 96, y1 + pad + 96), SILVER, SILVER_DIM, alpha=42, radius=24); d.rounded_rectangle((x1 + pad, y1 + pad, x1 + pad + 96, y1 + pad + 96), radius=24, outline=SILVER + (200,), width=3); _icon(d, x1 + pad + 48, y1 + pad + 49, header_icon, 40, SILVER_HI)
    lbl_x = x1 + pad + 96 + 22; d.text((lbl_x, y1 + pad + 14), "КОДЕКС", font=_font(14), fill=MUTED); d.text((lbl_x, y1 + pad + 38), "МАГАЗИНА", font=_font(22), fill=TEXT)
    sep_y = y1 + pad + 96 + 26; d.line((x1 + pad, sep_y, x2 - pad, sep_y), fill=STACK_HDR + (255,), width=2)
    if extra_blocks:
        for i, blk in enumerate(extra_blocks):
            by1, by2 = sep_y + 26 + i * (92 + 12), sep_y + 26 + i * (92 + 12) + 92; bx1, bx2 = x1 + pad, x2 - pad; base_color = blk.get("color", SILVER); text_color = _lighten(base_color, 0.45); border_color = _lighten(base_color, 0.25)
            _gradient_box(img, (bx1, by1, bx2, by2), base_color, base_color, alpha=30, radius=15); d.rounded_rectangle((bx1, by1, bx2, by2), radius=15, outline=border_color + (255,), width=3); d.rounded_rectangle((bx1 + 4, by1 + 12, bx1 + 8, by2 - 12), radius=2, fill=base_color + (255,))
            _alpha_fill(img, (bx1 + 20, by1 + (92 - 50) // 2, bx1 + 70, by1 + (92 + 50) // 2), base_color, alpha=70, radius=13); d.rounded_rectangle((bx1 + 20, by1 + (92 - 50) // 2, bx1 + 70, by1 + (92 + 50) // 2), radius=13, outline=border_color + (200,), width=2); _icon(d, bx1 + 45, by1 + 46, blk.get("icon", I_INFO), 24, base_color)
            tx = bx1 + 70 + 16; d.text((tx, by1 + 14), blk.get("label", "").upper(), font=_font(13), fill=text_color); d.text((tx, by1 + 42), _ellipsis(d, blk.get("value", "—"), _font(24), bx2 - 18 - tx), font=_font(24), fill=base_color)

def _draw_salary_card(img, d, x, y, w, h, role_data: dict):
    color, light, border = role_data["color"], _lighten(role_data["color"], 0.4), _lighten(role_data["color"], 0.2)
    d.rounded_rectangle((x - 3, y - 3, x + w + 3, y + h + 3), radius=19, fill=(8, 8, 10) + (255,)); _gradient_box(img, (x, y, x + w, y + h), color, color, alpha=28, radius=16); d.rounded_rectangle((x, y, x + w, y + h), radius=16, outline=border + (220,), width=3); d.rounded_rectangle((x + 6, y + 14, x + 11, y + h - 14), radius=2, fill=color + (255,))
    _alpha_fill(img, (x + 26, y + (h - 60) // 2, x + 86, y + (h + 60) // 2), color, alpha=75, radius=15); d.rounded_rectangle((x + 26, y + (h - 60) // 2, x + 86, y + (h + 60) // 2), radius=15, outline=light + (230,), width=3); _icon(d, x + 56, y + h // 2, role_data["icon"], 28, light)
    tx = x + 86 + 20; d.text((tx, y + h // 2 - 26), role_data["name"].upper(), font=_font(24), fill=light); tag_font = _font(11); tag_w = _tw(d, role_data["tag"], tag_font)
    _alpha_fill(img, (tx, y + h // 2 + 6, tx + tag_w + 20, y + h // 2 + 26), color, alpha=80, radius=6); d.rounded_rectangle((tx, y + h // 2 + 6, tx + tag_w + 20, y + h // 2 + 26), radius=6, outline=light + (200,), width=1); d.text((tx + 10, y + h // 2 + 10), role_data["tag"], font=tag_font, fill=light)
    right_x2, box_w, box_h, gap_inner = x + w - 24, 220, 62, 20; adv_x1, adv_y1 = right_x2 - 2 * box_w - gap_inner, y + (h - box_h) // 2
    _alpha_fill(img, (adv_x1, adv_y1, adv_x1 + box_w, adv_y1 + box_h), BLUE, alpha=40, radius=12); d.rounded_rectangle((adv_x1, adv_y1, adv_x1 + box_w, adv_y1 + box_h), radius=12, outline=BLUE + (200,), width=2); d.text((adv_x1 + 14, adv_y1 + 8), "АВАНС", font=_font(11), fill=_lighten(BLUE, 0.4)); d.text((adv_x1 + 14, adv_y1 + 26), _fmt(role_data["advance"]), font=_font(28), fill=SILVER_HI)
    sal_x1 = adv_x1 + box_w + gap_inner; _alpha_fill(img, (sal_x1, adv_y1, sal_x1 + box_w, adv_y1 + box_h), GREEN, alpha=45, radius=12); d.rounded_rectangle((sal_x1, adv_y1, sal_x1 + box_w, adv_y1 + box_h), radius=12, outline=GREEN + (200,), width=2); d.text((sal_x1 + 14, adv_y1 + 8), "ЗАРПЛАТА", font=_font(11), fill=_lighten(GREEN, 0.4)); d.text((sal_x1 + 14, adv_y1 + 26), _fmt(role_data["salary"]), font=_font(28), fill=SILVER_HI)

def render_work_salary(user_id: int) -> io.BytesIO:
    img, d = base_canvas(uid_label="кодекс · зарплата", logo_icon=I_GEM); body_y, body_h = 140, CANVAS_H - M - PAD_Y - 140 - 26; left_w, gap = 460, 30; left_x1, left_x2 = PAD_X, PAD_X + left_w; right_x1, right_x2 = left_x2 + gap, CANVAS_W - M - PAD_X
    _draw_left_panel_work(img, d, (left_x1, body_y, left_x2, body_y + body_h), extra_blocks=[{"label": "Дата аванса", "value": "15 число", "icon": I_CALENDAR, "color": BLUE}, {"label": "Дата зарплаты", "value": "29 число", "icon": I_CALENDAR, "color": GREEN}, {"label": "Ролей в системе", "value": f"{len(SALARY_ROLES)}", "icon": I_USERS, "color": SILVER}], header_icon=I_COINS)
    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22); rx1, rx2 = right_x1 + 30, right_x2 - 30; draw_right_head(d, rx1, body_y + 22, rx2, "Зарплата и аванс", "выплаты дважды в месяц")
    list_y, list_bottom, gap_card = body_y + 118, body_y + body_h - 22, 12; card_h = max((list_bottom - list_y - gap_card * (len(SALARY_ROLES) - 1)) // max(len(SALARY_ROLES), 1), 100)
    for i, role in enumerate(SALARY_ROLES): _draw_salary_card(img, d, rx1, list_y + i * (card_h + gap_card), rx2 - rx1, card_h, role)
    draw_footer(d, "Зарплата начисляется в Diamond Coins", "стр. 1 / 2"); buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf

def _draw_rule_card(img, d, x, y, w, h, rule: dict):
    color, light, border = rule["color"], _lighten(rule["color"], 0.4), _lighten(rule["color"], 0.2)
    d.rounded_rectangle((x - 3, y - 3, x + w + 3, y + h + 3), radius=19, fill=(8, 8, 10) + (255,)); _gradient_box(img, (x, y, x + w, y + h), color, color, alpha=18, radius=16); d.rounded_rectangle((x, y, x + w, y + h), radius=16, outline=border + (220,), width=3)
    _alpha_fill(img, (x + 24, y + 22, x + 84, y + 82), color, alpha=75, radius=15); d.rounded_rectangle((x + 24, y + 22, x + 84, y + 82), radius=15, outline=light + (230,), width=3); _icon(d, x + 54, y + 52, rule["icon"], 28, light)
    tx = x + 84 + 20; d.text((tx, y + 26), rule["title"].upper(), font=_font(22), fill=light); d.text((tx, y + 58), rule.get("subtitle", "").upper(), font=_font(12), fill=MUTED)
    lines = _wrap(d, rule["text"], _font(16), w - 48, max_lines=4)
    for i, line in enumerate(lines): d.text((x + 24, y + 100 + i * 24), line, font=_font(16), fill=TEXT_SOFT)
    if rule.get("example"):
        ex_y = y + 100 + len(lines) * 24 + 12; ex_w = _tw(d, rule["example"], _font(15)) + 60
        _alpha_fill(img, (x + 24, ex_y, x + 24 + ex_w, ex_y + 36), color, alpha=45, radius=9); d.rounded_rectangle((x + 24, ex_y, x + 24 + ex_w, ex_y + 36), radius=9, outline=light + (200,), width=2); _icon(d, x + 40, ex_y + 18, I_INFO, 14, light); d.text((x + 58, ex_y + 9), rule["example"], font=_font(15), fill=light)

def render_work_tickets(user_id: int) -> io.BytesIO:
    img, d = base_canvas(uid_label="кодекс · правила", logo_icon=I_GEM); body_y, body_h = 140, CANVAS_H - M - PAD_Y - 140 - 26; left_w, gap = 460, 30; left_x1, left_x2 = PAD_X, PAD_X + left_w; right_x1, right_x2 = left_x2 + gap, CANVAS_W - M - PAD_X
    _draw_left_panel_work(img, d, (left_x1, body_y, left_x2, body_y + body_h), extra_blocks=[{"label": "Строго для", "value": "Sales Manager", "icon": I_USER_TIE, "color": BLUE}, {"label": "Нарушение", "value": "выговор", "icon": I_XMARK, "color": RED}, {"label": "Обязательно", "value": "к прочтению", "icon": I_CHECK, "color": GREEN}], header_icon=I_BOOK)
    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22); rx1, rx2 = right_x1 + 30, right_x2 - 30; draw_right_head(d, rx1, body_y + 22, rx2, "Правила по тикетам", "регламент для sales manager")
    items_y, items_bottom, n, gap_item = body_y + 118, body_y + body_h - 22, 4, 12; item_h = max((items_bottom - items_y - gap_item * (n - 1)) // n, 140)
    rules = [{"icon": I_HAND, "title": "Вежливость и споры", "subtitle": "правило №1", "text": "Отвечаем вежливо, спорные ситуации решаем через главного администратора. Адекватность в тикетах должна быть всегда — если покупатель неадекватен, сообщить об этом старшему.", "color": GREEN}, {"icon": I_PEN, "title": "Название тикета", "subtitle": "правило №2", "text": "Название должно полностью отображать товар. Указываем по схеме Категория-Подкатегория-Подкатегория. Иные названия караются выговором.", "color": SILVER, "example": "Например: Дискорд-нитро-1м"}, {"icon": I_CHECK, "title": "Кнопка «Оплата»", "subtitle": "правило №3", "text": "Кнопкой «Оплата» можно пользоваться только после фактического подтверждения оплаты покупателем. До подтверждения — кнопка не нажимается.", "color": BLUE}, {"icon": I_XMARK, "title": "Ответственность", "subtitle": "правило №4", "text": "За нарушение любого из пунктов выше — выговор. Систематические нарушения ведут к снятию с должности Sales Manager.", "color": RED}]
    for i, rule in enumerate(rules): _draw_rule_card(img, d, rx1, items_y + i * (item_h + gap_item), rx2 - rx1, item_h, rule)
    draw_footer(d, "Обязательно к прочтению каждым менеджером", "стр. 2 / 2"); buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf
