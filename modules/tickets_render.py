# -*- coding: utf-8 -*-
"""
Pillow-рендер для системы тикетов:
  · render_policy       — политика магазина
  · render_rating_step1 — оценка менеджера + напоминание об отзыве
  · render_rating_step2 — оценка поставлена + ждём отзыв
1800×1000, стиль 1:1 с остальными рендерами.
"""
import io
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

from PIL import Image, ImageDraw, ImageFont

from core.utils import ADD_DIR, logger


# ============================================================
# ШРИФТЫ
# ============================================================
FONT_BOLD = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")

_FONT_CACHE: dict = {}
_FA_CACHE: dict = {}


def _font(size: int):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    try:
        f = ImageFont.truetype(FONT_BOLD, size)
    except Exception:
        f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


def _fa(size: int):
    if size in _FA_CACHE:
        return _FA_CACHE[size]
    f = None
    if os.path.exists(FONT_FA):
        try:
            f = ImageFont.truetype(FONT_FA, size)
        except Exception:
            pass
    _FA_CACHE[size] = f
    return f


# ============================================================
# ПАЛИТРА
# ============================================================
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
DARK      = (85, 85, 85)

SILVER     = (198, 208, 224)
SILVER_HI  = (224, 232, 245)
SILVER_DIM = (120, 132, 155)
SILVER_BG  = (34, 38, 48)

GREEN     = (46, 204, 113)
RED       = (255, 107, 107)
BLUE      = (106, 155, 209)
PURPLE    = (179, 157, 219)
GOLD      = (247, 201, 145)

GREEN_BG  = (18, 44, 28)
RED_BG    = (44, 20, 20)
BLUE_BG   = (20, 30, 44)
PURPLE_BG = (32, 26, 48)
GOLD_BG   = (40, 32, 21)

CARD_BRD  = (74, 74, 79)

EMBED_COLOR = 0x2b2d31


# ============================================================
# FA5-ИКОНКИ
# ============================================================
I_GEM        = 0xf3a5
I_STAR       = 0xf005
I_STAR_HALF  = 0xf5c0
I_COMMENT    = 0xf075
I_COMMENTS   = 0xf086
I_CLOCK      = 0xf017
I_CHECK      = 0xf00c
I_BAN        = 0xf05e
I_ROTATE     = 0xf2ea
I_INFO       = 0xf05a
I_EXCL       = 0xf06a
I_BOX        = 0xf466
I_USER       = 0xf007
I_HEAD       = 0xf590
I_BALANCE    = 0xf24e
I_SHIELD     = 0xf3ed
I_RECEIPT    = 0xf543
I_GIFT       = 0xf06b
I_HAND       = 0xf4c0
I_FIRE       = 0xf06d


# ============================================================
# УТИЛИТЫ
# ============================================================
def _tw(d, text, font):
    b = d.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def _ellipsis(d, text, font, max_w):
    if _tw(d, text, font) <= max_w:
        return text
    t = text
    while t and _tw(d, t + "…", font) > max_w:
        t = t[:-1]
    return t + "…"


