# -*- coding: utf-8 -*-
"""Кнопки инвайт-панели. Работают локально, заменяют контент."""
import io
import asyncio
import time
from datetime import datetime, timezone

import disnake
from disnake import ButtonStyle, PartialEmoji
from disnake.ui import View, Button

from core.utils import logger, load_json, ADD_DIR, CONFIG
from work import core as wcore
from work import render as wrender


# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _el(text, total):
    text = text.strip()
    if len(text) >= total:
        return text[:total]
    pad = total - len(text)
    left = pad // 2
    right = pad - left
    return f"\u3164"*left + text + "\u3164"*right


_ADV_BTN_TOTAL = 46


def _adv_labels(labels):
    base = sum(len(s) for s in labels)
    extra = max(0, _ADV_BTN_TOTAL - base)
    n = len(labels)
    if n == 0: return labels
    per = extra // n
    rem = extra % n
    return [
        f"\u3164"*((per + (1 if i < rem else 0))//2)
        + s
        + "\u3164"*((per + (1 if i < rem else 0)) - (per + (1 if i < rem else 0))//2)
        for i, s in enumerate(labels)
    ]


_L_LINK, _L_TOP, _L_REWARDS = _adv_labels([
    "Получить ссылку", "Общий топ", "Мои награды",
])


EMOJI_LINK = PartialEmoji(name="Oplacheno", id=1539657164778512496)
EMOJI_TOP  = PartialEmoji(name="prize",     id=1539657202170859561)
EMOJI_REW  = PartialEmoji(name="gid1",      id=1555654337953267794)


def build_panel_embeds():
    """Читает work/invite.json → список эмбедов."""
    path = f"{ADD_DIR}/../work/invite.json"
    data = load_json(path, {})
    if not data or "embeds" not in data:
        from core.utils import logger as lg
        lg.warning("work/invite.json не найден или пуст")
        e = disnake.Embed(
            title="📨 Инвайт-панель",
            description="> Жми кнопки ниже.",
            color=6776679,
        )
        return [e]
    return [disnake.Embed.from_dict(e) for e in data["embeds"]]


# ============================================================
# РЕНДЕР ЭКРАНА
# ============================================================
async def _render_screen(user_id, username, screen: str):
    """Возвращает (buf, filename) для нужного экрана."""
    if screen == "link":
        link = wcore.get_advertiser_link(user_id)
        stats = wcore.get_advertiser_stats(user_id)
        buf = await asyncio.to_thread(
            wrender.render_personal,
            user_id, username, stats,
            link["invite_url"] if link else None,
            link["created_at"] if link else None,
        )
        return buf, f"adv_personal_{user_id}.png"

    if screen == "top":
        stats = wcore.get_advertiser_stats(user_id)
        top_list = wcore.get_advertiser_top(limit=10)
        my_place = None
        my_diff_1 = None
        my_diff_3 = None
        for i, entry in enumerate(top_list, 1):
            if entry["advertiser_id"] == user_id:
                my_place = i
                break
        if top_list:
            my_diff_1 = max(top_list[0]["rewarded"] - stats["rewarded"], 0)
        if len(top_list) >= 3:
            my_diff_3 = max(top_list[2]["rewarded"] - stats["rewarded"], 0)

        buf = await asyncio.to_thread(
            wrender.render_top,
            user_id, username, stats, my_place, my_diff_1, my_diff_3, top_list,
        )
        return buf, f"adv_top_{user_id}.png"

    if screen == "rewards":
        stats = wcore.get_advertiser_stats(user_id)
        total = wcore.get_total_rewarded_dc(user_id)
        hold = wcore.get_hold_dc(user_id)
        history = wcore.get_reward_history(user_id, limit=15)
        buf = await asyncio.to_thread(
            wrender.render_rewards,
            user_id, username, stats, total, hold, history,
        )
        return buf, f"adv_rewards_{user_id}.png"

    return None, None


async def _send_or_edit(inter, screen: str, view, ephemeral_first: bool):
    """
    ephemeral_first=True → это первое нажатие из панели (send_message).
    ephemeral_first=False → это навигация внутри ephemeral (edit_original_response).
    """
    if screen == "link":
        # Генерим/получаем ссылку
        link = await wcore.ensure_advertiser_link(inter.bot, inter.author.id)
        if not link:
            return await inter.response.send_message(
                "❌ Не удалось создать ссылку. Проверь, что канал "
                "REF_INVITE_CHANNEL_ID существует.",
                ephemeral=True,
            )

    buf, fname = await _render_screen(inter.author.id, inter.author.display_name, screen)
    if not buf:
        return await inter.response.send_message("❌ Ошибка рендера", ephemeral=True)

    file = disnake.File(buf, filename=fname)
    embed = disnake.Embed(color=6776679)
    embed.set_image(url=f"attachment://{fname}")

    kwargs = dict(embed=embed, file=file, attachments=[], view=view)

    if ephemeral_first:
        await inter.response.send_message(ephemeral=True, **kwargs)
    else:
        await inter.edit_original_response(**kwargs)


# ============================================================
# ПАНЕЛЬ (в канале)
# ============================================================
class AdvertiserPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=_L_LINK, style=ButtonStyle.primary,
        custom_id="adv_panel:link", emoji=EMOJI_LINK, row=0,
    )
    async def _link(self, button, inter):
        await inter.response.defer(ephemeral=True)
        await _send_or_edit(inter, "link", AdvertiserActionsView("link"), False)

    @disnake.ui.button(
        label=_L_TOP, style=ButtonStyle.gray,
        custom_id="adv_panel:top", emoji=EMOJI_TOP, row=0,
    )
    async def _top(self, button, inter):
        await inter.response.defer(ephemeral=True)
        await _send_or_edit(inter, "top", AdvertiserActionsView("top"), False)

    @disnake.ui.button(
        label=_L_REWARDS, style=ButtonStyle.success,
        custom_id="adv_panel:rewards", emoji=EMOJI_REW, row=0,
    )
    async def _rewards(self, button, inter):
        await inter.response.defer(ephemeral=True)
        await _send_or_edit(inter, "rewards", AdvertiserActionsView("rewards"), False)


# ============================================================
# КНОПКИ ВНУТРИ EPHEMERAL
# ============================================================
class AdvertiserActionsView(View):
    def __init__(self, current: str = "link"):
        super().__init__(timeout=300)
        self.current = current

    @disnake.ui.button(
        label=_L_LINK, style=ButtonStyle.primary,
        custom_id="adv_act:link", emoji=EMOJI_LINK, row=0,
    )
    async def _link(self, button, inter):
        if self.current == "link":
            return await inter.response.defer()
        try: await inter.response.defer(ephemeral=True)
        except: pass
        await _send_or_edit(inter, "link", AdvertiserActionsView("link"), False)

    @disnake.ui.button(
        label=_L_TOP, style=ButtonStyle.gray,
        custom_id="adv_act:top", emoji=EMOJI_TOP, row=0,
    )
    async def _top(self, button, inter):
        if self.current == "top":
            return await inter.response.defer()
        try: await inter.response.defer(ephemeral=True)
        except: pass
        await _send_or_edit(inter, "top", AdvertiserActionsView("top"), False)

    @disnake.ui.button(
        label=_L_REWARDS, style=ButtonStyle.success,
        custom_id="adv_act:rewards", emoji=EMOJI_REW, row=0,
    )
    async def _rewards(self, button, inter):
        if self.current == "rewards":
            return await inter.response.defer()
        try: await inter.response.defer(ephemeral=True)
        except: pass
        await _send_or_edit(inter, "rewards", AdvertiserActionsView("rewards"), False)
