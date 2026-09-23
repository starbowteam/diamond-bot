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
    daily_bonus, check_unused_purchases, daily_activity_payout,
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

FLASH_SALE_ROLE_ID = 1127428607606796290
FLASH_SALE_DURATION = FLASH_SALE_DURATION_HOURS * 3600
FLASH_SALE_CHECK_MINUTES = 30

WELCOME_BONUS_DC = 50

MSK = timezone(timedelta(hours=3))

IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6ab152a3&is=6ab00123&hm=c5c2963ca1ebbe6eb37f673fcef993cacf375c5a80490205c230d4c4adfe8b58&"
IMG_WELCOME = "https://cdn.discordapp.com/attachments/1527006158282555412/1551605614839463977/image.png?ex=6ab294d6&is=6ab14356&hm=4bddf29fabcc31cf6d81f58d190276c64503a03f1b27fa66b35e465e68d54000&"
IMG_ORDER_PAID = "https://cdn.discordapp.com/attachments/1527006158282555412/1551608259230695595/image.png?ex=6ab2974c&is=6ab145cc&hm=a6e78b3cb2686d6c61fcf7e618564c04c557856b1af501eb26bf9015793e8a93&"
IMG_UNUSED = "https://cdn.discordapp.com/attachments/1527006158282555412/1551572210811011142/image.png?ex=6ab275b9&is=6ab12439&hm=7d8e471545619f792391577a7a0bf5335995f759c5c8b09534ac840b881fc806&"

# Файл состояния зарплат (защита от повторной выдачи + catch-up)
SALARY_STATE_FILE = os.path.join(DATA_DIR, "salary_state.json")

# защита от повторного запуска daily_activity_payout
_LAST_PAYOUT_DATE = None
_LAST_REMINDER_DATE = None


# ============================================================
# СОСТОЯНИЕ ЗАРПЛАТ (JSON)
# ============================================================
def load_salary_state() -> dict:
    return load_json(SALARY_STATE_FILE, {"advance": "", "salary": ""})


def save_salary_state(state: dict):
    save_json(SALARY_STATE_FILE, state)


