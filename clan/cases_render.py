# -*- coding: utf-8 -*-
"""Pillow-рендеры кейсов (перенесено из bonus)."""
import io
from datetime import datetime, timezone
from PIL import Image, ImageDraw

# Импортируем общие утилиты из bonus.render, чтобы не дублировать код
from bonus.render import (
    _canvas, _panel, _grad, _alpha, _icon, _tw, _el, _font, _wrap,
    BG, CARD_TOP, STACK_BG, STACK_BRD, STACK_HDR, INNER_BG, INNER_BRD,
    TEXT, TEXT_SOFT, MUTED, DIM, DARK, SILVER, SILVER_HI, GREEN, RED, BLUE,
    GOLD, PURPLE, BRONZE, CARD_BRD, W, H, PAD_X, PAD_Y,
    I_USER, I_TROPHY, I_MEDAL, I_CHECK, I_GIFT, I_GEM, I_COINS, I_CROWN,
    I_FIRE, I_CLOCK, I_ELL, I_TAG, I_CUBE, I_TICKET, I_BOLT, I_STAR,
    I_CART, I_BOX, I_INFO
)

FA_CASE_COLOR = {
    "blue":   BLUE,
    "green":  GREEN,
    "gold":   GOLD,
    "purple": PURPLE,
    "red":    RED,
}

