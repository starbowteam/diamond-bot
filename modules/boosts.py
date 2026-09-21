# -*- coding: utf-8 -*-
"""Система бустов DC-заработка + казино-предметы."""
import time

from core.utils import (
    get_item, get_active_items, activate_item, consume_use, clear_item,
    get_dc_cache, save_dc_cache, sync_dc_to_json, logger
)


# ============================================================
# ПРИМЕНЕНИЕ БУСТОВ К НАЧИСЛЕНИЯМ
# ============================================================
def get_multiplier(user_id: int, kind: str) -> float:
    """
    Возвращает множитель начисления.
    kind: 'messages' | 'voice' | 'review'
    Учитывает boost_all_x2 + специфичный буст — берёт максимальный.
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
    """Применяет буст к базовому начислению и возвращает итоговую сумму."""
    mult = get_multiplier(user_id, kind)
    return int(base * mult)


def get_review_cooldown(user_id: int) -> int:
    """Возвращает кулдаун отзыва (по умолчанию 120 сек, с бустом 60)."""
    item = get_item(user_id, "boost_cooldown_half")
    if item and item["value"]:
        try:
            return int(item["value"])
        except Exception:
            pass
    return 120


def try_daily_reset(user_id: int) -> bool:
    """
    Если у юзера куплен буст daily_reset — обнуляет счётчики
    messages_today / voice_time_today и удаляет буст.
    """
    item = get_item(user_id, "boost_daily_reset")
    if not item:
        return False
    data = get_dc_cache(user_id)
    data["messages_today"] = 0
    data["voice_time_today"] = 0
    data["last_voice_dc"] = 0
    save_dc_cache(user_id, data)
    sync_dc_to_json()
    clear_item(user_id, "boost_daily_reset")
    logger.info(f"Daily reset применён для {user_id}")
    return True


def is_daily_reset_active(user_id: int) -> bool:
    return get_item(user_id, "boost_daily_reset") is not None


# ============================================================
# КАЗИНО-ПРЕДМЕТЫ
# ============================================================
def get_casino_multiplier(user_id: int) -> float:
    """Множитель к выплате (lucky_hour + next_mult, если есть)."""
    mult = 1.0
    lh = get_item(user_id, "casino_lucky_hour")
    if lh:
        mult *= float(lh["value"] or 1.0)
    return mult


def has_insurance(user_id: int) -> bool:
    return get_item(user_id, "casino_insurance") is not None


def has_next_mult(user_id: int) -> bool:
    return get_item(user_id, "casino_boost_x2") is not None


def apply_casino_win(user_id: int, base_payout: int) -> tuple[int, list[str]]:
    """
    Применяет все активные казино-бусты к выигрышу.
    Возвращает (итоговая_выплата, [использованные_бусты])
    """
    used = []
    payout = base_payout

    # lucky_hour — постоянный на время
    lh = get_item(user_id, "casino_lucky_hour")
    if lh and lh["value"]:
        payout = int(payout * float(lh["value"]))
        used.append("lucky_hour")

    # next_mult — разово
    nm = get_item(user_id, "casino_boost_x2")
    if nm and nm["value"]:
        payout = int(payout * float(nm["value"]))
        consume_use(user_id, "casino_boost_x2")
        used.append("next_mult")

    return payout, used


def try_insurance(user_id: int, bet: int) -> int:
    """
    Если есть страховка и юзер проиграл — возвращает 50% ставки.
    Возвращает сумму возврата (0 если нет страховки).
    """
    ins = get_item(user_id, "casino_insurance")
    if not ins:
        return 0
    refund = int(bet * float(ins["value"] or 0.5))
    consume_use(user_id, "casino_insurance")
    return refund


# ============================================================
# ПРОФИЛЬ — витрина активных бустов для карточки
# ============================================================
def get_boosts_summary(user_id: int) -> list[dict]:
    """
    Список активных бустов с человеко-понятными названиями — для профиля/лога.
    """
    now = int(time.time())
    items = get_active_items(user_id)
    out = []
    name_map = {
        "boost_messages_x2":    "x2 к сообщениям",
        "boost_voice_x2":       "x2 к войсу",
        "boost_all_x2":         "x2 ко всему",
        "boost_review_x2":      "x2 к отзывам",
        "boost_cooldown_half":  "Кулдаун отзыва 60с",
        "casino_insurance":     "Страховка ставки",
        "casino_boost_x2":      "x2 к выигрышу",
        "casino_lucky_hour":    "Удачный час",
        "casino_jackpot_ticket":"Билет в джекпот",
    }
    for it in items:
        key = it["item_key"]
        name = name_map.get(key, key)
        if it["expires_at"] > 0:
            left = max(it["expires_at"] - now, 0)
            hours = left // 3600
            mins = (left % 3600) // 60
            if hours > 0:
                time_str = f"{hours}ч {mins}м"
            else:
                time_str = f"{mins}м"
            out.append({"name": name, "time": time_str})
        elif it["uses_left"] > 0:
            out.append({"name": name, "time": f"{it['uses_left']} исп."})
    return out
