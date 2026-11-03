# -*- coding: utf-8 -*-
"""Pillow-рендер для трёх разделов профиля."""
import io, os, math
from typing import Optional, List, Dict, Tuple
from PIL import Image, ImageDraw, ImageFont
from core.utils import ADD_DIR, logger
from core.render import (
    _font, _icon, _tw, _ellipsis, _wrap, _fmt, _alpha_fill, _gradient_box, _draw_stack_panel, _draw_dashed_rect, _lighten,
    BG, CARD_TOP, STACK_BG, STACK_BRD, STACK_HDR, INNER_BG, INNER_BRD, TEXT, TEXT_SOFT, MUTED, DIM, DARK, SILVER, SILVER_HI, SILVER_DIM, SILVER_BG, GREEN, RED, BLUE, PURPLE, GOLD, CARD_BRD, CANVAS_W, CANVAS_H, M, PAD_X, PAD_Y,
    I_GEM, I_STAR, I_USER, I_IMAGE, I_BEZIER, I_SMILE, I_PEN_NIB, I_LAYERS, I_MASKS, I_TAG, I_BULLHORN, I_BOLT, I_DICE, I_GIFT, I_CART, I_BAG, I_COINS, I_TICKET, I_CLOCK, I_INFO, I_CHECK, I_CROWN, I_MIC, I_COMMENT, I_CHART, I_BRIEFCASE, I_ELLIPSIS, I_MONEY, I_CUBE, I_TROPHY, I_SHOP, I_ARROW_L,
    base_canvas, draw_right_head, draw_footer
)

TYPE_FA = {"design": I_IMAGE, "ads": I_BULLHORN, "roles": I_MASKS, "discounts": I_TAG, "boosts": I_BOLT, "casino": I_DICE, "gifts": I_GIFT, "custom": I_CROWN, "Кастом": I_CROWN}

def _sanitize(text: str, fallback: str = "") -> str:
    if not text: return fallback
    allowed_special = set("—–‑‒―“”«»„‘’…№·•▪●◆◇■□")
    out = []
    for ch in text:
        cp = ord(ch)
        if 0x20 <= cp <= 0x7E: out.append(ch); continue
        if 0x0400 <= cp <= 0x04FF: out.append(ch); continue
        if 0x00C0 <= cp <= 0x017F: out.append(ch); continue
        if ch in allowed_special: out.append(ch); continue
    result = "".join(out).strip()
    while "  " in result: result = result.replace("  ", " ")
    return result or fallback

def _hex_to_rgb(h: int) -> Tuple[int, int, int]: return ((h >> 16) & 0xFF, (h >> 8) & 0xFF, h & 0xFF)

