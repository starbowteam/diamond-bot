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
    get_user_tickets_count_in_category
)
from modules.dc import (
    add_dc, remove_dc, add_purchase,
    get_user_purchases, remove_purchase,
    get_dc_cache, save_dc_cache,
    load_shop_catalog
)

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
        from core.bot import bot
        uid = inter.author.id
        now = time.time()
        last = getattr(bot, "_user_ticket_cooldowns", {})
        if uid in last and now - last[uid] < CONFIG["TICKET_COOLDOWN_SECONDS"]:
            remaining = int(CONFIG["TICKET_COOLDOWN_SECONDS"] - (now - last[uid]))
            return await inter.response.send_message(f"⏳ Подождите {remaining} сек.", ephemeral=True)
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
            return await inter.response.send_message("❌ Категория не найдена", ephemeral=True)

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

        view = TicketView(ticket_channel, inter.author.id)

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
        select_view = SelectView(ticket_channel)
        await ticket_channel.send(embed=select_embed, view=select_view)

        await inter.response.send_message(f"✅ Тикет создан: {ticket_channel.mention}", ephemeral=True)

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
        from core.bot import bot
        uid = inter.author.id
        now = time.time()
        last = getattr(bot, "_user_ticket_cooldowns", {})
        if uid in last and now - last[uid] < CONFIG["TICKET_COOLDOWN_SECONDS"]:
            remaining = int(CONFIG["TICKET_COOLDOWN_SECONDS"] - (now - last[uid]))
            return await inter.response.send_message(f"⏳ Подождите {remaining} сек.", ephemeral=True)
        last[uid] = now
        bot._user_ticket_cooldowns = last

        item = inter.text_values.get("item_name", "—")

        guild = inter.guild
        cat = guild.get_channel(CONFIG["COINS_CATEGORY_ID"])
        if not cat:
            return await inter.response.send_message("❌ Категория не найдена", ephemeral=True)

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
        view = CoinsTicketButtons(ticket_channel, inter.author.id)

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

        await inter.response.send_message(f"✅ Тикет создан: {ticket_channel.mention}", ephemeral=True)

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
# ВЫБОР ТИПА ПОКУПКИ
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
            )
        ]
        super().__init__(
            placeholder="Выберите способ оплаты...",
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

class BuyTypeView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BuySelect())

# ============================================================
# СЕЛЕКТ-МЕНЮ ДЛЯ ТИКЕТОВ
# ============================================================
class TicketActionSelect(disnake.ui.StringSelect):
    def __init__(self, channel):
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
        self.channel = channel

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

class SelectView(View):
    def __init__(self, channel):
        super().__init__(timeout=None)
        self.add_item(TicketActionSelect(channel))

# ============================================================
# ОСНОВНОЙ VIEW С КНОПКАМИ (РЕАЛЬНЫЕ ДЕНЬГИ)
# ============================================================
class TicketView(View):
    def __init__(self, channel, user_id):
        super().__init__(timeout=None)
        self.channel = channel
        self.user_id = user_id

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
        if not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие тикетов.", ephemeral=True)
        confirm = ConfirmCloseView(inter.channel)
        await inter.response.send_message("Подтвердите закрытие", view=confirm, ephemeral=True)
        await log_discord(
            title="🔒 Запрос на закрытие тикета (реальные деньги)",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
            color=0xffaa00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    async def pay_callback(self, inter: disnake.MessageInteraction):
        if not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на подтверждение оплаты.", ephemeral=True)

        msg = inter.message
        if not msg.embeds or len(msg.embeds) < 2:
            async for m in self.channel.history(limit=50):
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
            await inter.channel.edit(category=paid_category)
        else:
            logger.warning("PAID_CATEGORY_ID not found: %s", CONFIG["PAID_CATEGORY_ID"])

        manager_role = inter.guild.get_role(CONFIG["MANAGER_ROLE_ID"])
        manager_ping = manager_role.mention if manager_role else "@менеджер"
        await inter.channel.send(
            f"💚 {manager_ping} — заказ подтверждён как **оплаченный**!\n"
            f"> Подтвердил: {inter.author.mention}"
        )

        await inter.response.send_message("✅ Заказ отмечен как оплаченный.", ephemeral=True)

        member = inter.author
        await remove_ticket_role(member, CONFIG["TICKET_ROLES"]["real_created"])
        await assign_ticket_role(member, CONFIG["TICKET_ROLES"]["real_paid"])

        await log_discord(
            title="💰 Заказ оплачен",
            description=(
                f"> **Канал:** {inter.channel.mention}\n"
                f"> **Товар:** `{item_name}`\n"
                f"> **Оплата:** `{payment_method}`\n"
                f"> **Промокод:** `{promo_value}`\n"
                f"> **Подтвердил:** {inter.author.mention}"
            ),
            color=0x2ecc71,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    async def discounts_callback(self, inter: disnake.MessageInteraction):
        owner_id = get_ticket_owner(inter.channel.id)
        if not owner_id or inter.author.id != owner_id:
            return await inter.response.send_message("⛔ Эта кнопка доступна только создателю тикета.", ephemeral=True)

        discount_applied = False
        async for msg in self.channel.history(limit=50):
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
            async for msg in self.channel.history(limit=50):
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

            async for msg in self.channel.history(limit=50):
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
                description=f"> **Пользователь:** {inter.author.mention}\n> **Тикет:** {self.channel.mention}\n> **Скидка:** {item_value}",
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
        if not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие тикетов.", ephemeral=True)
        confirm = ConfirmCloseView(inter.channel)
        await inter.response.send_message("Подтвердите закрытие", view=confirm, ephemeral=True)
        await log_discord(
            title="🔒 Запрос на закрытие тикета (оплаченный)",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
            color=0xffaa00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

# ============================================================
# КНОПКИ ДЛЯ ТИКЕТОВ ЗА DC/ИНВАЙТЫ
# ============================================================
class CoinsTicketButtons(View):
    def __init__(self, channel, user_id):
        super().__init__(timeout=None)
        self.channel = channel
        self.user_id = user_id
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
        if not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие тикетов.", ephemeral=True)
        confirm = ConfirmCloseView(inter.channel)
        await inter.response.send_message("Подтвердите закрытие", view=confirm, ephemeral=True)
        await log_discord(
            title="🔒 Запрос на закрытие тикета (DC/Инвайты)",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
            color=0xffaa00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

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
        if inter.author.id != self.user_id:
            return await inter.response.send_message("⛔ Эта кнопка доступна только создателю тикета.", ephemeral=True)

        if self.message and self.message.embeds:
            embed = self.message.embeds[self.order_embed_index] if len(self.message.embeds) > self.order_embed_index else None
            if embed:
                for field in embed.fields:
                    if "подтверждение наличия" in field.name.lower():
                        if field.value.strip("`\n ") != "Не активирован":
                            return await inter.response.send_message("❌ К данному тикету уже применён товар.", ephemeral=True)
                        break

        all_purchases = await get_user_purchases(self.user_id, only_unused=True)
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
                custom_id=f"apply_coins_{self.user_id}_{idx}"
            )
            btn.callback = self.create_apply_callback(idx, inter, purchases)
            view.add_item(btn)

        await inter.response.send_message(embeds=embeds, view=view, ephemeral=True)

    def create_apply_callback(self, purchase_index, original_inter, purchases):
        async def callback(inter: disnake.MessageInteraction):
            if inter.author.id != self.user_id:
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

            full_purchases = await get_user_purchases(self.user_id, only_unused=False)
            target = None
            target_index = None
            for i, p in enumerate(full_purchases):
                if p['value'] == item_value and p.get('type') != 'discounts' and not p.get('used'):
                    target = p
                    target_index = i
                    break
            if target_index is None:
                return await inter.response.send_message("❌ Товар не найден.", ephemeral=True)

            success = await remove_purchase(self.user_id, target_index)
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
                description=f"> **Пользователь:** {inter.author.mention}\n> **Тикет:** {self.channel.mention}\n> **Товар:** {item_value}",
                color=0x00aaff,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        return callback

class ConfirmCloseView(View):
    def __init__(self, channel):
        super().__init__(timeout=60)
        self.channel = channel

    @disnake.ui.button(
        label="Подтвердить закрытие",
        style=disnake.ButtonStyle.gray,
        custom_id="confirm:close",
        emoji=PartialEmoji(name="OffTicket", id=1539657125716824185)
    )
    async def confirm(self, button, inter: disnake.MessageInteraction):
        if not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие тикетов.", ephemeral=True)

        await inter.response.send_message("Тикет удаляется...", ephemeral=True)
        await asyncio.sleep(2)

        try:
            await clear_ticket_owner(self.channel)
            await self.channel.delete()
            await log_discord(
                title="🗑️ Тикет закрыт",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {self.channel.name}",
                color=0xff6600,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        except Exception as e:
            logger.error(f"Ошибка при закрытии тикета: {e}")
            try:
                await asyncio.sleep(3)
                await self.channel.delete()
            except Exception as e2:
                logger.error(f"Повторная ошибка при закрытии тикета: {e2}")

# ============================================================
# ВЫБОР ТИПА КАТАЛОГА (для кнопки "Каталог")
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
     "emoji": "<:SuperCell:1465768886484996260>", "json_path": os.path.join(CATALOG_DIR, "menu_brawl.json")},
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
# ПАНЕЛЬ ТИКЕТОВ (кнопки)
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
            title="Выбор категории оплаты товара",
            description="В чем представлен ваш товар? Выберите метод ниже."
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
# ОБРАБОТЧИК ИНТЕРАКЦИЙ (кнопки)
# ============================================================
async def handle_interaction(inter: disnake.MessageInteraction):
    if inter.data.get("custom_id") == "menu:buy_ticket":
        await inter.response.send_modal(BuyTicketModal())
