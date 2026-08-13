# -*- coding: utf-8 -*-
import os
import sys
import json
import asyncio
import time
import re
import io
import aiohttp
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import disnake
from disnake.ext import commands
from disnake.ui import Modal, TextInput, View, Button, Select
from disnake import PartialEmoji, ui, ButtonStyle, Embed, SelectOption

# ============================================================
# Импорты из core.utils
# ============================================================
from core.utils import (
    CONFIG, FILES, BASE_DIR, DATA_DIR, CATALOG_DIR, ADD_DIR,
    db, cur,
    logger,
    load_json, save_json, now_ts,
    log_discord, log_command,
    has_admin_command_roles, has_review_moderation_roles,
    has_ticket_view_roles, has_ticket_manage_roles,
    clean_embed_for_discohook, parse_emoji,
    update_user_roles,
    get_roles_for_count,
    get_dc_cache, save_dc_cache
)

# ============================================================
# Импорт из core.bot
# ============================================================
from core.bot import update_review_counter, bot

# ============================================================
# Импорты из modules.dc
# ============================================================
from modules.dc import (
    get_user_balance, add_dc, remove_dc,
    add_purchase, get_user_purchases, remove_purchase,
    get_dc_cache, save_dc_cache,
    get_progress_bar,
    load_shop_catalog,
    get_user_dc_data  # <-- добавить
)

# ============================================================
# Импорт для генерации профиля
# ============================================================
# Класс для модерации отзывов
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

        log_chan = bot.get_channel(CONFIG["LOG_CHANNEL_ID"])
        if log_chan:
            await log_chan.send(
                embed=disnake.Embed(
                    title=log_title,
                    description=f"> **Админ:** {inter.author.mention}\n> **Автор отзыва:** <@{self.user_id}>\n> **Ссылка:** [перейти](https://discord.com/channels/{inter.guild_id}/{self.channel_id}/{self.msg_id})",
                    color=log_color,
                    timestamp=datetime.now(timezone.utc)
                )
            )

    @disnake.ui.button(label="✅ Одобрить", style=ButtonStyle.success)
    async def approve(self, button: Button, inter: disnake.MessageInteraction):
        if not has_review_moderation_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав для одобрения.", ephemeral=True)

        await add_dc(self.user_id, 10, "Одобрение отзыва")
        data = get_dc_cache(self.user_id)
        data["last_review"] = now_ts()
        save_dc_cache(self.user_id, data)

        try:
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
            user = bot.get_user(self.user_id)
            if user:
                await user.send("❌ Ваш отзыв был отклонён администратором.")
        except:
            pass

        await self.update_status_and_log(inter, "❌ Отклонено", "❌ Отзыв отклонён", 0xff0000)

# ============================================================
# ТИКЕТЫ
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
            from core.utils import promo_codes
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
        view = TicketButtons()

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

        await ticket_channel.send(
            f"> Добрый день, {inter.author.mention}, ваш тикет создан. Ожидайте ответа от <@&1154757071330365490>\n"
            f"> Помните, по кнопке реквизиты вы можете получить счет и оплатить — не дожидаясь менеджера.",
            embeds=[embeds_list[0], embed_order_info],
            view=view
        )
        await inter.response.send_message(f"✅ Тикет создан: {ticket_channel.mention}", ephemeral=True)

        purchases = await get_user_purchases(inter.author.id, only_unused=True)
        if purchases:
            embed_apply = disnake.Embed(
                title="💡 Уведомление о скидке",
                description="> У вас есть неиспользованные товары за Diamond Coins. Нажмите кнопку, чтобы применить к этому заказу:",
                color=6776679
            )
            embed_apply.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1532256186026426408/pisk.png?ex=6a6c3046&is=6a6adec6&hm=03b0737541d747391eb599ff5e7e8d735456b1f51eda9fa1832c26cf4965eacd&")

            apply_view = View(timeout=300)
            for idx, p in enumerate(purchases):
                label = f"{p['type']} {p['value']}"
                btn = Button(label=label, style=ButtonStyle.gray, custom_id=f"apply_{inter.author.id}_{idx}")
                btn.callback = self.create_apply_callback(inter.author.id, idx, ticket_channel, embed_order_info, inter, label)
                apply_view.add_item(btn)

            await inter.edit_original_message(
                content="✅ Тикет создан! У вас есть неиспользованные товары. Нажмите кнопку в тикете, чтобы применить.",
                view=None
            )
            await ticket_channel.send(embed=embed_apply, view=apply_view)

        log_ch = guild.get_channel(CONFIG["LOG_CHANNEL_ID_PANEL"])
        if log_ch:
            await log_ch.send(embed=disnake.Embed(
                title="📩 Тикет создан",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {ticket_channel.mention}\n> **Товар:** `{item}`\n> **Оплата:** `{pay}`\n> **Промокод:** `{promo_display}`",
                timestamp=datetime.now(timezone.utc),
                color=0x00ff00
            ))

    def create_apply_callback(self, user_id, purchase_index, ticket_channel, order_embed, original_inter, label):
        async def callback(inter: disnake.MessageInteraction):
            if inter.author.id != user_id:
                return await inter.response.send_message("⛔ Это не ваш товар.", ephemeral=True)
            success = await remove_purchase(user_id, purchase_index)
            if not success:
                return await inter.response.send_message("❌ Ошибка применения товара.", ephemeral=True)
            embed_dict = order_embed.to_dict()
            for field in embed_dict.get("fields", []):
                if "промокод" in field.get("name", "").lower():
                    field["value"] = f"```{label}```"
                    break
            async for msg in ticket_channel.history(limit=20):
                if msg.embeds and len(msg.embeds) > 1:
                    if msg.embeds[1].fields and any("Позиция" in f.name for f in msg.embeds[1].fields):
                        new_embeds = [msg.embeds[0], disnake.Embed.from_dict(embed_dict)]
                        await msg.edit(embeds=new_embeds)
                        break
            try:
                async for msg in ticket_channel.history(limit=20):
                    if msg.embeds and msg.embeds[0].title == "💡 Уведомление о скидке":
                        await msg.delete()
                        break
            except Exception as e:
                logger.error(f"Не удалось удалить эмбед уведомления: {e}")

            await inter.response.send_message(f"✅ {label} применена к заказу!", ephemeral=True)
            await log_discord(
                title="🛒 Применён товар за DC",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {label}\n> **Тикет:** {ticket_channel.mention}",
                color=0x00aaff
            )
        return callback