# ============================================================
# ЗАРПЛАТЫ И АВАНСЫ
# ============================================================
SALARY_ROLES = {
    1471844291595731016: {"advance": 300, "salary": 700},
    1513935883475226796: {"advance": 220, "salary": 500},
    1154757071330365490: {"advance": 220, "salary": 500},
    1471190371181789234: {"advance": 180, "salary": 400},
    1457964854441672806: {"advance": 150, "salary": 350},
}
SALARY_ROLE_ORDER = [
    1471844291595731016, 1513935883475226796, 1154757071330365490,
    1471190371181789234, 1457964854441672806,
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
            await add_dc(
                member.id, amount,
                f"{'Зарплата' if mode == 'salary' else 'Аванс'} по роли {top_role_id} (авто)",
                notify=True, log=False
            )
            stats[top_role_id] += 1
            awarded += 1
            total += amount
            await asyncio.sleep(0.4)
        except Exception as e:
            logger.error(f"Ошибка авто-начисления {mode} {member.id}: {e}")
            errors += 1

    try:
        sync_dc_to_json()
    except Exception:
        pass

    result_lines = []
    for role_id in SALARY_ROLE_ORDER:
        if stats[role_id] > 0:
            role = guild.get_role(role_id)
            role_name = role.name if role else str(role_id)
            result_lines.append(f"**{role_name}** – {stats[role_id]} чел.")
    result_text = "\n".join(result_lines) if result_lines else "Никто не получил."

    logger.info(f"Авто-выдача {mode}: {awarded} чел., {total} DC, ошибок: {errors}")
    await log_discord(
        title=f"💰 Авто-выдача {'зарплаты' if mode == 'salary' else 'аванса'}",
        description=(
            f"> **Тип:** {'Зарплата (29 число)' if mode == 'salary' else 'Аванс (15 число)'}\n"
            f"> **Сотрудников:** {awarded}\n"
            f"> **Всего выдано:** {total} DC\n"
            f"> **Ошибок:** {errors}\n"
            f"> **Распределение:**\n{result_text}"
        ),
        color=0x00ff00
    )


# ============================================================
# CATCH-UP: ДОГОНЯЮЩИЕ ВЫПЛАТЫ
# ============================================================
async def try_pay_advance() -> bool:
    """
    Аванс — 15 число.
    Окно срабатывания: 15-19 числа текущего месяца (5 дней grace).
    """
    state = load_salary_state()
    now = datetime.now(MSK)
    month_key = now.strftime("%Y-%m")

    if state.get("advance") == month_key:
        return False

    if now.day < 15 or now.day > 19:
        return False

    logger.info(f"💰 Авто-выдача аванса (month={month_key}, day={now.day})")
    await process_salary("advance")

    state["advance"] = month_key
    save_salary_state(state)
    return True


async def try_pay_salary() -> bool:
    """
    Зарплата — 29 число.
    Окно срабатывания: 29-31 текущего + 1-3 следующего.
    """
    state = load_salary_state()
    now = datetime.now(MSK)

    if now.day >= 29:
        month_key = now.strftime("%Y-%m")
    elif now.day <= 3:
        prev = now.replace(day=1) - timedelta(days=1)
        month_key = prev.strftime("%Y-%m")
    else:
        return False

    if state.get("salary") == month_key:
        return False

    logger.info(f"💰 Авто-выдача зарплаты (month={month_key}, day={now.day})")
    await process_salary("salary")

    state["salary"] = month_key
    save_salary_state(state)
    return True


# ============================================================
# БАННЕР / СЧЁТЧИК
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
        if not os.path.exists(base_path) or not os.path.exists(font_path):
            return
        img = Image.open(base_path).convert("RGBA")
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(font_path, 400)
        draw.text((594, 540), str(review_count), font=font, fill=(255, 255, 255), anchor="mm")
        img.save(output_path)
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild:
            return
        with open(output_path, "rb") as f:
            await guild.edit(banner=f.read())
        logger.info("Banner updated with %s reviews", review_count)
        if not silent:
            await log_discord(title="🖼️ Баннер обновлён",
                              description=f"> **Количество отзывов:** `{review_count}`",
                              color=0x00aaff)
    except Exception as e:
        logger.exception("Banner update error: %s", e)


# ============================================================
# ТАСКИ
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
    await bot.wait_until_ready()
    try:
        before = load_json(os.path.join(DATA_DIR, "daily_deal.json"), {})
        deal = refresh_daily_deal()
        after = load_json(os.path.join(DATA_DIR, "daily_deal.json"), {})
        if before.get("slot") != after.get("slot"):
            if after.get("flash_slot"):
                await start_flash_sale(bot)
            elif deal:
                logger.info(f"Товар дня: {deal['item_data']['name']}")
    except Exception as e:
        logger.exception(f"daily_deal_task error: {e}")


@tasks.loop(minutes=FLASH_SALE_CHECK_MINUTES)
async def flash_sale_task():
    await bot.wait_until_ready()
    try:
        data = load_flash_sale()
        now = time.time()
        if data.get("active"):
            if now - data.get("started_at", 0) >= FLASH_SALE_DURATION:
                ch_id = data.get("channel_id")
                msg_id = data.get("message_id")
                if ch_id and msg_id:
                    try:
                        ch = bot.get_channel(ch_id) or await bot.fetch_channel(ch_id)
                        msg = await ch.fetch_message(msg_id)
                        await msg.delete()
                    except Exception as e:
                        logger.warning(f"flash msg delete: {e}")
                save_flash_sale({"active": False, "item": None,
                                 "started_at": 0, "message_id": 0, "channel_id": 0})
                await log_discord(title="⚡ Flash sale завершён",
                                  description=f"> **Товар:** {data.get('item', {}).get('item_data', {}).get('name', '—')}",
                                  color=0xff6600)
    except Exception as e:
        logger.exception(f"flash_sale_task error: {e}")


# === АВАНС: проверка раз в минуту, окно 15-19 ===
@tasks.loop(minutes=1)
async def salary_advance_task():
    await bot.wait_until_ready()
    try:
        await try_pay_advance()
    except Exception as e:
        logger.exception(f"salary_advance_task: {e}")


# === ЗАРПЛАТА: проверка раз в минуту, окно 29-31 / 1-3 ===
@tasks.loop(minutes=1)
async def salary_main_task():
    await bot.wait_until_ready()
    try:
        await try_pay_salary()
    except Exception as e:
        logger.exception(f"salary_main_task: {e}")


# === НАПОМИНАНИЯ о неиспользованных товарах: 12:00 МСК ===
@tasks.loop(minutes=1)
async def unused_purchase_reminder_task():
    global _LAST_REMINDER_DATE
    await bot.wait_until_ready()
    try:
        now_msk = datetime.now(MSK)
        if now_msk.hour != 12 or now_msk.minute != 0:
            return
        today = now_msk.date()
        if _LAST_REMINDER_DATE == today:
            return
        _LAST_REMINDER_DATE = today
        await check_unused_purchases(bot)
    except Exception as e:
        logger.exception(f"unused_purchase_reminder_task: {e}")


# === ВЫПЛАТА ЗА АКТИВНОСТЬ: 00:00 МСК, раз в день ===
@tasks.loop(minutes=1)
async def daily_activity_payout_task():
    global _LAST_PAYOUT_DATE
    await bot.wait_until_ready()
    try:
        now_msk = datetime.now(MSK)
        if now_msk.hour != 0 or now_msk.minute != 0:
            return
        today = now_msk.date()
        if _LAST_PAYOUT_DATE == today:
            return
        _LAST_PAYOUT_DATE = today
        logger.info("Запуск выплаты за активность (00:00 МСК)")
        await daily_activity_payout()
    except Exception as e:
        logger.exception(f"daily_activity_payout_task: {e}")


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
            BuySelectView, QuestionTicketView,
        )
        from modules.commands_profile import send_profile_panel, ProfilePanelView, ProfileCardView
        from modules.commands_staff import (
            send_home_panel, send_tarology_panel, send_ticket_panel,
            send_work_panel, send_staff_panels,
            HomeView, TarologyView, WorkView,
            DCView, PromoView, AdminView,
        )

        bot.add_view(TicketPanelView())
        bot.add_view(TicketPaidView())
        bot.add_view(TicketView())
        bot.add_view(CoinsTicketButtons())
        bot.add_view(TicketRatingView())
        bot.add_view(SelectView())
        bot.add_view(CatalogTypeView())
        bot.add_view(CatalogView())
        bot.add_view(BuySelectView())
        bot.add_view(HomeView())
        bot.add_view(TarologyView())
        bot.add_view(ProfilePanelView())
        bot.add_view(ProfileCardView())
        bot.add_view(WorkView())
        bot.add_view(QuestionTicketView())
        bot.add_view(DCView())
        bot.add_view(PromoView())
        bot.add_view(AdminView())

        bot.loop.create_task(send_home_panel())
        bot.loop.create_task(send_tarology_panel())
        bot.loop.create_task(send_ticket_panel())
        bot.loop.create_task(send_profile_panel())
        bot.loop.create_task(send_work_panel())
        bot.loop.create_task(keep_voice_alive())
        bot.loop.create_task(send_actions_panel())
        bot.loop.create_task(send_staff_panels())

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
                logger.info(f"Роли обновлены для {len(counts)} пользователей")

        await update_review_counter(silent=False)

        # ⬇️ CATCH-UP: догоняем пропущенные выплаты
        try:
            paid_advance = await try_pay_advance()
            if paid_advance:
                logger.info("Catch-up: аванс выдан")
        except Exception as e:
            logger.exception(f"catch-up advance err: {e}")

        try:
            paid_salary = await try_pay_salary()
            if paid_salary:
                logger.info("Catch-up: зарплата выдана")
        except Exception as e:
            logger.exception(f"catch-up salary err: {e}")

        # Запуск тасок
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
        if not unused_purchase_reminder_task.is_running():
            unused_purchase_reminder_task.start()
        if not daily_activity_payout_task.is_running():
            daily_activity_payout_task.start()

        logger.info("%s is ready", bot.user)
        await log_discord(
            title="✅ Бот запустился",
            description=f"> **{bot.user}** готов и онлайн.\n> Роли обновлены для {len(counts) if counts else 0} пользователей.",
            color=0x00ff00
        )
    except Exception as e:
        logger.exception("on_ready error: %s", e)
        await log_discord(title="❌ Ошибка при запуске",
                          description=f"> **Ошибка:** `{str(e)}`", color=0xff0000)


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
                            logger.info("Подключился к голосовому: %s", voice_channel.name)
                    except Exception as e:
                        logger.debug("keep_voice_alive connect: %s", e)
        except Exception as e:
            logger.exception("keep_voice_alive loop: %s", e)
        await asyncio.sleep(60)


