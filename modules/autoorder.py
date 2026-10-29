# -*- coding: utf-8 -*-
"""
Автозаказ — новая система покупок.
Один файл: Pillow-панель + полный флоу (категория → товары → корзина → оплата → чек → тикет).
"""
import io
import os
import math
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict

import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption
from disnake.ui import Button, Select, View, Modal, TextInput
from PIL import Image, ImageDraw, ImageFont

from core.utils import (
    CONFIG, ADD_DIR, logger, db, cur,
    now_ts, log_discord, add_ticket_owner,
)

# ============================================================
# КОНСТАНТЫ
# ============================================================
AUTOORDER_CHANNEL_ID = 1565412940281024512
AUTOORDER_TICKET_CATEGORY = 1470779295650549885
LOG_CHANNEL_ID = 1530453871581855744
SESSION_TIMEOUT = 300  # 5 минут

COLOR_GREY = 0x676767
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"

P = "\u3164"

# ============================================================
# ПАЛИТРА (Pillow)
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
GREY      = (103, 103, 103)       # #676767
GREY_DARK = (74, 74, 82)
GREY_LIGHT = (150, 150, 158)
SILVER    = (212, 218, 230)

FONT_BOLD = os.path.join(ADD_DIR, "Fredoka_One.ttf")
FONT_FA   = os.path.join(ADD_DIR, "fa-solid-900.ttf")
_F, _FA = {}, {}

def _font(sz):
    if sz in _F: return _F[sz]
    try: f = ImageFont.truetype(FONT_BOLD, sz)
    except Exception: f = ImageFont.load_default()
    _F[sz] = f; return f

def _fa(sz):
    if sz in _FA: return _FA[sz]
    f = None
    if os.path.exists(FONT_FA):
        try: f = ImageFont.truetype(FONT_FA, sz)
        except Exception: pass
    _FA[sz] = f; return f

def _tw(d, t, f):
    b = d.textbbox((0, 0), t, font=f); return b[2] - b[0]

def _icon(d, cx, cy, code, sz, color):
    f = _fa(sz)
    if f is None: return
    try: d.text((cx, cy), chr(code), font=f, fill=color, anchor="mm")
    except Exception: pass

def _alpha(img, box, color, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    if radius > 0:
        ld.rounded_rectangle((0, 0, w-1, h-1), radius=radius, fill=color + (alpha,))
    else:
        ld.rectangle((0, 0, w-1, h-1), fill=color + (alpha,))
    img.paste(layer, (x1, y1), layer)

def _grad(img, box, c1, c2, alpha=30, radius=0):
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w <= 0 or h <= 0: return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i in range(w):
        t = i / max(w-1, 1)
        r = int(c1[0]*(1-t) + c2[0]*t)
        g = int(c1[1]*(1-t) + c2[1]*t)
        b = int(c1[2]*(1-t) + c2[2]*t)
        ld.line([(i, 0), (i, h)], fill=(r, g, b, alpha))
    if radius > 0:
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w-1, h-1), radius=radius, fill=255)
        a = layer.split()[3]
        a = Image.composite(a, Image.new("L", (w, h), 0), mask)
        layer.putalpha(a)
    img.paste(layer, (x1, y1), layer)

# FA icons
I_GEM       = 0xf3a5
I_BOLT      = 0xf0e7
I_CART      = 0xf07a
I_CHECK     = 0xf00c
I_TAG       = 0xf02b
I_CARD      = 0xf09d
I_SHIELD    = 0xf3ed
I_STAR      = 0xf005
I_INFO      = 0xf05a
I_BOX       = 0xf466
I_CLOCK     = 0xf017

