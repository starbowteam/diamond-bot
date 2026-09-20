# -*- coding: utf-8 -*-
import os
import sys
import asyncio
import time
import random
from datetime import datetime, timezone, timedelta
from datetime import time as dt_time
from typing import List
import disnake
from disnake.ext import commands, tasks
from disnake import PartialEmoji, ButtonStyle, ui

from core.utils import (
    CONFIG, FILES, logger, db, cur,
    load_json, save_json, now_ts,
    update_user_roles, sync_invites,
    has_admin_command_roles,
    log_discord,
    BASE_DIR, ADD_DIR, DATA_DIR, CATALOG_DIR, ACTIONS_DIR,
    get_dc_cache, save_dc_cache, sync_dc_to_json,
    assign_ticket_manager, get_ticket_manager, get_ticket_owner, clear_ticket_manager,
    increment_manager_closed, add_manager_rating,
    add_closed_order
)

from modules.actions import (
    send_actions_panel, handle_flash_interaction,
    refresh_daily_deal, load_flash_sale, save_flash_sale,
    generate_random_deal, FLASH_SALE_FILE,
    FLASH_SALE_DURATION_HOURS, DAILY_DEAL_REFRESH_HOURS,
    start_flash_sale,
)
from modules.dc import (
    add_dc, get_user_balance, load_shop_catalog,
    get_user_dc_data, save_user_dc_data,
    daily_bonus
)

intents = disnake.Intents.default()
intents.members = True
intents.messages = True
intents.guilds = True
intents.message_content = True
intents.moderation = True
intents.invites = True
intents.reactions = True
intents.voice_states = True

bot = commands.Bot(command_prefix='/', intents=intents)

# ============================================================
# КОНСТАНТЫ
# ============================================================
_REVIEW_COOLDOWN = {}
REVIEW_COOLDOWN_SECONDS = 120
REVIEW_MIN_LENGTH = 3
REVIEW_REWARD_DC = 15

# Flash sale
FLASH_SALE_ROLE_ID = 1127428607606796290
FLASH_SALE_DURATION = FLASH_SALE_DURATION_HOURS * 3600
FLASH_SALE_CHECK_MINUTES = 30

# МСК (UTC+3)
MSK = timezone(timedelta(hours=3))


# ============================================================
# ЗАРПЛАТЫ И АВАНСЫ
# ============================================================
SALARY_ROLES = {
    1471844291595731016: {"advance": 70, "salary": 150},
    1513935883475226796: {"advance": 50, "salary": 110},
    1154757071330365490: {"advance": 50, "salary": 110},
    1471190371181789234: {"advance": 45, "salary": 90},
    1457964854441672806: {"advance": 40, "salary": 80},
}
SALARY_ROLE_ORDER = [
    1471844291595731016,
    1513935883475226796,
    1154757071330365490,
    1471190371181789234,
    1457964854441672806,
]


async def process_salary(mode: str):
    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        logger.warning(f"process_salary({mode}): guild not found")
        return

    total = 0
    awarded = 0
    errors = 0
    stats = {role_id: 0 for role_id in SALARY_ROLE_ORDER}

    for member in guild.members:
        if member.bot:
            continue

        top_role_id = None
        for role_id in SALARY_ROLE_ORDER:
            if member.get_role(role_id):
                top_role_id = role_id
                break

        if not top_role_id:
            continue

        amount = SALARY_ROLES[top_role_id][mode]
        if amount <= 0:
            continue

        try:
            await add_dc(member.id, amount,
                         f"{'Зарплата' if mode == 'salary' else 'Аванс'} по роли {top_role_id} (авто)")
            stats[top_role_id] += 1
            awarded += 1
            total += amount
        except Exception as e:
            logger.error(f"Ошибка авто-начисления {mode} пользователю {member.id}: {e}")
            errors += 1

    result_lines = []
    for role_id in SALARY_ROLE_ORDER:
        count = stats[role_id]
        if count > 0:
            role = guild.get_role(role_id)
            role_name = role.name if role else str(role_id)
            result_lines.append(f"**{role_name}** – {count} чел.")
    result_text = "\n".join(result_lines) if result_lines else "Никто не получил."

    logger.info(f"Авто-выдача {mode}: {awarded} чел., {total} DC, ошибок: {errors}")
    await log_discord(
        title=f"💰 Авто-выдача {'зарплаты' if mode == 'salary' else 'аванса'}",
        description=(
            f"> **Тип:** {'Зарплата (31 число)' if mode == 'salary' else 'Аванс (15 число)'}\n"
            f"> **Сотрудников:** {awarded}\n"
            f"> **Всего выдано:** {total} DC\n"
            f"> **Ошибок:** {errors}\n"
            f"> **Распределение:**\n{result_text}"
        ),
        color=0x00ff00
    )


