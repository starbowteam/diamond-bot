# -*- coding: utf-8 -*-
import os
import sys
import json
import asyncio
import time
import re
import io
import math
import disnake
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from disnake.ext import commands
from disnake.ui import Modal, TextInput, View, Button, Select
from disnake import PartialEmoji, ui, ButtonStyle, Embed, SelectOption

# ============================================================
# Импорты из core.utils
# ============================================================
from core.utils import (
    CONFIG, FILES, BASE_DIR, DATA_DIR, CATALOG_DIR, ADD_DIR, ACTIONS_DIR,
    db, cur,
    logger,
    load_json, save_json, now_ts,
    log_discord, log_command,
    has_admin_command_roles, has_review_moderation_roles,
    has_ticket_view_roles, has_ticket_manage_roles,
    clean_embed_for_discohook, parse_emoji,
    update_user_roles,
    get_roles_for_count,
    get_dc_cache, save_dc_cache,
    get_promo_codes, add_promo_code, remove_promo_code, clear_promo_codes,
    add_ticket_owner, remove_ticket_owner, get_ticket_owner,
    get_user_tickets_count_in_category, get_user_ticket_channels_ids
)

# ============================================================
# Импорт из modules.dc
# ============================================================
from modules.dc import (
    get_user_balance, add_dc, remove_dc,
    add_purchase, get_user_purchases, remove_purchase,
    get_dc_cache, save_dc_cache,
    get_progress_bar,
    load_shop_catalog,
    sync_dc_to_json, get_dc_cache_all
)

# ============================================================
# Импорт из modules.actions
# ============================================================
from modules.actions import load_action_embed

# ============================================================
# Загружаем промокоды в память
# ============================================================
promo_codes = get_promo_codes()

def reload_promo_cache():
    global promo_codes
    promo_codes = get_promo_codes()

# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ РОЛЕЙ ТИКЕТОВ
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
# Функция загрузки "Доски" (board.json из ADD_DIR)
# ============================================================
def load_board_embed() -> list[Embed]:
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
# Функции загрузки эмбедов из add/*.json
# ============================================================
def load_embed_from_file(filename: str) -> list[Embed]:
    path = os.path.join(ADD_DIR, filename)
    if not os.path.exists(path):
        return [disnake.Embed(
            title="❌ Файл не найден",
            description=f"Файл `{filename}` отсутствует в папке add.",
            color=0xff0000
        )]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        embeds = []
        for e in data.get("embeds", []):
            embeds.append(disnake.Embed.from_dict(clean_embed_for_discohook(e)))
        return embeds
    except Exception as e:
        logger.error(f"Ошибка загрузки {filename}: {e}")
        return [disnake.Embed(
            title="❌ Ошибка загрузки",
            description=f"Не удалось загрузить {filename}.",
            color=0xff0000
        )]

# ============================================================
# Класс для модерации отзывов (без изменений)
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
# ТИКЕТЫ (МОДАЛКИ) – с отдельным сообщением для селекта
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
            reload_promo_cache()
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

        # Основное сообщение с заказом (с кнопками)
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

        # Создаём View с кнопками (закрыть, оплатить, скидки)
        view = TicketView(ticket_channel, inter.author.id)

        await ticket_channel.send(
            f"> Добрый день, {inter.author.mention}, ваш тикет создан. Ожидайте ответа от <@&1154757071330365490>\n"
            f"> Помните, по селекту ниже вы можете посмотреть реквизиты или политику, а кнопкой оплатить — подтвердить оплату.",
            embeds=[embeds_list[0], embed_order_info],
            view=view
        )

        # Отдельное сообщение с селект-меню (реквизиты/политика)
        select_embed = disnake.Embed(
            title="Что именно нужно посмотреть?",
            description="Выберите, что вы хотите увидеть, политику магазина, либо реквизиты? \n\nЕсли вы персонал, вам доступна кнопка оплатить.",
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
# СЕЛЕКТ-МЕНЮ (отдельное сообщение)
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
# ОСНОВНОЙ VIEW С КНОПКАМИ (для тикетов)
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

        # Проверяем, не применена ли уже скидка
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

        slid_embeds = load_embed_from_file("slid.json")
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

            # Повторная проверка на уже применённую скидку (на случай, если меню было открыто до применения)
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

            # Обновляем поле "Промокод" в заказе
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
        # Кнопка Закрыть – 1 пробел
        btn_close = Button(
            label="ㅤЗакрытьㅤ",
            style=ButtonStyle.gray,
            custom_id="ticket_paid:close",
            emoji=PartialEmoji(name="OffTicket", id=1539657125716824185),
            row=0
        )
        btn_close.callback = self.close_callback
        self.add_item(btn_close)

        # Кнопка Оплатить (disabled) – 1 пробел
        btn_pay = Button(
            label="ㅤОплатитьㅤ",
            style=ButtonStyle.gray,
            custom_id="ticket_paid:pay_done",
            emoji=PartialEmoji(name="Oplacheno", id=1539657164778512496),
            row=0,
            disabled=True
        )
        self.add_item(btn_pay)

        # Кнопка Скидки (disabled) – 2 пробела (не трогаем)
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
# КНОПКИ ДЛЯ ТИКЕТОВ ЗА DC/ИНВАЙТЫ (без изменений)
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

        # Проверяем, не применён ли уже товар к этому тикету
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

            # Повторная проверка на уже применённый товар (на случай, если меню было открыто до применения)
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
# ВЫБОР ТИПА ПОКУПКИ (для кнопки "Купить" в панели тикетов)
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
# НОВЫЙ ВЫБОР ТИПА КАТАЛОГА (для кнопки "Каталог" в панели тикетов)
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
# КАТАЛОГ (для реальных денег)
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
# ПАНЕЛЬ "СПРАВОЧНИК" (обновлённый – только работа, экосистема, доска)
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
# НОВАЯ ПАНЕЛЬ "ПРОФИЛЬ" (канал 1540018373503483934)
# ============================================================
PROFILE_CHANNEL_ID = 1540018373503483934

class ProfileSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="・Профиль",
                description="О себе ・Данные пользователя",
                emoji="<:people:1538395694648529009>",
                value="profile"
            ),
            disnake.SelectOption(
                label="・Управление покупками",
                description="Удобно・Узнай о покупке",
                emoji="<:cart:1538399645238165624>",
                value="purchases"
            ),
            disnake.SelectOption(
                label="・О валюте",
                description="Трата валюты・Её получение",
                emoji="<:buy:1538395716920148079>",
                value="currency"
            ),
            disnake.SelectOption(
                label="・Калькулятор",
                description="Расчет цен・Корзина покупок",
                emoji="<:calcu1:1538551848301109299>",
                value="calc"
            ),
            disnake.SelectOption(
                label="・Расчет скидки",
                description="Узнай и посчитай・Снижение цены",
                emoji="<:ckidsk:1538551877665427557>",
                value="discount"
            )
        ]
        super().__init__(
            placeholder="Выберите действие...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="profile_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await log_discord(
            title="👤 Выбор в панели профиля",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff
        )
        value = inter.data.values[0]
        if value == "profile":
            await show_profile(inter, inter.author)
        elif value == "purchases":
            # Показываем список неиспользованных покупок
            purchases = await get_user_purchases(inter.author.id, only_unused=True)
            if not purchases:
                return await inter.response.send_message("❌ У вас нет неиспользованных покупок.", ephemeral=True)
            # Отправляем эмбед с селектом
            embed = disnake.Embed(
                title="О какой покупке ты хочешь узнать?",
                description="> Выбери нужный товар ниже.",
                color=6776679
            )
            embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a887423&is=6a8722a3&hm=42c31ce6b67f4dbe9bc8e19eecfa29d805c871131064ccf76672953bff3573d6&")
            view = PurchaseSelectView(inter.author.id, purchases)
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)
        elif value == "currency":
            embeds = load_embed_from_file("vallue.json")
            await inter.response.send_message(embeds=embeds, ephemeral=True)
        elif value == "calc":
            await inter.response.send_modal(CalcModal())
        elif value == "discount":
            await inter.response.send_modal(DiscountModal())