def _draw_left_panel(img, d, box, balance, total_spent, extra_blocks=None):
    _draw_stack_panel(img, d, box, radius=18)
    x1, y1, x2, y2 = box; pad = 24
    bal_icon_size = 72; ib_x = x1 + pad; ib_y = y1 + pad
    _gradient_box(img, (ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size), SILVER, SILVER_DIM, alpha=42, radius=18)
    d.rounded_rectangle((ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size), radius=18, outline=SILVER + (140,), width=3)
    _icon(d, ib_x + bal_icon_size // 2, ib_y + bal_icon_size // 2 + 1, I_GEM, 30, SILVER_HI)
    lbl_x = ib_x + bal_icon_size + 16
    d.text((lbl_x, ib_y + 6), "ТВОЙ БАЛАНС", font=_font(13), fill=MUTED)
    bal_str = _fmt(balance); val_font = _font(40); max_w = x2 - pad - lbl_x - 16
    while _tw(d, bal_str + " DC", val_font) > max_w and val_font.size > 22: val_font = _font(val_font.size - 2)
    d.text((lbl_x, ib_y + 26), bal_str, font=val_font, fill=TEXT)
    bw = _tw(d, bal_str, val_font); d.text((lbl_x + bw + 6, ib_y + 26 + val_font.size - 22), "DC", font=_font(18), fill=SILVER)
    sep_y = ib_y + bal_icon_size + 22; d.line((x1 + pad, sep_y, x2 - pad, sep_y), fill=STACK_HDR + (255,), width=2)
    if extra_blocks:
        bb_h = 84; bb_gap = 10; bottom_y = y2 - pad - bb_h
        for i, blk in enumerate(reversed(extra_blocks)):
            by1 = bottom_y - i * (bb_h + bb_gap); by2 = by1 + bb_h; bx1 = x1 + pad; bx2 = x2 - pad
            bcolor = blk.get("color", SILVER)
            _gradient_box(img, (bx1, by1, bx2, by2), bcolor, bcolor, alpha=18, radius=14)
            d.rounded_rectangle((bx1, by1, bx2, by2), radius=14, outline=bcolor + (150,), width=2)
            icon_size = 46; ib2_x = bx1 + 14; ib2_y = by1 + (bb_h - icon_size) // 2
            _alpha_fill(img, (ib2_x, ib2_y, ib2_x + icon_size, ib2_y + icon_size), bcolor, alpha=50, radius=12)
            _icon(d, ib2_x + icon_size // 2, ib2_y + icon_size // 2 + 1, blk.get("icon", I_INFO), 22, bcolor)
            tx = ib2_x + icon_size + 14
            d.text((tx, by1 + 12), blk.get("label", "").upper(), font=_font(12), fill=bcolor)
            bv = blk.get("value", "—"); val_font = _font(18); max_w2 = bx2 - 16 - tx
            bv_shown = _ellipsis(d, bv, val_font, max_w2)
            d.text((tx, by1 + 36), bv_shown, font=val_font, fill=bcolor)

def _draw_right_head(d, x1, y1, x2, title: str, sub: str):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 46), radius=3, fill=SILVER + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(28), fill=TEXT)
    sub_w = _tw(d, sub.upper(), _font(14)); d.text((x2 - sub_w, y1 + 18), sub.upper(), font=_font(14), fill=MUTED)
    d.line((x1, y1 + 60, x2, y1 + 60), fill=STACK_HDR + (255,), width=2)