# ============================================================
# БАННЕР И СЧЁТЧИК ОТЗЫВОВ
# ============================================================
_banner_last_update = 0.0


async def schedule_banner_update():
    global _banner_last_update
    _banner_last_update = time.time()
    await asyncio.sleep(5)
    if time.time() - _banner_last_update < 4.5:
        return
    try:
        await update_review_counter(silent=True)
    except Exception as e:
        logger.exception(f"schedule_banner_update error: {e}")


async def update_review_counter(silent: bool = False):
    try:
        text_ch = bot.get_channel(CONFIG["REVIEW_COUNT_CHANNEL"])
        if not text_ch:
            text_ch = await bot.fetch_channel(CONFIG["REVIEW_COUNT_CHANNEL"])
        if not text_ch:
            logger.warning("update_review_counter: review channel not found")
            return
        count = 1431
        async for m in text_ch.history(limit=None):
            count += 1
        logger.info("Review count: %s", count)
        await update_server_banner(count, silent)
    except Exception as e:
        logger.exception("update_review_counter error: %s", e)
        if not silent:
            await log_discord(
                title="❌ Ошибка обновления счётчика отзывов",
                description=f"> **Ошибка:** `{str(e)}`",
                color=0xff0000
            )


async def update_server_banner(review_count: int, silent: bool = False):
    try:
        from PIL import Image, ImageDraw, ImageFont
        base_path = os.path.join(ADD_DIR, "banner.png")
        output_path = os.path.join(DATA_DIR, "banner_ready.png")
        font_path = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")

        if not os.path.exists(base_path):
            logger.warning("Banner file not found: %s", base_path)
            return
        if not os.path.exists(font_path):
            logger.warning("Font file not found: %s", font_path)
            return

        img = Image.open(base_path).convert("RGBA")
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(font_path, 400)
        text = str(review_count)
        draw.text((594, 540), text, font=font, fill=(255, 255, 255), anchor="mm")
        img.save(output_path)

        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild:
            logger.warning("update_server_banner: guild not found")
            return
        with open(output_path, "rb") as f:
            await guild.edit(banner=f.read())
        logger.info("Banner updated with %s reviews", review_count)
        if not silent:
            await log_discord(
                title="🖼️ Баннер обновлён",
                description=f"> **Количество отзывов:** `{review_count}`",
                color=0x00aaff
            )
    except Exception as e:
        logger.exception("Banner update error: %s", e)
        if not silent:
            await log_discord(
                title="❌ Ошибка обновления баннера",
                description=f"> **Ошибка:** `{str(e)}`",
                color=0xff0000
            )


# ============================================================
# TASKS
# ============================================================
@tasks.loop(hours=24)
async def review_counter_task():
    await bot.wait_until_ready()
    await update_review_counter(silent=False)


@tasks.loop(hours=24)
async def daily_bonus_task():
    await bot.wait_until_ready()
    await daily_bonus()


