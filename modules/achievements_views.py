# -*- coding: utf-8 -*-
"""Панель достижений (Pillow + Discord View)."""
import io, asyncio
from datetime import datetime, timezone
from typing import List, Dict, Set

import disnake
from disnake import ButtonStyle, PartialEmoji
from disnake.ui import View, Button
from PIL import Image, ImageDraw

from core.utils import logger, load_json, FILES, get_dc_cache
from core.render import *
from clan.achievements import ACHIEVEMENTS, CATEGORIES, CATEGORY_KEYS, CATEGORY_ORDER, get_category_progress, get_overall_progress, get_user_unlocked_set, check_and_unlock
from core.render import btn_labels_total

BTN_LABEL_TOTAL = 29
_L_BACK, _L_FWD = btn_labels_total(["Назад", "Вперёд"], BTN_LABEL_TOTAL)
EMOJI_BACK, EMOJI_FWD = PartialEmoji(name="baa1", id=1557224983539749004), PartialEmoji(name="rid1", id=1557225020265332816)

CATEGORY_COLORS = {"green": GREEN, "silver": SILVER, "gold": GOLD, "blue": BLUE, "purple": PURPLE, "red": RED, "orange": ORANGE, "steel": STEEL}

FA_MAP = {"fa-crown": I_CROWN, "fa-medal": I_MEDAL, "fa-award": I_AWARD, "fa-star": I_STAR, "fa-seedling": I_SEEDLING, "fa-comment": I_COMMENT, "fa-microphone": I_MIC, "fa-pen-fancy": I_PENF, "fa-cart-shopping": I_CART, "fa-gem": I_GEM, "fa-diamond": I_DIAMOND, "fa-bag-shopping": I_BAG, "fa-briefcase": I_BRIEF, "fa-trophy": I_TROPHY, "fa-sack-dollar": I_SACK, "fa-coins": I_COINS, "fa-money-bill-wave": I_MONEY, "fa-gift": I_GIFT, "fa-chart-line": I_CHART, "fa-building-columns": I_BANK, "fa-comments": I_COMMENTS, "fa-bullhorn": I_BULLHORN, "fa-fire": I_FIRE, "fa-headphones": I_HEADPH, "fa-scroll": I_SCROLL, "fa-hand-holding-dollar": I_HANDD, "fa-shield-halved": I_SHIELD, "fa-spade": I_SPADE, "fa-dice": I_DICE, "fa-dice-five": I_DICE5, "fa-dice-six": I_DICE6, "fa-money-bill-1-wave": I_MONEY2, "fa-check": I_CHECK, "fa-list": I_LIST, "fa-list-check": I_LISTC, "fa-ticket": I_TICKET, "fa-calendar-check": I_CALC}