# ============================================================
# ПЕРЕСТРОЙКА ПРАВ ТИКЕТА
# ============================================================
async def reassign_ticket_permissions(channel: disnake.TextChannel, manager: disnake.Member):
    guild = channel.guild
    for role_id in CONFIG["TICKET_MANAGE_ROLES"]:
        role = guild.get_role(role_id)
        if role:
            await channel.set_permissions(role, overwrite=disnake.PermissionOverwrite(
                view_channel=True, send_messages=False, read_message_history=True,
                add_reactions=False, create_public_threads=False
            ))
    await channel.set_permissions(manager, overwrite=disnake.PermissionOverwrite(
        view_channel=True, send_messages=True, read_message_history=True,
        add_reactions=True, create_public_threads=True, embed_links=True, attach_files=True
    ))
    owner_id = get_ticket_owner(channel.id)
    if owner_id:
        owner = guild.get_member(owner_id)
        if owner and owner.id != manager.id:
            await channel.set_permissions(owner, overwrite=disnake.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                add_reactions=True, create_public_threads=True
            ))
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

    # Приветственный бонус 50 DC
    try:
        data = get_dc_cache(member.id)
        already_received = any(
            "Приветственный бонус" in (h.get("reason", "") or "")
            for h in data.get("history", [])
        )
        if not already_received:
            await add_dc(member.id, WELCOME_BONUS_DC,
                         "Приветственный бонус за регистрацию",
                         notify=False, log=False)
            try:
                embed1 = disnake.Embed(color=6776679)
                embed1.set_image(url=IMG_WELCOME)
                embed2 = disnake.Embed(
                    title="Добро пожаловать в Diamond Shop!",
                    description=(
                        f"> Привет, **{member.display_name}**! Мы начислили тебе "
                        f"**{WELCOME_BONUS_DC} DC** в качестве приветственного бонуса.\n\n"
                        f"**💎 Diamond Coin** — внутренняя валюта сервера. "
                        f"Зарабатывай её активностью и трать на товары.\n\n"
                        f"**Как заработать DC?**\n"
                        f"> • **Сообщения** — 1 DC за 10 сообщений\n"
                        f"> • **Голос** — 3 DC в час\n"
                        f"> • **Отзывы** — 15 DC за одобренный отзыв\n"
                        f"> • **Ежедневный бонус** — +3 DC с ролью «Клуб»\n"
                        f"> • **Ежедневный подарок** — от 10 до 30 DC каждый день, забирай в панели профиля\n"
                        f"> • **Казино** — испытай удачу в рулетке, блэкджеке и монетке\n\n"
                        f"**🛒 Где потратить?**\n"
                        f"> Загляни в <#1462136361711829053>, нажми кнопку **Каталог** "
                        f"и выбери валюту **Diamond Coin**.\n\n"
                        f"**🎁 Забирай ежедневный подарок!**\n"
                        f"> В панели профиля <#1540018373503483934> выбери пункт "
                        f"**«Ежедневный подарок»** — каждый день получай от **10 до 30 DC**. "
                        f"Кулдаун — ровно 24 часа с момента получения.\n\n"
                        f"**📖 С чего начать?**\n"
                        f"> Справочник — <#1532398684074016870>.\n"
                        f"> Удачи и приятных покупок!"
                    ),
                    color=6776679,
                    timestamp=datetime.now(timezone.utc)
                )
                embed2.set_image(url=IMG_STRIPE)
                await member.send(embeds=[embed1, embed2])
            except Exception as e:
                logger.warning(f"Не удалось отправить приветственное ЛС {member.id}: {e}")

            await log_discord(
                title="🎁 Приветственный бонус",
                description=f"> **Пользователь:** {member.mention}\n> **Начислено:** `+{WELCOME_BONUS_DC} DC`",
                color=0xffaa00
            )
    except Exception as e:
        logger.exception(f"welcome bonus err: {e}")

    # Инвайты
    guild = member.guild
    snapshot_before = {row["invite_code"]: row for row in db.execute(
        "SELECT * FROM invites_snapshot WHERE guild_id=?", (guild.id,)).fetchall()}
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
    if message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        return
    content = message.content or "[Нет текста]"
    if len(content) > 1024:
        content = content[:1021] + "..."
    await log_discord(
        title="🗑️ Удалено сообщение",
        description=f"> **Автор:** {message.author.mention}\n> **Канал:** {message.channel.mention}\n> **Содержание:**\n```\n{content}\n```",
        color=0xff6600
    )


