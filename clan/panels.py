# clan/panels.py
# -*- coding: utf-8 -*-
"""UI и таски клановой лиги. Все игровые экраны — через clan/render.py."""
import os
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

import disnake
from disnake import ButtonStyle, SelectOption, PartialEmoji
from disnake.ui import Button, Select, View

from core.utils import (
    CONFIG, logger, db, cur, load_json, save_json, log_discord,
)

from clan.core import (
    CLANS_DATA, CLUB_ROLE_ID, MIN_BALANCE,
    get_clan, get_all_clans, get_user_clan, assign_user_to_clan,
    get_clan_bank, get_clan_top, get_clan_members_count,
    get_user_contribution, get_recent_contributions_all,
    get_current_cycle, start_new_cycle, close_cycle_and_pay,
    make_progress_bar, clan_status_emoji,
    MSK, EMBEDS_DIR, IMG_STRIPE, REPORT_DM_USER_ID,
    get_season_title, get_season_name,
    DAILY_CLAN_LIMIT, _get_daily_contributed,
)

from clan.quests import (
    format_quests_embed, reset_daily_quests, reset_weekly_quests,
    on_panel_click_quest_hook,
)

from clan.cases_views import CasesSelectView, show_cases_screen

from clan.render import (
    render_clan_deposits,
    render_clan_last,
    render_clan_total_pool,
    render_clan_bank,
    render_clan_top,
    render_clan_howto,
)

P = "\u3164"

# ============================================================
# ЭМОДЗИ
# ============================================================
EMOJI_BANK   = PartialEmoji.from_str("<:1d1ds:1552730624572391584>")
EMOJI_TOP    = PartialEmoji.from_str("<:d1edf:1552730601155596348>")
EMOJI_HOWTO  = PartialEmoji.from_str("<:infor:1552730394795970621>")

EMOJI_QUESTS = PartialEmoji.from_str("<:d11d1:1552732333394763776>")
EMOJI_SLOTS  = PartialEmoji.from_str("<:game1:1552732315606589460>")
EMOJI_CASES  = PartialEmoji(name="S21", id=1552381035092648026) # Новая иконка для кейсов

EMOJI_DEPOSITS = PartialEmoji.from_str("<:Otziv:1541808692314243172>")
EMOJI_LAST     = PartialEmoji.from_str("<:warn:1552325395171381388>")
EMOJI_TOTAL    = PartialEmoji.from_str("<:Politic:1539657020695650384>")

EMOJI_ROULETTE  = "<:ropulet:1550563615675781282>"
EMOJI_BLACKJACK = "<:joke:1551288467659428020>"
EMOJI_COINFLIP  = "<:coins:1539649259245408340>"

IMG_SLOTS_TOP = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
                 "1552731239398768711/image.png?ex=6ab6ad27&is=6ab55ba7&"
                 "hm=60031b3eef30f7e7448875045e47612b869469755e50801f3819ae2dfbbb8913&")

IMG_SEASON_TOP = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
                  "1556729820300316823/image.png?backend=b2&ex=6ac5391f&is=6ac3e79f&"
                  "hm=0c9118861dcf05bc1ee7902240a762035c086b1bbd67ed2f23d1a59ad1949f0f&")

IMG_NEWS_TOP = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
                "1556729818517741649/image.png?backend=b2&ex=6ac5391f&is=6ac3e79f&"
                "hm=700cd6018aa1de7b77e8c0eafd8e2cb5d2534b7f280e6fa5bd90e6a83471bf46&")

IMG_ADMIN_TOP = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
                 "1553238615444815963/image.png?ex=6ab885af&is=6ab7342f&"
                 "hm=cd565ec3073866b96954abcb9ef14bd41b860d9f087492ebdf6c200eecbcfdc2&")

# ============================================================
# ХЕЛПЕРЫ
# ============================================================
async def _send_clan_screen(inter: disnake.MessageInteraction, buf, fname: str):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    try:
        file = disnake.File(buf, filename=fname)
        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{fname}")
        await inter.followup.send(embed=embed, file=file, ephemeral=True)
    except Exception as e:
        logger.exception(f"_send_clan_screen: {e}")
        try:
            await inter.followup.send(
                content=f"❌ Ошибка рендера: `{str(e)[:200]}`",
                ephemeral=True,
            )
        except Exception:
            pass


