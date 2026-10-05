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
    """Отправка эфемерной картинки — не трогает исходное сообщение."""
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
    if sec < 60:
        return "только что"
    if sec < 3600:
        return f"{sec // 60} мин назад"
    if sec < 86400:
        return f"{sec // 3600} ч назад"
    if sec < 86400 * 2:
        return "вчера"
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

    e2 = disnake.Embed(
        title=title,
        description=desc,
        color=6776679
    )
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

        await _send_clan_screen(
            inter, buf, f"clan_bank_{inter.author.id}.png"
        )

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
            return await inter.response.send_message(
                "❌ Ты не в клане.", ephemeral=True
            )

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
            buf = render_clan_top(
                inter.author.id, balance, user_clan,
                top_list, my_rank, my_contrib, to_first,
            )
        except Exception as e:
            logger.exception(f"render_clan_top: {e}")
            return await inter.response.send_message(
                f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True
            )

        await _send_clan_screen(
            inter, buf, f"clan_top_{inter.author.id}.png"
        )

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
            return await inter.response.send_message(
                f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True
            )

        await _send_clan_screen(
            inter, buf, f"clan_howto_{inter.author.id}.png"
        )


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
            clans_data.append({
                "clan": c,
                "bank": bank,
                "members": members,
                "leader": leader,
            })

        try:
            buf = render_clan_deposits(inter.author.id, balance, clans_data)
        except Exception as e:
            logger.exception(f"render_clan_deposits: {e}")
            return await inter.response.send_message(
                f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True
            )

        await _send_clan_screen(
            inter, buf, f"clan_dep_{inter.author.id}.png"
        )

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
                "user_id": r["user_id"],
                "user_name": _guild_name(inter, r["user_id"]),
                "clan": clan,
                "amount": r["amount"],
                "reason": reason,
                "time_str": _time_ago(r["ts"]),
                "tag": tag,
            })

        today_count = len(feed)
        today_sum = sum(f["amount"] for f in feed)
        daily_used = _get_daily_contributed(inter.author.id)

        try:
            buf = render_clan_last(
                inter.author.id, balance, feed,
                today_count=today_count,
                today_sum=today_sum,
                daily_limit=DAILY_CLAN_LIMIT,
                daily_used=daily_used,
            )
        except Exception as e:
            logger.exception(f"render_clan_last: {e}")
            return await inter.response.send_message(
                f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True
            )

        await _send_clan_screen(
            inter, buf, f"clan_last_{inter.author.id}.png"
        )

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
            buf = render_clan_total_pool(
                inter.author.id, balance,
                total_bank, clans_data, total_members, top_clan,
            )
        except Exception as e:
            logger.exception(f"render_clan_total_pool: {e}")
            return await inter.response.send_message(
                f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True
            )

        await _send_clan_screen(
            inter, buf, f"clan_pool_{inter.author.id}.png"
        )


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
            return await inter.response.send_message(
                f"❌ Ошибка: `{str(e)[:200]}`", ephemeral=True
            )

        if file:
            await inter.response.send_message(
                embeds=embeds, file=file, ephemeral=True
            )
        else:
            await inter.response.send_message(
                embeds=embeds, ephemeral=True
            )

    @disnake.ui.button(
        label=f"{P}Игровые автоматы DC{P}",
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
                SelectOption(
                    label="Рулетка",
                    description="Поставь Diamond Coins на удачу!",
                    emoji=EMOJI_ROULETTE,
                    value="roulette"
                ),
                SelectOption(
                    label="Блэкджек",
                    description="21 очко — классика казино!",
                    emoji=EMOJI_BLACKJACK,
                    value="blackjack"
                ),
                SelectOption(
                    label="Монетка",
                    description="Орёл или решка? Быстрая игра!",
                    emoji=EMOJI_COINFLIP,
                    value="coinflip"
                ),
            ],
            custom_id="clan_games_select"
        )
        select.callback = _clan_games_select_callback
        view.add_item(select)
        await inter.response.send_message(
            embeds=[e1, e2], view=view, ephemeral=True
        )