@bot.event
async def on_bulk_message_delete(messages: List[disnake.Message]):
    if not messages:
        return
    channel = messages[0].channel
    if channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        asyncio.create_task(schedule_banner_update())
        return
    await log_discord(
        title="🗑️ Массовое удаление",
        description=f"> **Канал:** {channel.mention}\n> **Количество:** `{len(messages)}`",
        color=0xff6600
    )


@bot.event
async def on_message_edit(before: disnake.Message, after: disnake.Message):
    if before.author.bot or before.content == after.content:
        return
    if before.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        return
    b = (before.content or "[Нет]")[:500]
    a = (after.content or "[Нет]")[:500]
    await log_discord(
        title="✏️ Изменено сообщение",
        description=f"> **Автор:** {before.author.mention}\n> **Канал:** {before.channel.mention}\n> **Было:**\n```\n{b}\n```\n> **Стало:**\n```\n{a}\n```",
        color=0xffff00
    )


@bot.event
async def on_guild_channel_create(channel: disnake.abc.GuildChannel):
    await log_discord(title="➕ Создан канал",
                      description=f"> **{channel.mention}** (`{channel.name}`)\n> **ID:** `{channel.id}`",
                      color=0x00ff00)


@bot.event
async def on_guild_channel_delete(channel: disnake.abc.GuildChannel):
    await log_discord(title="➖ Удалён канал",
                      description=f"> **{channel.name}**\n> **ID:** `{channel.id}`",
                      color=0xff0000)