# ============================================================
# PILLOW: ПАНЕЛЬ
# ============================================================
def render_autoorder_panel() -> io.BytesIO:
    W, H = 1800, 1000
    PAD_X, PAD_Y = 56, 44

    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)

    # Внешняя карточка
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=30,
                        fill=CARD_TOP + (255,),
                        outline=STACK_BRD + (255,), width=3)

    # ── Header ──
    hx, hy = PAD_X, PAD_Y
    logo_size = 54
    d.rounded_rectangle((hx, hy, hx + logo_size, hy + logo_size),
                        radius=14, fill=(58, 58, 64, 255))
    _icon(d, hx + logo_size // 2, hy + logo_size // 2 + 1, I_BOLT, 26, SILVER)

    bx = hx + logo_size + 18
    d.text((bx, hy + 4), "DIAMOND", font=_font(26), fill=TEXT)
    d.text((bx + 2, hy + 38), "AUTOORDER SYSTEM", font=_font(11), fill=MUTED)

    meta_r = W - PAD_X
    lbl = "АВТОЗАКАЗ"
    w1 = _tw(d, lbl, _font(11))
    d.text((meta_r - w1, hy + 12), lbl, font=_font(11), fill=GREY_LIGHT)

    ver = "v1.0 · BETA"
    w2 = _tw(d, ver, _font(14))
    d.text((meta_r - w2, hy + 32), ver, font=_font(14), fill=GREY)

    sep_y = hy + logo_size + 16
    d.line((PAD_X, sep_y, W - PAD_X, sep_y), fill=STACK_HDR + (255,), width=2)

    # ── Body ──
    body_y = sep_y + 30
    body_h = H - PAD_Y - body_y

    # LEFT — заголовок + описание + шаги
    left_x1 = PAD_X
    left_x2 = PAD_X + 920

    # Плашка «АВТОЗАКАЗ»
    title_y = body_y + 20
    _grad(img, (left_x1, title_y, left_x1 + 720, title_y + 130),
          GREY_LIGHT, GREY_DARK, alpha=200, radius=24)
    d.text((left_x1 + 40, title_y + 20), "АВТОЗАКАЗ",
           font=_font(88), fill=(20, 20, 24))
    d.text((left_x1 + 42, title_y + 128), "AUTO · SHOP · SYSTEM",
           font=_font(13), fill=(20, 20, 24))

    # Подзаголовок
    sub_y = title_y + 150
    d.text((left_x1, sub_y),
           "Новая система покупок Diamond Shop",
           font=_font(22), fill=SILVER)

    # Описание
    desc_y = sub_y + 44
    desc_lines = [
        "Забудь про ожидание менеджера. Собирай корзину, применяй",
        "скидки и оплачивай заказ в один клик. Менеджер подключится",
        "только к подтверждению оплаты.",
    ]
    for i, line in enumerate(desc_lines):
        d.text((left_x1, desc_y + i * 26), line,
               font=_font(16), fill=TEXT_SOFT)

    # ── Шаги (5 блоков) ──
    steps_y = desc_y + 110
    steps = [
        ("1", "Категория", "7 разделов"),
        ("2", "Корзина", "С количеством"),
        ("3", "Скидки", "Промо или 10%"),
        ("4", "Оплата", "Т-Банк · СБП · Озон"),
        ("5", "Чек", "Фото или PDF"),
    ]
    step_w, step_h, step_gap = 172, 108, 12

    for i, (num, title, sub) in enumerate(steps):
        sx1 = left_x1 + i * (step_w + step_gap)
        sx2 = sx1 + step_w
        sy1 = steps_y
        sy2 = sy1 + step_h

        _grad(img, (sx1, sy1, sx2, sy2), GREY, GREY_DARK, alpha=25, radius=14)
        d.rounded_rectangle((sx1, sy1, sx2, sy2), radius=14,
                            outline=GREY + (180,), width=2)

        d.text((sx1 + 20, sy1 + 12), num, font=_font(30), fill=GREY_LIGHT)
        d.text((sx1 + 20, sy1 + 54), title, font=_font(15), fill=TEXT)
        d.text((sx1 + 20, sy1 + 78), sub, font=_font(11), fill=MUTED)

    # RIGHT — фичи
    right_x1 = left_x2 + 40
    right_x2 = W - PAD_X
    feats_y = body_y + 20
    feat_h = 200
    feat_gap = 16

    features = [
        (I_BOLT,   "Быстро",   "Оформление за 2 минуты",        "Без ожидания менеджера в тикете"),
        (I_SHIELD, "Безопасно","Скрытые тикеты",                "Юзер видит канал только после оплаты"),
        (I_STAR,   "Удобно",   "Всё в одном окне",              "Категории, корзина, скидки, чек"),
    ]

    for i, (icon, title, sub, desc) in enumerate(features):
        fy1 = feats_y + i * (feat_h + feat_gap)
        fy2 = fy1 + feat_h

        _grad(img, (right_x1, fy1, right_x2, fy2),
              GREY, GREY_DARK, alpha=30, radius=20)
        d.rounded_rectangle((right_x1, fy1, right_x2, fy2), radius=20,
                            outline=GREY + (180,), width=2)

        icon_size = 72
        ib_x = right_x1 + 24
        ib_y = fy1 + (feat_h - icon_size) // 2
        _alpha(img, (ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
               GREY, alpha=60, radius=18)
        d.rounded_rectangle((ib_x, ib_y, ib_x + icon_size, ib_y + icon_size),
                            radius=18, outline=SILVER + (150,), width=2)
        _icon(d, ib_x + icon_size // 2, ib_y + icon_size // 2 + 1, icon, 32, SILVER)

        tx = ib_x + icon_size + 24
        ty = fy1 + 42
        d.text((tx, ty), title, font=_font(28), fill=SILVER)
        d.text((tx, ty + 40), sub, font=_font(14), fill=TEXT_SOFT)
        d.text((tx, ty + 66), desc, font=_font(12), fill=MUTED)

    # ── Footer ──
    foot_y = H - PAD_Y - 30
    d.line((PAD_X, foot_y, W - PAD_X, foot_y),
           fill=STACK_HDR + (255,), width=2)
    _icon(d, PAD_X + 12, foot_y + 20, I_INFO, 16, DIM)
    d.text((PAD_X + 38, foot_y + 10),
           "Нажми «Открыть Автозаказ» ниже — чтобы начать",
           font=_font(15), fill=DIM)

    right_txt = "READY TO USE · v1.0"
    rw = _tw(d, right_txt, _font(14))
    d.text((W - PAD_X - rw, foot_y + 10), right_txt,
           font=_font(14), fill=GREY_LIGHT)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf

# ============================================================
# КАТАЛОГ
# ============================================================
CATALOG = {
    "discord": {
        "title": "Discord",
        "emoji": "<:Discord:1464831837300854936>",
        "items": [
            {"id": "d_n1",  "name": "Discord Nitro 1 Month",  "desc": "Полная подписка",     "price": 460,  "fixed": True},
            {"id": "d_n12", "name": "Discord Nitro 12 Month", "desc": "Годовая подписка",    "price": 4410, "fixed": True},
            {"id": "d_nb",  "name": "Nitro Basic",            "desc": "Базовый на месяц",    "price": 300,  "fixed": True},
            {"id": "d_ng",  "name": "Nitro Gift",             "desc": "Подарочная подписка", "price": 790,  "fixed": True},
            {"id": "d_b",   "name": "Boosts",                 "desc": "Улучшение сервера",   "price": 35,   "fixed": False, "unit": "шт"},
        ],
    },
    "steam": {
        "title": "Steam",
        "emoji": "<:Steam:1464833200416100402>",
        "items": [
            {"id": "s_rub", "name": "Пополнение Steam", "desc": "Мин. 100 ₽",   "price": 1.1, "fixed": False, "unit": "₽"},
            {"id": "s_reg", "name": "Смена региона",     "desc": "Любой регион", "price": 250, "fixed": True},
        ],
    },
    "telegram": {
        "title": "Telegram",
        "emoji": "<:Telegram:1465720888677896314>",
        "items": [
            {"id": "t_star", "name": "Звёзды Telegram",       "desc": "Валюта",       "price": 1.58, "fixed": False, "unit": "шт"},
            {"id": "t_acc",  "name": "Аккаунт Telegram",      "desc": "Без спама",    "price": 250,  "fixed": True},
            {"id": "t_acc2", "name": "Аккаунт (спам-блок)",   "desc": "С огранич.",   "price": 190,  "fixed": True},
            {"id": "t_prox", "name": "Прокси Telegram",       "desc": "Рабочие",      "price": 100,  "fixed": True},
        ],
    },
    "roblox": {
        "title": "Roblox",
        "emoji": "<:Roblox:1465752155251150911>",
        "items": [
            {"id": "r_bux",  "name": "Robux",          "desc": "Валюта Roblox", "price": 0.82, "fixed": False, "unit": "шт"},
            {"id": "r_plus", "name": "Roblox Plus",    "desc": "Подписка",      "price": 90,   "fixed": True},
        ],
    },
    "spotify": {
        "title": "Spotify",
        "emoji": "<:Spotify:1465770796411785330>",
        "items": [
            {"id": "sp_1", "name": "Spotify Individual", "desc": "На месяц", "price": 270, "fixed": True},
        ],
    },
    "bodesign": {
        "title": "Боты и Дизайн",
        "emoji": "<:Design:1465771436580012106>",
        "items": [
            {"id": "bd_bot",    "name": "Разработка бота", "desc": "Индивидуально",  "price": 500, "fixed": True},
            {"id": "bd_design", "name": "Дизайн сервера",  "desc": "Под ключ",       "price": 150, "fixed": True},
        ],
    },
    "decor": {
        "title": "Украшения",
        "emoji": "<:Decoration:1465729329290936403>",
        "items": [
            {"id": "dec_1", "name": "Украшение профиля", "desc": "Эффекты и рамки", "price": 200, "fixed": True},
            {"id": "dec_2", "name": "Наборы Discord",    "desc": "Полный комплект", "price": 420, "fixed": True},
        ],
    },
}

PER_PAGE = 5

# ============================================================
# СТЕЙТ
# ============================================================
CARTS: Dict[int, dict] = {}

def _get_cart(uid: int) -> dict:
    if uid not in CARTS:
        CARTS[uid] = {
            "items": [],
            "discount": 0,
            "promo": "",
            "bank": "tbank",
            "category": None,
            "page": 1,
            "receipt": False,
            "created_at": time.time(),
        }
    return CARTS[uid]

def _reset_cart(uid: int):
    CARTS.pop(uid, None)

def _cart_total(cart: dict) -> int:
    return math.ceil(sum(i["price"] * i["qty"] for i in cart["items"]))

def _cart_final(cart: dict) -> int:
    total = _cart_total(cart)
    discount_amount = math.floor(total * cart["discount"] / 100)
    return math.ceil(total - discount_amount)

# ============================================================
# EMBED-ХЕЛПЕРЫ
# ============================================================
def _embed_categories():
    return disnake.Embed(
        title="Автозаказ — выбор категории",
        description=(
            "> Выберите категорию товаров из списка ниже.\n\n"
            f"> **Доступно категорий:** `{len(CATALOG)}`\n"
            "> **Таймер сессии:** `5 минут`"
        ),
        color=COLOR_GREY,
    ).set_image(url=IMG_STRIPE)

def _embed_products(cat_key: str, page: int):
    cat = CATALOG[cat_key]
    total = len(cat["items"])
    total_pages = (total + PER_PAGE - 1) // PER_PAGE
    return disnake.Embed(
        title=f"{cat['title']} · Автозаказ",
        description=(
            f"> Выберите товар — он добавится в корзину.\n\n"
            f"> **Страница:** `{page} / {total_pages}`\n"
            f"> **Товаров в корзине:** `{0}`"
        ),
        color=COLOR_GREY,
    ).set_image(url=IMG_STRIPE)

def _embed_cart(cart: dict) -> disnake.Embed:
    if not cart["items"]:
        return disnake.Embed(
            title="Корзина пуста",
            description="> Добавьте товары из каталога.",
            color=COLOR_GREY,
        )
    lines = []
    for i in cart["items"]:
        total = math.ceil(i["price"] * i["qty"])
        unit = "" if i["qty"] == 1 else f" × {i['qty']}"
        lines.append(f"> `{i['name']}`{unit} — **{total} ₽**")
    total = _cart_total(cart)
    e = disnake.Embed(
        title="Корзина",
        description="\n".join(lines) + f"\n\n> **Итого:** `{total} ₽`",
        color=COLOR_GREY,
    )
    return e

def _embed_checkout(cart: dict) -> disnake.Embed:
    total = _cart_total(cart)
    final = _cart_final(cart)
    discount_line = ""
    if cart["discount"] > 0:
        discount_line = f"\n> **Скидка:** `{cart['discount']}%` (`-{total - final} ₽`)"
    banks = {
        "tbank": "Т-Банк  ·  `+7 900 000-00-00`",
        "sbp":   "СБП      ·  `+7 900 000-00-00`",
        "ozon":  "ОзонБанк ·  `2204 3204 4881 5151`",
    }
    return disnake.Embed(
        title="Оплата заказа",
        description=(
            f"> **Сумма:** `{total} ₽`"
            f"{discount_line}\n\n"
            f"> **Итого к оплате:** **`{final} ₽`**\n\n"
            f"> **Реквизиты:**\n> {banks[cart['bank']]}"
        ),
        color=COLOR_GREY,
    )

# ============================================================
# VIEW: ГЛАВНАЯ КНОПКА
# ============================================================
class AutoOrderOpenView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="Открыть Автозаказ",
        style=ButtonStyle.secondary,
        custom_id="autoorder:open",
        emoji=PartialEmoji(name="avtio1", id=1565386600219676702),
    )
    async def open_btn(self, button, inter):
        _reset_cart(inter.author.id)
        cart = _get_cart(inter.author.id)
        cart["created_at"] = time.time()
        try:
            await inter.response.send_message(
                embed=_embed_categories(),
                view=CategoriesView(),
                ephemeral=True,
            )
        except disnake.InteractionResponded:
            pass

# ============================================================
# VIEW: КАТЕГОРИИ
# ============================================================
class CategorySelect(Select):
    def __init__(self):
        opts = []
        for key, cat in CATALOG.items():
            opts.append(SelectOption(
                label=cat["title"],
                value=key,
                emoji=PartialEmoji.from_str(cat["emoji"]),
            ))
        super().__init__(
            placeholder="Выберите категорию...",
            min_values=1, max_values=1,
            options=opts,
            custom_id="autoorder:cat",
        )

    async def callback(self, inter):
        cart = _get_cart(inter.author.id)
        cart["category"] = self.values[0]
        cart["page"] = 1
        try:
            await inter.response.edit_message(
                embed=_embed_products(cart["category"], 1),
                view=ProductsView(cart["category"], 1),
            )
        except Exception as e:
            logger.warning(f"cat_select: {e}")

class CategoriesView(View):
    def __init__(self):
        super().__init__(timeout=SESSION_TIMEOUT)
        self.add_item(CategorySelect())

# ============================================================
# VIEW: ТОВАРЫ
# ============================================================
class ProductSelect(Select):
    def __init__(self, cat_key: str, page: int):
        cat = CATALOG[cat_key]
        start = (page - 1) * PER_PAGE
        end = start + PER_PAGE
        items = cat["items"][start:end]
        opts = []
        for item in items:
            price_str = f"{item['price']} ₽" + (f" / {item.get('unit','шт')}" if not item["fixed"] else "")
            opts.append(SelectOption(
                label=item["name"][:80],
                description=f"{price_str} · {item['desc']}"[:100],
                value=item["id"],
            ))
        super().__init__(
            placeholder=f"Товары · стр. {page}",
            min_values=1, max_values=1,
            options=opts,
            custom_id=f"autoorder:prod:{cat_key}:{page}",
        )

    async def callback(self, inter):
        parts = self.custom_id.split(":")
        cat_key = parts[2]
        item_id = self.values[0]
        item = next((i for i in CATALOG[cat_key]["items"] if i["id"] == item_id), None)
        if not item:
            return await inter.response.send_message("❌ Товар не найден", ephemeral=True)

        if item["fixed"]:
            cart = _get_cart(inter.author.id)
            existing = next((i for i in cart["items"] if i["id"] == item_id), None)
            if existing:
                existing["qty"] += 1
            else:
                cart["items"].append({
                    "id": item_id, "name": item["name"],
                    "price": item["price"], "qty": 1,
                    "unit": item.get("unit", "шт"),
                })
            await inter.response.edit_message(
                embed=_embed_products(cat_key, cart["page"]),
                view=ProductsView(cat_key, cart["page"]),
            )
            try:
                await inter.followup.send(f"✅ `{item['name']}` добавлен в корзину", ephemeral=True)
            except Exception:
                pass
        else:
            await inter.response.send_modal(QtyModal(cat_key, item))

class QtyModal(Modal):
    def __init__(self, cat_key: str, item: dict):
        self.cat_key = cat_key
        self.item = item
        super().__init__(
            title=f"Количество: {item['name'][:40]}",
            components=[TextInput(
                label=f"Сколько {item.get('unit','шт')}?",
                placeholder="Введите число",
                custom_id="qty",
                min_length=1, max_length=6,
            )],
        )

    async def callback(self, inter):
        try:
            qty = int(self.text_values["qty"])
            if qty <= 0: raise ValueError
        except Exception:
            return await inter.response.send_message("❌ Введите положительное число", ephemeral=True)

        cart = _get_cart(inter.author.id)
        existing = next((i for i in cart["items"] if i["id"] == self.item["id"]), None)
        if existing:
            existing["qty"] += qty
        else:
            cart["items"].append({
                "id": self.item["id"], "name": self.item["name"],
                "price": self.item["price"], "qty": qty,
                "unit": self.item.get("unit", "шт"),
            })
        await inter.response.edit_message(
            embed=_embed_products(self.cat_key, cart["page"]),
            view=ProductsView(self.cat_key, cart["page"]),
        )
        try:
            await inter.followup.send(
                f"✅ `{self.item['name']}` × {qty} добавлен", ephemeral=True
            )
        except Exception:
            pass

class ProductsView(View):
    def __init__(self, cat_key: str, page: int):
        super().__init__(timeout=SESSION_TIMEOUT)
        self.cat_key = cat_key
        self.page = page

        self.add_item(ProductSelect(cat_key, page))

        total = len(CATALOG[cat_key]["items"])
        total_pages = (total + PER_PAGE - 1) // PER_PAGE

        if total_pages > 1:
            prev = Button(label="← Назад", style=ButtonStyle.secondary, custom_id=f"autoorder:prev:{page}", disabled=(page <= 1))
            prev.callback = self._prev
            self.add_item(prev)

            nxt = Button(label="Далее →", style=ButtonStyle.secondary, custom_id=f"autoorder:next:{page}", disabled=(page >= total_pages))
            nxt.callback = self._next
            self.add_item(nxt)

        back = Button(label="Категории", style=ButtonStyle.secondary, custom_id="autoorder:back_cat")
        back.callback = self._back
        self.add_item(back)

        to_cart = Button(label="Корзина", style=ButtonStyle.secondary, custom_id="autoorder:to_cart")
        to_cart.callback = self._to_cart
        self.add_item(to_cart)

    async def _prev(self, inter):
        cart = _get_cart(inter.author.id)
        cart["page"] = max(1, self.page - 1)
        await inter.response.edit_message(
            embed=_embed_products(self.cat_key, cart["page"]),
            view=ProductsView(self.cat_key, cart["page"]),
        )

    async def _next(self, inter):
        cart = _get_cart(inter.author.id)
        cart["page"] = self.page + 1
        await inter.response.edit_message(
            embed=_embed_products(self.cat_key, cart["page"]),
            view=ProductsView(self.cat_key, cart["page"]),
        )

    async def _back(self, inter):
        cart = _get_cart(inter.author.id)
        cart["category"] = None
        await inter.response.edit_message(
            embed=_embed_categories(),
            view=CategoriesView(),
        )

    async def _to_cart(self, inter):
        cart = _get_cart(inter.author.id)
        if not cart["items"]:
            return await inter.response.send_message("❌ Корзина пуста", ephemeral=True)
        await inter.response.edit_message(
            embed=_embed_cart(cart),
            view=CartView(),
        )

# ============================================================
# VIEW: КОРЗИНА
# ============================================================
class CartView(View):
    def __init__(self):
        super().__init__(timeout=SESSION_TIMEOUT)

        back = Button(label="Добавить ещё", style=ButtonStyle.secondary, custom_id="autoorder:add_more")
        back.callback = self._add_more
        self.add_item(back)

        clear = Button(label="Очистить", style=ButtonStyle.secondary, custom_id="autoorder:clear")
        clear.callback = self._clear
        self.add_item(clear)

        checkout = Button(label="Оформить заказ", style=ButtonStyle.secondary, custom_id="autoorder:checkout")
        checkout.callback = self._checkout
        self.add_item(checkout)

    async def _add_more(self, inter):
        cart = _get_cart(inter.author.id)
        cart["category"] = None
        await inter.response.edit_message(
            embed=_embed_categories(),
            view=CategoriesView(),
        )

    async def _clear(self, inter):
        _reset_cart(inter.author.id)
        _get_cart(inter.author.id)
        await inter.response.edit_message(
            embed=_embed_categories(),
            view=CategoriesView(),
        )

    async def _checkout(self, inter):
        cart = _get_cart(inter.author.id)
        if not cart["items"]:
            return await inter.response.send_message("❌ Корзина пуста", ephemeral=True)
        await inter.response.edit_message(
            embed=_embed_checkout(cart),
            view=CheckoutView(),
        )

# ============================================================
# VIEW: ОПЛАТА
# ============================================================
class CheckoutView(View):
    def __init__(self):
        super().__init__(timeout=SESSION_TIMEOUT)

        promo = Button(label="Промокод", style=ButtonStyle.secondary, custom_id="autoorder:promo")
        promo.callback = self._promo
        self.add_item(promo)

        disc = Button(label="Скидка 10% из инвентаря", style=ButtonStyle.secondary, custom_id="autoorder:disc10")
        disc.callback = self._disc10
        self.add_item(disc)

        bank = Button(label="Сменить банк", style=ButtonStyle.secondary, custom_id="autoorder:bank")
        bank.callback = self._bank
        self.add_item(bank)

        paid = Button(label="Я оплатил", style=ButtonStyle.secondary, custom_id="autoorder:paid")
        paid.callback = self._paid
        self.add_item(paid)

    async def _promo(self, inter):
        cart = _get_cart(inter.author.id)
        if cart["discount"] > 0:
            return await inter.response.send_message("❌ Скидка уже применена", ephemeral=True)
        await inter.response.send_modal(PromoModal())

    async def _disc10(self, inter):
        cart = _get_cart(inter.author.id)
        if cart["discount"] > 0:
            return await inter.response.send_message("❌ Скидка уже применена", ephemeral=True)
        cart["discount"] = 10
        await inter.response.edit_message(
            embed=_embed_checkout(cart),
            view=CheckoutView(),
        )

    async def _bank(self, inter):
        cart = _get_cart(inter.author.id)
        banks = ["tbank", "sbp", "ozon"]
        cart["bank"] = banks[(banks.index(cart["bank"]) + 1) % len(banks)]
        await inter.response.edit_message(
            embed=_embed_checkout(cart),
            view=CheckoutView(),
        )

    async def _paid(self, inter):
        cart = _get_cart(inter.author.id)
        await inter.response.edit_message(
            embed=disnake.Embed(
                title="Пришлите чек",
                description=(
                    "> Отправьте **фото или PDF** чек прямо в этот канал следующим сообщением.\n\n"
                    "> Бот автоматически примет его и создаст тикет."
                ),
                color=COLOR_GREY,
            ).set_image(url=IMG_STRIPE),
            view=None,
        )

class PromoModal(Modal):
    def __init__(self):
        super().__init__(
            title="Ввод промокода",
            components=[TextInput(
                label="Промокод",
                placeholder="Например: DIAMOND15",
                custom_id="promo",
                min_length=1, max_length=32,
            )],
        )

    async def callback(self, inter):
        code = self.text_values["promo"].strip().upper()
        cart = _get_cart(inter.author.id)
        if code == "DIAMOND15":
            cart["discount"] = 15
            cart["promo"] = code
            await inter.response.edit_message(
                embed=_embed_checkout(cart),
                view=CheckoutView(),
            )
        else:
            await inter.response.send_message("❌ Промокод не найден", ephemeral=True)

# ============================================================
# ФИНАЛИЗАЦИЯ (по чеку)
# ============================================================
async def finalize_order(bot, user, cart, receipt_url: str):
    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        return

    cat = guild.get_channel(AUTOORDER_TICKET_CATEGORY)
    if not cat:
        logger.warning(f"[autoorder] Категория {AUTOORDER_TICKET_CATEGORY} не найдена")
        return

    raw = user.display_name.lower().replace(" ", "-")
    raw = "".join(c for c in raw if c.isalnum() or c in "-_")[:80] or f"auto-{user.id}"

    overwrites = {
        guild.default_role: disnake.PermissionOverwrite(view_channel=False),
        user: disnake.PermissionOverwrite(view_channel=False),  # скрыт до одобрения
    }
    for rid in CONFIG.get("TICKET_MANAGE_ROLES", []):
        role = guild.get_role(rid)
        if role:
            overwrites[role] = disnake.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

    try:
        ticket = await cat.create_text_channel(name=raw, overwrites=overwrites)
    except Exception as e:
        logger.exception(f"[autoorder] create_ticket: {e}")
        return

    lines = []
    for i in cart["items"]:
        total = math.ceil(i["price"] * i["qty"])
        lines.append(f"> `{i['name']}` × {i['qty']} — **{total} ₽**")

    total = _cart_total(cart)
    final = _cart_final(cart)
    discount = f"\n> **Скидка:** `{cart['discount']}%`" if cart["discount"] else ""

    embed = disnake.Embed(
        title="🧾 Автозаказ — новый заказ",
        description=(
            f"> **Юзер:** {user.mention}\n"
            f"> **Банк:** `{cart['bank'].upper()}`"
            f"{discount}\n\n"
            + "\n".join(lines)
            + f"\n\n> **Сумма:** `{total} ₽`\n> **К оплате:** **`{final} ₽`**"
        ),
        color=COLOR_GREY,
    )
    embed.set_image(url=receipt_url)

    view = View(timeout=None)
    approve = Button(label="Одобрить оплату", style=ButtonStyle.success, custom_id="autoorder:approve")
    reject = Button(label="Отклонить", style=ButtonStyle.danger, custom_id="autoorder:reject")

    async def on_approve(inter2):
        await inter2.response.defer(ephemeral=True)
        try:
            await ticket.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True)
            add_ticket_owner(ticket.id, user.id, cat.id)
        except Exception as e:
            logger.warning(f"approve set_perms: {e}")

        await ticket.send(
            f"> ✅ {user.mention}, оплата подтверждена!\n"
            f"> Менеджер приступит к выполнению заказа."
        )
        await inter2.followup.send("✅ Оплата одобрена, юзеру открыт доступ", ephemeral=True)

        try:
            await user.send(
                f"✅ **Оплата подтверждена**\n"
                f"> Заказ на **{final} ₽** принят.\n"
                f"> Тикет: {ticket.mention}"
            )
        except Exception:
            pass

        approve.disabled = True
        reject.disabled = True
        try:
            await inter2.message.edit(view=view)
        except Exception:
            pass

    async def on_reject(inter2):
        await inter2.response.send_message("❌ Заказ отклонён", ephemeral=True)
        try:
            await ticket.delete()
        except Exception:
            pass

    approve.callback = on_approve
    reject.callback = on_reject
    view.add_item(approve)
    view.add_item(reject)

    await ticket.send(embed=embed, view=view)

    await log_discord(
        title="🧾 Автозаказ — создан заказ",
        description=(
            f"> **Юзер:** {user.mention}\n"
            f"> **Сумма:** `{final} ₽`\n"
            f"> **Тикет:** {ticket.mention}"
        ),
        color=COLOR_GREY,
        channel_id=LOG_CHANNEL_ID,
    )

    try:
        await user.send(
            f"✅ **Заказ оформлен**\n"
            f"> Сумма: **{final} ₽**\n"
            f"> Менеджер проверит чек и подтвердит оплату."
        )
    except Exception:
        pass

# ============================================================
# ON_MESSAGE (ловит чек)
# ============================================================
async def handle_receipt(bot, message):
    if message.author.bot: return
    if message.channel.id != AUTOORDER_CHANNEL_ID: return
    if not message.attachments: return

    cart = CARTS.get(message.author.id)
    if not cart: return
    if not cart["items"]: return
    if cart["receipt"]: return

    att = message.attachments[0]
    name_low = att.filename.lower()
    if not any(name_low.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".pdf")):
        return

    cart["receipt"] = True

    try:
        await finalize_order(bot, message.author, cart, att.url)
    except Exception as e:
        logger.exception(f"[autoorder] finalize: {e}")

    try:
        await message.delete()
    except Exception:
        pass

    _reset_cart(message.author.id)

