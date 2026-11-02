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
    CONFIG, FILES, logger, db, cur, load_json, save_json, now_ts, update_user_roles, sync_invites,
    has_admin_command_roles, log_discord, BASE_DIR, ADD_DIR, DATA_DIR, CATALOG_DIR, ACTIONS_DIR,
    get_dc_cache, save_dc_cache, sync_dc_to_json,
)
from modules.actions import refresh_daily_deal
from modules.dc import (
    add_dc, get_user_balance, load_shop_catalog, get_user_dc_data, save_user_dc_data,
    daily_bonus, check_unused_purchases, daily_activity_payout, CLAN_SHARE,
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
REVIEW_REWARDS = {"bronze": 20, "silver": 35, "gold": 55, "diamond": 75, "crystalis": 85, "pka": 100}
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
_LAST_PAYOUT_DATE, _LAST_REMINDER_DATE, _LAST_BONUS_DATE = None, None, None

def load_salary_state() -> dict: return load_json(SALARY_STATE_FILE, {"advance": "", "salary": ""})
def save_salary_state(state: dict): save_json(SALARY_STATE_FILE, state)

SALARY_ROLES = {
    1471844291595731016: {"advance": 750, "salary": 1750},
    1513935883475226796: {"advance": 550, "salary": 1250},
    1154757071330365490: {"advance": 550, "salary": 1250},
    1457964854441672806: {"advance": 375, "salary": 875},
}
SALARY_ROLE_ORDER = [1471844291595731016, 1513935883475226796, 1154757071330365490, 1457964854441672806]

async def process_salary(mode: str):
    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild: return
    total, awarded, errors, stats = 0, 0, 0, {role_id: 0 for role_id in SALARY_ROLE_ORDER}
    for member in guild.members:
        if member.bot: continue
        top_role_id = next((role_id for role_id in SALARY_ROLE_ORDER if member.get_role(role_id)), None)
        if not top_role_id: continue
        amount = SALARY_ROLES[top_role_id][mode]
        if amount <= 0: continue
        try:
            await add_dc(member.id, amount, f"{'Зарплата' if mode == 'salary' else 'Аванс'} по роли {top_role_id} (авто)", notify=True, log=False)
            stats[top_role_id] += 1; awarded += 1; total += amount
            try:
                from clan.achievements import check_and_unlock
                await check_and_unlock(member.id, "staff_salary", value=1, bot=bot)
            except Exception: pass
            await asyncio.sleep(0.4)
        except Exception as e: logger.error(f"Ошибка авто-начисления {mode} {member.id}: {e}"); errors += 1
    try: sync_dc_to_json()
    except Exception: pass
    result_lines = [f"**{(guild.get_role(role_id).name if guild.get_role(role_id) else str(role_id))}** – {stats[role_id]} чел." for role_id in SALARY_ROLE_ORDER if stats[role_id] > 0]
    await log_discord(title=f"💰 Авто-выдача {'зарплаты' if mode == 'salary' else 'аванса'}", description=f"> **Тип:** {'Зарплата (29 число)' if mode == 'salary' else 'Аванс (15 число)'}\n> **Сотрудников:** {awarded}\n> **Всего выдано:** {total} DC\n> **Ошибок:** {errors}\n> **Распределение:**\n" + ("\n".join(result_lines) if result_lines else "Никто не получил."), color=0x00ff00)

async def try_pay_advance() -> bool:
    state = load_salary_state(); now = datetime.now(MSK); month_key = now.strftime("%Y-%m")
    if state.get("advance") == month_key or now.day < 15 or now.day > 19: return False
    await process_salary("advance"); state["advance"] = month_key; save_salary_state(state); return True

async def try_pay_salary() -> bool:
    state = load_salary_state(); now = datetime.now(MSK)
    if now.day >= 29: month_key = now.strftime("%Y-%m")
    elif now.day <= 3: month_key = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    else: return False
    if state.get("salary") == month_key: return False
    await process_salary("salary"); state["salary"] = month_key; save_salary_state(state); return True

_banner_last_update = 0.0
async def schedule_banner_update():
    global _banner_last_update
    _banner_last_update = time.time(); await asyncio.sleep(5)
    if time.time() - _banner_last_update < 4.5: return
    try: await update_review_counter(silent=True)
    except Exception: pass

async def update_review_counter(silent: bool = False):
    try:
        text_ch = bot.get_channel(CONFIG["REVIEW_COUNT_CHANNEL"]) or await bot.fetch_channel(CONFIG["REVIEW_COUNT_CHANNEL"])
        if not text_ch: return
        count = 1431
        async for m in text_ch.history(limit=None): count += 1
        await update_server_banner(count, silent)
    except Exception as e:
        if not silent: await log_discord(title="❌ Ошибка обновления счётчика отзывов", description=f"> **Ошибка:** `{str(e)}`", color=0xff0000)

def _process_banner_gif(gif_path: str, font_path: str, review_count: int):
    from PIL import Image, ImageDraw, ImageFont, ImageSequence
    import io
    img = Image.open(gif_path); original_frames = [frame.convert("RGBA") for frame in ImageSequence.Iterator(img)]; original_duration = img.info.get('duration', 100)
    configs = [{"w": 960, "h": 540, "colors": 128, "step": 1}, {"w": 960, "h": 540, "colors": 64, "step": 1}, {"w": 960, "h": 540, "colors": 64, "step": 2}, {"w": 800, "h": 450, "colors": 64, "step": 2}, {"w": 640, "h": 360, "colors": 64, "step": 2}, {"w": 640, "h": 360, "colors": 32, "step": 3}, {"w": 480, "h": 270, "colors": 32, "step": 3}]
    for cfg in configs:
        frames = []
        for i, frame in enumerate(original_frames):
            if i % cfg["step"] != 0: continue
            f = frame.copy(); f.thumbnail((cfg["w"], cfg["h"]), Image.LANCZOS); draw = ImageDraw.Draw(f); font_size = int(f.height * 0.37); font = ImageFont.truetype(font_path, font_size); x, y = int(f.width * 0.31), int(f.height * 0.50)
            draw.text((x + 4, y + 4), str(review_count), font=font, fill=(0, 0, 0, 150), anchor="mm"); draw.text((x, y), str(review_count), font=font, fill=(255, 255, 255), anchor="mm"); frames.append(f.convert("P", palette=Image.ADAPTIVE, colors=cfg["colors"]))
        if not frames: continue
        buf = io.BytesIO(); frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], loop=0, duration=original_duration * cfg["step"], optimize=True, disposal=2)
        if len(buf.getvalue()) / (1024 * 1024) <= 9.5: return buf.getvalue(), cfg
    return None, None