def _time_ago(ts: int) -> str:
    try:
        sec = int(datetime.now(timezone.utc).timestamp()) - int(ts)
    except Exception:
        return "—"
    if sec < 60: return "только что"
    if sec < 3600: return f"{sec // 60} мин назад"
    if sec < 86400: return f"{sec // 3600} ч назад"
    if sec < 86400 * 2: return "вчера"
    return f"{sec // 86400} дн назад"


async def _get_balance(user_id: int) -> int:
    try:
        from modules.dc import get_user_balance
        return await get_user_balance(user_id)
    except Exception:
        try:
            from core.utils import get_dc_cache
            return get_dc_cache(user_id).get("balance", 0)
        except Exception:
            return 0


def _guild_name(inter: disnake.MessageInteraction, user_id: int) -> str:
    try:
        m = inter.guild.get_member(user_id) if inter.guild else None
        if m:
            return m.display_name
    except Exception:
        pass
    return str(user_id)


# ============================================================
# 1. КОПИЛКА — СТАТИЧНЫЙ ЭМБЕД
# ============================================================
def _build_static_pool_embeds() -> List[disnake.Embed]:
    data = load_json(os.path.join(EMBEDS_DIR, "clan_pool.json"), {})
    embeds = []
    for e in data.get("embeds", []):
        embeds.append(disnake.Embed.from_dict(e))
    if not embeds:
        embeds = [disnake.Embed(color=6776679)]
    return embeds

# ============================================================
# 2. СЕЗОН — СТАТИЧНЫЙ ЭМБЕД
# ============================================================
def _build_season_static_embeds() -> List[disnake.Embed]:
    cycle = get_current_cycle()
    season_num = cycle["number"] if cycle else 1

    if cycle:
        title = f"Клубная лига — {get_season_title(season_num)}!"
    else:
        title = f"Клубная лига — {get_season_title(1)}!"

    e1 = disnake.Embed(color=6776679)
    e1.set_image(url=IMG_SEASON_TOP)

    if cycle:
        ends_ts = cycle["ends_at"]
        desc = (
            f"> В данный момент, участвуют 3 клана — "
            f"<@&1552707675257831525> | <@&1552707025723465838> | <@&1551280425312194650>.\n"
            f"> О каждом связующем — можно узнать по кнопкам ниже.\n\n"
            f"**Конец сезона:** <t:{ends_ts}:f>"
        )
    else:
        desc = (
            f"> В данный момент, участвуют 3 клана — "
            f"<@&1552707675257831525> | <@&1552707025723465838> | <@&1551280425312194650>.\n"
            f"> О каждом связующем — можно узнать по кнопкам ниже.\n\n"
            f"**Конец сезона:** — (сезон ещё не запущен)"
        )

    e2 = disnake.Embed(title=title, description=desc, color=6776679)
    e2.set_image(url=IMG_STRIPE)

    return [e1, e2]

# ============================================================
# 3. ИГРЫ — СТАТИЧНЫЙ ЭМБЕД
# ============================================================
def _build_games_embeds() -> List[disnake.Embed]:
    data = load_json(os.path.join(EMBEDS_DIR, "clan_games.json"), {})
    embeds = []
    for e in data.get("embeds", []):
        embeds.append(disnake.Embed.from_dict(e))
    if not embeds:
        embeds = [disnake.Embed(color=6776679)]
    return embeds