async def _clan_games_select_callback(inter: disnake.MessageInteraction):
    value = inter.data.values[0]
    from modules.actions import RouletteModal, BlackjackBetModal, CoinflipBetModal

    if value == "roulette":
        await inter.response.send_modal(RouletteModal())
    elif value == "blackjack":
        await inter.response.send_modal(BlackjackBetModal())
    elif value == "coinflip":
        await inter.response.send_modal(CoinflipBetModal())


# ============================================================
# 7. ОТПРАВКА ПАНЕЛЕЙ
# ============================================================
async def send_clan_pool_panel(bot):
    ch = bot.get_channel(CONFIG["CLAN_POOL_CHANNEL_ID"])
    if not ch:
        try:
            ch = await bot.fetch_channel(CONFIG["CLAN_POOL_CHANNEL_ID"])
        except Exception:
            ch = None
    if not ch:
        logger.warning("Clan pool channel not found")
        return

    async for msg in ch.history(limit=50):
        if msg.author == bot.user:
            try:
                await msg.delete()
            except Exception:
                pass

    embeds = _build_static_pool_embeds()
    await ch.send(embeds=embeds, view=ClanPoolView())
    logger.info("Клан-копилка: панель отправлена")


async def send_clan_season_panel(bot):
    ch = bot.get_channel(CONFIG["CLAN_SEASON_CHANNEL_ID"])
    if not ch:
        try:
            ch = await bot.fetch_channel(CONFIG["CLAN_SEASON_CHANNEL_ID"])
        except Exception:
            ch = None
    if not ch:
        logger.warning("Clan season channel not found")
        return

    async for msg in ch.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except Exception:
                pass
            break

    embeds = _build_season_static_embeds()
    await ch.send(embeds=embeds, view=ClanSeasonView())
    logger.info("Клан-сезон: панель отправлена")


async def send_clan_games_panel(bot):
    ch = bot.get_channel(CONFIG["CLAN_GAMES_CHANNEL_ID"])
    if not ch:
        try:
            ch = await bot.fetch_channel(CONFIG["CLAN_GAMES_CHANNEL_ID"])
        except Exception:
            ch = None
    if not ch:
        logger.warning("Clan games channel not found")
        return

    async for msg in ch.history(limit=50):
        if msg.author == bot.user:
            try:
                await msg.delete()
            except Exception:
                pass

    embeds = _build_games_embeds()
    await ch.send(embeds=embeds, view=ClanGamesView())
    logger.info("Клан-игры: панель отправлена")


async def update_clan_pool_embed(bot):
    await send_clan_pool_panel(bot)
    await send_clan_season_panel(bot)
    await send_clan_games_panel(bot)


# ============================================================
# 8. НОВОСТИ
# ============================================================
async def _post_clan_news(bot, title: str, news: str, description: str):
    try:
        ch = bot.get_channel(CONFIG["CLAN_NEWS_CHANNEL_ID"])
        if not ch:
            ch = await bot.fetch_channel(CONFIG["CLAN_NEWS_CHANNEL_ID"])
        if not ch:
            logger.warning("Clan news channel not found")
            return

        e1 = disnake.Embed(color=6776679)
        e1.set_image(url=IMG_NEWS_TOP)

        e2 = disnake.Embed(
            title=title,
            description=f"> Новость: {news}\n\n> Описание: {description}\n",
            color=6776679
        )
        e2.set_image(url=IMG_STRIPE)

        await ch.send(embeds=[e1, e2])
        logger.info(f"Клан-новость отправлена: {title}")
    except Exception as e:
        logger.exception(f"_post_clan_news: {e}")