def _wrap(d, text, font, max_w, max_lines=4):
    words = (text or "").split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if _tw(d, test, font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
                if len(lines) >= max_lines:
                    cur = ""
                    break
            cur = w
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines or [""]


def _fmt(n) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


def _draw_icon(d, cx, cy, code, size, color):
    f = _fa(size)
    if f is None:
        return
    try:
        d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception:
        pass


def _alpha_fill(base, box, color, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if radius > 0:
        ld.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=color + (alpha,))
    else:
        ld.rectangle((0, 0, w - 1, h - 1), fill=color + (alpha,))
    base.paste(layer, (x1, y1), layer)


def _gradient_box(base, box, c1, c2, alpha=30, radius=0, horizontal=True):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0:
        return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    steps = w if horizontal else h
    for i in range(steps):
        t = i / max(steps - 1, 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        if horizontal:
            ld.line([(i, 0), (i, h)], fill=(r, g, b, alpha))
        else:
            ld.line([(0, i), (w, i)], fill=(r, g, b, alpha))
    if radius > 0:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        alpha_ch = layer.split()[3]
        alpha_ch = Image.composite(alpha_ch, Image.new("L", (w, h), 0), mask)
        layer.putalpha(alpha_ch)
    base.paste(layer, (x1, y1), layer)


def _draw_stack_panel(base, d, box, radius=22):
    x1, y1, x2, y2 = box
    _alpha_fill(base, (x1 + 12, y1 + 12, x2 + 12, y2 + 12),
                (46, 46, 52), alpha=110, radius=radius)
    _alpha_fill(base, (x1 + 6, y1 + 6, x2 + 6, y2 + 6),
                (46, 46, 52), alpha=180, radius=radius)
    d.rounded_rectangle(box, radius=radius,
                        fill=STACK_BG + (255,),
                        outline=STACK_BRD + (255,), width=3)


# ============================================================
# КАРКАС
# ============================================================
CANVAS_W, CANVAS_H = 1800, 1000
M = 14
PAD_X = 40
PAD_Y = 40

REVIEW_CHANNEL_NAME = "💎・отзывы"


def _base_canvas(user_id: int, uid_label: str, status_label: str):
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (M, M, CANVAS_W - 1 - M, CANVAS_H - 1 - M),
        radius=28, fill=CARD_TOP + (255,),
        outline=CARD_BRD + (255,), width=3,
    )

    hx = PAD_X
    hy = PAD_Y

    logo_size = 64
    d.rounded_rectangle((hx, hy, hx + logo_size, hy + logo_size), radius=16,
                        fill=(58, 58, 64) + (255,),
                        outline=(94, 94, 100) + (255,), width=2)
    _draw_icon(d, hx + logo_size // 2, hy + logo_size // 2 + 1, I_GEM, 30, SILVER_HI)

    brand_x = hx + logo_size + 20
    d.text((brand_x, hy + 4), "DIAMOND", font=_font(34), fill=TEXT)
    d.text((brand_x + 4, hy + 46), "SHOP & ECOSYSTEM", font=_font(15), fill=MUTED)

    meta_r = CANVAS_W - M - PAD_X
    lbl = uid_label.upper()
    w1 = _tw(d, lbl, _font(15))
    w2 = _tw(d, status_label.upper(), _font(22))
    d.text((meta_r - w1, hy + 12), lbl, font=_font(15), fill=MUTED)
    d.text((meta_r - w2, hy + 36), status_label.upper(), font=_font(22), fill=TEXT)

    sep_y = hy + logo_size + 20
    d.line((PAD_X, sep_y, CANVAS_W - M - PAD_X, sep_y),
           fill=STACK_HDR + (255,), width=2)

    return img, d


def _draw_footer(d, left_text: str, page: str):
    y = CANVAS_H - M - PAD_Y + 6
    d.line((PAD_X, y - 10, CANVAS_W - M - PAD_X, y - 10),
           fill=STACK_HDR + (255,), width=2)
    _draw_icon(d, PAD_X + 12, y + 10, I_INFO, 16, DIM)
    d.text((PAD_X + 38, y), left_text, font=_font(15), fill=DIM)
    pw = _tw(d, page, _font(15))
    d.text((CANVAS_W - M - PAD_X - pw, y), page, font=_font(15), fill=DIM)


def _draw_right_head(d, x1, y1, x2, title: str, sub: str):
    d.rounded_rectangle((x1, y1 + 4, x1 + 6, y1 + 50), radius=3,
                        fill=SILVER + (255,))
    d.text((x1 + 22, y1 + 2), title.upper(), font=_font(30), fill=TEXT)
    sub_w = _tw(d, sub.upper(), _font(15))
    d.text((x2 - sub_w, y1 + 20), sub.upper(), font=_font(15), fill=MUTED)
    d.line((x1, y1 + 66, x2, y1 + 66), fill=STACK_HDR + (255,), width=2)


def _draw_left_block(img, d, x, y, w, h, color, icon_code, label, value):
    border = tuple(min(int(c + (255 - c) * 0.25), 255) for c in color)
    light = tuple(min(int(c + (255 - c) * 0.45), 255) for c in color)

    _gradient_box(img, (x, y, x + w, y + h), color, color, alpha=30, radius=15)
    d.rounded_rectangle((x, y, x + w, y + h),
                        radius=15, outline=border + (255,), width=3)
    d.rounded_rectangle((x + 4, y + 12, x + 8, y + h - 12),
                        radius=2, fill=color + (255,))

    icon_size = 54
    ib_x = x + 20
    ib_y = y + (h - icon_size) // 2

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                color, alpha=70, radius=14)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=14, outline=border + (200,), width=2)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               icon_code, 24, color)

    tx = ib_x + icon_size + 16
    d.text((tx, y + 16), label.upper(), font=_font(13), fill=light)
    val_font = _font(22)
    max_w = x + w - 18 - tx
    val_shown = _ellipsis(d, value, val_font, max_w)
    d.text((tx, y + 44), val_shown, font=val_font, fill=color)