class ProfileView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProfileSelect())

# ============================================================
# УПРАВЛЕНИЕ ПОКУПКАМИ (селект товаров и возврат)
# ============================================================
class PurchaseSelectView(View):
    def __init__(self, user_id, purchases):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.purchases = purchases
        options = []
        for idx, p in enumerate(purchases):
            label = p['value']
            if len(label) > 100:
                label = label[:97] + "..."
            options.append(SelectOption(
                label=label,
                description=f"Куплен: {datetime.fromtimestamp(p['date']).strftime('%d.%m.%Y')}",
                value=str(idx)
            ))
        select = Select(placeholder="Выберите товар...", options=options, custom_id="purchase_select")
        select.callback = self.purchase_select_callback
        self.add_item(select)

    async def purchase_select_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.user_id:
            return await inter.response.send_message("⛔ Это не ваш товар.", ephemeral=True)
        idx = int(inter.data.values[0])
        if idx >= len(self.purchases):
            return await inter.response.send_message("❌ Товар не найден.", ephemeral=True)
        p = self.purchases[idx]
        # Получаем цену товара из каталога
        catalog = load_shop_catalog()
        price = None
        for cat_key, cat_data in catalog.items():
            for item_key, item_data in cat_data.get("items", {}).items():
                if item_data.get("name") == p['value']:
                    price = item_data.get("price")
                    break
            if price is not None:
                break
        if price is None:
            price = 0  # Если не найдено, ставим 0
        embed = disnake.Embed(
            title="Информация о покупке!",
            description=(
                f"> **Товар:** {p['value']}\n"
                f"> **Куплен:** {datetime.fromtimestamp(p['date']).strftime('%d.%m.%Y')}\n\n"
                f"> **Цена:** {price} DC\n\n"
                "`Вы можете вернуть товар, получить DC обратно, но получите - только 75% Для этого - нажмите на кнопку ниже, в выборном меню.`"
            ),
            color=6776679
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a887423&is=6a8722a3&hm=42c31ce6b67f4dbe9bc8e19eecfa29d805c871131064ccf76672953bff3573d6&")
        view = ReturnItemView(self.user_id, idx, price)
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)

