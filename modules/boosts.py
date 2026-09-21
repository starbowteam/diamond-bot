# -*- coding: utf-8 -*-
"""Бусты DC + казино-предметы. Один активный предмет одного типа."""
import time

from core.utils import (
    get_item, get_active_items, activate_item, consume_use, clear_item,
    get_dc_cache, save_dc_cache, sync_dc_to_json, logger
)


def format_remaining(seconds: int) -> str:
    if seconds <= 0:
        return "истёк"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}ч {m}м"
    if m > 0:
        return f"{m}м"
    return f"{s}с"


def get_multiplier(user_id: int, kind: str) -> float:
    """
    Множитель начисления. kind: 'messages' | 'voice' | 'review'
    Берёт максимум из boost_all_x2 и специфичного.
    """
    m_all = 1.0
    m_spec = 1.0

    item_all = get_item(user_id, "boost_all_x2")
    if item_all:
        m_all = float(item_all["value"] or 1.0)

    key_map = {
        "messages": "boost_messages_x2",
        "voice":    "boost_voice_x2",
        "review":   "boost_review_x2",
    }
    key = key_map.get(kind)
    if key:
        item_spec = get_item(user_id, key)
        if item_spec:
            m_spec = float(item_spec["value"] or 1.0)

    return max(m_all, m_spec)


def apply_boost(user_id: int, kind: str, base: int) -> int:
    mult = get_multiplier(user_id, kind)
    return int(base * mult)


def get_review_cooldown(user_id: int) -> int:
    """120 сек по умолчанию, 60 сек с boost_cooldown_half."""
    item = get_item(user_id, "boost_cooldown_half")
    if item and item["value"]:
        try:
            return int(item["value"])
        except Exception:
            pass
    return 120


# ============================================================
# ПРОВЕРКА + АКТИВАЦИЯ
# ============================================================
def can_activate(user_id: int, item_key: str) -> tuple[bool, str]:
    """
    Проверяет, можно ли купить/активировать предмет.
    Возвращает (True, "") либо (False, "причина с временем остатка").
    """
    existing = get_item(user_id, item_key)
    if existing:
        if existing["expires_at"] > 0:
            left = existing["expires_at"] - int(time.time())
            if left > 0:
                return False, f"⏱ У вас уже активен **{existing['item_key']}**. Осталось: **{format_remaining(left)}**"
        elif existing["uses_left"] > 0:
            return False, f"⏱ У вас уже есть **{existing['item_key']}** ({existing['uses_left']} исп.)"
    return True, ""


async def do_activate(user_id: int, item_key: str, item: dict) -> str:
    """
    Активирует предмет. Возвращает текст для показа юзеру.
    """
    # ─── Мгновенный сброс лимита ───
    if item_key == "boost_daily_reset":
        data = get_dc_cache(user_id)
        data["messages_today"] = 0
        data["voice_time_today"] = 0
        data["last_voice_dc"] = 0
        save_dc_cache(user_id, data)
        sync_dc_to_json()
        return "✅ Лимит сообщений и войса **обнулён на сегодня**!"

    # ─── Обычные предметы ───
    duration = int(item.get("duration_hours", 0) or 0)
    uses = int(item.get("uses", -1))
    activate_item(
        user_id=user_id,
        item_key=item_key,
        item_type=item.get("_category", "boosts"),
        value=float(item.get("value", 0) or 0),
        duration_hours=duration,
        uses=uses,
    )

    if duration > 0:
        return f"✅ Активирован на **{duration}ч** — применяется сразу."
    if uses > 0:
        return f"✅ Активирован (**{uses}** исп.) — применяется сразу."
    return "✅ Активирован — применяется сразу."


# ============================================================
# КАЗИНО
# ============================================================
def get_casino_multiplier(user_id: int) -> float:
    mult = 1.0
    lh = get_item(user_id, "casino_lucky_hour")
    if lh:
        mult *= float(lh["value"] or 1.0)
    return mult


def has_insurance(user_id: int) -> bool:
    return get_item(user_id, "casino_insurance") is not None


def has_next_mult(user_id: int) -> bool:
    return get_item(user_id, "casino_boost_x2") is not None


def apply_casino_win(user_id: int, base_payout: int) -> tuple[int, list]:
    used = []
    payout = base_payout

    lh = get_item(user_id, "casino_lucky_hour")
    if lh and lh["value"]:
        payout = int(payout * float(lh["value"]))
        used.append("удачный час")

    nm = get_item(user_id, "casino_boost_x2")
    if nm and nm["value"]:
        payout = int(payout * float(nm["value"]))
        consume_use(user_id, "casino_boost_x2")
        used.append("x2 к выигрышу")

    return payout, used


def try_insurance(user_id: int, bet: int) -> int:
    ins = get_item(user_id, "casino_insurance")
    if not ins:
        return 0
    refund = int(bet * float(ins["value"] or 0.5))
    consume_use(user_id, "casino_insurance")
    return refund


# ============================================================
# ПРОФИЛЬ — витрина
# ============================================================
def get_boosts_summary(user_id: int) -> list:
    now = int(time.time())
    items = get_active_items(user_id)
    name_map = {
        "boost_messages_x2":     "x2 к сообщениям",
        "boost_voice_x2":        "x2 к войсу",
        "boost_all_x2":          "x2 ко всему",
        "boost_review_x2":       "x2 к отзывам",
        "boost_cooldown_half":   "Кулдаун отзыва 60с",
        "casino_insurance":      "Страховка ставки",
        "casino_boost_x2":       "x2 к выигрышу",
        "casino_lucky_hour":     "Удачный час",
        "casino_jackpot_ticket": "Билет джекпота",
    }
    out = []
    for it in items:
        key = it["item_key"]
        name = name_map.get(key, key)
        if it["expires_at"] > 0:
            left = max(it["expires_at"] - now, 0)
            out.append({"name": name, "time": format_remaining(left)})
        elif it["uses_left"] > 0:
            out.append({"name": name, "time": f"{it['uses_left']} исп."})
    return out