async def update_server_banner(review_count: int, silent: bool = False):
    try:
        from PIL import Image, ImageDraw, ImageFont
        gif_paths = [os.path.join(ADD_DIR, "banner.gif"), os.path.join(ADD_DIR, "copy_5B91850B-07EB-4E52-8E1C-96BDDEDE928C.gif")]; font_path = os.path.join(ADD_DIR, "Fredoka_One.ttf")
        for gif_path in gif_paths:
            if os.path.exists(gif_path) and os.path.exists(font_path):
                try:
                    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
                    if not guild: return
                    best_gif_bytes, used_config = await asyncio.to_thread(_process_banner_gif, gif_path, font_path, review_count)
                    if best_gif_bytes:
                        await guild.edit(banner=best_gif_bytes)
                        if not silent: await log_discord(title="🖼️ Анимированный баннер обновлён", description=f"> **Файл:** `{os.path.basename(gif_path)}`\n> **Количество отзывов:** `{review_count}`\n> **Сжатие:** {used_config['w']}x{used_config['h']} ({used_config['colors']} цв.)", color=0x00aaff)
                        return
                except Exception: pass
        base_path = os.path.join(ADD_DIR, "banner.png"); output_path = os.path.join(DATA_DIR, "banner_ready.png")
        if not os.path.exists(base_path) or not os.path.exists(font_path): return
        img = Image.open(base_path).convert("RGBA"); draw = ImageDraw.Draw(img); font = ImageFont.truetype(font_path, 400); draw.text((594, 540), str(review_count), font=font, fill=(255, 255, 255), anchor="mm"); img.save(output_path)
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild: return
        with open(output_path, "rb") as f: await guild.edit(banner=f.read())
        if not silent: await log_discord(title="🖼️ Баннер обновлён", description=f"> **Количество отзывов:** `{review_count}`", color=0x00aaff)
    except Exception: pass