class ReturnItemView(View):
    def __init__(self, user_id, purchase_index, price):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.purchase_index = purchase_index
        self.price = price

    @disnake.ui.button(
        label="Вернуть товар",
        style=disnake.ButtonStyle.danger,
        custom_id="return_item"
    )
    async def return_item(self, button: Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.user_id:
            return await inter.response.send_message("⛔ Это не ваш товар.", ephemeral=True)
        # Проверяем, существует ли ещё покупка
        purchases = await get_user_purchases(self.user_id, only_unused=False)
        if self.purchase_index >= len(purchases):
            return await inter.response.send_message("❌ Этот товар уже был возвращён или применён.", ephemeral=True)
        p = purchases[self.purchase_index]
        # Удаляем покупку
        success = await remove_purchase(self.user_id, self.purchase_index)
        if not success:
            return await inter.response.send_message("❌ Ошибка при возврате товара.", ephemeral=True)
        # Рассчитываем 75%
        refund = int(self.price * 0.75)
        await add_dc(self.user_id, refund, f"Возврат товара: {p['value']} (75%)")
        await inter.response.send_message(
            f"✅ Товар **{p['value']}** возвращён!\n"
            f"💎 Вам начислено **{refund} DC** (75% от стоимости).",
            ephemeral=True
        )
        await log_discord(
            title="🔄 Возврат товара",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {p['value']}\n> **Возвращено:** {refund} DC",
            color=0xffaa00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

# ============================================================
# МОДАЛКИ ДЛЯ КАЛЬКУЛЯТОРА И РАСЧЁТА СКИДКИ (перенесены в профиль)
# ============================================================
class CalcModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="Введите выражение",
                placeholder="Например: 2 + 2 * 10",
                custom_id="expression",
                min_length=1,
                max_length=100
            )
        ]
        super().__init__(title="🧮 Калькулятор", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        expr = inter.text_values["expression"].strip()
        allowed = set("0123456789+-*/().% ")
        if not all(c in allowed for c in expr):
            return await inter.response.send_message(
                "❌ Разрешены только цифры и операторы + - * / ( ) . %",
                ephemeral=True
            )
        try:
            result = eval(expr, {"__builtins__": None}, {})
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            await inter.response.send_message(
                f"🧮 **Результат:** `{result}`",
                ephemeral=True
            )
        except Exception as e:
            await inter.response.send_message(
                f"❌ Ошибка в выражении: {str(e)}",
                ephemeral=True
            )

class DiscountModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="Исходная цена",
                placeholder="Введите сумму",
                custom_id="price",
                min_length=1,
                max_length=20
            ),
            TextInput(
                label="Скидка (%)",
                placeholder="Введите процент скидки",
                custom_id="discount_percent",
                min_length=1,
                max_length=10
            )
        ]
        super().__init__(title="💰 Расчёт скидки", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        try:
            price = float(inter.text_values["price"].replace(",", ".").strip())
            discount = float(inter.text_values["discount_percent"].replace(",", ".").strip())
        except ValueError:
            return await inter.response.send_message("❌ Введите корректные числа.", ephemeral=True)

        if discount < 0 or discount > 100:
            return await inter.response.send_message("❌ Скидка должна быть от 0 до 100%.", ephemeral=True)

        final_price = price * (1 - discount / 100)
        savings = price - final_price

        embed = disnake.Embed(
            title="🧾 Результат расчёта скидки",
            color=0x2ecc71
        )
        embed.add_field(name="Исходная цена", value=f"`{price:.2f} ₽`", inline=True)
        embed.add_field(name="Скидка", value=f"`{discount:.0f}%`", inline=True)
        embed.add_field(name="Экономия", value=f"`{savings:.2f} ₽`", inline=True)
        embed.add_field(name="✅ Итоговая цена", value=f"**`{final_price:.2f} ₽`**", inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)

# ============================================================
# ФУНКЦИЯ ПОКАЗА ПРОФИЛЯ (для новой панели)
# ============================================================
async def show_profile(inter: disnake.MessageInteraction, user: disnake.Member):
    counts = load_json(FILES["review_counts"], {})
    count = counts.get(str(user.id), 0)
    target_role_ids = get_roles_for_count(count)
    buyer_roles = [inter.guild.get_role(rid) for rid in target_role_ids if rid]
    buyer_roles_names = ", ".join([r.mention for r in buyer_roles if r]) if buyer_roles else "Нет"
    top_role = user.top_role
    top_role_mention = top_role.mention if top_role else "Нет"
    balance = await get_user_balance(user.id)
    purchases = await get_user_purchases(user.id, only_unused=True)
    purchases_text = ""
    if purchases:
        for p in purchases:
            purchases_text += f"> {p['type']} {p['value']} - ⌛\n"
    else:
        purchases_text = "> Отсутствует"
    history = get_dc_cache(user.id).get("history", [])
    history_text = ""
    if history:
        for h in reversed(history[-5:]):
            date_str = datetime.fromtimestamp(h["date"]).strftime("%d.%m")
            sign = "+" if h["amount"] > 0 else ""
            history_text += f"[{date_str}] {sign}{h['amount']} DC — {h['reason']}\n"
    else:
        history_text = "Нет операций."
    joined_at = user.joined_at
    joined_str = joined_at.strftime("%d.%m.%Y") if joined_at else "Неизвестно"
    thresholds = [
        (1, "Клуб"),
        (2, "Бронзовый покупатель"),
        (4, "Серебряный покупатель"),
        (8, "Золотой покупатель"),
        (12, "Алмазный покупатель"),
        (17, "Изумрудный покупатель"),
        (23, "Аметистовый покупатель"),
        (25, "Легендарный покупатель"),
        (float('inf'), "Покупатель века")
    ]
    current_role_name = "Нет"
    next_role_name = "Клуб"
    next_threshold = 1
    for threshold, name in thresholds:
        if count >= threshold:
            current_role_name = name
        else:
            next_threshold = threshold
            next_role_name = name
            break
    if count >= 26:
        progress_bar = "█" * 10 + " (Максимум)"
        progress_text = "Вы достигли максимальной роли! 🎉"
    else:
        progress = min(count / next_threshold, 1.0)
        bar_length = 10
        filled = int(progress * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        progress_bar = f"{bar} {int(progress*100)}%"
        progress_text = f"Осталось {next_threshold - count} отзывов до {next_role_name}"
    role_color = 0x676767
    if count >= 26:
        role_color = 0xb3d9ff
    elif count >= 24:
        role_color = 0xe68585
    elif count >= 18:
        role_color = 0x9fc1ff
    elif count >= 13:
        role_color = 0x3d9e08
    elif count >= 9:
        role_color = 0x149bd0
    elif count >= 5:
        role_color = 0xae7911
    elif count >= 3:
        role_color = 0xb0b0b0
    elif count >= 1:
        role_color = 0xd15640
    embed = disnake.Embed(
        title=f"📋 Профиль {user.display_name}",
        description=(
            f"> **Текущая роль:** {current_role_name}\n"
            f"> **Следующая:** {next_role_name}\n"
            f"> **Прогресс:** {progress_bar}\n"
            f"> {progress_text}\n\n"
            f"> **Покупатель:** {buyer_roles_names}\n"
            f"> **Отзывов:** {count}"
        ),
        color=role_color
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="💎 Diamond Coins", value=f"{balance} DC", inline=True)
    embed.add_field(name="👑 Высшая роль", value=top_role_mention, inline=True)
    embed.add_field(name="🛒 Купленные товары (ожидают)", value=purchases_text, inline=False)
    embed.add_field(name="📜 История (последние 5)", value=f">>> {history_text}", inline=False)
    embed.add_field(
        name="📑 О пользователе",
        value=f">>> ID: {user.id}\nНа сервере с {joined_str}",
        inline=False
    )
    await inter.response.send_message(embed=embed, ephemeral=True)

# ============================================================
# ФУНКЦИЯ ОТПРАВКИ ПАНЕЛИ ПРОФИЛЬ
# ============================================================
async def send_profile_panel():
    from core.bot import bot
    await bot.wait_until_ready()
    channel = bot.get_channel(PROFILE_CHANNEL_ID)
    if not channel:
        channel = await bot.fetch_channel(PROFILE_CHANNEL_ID)
    if not channel:
        logger.warning("Profile panel channel not found")
        return
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except:
                pass
            break
    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1540035577997561968/image.png?ex=6a887d66&is=6a872be6&hm=1bcc66c5be7dda618d9041cea46a5f6e5bb7d6f26ce9ad5bfae8e7ccd93f0e51&")
    embed2 = disnake.Embed(
        title="Твой профиль на сервере Diamond Shop",
        description="> В данном разделе, ты можешь - увидить свой профиль, свои покупки, возможно - отменить их, и получить возрат, но - 75%! Узнать, как купить что либо за Diamond Coin и многое другое! Не забудь о калькуляторе, и расчете скидок, для своих покупок!",
        color=6776679
    )
    embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a887423&is=6a8722a3&hm=42c31ce6b67f4dbe9bc8e19eecfa29d805c871131064ccf76672953bff3573d6&")
    await channel.send(embeds=[embed1, embed2], view=ProfileView())
    await log_discord(
        title="👤 Панель Профиль отправлена",
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
# МОДАЛКИ ДЛЯ КАЛЬКУЛЯТОРА И РАСЧЁТА СКИДКИ
# ============================================================
class CalcModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="Введите выражение",
                placeholder="Например: 2 + 2 * 10",
                custom_id="expression",
                min_length=1,
                max_length=100
            )
        ]
        super().__init__(title="🧮 Калькулятор", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        expr = inter.text_values["expression"].strip()
        allowed = set("0123456789+-*/().% ")
        if not all(c in allowed for c in expr):
            return await inter.response.send_message(
                "❌ Разрешены только цифры и операторы + - * / ( ) . %",
                ephemeral=True
            )
        try:
            result = eval(expr, {"__builtins__": None}, {})
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            await inter.response.send_message(
                f"🧮 **Результат:** `{result}`",
                ephemeral=True
            )
        except Exception as e:
            await inter.response.send_message(
                f"❌ Ошибка в выражении: {str(e)}",
                ephemeral=True
            )

class DiscountModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="Исходная цена",
                placeholder="Введите сумму",
                custom_id="price",
                min_length=1,
                max_length=20
            ),
            TextInput(
                label="Скидка (%)",
                placeholder="Введите процент скидки",
                custom_id="discount_percent",
                min_length=1,
                max_length=10
            )
        ]
        super().__init__(title="💰 Расчёт скидки", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        try:
            price = float(inter.text_values["price"].replace(",", ".").strip())
            discount = float(inter.text_values["discount_percent"].replace(",", ".").strip())
        except ValueError:
            return await inter.response.send_message("❌ Введите корректные числа.", ephemeral=True)

        if discount < 0 or discount > 100:
            return await inter.response.send_message("❌ Скидка должна быть от 0 до 100%.", ephemeral=True)

        final_price = price * (1 - discount / 100)
        savings = price - final_price

        embed = disnake.Embed(
            title="🧾 Результат расчёта скидки",
            color=0x2ecc71
        )
        embed.add_field(name="Исходная цена", value=f"`{price:.2f} ₽`", inline=True)
        embed.add_field(name="Скидка", value=f"`{discount:.0f}%`", inline=True)
        embed.add_field(name="Экономия", value=f"`{savings:.2f} ₽`", inline=True)
        embed.add_field(name="✅ Итоговая цена", value=f"**`{final_price:.2f} ₽`**", inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)

# ============================================================
# ПАНЕЛЬ ЭКОНОМИКИ (panel_dc) – с зарплатой и авансом
# ============================================================
SALARY_ROLES = {
    1471844291595731016: {"salary": 120, "advance": 50},
    1513935883475226796: {"salary": 90, "advance": 30},
    1154757071330365490: {"salary": 90, "advance": 30},
    1471190371181789234: {"salary": 70, "advance": 25},
    1457964854441672806: {"salary": 60, "advance": 20},
}
SALARY_ROLE_ORDER = [1471844291595731016, 1513935883475226796, 1154757071330365490, 1471190371181789234, 1457964854441672806]

class DCSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="・Начисление",
                description="Начисление валюты",
                emoji="<:__:1538399607699021895>",
                value="give"
            ),
            disnake.SelectOption(
                label="・Списать",
                description="Снятие валюты",
                emoji="<:minus:1538399627521429534>",
                value="take"
            ),
            disnake.SelectOption(
                label="・Покупки",
                description="Ручное управление покупками",
                emoji="<:cart:1538399645238165624>",
                value="purchases"
            ),
            disnake.SelectOption(
                label="・Акция",
                description="Ручное обновление акций",
                emoji="<:actops:1538399662921490432>",
                value="flash"
            ),
            disnake.SelectOption(
                label="・Зарплата",
                description="Выдача зарплаты сотруднику: 31 число.",
                emoji="<:zapa:1538557843228332053>",
                value="salary"
            ),
            disnake.SelectOption(
                label="・Аванс",
                description="Выдача аванса сотруднику: 15 число.",
                emoji="<:avans:1538557862689902733>",
                value="advance"
            )
        ]
        super().__init__(
            placeholder="Выберите действие...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="dc_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await log_discord(
            title="💰 Выбор в панели экономики",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff
        )
        value = inter.data.values[0]
        if value == "give":
            await inter.response.send_modal(GiveDcModal())
        elif value == "take":
            await inter.response.send_modal(TakeDcModal())
        elif value == "purchases":
            await inter.response.send_modal(ManagePurchasesModal())
        elif value == "flash":
            await inter.response.defer(ephemeral=True)
            from modules.actions import refresh_actions_panel
            await refresh_actions_panel()
            await inter.edit_original_message(content="✅ Меню Actions обновлено с новой акцией!")
            await log_discord(
                title="🔄 Акция обновлена",
                description=f"> **Админ:** {inter.author.mention} обновил акцию.",
                color=0x00aaff
            )
        elif value == "salary":
            await inter.response.defer(ephemeral=True)
            await self.process_salary(inter, "salary")
        elif value == "advance":
            await inter.response.defer(ephemeral=True)
            await self.process_salary(inter, "advance")

    async def process_salary(self, inter: disnake.MessageInteraction, mode: str):
        if not has_admin_command_roles(inter.author):
            await inter.edit_original_response(content="⛔ У вас нет прав на это действие.")
            return

        guild = inter.guild
        if not guild:
            await inter.edit_original_response(content="❌ Не удалось определить сервер.")
            return

        members = guild.members
        total = 0
        awarded = 0
        errors = 0
        stats = {role_id: 0 for role_id in SALARY_ROLE_ORDER}

        for member in members:
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
                await add_dc(member.id, amount, f"{'Зарплата' if mode == 'salary' else 'Аванс'} по роли {top_role_id}")
                stats[top_role_id] += 1
                awarded += 1
                total += amount
            except Exception as e:
                logger.error(f"Ошибка начисления {mode} пользователю {member.id}: {e}")
                errors += 1

        result_lines = []
        for role_id in SALARY_ROLE_ORDER:
            count = stats[role_id]
            if count > 0:
                role = guild.get_role(role_id)
                role_name = role.name if role else str(role_id)
                result_lines.append(f"**{role_name}** – {count} чел.")

        result_text = "\n".join(result_lines) if result_lines else "Никто не получил."

        await inter.edit_original_response(
            content=f"✅ **{'Зарплата' if mode == 'salary' else 'Аванс'}** выдана!\n"
                    f"👥 Всего сотрудников: {awarded}\n"
                    f"💎 Всего выдано: **{total} DC**\n"
                    f"📊 Распределение:\n{result_text}\n"
                    f"⚠️ Ошибок: {errors}"
        )

        await log_discord(
            title=f"💰 Выдача {'зарплаты' if mode == 'salary' else 'аванса'}",
            description=(
                f"> **Админ:** {inter.author.mention}\n"
                f"> **Сотрудников:** {awarded}\n"
                f"> **Всего выдано:** {total} DC\n"
                f"> **Ошибок:** {errors}\n"
                f"> **Распределение:**\n{result_text}"
            ),
            color=0x00ff00
        )

class DCView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DCSelect())