@tasks.loop(minutes=5)
async def daily_deal_task():
    """Обновляет товар дня + детектирует флеш-слоты."""
    await bot.wait_until_ready()
    try:
        before = load_json(os.path.join(DATA_DIR, "daily_deal.json"), {})
        deal = refresh_daily_deal()
        after = load_json(os.path.join(DATA_DIR, "daily_deal.json"), {})

        if before.get("slot") != after.get("slot"):
            if after.get("flash_slot"):
                logger.info("Флеш-слот — запускаем флеш-акцию")
                await start_flash_sale(bot)
            elif deal:
                logger.info(f"Товар дня авто-обновлён: {deal['item_data']['name']}")
    except Exception as e:
        logger.exception(f"daily_deal_task error: {e}")


@tasks.loop(minutes=FLASH_SALE_CHECK_MINUTES)
async def flash_sale_task():
    """Только удаление истёкшего флеша (запуск — в daily_deal_task)."""
    await bot.wait_until_ready()
    try:
        data = load_flash_sale()
        now = time.time()

        if data.get("active"):
            started = data.get("started_at", 0)
            if now - started >= FLASH_SALE_DURATION:
                ch_id = data.get("channel_id")
                msg_id = data.get("message_id")
                if ch_id and msg_id:
                    try:
                        ch = bot.get_channel(ch_id) or await bot.fetch_channel(ch_id)
                        msg = await ch.fetch_message(msg_id)
                        await msg.delete()
                        logger.info("Flash sale истёк — сообщение удалено")
                    except Exception as e:
                        logger.warning(f"Не удалось удалить flash-сообщение: {e}")
                save_flash_sale({
                    "active": False, "item": None,
                    "started_at": 0, "message_id": 0, "channel_id": 0
                })
                await log_discord(
                    title="⚡ Flash sale завершён",
                    description=f"> **Товар:** {data.get('item', {}).get('item_data', {}).get('name', '—')}",
                    color=0xff6600
                )
    except Exception as e:
        logger.exception(f"flash_sale_task error: {e}")


@tasks.loop(time=dt_time(hour=0, minute=0, tzinfo=MSK))
async def salary_advance_task():
    await bot.wait_until_ready()
    try:
        now_msk = datetime.now(MSK)
        if now_msk.day != 15:
            return
        logger.info("Авто-выдача аванса запущена (15 число, 00:00 МСК)")
        await process_salary("advance")
    except Exception as e:
        logger.exception(f"salary_advance_task error: {e}")


@tasks.loop(time=dt_time(hour=0, minute=0, tzinfo=MSK))
async def salary_main_task():
    await bot.wait_until_ready()
    try:
        now_msk = datetime.now(MSK)
        tomorrow = now_msk + timedelta(days=1)
        if tomorrow.day != 1:
            return
        logger.info("Авто-выдача зарплаты запущена (последний день месяца, 00:00 МСК)")
        await process_salary("salary")
    except Exception as e:
        logger.exception(f"salary_main_task error: {e}")