@tasks.loop(hours=24)
async def review_counter_task(): await bot.wait_until_ready(); await update_review_counter(silent=False)

@tasks.loop(minutes=1)
async def daily_bonus_task():
    global _LAST_BONUS_DATE
    await bot.wait_until_ready(); now_msk = datetime.now(MSK)
    if now_msk.hour != 23 or now_msk.minute != 59: return
    today = now_msk.date()
    if _LAST_BONUS_DATE == today: return
    _LAST_BONUS_DATE = today; await daily_bonus()

@tasks.loop(minutes=5)
async def daily_deal_task():
    await bot.wait_until_ready()
    try:
        before = load_json(os.path.join(DATA_DIR, "daily_deal.json"), {}); deal = refresh_daily_deal(); after = load_json(os.path.join(DATA_DIR, "daily_deal.json"), {})
        if before.get("slot") != after.get("slot") and deal:
            try:
                from bonus.core import announce_deal_change
                await announce_deal_change(bot, deal)
            except Exception: pass
    except Exception: pass

@tasks.loop(minutes=1)
async def salary_advance_task(): await bot.wait_until_ready(); await try_pay_advance()

@tasks.loop(minutes=1)
async def salary_main_task(): await bot.wait_until_ready(); await try_pay_salary()

@tasks.loop(minutes=1)
async def unused_purchase_reminder_task():
    global _LAST_REMINDER_DATE
    await bot.wait_until_ready(); now_msk = datetime.now(MSK)
    if now_msk.hour != 12 or now_msk.minute != 0: return
    today = now_msk.date()
    if _LAST_REMINDER_DATE == today: return
    _LAST_REMINDER_DATE = today; await check_unused_purchases(bot)

@tasks.loop(minutes=1)
async def daily_activity_payout_task():
    global _LAST_PAYOUT_DATE
    await bot.wait_until_ready(); now_msk = datetime.now(MSK)
    if now_msk.hour != 0 or now_msk.minute != 0: return
    today = now_msk.date()
    if _LAST_PAYOUT_DATE == today: return
    _LAST_PAYOUT_DATE = today; await daily_activity_payout()

