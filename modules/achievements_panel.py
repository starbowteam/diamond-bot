# -*- coding: utf-8 -*-
"""
Pillow-рендер панели достижений с категориями.
1800×1000. Левая — счётчик + категории. Правая — сетка 3×4 + страница.
"""
import io
import os
from typing import List, Dict, Set

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, logger
from clan.achievements import ACHIEVEMENTS


FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_FONT_CACHE, _FA_CACHE = {}, {}


def _font(size):
    if size in _FONT_CACHE: return _FONT_CACHE[size]
    try: f = ImageFont.truetype(FONT_BOLD, size)
    except: f = ImageFont.load_default()
    _FONT_CACHE[size] = f; return f


def _fa(size):
    if size in _FA_CACHE: return _FA_CACHE[size]
    f = None
    if os.path.exists(FONT_FA):
        try: f = ImageFont.truetype(FONT_FA, size)
        except: pass
    _FA_CACHE[size] = f; return f


# Палитра (совпадает с profile_card.py)
BG        = (10, 10, 12)
CARD_TOP  = (16, 16, 20)
STACK_BG  = (21, 21, 26)
STACK_BRD = (58, 58, 64)
STACK_HDR = (36, 36, 42)
INNER_BG  = (15, 15, 20)
INNER_BRD = (36, 36, 42)
TEXT      = (255, 255, 255)
TEXT_SOFT = (232, 232, 236)
MUTED     = (136, 136, 136)
DIM       = (102, 102, 102)

SILVER = (198, 208, 224)
GOLD   = (247, 201, 145)
GREEN  = (46, 204, 113)
RED    = (255, 107, 107)
BLUE   = (106, 155, 209)
PURPLE = (179, 157, 219)
ORANGE = (224, 140, 90)

CARD_BRD = (74, 74, 79)


# FA-иконки
I_GEM=0xf3a5; I_TROPHY=0xf091; I_LOCK=0xf023; I_CHECK=0xf00c
I_INFO=0xf05a; I_STAR=0xf005; I_CROWN=0xf521; I_MEDAL=0xf5a2
I_SEED=0xf4d8; I_COMMENT=0xf075; I_MIC=0xf130; I_PEN=0xf304
I_CART=0xf07a; I_BAG=0xf290; I_BRIEF=0xf0b1; I_DIA=0xf219
I_SACK=0xf81d; I_COINS=0xf51e; I_MONEY=0xf53a; I_GIFT=0xf06b
I_CHART=0xf201; I_BANK=0xf19c; I_COMMS=0xf086; I_BULL=0xf0a1
I_FIRE=0xf06d; I_HEAD=0xf025; I_PENF=0xf5ac; I_SCROLL=0xf70e
I_BOOK=0xf02d; I_HAND=0xf4c0; I_CROSS=0xf05b; I_BULL2=0xf140
I_SHIELD=0xf3ed; I_SPADE=0xf2f4; I_DICE=0xf522; I_DICE5=0xf523
I_DICE6=0xf526; I_MONEY2=0xf53b; I_CLOVER=0xf4d8; I_LIST=0xf0ae
I_TICKET=0xf145; I_USERP=0xf234; I_USERS=0xf0c0; I_CAL=0xf274
I_ELL=0xf141; I_ARROW_L=0xf060; I_ARROW_R=0xf061


FA_MAP = {
    "fa-crown": I_CROWN, "fa-medal": I_MEDAL, "fa-star": I_STAR,
    "fa-seedling": I_SEED, "fa-comment": I_COMMENT, "fa-microphone": I_MIC,
    "fa-pen": I_PEN, "fa-cart-shopping": I_CART, "fa-gem": I_GEM,
    "fa-bag-shopping": I_BAG, "fa-briefcase": I_BRIEF, "fa-trophy": I_TROPHY,
    "fa-diamond": I_DIA, "fa-sack-dollar": I_SACK, "fa-coins": I_COINS,
    "fa-money-bill-wave": I_MONEY, "fa-gift": I_GIFT, "fa-chart-line": I_CHART,
    "fa-building-columns": I_BANK, "fa-comments": I_COMMS, "fa-bullhorn": I_BULL,
    "fa-fire": I_FIRE, "fa-headphones": I_HEAD, "fa-pen-fancy": I_PENF,
    "fa-scroll": I_SCROLL, "fa-book": I_BOOK, "fa-hand-holding-dollar": I_HAND,
    "fa-crosshairs": I_CROSS, "fa-bullseye": I_BULL2, "fa-shield-halved": I_SHIELD,
    "fa-spade": I_SPADE, "fa-dice": I_DICE, "fa-dice-five": I_DICE5,
    "fa-dice-six": I_DICE6, "fa-money-bill-1-wave": I_MONEY2, "fa-clover": I_CLOVER,
    "fa-check": I_CHECK, "fa-list-check": I_LIST, "fa-ticket": I_TICKET,
    "fa-user-plus": I_USERP, "fa-users": I_USERS, "fa-calendar-check": I_CAL,
}


# Категории достижений
CATEGORIES = [
    {"key": "base",     "label": "Базовые",     "icon": I_STAR,   "color": GREEN,
     "keys": ["newbie","first_message","first_voice","first_review",
              "first_purchase","creator","king","legend"]},
    {"key": "buyers",   "label": "Покупатели",  "icon": I_BAG,    "color": SILVER,
     "keys": ["role_bronze","role_silver","role_gold","role_diamond",
              "role_crystalis","role_pka","buyer_5","buyer_25","buyer_100","buyer_500"]},
    {"key": "economy",  "label": "Экономика",   "icon": I_COINS,  "color": GOLD,
     "keys": ["rich_10k","rich_500k","rich_1m","generous_10k",
              "investor_5k","investor_500k"]},
    {"key": "activity", "label": "Активность",  "icon": I_COMMS,  "color": BLUE,
     "keys": ["talker_1k","talker_10k","talker_100k","voice_100h",
              "voice_500h","reviewer_50","reviewer_100","reviewer_500"]},
    {"key": "clan",     "label": "Кланы",       "icon": I_SHIELD, "color": PURPLE,
     "keys": ["clan_first_deposit","clan_1k","clan_5k","clan_50k",
              "clan_loyal","clan_hunter","clan_sniper","clan_champion","clan_faithful"]},
    {"key": "casino",   "label": "Казино",      "icon": I_DICE,   "color": RED,
     "keys": ["casino_coin","casino_bj21","casino_jackpot","casino_100",
              "casino_1000","casino_highroller","casino_lucky"]},
    {"key": "quests",   "label": "Квесты",      "icon": I_LIST,   "color": ORANGE,
     "keys": ["quest_first","quest_50","quest_200"]},
    {"key": "staff",    "label": "Персонал",    "icon": I_BRIEF,  "color": (150,180,220),
     "keys": ["staff_first_ticket","staff_10_tickets","staff_100_tickets",
              "staff_perfect","staff_hr_5","staff_hr_50",
              "staff_first_salary","staff_year"]},
]


ACH_COLORS = {"gold": GOLD, "green": GREEN, "blue": BLUE, "purple": PURPLE, "red": RED}


# Утилиты
def _tw(d, text, font):
    b = d.textbbox((0,0), text, font=font); return b[2]-b[0]


def _ellipsis(d, text, font, max_w):
    if _tw(d, text, font) <= max_w: return text
    t = text
    while t and _tw(d, t+"…", font) > max_w: t = t[:-1]
    return t+"…"


def _wrap(d, text, font, max_w, max_lines=2):
    words = (text or "").split(); lines = []; cur = ""
    for w in words:
        test = (cur+" "+w).strip()
        if _tw(d, test, font) <= max_w: cur = test
        else:
            if cur:
                lines.append(cur)
                if len(lines) >= max_lines: return lines
            cur = w
    if cur and len(lines) < max_lines: lines.append(cur)
    return lines or [""]


