# -*- coding: utf-8 -*-
import os
import json
from datetime import datetime, timezone

import disnake
from disnake import ButtonStyle, SelectOption
from disnake.ui import Button, Modal, Select, TextInput, View

from core.utils import (
    CONFIG, ADD_DIR, CATALOG_DIR, logger,
    log_discord,
    clean_embed_for_discohook,
    load_json,
    cur, db,
    reset_manager_stats,
    has_admin_command_roles
)
from modules.commands_profile import load_embed_from_file
from modules.commands_tickets import TicketPanelView

# ============================================================
# ПАНЕЛЬ "ДОСКА" (board.json)
# ============================================================
def load_board_embed() -> list[disnake.Embed]:
    board_path = os.path.join(ADD_DIR, "board.json")
    if not os.path.exists(board_path):
        return [disnake.Embed(
            title="📋 Доска объявлений",
            description="> Здесь будет важная информация. Пока данных нет.",
            color=6776679
        )]
    try:
        with open(board_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        embeds = []
        for e in data.get("embeds", []):
            embeds.append(disnake.Embed.from_dict(clean_embed_for_discohook(e)))
        return embeds
    except Exception as e:
        logger.error(f"Ошибка загрузки board.json: {e}")
        return [disnake.Embed(
            title="❌ Ошибка",
            description="Не удалось загрузить доску объявлений.",
            color=0xff0000
        )]

# ============================================================
# ПАНЕЛЬ "СПРАВОЧНИК" (Home)
# ============================================================
HOME_CHANNEL_ID = 1532398684074016870

class HomeSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="・Работа в Diamond",
                description="Карьера・Заработная плата",
                emoji="<:working:1538767619602120744>",
                value="work"
            ),
            disnake.SelectOption(
                label="・Экосистема Diamond",
                description="Наши сайты・Лучшая жизнь",
                emoji="<:site:1538768985602916352>",
                value="eco"
            ),
            disnake.SelectOption(
                label="・Роли покупателей",
                description="Достоинства・Разделение прав",
                emoji="<:roles:1540046665984249878>",
                value="roles"
            ),
            disnake.SelectOption(
                label="・Доска",
                description="Знай о важном・Информация",
                emoji="<:banne1:1538551829246513312>",
                value="board"
            )
        ]
        super().__init__(
            placeholder="Выберите раздел...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="home_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await log_discord(
            title="📖 Выбор в справочнике",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff
        )
        value = inter.data.values[0]
        if value == "work":
            embeds = load_embed_from_file("work.json")
            await inter.response.send_message(embeds=embeds, ephemeral=True)
        elif value == "eco":
            embeds = load_embed_from_file("eco.json")
            await inter.response.send_message(embeds=embeds, ephemeral=True)
        elif value == "roles":
            embeds = load_embed_from_file("role.json")
            await inter.response.send_message(embeds=embeds, ephemeral=True)
        elif value == "board":
            embeds = load_board_embed()
            await inter.response.send_message(embeds=embeds, ephemeral=True)

class HomeView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(HomeSelect())

async def send_home_panel():
    from core.bot import bot
    await bot.wait_until_ready()
    channel = bot.get_channel(HOME_CHANNEL_ID)
    if not channel:
        channel = await bot.fetch_channel(HOME_CHANNEL_ID)
    if not channel:
        logger.warning("Home panel channel not found")
        return
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except:
                pass
            break
    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1538771484778958898/image.png?ex=6a83e41e&is=6a82929e&hm=78e0190f6955969d2c2f630b4e9d560557c5c08d4f0c5caf8b32fbfd520332ab&")
    embed2 = disnake.Embed(
        title="Справочник посетителя Diamond",
        description="Справочник посетителя Diamond, в нем можно ознакомиться о нас, нашей экосистемой, узнать о важном, способе получения валюты сервера, достоинствах ролей покупателя и многом другом!",
        color=6776679
    )
    embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307371667506/image.png?ex=6a8133e3&is=6a7fe263&hm=2af0f26a823ea59af3001dc16ce84920759e966bc40824095314e6cd1d9b38ca&")
    await channel.send(embeds=[embed1, embed2], view=HomeView())
    await log_discord(
        title="📖 Справочник отправлен (обновлён)",
        description=f"> Сообщение отправлено в {channel.mention}",
        color=0x00ff00
    )

# ============================================================
# ПАНЕЛЬ "EARLY TAROLOGY"
# ============================================================
TAROLOGY_CHANNEL_ID = 1536796929873420308

class TarologySelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="・Контакты для связи",
                description="Связь для заказа",
                emoji="<:people:1538395694648529009>",
                value="contacts"
            ),
            disnake.SelectOption(
                label="・Подробности и акции",
                description="Узнайте больше, о данной сфере и бонусах",
                emoji="<:CARDS:1538780592425017454>",
                value="details"
            )
        ]
        super().__init__(
            placeholder="Узнать о раскладах",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="tarology_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await log_discord(
            title="🔮 Выбор в Early Tarology",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff
        )
        value = inter.data.values[0]
        if value == "contacts":
            embed = disnake.Embed(
                title="📞 Контакты для связи",
                description="> Связаться можно в ТГК - https://t.me/earlytarology",
                color=6776679
            )
            embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307090772079/image.png?ex=6a83d6e3&is=6a828563&hm=0f9076ebc4177417cab012cf73e561f41aeb34fc6c897d365fd894f19784699f&")
            await inter.response.send_message(embed=embed, ephemeral=True)
        elif value == "details":
            embed = disnake.Embed(
                title="🔮 Подробности и акции.",
                description=(
                    "> Данный канал создан для того, чтобы помочь вам влиться в сферу заработка с помощью раскладов.\n\n"
                    "> При покупке расклада (стоимость — 40₽) вы получаете расклад на любую интересующую вас тему с высокой точностью. А при оставлении отзыва в Early Tarology и в Diamond — вы получаете кэшбэк в виде Diamond Coins в размере 20 шт. Таким образом, вы помогаете человеку развиваться в этом деле, узнаёте интересующую вас правду и получаете бонус на основные покупки."
                ),
                color=6776679
            )
            embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307090772079/image.png?ex=6a83d6e3&is=6a828563&hm=0f9076ebc4177417cab012cf73e561f41aeb34fc6c897d365fd894f19784699f&")
            await inter.response.send_message(embed=embed, ephemeral=True)

