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
# ЭМОДЗИ КНОПОК / СЕЛЕКТОВ
# ============================================================
EMOJI_BANK   = PartialEmoji.from_str("<:1d1ds:1552730624572391584>")
EMOJI_TOP    = PartialEmoji.from_str("<:d1edf:1552730601155596348>")
EMOJI_HOWTO  = PartialEmoji.from_str("<:infor:1552730394795970621>")

EMOJI_QUESTS = PartialEmoji.from_str("<:d11d1:1552732333394763776>")
EMOJI_SLOTS  = PartialEmoji.from_str("<:game1:1552732315606589460>")

# 👇 Оригинальные эмодзи игр (восстановил)
EMOJI_ROULETTE  = "<:ropulet:1550563615675781282>"
EMOJI_BLACKJACK = "<:joke:1551288467659428020>"
EMOJI_COINFLIP  = "<:coins:1539649259245408340>"

# 👇 Картинка embed1 при клике на «Игровые автоматы DC»
IMG_SLOTS_TOP = ("https://cdn.discordapp.com/attachments/1527006158282555412/"
                 "1552731239398768711/image.png?ex=6ab6ad27&is=6ab55ba7&"
                 "hm=60031b3eef30f7e7448875045e47612b869469755e50801f3819ae2dfbbb8913&")


# ============================================================
# СТАТИЧНЫЕ ЭМБЕДЫ КОПИЛКИ (clan_pool.json)
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
# ДИНАМИЧЕСКИЙ ЭМБЕД СЕЗОНА — ЧИСТЫЙ, БЕЗ ЛИШНИХ ЭМОДЗИ
# ============================================================
def _build_season_embeds() -> List[disnake.Embed]:
    cycle = get_current_cycle()

    blocks = []
    top_clan = None
    top_bank = -1
    total_bank = 0

    for c in get_all_clans():
        bank = get_clan_bank(c["id"])
        members = get_clan_members_count(c["id"])
        top = get_clan_top(c["id"], limit=1)
        total_bank += bank

        if bank > top_bank:
            top_bank = bank
            top_clan = c

        if top:
            leader_line = f"Лидер: <@{top[0]['user_id']}> — {top[0]['total']} DC"
        else:
            leader_line = "Лидер: —"

        blocks.append(
            f"{c['emoji']}  **{c['name'].upper()}**\n"
            f"{members} чел. · вклад {bank} DC\n"
            f"{leader_line}"
        )

    body = "\n\n".join(blocks)

    # Последние вклады — без лишних эмодзи
    recent = get_recent_contributions_all(limit=5)
    recent_lines = []
    for r in recent:
        clan = get_clan(r["clan_id"])
        emoji = clan["emoji"] if clan else "·"
        recent_lines.append(
            f"· <@{r['user_id']}> → +{r['amount']} DC ({emoji} · {r['reason'][:40]})"
        )
    if not recent_lines:
        recent_lines = ["· пока нет вкладов"]

    recent_block = "\n".join(recent_lines)

    # Шапка
    head_title = f"КЛУБНАЯ ЛИГА — СЕЗОН #{cycle['number'] if cycle else '?'}"

    # Собираем описание аккуратно
    desc = body
    desc += "\n\n────────────────────"
    desc += f"\nОбщий пул: **{total_bank} DC**"
    if top_clan:
        desc += f"\nВ лидерах: {top_clan['emoji']} **{top_clan['name'].upper()}**"

    desc += "\n\n**Последние вклады:**\n" + recent_block

    # Футер через footer, не через описание
    e_stats = disnake.Embed(
        title=head_title,
        description=desc,
        color=0x9b59b6
    )

    if cycle:
        ends_at = cycle["ends_at"]
        e_stats.add_field(
            name="До конца сезона",
            value=f"<t:{ends_at}:R>  ·  <t:{ends_at}:f>",
            inline=False
        )

    e_stats.set_footer(text="Топ обновляется каждый час")
    e_stats.timestamp = datetime.now(timezone.utc)

    return [e_stats]


