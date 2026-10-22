# -*- coding: utf-8 -*-
import io
import os
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont
from core.utils import ADD_DIR
from pet.core import (
    get_xp_progress, get_pet_name, get_pet_fa, get_pet_bonus, 
    get_xp_for_next, MAX_LEVEL, get_clan_pet, BONUS_PER_LEVEL, 
    get_pet_hourly_income, get_time_to_payout
)

FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_F, _FA = {}, {}

def _font(sz):
    if sz in _F: return _F[sz]
    try: f = ImageFont.truetype(FONT_BOLD, sz)
    except: f = ImageFont.load_default()
    _F[sz] = f; return f

def _fa(sz):
    if sz in _FA: return _FA[sz]
    f = None
    if os.path.exists(FONT_FA):
        try: f = ImageFont.truetype(FONT_FA, sz)
        except: pass
    _FA[sz] = f; return f

BG        = (10, 10, 12)
CARD_TOP  = (16, 16, 20)
STACK_BG  = (21, 21, 26)
STACK_BRD = (58, 58, 64)
INNER_BG  = (18, 18, 23)
INNER_BRD = (40, 40, 47)
TEXT      = (255, 255, 255)
TEXT_SOFT = (232, 232, 236)
MUTED     = (136, 136, 136)
DIM       = (102, 102, 102)

SILVER    = (198, 208, 224)
GREEN     = (46, 204, 113)
GOLD      = (247, 201, 145)
PURPLE    = (179, 157, 219)
CARD_BRD  = (74, 74, 79)

W, H = 1800, 1000
PAD_X, PAD_Y = 56, 44
BODY_Y = 138
BODY_H = H - PAD_Y - BODY_Y

I_GEM = 0xf3a5
I_USER = 0xf007
I_MEDAL = 0xf5a2
I_STAR = 0xf005
I_INFO = 0xf05a
I_CHART = 0xf201

def _tw(d, t, f):
    b = d.textbbox((0, 0), t, font=f); return b[2] - b[0]

def _icon(d, cx, cy, code, sz, color):
    f = _fa(sz)
    if f is None: return
    try: d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except: pass

def _canvas(title, user_id, clan_name):
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=28, fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)

    hx, hy = PAD_X, PAD_Y
    d.rounded_rectangle((hx, hy, hx + 54, hy + 54), radius=14, fill=(58, 58, 64) + (255,))
    _icon(d, hx + 27, hy + 28, I_GEM, 26, SILVER)

    bx = hx + 54 + 18
    d.text((bx, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx + 2, hy + 38), "SHOP & ECOSYSTEM", font=_font(11), fill=MUTED)

    meta_r = W - PAD_X
    lbl = f"ПИТОМЕЦ КЛАНА · {clan_name.upper()}"
    w1 = _tw(d, lbl, _font(12))
    d.text((meta_r - w1, hy + 14), lbl, font=_font(12), fill=PURPLE)
    d.text((meta_r - _tw(d, f"UID · {user_id}", _font(20)), hy + 32), f"UID · {user_id}", font=_font(20), fill=TEXT)

    sy = hy + 54 + 16
    d.line((PAD_X, sy, W - PAD_X, sy), fill=(36, 36, 42) + (255,), width=2)
    return img, d

