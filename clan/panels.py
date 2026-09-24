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
# ЭМБЕД КОПИЛКИ
# ============================================================
def _build_pool_embeds() -> List[disnake.Embed]:
    cycle = get_current_cycle()

    data = load_json(os.path.join(EMBEDS_DIR, "clan_pool.json"), {})
    embeds = []
    for e in data.get("embeds", []):
        embeds.append(disnake.Embed.from_dict(e))

    if not embeds:
        embeds = [disnake.Embed(color=6776679)]

    lines = []
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

        leader = f"<@{top[0]['user_id']}> — {top[0]['total']} DC" if top else "—"

        pct = bank / max(top_bank, 1) if top_bank > 0 else 0
        bar = make_progress_bar(pct, 10)

        lines.append(
            f"{c['emoji']}  **{c['name'].upper()}**  {clan_status_emoji(bank)}\n"
            f"> Участников: **{members}**  ·  Вклад: **{bank} DC**\n"
            f"> 👑 Лидер: {leader}\n"
            f"> {bar}"
        )

    recent = get_recent_contributions_all(limit=5)
    recent_lines = []
    for r in recent:
        clan = get_clan(r["clan_id"])
        emoji = clan["emoji"] if clan else "🎁"
        recent_lines.append(
            f"> • <@{r['user_id']}> внёс **{r['amount']} DC** в {emoji} за «{r['reason'][:40]}»"
        )
    if not recent_lines:
        recent_lines = ["> Пока нет вкладов"]

    stats_desc = "\n\n".join(lines)
    stats_desc += "\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
    stats_desc += f"📊 **Общий пул:** `{total_bank} DC`\n"
    if top_clan:
        stats_desc += f"🏆 **В лидерах:** {top_clan['emoji']} **{top_clan['name'].upper()}**\n"
    stats_desc += "\n🕐 **Последние вклады:**\n"
    stats_desc += "\n".join(recent_lines)

    e_stats = disnake.Embed(
        title=f"💎 КЛУБНАЯ ЛИГА — СЕЗОН #{cycle['number'] if cycle else '?'}",
        description=stats_desc,
        color=6776679
    )
    e_stats.set_image(url=IMG_STRIPE)

    if cycle:
        ends_at = cycle["ends_at"]
        e_stats.add_field(
            name="⏰ До конца сезона",
            value=f"<t:{ends_at}:R>\n<t:{ends_at}:f>",
            inline=False
        )

    embeds.append(e_stats)
    return embeds


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
        emoji=PartialEmoji(name="💎")
    )
    async def bank(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        await _show_clan_bank(inter)

    @disnake.ui.button(
        label=f"{P}Топ клана{P}",
        style=ButtonStyle.gray,
        custom_id="clan_pool:top",
        emoji=PartialEmoji(name="🏆")
    )
    async def top(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        await _show_clan_top(inter)

    @disnake.ui.button(
        label=f"{P}Как это работает{P}",
        style=ButtonStyle.gray,
        custom_id="clan_pool:howto",
        emoji=PartialEmoji(name="ℹ️")
    )
    async def howto(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        await _show_howto(inter)


async def _show_clan_bank(inter: disnake.MessageInteraction):
    user_clan = get_user_clan(inter.author.id)
    if not user_clan:
        return await inter.response.send_message(
            "❌ Ты не в клане. Обратись к администрации.", ephemeral=True
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

    lines = [f"> **Банк клана:** `{bank} DC`",
             f"> **Участников:** `{members}`",
             f"> **Твой вклад:** `{my_contrib} DC`"]
    if my_rank:
        lines.append(f"> **Твоё место:** `#{my_rank}`")

    if top:
        lines.append("\n**👑 Топ-3 клана:**")
        for i, t in enumerate(top, 1):
            medal = ["🥇", "🥈", "🥉"][i - 1]
            lines.append(f"> {medal} <@{t['user_id']}> — `{t['total']} DC`")

    e1 = disnake.Embed(color=user_clan["color"])
    e1.set_image(url=IMG_STRIPE)
    e2 = disnake.Embed(
        title=f"{user_clan['emoji']} Банк клана {user_clan['name']}",
        description="\n".join(lines),
        color=user_clan["color"]
    )
    e2.set_image(url=IMG_STRIPE)
    await inter.response.send_message(embeds=[e1, e2], ephemeral=True)


async def _show_clan_top(inter: disnake.MessageInteraction):
    user_clan = get_user_clan(inter.author.id)
    if not user_clan:
        return await inter.response.send_message(
            "❌ Ты не в клане.", ephemeral=True
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
        desc = "> Пока никто не вложил DC в копилку клана."
    else:
        lines = []
        for i, t in enumerate(top, 1):
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"`{i}.`"
            lines.append(f"> {medal} <@{t['user_id']}> — **{t['total']} DC**")
        desc = "\n".join(lines)

    desc += f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
    desc += f"📊 **Твой вклад:** `{my_contrib} DC`"
    if my_rank:
        desc += f"  ·  место **#{my_rank}**"

    e1 = disnake.Embed(color=user_clan["color"])
    data = load_json(os.path.join(EMBEDS_DIR, "top.json"), {})
    for e in data.get("embeds", [])[:1]:
        e1 = disnake.Embed.from_dict(e)

    e2 = disnake.Embed(
        title=f"🏆 Топ клана {user_clan['emoji']} {user_clan['name']}",
        description=desc,
        color=user_clan["color"]
    )
    e2.set_image(url=IMG_STRIPE)
    await inter.response.send_message(embeds=[e1, e2], ephemeral=True)


async def _show_howto(inter: disnake.MessageInteraction):
    data = load_json(os.path.join(EMBEDS_DIR, "howto.json"), {})
    embeds = []
    for e in data.get("embeds", []):
        embeds.append(disnake.Embed.from_dict(e))

    e2 = disnake.Embed(
        title="ℹ️ Как работает Клановая лига",
        description=(
            "> Каждый сезон длится **28 дней**, финал — **28 числа в 20:00 МСК**.\n\n"
            "**💰 Как копится банк**\n"
            "> • За каждый заработанный DC — **60%** уходит в копилку клана\n"
            "> • За выполнение квестов — **100%** награды в копилку\n"
            "> • За выигрыш в казино — **60%** от выплаты в копилку\n\n"
            "**🏆 Как делится**\n"
            "> • Весь банк клана распределяется между участниками\n"
            "> • Вес участника = время в клане × бонус\n"
            "> • Топ-3 по вкладу получают бонус ×1.75 / ×1.50 / ×1.30\n\n"
            "**📋 Квесты**\n"
            "> • Ежедневные — сброс в 00:00 МСК\n"
            "> • Недельные — сброс в пн 00:00 МСК\n"
            "> • Разовые — на весь сезон\n\n"
            "**🎮 Где играть**\n"
            "> • Копилка — <#1552700989465956403>\n"
            "> • Игры и квесты — <#1552700973753827509>"
        ),
        color=6776679
    )
    e2.set_image(url=IMG_STRIPE)
    embeds.append(e2)
    await inter.response.send_message(embeds=embeds, ephemeral=True)


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
        emoji=PartialEmoji(name="📋")
    )
    async def quests(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        embeds = format_quests_embed(inter.author.id)
        await inter.response.send_message(embeds=embeds, ephemeral=True)

    @disnake.ui.button(
        label=f"{P}Игровые автоматы{P}",
        style=ButtonStyle.gray,
        custom_id="clan_games:slots",
        emoji=PartialEmoji(name="🎰")
    )
    async def slots(self, button, inter: disnake.MessageInteraction):
        await on_panel_click_quest_hook(inter.author.id)
        e1 = disnake.Embed(color=6776679)
        e1.set_image(url=IMG_STRIPE)
        e2 = disnake.Embed(
            title="🎰 Игровые автоматы Diamond",
            description="> Выбери игру, чтобы сыграть.\n> **Все выигрыши — 60% в копилку клана.**",
            color=6776679
        )
        e2.set_image(url=IMG_STRIPE)

        view = View(timeout=300)
        select = Select(
            placeholder="В какую игру хочешь сыграть?",
            options=[
                SelectOption(label="Рулетка", description="Испытай удачу, до ×10", emoji="🎰", value="roulette"),
                SelectOption(label="Блэкджек", description="Классика 21", emoji="🃏", value="blackjack"),
                SelectOption(label="Монетка", description="Орёл или Решка, ×1.9", emoji="🪙", value="coinflip"),
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

    embeds = _build_pool_embeds()
    await ch.send(embeds=embeds, view=ClanPoolView())
    logger.info("Клан-копилка: панель отправлена")


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


# ============================================================
# АДМИН-ПАНЕЛЬ (в стаф-канале)
# ============================================================
class ClanAdminView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="🔄 Старт нового цикла",
        style=ButtonStyle.gray,
        custom_id="clan_admin:new_cycle"
    )
    async def new_cycle(self, button, inter: disnake.MessageInteraction):
        if not _is_admin(inter):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        cycle = get_current_cycle()
        if cycle:
            return await inter.response.send_message(
                f"❌ Уже есть активный цикл #{cycle['number']}. Сначала заверши.",
                ephemeral=True
            )
        start_new_cycle()
        await inter.response.send_message("✅ Новый цикл запущен.", ephemeral=True)
        await update_clan_pool_embed(inter.bot)

    @disnake.ui.button(
        label="⏹ Форс-конец и выплата",
        style=ButtonStyle.danger,
        custom_id="clan_admin:force_pay"
    )
    async def force_pay(self, button, inter: disnake.MessageInteraction):
        if not _is_admin(inter):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        result = await close_cycle_and_pay(inter.bot)
        if result:
            await inter.edit_original_response(content="✅ Цикл закрыт, выплаты произведены.")
        else:
            await inter.edit_original_response(content="❌ Нет активного цикла.")

    @disnake.ui.button(
        label="🚀 Автораспределение",
        style=ButtonStyle.gray,
        custom_id="clan_admin:distribute"
    )
    async def distribute(self, button, inter: disnake.MessageInteraction):
        if not _is_admin(inter):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        from clan.core import distribute_all_club_members
        result = distribute_all_club_members(inter.guild)
        await inter.edit_original_response(
            content=f"✅ Распределено: **{result['assigned']}**\n"
                    f"> Уже в клане: **{result['skipped']}**\n"
                    f"> Исключены: **{result.get('excluded', 0)}**"
        )

    @disnake.ui.button(
        label="👤 Кик из клана",
        style=ButtonStyle.gray,
        custom_id="clan_admin:kick"
    )
    async def kick(self, button, inter: disnake.MessageInteraction):
        if not _is_admin(inter):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.send_modal(_KickModal())


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
    """Отправляет админ-панель лиги в стаф-канал + красивая шапка с картинкой."""
    STAFF_CHANNEL = 1551276116679860314
    ch = bot.get_channel(STAFF_CHANNEL)
    if not ch:
        ch = await bot.fetch_channel(STAFF_CHANNEL)
    if not ch:
        return

    # 👇 Красивый embed1 + инфо
    e1 = disnake.Embed(color=6776679)
    e1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1552726263758585956/image.png?ex=6ab6a885&is=6ab55705&hm=a7418d5c6f38288a8518eee61d765e21c019bdf3a160bc0df960ea074b69de0b&")
    e2 = disnake.Embed(
        title="🏛 Управление клановой лигой",
        description=(
            "> **Старт нового цикла** — принудительно запустить сезон.\n"
            "> **Форс-конец и выплата** — закрыть сезон с расчётом.\n"
            "> **Автораспределение** — раскидать всех клубных без клана (с ребалансом).\n"
            "> **Кик из клана** — исключить юзера (вклад остаётся в банке).\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "> ⚠️ **Исключения:** `1124040555240898631`, `796293832751972352` не распределяются."
        ),
        color=6776679
    )
    e2.set_image(url=IMG_STRIPE)
    await ch.send(embeds=[e1, e2], view=ClanAdminView())


# ============================================================
# ХЕНДЛЕР ИНТЕРАКЦИЙ
# ============================================================
async def handle_clan_interaction(inter: disnake.MessageInteraction):
    pass


# ============================================================
# ТАСКИ
# ============================================================
def start_clan_tasks(bot):
    if not _clan_cycle_task.is_running():
        _clan_cycle_task.start(bot)
    if not _clan_daily_reset_task.is_running():
        _clan_daily_reset_task.start(bot)
    if not _clan_weekly_reset_task.is_running():
        _clan_weekly_reset_task.start(bot)


from disnake.ext import tasks


_last_payout_date = None


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


def init_clan_panels():
    pass
