# -*- coding: utf-8 -*-
import os
import sys
import json
import asyncio
import time
import re
import io
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
    get_dc_cache, save_dc_cache,
    get_promo_codes, add_promo_code, remove_promo_code, clear_promo_codes
)

# ============================================================
# Импорт из core.bot
# ============================================================
from core.bot import update_review_counter, bot, voice_track
from modules.dc import (
    get_user_balance, add_dc, remove_dc,
    add_purchase, get_user_purchases, remove_purchase,
    get_dc_cache, save_dc_cache,
    get_progress_bar,
    load_shop_catalog,
    sync_dc_to_json, get_dc_cache_all
)

# ============================================================
# Загружаем промокоды в память для быстрого доступа (используется в тикетах)
# ============================================================
promo_codes = get_promo_codes()

def reload_promo_cache():
    global promo_codes
    promo_codes = get_promo_codes()

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
# ТИКЕТЫ (без изменений)
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
# МЕНЮ (catalog) – без изменений
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
# НОВАЯ АДМИН-ПАНЕЛЬ DC (только 4 кнопки)
# ============================================================
class DCPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="💳 Начислить", style=ButtonStyle.gray, row=0)
    async def give_dc_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await inter.response.send_modal(GiveDcModal())

    @disnake.ui.button(label="💸 Снять", style=ButtonStyle.gray, row=0)
    async def take_dc_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await inter.response.send_modal(TakeDcModal())

    @disnake.ui.button(label="🛒 Покупки", style=ButtonStyle.gray, row=0)
    async def manage_purchases_button(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await inter.response.send_modal(ManagePurchasesModal())

    @disnake.ui.button(label="🔄 Акция", style=ButtonStyle.gray, row=0)
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
# МОДАЛКИ ДЛЯ DC-ПАНЕЛИ (Начислить, Снять, Покупки)
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
            await inter.response.send_message(f"✅ Списано {amount} DC у <@{user_id}>.", ephemeral=True)
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
# КОМАНДА /panel_dc (новая админ-панель)
# ============================================================
@bot.slash_command(name="panel_dc", description="Админ-панель управления Diamond Coins")
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

    await inter.send(embeds=[embed1, embed2], ephemeral=True, view=DCPanelView())

# ============================================================
# НОВАЯ ПАНЕЛЬ "ДОМИК" (канал 1532398684074016870)
# ============================================================
HOME_CHANNEL_ID = 1532398684074016870

class HomePanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤㅤㅤㅤПокупкаㅤㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="home:buy",
        row=0
    )
    async def home_buy(self, button: Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(BuyDcModal())

    @disnake.ui.button(
        label="ㅤㅤПолучение валютыㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="home:earn",
        row=0
    )
    async def home_earn(self, button: Button, inter: disnake.MessageInteraction):
        embed = disnake.Embed(
            title="💎 Как заработать Diamond Coins?",
            description=(
                "> **1. Отзывы** – напиши отзыв в <#1462074763437543435> и получи **+10 DC** после модерации.\n"
                "> **2. Сообщения** – каждые 10 сообщений в любом канале (кроме отзывов) приносят **+1 DC** (до 20 раз в день).\n"
                "> **3. Голосовые чаты** – каждый час в голосовом канале даёт **+3 DC** (до 15 часов в день).\n"
                "> **4. Ежедневный бонус** – если у вас есть роль «Клуб», каждый день вы получаете **+3 DC**.\n"
                "> **5. Акции** – следите за акциями в <#1469698608390606898> и покупайте товары со скидкой.\n"
                "> **6. Приглашения** – приглашайте друзей, и получайте бонусы за каждого реального пользователя."
            ),
            color=6776679
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307371667506/image.png?ex=6a8133e3&is=6a7fe263&hm=2af0f26a823ea59af3001dc16ce84920759e966bc40824095314e6cd1d9b38ca&")
        await inter.response.send_message(embed=embed, ephemeral=True)

    @disnake.ui.button(
        label="ㅤㅤㅤㅤПрофильㅤㅤㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="home:profile",
        row=0
    )
    async def home_profile(self, button: Button, inter: disnake.MessageInteraction):
        await show_profile(inter, inter.author)

class BuyDcModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Категория товара", custom_id="category", placeholder="Например: роли, дизайн, скидки", min_length=2, max_length=50),
            TextInput(label="Название товара", custom_id="item_name", placeholder="Введите точное название", min_length=2, max_length=100)
        ]
        super().__init__(title="Покупка за Diamond Coins", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        category_input = inter.text_values["category"].strip().lower()
        item_name = inter.text_values["item_name"].strip()

        catalog = load_shop_catalog()
        found_item = None
        found_category = None
        for cat_key, cat_data in catalog.items():
            for item_key, item_data in cat_data.get("items", {}).items():
                if item_data["name"].lower() == item_name.lower():
                    found_item = item_data
                    found_category = cat_key
                    break
            if found_item:
                break

        if not found_item:
            return await inter.response.send_message("❌ Товар не найден. Проверьте название.", ephemeral=True)

        price = found_item["price"]
        user_id = inter.author.id
        balance = await get_user_balance(user_id)
        if balance < price:
            return await inter.response.send_message(f"❌ Недостаточно DC. Нужно: **{price} DC**, у вас: **{balance} DC**.", ephemeral=True)

        success = await remove_dc(user_id, price, f"Покупка: {found_item['name']}")
        if not success:
            return await inter.response.send_message("❌ Ошибка списания DC.", ephemeral=True)

        await add_purchase(user_id, found_category, found_item["name"])

        if found_category == "roles" and found_item.get("role_id"):
            role = inter.guild.get_role(found_item["role_id"])
            if role:
                try:
                    await inter.author.add_roles(role)
                    await inter.response.send_message(
                        f"✅ Вы купили роль **{found_item['name']}** за **{price} DC**! Роль выдана. Не забудьте оставить отзыв в <#1462074763437543435>.",
                        ephemeral=True
                    )
                    await log_discord(
                        title="🛒 Покупка роли через Домик",
                        description=f"> **Пользователь:** {inter.author.mention}\n> **Роль:** {found_item['name']}\n> **Цена:** {price} DC",
                        color=0x00aaff
                    )
                    return
                except Exception as e:
                    await add_dc(user_id, price, "Возврат DC (ошибка выдачи роли)")
                    await inter.response.send_message(f"❌ Не удалось выдать роль: {e}\n💎 {price} DC возвращены.", ephemeral=True)
                    return
            else:
                await add_dc(user_id, price, "Возврат DC (роль не найдена)")
                await inter.response.send_message(f"❌ Роль не найдена на сервере.\n💎 {price} DC возвращены.", ephemeral=True)
                return

        await inter.response.send_message(
            f"✅ Вы купили **{found_item['name']}** за **{price} DC**! Товар будет выдан в ближайшее время. Не забудьте оставить отзыв в <#1462074763437543435>.",
            ephemeral=True
        )
        await log_discord(
            title="🛒 Покупка через Домик",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {found_item['name']}\n> **Цена:** {price} DC",
            color=0x00aaff
        )

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

async def send_home_panel():
    await bot.wait_until_ready()
    channel = bot.get_channel(HOME_CHANNEL_ID)
    if not channel:
        channel = await bot.fetch_channel(HOME_CHANNEL_ID)
    if not channel:
        logger.warning("Home panel channel not found")
        return

    # Удаляем старые сообщения бота в этом канале
    async for msg in channel.history(limit=50):
        if msg.author == bot.user:
            try:
                await msg.delete()
            except:
                pass

    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://media.discordapp.net/attachments/1527006158282555412/1538202626448171088/image.png?ex=6a81d254&is=6a8080d4&hm=3c8318fb665830d99422f59fe9cf66d8307cfbd1bc89d07525301190e36bd7fa&=&format=webp&quality=lossless")

    embed2 = disnake.Embed(
        title="Домик посетителя Diamond Shop",
        description=(
            "> Привет дорогой посетитель! В данном канале, ты можешь узнать о том: какие есть товары за Diamond Coins, как вообще - заработать Diamond Coin, а также - можешь увидеть свой профиль, отслеживать свои покупки, баланс валюты, и прочие изменения."
        ),
        color=6776679
    )
    embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307371667506/image.png?ex=6a8133e3&is=6a7fe263&hm=2af0f26a823ea59af3001dc16ce84920759e966bc40824095314e6cd1d9b38ca&")

    await channel.send(embeds=[embed1, embed2], view=HomePanelView())
    await log_discord(
        title="🏠 Панель «Домик» отправлена",
        description="> Новая панель для посетителей.",
        color=0x00ff00
    )

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
# РАССЫЛКА (без изменений)
# ============================================================
class MassSender:
    active_task = None
    stop_flag = False

class MassSendModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="JSON с embed (как в /say)", custom_id="embed_json", style=disnake.TextInputStyle.paragraph, placeholder='{"embeds": [...]}', required=False),
            TextInput(label="Роль для фильтра (ID или @упоминание, опционально)", custom_id="role_filter", required=False, placeholder="ID роли или @роль")
        ]
        super().__init__(title="Массовая рассылка", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        embed_json = inter.text_values.get("embed_json", "").strip()
        role_input = inter.text_values.get("role_filter", "").strip()
        if not embed_json:
            return await inter.response.send_message("❌ Введите JSON с embed.", ephemeral=True)
        try:
            data = json.loads(embed_json)
            if "embeds" not in data:
                return await inter.response.send_message("❌ Нет поля 'embeds'.", ephemeral=True)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data["embeds"]]
            content = data.get("content", " ")
        except Exception as e:
            return await inter.response.send_message(f"❌ Ошибка парсинга JSON: {e}", ephemeral=True)

        guild = inter.guild or bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild:
            return await inter.response.send_message("❌ Сервер не найден.", ephemeral=True)

        role = None
        if role_input:
            if role_input.isdigit():
                role = guild.get_role(int(role_input))
            else:
                match = re.search(r'<@&?(\d+)>', role_input)
                if match:
                    role = guild.get_role(int(match.group(1)))
            if not role:
                return await inter.response.send_message("❌ Роль не найдена.", ephemeral=True)

        members = [m for m in guild.members if not m.bot and m != inter.author]
        if role:
            members = [m for m in members if role in m.roles]
        if not members:
            return await inter.response.send_message("❌ Нет получателей.", ephemeral=True)

        if MassSender.active_task and not MassSender.active_task.done():
            return await inter.response.send_message("⚠️ Уже идёт рассылка.", ephemeral=True)

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
        progress_msg = await inter.response.send_message(embed=progress_embed, view=stop_view, ephemeral=True)
        MassSender.stop_flag = False
        task = bot.loop.create_task(
            send_mass_messages(
                members=members,
                content=content,
                embeds=embeds,
                progress_msg=progress_msg,
                progress_embed=progress_embed,
                ctx=inter
            )
        )
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
# МОДАЛКИ ДЛЯ НОВЫХ ПАНЕЛЕЙ (admin_panel, promocodes) – без изменений
# ============================================================
class SayModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Канал (ID или упоминание)", custom_id="channel", placeholder="Введите ID канала или #канал", min_length=1, max_length=50),
            TextInput(label="Тип", custom_id="type", placeholder="text или embed", min_length=3, max_length=10),
            TextInput(label="Содержание", custom_id="content", style=disnake.TextInputStyle.paragraph, placeholder="Текст или JSON для embed", max_length=2000)
        ]
        super().__init__(title="Отправить сообщение от бота", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        channel_input = inter.text_values["channel"].strip()
        msg_type = inter.text_values["type"].strip().lower()
        content = inter.text_values["content"].strip()

        channel = None
        if channel_input.isdigit():
            channel = bot.get_channel(int(channel_input))
        else:
            match = re.search(r'<#(\d+)>', channel_input)
            if match:
                channel = bot.get_channel(int(match.group(1)))
        if not channel:
            return await inter.response.send_message("❌ Канал не найден.", ephemeral=True)

        try:
            if msg_type == "text":
                await channel.send(content)
                await inter.response.send_message(f"✅ Сообщение отправлено в {channel.mention}", ephemeral=True)
                await log_discord("📨 Say: текст отправлен", f"Админ {inter.author.mention} → {channel.mention}", color=0x00ff00)
            elif msg_type == "embed":
                data = json.loads(content)
                if "embeds" not in data:
                    return await inter.response.send_message("❌ Нет поля 'embeds'.", ephemeral=True)
                embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data["embeds"]]
                await channel.send(content=data.get("content", " "), embeds=embeds)
                await inter.response.send_message(f"✅ Embed отправлен в {channel.mention}", ephemeral=True)
                await log_discord("📨 Say: embed отправлен", f"Админ {inter.author.mention} → {channel.mention}", color=0x00ff00)
            else:
                await inter.response.send_message("❌ Тип должен быть 'text' или 'embed'.", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

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
# ПАНЕЛИ (admin_panel, promocodes) – без изменений
# ============================================================
class AdminPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="Пересчёт отзывов",
        style=disnake.ButtonStyle.gray,
        row=0,
        custom_id="admin_recalc"
    )
    async def admin_recalc(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        await recalc_reviews(inter)

    @disnake.ui.button(
        label="Обновление баннера",
        style=disnake.ButtonStyle.gray,
        row=0,
        custom_id="admin_banner"
    )
    async def admin_banner(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        await update_review_counter(silent=False)

    @disnake.ui.button(
        label="Выгрузка JSON",
        style=disnake.ButtonStyle.gray,
        row=0,
        custom_id="admin_get_json"
    )
    async def admin_get_json(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.send_modal(GetJsonModal())

class PromoPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="Промокод",
        style=disnake.ButtonStyle.gray,
        row=0,
        custom_id="promo_list"
    )
    async def promo_list(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        reload_promo_cache()
        if not promo_codes:
            await inter.response.send_message("Промокодов нет.", ephemeral=True)
            return
        text = "\n".join([f"{code} → {value}" for code, value in promo_codes.items()])
        await inter.response.send_message(f"```\n{text}\n```", ephemeral=True)

    @disnake.ui.button(
        label="Добавление промокода",
        style=disnake.ButtonStyle.gray,
        row=0,
        custom_id="promo_add"
    )
    async def promo_add(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.send_modal(PromoAddModal())

    @disnake.ui.button(
        label="Удаление промокода",
        style=disnake.ButtonStyle.gray,
        row=0,
        custom_id="promo_remove"
    )
    async def promo_remove(self, button: Button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.send_message("Выберите промокод для удаления:", ephemeral=True, view=PromoRemoveSelectView())

# ============================================================
# Функция для пересчёта отзывов
# ============================================================
async def recalc_reviews(inter):
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
# СЛЕШ-КОМАНДЫ (новые и оставшиеся)
# ============================================================
@bot.slash_command(name="admin_panel", description="Панель управления сервером (админ)")
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
    await inter.send(embeds=embeds, ephemeral=True, view=AdminPanelView())

@bot.slash_command(name="promocodes", description="Управление промокодами (админ)")
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
    await inter.send(embeds=embeds, ephemeral=True, view=PromoPanelView())

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

@bot.slash_command(
    name="say",
    description="Отправить сообщение от лица бота (текст или embed)",
    default_member_permissions=disnake.Permissions(administrator=True)
)
async def say(
    ctx,
    канал: disnake.TextChannel,
    тип_сообщения: str = commands.Param(choices=["text", "embed"], description="Тип сообщения"),
    текст: Optional[str] = None,
    файл: Optional[disnake.Attachment] = None
):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав на использование этой команды.", ephemeral=True)

    if тип_сообщения == "text":
        if not текст:
            return await ctx.send("❌ Введите текст для отправки.", ephemeral=True)
        await канал.send(текст)
        await ctx.send(f"✅ Сообщение отправлено в {канал.mention}", ephemeral=True)
        await log_discord(
            title="📨 Say: текст отправлен",
            description=f"> **Админ:** {ctx.author.mention}\n> **Канал:** {канал.mention}\n> **Текст:** {текст[:500]}",
            color=0x00ff00
        )
        return

    if тип_сообщения == "embed":
        if not текст and not файл:
            return await ctx.send("❌ Укажите JSON текст или файл с JSON для embed.", ephemeral=True)
        if текст and файл:
            return await ctx.send("❌ Только один источник: либо текст JSON, либо файл.", ephemeral=True)
        try:
            if файл:
                raw = await файл.read()
                data = json.loads(raw.decode("utf-8"))
            else:
                data = json.loads(текст)
            if "embeds" not in data:
                return await ctx.send("❌ Нет поля 'embeds' в JSON.", ephemeral=True)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data["embeds"]]
            content = data.get("content", " ")
            await канал.send(content=content, embeds=embeds)
            await ctx.send(f"✅ Embed отправлен в {канал.mention}", ephemeral=True)
            await log_discord(
                title="📨 Say: embed отправлен",
                description=f"> **Админ:** {ctx.author.mention}\n> **Канал:** {канал.mention}",
                color=0x00ff00
            )
        except Exception as e:
            logger.exception("say embed error: %s", e)
            await ctx.send(f"❌ Ошибка при отправке embed: {e}", ephemeral=True)

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

# ============================================================
# НАСТРОЙКА МОДУЛЯ (для main.py)
# ============================================================
def setup_commands(bot):
    pass