# ============================================================
# ON READY
# ============================================================
@bot.event
async def on_ready():
    try:
        await bot.change_presence(activity=disnake.Game(name="Основной бот + DC"))

        from modules.commands_tickets import (
            TicketPanelView, TicketPaidView, TicketView, CoinsTicketButtons,
            TicketRatingView, SelectView, CatalogTypeView, CatalogView,
            BuySelectView, QuestionTicketView, handle_interaction
        )
        from modules.commands_panels import (
            send_home_panel, send_tarology_panel, send_ticket_panel,
            send_manager_top, send_work_panel, ResetStatsView, HomeView,
            TarologyView, WorkView
        )
        from modules.commands_profile import send_profile_panel, ProfileView

        bot.add_view(TicketPanelView())
        bot.add_view(TicketPaidView())
        bot.add_view(TicketView())
        bot.add_view(CoinsTicketButtons())
        bot.add_view(TicketRatingView())
        bot.add_view(SelectView())
        bot.add_view(CatalogTypeView())
        bot.add_view(CatalogView())
        bot.add_view(BuySelectView())
        bot.add_view(ResetStatsView())
        bot.add_view(HomeView())
        bot.add_view(TarologyView())
        bot.add_view(ProfileView())
        bot.add_view(WorkView())
        bot.add_view(QuestionTicketView())

        bot.loop.create_task(send_home_panel())
        bot.loop.create_task(send_tarology_panel())
        bot.loop.create_task(send_ticket_panel())
        bot.loop.create_task(send_profile_panel())
        bot.loop.create_task(send_work_panel())
        bot.loop.create_task(keep_voice_alive())
        bot.loop.create_task(send_actions_panel())
        bot.loop.create_task(send_manager_top())

        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        counts = {}
        if guild:
            for member in guild.members:
                if member.bot:
                    continue
                get_user_dc_data(member.id)
            sync_dc_to_json()
            logger.info("DC data initialized and synced to SQLite")

            counts = load_json(FILES["review_counts"], {})
            if counts:
                for uid_str, count in counts.items():
                    uid = int(uid_str)
                    member = guild.get_member(uid)
                    if member:
                        await update_user_roles(member, count, keep_pka=True)
                logger.info(f"Роли обновлены для {len(counts)} пользователей по отзывам")

        await update_review_counter(silent=False)

        if not review_counter_task.is_running():
            review_counter_task.start()
        if not daily_bonus_task.is_running():
            daily_bonus_task.start()
        if not daily_deal_task.is_running():
            daily_deal_task.start()
        if not flash_sale_task.is_running():
            flash_sale_task.start()
        if not salary_advance_task.is_running():
            salary_advance_task.start()
        if not salary_main_task.is_running():
            salary_main_task.start()

        logger.info("%s is ready", bot.user)
        await log_discord(
            title="✅ Бот запустился",
            description=f"> **{bot.user}** готов и онлайн.\n> Роли обновлены для {len(counts) if counts else 0} пользователей.",
            color=0x00ff00
        )
    except Exception as e:
        logger.exception("on_ready error: %s", e)
        await log_discord(
            title="❌ Ошибка при запуске",
            description=f"> **Ошибка:** `{str(e)}`",
            color=0xff0000
        )


async def keep_voice_alive():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
            if guild:
                vc = guild.voice_client
                if not vc or not vc.is_connected():
                    try:
                        voice_channel = guild.get_channel(CONFIG["VOICE_CHANNEL_ID"])
                        if not voice_channel:
                            voice_channel = await bot.fetch_channel(CONFIG["VOICE_CHANNEL_ID"])
                        if voice_channel and isinstance(voice_channel, disnake.VoiceChannel):
                            await voice_channel.connect()
                            logger.info("Подключился к голосовому каналу: %s", voice_channel.name)
                    except Exception as e:
                        logger.debug("keep_voice_alive connect failed: %s", e)
        except Exception as e:
            logger.exception("keep_voice_alive loop error: %s", e)
        await asyncio.sleep(60)


# ============================================================
# ПЕРЕСТРОЙКА ПРАВ ТИКЕТА
# ============================================================
async def reassign_ticket_permissions(channel: disnake.TextChannel, manager: disnake.Member):
    guild = channel.guild

    for role_id in CONFIG["TICKET_MANAGE_ROLES"]:
        role = guild.get_role(role_id)
        if role:
            overwrite = disnake.PermissionOverwrite(
                view_channel=True, send_messages=False,
                read_message_history=True, add_reactions=False,
                create_public_threads=False
            )
            await channel.set_permissions(role, overwrite=overwrite)

    manager_overwrites = disnake.PermissionOverwrite(
        view_channel=True, send_messages=True,
        read_message_history=True, add_reactions=True,
        create_public_threads=True, embed_links=True, attach_files=True
    )
    await channel.set_permissions(manager, overwrite=manager_overwrites)

    owner_id = get_ticket_owner(channel.id)
    if owner_id:
        owner = guild.get_member(owner_id)
        if owner and owner.id != manager.id:
            owner_overwrite = disnake.PermissionOverwrite(
                view_channel=True, send_messages=True,
                read_message_history=True, add_reactions=True,
                create_public_threads=True
            )
            await channel.set_permissions(owner, overwrite=owner_overwrite)

    await log_discord(
        title="🔐 Права тикета обновлены",
        description=f"> **Тикет:** {channel.mention}\n> **Менеджер:** {manager.mention}",
        color=0x00aaff,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )


# ============================================================
# СОБЫТИЯ
# ============================================================
@bot.event
async def on_member_join(member: disnake.Member):
    await log_discord(
        title="👤 Участник зашёл",
        description=f"> **{member.mention}** (`{member}`) присоединился.\n> ID: `{member.id}`",
        color=0x00ff00
    )
    role = member.guild.get_role(1127428607606796290)
    if role:
        try:
            await member.add_roles(role)
        except Exception as e:
            logger.error(f"Не удалось выдать роль: {e}")
    guild = member.guild
    snapshot_before = {row["invite_code"]: row for row in db.execute("SELECT * FROM invites_snapshot WHERE guild_id=?", (guild.id,)).fetchall()}
    try:
        invites_now = await guild.invites()
    except Exception:
        return
    used_invite = None
    for inv in invites_now:
        old = snapshot_before.get(inv.code)
        if old and inv.uses > old["uses"]:
            used_invite = inv
            break
    for inv in invites_now:
        db.execute("REPLACE INTO invites_snapshot (invite_code, guild_id, uses, inviter_id) VALUES (?, ?, ?, ?)",
                    (inv.code, guild.id, inv.uses, inv.inviter.id if inv.inviter else None))
    if not used_invite or not used_invite.inviter:
        db.commit()
        return
    inviter_id = used_invite.inviter.id
    is_bot = 1 if member.bot else 0
    joined_at = now_ts()
    db.execute("INSERT INTO invites (guild_id, inviter_id, member_id, joined_at, is_bot) VALUES (?, ?, ?, ?, ?)",
                (guild.id, inviter_id, member.id, joined_at, is_bot))
    db.commit()
    await log_discord(
        title="📨 Использован инвайт",
        description=f"> **Пользователь:** {member.mention}\n> **Пригласил:** <@{inviter_id}>\n> **Код:** `{used_invite.code}`",
        color=0x00aaff
    )


@bot.event
async def on_member_remove(member: disnake.Member):
    guild = member.guild
    await log_discord(
        title="🚪 Участник вышел",
        description=f"> **{member.mention}** (`{member}`) покинул сервер.\n> ID: `{member.id}`",
        color=0xff0000
    )
    db.execute("UPDATE invites SET left_at=? WHERE guild_id=? AND member_id=? AND left_at IS NULL",
                (now_ts(), guild.id, member.id))
    row = db.execute("SELECT joined_at FROM invites WHERE guild_id=? AND member_id=? ORDER BY joined_at DESC LIMIT 1",
                      (guild.id, member.id)).fetchone()
    if row and (now_ts() - row["joined_at"]) < 600:
        db.execute("UPDATE invites SET is_fake=1 WHERE guild_id=? AND member_id=? AND is_fake=0",
                    (guild.id, member.id))
        await log_discord(
            title="⚠️ Фейковый вход",
            description=f"> **Пользователь:** {member.mention}\n> Ушёл менее чем через **10 минут** после входа.",
            color=0xff6600
        )
    db.commit()


@bot.event
async def on_member_update(before: disnake.Member, after: disnake.Member):
    if before.display_name != after.display_name:
        await log_discord(
            title="✏️ Изменён никнейм",
            description=f"> **Пользователь:** {before.mention}\n> **Было:** `{before.display_name}`\n> **Стало:** `{after.display_name}`",
            color=0xffff00
        )
    if before.roles != after.roles:
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if added:
            await log_discord(
                title="➕ Выдана роль",
                description=f"> **Пользователь:** {after.mention}\n> **Роль:** {', '.join(r.mention for r in added)}",
                color=0x00ff00
            )
        if removed:
            await log_discord(
                title="➖ Снята роль",
                description=f"> **Пользователь:** {after.mention}\n> **Роль:** {', '.join(r.mention for r in removed)}",
                color=0xff0000
            )
    if before.display_avatar.url != after.display_avatar.url:
        await log_discord(
            title="🖼️ Изменён аватар",
            description=f"> **Пользователь:** {after.mention}\n> [Новый аватар]({after.display_avatar.url})",
            color=0xffff00
        )


