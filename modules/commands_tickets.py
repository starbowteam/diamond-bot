# -*- coding: utf-8 -*-
"""
Тикеты Diamond Shop — полный модуль.
Включает: инфо-экраны (Pillow), политику, оценку менеджера, отзыв, закрытие.
Один файл — логика + рендеры.
"""
import os
import io
import json
import re
import ast
import math
import asyncio
import time as _time
from datetime import datetime, timezone
from typing import Optional, List, Tuple

import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption
from disnake.ui import Button, Modal, Select, TextInput, View
from PIL import Image, ImageDraw, ImageFont

from core.utils import (
    CONFIG, ADD_DIR, CATALOG_DIR, logger,
    load_json, save_json, now_ts, log_discord,
    has_admin_command_roles, has_review_moderation_roles,
    clean_embed_for_discohook, parse_emoji,
    add_ticket_owner, remove_ticket_owner, get_ticket_owner,
    get_user_tickets_count_in_category,
    assign_ticket_manager, get_ticket_manager, clear_ticket_manager,
    increment_manager_closed, add_manager_rating,
    add_closed_order,
    get_promo_codes,
    save_ticket_review, get_ticket_review, clear_ticket_review,
    set_ticket_cooldown, get_ticket_cooldown, get_ticket_cooldown_info,
    is_supreme,
    cur, db,
)
from modules.dc import (
    add_dc, remove_dc, add_purchase,
    get_user_purchases, remove_purchase,
    get_dc_cache, save_dc_cache,
    get_user_balance,
    load_shop_catalog,
)
from modules.actions import load_action_embed


_IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"

IMG_ORDER_PAID = "https://cdn.discordapp.com/attachments/1527006158282555412/1551608259230695595/image.png?ex=6ab2974c&is=6ab145cc&hm=a6e78b3cb2686d6c61fcf7e618564c04c557856b1af501eb26bf9015793e8a93&"
IMG_RATING = "https://cdn.discordapp.com/attachments/1527006158282555412/1551636456403894383/image.png?ex=6ab2b18f&is=6ab1600f&hm=b735a4db21085a96326573718f9c397d574fd2d6690c5c55a22e7bc33f4da67a&"

HIDDEN_FROM_TICKETS_ROLE_ID = 1513935883475226796
PAY_CONFIRM_DELAY_SECONDS = 60
WARN_CLOSE_COOLDOWN_SECONDS = 2 * 60 * 60
QUESTIONS_CATEGORY_ID = 1544363672128987196

REVIEW_CHANNEL_ID = 1462074763437543435   # 💎・отзывы
REVIEW_CHANNEL_MENTION = f"<#{REVIEW_CHANNEL_ID}>"

P = "\u3164"


# ============================================================
# PILLOW — ХЕЛПЕРЫ
# ============================================================
FONT_BOLD = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")
_FC, _FAC = {}, {}

def _f(sz):
    if sz in _FC: return _FC[sz]
    try: f = ImageFont.truetype(FONT_BOLD, sz)
    except Exception: f = ImageFont.load_default()
    _FC[sz] = f
    return f

def _fa(sz):
    if sz in _FAC: return _FAC[sz]
    f = None
    if os.path.exists(FONT_FA):
        try: f = ImageFont.truetype(FONT_FA, sz)
        except Exception: pass
    _FAC[sz] = f
    return f

BG, CARD_TOP, STACK_BG, STACK_BRD, STACK_HDR = (10,10,12), (16,16,20), (21,21,26), (58,58,64), (36,36,42)
INNER_BG, INNER_BRD = (18,18,23), (40,40,47)
TEXT, TEXT_SOFT, MUTED, DIM = (255,255,255), (232,232,236), (136,136,136), (102,102,102)
SILVER, SILVER_HI, SILVER_DIM = (198,208,224), (224,232,245), (120,132,155)
GREEN, RED, BLUE, PURPLE, GOLD, BRONZE = (46,204,113), (255,107,107), (106,155,209), (179,157,219), (247,201,145), (209,146,96)
GREEN_BG, RED_BG, BLUE_BG, PURPLE_BG, GOLD_BG = (18,44,28), (44,20,20), (20,30,44), (32,26,48), (40,32,21)
CARD_BRD = (74,74,79)

I_GEM, I_STAR, I_CHECK, I_XMARK, I_CROWN = 0xf3a5, 0xf005, 0xf00c, 0xf00d, 0xf521
I_CLOCK, I_INFO, I_USER, I_HAND, I_COINS = 0xf017, 0xf05a, 0xf007, 0xf4c0, 0xf51e
I_SCALE, I_ROTATE, I_BAN, I_TICKET, I_BOX = 0xf24e, 0xf2ea, 0xf05e, 0xf145, 0xf466
I_COMMENT, I_COMMENTS, I_STAR_FILL, I_HEADSET = 0xf075, 0xf086, 0xf005, 0xf590
I_SHOP, I_CART, I_BAG, I_CALENDAR = 0xf54f, 0xf07a, 0xf290, 0xf133

def _tw(d, t, f):
    b = d.textbbox((0,0), t, font=f); return b[2]-b[0]

def _ell(d, t, f, mw):
    if _tw(d,t,f) <= mw: return t
    x = t
    while x and _tw(d, x+"…", f) > mw: x = x[:-1]
    return x+"…"

def _fmt(n):
    try: return f"{int(n):,}".replace(",", " ")
    except Exception: return str(n)

