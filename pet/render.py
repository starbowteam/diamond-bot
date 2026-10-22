# -*- coding: utf-8 -*-
import io
import os
from PIL import Image, ImageDraw, ImageFont
from core.utils import ADD_DIR
from pet.core import get_xp_progress, get_pet_name, get_pet_fa, get_pet_bonus, get_xp_for_next, MAX_LEVEL

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

# Палитра
BG        = (10, 10, 12)
CARD_TOP  = (16, 16, 20)
STACK_BG  = (21, 21, 26)
STACK_BRD = (58, 58, 64)
STACK_HDR = (36, 36, 42)
INNER_BG  = (18, 18, 23)
INNER_BRD = (40, 40, 47)
TEXT      = (255, 255, 255)
TEXT_SOFT = (232, 232, 236)
MUTED     = (136, 136, 136)
DIM       = (102, 102, 102)

SILVER    = (198, 208, 224)
SILVER_HI = (224, 232, 245)
GREEN     = (46, 204, 113)
GOLD      = (247, 201, 145)
PURPLE    = (179, 157, 219)
CARD_BRD  = (74, 74, 79)

W, H = 1800, 1000
PAD_X, PAD_Y = 56, 44
BODY_Y = 138
BODY_H = H - PAD_Y - BODY_Y

# Иконки
I_GEM = 0xf3a5
I_USER = 0xf007
I_MEDAL = 0xf5a2
I_TROPHY = 0xf091
I_STAR = 0xf005

def _tw(d, t, f):
    b = d.textbbox((0, 0), t, font=f); return b[2] - b[0]

def _el(d, t, f, w):
    if _tw(d, t, f) <= w: return t
    while t and _tw(d, t + "…", f) > w: t = t[:-1]
    return t + "…"

def _icon(d, cx, cy, code, sz, color):
    f = _fa(sz)
    if f is None: return
    try: d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except: pass