@bot.event
async def on_guild_channel_update(before, after):
    if before.name != after.name:
        await log_discord(title="✏️ Изменён канал",
                          description=f"> **{after.mention}**\n> **Было:** `{before.name}`\n> **Стало:** `{after.name}`",
                          color=0xffff00)


@bot.event
async def on_guild_role_create(role: disnake.Role):
    await log_discord(title="➕ Создана роль",
                      description=f"> **{role.mention}** (`{role.name}`)\n> **ID:** `{role.id}`",
                      color=0x00ff00)


@bot.event
async def on_guild_role_delete(role: disnake.Role):
    await log_discord(title="➖ Удалена роль",
                      description=f"> **{role.name}**\n> **ID:** `{role.id}`",
                      color=0xff0000)


@bot.event
async def on_guild_role_update(before: disnake.Role, after: disnake.Role):
    if before.name != after.name:
        await log_discord(title="✏️ Изменена роль",
                          description=f"> **{after.mention}**\n> **Было:** `{before.name}`\n> **Стало:** `{after.name}`",
                          color=0xffff00)


@bot.event
async def on_invite_create(invite: disnake.Invite):
    db.execute("REPLACE INTO invites_snapshot VALUES (?, ?, ?, ?)",
               (invite.code, invite.guild.id, invite.uses,
                invite.inviter.id if invite.inviter else None))
    db.commit()
    await log_discord(title="📨 Создан инвайт",
                      description=f"> **Код:** `{invite.code}`\n> **Создатель:** {invite.inviter.mention if invite.inviter else '?'}",
                      color=0x00aaff)


