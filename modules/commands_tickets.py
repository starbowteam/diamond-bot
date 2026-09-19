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
    add_closed_order,
    get_promo_codes
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
# ХЕЛПЕР: загрузка slid.json из actions/ или add/
# ============================================================
def _load_slid_embeds() -> list:
    base_project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base_project, "actions", "slid.json"),
        os.path.join(ADD_DIR, "slid.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return [
                    disnake.Embed.from_dict(clean_embed_for_discohook(e))
                    for e in data.get("embeds", [])
                ]
            except Exception as e:
                logger.error(f"Ошибка чтения {path}: {e}")
    logger.error("slid.json не найден ни в actions/, ни в add/")
    return []


def clear_ticket_owner(channel: disnake.TextChannel):
    user_id = get_ticket_owner(channel.id)
    if user_id:
        remove_ticket_owner(channel.id)


# ============================================================
# СОЗДАНИЕ ТИКЕТА ЗА РЕАЛЬНЫЕ ДЕНЬГИ (без формы)
# ============================================================
async def create_real_ticket(inter: disnake.MessageInteraction):
    user = inter.author
    guild = inter.guild

    cat = guild.get_channel(CONFIG["TICKET_CATEGORY_ID"])
    if not cat:
        return await inter.response.send_message("❌ Категория не найдена.", ephemeral=True)

    # Название канала = имя заказчика
    raw = user.display_name.lower().replace(" ", "-")
    raw = re.sub(r"[^a-zа-яё0-9\-_]", "", raw)
    channel_name = raw[:80] or f"order-{user.id}"

    overwrites = {
        guild.default_role: disnake.PermissionOverwrite(view_channel=False),
        user: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    for rid in CONFIG["TICKET_VIEW_ROLES"]:
        role = guild.get_role(rid)
        if role:
            overwrites[role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    for rid in CONFIG["TICKET_MANAGE_ROLES"]:
        role = guild.get_role(rid)
        if role:
            overwrites[role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    await inter.response.defer(ephemeral=True)

    try:
        ticket_channel = await cat.create_text_channel(name=channel_name, overwrites=overwrites)
    except Exception as e:
        logger.error(f"Не удалось создать тикет: {e}")
        return await inter.edit_original_response(content=f"❌ Ошибка создания тикета: {e}")

    # Загружаем шаблон info-o-zakaze.json
    try:
        with open(CONFIG["INFO_TEMPLATE_PATH"], "r", encoding="utf-8") as f:
            data = json.load(f)
        embeds_list = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]
    except Exception as e:
        logger.error(f"Ошибка загрузки шаблона: {e}")
        embeds_list = [disnake.Embed(color=6776679), disnake.Embed(title="Информация о заказе", color=6776679)]

    embed_order_info = embeds_list[1] if len(embeds_list) > 1 else disnake.Embed(title="Информация о заказе", color=0x7c3131)
    embed_order_info.clear_fields()
    embed_order_info.add_field(name="> Заказчик", value=f"```{user.display_name}```", inline=True)
    embed_order_info.add_field(name="> Скидка на товар", value="```Не активирована```", inline=True)

    current_time = int(time.time())
    embed_order_info.description = (
        f"Статус - Не оплачен\n"
        f"> Ожидайте <@&1154757071330365490> для подтверждения.\n"
        f"> Время заказа: <t:{current_time}:f>"
    )

    view = TicketView()
    await ticket_channel.send(
        f"> Добрый день, {user.mention}, ваш тикет создан. Ожидайте ответа от <@&1154757071330365490>\n"
        f"> После уточнения заказа - менеджер создаст вам счёт.",
        embeds=[embeds_list[0], embed_order_info],
        view=view
    )

    # Селект с политикой и счётом
    select_embed = disnake.Embed(
        title="Что именно нужно посмотреть?",
        description="Ниже, выбор - просмотр политики по заказу, либо - создать счет  \n\nВыберите нужный пункт.",
        color=6776679
    )
    select_embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8b1723&is=6a89c5a3&hm=84444a514a08c282e27d51013698ba7b5e82c75a45ae4a004c56b3e58a9acd12&")
    await ticket_channel.send(embed=select_embed, view=SelectView())

    add_ticket_owner(ticket_channel.id, user.id, cat.id)

    await inter.edit_original_response(content=f"✅ Тикет создан: {ticket_channel.mention}")

    log_ch = guild.get_channel(CONFIG["LOG_TICKET_CHANNEL_ID"])
    if log_ch:
        await log_ch.send(embed=disnake.Embed(
            title="📩 Тикет создан (реальные деньги)",
            description=f"> **Заказчик:** {user.mention}\n> **Канал:** {ticket_channel.mention}",
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
        await inter.response.defer(ephemeral=True)
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
            # Сразу создаём тикет без модалки
            await create_real_ticket(inter)
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

        cat = guild.get_channel(1544363672128987196)
        if not cat:
            return await inter.edit_original_response(content="❌ Категория для вопросов не найдена.")

        channel_name = inter.author.display_name.lower().replace(" ", "-")[:80]
        if not channel_name:
            channel_name = f"question-{inter.author.id}"

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            inter.author: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }

        support_role = guild.get_role(1423360115335106570)
        if support_role:
            overwrites[support_role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        admin_role = guild.get_role(1127428607606796294)
        if admin_role:
            overwrites[admin_role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        ticket_channel = await cat.create_text_channel(name=channel_name, overwrites=overwrites)

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

        view = QuestionTicketView()
        await ticket_channel.send(
            content=f"<@&1423360115335106570> - задан вопрос, постарайтесь ответить!",
            embeds=[embed1, embed2],
            view=view
        )

        await inter.edit_original_response(content=f"✅ Ваш вопрос создан: {ticket_channel.mention}")

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
        label="ㅤКак правильно задать вопрос?ㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="question:howto",
        emoji=PartialEmoji(name="pravil", id=1544388874497687622),
        row=0
    )
    async def howto(self, button: Button, inter: disnake.MessageInteraction):
        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1544387485684203682/image.png?ex=6a98526d&is=6a9700ed&hm=e6eb0b7ec153c23c7d63cb3fe64a405c56dee64cc9edbe9792cd69bfe7e4fe3b&")

        embed2 = disnake.Embed(
            title="Как правильно задать вопрос?",
            description=(
                "> Чтобы правильно задать вопрос, нужно сформулировать его чётко, кратко и без скрытых подсказок, указав суть проблемы и ожидаемый результат.\n\n"
                "> Основные правила сильного вопроса\n\n"
                "`Определите цель: `Поймите, какая информация вам нужна.\n"
                "`Говорите просто: `Избегайте сложных терминов и длинных конструкций.\n"
                "`Избегайте наводок:` Не подталкивайте собеседника к нужному вам ответу.\n"
                "`Используйте открытые вопросы:` Начинайте со слов «что», «как» и тд. чтобы получить развёрнутый ответ.\n"
                "`Добавляйте контекст:` Если это технический вопрос или обращение на форум, опишите проблему, что вы уже сделали и какой результат ожидали."
            ),
            color=6776679
        )
        embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a979d63&is=6a964be3&hm=6b425dcaba72f3d56d43c943a7a02f5a4d6627fbfa68330b6a0a1905992e9705&")
        embed2.add_field(name="", value="")

        await inter.response.send_message(embeds=[embed1, embed2])
        await log_discord(
            title="📖 Просмотр инструкции по вопросам",
            description=f"> **Канал:** {inter.channel.mention}\n> **Пользователь:** {inter.author.mention}",
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    @disnake.ui.button(
        label="ㅤㅤЗакрытьㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="question:close",
        emoji=PartialEmoji(name="OffTicket", id=1539657125716824185),
        row=0
    )
    async def close(self, button: Button, inter: disnake.MessageInteraction):
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
                    label="Счет на оплату",
                    description="Сгенерировать счёт на оплату",
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
            if not any(r.id == 1154757071330365490 for r in inter.author.roles):
                return await inter.response.send_message(
                    "⛔ Кнопка доступна только менеджерам.", ephemeral=True
                )
            await inter.response.send_modal(InvoiceModal())
        elif value == "policy":
            await self.send_policy(inter)

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
# МОДАЛКА СОЗДАНИЯ СЧЁТА (только для менеджеров)
# ============================================================
class InvoiceModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="Товар / Услуга",
                placeholder="Например: Discord Nitro 1 Month",
                custom_id="product",
                min_length=2,
                max_length=80
            ),
            TextInput(
                label="Введите сумму для счёта",
                placeholder="Например: 445",
                custom_id="amount",
                min_length=1,
                max_length=10
            ),
            TextInput(
                label="Скидка в %, если была (необязательно)",
                placeholder="Например: 10",
                custom_id="discount",
                required=False,
                max_length=3
            )
        ]
        super().__init__(title="Создание счёта", components=components, custom_id="invoice_modal")

    async def callback(self, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)

        import asyncio as _asyncio
        from modules.receipt import generate_receipt_png, generate_receipt_id

        product_name = inter.text_values["product"].strip()
        amount_str = inter.text_values["amount"].strip()
        discount_str = inter.text_values.get("discount", "").strip()

        if not amount_str.isdigit():
            return await inter.edit_original_response(content="❌ Сумма должна быть числом.")
        amount = int(amount_str)
        if amount <= 0:
            return await inter.edit_original_response(content="❌ Сумма должна быть больше 0.")

        discount_percent = 0
        if discount_str:
            if not discount_str.isdigit():
                return await inter.edit_original_response(content="❌ Скидка должна быть числом.")
            discount_percent = int(discount_str)
            if discount_percent < 0 or discount_percent > 100:
                return await inter.edit_original_response(content="❌ Скидка должна быть от 0 до 100%.")

        manager_id = get_ticket_manager(inter.channel.id)
        manager = inter.guild.get_member(manager_id) if manager_id else None
        manager_name = str(manager) if manager else "—"

        # Имя заказчика = владелец тикета
        owner_id = get_ticket_owner(inter.channel.id)
        owner = inter.guild.get_member(owner_id) if owner_id else None
        customer_name = owner.display_name if owner else inter.channel.name

        order_id = generate_receipt_id()

        buf = await _asyncio.to_thread(
            generate_receipt_png,
            manager_name=manager_name,
            customer_name=customer_name,
            product_name=product_name,
            amount=amount,
            discount_percent=discount_percent,
            order_id=order_id
        )

        total = amount - int(amount * discount_percent / 100)

        file = disnake.File(buf, filename=f"receipt_{order_id}.png")

        embed = disnake.Embed(
            title=f"Счёт для оплаты создан: к оплате {total} Р",
            color=6776679
        )
        embed.set_image(url=f"attachment://receipt_{order_id}.png")

        await inter.channel.send(embed=embed, file=file)
        await inter.edit_original_response(content="✅ Счёт отправлен в тикет.")

        await log_discord(
            title="🧾 Создан счёт",
            description=(
                f"> **Менеджер:** {inter.author.mention}\n"
                f"> **Канал:** {inter.channel.mention}\n"
                f"> **Товар/Услуга:** {product_name}\n"
                f"> **Сумма:** {amount} Р\n"
                + (f"> **Скидка:** {discount_percent}%\n" if discount_percent > 0 else "")
                + f"> **Итого:** {total} Р"
            ),
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )


# ============================================================
# МОДАЛКА ВВОДА ПРОМОКОДА
# ============================================================
class PromoCodeModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="Промокод",
                placeholder="Введите код промокода",
                custom_id="promo_code",
                min_length=1,
                max_length=50
            )
        ]
        super().__init__(title="🎟️ Ввод промокода", components=components, custom_id="promo_code_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        code = inter.text_values["promo_code"].strip().upper()

        codes = get_promo_codes()
        if code not in codes:
            return await inter.response.send_message(
                "❌ Такой промокод не найден или уже недействителен.",
                ephemeral=True
            )

        value = codes[code]
        channel = inter.channel

        # Ищем info-эмбед заказа
        target_msg = None
        async for msg in channel.history(limit=50):
            if msg.author == inter.bot.user and msg.embeds and len(msg.embeds) >= 2:
                target_msg = msg
                break

        if not target_msg:
            return await inter.response.send_message(
                "❌ Не найдено сообщение с информацией о заказе.",
                ephemeral=True
            )

        # Обновляем поле "Скидка на товар"
        embed_dict = target_msg.embeds[1].to_dict()
        for field in embed_dict.get("fields", []):
            if "скидка" in field.get("name", "").lower():
                field["value"] = f"```{code} — {value}```"
                break

        new_embed = disnake.Embed.from_dict(embed_dict)
        embeds = list(target_msg.embeds)
        embeds[1] = new_embed
        await target_msg.edit(embeds=embeds)

        await inter.response.send_message(
            f"✅ Промокод **{code}** активирован!\n"
            f"> **Скидка:** `{value}`",
            ephemeral=True
        )

        await log_discord(
            title="🎟️ Промокод активирован",
            description=(
                f"> **Пользователь:** {inter.author.mention}\n"
                f"> **Тикет:** {channel.mention}\n"
                f"> **Код:** `{code}` — {value}"
            ),
            color=0x00ff00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )


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
            clear_ticket_owner(channel)
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
                clear_ticket_owner(channel)
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

        embed = disnake.Embed(
            title="💚 Заказ оплачен",
            description=f"> **Подтвердил:** {inter.author.mention}",
            color=0x2ecc71
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a8e62e3&is=6a8d1163&hm=1bb78040233c69c4629e20b50c7dd52a621f0eba270ddc51152b974800d6b48b&")
        await channel.send(embed=embed)

        await inter.response.send_message("✅ Заказ отмечен как оплаченный.", ephemeral=True)

        await log_discord(
            title="💰 Заказ оплачен",
            description=(
                f"> **Канал:** {channel.mention}\n"
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

        # Проверка: скидка уже применена?
        discount_applied = False
        async for msg in channel.history(limit=50):
            if msg.author == inter.bot.user and msg.embeds and len(msg.embeds) >= 2:
                for field in msg.embeds[1].fields:
                    if "скидка" in field.name.lower():
                        val = field.value.strip("`\n ")
                        if val not in ["Не активирована", "Не введён", "Не активирован"]:
                            discount_applied = True
                        break
                break
        if discount_applied:
            return await inter.response.send_message("❌ К данному заказу уже применена скидка.", ephemeral=True)

        all_purchases = await get_user_purchases(inter.author.id, only_unused=True)
        discounts = [p for p in all_purchases if p.get('type') == 'discounts']

        slid_embeds = _load_slid_embeds()
        if not slid_embeds:
            slid_embeds = [disnake.Embed(
                title="📦 Ваши скидки",
                description="> Введи промокод или выбери купленную скидку.",
                color=6776679
            )]

        view = View(timeout=300)

        # Первая кнопка — Ввести промокод
        btn_promo = Button(
            label="Ввести промокод",
            style=ButtonStyle.gray,
            custom_id=f"promo_input_{inter.author.id}",
            emoji=PartialEmoji(name="prom1", id=1539646792139014234),
            row=0
        )

        async def promo_callback(inter2: disnake.MessageInteraction):
            if inter2.author.id != inter.author.id:
                return await inter2.response.send_message("⛔ Это не ваш тикет.", ephemeral=True)
            await inter2.response.send_modal(PromoCodeModal())

        btn_promo.callback = promo_callback
        view.add_item(btn_promo)

        # Купленные скидки — начиная с row=1
        row = 1
        col = 0
        for idx, p in enumerate(discounts):
            if col >= 5:
                row += 1
                col = 0
            label = p['value']
            if len(label) > 80:
                label = label[:77] + "..."
            btn = Button(
                label=label,
                style=ButtonStyle.gray,
                custom_id=f"apply_discount_{inter.author.id}_{idx}",
                row=row
            )
            btn.callback = self.create_discount_callback(idx, inter, discounts)
            view.add_item(btn)
            col += 1

        await inter.response.send_message(embeds=slid_embeds, view=view, ephemeral=True)

    def create_discount_callback(self, discount_index, original_inter, discounts):
        async def callback(inter: disnake.MessageInteraction):
            if inter.author.id != original_inter.author.id:
                return await inter.response.send_message("⛔ Это не ваш товар.", ephemeral=True)

            if discount_index >= len(discounts):
                return await inter.response.send_message("❌ Скидка уже применена.", ephemeral=True)

            channel = inter.channel

            discount_applied = False
            async for msg in channel.history(limit=50):
                if msg.author == inter.bot.user and msg.embeds and len(msg.embeds) >= 2:
                    for field in msg.embeds[1].fields:
                        if "скидка" in field.name.lower():
                            val = field.value.strip("`\n ")
                            if val not in ["Не активирована", "Не введён", "Не активирован"]:
                                discount_applied = True
                            break
                    break
            if discount_applied:
                return await inter.response.send_message("❌ К данному заказу уже применена скидка.", ephemeral=True)

            item_value = discounts[discount_index]['value']

            full_purchases = await get_user_purchases(inter.author.id, only_unused=False)
            target_index = None
            for i, p in enumerate(full_purchases):
                if p['value'] == item_value and p.get('type') == 'discounts' and not p.get('used'):
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
                        if "скидка" in field.get("name", "").lower():
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
                clear_ticket_owner(channel)
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
                clear_ticket_owner(channel)
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
            target_index = None
            for i, p in enumerate(full_purchases):
                if p['value'] == item_value and p.get('type') != 'discounts' and not p.get('used'):
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
     "emoji": "<:SuperCell:1465768886484996260>", "json_path": os.path.join(CATALOG_DIR, "menu_supercell.json")},
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
    async def buy(self, button: disnake.Button, inter: disnake.MessageInteraction):
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
    async def promo(self, button: disnake.Button, inter: disnake.MessageInteraction):
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
    async def catalog(self, button: disnake.Button, inter: disnake.MessageInteraction):
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
    # Логика buy_ticket убрана — теперь тикет создаётся сразу из BuySelect
    pass