def _grad(img, box, c1, c2, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i in range(w):
        t = i / max(w - 1, 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        ld.line([(i, 0), (i, h)], fill=(r, g, b, alpha))
    if radius > 0:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        a = layer.split()[3]
        a = Image.composite(a, Image.new("L", (w, h), 0), mask)
        layer.putalpha(a)
    img.paste(layer, (x1, y1), layer)

def _canvas(title, user_id, clan_name):
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=28, fill=CARD_TOP + (255,), outline=CARD_BRD + (255,), width=3)

    hx, hy = PAD_X, PAD_Y
    d.rounded_rectangle((hx, hy, hx + 54, hy + 54), radius=14, fill=(58, 58, 64) + (255,))
    _icon(d, hx + 27, hy + 28, I_GEM, 26, SILVER_HI)

    bx = hx + 54 + 18
    d.text((bx, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx + 2, hy + 38), "SHOP & ECOSYSTEM", font=_font(11), fill=MUTED)

    meta_r = W - PAD_X
    lbl = f"ПИТОМЕЦ КЛАНА · {clan_name.upper()}"
    w1 = _tw(d, lbl, _font(11))
    d.text((meta_r - w1, hy + 14), lbl, font=_font(11), fill=MUTED)
    d.text((meta_r - _tw(d, f"UID · {user_id}", _font(20)), hy + 32), f"UID · {user_id}", font=_font(20), fill=TEXT)

    sy = hy + 54 + 16
    d.line((PAD_X, sy, W - PAD_X, sy), fill=STACK_HDR + (255,), width=2)
    return img, d

# ============================================================
# СОСТОЯНИЕ 1: ГЛАВНАЯ
# ============================================================
def render_pet_main(user_id, clan_name, clan_id, balance):
    img, d = _canvas("Главная", user_id, clan_name)
    
    lx1, lx2 = PAD_X, PAD_X + 460
    rx1, rx2 = lx2 + 36, W - PAD_X
    ly1, ly2 = BODY_Y, BODY_Y + BODY_H

    d.rounded_rectangle((lx1, ly1, lx2, ly2), radius=24, fill=STACK_BG + (255,), outline=STACK_BRD + (255,), width=2)
    
    pet_fa = get_pet_fa(clan_id)
    pet_name = get_pet_name(clan_id)
    
    c_glow = (lx1 + (lx2-lx1)//2, ly1 + 160)
    for i in range(3):
        r = 130 - i*20
        d.ellipse((c_glow[0]-r, c_glow[1]-r, c_glow[0]+r, c_glow[1]+r), fill=(179, 157, 219, 10 + i*10))

    d.ellipse((c_glow[0]-80, c_glow[1]-80, c_glow[0]+80, c_glow[1]+80), fill=(30,30,35,255), outline=PURPLE+(255,), width=4)
    _icon(d, c_glow[0], c_glow[1]+2, pet_fa, 60, PURPLE)

    d.text((c_glow[0], c_glow[1]+120), pet_name, font=_font(36), fill=TEXT, anchor="mm")
    
    pet = get_clan_pet(clan_id)
    d.text((c_glow[0], c_glow[1]+170), f"Уровень {pet['level']}", font=_font(22), fill=PURPLE, anchor="mm")
    
    xp, need, pct = get_xp_progress(pet["xp"], pet["level"])
    bar_w = 350
    bar_x1 = c_glow[0] - bar_w//2
    bar_y1 = c_glow[1] + 220
    d.rounded_rectangle((bar_x1, bar_y1, bar_x1+bar_w, bar_y1+18), radius=9, fill=(30,30,35,255), outline=STACK_BRD+(255,), width=2)
    if pct > 0:
        _grad(img, (bar_x1, bar_y1, bar_x1 + int(bar_w*pct/100), bar_y1+18), (106, 155, 209), SILVER, alpha=255, radius=9)
    d.text((c_glow[0], bar_y1+35), f"{xp} / {need} XP" if pet["level"] < MAX_LEVEL else "МАКС. УРОВЕНЬ", font=_font(16), fill=MUTED, anchor="mm")

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
        rem_dc = rem_xp # Теперь 1 XP = 1 DC
        d.text((tx+60, info_y+40), f"До {pet['level']+1} уровня осталось: {rem_xp} XP (~{rem_dc} DC). Бонус вырастет до +{int((pet['level'])*BONUS_PER_LEVEL*100)}%.", font=_font(16), fill=TEXT_SOFT)
    else:
        d.text((tx+60, info_y+40), "Питомец достиг максимального уровня!", font=_font(16), fill=TEXT_SOFT)

    info_y += info_h + 20
    d.rounded_rectangle((tx, info_y, rx2-rpad, info_y+info_h), radius=16, fill=INNER_BG+(255,), outline=INNER_BRD+(255,), width=2)
    _icon(d, tx+30, info_y+45, 0xf05a, 24, PURPLE)
    d.text((tx+60, info_y+15), "КАК КАЧАТЬ?", font=_font(16), fill=PURPLE)
    d.text((tx+60, info_y+40), "• 1 DC = 1 XP. Любой участник клана может кормить. Лимит: 10 000 DC в день.", font=_font(16), fill=TEXT_SOFT)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf

# ============================================================
# СОСТОЯНИЕ 2: ТОП
# ============================================================
def render_pet_top(user_id, clan_name, clan_id, top_list):
    img, d = _canvas("Топ", user_id, clan_name)
    
    cx = W // 2
    d.text((cx, 150), "ТОП КОРМИЛЬЦЕВ", font=_font(52), fill=SILVER_HI, anchor="mm")
    
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

# ============================================================
# СОСТОЯНИЕ 3: О ПИТОМЦЕ
# ============================================================
def render_pet_about(user_id, clan_name):
    img, d = _canvas("О питомце", user_id, clan_name)
    
    cx = W // 2
    _icon(d, cx, 250, 0xf3a5, 100, SILVER_HI)
    
    d.text((cx, 370), "О ПИТОМЦЕ", font=_font(56), fill=SILVER_HI, anchor="mm")
    
    desc = (
        "Ваш клановый питомец — это не просто зверёк, а душа вашего союза.\n"
        "Он растёт вместе с вами и приносит пользу всему клану.\n\n"
        "• Питомца нельзя сменить или выкинуть. Он привязан к клану навсегда.\n"
        "• Прокачивают его все участники клана сообща.\n"
        "• Бонус от уровня прибавляется к общей выплате в конце сезона (до +30%).\n"
        "• Каждое кормление увеличивает ваш вклад в Топ кормильцев."
    )
    
    box_w = 1200
    box_h = 350
    bx1 = cx - box_w//2
    by1 = 430
    d.rounded_rectangle((bx1, by1, bx1+box_w, by1+box_h), radius=24, fill=INNER_BG+(255,), outline=STACK_BRD+(255,), width=2)
    
    lines = desc.split('\n')
    ty = by1 + 40
    for line in lines:
        if not line:
            ty += 20
            continue
        d.text((bx1+50, ty), line, font=_font(22), fill=TEXT_SOFT)
        ty += 40

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf
