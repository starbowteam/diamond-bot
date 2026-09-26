# -*- coding: utf-8 -*-
"""UI и таски клановой лиги."""
import os
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

import disnake
from disnake import ButtonStyle, SelectOption, PartialEmoji
from disnake.ui import Button, Select, View

from core.utils import (
    CONFIG, logger, db, cur, load_json, save_json, log_discord
)

from clan.core import (
    CLANS_DATA, CLUB_ROLE_ID, MIN_BALANCE,
    get_clan, get_all_clans, get_user_clan, assign_user_to_clan,
    get_clan_bank, get_clan_top, get_clan_members_count,
    get_user_contribution, get_recent_contributions_all,
    get_current_cycle, start_new_cycle, close_cycle_and_pay,
    make_progress_bar, clan_status_emoji,
    MSK, EMBEDS_DIR, IMG_STRIPE, REPORT_DM_USER_ID,
)

from clan.quests import (
    format_quests_embed, reset_daily_quests, reset_weekly_quests,
    on_panel_click_quest_hook,
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
                  "1552734704120238080/image.png?ex=6ab6b061&is=6ab55ee1&"
                  "hm=39d4ed4a6b4d2162fd5a8931b5ddc0c0a0bb9d216ce7503e968aafab94b8f8a5&")

IMG_NEWS_TOP = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
                "1552733874444959824/image.png?ex=6ab6af9c&is=6ab55e1c&"
                "hm=18b6186e463332b0a9ce258825a1be6592353df0d6ddb346b3e3455eae5206af&")

IMG_ADMIN_TOP = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
                 "1553238615444815963/image.png?ex=6ab885af&is=6ab7342f&"
                 "hm=cd565ec3073866b96954abcb9ef14bd41b860d9f087492ebdf6c200eecbcfdc2&")


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
    season_num = cycle["number"] if cycle else "?"

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
        title=f"Клубная лига - сезон {season_num}!",
        description=desc,
        color=6776679
    )
    e2.set_image(url=IMG_STRIPE)

    return [e1, e2]


# ============================================================
# 3. ВКЛАДЫ
# ============================================================
def _build_contributions_embed() -> disnake.Embed:
    e = disnake.Embed(
        title="Вклады кланов",
        description="> О том, какой клан, сколько внёс в копилку, и о лидерах внутри кланов.\n",
        color=6776679
    )
    e.set_image(url=IMG_STRIPE)

    for c in get_all_clans():
        bank = get_clan_bank(c["id"])
        members = get_clan_members_count(c["id"])
        top = get_clan_top(c["id"], limit=1)
        if top:
            leader = f"<@{top[0]['user_id']}> — {top[0]['total']} DC"
        else:
            leader = "—"
        e.add_field(
            name=f"{c['emoji']} {c['name'].upper()}",
            value=f"{members} чел. · вклад {bank} DC\nЛидер: {leader}",
            inline=True
        )
    return e


# ============================================================
# 4. ПОСЛЕДНЕЕ
# ============================================================
def _build_last_embed() -> disnake.Embed:
    recent = get_recent_contributions_all(limit=5)
    lines = []
    for r in recent:
        clan = get_clan(r["clan_id"])
        emoji = clan["emoji"] if clan else "·"
        lines.append(
            f"· <@{r['user_id']}> → +{r['amount']} DC ({emoji} · {r['reason'][:60]})"
        )
    if not lines:
        lines = ["· Пока нет вкладов"]

    e = disnake.Embed(
        title="Последнее",
        description=(
            "> Последние вклады участников в свои кланы\n\n"
            "**Последние вклады:**\n" + "\n".join(lines) + "\n"
        ),
        color=6776679
    )
    e.set_image(url=IMG_STRIPE)
    return e


# ============================================================
# 5. ОБЩИЙ ПУЛ
# ============================================================
def _build_total_pool_embed() -> disnake.Embed:
    total_bank = 0
    top_clan = None
    top_bank = -1
    for c in get_all_clans():
        bank = get_clan_bank(c["id"])
        total_bank += bank
        if bank > top_bank:
            top_bank = bank
            top_clan = c

    if top_clan:
        leader_line = f"{top_clan['emoji']} {top_clan['name'].upper()}"
    else:
        leader_line = "—"

    e = disnake.Embed(
        title="Общий пул",
        description=(
            "> Общий охват копилки со всех кланов\n\n"
            ">>> Общий пул: **{} DC**\n"
            "В лидерах: — {}".format(total_bank, leader_line)
        ),
        color=6776679
    )
    e.set_image(url=IMG_STRIPE)
    return e