class TicketButtons(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤㅤЗакрыть тикетㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket:close",
        emoji=PartialEmoji(name="image_20260110_001524", id=1459219228870578371)
    )
    async def close(self, button, inter: disnake.MessageInteraction):
        if not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие тикетов.", ephemeral=True)
        confirm = ConfirmCloseView(inter.channel)
        await inter.response.send_message("Подтвердите закрытие", view=confirm, ephemeral=True)
        await log_discord(
            title="🔒 Запрос на закрытие тикета",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
            color=0xffaa00
        )

    @disnake.ui.button(
        label="ㅤㅤㅤㅤРеквизиты ㅤ ㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket:requisites",
        emoji=PartialEmoji(name="image_20260110_001406", id=1459219370495709374),
        row=0
    )
    async def requisites(self, button, inter: disnake.MessageInteraction):
        embeds_data = [
            {
                "type": "rich",
                "title": "Реквизиты к заказу ",
                "description": "\n> Выберите удобный вам способ оплаты → оплатите → подтвердите кнопкой \"Оплата\". После - ожидайте <@796293832751972352>. При наличии промокода - напишите его в лот заказа, его проверят, и назначат скидку.",
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
            color=0x00ff00
        )

    @disnake.ui.button(
        label="ㅤㅤㅤㅤПолитикаㅤㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket:policy",
        emoji=PartialEmoji(name="d1d1", id=1530779605919596604),
        row=1
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
                title="📜 Просмотр политики",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
                color=0x00ff00
            )
        except Exception as e:
            logger.exception("Ошибка при отправке policy: %s", e)
            await inter.response.send_message("❌ Ошибка при загрузке правил.", ephemeral=True)

    @disnake.ui.button(
        label="ㅤㅤㅤ  Оплатитьㅤㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket:pay",
        emoji=PartialEmoji(name="corr", id=1530784600777953300),
        row=1
    )
    async def pay(self, button, inter: disnake.MessageInteraction):
        if not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на подтверждение оплаты.", ephemeral=True)

        msg = inter.message
        if not msg.embeds or len(msg.embeds) < 2:
            return await inter.response.send_message("❌ Второй embed не найден", ephemeral=True)

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
        new_view = TicketButtonsPaid()

        await msg.edit(
            embeds=[msg.embeds[0], disnake.Embed.from_dict(ed)],
            view=new_view
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

        await log_discord(
            title="💰 Заказ оплачен",
            description=(
                f"> **Канал:** {inter.channel.mention}\n"
                f"> **Товар:** `{item_name}`\n"
                f"> **Оплата:** `{payment_method}`\n"
                f"> **Промокод:** `{promo_value}`\n"
                f"> **Подтвердил:** {inter.author.mention}"
            ),
            color=0x2ecc71
        )

class TicketButtonsPaid(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤㅤЗакрыть тикетㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket_paid:close",
        emoji=PartialEmoji(name="image_20260110_001524", id=1459219228870578371)
    )
    async def close(self, button, inter: disnake.MessageInteraction):
        if not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие тикетов.", ephemeral=True)
        confirm = ConfirmCloseView(inter.channel)
        await inter.response.send_message("Подтвердите закрытие", view=confirm, ephemeral=True)
        await log_discord(
            title="🔒 Запрос на закрытие тикета (оплаченный)",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
            color=0xffaa00
        )

    @disnake.ui.button(
        label="ㅤㅤㅤㅤРеквизиты ㅤ ㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket_paid:requisites",
        emoji=PartialEmoji(name="image_20260110_001406", id=1459219370495709374),
        row=0
    )
    async def requisites(self, button, inter: disnake.MessageInteraction):
        embeds_data = [
            {
                "type": "rich",
                "title": "Реквизиты к заказу ",
                "description": "\n> Выберите удобный вам способ оплаты → оплатите → подтвердите кнопкой \"Оплата\". После - ожидайте <@796293832751972352>. При наличии промокода - напишите его в лот заказа, его проверят, и назначат скидку.",
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
            title="📄 Просмотр реквизитов (оплачено)",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
            color=0x00ff00
        )

    @disnake.ui.button(
        label="ㅤㅤㅤㅤПолитикаㅤㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket_paid:policy",
        emoji=PartialEmoji(name="d1d1", id=1530779605919596604),
        row=1
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
                title="📜 Просмотр политики (оплачено)",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {inter.channel.mention}",
                color=0x00ff00
            )
        except Exception as e:
            logger.exception("Ошибка при отправке policy: %s", e)
            await inter.response.send_message("❌ Ошибка при загрузке правил.", ephemeral=True)

    @disnake.ui.button(
        label="ㅤㅤㅤ  Оплатитьㅤㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="ticket_paid:paid_done",
        emoji=PartialEmoji(name="corr", id=1530784600777953300),
        row=1,
        disabled=True
    )
    async def paid_done(self, button, inter: disnake.MessageInteraction):
        await inter.response.send_message("Заказ уже оплачен.", ephemeral=True)

class ConfirmCloseView(View):
    def __init__(self, channel):
        super().__init__(timeout=60)
        self.channel = channel

    @disnake.ui.button(
        label="Подтвердить закрытие",
        style=disnake.ButtonStyle.gray,
        custom_id="confirm:close",
        emoji=PartialEmoji(name="image_20260110_001524", id=1459219228870578371)
    )
    async def confirm(self, button, inter: disnake.MessageInteraction):
        if not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие тикетов.", ephemeral=True)
        await inter.response.send_message("Тикет удаляется...", ephemeral=True)
        await asyncio.sleep(2)
        await self.channel.delete()
        await log_discord(
            title="🗑️ Тикет закрыт",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {self.channel.name}",
            color=0xff6600
        )

class TicketPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤㅤКупитьㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:buy",
        emoji=PartialEmoji(name="image_20260110_0014062", id=1459219275934863402)
    )
    async def buy(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(BuyTicketModal())
        await log_discord(
            title="🛒 Нажата кнопка Купить",
            description=f"> **Пользователь:** {inter.author.mention}",
            color=0x00ff00
        )

    @disnake.ui.button(
        label="ㅤПромокодыㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:promo",
        emoji=PartialEmoji(name="image_20260110_001407", id=1459219251775799511)
    )
    async def promo(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        text = "🎟️ Промокоды публикуются в <#1462070136856117258>, следи и забирай свою скидку!"
        await inter.response.send_message(text, ephemeral=True)
        await log_discord(
            title="🎟️ Просмотр промокодов",
            description=f"> **Пользователь:** {inter.author.mention}",
            color=0x00ff00
        )

    @disnake.ui.button(
        label="ㅤОплатаㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:payinfo",
        emoji=PartialEmoji(name="image_20260110_001406", id=1459219370495709374)
    )
    async def payinfo(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_message("💳 Доступна оплата валютами: RUB | KZT | UAH | USD | USDT | TON", ephemeral=True)
        await log_discord(
            title="💳 Просмотр информации об оплате",
            description=f"> **Пользователь:** {inter.author.mention}",
            color=0x00ff00
        )

# ============================================================
# МЕНЮ (catalog)
# ============================================================
MENU_CHANNEL_ID = 1462140026073776280
MENU_OPTIONS = [
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

class MenuSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label=item["label"],
                description=item["description"],
                emoji=item["emoji"],
                value=item["json_path"]
            ) for item in MENU_OPTIONS
        ]
        super().__init__(
            placeholder="Выберите категорию...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="menu_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        json_path = self.values[0]
        try:
            if not os.path.exists(json_path):
                return await inter.response.send_message("Файл с embed не найден.", ephemeral=True)
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            view = disnake.ui.View(timeout=None)
            view.add_item(disnake.ui.Button(
                label="Перейти в канал покупки",
                style=disnake.ButtonStyle.link,
                url="https://discord.com/channels/1127428607606796288/1462136361711829053"
            ))
            await inter.response.send_message(embeds=embeds, view=view, ephemeral=True)
            await log_discord(
                title="📂 Выбор категории меню",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Категория:** `{json_path}`",
                color=0x00aaff
            )
        except Exception as e:
            logger.exception("MenuSelect callback error: %s", e)

class MenuView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MenuSelect())

async def send_menu_panel():
    await bot.wait_until_ready()
    channel = bot.get_channel(MENU_CHANNEL_ID)
    if not channel:
        channel = await bot.fetch_channel(MENU_CHANNEL_ID)
    if not channel:
        logger.warning("Menu panel channel not found")
        return
    existing_msg = None
    async for m in channel.history(limit=50):
        if m.author == bot.user and m.components:
            existing_msg = m
            break
    if existing_msg:
        return
    embed_path = os.path.join(CATALOG_DIR, "menu_embed.json")
    embed = disnake.Embed(title="Меню выбора", description="Выберите категорию", color=0x0499D2)
    if os.path.exists(embed_path):
        with open(embed_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            embed = disnake.Embed.from_dict(data["embeds"][0])
    msg = await channel.send(embed=embed, view=MenuView())
    bot.add_view(MenuView())
    await log_discord(
        title="📋 Меню отправлено",
        description="> Панель меню была отправлена в канал.",
        color=0x00ff00
    )

# ============================================================
# АДМИН-ПАНЕЛЬ DC
# ============================================================
class DCPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="💳 Начислить DC", style=ButtonStyle.gray, row=0)
    async def give_dc_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await inter.response.send_modal(GiveDcModal())

    @disnake.ui.button(label="💸 Списать DC", style=ButtonStyle.gray, row=0)
    async def take_dc_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await inter.response.send_modal(TakeDcModal())

    @disnake.ui.button(label="🔄 Вернуть DC", style=ButtonStyle.gray, row=0)
    async def refund_dc_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await inter.response.send_modal(RefundDcModal())

    @disnake.ui.button(label="📊 Пересчитать DC", style=ButtonStyle.gray, row=1)
    async def recalc_dc_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        counts = load_json(FILES["review_counts"], {})
        if not counts:
            return await inter.edit_original_message(content="❌ Нет данных об отзывах.")
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild:
            return await inter.edit_original_message(content="❌ Сервер не найден.")
        ignore_list = CONFIG["DC_RECALC_IGNORE"]
        total = 0
        for user_id_str, count in counts.items():
            uid = int(user_id_str)
            if uid in ignore_list:
                continue
            member = guild.get_member(uid)
            if not member:
                continue
            dc_amount = count * 10
            await add_dc(uid, dc_amount, f"Пересчёт за {count} отзывов")
            total += 1
            await update_user_roles(member, count, keep_pka=True)
        await inter.edit_original_message(content=f"✅ Пересчёт завершён. Начислено для {total} пользователей.")
        await log_discord(
            title="🔄 Пересчёт DC",
            description=f"> **Админ:** {inter.author.mention}\n> **Обработано:** `{total}`",
            color=0x00aaff
        )

    @disnake.ui.button(label="📊 Статистика DC", style=ButtonStyle.gray, row=1)
    async def dc_stats_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        data = get_dc_cache_all()
        total_users = len(data)
        total_balance = sum(user["balance"] for user in data.values())
        avg_balance = total_balance / total_users if total_users else 0
        top_users = sorted(data.items(), key=lambda x: x[1]["balance"], reverse=True)[:5]
        top_text = ""
        for idx, (uid, ud) in enumerate(top_users, 1):
            top_text += f"`#{idx}` <@{uid}> — {ud['balance']} DC\n"
        if not top_text:
            top_text = "Нет данных."

        embed = disnake.Embed(
            title="📊 Статистика DC",
            description=f"> **Всего пользователей:** `{total_users}`\n> **Общий баланс:** `{total_balance} DC`\n> **Средний баланс:** `{avg_balance:.2f} DC`\n\n**🏆 Топ-5 по балансу:**\n{top_text}",
            color=0x00aaff
        )
        await inter.send(embed=embed, ephemeral=True)

    @disnake.ui.button(label="🗑️ Управление покупками", style=ButtonStyle.gray, row=2)
    async def manage_purchases_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await inter.response.send_modal(ManagePurchasesModal())

    @disnake.ui.button(label="🧹 Удалить все DC", style=ButtonStyle.danger, row=1)
    async def reset_dc_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await inter.response.send_modal(ResetDcModal())

    @disnake.ui.button(label="🔄 Обновить акцию", style=ButtonStyle.gray, row=2)
    async def refresh_flash_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        from modules.actions import refresh_actions_panel
        await refresh_actions_panel()
        await inter.edit_original_message(content="✅ Меню Actions обновлено с новой акцией!")
        await log_discord(
            title="🔄 Акция обновлена",
            description=f"> **Админ:** {inter.author.mention} обновил акцию.",
            color=0x00aaff
        )

# ============================================================
# МОДАЛЬНЫЕ ОКНА ДЛЯ ПАНЕЛИ
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
        super().__init__(title="Списать DC", components=components)

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
            await inter.response.send_message(f"✅ Списано {amount} DC у <@{user_id}>.", ephemeral=True)
        else:
            await inter.response.send_message(f"❌ Недостаточно DC у <@{user_id}>.", ephemeral=True)

class RefundDcModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="ID пользователя или @упоминание", custom_id="user", placeholder="Введите ID или @username", min_length=2, max_length=50),
            TextInput(label="Количество DC", custom_id="amount", placeholder="Число", min_length=1, max_length=10),
            TextInput(label="Причина (необязательно)", custom_id="reason", required=False, placeholder="Причина возврата", max_length=200)
        ]
        super().__init__(title="Вернуть DC", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        user_input = inter.text_values["user"].strip()
        try:
            amount = int(inter.text_values["amount"].strip())
            if amount <= 0:
                raise ValueError
        except:
            return await inter.response.send_message("❌ Введите корректное количество >0.", ephemeral=True)

        reason = inter.text_values.get("reason", "").strip() or "Возврат через панель"
        user_id = None
        if user_input.isdigit():
            user_id = int(user_input)
        else:
            match = re.search(r'<@!?(\d+)>', user_input)
            if match:
                user_id = int(match.group(1))
        if not user_id:
            return await inter.response.send_message("❌ Не удалось определить пользователя.", ephemeral=True)

        await add_dc(user_id, amount, reason)
        await inter.response.send_message(f"✅ Возвращено {amount} DC пользователю <@{user_id}>.", ephemeral=True)

class ResetDcModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Введите 'ПОДТВЕРДИТЬ' для сброса", custom_id="confirm", placeholder="ПОДТВЕРДИТЬ", min_length=10, max_length=20)
        ]
        super().__init__(title="Удалить все DC", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        confirm_text = inter.text_values["confirm"].strip()
        if confirm_text != "ПОДТВЕРДИТЬ":
            return await inter.response.send_message("❌ Неверное подтверждение. Введите 'ПОДТВЕРДИТЬ'.", ephemeral=True)

        data = load_dc_data()
        for uid in data:
            data[uid]["balance"] = 0
        save_dc_data(data)
        await log_discord(
            title="💎 Все балансы обнулены",
            description=f"> **Действие:** все Diamond Coins удалены.",
            color=0xff0000
        )
        await inter.response.send_message("✅ Все балансы DC удалены (установлены в 0).", ephemeral=True)

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
# ПАНЕЛЬ DC (отправка в канал)
# ============================================================
async def send_dc_panel():
    await bot.wait_until_ready()
    channel = bot.get_channel(CONFIG["DC_PANEL_CHANNEL"])
    if not channel:
        channel = await bot.fetch_channel(CONFIG["DC_PANEL_CHANNEL"])
    if not channel:
        logger.warning("DC panel channel not found")
        return
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.edit(view=DCPanelView())
            except:
                pass
            return
    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1531735616633704769/image.png?ex=6a6a4b75&is=6a68f9f5&hm=11d9df72c3abde0269710aa0384db7e1b5d330e6828786322798775f4e1e7414&")

    embed2 = disnake.Embed(
        title="Панель управления Diamond Coins",
        description="> Используйте кнопки ниже для управления балансами и покупками пользователей.\n\n",
        color=6776679
    )
    embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1530795801268453447/pisk.png?ex=6a69832f&is=6a6831af&hm=106c0b5c55c83b94fce2e11af7a4c65ec26d550b6da30575f1fef0981f7dc914&")
    embed2.add_field(name="> Начислить DC", value="**Выдать DC пользователю.**", inline=True)
    embed2.add_field(name="> Списать DC", value="**Списать DC.**", inline=True)
    embed2.add_field(name="> Вернуть DC", value="**Возврат при отмене заказа.**", inline=True)
    embed2.add_field(name="> Пересчитать DC", value="**Начислить 10 DC за каждый существующий отзыв.**", inline=True)
    embed2.add_field(name="> Статистика DC", value="**Показать общую статистику и топ-5.**", inline=True)
    embed2.add_field(name="> Управление покупками", value="**Удалить неиспользованные покупки.**", inline=True)
    embed2.add_field(name="> Удалить все DC", value="**Удаление коинов в корень (установить 0).**", inline=True)

    await channel.send(embeds=[embed1, embed2], view=DCPanelView())

# ============================================================
# ОБРАБОТЧИК ИНТЕРАКЦИЙ (кнопки)
# ============================================================
async def handle_interaction(inter: disnake.MessageInteraction):
    if inter.data.get("custom_id") == "menu:buy_ticket":
        await inter.response.send_modal(BuyTicketModal())
    elif inter.data.get("custom_id") == "stop_mass_send":
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав для остановки.", ephemeral=True)
        if MassSender.stop_flag:
            return await inter.response.send_message("⛔ Рассылка уже остановлена.", ephemeral=True)
        MassSender.stop_flag = True
        await inter.response.send_message("⏹️ Рассылка будет остановлена после текущей пачки.", ephemeral=True)
        await log_discord(
            title="⏹️ Запрос на остановку",
            description=f"> **Админ:** {inter.author.mention}",
            color=0xff6600
        )

# ============================================================
# РАССЫЛКА (MassSender)
# ============================================================
class MassSender:
    active_task = None
    stop_flag = False

@bot.slash_command(
    name="рассылка",
    description="Массовая рассылка в ЛС (админ)",
    default_member_permissions=disnake.Permissions(administrator=True)
)
async def рассылка(
    ctx,
    embed_json: Optional[str] = commands.Param(default=None, description="JSON с embed"),
    файл_embed: Optional[disnake.Attachment] = commands.Param(default=None, description="JSON-файл"),
    только_с_ролью: Optional[disnake.Role] = commands.Param(default=None, description="Роль для фильтра")
):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)
    await ctx.response.defer(ephemeral=True)

    if not embed_json and not файл_embed:
        return await ctx.edit_original_response("❌ Укажите JSON или файл.")
    try:
        if файл_embed:
            raw = await файл_embed.read()
            data = json.loads(raw.decode("utf-8"))
        else:
            data = json.loads(embed_json)
        if "embeds" not in data:
            return await ctx.edit_original_response("❌ Нет поля 'embeds'.")
        embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data["embeds"]]
        content = data.get("content", " ")
    except Exception as e:
        return await ctx.edit_original_response(f"❌ Ошибка парсинга: {e}")

    guild = ctx.guild or bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        return await ctx.edit_original_response("❌ Сервер не найден.")
    members = [m for m in guild.members if not m.bot and m != ctx.author]
    if только_с_ролью:
        members = [m for m in members if только_с_ролью in m.roles]
    if not members:
        return await ctx.edit_original_response("❌ Нет получателей.")
    if MassSender.active_task and not MassSender.active_task.done():
        return await ctx.edit_original_response("⚠️ Уже идёт рассылка.")

    progress_embed = disnake.Embed(
        title="📨 Массовая рассылка",
        description=(
            f"**Получателей:** {len(members)}\n"
            f"**Успешно:** 0\n"
            f"**Ошибок:** 0\n"
            f"**Осталось:** {len(members)}"
        ),
        color=0x00aaff
    )
    stop_view = View()
    stop_view.add_item(Button(label="⏹️ Остановить", style=ButtonStyle.danger, custom_id="stop_mass_send"))
    progress_msg = await ctx.edit_original_response(embed=progress_embed, view=stop_view)

    MassSender.stop_flag = False
    task = bot.loop.create_task(send_mass_messages(members, content, embeds, progress_msg, progress_embed, ctx))
    MassSender.active_task = task

async def send_mass_messages(members, content, embeds, progress_msg, progress_embed, ctx):
    total = len(members)
    sent = 0
    errors = 0
    batch_size = 5
    for i in range(0, total, batch_size):
        if MassSender.stop_flag:
            progress_embed.title = "⏹️ Остановлена"
            progress_embed.description = (
                f"**Получателей:** {total}\n"
                f"**Успешно:** {sent}\n"
                f"**Ошибок:** {errors}\n"
                f"**Осталось:** {total - sent}"
            )
            progress_embed.color = 0xff0000
            await progress_msg.edit(embed=progress_embed, view=None)
            await log_discord("⛔ Рассылка остановлена", f"Отправлено: {sent}, ошибок: {errors}", color=0xff0000)
            return
        batch = members[i:i+batch_size]
        tasks = [send_dm(m, content, embeds) for m in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                errors += 1
            else:
                sent += 1
        progress_embed.description = (
            f"**Получателей:** {total}\n"
            f"**Успешно:** {sent}\n"
            f"**Ошибок:** {errors}\n"
            f"**Осталось:** {total - sent}"
        )
        await progress_msg.edit(embed=progress_embed)
        await asyncio.sleep(0.5)
    progress_embed.title = "✅ Завершена"
    progress_embed.description = (
        f"**Получателей:** {total}\n"
        f"**Успешно:** {sent}\n"
        f"**Ошибок:** {errors}\n"
        f"**Осталось:** 0"
    )
    progress_embed.color = 0x00ff00
    await progress_msg.edit(embed=progress_embed, view=None)
    await log_discord("✅ Рассылка завершена", f"Отправлено: {sent}, ошибок: {errors}", color=0x00ff00)

async def send_dm(member, content, embeds):
    try:
        await member.send(content=content, embeds=embeds)
    except Exception as e:
        raise e

# ============================================================
# КОМАНДА /buy (с выдачей ролей)
# ============================================================
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
            return await inter.edit_original_response(content=f"❌ Недостаточно DC. Нужно: {price}, у вас: {balance}")

        # Определяем тип и значение для записи покупки
        if category == "discounts":
            item_type = "Скидка"
            item_value = item["name"].replace("скидка", "").strip()
        elif category == "design":
            item_type = "Дизайн"
            item_value = item["name"]
        elif category == "ads":
            item_type = "Реклама"
            item_value = item["name"]
        elif category == "roles":
            item_type = "Роль"
            item_value = item["name"]
            # Выдаём роль, если есть role_id
            role_id = item.get("role_id")
            if role_id:
                guild = inter.guild
                role = guild.get_role(role_id)
                if role:
                    try:
                        await inter.author.add_roles(role)
                        success = await remove_dc(user_id, price, f"Покупка роли: {item['name']}")
                        if not success:
                            return await inter.edit_original_response(content="❌ Ошибка списания DC.")
                        await add_purchase(user_id, item_type, item_value)
                        await inter.edit_original_response(
                            content=f"✅ Вы купили роль **{item['name']}** за **{price} DC**! Роль выдана. Не забудьте оставить отзыв в <#1462074763437543435>.",
                            ephemeral=True
                        )
                        await log_discord(
                            title="🛒 Покупка роли в магазине DC",
                            description=f"> **Пользователь:** {inter.author.mention}\n> **Роль:** {item['name']}\n> **Цена:** {price} DC\n> **Категория:** {catalog[category]['label']}",
                            color=0x00aaff
                        )
                        return
                    except Exception as e:
                        await inter.edit_original_response(content=f"❌ Не удалось выдать роль: {e}")
                        return
                else:
                    await inter.edit_original_response(content="❌ Роль не найдена на сервере.")
                    return
            else:
                # Если role_id нет, просто сохраняем покупку
                success = await remove_dc(user_id, price, f"Покупка: {item['name']}")
                if not success:
                    return await inter.edit_original_response(content="❌ Ошибка списания.")
                await add_purchase(user_id, item_type, item_value)
                await inter.edit_original_response(
                    content=f"✅ Вы купили **{item['name']}** за **{price} DC**. Проверьте свои покупки в `/profile`.",
                    ephemeral=True
                )
                await log_discord(
                    title="🛒 Покупка в магазине DC",
                    description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {item['name']}\n> **Цена:** {price} DC\n> **Категория:** {catalog[category]['label']}",
                    color=0x00aaff
                )
                return
        else:
            item_type = "Другое"
            item_value = item["name"]
            success = await remove_dc(user_id, price, f"Покупка: {item['name']}")
            if not success:
                return await inter.edit_original_response(content="❌ Ошибка списания.")
            await add_purchase(user_id, item_type, item_value)
            await inter.edit_original_response(
                content=f"✅ Вы купили **{item['name']}** за **{price} DC**. Проверьте свои покупки в `/profile`.",
                ephemeral=True
            )
            await log_discord(
                title="🛒 Покупка в магазине DC",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {item['name']}\n> **Цена:** {price} DC\n> **Категория:** {catalog[category]['label']}",
                color=0x00aaff
            )
            return

    async def back_callback(self, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        await inter.edit_original_response(content="Выберите категорию:", view=BuySelectView())

@bot.slash_command(name="buy", description="Купить товар за Diamond Coins")
async def buy(inter: disnake.ApplicationCommandInteraction):
    await inter.response.send_message("Выберите категорию товара:", ephemeral=True, view=BuySelectView())

@bot.slash_command(name="profile", description="Показать профиль пользователя")
async def profile(inter: disnake.ApplicationCommandInteraction, user: disnake.Member = None):
    user = user or inter.author
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

    # ===== ПРОГРЕСС-БАР (текстовый) =====
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

    # Цвет embed в зависимости от роли
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

    await inter.send(embed=embed)
    await log_discord(
        title="👤 Просмотр профиля",
        description=f"> **Кто:** {inter.author.mention}\n> **Профиль:** {user.mention}",
        color=0x00aaff
    )
# ============================================================
# Административные команды (без изменений)
# ============================================================
@bot.slash_command(name="cleaning", description="Удалить указанное количество сообщений (админ)", default_member_permissions=disnake.Permissions(administrator=True))
async def cleaning(ctx, количество: int):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)
    if количество < 1 or количество > 100:
        return await ctx.send("❌ Укажите число от 1 до 100.", ephemeral=True)
    try:
        deleted = await ctx.channel.purge(limit=количество)
        await ctx.send(f"✅ Удалено {len(deleted)} сообщений.", ephemeral=True)
        await log_discord(
            title="🗑️ Очистка канала",
            description=f"> **Админ:** {ctx.author.mention}\n> **Канал:** {ctx.channel.mention}\n> **Удалено:** `{len(deleted)}`",
            color=0xff6600
        )
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {e}", ephemeral=True)

@bot.slash_command(name="set_rate", description="Установить курс (админ)", default_member_permissions=disnake.Permissions(administrator=True))
async def set_rate(ctx, имя: str, коэффициент: float):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)
    from core.utils import rates, save_json, FILES
    имя = имя.upper()
    rates[имя] = float(коэффициент)
    save_json(FILES["rates"], rates)
    await ctx.send(f"✅ Установлено: {имя} → {коэффициент}", ephemeral=True)
    await log_discord(
        title="📊 Изменён курс",
        description=f"> **Админ:** {ctx.author.mention}\n> **Валюта:** `{имя}`\n> **Курс:** `{коэффициент}`",
        color=0x00ff00
    )

@bot.slash_command(name="get_rates", description="Показать курсы (админ)", default_member_permissions=disnake.Permissions(administrator=True))
async def get_rates(ctx):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)
    from core.utils import rates
    embed = disnake.Embed(title="📊 Текущие курсы", description=json.dumps(rates, ensure_ascii=False, indent=2))
    await ctx.send(embed=embed, ephemeral=True)

@bot.slash_command(name="say", description="Отправить сообщение от бота (админ)", default_member_permissions=disnake.Permissions(administrator=True))
async def say(ctx, канал: disnake.TextChannel, тип_сообщения: str = commands.Param(choices=["text", "embed"]), текст: Optional[str] = None, файл: Optional[disnake.Attachment] = None):
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

@bot.slash_command(name="get_json", description="Получить JSON сообщения (админ)", default_member_permissions=disnake.Permissions(administrator=True))
async def get_json(ctx, message_link: str):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)
    try:
        parts = message_link.strip("/").split("/")
        guild_id, channel_id, message_id = map(int, parts[-3:])
    except Exception:
        return await ctx.send("Неверная ссылка.", ephemeral=True)
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        msg = await channel.fetch_message(message_id)
    except Exception as e:
        return await ctx.send(f"Ошибка: {e}", ephemeral=True)
    payload = {"content": msg.content or " ", "embeds": [clean_embed_for_discohook(e.to_dict()) for e in msg.embeds]}
    buf = io.StringIO(json.dumps(payload, ensure_ascii=False, indent=2))
    await ctx.response.send_message(file=disnake.File(fp=buf, filename="message.json"), ephemeral=True)
    await log_discord(
        title="📥 Выгрузка JSON",
        description=f"> **Админ:** {ctx.author.mention}\n> **Канал:** {channel.mention}",
        color=0x00ff00
    )

@bot.slash_command(name="promo_add", description="Добавить промокод (админ)", default_member_permissions=disnake.Permissions(administrator=True))
async def promo_add(ctx, code: str, value: str):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)
    from core.utils import promo_codes, save_json, FILES
    code = code.upper()
    promo_codes[code] = value
    save_json(FILES["promo"], promo_codes)
    try:
        lines = [f"{k} - {v}" for k, v in promo_codes.items()]
        with open(FILES["promo_txt"], "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        logger.exception("write_promo_txt error: %s", e)
    await ctx.send(f"✅ Добавлен `{code}` → {value}", ephemeral=True)
    await log_discord(
        title="➕ Промокод добавлен",
        description=f"> **Админ:** {ctx.author.mention}\n> **Код:** `{code}`\n> **Скидка:** `{value}`",
        color=0x00ff00
    )

@bot.slash_command(name="promo_remove", description="Удалить промокод (админ)", default_member_permissions=disnake.Permissions(administrator=True))
async def promo_remove(ctx, code: str):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)
    from core.utils import promo_codes, save_json, FILES
    code = code.upper()
    if code in promo_codes:
        promo_codes.pop(code)
        save_json(FILES["promo"], promo_codes)
        try:
            lines = [f"{k} - {v}" for k, v in promo_codes.items()]
            with open(FILES["promo_txt"], "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception as e:
            logger.exception("write_promo_txt error: %s", e)
        await ctx.send(f"✅ Удалён `{code}`", ephemeral=True)
        await log_discord(
            title="➖ Промокод удалён",
            description=f"> **Админ:** {ctx.author.mention}\n> **Код:** `{code}`",
            color=0xff6600
        )
    else:
        await ctx.send("❌ Нет такого промокода.", ephemeral=True)

@bot.slash_command(name="promo_list", description="Список промокодов (админ)", default_member_permissions=disnake.Permissions(administrator=True))
async def promo_list(ctx):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)
    from core.utils import promo_codes
    if not promo_codes:
        return await ctx.send("Промокодов нет.", ephemeral=True)
    text = "\n".join([f"{k} → {v}" for k, v in promo_codes.items()])
    await ctx.send(f"```\n{text}\n```", ephemeral=True)

@bot.slash_command(name="расчет", description="Рассчитать скидку")
async def расчет(ctx, цена: float, скидка: float):
    await ctx.response.defer(ephemeral=True)
    try:
        if скидка < 0 or скидка > 100:
            return await ctx.edit_original_response(content="❌ Скидка от 0 до 100%.")
        итог = цена - (цена * (скидка / 100))
        экономия = цена - итог
        embed = disnake.Embed(title="💰 Расчёт скидки", color=0x2ecc71)
        embed.add_field(name="Исходная цена", value=f"`{цена:.2f} ₽`", inline=True)
        embed.add_field(name="Скидка", value=f"`{скидка}%`", inline=True)
        embed.add_field(name="Экономия", value=f"`{экономия:.2f} ₽`", inline=True)
        embed.add_field(name="✅ Итого", value=f"**`{итог:.2f} ₽`**", inline=False)
        await ctx.edit_original_response(embed=embed)
        await log_discord(
            title="🧮 Расчёт скидки",
            description=f"> **Пользователь:** {ctx.author.mention}\n> **Цена:** `{цена}`\n> **Скидка:** `{скидка}%`\n> **Итог:** `{итог:.2f}`",
            color=0x00ff00
        )
    except Exception as e:
        await ctx.edit_original_response(content=f"Ошибка: {e}")

