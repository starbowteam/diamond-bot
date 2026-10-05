# -*- coding: utf-8 -*-
import os
import json
import time
import random
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import disnake
from disnake.ext import commands
from disnake.ui import View, Button, Select, Modal, TextInput
from disnake import ButtonStyle, SelectOption

from core.utils import (
    CONFIG, FILES, BASE_DIR, DATA_DIR, CATALOG_DIR, ADD_DIR,
    logger, db, cur,
    load_json, save_json, now_ts,
    log_discord, log_command,
    has_admin_command_roles,
    clean_embed_for_discohook,
    get_dc_cache, save_dc_cache, sync_dc_to_json,
    update_user_roles,
    activate_item, get_item, clear_item,
)

IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"
IMG_UNUSED = "https://cdn.discordapp.com/attachments/1527006158282555412/1556735382689947688/image.png?backend=b2&ex=6ac53e4d&is=6ac3eccd&hm=ec03756f0f5f5c1b18fe17468fe0aee06a8fa872ce79caa150ec2a817dec85f9&"

# 👇 Правило копилки клана живёт в clan/core.py (функция clan_cut):
#    до 100 DC — 100% в копилку, больше 100 DC — 40%.
#    Пользователь при этом ВСЕГДА получает 100% начисления.
CLAN_SHARE = 0.40  # оставлено для совместимости со старым кодом

# ============================================================
# 👇 ЕЖЕДНЕВНЫЙ КЛУБНЫЙ БОНУС
# ============================================================
MSK = timezone(timedelta(hours=3))

DAILY_CLUB_BONUS = 10          # было 3 DC
DAILY_BONUS_COOLDOWN = 86400   # раз в сутки


def _msk_day_start_ts() -> int:
    """Начало текущих суток по МСК — та же граница, что у сброса активности."""
    now = datetime.now(MSK)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def touch_activity(user_id: int):
    """
    Отмечает активность юзера (сообщение / вход в войс).
    Используется автоочисткой клана: кто не активен 3 недели — вон.
    """
    try:
        data = get_dc_cache(user_id)
        data["last_active_ts"] = int(time.time())
        save_dc_cache(user_id, data)
    except Exception as e:
        logger.warning(f"touch_activity {user_id}: {e}")


def has_daily_activity(data: dict) -> bool:
    """
    Активил ли юзер за текущие сутки (МСК).
    Считаем: писал в чат ИЛИ был в войсе ИЛИ есть свежая отметка активности.
    """
    ts = int(data.get("last_active_ts", 0) or 0)
    if ts >= _msk_day_start_ts():
        return True
    # Фолбэк для старых записей, где отметки активности ещё нет
    return bool(
        (data.get("messages_today", 0) or 0) > 0
        or (data.get("voice_time_today", 0) or 0) > 0
    )


def get_user_dc_data(user_id: int) -> dict:
    return get_dc_cache(user_id)


def save_user_dc_data(user_id: int, user_data: dict):
    save_dc_cache(user_id, user_data)
    sync_dc_to_json()


async def get_user_balance(user_id: int) -> int:
    return get_dc_cache(user_id)["balance"]


async def set_user_balance(user_id: int, amount: int):
    data = get_dc_cache(user_id)
    data["balance"] = amount
    save_dc_cache(user_id, data)
    sync_dc_to_json()