# ============================================================
# 4. КНОПКИ КОПИЛКИ
# ============================================================
class ClanPoolView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=f"{P}Банк клана{P}",
        style=ButtonStyle.gray,
        custom_id="clan_pool:bank",
        emoji=EMOJI_BANK
    )
    async def bank(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)

        user_clan = get_user_clan(inter.author.id)
        if not user_clan:
            return await inter.response.send_message(
                "❌ Ты не в клане. Получи роль покупателя — и получишь клан.",
                ephemeral=True,
            )

        balance = await _get_balance(inter.author.id)
        bank_sum = get_clan_bank(user_clan["id"])
        members = get_clan_members_count(user_clan["id"])
        my_contrib = get_user_contribution(inter.author.id)

        all_top = get_clan_top(user_clan["id"], limit=1000)
        my_rank = None
        for i, t in enumerate(all_top, 1):
            if t["user_id"] == inter.author.id:
                my_rank = i
                break

        to_top3 = 0
        if all_top and len(all_top) >= 3 and my_rank and my_rank > 3:
            to_top3 = max(all_top[2]["total"] - my_contrib + 1, 0)

        top3 = []
        for t in all_top[:3]:
            top3.append({
                "user_id": t["user_id"],
                "user_name": _guild_name(inter, t["user_id"]),
                "total": t["total"],
            })

        try:
            buf = render_clan_bank(
                inter.author.id, balance, user_clan,
                bank_sum, members, my_contrib, my_rank, to_top3, top3,
            )
        except Exception as e:
            logger.exception(f"render_clan_bank: {e}")
            return await inter.response.send_message(
                f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True
            )

        await _send_clan_screen(inter, buf, f"clan_bank_{inter.author.id}.png")

    @disnake.ui.button(
        label=f"{P}Топ{P}",
        style=ButtonStyle.gray,
        custom_id="clan_pool:top",
        emoji=EMOJI_TOP
    )
    async def top(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)

        user_clan = get_user_clan(inter.author.id)
        if not user_clan:
            return await inter.response.send_message("❌ Ты не в клане.", ephemeral=True)

        balance = await _get_balance(inter.author.id)
        my_contrib = get_user_contribution(inter.author.id)
        top_raw = get_clan_top(user_clan["id"], limit=10)

        my_rank = None
        to_first = 0
        for i, t in enumerate(top_raw, 1):
            if t["user_id"] == inter.author.id:
                my_rank = i
                break
        if top_raw and my_rank and my_rank > 1:
            to_first = max(top_raw[0]["total"] - my_contrib + 1, 0)

        top_list = []
        for t in top_raw:
            top_list.append({
                "user_id": t["user_id"],
                "user_name": _guild_name(inter, t["user_id"]),
                "total": t["total"],
            })

        try:
            buf = render_clan_top(inter.author.id, balance, user_clan, top_list, my_rank, my_contrib, to_first)
        except Exception as e:
            logger.exception(f"render_clan_top: {e}")
            return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)

        await _send_clan_screen(inter, buf, f"clan_top_{inter.author.id}.png")

    @disnake.ui.button(
        label=f"{P}Как это работает{P}",
        style=ButtonStyle.gray,
        custom_id="clan_pool:howto",
        emoji=EMOJI_HOWTO
    )
    async def howto(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        balance = await _get_balance(inter.author.id)
        try:
            buf = render_clan_howto(inter.author.id, balance)
        except Exception as e:
            logger.exception(f"render_clan_howto: {e}")
            return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
        await _send_clan_screen(inter, buf, f"clan_howto_{inter.author.id}.png")


# ============================================================
# 5. КНОПКИ СЕЗОНА
# ============================================================
class ClanSeasonView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=f"{P}Вклады{P}",
        style=ButtonStyle.gray,
        custom_id="clan_season:deposits",
        emoji=EMOJI_DEPOSITS
    )
    async def deposits(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        balance = await _get_balance(inter.author.id)

        clans_data = []
        for c in get_all_clans():
            bank = get_clan_bank(c["id"])
            members = get_clan_members_count(c["id"])
            top = get_clan_top(c["id"], limit=1)
            leader_id = top[0]["user_id"] if top else None
            leader = f"@{_guild_name(inter, leader_id)}" if leader_id else "—"
            clans_data.append({"clan": c, "bank": bank, "members": members, "leader": leader})

        try:
            buf = render_clan_deposits(inter.author.id, balance, clans_data)
        except Exception as e:
            logger.exception(f"render_clan_deposits: {e}")
            return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)

        await _send_clan_screen(inter, buf, f"clan_dep_{inter.author.id}.png")

    @disnake.ui.button(
        label=f"{P}Последнее{P}",
        style=ButtonStyle.gray,
        custom_id="clan_season:last",
        emoji=EMOJI_LAST
    )
    async def last(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        balance = await _get_balance(inter.author.id)
        recent = get_recent_contributions_all(limit=8)

        feed = []
        for r in recent:
            clan = get_clan(r["clan_id"])
            reason = r.get("reason", "") or ""
            tag = reason.split(":")[0][:16].upper() if reason else "ВКЛАД"
            feed.append({
                "user_id": r["user_id"], "user_name": _guild_name(inter, r["user_id"]),
                "clan": clan, "amount": r["amount"], "reason": reason,
                "time_str": _time_ago(r["ts"]), "tag": tag,
            })

        today_count = len(feed)
        today_sum = sum(f["amount"] for f in feed)
        daily_used = _get_daily_contributed(inter.author.id)

        try:
            buf = render_clan_last(
                inter.author.id, balance, feed, today_count=today_count,
                today_sum=today_sum, daily_limit=DAILY_CLAN_LIMIT, daily_used=daily_used,
            )
        except Exception as e:
            logger.exception(f"render_clan_last: {e}")
            return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)

        await _send_clan_screen(inter, buf, f"clan_last_{inter.author.id}.png")

    @disnake.ui.button(
        label=f"{P}Общий пул{P}",
        style=ButtonStyle.gray,
        custom_id="clan_season:total",
        emoji=EMOJI_TOTAL
    )
    async def total(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        balance = await _get_balance(inter.author.id)

        clans_data = []
        total_bank = 0
        total_members = 0
        top_clan = None
        top_bank = -1

        for c in get_all_clans():
            bank = get_clan_bank(c["id"])
            members = get_clan_members_count(c["id"])
            clans_data.append({"clan": c, "bank": bank})
            total_bank += bank
            total_members += members
            if bank > top_bank:
                top_bank = bank
                top_clan = c

        try:
            buf = render_clan_total_pool(inter.author.id, balance, total_bank, clans_data, total_members, top_clan)
        except Exception as e:
            logger.exception(f"render_clan_total_pool: {e}")
            return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)

        await _send_clan_screen(inter, buf, f"clan_pool_{inter.author.id}.png")