@bot.event
async def on_ready():
    try:
        await bot.change_presence(activity=disnake.Game(name="Магазин и экономика"))
        try:
            from modules.giveaways import setup_giveaways
            setup_giveaways(bot)
        except Exception as e: pass
        
        from modules.commands_tickets import TicketPanelView, TicketPaidView, TicketView, CoinsTicketButtons, SelectView, CatalogTypeView, CatalogView, QuestionTicketView
        from modules.tickets import ReceiptView
        from modules.commands_profile import send_profile_panel, ProfilePanelView, ProfileCardView
        from modules.commands_staff import send_tarology_panel, send_ticket_panel, send_work_panel, send_staff_panels, TarologyView, WorkView, DCView, PromoView, AdminView
        
        bot.add_view(TicketPanelView()); bot.add_view(TicketPaidView()); bot.add_view(TicketView()); bot.add_view(CoinsTicketButtons()); bot.add_view(SelectView()); bot.add_view(CatalogTypeView()); bot.add_view(CatalogView()); bot.add_view(ReceiptView()); bot.add_view(TarologyView()); bot.add_view(ProfilePanelView()); bot.add_view(ProfileCardView()); bot.add_view(WorkView()); bot.add_view(QuestionTicketView()); bot.add_view(DCView()); bot.add_view(PromoView()); bot.add_view(AdminView())
        bot.loop.create_task(send_tarology_panel()); bot.loop.create_task(send_ticket_panel()); bot.loop.create_task(send_profile_panel()); bot.loop.create_task(send_work_panel()); bot.loop.create_task(send_staff_panels())

        guild = bot.get_guild(int(CONFIG["GUILD_ID"])); counts = {}
        if guild:
            for member in guild.members:
                if not member.bot: get_user_dc_data(member.id)
            sync_dc_to_json()
            counts = load_json(FILES["review_counts"], {})
            if counts:
                for uid_str, count in counts.items():
                    member = guild.get_member(int(uid_str))
                    if member: await update_user_roles(member, count, keep_pka=True)
        bot.loop.create_task(update_review_counter(silent=False))

        try: await try_pay_advance()
        except Exception: pass
        try: await try_pay_salary()
        except Exception: pass

        try:
            from clan import init_clan_league
            from clan.panels import send_clan_pool_panel, send_clan_season_panel, send_clan_games_panel
            init_clan_league(bot)
            bot.loop.create_task(send_clan_pool_panel(bot)); bot.loop.create_task(send_clan_season_panel(bot)); bot.loop.create_task(send_clan_games_panel(bot))
            try:
                from clan.core import distribute_all_club_members, prune_ineligible_clan_members
                guild_for_clan = bot.get_guild(int(CONFIG["GUILD_ID"]))
                if guild_for_clan:
                    await prune_ineligible_clan_members(guild_for_clan)
                    distribute_all_club_members(guild_for_clan)
            except Exception: pass
            try:
                from clan.achievements import unlock_achievement, CREATOR_USER_ID
                await unlock_achievement(CREATOR_USER_ID, "creator", bot=bot, notify=False)
            except Exception: pass
        except Exception: pass

        try:
            from pet import init_pet_league
            from pet.core import start_pet_tasks
            init_pet_league(bot); start_pet_tasks(bot)
        except Exception: pass

        try:
            from bonus import init_bonus
            from bonus.views import BonusPanelView, build_panel_embeds as build_bonus_embeds
            from bonus.core import BONUS_CHANNEL_ID
            init_bonus(bot); bot.add_view(BonusPanelView())
            async def _post_bonus_panel():
                await asyncio.sleep(10)
                try:
                    ch = bot.get_channel(BONUS_CHANNEL_ID) or await bot.fetch_channel(BONUS_CHANNEL_ID)
                    if not ch: return
                    async for m in ch.history(limit=30):
                        if m.author == bot.user and m.components: await m.delete(); break
                    await ch.send(embeds=build_bonus_embeds(), view=BonusPanelView())
                except Exception: pass
            bot.loop.create_task(_post_bonus_panel())
        except Exception: pass

        for task in (review_counter_task, daily_bonus_task, daily_deal_task, salary_advance_task, salary_main_task, unused_purchase_reminder_task, daily_activity_payout_task):
            if not task.is_running(): task.start()

        await log_discord(title="✅ Бот запустился", description=f"> **{bot.user}** готов и онлайн.\n> Роли обновлены для {len(counts) if counts else 0} пользователей.", color=0x00ff00)
    except Exception as e: await log_discord(title="❌ Ошибка при запуске", description=f"> **Ошибка:** `{str(e)}`", color=0xff0000)