async def _notify_dc_change(user_id: int, delta: int, reason: str, new_balance: int):
    try:
        from core.bot import bot
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except Exception:
                return
        if user is None:
            return

        if delta >= 0:
            title = f"💎 Вам начислено {abs(delta)} DC"
            color = 0x2ecc71
        else:
            title = f"💎 У вас списано {abs(delta)} DC"
            color = 0xff6600

        embed = disnake.Embed(
            title=title,
            description=(
                f"> **Причина:** {reason}\n"
                f"> **Новый баланс:** `{new_balance} DC`"
            ),
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_image(url=IMG_STRIPE)
        await user.send(embed=embed)
    except disnake.Forbidden:
        logger.debug(f"ЛС закрыты у {user_id}")
    except Exception as e:
        logger.warning(f"_notify_dc_change {user_id}: {e}")


async def add_dc(user_id: int, amount: int, reason: str, notify: bool = True, log: bool = True,
                 clan_share: float = 0.0, to_clan_pool: bool = False):
    """
    Начисляет DC пользователю.

    Пользователь ВСЕГДА получает всю сумму — вклад в копилку с него не списывается,
    он начисляется сверху.

    to_clan_pool=True — дополнительно начислить в копилку клана по правилу
        (см. clan.core.clan_cut): до 100 DC — вся сумма, больше 100 DC — 40%.
    clan_share — явная доля 0..1, если правило нужно переопределить вручную.
    """
    data = get_dc_cache(user_id)
    data["balance"] += amount
    data["history"].append({
        "date": int(time.time()),
        "amount": amount,
        "reason": reason,
    })
    if len(data["history"]) > 50:
        data["history"] = data["history"][-50:]
    save_dc_cache(user_id, data)
    sync_dc_to_json()

    # 👇 Клан-вклад: считаем по правилу копилки
    bank_amount = 0
    if amount > 0:
        if to_clan_pool:
            try:
                from clan.core import clan_cut
                bank_amount = clan_cut(amount)
            except Exception as e:
                logger.warning(f"clan_cut err: {e}")
                bank_amount = 0
        elif clan_share > 0:
            bank_amount = int(amount * clan_share)

    if bank_amount > 0:
        try:
            from clan.core import add_clan_contribution
            await add_clan_contribution(user_id, bank_amount, reason)
        except Exception as e:
            logger.warning(f"clan pool add_dc err: {e}")

    # 👇 Достижения по балансу
    if amount > 0:
        try:
            from clan.achievements import check_and_unlock
            from core.bot import bot
            asyncio.create_task(check_and_unlock(user_id, "balance", value=data["balance"], bot=bot))
        except Exception as e:
            logger.warning(f"balance ach: {e}")

    # 👇 АВТОВЫДАЧА КЛАНА: баланс только что дорос до порога (было < MIN_BALANCE)
    if amount > 0:
        try:
            from clan.core import try_auto_assign_clan, MIN_BALANCE
            if data["balance"] >= MIN_BALANCE > data["balance"] - amount:
                await try_auto_assign_clan(user_id)
        except Exception as e:
            logger.warning(f"auto-assign clan после начисления {user_id}: {e}")

    if log:
        await log_discord(
            title="💎 Начислены Diamond Coins",
            description=f"> **Пользователь:** <@{user_id}>\n> **Количество:** `+{amount} DC`\n> **Причина:** {reason}\n> **Новый баланс:** `{data['balance']} DC`",
            color=0x00ff00
        )

    if notify:
        await _notify_dc_change(user_id, amount, reason, data["balance"])


async def remove_dc(user_id: int, amount: int, reason: str, notify: bool = True, log: bool = True,
                    mark_activity: bool = True) -> bool:
    """
    Списывает DC.

    mark_activity=True — засчитывает это как действие юзера (покупка, ставка).
    Ставь False, если списание делает персонал вручную: это не активность юзера.
    """
    data = get_dc_cache(user_id)
    if data["balance"] < amount:
        return False
    data["balance"] -= amount
    data["history"].append({
        "date": int(time.time()),
        "amount": -amount,
        "reason": reason,
    })
    if len(data["history"]) > 50:
        data["history"] = data["history"][-50:]
    # 👇 Покупка/ставка — это действие, сбрасывает счётчик неактивности
    if mark_activity:
        data["last_active_ts"] = int(time.time())
    save_dc_cache(user_id, data)
    sync_dc_to_json()

    if log:
        await log_discord(
            title="💎 Списаны Diamond Coins",
            description=f"> **Пользователь:** <@{user_id}>\n> **Количество:** `-{amount} DC`\n> **Причина:** {reason}\n> **Новый баланс:** `{data['balance']} DC`",
            color=0xff6600
        )

    if notify:
        await _notify_dc_change(user_id, -amount, reason, data["balance"])

    return True


async def add_purchase(user_id: int, item_type: str, item_value: str, from_action: bool = False):
    data = get_dc_cache(user_id)
    for p in data["purchases"]:
        if p["type"] == item_type and p["value"] == item_value and not p["used"]:
            return
    data["purchases"].append({
        "type": item_type,
        "value": item_value,
        "used": False,
        "from_action": from_action,
        "date": int(time.time()),
    })
    save_dc_cache(user_id, data)
    sync_dc_to_json()


async def get_user_purchases(user_id: int, only_unused: bool = False) -> list:
    data = get_dc_cache(user_id)
    purchases = data.get("purchases", [])
    if only_unused:
        return [p for p in purchases if not p["used"]]
    return purchases


async def remove_purchase(user_id: int, purchase_index: int):
    data = get_dc_cache(user_id)
    if 0 <= purchase_index < len(data["purchases"]):
        del data["purchases"][purchase_index]
        save_dc_cache(user_id, data)
        sync_dc_to_json()
        return True
    return False


async def add_message_dc(user_id: int):
    data = get_dc_cache(user_id)
    data["messages_today"] = data.get("messages_today", 0) + 1
    data["last_active_ts"] = int(time.time())
    save_dc_cache(user_id, data)


async def add_voice_dc(user_id: int, seconds: int):
    data = get_dc_cache(user_id)
    data["voice_time_today"] = data.get("voice_time_today", 0) + seconds
    data["last_active_ts"] = int(time.time())
    save_dc_cache(user_id, data)


async def daily_activity_payout():
    rows = cur.execute("SELECT user_id, messages_today, voice_time_today FROM dc_cache").fetchall()
    paid_users = 0
    total_paid = 0

    for row in rows:
        uid = row["user_id"]
        msgs = row["messages_today"] or 0
        voice_sec = row["voice_time_today"] or 0

        msg_batches = msgs // CONFIG["MESSAGE_BATCH"]
        msg_dc = min(msg_batches * CONFIG["MESSAGE_RATE"], CONFIG["MAX_DAILY_MESSAGES"])

        voice_hours = voice_sec // 3600
        voice_dc = min(voice_hours * CONFIG["VOICE_RATE"], CONFIG["MAX_DAILY_VOICE"])

        total = msg_dc + voice_dc

        data = get_dc_cache(uid)
        data["messages_today"] = 0
        data["voice_time_today"] = 0
        data["last_voice_dc"] = 0
        save_dc_cache(uid, data)

        if total > 0:
            parts = []
            if msg_dc > 0:
                parts.append(f"чат: {msg_dc} DC")
            if voice_dc > 0:
                parts.append(f"голос: {voice_dc} DC")
            reason = "Активность за день (" + ", ".join(parts) + ")"

            # 👇 Копилка клана по правилу: до 100 DC — вся сумма, больше — 40%
            await add_dc(uid, total, reason, notify=True, log=False, to_clan_pool=True)
            paid_users += 1
            total_paid += total
            await asyncio.sleep(0.4)

    try:
        sync_dc_to_json()
    except Exception:
        pass

    logger.info(f"daily_activity_payout: {paid_users} юзеров, {total_paid} DC")

    if paid_users > 0:
        await log_discord(
            title="💎 Ежедневная выплата за активность",
            description=(
                f"> **Получателей:** `{paid_users}`\n"
                f"> **Всего выдано:** `{total_paid} DC`"
            ),
            color=0x00ff00
        )


# ============================================================
# ЕЖЕДНЕВНЫЙ ПОДАРОК
# ============================================================
DAILY_GIFT_ITEM_KEY = "daily_gift"
DAILY_GIFT_MIN = 10
DAILY_GIFT_MAX = 30
DAILY_GIFT_COOLDOWN_HOURS = 24


def get_daily_gift_status(user_id: int) -> dict:
    item = get_item(user_id, DAILY_GIFT_ITEM_KEY)
    if item is None:
        return {"ready": True, "next_ts": 0}
    return {"ready": False, "next_ts": item["expires_at"]}


async def claim_daily_gift(user_id: int) -> dict:
    status = get_daily_gift_status(user_id)
    if not status["ready"]:
        return {
            "ok": False,
            "amount": 0,
            "next_ts": status["next_ts"],
            "error": "not_ready",
        }

    amount = random.randint(DAILY_GIFT_MIN, DAILY_GIFT_MAX)

    # 👇 Забрал подарок — значит зашёл и что-то сделал
    touch_activity(user_id)

    await add_dc(user_id, amount, "Ежедневный подарок", notify=False, log=False, to_clan_pool=True)

    activate_item(
        user_id,
        DAILY_GIFT_ITEM_KEY,
        "gift",
        value=amount,
        duration_hours=DAILY_GIFT_COOLDOWN_HOURS,
        uses=-1,
    )

    item = get_item(user_id, DAILY_GIFT_ITEM_KEY)
    next_ts = item["expires_at"] if item else 0

    return {
        "ok": True,
        "amount": amount,
        "next_ts": next_ts,
        "error": "",
    }


def load_shop_catalog() -> dict:
    path = CONFIG["SHOP_CATALOG_PATH"]
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                logger.error("shop_catalog.json parse err")
                return create_default_catalog()
    return create_default_catalog()


def create_default_catalog() -> dict:
    catalog = {
        "discounts": {"label": "🛒 Скидки", "description": "Скидки на заказы", "items": {
            "3": {"name": "3% скидка", "price": 30, "description": "Скидка 3%"},
        }},
        "design": {"label": "🎨 Дизайн", "description": "Услуги дизайнера", "items": {
            "avatar": {"name": "Аватарка", "price": 40, "description": "Уникальная аватарка"},
        }},
    }
    with open(CONFIG["SHOP_CATALOG_PATH"], "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    return catalog


async def daily_bonus():
    """
    Ежедневный клубный бонус.

    👇 Что изменилось:
      · сумма 3 DC → 10 DC
      · выдаётся ТОЛЬКО тем, кто за сутки хоть как-то активил
        (писал в чат или был в войсе)
    """
    from core.bot import bot
    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        return

    club_role = guild.get_role(CONFIG["ROLE_IDS"]["club"])
    if not club_role:
        return

    now = now_ts()
    paid = 0
    skipped_inactive = 0
    total = 0

    for member in guild.members:
        if member.bot:
            continue
        if club_role not in member.roles:
            continue

        data = get_dc_cache(member.id)
        # Уже получал за последние сутки
        if data["last_bonus"] >= now - DAILY_BONUS_COOLDOWN:
            continue

        # 👇 Новое условие: без активности за день бонус не выдаём
        if not has_daily_activity(data):
            skipped_inactive += 1
            continue

        await add_dc(
            member.id, DAILY_CLUB_BONUS, "Ежедневный бонус (Клуб)",
            notify=True, log=False, to_clan_pool=True
        )

        data = get_dc_cache(member.id)
        data["last_bonus"] = now
        save_dc_cache(member.id, data)

        paid += 1
        total += DAILY_CLUB_BONUS
        await asyncio.sleep(0.4)

    try:
        sync_dc_to_json()
    except Exception:
        pass

    logger.info(
        f"daily_bonus: выдано {paid} юзерам по {DAILY_CLUB_BONUS} DC "
        f"(всего {total} DC), пропущено неактивных: {skipped_inactive}"
    )


async def check_unused_purchases(bot):
    now = int(time.time())
    week = 7 * 86400

    rows = cur.execute("SELECT user_id, purchases FROM dc_cache").fetchall()
    sent = 0
    checked = 0

    for row in rows:
        uid = row["user_id"]
        try:
            purchases = json.loads(row["purchases"]) if row["purchases"] else []
        except Exception:
            continue
        if not purchases:
            continue

        checked += 1
        old_unused = []
        for idx, p in enumerate(purchases):
            if p.get("used"):
                continue
            d = p.get("date", 0)
            if d == 0:
                continue
            age = now - d
            if week <= age <= 60 * 86400:
                last_rem = p.get("last_reminder", 0)
                if now - last_rem >= week:
                    old_unused.append((idx, p))

        if not old_unused:
            continue

        user = bot.get_user(uid)
        if user is None:
            try:
                user = await bot.fetch_user(uid)
            except Exception:
                continue

        try:
            items_lines = []
            for _, p in old_unused[:10]:
                v = p.get("value", "—")
                t = p.get("type", "")
                dstr = datetime.fromtimestamp(p.get("date", 0)).strftime("%d.%m.%Y")
                items_lines.append(f"> 💎 **{v}** — `{t}` (куплен {dstr})")
            items_text = "\n".join(items_lines)
            more = ""
            if len(old_unused) > 10:
                more = f"\n\n> …и ещё **{len(old_unused) - 10}** товаров"

            embed1 = disnake.Embed(color=6776679)
            embed1.set_image(url=IMG_UNUSED)
            embed2 = disnake.Embed(
                title="🎁 У вас есть неиспользованные товары!",
                description=(
                    f"> Привет, **{user.display_name}**! Мы заметили, что у вас есть купленные товары, которые вы **ещё не активировали**.\n\n"
                    f"**Товары:**\n{items_text}{more}\n\n"
                    f"**Как активировать?**\n"
                    f"> Перейдите в <#1462136361711829053>, нажмите кнопку **Купить** → выберите **Diamond Coins** → выберите нужный товар.\n\n"
                    f"> Если возникли вопросы — обратитесь в поддержку.\n"
                    f"> Приятных покупок! 💎"
                ),
                color=6776679,
                timestamp=datetime.now(timezone.utc)
            )
            embed2.set_image(url=IMG_STRIPE)
            await user.send(embeds=[embed1, embed2])

            for idx, p in old_unused:
                purchases[idx]["last_reminder"] = now

            dc_data = get_dc_cache(uid)
            dc_data["purchases"] = purchases
            save_dc_cache(uid, dc_data)
            sent += 1

            await asyncio.sleep(0.5)
        except disnake.Forbidden:
            continue
        except Exception as e:
            logger.warning(f"unused reminder {uid}: {e}")
            continue

    try:
        sync_dc_to_json()
    except Exception:
        pass

    logger.info(f"check_unused_purchases: проверено {checked}, отправлено {sent}")


def get_progress_bar(count: int):
    thresholds = [
        (1, "club", "Клуб"),
        (5, "bronze", "Bronze Buyer"),
        (10, "silver", "Silver Buyer"),
        (15, "gold", "Gold Buyer"),
        (20, "diamond", "Diamond Buyer"),
        (25, "crystalis", "Crystalis Buyer"),
        (float('inf'), "pka", "Покупатель века"),
    ]
    current_role = "Нет"
    next_role = "Клуб"
    next_threshold = 1
    for threshold, key, name in thresholds:
        if count >= threshold:
            current_role = name
        else:
            next_threshold = threshold
            next_role = name
            break
    if count >= 26:
        return f"Текущая: **{current_role}** (26+)\n🎉 Вы достигли максимальной роли!"
    else:
        progress = min(count / next_threshold, 1.0)
        bar_length = 10
        filled = int(progress * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        return (f"Текущая: **{current_role}**\n"
                f"Следующая: **{next_role}** (нужно {next_threshold} отзывов)\n"
                f"Прогресс: `{bar}` {int(progress*100)}%")


def get_dc_cache_all() -> dict:
    rows = cur.execute("SELECT * FROM dc_cache").fetchall()
    data = {}
    for row in rows:
        uid = row["user_id"]
        data[str(uid)] = {
            "balance": row["balance"],
            "purchases": json.loads(row["purchases"]) if row["purchases"] else [],
            "history": json.loads(row["history"]) if row["history"] else [],
            "last_review": row["last_review"],
            "last_bonus": row["last_bonus"],
            "messages_today": row["messages_today"],
            "voice_time_today": row["voice_time_today"],
            "last_reset_date": row["last_reset_date"],
            "last_voice_dc": row["last_voice_dc"],
        }
    return data


def setup_dc(bot):
    pass