# ============================================================
# 6. КНОПКИ ИГР
# ============================================================
class ClanGamesView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=f"{P}Квесты для копилки{P}",
        style=ButtonStyle.gray,
        custom_id="clan_games:quests",
        emoji=EMOJI_QUESTS
    )
    async def quests(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)

        from clan.quests import build_quests_embeds
        try:
            embeds, file = build_quests_embeds(inter.author.id)
        except Exception as e:
            logger.exception(f"build_quests_embeds: {e}")
            return await inter.response.send_message(f"❌ Ошибка: `{str(e)[:200]}`", ephemeral=True)

        if file:
            await inter.response.send_message(embeds=embeds, file=file, ephemeral=True)
        else:
            await inter.response.send_message(embeds=embeds, ephemeral=True)

    @disnake.ui.button(
        label=f"{P}Игровые автоматы{P}",
        style=ButtonStyle.gray,
        custom_id="clan_games:slots",
        emoji=EMOJI_SLOTS
    )
    async def slots(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)

        e1 = disnake.Embed(color=6776679)
        e1.set_image(url=IMG_SLOTS_TOP)

        e2 = disnake.Embed(
            title="Игровые автоматы DC",
            description=(
                "> Выбери игру, чтобы сыграть.\n"
                "> Все выигрыши — до 100 DC вся сумма в копилку, больше — 40%."
            ),
            color=6776679
        )
        e2.set_image(url=IMG_STRIPE)

        view = View(timeout=300)
        select = Select(
            placeholder="В какую игру хочешь сыграть?",
            options=[
                SelectOption(label="Рулетка", description="Поставь Diamond Coins на удачу!", emoji=EMOJI_ROULETTE, value="roulette"),
                SelectOption(label="Блэкджек", description="21 очко — классика казино!", emoji=EMOJI_BLACKJACK, value="blackjack"),
                SelectOption(label="Монетка", description="Орёл или решка? Быстрая игра!", emoji=EMOJI_COINFLIP, value="coinflip"),
                SelectOption(label="Кейсы", description="Испытай удачу и забери ценный приз", emoji=EMOJI_CASES, value="cases"), # НОВОЕ
            ],
            custom_id="clan_games_select"
        )
        select.callback = _clan_games_select_callback
        view.add_item(select)
        await inter.response.send_message(embeds=[e1, e2], view=view, ephemeral=True)

    @disnake.ui.button(
        label=f"{P}Кейсы{P}",
        style=ButtonStyle.gray,
        custom_id="clan_games:cases",
        emoji=EMOJI_CASES
    )
    async def cases_button(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        await show