@bot.event
async def on_member_join(member: disnake.Member):
    await log_discord(title="👤 Участник зашёл", description=f"> **{member.mention}** (`{member}`) присоединился.\n> ID: `{member.id}`", color=0x00ff00)
    from clan.core import CLUB_ROLE_ID
    role = member.guild.get_role(CLUB_ROLE_ID)
    if role:
        try: await member.add_roles(role)
        except Exception: pass
    try:
        from clan.achievements import unlock_achievement
        await unlock_achievement(member.id, "newbie", bot=bot)
    except Exception: pass
    try:
        data = get_dc_cache(member.id); already_received = any("Приветственный бонус" in (h.get("reason", "") or "") for h in data.get("history", []))
        if not already_received:
            await add_dc(member.id, WELCOME_BONUS_DC, "Приветственный бонус за регистрацию", notify=False, log=False)
            try:
                embed1 = disnake.Embed(color=6776679).set_image(url=IMG_WELCOME)
                embed2 = disnake.Embed(title="Добро пожаловать в Diamond Shop!", description=f"> Привет, **{member.display_name}**! Мы начислили тебе **{WELCOME_BONUS_DC} DC** в качестве приветственного бонуса.\n\n**💎 Diamond Coin** — внутренняя валюта сервера. Зарабатывай её активностью и трать на товары.\n\n**Как заработать DC?**\n> • **Сообщения** — 1 DC за 10 сообщений\n> • **Голос** — 3 DC в час\n> • **Отзывы** — от 20 до 100 DC\n> • **Ежедневный бонус** — +10 DC с ролью «Клуб»\n> • **Ежедневный подарок** — от 10 до 30 DC в панели профиля\n> • **Питомцы** — 1–20 DC в час\n> • **Казино** — рулетка, блэкджек, монетка\n\n> Удачи и приятных покупок!", color=6776679, timestamp=datetime.now(timezone.utc)).set_image(url=IMG_STRIPE)
                await member.send(embeds=[embed1, embed2])
            except Exception: pass
            await log_discord(title="🎁 Приветственный бонус", description=f"> **Пользователь:** {member.mention}\n> **Начислено:** `+{WELCOME_BONUS_DC} DC`", color=0xffaa00)
    except Exception: pass

    guild = member.guild
    snapshot_before = {row["invite_code"]: row for row in db.execute("SELECT * FROM invites_snapshot WHERE guild_id=?", (guild.id,)).fetchall()}
    try: invites_now = await guild.invites()
    except Exception: return
    used_invite = None
    for inv in invites_now:
        old = snapshot_before.get(inv.code)
        if old and inv.uses > old["uses"]: used_invite = inv; break
    for inv in invites_now:
        db.execute("REPLACE INTO invites_snapshot (invite_code, guild_id, uses, inviter_id) VALUES (?, ?, ?, ?)", (inv.code, guild.id, inv.uses, inv.inviter.id if inv.inviter else None))
    if not used_invite or not used_invite.inviter: db.commit(); return
    inviter_id = used_invite.inviter.id; is_bot = 1 if member.bot else 0; joined_at = now_ts(); ref_user_id = None
    try:
        from bonus.core import get_user_by_ref_code
        ref_user_id = get_user_by_ref_code(used_invite.code)
    except Exception: pass
    db.execute("INSERT INTO invites (guild_id, inviter_id, member_id, joined_at, is_bot, invite_code, ref_user_id) VALUES (?, ?, ?, ?, ?, ?, ?)", (guild.id, inviter_id, member.id, joined_at, is_bot, used_invite.code, ref_user_id)); db.commit()
    await log_discord(title="📨 Использован инвайт", description=f"> **Пользователь:** {member.mention}\n> **Пригласил:** <@{inviter_id}>\n> **Код:** `{used_invite.code}`" + (f"\n> **Реферал:** <@{ref_user_id}>" if ref_user_id else ""), color=0x00aaff)

@bot.event
async def on_member_remove(member: disnake.Member):
    guild = member.guild
    await log_discord(title="🚪 Участник вышел", description=f"> **{member.mention}** (`{member}`) покинул сервер.\n> ID: `{member.id}`", color=0xff0000)
    db.execute("UPDATE invites SET left_at=? WHERE guild_id=? AND member_id=? AND left_at IS NULL", (now_ts(), guild.id, member.id))
    row = db.execute("SELECT joined_at FROM invites WHERE guild_id=? AND member_id=? ORDER BY joined_at DESC LIMIT 1", (guild.id, member.id)).fetchone()
    if row and (now_ts() - row["joined_at"]) < 600:
        db.execute("UPDATE invites SET is_fake=1 WHERE guild_id=? AND member_id=? AND is_fake=0", (guild.id, member.id))
        await log_discord(title="⚠️ Фейковый вход", description=f"> **Пользователь:** {member.mention}\n> Ушёл менее чем через **10 минут** после входа.", color=0xff6600)
    db.commit()

