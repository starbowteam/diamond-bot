# -*- coding: utf-8 -*-
"""Рендер карточки профиля через htmlcsstoimage.com — 1 в 1 как HTML в браузере."""

import io
import os
import base64
import random
import time
from typing import Optional, List, Dict

import aiohttp

from core.utils import ADD_DIR, logger

TEMPLATE_PATH = os.path.join(ADD_DIR, "profile_template.html")

# ============================================================
# API КЛЮЧИ HTMLCSSTOIMAGE
# ============================================================
HCTI_USER_ID = "01M2FJ7BRZVNDREJ2KGRATD127"
HCTI_API_KEY = "h1-afotTIvPTxWvnvKAw1iTfA10-b698a91b"

# ============================================================
# КЕШ (10 минут на юзера, чтобы не жрать лимит API)
# ============================================================
_RENDER_CACHE = {}
_CACHE_TTL = 600


# ---- Стили ролей ----
ROLE_STYLES = {
    "none":      {"name": "НЕТ РОЛИ",        "color": "#888",    "bg": "rgba(136,136,136,0.12)", "border": "rgba(136,136,136,0.4)",  "gradient": "linear-gradient(90deg, #888, #555)",       "glow": "rgba(136,136,136,0.3)",  "header": "Без роли"},
    "bronze":    {"name": "BRONZE BUYER",    "color": "#e78f67", "bg": "rgba(209,86,64,0.12)",   "border": "rgba(209,86,64,0.45)",   "gradient": "linear-gradient(90deg, #e78f67, #d15640)", "glow": "rgba(209,86,64,0.4)",    "header": "Bronze Buyer"},
    "silver":    {"name": "SILVER BUYER",    "color": "#e0e0e0", "bg": "rgba(176,176,176,0.12)", "border": "rgba(176,176,176,0.45)", "gradient": "linear-gradient(90deg, #ffffff, #979797)", "glow": "rgba(176,176,176,0.4)",  "header": "Silver Buyer"},
    "gold":      {"name": "GOLD BUYER",      "color": "#f7c991", "bg": "rgba(174,121,17,0.12)",  "border": "rgba(174,121,17,0.45)",  "gradient": "linear-gradient(90deg, #f7c991, #ae7911)", "glow": "rgba(174,121,17,0.4)",   "header": "Gold Buyer"},
    "diamond":   {"name": "DIAMOND BUYER",   "color": "#ddf0ef", "bg": "rgba(20,155,208,0.12)",  "border": "rgba(20,155,208,0.45)",  "gradient": "linear-gradient(90deg, #ddf0ef, #149bd0)", "glow": "rgba(20,155,208,0.4)",   "header": "Diamond Buyer"},
    "emerald":   {"name": "EMERALD BUYER",   "color": "#eff3d3", "bg": "rgba(61,158,8,0.12)",    "border": "rgba(61,158,8,0.45)",    "gradient": "linear-gradient(90deg, #eff3d3, #3d9e08)", "glow": "rgba(61,158,8,0.4)",     "header": "Emerald Buyer"},
    "amethyst":  {"name": "AMETHYST BUYER",  "color": "#9fc1ff", "bg": "rgba(216,142,223,0.12)", "border": "rgba(216,142,223,0.45)", "gradient": "linear-gradient(90deg, #9fc1ff, #d88edf)", "glow": "rgba(216,142,223,0.4)",  "header": "Amethyst Buyer"},
    "legendary": {"name": "LEGENDARY BUYER", "color": "#e68585", "bg": "rgba(197,28,178,0.12)",  "border": "rgba(197,28,178,0.45)",  "gradient": "linear-gradient(90deg, #e68585, #c51cb2)", "glow": "rgba(197,28,178,0.4)",   "header": "Legendary Buyer"},
    "pka":       {"name": "ПОКУПАТЕЛЬ ВЕКА", "color": "#d4bfff", "bg": "rgba(179,217,255,0.12)", "border": "rgba(179,217,255,0.45)", "gradient": "linear-gradient(90deg, #b3d9ff, #d4bfff)", "glow": "rgba(179,217,255,0.4)",  "header": "Покупатель Века"},
}

ROLE_ICON_POOL = [
    "fa-star", "fa-heart", "fa-crown", "fa-gem", "fa-bolt", "fa-fire",
    "fa-rocket", "fa-robot", "fa-paw", "fa-dragon", "fa-cat", "fa-dove",
    "fa-frog", "fa-user-astronaut", "fa-user-ninja", "fa-user-secret",
    "fa-hat-wizard", "fa-magic", "fa-ice-cream", "fa-hamburger",
    "fa-wine-glass", "fa-umbrella", "fa-anchor", "fa-plane", "fa-bomb",
    "fa-feather", "fa-skull", "fa-moon", "fa-sun", "fa-snowflake",
    "fa-leaf", "fa-shield", "fa-ghost", "fa-car", "fa-motorcycle",
    "fa-bicycle", "fa-chess", "fa-chess-king", "fa-chess-queen",
    "fa-fish", "fa-horse",
]