class TarologyView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TarologySelect())

async def send_tarology_panel():
    from core.bot import bot
    await bot.wait_until_ready()
    channel = bot.get_channel(TAROLOGY_CHANNEL_ID)
    if not channel:
        channel = await bot.fetch_channel(TAROLOGY_CHANNEL_ID)
    if not channel:
        logger.warning("Tarology panel channel not found")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except:
                pass
            break

    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://media.discordapp.net/attachments/1527006158282555412/1536977317912518677/image.png?ex=6a834bec&is=6a81fa6c&hm=a2a91a7975af349270ec5d97d17f7814e87de0da7943103eceb10dbbb3725978&=&format=webp&quality=lossless&width=1536&height=597")

    embed2 = disnake.Embed(
        title="Early Tarology от Diamond Lady",
        description="> Данный канал, путь в мистику и веру. Расклады неимоверно точные, она приугадала почти все, что произошло в магазине за Пол-Года до событий. Цены низкие, качество высокое. Информация - ниже по категориям.",
        color=6776679
    )
    embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307090772079/image.png?ex=6a83d6e3&is=6a828563&hm=0f9076ebc4177417cab012cf73e561f41aeb34fc6c897d365fd894f19784699f&")

    await channel.send(embeds=[embed1, embed2], view=TarologyView())
    await log_discord(
        title="🔮 Панель Early Tarology отправлена",
        description=f"> Сообщение отправлено в {channel.mention}",
        color=0x00ff00
    )

# ============================================================
# ПАНЕЛЬ ТИКЕТОВ (send_ticket_panel)
# ============================================================
TICKET_PANEL_CHANNEL_ID = 1462136361711829053