# ═══════════════════════════════════════════════════
# ЭКРАН 3: КЕЙСЫ (ВЫБОР)
# ═══════════════════════════════════════════════════
def render_cases(user_id, username, balance, stats):
    img, d = _canvas("кейсы")

    from clan.cases import CASES

    top_y1 = PAD_Y + 80
    top_h = 90
    gap_top = 14
    col_w = (W - 2 * PAD_X - 2 * gap_top) // 3

    tb_data = [
        ("ТВОЙ БАЛАНС", f"{balance:,}".replace(",", " ") + " DC", GREEN, I_COINS, True),
        ("ОТКРЫТО", str(stats.get("opened", 0)), BLUE, I_GIFT, False),
        ("ЛУЧШИЙ ВЫИГРЫШ", f"{stats.get('best', 0)} DC", GOLD, I_TROPHY, False),
    ]

    for i, (lbl, val, color, ic_code, is_green) in enumerate(tb_data):
        bx1 = PAD_X + i * (col_w + gap_top)
        bx2 = bx1 + col_w
        by1 = top_y1
        by2 = top_y1 + top_h

        _grad(img, (bx1, by1, bx2, by2), color, color, alpha=18 if is_green else 10, radius=16)
        d.rounded_rectangle((bx1, by1, bx2, by2), radius=16, outline=color + (200,), width=2)

        _alpha(img, (bx1 + 16, by1 + 22, bx1 + 62, by1 + 68), color, alpha=45, radius=12)
        _icon(d, bx1 + 39, by1 + 45, ic_code, 22, color)

        d.text((bx1 + 78, by1 + 20), lbl, font=_font(11), fill=MUTED)
        vf = _font(24)
        v = _el(d, val, vf, bx2 - 90)
        d.text((bx1 + 78, by1 + 42), v, font=vf, fill=color)

    head_y = top_y1 + top_h + 22
    d.text((PAD_X, head_y), "🎰 Кейсы", font=_font(32), fill=TEXT)
    sw = _tw(d, "выбери свою удачу", _font(15))
    d.text((W - PAD_X - sw, head_y + 14), "выбери свою удачу", font=_font(15), fill=MUTED)
    d.line((PAD_X, head_y + 56, W - PAD_X, head_y + 56), fill=STACK_HDR + (255,), width=2)

    grid_y = head_y + 70
    grid_bottom = H - PAD_Y - 20
    grid_h = grid_bottom - grid_y

    gap = 18
    cols = 5
    cell_w = (W - 2 * PAD_X - gap * (cols - 1)) // cols
    cell_h = min(grid_h, int(cell_w * 1.15))

    for i, case in enumerate(CASES):
        cx1 = PAD_X + i * (cell_w + gap)
        cy1 = grid_y
        cy2 = cy1 + cell_h
        cx2 = cx1 + cell_w
        color = FA_CASE_COLOR.get(case["color"], SILVER)

        _grad(img, (cx1, cy1, cx2, cy2), color, color, alpha=20, radius=24)
        d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=24, outline=color + (230,), width=3)

        if case["num"] == 5:
            bw_ = 64
            bx1 = cx2 - bw_ - 18
            by1 = cy1 + 16
            d.rounded_rectangle((bx1, by1, bx1 + bw_, by1 + 28), radius=8, fill=RED + (255,))
            d.text((bx1 + 10, by1 + 6), "TOP", font=_font(12), fill=TEXT)

        ic_size = 130
        ic_x = cx1 + (cell_w - ic_size) // 2
        ic_y = cy1 + 34
        _alpha(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), color, alpha=50, radius=28)
        d.rounded_rectangle((ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), radius=28, outline=color + (220,), width=3)
        icon_code = {1: I_GIFT, 2: I_COINS, 3: I_GEM, 4: I_CROWN, 5: I_TROPHY}.get(case["num"], I_GIFT)
        _icon(d, ic_x + ic_size // 2, ic_y + ic_size // 2 + 1, icon_code, 58, color)

        nf = _font(20)
        name_lines = _wrap(d, case["name"], nf, cell_w - 30, max_lines=2)
        ny = ic_y + ic_size + 22
        for j, ln in enumerate(name_lines):
            lw = _tw(d, ln, nf)
            d.text((cx1 + (cell_w - lw) // 2, ny + j * 26), ln, font=nf, fill=color)

        price_str = str(case["price"])
        pf = _font(44)
        pw = _tw(d, price_str, pf)
        uf = _font(18)
        uw = _tw(d, " DC", uf)
        total = pw + uw
        px = cx1 + (cell_w - total) // 2
        py = cy2 - 70
        d.text((px, py), price_str, font=pf, fill=color)
        d.text((px + pw + 6, py + pf.size - 22), " DC", font=uf, fill=MUTED)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf

# ═══════════════════════════════════════════════════
# ЭКРАН 4: КРУТКА
# ═══════════════════════════════════════════════════
def render_spin(case):
    img, d = _canvas("крутка кейса")

    color = FA_CASE_COLOR.get(case["color"], GOLD)
    cx = W // 2

    circle_size = 420
    cy = 460
    circle_x = cx - circle_size // 2
    circle_y = cy - circle_size // 2

    _grad(img, (circle_x, circle_y, circle_x + circle_size, circle_y + circle_size),
          color, color, alpha=35, radius=circle_size // 2)
    d.ellipse((circle_x - 5, circle_y - 5, circle_x + circle_size + 5, circle_y + circle_size + 5),
              outline=color + (255,), width=10)
    d.ellipse((circle_x + 26, circle_y + 26, circle_x + circle_size - 26, circle_y + circle_size - 26),
              outline=color + (140,), width=4)

    _icon(d, cx, cy + 2, I_GIFT, 180, color)

    title = "КРУТИМ БАРАБАН..."
    tf = _font(56)
    tw_ = _tw(d, title, tf)
    title_y = circle_y + circle_size + 40
    d.text((cx - tw_ // 2, title_y), title, font=tf, fill=color)

    sub = f"{case['name']} · {case['price']} DC списано"
    sf = _font(22)
    sw = _tw(d, sub, sf)
    sub_y = title_y + 56 + 24
    d.text((cx - sw // 2, sub_y), sub, font=sf, fill=MUTED)

    hint = "результат через пару секунд..."
    hf = _font(16)
    hw = _tw(d, hint, hf)
    hint_y = sub_y + 22 + 16
    d.text((cx - hw // 2, hint_y), hint, font=hf, fill=DIM)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf

# ═══════════════════════════════════════════════════
# ЭКРАН 5: РЕЗУЛЬТАТ КЕЙСА
# ═══════════════════════════════════════════════════
def render_result(case, prize, desc, user_balance):
    ptype = (prize or {}).get("type", "dc")

    try: case_price = int(case.get("price", 0) or 0)
    except Exception: case_price = 0

    try: prize_value = int((prize or {}).get("value", 0) or 0)
    except Exception: prize_value = 0

    if ptype == "dc":
        if case_price > 0 and prize_value >= case_price * 3: tag = "ПОЗДРАВЛЯЕМ, ДЖЕКПОТ"
        elif case_price > 0 and prize_value >= case_price: tag = "ПОЗДРАВЛЯЕМ, ВЫПАЛО"
        else: tag = "ВЫПАЛО"
    elif ptype == "role": tag = "ПОЗДРАВЛЯЕМ, РОЛЬ"
    elif ptype == "boost": tag = "ВЫПАЛ БУСТ"
    elif ptype == "discount": tag = "ВЫПАЛА СКИДКА"
    else: tag = "ВЫПАЛО"

    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=30, fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)

    cx = W // 2

    for sx, sy, sz in [(180, 150, 44), (W - 200, 180, 52), (200, H - 260, 36), (W - 220, H - 240, 40), (120, 440, 32), (W - 140, 420, 36)]:
        _icon(d, sx, sy, I_STAR, sz, SILVER)

    hx, hy = PAD_X, PAD_Y
    d.rounded_rectangle((hx, hy, hx + 54, hy + 54), radius=14, fill=(58, 58, 64) + (255,))
    _icon(d, hx + 27, hy + 28, I_TROPHY, 26, SILVER)
    bx = hx + 54 + 18
    d.text((bx, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx + 2, hy + 38), "BONUS · ВЫИГРЫШ", font=_font(11), fill=MUTED)

    meta_r = W - PAD_X
    mtext = f"КЕЙС {case.get('num', '?')}"
    w1 = _tw(d, mtext, _font(11))
    d.text((meta_r - w1, hy + 14), mtext, font=_font(11), fill=MUTED)
    d.line((PAD_X, hy + 54 + 16, W - PAD_X, hy + 54 + 16), fill=STACK_HDR + (255,), width=2)

    txf = _font(16)
    txw = _tw(d, tag, txf)
    pad_tx = 36
    tag_w = txw + pad_tx * 2
    tag_h = 50
    tag_x = cx - tag_w // 2
    tag_y = 180

    _alpha(img, (tag_x, tag_y, tag_x + tag_w, tag_y + tag_h), SILVER, alpha=40, radius=tag_h // 2)
    d.rounded_rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + tag_h), radius=tag_h // 2, outline=SILVER + (230,), width=3)
    d.text((cx - txw // 2, tag_y + 12), tag, font=txf, fill=SILVER)

    ic_size = 240
    ic_x = cx - ic_size // 2
    ic_y = tag_y + tag_h + 30

    _alpha(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), SILVER, alpha=50, radius=ic_size // 2)
    d.ellipse((ic_x - 4, ic_y - 4, ic_x + ic_size + 4, ic_y + ic_size + 4), outline=SILVER + (255,), width=6)
    _icon(d, cx, ic_y + ic_size // 2 + 2, I_TROPHY, 110, SILVER)

    num_y = ic_y + ic_size + 30
    num_str = str(desc or "—")
    nf = _font(140)
    while _tw(d, num_str, nf) > W - 200 and nf.size > 60: nf = _font(nf.size - 6)
    nw = _tw(d, num_str, nf)
    d.text((cx - nw // 2, num_y), num_str, font=nf, fill=SILVER)

    sub_y = num_y + nf.size + 16
    sub = f"Кейс «{case.get('name', '—')}» · {case_price} DC"
    sf = _font(15)
    sw = _tw(d, sub, sf)
    d.text((cx - sw // 2, sub_y), sub, font=sf, fill=MUTED)

    info_y = H - PAD_Y - 130
    info_h = 130
    ix1 = PAD_X; ix2 = W - PAD_X

    d.rounded_rectangle((ix1, info_y, ix2, info_y + info_h), radius=20, fill=(20, 20, 28) + (255,), outline=SILVER + (200,), width=2)
    mid_x = (ix1 + ix2) // 2

    _icon(d, ix1 + 70, info_y + info_h // 2, I_COINS if ptype == "dc" else I_GIFT, 46, SILVER)

    if ptype == "dc":
        d.text((ix1 + 116, info_y + 26), "ЗАЧИСЛЕНО НА БАЛАНС", font=_font(12), fill=SILVER)
        d.text((ix1 + 116, info_y + 50), f"+{prize_value} DC", font=_font(38), fill=TEXT)
        if case_price > 0: mult_str = f"×{prize_value / case_price:.1f} от ставки"
        else: mult_str = ""
        d.text((ix1 + 116, info_y + 98), mult_str, font=_font(14), fill=MUTED)
    elif ptype == "role":
        d.text((ix1 + 116, info_y + 30), "РОЛЬ ВЫДАНА", font=_font(12), fill=SILVER)
        d.text((ix1 + 116, info_y + 54), str(desc or "—"), font=_font(30), fill=TEXT)
        d.text((ix1 + 116, info_y + 98), "проверь профиль", font=_font(14), fill=MUTED)
    elif ptype == "boost":
        d.text((ix1 + 116, info_y + 30), "БУСТ АКТИВИРОВАН", font=_font(12), fill=SILVER)
        d.text((ix1 + 116, info_y + 54), "уже работает", font=_font(30), fill=TEXT)
        d.text((ix1 + 116, info_y + 98), "смотри в профиле", font=_font(14), fill=MUTED)
    elif ptype == "discount":
        d.text((ix1 + 116, info_y + 30), "СКИДКА В ИНВЕНТАРЕ", font=_font(12), fill=SILVER)
        d.text((ix1 + 116, info_y + 54), str(desc or "—"), font=_font(30), fill=TEXT)
        d.text((ix1 + 116, info_y + 98), "примени в тикете", font=_font(14), fill=MUTED)

    d.rectangle((mid_x - 1, info_y + 24, mid_x + 1, info_y + info_h - 24), fill=(60, 60, 68) + (255,))
    _icon(d, mid_x + 60, info_y + info_h // 2, I_GEM, 46, SILVER)
    d.text((mid_x + 106, info_y + 26), "ТЕКУЩИЙ БАЛАНС", font=_font(12), fill=SILVER)
    bal_str = f"{int(user_balance):,}".replace(",", " ") + " DC"
    d.text((mid_x + 106, info_y + 50), bal_str, font=_font(38), fill=TEXT)
    d.text((mid_x + 106, info_y + 98), "готов к новому кейсу", font=_font(14), fill=MUTED)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