@bot.event
async def on_raw_message_delete(payload: disnake.RawMessageDeleteEvent):
    if payload.channel_id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        asyncio.create_task(schedule_banner_update())


@bot.event
async def on_message_delete(message: disnake.Message):
    if message.author.bot:
        return
    content = message.content or "[Нет текста]"
    if len(content) > 1024:
        content = content[:1021] + "..."
    await log_discord(
        title="🗑️ Удалено сообщение",
        description=f"> **Автор:** {message.author.mention} (`{message.author}`)\n> **Канал:** {message.channel.mention}\n> **Содержание:**\n```\n{content}\n```",
        color=0xff6600
    )


@bot.event
async def on_bulk_message_delete(messages: List[disnake.Message]):
    channel = messages[0].channel if messages else None
    count = len(messages)
    await log_discord(
        title="🗑️ Массовое удаление сообщений",
        description=f"> **Канал:** {channel.mention if channel else 'неизвестно'}\n> **Количество:** `{count}` сообщений",
        color=0xff6600
    )
    if channel and channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        asyncio.create_task(schedule_banner_update())


@bot.event
async def on_message_edit(before: disnake.Message, after: disnake.Message):
    if before.author.bot:
        return
    if before.content == after.content:
        return
    before_content = before.content or "[Нет текста]"
    after_content = after.content or "[Нет текста]"
    if len(before_content) > 500:
        before_content = before_content[:497] + "..."
    if len(after_content) > 500:
        after_content = after_content[:497] + "..."
    await log_discord(
        title="✏️ Изменено сообщение",
        description=f"> **Автор:** {before.author.mention} (`{before.author}`)\n> **Канал:** {before.channel.mention}\n> **Было:**\n```\n{before_content}\n```\n> **Стало:**\n```\n{after_content}\n```",
        color=0xffff00
    )


@bot.event
async def on_guild_channel_create(channel: disnake.abc.GuildChannel):
    await log_discord(
        title="➕ Создан канал",
        description=f"> **Название:** {channel.mention} (`{channel.name}`)\n> **Тип:** `{channel.type}`\n> **ID:** `{channel.id}`",
        color=0x00ff00
    )


@bot.event
async def on_guild_channel_delete(channel: disnake.abc.GuildChannel):
    await log_discord(
        title="➖ Удалён канал",
        description=f"> **Название:** `{channel.name}`\n> **Тип:** `{channel.type}`\n> **ID:** `{channel.id}`",
        color=0xff0000
    )


@bot.event
async def on_guild_channel_update(before: disnake.abc.GuildChannel, after: disnake.abc.GuildChannel):
    if before.name != after.name:
        await log_discord(
            title="✏️ Изменён канал",
            description=f"> **Канал:** {after.mention}\n> **Было:** `{before.name}`\n> **Стало:** `{after.name}`",
            color=0xffff00
        )


@bot.event
async def on_guild_role_create(role: disnake.Role):
    await log_discord(
        title="➕ Создана роль",
        description=f"> **Название:** {role.mention} (`{role.name}`)\n> **Цвет:** `{role.color}`\n> **ID:** `{role.id}`",
        color=0x00ff00
    )


@bot.event
async def on_guild_role_delete(role: disnake.Role):
    await log_discord(
        title="➖ Удалена роль",
        description=f"> **Название:** `{role.name}`\n> **ID:** `{role.id}`",
        color=0xff0000
    )