@bot.slash_command(name="обновить_баннер", description="Обновить баннер (админ)", default_member_permissions=disnake.Permissions(administrator=True))
async def обновить_баннер(ctx):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)
    await ctx.response.defer(ephemeral=True)
    await update_review_counter(silent=False)
    await ctx.edit_original_response(content="✅ Баннер обновлён!")

@bot.slash_command(name="пересчитать_отзывы", description="Пересчитать отзывы и роли (админ)", default_member_permissions=disnake.Permissions(administrator=True))
async def пересчитать_отзывы(ctx: disnake.ApplicationCommandInteraction):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)
    await ctx.response.defer(ephemeral=True)
    channel_id = CONFIG["REVIEW_COUNT_CHANNEL"]
    channel = bot.get_channel(channel_id)
    if not channel:
        channel = await bot.fetch_channel(channel_id)
    if not channel or not isinstance(channel, disnake.TextChannel):
        return await ctx.edit_original_response(content="❌ Канал не найден.")
    counts = {}
    try:
        async for message in channel.history(limit=None):
            if message.author.bot:
                continue
            uid = str(message.author.id)
            counts[uid] = counts.get(uid, 0) + 1
    except Exception as e:
        logger.exception("Ошибка чтения истории: %s", e)
        return await ctx.edit_original_response(content=f"❌ Ошибка: {e}")
    if not counts:
        return await ctx.edit_original_response(content="ℹ️ Нет сообщений.")
    save_json(FILES["review_counts"], counts)
    guild = ctx.guild or bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild:
        return await ctx.edit_original_response(content="❌ Сервер не найден.")
    updated = 0
    for uid_str, count in counts.items():
        uid = int(uid_str)
        member = guild.get_member(uid)
        if member:
            await update_user_roles(member, count, keep_pka=True)
            updated += 1
    await update_review_counter(silent=False)
    await ctx.edit_original_response(
        content=f"✅ Пересчёт завершён!\n"
                f"Всего: {len(counts)}\n"
                f"Обновлено: {updated}"
    )
    await log_discord(
        title="📊 Пересчёт отзывов",
        description=f"> **Админ:** {ctx.author.mention}\n> **Записей:** `{len(counts)}`\n> **Ролей обновлено:** `{updated}`",
        color=0x00aaff
    )

