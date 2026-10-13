# -*- coding: utf-8 -*-
"""DCC+ · Diamond Coin Crypto+."""
import os
import asyncio

import disnake

from core.utils import logger, load_json
from dccplus.core import (
    init_dccplus_tables,
    start_dcc_tasks,
    update_price,
)
from dccplus.views import DCCPanelView


# 👇 ТЕСТОВЫЙ КАНАЛ — поменяешь когда скажешь
DCC_CHANNEL_ID = 1559603203224637460
EMBED_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "embeds", "dccplus.json"
)


def _build_panel_embeds():
    data = load_json(EMBED_FILE, {})
    embeds = []
    for e in data.get("embeds", []):
        try:
            embeds.append(disnake.Embed.from_dict(e))
        except Exception as exc:
            logger.warning(f"dcc embed: {exc}")
    if not embeds:
        embeds = [disnake.Embed(
            title="💠 DCC+ · Diamond Crypto+",
            description="> Инвестируй, стейкай, зарабатывай.",
            color=0x4dd0e1,
        )]
    return embeds


async def send_dcc_panel(bot):
    ch = bot.get_channel(DCC_CHANNEL_ID)
    if not ch:
        try:
            ch = await bot.fetch_channel(DCC_CHANNEL_ID)
        except Exception as e:
            logger.warning(f"dcc panel channel not found: {e}")
            return

    # Чистим старые сообщения бота
    try:
        async for m in ch.history(limit=50):
            if m.author == bot.user:
                try:
                    await m.delete()
                except Exception:
                    pass
    except Exception:
        pass

    embeds = _build_panel_embeds()
    await ch.send(embeds=embeds, view=DCCPanelView())
    logger.info("💠 DCC+ панель отправлена")


def init_dccplus(bot):
    """Инициализация DCC+. Вызывать из bot.on_ready()."""
    init_dccplus_tables()

    try:
        update_price()
    except Exception as e:
        logger.warning(f"dcc init price: {e}")

    start_dcc_tasks(bot)

    try:
        bot.add_view(DCCPanelView())
    except Exception as e:
        logger.warning(f"dcc add_view: {e}")

    bot.loop.create_task(send_dcc_panel(bot))

    logger.info("💠 DCC+ инициализирован")