# ============================================================
# КНОПКИ КОПИЛКИ
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
        await _show_clan_bank(inter)

    @disnake.ui.button(
        label=f"{P}Топ{P}",
        style=ButtonStyle.gray,
        custom_id="clan_pool:top",
        emoji=EMOJI_TOP
    )
    async def top(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        await _show_clan_top(inter)

    @disnake.ui.button(
        label=f"{P}Как это работает{P}",
        style=ButtonStyle.gray,
        custom_id="clan_pool:howto",
        emoji=EMOJI_HOWTO
    )
    async def howto(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        await _show_howto(inter)


async def _show_clan_bank(inter: disnake.MessageInteraction):
    user_clan = get_user_clan(inter.author.id)
    if not user_clan:
        return await inter.response.send_message(
            "Ты не в клане. Обратись к администрации.", ephemeral=True
        )

    bank = get_clan_bank(user_clan["id"])
    members = get_clan_members_count(user_clan["id"])
    top = get_clan_top(user_clan["id"], limit=3)
    my_contrib = get_user_contribution(inter.author.id)

    all_top = get_clan_top(user_clan["id"], limit=1000)
    my_rank = None
    for i, t in enumerate(all_top, 1):
        if t["user_id"] == inter.author.id:
            my_rank = i
            break

    lines = [f"Банк клана: **{bank} DC**",
             f"Участников: **{members}**",
             f"Твой вклад: **{my_contrib} DC**"]
    if my_rank:
        lines.append(f"Твоё место: **#{my_rank}**")

    if top:
        lines.append("\n**Топ-3 клана:**")
        medals = ["🥇", "🥈", "🥉"]
        for i, t in enumerate(top, 1):
            lines.append(f"{medals[i-1]} <@{t['user_id']}> — {t['total']} DC")

    e = disnake.Embed(
        title=f"{user_clan['emoji']} Банк клана {user_clan['name']}",
        description="\n".join(lines),
        color=user_clan["color"]
    )
    e.set_footer(text="Клановая лига Diamond")
    await inter.response.send_message(embed=e, ephemeral=True)


async def _show_clan_top(inter: disnake.MessageInteraction):
    user_clan = get_user_clan(inter.author.id)
    if not user_clan:
        return await inter.response.send_message(
            "Ты не в клане.", ephemeral=True
        )

    top = get_clan_top(user_clan["id"], limit=10)
    my_contrib = get_user_contribution(inter.author.id)

    all_top = get_clan_top(user_clan["id"], limit=1000)
    my_rank = None
    for i, t in enumerate(all_top, 1):
        if t["user_id"] == inter.author.id:
            my_rank = i
            break

    if not top:
        desc = "Пока никто не вложил DC в копилку клана."
    else:
        lines = []
        for i, t in enumerate(top, 1):
            prefix = f"{['🥇','🥈','🥉'][i-1]}" if i <= 3 else f"`{i}.`"
            lines.append(f"{prefix} <@{t['user_id']}> — **{t['total']} DC**")
        desc = "\n".join(lines)

    desc += "\n\n────────────────────"
    desc += f"\nТвой вклад: **{my_contrib} DC**"
    if my_rank:
        desc += f" · место **#{my_rank}**"

    e = disnake.Embed(
        title=f"Топ клана {user_clan['emoji']} {user_clan['name']}",
        description=desc,
        color=user_clan["color"]
    )
    e.set_footer(text="Обновляется каждый час")
    await inter.response.send_message(embed=e, ephemeral=True)


async def _show_howto(inter: disnake.MessageInteraction):
    e = disnake.Embed(
        title="Как работает Клановая лига",
        description=(
            "Сезон длится **28 дней**, финал — **28 числа в 20:00 МСК**.\n\n"
            "**Как копится банк**\n"
            "· каждый заработанный DC — **60%** в копилку клана\n"
            "· выполнение квестов — **100%** награды в копилку\n"
            "· выигрыш в казино — **60%** от выплаты в копилку\n\n"
            "**Как делится**\n"
            "· весь банк клана делится между участниками\n"
            "· вес участника = время в клане × бонус\n"
            "· Топ-3 по вкладу получают ×1.75 / ×1.50 / ×1.30\n\n"
            "**Квесты**\n"
            "· ежедневные — сброс в 00:00 МСК\n"
            "· недельные — сброс в пн 00:00 МСК\n"
            "· разовые — на весь сезон\n\n"
            "**Где смотреть**\n"
            "· Копилка — <#1552700960474800128>\n"
            "· Сезон — <#1552700989465956403>\n"
            "· Игры и квесты — <#1552700973753827509>"
        ),
        color=6776679
    )
    await inter.response.send_message(embed=e, ephemeral=True)


# ============================================================
# ЭМБЕД ИГР И КВЕСТОВ
# ============================================================
def _build_games_embeds() -> List[disnake.Embed]:
    data = load_json(os.path.join(EMBEDS_DIR, "clan_games.json"), {})
    embeds = []
    for e in data.get("embeds", []):
        embeds.append(disnake.Embed.from_dict(e))
    if not embeds:
        embeds = [disnake.Embed(color=6776679)]
    return embeds


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

        # 👇 embed1 — картинка из IMG_SLOTS_TOP
        e1 = disnake.Embed(color=6776679)
        e1.set_image(url=IMG_SLOTS_TOP)

        e2 = disnake.Embed(
            title="Игровые автоматы DC",
            description=(
                "Выбери игру, чтобы сыграть.\n"
                "Все выигрыши — **60%** в копилку клана."
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
# ОТПРАВКА ПАНЕЛЕЙ
# ============================================================
async def send_clan_pool_panel(bot):
    """Канал 1552700960474800128 — статичный."""
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
    logger.info("Клан-копилка: статичная панель отправлена")


async def send_clan_season_panel(bot):
    """Канал 1552700989465956403 — динамический эмбед сезона."""
    ch = bot.get_channel(CONFIG["CLAN_SEASON_CHANNEL_ID"])
    if not ch:
        ch = await bot.fetch_channel(CONFIG["CLAN_SEASON_CHANNEL_ID"])
    if not ch:
        logger.warning("Clan season channel not found")
        return

    # Ищем прошлое сообщение бота и редактируем, если есть
    old_msg = None
    async for msg in ch.history(limit=20):
        if msg.author == bot.user and msg.embeds:
            old_msg = msg
            break

    embeds = _build_season_embeds()

    if old_msg:
        try:
            await old_msg.edit(embeds=embeds)
            logger.info("Клан-сезон: эмбед обновлён (edit)")
            return
        except Exception:
            pass

    await ch.send(embeds=embeds)
    logger.info("Клан-сезон: эмбед отправлен (new)")


async def send_clan_games_panel(bot):
    """Канал 1552700973753827509 — игры + квесты."""
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
    """Обновляет и копилку, и сезон."""
    await send_clan_pool_panel(bot)
    await send_clan_season_panel(bot)


# ============================================================
# АДМИН-ПАНЕЛЬ (селект)
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
    STAFF_CHANNEL = 1551276116679860314
    ch = bot.get_channel(STAFF_CHANNEL)
    if not ch:
        ch = await bot.fetch_channel(STAFF_CHANNEL)
    if not ch:
        return

    # Чистим только прошлые панели лиги
    async for msg in ch.history(limit=30):
        if msg.author == bot.user and msg.embeds:
            for e in msg.embeds:
                if e.title and "клановой лигой" in e.title.lower():
                    try:
                        await msg.delete()
                    except Exception:
                        pass
                    break

    e2 = disnake.Embed(
        title="🏛 Управление клановой лигой",
        description=(
            "Старт нового цикла — принудительно запустить сезон.\n"
            "Форс-конец и выплата — закрыть сезон с расчётом.\n"
            "Автораспределение — раскидать всех клубных без клана (с ребалансом).\n"
            "Кик из клана — исключить юзера (вклад остаётся в банке).\n"
            "Обновить панели — пересобрать эмбеды копилки и сезона.\n\n"
            "────────────────────\n"
            "Исключения: `1124040555240898631`, `796293832751972352` не распределяются."
        ),
        color=6776679
    )
    e2.set_image(url=IMG_STRIPE)
    await ch.send(embed=e2, view=ClanAdminView())


# ============================================================
# ХЕНДЛЕР ИНТЕРАКЦИЙ
# ============================================================
async def handle_clan_interaction(inter: disnake.MessageInteraction):
    pass


# ============================================================
# ТАСКИ
# ============================================================
from disnake.ext import tasks


_last_payout_date = None


def start_clan_tasks(bot):
    if not _clan_cycle_task.is_running():
        _clan_cycle_task.start(bot)
    if not _clan_daily_reset_task.is_running():
        _clan_daily_reset_task.start(bot)
    if not _clan_weekly_reset_task.is_running():
        _clan_weekly_reset_task.start(bot)
    if not _clan_season_update_task.is_running():
        _clan_season_update_task.start(bot)


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


# 👇 Обновление сезонного эмбеда раз в час
@tasks.loop(hours=1)
async def _clan_season_update_task(bot):
    await bot.wait_until_ready()
    try:
        await send_clan_season_panel(bot)
        logger.info("Клан-сезон: авто-обновление раз в час")
    except Exception as e:
        logger.exception(f"clan season update: {e}")


def init_clan_panels():
    pass
