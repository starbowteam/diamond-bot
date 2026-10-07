# -*- coding: utf-8 -*-
"""Инвайт-панель адвайтеров: статичная панель + ephemeral экраны."""

import asyncio
import os
from datetime import datetime, timezone

import disnake
from disnake import ButtonStyle, PartialEmoji
from disnake.ui import View

from core.utils import logger, load_json
from work import core as wcore
from work import render as wrender


P = "\u3164"

IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"

# Суммарная длина 3 кнопок = 35 символов
_BTN_TOTAL = 39

# Эмодзи
EMOJI_LINK    = PartialEmoji(name="reklama", id=1555654392202535073)
EMOJI_TOP     = PartialEmoji(name="peope",   id=1555654375781834883)
EMOJI_REWARDS = PartialEmoji(name="1d1ds",   id=1552730624572391584)


def _btn_labels_total(labels, total=_BTN_TOTAL):
    base = sum(len(s) for s in labels)
    extra = max(0, total - base)
    n = len(labels)
    if n == 0:
        return labels
    per = extra // n
    rem = extra % n
    result = []
    for i, s in enumerate(labels):
        pad = per + (1 if i < rem else 0)
        left = pad // 2
        right = pad - left
        result.append(f"{P * left}{s}{P * right}")
    return result


_L_LINK, _L_TOP, _L_REWARDS = _btn_labels_total([
    "Ссылка", "Общий топ", "Награды",
])


# ============================================================
# ЭМБЕД ПАНЕЛИ (из invite.json)
# ============================================================
def build_panel_embeds():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "invite.json")
    data = load_json(path, {})
    if not data or "embeds" not in data:
        return [disnake.Embed(
            title="📨 Инвайт-панель",
            description="> Жми кнопки ниже.",
            color=6776679,
        )]
    return [disnake.Embed.from_dict(e) for e in data["embeds"]]


# ============================================================
# СБОРКА PAYLOAD ДЛЯ ЭКРАНА
# ============================================================
async def _build_payload(inter, screen):
    link = None

    if screen == "link":
        link = await wcore.ensure_advertiser_link(inter.bot, inter.author.id)
        if not link:
            return None, None, None

    buf = None
    fname = None

    if screen == "link":
        stats = wcore.get_advertiser_stats(inter.author.id)
        buf = await asyncio.to_thread(
            wrender.render_personal,
            inter.author.id, inter.author.display_name, stats,
            link["invite_url"] if link else None,
            link["created_at"] if link else None,
        )
        fname = f"adv_personal_{inter.author.id}.png"

    elif screen == "top":
        stats = wcore.get_advertiser_stats(inter.author.id)
        top_list = wcore.get_advertiser_top(limit=10)
        my_place = None
        my_diff_1 = None
        my_diff_3 = None
        for i, entry in enumerate(top_list, 1):
            if entry["advertiser_id"] == inter.author.id:
                my_place = i
                break
        if top_list:
            my_diff_1 = max(top_list[0]["rewarded"] - stats["rewarded"], 0)
        if len(top_list) >= 3:
            my_diff_3 = max(top_list[2]["rewarded"] - stats["rewarded"], 0)

        buf = await asyncio.to_thread(
            wrender.render_top,
            inter.author.id, inter.author.display_name,
            stats, my_place, my_diff_1, my_diff_3, top_list,
        )
        fname = f"adv_top_{inter.author.id}.png"

    elif screen == "rewards":
        stats = wcore.get_advertiser_stats(inter.author.id)
        total = wcore.get_total_rewarded_dc(inter.author.id)
        hold = wcore.get_hold_dc(inter.author.id)
        history = wcore.get_reward_history(inter.author.id, limit=15)
        buf = await asyncio.to_thread(
            wrender.render_rewards,
            inter.author.id, inter.author.display_name,
            stats, total, hold, history,
        )
        fname = f"adv_rewards_{inter.author.id}.png"

    if not buf:
        return None, None, None

    file = disnake.File(buf, filename=fname)

    embeds = []
    pillow_embed = disnake.Embed(color=6776679)
    pillow_embed.set_image(url=f"attachment://{fname}")
    embeds.append(pillow_embed)

    if screen == "link":
        url = link["invite_url"] if link else "—"
        link_embed = disnake.Embed(
            title="📨 Твоя реферальная ссылка",
            description=(
                f"> Скопируй и делись:\n"
                f"```\n{url}\n```\n"
                f"> Все приглашения по ней считаются автоматически."
            ),
            color=6776679,
        )
        link_embed.set_image(url=IMG_STRIPE)
        embeds.append(link_embed)

    view = AdvertiserActionsView(screen)
    return embeds, file, view


# ============================================================
# ПАНЕЛЬ В КАНАЛЕ (статичная, 3 кнопки gray)
# ============================================================
class AdvertiserPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=_L_LINK, style=ButtonStyle.gray,
        custom_id="adv_panel:link", emoji=EMOJI_LINK, row=0,
    )
    async def _link(self, button, inter):
        await _open_ephemeral(inter, "link")

    @disnake.ui.button(
        label=_L_TOP, style=ButtonStyle.gray,
        custom_id="adv_panel:top", emoji=EMOJI_TOP, row=0,
    )
    async def _top(self, button, inter):
        await _open_ephemeral(inter, "top")

    @disnake.ui.button(
        label=_L_REWARDS, style=ButtonStyle.gray,
        custom_id="adv_panel:rewards", emoji=EMOJI_REWARDS, row=0,
    )
    async def _rewards(self, button, inter):
        await _open_ephemeral(inter, "rewards")


# ============================================================
# КНОПКИ ВНУТРИ EPHEMERAL (заменяют контент)
# ============================================================
class AdvertiserActionsView(View):
    def __init__(self, current="link"):
        super().__init__(timeout=300)
        self.current = current

    @disnake.ui.button(
        label=_L_LINK, style=ButtonStyle.gray,
        custom_id="adv_act:link", emoji=EMOJI_LINK, row=0,
    )
    async def _link(self, button, inter):
        if self.current == "link":
            return await inter.response.defer()
        await _switch(inter, "link")

    @disnake.ui.button(
        label=_L_TOP, style=ButtonStyle.gray,
        custom_id="adv_act:top", emoji=EMOJI_TOP, row=0,
    )
    async def _top(self, button, inter):
        if self.current == "top":
            return await inter.response.defer()
        await _switch(inter, "top")

    @disnake.ui.button(
        label=_L_REWARDS, style=ButtonStyle.gray,
        custom_id="adv_act:rewards", emoji=EMOJI_REWARDS, row=0,
    )
    async def _rewards(self, button, inter):
        if self.current == "rewards":
            return await inter.response.defer()
        await _switch(inter, "rewards")


# ============================================================
# ОБРАБОТЧИКИ
# ============================================================
async def _open_ephemeral(inter, screen):
    """Первое нажатие из панели → ephemeral сообщение."""
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    embeds, file, view = await _build_payload(inter, screen)
    if not embeds:
        try:
            await inter.followup.send("❌ Ошибка рендера", ephemeral=True)
        except Exception:
            pass
        return

    try:
        await inter.followup.send(
            embeds=embeds, file=file, view=view, ephemeral=True,
        )
    except Exception as e:
        logger.exception(f"_open_ephemeral: {e}")


async def _switch(inter, screen):
    """Переключение внутри ephemeral → заменяем сообщение."""
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    embeds, file, view = await _build_payload(inter, screen)
    if not embeds:
        return

    try:
        await inter.edit_original_response(
            embeds=embeds, file=file, attachments=[], view=view,
        )
    except Exception as e:
        logger.exception(f"_switch: {e}")