async def send_ticket_panel():
    from core.bot import bot
    await bot.wait_until_ready()
    channel = bot.get_channel(TICKET_PANEL_CHANNEL_ID)
    if not channel:
        channel = await bot.fetch_channel(TICKET_PANEL_CHANNEL_ID)
    if not channel:
        logger.warning("Ticket panel channel not found")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except:
                pass
            break

    embed_path = os.path.join(CATALOG_DIR, "menu_embed.json")
    embed = disnake.Embed(
        title="🛒 Панель покупок",
        description="> Нажмите **Купить**, чтобы создать тикет для заказа.\n"
                    "> Нажмите **Промокоды**, чтобы узнать о текущих акциях.\n"
                    "> Нажмите **Каталог**, чтобы посмотреть ассортимент товаров.",
        color=6776679
    )
    embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8679e3&is=6a852863&hm=2846271def3b36c9d96bb56818b8f3cf22e071ef66a90ab4da459e40de563255&")

    if os.path.exists(embed_path):
        try:
            with open(embed_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("embeds") and len(data["embeds"]) > 0:
                embed = disnake.Embed.from_dict(data["embeds"][0])
        except Exception as e:
            logger.error(f"Ошибка загрузки menu_embed.json: {e}")

    await channel.send(embed=embed, view=TicketPanelView())
    await log_discord(
        title="🛒 Панель тикетов отправлена",
        description=f"> Сообщение отправлено в {channel.mention}",
        color=0x00ff00,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

# ============================================================
# НОВАЯ ПАНЕЛЬ "РАБОТА" (канал 1532435807242289314)
# ============================================================
WORK_CHANNEL_ID = 1532435807242289314

class WorkSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="Зарплата",
                description="О заработной плате работников",
                emoji="<:shopf:1541881304981966920>",
                value="salary"
            ),
            disnake.SelectOption(
                label="Топ Sales Manager",
                description="Статистика менеджеров продаж",
                emoji="<:diagram:1541881258873983046>",
                value="top"
            )
        ]
        super().__init__(
            placeholder="Выберите раздел...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="work_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await log_discord(
            title="📂 Выбор в панели работы",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff
        )
        value = inter.data.values[0]
        if value == "salary":
            embeds = load_embed_from_file("zp.json")
            await inter.response.send_message(embeds=embeds, ephemeral=True)
        elif value == "top":
            # Получаем топ менеджеров из БД и формируем embed
            guild = inter.guild
            sales_role = guild.get_role(1154757071330365490)
            if not sales_role:
                return await inter.response.send_message("❌ Роль Sales Manager не найдена.", ephemeral=True)
            
            rows = cur.execute("SELECT user_id, closed_tickets, total_rating, ratings_count FROM manager_stats").fetchall()
            stats = {row["user_id"]: row for row in rows}
            members = [m for m in guild.members if sales_role in m.roles and not m.bot]
            data = []
            for m in members:
                s = stats.get(m.id)
                closed = s["closed_tickets"] if s else 0
                total_rating = s["total_rating"] if s else 0
                ratings_count = s["ratings_count"] if s else 0
                avg = total_rating / ratings_count if ratings_count else 0
                data.append((m, closed, avg))
            data.sort(key=lambda x: (-x[1], -x[2]))
            
            lines = []
            for m, closed, avg in data:
                lines.append(f"> {m.mention} - **{closed}** закрытых заказов. [Рейтинг: **{avg:.1f}**]")
            
            embed = disnake.Embed(
                title="🏆 Топ Sales Manager",
                description="\n".join(lines) if lines else "> Пока нет данных.",
                color=0xffaa00
            )
            embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")
            await inter.response.send_message(embed=embed, ephemeral=True)

class WorkView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WorkSelect())

async def send_work_panel():
    from core.bot import bot
    await bot.wait_until_ready()
    channel = bot.get_channel(WORK_CHANNEL_ID)
    if not channel:
        channel = await bot.fetch_channel(WORK_CHANNEL_ID)
    if not channel:
        logger.warning("Work panel channel not found")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except:
                pass
            break

    embeds = load_embed_from_file("panel_zp.json")
    if not embeds:
        embeds = [disnake.Embed(
            title="❌ Ошибка",
            description="Не удалось загрузить панель работы.",
            color=0xff0000
        )]

    await channel.send(embeds=embeds, view=WorkView())
    await log_discord(
        title="📂 Панель работы отправлена",
        description=f"> Сообщение отправлено в {channel.mention}",
        color=0x00ff00
    )

# ============================================================
# ЛОГИРОВАНИЕ И КНОПКИ СБРОСА / СПИСАНИЯ
# ============================================================
class ResetStatsView(View):
    def __init__(self):
        super().__init__(timeout=None)
        # Кнопки добавляются через декораторы

    @disnake.ui.button(label="Сбросить статистику", style=ButtonStyle.danger, custom_id="reset_stats")
    async def reset(self, button, inter):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав на сброс.", ephemeral=True)
        reset_manager_stats()
        await send_work_panel()
        await send_manager_top()  # обновит и лог, и работу
        await inter.response.send_message("✅ Статистика сброшена.", ephemeral=True)

    @disnake.ui.button(label="Списать заказ", style=ButtonStyle.secondary, custom_id="spisat_zakaz")
    async def spisat(self, button, inter):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав на списание.", ephemeral=True)
        await inter.response.send_modal(SpisatZakazModal())

class SpisatZakazModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="ID пользователя",
                placeholder="Введите ID пользователя",
                custom_id="user_id",
                min_length=1,
                max_length=30
            )
        ]
        super().__init__(title="Списание заказа", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        user_input = inter.text_values["user_id"].strip()
        if not user_input.isdigit():
            return await inter.response.send_message("❌ Введите корректный ID.", ephemeral=True)
        user_id = int(user_input)
        purchases = await get_user_purchases(user_id, only_unused=True)
        if not purchases:
            return await inter.response.send_message("❌ У пользователя нет неиспользованных покупок.", ephemeral=True)
        options = []
        for idx, p in enumerate(purchases):
            label = f"{p['type']} {p['value']}"
            if len(label) > 100:
                label = label[:97] + "..."
            options.append(SelectOption(label=label, value=str(idx), description=f"Дата: {datetime.fromtimestamp(p['date']).strftime('%d.%m.%Y')}"))
        select = Select(placeholder="Выберите покупку для удаления...", options=options, custom_id="spisat_select")
        view = View(timeout=60)
        view.add_item(select)
        async def select_callback(inter2: disnake.MessageInteraction):
            idx = int(inter2.data.values[0])
            success = await remove_purchase(user_id, idx)
            if success:
                await inter2.response.send_message("✅ Покупка удалена.", ephemeral=True)
                await send_work_panel()
                await send_manager_top()
            else:
                await inter2.response.send_message("❌ Ошибка удаления.", ephemeral=True)
        select.callback = select_callback
        await inter.response.send_message("Выберите покупку для удаления:", ephemeral=True, view=view)

# ============================================================
# ТОП МЕНЕДЖЕРОВ + ЛОГИ
# ============================================================
async def send_manager_top():
    """Отправляет/обновляет топ менеджеров в канал 1541809640491458571 (удалён, но оставим для совместимости) и кнопки в лог."""
    from core.bot import bot
    await bot.wait_until_ready()

    # Топ в канал 1541809640491458571 (может быть удалён)
    top_channel = bot.get_channel(1541809640491458571)
    if top_channel:
        # Удаляем старое сообщение
        async for msg in top_channel.history(limit=50):
            if msg.author == bot.user and msg.embeds:
                try:
                    await msg.delete()
                except:
                    pass
                break

        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild:
            return

        sales_manager_role = guild.get_role(1154757071330365490)
        if not sales_manager_role:
            return

        members_with_role = [m for m in guild.members if sales_manager_role in m.roles and not m.bot]
        rows = cur.execute("SELECT user_id, closed_tickets, total_rating, ratings_count FROM manager_stats").fetchall()
        stats = {row["user_id"]: row for row in rows}
        managers_data = []
        for member in members_with_role:
            s = stats.get(member.id)
            closed = s["closed_tickets"] if s else 0
            total_rating = s["total_rating"] if s else 0
            ratings_count = s["ratings_count"] if s else 0
            avg = total_rating / ratings_count if ratings_count else 0
            managers_data.append({"member": member, "closed": closed, "avg": avg})

        managers_data.sort(key=lambda x: (-x["closed"], -x["avg"]))

        lines = []
        for data in managers_data:
            lines.append(f"> {data['member'].mention} - **{data['closed']}** закрытых заказов. [Рейтинг: **{data['avg']:.1f}**]")

        best = managers_data[0] if managers_data else None
        best_mention = best["member"].mention if best else "Нет данных"

        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1541810014463729724/image.png?ex=6a8ef1f8&is=6a8da078&hm=21f7a8bd88c0787fbefd0568f073761b139879ac3fa156962f5b0abded608351&")
        embed2 = disnake.Embed(
            title="Таблиц работников на роли Sales Manager.\n",
            description="> Предоставлены актуальные данные работы, после каждого выполненого заказа - таблица обновляется.\n\n" + "\n".join(lines) if lines else "> Пока нет данных.",
            color=6776679
        )
        embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")
        if best:
            embed2.add_field(name="По актуальным данным, работником недели является ",
                             value=f"<@&1154757071330365490> - {best_mention}, уверенное повышение!",
                             inline=False)

        await top_channel.send(embeds=[embed1, embed2])

    # ЛОГИ (канал 1462418981825810535) – кнопки сброса и списания
    log_channel = bot.get_channel(1462418981825810535)
    if log_channel:
        async for msg in log_channel.history(limit=50):
            if msg.author == bot.user and msg.components:
                try:
                    await msg.delete()
                except:
                    pass
                break
        embed_log = disnake.Embed(
            title="🗑️ Управление статистикой менеджеров",
            description="> Нажмите кнопку ниже, чтобы сбросить статистику менеджеров (только для администраторов).",
            color=0xff6600
        )
        embed_log.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")
        await log_channel.send(embed=embed_log, view=ResetStatsView())

    # Отправляем панель работы (чтобы обновить)
    await send_work_panel()

    await log_discord(
        title="📊 Топ менеджеров обновлён",
        description="> Панель работы и логи обновлены.",
        color=0x00ff00
    )