async def post_news_season_start(bot):
    cycle = get_current_cycle()
    if not cycle:
        return
    season_title = get_season_title(cycle["number"])
    news = f"Стартует новый сезон — **{season_title}**."
    desc = (
        f"{season_title} официально открыт. "
        f"Копилки кланов обнулены, отсчёт пошёл. "
        f"Участники могут зарабатывать DC, выполнять квесты и вносить вклад в банк клана. "
        f"Финал — **28 числа в 20:00 МСК**."
    )
    await _post_clan_news(bot, f"Старт — {season_title}", news, desc)


async def post_news_season_3days(bot):
    cycle = get_current_cycle()
    if not cycle:
        return
    season_name = get_season_name(cycle["number"])
    news = f"До финала сезона «{season_name}» осталось 3 дня."
    desc = (
        f"Самое время увеличить свой вклад в банк клана. "
        f"Топ-3 участника получат бонусы ×3.00 / ×2.00 / ×1.50. "
        f"Финал — **28 числа в 20:00 МСК**."
    )
    await _post_clan_news(bot, "До финала клубной лиги 3 дня", news, desc)


async def post_news_season_1hour(bot):
    cycle = get_current_cycle()
    if not cycle:
        return
    season_name = get_season_name(cycle["number"])
    news = f"Остался последний час до финала сезона «{season_name}»."
    desc = (
        f"Успей внести последний вклад в свой клан. "
        f"После 20:00 МСК банк будет распределён между участниками. "
        f"Топ-3 забирают бонусы ×3.00 / ×2.00 / ×1.50."
    )
    await _post_clan_news(bot, "Час до финала клубной лиги", news, desc)


async def post_news_season_end(bot, report: dict):
    cycle = report["cycle"]
    season_title = get_season_title(cycle["number"])
    total = sum(c["bank"] for c in report["clans"])
    top_clan = max(report["clans"], key=lambda x: x["bank"]) if report["clans"] else None

    news = f"{season_title} официально завершён."
    winner_line = ""
    if top_clan:
        winner_line = (
            f"Победитель сезона — "
            f"{top_clan['clan']['emoji']} **{top_clan['clan']['name'].upper()}** "
            f"с банком {top_clan['bank']} DC. "
        )
    desc = (
        winner_line +
        f"Общий пул всех кланов составил {total} DC. "
        f"Выплаты произведены всем участникам, "
        f"топ-3 по вкладу получили повышенные коэффициенты. "
        f"Новый сезон стартует через 5 минут."
    )
    await _post_clan_news(bot, f"{season_title} завершён", news, desc)


async def post_news_weekly(bot):
    cycle = get_current_cycle()
    if not cycle:
        return

    total_bank = 0
    top_clan = None
    top_bank = -1
    for c in get_all_clans():
        bank = get_clan_bank(c["id"])
        total_bank += bank
        if bank > top_bank:
            top_bank = bank
            top_clan = c

    season_name = get_season_name(cycle["number"])
    news = f"Еженедельный отчёт по сезону «{season_name}»."
    if top_clan:
        desc = (
            f"В лидерах — {top_clan['emoji']} **{top_clan['name'].upper()}** "
            f"с банком {top_bank} DC. "
            f"Общий пул всех кланов составляет {total_bank} DC. "
            f"До конца сезона осталось совсем немного — успей поддержать свой клан."
        )
    else:
        desc = f"Общий пул кланов: {total_bank} DC. Успей поддержать свой клан."
    await _post_clan_news(bot, "Итоги недели в клубной лиге", news, desc)