def _draw_left_panel(img, d, box, top_icon, top_label, top_value, blocks: List[Dict]):
    """Левая панель: верхний блок + N инфо-блоков снизу."""
    _draw_stack_panel(img, d, box, radius=22)
    x1, y1, x2, y2 = box
    pad = 28

    # Верхний блок
    bal_icon_size = 84
    ib_x = x1 + pad
    ib_y = y1 + pad

    _gradient_box(img, (ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                  SILVER, SILVER_DIM, alpha=42, radius=22)
    d.rounded_rectangle((ib_x, ib_y, ib_x + bal_icon_size, ib_y + bal_icon_size),
                        radius=22, outline=SILVER + (200,), width=3)
    _draw_icon(d, ib_x + bal_icon_size // 2, ib_y + bal_icon_size // 2 + 1,
               top_icon, 34, SILVER_HI)

    lbl_x = ib_x + bal_icon_size + 20
    d.text((lbl_x, ib_y + 8), top_label.upper(), font=_font(14), fill=MUTED)

    top_str = str(top_value)
    val_font = _font(34)
    max_w = x2 - pad - lbl_x - 16
    while _tw(d, top_str, val_font) > max_w and val_font.size > 20:
        val_font = _font(val_font.size - 2)
    d.text((lbl_x, ib_y + 32), top_str, font=val_font, fill=TEXT)

    sep_y = ib_y + bal_icon_size + 26
    d.line((x1 + pad, sep_y, x2 - pad, sep_y),
           fill=STACK_HDR + (255,), width=2)

    if blocks:
        bb_h = 92
        bb_gap = 14
        top_y = sep_y + 26

        for i, blk in enumerate(blocks):
            by1 = top_y + i * (bb_h + bb_gap)
            _draw_left_block(
                img, d, x1 + pad, by1, (x2 - pad) - (x1 + pad), bb_h,
                blk["color"], blk["icon"], blk["label"], blk["value"],
            )


def _now_msk_str() -> str:
    now_msk = datetime.now(timezone(timedelta(hours=3)))
    return now_msk.strftime("%d.%m.%Y %H:%M")


# ============================================================
# ЭКРАН 1: ПОЛИТИКА
# ============================================================
def _draw_policy_block(img, d, x, y, w, h, color, icon_code, title, text):
    border = tuple(min(int(c + (255 - c) * 0.25), 255) for c in color)

    d.rounded_rectangle((x, y, x + w, y + h), radius=14,
                        fill=INNER_BG + (255,),
                        outline=INNER_BRD + (255,), width=2)
    d.rounded_rectangle((x, y + 10, x + 5, y + h - 10), radius=2,
                        fill=color + (255,))

    icon_size = 52
    ib_x = x + 22
    ib_y = y + 18

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                color, alpha=65, radius=13)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=13, outline=color + (210,), width=2)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               icon_code, 24, color)

    tx = ib_x + icon_size + 18
    d.text((tx, ib_y + 4), title.upper(), font=_font(16), fill=color)

    text_font = _font(14)
    max_w = x + w - 24 - tx
    lines = _wrap(d, text, text_font, max_w, max_lines=3)
    text_y = ib_y + 30
    for i, line in enumerate(lines):
        d.text((tx, text_y + i * 22), line, font=text_font, fill=TEXT_SOFT)