@bot.slash_command(name="export_dc", description="Экспорт всех данных DC (только для владельца)")
async def export_dc(inter: disnake.ApplicationCommandInteraction):
    if inter.author.id != 796293832751972352:
        return await inter.send("⛔ Эта команда доступна только владельцу.", ephemeral=True)
    data = get_dc_cache_all()
    if not data:
        return await inter.send("❌ Нет данных для экспорта.", ephemeral=True)
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    file = disnake.File(io.StringIO(json_str), filename="dc_data_export.json")
    await inter.send("📁 Вот актуальный файл DC данных:", file=file, ephemeral=True)
    await log_discord(
        title="📤 Экспорт DC данных",
        description=f"> **Владелец:** {inter.author.mention} выполнил экспорт.",
        color=0x00aaff
    )

# ============================================================
# Обеспечение панели (ensure_panel)
# ============================================================
async def ensure_panel():
    await bot.wait_until_ready()
    chan = bot.get_channel(CONFIG["PANEL_CHANNEL_ID"])
    if not chan:
        chan = await bot.fetch_channel(CONFIG["PANEL_CHANNEL_ID"])
    if not chan or not isinstance(chan, disnake.TextChannel):
        logger.warning("Panel channel not found")
        return
    while not bot.is_closed():
        try:
            panel_msg = None
            async for m in chan.history(limit=50):
                if m.author == bot.user and m.components:
                    panel_msg = m
                    break
            if not panel_msg:
                embed = disnake.Embed(color=disnake.Color(0x676767))
                embed.set_image(url=CONFIG["EMBED_IMAGE_URL"])
                sent_msg = await chan.send(embed=embed, view=TicketPanelView())
                bot.add_view(TicketPanelView(), message_id=sent_msg.id)
                await log_discord(
                    title="🖼️ Панель отправлена",
                    description=f"> Сообщение `{sent_msg.id}` отправлено заново",
                    color=0x00ff00
                )
                logger.info("Panel message sent %s", sent_msg.id)
        except Exception as e:
            logger.exception("ensure_panel error: %s", e)
        await asyncio.sleep(7200)

# ============================================================
# Настройка модуля
# ============================================================
def setup_commands(bot):
    pass