def render_inventory(user_id: int, balance: int, total_spent: int, purchases: List[Dict]) -> io.BytesIO:
    img, d = base_canvas(uid_label="инвентарь dc", uid_value=user_id)
    body_y, body_h = 130, CANVAS_H - M - PAD_Y - 130 - 40
    left_w, gap = 380, 26; left_x1, left_x2 = PAD_X, PAD_X + left_w; right_x1, right_x2 = left_x2 + gap, CANVAS_W - M - PAD_X
    _draw_left_panel(img, d, (left_x1, body_y, left_x2, body_y + body_h), balance, total_spent, extra_blocks=[{"label": "Активных товаров", "value": f"{len(purchases)} шт.", "icon": I_BAG, "color": SILVER}, {"label": "Всего потрачено", "value": f"{_fmt(total_spent)} DC", "icon": I_COINS, "color": GREEN}])
    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=18)
    rx1, rx2 = right_x1 + 26, right_x2 - 26
    draw_right_head(d, rx1, body_y + 20, rx2, "Инвентарь", "купленные товары · оформи в тикет")
    grid_y1, grid_y2 = body_y + 100, body_y + body_h - 22; grid_h = grid_y2 - grid_y1; cell_gap, cols, rows = 14, 3, 2
    cell_w = (rx2 - rx1 - cell_gap * (cols - 1)) // cols; cell_h = (grid_h - cell_gap * (rows - 1)) // rows
    if not purchases:
        box = (rx1, grid_y1, rx2, grid_y2); _draw_dashed_rect(d, box, 18, (58, 58, 64), dash=12, gap=8, width=2)
        icon_cx = (rx1 + rx2) // 2; icon_cy = (grid_y1 + grid_y2) // 2 - 50
        _alpha_fill(img, (icon_cx - 55, icon_cy - 55, icon_cx + 55, icon_cy + 55), SILVER, alpha=25, radius=26); _icon(d, icon_cx, icon_cy, I_BAG, 48, SILVER)
        d.text((icon_cx, icon_cy + 90), "У тебя пока нет активных покупок", font=_font(26), fill=TEXT, anchor="mm")
        d.text((icon_cx, icon_cy + 128), "Загляни в каталог — там есть из чего выбрать.", font=_font(16), fill=MUTED, anchor="mm")
        d.text((icon_cx, icon_cy + 158), "После покупки товар появится здесь и его можно оформить в тикет.", font=_font(14), fill=DIM, anchor="mm")
    else:
        for idx in range(cols * rows):
            r, c = divmod(idx, cols); cx = rx1 + c * (cell_w + cell_gap); cy = grid_y1 + r * (cell_h + cell_gap)
            if idx < len(purchases): _draw_inv_tile(d, img, cx, cy, cell_w, cell_h, purchases[idx])
            else: _draw_dashed_rect(d, (cx, cy, cx + cell_w, cy + cell_h), 18, (36, 36, 42), dash=12, gap=8, width=2); _icon(d, cx + cell_w // 2, cy + cell_h // 2, I_ELLIPSIS, 28, DARK)
    draw_footer(d, "Выбери товар и открой тикет через «Купить» → Diamond Coins", f"показано {min(len(purchases), 6)} / {len(purchases)}")
    buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf

def _draw_inv_tile(d, img, x, y, w, h, p: Dict):
    d.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    pad = 18; ptype = p.get("type", "—"); pvalue = _sanitize(p.get("value", "—"), fallback="Товар"); pdate = p.get("date", 0)
    icon_size = 52; ib_x = x + pad; ib_y = y + pad; color = SILVER
    if ptype == "design": color = GOLD
    elif ptype == "ads": color = RED
    elif ptype == "roles": color = PURPLE
    elif ptype == "discounts": color = GREEN
    elif ptype == "boosts": color = BLUE
    icon_code = TYPE_FA.get(ptype, I_CUBE)
    _gradient_box(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size), color, color, alpha=35, radius=13)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size), radius=13, outline=color + (140,), width=2)
    _icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1, icon_code, 24, color)
    name_x = ib_x + icon_size + 14; name_w = w - (name_x - x) - pad; name_font = _font(18)
    name_shown = _ellipsis(d, pvalue, name_font, name_w); d.text((name_x, ib_y + 2), name_shown, font=name_font, fill=TEXT)
    d.text((name_x, ib_y + 28), ptype.upper(), font=_font(11), fill=MUTED)
    desc_y = ib_y + icon_size + 14; desc_font = _font(12); desc_text = _inv_desc_by_type(ptype, pvalue)
    desc_lines = _wrap(d, desc_text, desc_font, w - pad * 2, max_lines=3)
    for i, line in enumerate(desc_lines): d.text((x + pad, desc_y + i * 17), line, font=desc_font, fill=MUTED)
    foot_y = y + h - 44; d.line((x + pad, foot_y - 10, x + w - pad, foot_y - 10), fill=INNER_BRD + (255,), width=1)
    try: date_str = datetime.fromtimestamp(pdate, timezone.utc).strftime("%d.%m.%Y")
    except: date_str = "—"
    d.text((x + pad, foot_y + 6), date_str, font=_font(12), fill=DIM)
    badge_text = "ОФОРМИТЬ"; bf = _font(11); btw = _tw(d, badge_text, bf); bpad = 12; bx = x + w - pad - btw - bpad * 2; by = foot_y + 2
    d.rounded_rectangle((bx, by, bx + btw + bpad * 2, by + 26), radius=7, fill=GREEN_BG + (255,), outline=GREEN + (170,), width=1)
    d.text((bx + bpad, by + 7), badge_text, font=bf, fill=GREEN)

def _inv_desc_by_type(ptype: str, name: str) -> str:
    return {"design": "Уникальный дизайн от команды Diamond. Стиль и композиция согласуются в тикете.", "ads": "Реклама в каналах Diamond. Расскажем о тебе или твоём проекте.", "roles": "Особая роль сервера. Даёт свой стиль и доступ.", "discounts": "Применяется в тикете — подставится в заказ автоматически.", "boosts": "Усилитель DC-заработка. Активируется сразу после покупки.", "casino": "Предмет для казино. Применяется в следующей партии.", "gifts": "Подарок DC другому участнику."}.get(ptype, f"Товар «{name}» из магазина Diamond.")

