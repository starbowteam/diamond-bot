# -*- coding: utf-8 -*-
"""Pillow-рендер панели квестов. 3 колонки: Ежедневные / Недельные / Разовые. По 4 квеста в каждой."""
import io
import os
import math
from typing import List, Dict
from PIL import Image, ImageDraw
from core.render import *

DESC_GREY = (168, 174, 186)
GREEN_BG, PURPLE_BG, SILVER_BG = (18, 44, 28), (32, 26, 48), (34, 38, 48)

FA_MAP = {
    "fa-comment": I_COMMENT, "fa-microphone": I_MIC, "fa-dice": I_DICE, "fa-computer-mouse": I_MOUSE, "fa-cart-shopping": I_CART, "fa-comments": I_COMMENTS, "fa-headphones": I_HEADPH, "fa-dice-five": I_DICE5, "fa-sack-dollar": I_SACK, "fa-trophy": I_TROPHY, "fa-star": I_STAR, "fa-gift": I_GIFT, "fa-fire": I_FIRE, "fa-crown": I_CROWN, "fa-money-bill-wave": I_MONEY,
}

COL_ICON = {"daily": I_CLOCK, "weekly": I_CALENDAR, "once": I_STAR}
COL_COLOR = {"daily": BLUE, "weekly": SILVER, "once": PURPLE}
COL_TITLE = {"daily": "Ежедневные", "weekly": "Недельные", "once": "Разовые"}
COL_SUB = {"daily": "СБРОС 00:00 МСК", "weekly": "СБРОС ПН 00:00 МСК", "once": "НА ВЕСЬ СЕЗОН"}