@bot.event
async def on_guild_role_update(before: disnake.Role, after: disnake.Role):
    if before.name != after.name:
        await log_discord(
            title="✏️ Изменена роль",
            description=f"> **Роль:** {after.mention}\n> **Было:** `{before.name}`\n> **Стало:** `{after.name}`",
            color=0xffff00
        )
    if before.color != after.color:
        await log_discord(
            title="🎨 Изменён цвет роли",
            description=f"> **Роль:** {after.mention}\n> **Было:** `{before.color}`\n> **Стало:** `{after.color}`",
            color=0xffff00
        )


@bot.event
async def on_invite_create(invite: disnake.Invite):
    db.execute("REPLACE INTO invites_snapshot VALUES (?, ?, ?, ?)",
                (invite.code, invite.guild.id, invite.uses, invite.inviter.id if invite.inviter else None))
    db.commit()
    await log_discord(
        title="📨 Создан инвайт",
        description=f"> **Код:** `{invite.code}`\n> **Создатель:** {invite.inviter.mention if invite.inviter else 'Неизвестно'}\n> **Канал:** {invite.channel.mention if invite.channel else 'Неизвестно'}\n> **Лимит использований:** `{invite.max_uses}`",
        color=0x00aaff
    )


@bot.event
async def on_invite_delete(invite: disnake.Invite):
    db.execute("DELETE FROM invites_snapshot WHERE invite_code=?", (invite.code,))
    db.commit()
    await log_discord(
        title="🗑️ Удалён инвайт",
        description=f"> **Код:** `{invite.code}`\n> **Канал:** {invite.channel.mention if invite.channel else 'Неизвестно'}",
        color=0xff6600
    )


@bot.event
async def on_raw_reaction_add(payload: disnake.RawReactionActionEvent):
    if payload.member is None or payload.member.bot:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    row = db.execute(
        "SELECT role_id FROM reaction_roles WHERE guild_id=? AND channel_id=? AND message_id=? AND emoji=?",
        (payload.guild_id, payload.channel_id, payload.message_id, str(payload.emoji))
    ).fetchone()
    if row:
        role = guild.get_role(row["role_id"])
        if role:
            try:
                await payload.member.add_roles(role)
            except Exception as e:
                logger.error(f"Не удалось выдать реакционную роль: {e}")