# ============================================================
# ПАНЕЛЬ ПРОМОКОДОВ (promocodes) – селект-меню
# ============================================================
class PromoSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="・Создать промокод",
                description="Добавление",
                emoji="<:__:1538399607699021895>",
                value="add"
            ),
            disnake.SelectOption(
                label="・Удалить промокод",
                description="Удаление",
                emoji="<:minus:1538399627521429534>",
                value="remove"
            ),
            disnake.SelectOption(
                label="・Список промокодов",
                description="Все существующие промокоды",
                emoji="<:list:1538400957803798588>",
                value="list"
            )
        ]
        super().__init__(
            placeholder="Выберите действие...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="promo_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await log_discord(
            title="🎟️ Выбор в панели промокодов",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff
        )
        value = inter.data.values[0]
        if value == "add":
            await inter.response.send_modal(PromoAddModal())
        elif value == "remove":
            await inter.response.send_message("Выберите промокод для удаления:", ephemeral=True, view=PromoRemoveSelectView())
        elif value == "list":
            reload_promo_cache()
            if not promo_codes:
                await inter.response.send_message("Промокодов нет.", ephemeral=True)
                return
            text = "\n".join([f"{code} → {value}" for code, value in promo_codes.items()])
            await inter.response.send_message(f"```\n{text}\n```", ephemeral=True)

class PromoView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PromoSelect())