# ============================================================
# 9. АДМИН-ПАНЕЛЬ
# ============================================================
class ClanAdminSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            SelectOption(
                label="・Обновление кланов",
                description="Роли + чистка по условиям + распределение + панели",
                emoji="🔄",
                value="update_clans"
            ),
            SelectOption(
                label="・Пересобрать кланы (рандом)",
                description="СНЯТЬ ВСЕХ из кланов и раскидать заново случайно",
                emoji="🎲",
                value="rebuild_clans"
            ),
            SelectOption(
                label="・Пересчитать достижения",
                description="Прогнать всех юзеров и выдать недостающие достижения",
                emoji="🏆",
                value="recalc_ach"
            ),
            SelectOption(
                label="・Обновить панели",
                description="Пересобрать эмбеды копилки и сезона",
                emoji="🖼",
                value="refresh"
            ),
        ]
        super().__init__(
            placeholder="Выберите действие...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="clan_admin_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        if not _is_admin(inter):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)

        value = inter.data.values[0]

        await inter.response.defer(with_message=True, ephemeral=True)

        if value == "update_clans":
            await self._update_clans(inter)
        elif value == "rebuild_clans":
            await self._confirm_rebuild(inter)
        elif value == "recalc_ach":
            await self._recalc_ach(inter)
        elif value == "refresh":
            await update_clan_pool_embed(inter.bot)
            await inter.edit_original_response(content="✅ Панели обновлены.")

    async def _confirm_rebuild(self, inter: disnake.MessageInteraction):
        await inter.edit_original_response(
            content=(
                "⚠️ **Полная пересборка кланов**\n\n"
                "> Снимет роли кланов **у всех** и раскидает заново случайно.\n"
                "> Вклады за сезон переедут за людьми в их новые кланы.\n\n"
                "> Точно делаем?"
            ),
            view=ClanRebuildConfirmView()
        )

    async def _update_clans(self, inter: disnake.MessageInteraction):
        try:
            from clan.core import (
                recalculate_clan_league, MIN_BALANCE, INACTIVE_DAYS_LIMIT,
            )

            await inter.edit_original_response(
                content="⏳ Обновляю кланы: роли, чистка, распределение...\n"
                        "> Это может занять пару минут."
            )

            stats = await recalculate_clan_league(inter.guild)

            await update_clan_pool_embed(inter.bot)

            await inter.edit_original_response(
                content=(
                    f"✅ **Обновление кланов завершено**\n\n"
                    f"**Роли покупателей**\n"
                    f"> 🔍 Пересчитано (есть отзыв): **{stats['roles_checked']}**\n"
                    f"> ⚠️ Ошибок: **{stats['roles_errors']}**\n\n"
                    f"**Чистка кланов**\n"
                    f"> 📋 Условия (провалил любое — вон): баланс < {MIN_BALANCE} DC, "
                    f"нет роли покупателя, нет действий {INACTIVE_DAYS_LIMIT} дн.\n"
                    f"> 👀 Проверено участников: **{stats['members_checked']}**\n"
                    f"> 🚪 Исключено из клана: **{stats['removed']}**\n"
                    f"> 💸 Вкладов вычищено: **{stats.get('removed_dc', 0)} DC**\n"
                    f"> ⏳ Первый отсчёт активности: **{stats.get('seeded', 0)}**\n\n"
                    f"**Распределение**\n"
                    f"> ♻️ Возвращены снятые роли: **{stats.get('repaired', 0)}**\n"
                    f"> 🔄 Вклады перенесены в текущий клан: **{stats.get('moved', 0)}**\n"
                    f"> ✅ Выдан клан заново: **{stats['assigned']}**\n"
                    f"> 👥 Уже были в клане (роль на месте): **{stats['skipped']}**\n"
                    f"> ⛔ В жёстком исключении: **{stats['excluded']}**"
                )
            )
        except Exception as e:
            logger.exception(f"update_clans: {e}")
            await inter.edit_original_response(
                content=f"❌ Ошибка обновления кланов: `{str(e)[:300]}`"
            )

    async def _recalc_ach(self, inter: disnake.MessageInteraction):
        try:
            from clan.achievements import recalculate_all_achievements
            await inter.edit_original_response(
                content="⏳ Начинаю пересчёт достижений для всех юзеров...\n"
                        "> Это может занять несколько минут, всем получателям придут ЛС."
            )
            stats = await recalculate_all_achievements(inter.bot)
            await inter.edit_original_response(
                content=(
                    f"✅ **Пересчёт достижений завершён!**\n\n"
                    f"> **Проверено юзеров:** `{stats['checked']}`\n"
                    f"> **Ошибок:** `{stats['errors']}`\n\n"
                    f"> Всем получателям отправлены ЛС о новых достижениях. "
                    f"Теперь они отображаются в профиле."
                )
            )
        except Exception as e:
            logger.exception(f"recalc_ach: {e}")
            await inter.edit_original_response(
                content=f"❌ Ошибка пересчёта: `{str(e)[:300]}`"
            )


