# -*- coding: utf-8 -*-
import os
import sys
import asyncio
import time
import random
from datetime import datetime, timezone, timedelta
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
    get_dc_cache, save_dc_cache, sync_dc_to_json
)

# ============================================================
# Импорт модулей (без топ-задачи)
# ============================================================
from modules.actions import send_actions_panel, handle_flash_interaction
from modules.dc import (
    add_dc, get_user_balance, load_shop_catalog,
    get_user_dc_data, save_user_dc_data,
    daily_bonus, monthly_fee
)

# ============================================================
# Инициализация бота
# ============================================================
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
# Обновление баннера
# ============================================================
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
# Задачи (без топа)
# ============================================================
@tasks.loop(hours=24)
async def review_counter_task():
    await bot.wait_until_ready()
    await update_review_counter(silent=False)

@tasks.loop(hours=24)
async def daily_bonus_task():
    await bot.wait_until_ready()
    await daily_bonus()

@tasks.loop(hours=24)
async def monthly_fee_task():
    await bot.wait_until_ready()
    await monthly_fee()

# ============================================================
# Глобальные события
# ============================================================
@bot.event
async def on_ready():
    try:
        await bot.change_presence(activity=disnake.Game(name="Основной бот + DC"))

        # Импортируем классы View и панели только внутри on_ready
        from modules.commands import TicketPanelView, TicketButtons, TicketButtonsPaid, MenuView, send_home_panel
        bot.add_view(TicketPanelView())
        bot.add_view(TicketButtons())
        bot.add_view(TicketButtonsPaid())
        bot.add_view(MenuView())

        bot.loop.create_task(send_menu_panel())
        bot.loop.create_task(keep_voice_alive())
        bot.loop.create_task(send_actions_panel())
        bot.loop.create_task(send_home_panel())  # Домик

        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
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
            else:
                logger.info("Нет данных об отзывах для обновления ролей")

        await update_review_counter(silent=False)

        # Запускаем задачи
        if not review_counter_task.is_running():
            review_counter_task.start()
        if not daily_bonus_task.is_running():
            daily_bonus_task.start()
        if not monthly_fee_task.is_running():
            monthly_fee_task.start()

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

# ============================================================
# Фоновые задачи (панели)
# ============================================================
async def send_menu_panel():
    await bot.wait_until_ready()
    from modules.commands import send_menu_panel as _send_menu_panel
    await _send_menu_panel()

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
                            await log_discord(
                                title="🔊 Подключение к голосовому каналу",
                                description=f"> Бот подключился к {voice_channel.mention}",
                                color=0x00aaff
                            )
                    except Exception as e:
                        logger.debug("keep_voice_alive connect failed: %s", e)
        except Exception as e:
            logger.exception("keep_voice_alive loop error: %s", e)
        await asyncio.sleep(60)

# ============================================================
# Глобальные обработчики событий (логирование)
# ============================================================
@bot.event
async def on_member_join(member: disnake.Member):
    await log_discord(
        title="👤 Участник зашёл",
        description=f"> **{member.mention}** (`{member}`) присоединился к серверу.\n> ID: `{member.id}`",
        color=0x00ff00
    )
    role = member.guild.get_role(1127428607606796290)
    if role:
        try:
            await member.add_roles(role)
            await log_discord(
                title="👤 Автороль выдана",
                description=f"> **Пользователь:** {member.mention}\n> **Роль:** {role.mention}",
                color=0x00aaff
            )
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
                await log_discord(
                    title="✅ Выдана реакционная роль",
                    description=f"> **Пользователь:** {payload.member.mention}\n> **Роль:** {role.mention}\n> **Реакция:** {payload.emoji}\n> **Сообщение:** <https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}>",
                    color=0x00ff00
                )
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
                    await log_discord(
                        title="❌ Снята реакционная роль",
                        description=f"> **Пользователь:** {member.mention}\n> **Роль:** {role.mention}\n> **Реакция:** {payload.emoji}\n> **Сообщение:** <https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}>",
                        color=0xff0000
                    )
                except Exception as e:
                    logger.error(f"Не удалось снять реакционную роль: {e}")