@bot.event
async def on_invite_delete(invite: disnake.Invite):
    db.execute("DELETE FROM invites_snapshot WHERE invite_code=?", (invite.code,))
    db.commit()
    await log_discord(title="🗑️ Удалён инвайт", description=f"> **Код:** `{invite.code}`", color=0xff6600)


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
                logger.error(f"reaction role: {e}")


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
                    logger.error(f"reaction remove: {e}")


@bot.event
async def on_interaction(inter: disnake.MessageInteraction):
    from modules.commands_tickets import handle_interaction
    await handle_interaction(inter)
    await handle_flash_interaction(inter)


@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return

    is_guild_text = isinstance(message.channel, disnake.TextChannel)

    if is_guild_text and message.channel.category:
        cat_id = message.channel.category.id
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
                    embed.set_image(url=IMG_STRIPE)
                    await message.channel.send(embed=embed)
                    await log_discord(
                        title="📌 Менеджер назначен",
                        description=f"> **Тикет:** {message.channel.mention}\n> **Менеджер:** {message.author.mention}",
                        color=0x00aaff,
                        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
                    )
                    await reassign_ticket_permissions(message.channel, message.author)

    if is_guild_text:
        from modules.dc import add_message_dc
        if len(message.content.strip()) >= CONFIG["MIN_MESSAGE_LENGTH"]:
            if message.channel.id != CONFIG["REVIEW_COUNT_CHANNEL"]:
                await add_message_dc(message.author.id)

    # Обработка отзывов
    if is_guild_text and message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        user_id = message.author.id
        now = time.time()
        text = (message.content or "").strip()

        last = _REVIEW_COOLDOWN.get(user_id, 0)
        if now - last < REVIEW_COOLDOWN_SECONDS:
            left = int(REVIEW_COOLDOWN_SECONDS - (now - last))
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await message.author.send(
                    f"⏳ **Слишком часто.**\n"
                    f"> Ты уже оставил отзыв недавно.\n"
                    f"> Подожди ещё **{left} сек** перед следующим."
                )
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
        except Exception:
            pass

        counts = load_json(FILES["review_counts"], {})
        counts[str(user_id)] = counts.get(str(user_id), 0) + 1
        save_json(FILES["review_counts"], counts)

        try:
            await add_dc(user_id, REVIEW_REWARD_DC, "Отзыв о покупке",
                         notify=False, log=False)
        except Exception as e:
            logger.exception(f"DC за отзыв: {e}")

        if isinstance(message.author, disnake.Member):
            try:
                await update_user_roles(message.author, counts[str(user_id)], keep_pka=True)
            except Exception as e:
                logger.exception(f"update roles: {e}")

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
            dm_embed.set_image(url=IMG_STRIPE)
            await message.author.send(embed=dm_embed)
        except Exception:
            pass

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
                # лог не пишем — иначе спам в канале