# ============================================================
# 6. БАНК КЛАНА
# ============================================================
def _build_clan_bank_embed(user_id: int) -> Optional[disnake.Embed]:
    user_clan = get_user_clan(user_id)
    if not user_clan:
        return None

    bank = get_clan_bank(user_clan["id"])
    members = get_clan_members_count(user_clan["id"])
    my_contrib = get_user_contribution(user_id)

    all_top = get_clan_top(user_clan["id"], limit=1000)
    my_rank = None
    for i, t in enumerate(all_top, 1):
        if t["user_id"] == user_id:
            my_rank = i
            break

    rank_line = f"#{my_rank}" if my_rank else "—"

    e = disnake.Embed(
        title=f"Банк клана {user_clan['emoji']} {user_clan['name']}",
        description=(
            f"***💎 Банк клана \"{user_clan['name']}\"***\n\n"
            f"> Банк клана: {bank} DC\n"
            f"> Участников: {members}\n"
            f"> Твой вклад: {my_contrib} DC\n"
            f"> Твоё место: {rank_line}\n"
        ),
        color=user_clan["color"]
    )
    e.set_image(url=IMG_STRIPE)
    return e


# ============================================================
# 7. ТОП КЛАНА
# ============================================================
def _build_clan_top_embed(user_id: int) -> Optional[disnake.Embed]:
    user_clan = get_user_clan(user_id)
    if not user_clan:
        return None

    top = get_clan_top(user_clan["id"], limit=10)
    my_contrib = get_user_contribution(user_id)

    all_top = get_clan_top(user_clan["id"], limit=1000)
    my_rank = None
    for i, t in enumerate(all_top, 1):
        if t["user_id"] == user_id:
            my_rank = i
            break

    medals = ["🥇", "🥈", "🥉"]
    if not top:
        lines = ["Пока никто не вложил DC в копилку клана."]
    else:
        lines = []
        for i, t in enumerate(top, 1):
            prefix = medals[i - 1] if i <= 3 else f"`{i}.`"
            lines.append(f"{prefix} <@{t['user_id']}> — {t['total']} DC")

    rank_line = f"#{my_rank}" if my_rank else "—"

    desc = (
        f"***💎 Топ клана \"{user_clan['name']}\"***\n\n"
        + "\n".join(lines)
        + f"\n\n***Твой вклад: {my_contrib} DC · место {rank_line}***"
    )

    e = disnake.Embed(
        title=f"Топ клана {user_clan['emoji']} {user_clan['name']}",
        description=desc,
        color=user_clan["color"]
    )
    e.set_image(url=IMG_STRIPE)
    return e


# ============================================================
# 8. КАК ЭТО РАБОТАЕТ
# ============================================================
def _build_howto_embed() -> disnake.Embed:
    e = disnake.Embed(
        title="Как работает Клановая лига",
        description=(
            "> Сезон длится **28 дней**. Финал — **28 числа в 20:00 МСК**.\n"
            "> По итогам сезона, весь банк клана распределяется между участниками.\n\n"
            "**Как копится банк**\n"
            ">>> · Каждый заработанный DC — **60%** в копилку клана\n"
            "· Выполнение квестов — **100%** награды в копилку\n"
            "· Победа в казино — **60%** от выплаты в копилку\n\n"
            "**Как делится пул**\n"
            ">>> · Весь банк клана делится между всеми участниками\n"
            "· Вес участника = время в клане × бонус\n"
            "· Топ-3 по вкладу получают бонусы ×1.75 / ×1.50 / ×1.30\n\n"
            "**Квесты**\n"
            ">>> · Ежедневные — сброс в 00:00 МСК\n"
            "· Недельные — сброс в пн 00:00 МСК\n"
            "· Разовые — на весь сезон\n\n"
            "**Где смотреть**\n"
            ">>> · Копилка — <#1552700960474800128>\n"
            "· Сезон — <#1552700989465956403>\n"
            "· Игры и квесты — <#1552700973753827509>\n"
            "· Новости — <#1552700701128400979>"
        ),
        color=6776679
    )
    e.set_image(url=IMG_STRIPE)
    return e