class ClanAdminView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ClanAdminSelect())


def _is_admin(inter: disnake.MessageInteraction) -> bool:
    from core.utils import has_admin_command_roles
    return has_admin_command_roles(inter.author)


# ============================================================
# 10. ПОДТВЕРЖДЕНИЕ ПОЛНОЙ ПЕРЕСБОРКИ
# ============================================================
class ClanRebuildConfirmView(View):
    def __init__(self):
        super().__init__(timeout=120)

    @disnake.ui.button(
        label="Да, снять всех и раскидать",
        style=ButtonStyle.danger,
        custom_id="clan_rebuild:yes",
        emoji="🎲",
    )
    async def confirm(self, button, inter: disnake.MessageInteraction):
        if not _is_admin(inter):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.defer(with_message=True, ephemeral=True)
        await _run_clan_rebuild(inter)

    @disnake.ui.button(
        label="Отмена",
        style=ButtonStyle.secondary,
        custom_id="clan_rebuild:no",
    )
    async def cancel(self, button, inter: disnake.MessageInteraction):
        await inter.response.edit_message(
            content="❌ Пересборка кланов отменена.", view=None
        )


async def _run_clan_rebuild(inter: disnake.MessageInteraction):
    try:
        from clan.core import rebuild_clans_random

        await inter.edit_original_response(
            content="🎲 Пересобираю кланы: снимаю всех и раскидываю заново...\n"
                    "> Может занять пару минут, не трогай панель.",
            view=None
        )

        stats = await rebuild_clans_random(inter.guild)

        await update_clan_pool_embed(inter.bot)

        dist_lines = "\n".join(
            f"> · {name}: **{count}**" for name, count in stats["distribution"].items()
        )

        await inter.edit_original_response(
            content=(
                f"🎲 **Кланы пересобраны с нуля**\n\n"
                f"**Снято**\n"
                f"> 🚪 Освобождено от кланов: **{stats['stripped']}** чел.\n"
                f"> ⚠️ Ошибок снятия: **{stats['strip_errors']}**\n\n"
                f"**Раскидано заново (случайно)**\n"
                f"> ✅ Получили клан: **{stats['assigned']}**\n"
                f"> 🚫 Не прошли условия: **{stats['skipped']}**\n"
                f"> ⚠️ Ошибок с ролями: **{stats['role_errors']}**\n\n"
                f"**Новая раскладка**\n{dist_lines}\n\n"
                f"> 🔄 Вклады перенесены: **{stats['moved']}** записей"
            ),
            view=None
        )
    except Exception as e:
        logger.exception(f"_run_clan_rebuild: {e}")
        await inter.edit_original_response(
            content=f"❌ Ошибка пересборки: `{str(e)[:300]}`", view=None
        )


async def send_clan_admin_panel(bot):
    """Отправляет админ-панель лиги с селектом + красивой шапкой."""
    STAFF_CHANNEL = 1551276116679860314
    ch = bot.get_channel(STAFF_CHANNEL)
    if not ch:
        ch = await bot.fetch_channel(STAFF_CHANNEL)
    if not ch:
        return

    async for msg in ch.history(limit=30):
        if msg.author == bot.user and msg.embeds:
            for e in msg.embeds:
                if e.title and "клановой лигой" in e.title.lower():
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    break

        e = disnake.Embed(
        title="Управление клановой лигой",
        description=(
            "> Обновление кланов, пересборка случайно, пересчёт достижений, обновление панелей.\n"
            "> Сезон идёт автоматически: старт и выплата 28-го числа в 20:00 МСК.\n"
            "> Условие нахождения в клане: баланс ≥ 45 DC, роль покупателя, активность за 30 дней."
        ),
        color=0x676767
    )
    e.set_image(url=IMG_STRIPE)

    await ch.send(embed=e, view=ClanAdminView())