def render_quests(user_id: int, quests: List[Dict]) -> io.BytesIO:
    img, d = base_canvas(uid_label="твои квесты", uid_value=user_id, logo_icon=I_STAR)
    title_y = 130
    d.rounded_rectangle((PAD_X, title_y + 6, PAD_X + 6, title_y + 48), radius=3, fill=SILVER + (255,))
    d.text((PAD_X + 22, title_y), "КВЕСТЫ КЛУБА", font=_font(30), fill=TEXT)
    d.text((PAD_X + 22, title_y + 40), "выполняй задания · получай dc в копилку", font=_font(15), fill=MUTED)
    total_done = sum(1 for q in quests if q.get("completed")); total_all = len(quests) or 1
    meta_r = CANVAS_W - M - PAD_X; lbl = "ВЫПОЛНЕНО"; val = f"{total_done} / {total_all}"
    w1, w2 = _tw(d, lbl, _font(15)), _tw(d, val, _font(30))
    d.text((meta_r - w1, title_y + 8), lbl, font=_font(15), fill=MUTED); d.text((meta_r - w2, title_y + 30), val, font=_font(30), fill=SILVER_HI)
    d.line((PAD_X, title_y + 60, CANVAS_W - M - PAD_X, title_y + 60), fill=STACK_HDR + (255,), width=2)
    body_y = title_y + 76; body_h = CANVAS_H - M - PAD_Y - body_y - 40; gap = 16; col_w = (CANVAS_W - M * 2 - PAD_X * 2 - gap * 2) // 3
    buckets = {"daily": [], "weekly": [], "once": []}
    for q in quests:
        t = q.get("type", "daily")
        if t in buckets: buckets[t].append(q)
    for idx, t in enumerate(["daily", "weekly", "once"]):
        x1 = PAD_X + idx * (col_w + gap); x2 = x1 + col_w; _draw_column(d, img, x1, body_y, col_w, body_h, t, buckets[t])
    foot_y = CANVAS_H - M - PAD_Y + 4; d.line((PAD_X, foot_y - 10, CANVAS_W - M - PAD_X, foot_y - 10), fill=STACK_HDR + (255,), width=2)
    d.text((PAD_X, foot_y), "Квесты сбрасываются автоматически · daily 00:00 МСК · weekly пн 00:00 МСК", font=_font(13), fill=DIM)
    right_txt = "НАГРАДА ИДЁТ В КОПИЛКУ КЛАНА"; rw = _tw(d, right_txt, _font(13))
    d.text((CANVAS_W - M - PAD_X - rw, foot_y), right_txt, font=_font(13), fill=SILVER)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def _draw_column(d, img, x, y, w, h, kind: str, quests: List[Dict]):
    color = COL_COLOR[kind]
    d.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)
    pad = 16; head_h = 72; icon_size = 46; ix = x + pad; iy = y + pad
    _alpha_fill(img, (ix, iy, ix + icon_size, iy + icon_size), color, alpha=50, radius=12)
    _icon(d, ix + icon_size // 2, iy + icon_size // 2 + 1, COL_ICON[kind], 22, color)
    d.text((ix + icon_size + 14, iy + 2), COL_TITLE[kind].upper(), font=_font(22), fill=TEXT)
    d.text((ix + icon_size + 14, iy + 28), COL_SUB[kind], font=_font(12), fill=MUTED)
    d.line((x + pad, y + pad + head_h - 10, x + w - pad, y + pad + head_h - 10), fill=STACK_HDR + (255,), width=2)
    q_y = y + pad + head_h; q_gap = 12; available = h - pad * 2 - head_h - 4; n = max(len(quests), 1)
    q_h = max((available - q_gap * (n - 1)) // n, 90)
    for i, q in enumerate(quests):
        cy = q_y + i * (q_h + q_gap); _draw_quest_card(d, img, x + pad, cy, w - pad * 2, q_h, q, kind)

def _draw_quest_card(d, img, x, y, w, h, q: Dict, kind: str):
    color = COL_COLOR[kind]; done = q.get("completed", False)
    if done: d.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=GREEN_BG + (255,), outline=GREEN + (150,), width=2); accent = GREEN
    else: d.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2); accent = color
    pad_x = 16; pad_y = 12; ic_size = 44; ix = x + pad_x; iy = y + pad_y
    if done:
        _alpha_fill(img, (ix, iy, ix + ic_size, iy + ic_size), GREEN, alpha=50, radius=11); _icon(d, ix + ic_size // 2, iy + ic_size // 2 + 1, I_CHECK, 22, GREEN)
    else:
        _alpha_fill(img, (ix, iy, ix + ic_size, iy + ic_size), color, alpha=45, radius=11); _icon(d, ix + ic_size // 2, iy + ic_size // 2 + 1, FA_MAP.get(q.get("icon", "fa-star"), I_STAR), 22, color)
    reward_cut = q.get("reward_cut", q.get("reward", 0)); rw_txt = f"{reward_cut}"; rwf = _font(28); unit_f = _font(16); rw_w = _tw(d, rw_txt, rwf) + _tw(d, " DC", unit_f) + 4
    reward_color = GREEN if done else SILVER_HI; rw_x = x + w - pad_x - rw_w
    d.text((rw_x, iy + 4), rw_txt, font=rwf, fill=reward_color); w1 = _tw(d, rw_txt, rwf); d.text((rw_x + w1 + 4, iy + 14), "DC", font=unit_f, fill=reward_color)
    tx = ix + ic_size + 14; tx_max = rw_x - 12; name_font = _font(28)
    name = _ellipsis(d, q.get("title", "—"), name_font, tx_max - tx); d.text((tx, iy + 6), name, font=name_font, fill=GREEN if done else TEXT)
    desc_font = _font(22); desc_y = iy + ic_size + 10
    desc = _ellipsis(d, q.get("desc", ""), desc_font, w - pad_x * 2); d.text((x + pad_x, desc_y), desc, font=desc_font, fill=DESC_GREY)
    bar_y = y + h - pad_y - 12; bar_x1 = x + pad_x; bar_x2 = x + w - pad_x - 110; bar_h = 12
    if bar_x2 < bar_x1 + 60: bar_x2 = bar_x1 + 60
    d.rounded_rectangle((bar_x1, bar_y, bar_x2, bar_y + bar_h), radius=bar_h // 2, fill=(28, 28, 34) + (255,))
    goal = q.get("goal", 1) or 1; prog = min(q.get("progress", 0), goal); ratio = prog / goal
    fill_w = int((bar_x2 - bar_x1) * ratio)
    if fill_w > 0: d.rounded_rectangle((bar_x1, bar_y, bar_x1 + fill_w, bar_y + bar_h), radius=bar_h // 2, fill=GREEN + (255,) if done else color + (255,))
    prog_txt = f"{goal} / {goal}" if done else f"{prog} / {goal}"
    if goal >= 1000: prog_txt = f"{prog // 1000}k / {goal // 1000}k"
    pf = _font(16); pw = _tw(d, prog_txt, pf); d.text((x + w - pad_x - pw, bar_y - 4), prog_txt, font=pf, fill=GREEN if done else MUTED)