# ============================================================
# 9. ИГРЫ
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
# 10. КНОПКИ КОПИЛКИ
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
        e = _build_clan_bank_embed(inter.author.id)
        if not e:
            return await inter.response.send_message("Ты не в клане.", ephemeral=True)
        await inter.response.send_message(embed=e, ephemeral=True)

    @disnake.ui.button(
        label=f"{P}Топ{P}",
        style=ButtonStyle.gray,
        custom_id="clan_pool:top",
        emoji=EMOJI_TOP
    )
    async def top(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        e = _build_clan_top_embed(inter.author.id)
        if not e:
            return await inter.response.send_message("Ты не в клане.", ephemeral=True)
        await inter.response.send_message(embed=e, ephemeral=True)

    @disnake.ui.button(
        label=f"{P}Как это работает{P}",
        style=ButtonStyle.gray,
        custom_id="clan_pool:howto",
        emoji=EMOJI_HOWTO
    )
    async def howto(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        await inter.response.send_message(embed=_build_howto_embed(), ephemeral=True)


# ============================================================
# 11. КНОПКИ СЕЗОНА
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
        await inter.response.send_message(embed=_build_contributions_embed(), ephemeral=True)

    @disnake.ui.button(
        label=f"{P}Последнее{P}",
        style=ButtonStyle.gray,
        custom_id="clan_season:last",
        emoji=EMOJI_LAST
    )
    async def last(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        await inter.response.send_message(embed=_build_last_embed(), ephemeral=True)

    @disnake.ui.button(
        label=f"{P}Общий пул{P}",
        style=ButtonStyle.gray,
        custom_id="clan_season:total",
        emoji=EMOJI_TOTAL
    )
    async def total(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        await inter.response.send_message(embed=_build_total_pool_embed(), ephemeral=True)


# ============================================================
# 12. КНОПКИ ИГР
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
        embeds = format_quests_embed(inter.author.id)
        await inter.response.send_message(embeds=embeds, ephemeral=True)

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
                "> Все выигрыши — **60%** в копилку клана."
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
        await inter.response.send_message(embeds=[e1, e2], view=view, ephemeral=True)


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
# 13. ОТПРАВКА ПАНЕЛЕЙ
# ============================================================
async def send_clan_pool_panel(bot):
    ch = bot.get_channel(CONFIG["CLAN_POOL_CHANNEL_ID"])
    if not ch:
        ch = await bot.fetch_channel(CONFIG["CLAN_POOL_CHANNEL_ID"])
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
        ch = await bot.fetch_channel(CONFIG["CLAN_SEASON_CHANNEL_ID"])
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
        ch = await bot.fetch_channel(CONFIG["CLAN_GAMES_CHANNEL_ID"])
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
# 14. НОВОСТИ
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
    news = "Стартует новый сезон клубной лиги."
    desc = (
        f"Сезон #{cycle['number']} официально открыт. "
        f"Копилки кланов обнулены, отсчёт пошёл. "
        f"Участники могут зарабатывать DC, выполнять квесты и вносить вклад в банк клана. "
        f"Финал — **28 числа в 20:00 МСК**."
    )
    await _post_clan_news(bot, "Старт нового сезона клубной лиги", news, desc)


async def post_news_season_3days(bot):
    cycle = get_current_cycle()
    if not cycle:
        return
    news = "До финала сезона осталось 3 дня."
    desc = (
        f"Самое время увеличить свой вклад в банк клана. "
        f"Топ-3 участника получат бонусы ×1.75 / ×1.50 / ×1.30. "
        f"Финал — **28 числа в 20:00 МСК**."
    )
    await _post_clan_news(bot, "До финала клубной лиги 3 дня", news, desc)


async def post_news_season_1hour(bot):
    cycle = get_current_cycle()
    if not cycle:
        return
    news = "Остался последний час до финала сезона."
    desc = (
        f"Успей внести последний вклад в свой клан. "
        f"После 20:00 МСК банк будет распределён между участниками. "
        f"Топ-3 забирают бонусы ×1.75 / ×1.50 / ×1.30."
    )
    await _post_clan_news(bot, "Час до финала клубной лиги", news, desc)


async def post_news_season_end(bot, report: dict):
    cycle = report["cycle"]
    total = sum(c["bank"] for c in report["clans"])
    top_clan = max(report["clans"], key=lambda x: x["bank"]) if report["clans"] else None

    news = f"Сезон #{cycle['number']} официально завершён."
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
    await _post_clan_news(bot, "Сезон клубной лиги завершён", news, desc)


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

    news = "Еженедельный отчёт по клубной лиге."
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
# 15. АДМИН-ПАНЕЛЬ
# ============================================================
class ClanAdminSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            SelectOption(
                label="・Старт нового цикла",
                description="Принудительно запустить новый сезон",
                emoji="🔄",
                value="new_cycle"
            ),
            SelectOption(
                label="・Форс-конец и выплата",
                description="Закрыть сезон с расчётом пула",
                emoji="⏹",
                value="force_pay"
            ),
            SelectOption(
                label="・Автораспределение",
                description="Раскидать всех клубных без клана (с ребалансом)",
                emoji="🚀",
                value="distribute"
            ),
            SelectOption(
                label="・Кик из клана",
                description="Исключить юзера из клана (вклад остаётся)",
                emoji="👤",
                value="kick"
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

        if value == "new_cycle":
            cycle = get_current_cycle()
            if cycle:
                return await inter.response.send_message(
                    f"❌ Уже есть активный цикл #{cycle['number']}. Сначала заверши.",
                    ephemeral=True
                )
            start_new_cycle()
            await inter.response.send_message("✅ Новый цикл запущен.", ephemeral=True)
            await update_clan_pool_embed(inter.bot)
            await post_news_season_start(inter.bot)

        elif value == "force_pay":
            await inter.response.defer(ephemeral=True)
            result = await close_cycle_and_pay(inter.bot)
            if result:
                await inter.edit_original_response(content="✅ Цикл закрыт, выплаты произведены.")
            else:
                await inter.edit_original_response(content="❌ Нет активного цикла.")

        elif value == "distribute":
            await inter.response.defer(ephemeral=True)
            from clan.core import distribute_all_club_members
            result = distribute_all_club_members(inter.guild)
            await inter.edit_original_response(
                content=f"✅ Распределено: **{result['assigned']}**\n"
                        f"Уже в клане: **{result['skipped']}**\n"
                        f"Исключены: **{result.get('excluded', 0)}**"
            )
            await update_clan_pool_embed(inter.bot)

        elif value == "kick":
            await inter.response.send_modal(_KickModal())

        elif value == "refresh":
            await inter.response.defer(ephemeral=True)
            await update_clan_pool_embed(inter.bot)
            await inter.edit_original_response(content="✅ Панели обновлены.")


class ClanAdminView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ClanAdminSelect())


def _is_admin(inter: disnake.MessageInteraction) -> bool:
    from core.utils import has_admin_command_roles
    return has_admin_command_roles(inter.author)


class _KickModal(disnake.ui.Modal):
    def __init__(self):
        super().__init__(
            title="Кик из клана",
            components=[disnake.ui.TextInput(
                label="ID юзера",
                custom_id="uid",
                min_length=1, max_length=30
            )]
        )

    async def callback(self, inter: disnake.MessageInteraction):
        uid = inter.text_values["uid"].strip()
        if not uid.isdigit():
            return await inter.response.send_message("❌ ID должен быть числом.", ephemeral=True)
        uid = int(uid)
        cur.execute(
            "UPDATE clan_members SET left_at=? WHERE user_id=? AND left_at IS NULL",
            (int(time.time()), uid)
        )
        db.commit()
        from clan.core import get_all_clans
        for c in get_all_clans():
            role = inter.guild.get_role(c["role_id"])
            member = inter.guild.get_member(uid)
            if role and member and role in member.roles:
                try:
                    await member.remove_roles(role)
                except Exception:
                    pass
        await inter.response.send_message(f"✅ Юзер <@{uid}> кикнут из клана.", ephemeral=True)
        await log_discord(
            title="👤 Кик из клана",
            description=f"> **Кем:** {inter.author.mention}\n> **Кого:** <@{uid}>",
            color=0xFF6B6B,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )


async def send_clan_admin_panel(bot):
    """Отправляет админ-панель лиги с СЕЛЕКТОМ + красивой шапкой (676767)."""
    STAFF_CHANNEL = 1551276116679860314
    ch = bot.get_channel(STAFF_CHANNEL)
    if not ch:
        ch = await bot.fetch_channel(STAFF_CHANNEL)
    if not ch:
        return

    # Чистим прошлые панели лиги
    async for msg in ch.history(limit=30):
        if msg.author == bot.user and msg.embeds:
            for e in msg.embeds:
                if e.title and "клановой лигой" in e.title.lower():
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    break

    # 👇 Embed1 — картинка-шапка (676767)
    e1 = disnake.Embed(color=0x676767)
    e1.set_image(url=IMG_ADMIN_TOP)

    # 👇 Embed2 — описание
    e2 = disnake.Embed(
        title="Управление клановой лигой",
        description=(
            "> Управление клановой лигой по ручному вводу, имей ввиду, нажимая что то тут - ты управляешь **всем сезоном!**\n\n"
            "> **Старт нового цикла** — принудительно запустить сезон.\n"
            "> **Форс-конец и выплата** — закрыть сезон с расчётом пула.\n"
            "> **Автораспределение** — раскидать всех клубных без клана (с ребалансом).\n"
            "> **Кик из клана** — исключить юзера (вклад остаётся в банке).\n"
            "> **Обновить панели** — пересобрать эмбеды копилки и сезона.\n\n"
            "────────────────────\n"
            "Исключения: `1124040555240898631`, `796293832751972352` не распределяются."
        ),
        color=0x676767
    )
    e2.set_image(url=IMG_STRIPE)

    await ch.send(embeds=[e1, e2], view=ClanAdminView())


# ============================================================
# 16. ХЕНДЛЕР
# ============================================================
async def handle_clan_interaction(inter: disnake.MessageInteraction):
    pass


# ============================================================
# 17. ТАСКИ
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


def init_clan_panels():
    pass