# ============================================================
# 11. ХЕНДЛЕР
# ============================================================
async def handle_clan_interaction(inter: disnake.MessageInteraction):
    pass


# ============================================================
# 12. ТАСКИ
# ============================================================
from disnake.ext import tasks


_last_payout_date = None
_news_sent = {
    "3days": None,
    "1hour": None,
    "weekly": None,
}


def start_clan_tasks(bot):
    if not _clan_cycle_task.is_running():
        _clan_cycle_task.start(bot)
    if not _clan_daily_reset_task.is_running():
        _clan_daily_reset_task.start(bot)
    if not _clan_weekly_reset_task.is_running():
        _clan_weekly_reset_task.start(bot)
    if not _clan_news_task.is_running():
        _clan_news_task.start(bot)
    if not _clan_prune_task.is_running():
        _clan_prune_task.start(bot)


@tasks.loop(minutes=1)
async def _clan_cycle_task(bot):
    global _last_payout_date
    await bot.wait_until_ready()

    now = datetime.now(MSK)
    today = now.date()

    cycle = get_current_cycle()

    if not cycle:
        if now.day == 28 and now.hour == 20 and now.minute < 2:
            start_new_cycle()
            await update_clan_pool_embed(bot)
            await post_news_season_start(bot)
        return

    if cycle["ends_at"] <= int(time.time()):
        if _last_payout_date == today:
            return
        _last_payout_date = today
        await close_cycle_and_pay(bot)


@tasks.loop(minutes=1)
async def _clan_daily_reset_task(bot):
    await bot.wait_until_ready()
    now = datetime.now(MSK)
    if now.hour == 0 and now.minute == 0:
        reset_daily_quests()


@tasks.loop(minutes=1)
async def _clan_weekly_reset_task(bot):
    await bot.wait_until_ready()
    now = datetime.now(MSK)
    if now.weekday() == 0 and now.hour == 0 and now.minute == 0:
        reset_weekly_quests()


@tasks.loop(minutes=1)
async def _clan_news_task(bot):
    await bot.wait_until_ready()
    try:
        now = datetime.now(MSK)
        today = now.date()
        cycle = get_current_cycle()
        if not cycle:
            return

        if now.day == 25 and now.hour == 20 and now.minute < 2:
            if _news_sent["3days"] != today:
                _news_sent["3days"] = today
                await post_news_season_3days(bot)

        if now.day == 28 and now.hour == 19 and now.minute < 2:
            if _news_sent["1hour"] != today:
                _news_sent["1hour"] = today
                await post_news_season_1hour(bot)

        if now.weekday() == 6 and now.hour == 20 and now.minute < 2:
            if _news_sent["weekly"] != today:
                _news_sent["weekly"] = today
                await post_news_weekly(bot)
    except Exception as e:
        logger.exception(f"clan news task: {e}")


@tasks.loop(hours=6)
async def _clan_prune_task(bot):
    """Автоматическая чистка кланов каждые 6 часов."""
    await bot.wait_until_ready()
    try:
        from clan.core import prune_ineligible_clan_members
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild:
            return
        result = await prune_ineligible_clan_members(guild)
        if result["removed"] > 0:
            logger.info(
                f"🧹 Авто-чистка кланов: исключено {result['removed']} чел., "
                f"вычищено {result.get('removed_dc', 0)} DC из копилок"
            )
            await update_clan_pool_embed(bot)
    except Exception as e:
        logger.exception(f"_clan_prune_task: {e}")


def init_clan_panels():
    pass