@bot.event
async def on_member_update(before: disnake.Member, after: disnake.Member):
    if before.display_name != after.display_name: await log_discord(title="✏️ Изменён никнейм", description=f"> **Пользователь:** {before.mention}\n> **Было:** `{before.display_name}`\n> **Стало:** `{after.display_name}`", color=0xffff00)
    if before.roles != after.roles:
        added = [r for r in after.roles if r not in before.roles]; removed = [r for r in before.roles if r not in after.roles]
        if added:
            await log_discord(title="➕ Выдана роль", description=f"> **Пользователь:** {after.mention}\n> **Роль:** {', '.join(r.mention for r in added)}", color=0x00ff00)
            try:
                from clan.core import CLUB_ROLE_ID, assign_user_to_clan, get_user_clan
                if any(r.id == CLUB_ROLE_ID for r in added) and not get_user_clan(after.id): assign_user_to_clan(after.id, after.guild)
            except Exception: pass
            try:
                from clan.achievements import check_and_unlock
                role_ids = CONFIG["ROLE_IDS"]; role_map = {role_ids["bronze"]: "bronze", role_ids["silver"]: "silver", role_ids["gold"]: "gold", role_ids["diamond"]: "diamond", role_ids["crystalis"]: "crystalis", role_ids["pka"]: "pka"}
                for r in added:
                    if r.id in role_map: await check_and_unlock(after.id, "role", role_key=role_map[r.id], bot=bot)
            except Exception: pass
        if removed: await log_discord(title="➖ Снята роль", description=f"> **Пользователь:** {after.mention}\n> **Роль:** {', '.join(r.mention for r in removed)}", color=0xff0000)
    if before.display_avatar.url != after.display_avatar.url: await log_discord(title="🖼️ Изменён аватар", description=f"> **Пользователь:** {after.mention}\n> [Новый аватар]({after.display_avatar.url})", color=0xffff00)

@bot.event
async def on_raw_message_delete(payload: disnake.RawMessageDeleteEvent):
    if payload.channel_id == CONFIG["REVIEW_COUNT_CHANNEL"]: asyncio.create_task(schedule_banner_update())

@bot.event
async def on_message_delete(message: disnake.Message):
    if message.author.bot or message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]: return
    content = (message.content or "[Нет текста]")[:1021] + ("..." if len(message.content or "") > 1024 else "")
    await log_discord(title="🗑️ Удалено сообщение", description=f"> **Автор:** {message.author.mention}\n> **Канал:** {message.channel.mention}\n> **Содержание:**\n```\n{content}\n```", color=0xff6600)

@bot.event
async def on_bulk_message_delete(messages: List[disnake.Message]):
    if not messages: return
    channel = messages[0].channel
    if channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]: asyncio.create_task(schedule_banner_update()); return
    await log_discord(title="🗑️ Массовое удаление", description=f"> **Канал:** {channel.mention}\n> **Количество:** `{len(messages)}`", color=0xff6600)

@bot.event
async def on_message_edit(before: disnake.Message, after: disnake.Message):
    if before.author.bot or before.content == after.content or before.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]: return
    await log_discord(title="✏️ Изменено сообщение", description=f"> **Автор:** {before.author.mention}\n> **Канал:** {before.channel.mention}\n> **Было:**\n```\n{(before.content or '[Нет]')[:500]}\n```\n> **Стало:**\n```\n{(after.content or '[Нет]')[:500]}\n```", color=0xffff00)

@bot.event
async def on_guild_channel_create(channel: disnake.abc.GuildChannel): await log_discord(title="➕ Создан канал", description=f"> **{channel.mention}** (`{channel.name}`)\n> **ID:** `{channel.id}`", color=0x00ff00)
@bot.event
async def on_guild_channel_delete(channel: disnake.abc.GuildChannel): await log_discord(title="➖ Удалён канал", description=f"> **{channel.name}**\n> **ID:** `{channel.id}`", color=0xff0000)
@bot.event
async def on_guild_channel_update(before, after):
    if before.name != after.name: await log_discord(title="✏️ Изменён канал", description=f"> **{after.mention}**\n> **Было:** `{before.name}`\n> **Стало:** `{after.name}`", color=0xffff00)
