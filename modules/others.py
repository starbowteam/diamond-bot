# -*- coding: utf-8 -*-
"""
Единый модуль вспомогательных систем Diamond.

Объединяет:
  · Бусты DC + казино-предметы
  · Анонс акции дня
  · Подарки DC
  · Автозамена ссылок страйпа
"""
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import disnake

from core.utils import (
    DATA_DIR, CONFIG,
    logger, log_discord,
    load_json, save_json,
    get_item, get_active_items, activate_item, consume_use, clear_item,
    get_dc_cache, save_dc_cache, sync_dc_to_json,
)
from modules.dc import get_user_balance, remove_dc, add_dc


# ============================================================
# БЛОК 1: БУСТЫ
# ============================================================
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
    """kind: 'messages' | 'voice' | 'review'"""
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
    item = get_item(user_id, "boost_cooldown_half")
    if item and item["value"]:
        try:
            return int(item["value"])
        except Exception:
            pass
    return 120


def can_activate(user_id: int, item_key: str) -> tuple[bool, str]:
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
    if item_key == "boost_daily_reset":
        data = get_dc_cache(user_id)
        data["messages_today"] = 0
        data["voice_time_today"] = 0
        data["last_voice_dc"] = 0
        save_dc_cache(user_id, data)
        sync_dc_to_json()
        return "✅ Лимит сообщений и войса **обнулён на сегодня**!"

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
# БЛОК 2: АНОНС АКЦИИ ДНЯ
# ============================================================
ANNOUNCE_CHANNEL_ID = 1462136361711829053
PING_ROLE_ID = 1127428607606796290

DAILY_DEAL_FILE = os.path.join(DATA_DIR, "daily_deal.json")
STATE_FILE = os.path.join(DATA_DIR, "deal_announce.json")

ANNOUNCE_LIFETIME = 3600


def _load_state() -> dict:
    return load_json(STATE_FILE, {
        "slot": 0, "message_id": 0, "sent_at": 0, "channel_id": 0,
    })


def _save_state(state: dict):
    save_json(STATE_FILE, state)


async def _delete_announce(bot, state: dict):
    mid = state.get("message_id")
    cid = state.get("channel_id") or ANNOUNCE_CHANNEL_ID
    if not mid:
        return
    try:
        ch = bot.get_channel(cid)
        if not ch:
            ch = await bot.fetch_channel(cid)
        msg = await ch.fetch_message(mid)
        await msg.delete()
        logger.info(f"Deal announce deleted: msg={mid}")
    except disnake.NotFound:
        pass
    except Exception as e:
        logger.warning(f"deal_announce delete: {e}")

    state["message_id"] = 0
    state["sent_at"] = 0
    _save_state(state)


def _build_text(deal: dict) -> str:
    item_data = deal.get("item_data", {})
    name = item_data.get("name", "—")
    orig = deal.get("original_price", 0)
    new = deal.get("new_price", 0)
    discount = deal.get("discount", 0)

    return (
        f"<@&{PING_ROLE_ID}> — **новая акция за DC!**\n\n"
        f"Скидка **{discount}%** на **«{name}»** — сейчас "
        f"**{new} DC** вместо ~~{orig} DC~~.\n\n"
        f"**Как забрать:**\n"
        f"> **Каталог** → **Diamond Coins** → **Акция дня**\n"
        f"Успей — товар дня меняется каждые несколько часов."
    )


async def announce_deal(bot, deal: dict, slot: int):
    ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if not ch:
        try:
            ch = await bot.fetch_channel(ANNOUNCE_CHANNEL_ID)
        except Exception as e:
            logger.warning(f"deal_announce channel fetch: {e}")
            return

    text = _build_text(deal)
    try:
        msg = await ch.send(text)
    except Exception as e:
        logger.warning(f"deal_announce send: {e}")
        return

    state = {
        "slot": slot,
        "message_id": msg.id,
        "sent_at": int(time.time()),
        "channel_id": ch.id,
    }
    _save_state(state)

    logger.info(f"Deal announce sent: slot={slot} msg={msg.id}")


async def process_deal_announce(bot):
    try:
        deal_data = load_json(DAILY_DEAL_FILE, {})
        cur_slot = deal_data.get("slot", 0)
        cur_deal = deal_data.get("item")
        updated_at = deal_data.get("updated_at", 0)

        state = _load_state()
        now = time.time()

        if state.get("message_id") and state.get("sent_at"):
            if now - state["sent_at"] > ANNOUNCE_LIFETIME:
                await _delete_announce(bot, state)

        if cur_deal and cur_slot and cur_slot != state.get("slot"):
            if (now - updated_at) < ANNOUNCE_LIFETIME:
                if state.get("message_id"):
                    await _delete_announce(bot, state)
                await announce_deal(bot, cur_deal, cur_slot)
            else:
                state["slot"] = cur_slot
                _save_state(state)
                logger.info(
                    f"Deal announce skipped (old): slot={cur_slot}, "
                    f"updated {int(now - updated_at)}s ago"
                )

    except Exception as e:
        logger.exception(f"process_deal_announce: {e}")


# ============================================================
# БЛОК 3: ПОДАРКИ DC
# ============================================================
GIFT_FEE_PERCENT = 5
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"