def _icon(d, cx, cy, code, size, color):
    f = _fa(size)
    if f is None: return
    try: d.text((cx,cy), chr(code), font=f, fill=color, anchor="mm")
    except: pass


def _alpha(base, box, color, alpha=30, radius=0):
    x1,y1,x2,y2 = box; w,h = x2-x1, y2-y1
    if w<=0 or h<=0: return
    layer = Image.new("RGBA",(w,h),(0,0,0,0)); ld = ImageDraw.Draw(layer)
    if radius>0: ld.rounded_rectangle((0,0,w-1,h-1), radius=radius, fill=color+(alpha,))
    else: ld.rectangle((0,0,w-1,h-1), fill=color+(alpha,))
    base.paste(layer,(x1,y1),layer)


def _grad(base, box, c1, c2, alpha=30, radius=0):
    x1,y1,x2,y2 = box; w,h = x2-x1, y2-y1
    if w<=0 or h<=0: return
    layer = Image.new("RGBA",(w,h),(0,0,0,0)); ld = ImageDraw.Draw(layer)
    for i in range(w):
        t = i/max(w-1,1)
        r,g,b = int(c1[0]*(1-t)+c2[0]*t), int(c1[1]*(1-t)+c2[1]*t), int(c1[2]*(1-t)+c2[2]*t)
        ld.line([(i,0),(i,h)], fill=(r,g,b,alpha))
    if radius>0:
        mask = Image.new("L",(w,h),0)
        ImageDraw.Draw(mask).rounded_rectangle((0,0,w-1,h-1), radius=radius, fill=255)
        a = layer.split()[3]
        a = Image.composite(a, Image.new("L",(w,h),0), mask)
        layer.putalpha(a)
    base.paste(layer,(x1,y1),layer)