@bot.event
async def on_guild_role_create(role: disnake.Role): await log_discord(title="➕ Создана роль", description=f"> **{role.mention}** (`{role.name}`)\n> **ID:** `{role.id}`", color=0x00ff00)
@bot.event
async def on_guild_role_delete(role: disnake.Role): await log_discord(title="➖ Удалена роль", description=f"> **{role.name}**\n> **ID:** `{role.id}`", color=0xff0000)
@bot.event
async def on_guild_role_update(before: disnake.Role, after: disnake.Role):
    if before.name != after.name: await log_discord(title="✏️ Изменена роль", description=f"> **{after.mention}**\n> **Было:** `{before.name}`\n> **Стало:** `{after.name}`", color=0xffff00)
@bot.event
async def on_invite_create(invite: disnake.Invite):
    db.execute("REPLACE INTO invites_snapshot VALUES (?, ?, ?, ?)", (invite.code, invite.guild.id, invite.uses, invite.inviter.id if invite.inviter else None)); db.commit()
    await log_discord(title="📨 Создан инвайт", description=f"> **Код:** `{invite.code}`\n> **Создатель:** {invite.inviter.mention if invite.inviter else '?'}", color=0x00aaff)
@bot.event
async def on_invite_delete(invite: disnake.Invite):
    db.execute("DELETE FROM invites_snapshot WHERE invite_code=?", (invite.code,)); db.commit()
    await log_discord(title="🗑️ Удалён инвайт", description=f"> **Код:** `{invite.code}`", color=0xff6600)

@bot.event
async def on_raw_reaction_add(payload: disnake.RawReactionActionEvent):
    if payload.member is None or payload.member.bot: return
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    row = db.execute("SELECT role_id FROM reaction_roles WHERE guild_id=? AND channel_id=? AND message_id=? AND emoji=?", (payload.guild_id, payload.channel_id, payload.message_id, str(payload.emoji))).fetchone()
    if row:
        role = guild.get_role(row["role_id"])
        if role:
            try: await payload.member.add_roles(role)
            except Exception: pass
@bot.event
async def on_raw_reaction_remove(payload: disnake.RawReactionActionEvent):
    if payload.user_id == bot.user.id: return
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    row = db.execute("SELECT role_id FROM reaction_roles WHERE guild_id=? AND channel_id=? AND message_id=? AND emoji=?", (payload.guild_id, payload.channel_id, payload.message_id, str(payload.emoji))).fetchone()
    if row:
        role = guild.get_role(row["role_id"]); member = guild.get_member(payload.user_id)
        if role and member:
            try: await member.remove_roles(role)
            except Exception: pass

@bot.event
async def on_interaction(inter: disnake.MessageInteraction):
    try:
        from clan.panels import handle_clan_interaction
        await handle_clan_interaction(inter)
    except Exception: pass

