# -*- coding: utf-8 -*-
import os
import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import List
import disnake
from disnake.ext import commands, tasks
from disnake import PartialEmoji, ButtonStyle

from core.utils import (
    CONFIG, FILES, logger, db, cur,
    load_json, save_json, now_ts,
    update_user_roles, sync_invites,
    has_admin_command_roles,
    log_discord,
    BASE_DIR, ADD_DIR, DATA_DIR, CATALOG_DIR, ACTIONS_DIR,
    get_dc_cache, save_dc_cache, sync_dc_to_json,
)

from modules.actions import refresh_daily_deal
from modules.dc import (
    add_dc, get_user_balance, load_shop_catalog,
    get_user_dc_data, save_user_dc_data,
    daily_bonus, check_unused_purchases, daily_activity_payout,
    CLAN_SHARE,
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

_REVIEW_COOLDOWN = {}
REVIEW_COOLDOWN_SECONDS = 120
REVIEW_MIN_LENGTH = 3

REVIEW_REWARDS = {
    "bronze":    20,
    "silver":    35,
    "gold":      55,
    "diamond":   75,
    "crystalis": 85,
    "pka":       100,
}
REVIEW_REWARD_DEFAULT = 15

def get_review_reward(count: int) -> int:
    if count >= 26: return REVIEW_REWARDS["pka"]
    if count >= 21: return REVIEW_REWARDS["crystalis"]
    if count >= 16: return REVIEW_REWARDS["diamond"]
    if count >= 11: return REVIEW_REWARDS["gold"]
    if count >= 6:  return REVIEW_REWARDS["silver"]
    if count >= 1:  return REVIEW_REWARDS["bronze"]
    return REVIEW_REWARD_DEFAULT

WELCOME_BONUS_DC = 50
MSK = timezone(timedelta(hours=3))

IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"
IMG_ORDER_PAID = "https://cdn.discordapp.com/attachments/1527006158282555412/1551608259230695595/image.png?ex=6ab2974c&is=6ab145cc&hm=a6e78b3cb2686d6c61fcf7e618564c04c557856b1af501eb26bf9015793e8a93&"
IMG_UNUSED = "https://cdn.discordapp.com/attachments/1527006158282555412/1551572210811011142/image.png?ex=6ab275b9&is=6ab12439&hm=7d8e471545619f792391577a7a0bf5335995f759c5c8b09534ac840b881fc806&"
IMG_WELCOME = "https://cdn.discordapp.com/attachments/1527006158282555412/1556733201970626732/image.png?backend=b2&ex=6ac5e506&is=6ac49386&hm=574cd55b0658621f44bee53d8ed386f3b7e7372997e73326c327efef482daca5&"

SALARY_STATE_FILE = os.path.join(DATA_DIR, "salary_state.json")

_LAST_PAYOUT_DATE = None
_LAST_REMINDER_DATE = None
_LAST_BONUS_DATE = None

ADVERTISER_PANEL_CHANNEL_ID = 1557405478890373210

def load_salary_state() -> dict:
    return load_json(SALARY_STATE_FILE, {"advance": "", "salary": ""})

def save_salary_state(state: dict):
    save_json(SALARY_STATE_FILE, state)

SALARY_ROLES = {
    1471844291595731016: {"advance": 750, "salary": 1750},
    1513935883475226796: {"advance": 550, "salary": 1250},
    1154757071330365490: {"advance": 550, "salary": 1250},
    1457964854441672806: {"advance": 375, "salary": 875},
}

SALARY_ROLE_ORDER = [
    1471844291595731016,
    1513935883475226796,
    1154757071330365490,
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
            await add_dc(
                member.id, amount,
                f"{'Зарплата' if mode == 'salary' else 'Аванс'} по роли {top_role_id} (авто)",
                notify=True, log=False
            )
            stats[top_role_id] += 1
            awarded += 1
            total += amount

            try:
                from clan.achievements import check_and_unlock
                await check_and_unlock(member.id, "staff_salary", value=1, bot=bot)
            except Exception as e:
                logger.warning(f"staff_salary ach: {e}")

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

async def try_pay_advance() -> bool:
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

def _process_banner_gif(gif_path: str, font_path: str, review_count: int):
    from PIL import Image, ImageDraw, ImageFont, ImageSequence
    import io

    img = Image.open(gif_path)
    original_frames = [frame.convert("RGBA") for frame in ImageSequence.Iterator(img)]
    original_duration = img.info.get('duration', 100)

    configs = [
        {"w": 960, "h": 540, "colors": 128, "step": 1},
        {"w": 960, "h": 540, "colors": 64,  "step": 1},
        {"w": 960, "h": 540, "colors": 64,  "step": 2},
        {"w": 800, "h": 450, "colors": 64,  "step": 2},
        {"w": 640, "h": 360, "colors": 64,  "step": 2},
        {"w": 640, "h": 360, "colors": 32,  "step": 3},
        {"w": 480, "h": 270, "colors": 32,  "step": 3},
    ]

    for cfg in configs:
        frames = []
        for i, frame in enumerate(original_frames):
            if i % cfg["step"] != 0:
                continue

            f = frame.copy()
            f.thumbnail((cfg["w"], cfg["h"]), Image.LANCZOS)

            draw = ImageDraw.Draw(f)

            font_size = int(f.height * 0.37)
            font = ImageFont.truetype(font_path, font_size)
            x = int(f.width * 0.31)
            y = int(f.height * 0.50)

            draw.text((x + 4, y + 4), str(review_count), font=font, fill=(0, 0, 0, 150), anchor="mm")
            draw.text((x, y), str(review_count), font=font, fill=(255, 255, 255), anchor="mm")

            frames.append(f.convert("P", palette=Image.ADAPTIVE, colors=cfg["colors"]))

        if not frames:
            continue

        buf = io.BytesIO()
        frames[0].save(
            buf, format="GIF", save_all=True, append_images=frames[1:],
            loop=0, duration=original_duration * cfg["step"],
            optimize=True, disposal=2
        )
        gif_bytes = buf.getvalue()
        size_mb = len(gif_bytes) / (1024 * 1024)

        logger.info(
            f"Тест сжатия {cfg['w']}x{cfg['h']}, {cfg['colors']} цв., "
            f"шаг {cfg['step']}: {size_mb:.2f} MB"
        )

        if size_mb <= 9.5:
            return gif_bytes, cfg

    return None, None

async def update_server_banner(review_count: int, silent: bool = False):
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        gif_paths = [
            os.path.join(ADD_DIR, "banner.gif"),
            os.path.join(ADD_DIR, "copy_5B91850B-07EB-4E52-8E1C-96BDDEDE928C.gif")
        ]

        font_path = os.path.join(ADD_DIR, "Fredoka_One.ttf")

        for gif_path in gif_paths:
            if os.path.exists(gif_path) and os.path.exists(font_path):
                try:
                    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
                    if not guild:
                        return

                    best_gif_bytes, used_config = await asyncio.to_thread(
                        _process_banner_gif, gif_path, font_path, review_count
                    )

                    if best_gif_bytes:
                        await guild.edit(banner=best_gif_bytes)
                        logger.info(
                            f"✅ Баннер обновлён (GIF+текст, сжатие: "
                            f"{used_config['w']}x{used_config['h']}, шаг {used_config['step']})"
                        )

                        if not silent:
                            await log_discord(
                                title="🖼️ Анимированный баннер обновлён",
                                description=(
                                    f"> **Файл:** `{os.path.basename(gif_path)}`\n"
                                    f"> **Количество отзывов:** `{review_count}`\n"
                                    f"> **Сжатие:** {used_config['w']}x{used_config['h']} "
                                    f"({used_config['colors']} цв.)"
                                ),
                                color=0x00aaff
                            )
                        return
                    else:
                        logger.error(
                            "update_server_banner: все варианты сжатия GIF весят > 9.5MB"
                        )

                except disnake.HTTPException as e:
                    logger.error(f"❌ Discord отклонил GIF: {e.text if hasattr(e, 'text') else e}")
                except Exception as e:
                    logger.exception(f"update_server_banner: ошибка при обработке GIF: {e}")

        base_path = os.path.join(ADD_DIR, "banner.png")
        output_path = os.path.join(DATA_DIR, "banner_ready.png")

        if not os.path.exists(base_path) or not os.path.exists(font_path):
            logger.warning("update_server_banner: banner.png или шрифт не найдены")
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

        logger.info("Баннер обновлён (статичный PNG)")
        if not silent:
            await log_discord(
                title="🖼️ Баннер обновлён",
                description=f"> **Количество отзывов:** `{review_count}`",
                color=0x00aaff
            )

    except Exception as e:
        logger.exception("Banner update error: %s", e)

@tasks.loop(hours=24)
async def review_counter_task():
    await bot.wait_until_ready()
    await update_review_counter(silent=False)

@tasks.loop(minutes=1)
async def daily_bonus_task():
    global _LAST_BONUS_DATE
    await bot.wait_until_ready()
    try:
        now_msk = datetime.now(MSK)
        if now_msk.hour != 23 or now_msk.minute != 59:
            return
        today = now_msk.date()
        if _LAST_BONUS_DATE == today:
            return
        _LAST_BONUS_DATE = today
        logger.info("Запуск ежедневного клубного бонуса (23:59 МСК)")
        await daily_bonus()
    except Exception as e:
        logger.exception(f"daily_bonus_task: {e}")

@tasks.loop(minutes=5)
async def daily_deal_task():
    await bot.wait_until_ready()
    try:
        before = load_json(os.path.join(DATA_DIR, "daily_deal.json"), {})
        deal = refresh_daily_deal()
        after = load_json(os.path.join(DATA_DIR, "daily_deal.json"), {})
        if before.get("slot") != after.get("slot"):
            if deal:
                logger.info(f"Товар дня: {deal['item_data']['name']}")
                try:
                    from bonus.core import announce_deal_change
                    await announce_deal_change(bot, deal)
                except Exception as e:
                    logger.warning(f"deal announce: {e}")
    except Exception as e:
        logger.exception(f"daily_deal_task error: {e}")

@tasks.loop(minutes=1)
async def salary_advance_task():
    await bot.wait_until_ready()
    try:
        await try_pay_advance()
    except Exception as e:
        logger.exception(f"salary_advance_task: {e}")

@tasks.loop(minutes=1)
async def salary_main_task():
    await bot.wait_until_ready()
    try:
        await try_pay_salary()
    except Exception as e:
        logger.exception(f"salary_main_task: {e}")

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

@bot.event
async def on_ready():
    try:
        await bot.change_presence(activity=disnake.Game(name="Магазин и экономика"))

        try:
            from modules.giveaways import setup_giveaways
            setup_giveaways(bot)
            logger.info("🎁 Модуль розыгрышей подключён")
        except Exception as e:
            logger.exception(f"giveaways init err: {e}")

        from modules.commands_tickets import (
            TicketPanelView, TicketPaidView, TicketView, CoinsTicketButtons,
            SelectView, CatalogTypeView, CatalogView,
            QuestionTicketView,
        )
        from modules.tickets import ReceiptView
        from modules.commands_profile import (
            send_profile_panel, ProfilePanelView, ProfileCardView,
        )
        from modules.commands_staff import (
            send_tarology_panel, send_ticket_panel,
            send_work_panel, send_staff_panels,
            TarologyView, WorkView,
            DCView, PromoView, AdminView,
        )

        bot.add_view(TicketPanelView())
        bot.add_view(TicketPaidView())
        bot.add_view(TicketView())
        bot.add_view(CoinsTicketButtons())
        bot.add_view(SelectView())
        bot.add_view(CatalogTypeView())
        bot.add_view(CatalogView())
        bot.add_view(ReceiptView())
        bot.add_view(TarologyView())
        bot.add_view(ProfilePanelView())
        bot.add_view(ProfileCardView())
        bot.add_view(WorkView())
        bot.add_view(QuestionTicketView())
        bot.add_view(DCView())
        bot.add_view(PromoView())
        bot.add_view(AdminView())

        bot.loop.create_task(send_tarology_panel())
        bot.loop.create_task(send_ticket_panel())
        bot.loop.create_task(send_profile_panel())
        bot.loop.create_task(send_work_panel())
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

        bot.loop.create_task(update_review_counter(silent=False))

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

        try:
            from clan import init_clan_league
            from clan.panels import (
                send_clan_pool_panel, send_clan_season_panel,
                send_clan_games_panel, send_clan_admin_panel
            )
            init_clan_league(bot)
            bot.loop.create_task(send_clan_pool_panel(bot))
            bot.loop.create_task(send_clan_season_panel(bot))
            bot.loop.create_task(send_clan_games_panel(bot))
            logger.info("Клан-лига инициализирована (с кейсами)")

            try:
                from clan.core import (
                    distribute_all_club_members, prune_ineligible_clan_members
                )
                guild_for_clan = bot.get_guild(int(CONFIG["GUILD_ID"]))
                if guild_for_clan:
                    pruned = await prune_ineligible_clan_members(guild_for_clan)
                    logger.info(
                        f"Чистка кланов: removed={pruned['removed']}, "
                        f"seeded={pruned['seeded']}, checked={pruned['checked']}"
                    )
                    result = distribute_all_club_members(guild_for_clan)
                    logger.info(f"Распределение кланов: assigned={result['assigned']}, skipped={result['skipped']}")
            except Exception as e:
                logger.exception(f"auto-distribute clan err: {e}")

            try:
                from clan.achievements import unlock_achievement, CREATOR_USER_ID
                await unlock_achievement(CREATOR_USER_ID, "creator", bot=bot, notify=False)
                logger.info("👑 Достижение Создателя проверено")
            except Exception as e:
                logger.warning(f"creator ach: {e}")

        except Exception as e:
            logger.exception(f"clan league init err: {e}")

        try:
            from pet import init_pet_league
            from pet.core import start_pet_tasks
            init_pet_league(bot)
            start_pet_tasks(bot)
            logger.info("🐾 Питомцы подключены")
        except Exception as e:
            logger.exception(f"init pets: {e}")

        try:
            from bonus import init_bonus
            from bonus.views import BonusPanelView, build_panel_embeds as build_bonus_embeds
            from bonus.core import BONUS_CHANNEL_ID

            init_bonus(bot)
            bot.add_view(BonusPanelView())

            async def _post_bonus_panel():
                await asyncio.sleep(10)
                try:
                    ch = bot.get_channel(BONUS_CHANNEL_ID)
                    if not ch:
                        try:
                            ch = await bot.fetch_channel(BONUS_CHANNEL_ID)
                        except Exception as e:
                            logger.warning(f"bonus panel fetch: {e}")
                            return
                    if not ch:
                        return
                    async for m in ch.history(limit=30):
                        if m.author == bot.user and m.components:
                            try:
                                await m.delete()
                            except Exception:
                                pass
                            break
                    await ch.send(embeds=build_bonus_embeds(), view=BonusPanelView())
                    logger.info(f"🎁 Бонус-панель отправлена в {ch.name}")
                except Exception as e:
                    logger.exception(f"_post_bonus_panel: {e}")

            bot.loop.create_task(_post_bonus_panel())
            logger.info("🎁 Бонус-панель инициализирована (Рефералы + Адвайтеры)")
        except Exception as e:
            logger.exception(f"init bonus: {e}")

        if not review_counter_task.is_running():
            review_counter_task.start()
        if not daily_bonus_task.is_running():
            daily_bonus_task.start()
        if not daily_deal_task.is_running():
            daily_deal_task.start()
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

    try:
        from clan.achievements import unlock_achievement
        await unlock_achievement(member.id, "newbie", bot=bot)
    except Exception as e:
        logger.warning(f"newbie ach: {e}")

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
                        f"> • **Отзывы** — от 20 до 100 DC в зависимости от роли покупателя\n"
                        f"> • **Ежедневный бонус** — +10 DC с ролью «Клуб» (нужна активность за день)\n"
                        f"> • **Ежедневный подарок** — от 10 до 30 DC каждый день, забирай в панели профиля\n"
                        f"> • **Питомцы** — заведи питомца, он приносит 1–20 DC в час\n"
                        f"> • **Казино** — испытай удачу в рулетке, блэкджеке и монетке\n\n"
                        f"**🛒 Где потратить?**\n"
                        f"> Загляни в <#1462136361711829053>, нажми кнопку **Каталог** "
                        f"и выбери валюту **Diamond Coin**.\n\n"
                        f"**🎁 Забирай ежедневный подарок!**\n"
                        f"> В панели профиля <#1540018373503483934> выбери пункт "
                        f"**«Ежедневный подарок»** — каждый день получай от **10 до 30 DC**. "
                        f"Кулдаун — ровно 24 часа с момента получения.\n\n"
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

    guild = member.guild
    snapshot_before = {
        row["invite_code"]: row
        for row in db.execute(
            "SELECT * FROM invites_snapshot WHERE guild_id=?", (guild.id,)
        ).fetchall()
    }
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
        db.execute(
            "REPLACE INTO invites_snapshot (invite_code, guild_id, uses, inviter_id) "
            "VALUES (?, ?, ?, ?)",
            (inv.code, guild.id, inv.uses, inv.inviter.id if inv.inviter else None)
        )
    if not used_invite or not used_invite.inviter:
        db.commit()
        return
    inviter_id = used_invite.inviter.id
    is_bot = 1 if member.bot else 0
    joined_at = now_ts()

    ref_user_id = None
    try:
        from bonus.core import get_user_by_ref_code
        ref_user_id = get_user_by_ref_code(used_invite.code)
    except Exception as e:
        logger.warning(f"get_user_by_ref_code on join: {e}")

    db.execute(
        "INSERT INTO invites "
        "(guild_id, inviter_id, member_id, joined_at, is_bot, invite_code, ref_user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (guild.id, inviter_id, member.id, joined_at, is_bot,
         used_invite.code, ref_user_id)
    )
    db.commit()

    await log_discord(
        title="📨 Использован инвайт",
        description=(
            f"> **Пользователь:** {member.mention}\n"
            f"> **Пригласил:** <@{inviter_id}>\n"
            f"> **Код:** `{used_invite.code}`"
            + (f"\n> **Реферал:** <@{ref_user_id}>" if ref_user_id else "")
        ),
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
    db.execute(
        "UPDATE invites SET left_at=? WHERE guild_id=? AND member_id=? AND left_at IS NULL",
        (now_ts(), guild.id, member.id)
    )
    row = db.execute(
        "SELECT joined_at FROM invites WHERE guild_id=? AND member_id=? "
        "ORDER BY joined_at DESC LIMIT 1",
        (guild.id, member.id)
    ).fetchone()
    if row and (now_ts() - row["joined_at"]) < 600:
        db.execute(
            "UPDATE invites SET is_fake=1 WHERE guild_id=? AND member_id=? AND is_fake=0",
            (guild.id, member.id)
        )
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
            try:
                from clan.core import CLUB_ROLE_ID, assign_user_to_clan, get_user_clan
                if any(r.id == CLUB_ROLE_ID for r in added) and not get_user_clan(after.id):
                    assign_user_to_clan(after.id, after.guild)
            except Exception as e:
                logger.warning(f"clan auto-assign on role: {e}")

            try:
                from clan.achievements import check_and_unlock
                role_ids = CONFIG["ROLE_IDS"]
                role_map = {
                    role_ids["bronze"]: "bronze",
                    role_ids["silver"]: "silver",
                    role_ids["gold"]: "gold",
                    role_ids["diamond"]: "diamond",
                    role_ids["crystalis"]: "crystalis",
                    role_ids["pka"]: "pka",
                }
                for r in added:
                    if r.id in role_map:
                        await check_and_unlock(after.id, "role", role_key=role_map[r.id], bot=bot)
            except Exception as e:
                logger.warning(f"role ach: {e}")

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
    await log_discord(title="🗑️ Удалён инвайт",
                      description=f"> **Код:** `{invite.code}`",
                      color=0xff6600)

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
    try:
        from clan.panels import handle_clan_interaction
        await handle_clan_interaction(inter)
    except Exception as e:
        logger.warning(f"clan interaction err: {e}")

@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot:
        return

    is_guild_text = isinstance(message.channel, disnake.TextChannel)

    if is_guild_text:
        from modules.dc import add_message_dc
        if len(message.content.strip()) >= CONFIG["MIN_MESSAGE_LENGTH"]:
            if message.channel.id != CONFIG["REVIEW_COUNT_CHANNEL"]:
                await add_message_dc(message.author.id)
                try:
                    from clan.achievements import unlock_achievement
                    await unlock_achievement(message.author.id, "first_message", bot=bot, notify=False)
                except Exception:
                    pass

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

        new_count = counts[str(user_id)]

        if isinstance(message.author, disnake.Member):
            try:
                await update_user_roles(message.author, new_count, keep_pka=True)
            except Exception as e:
                logger.exception(f"update roles: {e}")

        reward = get_review_reward(new_count)

        pet_mult = 1.0
        try:
            from pet.core import get_review_bonus
            pet_mult = get_review_bonus(user_id)
            if pet_mult > 1.0:
                reward = int(reward * pet_mult)
        except Exception as e:
            logger.debug(f"pet review bonus: {e}")

        try:
            await add_dc(user_id, reward, "Отзыв о покупке",
                         notify=False, log=False, to_clan_pool=True)
        except Exception as e:
            logger.exception(f"DC за отзыв: {e}")

        try:
            from pet.core import add_pet_xp
            await add_pet_xp(user_id, 25, "review")
        except Exception as e:
            logger.debug(f"pet xp review: {e}")

        try:
            from clan.achievements import check_and_unlock
            await check_and_unlock(user_id, "reviews", value=new_count, bot=bot)
        except Exception as e:
            logger.warning(f"reviews ach: {e}")

        try:
            from clan.quests import on_review_quest_hook
            await on_review_quest_hook(user_id)
        except Exception as e:
            logger.warning(f"clan review hook: {e}")

        # 👇 ВЫПЛАТА ПРИЗОВ ЗА ШАБЛОННЫЕ РОЗЫГРЫШИ (после отзыва)
        try:
            from modules.giveaways import process_pending_payouts
            paid = await process_pending_payouts(bot, user_id)
            if paid > 0:
                logger.info(f"💰 Призы за розыгрыши выплачены: {user_id} → {paid} DC")
        except Exception as e:
            logger.warning(f"giveaway payout after review: {e}")

        try:
            reward_line = f"> **Начислено:** `+{reward} DC`"
            if pet_mult > 1.0:
                reward_line += f" (бонус питомца ×{pet_mult:.2f})"

            dm_embed = disnake.Embed(
                title="✅ Отзыв принят!",
                description=(
                    f"> Спасибо за отзыв!\n\n"
                    f"> **Всего отзывов:** `{new_count}`\n"
                    f"{reward_line}\n"
                    f"> **Следующий отзыв:** можно оставить через 2 минуты"
                ),
                color=0x2ecc71,
                timestamp=datetime.now(timezone.utc)
            )
            dm_embed.set_image(url=IMG_STRIPE)
            await message.author.send(embed=dm_embed)
        except Exception:
            pass

        log_desc = (
            f"> **Пользователь:** {message.author.mention}\n"
            f"> **Всего отзывов:** `{new_count}`\n"
            f"> **Начислено:** `+{reward} DC`\n"
        )
        if pet_mult > 1.0:
            log_desc += f"> **Бонус питомца:** `×{pet_mult:.2f}`\n"
        log_desc += (
            f"> **Текст:** {text[:200]}\n"
            f"> **Ссылка:** [перейти]({message.jump_url})"
        )

        await log_discord(
            title="📝 Отзыв принят",
            description=log_desc,
            color=0x00ff00
        )
        await update_review_counter(silent=False)
        return

    if is_guild_text:
        try:
            from clan.quests import on_message_quest_hook
            await on_message_quest_hook(message)
        except Exception as e:
            logger.warning(f"clan quest hook msg: {e}")

    await bot.process_commands(message)


voice_track = {}

@bot.event
async def on_voice_state_update(member: disnake.Member, before: disnake.VoiceState, after: disnake.VoiceState):
    if member.bot:
        return
    user_id = member.id
    if after.channel and (before.channel is None or before.channel != after.channel):
        voice_track[user_id] = (after.channel.id, int(time.time()))
        try:
            from modules.dc import touch_activity
            touch_activity(user_id)
        except Exception as e:
            logger.warning(f"touch_activity voice: {e}")
        try:
            from clan.achievements import unlock_achievement
            await unlock_achievement(user_id, "first_voice", bot=bot, notify=False)
        except Exception:
            pass
    elif before.channel and (after.channel is None or after.channel != before.channel):
        if user_id in voice_track:
            channel_id, join_time = voice_track.pop(user_id)
            duration = int(time.time()) - join_time
            if duration > 60:
                from modules.dc import add_voice_dc
                await add_voice_dc(user_id, duration)
                try:
                    from clan.quests import on_voice_quest_hook
                    await on_voice_quest_hook(user_id, duration)
                except Exception as e:
                    logger.warning(f"clan voice hook: {e}")
                try:
                    from pet.core import add_pet_xp
                    hours = max(duration // 3600, 1)
                    await add_pet_xp(user_id, 5 * hours, "voice")
                except Exception as e:
                    logger.debug(f"pet xp voice: {e}")