def _stack_panel(base, d, box, radius=22):
    x1,y1,x2,y2 = box
    _alpha(base, (x1+12,y1+12,x2+12,y2+12), (46,46,52), alpha=110, radius=radius)
    _alpha(base, (x1+6,y1+6,x2+6,y2+6), (46,46,52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG+(255,),
                        outline=STACK_BRD+(255,), width=2)


def _dashed(d, box, radius, color, dash=8, gap=6, width=2):
    x1,y1,x2,y2 = box; r = radius
    def dl(p1,p2):
        dx,dy = p2[0]-p1[0], p2[1]-p1[1]
        L = (dx*dx+dy*dy)**.5
        if L==0: return
        ux,uy = dx/L, dy/L; pos = 0.0
        while pos < L:
            e = min(pos+dash, L)
            d.line([(p1[0]+ux*pos, p1[1]+uy*pos), (p1[0]+ux*e, p1[1]+uy*e)], fill=color, width=width)
            pos = e+gap
    dl((x1+r,y1),(x2-r,y1)); dl((x2-r,y2),(x1+r,y2))
    dl((x1,y1+r),(x1,y2-r)); dl((x2,y1+r),(x2,y2-r))
    d.arc((x1,y1,x1+2*r,y1+2*r),180,270,fill=color,width=width)
    d.arc((x2-2*r,y1,x2,y1+2*r),270,360,fill=color,width=width)
    d.arc((x1,y2-2*r,x1+2*r,y2),90,180,fill=color,width=width)
    d.arc((x2-2*r,y2-2*r,x2,y2),0,90,fill=color,width=width)


def _lighten(c, a=0.4):
    a = max(0,min(1,a))
    return (min(int(c[0]+(255-c[0])*a),255),
            min(int(c[1]+(255-c[1])*a),255),
            min(int(c[2]+(255-c[2])*a),255))


CANVAS_W, CANVAS_H = 1800, 1000
PAD_X, PAD_Y = 56, 44


def _base_canvas(user_id):
    img = Image.new("RGBA",(CANVAS_W,CANVAS_H), BG+(255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0,0,CANVAS_W-1,CANVAS_H-1), radius=30,
                        fill=CARD_TOP+(255,), outline=CARD_BRD+(255,), width=3)
    hx, hy = PAD_X, PAD_Y
    d.rounded_rectangle((hx,hy,hx+54,hy+54), radius=14, fill=(58,58,64)+(255,))
    _icon(d, hx+27, hy+28, I_TROPHY, 26, GOLD)
    bx = hx+54+18
    d.text((bx, hy+4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx+2, hy+38), "SHOP & ECOSYSTEM", font=_font(11), fill=MUTED)
    meta_r = CANVAS_W-PAD_X
    lbl, uid = "ДОСТИЖЕНИЯ", f"#{user_id}"
    w1 = _tw(d, lbl, _font(11)); w2 = _tw(d, uid, _font(20))
    d.text((meta_r-w1, hy+12), lbl, font=_font(11), fill=MUTED)
    d.text((meta_r-w2, hy+32), uid, font=_font(20), fill=TEXT)
    sy = hy+54+16
    d.line((PAD_X, sy, CANVAS_W-PAD_X, sy), fill=STACK_HDR+(255,), width=2)
    return img, d


# ─── Левая панель ───
def _draw_left_panel(img, d, box, unlocked_set, active_key):
    _stack_panel(img, d, box, radius=22)
    x1,y1,x2,y2 = box; pad = 22

    total_all = sum(len(c["keys"]) for c in CATEGORIES)
    total_unlocked = sum(1 for c in CATEGORIES for k in c["keys"] if k in unlocked_set)

    # Счётчик
    tot_y1 = y1+pad; tot_y2 = tot_y1+158
    tx1, tx2 = x1+pad, x2-pad
    _grad(img, (tx1,tot_y1,tx2,tot_y2), GOLD, GOLD, alpha=22, radius=16)
    d.rounded_rectangle((tx1,tot_y1,tx2,tot_y2), radius=16, outline=GOLD+(200,), width=2)
    ib_size=48; ib_x=(tx1+tx2)//2-24; ib_y=tot_y1+18
    _alpha(img,(ib_x,ib_y,ib_x+ib_size,ib_y+ib_size), GOLD, alpha=70, radius=12)
    d.rounded_rectangle((ib_x,ib_y,ib_x+ib_size,ib_y+ib_size), radius=12,
                        outline=GOLD+(230,), width=2)
    _icon(d, ib_x+24, ib_y+25, I_TROPHY, 24, GOLD)
    d.text(((tx1+tx2)//2, tot_y1+76), "ОТКРЫТО", font=_font(11), fill=MUTED, anchor="mm")
    vw = _tw(d, str(total_unlocked), _font(48))
    ow = _tw(d, f" / {total_all}", _font(22))
    sx = (tx1+tx2-vw-ow)//2
    d.text((sx, tot_y1+96), str(total_unlocked), font=_font(48), fill=GOLD)
    d.text((sx+vw+4, tot_y1+96+22), f" / {total_all}", font=_font(22), fill=DIM)

    # Категории
    tt_y = tot_y2+18
    d.text((x1+pad, tt_y), "ПО КАТЕГОРИЯМ", font=_font(11), fill=MUTED)
    list_y = tt_y+24
    list_bottom = y2-pad
    n = len(CATEGORIES); gap = 8
    rh = (list_bottom-list_y-gap*(n-1))//n
    rh = max(rh, 44)

    for i, cat in enumerate(CATEGORIES):
        cy = list_y + i*(rh+gap)
        _draw_cat_row(img, d, x1+pad, cy, (x2-pad)-(x1+pad), rh, cat,
                      unlocked_set, cat["key"]==active_key)


def _draw_cat_row(img, d, x, y, w, h, cat, unlocked_set, active):
    color = cat["color"]; is_act = active
    cnt = sum(1 for k in cat["keys"] if k in unlocked_set); total = len(cat["keys"])

    if is_act:
        _grad(img,(x,y,x+w,y+h),color,color,alpha=28,radius=12)
        d.rounded_rectangle((x,y,x+w,y+h), radius=12, outline=color+(220,), width=2)
    else:
        d.rounded_rectangle((x,y,x+w,y+h), radius=12, fill=INNER_BG+(255,),
                            outline=INNER_BRD+(255,), width=2)

    ic_s=36; ib_x=x+10; ib_y=y+(h-ic_s)//2
    _alpha(img,(ib_x,ib_y,ib_x+ic_s,ib_y+ic_s), color, alpha=55, radius=10)
    _icon(d, ib_x+ic_s//2, ib_y+ic_s//2+1, cat["icon"], 16, color)

    tx = ib_x+ic_s+12
    d.text((tx, y+h//2-10), cat["label"], font=_font(14),
           fill=TEXT if is_act else TEXT_SOFT)

    val = f"{cnt} / {total}"; vf = _font(14)
    vw = _tw(d, val, vf)
    vc = GREEN if cnt==total else (GOLD if cnt>0 else DIM)
    d.text((x+w-12-vw, y+h//2-10), val, font=vf, fill=vc)


# ─── Правая панель ───
def _draw_ach_card(img, d, x, y, w, h, ach, unlocked):
    if ach and unlocked:
        color = ACH_COLORS.get(ach.get("color", "gold"), GOLD)
        _grad(img,(x,y,x+w,y+h),color,color,alpha=18,radius=16)
        d.rounded_rectangle((x,y,x+w,y+h), radius=16, outline=color+(220,), width=2)

        ic_s=54; ib_x=x+16; ib_y=y+16
        _alpha(img,(ib_x,ib_y,ib_x+ic_s,ib_y+ic_s), color, alpha=70, radius=14)
        d.rounded_rectangle((ib_x,ib_y,ib_x+ic_s,ib_y+ic_s), radius=14,
                            outline=color+(230,), width=2)
        fa = FA_MAP.get(ach.get("icon", "fa-star"), I_STAR)
        _icon(d, ib_x+ic_s//2, ib_y+ic_s//2+1, fa, 24, color)

        tx = ib_x+ic_s+14
        name = _ellipsis(d, ach.get("name","—"), _font(15), x+w-16-tx)
        d.text((tx, ib_y+ic_s//2-10), name, font=_font(15), fill=TEXT)

        desc_y = ib_y+ic_s+12
        for i, line in enumerate(_wrap(d, ach.get("desc",""), _font(12), w-32, 2)):
            d.text((x+16, desc_y+i*18), line, font=_font(12), fill=MUTED)

        sy = y+h-26
        d.line((x+16, sy-8, x+w-16, sy-8), fill=color+(60,), width=1)
        _icon(d, x+22, sy+8, I_CHECK, 12, color)
        d.text((x+40, sy), "ПОЛУЧЕНО", font=_font(10), fill=color)

    elif ach:
        d.rounded_rectangle((x,y,x+w,y+h), radius=16, fill=INNER_BG+(255,),
                            outline=(42,42,48)+(255,), width=2)
        _dashed(d,(x,y,x+w,y+h),16,(42,42,48),dash=8,gap=6,width=2)

        ic_s=54; ib_x=x+16; ib_y=y+16
        d.rounded_rectangle((ib_x,ib_y,ib_x+ic_s,ib_y+ic_s), radius=14,
                            fill=(26,26,32)+(255,))
        _icon(d, ib_x+ic_s//2, ib_y+ic_s//2+1, I_LOCK, 22, (58,58,64))

        tx = ib_x+ic_s+14
        name = _ellipsis(d, ach.get("name","—"), _font(15), x+w-16-tx)
        d.text((tx, ib_y+ic_s//2-10), name, font=_font(15), fill=(90,90,96))

        desc_y = ib_y+ic_s+12
        for i, line in enumerate(_wrap(d, ach.get("desc","Условие скрыто"),
                                       _font(12), w-32, 2)):
            d.text((x+16, desc_y+i*18), line, font=_font(12), fill=(70,70,76))

        sy = y+h-26
        d.line((x+16, sy-8, x+w-16, sy-8), fill=(42,42,48)+(255,), width=1)
        d.text((x+22, sy), "НЕ ПОЛУЧЕНО", font=_font(10), fill=(70,70,76))
    else:
        # Пустой слот
        d.rounded_rectangle((x,y,x+w,y+h), radius=16, fill=(12,12,16)+(255,),
                            outline=(28,28,34)+(255,), width=2)
        _dashed(d,(x,y,x+w,y+h),16,(28,28,34),dash=8,gap=6,width=2)
        _icon(d, x+w//2, y+h//2, I_ELL, 24, (46,46,52))


def generate_achievements_panel(user_id, unlocked_set, active_key="base", page=0):
    """
    user_id — id юзера
    unlocked_set — set(str) разблокированных ключей
    active_key — ключ категории
    page — страница внутри категории (0-based), PAGE_SIZE = 12
    """
    img, d = _base_canvas(user_id)

    body_y = 138
    body_h = CANVAS_H - PAD_Y - body_y

    left_w = 448; gap = 30
    lx1 = PAD_X; lx2 = lx1+left_w
    rx1 = lx2+gap; rx2 = CANVAS_W-PAD_X

    # Активная категория
    cat = next((c for c in CATEGORIES if c["key"]==active_key), CATEGORIES[0])

    # Левая панель
    _draw_left_panel(img, d, (lx1, body_y, lx2-12, body_y+body_h-12),
                     unlocked_set, active_key)

    # Правая панель
    _stack_panel(img, d, (rx1, body_y, rx2-12, body_y+body_h-12), radius=22)
    rpx1 = rx1+28; rpx2 = rx2-12-28; rpy = body_y+22

    # Заголовок
    d.rounded_rectangle((rpx1, rpy+4, rpx1+6, rpy+46), radius=3, fill=cat["color"]+(255,))
    d.text((rpx1+22, rpy), f"{cat['label'].upper()} · достижения",
           font=_font(22), fill=TEXT)

    cnt = sum(1 for k in cat["keys"] if k in unlocked_set)
    total = len(cat["keys"])
    sub = f"{cnt} / {total} открыто"
    sw = _tw(d, sub, _font(14))
    d.text((rpx2-sw, rpy+8), sub, font=_font(14), fill=MUTED)

    sep_y = rpy+56
    d.line((rpx1, sep_y, rpx2, sep_y), fill=STACK_HDR+(255,), width=2)

    # Сетка
    grid_y = sep_y+18
    grid_bottom = body_y+body_h-12-46  # оставляем место под номер страницы
    grid_h = grid_bottom-grid_y

    cell_gap = 14; cols, rows = 3, 4
    cell_w = (rpx2-rpx1-cell_gap*(cols-1))//cols
    cell_h = (grid_h-cell_gap*(rows-1))//rows

    PAGE_SIZE = 12
    all_keys = cat["keys"]
    total_pages = max(1, (len(all_keys)+PAGE_SIZE-1)//PAGE_SIZE)
    page = max(0, min(page, total_pages-1))
    slice_keys = all_keys[page*PAGE_SIZE:(page+1)*PAGE_SIZE]

    for idx in range(PAGE_SIZE):
        r = idx//cols; c = idx%cols
        cx = rpx1+c*(cell_w+cell_gap); cy = grid_y+r*(cell_h+cell_gap)
        if idx < len(slice_keys):
            key = slice_keys[idx]
            ach = ACHIEVEMENTS.get(key)
            _draw_ach_card(img, d, cx, cy, cell_w, cell_h, ach, key in unlocked_set)
        else:
            _draw_ach_card(img, d, cx, cy, cell_w, cell_h, None, False)

    # Индикатор страницы
    page_y = body_y+body_h-12-30
    pg_text = f"СТРАНИЦА {page+1} / {total_pages}"
    pw = _tw(d, pg_text, _font(12))
    d.text(((rpx1+rpx2-pw)//2, page_y), pg_text, font=_font(12), fill=DIM)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