# ============================================================
# SEND PANEL
# ============================================================
async def send_autoorder_panel(bot):
    await bot.wait_until_ready()
    await asyncio.sleep(5)

    ch = bot.get_channel(AUTOORDER_CHANNEL_ID)
    if not ch:
        try:
            ch = await bot.fetch_channel(AUTOORDER_CHANNEL_ID)
        except Exception as e:
            logger.warning(f"[autoorder] канал {AUTOORDER_CHANNEL_ID} не найден: {e}")
            return

    # Удалить старые сообщения бота
    try:
        async for m in ch.history(limit=20):
            if m.author == bot.user:
                try:
                    await m.delete()
                except Exception:
                    pass
    except Exception:
        pass

    # Рендер + отправка
    try:
        buf = await asyncio.to_thread(render_autoorder_panel)
        fname = "autoorder_panel.png"
        file = disnake.File(buf, filename=fname)
        embed = disnake.Embed(color=COLOR_GREY)
        embed.set_image(url=f"attachment://{fname}")
        await ch.send(embed=embed, file=file, view=AutoOrderOpenView())
        logger.info("[autoorder] ✅ Панель Автозаказа отправлена")
    except Exception as e:
        logger.exception(f"[autoorder] send_panel: {e}")

# ============================================================
# SETUP
# ============================================================
def setup_autoorder(bot):
    try:
        bot.add_view(AutoOrderOpenView())
        bot.loop.create_task(send_autoorder_panel(bot))
        logger.info("[autoorder] ✅ модуль подключён")
    except Exception as e:
        logger.exception(f"[autoorder] setup: {e}")