# ============================================================
# Обработка взаимодействий (кнопки)
# ============================================================
@bot.event
async def on_interaction(inter: disnake.MessageInteraction):
    from modules.commands import handle_interaction
    await handle_interaction(inter)
    await handle_flash_interaction(inter)

# ============================================================
# Обработка сообщений (отзывы, активность)
# ============================================================
@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return

    from modules.dc import add_message_dc
    if len(message.content.strip()) >= CONFIG["MIN_MESSAGE_LENGTH"]:
        if message.channel.id != CONFIG["REVIEW_COUNT_CHANNEL"]:
            await add_message_dc(message.author.id)

    # ===== КАНАЛ ОТЗЫВОВ =====
    if message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        # 1. Ставим реакцию 💎
        try:
            await message.add_reaction("💎")
        except Exception as e:
            logger.warning(f"Не удалось поставить реакцию на отзыв: {e}")

        # 2. Увеличиваем счётчик отзывов
        counts = load_json(FILES["review_counts"], {})
        user_id = str(message.author.id)
        counts[user_id] = counts.get(user_id, 0) + 1
        save_json(FILES["review_counts"], counts)

        # 3. Обновляем роли
        if isinstance(message.author, disnake.Member):
            await update_user_roles(message.author, counts[user_id], keep_pka=True)
            await log_discord(
                title="🔄 Роли обновлены (отзыв)",
                description=f"> **Пользователь:** {message.author.mention}\n> **Отзывов стало:** `{counts[user_id]}`",
                color=0x00ff00
            )

        # 4. Отправляем на модерацию
        from modules.commands import ReviewModerationView
        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1531737026322370872/image.png?ex=6a6a4cc5&is=6a68fb45&hm=e5cf13f52a87fc671b53b8422a3cffa149579ce66d40846ed15a8c9d2ec89d76&")
        embed2 = disnake.Embed(
            title="✍️ Новый отзыв на модерацию",
            description=f">>> Автор: {message.author.mention}\nОтзыв: {message.content}\n\n",
            color=6776679
        )
        embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1530795801268453447/pisk.png?ex=6a69832f&is=6a6831af&hm=106c0b5c55c83b94fce2e11af7a4c65ec26d550b6da30575f1fef0981f7dc914&")
        embed2.add_field(name="> Канал", value="<#1462074763437543435>", inline=True)
        embed2.add_field(name="> Ссылка на отзыв", value=f"[Перейти]({message.jump_url})", inline=True)
        embed2.add_field(name="> Статус", value="🕑 На рассмотрении", inline=True)

        view = ReviewModerationView(message.author.id, message.content, message.id, message.channel.id)
        log_channel = bot.get_channel(CONFIG["MODERATION_LOG_CHANNEL"])
        if log_channel:
            sent_msg = await log_channel.send(embeds=[embed1, embed2], view=view)
            view.message = sent_msg

        try:
            await message.author.send("📩 Ваш отзыв отправлен на модерацию по начислению Diamond Coins. Ожидайте подтверждения от администратора.")
        except:
            pass

        await update_review_counter(silent=False)
        return

    await bot.process_commands(message)

# ============================================================
# Голосовые события (для DC)
# ============================================================
voice_track = {}  # {user_id: (channel_id, join_time)}

@bot.event
async def on_voice_state_update(member: disnake.Member, before: disnake.VoiceState, after: disnake.VoiceState):
    if member.bot:
        return
    user_id = member.id
    if after.channel and (before.channel is None or before.channel != after.channel):
        voice_track[user_id] = (after.channel.id, int(time.time()))
    elif before.channel and (after.channel is None or before.channel != after.channel):
        if user_id in voice_track:
            channel_id, join_time = voice_track.pop(user_id)
            duration = int(time.time()) - join_time
            if duration > 60:
                from modules.dc import add_voice_dc
                await add_voice_dc(user_id, duration)
                await log_discord(
                    title="🎙️ Выход из голосового канала",
                    description=f"> **Пользователь:** {member.mention}\n> **Время:** {duration//60} мин.\n> **Начислено:** за голосовую активность",
                    color=0x00aaff
                )