def _draw_ach_card(img, d, x, y, w, h, ach, unlocked, cat_color):
    if ach and unlocked:
        color = cat_color; border = _lighten(color, 0.15); _gradient_box(img, (x, y, x + w, y + h), color, color, alpha=18, radius=16); d.rounded_rectangle((x, y, x + w, y + h), radius=16, outline=color + (220,), width=2)
        _alpha_fill(img, (x + 18, y + 18, x + 76, y + 76), color, alpha=70, radius=14); d.rounded_rectangle((x + 18, y + 18, x + 76, y + 76), radius=14, outline=color + (230,), width=2); _icon(d, x + 47, y + 47, FA_MAP.get(ach.get("icon", "fa-star"), I_STAR), 26, color)
        tx = x + 76 + 16; name_shown = _ellipsis(d, ach.get("name", "—"), _font(17), x + w - 18 - tx); d.text((tx, y + 18 + 29 - 12), name_shown, font=_font(17), fill=TEXT)
        for i, line in enumerate(_wrap(d, ach.get("desc", ""), _font(13), w - 36, 2)): d.text((x + 18, y + 76 + 14 + i * 20), line, font=_font(13), fill=MUTED)
        sy = y + h - 30; d.line((x + 18, sy - 10, x + w - 18, sy - 10), fill=color + (60,), width=1); _icon(d, x + 26, sy + 8, I_CHECK, 13, color); d.text((x + 46, sy), "ПОЛУЧЕНО", font=_font(11), fill=color)
    elif ach:
        d.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=INNER_BG + (255,), outline=(42, 42, 48) + (255,), width=2); _draw_dashed_rect(d, (x, y, x + w, y + h), 16, (42, 42, 48), dash=8, gap=6, width=2)
        d.rounded_rectangle((x + 18, y + 18, x + 76, y + 76), radius=14, fill=(26, 26, 32) + (255,)); _icon(d, x + 47, y + 47, I_LOCK, 24, (58, 58, 64))
        tx = x + 76 + 16; name_shown = _ellipsis(d, ach.get("name", "—"), _font(17), x + w - 18 - tx); d.text((tx, y + 18 + 29 - 12), name_shown, font=_font(17), fill=(90, 90, 96))
        for i, line in enumerate(_wrap(d, ach.get("desc", ""), _font(13), w - 36, 2)): d.text((x + 18, y + 76 + 14 + i * 20), line, font=_font(13), fill=(70, 70, 76))
        sy = y + h - 30; d.line((x + 18, sy - 10, x + w - 18, sy - 10), fill=(42, 42, 48) + (255,), width=1); d.text((x + 18, sy), "НЕ ПОЛУЧЕНО", font=_font(11), fill=(70, 70, 76))
    else:
        d.rounded_rectangle((x, y, x + w, y + h), radius=16, fill=(12, 12, 16) + (255,), outline=(28, 28, 34) + (255,), width=2); _draw_dashed_rect(d, (x, y, x + w, y + h), 16, (28, 28, 34), dash=8, gap=6, width=2); _icon(d, x + w // 2, y + h // 2, I_ELL, 26, (46, 46, 52))

def generate_achievements_panel(user_id: int, active_key: str = "base") -> io.BytesIO:
    if active_key not in CATEGORY_ORDER: active_key = CATEGORY_ORDER[0]
    cat = next((c for c in CATEGORIES if c["key"] == active_key), CATEGORIES[0]); cat_color = CATEGORY_COLORS.get(cat["color"], SILVER)
    unlocked = get_user_unlocked_set(user_id); img, d = base_canvas(uid_label="достижения", uid_value=user_id, logo_icon=I_TROPHY)
    body_y, body_h, left_w, gap = 138, CANVAS_H - M - PAD_Y - 138 - 26, 448, 30; lx1, lx2 = PAD_X, PAD_X + left_w; rx1, rx2 = lx2 + gap, CANVAS_W - PAD_X
    # Left panel
    _draw_stack_panel(img, d, (lx1, body_y, lx2 - 12, body_y + body_h - 12), radius=22); tot_y1 = body_y + 22; tx1, tx2 = lx1 + 22, lx2 - 12 - 22
    _gradient_box(img, (tx1, tot_y1, tx2, tot_y1 + 150), GOLD, GOLD, alpha=22, radius=16); d.rounded_rectangle((tx1, tot_y1, tx2, tot_y1 + 150), radius=16, outline=GOLD + (200,), width=2)
    _alpha_fill(img, ((tx1 + tx2)//2 - 23, tot_y1 + 16, (tx1 + tx2)//2 + 23, tot_y1 + 62), GOLD, alpha=70, radius=12); d.rounded_rectangle(((tx1 + tx2)//2 - 23, tot_y1 + 16, (tx1 + tx2)//2 + 23, tot_y1 + 62), radius=12, outline=GOLD + (230,), width=2); _icon(d, (tx1 + tx2)//2, tot_y1 + 39, I_TROPHY, 22, GOLD)
    overall = get_overall_progress(user_id); d.text(((tx1 + tx2) // 2, tot_y1 + 74), "ОТКРЫТО", font=_font(11), fill=MUTED, anchor="mm"); vw, ow = _tw(d, str(overall["unlocked"]), _font(46)), _tw(d, f" / {overall['total']}", _font(20)); sx = (tx1 + tx2 - vw - ow) // 2
    d.text((sx, tot_y1 + 92), str(overall["unlocked"]), font=_font(46), fill=GOLD); d.text((sx + vw + 4, tot_y1 + 114), f" / {overall['total']}", font=_font(20), fill=DIM)
    tt_y = tot_y1 + 168; d.text((lx1 + 22, tt_y), "КАТЕГОРИИ", font=_font(11), fill=MUTED); list_y, list_bottom, n, gap_r = tt_y + 24, body_y + body_h - 12 - 22, len(CATEGORIES), 6; rh = max((list_bottom - list_y - gap_r * (n - 1)) // n, 44); progress = get_category_progress(user_id)
    for i, c in enumerate(CATEGORIES):
        cy = list_y + i * (rh + gap_r); color = CATEGORY_COLORS.get(c["color"], SILVER); cnt, total = progress.get(c["key"], {}).get("unlocked", 0), progress.get(c["key"], {}).get("total", 0)
        if c["key"] == active_key: _gradient_box(img, (lx1 + 22, cy, lx2 - 12 - 22, cy + rh), color, color, alpha=28, radius=12); d.rounded_rectangle((lx1 + 22, cy, lx2 - 12 - 22, cy + rh), radius=12, outline=color + (220,), width=2)
        else: d.rounded_rectangle((lx1 + 22, cy, lx2 - 12 - 22, cy + rh), radius=12, fill=INNER_BG + (255,), outline=INNER_BRD + (255,), width=2)
        _alpha_fill(img, (lx1 + 32, cy + (rh - 34)//2, lx1 + 66, cy + (rh + 34)//2), color, alpha=55, radius=9); _icon(d, lx1 + 49, cy + rh // 2 + 1, FA_MAP.get(c.get("icon", "fa-star"), I_STAR), 15, color)
        d.text((lx1 + 78, cy + rh // 2 - 10), c["label"], font=_font(14), fill=TEXT if c["key"] == active_key else TEXT_SOFT); val = f"{cnt} / {total}"; vc = GREEN if cnt == total and total > 0 else (GOLD if cnt > 0 else DIM)
        d.text((lx2 - 34 - _tw(d, val, _font(14)), cy + rh // 2 - 10), val, font=_font(14), fill=vc)
    # Right panel
    _draw_stack_panel(img, d, (rx1, body_y, rx2 - 12, body_y + body_h - 12), radius=22); rpx1, rpx2, rpy = rx1 + 28, rx2 - 12 - 28, body_y + 22
    head_icon_size = 42; d.rounded_rectangle((rpx1, rpy + 2, rpx1 + 6, rpy + 48), radius=3, fill=cat_color + (255,)); _alpha_fill(img, (rpx1 + 20, rpy, rpx1 + 20 + head_icon_size, rpy + head_icon_size), cat_color, alpha=65, radius=11); _icon(d, rpx1 + 41, rpy + 22, FA_MAP.get(cat.get("icon", "fa-star"), I_STAR), 20, cat_color)
    d.text((rpx1 + 78, rpy + 6), cat["label"].upper(), font=_font(24), fill=TEXT); keys = CATEGORY_KEYS.get(active_key, []); cnt = sum(1 for k in keys if k in unlocked); page_idx = CATEGORY_ORDER.index(active_key)
    sw = _tw(d, f"страница {page_idx + 1} / {len(CATEGORY_ORDER)} · {cnt} / {len(keys)} открыто", _font(14)); d.text((rpx2 - sw, rpy + 12), f"страница {page_idx + 1} / {len(CATEGORY_ORDER)} · {cnt} / {len(keys)} открыто", font=_font(14), fill=MUTED)
    sep_y = rpy + 56; d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR + (255,), width=2); grid_y, grid_bottom = sep_y + 16, body_y + body_h - 12 - 26; grid_h = grid_bottom - grid_y
    cell_gap, cols, rows = 14, 3, 2; cell_w = (rpx2 - rpx1 - cell_gap * (cols - 1)) // cols; cell_h = (grid_h - cell_gap * (rows - 1)) // rows
    for idx in range(cols * rows):
        r, c = divmod(idx, cols); cx, cy = rpx1 + c * (cell_w + cell_gap), grid_y + r * (cell_h + cell_gap)
        if idx < len(keys): _draw_ach_card(img, d, cx, cy, cell_w, cell_h, ACHIEVEMENTS.get(keys[idx]), keys[idx] in unlocked, cat_color)
        else: _draw_ach_card(img, d, cx, cy, cell_w, cell_h, None, False, cat_color)
    pw = _tw(d, f"стр. {page_idx + 1} / {len(CATEGORY_ORDER)}", _font(12)); d.text(((rpx1 + rpx2 - pw) // 2, grid_bottom + 6), f"стр. {page_idx + 1} / {len(CATEGORY_ORDER)}", font=_font(12), fill=DIM)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "PNG"); buf.seek(0); return buf

async def _catchup_for_user(user_id: int):
    try:
        dc = get_dc_cache(user_id); bal = dc.get("balance", 0) or 0
        if bal > 0: await check_and_unlock(user_id, "balance", value=bal)
        if dc.get("purchases"): await check_and_unlock(user_id, "first_purchase", value=1)
    except Exception: pass
    try:
        counts = load_json(FILES["review_counts"], {}); rc = int(counts.get(str(user_id), 0) or 0)
        if rc > 0: await check_and_unlock(user_id, "reviews", value=rc); await check_and_unlock(user_id, "buyer_count", value=rc); await check_and_unlock(user_id, "first_review", value=1)
    except Exception: pass
    try:
        from clan.core import get_user_clan, get_user_contribution
        if get_user_clan(user_id): await check_and_unlock(user_id, "clan_deposit", value=get_user_contribution(user_id))
    except Exception: pass
    try:
        from modules.actions import load_roulette_stats
        st = load_roulette_stats(); rolls = int(st.get("rolls", 0) or 0)
        if rolls > 0: await check_and_unlock(user_id, "casino_games", value=rolls)
    except Exception: pass
    try:
        from core.utils import cur
        row = cur.execute("SELECT COUNT(*) AS c FROM quest_progress WHERE user_id=? AND completed_at IS NOT NULL", (user_id,)).fetchone(); qc = row["c"] if row else 0
        if qc > 0: await check_and_unlock(user_id, "quests", value=qc)
    except Exception: pass

async def render_category(inter: disnake.MessageInteraction, category_key: str):
    if category_key not in CATEGORY_ORDER: category_key = CATEGORY_ORDER[0]
    try: await _catchup_for_user(inter.author.id)
    except Exception: pass
    try:
        buf = await asyncio.to_thread(generate_achievements_panel, inter.author.id, category_key)
        fname = f"ach_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"; file = disnake.File(buf, filename=fname); embed = disnake.Embed(color=6776679); embed.set_image(url=f"attachment://{fname}"); view = AchievementsPanelView(category_key)
        kwargs = dict(embed=embed, file=file, attachments=[], view=view)
        if inter.response.is_done(): await inter.edit_original_response(**kwargs)
        else: await inter.response.edit_message(**kwargs)
    except Exception as e:
        try:
            if inter.response.is_done(): await inter.followup.send(f"❌ {str(e)[:200]}", ephemeral=True)
            else: await inter.response.send_message(f"❌ {str(e)[:200]}", ephemeral=True)
        except Exception: pass

async def _return_to_profile(inter: disnake.MessageInteraction):
    try:
        from modules.commands_profile import render_profile_into_interaction, ProfileCardView
        await render_profile_into_interaction(inter, inter.author, ProfileCardView())
    except Exception: pass

class AchievementsPanelView(View):
    def __init__(self, category_key: str = "base"):
        super().__init__(timeout=300); self.category_key = category_key; self._idx = CATEGORY_ORDER.index(category_key) if category_key in CATEGORY_ORDER else 0
        b_back = Button(label=_L_BACK, style=ButtonStyle.gray, custom_id="ach_panel:back", emoji=EMOJI_BACK, row=0); b_back.callback = self._on_back; self.add_item(b_back)
        b_fwd = Button(label=_L_FWD, style=ButtonStyle.gray, custom_id="ach_panel:fwd", emoji=EMOJI_FWD, row=0); b_fwd.callback = self._on_fwd; self.add_item(b_fwd)
    async def _on_back(self, inter: disnake.MessageInteraction):
        try: await inter.response.defer(ephemeral=True)
        except Exception: pass
        if self._idx <= 0: return await _return_to_profile(inter)
        await render_category(inter, CATEGORY_ORDER[self._idx - 1])
    async def _on_fwd(self, inter: disnake.MessageInteraction):
        try: await inter.response.defer(ephemeral=True)
        except Exception: pass
        new_key = CATEGORY_ORDER[0] if self._idx >= len(CATEGORY_ORDER) - 1 else CATEGORY_ORDER[self._idx + 1]
        await render_category(inter, new_key)
