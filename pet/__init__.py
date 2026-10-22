# -*- coding: utf-8 -*-
import os
import asyncio
import disnake

from core.utils import logger, load_json, CONFIG
from pet.core import (
    init_pet_tables,
    migrate_old_pets,
    get_clan_pet,
)
from pet.views import ClanPetMainView

PET_CHANNEL_ID = 1558887828920995880
PET_EMBED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet.json")

def _build_panel_embeds():
    data = load_json(PET_EMBED_FILE, {})
    embeds = []
    for e in data.get("embeds", []):
        try:
            embeds.append(disnake.Embed.from_dict(e))
        except Exception as exc:
            logger.warning(f"pet embed: {exc}")
    if not embeds:
        embeds = [disnake.Embed(
            title="🐾 Душа Клана",
            description="> Корми питомца и получай бонус.",
            color=6776679,
        )]
    return embeds

async def send_pet_panel(bot):
    ch = bot.get_channel(PET_CHANNEL_ID)
    if not ch:
        try:
            ch = await bot.fetch_channel(PET_CHANNEL_ID)
        except Exception as e:
            logger.warning(f"pet panel channel not found: {e}")
            return

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
    await ch.send(embeds=embeds, view=ClanPetMainView())
    logger.info("🐾 Панель питомцев отправлена")

def init_pet_league(bot):
    """Инициализация модуля питомцев."""
    init_pet_tables()
    
    # Запуск миграции в фоне (чтобы не блокировать старт)
    bot.loop.create_task(migrate_old_pets())

    # Регистрация View
    try:
        bot.add_view(ClanPetMainView())
    except Exception as e:
        logger.warning(f"pet add_view: {e}")

    # Отправляем панель
    bot.loop.create_task(send_pet_panel(bot))

    logger.info("🐾 Клановые питомцы инициализированы")