# ============================================================
# ПАНЕЛЬ АДМИНА (admin_panel) – с очисткой и /say
# ============================================================
class ClearModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="ID канала",
                placeholder="Введите числовой ID канала",
                custom_id="channel_id",
                min_length=1,
                max_length=30
            ),
            TextInput(
                label="Количество сообщений",
                placeholder="От 1 до 100",
                custom_id="amount",
                min_length=1,
                max_length=3
            )
        ]
        super().__init__(title="🧹 Очистка канала", components=components)

    async def callback(self, inter: disnake.MessageInteraction):
        channel_id_str = inter.text_values["channel_id"].strip()
        amount_str = inter.text_values["amount"].strip()

        if not channel_id_str.isdigit():
            return await inter.response.send_message("❌ ID канала должен быть числом.", ephemeral=True)
        try:
            amount = int(amount_str)
        except ValueError:
            return await inter.response.send_message("❌ Количество должно быть числом.", ephemeral=True)

        if amount < 1 or amount > 100:
            return await inter.response.send_message("❌ Количество должно быть от 1 до 100.", ephemeral=True)

        channel_id = int(channel_id_str)
        guild = inter.guild
        if not guild:
            return await inter.response.send_message("❌ Не удалось определить сервер.", ephemeral=True)

        channel = guild.get_channel(channel_id)
        if not channel:
            return await inter.response.send_message("❌ Канал с таким ID не найден.", ephemeral=True)

        if not isinstance(channel, disnake.TextChannel):
            return await inter.response.send_message("❌ Это не текстовый канал.", ephemeral=True)

        bot_member = guild.get_member(inter.bot.user.id)
        if not channel.permissions_for(bot_member).manage_messages:
            return await inter.response.send_message("❌ У бота нет прав на удаление сообщений в этом канале.", ephemeral=True)

        try:
            deleted = await channel.purge(limit=amount, bulk=True)
            await inter.response.send_message(
                f"✅ Удалено **{len(deleted)}** сообщений в канале {channel.mention}.",
                ephemeral=True
            )
            await log_discord(
                title="🧹 Очистка канала",
                description=f"> **Админ:** {inter.author.mention}\n> **Канал:** {channel.mention}\n> **Удалено:** {len(deleted)}",
                color=0xff6600
            )
        except Exception as e:
            logger.exception("Ошибка очистки: %s", e)
            await inter.response.send_message(f"❌ Ошибка при очистке: {e}", ephemeral=True)

class AdminSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label="・Пересчет отзывов",
                description="Корректировка отзывов",
                emoji="<:bannersc1:1538401325522489395>",
                value="recalc"
            ),
            disnake.SelectOption(
                label="・Обновление баннера",
                description="Корректировка баннера",
                emoji="<:restart:1538401342391853118>",
                value="banner"
            ),
            disnake.SelectOption(
                label="・Выгрузка JSON",
                description="Сообщение - Скрипт",
                emoji="<:jsons:1538401299459080263>",
                value="json"
            ),
            disnake.SelectOption(
                label="・Очистка",
                description="Удаление сообщений в определенном чате",
                emoji="<:clear:1538561439491686410>",
                value="clear"
            )
        ]
        super().__init__(
            placeholder="Выберите действие...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="admin_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await log_discord(
            title="🔧 Выбор в админ-панели",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff
        )
        value = inter.data.values[0]
        if value == "recalc":
            await inter.response.defer(ephemeral=True)
            await recalc_reviews(inter)
        elif value == "banner":
            await inter.response.defer(ephemeral=True)
            from core.bot import update_review_counter
            await update_review_counter(silent=False)
        elif value == "json":
            await inter.response.send_modal(GetJsonModal())
        elif value == "clear":
            await inter.response.send_modal(ClearModal())

class AdminView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AdminSelect())

# ============================================================
# КОМАНДА /say (админ)
# ============================================================
@commands.slash_command(
    name="say",
    description="Отправить сообщение от бота (админ)"
)
async def say(
    ctx,
    канал: disnake.TextChannel,
    тип_сообщения: str = commands.Param(choices=["text", "embed"]),
    текст: Optional[str] = None,
    файл: Optional[disnake.Attachment] = None
):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)

    if тип_сообщения == "text":
        if not текст:
            return await ctx.send("Введите текст.", ephemeral=True)
        await канал.send(текст)
        await ctx.send("✅ Отправлено", ephemeral=True)
        await log_discord(
            title="📨 Say: текст",
            description=f"> **Админ:** {ctx.author.mention}\n> **Канал:** {канал.mention}",
            color=0x00ff00
        )
        return

    if тип_сообщения == "embed":
        if not текст and not файл:
            return await ctx.send("Укажите JSON или файл.", ephemeral=True)
        if текст and файл:
            return await ctx.send("Только один источник.", ephemeral=True)
        try:
            if файл:
                raw = await файл.read()
                data = json.loads(raw.decode("utf-8"))
            else:
                data = json.loads(текст)
            if "embeds" not in data:
                return await ctx.send("Нет поля 'embeds'.", ephemeral=True)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data["embeds"]]
            content = data.get("content", " ")
            await канал.send(content=content, embeds=embeds)
            await ctx.send("✅ Embed отправлен", ephemeral=True)
            await log_discord(
                title="📨 Say: embed",
                description=f"> **Админ:** {ctx.author.mention}\n> **Канал:** {канал.mention}",
                color=0x00ff00
            )
        except Exception as e:
            logger.exception("say embed error: %s", e)
            await ctx.send("❌ Ошибка.", ephemeral=True)

# ============================================================
# КОМАНДЫ (панели) – с проверкой роли
# ============================================================
@commands.slash_command(name="panel_dc", description="Экономическая панель Diamond Coins (админ)")
async def panel_dc(inter: disnake.ApplicationCommandInteraction):
    if not has_admin_command_roles(inter.author):
        return await inter.send("⛔ У вас нет прав.", ephemeral=True)
    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://media.discordapp.net/attachments/1527006158282555412/1538202627005874318/image.png?ex=6a81d254&is=6a8080d4&hm=638d4a0af652ad4a72f25c2d193abff8e74879cf2dd173079a863484559c1dca&=&format=webp&quality=lossless")
    embed2 = disnake.Embed(
        title="Экономическая панель Diamond Coins",
        description="> В данном разделе, происходит ручная корректировка валютного дела, связанного с акциями, и самой валютой, ниже - кнопки. Нажимай с умом.",
        color=6776679
    )
    embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307371667506/image.png?ex=6a8133e3&is=6a7fe263&hm=2af0f26a823ea59af3001dc16ce84920759e966bc40824095314e6cd1d9b38ca&")
    await inter.send(embeds=[embed1, embed2], ephemeral=True, view=DCView())

@commands.slash_command(name="promocodes", description="Управление промокодами (админ)")
async def promocodes(inter: disnake.ApplicationCommandInteraction):
    if not has_admin_command_roles(inter.author):
        return await inter.send("⛔ У вас нет прав.", ephemeral=True)
    embeds = [
        disnake.Embed(color=6776679).set_image(url="https://media.discordapp.net/attachments/1527006158282555412/1537853007754957021/image.png?ex=6a808cb8&is=6a7f3b38&hm=9a8ed29d187e151fe6fe207910dd8665d74b9e2ab794c62e364e72e17079d7f6&=&format=webp&quality=lossless"),
        disnake.Embed(
            title="Управление промокодами",
            description="> Используй данную панель, для управления промокодами.",
            color=6776679
        ).set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a808b23&is=6a7f39a3&hm=38fda4f54c273fb8cada8c1332a7f5fe77041eed1e642797bd7e8d92094252b7&")
    ]
    await inter.send(embeds=embeds, ephemeral=True, view=PromoView())