@bot.event
async def on_message(message: disnake.Message):
    if message.author.bot: return
    is_guild_text = isinstance(message.channel, disnake.TextChannel)
    if is_guild_text:
        from modules.dc import add_message_dc
        if len(message.content.strip()) >= CONFIG["MIN_MESSAGE_LENGTH"] and message.channel.id != CONFIG["REVIEW_COUNT_CHANNEL"]:
            await add_message_dc(message.author.id)
            try:
                from clan.achievements import unlock_achievement
                await unlock_achievement(message.author.id, "first_message", bot=bot, notify=False)
            except Exception: pass

    if is_guild_text and message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"]:
        user_id = message.author.id; now = time.time(); text = (message.content or "").strip(); last = _REVIEW_COOLDOWN.get(user_id, 0)
        if now - last < REVIEW_COOLDOWN_SECONDS:
            left = int(REVIEW_COOLDOWN_SECONDS - (now - last))
            try: await message.delete()
            except Exception: pass
            try: await message.author.send(f"⏳ **Слишком часто.**\n> Ты уже оставил отзыв недавно.\n> Подожди ещё **{left} сек** перед следующим.")
            except Exception: pass
            return
        if message.attachments or message.stickers or message.embeds or len(text) < REVIEW_MIN_LENGTH:
            try: await message.delete()
            except Exception: pass
            return
        _REVIEW_COOLDOWN[user_id] = now
        try: await message.add_reaction("💎")
        except Exception: pass

        counts = load_json(FILES["review_counts"], {}); counts[str(user_id)] = counts.get(str(user_id), 0) + 1; save_json(FILES["review_counts"], counts); new_count = counts[str(user_id)]
        if isinstance(message.author, disnake.Member):
            try: await update_user_roles(message.author, new_count, keep_pka=True)
            except Exception: pass
        reward = get_review_reward(new_count); pet_mult = 1.0
        try:
            from pet.core import get_review_bonus
            pet_mult = get_review_bonus(user_id)
            if pet_mult > 1.0: reward = int(reward * pet_mult)
        except Exception: pass
        try: await add_dc(user_id, reward, "Отзыв о покупке", notify=False, log=False, to_clan_pool=True)
        except Exception: pass
        try:
            from pet.core import add_pet_xp
            await add_pet_xp(user_id, 25, "review")
        except Exception: pass
        try:
            from clan.achievements import check_and_unlock
            await check_and_unlock(user_id, "reviews", value=new_count, bot=bot)
        except Exception: pass
        try:
            from clan.quests import on_review_quest_hook
            await on_review_quest_hook(user_id)
        except Exception: pass
        try:
            from modules.giveaways import process_pending_payouts
            await process_pending_payouts(bot, user_id)
        except Exception: pass
        try:
            reward_line = f"> **Начислено:** `+{reward} DC`" + (f" (бонус питомца ×{pet_mult:.2f})" if pet_mult > 1.0 else "")
            dm_embed = disnake.Embed(title="✅ Отзыв принят!", description=f"> Спасибо за отзыв!\n\n> **Всего отзывов:** `{new_count}`\n{reward_line}\n> **Следующий отзыв:** можно оставить через 2 минуты", color=0x2ecc71, timestamp=datetime.now(timezone.utc)).set_image(url=IMG_STRIPE)
            await message.author.send(embed=dm_embed)
        except Exception: pass
        log_desc = f"> **Пользователь:** {message.author.mention}\n> **Всего отзывов:** `{new_count}`\n> **Начислено:** `+{reward} DC`\n" + (f"> **Бонус питомца:** `×{pet_mult:.2f}`\n" if pet_mult > 1.0 else "") + f"> **Текст:** {text[:200]}\n> **Ссылка:** [перейти]({message.jump_url})"
        await log_discord(title="📝 Отзыв принят", description=log_desc, color=0x00ff00)
        await update_review_counter(silent=False)
        return

    if is_guild_text:
        try:
            from clan.quests import on_message_quest_hook
            await on_message_quest_hook(message)
        except Exception: pass
    await bot.process_commands(message)

voice_track = {}
@bot.event
async def on_voice_state_update(member: disnake.Member, before: disnake.VoiceState, after: disnake.VoiceState):
    if member.bot: return
    user_id = member.id
    if after.channel and (before.channel is None or before.channel != after.channel):
        voice_track[user_id] = (after.channel.id, int(time.time()))
        try:
            from modules.dc import touch_activity
            touch_activity(user_id)
        except Exception: pass
        try:
            from clan.achievements import unlock_achievement
            await unlock_achievement(user_id, "first_voice", bot=bot, notify=False)
        except Exception: pass
    elif before.channel and (after.channel is None or after.channel != before.channel):
        if user_id in voice_track:
            channel_id, join_time = voice_track.pop(user_id); duration = int(time.time()) - join_time
            if duration > 60:
                from modules.dc import add_voice_dc
                await add_voice_dc(user_id, duration)
                try:
                    from clan.quests import on_voice_quest_hook
                    await on_voice_quest_hook(user_id, duration)
                except Exception: pass
                try:
                    from pet.core import add_pet_xp
                    await add_pet_xp(user_id, 5 * max(duration // 3600, 1), "voice")
                except Exception: pass