@bot.event
async def on_raw_reaction_remove(payload: disnake.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    row = db.execute(
        "SELECT role_id FROM reaction_roles WHERE guild_id=? AND channel_id=? AND message_id=? AND emoji=?",
        (payload.guild_id, payload.channel_id, payload.message_id, str(payload.emoji))
    ).fetchone()
    if row:
        role = guild.get_role(row["role_id"])
        if role:
            member = guild.get_member(payload.user_id)
            if member:
                try:
                    await member.remove_roles(role)
                except Exception as e:
                    logger.error(f"Не удалось снять реакционную роль: {e}")


@bot.event
async def on_interaction(inter: disnake.MessageInteraction):
    from modules.commands_tickets import handle_interaction
    await handle_interaction(inter)
    await handle_flash_interaction(inter)


@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return

    if message.channel.category:
        cat_id = message.channel.category.id
        # Только эти 3 категории — назначаем менеджера с первого сообщения
        # Категория вопросов (1544363672128987196) НЕ входит
        if cat_id in [CONFIG["TICKET_CATEGORY_ID"], CONFIG["PAID_CATEGORY_ID"], CONFIG["COINS_CATEGORY_ID"]]:
            if get_ticket_manager(message.channel.id) is None:
                owner_id = get_ticket_owner(message.channel.id)
                if message.author.id != owner_id and any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in message.author.roles):
                    assign_ticket_manager(message.channel.id, message.author.id)
                    embed = disnake.Embed(
                        title="✅ Менеджер назначен",
                        description=f"> **Менеджер:** {message.author.mention}\n> **Тикет:** {message.channel.mention}",
                        color=0x00ff00,
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")
                    await message.channel.send(embed=embed)
                    await log_discord(
                        title="📌 Менеджер назначен",
                        description=f"> **Тикет:** {message.channel.mention}\n> **Менеджер:** {message.author.mention}",
                        color=0x00aaff,
                        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
                    )
                    await reassign_ticket_permissions(message.channel, message.author)

    from modules.dc import add_message_dc
    if len(message.content.strip()) >= CONFIG["MIN_MESSAGE_LENGTH"]:
        if message.channel.id != CONFIG["REVIEW_COUNT_CHANNEL"]:
            await add_message_dc(message.author.id)

    if message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        user_id = message.author.id
        now = time.time()
        text = (message.content or "").strip()

        last = _REVIEW_COOLDOWN.get(user_id, 0)
        if now - last < REVIEW_COOLDOWN_SECONDS:
            try:
                await message.delete()
            except Exception:
                pass
            return

        if message.attachments or message.stickers or message.embeds:
            try:
                await message.delete()
            except Exception:
                pass
            return

        if len(text) < REVIEW_MIN_LENGTH:
            try:
                await message.delete()
            except Exception:
                pass
            return

        _REVIEW_COOLDOWN[user_id] = now

        try:
            await message.add_reaction("💎")
        except Exception as e:
            logger.warning(f"Не удалось поставить реакцию на отзыв: {e}")

        counts = load_json(FILES["review_counts"], {})
        counts[str(user_id)] = counts.get(str(user_id), 0) + 1
        save_json(FILES["review_counts"], counts)

        try:
            await add_dc(user_id, REVIEW_REWARD_DC, "Отзыв о покупке")
        except Exception as e:
            logger.exception(f"Ошибка начисления DC за отзыв: {e}")

        if isinstance(message.author, disnake.Member):
            try:
                await update_user_roles(message.author, counts[str(user_id)], keep_pka=True)
            except Exception as e:
                logger.exception(f"Ошибка обновления ролей: {e}")

        try:
            dm_embed = disnake.Embed(
                title="✅ Отзыв принят!",
                description=(
                    f"> Спасибо за отзыв!\n\n"
                    f"> **Всего отзывов:** `{counts[str(user_id)]}`\n"
                    f"> **Начислено:** `+{REVIEW_REWARD_DC} DC`\n"
                    f"> **Следующий отзыв:** можно оставить через 2 минуты"
                ),
                color=0x2ecc71,
                timestamp=datetime.now(timezone.utc)
            )
            dm_embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")
            await message.author.send(embed=dm_embed)
        except Exception as e:
            logger.warning(f"Не удалось отправить ЛС об отзыве: {e}")

        await log_discord(
            title="📝 Отзыв принят",
            description=(
                f"> **Пользователь:** {message.author.mention}\n"
                f"> **Всего отзывов:** `{counts[str(user_id)]}`\n"
                f"> **Начислено:** `+{REVIEW_REWARD_DC} DC`\n"
                f"> **Текст:** {text[:200]}\n"
                f"> **Ссылка:** [перейти]({message.jump_url})"
            ),
            color=0x00ff00
        )

        await update_review_counter(silent=False)
        return

    await bot.process_commands(message)


voice_track = {}


@bot.event
async def on_voice_state_update(member: disnake.Member, before: disnake.VoiceState, after: disnake.VoiceState):
    if member.bot:
        return
    user_id = member.id
    if after.channel and (before.channel is None or before.channel != after.channel):
        voice_track[user_id] = (after.channel.id, int(time.time()))
    elif before.channel and (after.channel is None or after.channel != before.channel):
        if user_id in voice_track:
            channel_id, join_time = voice_track.pop(user_id)
            duration = int(time.time()) - join_time
            if duration > 60:
                from modules.dc import add_voice_dc
                await add_voice_dc(user_id, duration)
                await log_discord(
                    title="🎙️ Выход из голосового канала",
                    description=f"> **Пользователь:** {member.mention}\n> **Время:** {duration//60} мин.",
                    color=0x00aaff
                )