def render_pet_main(user_id, clan_name, clan_id, balance):
    img, d = _canvas("Главная", user_id, clan_name)
    
    lx1, lx2 = PAD_X, PAD_X + 460
    rx1, rx2 = lx2 + 36, W - PAD_X
    ly1, ly2 = BODY_Y, BODY_Y + BODY_H

    d.rounded_rectangle((lx1, ly1, lx2, ly2), radius=24, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)
    
    pet_fa = get_pet_fa(clan_id)
    pet_name = get_pet_name(clan_id)
    pet = get_clan_pet(clan_id)
    
    c_glow = (lx1 + (lx2-lx1)//2, ly1 + 140)
    d.ellipse((c_glow[0]-80, c_glow[1]-80, c_glow[0]+80, c_glow[1]+80), fill=(26,26,34,255), outline=PURPLE+(255,), width=4)
    _icon(d, c_glow[0], c_glow[1]+2, pet_fa, 60, PURPLE)

    d.text((c_glow[0], c_glow[1]+110), pet_name, font=_font(34), fill=TEXT, anchor="mm")
    d.text((c_glow[0], c_glow[1]+150), f"Уровень {pet['level']}", font=_font(20), fill=PURPLE, anchor="mm")
    
    xp, need, pct = get_xp_progress(pet["xp"], pet["level"])
    bar_w = 360
    bar_x1 = c_glow[0] - bar_w//2
    bar_y1 = c_glow[1] + 180
    d.rounded_rectangle((bar_x1, bar_y1, bar_x1+bar_w, bar_y1+16), radius=8, fill=INNER_BG+(255,), outline=STACK_BRD+(255,), width=2)
    if pct > 0:
        d.rounded_rectangle((bar_x1, bar_y1, bar_x1 + int(bar_w*pct/100), bar_y1+16), radius=8, fill=SILVER+(255,))
    d.text((c_glow[0], bar_y1+30), f"{xp} / {need} XP" if pet["level"] < MAX_LEVEL else "МАКС. УРОВЕНЬ", font=_font(14), fill=MUTED, anchor="mm")

    # Блок дохода
    income_y = ly2 - 140
    d.rounded_rectangle((lx1+30, income_y, lx2-30, income_y+110), radius=16, fill=INNER_BG+(255,), outline=GREEN+(150,), width=2)
    
    hourly = get_pet_hourly_income(pet["level"])
    d.text(((lx1+lx2)//2, income_y+25), f"ДОХОД В КОПИЛКУ: +{hourly:.0f} DC/ч", font=_font(16), fill=GREEN, anchor="mm")
    
    time_left = get_time_to_payout(clan_id)
    h_left = time_left // 3600
    m_left = (time_left % 3600) // 60
    
    if time_left > 0:
        d.text(((lx1+lx2)//2, income_y+60), f"До начисления: {h_left}ч {m_left}м", font=_font(20), fill=TEXT, anchor="mm")
    else:
        d.text(((lx1+lx2)//2, income_y+60), f"Начисление сейчас...", font=_font(20), fill=TEXT, anchor="mm")
        
    d.text(((lx1+lx2)//2, income_y+85), "Деньги падают напрямую в копилку клана", font=_font(12), fill=MUTED, anchor="mm")

    # Правая панель
    d.rounded_rectangle((rx1, ly1, rx2, ly2), radius=24, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)
    
    rpad = 40
    tx = rx1 + rpad
    ty = ly1 + rpad

    d.text((tx, ty), "Сила Питомца", font=_font(36), fill=TEXT)
    bonus = get_pet_bonus(pet["level"])
    
    st_y = ty + 60
    d.rounded_rectangle((tx, st_y, tx+350, st_y+110), radius=16, fill=INNER_BG+(255,), outline=INNER_BRD+(255,), width=2)
    d.rounded_rectangle((tx, st_y, tx+6, st_y+110), radius=3, fill=SILVER+(255,))
    d.text((tx+24, st_y+20), "ТЕКУЩИЙ БОНУС К ПУЛУ", font=_font(14), fill=MUTED)
    d.text((tx+24, st_y+50), f"+{int(bonus*100)}%", font=_font(42), fill=GREEN)

    d.rounded_rectangle((tx+370, st_y, tx+720, st_y+110), radius=16, fill=INNER_BG+(255,), outline=INNER_BRD+(255,), width=2)
    d.rounded_rectangle((tx+370, st_y, tx+376, st_y+110), radius=3, fill=SILVER+(255,))
    d.text((tx+394, st_y+20), "ВСЕГО СКОРМЛЕНО", font=_font(14), fill=MUTED)
    d.text((tx+394, st_y+50), f"{pet['total_fed']:,} DC".replace(",", " "), font=_font(42), fill=SILVER)

    info_y = st_y + 140
    info_h = 90
    
    d.rounded_rectangle((tx, info_y, rx2-rpad, info_y+info_h), radius=16, fill=INNER_BG+(255,), outline=INNER_BRD+(255,), width=2)
    _icon(d, tx+30, info_y+45, I_STAR, 24, SILVER)
    d.text((tx+60, info_y+15), "ТЕКУЩИЙ ЭФФЕКТ", font=_font(16), fill=SILVER)
    d.text((tx+60, info_y+40), f"Ваш {pet_name} на {pet['level']} уровне приносит клану бонус +{int(bonus*100)}% к итоговой выплате.", font=_font(16), fill=TEXT_SOFT)

    info_y += info_h + 20
    d.rounded_rectangle((tx, info_y, rx2-rpad, info_y+info_h), radius=16, fill=INNER_BG+(255,), outline=INNER_BRD+(255,), width=2)
    _icon(d, tx+30, info_y+45, 0xf062, 24, GREEN)
    d.text((tx+60, info_y+15), "ПРОГРЕСС", font=_font(16), fill=GREEN)
    
    if pet["level"] < MAX_LEVEL:
        next_need = get_xp_for_next(pet["level"])
        rem_xp = next_need - pet["xp"]
        rem_dc = rem_xp
        d.text((tx+60, info_y+40), f"До {pet['level']+1} уровня осталось: {rem_xp} XP (~{rem_dc} DC). Бонус вырастет до +{int((pet['level'])*BONUS_PER_LEVEL*100)}%.", font=_font(16), fill=TEXT_SOFT)
    else:
        d.text((tx+60, info_y+40), "Питомец достиг максимального уровня!", font=_font(16), fill=TEXT_SOFT)

    info_y += info_h + 20
    d.rounded_rectangle((tx, info_y, rx2-rpad, info_y+info_h), radius=16, fill=INNER_BG+(255,), outline=INNER_BRD+(255,), width=2)
    _icon(d, tx+30, info_y+45, I_INFO, 24, PURPLE)
    d.text((tx+60, info_y+15), "КАК КАЧАТЬ?", font=_font(16), fill=PURPLE)
    d.text((tx+60, info_y+40), "• 1 DC = 1 XP. Любой участник клана может кормить. Лимит: 10 000 DC в день.", font=_font(16), fill=TEXT_SOFT)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf

def render_pet_top(user_id, clan_name, clan_id, top_list):
    img, d = _canvas("Топ", user_id, clan_name)
    cx = W // 2
    d.text((cx, 150), "ТОП КОРМИЛЬЦЕВ", font=_font(52), fill=SILVER, anchor="mm")
    list_y = 240
    row_h = 80
    gap = 15
    col_w = 1000
    start_x = cx - col_w // 2
    
    if not top_list:
        d.text((cx, 500), "Пока никто не кормил питомца", font=_font(24), fill=DIM, anchor="mm")
    else:
        for i, entry in enumerate(top_list):
            ry = list_y + i * (row_h + gap)
            medal_color = GOLD if i==0 else SILVER if i==1 else (209,146,96) if i==2 else DIM
            d.rounded_rectangle((start_x, ry, start_x + col_w, ry + row_h), radius=16, fill=INNER_BG+(255,), outline=medal_color+(150,), width=2)
            _icon(d, start_x + 40, ry + row_h//2, I_MEDAL, 28, medal_color)
            d.text((start_x + 80, ry + row_h//2), f"#{i+1}", font=_font(24), fill=medal_color, anchor="lm")
            d.text((start_x + 150, ry + row_h//2), entry['username'], font=_font(24), fill=TEXT, anchor="lm")
            d.text((start_x + col_w - 40, ry + row_h//2), f"+{entry['total']:,} DC".replace(",", " "), font=_font(26), fill=GREEN, anchor="rm")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf

def render_pet_about(user_id, clan_name, clan_id):
    img, d = _canvas("О питомце", user_id, clan_name)
    lx1, lx2 = PAD_X, PAD_X + 460
    rx1, rx2 = lx2 + 36, W - PAD_X
    ly1, ly2 = BODY_Y, BODY_Y + BODY_H

    pet_fa = get_pet_fa(clan_id)
    pet_name = get_pet_name(clan_id)
    pet = get_clan_pet(clan_id)
    level = pet["level"]
    xp = pet["xp"]
    total_fed = pet["total_fed"]
    bonus = get_pet_bonus(level)
    
    d.rounded_rectangle((lx1, ly1, lx2, ly2), radius=24, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)
    c_glow = (lx1 + (lx2-lx1)//2, ly1 + 130)
    d.ellipse((c_glow[0]-90, c_glow[1]-90, c_glow[0]+90, c_glow[1]+90), fill=(26,26,34,255), outline=PURPLE+(255,), width=4)
    _icon(d, c_glow[0], c_glow[1]+2, pet_fa, 70, PURPLE)
    d.text((c_glow[0], c_glow[1]+120), pet_name, font=_font(36), fill=TEXT, anchor="mm")
    d.text((c_glow[0], c_glow[1]+165), f"Уровень {level}", font=_font(22), fill=PURPLE, anchor="mm")

    xp_pct = get_xp_progress(xp, level)[2]
    bar_w = 340
    bar_x1 = c_glow[0] - bar_w//2
    bar_y1 = c_glow[1] + 210
    d.text((bar_x1, bar_y1 - 25), "ПРОГРЕСС", font=_font(12), fill=MUTED)
    need_xp = get_xp_for_next(level) if level < MAX_LEVEL else 100
    d.text((bar_x1 + bar_w - _tw(d, f"{xp} / {need_xp} XP", _font(12)), bar_y1 - 25), f"{xp} / {need_xp} XP", font=_font(12), fill=MUTED)
    d.rounded_rectangle((bar_x1, bar_y1, bar_x1+bar_w, bar_y1+16), radius=8, fill=INNER_BG+(255,), outline=STACK_BRD+(255,), width=2)
    if xp_pct > 0:
        d.rounded_rectangle((bar_x1, bar_y1, bar_x1 + int(bar_w*xp_pct/100), bar_y1+16), radius=8, fill=(106, 155, 209)+(255,))

    payout_y = ly2 - 200
    d.rounded_rectangle((lx1 + 30, payout_y, lx2 - 30, payout_y + 160), radius=16, fill=INNER_BG+(255,), outline=GREEN+(150,), width=2)
    d.text(((lx1+lx2)//2, payout_y + 25), "ДАСТ В КОНЦЕ СЕЗОНА", font=_font(15), fill=GREEN, anchor="mm")
    example_bank = 10000
    payout = int(example_bank * bonus)
    d.text(((lx1+lx2)//2, payout_y + 75), f"+{payout:,} DC".replace(",", " "), font=_font(48), fill=TEXT, anchor="mm")
    d.text(((lx1+lx2)//2, payout_y + 120), f"При банке клана {example_bank:,} DC".replace(",", " "), font=_font(14), fill=MUTED, anchor="mm")

    d.rounded_rectangle((rx1, ly1, rx2, ly2), radius=24, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)
    tx = rx1 + 36
    rx_pad = rx2 - 36
    ty = ly1 + 30
    
    st_w = 300
    st_h = 100
    gap = 20
    
    d.rounded_rectangle((tx, ty, tx+st_w, ty+st_h), radius=16, fill=INNER_BG+(255,), outline=INNER_BRD+(255,), width=2)
    d.rounded_rectangle((tx, ty, tx+6, ty+st_h), radius=3, fill=SILVER+(255,))
    d.text((tx+24, ty+20), "ВСЕГО СКОРМЛЕНО", font=_font(14), fill=MUTED)
    d.text((tx+24, ty+48), f"{total_fed:,} DC".replace(",", " "), font=_font(32), fill=SILVER)

    d.rounded_rectangle((tx+st_w+gap, ty, tx+st_w*2+gap, ty+st_h), radius=16, fill=INNER_BG+(255,), outline=INNER_BRD+(255,), width=2)
    d.rounded_rectangle((tx+st_w+gap, ty, tx+st_w+gap+6, ty+st_h), radius=3, fill=GREEN+(255,))
    d.text((tx+st_w+gap+24, ty+20), "ТЕКУЩИЙ БОНУС", font=_font(14), fill=MUTED)
    d.text((tx+st_w+gap+24, ty+48), f"+{int(bonus*100)}%", font=_font(32), fill=GREEN)

    d.rounded_rectangle((tx+st_w*2+gap*2, ty, tx+st_w*3+gap*2, ty+st_h), radius=16, fill=INNER_BG+(255,), outline=INNER_BRD+(255,), width=2)
    d.rounded_rectangle((tx+st_w*2+gap*2, ty, tx+st_w*2+gap*2+6, ty+st_h), radius=3, fill=PURPLE+(255,))
    d.text((tx+st_w*2+gap*2+24, ty+20), "МАКС. БОНУС", font=_font(14), fill=MUTED)
    d.text((tx+st_w*2+gap*2+24, ty+48), f"+{int(get_pet_bonus(MAX_LEVEL)*100)}%", font=_font(32), fill=PURPLE)

    tl_y = ty + st_h + 30
    d.text((tx, tl_y), "ВЕХИ РАЗВИТИЯ", font=_font(20), fill=TEXT)
    _icon(d, tx + _tw(d, "ВЕХИ РАЗВИТИЯ", _font(20)) + 20, tl_y + 10, I_CHART, 20, SILVER)
    
    row_y = tl_y + 40
    row_h = 60
    row_gap = 12
    rows = []
    milestones = [1, 5, 10]
    if level not in milestones:
        milestones.append(level)
        milestones.sort()
        
    for m_lvl in milestones:
        m_bonus = get_pet_bonus(m_lvl)
        rows.append({"lvl": m_lvl, "bonus": m_bonus, "is_done": level > m_lvl, "is_current": level == m_lvl, "req_xp": get_xp_for_next(m_lvl) if m_lvl < MAX_LEVEL else 0})

    for r in rows:
        if r["is_current"]: bg_col, brd_col = (34, 29, 46, 255), PURPLE + (255,)
        elif r["is_done"]: bg_col, brd_col = (18, 26, 20, 255), GREEN + (255,)
        else: bg_col, brd_col = INNER_BG + (255,), INNER_BRD + (255,)
            
        d.rounded_rectangle((tx, row_y, rx_pad, row_y+row_h), radius=12, fill=bg_col, outline=brd_col, width=2)
        d.text((tx+24, row_y+row_h//2), f"Ур. {r['lvl']}", font=_font(20), fill=TEXT, anchor="lm")
        d.text((tx+130, row_y+row_h//2), f"+{int(r['bonus']*100)}%", font=_font(22), fill=GREEN, anchor="lm")
        
        bar_x = tx + 260
        bar_w = 300
        d.rounded_rectangle((bar_x, row_y+row_h//2-6, bar_x+bar_w, row_y+row_h//2+6), radius=6, fill=BG+(255,))
        if r["is_done"]: d.rounded_rectangle((bar_x, row_y+row_h//2-6, bar_x+bar_w, row_y+row_h//2+6), radius=6, fill=GREEN+(255,))
        elif r["is_current"]:
            fill_w = int(bar_w * (xp / max(r["req_xp"], 1)))
            if fill_w > 0: d.rounded_rectangle((bar_x, row_y+row_h//2-6, bar_x+fill_w, row_y+row_h//2+6), radius=6, fill=PURPLE+(255,))
        
        if r["is_done"]: right_str, col = "Достигнуто", GREEN
        elif r["is_current"]: right_str, col = "Текущий", PURPLE
        else: right_str, col = f"{r['req_xp']} XP", MUTED
            
        d.text((rx_pad - 24 - _tw(d, right_str, _font(16)), row_y+row_h//2), right_str, font=_font(16), fill=col, anchor="lm")
        row_y += row_h + row_gap

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
