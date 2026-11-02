# -*- coding: utf-8 -*-
"""Pillow-рендеры кейсов."""
import io
from datetime import datetime, timezone
from PIL import Image, ImageDraw
from core.render import _font, _icon, _tw, _ellipsis, _wrap, _fmt, _alpha_fill, _gradient_box, BG, CARD_TOP, STACK_BG, STACK_BRD, STACK_HDR, INNER_BG, INNER_BRD, TEXT, TEXT_SOFT, MUTED, DIM, DARK, SILVER, SILVER_HI, GREEN, RED, BLUE, GOLD, PURPLE, CARD_BRD, CANVAS_W, CANVAS_H, PAD_X, PAD_Y, I_GIFT, I_COINS, I_GEM, I_CROWN, I_TROPHY, I_STAR, I_HISTORY, base_canvas, draw_footer
from modules.cases import CASES

FA_CASE_COLOR = {"blue": BLUE, "green": GREEN, "gold": GOLD, "purple": PURPLE, "red": RED}

def render_cases(user_id, username, balance, stats):
    img, d = base_canvas(uid_label="кейсы", uid_value=user_id, logo_icon=I_GIFT)
    top_y1, top_h, gap_top = PAD_Y + 80, 90, 14
    col_w = (CANVAS_W - 2 * PAD_X - 2 * gap_top) // 3
    tb_data = [("ТВОЙ БАЛАНС", f"{_fmt(balance)} DC", GREEN, I_COINS, True), ("ОТКРЫТО", str(stats.get("opened", 0)), BLUE, I_GIFT, False), ("ЛУЧШИЙ ВЫИГРЫШ", f"{stats.get('best', 0)} DC", GOLD, I_TROPHY, False)]
    for i, (lbl, val, color, ic_code, is_green) in enumerate(tb_data):
        bx1, bx2, by1, by2 = PAD_X + i * (col_w + gap_top), PAD_X + i * (col_w + gap_top) + col_w, top_y1, top_y1 + top_h
        _gradient_box(img, (bx1, by1, bx2, by2), color, color, alpha=18 if is_green else 10, radius=16)
        d.rounded_rectangle((bx1, by1, bx2, by2), radius=16, outline=color + (200,), width=2)
        _alpha_fill(img, (bx1 + 16, by1 + 22, bx1 + 62, by1 + 68), color, alpha=45, radius=12); _icon(d, bx1 + 39, by1 + 45, ic_code, 22, color)
        d.text((bx1 + 78, by1 + 20), lbl, font=_font(11), fill=MUTED); d.text((bx1 + 78, by1 + 42), _ellipsis(d, val, _font(24), bx2 - 90), font=_font(24), fill=color)
    head_y = top_y1 + top_h + 22
    d.text((PAD_X, head_y), "🎰 Кейсы", font=_font(32), fill=TEXT)
    sw = _tw(d, "выбери свою удачу", _font(15)); d.text((CANVAS_W - PAD_X - sw, head_y + 14), "выбери свою удачу", font=_font(15), fill=MUTED)
    d.line((PAD_X, head_y + 56, CANVAS_W - PAD_X, head_y + 56), fill=STACK_HDR + (255,), width=2)
    grid_y, grid_bottom = head_y + 70, CANVAS_H - PAD_Y - 20
    gap, cols = 18, 5
    cell_w = (CANVAS_W - 2 * PAD_X - gap * (cols - 1)) // cols
    cell_h = min(grid_bottom - grid_y, int(cell_w * 1.15))
    for i, case in enumerate(CASES):
        cx1, cy1 = PAD_X + i * (cell_w + gap), grid_y
        cy2, cx2 = cy1 + cell_h, cx1 + cell_w
        color = FA_CASE_COLOR.get(case["color"], SILVER)
        _gradient_box(img, (cx1, cy1, cx2, cy2), color, color, alpha=20, radius=24); d.rounded_rectangle((cx1, cy1, cx2, cy2), radius=24, outline=color + (230,), width=3)
        if case["num"] == 5:
            d.rounded_rectangle((cx2 - 82, cy1 + 16, cx2 - 18, cy1 + 44), radius=8, fill=RED + (255,)); d.text((cx2 - 72, cy1 + 22), "TOP", font=_font(12), fill=TEXT)
        ic_size = 130; ic_x, ic_y = cx1 + (cell_w - ic_size) // 2, cy1 + 34
        _alpha_fill(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), color, alpha=50, radius=28); d.rounded_rectangle((ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), radius=28, outline=color + (220,), width=3)
        _icon(d, ic_x + ic_size // 2, ic_y + ic_size // 2 + 1, {1: I_GIFT, 2: I_COINS, 3: I_GEM, 4: I_CROWN, 5: I_TROPHY}.get(case["num"], I_GIFT), 58, color)
        ny = ic_y + ic_size + 22
        for j, ln in enumerate(_wrap(d, case["name"], _font(20), cell_w - 30, max_lines=2)): d.text((cx1 + (cell_w - _tw(d, ln, _font(20))) // 2, ny + j * 26), ln, font=_font(20), fill=color)
        pf = _font(44); pw = _tw(d, str(case["price"]), pf); uf = _font(18); uw = _tw(d, " DC", uf)
        d.text((cx1 + (cell_w - (pw + uw)) // 2, cy2 - 70), str(case["price"]), font=pf, fill=color); d.text((cx1 + (cell_w - (pw + uw)) // 2 + pw + 6, cy2 - 70 + pf.size - 22), " DC", font=uf, fill=MUTED)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_spin(case):
    img, d = base_canvas(uid_label="крутка кейса", logo_icon=I_GIFT)
    color = FA_CASE_COLOR.get(case["color"], GOLD); cx = CANVAS_W // 2; circle_size, cy = 420, 460
    circle_x, circle_y = cx - circle_size // 2, cy - circle_size // 2
    _gradient_box(img, (circle_x, circle_y, circle_x + circle_size, circle_y + circle_size), color, color, alpha=35, radius=circle_size // 2)
    d.ellipse((circle_x - 5, circle_y - 5, circle_x + circle_size + 5, circle_y + circle_size + 5), outline=color + (255,), width=10)
    d.ellipse((circle_x + 26, circle_y + 26, circle_x + circle_size - 26, circle_y + circle_size - 26), outline=color + (140,), width=4)
    _icon(d, cx, cy + 2, I_GIFT, 180, color)
    title = "КРУТИМ БАРАБАН..."; tf = _font(56); tw_ = _tw(d, title, tf); title_y = circle_y + circle_size + 40
    d.text((cx - tw_ // 2, title_y), title, font=tf, fill=color)
    sub = f"{case['name']} · {case['price']} DC списано"; sf = _font(22); sw = _tw(d, sub, sf); sub_y = title_y + 56 + 24
    d.text((cx - sw // 2, sub_y), sub, font=sf, fill=MUTED)
    hint = "результат через пару секунд..."; hf = _font(16); hw = _tw(d, hint, hf); hint_y = sub_y + 22 + 16
    d.text((cx - hw // 2, hint_y), hint, font=hf, fill=DIM)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_result(case, prize, desc, user_balance):
    ptype = (prize or {}).get("type", "dc"); case_price = int(case.get("price", 0) or 0); prize_value = int((prize or {}).get("value", 0) or 0)
    tag = "ПОЗДРАВЛЯЕМ, ДЖЕКПОТ" if ptype == "dc" and case_price > 0 and prize_value >= case_price * 3 else "ПОЗДРАВЛЯЕМ, ВЫПАЛО" if ptype == "dc" and case_price > 0 and prize_value >= case_price else "ВЫПАЛО" if ptype == "dc" else "ПОЗДРАВЛЯЕМ, РОЛЬ" if ptype == "role" else "ВЫПАЛ БУСТ" if ptype == "boost" else "ВЫПАЛА СКИДКА" if ptype == "discount" else "ВЫПАЛО"
    img, d = base_canvas(uid_label="bonus · выигрыш", status_label=f"КЕЙС {case.get('num', '?')}", logo_icon=I_TROPHY); cx = CANVAS_W // 2
    for sx, sy, sz in [(180, 150, 44), (CANVAS_W - 200, 180, 52), (200, CANVAS_H - 260, 36), (CANVAS_W - 220, CANVAS_H - 240, 40), (120, 440, 32), (CANVAS_W - 140, 420, 36)]: _icon(d, sx, sy, I_STAR, sz, SILVER)
    txf = _font(16); txw = _tw(d, tag, txf); tag_w, tag_h = txw + 72, 50; tag_x, tag_y = cx - tag_w // 2, 180
    _alpha_fill(img, (tag_x, tag_y, tag_x + tag_w, tag_y + tag_h), SILVER, alpha=40, radius=tag_h // 2); d.rounded_rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + tag_h), radius=tag_h // 2, outline=SILVER + (230,), width=3); d.text((cx - txw // 2, tag_y + 12), tag, font=txf, fill=SILVER)
    ic_size = 240; ic_x, ic_y = cx - ic_size // 2, tag_y + tag_h + 30
    _alpha_fill(img, (ic_x, ic_y, ic_x + ic_size, ic_y + ic_size), SILVER, alpha=50, radius=ic_size // 2); d.ellipse((ic_x - 4, ic_y - 4, ic_x + ic_size + 4, ic_y + ic_size + 4), outline=SILVER + (255,), width=6); _icon(d, cx, ic_y + ic_size // 2 + 2, I_TROPHY, 110, SILVER)
    num_y = ic_y + ic_size + 30; num_str = str(desc or "—"); nf = _font(140)
    while _tw(d, num_str, nf) > CANVAS_W - 200 and nf.size > 60: nf = _font(nf.size - 6)
    d.text((cx - _tw(d, num_str, nf) // 2, num_y), num_str, font=nf, fill=SILVER)
    sub = f"Кейс «{case.get('name', '—')}» · {case_price} DC"; sf = _font(15); sw = _tw(d, sub, sf); d.text((cx - sw // 2, num_y + nf.size + 16), sub, font=sf, fill=MUTED)
    info_y, info_h = CANVAS_H - PAD_Y - 130, 130; ix1, ix2 = PAD_X, CANVAS_W - PAD_X
    d.rounded_rectangle((ix1, info_y, ix2, info_y + info_h), radius=20, fill=(20, 20, 28) + (255,), outline=SILVER + (200,), width=2); mid_x = (ix1 + ix2) // 2
    _icon(d, ix1 + 70, info_y + info_h // 2, I_COINS if ptype == "dc" else I_GIFT, 46, SILVER)
    if ptype == "dc":
        d.text((ix1 + 116, info_y + 26), "ЗАЧИСЛЕНО НА БАЛАНС", font=_font(12), fill=SILVER); d.text((ix1 + 116, info_y + 50), f"+{prize_value} DC", font=_font(38), fill=TEXT)
        d.text((ix1 + 116, info_y + 98), f"×{prize_value / case_price:.1f} от ставки" if case_price > 0 else "", font=_font(14), fill=MUTED)
    elif ptype == "role":
        d.text((ix1 + 116, info_y + 30), "РОЛЬ ВЫДАНА", font=_font(12), fill=SILVER); d.text((ix1 + 116, info_y + 54), str(desc or "—"), font=_font(30), fill=TEXT); d.text((ix1 + 116, info_y + 98), "проверь профиль", font=_font(14), fill=MUTED)
    elif ptype == "boost":
        d.text((ix1 + 116, info_y + 30), "БУСТ АКТИВИРОВАН", font=_font(12), fill=SILVER); d.text((ix1 + 116, info_y + 54), "уже работает", font=_font(30), fill=TEXT); d.text((ix1 + 116, info_y + 98), "смотри в профиле", font=_font(14), fill=MUTED)
    elif ptype == "discount":
        d.text((ix1 + 116, info_y + 30), "СКИДКА В ИНВЕНТАРЕ", font=_font(12), fill=SILVER); d.text((ix1 + 116, info_y + 54), str(desc or "—"), font=_font(30), fill=TEXT); d.text((ix1 + 116, info_y + 98), "примени в тикете", font=_font(14), fill=MUTED)
    d.rectangle((mid_x - 1, info_y + 24, mid_x + 1, info_y + info_h - 24), fill=(60, 60, 68) + (255,)); _icon(d, mid_x + 60, info_y + info_h // 2, I_GEM, 46, SILVER)
    d.text((mid_x + 106, info_y + 26), "ТЕКУЩИЙ БАЛАНС", font=_font(12), fill=SILVER); d.text((mid_x + 106, info_y + 50), f"{_fmt(user_balance)} DC", font=_font(38), fill=TEXT); d.text((mid_x + 106, info_y + 98), "готов к новому кейсу", font=_font(14), fill=MUTED)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

def render_my_cases(user_id, username, stats, history):
    img, d = base_canvas(uid_label="мои кейсы", uid_value=user_id, logo_icon=I_HISTORY)
    body_y, body_h = 138, CANVAS_H - PAD_Y - 138 - 26
    left_w, gap = 420, 26; left_x1, left_x2 = PAD_X, PAD_X + left_w; right_x1, right_x2 = left_x2 + gap, CANVAS_W - PAD_X
    d.rounded_rectangle((left_x1, body_y, left_x2, body_y + body_h), radius=22, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)
    d.text((left_x1 + 24, body_y + 20), "СТАТИСТИКА", font=_font(14), fill=MUTED); d.line((left_x1 + 24, body_y + 44, left_x2 - 24, body_y + 44), fill=STACK_HDR + (255,), width=2)
    card_y, card_h, card_gap = body_y + 60, 120, 14
    for lbl, val, icon, color in [("ОТКРЫТО", f"{stats.get('opened', 0)}", I_GIFT, BLUE), ("ПОТРАЧЕНО", f"{_fmt(stats.get('spent', 0))} DC", I_COINS, GOLD), ("ЛУЧШИЙ", f"{_fmt(stats.get('best', 0))} DC", I_TROPHY, GREEN)]:
        _gradient_box(img, (left_x1 + 24, card_y, left_x2 - 24, card_y + card_h), color, color, alpha=18, radius=14); d.rounded_rectangle((left_x1 + 24, card_y, left_x2 - 24, card_y + card_h), radius=14, outline=color + (180,), width=2)
        _alpha_fill(img, (left_x1 + 40, card_y + 30, left_x1 + 100, card_y + 90), color, alpha=45, radius=14); _icon(d, left_x1 + 70, card_y + 60, icon, 26, color)
        d.text((left_x1 + 120, card_y + 30), lbl, font=_font(12), fill=MUTED); d.text((left_x1 + 120, card_y + 52), val, font=_font(28), fill=color)
        card_y += card_h + card_gap
    d.rounded_rectangle((right_x1, body_y, right_x2, body_y + body_h), radius=22, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)
    d.rounded_rectangle((right_x1 + 24, body_y + 24, right_x1 + 30, body_y + 60), radius=3, fill=SILVER + (255,)); d.text((right_x1 + 44, body_y + 20), "ПОСЛЕДНИЕ ОТКРЫТИЯ", font=_font(28), fill=TEXT)
    sw = _tw(d, f"{len(history)} из {stats.get('opened', 0)}", _font(15)); d.text((right_x2 - 24 - sw, body_y + 34), f"{len(history)} из {stats.get('opened', 0)}", font=_font(15), fill=MUTED); d.line((right_x1 + 24, body_y + 74, right_x2 - 24, body_y + 74), fill=STACK_HDR + (255,), width=2)
    list_y, list_bottom = body_y + 100, body_y + body_h - 24
    if not history:
        d.text(((right_x1 + right_x2) // 2, (list_y + list_bottom) // 2), "Ты ещё не открывал кейсы", font=_font(24), fill=DIM, anchor="mm"); d.text(((right_x1 + right_x2) // 2, (list_y + list_bottom) // 2 + 40), "Попробуй удачу — выбери кейс в панели выше", font=_font(15), fill=MUTED, anchor="mm")
    else:
        row_h, row_gap = 76, 10; n = len(history[:8]); start_y = list_y + max(0, (list_bottom - list_y - row_h * n - row_gap * (n - 1)) // 2)
        for i, h in enumerate(history[:8]):
            ry = start_y + i * (row_h + row_gap); case = next((c for c in CASES if c["num"] == h.get("case_num")), None); color = FA_CASE_COLOR.get(case["color"], SILVER) if case else SILVER
            _gradient_box(img, (right_x1 + 24, ry, right_x2 - 24, ry + row_h), color, color, alpha=10, radius=12); d.rounded_rectangle((right_x1 + 24, ry, right_x2 - 24, ry + row_h), radius=12, outline=color + (150,), width=2)
            d.rounded_rectangle((right_x1 + 24, ry + 12, right_x1 + 30, ry + row_h - 12), radius=3, fill=color + (255,)); _alpha_fill(img, (right_x1 + 46, ry + 14, right_x1 + 104, ry + 62), color, alpha=45, radius=12); _icon(d, right_x1 + 75, ry + 38, I_GIFT, 22, color)
            d.text((right_x1 + 120, ry + 16), case.get("name", "—") if case else f"Кейс #{h.get('case_num')}", font=_font(18), fill=TEXT); d.text((right_x1 + 120, ry + 42), _ellipsis(d, h.get("prize_desc", "—"), _font(14), 400), font=_font(14), fill=MUTED)
            try: date_str = datetime.fromtimestamp(h.get("opened_at", 0), timezone.utc).strftime("%d.%m.%Y · %H:%M")
            except: date_str = "—"
            dw = _tw(d, date_str, _font(13)); d.text((right_x2 - 46 - dw, ry + 30), date_str, font=_font(13), fill=DIM)
    draw_footer(d, "Все открытия · свежие сверху", "кейсы · история")
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf
