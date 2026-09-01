# -*- coding: utf-8 -*-
import os
import json
import asyncio
import time
import re
from datetime import datetime, timezone
from typing import Optional, List

import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption
from disnake.ui import Button, Modal, Select, TextInput, View

from core.utils import (
    CONFIG, ADD_DIR, CATALOG_DIR, logger,
    load_json, save_json, now_ts, log_discord,
    has_admin_command_roles, has_review_moderation_roles,
    clean_embed_for_discohook, parse_emoji,
    add_ticket_owner, remove_ticket_owner, get_ticket_owner,
    get_user_tickets_count_in_category,
    assign_ticket_manager, get_ticket_manager, clear_ticket_manager,
    increment_manager_closed, add_manager_rating,
    add_closed_order
)
from modules.dc import (
    add_dc, remove_dc, add_purchase,
    get_user_purchases, remove_purchase,
    get_dc_cache, save_dc_cache,
    get_user_balance,
    load_shop_catalog
)
from modules.actions import load_action_embed

# ============================================================
# РОЛИ ДЛЯ ТИКЕТОВ
# ============================================================
async def assign_ticket_role(member: disnake.Member, role_id: int):
    if role_id is None:
        return
    role = member.guild.get_role(role_id)
    if role and role not in member.roles:
        try:
            await member.add_roles(role)
            logger.info(f"Выдана роль {role.name} пользователю {member}")
        except Exception as e:
            logger.error(f"Не удалось выдать роль {role_id}: {e}")

async def remove_ticket_role(member: disnake.Member, role_id: int):
    if role_id is None:
        return
    role = member.guild.get_role(role_id)
    if role and role in member.roles:
        try:
            await member.remove_roles(role)
            logger.info(f"Снята роль {role.name} у пользователя {member}")
        except Exception as e:
            logger.error(f"Не удалось снять роль {role_id}: {e}")

async def handle_ticket_roles_on_close(channel: disnake.TextChannel):
    user_id = get_ticket_owner(channel.id)
    if not user_id:
        logger.warning(f"Не найден владелец для канала {channel.id}")
        return
    member = channel.guild.get_member(user_id)
    if not member:
        return
    category = channel.category
    if not category:
        return
    category_id = category.id
    count = get_user_tickets_count_in_category(user_id, category_id)
    if count <= 1:
        if category_id == CONFIG["TICKET_CATEGORY_ID"] or category_id == CONFIG["PAID_CATEGORY_ID"]:
            await remove_ticket_role(member, CONFIG["TICKET_ROLES"]["real_created"])
            await remove_ticket_role(member, CONFIG["TICKET_ROLES"]["real_paid"])
        elif category_id == CONFIG["COINS_CATEGORY_ID"]:
            await remove_ticket_role(member, CONFIG["TICKET_ROLES"]["coins_created"])

async def clear_ticket_owner(channel: disnake.TextChannel):
    user_id = get_ticket_owner(channel.id)
    if user_id:
        remove_ticket_owner(channel.id)
        await handle_ticket_roles_on_close(channel)

# ============================================================
# КЛАСС МОДЕРАЦИИ ОТЗЫВОВ
# ============================================================
class ReviewModerationView(View):
    def __init__(self, user_id: int, content: str, msg_id: int, channel_id: int):
        super().__init__(timeout=86400)
        self.user_id = user_id
        self.content = content
        self.msg_id = msg_id
        self.channel_id = channel_id
        self.message = None

    async def update_status_and_log(self, inter: disnake.MessageInteraction, status: str, log_title: str, log_color: int):
        if not has_review_moderation_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        if self.message and self.message.embeds:
            embeds = self.message.embeds
            new_embeds = []
            for i, embed in enumerate(embeds):
                if i == 1:
                    embed_dict = embed.to_dict()
                    fields = embed_dict.get("fields", [])
                    for field in fields:
                        if field.get("name") == "> Статус":
                            field["value"] = status
                            break
                    new_embeds.append(disnake.Embed.from_dict(embed_dict))
                else:
                    new_embeds.append(embed)
            await self.message.edit(embeds=new_embeds, view=None)
        for child in self.children:
            child.disabled = True
        await inter.response.edit_message(view=self)
        log_chan = self.get_log_channel(inter)
        if log_chan:
            await log_chan.send(
                embed=disnake.Embed(
                    title=log_title,
                    description=f"> **Админ:** {inter.author.mention}\n> **Автор отзыва:** <@{self.user_id}>\n> **Ссылка:** [перейти](https://discord.com/channels/{inter.guild_id}/{self.channel_id}/{self.msg_id})",
                    color=log_color,
                    timestamp=datetime.now(timezone.utc)
                )
            )

    def get_log_channel(self, inter):
        from core.bot import bot
        return bot.get_channel(CONFIG["LOG_CHANNEL_ID"])

    @disnake.ui.button(label="✅ Одобрить", style=ButtonStyle.success)
    async def approve(self, button: Button, inter: disnake.MessageInteraction):
        if not has_review_moderation_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав для одобрения.", ephemeral=True)
        await add_dc(self.user_id, 10, "Одобрение отзыва")
        data = get_dc_cache(self.user_id)
        data["last_review"] = now_ts()
        save_dc_cache(self.user_id, data)
        try:
            from core.bot import bot
            user = bot.get_user(self.user_id)
            if user:
                await user.send("✅ Ваш отзыв одобрен! Вам начислено **+10 DC**.")
        except:
            pass
        await self.update_status_and_log(inter, "✅ Одобрено", "✅ Отзыв одобрен", 0x00ff00)

    @disnake.ui.button(label="❌ Отклонить", style=ButtonStyle.danger)
    async def reject(self, button: Button, inter: disnake.MessageInteraction):
        if not has_review_moderation_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав для отклонения.", ephemeral=True)
        try:
            from core.bot import bot
            user = bot.get_user(self.user_id)
            if user:
                await user.send("❌ Ваш отзыв был отклонён администратором.")
        except:
            pass
        await self.update_status_and_log(inter, "❌ Отклонено", "❌ Отзыв отклонён", 0xff0000)

# ============================================================
# МОДАЛКА ПОКУПКИ ЗА РЕАЛЬНЫЕ ДЕНЬГИ
# ============================================================
class BuyTicketModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Товар", placeholder="Введите название товара", custom_id="item_name", min_length=4, max_length=50),
            TextInput(label="Способ оплаты", placeholder="Т-Банк, СПБ и т.д.", custom_id="payment_method", min_length=3, max_length=50),
            TextInput(label="Промокод (необязательно)", placeholder="Введите промокод, если есть", custom_id="promo_code", required=False, max_length=50)
        ]
        super().__init__(title="Создание тикета на покупку", components=components, custom_id="buy_ticket_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)  # ДОБАВЛЕНО
        from core.bot import bot
        uid = inter.author.id
        now = time.time()
        last = getattr(bot, "_user_ticket_cooldowns", {})
        if uid in last and now - last[uid] < CONFIG["TICKET_COOLDOWN_SECONDS"]:
            remaining = int(CONFIG["TICKET_COOLDOWN_SECONDS"] - (now - last[uid]))
            return await inter.edit_original_response(content=f"⏳ Подождите {remaining} сек.")
        last[uid] = now
        bot._user_ticket_cooldowns = last

        item = inter.text_values.get("item_name", "—")
        pay = inter.text_values.get("payment_method", "—")
        promo = inter.text_values.get("promo_code", "").strip().upper()
        promo_display = "Не введён"
        if promo:
            from core.utils import get_promo_codes
            promo_codes = get_promo_codes()
            if promo in promo_codes:
                promo_display = f"{promo} — {promo_codes[promo]}"
            else:
                promo_display = "Неверный промокод"

        guild = inter.guild
        cat = guild.get_channel(CONFIG["TICKET_CATEGORY_ID"])
        if not cat:
            return await inter.edit_original_response(content="❌ Категория не найдена")

        safe_item = item.lower().replace(" ", "-")[:80]
        channel_name = f"{safe_item}"
        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            inter.author: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        for rid in CONFIG["TICKET_VIEW_ROLES"]:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        for rid in CONFIG["TICKET_MANAGE_ROLES"]:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        ticket_channel = await cat.create_text_channel(name=channel_name, overwrites=overwrites)

        with open(CONFIG["INFO_TEMPLATE_PATH"], "r", encoding="utf-8") as f:
            data = json.load(f)
            embeds_list = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]

        embed_order_info = embeds_list[1] if len(embeds_list) > 1 else disnake.Embed(title="Информация о заказе", color=0x7c3131)
        embed_order_info.clear_fields()
        embed_order_info.add_field(name="> Позиция:", value=f"```{item}```", inline=True)
        embed_order_info.add_field(name="> Способ оплаты:", value=f"```{pay}```", inline=True)
        embed_order_info.add_field(name="> Промокод:", value=f"```{promo_display}```", inline=True)

        current_time = int(time.time())
        embed_order_info.description = f"Статус - Не оплачен\nОжидайте <@&1154757071330365490> для подтверждения.\nВремя: <t:{current_time}:F>"

        view = TicketView()
        await ticket_channel.send(
            f"> Добрый день, {inter.author.mention}, ваш тикет создан. Ожидайте ответа от <@&1154757071330365490>\n"
            f"> Помните, по селекту ниже вы можете посмотреть реквизиты или политику, а кнопкой оплатить — подтвердить оплату.",
            embeds=[embeds_list[0], embed_order_info],
            view=view
        )

        select_embed = disnake.Embed(
            title="Что именно нужно посмотреть?",
            description="Ниже, выбор - просмотр политики по заказу, либо - просмотр реквизитов для оплаты  \n\nВыберите нужный пункт.",
            color=6776679
        )
        select_embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8b1723&is=6a89c5a3&hm=84444a514a08c282e27d51013698ba7b5e82c75a45ae4a004c56b3e58a9acd12&")
        select_view = SelectView()
        await ticket_channel.send(embed=select_embed, view=select_view)

        await inter.edit_original_response(content=f"✅ Тикет создан: {ticket_channel.mention}")

        add_ticket_owner(ticket_channel.id, inter.author.id, cat.id)

        member = inter.author
        await assign_ticket_role(member, CONFIG["TICKET_ROLES"]["real_created"])

        log_ch = guild.get_channel(CONFIG["LOG_TICKET_CHANNEL_ID"])
        if log_ch:
            await log_ch.send(embed=disnake.Embed(
                title="📩 Тикет создан (реальные деньги)",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {ticket_channel.mention}\n> **Товар:** `{item}`\n> **Оплата:** `{pay}`\n> **Промокод:** `{promo_display}`",
                timestamp=datetime.now(timezone.utc),
                color=0x00ff00
            ))

# ============================================================
# МОДАЛКА ПОКУПКИ ЗА DC / ИНВАЙТЫ
# ============================================================
class CoinsTicketModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Товар", placeholder="Введите название товара", custom_id="item_name", min_length=4, max_length=50)
        ]
        super().__init__(title="Создание тикета на покупку (DC/Инвайты)", components=components, custom_id="coins_ticket_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)  # ДОБАВЛЕНО
        from core.bot import bot
        uid = inter.author.id
        now = time.time()
        last = getattr(bot, "_user_ticket_cooldowns", {})
        if uid in last and now - last[uid] < CONFIG["TICKET_COOLDOWN_SECONDS"]:
            remaining = int(CONFIG["TICKET_COOLDOWN_SECONDS"] - (now - last[uid]))
            return await inter.edit_original_response(content=f"⏳ Подождите {remaining} сек.")
        last[uid] = now
        bot._user_ticket_cooldowns = last

        item = inter.text_values.get("item_name", "—")

        guild = inter.guild
        cat = guild.get_channel(CONFIG["COINS_CATEGORY_ID"])
        if not cat:
            return await inter.edit_original_response(content="❌ Категория не найдена")

        safe_item = item.lower().replace(" ", "-")[:80]
        channel_name = f"{safe_item}"
        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            inter.author: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        for rid in CONFIG["TICKET_VIEW_ROLES"]:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        for rid in CONFIG["TICKET_MANAGE_ROLES"]:
            role = guild.get_role(rid)
            if role:
                overwrites[role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        ticket_channel = await cat.create_text_channel(name=channel_name, overwrites=overwrites)
        view = CoinsTicketButtons()

        with open(CONFIG["COINS_INFO_TEMPLATE_PATH"], "r", encoding="utf-8") as f:
            data = json.load(f)
            embeds_list = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]

        embed_order_info = embeds_list[1] if len(embeds_list) > 1 else disnake.Embed(title="Информация о заказе", color=0x7c3131)
        embed_order_info.clear_fields()
        embed_order_info.add_field(name="> Позиция:", value=f"```{item}```", inline=True)
        embed_order_info.add_field(name="> Подтверждение наличия", value=f"```Не активирован```", inline=True)

        current_time = int(time.time())
        embed_order_info.description = f"\n> Время: <t:{current_time}:f>\n> Заказ на Diamond Coin-ы, либо на Инвайты"

        sent_msg = await ticket_channel.send(
            f"> Добрый день, {inter.author.mention}, ваш тикет создан. Ожидайте ответа от <@&1154757071330365490>\n",
            embeds=[embeds_list[0], embed_order_info],
            view=view
        )
        view.message = sent_msg
        view.order_embed_index = 1

        await inter.edit_original_response(content=f"✅ Тикет создан: {ticket_channel.mention}")

        add_ticket_owner(ticket_channel.id, inter.author.id, cat.id)

        member = inter.author
        await assign_ticket_role(member, CONFIG["TICKET_ROLES"]["coins_created"])

        log_ch = guild.get_channel(CONFIG["LOG_TICKET_CHANNEL_ID"])
        if log_ch:
            await log_ch.send(embed=disnake.Embed(
                title="📩 Тикет создан (DC/Инвайты)",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {ticket_channel.mention}\n> **Товар:** `{item}`",
                timestamp=datetime.now(timezone.utc),
                color=0x00ff00
            ))

# ============================================================
# ВЫБОР ТИПА ПОКУПКИ (СЕЛЕКТ-МЕНЮ)
# ============================================================
class BuySelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="Реальные деньги",
                description="Оплата в рублях, USDT и т.д.",
                emoji="<:realmomne:1539649281575620618>",
                value="real"
            ),
            disnake.SelectOption(
                label="Инвайты / Diamond Coins",
                description="Бонусная валюта сервера",
                emoji="<:coins:1539649259245408340>",
                value="coins"
            ),
            disnake.SelectOption(
                label="Задать вопрос",
                description="Узнать о нужном товаре",
                emoji="<:questi:1544371841118773328>",
                value="question"
            )
        ]
        super().__init__(
            placeholder="Выберите способ оплаты или задайте вопрос...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="buy_type_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await log_discord(
            title="🛒 Выбор типа покупки",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )
        value = inter.data.values[0]
        if value == "real":
            await inter.response.send_modal(BuyTicketModal())
        elif value == "coins":
            await inter.response.send_modal(CoinsTicketModal())
        elif value == "question":
            await inter.response.send_modal(QuestionModal())

class BuyTypeView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BuySelect())

# ============================================================
# МОДАЛКА ВОПРОСА
# ============================================================
class QuestionModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="Что за вопрос вы хотите задать?",
                placeholder="Например: Как давно вы занимаетесь магазином?",
                custom_id="question",
                min_length=3,
                max_length=500
            )
        ]
        super().__init__(title="Задать вопрос", components=components, custom_id="question_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        question = inter.text_values["question"]
        guild = inter.guild

        # Категория для вопросов
        cat = guild.get_channel(1544363672128987196)
        if not cat:
            return await inter.edit_original_response(content="❌ Категория для вопросов не найдена.")

        # Имя канала = никнейм пользователя (без пробелов)
        channel_name = inter.author.display_name.lower().replace(" ", "-")[:80]
        if not channel_name:
            channel_name = f"question-{inter.author.id}"

        # Права доступа
        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            inter.author: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }

        # Роль, у которой есть доступ
        support_role = guild.get_role(1423360115335106570)
        if support_role:
            overwrites[support_role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        # Админы тоже могут видеть (опционально)
        admin_role = guild.get_role(1127428607606796294)
        if admin_role:
            overwrites[admin_role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        # Создаём канал
        ticket_channel = await cat.create_text_channel(name=channel_name, overwrites=overwrites)

        # Собираем эмбеды
        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url="https://cdn.discordapp.com/attachments/1064857845838925865/1544369476475158629/image.png?ex=6a9841a8&is=6a96f028&hm=e2f80206537e8c87820b03cccdb39f120cdc1452055767b4e122f455b3f66e1b&")

        current_time = int(time.time())
        embed2 = disnake.Embed(
            title="Что за вопрос был задан:",
            description=f"> Время: <t:{current_time}:f>\n> Ответ на вопрос от персонала.",
            color=6776679
        )
        embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a979d63&is=6a964be3&hm=6b425dcaba72f3d56d43c943a7a02f5a4d6627fbfa68330b6a0a1905992e9705&")
        embed2.add_field(name="> Суть вопроса", value=f"```{question}```")

        # Отправляем сообщение в канал с кнопкой закрытия
        view = QuestionTicketView()
        await ticket_channel.send(
            content=f"<@&1423360115335106570> - задан вопрос, постарайтесь ответить!",
            embeds=[embed1, embed2],
            view=view
        )

        # Уведомляем пользователя
        await inter.edit_original_response(content=f"✅ Ваш вопрос создан: {ticket_channel.mention}")

        # Логируем
        await log_discord(
            title="❓ Новый вопрос",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {ticket_channel.mention}\n> **Вопрос:** {question}",
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

# ============================================================
# ВИД ДЛЯ КАНАЛА ВОПРОСА
# ============================================================
class QuestionTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤЗакрытьㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="question:close",
        emoji=PartialEmoji(name="OffTicket", id=1539657125716824185),
        row=0
    )
    async def close(self, button: Button, inter: disnake.MessageInteraction):
        # Разрешаем закрыть автору вопроса, роли поддержки или админу
        if not any(r.id == 1423360115335106570 for r in inter.author.roles) and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие.", ephemeral=True)

        await inter.response.send_message("Канал закрывается...", ephemeral=True)
        await asyncio.sleep(1)
        channel = inter.channel
        try:
            await channel.delete()
        except:
            pass
        await log_discord(
            title="❓ Вопрос закрыт",
            description=f"> **Канал:** {channel.name}\n> **Закрыл:** {inter.author.mention}",
            color=0xff6600,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

# ============================================================
# СЕЛЕКТ-МЕНЮ ДЛЯ ТИКЕТОВ
# ============================================================
class TicketActionSelect(disnake.ui.StringSelect):
    def __init__(self):
        super().__init__(
            placeholder="Выберите действие...",
            min_values=1,
            max_values=1,
            options=[
                disnake.SelectOption(
                    label="Реквизиты",
                    description="Просмотреть реквизиты для оплаты",
                    emoji="<:Rekvi:1539656975091105892>",
                    value="requisites"
                ),
                disnake.SelectOption(
                    label="Политика",
                    description="Правила и условия магазина",
                    emoji="<:Politic:1539657020695650384>",
                    value="policy"
                )
            ],
            custom_id="ticket_action_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        value = inter.data.values[0]
        if value == "requisites":
            await self.send_requisites(inter)
        elif value == "policy":
            await self.send_policy(inter)

    async def send_requisites(self, inter: disnake.MessageInteraction):
        embeds_data = [
            {
                "type": "rich",
                "title": "Реквизиты к заказу ",
                "description": "\n> Выберите удобный вам способ оплаты → оплатите → подтвердите кнопкой \"Оплатить\" в меню оформления. После - ожидайте <@796293832751972352>. При наличии промокода - напишите его в лот заказа, его проверят, и назначат скидку.",
                "color": 6776679,
                "fields": [
                    {"name": "> Т-БАНК", "value": "```2200 7020 8029 9345```", "inline": True},
                    {"name": "> АльфаБанк", "value": "```2200 1545 6426 7465```", "inline": True},
                    {"name": "> ОзонБанк", "value": "```2204 3204 4881 5151 ``` ", "inline": True},
                    {"name": "> Система Быстрых Платежей [ СБП ] ", "value": "```+7 983 694 76 41 Получатель - Виктор А```", "inline": False},
                    {"name": "> \nПо оплате по KTZ | UAH | USD | TON | USDT", "value": "```Ожидать ответа продавца для удтверждения реквизитов```", "inline": False},
                    {"name": "Помните - всё проверяется, обмануть - не получится.", "value": ""}
                ],
                "image": {
                    "url": "https://cdn.discordapp.com/attachments/1527006158282555412/1530795801268453447/pisk.png?ex=6a69832f&is=6a6831af&hm=106c0b5c55c83b94fce2e11af7a4c65ec26d550b6da30575f1fef0981f7dc914&"
                }
            },
            {
                "type": "rich",
                "title": "Быстрая оплата по QR-Коду на OZON-Банк.",
                "color": 6776679,
                "fields": [],
                "image": {
                    "url": "https://media.discordapp.net/attachments/1527006158282555412/1527179418726826044/image.png?ex=6a59b82b&is=6a5866ab&hm=7c18b8d4df703ae4a509c7855b9d3ead331bf16597547ca9184ef543395cfcc9&=&format=webp&quality=lossless&width=1870&height=727"
                },
                "description": "> В данном QR-Коде, заранее выставлена оплата на Ozon-Банк. Вам достаточно выбрать с какого банка перевести, и сумму перевода."
            }
        ]
        embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in embeds_data]
        await inter.response.send_message(embeds=embeds)
        await log_discord(
            title="📄 Просмотр реквизитов",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
            color=0x00ff00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    async def send_policy(self, inter: disnake.MessageInteraction):
        policy_path = os.path.join(CATALOG_DIR, "menu_policy.json")
        try:
            if not os.path.exists(policy_path):
                await inter.response.send_message("❌ Файл с правилами не найден.", ephemeral=True)
                return
            with open(policy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.send_message(embeds=embeds)
            await log_discord(
                title="📜 Просмотр политики",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
                color=0x00ff00,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        except Exception as e:
            logger.exception("Ошибка при отправке policy: %s", e)
            await inter.response.send_message("❌ Ошибка при загрузке правил.", ephemeral=True)

class SelectView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketActionSelect())

# ============================================================
# КНОПКА ЗАКРЫТИЯ / ОЦЕНКИ
# ============================================================
class TicketRatingView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn_rate = Button(
            label="ㅤОценить работу менеджераㅤ",
            style=ButtonStyle.gray,
            custom_id="ticket:rate_manager",
            emoji=PartialEmoji(name="Otziv", id=1541808692314243172),
            row=0
        )
        btn_rate.callback = self.rate_callback
        self.add_item(btn_rate)

        btn_close = Button(
            label="ㅤЗакрыть заказㅤ",
            style=ButtonStyle.gray,
            custom_id="ticket:close_order",
            emoji=PartialEmoji(name="OffTicket", id=1539657125716824185),
            row=0
        )
        btn_close.callback = self.close_callback
        self.add_item(btn_close)

    async def rate_callback(self, inter: disnake.MessageInteraction):
        channel = inter.channel
        user_id = get_ticket_owner(channel.id)
        if user_id and inter.author.id != user_id:
            return await inter.response.send_message("⛔ Оценивать может только владелец тикета.", ephemeral=True)
        manager_id = get_ticket_manager(channel.id)
        if not manager_id:
            return await inter.response.send_message("❌ Менеджер не назначен.", ephemeral=True)
        await inter.response.send_modal(RatingModal(channel, manager_id))

    async def close_callback(self, inter: disnake.MessageInteraction):
        channel = inter.channel
        user_id = get_ticket_owner(channel.id)
        if user_id and inter.author.id != user_id and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Закрывать заказ может только владелец тикета или админ.", ephemeral=True)
        await self.close_ticket(inter)

    async def close_ticket(self, inter: disnake.MessageInteraction):
        channel = inter.channel
        await inter.response.send_message("Тикет закрывается...", ephemeral=True)
        await asyncio.sleep(3)
        try:
            manager_id = get_ticket_manager(channel.id)
            if manager_id:
                increment_manager_closed(manager_id)
                add_closed_order(manager_id, channel.id)
            await clear_ticket_owner(channel)
            await channel.delete()
            await log_discord(
                title="🗑️ Тикет закрыт (после выполнения)",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {channel.name}",
                color=0xff6600,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
            from modules.commands_panels import send_manager_top
            await send_manager_top()
        except Exception as e:
            logger.error(f"Ошибка при закрытии тикета: {e}")
            try:
                await asyncio.sleep(3)
                await channel.delete()
            except Exception as e2:
                logger.error(f"Повторная ошибка при закрытии тикета: {e2}")

class RatingModal(Modal):
    def __init__(self, channel, manager_id):
        self.channel = channel
        self.manager_id = manager_id
        components = [
            TextInput(
                label="Как вы оцениваете работу менеджера?",
                placeholder="Оцените работу от 1 до 5",
                custom_id="rating",
                min_length=1,
                max_length=1
            )
        ]
        super().__init__(title="Оценка работы менеджера", components=components)

    async def callback(self, inter: disnake.MessageInteraction):
        rating_str = inter.text_values["rating"].strip()
        if not rating_str.isdigit() or int(rating_str) < 1 or int(rating_str) > 5:
            return await inter.response.send_message("❌ Оценка должна быть числом от 1 до 5.", ephemeral=True)
        rating = int(rating_str)
        if self.manager_id:
            add_manager_rating(self.manager_id, rating)
            await log_discord(
                title="⭐ Оценка менеджера",
                description=f"> **Менеджер:** <@{self.manager_id}>\n> **Оценка:** {rating}/5\n> **Тикет:** {self.channel.mention}",
                color=0xffaa00,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
            await inter.response.send_message(f"✅ Спасибо! Оценка {rating}/5 сохранена.", ephemeral=True)
            from modules.commands_panels import send_manager_top
            await send_manager_top()
        else:
            await inter.response.send_message("❌ Менеджер не назначен.", ephemeral=True)

# ============================================================
# ОСНОВНОЙ VIEW С КНОПКАМИ (РЕАЛЬНЫЕ ДЕНЬГИ)
# ============================================================
class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn_close = Button(
            label="ㅤЗакрытьㅤ",
            style=ButtonStyle.gray,
            custom_id="ticket:close",
            emoji=PartialEmoji(name="OffTicket", id=1539657125716824185),
            row=0
        )
        btn_close.callback = self.close_callback
        self.add_item(btn_close)

        btn_pay = Button(
            label="ㅤОплатитьㅤ",
            style=ButtonStyle.gray,
            custom_id="ticket:pay",
            emoji=PartialEmoji(name="Oplacheno", id=1539657164778512496),
            row=0
        )
        btn_pay.callback = self.pay_callback
        self.add_item(btn_pay)

        btn_discounts = Button(
            label="ㅤㅤСкидкиㅤㅤ",
            style=ButtonStyle.gray,
            custom_id="ticket:discounts",
            emoji=PartialEmoji(name="skidka", id=1540819242625146961),
            row=0
        )
        btn_discounts.callback = self.discounts_callback
        self.add_item(btn_discounts)

    async def close_callback(self, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие тикетов.", ephemeral=True)
        channel = inter.channel
        manager_id = get_ticket_manager(channel.id)
        if manager_id and inter.author.id != manager_id and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Этот тикет уже ведёт другой менеджер.", ephemeral=True)
        owner_id = get_ticket_owner(channel.id)
        if not owner_id:
            await inter.response.send_message("Тикет закрывается...", ephemeral=True)
            await asyncio.sleep(3)
            try:
                await clear_ticket_owner(channel)
                await channel.delete()
                await log_discord(
                    title="🗑️ Тикет закрыт",
                    description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {channel.name}",
                    color=0xff6600,
                    channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
                )
                from modules.commands_panels import send_manager_top
                await send_manager_top()
            except Exception as e:
                logger.error(f"Ошибка при закрытии тикета: {e}")
        else:
            await self.send_rating_embed(inter)

    async def send_rating_embed(self, inter: disnake.MessageInteraction):
        channel = inter.channel
        owner_id = get_ticket_owner(channel.id)
        manager_id = get_ticket_manager(channel.id)
        owner = inter.guild.get_member(owner_id) if owner_id else None
        manager = inter.guild.get_member(manager_id) if manager_id else None
        user_mention = owner.mention if owner else f"<@{owner_id}>"
        manager_mention = manager.mention if manager else "Не назначен"

        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1541805596842664017/image.png?ex=6a8eeddb&is=6a8d9c5b&hm=bd497621b27b7c095b9b6cd3af8fa2d5135f68ad247ca03a2e3305c4350107e7&")
        embed2 = disnake.Embed(
            title="Отзыв после выполнения товара.\n",
            description=f"> {user_mention}, заказ выполнен! Оставьте отзыв в канале - <#1462074763437543435>.\n\n"
                        f"> Также, ваш тикет обработал менеджер {manager_mention}. Вы можете дать ему оценку по кнопке ниже. После успешного выполнения действий - менеджер закроет тикет.",
            color=6776679
        )
        embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")
        view = TicketRatingView()
        await channel.send(embeds=[embed1, embed2], view=view)
        await log_discord(
            title="📤 Отправлен запрос на оценку",
            description=f"> **Тикет:** {channel.mention}\n> **Менеджер:** {manager_mention}",
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    async def pay_callback(self, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на подтверждение оплаты.", ephemeral=True)
        channel = inter.channel
        manager_id = get_ticket_manager(channel.id)
        if manager_id and inter.author.id != manager_id and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Этот тикет уже ведёт другой менеджер.", ephemeral=True)

        msg = inter.message
        if not msg.embeds or len(msg.embeds) < 2:
            async for m in channel.history(limit=50):
                if m.author == inter.bot.user and m.embeds and len(m.embeds) >= 2:
                    msg = m
                    break
        if not msg.embeds or len(msg.embeds) < 2:
            return await inter.response.send_message("❌ Не найдено сообщение с заказом.", ephemeral=True)

        desc = msg.embeds[1].description or ""
        if "Статус - Заказ оплачен" in desc:
            return await inter.response.send_message("Заказ уже оплачен.", ephemeral=True)

        order_embed = msg.embeds[1]
        item_name = "—"
        payment_method = "—"
        promo_value = "—"
        for field in order_embed.fields:
            fn = field.name.lower()
            if "позиция" in fn:
                item_name = field.value.strip("`\n ")
            elif "оплаты" in fn:
                payment_method = field.value.strip("`\n ")
            elif "промокод" in fn:
                promo_value = field.value.strip("`\n ")

        ed = order_embed.to_dict()
        ed["color"] = 0x676767
        ed["description"] = (
            "Статус - Заказ оплачен\n"
            f"> Подтверждено: {inter.author.mention}\n"
            f"> Время: <t:{int(time.time())}:f>"
        )

        paid_view = TicketPaidView()
        await msg.edit(
            embeds=[msg.embeds[0], disnake.Embed.from_dict(ed)],
            view=paid_view
        )

        paid_category = inter.guild.get_channel(CONFIG["PAID_CATEGORY_ID"])
        if paid_category:
            await channel.edit(category=paid_category)
        else:
            logger.warning("PAID_CATEGORY_ID not found: %s", CONFIG["PAID_CATEGORY_ID"])

        manager_role = inter.guild.get_role(CONFIG["MANAGER_ROLE_ID"])
        manager_ping = manager_role.mention if manager_role else "@менеджер"
        embed = disnake.Embed(
            title="💚 Заказ оплачен",
            description=f"> **Подтвердил:** {inter.author.mention}\n> **Товар:** `{item_name}`\n> **Оплата:** `{payment_method}`\n> **Промокод:** `{promo_value}`",
            color=0x2ecc71
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")
        await channel.send(embed=embed)

        await inter.response.send_message("✅ Заказ отмечен как оплаченный.", ephemeral=True)

        member = inter.author
        await remove_ticket_role(member, CONFIG["TICKET_ROLES"]["real_created"])
        await assign_ticket_role(member, CONFIG["TICKET_ROLES"]["real_paid"])

        await log_discord(
            title="💰 Заказ оплачен",
            description=(
                f"> **Канал:** {channel.mention}\n"
                f"> **Товар:** `{item_name}`\n"
                f"> **Оплата:** `{payment_method}`\n"
                f"> **Промокод:** `{promo_value}`\n"
                f"> **Подтвердил:** {inter.author.mention}"
            ),
            color=0x2ecc71,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    async def discounts_callback(self, inter: disnake.MessageInteraction):
        channel = inter.channel
        owner_id = get_ticket_owner(channel.id)
        if not owner_id or inter.author.id != owner_id:
            return await inter.response.send_message("⛔ Эта кнопка доступна только создателю тикета.", ephemeral=True)

        discount_applied = False
        async for msg in channel.history(limit=50):
            if msg.author == inter.bot.user and msg.embeds and len(msg.embeds) >= 2:
                embed = msg.embeds[1]
                for field in embed.fields:
                    if "промокод" in field.name.lower():
                        if field.value.strip("`\n ") not in ["Не введён", "Не активирован"]:
                            discount_applied = True
                        break
                break
        if discount_applied:
            return await inter.response.send_message("❌ К данному заказу уже применена скидка.", ephemeral=True)

        all_purchases = await get_user_purchases(inter.author.id, only_unused=True)
        discounts = [p for p in all_purchases if p.get('type') == 'discounts']

        if not discounts:
            return await inter.response.send_message("❌ У вас нету доступных купленных скидок.", ephemeral=True)

        slid_embeds = load_action_embed("slid.json")
        if not slid_embeds or len(slid_embeds) == 0:
            slid_embeds = [disnake.Embed(
                title="📦 Ваши скидки",
                description="> Выберите скидку для применения к заказу.",
                color=6776679
            )]

        view = View(timeout=300)
        for idx, p in enumerate(discounts):
            label = p['value']
            if len(label) > 80:
                label = label[:77] + "..."
            btn = Button(
                label=label,
                style=ButtonStyle.gray,
                custom_id=f"apply_discount_{inter.author.id}_{idx}"
            )
            btn.callback = self.create_discount_callback(idx, inter, discounts)
            view.add_item(btn)

        await inter.response.send_message(embeds=slid_embeds, view=view, ephemeral=True)

    def create_discount_callback(self, discount_index, original_inter, discounts):
        async def callback(inter: disnake.MessageInteraction):
            if inter.author.id != original_inter.author.id:
                return await inter.response.send_message("⛔ Это не ваш товар.", ephemeral=True)

            if discount_index >= len(discounts):
                return await inter.response.send_message("❌ Скидка уже применена.", ephemeral=True)

            discount_applied = False
            async for msg in channel.history(limit=50):
                if msg.author == inter.bot.user and msg.embeds and len(msg.embeds) >= 2:
                    embed = msg.embeds[1]
                    for field in embed.fields:
                        if "промокод" in field.name.lower():
                            if field.value.strip("`\n ") not in ["Не введён", "Не активирован"]:
                                discount_applied = True
                            break
                    break
            if discount_applied:
                return await inter.response.send_message("❌ К данному заказу уже применена скидка.", ephemeral=True)

            item_value = discounts[discount_index]['value']

            full_purchases = await get_user_purchases(inter.author.id, only_unused=False)
            target = None
            target_index = None
            for i, p in enumerate(full_purchases):
                if p['value'] == item_value and p.get('type') == 'discounts' and not p.get('used'):
                    target = p
                    target_index = i
                    break
            if target_index is None:
                return await inter.response.send_message("❌ Скидка не найдена.", ephemeral=True)

            success = await remove_purchase(inter.author.id, target_index)
            if not success:
                return await inter.response.send_message("❌ Ошибка применения скидки.", ephemeral=True)

            async for msg in channel.history(limit=50):
                if msg.author == inter.bot.user and msg.embeds and len(msg.embeds) >= 2:
                    embed_dict = msg.embeds[1].to_dict()
                    for field in embed_dict.get("fields", []):
                        if "промокод" in field.get("name", "").lower():
                            field["value"] = f"```{item_value}```"
                            break
                    new_embed = disnake.Embed.from_dict(embed_dict)
                    embeds = list(msg.embeds)
                    embeds[1] = new_embed
                    await msg.edit(embeds=embeds)
                    break

            await inter.response.send_message(
                f"✅ Скидка **{item_value}** применена к заказу!",
                ephemeral=True
            )
            await log_discord(
                title="🛒 Применена скидка в тикете",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Тикет:** {channel.mention}\n> **Скидка:** {item_value}",
                color=0x00aaff,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        return callback

class TicketPaidView(View):
    def __init__(self):
        super().__init__(timeout=None)
        btn_close = Button(
            label="ㅤЗакрытьㅤ",
            style=ButtonStyle.gray,
            custom_id="ticket_paid:close",
            emoji=PartialEmoji(name="OffTicket", id=1539657125716824185),
            row=0
        )
        btn_close.callback = self.close_callback
        self.add_item(btn_close)

        btn_pay = Button(
            label="ㅤОплатитьㅤ",
            style=ButtonStyle.gray,
            custom_id="ticket_paid:pay_done",
            emoji=PartialEmoji(name="Oplacheno", id=1539657164778512496),
            row=0,
            disabled=True
        )
        self.add_item(btn_pay)

        btn_discounts = Button(
            label="ㅤㅤСкидкиㅤㅤ",
            style=ButtonStyle.gray,
            custom_id="ticket_paid:discounts_done",
            emoji=PartialEmoji(name="skidka", id=1540819242625146961),
            row=0,
            disabled=True
        )
        self.add_item(btn_discounts)

    async def close_callback(self, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие тикетов.", ephemeral=True)
        channel = inter.channel
        manager_id = get_ticket_manager(channel.id)
        if manager_id and inter.author.id != manager_id and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Этот тикет уже ведёт другой менеджер.", ephemeral=True)

        owner_id = get_ticket_owner(channel.id)
        if not owner_id:
            await inter.response.send_message("Тикет закрывается...", ephemeral=True)
            await asyncio.sleep(3)
            try:
                await clear_ticket_owner(channel)
                await channel.delete()
                await log_discord(
                    title="🗑️ Тикет закрыт (оплаченный)",
                    description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {channel.name}",
                    color=0xff6600,
                    channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
                )
                from modules.commands_panels import send_manager_top
                await send_manager_top()
            except Exception as e:
                logger.error(f"Ошибка при закрытии тикета: {e}")
        else:
            manager_id = get_ticket_manager(channel.id)
            owner = channel.guild.get_member(owner_id)
            manager = channel.guild.get_member(manager_id) if manager_id else None
            user_mention = owner.mention if owner else f"<@{owner_id}>"
            manager_mention = manager.mention if manager else "Не назначен"

            embed1 = disnake.Embed(color=6776679)
            embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1541805596842664017/image.png?ex=6a8eeddb&is=6a8d9c5b&hm=bd497621b27b7c095b9b6cd3af8fa2d5135f68ad247ca03a2e3305c4350107e7&")
            embed2 = disnake.Embed(
                title="Отзыв после выполнения товара.\n",
                description=f"> {user_mention}, заказ выполнен! Оставьте отзыв в канале - <#1462074763437543435>.\n\n"
                            f"> Также, ваш тикет обработал менеджер {manager_mention}. Вы можете дать ему оценку по кнопке ниже. После успешного выполнения действий - менеджер закроет тикет.",
                color=6776679
            )
            embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")
            view = TicketRatingView()
            await channel.send(embeds=[embed1, embed2], view=view)

# ============================================================
# КНОПКИ ДЛЯ ТИКЕТОВ ЗА DC/ИНВАЙТЫ
# ============================================================
class CoinsTicketButtons(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.message = None
        self.order_embed_index = 1

    @disnake.ui.button(
        label="ㅤЗакрытьㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="coins_ticket:close",
        emoji=PartialEmoji(name="OffTicket", id=1539657125716824185),
        row=0
    )
    async def close(self, button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие тикетов.", ephemeral=True)
        channel = inter.channel
        manager_id = get_ticket_manager(channel.id)
        if manager_id and inter.author.id != manager_id and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Этот тикет уже ведёт другой менеджер.", ephemeral=True)

        owner_id = get_ticket_owner(channel.id)
        if not owner_id:
            await inter.response.send_message("Тикет закрывается...", ephemeral=True)
            await asyncio.sleep(3)
            try:
                await clear_ticket_owner(channel)
                await channel.delete()
                await log_discord(
                    title="🗑️ Тикет закрыт (DC/Инвайты)",
                    description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {channel.name}",
                    color=0xff6600,
                    channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
                )
                from modules.commands_panels import send_manager_top
                await send_manager_top()
            except Exception as e:
                logger.error(f"Ошибка при закрытии тикета: {e}")
        else:
            manager_id = get_ticket_manager(channel.id)
            owner = channel.guild.get_member(owner_id)
            manager = channel.guild.get_member(manager_id) if manager_id else None
            user_mention = owner.mention if owner else f"<@{owner_id}>"
            manager_mention = manager.mention if manager else "Не назначен"

            embed1 = disnake.Embed(color=6776679)
            embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1541805596842664017/image.png?ex=6a8eeddb&is=6a8d9c5b&hm=bd497621b27b7c095b9b6cd3af8fa2d5135f68ad247ca03a2e3305c4350107e7&")
            embed2 = disnake.Embed(
                title="Отзыв после выполнения товара.\n",
                description=f"> {user_mention}, заказ выполнен! Оставьте отзыв в канале - <#1462074763437543435>.\n\n"
                            f"> Также, ваш тикет обработал менеджер {manager_mention}. Вы можете дать ему оценку по кнопке ниже. После успешного выполнения действий - менеджер закроет тикет.",
                color=6776679
            )
            embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")
            view = TicketRatingView()
            await channel.send(embeds=[embed1, embed2], view=view)

    @disnake.ui.button(
        label="ㅤПолитикаㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="coins_ticket:policy",
        emoji=PartialEmoji(name="Politic", id=1539657020695650384),
        row=0
    )
    async def policy(self, button, inter: disnake.MessageInteraction):
        policy_path = os.path.join(CATALOG_DIR, "menu_policy.json")
        try:
            if not os.path.exists(policy_path):
                await inter.response.send_message("❌ Файл с правилами не найден.", ephemeral=True)
                return
            with open(policy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.send_message(embeds=embeds)
            await log_discord(
                title="📜 Просмотр политики (DC/Инвайты)",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
                color=0x00ff00,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        except Exception as e:
            logger.exception("Ошибка при отправке policy: %s", e)
            await inter.response.send_message("❌ Ошибка при загрузке правил.", ephemeral=True)

    @disnake.ui.button(
        label="ㅤㅤКупленноеㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="coins_ticket:items",
        emoji=PartialEmoji(name="prize", id=1539657202170859561),
        row=0
    )
    async def items(self, button, inter: disnake.MessageInteraction):
        channel = inter.channel
        user_id = get_ticket_owner(channel.id)
        if not user_id or inter.author.id != user_id:
            return await inter.response.send_message("⛔ Эта кнопка доступна только создателю тикета.", ephemeral=True)

        if self.message and self.message.embeds:
            embed = self.message.embeds[self.order_embed_index] if len(self.message.embeds) > self.order_embed_index else None
            if embed:
                for field in embed.fields:
                    if "подтверждение наличия" in field.name.lower():
                        if field.value.strip("`\n ") != "Не активирован":
                            return await inter.response.send_message("❌ К данному тикету уже применён товар.", ephemeral=True)
                        break

        all_purchases = await get_user_purchases(user_id, only_unused=True)
        purchases = [p for p in all_purchases if p.get('type') != 'discounts']

        if not purchases:
            return await inter.response.send_message("❌ У вас нет неиспользованных товаров (кроме скидок) для этого тикета.", ephemeral=True)

        invet_path = os.path.join(ADD_DIR, "invet.json")
        if os.path.exists(invet_path):
            try:
                with open(invet_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            except Exception as e:
                logger.error(f"Ошибка загрузки invet.json: {e}")
                embeds = [
                    disnake.Embed(
                        title="📦 Инвентарь товаров за Diamond Coin",
                        description="> Если вы создали тикет в данной категории, у вас должны быть товары, которые куплены за них, если вы получаете товар, оплатой в Diamond Coin-ах.\n\n> Выберите товар, который относится к вашему тикету, он обновит статус в \"Подтверждения Наличия\"",
                        color=6776679
                    )
                ]
        else:
            embeds = [
                disnake.Embed(
                    title="📦 Инвентарь товаров за Diamond Coin",
                    description="> Если вы создали тикет в данной категории, у вас должны быть товары, которые куплены за них, если вы получаете товар, оплатой в Diamond Coin-ах.\n\n> Выберите товар, который относится к вашему тикету, он обновит статус в \"Подтверждения Наличия\"",
                    color=6776679
                )
            ]

        view = View(timeout=300)
        for idx, p in enumerate(purchases):
            label = p['value']
            if len(label) > 80:
                label = label[:77] + "..."
            btn = Button(
                label=label,
                style=ButtonStyle.gray,
                custom_id=f"apply_coins_{user_id}_{idx}"
            )
            btn.callback = self.create_apply_callback(idx, inter, purchases)
            view.add_item(btn)

        await inter.response.send_message(embeds=embeds, view=view, ephemeral=True)

    def create_apply_callback(self, purchase_index, original_inter, purchases):
        async def callback(inter: disnake.MessageInteraction):
            channel = inter.channel
            user_id = get_ticket_owner(channel.id)
            if not user_id or inter.author.id != user_id:
                return await inter.response.send_message("⛔ Это не ваш товар.", ephemeral=True)

            if purchase_index >= len(purchases):
                return await inter.response.send_message("❌ Товар уже применён.", ephemeral=True)

            if self.message and self.message.embeds:
                embed = self.message.embeds[self.order_embed_index] if len(self.message.embeds) > self.order_embed_index else None
                if embed:
                    for field in embed.fields:
                        if "подтверждение наличия" in field.name.lower():
                            if field.value.strip("`\n ") != "Не активирован":
                                return await inter.response.send_message("❌ К данному тикету уже применён товар.", ephemeral=True)
                            break

            item_value = purchases[purchase_index]['value']

            full_purchases = await get_user_purchases(user_id, only_unused=False)
            target = None
            target_index = None
            for i, p in enumerate(full_purchases):
                if p['value'] == item_value and p.get('type') != 'discounts' and not p.get('used'):
                    target = p
                    target_index = i
                    break
            if target_index is None:
                return await inter.response.send_message("❌ Товар не найден.", ephemeral=True)

            success = await remove_purchase(user_id, target_index)
            if not success:
                return await inter.response.send_message("❌ Ошибка применения товара.", ephemeral=True)

            if self.message and self.message.embeds:
                embeds = list(self.message.embeds)
                if len(embeds) > self.order_embed_index:
                    embed_dict = embeds[self.order_embed_index].to_dict()
                    for field in embed_dict.get("fields", []):
                        if "подтверждение наличия" in field.get("name", "").lower():
                            field["value"] = f"```{item_value}```"
                            break
                    new_embed = disnake.Embed.from_dict(embed_dict)
                    embeds[self.order_embed_index] = new_embed
                    await self.message.edit(embeds=embeds)

            await inter.response.send_message(
                f"✅ Товар **{item_value}** применён к тикету!",
                ephemeral=True
            )
            await log_discord(
                title="🛒 Применён товар в тикете (DC/Инвайты)",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Тикет:** {channel.mention}\n> **Товар:** {item_value}",
                color=0x00aaff,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        return callback

# ============================================================
# ВЫБОР ТИПА КАТАЛОГА
# ============================================================
class CatalogTypeSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="Реальные деньги",
                description="Оплата в рублях, USDT и т.д.",
                emoji="<:realmomne:1539649281575620618>",
                value="real"
            ),
            disnake.SelectOption(
                label="Diamond Coin-ы",
                description="Внутренняя валюта сервера",
                emoji="<:coins:1539649259245408340>",
                value="coins"
            ),
            disnake.SelectOption(
                label="Товары за Инвайты",
                description="Бесплатные товары за приглашения",
                emoji="<:hpp:1536788440761245726>",
                value="invites"
            )
        ]
        super().__init__(
            placeholder="Выберите тип товаров...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="catalog_type_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        value = inter.data.values[0]
        if value == "real":
            embed = disnake.Embed(
                color=6776679,
                title="Выбор для покупки в каталоге товаров",
                description="Ниже, представлены цены, на интересующие вас категории, ознакомьтесь."
            )
            embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8679e3&is=6a852863&hm=2846271def3b36c9d96bb56818b8f3cf22e071ef66a90ab4da459e40de563255&")
            await inter.response.send_message(embed=embed, view=CatalogView(), ephemeral=True)
        elif value == "coins":
            await inter.response.send_message("Выберите категорию товара:", ephemeral=True, view=BuySelectView())
        elif value == "invites":
            embeds = load_action_embed("menu_happy.json")
            await inter.response.send_message(embeds=embeds, ephemeral=True)

class CatalogTypeView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CatalogTypeSelect())

# ============================================================
# КАТАЛОГ ДЛЯ РЕАЛЬНЫХ ДЕНЕГ
# ============================================================
CATALOG_OPTIONS = [
    {"label": "・BuyAll", "description": "Покупка всего ・Всё в одном месте",
     "emoji": "<:buyall:1489833017047253032> ", "json_path": os.path.join(CATALOG_DIR, "menu_buyall.json")},
    {"label": "・Discord", "description": "Покупка Nitro и Boosts ・Статус и величие",
     "emoji": "<:Discord:1464831837300854936>", "json_path": os.path.join(CATALOG_DIR, "menu_discord.json")},
    {"label": "・Steam", "description": "Пополнение и очки ・Свобода к играм",
     "emoji": "<:Steam:1464833200416100402>", "json_path": os.path.join(CATALOG_DIR, "menu_steam.json")},
    {"label": "・Telegram", "description": "Звезды и Подарки ・Индивидуальность и защита",
     "emoji": "<:Telegram:1465720888677896314>", "json_path": os.path.join(CATALOG_DIR, "menu_telegram.json")},
    {"label": "・Украшение Discord", "description": "Украшения и Бейджики ・Изысканность и красота",
     "emoji": "<:Decoration:1465729329290936403>", "json_path": os.path.join(CATALOG_DIR, "menu_decoration.json")},
    {"label": "・Roblox", "description": "Донат и Помощь ・Красота и играбельность",
     "emoji": "<:Roblox:1465752155251150911>", "json_path": os.path.join(CATALOG_DIR, "menu_roblox.json")},
    {"label": "・Epic Games", "description": "Фортнайт и Аккаунт ・ Заработок и донат",
     "emoji": "<:EpicGames:1465765441887797248>", "json_path": os.path.join(CATALOG_DIR, "menu_epic.json")},
    {"label": "・Supercell", "description": "Brawl Stars и Clash Royale ・Динамика и богатство",
     "emoji": "<:SuperCell:1465768886484996260>", "json_path": os.path.join(CATALOG_DIR, "menu_supersell.json")},
    {"label": "・Spotify", "description": "Подписка на музыку ・Громкость и красочность",
     "emoji": "<:Spotify:1465770796411785330>", "json_path": os.path.join(CATALOG_DIR, "menu_spotify.json")},
    {"label": "・Дизайн", "description": "Отличный дизайн ・Выбор для лучших",
     "emoji": "<:Design:1465771436580012106>", "json_path": os.path.join(CATALOG_DIR, "menu_design.json")},
    {"label": "・Бот для Дискорда", "description": "Рабочий и легкий ・Плавность и скорость",
     "emoji": "<:Bot:1465771816080380109>", "json_path": os.path.join(CATALOG_DIR, "menu_bot.json")},
]

class CatalogSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label=item["label"],
                description=item["description"],
                emoji=item["emoji"],
                value=item["json_path"]
            ) for item in CATALOG_OPTIONS
        ]
        super().__init__(
            placeholder="Выберите категорию...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="catalog_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        json_path = self.values[0]
        try:
            if not os.path.exists(json_path):
                return await inter.response.send_message("Файл с embed не найден.", ephemeral=True)
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.send_message(embeds=embeds, ephemeral=True)
            await log_discord(
                title="📂 Выбор категории (Каталог)",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Категория:** `{json_path}`",
                color=0x00aaff,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        except Exception as e:
            logger.exception("CatalogSelect callback error: %s", e)

class CatalogView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CatalogSelect())

# ============================================================
# КАТАЛОГ ДЛЯ ПОКУПКИ ЗА DC
# ============================================================
class BuySelectView(View):
    def __init__(self):
        super().__init__(timeout=None)  # исправлено
        catalog = load_shop_catalog()
        options = []
        for key, cat in catalog.items():
            emoji = cat.get("label", "").split()[0] if " " in cat.get("label", "") else "📦"
            label = cat.get("label", key)
            options.append(SelectOption(
                label=label[:100],
                description=cat.get("description", "")[:100],
                value=key,
                emoji=emoji
            ))
        select = Select(placeholder="Выберите категорию товара...", options=options, custom_id="buy_category")
        select.callback = self.category_callback
        self.add_item(select)

    async def category_callback(self, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        category = inter.data.values[0]
        catalog = load_shop_catalog()
        items = catalog.get(category, {}).get("items", {})
        if not items:
            return await inter.edit_original_response(content="❌ В этой категории пока нет товаров.")
        options = []
        for key, item in items.items():
            label = f"{item['name']} - {item['price']} DC"
            if len(label) > 100:
                label = label[:97] + "..."
            options.append(SelectOption(
                label=label,
                description=item.get("description", "")[:100],
                value=f"{category}_{key}"
            ))
        view = View(timeout=None)
        select2 = Select(placeholder="Выберите товар...", options=options, custom_id="buy_item")
        select2.callback = self.item_callback
        view.add_item(select2)
        back_btn = Button(label="🔙 Назад", style=ButtonStyle.gray, custom_id="buy_back")
        back_btn.callback = self.back_callback
        view.add_item(back_btn)
        await inter.edit_original_response(content="Выберите товар из категории:", view=view)

    async def item_callback(self, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        value = inter.data.values[0]
        try:
            category, item_key = value.split("_", 1)
        except ValueError:
            return await inter.edit_original_response(content="❌ Ошибка формата товара.")
        catalog = load_shop_catalog()
        item = catalog.get(category, {}).get("items", {}).get(item_key)
        if not item:
            return await inter.edit_original_response(content="❌ Товар не найден.")

        embed = disnake.Embed(
            title="🛒 Информация о товаре:",
            description=(
                f"> **Название:** {item['name']}\n\n"
                f"> **Описание:** {item['description']}\n\n"
                "Как покупаем данный товар, выберите способ ниже:\n\n"
            ),
            color=6776679
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")

        select = Select(
            placeholder="Как купить товар?",
            min_values=1,
            max_values=1,
            options=[
                SelectOption(
                    label="Купить себе",
                    description="Приобрести товар для себя",
                    emoji="<:people:1538395694648529009>",
                    value="self"
                ),
                SelectOption(
                    label="Подарить товар",
                    description="Приобрести товар для другого участника",
                    emoji="<:gist:1541657784926339153>",
                    value="gift"
                )
            ],
            custom_id="buy_way_select"
        )
        select.callback = self.create_select_callback(inter, category, item_key, item)
        view = View(timeout=300)
        view.add_item(select)
        await inter.edit_original_response(content=None, embed=embed, view=view)

    def create_select_callback(self, original_inter, category, item_key, item):
        async def callback(inter: disnake.MessageInteraction):
            if inter.author.id != original_inter.author.id:
                return await inter.response.send_message("⛔ Это не ваш выбор.", ephemeral=True)
            value = inter.data.values[0]
            if value == "self":
                await self.process_buy(inter, category, item_key, item, None)
            elif value == "gift":
                await inter.response.send_modal(GiftRecipientModal(self, original_inter, category, item_key, item))
        return callback

    async def process_buy(self, inter, category, item_key, item, recipient_id=None):
        user_id = inter.author.id if recipient_id is None else recipient_id
        price = item["price"]
        balance = await get_user_balance(inter.author.id)
        if balance < price:
            return await inter.response.send_message(f"❌ Недостаточно DC. Нужно: **{price} DC**, у вас: **{balance} DC**.", ephemeral=True)

        if category == "roles" and item.get("role_id"):
            role_id = item["role_id"]
            role = inter.guild.get_role(role_id)
            if role:
                if role in inter.author.roles:
                    return await inter.response.send_message(f"❌ У вас уже есть роль **{role.name}**.", ephemeral=True)
                purchases = await get_user_purchases(inter.author.id, only_unused=True)
                for p in purchases:
                    if p.get('type') == 'roles' and p.get('value') == item['name']:
                        return await inter.response.send_message(f"❌ Вы уже купили эту роль, но она ещё не выдана.", ephemeral=True)
            else:
                return await inter.response.send_message("❌ Роль не найдена на сервере.", ephemeral=True)

        success = await remove_dc(inter.author.id, price, f"Покупка: {item['name']}" + (f" (подарок для <@{recipient_id}>)" if recipient_id else ""))
        if not success:
            return await inter.response.send_message("❌ Не удалось списать DC. Попробуйте позже.", ephemeral=True)

        target_id = recipient_id if recipient_id else inter.author.id
        await add_purchase(target_id, category, item["name"])

        if category == "roles" and item.get("role_id"):
            role = inter.guild.get_role(item["role_id"])
            if role:
                try:
                    target_member = inter.guild.get_member(target_id)
                    if target_member:
                        await target_member.add_roles(role)
                        await inter.response.send_message(
                            f"✅ Вы купили роль **{item['name']}** за **{price} DC**!\n"
                            f"🎭 Роль **{role.name}** выдана {target_member.mention}.\n"
                            f"📝 Не забудьте оставить отзыв в <#1462074763437543435>.",
                            ephemeral=True
                        )
                        await log_discord(
                            title="🛒 Покупка роли в магазине DC",
                            description=f"> **Покупатель:** {inter.author.mention}\n> **Получатель:** {target_member.mention}\n> **Роль:** {item['name']}\n> **Цена:** {price} DC",
                            color=0x00aaff
                        )
                        return
                    else:
                        await add_dc(inter.author.id, price, "Возврат DC (получатель не найден)")
                        await inter.response.send_message("❌ Получатель не найден на сервере. Средства возвращены.", ephemeral=True)
                        return
                except Exception as e:
                    await add_dc(inter.author.id, price, "Возврат DC (ошибка выдачи роли)")
                    await inter.response.send_message(
                        f"❌ Не удалось выдать роль: {e}\n"
                        f"💎 {price} DC возвращены на баланс.",
                        ephemeral=True
                    )
                    return
            else:
                await add_dc(inter.author.id, price, "Возврат DC (роль не найдена)")
                await inter.response.send_message("❌ Роль не найдена на сервере. Средства возвращены.", ephemeral=True)
                return

        if recipient_id:
            await inter.response.send_message(
                f"✅ Вы купили **{item['name']}** за **{price} DC** и подарили <@{recipient_id}>!\n"
                f"📦 Товар уже в инвентаре получателя.\n"
                f"📝 Не забудьте оставить отзыв в <#1462074763437543435>.",
                ephemeral=True
            )
            await log_discord(
                title="🎁 Покупка в подарок",
                description=f"> **Покупатель:** {inter.author.mention}\n> **Получатель:** <@{recipient_id}>\n> **Товар:** {item['name']}\n> **Цена:** {price} DC",
                color=0xffaa00,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        else:
            await inter.response.send_message(
                f"✅ Вы купили **{item['name']}** за **{price} DC**!\n"
                f"📦 Товар будет выдан в ближайшее время.\n"
                f"📝 Не забудьте оставить отзыв в <#1462074763437543435>.",
                ephemeral=True
            )
            await log_discord(
                title="🛒 Покупка в магазине DC",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {item['name']}\n> **Цена:** {price} DC",
                color=0x00aaff
            )

    async def back_callback(self, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        await inter.edit_original_response(content="Выберите категорию:", view=BuySelectView())

class GiftRecipientModal(Modal):
    def __init__(self, buy_view, original_inter, category, item_key, item):
        self.buy_view = buy_view
        self.original_inter = original_inter
        self.category = category
        self.item_key = item_key
        self.item = item
        components = [
            TextInput(
                label="Введите ID получателя",
                placeholder="Например, 123456789012345678",
                custom_id="recipient_id",
                min_length=1,
                max_length=30
            )
        ]
        super().__init__(title="Подарок", components=components)

    async def callback(self, inter: disnake.MessageInteraction):
        recipient_input = inter.text_values["recipient_id"].strip()
        if not recipient_input.isdigit():
            return await inter.response.send_message("❌ Введите корректный ID (только цифры).", ephemeral=True)
        recipient_id = int(recipient_input)
        if recipient_id == inter.author.id:
            return await inter.response.send_message("❌ Вы не можете подарить товар самому себе.", ephemeral=True)
        guild = inter.guild
        recipient_member = guild.get_member(recipient_id)
        if not recipient_member:
            return await inter.response.send_message("❌ Пользователь с таким ID не найден на сервере.", ephemeral=True)
        if recipient_member.bot:
            return await inter.response.send_message("❌ Нельзя дарить товар ботам.", ephemeral=True)

        await self.buy_view.process_buy(inter, self.category, self.item_key, self.item, recipient_id)

# ============================================================
# ПАНЕЛЬ ТИКЕТОВ
# ============================================================
class TicketPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤㅤКупитьㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:buy",
        emoji=PartialEmoji(name="shopg", id=1539646815530651718)
    )
    async def buy(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        embed = disnake.Embed(
            color=6776679,
            title="Выбор категории по оплате",
            description="В какой валюте вы хотите купить товар? Если у вас есть вопрос, вы можете его задать, выбрав соответствующий пункт ниже."
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8679e3&is=6a852863&hm=2846271def3b36c9d96bb56818b8f3cf22e071ef66a90ab4da459e40de563255&")
        view = BuyTypeView()
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)

    @disnake.ui.button(
        label="ㅤПромокодыㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:promo",
        emoji=PartialEmoji(name="prom1", id=1539646792139014234)
    )
    async def promo(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        text = "🎟️ Промокоды публикуются в <#1462070136856117258>, следи и забирай свою скидку!"
        await inter.response.send_message(text, ephemeral=True)
        await log_discord(
            title="🎟️ Просмотр промокодов",
            description=f"> **Пользователь:** {inter.author.mention}",
            color=0x00ff00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    @disnake.ui.button(
        label="ㅤКаталогㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:catalog",
        emoji=PartialEmoji(name="catal", id=1539646769053306980)
    )
    async def catalog(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        embed = disnake.Embed(
            title="Выбор категории товаров",
            description="В чем представлен ваш товар? Выберите метод ниже.",
            color=6776679
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307090772079/image.png?ex=6a8679e3&is=6a852863&hm=59892e8783bfb24b381e2a76e3689f727bef8f1e3aea9595dd3d130b587dede4&")
        view = CatalogTypeView()
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)

# ============================================================
# ОБРАБОТЧИК ИНТЕРАКЦИЙ
# ============================================================
async def handle_interaction(inter: disnake.MessageInteraction):
    if inter.data.get("custom_id") == "menu:buy_ticket":
        await inter.response.send_modal(BuyTicketModal())