def _pick_role_icon(role_id: int) -> str:
    return random.Random(int(role_id) & 0xFFFFFFFF).choice(ROLE_ICON_POOL)


def _rgb_to_hex(rgb) -> str:
    if isinstance(rgb, str):
        return rgb
    r, g, b = rgb[:3]
    return f"#{r:02x}{g:02x}{b:02x}"


def _fmt_num(n: int) -> str:
    try:
        return f"{int(n):,}".replace(",", " ")
    except Exception:
        return str(n)


def _esc(s) -> str:
    s = str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ============================================================
# СБОРКА HTML ИЗ ШАБЛОНА
# ============================================================
def _build_html(
    user_name: str,
    user_id: int,
    avatar_url: str,
    role_key: str,
    reviews: int,
    next_role_name: str,
    progress_pct: int,
    progress_text: str,
    balance: int,
    total_earned: int,
    earned_month: int,
    spent_month: int,
    purchases_count: int,
    inventory: List[Dict],
    history: List[Dict],
    custom_roles: List[Dict],
) -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    st = ROLE_STYLES.get(role_key, ROLE_STYLES["none"])

    # ---- кастомные роли ----
    if custom_roles:
        parts = []
        for r in custom_roles:
            icon_cls = _pick_role_icon(r.get("id", 0))
            rc = _rgb_to_hex(r.get("color", (20, 155, 208)))
            name = _esc(r.get("name", "—"))
            pos = _esc(r.get("pos", ""))
            parts.append(
                '<div class="role-item" style="--role-item-color:{rc};">'
                '<div class="dot" style="background:{rc};box-shadow:0 0 13px {rc};"></div>'
                '<i class="fa-solid {icon}" style="color:{rc};font-size:20px;width:24px;text-align:center;flex-shrink:0;"></i>'
                '<div class="name">{name}</div>'
                '<div class="pos">{pos}</div>'
                '</div>'.format(rc=rc, icon=icon_cls, name=name, pos=pos)
            )
        roles_html = '<div class="roles-list">' + "".join(parts) + '</div>'
    else:
        roles_html = (
            '<div class="empty-roles">'
            '<div class="empty-icon"><i class="fa-solid fa-user-slash"></i></div>'
            '<div class="empty-text">Нету кастомных ролей</div>'
            '<div class="empty-sub">Приобретите в магазине</div>'
            '</div>'
        )

    # ---- инвентарь ----
    icon_map = {
        "roles": "fa-user-tie",
        "discounts": "fa-percent",
        "design": "fa-image",
        "design_avatar": "fa-image",
        "design_banner": "fa-image",
        "ads": "fa-bolt",
        "custom": "fa-gift",
    }
    inv_items = []
    for i in range(3):
        if i < len(inventory):
            it = inventory[i]
            accent = _rgb_to_hex(it.get("accent", (20, 155, 208)))
            ptype = it.get("_ptype", "")
            icon_cls = icon_map.get(ptype, "fa-gem")
            name = _esc(it.get("name", ""))
            qty = _esc(it.get("qty", ""))
            inv_items.append(
                '<div class="inv-item filled">'
                '<div class="inv-icon" style="color:{accent};"><i class="fa-solid {icon}"></i></div>'
                '<div class="inv-body">'
                '<div class="inv-name">{name}</div>'
                '<div class="inv-qty">{qty}</div>'
                '</div></div>'.format(accent=accent, icon=icon_cls, name=name, qty=qty)
            )
        else:
            inv_items.append('<div class="inv-item empty"></div>')
    inv_items_html = "".join(inv_items)

    inv_total = len(inventory)
    if inv_total > 3:
        inv_more_html = f'<i class="fa-solid fa-circle-plus"></i> +{inv_total - 3} ещё'
    elif inv_total > 0:
        inv_more_html = f'всего {inv_total}'
    else:
        inv_more_html = ""

    # ---- история ----
    hist_parts = []
    for h in history[:6]:
        amt = h.get("amount", 0)
        if amt >= 0:
            cls, s = "plus", f"+{amt} DC"
        else:
            cls, s = "minus", f"−{abs(amt)} DC"
        hist_parts.append(
            '<div class="history-item">'
            '<span class="date">{d}</span>'
            '<span class="amount {c}">{a}</span>'
            '</div>'.format(d=_esc(h.get("date", "")), c=cls, a=s)
        )
    history_html = "".join(hist_parts)

    # ---- подстановки ----
    repl = {
        "ROLE_GLOW_PLACEHOLDER": st["glow"],
        "ROLE_GRADIENT_PLACEHOLDER": st["gradient"],
        "ROLE_BORDER_PLACEHOLDER": st["border"],
        "ROLE_BG_PLACEHOLDER": st["bg"],
        "ROLE_COLOR_PLACEHOLDER": st["color"],
        "ROLE_HEADER_PLACEHOLDER": _esc(st["header"]),
        "ROLE_BADGE_PLACEHOLDER": _esc(st["name"]),
        "AVATAR_URL_PLACEHOLDER": avatar_url,
        "USERNAME_PLACEHOLDER": _esc(user_name[:22]),
        "USER_ID_PLACEHOLDER": str(user_id),
        "NEXT_ROLE_PLACEHOLDER": _esc(next_role_name),
        "PROGRESS_PCT_PLACEHOLDER": str(int(progress_pct)),
        "PROGRESS_TEXT_PLACEHOLDER": _esc(progress_text),
        "REVIEWS_PLACEHOLDER": str(reviews),
        "PURCHASES_COUNT_PLACEHOLDER": str(purchases_count),
        "TOTAL_EARNED_PLACEHOLDER": _fmt_num(total_earned),
        "BALANCE_PLACEHOLDER": _fmt_num(balance),
        "EARNED_MONTH_PLACEHOLDER": _fmt_num(earned_month),
        "SPENT_MONTH_PLACEHOLDER": _fmt_num(spent_month),
        "ROLES_COUNT_PLACEHOLDER": str(len(custom_roles)),
        "ROLES_HTML_PLACEHOLDER": roles_html,
        "INV_MORE_PLACEHOLDER": inv_more_html,
        "INV_ITEMS_PLACEHOLDER": inv_items_html,
        "HISTORY_PLACEHOLDER": history_html,
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    return html


# ============================================================
# ОТПРАВКА В HTMLCSSTOIMAGE API
# ============================================================
async def _render_via_api(html: str) -> bytes:
    auth = base64.b64encode(f"{HCTI_USER_ID}:{HCTI_API_KEY}".encode()).decode()
    payload = {
        "html": html,
        "viewport_width": 1800,
        "viewport_height": 1200,
        "device_scale_factor": 1,
    }
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=40)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post("https://hcti.io/v1/image", json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error(f"HCTI create error {resp.status}: {body}")
                raise RuntimeError(f"HCTI error {resp.status}: {body}")
            data = await resp.json()
            image_url = data.get("url")
            if not image_url:
                raise RuntimeError(f"HCTI: no url in response: {data}")

        async with session.get(image_url) as img_resp:
            if img_resp.status != 200:
                raise RuntimeError(f"HCTI download error {img_resp.status}")
            return await img_resp.read()


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================
async def generate_profile_card(
    user_name: str,
    user_id: int,
    avatar_bytes: Optional[bytes],
    role_key: str,
    reviews: int,
    next_role_name: str,
    progress_pct: int,
    progress_text: str,
    balance: int,
    total_earned: int,
    earned_month: int,
    spent_month: int,
    purchases_count: int,
    streak: int,
    inventory: List[Dict],
    history: List[Dict],
    custom_roles: List[Dict],
) -> io.BytesIO:
    now = time.time()
    cached = _RENDER_CACHE.get(user_id)
    if cached and now - cached[0] < _CACHE_TTL:
        logger.info(f"Profile card from cache for user {user_id}")
        return io.BytesIO(cached[1])

    if avatar_bytes:
        b64 = base64.b64encode(avatar_bytes).decode()
        avatar_url = f"data:image/png;base64,{b64}"
    else:
        avatar_url = "https://cdn.discordapp.com/embed/avatars/0.png"

    html = _build_html(
        user_name=user_name,
        user_id=user_id,
        avatar_url=avatar_url,
        role_key=role_key,
        reviews=reviews,
        next_role_name=next_role_name,
        progress_pct=progress_pct,
        progress_text=progress_text,
        balance=balance,
        total_earned=total_earned,
        earned_month=earned_month,
        spent_month=spent_month,
        purchases_count=purchases_count,
        inventory=inventory,
        history=history,
        custom_roles=custom_roles,
    )

    png_bytes = await _render_via_api(html)
    _RENDER_CACHE[user_id] = (now, png_bytes)

    buf = io.BytesIO(png_bytes)
    buf.seek(0)
    logger.info(f"Profile card generated (HCTI) for user {user_id}, size={len(png_bytes)}")
    return buf


def generate_profile_id() -> str:
    return f"P-{int(time.time())}-{random.randint(100, 999)}"