async def process_gift_dc(
    sender: disnake.Member,
    recipient_id: int,
    amount: int,
    price_paid: int,
) -> tuple[bool, str]:
    guild = sender.guild
    recipient = guild.get_member(recipient_id)

    if not recipient:
        await add_dc(sender.id, price_paid, "Возврат — получатель не найден")
        return False, "Получатель не найден на сервере"

    if recipient.bot:
        await add_dc(sender.id, price_paid, "Возврат — получатель бот")
        return False, "Нельзя дарить ботам"

    if recipient.id == sender.id:
        await add_dc(sender.id, price_paid, "Возврат — сам себе")
        return False, "Нельзя подарить самому себе"

    try:
        await add_dc(recipient.id, amount, f"Подарок от {sender.display_name}")
    except Exception as e:
        logger.exception(f"gift: add_dc error: {e}")
        await add_dc(sender.id, price_paid, "Возврат — ошибка начисления")
        return False, f"Ошибка начисления: {e}"

    try:
        from clan.quests import on_gift_quest_hook
        await on_gift_quest_hook(sender.id, amount)
    except Exception as e:
        logger.warning(f"clan gift hook: {e}")

    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot
        from core.utils import get_dc_cache
        data = get_dc_cache(sender.id)
        total_gifted = 0
        for h in data.get("history", []):
            reason = h.get("reason", "")
            amt = h.get("amount", 0)
            if reason.startswith("Подарок от") and amt > 0:
                total_gifted += amt
        total_gifted += amount
        await check_and_unlock(sender.id, "gift_total", value=total_gifted, bot=bot)
    except Exception as e:
        logger.warning(f"gift ach: {e}")

    try:
        dm_embed = disnake.Embed(
            title="🎁 Вам подарили Diamond Coins!",
            description=(
                f"> **Отправитель:** {sender.display_name}\n"
                f"> **Получено:** `+{amount} DC`\n\n"
                f"> Спасибо за то, что вы с нами! Оставить отзыв можно в <#1462074763437543435>."
            ),
            color=0x2ecc71,
            timestamp=datetime.now(timezone.utc)
        )
        dm_embed.set_image(url=IMG_STRIPE)
        await recipient.send(embed=dm_embed)
    except Exception as e:
        logger.warning(f"gift: не удалось отправить ЛС получателю {recipient.id}: {e}")

    await log_discord(
        title="🎁 Подарок DC",
        description=(
            f"> **Отправитель:** {sender.mention}\n"
            f"> **Получатель:** {recipient.mention}\n"
            f"> **Сумма:** `{amount} DC`\n"
            f"> **Комиссия:** `{price_paid - amount} DC`"
        ),
        color=0x00ff00,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return True, f"Подарок отправлен! Получатель: {recipient.mention}"


# ============================================================
# БЛОК 4: АВТОЗАМЕНА ССЫЛОК СТРАЙПА
# ============================================================
NEW_URL = (
    "https://cdn.discordapp.com/attachments/1527006158282555412/"
    "1537851307757539390/image.png"
    "?ex=6aba8d23&is=6ab93ba3&"
    "hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"
)

STRIPE_URL_RE = re.compile(
    r"https://cdn\.discordapp\.com/attachments/1527006158282555412/"
    r"1537851307757539390/image\.png\?[^\s\"'\)\]]+"
)

BASE_DIR = Path(__file__).parent.resolve()

EXCLUDE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".backup_stripe", ".idea", ".vscode",
}

VALID_EXTS = {".py", ".json", ".txt", ".md"}


def should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return True
    return path.suffix.lower() not in VALID_EXTS


def fix_content(content: str) -> tuple[str, int]:
    matches = STRIPE_URL_RE.findall(content)
    count = len(matches)
    if count == 0:
        return content, 0
    new_content = STRIPE_URL_RE.sub(NEW_URL, content)
    return new_content, count


def run_fix(verbose: bool = True) -> dict:
    stats = {
        "scanned": 0,
        "changed": 0,
        "total_replacements": 0,
        "files": [],
    }

    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for fname in files:
            path = Path(root) / fname
            if should_skip(path):
                continue

            stats["scanned"] += 1

            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, PermissionError, IsADirectoryError):
                continue

            new_content, count = fix_content(content)
            if count == 0:
                continue

            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)

                stats["changed"] += 1
                stats["total_replacements"] += count
                rel = str(path.relative_to(BASE_DIR))
                stats["files"].append((rel, count))

                if verbose:
                    print(f"  ✅ {rel} — {count} замен")

            except Exception as e:
                if verbose:
                    print(f"  ❌ {path}: {e}")

    return stats


def main():
    print("🔧 Автозамена ссылок страйпа (stripe)")
    print(f"📂 {BASE_DIR}")
    print()
    print("🔍 Сканирую .py / .json / .txt / .md ...")
    print()

    stats = run_fix(verbose=True)

    print()
    print("=" * 55)
    print(f"📊 Просканировано файлов:      {stats['scanned']}")
    print(f"✏️  Изменено файлов:            {stats['changed']}")
    print(f"🔄 Всего ссылок заменено:      {stats['total_replacements']}")

    if stats["changed"] == 0:
        print()
        print("✅ Всё актуально, менять нечего.")
    else:
        print()
        print("✅ Готово!")

    return stats


if __name__ == "__main__":
    main()
