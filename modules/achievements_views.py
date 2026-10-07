# -*- coding: utf-8 -*-
"""Discord-view панели достижений: селект категорий + Назад/Вперёд."""
import asyncio
from datetime import datetime, timezone

import disnake
from disnake import SelectOption
from disnake.ui import View, Select, Button
from disnake import ButtonStyle, PartialEmoji

from core.utils import logger
from clan.achievements import get_user_achievements
from modules.achievements_panel import CATEGORIES, generate_achievements_panel


P = "\u3164"


def _btn_label(text: str, total: int = 46) -> str:
    text = text.strip()
    if len(text) >= total:
        return text[:total]
    padding = total - len(text)
    left = padding // 2
    right = padding - left
    return f"{P*left}{text}{P*right}"


class AchievementsCategorySelect(Select):
    def __init__(self, active: str = "base"):
        options = [
            SelectOption(
                label=c["label"],
                value=c["key"],
                default=(c["key"] == active),
            ) for c in CATEGORIES
        ]
        super().__init__(
            placeholder="Выбери категорию достижений...",
            min_values=1, max_values=1,
            options=options,
            custom_id="ach_panel:select",
            row=0,
        )

    async def callback(self, inter: disnake.MessageInteraction):
        key = inter.data.values[0]
        await _render(inter, key, 0)


class AchievementsCategoryView(View):
    def __init__(self, active: str = "base"):
        super().__init__(timeout=300)
        self.active = active
        self.add_item(AchievementsCategorySelect(active))

        idx = next((i for i, c in enumerate(CATEGORIES) if c["key"] == active), 0)
        prev_key = CATEGORIES[(idx-1) % len(CATEGORIES)]["key"]
        next_key = CATEGORIES[(idx+1) % len(CATEGORIES)]["key"]

        b_back = Button(label=_btn_label("Назад"), style=ButtonStyle.gray,
                        custom_id=f"ach_panel:back:{prev_key}",
                        emoji=PartialEmoji(name="OffTicket", id=1539657125716824185),
                        row=1)
        b_back.callback = self._back
        self.add_item(b_back)

        b_fwd = Button(label=_btn_label("Вперёд"), style=ButtonStyle.gray,
                       custom_id=f"ach_panel:fwd:{next_key}",
                       emoji=PartialEmoji(name="Oplacheno", id=1539657164778512496),
                       row=1)
        b_fwd.callback = self._fwd
        self.add_item(b_fwd)

    async def _back(self, inter):
        key = self.custom_id.split(":")[-1]
        await _render(inter, key, 0)

    async def _fwd(self, inter):
        key = self.custom_id.split(":")[-1]
        await _render(inter, key, 0)


async def _render(inter: disnake.MessageInteraction, key: str, page: int):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    unlocked = set(get_user_achievements(inter.author.id))

    try:
        buf = await asyncio.to_thread(
            generate_achievements_panel, inter.author.id, unlocked, key, page
        )
        fname = f"ach_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
        file = disnake.File(buf, filename=fname)
        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{fname}")

        kwargs = dict(
            embed=embed, file=file, attachments=[],
            view=AchievementsCategoryView(key),
        )
        try:
            await inter.edit_original_response(**kwargs)
        except Exception:
            await inter.followup.send(ephemeral=True, **kwargs)
    except Exception as e:
        logger.exception(f"ach panel render: {e}")
        try:
            await inter.followup.send(f"❌ {str(e)[:200]}", ephemeral=True)
        except Exception:
            pass