def render_policy(user_id: int) -> io.BytesIO:
    img, d = _base_canvas(user_id, "политика магазина", "действует с 26.07.26")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        top_icon=I_RECEIPT, top_label="Документ", top_value="Политика",
        blocks=[
            {"color": BLUE,  "icon": I_CLOCK,   "label": "Срок обработки", "value": "до 2 дней"},
            {"color": RED,   "icon": I_ROTATE,  "label": "Возврат",        "value": "75% от суммы"},
            {"color": GREEN, "icon": I_SHIELD,  "label": "Гарантия",       "value": "100% выдача"},
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Политика покупки", "читай внимательно")

    items_y = body_y + 118
    items_bottom = body_y + body_h - 22 - 60
    n = 4
    gap_item = 12
    item_h = (items_bottom - items_y - gap_item * (n - 1)) // n

    rules = [
        {
            "color": BLUE,
            "icon": I_CLOCK,
            "title": "Сроки обработки заказа",
            "text": "Максимальный срок — 2 рабочих дня с момента подтверждения оплаты. "
                    "В большинстве случаев товар выдаётся в течение 3 часов. "
                    "Часовой пояс продавца — МСК+5 (UTC+8).",
        },
        {
            "color": RED,
            "icon": I_ROTATE,
            "title": "Возврат средств",
            "text": "Если вы отказываетесь после оплаты — возврат 75% от суммы. "
                    "25% удерживаются для покрытия комиссий платёжных систем и обработки.",
        },
        {
            "color": GOLD,
            "icon": I_BAN,
            "title": "Стоп-лист",
            "text": "Массовые пинги персонала, продавца или менеджеров, "
                    "а также агрессивное поведение переводят тикет в «стоп-лист». "
                    "Такие заказы обрабатываются в последнюю очередь.",
        },
        {
            "color": GREEN,
            "icon": I_CHECK,
            "title": "Подтверждение оплаты",
            "text": "Для подтверждения необходимо прикрепить чек оплаты и указать, "
                    "куда перевод был сделан. После проверки менеджер подтвердит оплату — "
                    "и продавец начнёт работу.",
        },
    ]

    for i, rule in enumerate(rules):
        cy = items_y + i * (item_h + gap_item)
        _draw_policy_block(img, d, rx1, cy, rx2 - rx1, item_h,
                           rule["color"], rule["icon"], rule["title"], rule["text"])

    # Нижняя плашка-предупреждение
    hint_h = 48
    hint_y = items_bottom + 12
    _alpha_fill(img, (rx1, hint_y, rx2, hint_y + hint_h), GOLD, alpha=22, radius=11)
    d.rounded_rectangle((rx1, hint_y, rx2, hint_y + hint_h),
                        radius=11, outline=GOLD + (150,), width=2)
    _draw_icon(d, rx1 + 24, hint_y + hint_h // 2, I_INFO, 18, GOLD)
    d.text((rx1 + 48, hint_y + hint_h // 2 - 9),
           "Незнание политики не освобождает от ответственности. Действует с 26.07.26",
           font=_font(14), fill=TEXT_SOFT)

    _draw_footer(d, f"Политика магазина · данные на {_now_msk_str()} МСК", "политика · v1.0")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 2: ОЦЕНКА МЕНЕДЖЕРА (STEP 1)
# ============================================================
def _draw_star(img, d, cx, cy, size, color, filled=True):
    """Рисует 5-конечную звезду через FA-иконку."""
    _draw_icon(d, cx, cy, I_STAR, size, color if filled else DARK)


def render_rating_step1(
    user_id: int,
    manager_name: str,
    product_name: str,
    order_id: int,
) -> io.BytesIO:
    img, d = _base_canvas(user_id, "оценка · менеджер", f"заказ #{order_id}")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        top_icon=I_HEAD, top_label="Менеджер", top_value=f"@{manager_name}",
        blocks=[
            {"color": SILVER, "icon": I_BOX,    "label": "Товар",          "value": product_name},
            {"color": GREEN,  "icon": I_CHECK,  "label": "Статус заказа",  "value": "Выполнен"},
            {"color": BLUE,   "icon": I_STAR,   "label": "Оценка",         "value": "Не поставлена"},
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Оцени работу", "шаг 1 из 2")

    # ── HERO: 5 звёзд + текст ──
    hero_y1 = body_y + 118
    hero_h = 340
    hero_y2 = hero_y1 + hero_h

    _gradient_box(img, (rx1, hero_y1, rx2, hero_y2),
                  GOLD, GOLD, alpha=18, radius=20)
    d.rounded_rectangle((rx1, hero_y1, rx2, hero_y2),
                        radius=20, outline=GOLD + (180,), width=3)

    cx = (rx1 + rx2) // 2

    # TAG
    tag_text = "ШАГ 1 · ОЦЕНКА МЕНЕДЖЕРА"
    tag_font = _font(14)
    tag_w = _tw(d, tag_text, tag_font) + 80
    tag_h = 36
    tag_x = cx - tag_w // 2
    tag_y = hero_y1 + 24

    _alpha_fill(img, (tag_x, tag_y, tag_x + tag_w, tag_y + tag_h),
                GOLD, alpha=55, radius=tag_h // 2)
    d.rounded_rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + tag_h),
                        radius=tag_h // 2, outline=GOLD + (200,), width=2)
    _draw_icon(d, tag_x + 24, tag_y + tag_h // 2, I_STAR, 15, GOLD)
    d.text((tag_x + 44, tag_y + tag_h // 2), tag_text,
           font=tag_font, fill=GOLD, anchor="lm")

    # Заголовок
    title_text = "Как прошёл заказ?"
    title_font = _font(28)
    tw = _tw(d, title_text, title_font)
    d.text((cx - tw // 2, tag_y + tag_h + 14), title_text,
           font=title_font, fill=TEXT)

    sub_text = "Твоя оценка пойдёт в рейтинг менеджера"
    sub_font = _font(15)
    sw = _tw(d, sub_text, sub_font)
    d.text((cx - sw // 2, tag_y + tag_h + 52), sub_text,
           font=sub_font, fill=MUTED)

    # 5 звёзд
    star_size = 100
    star_gap = 30
    star_y = tag_y + tag_h + 100
    total_stars_w = star_size * 5 + star_gap * 4
    star_x_start = cx - total_stars_w // 2

    for i in range(5):
        sx1 = star_x_start + i * (star_size + star_gap)
        sy1 = star_y

        _gradient_box(img, (sx1, sy1, sx1 + star_size, sy1 + star_size),
                      GOLD, GOLD, alpha=45, radius=22)
        d.rounded_rectangle((sx1, sy1, sx1 + star_size, sy1 + star_size),
                            radius=22, outline=GOLD + (220,), width=3)
        _draw_icon(d, sx1 + star_size // 2, sy1 + star_size // 2 - 6,
                   I_STAR, 46, GOLD)

        num_text = str(i + 1)
        nw = _tw(d, num_text, _font(14))
        d.text((sx1 + star_size // 2 - nw // 2, sy1 + star_size - 24),
               num_text, font=_font(14), fill=GOLD)

    hint_text = "Нажми на кнопку ниже — она откроет форму оценки"
    hint_font = _font(13)
    hw = _tw(d, hint_text, hint_font)
    d.text((cx - hw // 2, hero_y2 - 32), hint_text,
           font=hint_font, fill=DIM)

    # ── ПЛАШКА: ОТЗЫВ ──
    rev_y1 = hero_y2 + 14
    rev_y2 = body_y + body_h - 22
    rev_h = rev_y2 - rev_y1

    _gradient_box(img, (rx1, rev_y1, rx2, rev_y2),
                  PURPLE, PURPLE, alpha=22, radius=18)
    d.rounded_rectangle((rx1, rev_y1, rx2, rev_y2),
                        radius=18, outline=PURPLE + (200,), width=3)

    # Иконка
    icon_size = 80
    ib_x = rx1 + 26
    ib_y = rev_y1 + (rev_h - icon_size) // 2

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                PURPLE, alpha=55, radius=20)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=20, outline=PURPLE + (220,), width=3)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               I_COMMENTS, 38, PURPLE)

    # Текст
    tx = ib_x + icon_size + 22
    d.text((tx, rev_y1 + 18), "ШАГ 2 · ОСТАВЬ ОТЗЫВ В КАНАЛЕ",
           font=_font(14), fill=PURPLE)

    # Канал
    gem_size = 26
    gem_x = tx
    gem_y = rev_y1 + 44
    _alpha_fill(img, (gem_x, gem_y, gem_x + gem_size, gem_y + gem_size),
                PURPLE, alpha=70, radius=8)
    _draw_icon(d, gem_x + gem_size // 2, gem_y + gem_size // 2 + 1,
               I_GEM, 14, PURPLE)

    d.text((gem_x + gem_size + 10, gem_y + 2),
           REVIEW_CHANNEL_NAME, font=_font(22), fill=TEXT)

    # Пояснение
    hint2 = "За одобренный отзыв — +15 DC · без отзыва тикет не закрыть"
    d.text((tx, rev_y1 + 86), hint2, font=_font(14), fill=TEXT_SOFT)

    _draw_footer(d, f"Оценка менеджера · данные на {_now_msk_str()} МСК", "тикет · оценка")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


# ============================================================
# ЭКРАН 3: ОЦЕНКА ПОСТАВЛЕНА (STEP 2)
# ============================================================
def _draw_star_filled_row(img, d, x, y, count: int, total: int = 5):
    """Ряд из 5 звёзд — filled/unfilled."""
    star_size = 42
    gap = 10
    for i in range(total):
        sx = x + i * (star_size + gap)
        if i < count:
            _alpha_fill(img, (sx, y, sx + star_size, sy + star_size) if False else (sx, y, sx + star_size, y + star_size),
                        GOLD, alpha=55, radius=12)
            d.rounded_rectangle((sx, y, sx + star_size, y + star_size),
                                radius=12, outline=GOLD + (220,), width=2)
            _draw_icon(d, sx + star_size // 2, y + star_size // 2 + 1,
                       I_STAR, 22, GOLD)
        else:
            d.rounded_rectangle((sx, y, sx + star_size, y + star_size),
                                radius=12, fill=INNER_BG + (255,),
                                outline=INNER_BRD + (255,), width=2)
            _draw_icon(d, sx + star_size // 2, y + star_size // 2 + 1,
                       I_STAR, 22, DARK)


def render_rating_step2(
    user_id: int,
    manager_name: str,
    rating: int,
    has_review: bool = False,
) -> io.BytesIO:
    img, d = _base_canvas(user_id, "оценка · менеджер", "оценка поставлена")

    body_y = 140
    body_h = CANVAS_H - M - PAD_Y - body_y - 26

    left_w = 460
    gap = 30
    left_x1 = PAD_X
    left_x2 = left_x1 + left_w
    right_x1 = left_x2 + gap
    right_x2 = CANVAS_W - M - PAD_X

    _draw_left_panel(
        img, d, (left_x1, body_y, left_x2, body_y + body_h),
        top_icon=I_HEAD, top_label="Менеджер", top_value=f"@{manager_name}",
        blocks=[
            {"color": GREEN,  "icon": I_STAR,    "label": "Оценка",         "value": f"{rating} / 5 ⭐"},
            {"color": PURPLE, "icon": I_COMMENTS,"label": "Следующий шаг",  "value": "Отзыв в канале"},
            {"color": GOLD,   "icon": I_GIFT,    "label": "Бонус за отзыв", "value": "+15 DC"},
        ],
    )

    _draw_stack_panel(img, d, (right_x1, body_y, right_x2, body_y + body_h), radius=22)
    rx1 = right_x1 + 30
    rx2 = right_x2 - 30

    _draw_right_head(d, rx1, body_y + 22, rx2,
                     "Остался последний шаг", "без отзыва не закрыть")

    # ── HERO: оценка сохранена ──
    hero_y1 = body_y + 118
    hero_h = 220
    hero_y2 = hero_y1 + hero_h

    _gradient_box(img, (rx1, hero_y1, rx2, hero_y2),
                  GREEN, GREEN, alpha=18, radius=20)
    d.rounded_rectangle((rx1, hero_y1, rx2, hero_y2),
                        radius=20, outline=GREEN + (200,), width=3)

    icon_size = 100
    ib_x = rx1 + 28
    ib_y = hero_y1 + (hero_h - icon_size) // 2

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                GREEN, alpha=55, radius=22)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=22, outline=GREEN + (230,), width=3)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               I_CHECK, 48, GREEN)

    tx = ib_x + icon_size + 26
    d.text((tx, hero_y1 + 30), "ОЦЕНКА СОХРАНЕНА",
           font=_font(14), fill=GREEN)

    d.text((tx, hero_y1 + 56), "Спасибо! Менеджер оценён",
           font=_font(30), fill=TEXT)

    # Ряд звёзд
    stars_y = hero_y1 + 106
    _draw_star_filled_row(img, d, tx, stars_y, rating, 5)

    # Текст «на N звёзд»
    d.text((tx + 5 * 52, stars_y + 8),
           f"{rating} / 5", font=_font(22), fill=GREEN)

    # ── ПЛАШКА: ОТЗЫВ ──
    rev_y1 = hero_y2 + 14
    rev_y2 = body_y + body_h - 22
    rev_h = rev_y2 - rev_y1

    if has_review:
        # Отзыв есть — зелёная плашка
        main_color = GREEN
        status_text = "ОТЗЫВ ОСТАВЛЕН ✓"
        head_text = "Всё готово — можно завершать заказ"
        body_text = "Ты уже оставил отзыв. Нажми на кнопку ниже, чтобы закрыть тикет."
        icon_code = I_CHECK
    else:
        # Отзыва нет — фиолетовая плашка
        main_color = PURPLE
        status_text = "ОСТАЛСЯ ОТЗЫВ В КАНАЛЕ"
        head_text = "Канал 💎・отзывы — следующий шаг"
        body_text = ("Напиши пару слов о заказе. За одобренный отзыв начислим +15 DC. "
                     "Без отзыва тикет не закроется.")
        icon_code = I_COMMENTS

    _gradient_box(img, (rx1, rev_y1, rx2, rev_y2),
                  main_color, main_color, alpha=22, radius=18)
    d.rounded_rectangle((rx1, rev_y1, rx2, rev_y2),
                        radius=18, outline=main_color + (200,), width=3)

    icon_size = 80
    ib_x = rx1 + 26
    ib_y = rev_y1 + (rev_h - icon_size) // 2

    _alpha_fill(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                main_color, alpha=55, radius=20)
    d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                        radius=20, outline=main_color + (230,), width=3)
    _draw_icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1,
               icon_code, 38, main_color)

    tx = ib_x + icon_size + 22
    d.text((tx, rev_y1 + 16), status_text,
           font=_font(14), fill=main_color)

    # Канал с FA-алмазом
    gem_size = 26
    gem_x = tx
    gem_y = rev_y1 + 42
    _alpha_fill(img, (gem_x, gem_y, gem_x + gem_size, gem_y + gem_size),
                main_color, alpha=70, radius=8)
    _draw_icon(d, gem_x + gem_size // 2, gem_y + gem_size // 2 + 1,
               I_GEM, 14, main_color)

    d.text((gem_x + gem_size + 10, gem_y + 2),
           REVIEW_CHANNEL_NAME, font=_font(22), fill=TEXT)

    d.text((tx, rev_y1 + 84), head_text, font=_font(15), fill=TEXT_SOFT)

    text_font = _font(13)
    lines = _wrap(d, body_text, text_font, rx2 - tx - 20, max_lines=2)
    for i, line in enumerate(lines):
        d.text((tx, rev_y1 + 110 + i * 18), line, font=text_font, fill=MUTED)

    _draw_footer(d, f"Оценка менеджера · данные на {_now_msk_str()} МСК", "тикет · оценка")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