def render_custom_roles(user_id: int, balance: int, total_spent: int, roles_list: List[Dict]) -> io.BytesIO:
    img, d = base_canvas(uid_label="кастомные роли", uid_value=user_id)
    body_y, body_h = 130, CANVAS_H - M - PAD_Y - 130 - 40
    left_w, gap = 380, 26; left_x1, left_x2 = PAD_X, PAD_X + left_w; right_x1, right_x2 = left_x2 + gap, CANVAS_W - M - PAD_X
    max_pos = max((r.get("position", 0) for r in roles_list), default=0)
    _draw_left_panel(img, d, (left_x1, body_y, left_x2, body_y + body_h), balance, total_spent, extra_blocks=[{"label": "Кастомных ролей", "value": f"{len(roles_list)} шт.", "icon": I_MASKS, "color": PURPLE}, {"label": "Макс. позиция", "value": f"#{max_pos}" if max_pos else "—", "icon": I_CROWN, "color": SILVER}])
    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=18)
    rx1, rx2 = right_x1 + 26, right_x2 - 26
    draw_right_head(d, rx1, body_y + 20, rx2, "Кастомные роли", "твои уникальные роли на сервере")
    list_y1, row_h, gap_row = body_y + 100, 74, 10
    if not roles_list:
        box = (rx1, list_y1, rx2, body_y + body_h - 22); _draw_dashed_rect(d, box, 18, (58, 58, 64), dash=12, gap=8, width=2)
        icon_cx = (rx1 + rx2) // 2; icon_cy = (list_y1 + body_y + body_h - 22) // 2 - 50
        _alpha_fill(img, (icon_cx - 55, icon_cy - 55, icon_cx + 55, icon_cy + 55), PURPLE, alpha=25, radius=26); _icon(d, icon_cx, icon_cy, I_MASKS, 48, PURPLE)
        d.text((icon_cx, icon_cy + 90), "У тебя пока нет кастомных ролей", font=_font(26), fill=TEXT, anchor="mm")
        d.text((icon_cx, icon_cy + 128), "Приобрести кастомную роль можно в каталоге DC-магазина.", font=_font(16), fill=MUTED, anchor="mm")
    else:
        for idx, r in enumerate(roles_list[:8]):
            ry = list_y1 + idx * (row_h + gap_row); _draw_role_row(d, img, rx1, ry, rx2 - rx1, row_h, r)
    draw_footer(d, "Кастомные роли покупаются в разделе «Особые роли»", f"показано {min(len(roles_list), 8)} / {len(roles_list)}")
    buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf

def _draw_role_row(d, img, x, y, w, h, r: Dict):
    d.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
    pad = 18; color_int = int(r.get("color", 0) or 0)
    role_color = SILVER if color_int == 0 else _hex_to_rgb(color_int)
    role_color = tuple(min(255, max(0, c)) for c in role_color)
    dot_size = 52; cx = x + pad + dot_size // 2; cy = y + h // 2
    _alpha_fill(img, (cx - dot_size // 2, cy - dot_size // 2, cx + dot_size // 2, cy + dot_size // 2), role_color, alpha=55, radius=dot_size // 2)
    d.ellipse((cx - dot_size // 2, cy - dot_size // 2, cx + dot_size // 2, cy + dot_size // 2), outline=role_color + (255,), width=3)
    _icon(d, cx, cy + 1, I_MASKS, 22, role_color)
    name_x = cx + dot_size // 2 + 16; name = _sanitize(r.get("name", ""), fallback=f"Роль #{r.get('id', 0)}"); name_font = _font(20)
    max_name_w = w - (name_x - x) - 320; name_shown = _ellipsis(d, name, name_font, max_name_w); name_y = y + h // 2 - 22
    d.text((name_x, name_y), name_shown, font=name_font, fill=TEXT)
    sub_y = name_y + 26; pos = r.get("position", 0); sub_text = f"Позиция в иерархии: #{pos}" if pos else "Кастомная роль"
    d.text((name_x, sub_y), sub_text, font=_font(12), fill=MUTED)
    pos_text = f"#{pos}" if pos else "—"; pf = _font(16); pw = _tw(d, pos_text, pf); pos_pad = 12
    bx = x + w - pad - pw - pos_pad * 2 - 180; by = y + h // 2 - 18
    d.rounded_rectangle((bx, by, bx + pw + pos_pad * 2, by + 36), radius=8, fill=SILVER_BG + (255,), outline=SILVER + (150,), width=1)
    d.text((bx + pos_pad, by + 8), pos_text, font=pf, fill=SILVER_HI)
    rid = str(r.get("id", "—")); id_text = f"ID · {rid}"; idf = _font(12); idw = _tw(d, id_text, idf)
    d.text((x + w - pad - idw, y + h // 2 + 6), id_text, font=idf, fill=DIM)
