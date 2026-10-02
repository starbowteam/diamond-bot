# -*- coding: utf-8 -*-
"""
Анонс акции дня в канал витрины.
Новая акция → пинг роли + сообщение. Через час — удаляется.
"""
import os
import time

import disnake

from core.utils import DATA_DIR, logger, load_json, save_json


# ============================================================
# КОНСТАНТЫ
# ============================================================
ANNOUNCE_CHANNEL_ID = 1462136361711829053
PING_ROLE_ID = 1127428607606796290
DEAL_CATALOG_CHANNEL = 1462136361711829053   # тот же канал витрины

DAILY_DEAL_FILE = os.path.join(DATA_DIR, "daily_deal.json")
STATE_FILE = os.path.join(DATA_DIR, "deal_announce.json")

ANNOUNCE_LIFETIME = 3600   # 1 час


# ============================================================
# СОСТОЯНИЕ
# ============================================================
def _load_state() -> dict:
    return load_json(STATE_FILE, {
        "slot": 0,
        "message_id": 0,
        "sent_at": 0,
        "channel_id": 0,
    })


def _save_state(state: dict):
    save_json(STATE_FILE, state)


# ============================================================
# УДАЛЕНИЕ СТАРОГО АНОНСА
# ============================================================
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


# ============================================================
# ТЕКСТ СООБЩЕНИЯ
# ============================================================
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


# ============================================================
# ОТПРАВКА АНОНСА
# ============================================================
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


# ============================================================
# ЗАДАЧА: ПРОВЕРКА НОВОЙ АКЦИИ + УДАЛЕНИЕ СТАРОГО
# ============================================================
async def process_deal_announce(bot):
    """
    1) если анонс висит больше часа — удалить
    2) если слот сменился и акция свежая (< 1 ч) — отправить новый анонс
    3) если слот сменился, но акция старая — слот запомнить, не отправлять
    """
    try:
        deal_data = load_json(DAILY_DEAL_FILE, {})
        cur_slot = deal_data.get("slot", 0)
        cur_deal = deal_data.get("item")
        updated_at = deal_data.get("updated_at", 0)

        state = _load_state()
        now = time.time()

        # ---- 1) старое сообщение старше часа — удалить ----
        if state.get("message_id") and state.get("sent_at"):
            if now - state["sent_at"] > ANNOUNCE_LIFETIME:
                await _delete_announce(bot, state)

        # ---- 2) новый слот ----
        if cur_deal and cur_slot and cur_slot != state.get("slot"):
            # проверим свежесть акции
            if (now - updated_at) < ANNOUNCE_LIFETIME:
                # старое сообщение (если ещё висит) убираем
                if state.get("message_id"):
                    await _delete_announce(bot, state)
                await announce_deal(bot, cur_deal, cur_slot)
            else:
                # опоздали — просто запоминаем слот, чтобы не спамить
                state["slot"] = cur_slot
                _save_state(state)
                logger.info(
                    f"Deal announce skipped (old): slot={cur_slot}, "
                    f"updated {int(now - updated_at)}s ago"
                )

    except Exception as e:
        logger.exception(f"process_deal_announce: {e}")