def _di(d, cx, cy, code, sz, color):
    f = _fa(sz)
    if f is None: return
    try: d.text((cx,cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception: pass

def _af(base, box, color, alpha=30, radius=0):
    x1,y1,x2,y2 = box; w,h = x2-x1, y2-y1
    if w<=0 or h<=0: return
    l = Image.new("RGBA", (w,h), (0,0,0,0)); ld = ImageDraw.Draw(l)
    if radius>0: ld.rounded_rectangle((0,0,w-1,h-1), radius=radius, fill=color+(alpha,))
    else: ld.rectangle((0,0,w-1,h-1), fill=color+(alpha,))
    base.paste(l, (x1,y1), l)

def _gb(base, box, c1, c2, alpha=30, radius=0):
    x1,y1,x2,y2 = box; w,h = x2-x1, y2-y1
    if w<=0 or h<=0: return
    l = Image.new("RGBA", (w,h), (0,0,0,0)); ld = ImageDraw.Draw(l)
    for i in range(w):
        t = i/max(w-1,1)
        r = int(c1[0]*(1-t)+c2[0]*t); g = int(c1[1]*(1-t)+c2[1]*t); b = int(c1[2]*(1-t)+c2[2]*t)
        ld.line([(i,0),(i,h)], fill=(r,g,b,alpha))
    if radius>0:
        m = Image.new("L",(w,h),0); ImageDraw.Draw(m).rounded_rectangle((0,0,w-1,h-1), radius=radius, fill=255)
        a = l.split()[3]; a = Image.composite(a, Image.new("L",(w,h),0), m); l.putalpha(a)
    base.paste(l, (x1,y1), l)

def _stack(base, d, box, radius=22):
    x1,y1,x2,y2 = box
    _af(base, (x1+12,y1+12,x2+12,y2+12), (46,46,52), alpha=110, radius=radius)
    _af(base, (x1+6,y1+6,x2+6,y2+6), (46,46,52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius, fill=STACK_BG+(255,), outline=STACK_BRD+(255,), width=3)

CW, CH, M, PX, PY = 1800, 1000, 14, 40, 40

def _canvas(user_id, lbl, status_val):
    img = Image.new("RGBA", (CW,CH), BG+(255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((M,M,CW-1-M,CH-1-M), radius=28, fill=CARD_TOP+(255,), outline=CARD_BRD+(255,), width=3)
    hx, hy = PX, PY
    ls = 64
    d.rounded_rectangle((hx,hy,hx+ls,hy+ls), radius=16, fill=(58,58,64)+(255,), outline=(94,94,100)+(255,), width=2)
    _di(d, hx+ls//2, hy+ls//2+1, I_GEM, 30, SILVER_HI)
    bx = hx+ls+20
    d.text((bx,hy+4), "DIAMOND", font=_f(34), fill=TEXT)
    d.text((bx+4,hy+46), "SHOP & ECOSYSTEM", font=_f(15), fill=MUTED)
    mr = CW-M-PX
    w1 = _tw(d, lbl.upper(), _f(15)); w2 = _tw(d, status_val.upper(), _f(24))
    d.text((mr-w1,hy+14), lbl.upper(), font=_f(15), fill=MUTED)
    d.text((mr-w2,hy+38), status_val.upper(), font=_f(24), fill=TEXT)
    sy = hy+ls+20
    d.line((PX,sy,CW-M-PX,sy), fill=STACK_HDR+(255,), width=2)
    return img, d

def _footer(d, left, right):
    y = CH-M-PY+6
    d.line((PX,y-10,CW-M-PX,y-10), fill=STACK_HDR+(255,), width=2)
    _di(d, PX+12, y+10, I_INFO, 16, DIM)
    d.text((PX+38,y), left, font=_f(15), fill=DIM)
    pw = _tw(d, right, _f(15))
    d.text((CW-M-PX-pw,y), right, font=_f(15), fill=DIM)

def _rhead(d, x1, y1, x2, title, sub):
    d.rounded_rectangle((x1,y1+4,x1+6,y1+50), radius=3, fill=SILVER+(255,))
    d.text((x1+22,y1+2), title.upper(), font=_f(32), fill=TEXT)
    sw = _tw(d, sub.upper(), _f(15))
    d.text((x2-sw,y1+20), sub.upper(), font=_f(15), fill=MUTED)
    d.line((x1,y1+66,x2,y1+66), fill=STACK_HDR+(255,), width=2)

def _leftpanel(img, d, box, header_icon, header_lbl, header_val, blocks):
    _stack(img, d, box, radius=22)
    x1,y1,x2,y2 = box; pad = 28
    isz = 84; ib_x, ib_y = x1+pad, y1+pad
    _gb(img, (ib_x,ib_y,ib_x+isz,ib_y+isz), SILVER, SILVER_DIM, alpha=42, radius=22)
    d.rounded_rectangle((ib_x,ib_y,ib_x+isz,ib_y+isz), radius=22, outline=SILVER+(200,), width=3)
    _di(d, ib_x+isz//2, ib_y+isz//2+1, header_icon, 34, SILVER_HI)
    lbl_x = ib_x+isz+20
    d.text((lbl_x,ib_y+8), header_lbl.upper(), font=_f(14), fill=MUTED)
    vf = _f(42)
    max_w = x2-pad-lbl_x-16
    while _tw(d, header_val+" ", vf) > max_w and vf.size > 22: vf = _f(vf.size-2)
    d.text((lbl_x,ib_y+30), header_val, font=vf, fill=TEXT)
    sy = ib_y+isz+26
    d.line((x1+pad,sy,x2-pad,sy), fill=STACK_HDR+(255,), width=2)
    if blocks:
        bh = 92; gap = 12; ty = sy+26
        for i, b in enumerate(blocks):
            by1 = ty+i*(bh+gap)
            bx1 = x1+pad; bx2 = x2-pad
            c = b["color"]; light = tuple(min(int(v+(255-v)*0.4),255) for v in c)
            border = tuple(min(int(v+(255-v)*0.25),255) for v in c)
            _gb(img, (bx1,by1,bx2,by1+bh), c, c, alpha=30, radius=15)
            d.rounded_rectangle((bx1,by1,bx2,by1+bh), radius=15, outline=border+(255,), width=3)
            d.rounded_rectangle((bx1+4,by1+12,bx1+8,by1+bh-12), radius=2, fill=c+(255,))
            isz2 = 50; ib2x = bx1+20; ib2y = by1+(bh-isz2)//2
            _af(img, (ib2x,ib2y,ib2x+isz2,ib2y+isz2), c, alpha=70, radius=13)
            d.rounded_rectangle((ib2x,ib2y,ib2x+isz2,ib2y+isz2), radius=13, outline=border+(200,), width=2)
            _di(d, ib2x+isz2//2, ib2y+isz2//2+1, b["icon"], 24, c)
            tx = ib2x+isz2+16
            d.text((tx,by1+14), b["label"].upper(), font=_f(13), fill=light)
            vf2 = _f(22)
            bv = _ell(d, b["value"], vf2, bx2-18-tx)
            d.text((tx,by1+42), bv, font=vf2, fill=c)


# ============================================================
# PILLOW — ЭКРАН ПОЛИТИКИ
# ============================================================
def _render_policy(user_id: int) -> io.BytesIO:
    img, d = _canvas(user_id, "политика · магазин", "действует с 26.07.26")
    by = 140; bh = CH-M-PY-by-26
    lw = 460; gap = 30
    lx1, lx2 = PX, PX+lw
    rx1, rx2 = lx2+gap, CW-M-PX
    _leftpanel(img, d, (lx1,by,lx2,by+bh), I_SCALE, "документ", "Политика", [
        {"color": BLUE, "icon": I_CLOCK,  "label": "Срок обработки", "value": "до 2 дней"},
        {"color": RED,  "icon": I_ROTATE, "label": "Возврат",        "value": "75% от суммы"},
        {"color": GREEN,"icon": I_CHECK,  "label": "Гарантия",       "value": "100% выдача"},
    ])
    _stack(img, d, (rx1,by,rx2,by+bh), radius=22)
    inx1 = rx1+30; inx2 = rx2-30
    _rhead(d, inx1, by+22, inx2, "Политика покупки", "читай внимательно")
    cy = by+118; cb = by+bh-22
    n = 4; gp = 12; ch = (cb-cy-gp*(n-1))//n
    rules = [
        {"color": BLUE, "icon": I_CLOCK, "title": "Сроки обработки заказа",
         "text": "Максимальный срок — 2 рабочих дня с момента подтверждения оплаты. В большинстве случаев товар выдаётся в течение 3 часов. Часовой пояс продавца — МСК+5 (UTC+8)."},
        {"color": RED, "icon": I_ROTATE, "title": "Возврат средств",
         "text": "Если вы отказываетесь от заказа после оплаты — возврат 75% от суммы. 25% удерживаются для покрытия комиссий платёжных систем и обработки."},
        {"color": GOLD, "icon": I_BAN, "title": "Стоп-лист",
         "text": "Массовые пинги персонала, продавца или менеджеров, а также агрессивное поведение переводят ваш тикет в «стоп-лист». Такие заказы обрабатываются в последнюю очередь."},
        {"color": GREEN, "icon": I_CHECK, "title": "Подтверждение оплаты",
         "text": "Для подтверждения необходимо прикрепить чек оплаты и указать, куда перевод был сделан. После проверки менеджер подтвердит оплату — и продавец начнёт работу."},
    ]
    for i, r in enumerate(rules):
        ry = cy+i*(ch+gp)
        c = r["color"]; light = tuple(min(int(v+(255-v)*0.4),255) for v in c)
        border = tuple(min(int(v+(255-v)*0.25),255) for v in c)
        _gb(img, (inx1,ry,inx2,ry+ch), c, c, alpha=18, radius=16)
        d.rounded_rectangle((inx1,ry,inx2,ry+ch), radius=16, outline=border+(220,), width=3)
        d.rounded_rectangle((inx1+4,ry+12,inx1+8,ry+ch-12), radius=2, fill=c+(255,))
        isz = 56; ibx = inx1+22; iby = ry+22
        _af(img, (ibx,iby,ibx+isz,iby+isz), c, alpha=70, radius=14)
        d.rounded_rectangle((ibx,iby,ibx+isz,iby+isz), radius=14, outline=light+(230,), width=2)
        _di(d, ibx+isz//2, iby+isz//2+1, r["icon"], 26, light)
        tx = ibx+isz+18
        d.text((tx,ry+26), r["title"].upper(), font=_f(19), fill=light)
        tf = _f(15); words = r["text"].split(); lines = []; cur = ""
        for w in words:
            test = (cur+" "+w).strip()
            if _tw(d, test, tf) <= (inx2-30-tx): cur = test
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        for j, ln in enumerate(lines[:4]):
            d.text((tx, ry+58+j*22), ln, font=tf, fill=TEXT_SOFT)
    _footer(d, "Политика магазина · регламент · v1.0", "политика · 1 / 1")
    buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf


# ============================================================
# PILLOW — ЭКРАН ОЦЕНКИ МЕНЕДЖЕРА (ШАГ 1)
# ============================================================
def _render_rating1(user_id, manager_name, product, order_id) -> io.BytesIO:
    img, d = _canvas(user_id, "оценка · менеджер", f"заказ #{order_id}")
    by = 140; bh = CH-M-PY-by-26
    lw = 460; gap = 30
    lx1, lx2 = PX, PX+lw; rx1, rx2 = lx2+gap, CW-M-PX
    _leftpanel(img, d, (lx1,by,lx2,by+bh), I_HEADSET, "менеджер", f"@{manager_name}", [
        {"color": SILVER, "icon": I_BOX,     "label": "Товар",           "value": product[:24]},
        {"color": GREEN,  "icon": I_CHECK,   "label": "Статус заказа",   "value": "Выполнен"},
        {"color": BLUE,   "icon": I_CLOCK,   "label": "Время обработки", "value": "— минут"},
    ])
    _stack(img, d, (rx1,by,rx2,by+bh), radius=22)
    inx1 = rx1+30; inx2 = rx2-30
    _rhead(d, inx1, by+22, inx2, "Оцени работу", "2 шага до закрытия")
    cy = by+118; cb = by+bh-22
    # HERO звёзды
    hh = 340
    c = GOLD; border = tuple(min(int(v+(255-v)*0.25),255) for v in c)
    _gb(img, (inx1,cy,inx2,cy+hh), c, c, alpha=18, radius=20)
    d.rounded_rectangle((inx1,cy,inx2,cy+hh), radius=20, outline=c+(200,), width=3)
    cx = (inx1+inx2)//2
    tag = "ШАГ 1 · ОЦЕНКА МЕНЕДЖЕРА"
    tf = _f(15); tw = _tw(d, tag, tf); th = 38
    tx1 = cx-tw//2-24
    _af(img, (tx1,cy+24,tx1+tw+48,cy+24+th), c, alpha=55, radius=19)
    d.rounded_rectangle((tx1,cy+24,tx1+tw+48,cy+24+th), radius=19, outline=c+(180,), width=2)
    _di(d, tx1+20, cy+24+th//2, I_STAR, 16, c)
    d.text((tx1+42, cy+24+th//2), tag, font=tf, fill=c, anchor="lm")
    q = "Как прошёл заказ?"
    qf = _f(28); qw = _tw(d, q, qf)
    d.text((cx-qw//2, cy+90), q, font=qf, fill=TEXT)
    sub = "Твоя оценка пойдёт в рейтинг менеджера"
    sf = _f(15); sw = _tw(d, sub, sf)
    d.text((cx-sw//2, cy+130), sub, font=sf, fill=MUTED)
    # 5 звёзд-кнопок
    sc = 100; scg = 22; n = 5
    total = sc*5+scg*4
    sx0 = cx-total//2
    for i in range(5):
        sx = sx0+i*(sc+scg)
        sy = cy+180
        _gb(img, (sx,sy,sx+sc,sy+sc), c, c, alpha=42, radius=22)
        d.rounded_rectangle((sx,sy,sx+sc,sy+sc), radius=22, outline=c+(220,), width=3)
        _di(d, sx+sc//2, sy+sc//2-4, I_STAR, 44, c)
        num = str(i+1); nf = _f(13); nw = _tw(d, num, nf)
        d.text((sx+sc//2-nw//2, sy+sc-22), num, font=nf, fill=c)
    # HINT шаг 2
    hy = cy+hh+12
    hh2 = cb-hy
    c2 = PURPLE; border2 = tuple(min(int(v+(255-v)*0.25),255) for v in c2)
    _gb(img, (inx1,hy,inx2,hy+hh2), c2, c2, alpha=20, radius=18)
    d.rounded_rectangle((inx1,hy,inx2,hy+hh2), radius=18, outline=c2+(220,), width=3)
    d.rounded_rectangle((inx1+4,hy+12,inx1+8,hy+hh2-12), radius=2, fill=c2+(255,))
    isz = 70; ibx = inx1+24; iby = hy+(hh2-isz)//2
    _af(img, (ibx,iby,ibx+isz,iby+isz), c2, alpha=70, radius=16)
    d.rounded_rectangle((ibx,iby,ibx+isz,iby+isz), radius=16, outline=c2+(220,), width=2)
    _di(d, ibx+isz//2, iby+isz//2+1, I_COMMENT, 32, c2)
    tx = ibx+isz+22
    d.text((tx, hy+18), "ШАГ 2 · ОСТАВЬ ОТЗЫВ В КАНАЛЕ", font=_f(14), fill=c2)
    msg = "Канал отзывов — обязателен для закрытия"
    mf = _f(20); d.text((tx, hy+42), msg, font=mf, fill=TEXT)
    sub2 = "За одобренный отзыв начислим +15 DC. Без отзыва тикет закрыть нельзя."
    s2f = _f(13); s2w = _tw(d, sub2, s2f)
    if s2w > inx2-20-tx:
        sub2 = "За отзыв — +15 DC. Без отзыва тикет не закрыть."
    d.text((tx, hy+74), sub2, font=s2f, fill=MUTED)
    _footer(d, f"Оценка менеджера · отзыв в канале отзывов", "тикет · оценка")
    buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf


# ============================================================
# PILLOW — ЭКРАН ОЦЕНКИ (ШАГ 2 — ЖДЁМ ОТЗЫВ)
# ============================================================
def _render_rating2(user_id, manager_name, rating) -> io.BytesIO:
    img, d = _canvas(user_id, "оценка · менеджер", "оценка поставлена")
    by = 140; bh = CH-M-PY-by-26
    lw = 460; gap = 30
    lx1, lx2 = PX, PX+lw; rx1, rx2 = lx2+gap, CW-M-PX
    _leftpanel(img, d, (lx1,by,lx2,by+bh), I_HEADSET, "менеджер", f"@{manager_name}", [
        {"color": GREEN,  "icon": I_STAR,    "label": "Оценка",        "value": f"{rating} / 5"},
        {"color": PURPLE, "icon": I_COMMENT, "label": "Следующий шаг", "value": "Отзыв в канале"},
        {"color": GOLD,   "icon": I_GIFT if False else I_COINS, "label": "Бонус за отзыв", "value": "+15 DC"},
    ])
    _stack(img, d, (rx1,by,rx2,by+bh), radius=22)
    inx1 = rx1+30; inx2 = rx2-30
    _rhead(d, inx1, by+22, inx2, "Остался последний шаг", "без отзыва не закрыть")
    cy = by+118; cb = by+bh-22
    # HERO зелёный
    c = GREEN; border = tuple(min(int(v+(255-v)*0.25),255) for v in c)
    hh = 220
    _gb(img, (inx1,cy,inx2,cy+hh), c, c, alpha=18, radius=20)
    d.rounded_rectangle((inx1,cy,inx2,cy+hh), radius=20, outline=c+(220,), width=3)
    isz = 110; ibx = inx1+28; iby = cy+(hh-isz)//2
    _gb(img, (ibx,iby,ibx+isz,iby+isz), c, c, alpha=60, radius=26)
    d.rounded_rectangle((ibx,iby,ibx+isz,iby+isz), radius=26, outline=c+(230,), width=3)
    _di(d, ibx+isz//2, iby+isz//2+1, I_CHECK, 54, c)
    tx = ibx+isz+26
    d.text((tx, cy+30), "ОЦЕНКА СОХРАНЕНА", font=_f(15), fill=c)
    m1 = f"Спасибо! Менеджер оценён на {rating} звёзд"
    mf = _f(28); d.text((tx, cy+56), m1, font=mf, fill=TEXT)
    m2 = "Осталось совсем немного — написать отзыв в канале"
    d.text((tx, cy+100), m2, font=_f(15), fill=TEXT_SOFT)
    # ПЛАШКА ОТЗЫВА
    hy = cy+hh+14
    hh2 = cb-hy
    c2 = PURPLE; border2 = tuple(min(int(v+(255-v)*0.25),255) for v in c2)
    _gb(img, (inx1,hy,inx2,hy+hh2), c2, c2, alpha=22, radius=18)
    d.rounded_rectangle((inx1,hy,inx2,hy+hh2), radius=18, outline=c2+(230,), width=3)
    d.rounded_rectangle((inx1+4,hy+12,inx1+8,hy+hh2-12), radius=2, fill=c2+(255,))
    isz2 = 80; ibx2 = inx1+26; iby2 = hy+(hh2-isz2)//2
    _af(img, (ibx2,iby2,ibx2+isz2,iby2+isz2), c2, alpha=75, radius=18)
    d.rounded_rectangle((ibx2,iby2,ibx2+isz2,iby2+isz2), radius=18, outline=c2+(220,), width=3)
    _di(d, ibx2+isz2//2, iby2+isz2//2+1, I_COMMENT, 36, c2)
    tx2 = ibx2+isz2+22
    d.text((tx2, hy+16), "ОСТАВЬ ОТЗЫВ В КАНАЛЕ", font=_f(15), fill=c2)
    h1 = "Канал «💎・отзывы» — твой следующий шаг"
    h1f = _f(22); d.text((tx2, hy+42), h1, font=h1f, fill=TEXT)
    h2 = "Напиши пару слов о заказе — за одобренный отзыв начислим +15 DC."
    d.text((tx2, hy+78), h2, font=_f(14), fill=TEXT_SOFT)
    h3 = "После отзыва нажми «Завершить заказ» — и тикет закроется."
    d.text((tx2, hy+100), h3, font=_f(13), fill=MUTED)
    _footer(d, "Оценка менеджера · отзыв в канале · закрытие тикета", "тикет · оценка")
    buf = io.BytesIO(); img.convert("RGB").save(buf, format="PNG"); buf.seek(0); return buf


# ============================================================
# КНОПКА-РАСТЯЖКА (как в BuyAll)
# ============================================================
def _wide_label(text: str) -> str:
    base = f"{P*12}{text}{P*12}"
    if len(base) > 80:
        base = f"{P*9}{text}{P*9}"
    return base


# ============================================================
# ЗАЩИТА ОТ БАГОЮЗА
# ============================================================
_BUY_LOCKS = {}
_BUY_LOCK_TIMEOUT = 15

def _acquire_buy_lock(uid: int) -> bool:
    now = _time.time()
    if uid in _BUY_LOCKS and now - _BUY_LOCKS[uid] < _BUY_LOCK_TIMEOUT: return False
    _BUY_LOCKS[uid] = now
    return True

def _release_buy_lock(uid: int):
    _BUY_LOCKS.pop(uid, None)


# ============================================================
# ОТВЕТ НА ИНТЕРАКЦИЮ БЕЗ ОШИБКИ 10062
# ============================================================
_BG_TASKS: set = set()

def _spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro); _BG_TASKS.add(t); t.add_done_callback(_BG_TASKS.discard); return t

async def _ack(inter, *, ephemeral: bool = False, with_message: bool = False) -> bool:
    try:
        if not inter.response.is_done():
            await inter.response.defer(ephemeral=ephemeral, with_message=with_message)
        return True
    except disnake.InteractionResponded: return True
    except disnake.NotFound as e:
        logger.warning(f"_ack: интеракция просрочена — {e}"); return False
    except Exception as e:
        logger.warning(f"_ack: {e}"); return False

async def _safe_edit(inter, **kwargs) -> bool:
    try:
        if inter.response.is_done(): await inter.edit_original_response(**kwargs)
        else: await inter.response.edit_message(**kwargs)
        return True
    except disnake.InteractionResponded:
        try: await inter.edit_original_response(**kwargs); return True
        except Exception as e: logger.warning(f"_safe_edit: {e}")
    except disnake.NotFound as e: logger.warning(f"_safe_edit: просрочена — {e}")
    except Exception as e: logger.warning(f"_safe_edit: {e}")
    return False

async def _ephemeral_reply(inter, content: str) -> bool:
    try: await inter.edit_original_response(content=content); return True
    except Exception:
        try: await inter.followup.send(content=content, ephemeral=True); return True
        except Exception as e: logger.warning(f"_ephemeral_reply: {e}"); return False


# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _load_slid_embeds():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in [os.path.join(base, "actions", "slid.json"), os.path.join(ADD_DIR, "slid.json")]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f: data = json.load(f)
                return [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            except Exception as e: logger.error(f"slid.json: {e}")
    return []

def clear_ticket_owner(channel):
    uid = get_ticket_owner(channel.id)
    if uid: remove_ticket_owner(channel.id)

def _is_paid_ticket(channel) -> bool:
    if not channel.category: return False
    return channel.category.id == CONFIG["PAID_CATEGORY_ID"]

def _is_coins_ticket(channel) -> bool:
    if not channel.category: return False
    return channel.category.id == CONFIG["COINS_CATEGORY_ID"]

def _is_real_ticket(channel) -> bool:
    if not channel.category: return False
    return channel.category.id == CONFIG["TICKET_CATEGORY_ID"]

def _get_auto_role_names() -> set:
    try:
        catalog = load_shop_catalog(); names = set()
        for k, c in catalog.items():
            if k != "roles": continue
            for _, it in c.get("items", {}).items():
                if it.get("role_id"): names.add(it["name"])
        return names
    except Exception as e: logger.warning(f"_get_auto_role_names: {e}"); return set()

def _filter_purchases_for_ticket(purchases: list) -> list:
    auto = _get_auto_role_names()
    return [p for p in purchases if not (p.get("type") == "roles" and p.get("value") in auto)]

def _build_ticket_overwrites(guild, user) -> dict:
    ow = {
        guild.default_role: disnake.PermissionOverwrite(view_channel=False),
        user: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    hidden = guild.get_role(HIDDEN_FROM_TICKETS_ROLE_ID)
    if hidden: ow[hidden] = disnake.PermissionOverwrite(view_channel=False)
    for rid in CONFIG["TICKET_VIEW_ROLES"]:
        r = guild.get_role(rid)
        if r: ow[r] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    for rid in CONFIG["TICKET_MANAGE_ROLES"]:
        r = guild.get_role(rid)
        if r: ow[r] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    return ow

async def _send_role_review_dm(member, role_name):
    try:
        await member.send(
            f"**Спасибо за покупку роли «{role_name}»!**\n\n"
            f"Не забудь оставить отзыв в {REVIEW_CHANNEL_MENTION} — это очень помогает нам расти 💎"
        )
    except Exception as e: logger.warning(f"_send_role_review_dm {member.id}: {e}")

async def _has_review_in_channel(channel, user_id: int) -> bool:
    rc = channel.guild.get_channel(REVIEW_CHANNEL_ID)
    if not rc: return False
    try:
        created = channel.created_at
        async for m in rc.history(after=created, limit=200):
            if m.author.bot: continue
            if m.author.id == user_id: return True
    except Exception as e: logger.warning(f"_has_review_in_channel: {e}")
    return False

async def _check_ticket_blocked(inter) -> bool:
    uid = inter.author.id
    if is_supreme(uid): return False
    until = get_ticket_cooldown(uid)
    if until > 0:
        info = get_ticket_cooldown_info(uid)
        reason = info.get("reason", "—") if info else "—"
        left = max(1, (until-int(_time.time()))//60)
        if not await _safe_edit(inter, content=(
            f"⚠️ **Вам запрещено создавать тикеты.**\n"
            f"> **Причина:** {reason}\n"
            f"> **Осталось:** ~`{left} мин`\n"
            f"> **Разблокировка:** <t:{until}:R>"
        ), embeds=[], view=None):
            try: await inter.followup.send(f"⛔ Заблокировано. Причина: {reason}", ephemeral=True)
            except Exception: pass
        return True
    return False


# ============================================================
# ФИНАЛЬНОЕ ЗАКРЫТИЕ ТИКЕТА
# ============================================================
async def _do_close_ticket(inter, check_reviews: bool = True):
    channel = inter.channel
    if not await _ack(inter, ephemeral=True, with_message=True): return

    if check_reviews:
        owner_id = get_ticket_owner(channel.id)
        if owner_id:
            is_coins = _is_coins_ticket(channel)

            # Для RUB/PAID — требуем оценку менеджера
            if not is_coins:
                manager_id = get_ticket_manager(channel.id)
                if manager_id:
                    review = get_ticket_review(channel.id)
                    if not review:
                        return await _ephemeral_reply(inter,
                            "❌ Сначала оцени менеджера — нажми на кнопку выше.")

            # Для всех — требуем отзыв в канале отзывов
            has_review = await _has_review_in_channel(channel, owner_id)
            if not has_review:
                return await _ephemeral_reply(inter,
                    f"❌ **Необходимо оставить отзыв в канале.**\n"
                    f"> Перейди в {REVIEW_CHANNEL_MENTION} и напиши отзыв.\n"
                    f"> После этого сможешь закрыть тикет.")

    await _ephemeral_reply(inter, content="Тикет закрывается...")
    await asyncio.sleep(3)
    try:
        manager_id = get_ticket_manager(channel.id)
        if manager_id and _is_paid_ticket(channel):
            increment_manager_closed(manager_id)
            add_closed_order(manager_id, channel.id)
        clear_ticket_owner(channel)
        clear_ticket_manager(channel.id)
        clear_ticket_review(channel.id)
        await channel.delete()
        try:
            if manager_id:
                from clan.achievements import check_and_unlock
                from core.bot import bot
                row = cur.execute("SELECT closed_tickets FROM manager_stats WHERE user_id=?", (manager_id,)).fetchone()
                total = row["closed_tickets"] if row else 0
                await check_and_unlock(manager_id, "staff_tickets", value=total, bot=bot)
        except Exception as e: logger.warning(f"staff tickets ach: {e}")
        await log_discord(
            title="🗑️ Тикет закрыт",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {channel.name}",
            color=0xff6600, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )
        try:
            from modules.commands_staff import send_manager_top
            await send_manager_top()
        except Exception: pass
    except Exception as e: logger.error(f"Ошибка закрытия: {e}")


# ============================================================
# ФЛОУ ЗАКРЫТИЯ (запуск оценки / проверка отзыва / финал)
# ============================================================
async def _start_close_flow(inter):
    """Вызывается кнопкой «Закрыть». Показывает нужный экран."""
    channel = inter.channel
    owner_id = get_ticket_owner(channel.id)
    is_coins = _is_coins_ticket(channel)

    manager_id = get_ticket_manager(channel.id)
    manager_name = "—"
    if manager_id:
        m = inter.guild.get_member(manager_id)
        manager_name = m.display_name if m else str(manager_id)

    # Есть ли отзыв в канале
    has_review = await _has_review_in_channel(channel, owner_id) if owner_id else False

    # Есть ли оценка менеджера
    review_row = get_ticket_review(channel.id) if manager_id else None

    # Для COINS — только отзыв
    if is_coins:
        if has_review:
            # Финальная кнопка
            await inter.response.send_message(
                content=(
                    f"✅ **Отзыв найден!**\n"
                    f"> Можешь закрыть тикет.\n\n"
                    f"> Нажми кнопку ниже."
                ),
                view=FinalCloseView(), ephemeral=True,
            )
        else:
            await inter.response.send_message(
                content=(
                    f"📝 **Оставь отзыв перед закрытием**\n"
                    f"> Перейди в {REVIEW_CHANNEL_MENTION} и напиши пару слов о заказе.\n"
                    f"> За одобренный отзыв мы начисляем **+15 DC**.\n\n"
                    f"> После этого нажми **«Проверить отзыв»** — тикет закроется."
                ),
                view=CoinsReviewCheckView(), ephemeral=True,
            )
        return

    # Для RUB/PAID — сначала оценка
    if not manager_id:
        # Нет менеджера — сразу финал (без оценки)
        if has_review:
            await inter.response.send_message(
                content="✅ Отзыв найден. Можно закрывать.",
                view=FinalCloseView(), ephemeral=True,
            )
        else:
            await inter.response.send_message(
                content=(
                    f"📝 **Оставь отзыв перед закрытием**\n"
                    f"> Напиши отзыв в {REVIEW_CHANNEL_MENTION}, затем нажми «Проверить отзыв»."
                ),
                view=CoinsReviewCheckView(), ephemeral=True,
            )
        return

    if not review_row:
        # Шаг 1 — оценка
        try:
            buf = await asyncio.to_thread(
                _render_rating1, inter.author.id, manager_name,
                "Уточняется в тикете", "—"
            )
            fname = f"rating1_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
            file = disnake.File(buf, filename=fname)
            emb = disnake.Embed(color=6776679); emb.set_image(url=f"attachment://{fname}")
            await inter.response.send_message(
                embed=emb, file=file,
                view=RatingStartView(), ephemeral=True,
            )
        except Exception as e:
            logger.exception(f"_start_close_flow render1: {e}")
            await inter.response.send_message(
                f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True,
            )
        return

    # Есть оценка
    rating_val = review_row.get("rating") if isinstance(review_row, dict) else 5
    if has_review:
        # Финал
        try:
            buf = await asyncio.to_thread(_render_rating2, inter.author.id, manager_name, rating_val)
            fname = f"rating2_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
            file = disnake.File(buf, filename=fname)
            emb = disnake.Embed(color=6776679); emb.set_image(url=f"attachment://{fname}")
            await inter.response.send_message(
                content=f"✅ Отзыв найден! Нажми **«Завершить заказ»** ниже.",
                embed=emb, file=file,
                view=FinalCloseView(), ephemeral=True,
            )
        except Exception as e:
            logger.exception(f"_start_close_flow final: {e}")
            await inter.response.send_message(
                f"✅ Отзыв найден. Нажми «Завершить заказ».",
                view=FinalCloseView(), ephemeral=True,
            )
    else:
        # Шаг 2 — ждём отзыв
        try:
            buf = await asyncio.to_thread(_render_rating2, inter.author.id, manager_name, rating_val)
            fname = f"rating2_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
            file = disnake.File(buf, filename=fname)
            emb = disnake.Embed(color=6776679); emb.set_image(url=f"attachment://{fname}")
            await inter.response.send_message(
                embed=emb, file=file,
                view=RatingWaitingView(), ephemeral=True,
            )
        except Exception as e:
            logger.exception(f"_start_close_flow render2: {e}")
            await inter.response.send_message(
                f"📝 Оставь отзыв в {REVIEW_CHANNEL_MENTION}.",
                view=RatingWaitingView(), ephemeral=True,
            )


# ============================================================
# VIEW: СТАРТ ОЦЕНКИ (1 кнопка растянута)
# ============================================================
class RatingStartView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=_wide_label("🌟 Оценить менеджера"),
        style=ButtonStyle.primary,
        custom_id="ticket_flow:rate_start",
    )
    async def rate_start(self, button, inter: disnake.MessageInteraction):
        manager_id = get_ticket_manager(inter.channel.id)
        if not manager_id:
            return await inter.response.send_message("❌ Менеджер не назначен.", ephemeral=True)
        try:
            await inter.response.send_modal(RatingStarsModal())
        except Exception as e:
            logger.warning(f"rate_start modal: {e}")


# ============================================================
# МОДАЛКА ОЦЕНКИ (1-5)
# ============================================================
class RatingStarsModal(Modal):
    def __init__(self):
        super().__init__(
            title="Оценка менеджера",
            components=[TextInput(
                label="Оценка от 1 до 5",
                placeholder="Введите число: 1, 2, 3, 4 или 5",
                custom_id="rating_val",
                min_length=1, max_length=1,
            )],
        )

    async def callback(self, inter: disnake.ModalInteraction):
        raw = inter.text_values["rating_val"].strip()
        if not raw.isdigit() or int(raw) < 1 or int(raw) > 5:
            return await inter.response.send_message("❌ Введи число от 1 до 5.", ephemeral=True)
        rating = int(raw)

        manager_id = get_ticket_manager(inter.channel.id)
        if not manager_id:
            return await inter.response.send_message("❌ Менеджер не найден.", ephemeral=True)

        add_manager_rating(manager_id, rating)
        save_ticket_review(inter.channel.id, inter.author.id, manager_id, rating)

        # Достижение "идеальный сервис"
        try:
            if rating == 5:
                row = cur.execute("SELECT COUNT(*) AS c FROM ticket_reviews WHERE manager_id=? AND rating=5", (manager_id,)).fetchone()
                if row and row["c"] >= 10:
                    from clan.achievements import unlock_achievement
                    from core.bot import bot
                    await unlock_achievement(manager_id, "staff_perfect", bot=bot)
        except Exception as e: logger.warning(f"staff perfect ach: {e}")

        await log_discord(
            title="⭐ Оценка менеджера",
            description=f"> **Менеджер:** <@{manager_id}>\n> **Оценка:** {rating}/5\n> **Тикет:** {inter.channel.mention}",
            color=0xffaa00, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )

        # Обновляем экран → показываем шаг 2 (ждём отзыв)
        manager = inter.guild.get_member(manager_id)
        manager_name = manager.display_name if manager else str(manager_id)

        try:
            await inter.response.defer(ephemeral=True)
            buf = await asyncio.to_thread(_render_rating2, inter.author.id, manager_name, rating)
            fname = f"rating2_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
            file = disnake.File(buf, filename=fname)
            emb = disnake.Embed(color=6776679); emb.set_image(url=f"attachment://{fname}")
            await inter.edit_original_response(
                content=None, embed=emb, file=file,
                view=RatingWaitingView(),
            )
        except Exception as e:
            logger.exception(f"rating modal update: {e}")
            await inter.edit_original_response(
                content=f"✅ Оценка {rating}/5 сохранена.\n📝 Оставь отзыв в {REVIEW_CHANNEL_MENTION}.",
                embed=None, view=RatingWaitingView(),
            )

        try:
            from modules.commands_staff import send_manager_top
            await send_manager_top()
        except Exception: pass


# ============================================================
# VIEW: ЖДЁМ ОТЗЫВ
# ============================================================
class RatingWaitingView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=_wide_label("✅ Завершить заказ"),
        style=ButtonStyle.success,
        custom_id="ticket_flow:finish_order",
    )
    async def finish(self, button, inter: disnake.MessageInteraction):
        await _do_close_ticket(inter, check_reviews=True)


# ============================================================
# VIEW: COINS — ПРОВЕРКА ОТЗЫВА
# ============================================================
class CoinsReviewCheckView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=_wide_label("🔄 Проверить отзыв"),
        style=ButtonStyle.primary,
        custom_id="ticket_flow:check_review",
    )
    async def check(self, button, inter: disnake.MessageInteraction):
        await _start_close_flow(inter)


# ============================================================
# VIEW: ФИНАЛ — ЗАВЕРШИТЬ ЗАКАЗ
# ============================================================
class FinalCloseView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=_wide_label("✅ Завершить заказ"),
        style=ButtonStyle.success,
        custom_id="ticket_flow:final_close",
    )
    async def close(self, button, inter: disnake.MessageInteraction):
        await _do_close_ticket(inter, check_reviews=True)


# ============================================================
# WARN CLOSE (предупредительное закрытие)
# ============================================================
async def _do_warn_close_ticket(inter: disnake.ModalInteraction, reason: str):
    channel = inter.channel
    owner_id = get_ticket_owner(channel.id)
    if not owner_id:
        return await inter.edit_original_response(content="❌ У тикета нет владельца.")

    owner = inter.guild.get_member(owner_id)
    if not owner:
        try: owner = await inter.guild.fetch_member(owner_id)
        except Exception: owner = None

    owner_is_supreme = is_supreme(owner_id)
    until = set_ticket_cooldown(owner_id, seconds=WARN_CLOSE_COOLDOWN_SECONDS, reason=reason, set_by=inter.author.id)

    if owner:
        try:
            dm_desc = (
                f"> Тикет закрыт менеджером **{inter.author.display_name}**.\n\n"
                f"> **Причина:** {reason}\n\n"
                + ("Вы — **VIP-пользователь**, ограничения не применяются. 💎" if owner_is_supreme
                   else f"**Вам запрещено создавать тикеты на 2 часа.**\nРазблокировка: <t:{until}:R>")
            )
            dm_emb = disnake.Embed(title="⚠️ Предупредительное закрытие", description=dm_desc,
                                   color=0xff6600, timestamp=datetime.now(timezone.utc))
            dm_emb.set_image(url=_IMG_STRIPE)
            await owner.send(embed=dm_emb)
        except Exception: pass

    log_desc = (
        f"> **Менеджер:** {inter.author.mention}\n"
        f"> **Нарушитель:** <@{owner_id}>\n"
        f"> **Канал:** `{channel.name}`\n"
        f"> **Причина:** {reason}\n"
        + ("" if owner_is_supreme else f"> **Блокировка до:** <t:{until}:f>")
    )
    await log_discord(title="⚠️ Предупредительное закрытие", description=log_desc,
                      color=0xff6600, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"])

    clear_ticket_owner(channel); clear_ticket_manager(channel.id); clear_ticket_review(channel.id)
    try:
        resp = (
            f"✅ Тикет закрыт предупредительно.\n"
            f"> **Нарушитель:** <@{owner_id}>"
            + ("" if owner_is_supreme else f"\n> **Блокировка до:** <t:{until}:R>")
        )
        await inter.edit_original_response(content=resp)
    except Exception: pass

    await asyncio.sleep(2)
    try: await channel.delete()
    except Exception as e: logger.warning(f"del channel {channel.name}: {e}")


# ============================================================
# СОЗДАНИЕ ТИКЕТА — REAL
# ============================================================
async def create_real_ticket(inter):
    user = inter.author; guild = inter.guild
    if await _check_ticket_blocked(inter): return
    cat = guild.get_channel(CONFIG["TICKET_CATEGORY_ID"])
    if not cat:
        return await _safe_edit(inter, content="❌ Категория не найдена.", embeds=[], view=None)
    raw = user.display_name.lower().replace(" ", "-")
    raw = re.sub(r"[^a-zа-яё0-9\-_]", "", raw)
    cname = raw[:80] or f"order-{user.id}"
    ow = _build_ticket_overwrites(guild, user)
    await _safe_edit(inter, content="⏳ Создаём тикет...", embeds=[], view=None)
    try:
        tc = await cat.create_text_channel(name=cname, overwrites=ow)
    except Exception as e:
        logger.error(f"create_real_ticket: {e}")
        try: await inter.edit_original_response(content=f"❌ Ошибка: {e}")
        except Exception: pass
        return
    try:
        with open(CONFIG["INFO_TEMPLATE_PATH"], "r", encoding="utf-8") as f: data = json.load(f)
        embs = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]
    except Exception as e:
        logger.error(f"template: {e}"); embs = [disnake.Embed(color=6776679), disnake.Embed(title="Информация о заказе", color=6776679)]
    e_info = embs[1] if len(embs) > 1 else disnake.Embed(title="Информация о заказе", color=0x7c3131)
    e_info.clear_fields()
    e_info.add_field(name="> Заказчик", value=f"```{user.display_name}```", inline=True)
    e_info.add_field(name="> Скидка на товар", value="```Не активирована```", inline=True)
    cur_t = int(_time.time())
    e_info.description = f"Статус - Не оплачен\n> Ожидайте <@&1154757071330365490> для подтверждения.\n> Время заказа: <t:{cur_t}:f>"
    await tc.send(
        f"> Добрый день, {user.mention}, ваш тикет создан. Ожидайте ответа от <@&1154757071330365490>\n"
        f"> После уточнения заказа - менеджер создаст вам счёт.",
        embeds=[embs[0], e_info], view=TicketView(),
    )
    sel_emb = disnake.Embed(
        title="Что именно нужно посмотреть?",
        description="Ниже, выбор - политика, счет, имя, варны.  \n\nВыберите нужный пункт.",
        color=6776679,
    )
    sel_emb.set_image(url=_IMG_STRIPE)
    await tc.send(embed=sel_emb, view=SelectView())
    add_ticket_owner(tc.id, user.id, cat.id)
    try: await inter.edit_original_response(content=f"> {user.mention}   ᶻ 𝘇 𐰁, тикет создан — {tc.mention}")
    except Exception:
        try: await inter.followup.send(f"> {user.mention}   ᶻ 𝘇 𐰁, тикет создан — {tc.mention}", ephemeral=True)
        except Exception: pass
    log_ch = guild.get_channel(CONFIG["LOG_TICKET_CHANNEL_ID"])
    if log_ch:
        await log_ch.send(embed=disnake.Embed(
            title="📩 Тикет создан (реальные деньги)",
            description=f"> **Заказчик:** {user.mention}\n> **Канал:** {tc.mention}",
            timestamp=datetime.now(timezone.utc), color=0x00ff00,
        ))


# ============================================================
# СОЗДАНИЕ ТИКЕТА — DC
# ============================================================
async def create_coins_ticket(inter, purchase: dict, purchase_index: int):
    user = inter.author; guild = inter.guild
    if await _check_ticket_blocked(inter): return
    cat = guild.get_channel(CONFIG["COINS_CATEGORY_ID"])
    if not cat:
        return await _safe_edit(inter, content="❌ Категория не найдена.", embeds=[], view=None)
    item_name = purchase.get("value", "—")
    raw = item_name.lower().replace(" ", "-")
    raw = re.sub(r"[^a-zа-яё0-9\-_]", "", raw)
    cname = raw[:80] or f"item-{user.id}"
    ow = _build_ticket_overwrites(guild, user)
    await _safe_edit(inter, content="⏳ Создаём тикет...", embeds=[], view=None)
    try:
        tc = await cat.create_text_channel(name=cname, overwrites=ow)
    except Exception as e:
        logger.error(f"coins ticket: {e}")
        try: await inter.edit_original_response(content=f"❌ Ошибка: {e}")
        except Exception: pass
        return
    try: await remove_purchase(user.id, purchase_index)
    except Exception as e: logger.warning(f"rm purchase: {e}")
    try:
        with open(CONFIG["COINS_INFO_TEMPLATE_PATH"], "r", encoding="utf-8") as f: data = json.load(f)
        embs = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]
    except Exception as e:
        logger.error(f"coins tmpl: {e}"); embs = [disnake.Embed(color=6776679), disnake.Embed(title="Информация о заказе", color=6776679)]
    e_info = embs[1] if len(embs) > 1 else disnake.Embed(title="Информация о заказе", color=0x7c3131)
    e_info.clear_fields()
    e_info.add_field(name="> Нужный товар", value=f"```{item_name}```", inline=False)
    cur_t = int(_time.time())
    e_info.description = f"Статус - Не оплачен\n> Ожидайте <@&1154757071330365490> для подтверждения.\n> Время: <t:{cur_t}:f>"
    await tc.send(
        content=f"> Добрый день, {user.mention}, ваш тикет на категорию **DC** — создан.\n> Ожидайте ответа от <@&1154757071330365490>.",
        embeds=[embs[0], e_info], view=CoinsTicketButtons(),
    )
    add_ticket_owner(tc.id, user.id, cat.id)
    try: await inter.edit_original_response(content=f"> {user.mention}   ᶻ 𝘇 𐰁, тикет на DC — создан.\n> {tc.mention}")
    except Exception:
        try: await inter.followup.send(f"> {user.mention}   ᶻ 𝘇 𐰁, тикет на DC — создан.\n> {tc.mention}", ephemeral=True)
        except Exception: pass
    log_ch = guild.get_channel(CONFIG["LOG_TICKET_CHANNEL_ID"])
    if log_ch:
        await log_ch.send(embed=disnake.Embed(
            title="📩 Тикет создан (Diamond Coins)",
            description=f"> **Пользователь:** {user.mention}\n> **Канал:** {tc.mention}\n> **Товар:** `{item_name}`",
            timestamp=datetime.now(timezone.utc), color=0x00ff00,
        ))


# ============================================================
# ВЫБОР СПОСОБА ОПЛАТЫ
# ============================================================
class BuySelect(disnake.ui.StringSelect):
    def __init__(self):
        super().__init__(
            placeholder="Выберите способ оплаты или задайте вопрос...",
            min_values=1, max_values=1, custom_id="buy_type_select",
            options=[
                SelectOption(label="Реальные деньги", description="Оплата в рублях, USDT и т.д.", emoji="<:realmomne:1539649281575620618>", value="real"),
                SelectOption(label="Diamond Coins", description="Бонусная валюта сервера", emoji="<:coins:1539649259245408340>", value="coins"),
                SelectOption(label="Задать вопрос", description="Узнать о нужном товаре", emoji="<:questi:1544371841118773328>", value="question"),
            ],
        )

    async def callback(self, inter):
        v = inter.data.values[0] if inter.data.values else ""
        if v == "question":
            try: await inter.response.send_modal(QuestionModal())
            except Exception: pass
            return
        if not await _ack(inter): return
        _spawn(log_discord(
            title="🛒 Выбор типа покупки",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{v}`",
            color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        ))
        if v == "real": await create_real_ticket(inter)
        elif v == "coins":
            purchases = await get_user_purchases(inter.author.id, only_unused=True)
            purchases = [p for p in purchases if p.get("type") != "discounts"]
            purchases = _filter_purchases_for_ticket(purchases)
            if not purchases:
                return await _safe_edit(inter,
                    content="❌ У вас нет товаров для покупки за Diamond Coins.\n> Сначала купите товар в каталоге за DC.",
                    embeds=[], view=None)
            embed = disnake.Embed(
                title="Выбор товара к тикету",
                description="Выберите товар.\nОдин товар — один тикет.",
                color=6776679,
            )
            embed.set_image(url=_IMG_STRIPE)
            await _safe_edit(inter, content=None, embeds=[embed], view=CoinsBuyView(purchases))


class BuyTypeView(View):
    def __init__(self):
        super().__init__(timeout=None); self.add_item(BuySelect())


# ============================================================
# ВЫБОР ТОВАРОВ ЗА DC
# ============================================================
class CoinsBuySelect(disnake.ui.StringSelect):
    def __init__(self, purchases: list):
        self.purchases = purchases
        opts = []
        for idx, p in enumerate(purchases):
            label = p.get("value", "—")
            if len(label) > 90: label = label[:87] + "..."
            ds = datetime.fromtimestamp(p.get("date", 0)).strftime("%d.%m.%Y")
            opts.append(SelectOption(label=label, description=f"Куплено: {ds}", value=str(idx)))
        super().__init__(placeholder="Выберите товар...", min_values=1, max_values=1,
                         options=opts, custom_id="coins_buy_select")

    async def callback(self, inter):
        idx = int(inter.data.values[0])
        if not await _ack(inter): return
        if idx >= len(self.purchases):
            return await _safe_edit(inter, content="❌ Товар не найден.", embeds=[], view=None)
        uid = inter.author.id
        if not _acquire_buy_lock(uid):
            return await inter.followup.send("⏳ Уже обрабатывается...", ephemeral=True)
        try:
            up = await get_user_purchases(uid, only_unused=False)
            tgt = self.purchases[idx]; ti = None
            for i, p in enumerate(up):
                if p.get("value") == tgt.get("value") and p.get("type") == tgt.get("type") and not p.get("used"):
                    ti = i; break
            if ti is None:
                return await _safe_edit(inter, content="❌ Товар уже использован.", embeds=[], view=None)
            await create_coins_ticket(inter, tgt, ti)
        finally:
            _release_buy_lock(uid)


class CoinsBuyView(View):
    def __init__(self, purchases: list):
        super().__init__(timeout=300); self.add_item(CoinsBuySelect(purchases))


# ============================================================
# МОДАЛКА ВОПРОСА
# ============================================================
class QuestionModal(Modal):
    def __init__(self):
        super().__init__(
            title="Задать вопрос", custom_id="question_modal",
            components=[TextInput(label="Что за вопрос вы хотите задать?",
                                  placeholder="Например: Как давно вы занимаетесь магазином?",
                                  custom_id="question", min_length=3, max_length=500)],
        )

    async def callback(self, inter):
        await inter.response.defer(ephemeral=True)
        q = inter.text_values["question"]
        guild = inter.guild
        cat = guild.get_channel(QUESTIONS_CATEGORY_ID)
        if not cat:
            return await inter.edit_original_response(content="❌ Категория не найдена.")
        cname = inter.author.display_name.lower().replace(" ", "-")[:80] or f"question-{inter.author.id}"
        ow = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            inter.author: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        sr = guild.get_role(1423360115335106570)
        if sr: ow[sr] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        ar = guild.get_role(1127428607606796294)
        if ar: ow[ar] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        tc = await cat.create_text_channel(name=cname, overwrites=ow)
        e1 = disnake.Embed(color=6776679)
        e1.set_image(url="https://cdn.discordapp.com/attachments/1064857845838925865/1544369476475158629/image.png?ex=6a9841a8&is=6a96f028&hm=e2f80206537e8c87820b03cccdb39f120cdc1452055767b4e122f455b3f66e1b&")
        cur_t = int(_time.time())
        e2 = disnake.Embed(
            title="Что за вопрос был задан:",
            description=f"> Время: <t:{cur_t}:f>\n> Ответ на вопрос от персонала.",
            color=6776679,
        )
        e2.set_image(url=_IMG_STRIPE)
        e2.add_field(name="> Суть вопроса", value=f"```{q}```")
        await tc.send(
            content=f"<@&1423360115335106570> - задан вопрос, постарайтесь ответить!",
            embeds=[e1, e2], view=QuestionTicketView(),
        )
        await inter.edit_original_response(content=f"> {inter.author.mention}   ᶻ 𝘇 𐰁, тикет с вопросом создан — {tc.mention}")
        await log_discord(
            title="❓ Новый вопрос",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {tc.mention}\n> **Вопрос:** {q}",
            color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )


# ============================================================
# VIEW: КАНАЛ ВОПРОСА
# ============================================================
class QuestionTicketView(View):
    def __init__(self): super().__init__(timeout=None)

    @disnake.ui.button(label="ㅤКак правильно задать вопрос?ㅤ", style=ButtonStyle.gray,
                       custom_id="question:howto",
                       emoji=PartialEmoji(name="pravil", id=1544388874497687622), row=0)
    async def howto(self, button, inter):
        e1 = disnake.Embed(color=6776679)
        e1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1544387485684203682/image.png?ex=6a98526d&is=6a9700ed&hm=e6eb0b7ec153c23c7d63cb3fe64a405c56dee64cc9edbe9792cd69bfe7e4fe3b&")
        e2 = disnake.Embed(
            title="Как правильно задать вопрос?",
            description=(
                "> Чтобы правильно задать вопрос, нужно сформулировать его чётко, кратко и без скрытых подсказок.\n\n"
                "`Определите цель:` Поймите, какая информация нужна.\n"
                "`Говорите просто:` Избегайте сложных терминов.\n"
                "`Используйте открытые вопросы:` «что», «как», «почему».\n"
                "`Добавляйте контекст:` Опишите, что вы уже сделали."
            ),
            color=6776679,
        )
        e2.set_image(url=_IMG_STRIPE)
        await inter.response.send_message(embeds=[e1, e2])
        await log_discord(
            title="📖 Просмотр инструкции по вопросам",
            description=f"> **Канал:** {inter.channel.mention}\n> **Пользователь:** {inter.author.mention}",
            color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )

    @disnake.ui.button(label="ㅤㅤЗакрытьㅤㅤ", style=ButtonStyle.gray,
                       custom_id="question:close",
                       emoji=PartialEmoji(name="OffTicket", id=1539657125716824185), row=0)
    async def close(self, button, inter):
        if not any(r.id == 1423360115335106570 for r in inter.author.roles) and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие.", ephemeral=True)
        await inter.response.send_message("Канал закрывается...", ephemeral=True)
        await asyncio.sleep(1)
        ch = inter.channel
        try: await ch.delete()
        except Exception: pass
        await log_discord(
            title="❓ Вопрос закрыт",
            description=f"> **Канал:** {ch.name}\n> **Закрыл:** {inter.author.mention}",
            color=0xff6600, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )


# ============================================================
# МОДАЛКИ: переименование / предупр. закрытие / счёт / промокод
# ============================================================
class RenameTicketModal(Modal):
    def __init__(self):
        super().__init__(
            title="✏️ Изменение названия тикета", custom_id="rename_ticket_modal",
            components=[TextInput(label="Новое название тикета", placeholder="Введите новое название",
                                  custom_id="new_name", min_length=2, max_length=80)],
        )

    async def callback(self, inter):
        raw = inter.text_values["new_name"].strip()
        nn = raw.lower().replace(" ", "-")
        nn = re.sub(r"[^a-zа-яё0-9\-_]", "", nn)[:80]
        if not nn:
            return await inter.response.send_message("❌ Введите корректное название.", ephemeral=True)
        ch = inter.channel; old = ch.name
        try: await ch.edit(name=nn)
        except Exception as e:
            return await inter.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)
        try:
            await ch.send(content=f"> **Тикет переименован** — новый заказ: **{raw}**\n> Выполнение заказа скоро начнётся, ожидайте.")
        except Exception: pass
        await inter.response.send_message(f"✅ Название: `{old}` → `{nn}`.", ephemeral=True)
        await log_discord(
            title="✏️ Название тикета изменено",
            description=f"> **Кем:** {inter.author.mention}\n> **Тикет:** {ch.mention}\n> **Было:** `{old}`\n> **Стало:** `{nn}`",
            color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )


class WarnCloseModal(Modal):
    def __init__(self):
        super().__init__(
            title="⚠️ Предупредительное закрытие",
            components=[TextInput(label="Причина предупреждения",
                                  placeholder="Опишите причину (увидит нарушитель и лог)",
                                  custom_id="warn_reason", min_length=3, max_length=200)],
        )

    async def callback(self, inter):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        reason = inter.text_values["warn_reason"].strip()
        if not reason:
            return await inter.response.send_message("❌ Причина обязательна.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        await _do_warn_close_ticket(inter, reason)


# ============================================================
# ВЫБОР ДЕЙСТВИЙ В ТИКЕТЕ
# ============================================================
class TicketActionSelect(disnake.ui.StringSelect):
    def __init__(self):
        super().__init__(
            placeholder="Выберите действие...", min_values=1, max_values=1,
            custom_id="ticket_action_select",
            options=[
                SelectOption(label="Счет на оплату", description="Сгенерировать счёт на оплату",
                             emoji="<:Rekvi:1539656975091105892>", value="requisites"),
                SelectOption(label="Политика", description="Правила и условия магазина",
                             emoji="<:Politic:1539657020695650384>", value="policy"),
                SelectOption(label="Изменить название тикета", description="Изменения для удобства выполнения.",
                             emoji="<:image:1550869363266027641>", value="rename"),
                SelectOption(label="Предупредительное закрытие", description="Закрыть тикет с блокировкой юзера на 2 часа.",
                             emoji="<:warn:1552325395171381388>", value="warn_close"),
            ],
        )

    async def callback(self, inter):
        v = inter.data.values[0]
        if v == "requisites":
            if not any(r.id == 1154757071330365490 for r in inter.author.roles):
                return await inter.response.send_message("⛔ Кнопка доступна только менеджерам.", ephemeral=True)
            await inter.response.send_modal(InvoiceModal())
        elif v == "policy":
            await self.send_policy(inter)
        elif v == "rename":
            if not _is_paid_ticket(inter.channel):
                return await inter.response.send_message(
                    "⛔ **Кнопка доступна только для оплаченных тикетов.**\n> Дождитесь подтверждения оплаты.",
                    ephemeral=True)
            mgr = get_ticket_manager(inter.channel.id)
            is_admin = has_admin_command_roles(inter.author)
            if not is_admin:
                if mgr is None:
                    return await inter.response.send_message("⛔ Менеджер ещё не назначен.", ephemeral=True)
                if inter.author.id != mgr:
                    return await inter.response.send_message(f"⛔ Назначенный менеджер: <@{mgr}>", ephemeral=True)
            await inter.response.send_modal(RenameTicketModal())
        elif v == "warn_close":
            if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
                return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
            await inter.response.send_modal(WarnCloseModal())

    async def send_policy(self, inter):
        # Показываем Pillow-политику
        try:
            await inter.response.defer(ephemeral=True)
            buf = await asyncio.to_thread(_render_policy, inter.author.id)
            fname = f"policy_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
            file = disnake.File(buf, filename=fname)
            emb = disnake.Embed(color=6776679); emb.set_image(url=f"attachment://{fname}")
            await inter.followup.send(embed=emb, file=file, ephemeral=True)
            await log_discord(
                title="📜 Просмотр политики",
                description=f"> **Кем:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
                color=0x00ff00, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
            )
        except Exception as e:
            logger.exception(f"policy render: {e}")
            try: await inter.followup.send(f"❌ Ошибка: `{str(e)[:200]}`", ephemeral=True)
            except Exception: pass


class SelectView(View):
    def __init__(self):
        super().__init__(timeout=None); self.add_item(TicketActionSelect())


# ============================================================
# МОДАЛКА СЧЁТА
# ============================================================
class InvoiceModal(Modal):
    def __init__(self):
        super().__init__(
            title="Создание счёта", custom_id="invoice_modal",
            components=[
                TextInput(label="Товар / Услуга", placeholder="Например: Discord Nitro 1 Month", custom_id="product", min_length=2, max_length=80),
                TextInput(label="Введите сумму для счёта", placeholder="Например: 445", custom_id="amount", min_length=1, max_length=10),
                TextInput(label="Скидка в %, если была (необязательно)", placeholder="Например: 10", custom_id="discount", required=False, max_length=3),
            ],
        )

    async def callback(self, inter):
        await inter.response.defer(ephemeral=True)
        from modules.receipt import generate_receipt_png, generate_receipt_id
        pn = inter.text_values["product"].strip()
        astr = inter.text_values["amount"].strip()
        dstr = inter.text_values.get("discount", "").strip()
        if not astr.isdigit():
            return await inter.edit_original_response(content="❌ Сумма — число.")
        amount = int(astr)
        if amount <= 0:
            return await inter.edit_original_response(content="❌ Сумма > 0.")
        dp = 0
        if dstr:
            if not dstr.isdigit(): return await inter.edit_original_response(content="❌ Скидка — число.")
            dp = int(dstr)
            if dp < 0 or dp > 100: return await inter.edit_original_response(content="❌ Скидка 0-100%.")
        mid = get_ticket_manager(inter.channel.id)
        mgr = inter.guild.get_member(mid) if mid else None
        mn = str(mgr) if mgr else "—"
        oid = get_ticket_owner(inter.channel.id)
        ow = inter.guild.get_member(oid) if oid else None
        cn = ow.display_name if ow else inter.channel.name
        order_id = generate_receipt_id()
        buf = await asyncio.to_thread(generate_receipt_png, manager_name=mn, customer_name=cn,
                                      product_name=pn, amount=amount, discount_percent=dp, order_id=order_id)
        total = amount - int(amount * dp / 100)
        file = disnake.File(buf, filename=f"receipt_{order_id}.png")
        emb = disnake.Embed(title=f"Счёт для оплаты создан: к оплате {total} Р", color=6776679)
        emb.set_image(url=f"attachment://receipt_{order_id}.png")
        await inter.channel.send(embed=emb, file=file)
        await inter.edit_original_response(content="✅ Счёт отправлен.")
        await log_discord(
            title="🧾 Создан счёт",
            description=f"> **Менеджер:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}\n> **Товар:** {pn}\n> **Сумма:** {amount} Р" + (f"\n> **Скидка:** {dp}%" if dp > 0 else "") + f"\n> **Итого:** {total} Р",
            color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )


# ============================================================
# МОДАЛКА ПРОМОКОДА
# ============================================================
class PromoCodeModal(Modal):
    def __init__(self, original_view: View):
        self.original_view = original_view
        super().__init__(
            title="🎟️ Ввод промокода", custom_id="promo_code_modal",
            components=[TextInput(label="Промокод", placeholder="Введите код промокода",
                                  custom_id="promo_code", min_length=1, max_length=50)],
        )

    async def callback(self, inter):
        code = inter.text_values["promo_code"].strip().upper()
        codes = get_promo_codes()
        if code not in codes:
            return await inter.response.send_message("❌ Промокод не найден.", ephemeral=True)
        val = codes[code]
        ch = inter.channel; tgt = None
        async for m in ch.history(limit=50):
            if m.author == inter.bot.user and m.embeds and len(m.embeds) >= 2:
                tgt = m; break
        if not tgt:
            return await inter.response.send_message("❌ Сообщение не найдено.", ephemeral=True)
        ed = tgt.embeds[1].to_dict()
        for f in ed.get("fields", []):
            if "скидка" in f.get("name", "").lower():
                f["value"] = f"```{code} — {val}```"; break
        ne = disnake.Embed.from_dict(ed)
        embs = list(tgt.embeds); embs[1] = ne
        await tgt.edit(embeds=embs)
        try:
            for c in self.original_view.children: c.disabled = True
            await inter.message.edit(view=self.original_view)
        except Exception: pass
        await inter.response.send_message(f"✅ Промокод **{code}** активирован!\n> Скидка: `{val}`", ephemeral=True)
        await log_discord(
            title="🎟️ Промокод активирован",
            description=f"> **Кем:** {inter.author.mention}\n> **Тикет:** {ch.mention}\n> **Код:** `{code}` — {val}",
            color=0x00ff00, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )


# ============================================================
# VIEW: TICKET (REAL) — кнопки в оплаченном сообщении
# ============================================================
class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        b1 = Button(label="ㅤЗакрытьㅤ", style=ButtonStyle.gray, custom_id="ticket:close",
                    emoji=PartialEmoji(name="OffTicket", id=1539657125716824185), row=0)
        b1.callback = self.close_callback
        self.add_item(b1)
        b2 = Button(label="ㅤОплатитьㅤ", style=ButtonStyle.gray, custom_id="ticket:pay",
                    emoji=PartialEmoji(name="Oplacheno", id=1539657164778512496), row=0)
        b2.callback = self.pay_callback
        self.add_item(b2)
        b3 = Button(label="ㅤㅤСкидкиㅤㅤ", style=ButtonStyle.gray, custom_id="ticket:discounts",
                    emoji=PartialEmoji(name="skidka", id=1540819242625146961), row=0)
        b3.callback = self.discounts_callback
        self.add_item(b3)

    async def close_callback(self, inter):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав на закрытие.", ephemeral=True)
        ch = inter.channel
        mgr = get_ticket_manager(ch.id)
        if mgr and inter.author.id != mgr and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Тикет ведёт другой менеджер.", ephemeral=True)
        await _start_close_flow(inter)

    async def pay_callback(self, inter):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав на подтверждение оплаты.", ephemeral=True)
        ch = inter.channel
        try: age = _time.time() - ch.created_at.timestamp()
        except Exception: age = PAY_CONFIRM_DELAY_SECONDS
        if age < PAY_CONFIRM_DELAY_SECONDS:
            left = int(PAY_CONFIRM_DELAY_SECONDS - age)
            return await inter.response.send_message(
                f"⏳ **Слишком рано.**\n> Подтвердить оплату можно через **{left} сек** после создания тикета.",
                ephemeral=True)
        mgr = get_ticket_manager(ch.id)
        if mgr and inter.author.id != mgr and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Тикет ведёт другой менеджер.", ephemeral=True)
        msg = inter.message
        if not msg.embeds or len(msg.embeds) < 2:
            async for m in ch.history(limit=50):
                if m.author == inter.bot.user and m.embeds and len(m.embeds) >= 2:
                    msg = m; break
        if not msg.embeds or len(msg.embeds) < 2:
            return await inter.response.send_message("❌ Сообщение с заказом не найдено.", ephemeral=True)
        desc = msg.embeds[1].description or ""
        if "Статус - Заказ оплачен" in desc:
            return await inter.response.send_message("Заказ уже оплачен.", ephemeral=True)
        oe = msg.embeds[1]; ed = oe.to_dict()
        ed["color"] = 0x676767
        ed["description"] = f"Статус - Заказ оплачен\n> Подтверждено: {inter.author.mention}\n> Время: <t:{int(_time.time())}:f>"
        paid_view = TicketPaidView()
        await msg.edit(embeds=[msg.embeds[0], disnake.Embed.from_dict(ed)], view=paid_view)
        pc = inter.guild.get_channel(CONFIG["PAID_CATEGORY_ID"])
        if pc: await ch.edit(category=pc)
        emb = disnake.Embed(title="💚 Заказ оплачен", description=f"> **Подтвердил:** {inter.author.mention}", color=0x2ecc71)
        emb.set_image(url=_IMG_STRIPE)
        await ch.send(embed=emb)
        try:
            oid = get_ticket_owner(ch.id); om = inter.guild.get_member(oid) if oid else None
            if om:
                d1 = disnake.Embed(color=6776679); d1.set_image(url=IMG_ORDER_PAID)
                d2 = disnake.Embed(
                    title="💚 Ваш заказ подтверждён как оплачен!",
                    description=f"> Менеджер **{inter.author.display_name}** подтвердил оплату.\n\n> **Тикет:** {ch.mention}\n\n> Скоро приступим к выполнению.",
                    color=0x2ecc71, timestamp=datetime.now(timezone.utc),
                )
                d2.set_image(url=_IMG_STRIPE)
                await om.send(embeds=[d1, d2])
        except Exception as e: logger.warning(f"DM при оплате: {e}")
        await inter.response.send_message("✅ Заказ отмечен как оплаченный.", ephemeral=True)
        await log_discord(
            title="💰 Заказ оплачен",
            description=f"> **Канал:** {ch.mention}\n> **Подтвердил:** {inter.author.mention}",
            color=0x2ecc71, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )

    async def discounts_callback(self, inter):
        ch = inter.channel
        oid = get_ticket_owner(ch.id)
        if not oid or inter.author.id != oid:
            return await inter.response.send_message("⛔ Только создатель тикета.", ephemeral=True)
        applied = False
        async for m in ch.history(limit=50):
            if m.author == inter.bot.user and m.embeds and len(m.embeds) >= 2:
                for f in m.embeds[1].fields:
                    if "скидка" in f.name.lower():
                        val = f.value.strip("`\n ")
                        if val not in ["Не активирована", "Не введён", "Не активирован"]:
                            applied = True
                        break
                break
        if applied:
            return await inter.response.send_message("❌ Скидка уже применена.", ephemeral=True)
        all_p = await get_user_purchases(inter.author.id, only_unused=True)
        discounts = [p for p in all_p if p.get("type") == "discounts"]
        slid = _load_slid_embeds() or [disnake.Embed(title="📦 Ваши скидки", description="> Введи промокод или выбери купленную скидку.", color=6776679)]
        view = View(timeout=300)
        b = Button(label="Ввести промокод", style=ButtonStyle.gray,
                   custom_id=f"promo_input_{inter.author.id}",
                   emoji=PartialEmoji(name="prom1", id=1539646792139014234), row=0)

        async def promo_cb(inter2, _view=view):
            if inter2.author.id != inter.author.id:
                return await inter2.response.send_message("⛔ Не ваш тикет.", ephemeral=True)
            await inter2.response.send_modal(PromoCodeModal(original_view=_view))

        b.callback = promo_cb; view.add_item(b)
        row = 0; col = 1
        for idx, p in enumerate(discounts):
            if col >= 3: row += 1; col = 0
            lbl = p["value"][:80]
            bt = Button(label=lbl, style=ButtonStyle.gray, custom_id=f"apply_disc_{inter.author.id}_{idx}", row=row)
            bt.callback = self._create_disc_cb(idx, inter, discounts)
            view.add_item(bt); col += 1
        await inter.response.send_message(embeds=slid, view=view, ephemeral=True)

    def _create_disc_cb(self, di, oi, discounts):
        async def cb(inter):
            if inter.author.id != oi.author.id:
                return await inter.response.send_message("⛔ Не ваш товар.", ephemeral=True)
            if di >= len(discounts):
                return await inter.response.send_message("❌ Уже применена.", ephemeral=True)
            ch = inter.channel; applied = False
            async for m in ch.history(limit=50):
                if m.author == inter.bot.user and m.embeds and len(m.embeds) >= 2:
                    for f in m.embeds[1].fields:
                        if "скидка" in f.name.lower():
                            v = f.value.strip("`\n ")
                            if v not in ["Не активирована", "Не введён", "Не активирован"]: applied = True
                            break
                    break
            if applied:
                return await inter.response.send_message("❌ Уже применена.", ephemeral=True)
            iv = discounts[di]["value"]
            full = await get_user_purchases(inter.author.id, only_unused=False)
            ti = None
            for i, p in enumerate(full):
                if p["value"] == iv and p.get("type") == "discounts" and not p.get("used"): ti = i; break
            if ti is None:
                return await inter.response.send_message("❌ Скидка не найдена.", ephemeral=True)
            if not await remove_purchase(inter.author.id, ti):
                return await inter.response.send_message("❌ Ошибка.", ephemeral=True)
            async for m in ch.history(limit=50):
                if m.author == inter.bot.user and m.embeds and len(m.embeds) >= 2:
                    ed = m.embeds[1].to_dict()
                    for f in ed.get("fields", []):
                        if "скидка" in f.get("name", "").lower(): f["value"] = f"```{iv}```"; break
                    ne = disnake.Embed.from_dict(ed)
                    embs = list(m.embeds); embs[1] = ne
                    await m.edit(embeds=embs); break
            try:
                if inter.message and inter.message.components: await inter.message.edit(view=View())
            except Exception: pass
            await inter.response.send_message(f"✅ Скидка **{iv}** применена!", ephemeral=True)
            await log_discord(
                title="🛒 Применена скидка",
                description=f"> **Кем:** {inter.author.mention}\n> **Тикет:** {ch.mention}\n> **Скидка:** {iv}",
                color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
            )
        return cb


# ============================================================
# VIEW: TICKET PAID
# ============================================================
class TicketPaidView(View):
    def __init__(self):
        super().__init__(timeout=None)
        b1 = Button(label="ㅤЗакрытьㅤ", style=ButtonStyle.gray, custom_id="ticket_paid:close",
                    emoji=PartialEmoji(name="OffTicket", id=1539657125716824185), row=0)
        b1.callback = self.close_callback
        self.add_item(b1)
        b2 = Button(label="ㅤОплатитьㅤ", style=ButtonStyle.gray, custom_id="ticket_paid:pay_done",
                    emoji=PartialEmoji(name="Oplacheno", id=1539657164778512496), row=0, disabled=True)
        self.add_item(b2)
        b3 = Button(label="ㅤㅤСкидкиㅤㅤ", style=ButtonStyle.gray, custom_id="ticket_paid:discounts_done",
                    emoji=PartialEmoji(name="skidka", id=1540819242625146961), row=0, disabled=True)
        self.add_item(b3)

    async def close_callback(self, inter):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        ch = inter.channel
        mgr = get_ticket_manager(ch.id)
        if mgr and inter.author.id != mgr and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Тикет ведёт другой менеджер.", ephemeral=True)
        await _start_close_flow(inter)


# ============================================================
# VIEW: COINS TICKET
# ============================================================
class CoinsTicketButtons(View):
    def __init__(self): super().__init__(timeout=None)

    @disnake.ui.button(label="ㅤПолитика выполнения заказаㅤ", style=ButtonStyle.gray,
                       custom_id="coins_ticket:policy",
                       emoji=PartialEmoji(name="Politic", id=1539657020695650384), row=0)
    async def policy(self, button, inter):
        try:
            await inter.response.defer(ephemeral=True)
            buf = await asyncio.to_thread(_render_policy, inter.author.id)
            fname = f"policy_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
            file = disnake.File(buf, filename=fname)
            emb = disnake.Embed(color=6776679); emb.set_image(url=f"attachment://{fname}")
            await inter.followup.send(embed=emb, file=file, ephemeral=True)
        except Exception as e:
            logger.exception(f"coins policy: {e}")
            try: await inter.followup.send(f"❌ Ошибка: `{str(e)[:200]}`", ephemeral=True)
            except Exception: pass

    @disnake.ui.button(label="ㅤㅤЗакрытьㅤㅤ", style=ButtonStyle.gray,
                       custom_id="coins_ticket:close",
                       emoji=PartialEmoji(name="OffTicket", id=1539657125716824185), row=0)
    async def close(self, button, inter):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        ch = inter.channel
        mgr = get_ticket_manager(ch.id)
        if mgr and inter.author.id != mgr and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Тикет ведёт другой менеджер.", ephemeral=True)
        await _start_close_flow(inter)


# ============================================================
# КАТАЛОГ ВЫБОРА
# ============================================================
class CatalogTypeSelect(disnake.ui.StringSelect):
    def __init__(self):
        super().__init__(
            placeholder="Выберите тип товаров...", min_values=1, max_values=1,
            custom_id="catalog_type_select",
            options=[
                SelectOption(label="Реальные деньги", description="Оплата в рублях, USDT и т.д.", emoji="<:realmomne:1539649281575620618>", value="real"),
                SelectOption(label="Diamond Coin-ы", description="Внутренняя валюта сервера", emoji="<:coins:1539649259245408340>", value="coins"),
            ],
        )

    async def callback(self, inter):
        v = inter.data.values[0]
        if v == "real":
            emb = disnake.Embed(color=6776679, title="Выбор для покупки в каталоге товаров",
                                description="Ниже, представлены цены, на интересующие вас категории, ознакомьтесь.")
            emb.set_image(url=_IMG_STRIPE)
            await inter.response.edit_message(content=None, embeds=[emb], view=CatalogView())
        elif v == "coins":
            from modules.shop import open_shop
            await open_shop(inter)


class CatalogTypeView(View):
    def __init__(self): super().__init__(timeout=None); self.add_item(CatalogTypeSelect())


CATALOG_OPTIONS = [
    {"label": "・Discord", "description": "Покупка Nitro и Boosts ・Статус и величие", "emoji": "<:Discord:1464831837300854936>", "json_path": os.path.join(CATALOG_DIR, "menu_discord.json")},
    {"label": "・Steam", "description": "Пополнение и очки ・Свобода к играм", "emoji": "<:Steam:1464833200416100402>", "json_path": os.path.join(CATALOG_DIR, "menu_steam.json")},
    {"label": "・Telegram", "description": "Звезды и Подарки ・Индивидуальность и защита", "emoji": "<:Telegram:1465720888677896314>", "json_path": os.path.join(CATALOG_DIR, "menu_telegram.json")},
    {"label": "・Украшение Discord", "description": "Украшения и Бейджики ・Изысканность и красота", "emoji": "<:Decoration:1465729329290936403>", "json_path": os.path.join(CATALOG_DIR, "menu_decoration.json")},
    {"label": "・Roblox", "description": "Донат и Помощь ・Красота и играбельность", "emoji": "<:Roblox:1465752155251150911>", "json_path": os.path.join(CATALOG_DIR, "menu_roblox.json")},
    {"label": "・Epic Games", "description": "Фортнайт и Аккаунт ・ Заработок и донат", "emoji": "<:EpicGames:1465765441887797248>", "json_path": os.path.join(CATALOG_DIR, "menu_epic.json")},
    {"label": "・Supercell", "description": "Brawl Stars и Clash Royale ・Динамика и богатство", "emoji": "<:SuperCell:1465768886484996260>", "json_path": os.path.join(CATALOG_DIR, "menu_supercell.json")},
    {"label": "・Spotify", "description": "Подписка на музыку ・Громкость и красочность", "emoji": "<:Spotify:1465770796411785330>", "json_path": os.path.join(CATALOG_DIR, "menu_spotify.json")},
    {"label": "・Дизайн", "description": "Отличный дизайн ・Выбор для лучших", "emoji": "<:Design:1465771436580012106>", "json_path": os.path.join(CATALOG_DIR, "menu_design.json")},
    {"label": "・Бот для Дискорда", "description": "Рабочий и легкий ・Плавность и скорость", "emoji": "<:Bot:1465771816080380109>", "json_path": os.path.join(CATALOG_DIR, "menu_bot.json")},
]


class CatalogSelect(disnake.ui.StringSelect):
    def __init__(self):
        super().__init__(
            placeholder="Выберите категорию...", min_values=1, max_values=1,
            custom_id="catalog_select",
            options=[SelectOption(label=i["label"], description=i["description"], emoji=i["emoji"], value=i["json_path"]) for i in CATALOG_OPTIONS],
        )

    async def callback(self, inter):
        jp = self.values[0]
        try:
            if not os.path.exists(jp):
                return await inter.response.edit_message(content="❌ Файл с embed не найден.", embeds=[], view=None)
            with open(jp, "r", encoding="utf-8") as f: data = json.load(f)
            embs = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.edit_message(content=None, embeds=embs, view=CatalogView())
            await log_discord(
                title="📂 Выбор категории (Каталог)",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Категория:** `{jp}`",
                color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
            )
        except Exception as e: logger.exception(f"CatalogSelect: {e}")


class CatalogView(View):
    def __init__(self): super().__init__(timeout=None); self.add_item(CatalogSelect())


# ============================================================
# ПАНЕЛЬ ТИКЕТОВ
# ============================================================
class TicketPanelView(View):
    def __init__(self): super().__init__(timeout=None)

    @disnake.ui.button(label="ㅤㅤКупитьㅤㅤ", style=ButtonStyle.gray,
                       custom_id="panel:buy",
                       emoji=PartialEmoji(name="shopg", id=1539646815530651718))
    async def buy(self, button, inter):
        emb = disnake.Embed(color=6776679, title="Выбор категории по оплате",
                            description="В какой валюте вы хотите купить товар? Если у вас есть вопрос, задайте его, выбрав соответствующий пункт ниже.")
        emb.set_image(url=_IMG_STRIPE)
        await inter.response.send_message(embed=emb, view=BuyTypeView(), ephemeral=True)

    @disnake.ui.button(label="ㅤПромокодыㅤ", style=ButtonStyle.gray,
                       custom_id="panel:promo",
                       emoji=PartialEmoji(name="prom1", id=1539646792139014234))
    async def promo(self, button, inter):
        await inter.response.send_message(
            "Промокоды публикуются в <#1462070136856117258> — следи за новостями и забирай свою скидку.",
            ephemeral=True,
        )
        await log_discord(
            title="🎟️ Просмотр промокодов",
            description=f"> **Пользователь:** {inter.author.mention}",
            color=0x00ff00, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )

    @disnake.ui.button(label="ㅤКаталогㅤ", style=ButtonStyle.gray,
                       custom_id="panel:catalog",
                       emoji=PartialEmoji(name="catal", id=1539646769053306980))
    async def catalog(self, button, inter):
        emb = disnake.Embed(title="Выбор категории товаров",
                            description="В чем представлен ваш товар? Выберите метод ниже.",
                            color=6776679)
        emb.set_image(url=_IMG_STRIPE)
        await inter.response.send_message(embed=emb, view=CatalogTypeView(), ephemeral=True)
# ============================================================
# АЛИАСЫ ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ (core/bot.py)
# ============================================================
TicketRatingView = RatingWaitingView   # старое имя, теперь → RatingWaitingView

# ============================================================
# ОБРАБОТЧИК
# ============================================================
async def handle_interaction(inter: disnake.MessageInteraction):
    pass