@commands.slash_command(name="admin_panel", description="Панель управления сервером (админ)")
async def admin_panel(inter: disnake.ApplicationCommandInteraction):
    if not has_admin_command_roles(inter.author):
        return await inter.send("⛔ У вас нет прав.", ephemeral=True)
    embeds = [
        disnake.Embed(color=6776679).set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851161233596556/image.png?ex=6a808b00&is=6a7f3980&hm=e19375ab0a3d1eae8df69da1ddcc71ded19ed8a6c53267f930e7bc8550a82796&"),
        disnake.Embed(
            title="Панель управление сервером",
            description="> С помощью данной панели, происходит управление сервером, старые команды, были заменены одной панелью, что дает доступ, в одном виде. Ниже - предоставлены кнопки. Используй с умом.",
            color=6776679
        ).set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a808b23&is=6a7f39a3&hm=38fda4f54c273fb8cada8c1332a7f5fe77041eed1e642797bd7e8d92094252b7&")
    ]
    await inter.send(embeds=embeds, ephemeral=True, view=AdminView())

# ============================================================
# КОМАНДА /gw_dc – выдача DC победителям розыгрыша из файла
# ============================================================
@commands.slash_command(
    name="gw_dc",
    description="Выдать DC победителям розыгрыша из файла (админ)"
)
async def gw_dc(
    ctx,
    amount: int = commands.Param(description="Количество DC для каждого победителя"),
    file: disnake.Attachment = commands.Param(description="Текстовый файл с ID победителей (по одному на строку)")
):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)

    if amount <= 0:
        return await ctx.send("❌ Количество DC должно быть больше 0.", ephemeral=True)

    if not file.filename.endswith('.txt'):
        return await ctx.send("❌ Файл должен быть в формате .txt", ephemeral=True)

    try:
        content = await file.read()
        text = content.decode('utf-8')
        lines = text.strip().splitlines()
        user_ids = []
        for line in lines:
            line = line.strip()
            if line.isdigit():
                user_ids.append(int(line))
            else:
                await ctx.send(f"⚠️ Строка '{line}' не является ID, пропущена.", ephemeral=True)

        if not user_ids:
            return await ctx.send("❌ В файле не найдено ни одного корректного ID.", ephemeral=True)

        success_count = 0
        fail_count = 0
        for uid in user_ids:
            try:
                await add_dc(uid, amount, f"Выигрыш в розыгрыше ({amount} DC)")
                success_count += 1
            except Exception as e:
                logger.error(f"Ошибка начисления {amount} DC пользователю {uid}: {e}")
                fail_count += 1

        await ctx.send(
            f"✅ Розыгрыш завершён!\n"
            f"👥 Всего участников: {len(user_ids)}\n"
            f"✅ Успешно начислено: {success_count}\n"
            f"❌ Ошибок: {fail_count}\n"
            f"💎 Всего выдано: {success_count * amount} DC",
            ephemeral=True
        )

        await log_discord(
            title="🎁 Выдача DC победителям розыгрыша",
            description=(
                f"> **Админ:** {ctx.author.mention}\n"
                f"> **Количество:** {amount} DC на человека\n"
                f"> **Участников:** {len(user_ids)}\n"
                f"> **Всего выдано:** {success_count * amount} DC"
            ),
            color=0xffaa00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    except Exception as e:
        logger.exception(f"Ошибка в команде gw_dc: {e}")
        await ctx.send(f"❌ Произошла ошибка: {e}", ephemeral=True)
        
# ============================================================
# МОДАЛКИ ДЛЯ DC-ПАНЕЛИ (без изменений)
# ============================================================
class GiveDcModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="ID пользователя или @упоминание", custom_id="user", placeholder="Введите ID или @username", min_length=2, max_length=50),
            TextInput(label="Количество DC", custom_id="amount", placeholder="Число", min_length=1, max_length=10),
            TextInput(label="Причина (необязательно)", custom_id="reason", required=False, placeholder="Причина начисления", max_length=200)
        ]
        super().__init__(title="Начислить DC", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        user_input = inter.text_values["user"].strip()
        try:
            amount = int(inter.text_values["amount"].strip())
            if amount <= 0:
                raise ValueError
        except:
            return await inter.response.send_message("❌ Введите корректное количество >0.", ephemeral=True)
        reason = inter.text_values.get("reason", "").strip() or "Начисление через панель"
        user_id = None
        if user_input.isdigit():
            user_id = int(user_input)
        else:
            match = re.search(r'<@!?(\d+)>', user_input)
            if match:
                user_id = int(match.group(1))
        if not user_id:
            return await inter.response.send_message("❌ Не удалось определить пользователя. Введите ID или @упоминание.", ephemeral=True)
        await add_dc(user_id, amount, reason)
        await inter.response.send_message(f"✅ Начислено {amount} DC пользователю <@{user_id}>.", ephemeral=True)

class TakeDcModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="ID пользователя или @упоминание", custom_id="user", placeholder="Введите ID или @username", min_length=2, max_length=50),
            TextInput(label="Количество DC", custom_id="amount", placeholder="Число", min_length=1, max_length=10),
            TextInput(label="Причина (необязательно)", custom_id="reason", required=False, placeholder="Причина списания", max_length=200)
        ]
        super().__init__(title="Снять DC", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        user_input = inter.text_values["user"].strip()
        try:
            amount = int(inter.text_values["amount"].strip())
            if amount <= 0:
                raise ValueError
        except:
            return await inter.response.send_message("❌ Введите корректное количество >0.", ephemeral=True)
        reason = inter.text_values.get("reason", "").strip() or "Списание через панель"
        user_id = None
        if user_input.isdigit():
            user_id = int(user_input)
        else:
            match = re.search(r'<@!?(\d+)>', user_input)
            if match:
                user_id = int(match.group(1))
        if not user_id:
            return await inter.response.send_message("❌ Не удалось определить пользователя.", ephemeral=True)
        success = await remove_dc(user_id, amount, reason)
        if success:
            await inter.response.send_message(f"✅ Снято {amount} DC у <@{user_id}>.", ephemeral=True)
        else:
            await inter.response.send_message(f"❌ Недостаточно DC у <@{user_id}>.", ephemeral=True)

class ManagePurchasesModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="ID пользователя", custom_id="user_id", placeholder="Введите числовой ID пользователя", min_length=1, max_length=30)
        ]
        super().__init__(title="Управление покупками", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        user_input = inter.text_values["user_id"].strip()
        if not user_input.isdigit():
            return await inter.response.send_message("❌ Введите корректный ID пользователя (только цифры).", ephemeral=True)
        user_id = int(user_input)
        purchases = await get_user_purchases(user_id, only_unused=True)
        if not purchases:
            return await inter.response.send_message(f"❌ У пользователя <@{user_id}> нет неиспользованных покупок.", ephemeral=True)
        select = Select(
            placeholder="Выберите покупку для удаления...",
            options=[]
        )
        for idx, p in enumerate(purchases):
            label = f"{p['type']} {p['value']}"
            if len(label) > 100:
                label = label[:97] + "..."
            select.options.append(SelectOption(label=label, value=str(idx), description=f"Дата: {datetime.fromtimestamp(p['date']).strftime('%d.%m.%Y')}"))
        view = View()
        view.add_item(select)
        async def select_callback(inter2: disnake.MessageInteraction):
            idx = int(inter2.data.values[0])
            success = await remove_purchase(user_id, idx)
            if success:
                await inter2.response.send_message(f"✅ Покупка удалена.", ephemeral=True)
            else:
                await inter2.response.send_message(f"❌ Ошибка удаления покупки.", ephemeral=True)
        select.callback = select_callback
        await inter.response.send_message(f"Выберите покупку пользователя <@{user_id}>, которую хотите удалить:", ephemeral=True, view=view)

# ============================================================
# МОДАЛКИ ДЛЯ ПРОМОКОДОВ И JSON
# ============================================================
class GetJsonModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Ссылка на сообщение", custom_id="link", placeholder="https://discord.com/channels/.../...", min_length=10, max_length=200)
        ]
        super().__init__(title="Получить JSON сообщения", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        link = inter.text_values["link"].strip()
        try:
            parts = link.strip("/").split("/")
            guild_id, channel_id, message_id = map(int, parts[-3:])
        except:
            return await inter.response.send_message("❌ Неверная ссылка.", ephemeral=True)
        try:
            from core.bot import bot
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            msg = await channel.fetch_message(message_id)
        except Exception as e:
            return await inter.response.send_message(f"Ошибка получения сообщения: {e}", ephemeral=True)
        payload = {"content": msg.content or " ", "embeds": [clean_embed_for_discohook(e.to_dict()) for e in msg.embeds]}
        buf = io.StringIO(json.dumps(payload, ensure_ascii=False, indent=2))
        await inter.response.send_message(file=disnake.File(fp=buf, filename="message.json"), ephemeral=True)
        await log_discord("📥 Выгрузка JSON", f"Админ {inter.author.mention} выгрузил JSON из {channel.mention}", color=0x00ff00)

class PromoAddModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Код промокода", custom_id="code", placeholder="Например VSEMPROMO25", min_length=2, max_length=50),
            TextInput(label="Скидка (например 10%)", custom_id="value", placeholder="10%", min_length=1, max_length=20)
        ]
        super().__init__(title="Добавить промокод", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        code = inter.text_values["code"].strip().upper()
        value = inter.text_values["value"].strip()
        add_promo_code(code, value)
        reload_promo_cache()
        await inter.response.send_message(f"✅ Промокод `{code}` добавлен → {value}", ephemeral=True)
        await log_discord("➕ Промокод добавлен", f"Админ {inter.author.mention} добавил `{code}` → {value}", color=0x00ff00)

class PromoRemoveSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        options = []
        reload_promo_cache()
        if not promo_codes:
            options.append(SelectOption(label="Нет промокодов", value="none", default=True))
        else:
            for code, value in promo_codes.items():
                label = f"{code} - {value}"
                if len(label) > 100:
                    label = label[:97] + "..."
                options.append(SelectOption(label=label, value=code))
        select = Select(placeholder="Выберите промокод для удаления...", options=options, custom_id="promo_remove_select")
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        code = inter.data.values[0]
        if code == "none":
            return await inter.response.send_message("Нет промокодов для удаления.", ephemeral=True)
        if code in promo_codes:
            remove_promo_code(code)
            reload_promo_cache()
            await inter.response.send_message(f"✅ Промокод `{code}` удалён.", ephemeral=True)
            await log_discord("➖ Промокод удалён", f"Админ {inter.author.mention} удалил `{code}`", color=0xff6600)
        else:
            await inter.response.send_message("❌ Промокод не найден.", ephemeral=True)

# ============================================================
# BuySelectView, show_profile, recalc_reviews
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

class BuySelectView(View):
    def __init__(self):
        super().__init__(timeout=None)
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
        user_id = inter.author.id
        balance = await get_user_balance(user_id)
        price = item["price"]
        if balance < price:
            return await inter.edit_original_response(content=f"❌ Недостаточно DC. Нужно: **{price} DC**, у вас: **{balance} DC**.")

        # ============================================================
        # ПРОВЕРКА ДЛЯ РОЛЕЙ (кроме кастомных)
        # ============================================================
        if category == "roles" and item.get("role_id"):
            role_id = item["role_id"]
            role = inter.guild.get_role(role_id)
            if role:
                # Проверяем, есть ли уже у пользователя эта роль
                if role in inter.author.roles:
                    return await inter.edit_original_response(
                        content=f"❌ У вас уже есть роль **{role.name}**. Вы не можете купить её повторно."
                    )
                # Проверяем, не куплена ли уже эта роль (в инвентаре есть неиспользованная)
                purchases = await get_user_purchases(user_id, only_unused=True)
                for p in purchases:
                    if p.get('type') == 'roles' and p.get('value') == item['name']:
                        return await inter.edit_original_response(
                            content=f"❌ Вы уже купили роль **{item['name']}**, но она ещё не выдана. Обратитесь к администратору."
                        )
            else:
                return await inter.edit_original_response(content="❌ Роль не найдена на сервере.")

        success = await remove_dc(user_id, price, f"Покупка: {item['name']}")
        if not success:
            return await inter.edit_original_response(content="❌ Не удалось списать DC. Попробуйте позже.")

        await add_purchase(user_id, category, item["name"])

        if category == "roles" and item.get("role_id"):
            role = inter.guild.get_role(item["role_id"])
            if role:
                try:
                    await inter.author.add_roles(role)
                    await inter.edit_original_response(
                        content=f"✅ Вы купили роль **{item['name']}** за **{price} DC**!\n"
                                f"🎭 Роль **{role.name}** выдана.\n"
                                f"📝 Не забудьте оставить отзыв в <#1462074763437543435>."
                    )
                    await log_discord(
                        title="🛒 Покупка роли в магазине DC",
                        description=f"> **Пользователь:** {inter.author.mention}\n> **Роль:** {item['name']}\n> **Цена:** {price} DC\n> **Категория:** {catalog[category]['label']}",
                        color=0x00aaff
                    )
                    return
                except Exception as e:
                    await add_dc(user_id, price, "Возврат DC (ошибка выдачи роли)")
                    await inter.edit_original_response(
                        content=f"❌ Не удалось выдать роль: {e}\n"
                                f"💎 {price} DC возвращены на баланс."
                    )
                    return
            else:
                await add_dc(user_id, price, "Возврат DC (роль не найдена)")
                await inter.edit_original_response(
                    content=f"❌ Роль не найдена на сервере.\n"
                            f"💎 {price} DC возвращены на баланс."
                )
                return

        await inter.edit_original_response(
            content=f"✅ Вы купили **{item['name']}** за **{price} DC**!\n"
                    f"📦 Товар будет выдан в ближайшее время.\n"
                    f"📝 Не забудьте оставить отзыв в <#1462074763437543435>."
        )
        await log_discord(
            title="🛒 Покупка в магазине DC",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {item['name']}\n> **Цена:** {price} DC\n> **Категория:** {catalog[category]['label']}",
            color=0x00aaff
        )

    async def back_callback(self, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        await inter.edit_original_response(content="Выберите категорию:", view=BuySelectView())

async def show_profile(inter: disnake.MessageInteraction, user: disnake.Member):
    counts = load_json(FILES["review_counts"], {})
    count = counts.get(str(user.id), 0)
    target_role_ids = get_roles_for_count(count)
    buyer_roles = [inter.guild.get_role(rid) for rid in target_role_ids if rid]
    buyer_roles_names = ", ".join([r.mention for r in buyer_roles if r]) if buyer_roles else "Нет"
    top_role = user.top_role
    top_role_mention = top_role.mention if top_role else "Нет"
    balance = await get_user_balance(user.id)
    purchases = await get_user_purchases(user.id, only_unused=True)
    purchases_text = ""
    if purchases:
        for p in purchases:
            purchases_text += f"> {p['type']} {p['value']} - ⌛\n"
    else:
        purchases_text = "> Отсутствует"
    history = get_dc_cache(user.id).get("history", [])
    history_text = ""
    if history:
        for h in reversed(history[-5:]):
            date_str = datetime.fromtimestamp(h["date"]).strftime("%d.%m")
            sign = "+" if h["amount"] > 0 else ""
            history_text += f"[{date_str}] {sign}{h['amount']} DC — {h['reason']}\n"
    else:
        history_text = "Нет операций."
    joined_at = user.joined_at
    joined_str = joined_at.strftime("%d.%m.%Y") if joined_at else "Неизвестно"
    thresholds = [
        (1, "Клуб"),
        (2, "Бронзовый покупатель"),
        (4, "Серебряный покупатель"),
        (8, "Золотой покупатель"),
        (12, "Алмазный покупатель"),
        (17, "Изумрудный покупатель"),
        (23, "Аметистовый покупатель"),
        (25, "Легендарный покупатель"),
        (float('inf'), "Покупатель века")
    ]
    current_role_name = "Нет"
    next_role_name = "Клуб"
    next_threshold = 1
    for threshold, name in thresholds:
        if count >= threshold:
            current_role_name = name
        else:
            next_threshold = threshold
            next_role_name = name
            break
    if count >= 26:
        progress_bar = "█" * 10 + " (Максимум)"
        progress_text = "Вы достигли максимальной роли! 🎉"
    else:
        progress = min(count / next_threshold, 1.0)
        bar_length = 10
        filled = int(progress * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)
        progress_bar = f"{bar} {int(progress*100)}%"
        progress_text = f"Осталось {next_threshold - count} отзывов до {next_role_name}"
    role_color = 0x676767
    if count >= 26:
        role_color = 0xb3d9ff
    elif count >= 24:
        role_color = 0xe68585
    elif count >= 18:
        role_color = 0x9fc1ff
    elif count >= 13:
        role_color = 0x3d9e08
    elif count >= 9:
        role_color = 0x149bd0
    elif count >= 5:
        role_color = 0xae7911
    elif count >= 3:
        role_color = 0xb0b0b0
    elif count >= 1:
        role_color = 0xd15640
    embed = disnake.Embed(
        title=f"📋 Профиль {user.display_name}",
        description=(
            f"> **Текущая роль:** {current_role_name}\n"
            f"> **Следующая:** {next_role_name}\n"
            f"> **Прогресс:** {progress_bar}\n"
            f"> {progress_text}\n\n"
            f"> **Покупатель:** {buyer_roles_names}\n"
            f"> **Отзывов:** {count}"
        ),
        color=role_color
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="💎 Diamond Coins", value=f"{balance} DC", inline=True)
    embed.add_field(name="👑 Высшая роль", value=top_role_mention, inline=True)
    embed.add_field(name="🛒 Купленные товары (ожидают)", value=purchases_text, inline=False)
    embed.add_field(name="📜 История (последние 5)", value=f">>> {history_text}", inline=False)
    embed.add_field(
        name="📑 О пользователе",
        value=f">>> ID: {user.id}\nНа сервере с {joined_str}",
        inline=False
    )
    await inter.response.send_message(embed=embed, ephemeral=True)
    await log_discord(
        title="👤 Просмотр профиля",
        description=f"> **Кто:** {inter.author.mention}\n> **Профиль:** {user.mention}",
        color=0x00aaff
    )

async def recalc_reviews(inter):
    from core.bot import bot
    channel_id = CONFIG["REVIEW_COUNT_CHANNEL"]
    channel = bot.get_channel(channel_id)
    if not channel:
        channel = await bot.fetch_channel(channel_id)
    if not channel or not isinstance(channel, disnake.TextChannel):
        await inter.edit_original_response(content="❌ Канал отзывов не найден.")
        return
    counts = {}
    try:
        async for message in channel.history(limit=None):
            if message.author.bot:
                continue
            uid = str(message.author.id)
            counts[uid] = counts.get(uid, 0) + 1
    except Exception as e:
        logger.exception("Ошибка чтения истории: %s", e)
        await inter.edit_original_response(content=f"❌ Ошибка: {e}")
        return
    if not counts:
        await inter.edit_original_response(content="ℹ️ Нет сообщений.")
        return
    save_json(FILES["review_counts"], counts)
    guild = inter.guild or bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        await inter.edit_original_response(content="❌ Сервер не найден.")
        return
    updated = 0
    for uid_str, count in counts.items():
        uid = int(uid_str)
        member = guild.get_member(uid)
        if member:
            await update_user_roles(member, count, keep_pka=True)
            updated += 1
    from core.bot import update_review_counter
    await update_review_counter(silent=False)
    await inter.edit_original_response(
        content=f"✅ Пересчёт завершён!\n"
                f"Всего: {len(counts)}\n"
                f"Обновлено: {updated}"
    )
    await log_discord(
        title="📊 Пересчёт отзывов",
        description=f"> **Админ:** {inter.author.mention}\n> **Записей:** `{len(counts)}`\n> **Ролей обновлено:** `{updated}`",
        color=0x00aaff
    )
# ============================================================
# ОТПРАВКА ПАНЕЛИ ТИКЕТОВ (в канал 1462136361711829053)
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
# ОБРАБОТЧИК ИНТЕРАКЦИЙ (кнопки)
# ============================================================
async def handle_interaction(inter: disnake.MessageInteraction):
    if inter.data.get("custom_id") == "menu:buy_ticket":
        await inter.response.send_modal(BuyTicketModal())
# ============================================================
# НАСТРОЙКА МОДУЛЯ (для main.py)
# ============================================================
def setup_commands(bot):
    bot.add_slash_command(panel_dc)
    bot.add_slash_command(admin_panel)
    bot.add_slash_command(promocodes)
    bot.add_slash_command(say)
    bot.add_slash_command(gw_dc)



