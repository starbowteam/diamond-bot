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
    get_promo_codes,
    activate_item, add_jackpot_bank,
)
from modules.dc import (
    add_dc, remove_dc, add_purchase,
    get_user_purchases, remove_purchase,
    get_dc_cache, save_dc_cache,
    get_user_balance,
    load_shop_catalog
)
from modules.actions import load_action_embed
from modules.gifts import process_gift_dc
from modules.boosts import can_activate, do_activate

IMG_STRIPE_TICKETS = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6ab152a3&is=6ab00123&hm=c5c2963ca1ebbe6eb37f673fcef993cacf375c5a80490205c230d4c4adfe8b58&"

DIRECT_BUY_CATEGORIES = {"discounts", "boosts", "casino", "gifts"}


# ============================================================
# HELPERS
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
    logger.error("slid.json не найден")
    return []


def clear_ticket_owner(channel):
    user_id = get_ticket_owner(channel.id)
    if user_id:
        remove_ticket_owner(channel.id)


def _is_paid_ticket(channel):
    if not channel.category:
        return False
    return channel.category.id == CONFIG["PAID_CATEGORY_ID"]


# ============================================================
# СОЗДАНИЕ ТИКЕТОВ
# ============================================================
async def create_real_ticket(inter):
    user = inter.author
    guild = inter.guild
    cat = guild.get_channel(CONFIG["TICKET_CATEGORY_ID"])
    if not cat:
        return await inter.response.send_message("❌ Категория не найдена.", ephemeral=True)

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
        return await inter.followup.send(content=f"❌ Ошибка создания: {e}", ephemeral=True)

    try:
        with open(CONFIG["INFO_TEMPLATE_PATH"], "r", encoding="utf-8") as f:
            data = json.load(f)
        embeds_list = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]
    except Exception as e:
        logger.error(f"Ошибка загрузки шаблона: {e}")
        embeds_list = [disnake.Embed(color=6776679), disnake.Embed(title="Информация о заказе", color=6776679)]

    embed_order_info = embeds_list[1] if len(embeds_list) > 1 else disnake.Embed(title="Инфо", color=0x7c3131)
    embed_order_info.clear_fields()
    embed_order_info.add_field(name="> Заказчик", value=f"```{user.display_name}```", inline=True)
    embed_order_info.add_field(name="> Скидка на товар", value="```Не активирована```", inline=True)
    embed_order_info.description = (
        f"Статус - Не оплачен\n"
        f"> Ожидайте <@&1154757071330365490> для подтверждения.\n"
        f"> Время заказа: <t:{int(time.time())}:f>"
    )

    view = TicketView()
    await ticket_channel.send(
        f"> Добрый день, {user.mention}, ваш тикет создан. Ожидайте ответа от <@&1154757071330365490>\n"
        f"> После уточнения заказа - менеджер создаст вам счёт.",
        embeds=[embeds_list[0], embed_order_info],
        view=view
    )

    select_embed = disnake.Embed(
        title="Что именно нужно посмотреть?",
        description="Ниже, выбор - просмотр политики по заказу, либо - создать счет\n\nВыберите нужный пункт.",
        color=6776679
    )
    select_embed.set_image(url=IMG_STRIPE_TICKETS)
    await ticket_channel.send(embed=select_embed, view=SelectView())

    add_ticket_owner(ticket_channel.id, user.id, cat.id)

    try:
        await inter.response.edit_message(
            content=f"> {user.mention}, тикет создан — {ticket_channel.mention}\n> Сообщите в тикете, о товаре.",
            embeds=[], view=None
        )
    except Exception:
        await inter.followup.send(
            content=f"> {user.mention}, тикет создан — {ticket_channel.mention}",
            ephemeral=True
        )

    log_ch = guild.get_channel(CONFIG["LOG_TICKET_CHANNEL_ID"])
    if log_ch:
        await log_ch.send(embed=disnake.Embed(
            title="📩 Тикет создан (реальные деньги)",
            description=f"> **Заказчик:** {user.mention}\n> **Канал:** {ticket_channel.mention}",
            timestamp=datetime.now(timezone.utc), color=0x00ff00
        ))


async def create_coins_ticket(inter, purchase, purchase_index):
    user = inter.author
    guild = inter.guild
    cat = guild.get_channel(CONFIG["COINS_CATEGORY_ID"])
    if not cat:
        return await inter.response.send_message("❌ Категория не найдена.", ephemeral=True)

    item_name = purchase.get("value", "—")
    raw = item_name.lower().replace(" ", "-")
    raw = re.sub(r"[^a-zа-яё0-9\-_]", "", raw)
    channel_name = raw[:80] or f"item-{user.id}"

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
        logger.error(f"Не удалось создать DC-тикет: {e}")
        return await inter.edit_original_response(content=f"❌ Ошибка: {e}")

    try:
        await remove_purchase(user.id, purchase_index)
    except Exception as e:
        logger.warning(f"Не удалить покупку #{purchase_index}: {e}")

    try:
        with open(CONFIG["COINS_INFO_TEMPLATE_PATH"], "r", encoding="utf-8") as f:
            data = json.load(f)
        embeds_list = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]
    except Exception as e:
        embeds_list = [disnake.Embed(color=6776679), disnake.Embed(title="Инфо", color=6776679)]

    embed_order_info = embeds_list[1] if len(embeds_list) > 1 else disnake.Embed(title="Инфо", color=0x7c3131)
    embed_order_info.clear_fields()
    embed_order_info.add_field(name="> Нужный товар", value=f"```{item_name}```", inline=False)
    embed_order_info.description = (
        f"Статус - Не оплачен\n"
        f"> Ожидайте <@&1154757071330365490> для подтверждения.\n"
        f"> Время: <t:{int(time.time())}:f>"
    )

    view = CoinsTicketButtons()
    await ticket_channel.send(
        content=f"> Добрый день, {user.mention}, ваш тикет на категорию **DC** — создан.",
        embeds=[embeds_list[0], embed_order_info], view=view
    )

    add_ticket_owner(ticket_channel.id, user.id, cat.id)

    new_content = f"> {user.mention}, тикет на **DC** — создан.\n> Перейти: {ticket_channel.mention}"
    try:
        await inter.response.edit_message(content=new_content, embeds=[], view=None)
    except Exception:
        try:
            await inter.edit_original_response(content=new_content, embeds=[], view=None)
        except Exception:
            await inter.followup.send(content=new_content, ephemeral=True)

    log_ch = guild.get_channel(CONFIG["LOG_TICKET_CHANNEL_ID"])
    if log_ch:
        await log_ch.send(embed=disnake.Embed(
            title="📩 Тикет создан (DC)",
            description=f"> **Пользователь:** {user.mention}\n> **Канал:** {ticket_channel.mention}\n> **Товар:** `{item_name}`",
            timestamp=datetime.now(timezone.utc), color=0x00ff00
        ))


# ============================================================
# ВЫБОР ТИПА ПОКУПКИ
# ============================================================
class BuySelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="Реальные деньги", description="Оплата в рублях, USDT и т.д.",
                                 emoji="<:realmomne:1539649281575620618>", value="real"),
            disnake.SelectOption(label="Diamond Coins", description="Бонусная валюта сервера",
                                 emoji="<:coins:1539649259245408340>", value="coins"),
            disnake.SelectOption(label="Задать вопрос", description="Узнать о нужном товаре",
                                 emoji="<:questi:1544371841118773328>", value="question"),
        ]
        super().__init__(placeholder="Выберите способ оплаты...", min_values=1, max_values=1,
                         options=options, custom_id="buy_type_select")

    async def callback(self, inter):
        await log_discord(
            title="🛒 Выбор типа покупки",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )
        value = inter.data.values[0]
        if value == "real":
            await create_real_ticket(inter)
        elif value == "coins":
            EXCLUDED = {'discounts', 'boosts', 'casino', 'gifts'}
            purchases = await get_user_purchases(inter.author.id, only_unused=True)
            purchases = [p for p in purchases if p.get('type') not in EXCLUDED]
            if not purchases:
                return await inter.response.send_message(
                    "❌ У вас нет товаров для покупки за Diamond Coins.", ephemeral=True)
            embed = disnake.Embed(
                title="Выбор товара к тикету",
                description="Выберите товар.\nОдин товар — один тикет.",
                color=6776679
            )
            embed.set_image(url=IMG_STRIPE_TICKETS)
            view = CoinsBuyView(purchases)
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)
        elif value == "question":
            await inter.response.send_modal(QuestionModal())


class BuyTypeView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BuySelect())


class CoinsBuySelect(disnake.ui.StringSelect):
    def __init__(self, purchases):
        self.purchases = purchases
        options = []
        for idx, p in enumerate(purchases):
            label = p.get("value", "—")
            if len(label) > 90:
                label = label[:87] + "..."
            date_str = datetime.fromtimestamp(p.get("date", 0)).strftime("%d.%m.%Y")
            options.append(disnake.SelectOption(label=label, description=f"Куплено: {date_str}", value=str(idx)))
        super().__init__(placeholder="Выберите товар...", min_values=1, max_values=1,
                         options=options, custom_id="coins_buy_select")

    async def callback(self, inter):
        idx = int(inter.data.values[0])
        if idx >= len(self.purchases):
            return await inter.response.send_message("❌ Товар не найден.", ephemeral=True)
        user_purchases = await get_user_purchases(inter.author.id, only_unused=False)
        target = self.purchases[idx]
        target_index = None
        for i, p in enumerate(user_purchases):
            if p.get("value") == target.get("value") and p.get("type") == target.get("type") and not p.get("used"):
                target_index = i
                break
        if target_index is None:
            return await inter.response.send_message("❌ Товар уже использован.", ephemeral=True)
        await create_coins_ticket(inter, target, target_index)


class CoinsBuyView(View):
    def __init__(self, purchases):
        super().__init__(timeout=300)
        self.add_item(CoinsBuySelect(purchases))


# ============================================================
# ВОПРОС
# ============================================================
class QuestionModal(Modal):
    def __init__(self):
        components = [TextInput(label="Что за вопрос?", placeholder="Кратко суть", custom_id="question",
                                min_length=3, max_length=500)]
        super().__init__(title="Задать вопрос", components=components, custom_id="question_modal")

    async def callback(self, inter):
        await inter.response.defer(ephemeral=True)
        question = inter.text_values["question"]
        guild = inter.guild
        cat = guild.get_channel(1544363672128987196)
        if not cat:
            return await inter.edit_original_response(content="❌ Категория не найдена.")
        channel_name = inter.author.display_name.lower().replace(" ", "-")[:80] or f"q-{inter.author.id}"
        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            inter.author: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        for rid in (1423360115335106570, 1127428607606796294):
            role = guild.get_role(rid)
            if role:
                overwrites[role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        ticket_channel = await cat.create_text_channel(name=channel_name, overwrites=overwrites)
        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url="https://cdn.discordapp.com/attachments/1064857845838925865/1544369476475158629/image.png?ex=6a9841a8&is=6a96f028&hm=e2f80206537e8c87820b03cccdb39f120cdc1452055767b4e122f455b3f66e1b&")
        embed2 = disnake.Embed(
            title="Что за вопрос был задан:",
            description=f"> Время: <t:{int(time.time())}:f>",
            color=6776679
        )
        embed2.set_image(url=IMG_STRIPE_TICKETS)
        embed2.add_field(name="> Суть вопроса", value=f"```{question}```")
        await ticket_channel.send(content=f"<@&1423360115335106570> - задан вопрос!",
                                  embeds=[embed1, embed2], view=QuestionTicketView())
        await inter.edit_original_response(content=f"✅ Ваш вопрос создан: {ticket_channel.mention}")
        await log_discord(
            title="❓ Новый вопрос",
            description=f"> **Юзер:** {inter.author.mention}\n> **Канал:** {ticket_channel.mention}",
            color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )


class QuestionTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="ㅤКак правильно задать вопрос?ㅤ", style=disnake.ButtonStyle.gray,
                       custom_id="question:howto", emoji=PartialEmoji(name="pravil", id=1544388874497687622), row=0)
    async def howto(self, button, inter):
        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1544387485684203682/image.png?ex=6a98526d&is=6a9700ed&hm=e6eb0b7ec153c23c7d63cb3fe64a405c56dee64cc9edbe9792cd69bfe7e4fe3b&")
        embed2 = disnake.Embed(
            title="Как правильно задать вопрос?",
            description=(
                "> Чтобы правильно задать вопрос — сформулируй чётко, кратко, без подсказок.\n\n"
                "`Определите цель:` Поймите, какая информация нужна.\n"
                "`Говорите просто:` Без сложных терминов.\n"
                "`Избегайте наводок:` Не подталкивай к нужному ответу.\n"
                "`Открытые вопросы:` «что», «как» и т.д.\n"
                "`Контекст:` Опиши проблему, что сделал, что ожидал."
            ),
            color=6776679
        )
        embed2.set_image(url=IMG_STRIPE_TICKETS)
        await inter.response.send_message(embeds=[embed1, embed2])

    @disnake.ui.button(label="ㅤㅤЗакрытьㅤㅤ", style=disnake.ButtonStyle.gray,
                       custom_id="question:close", emoji=PartialEmoji(name="OffTicket", id=1539657125716824185), row=0)
    async def close(self, button, inter):
        if not any(r.id == 1423360115335106570 for r in inter.author.roles) and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.send_message("Закрывается...", ephemeral=True)
        await asyncio.sleep(1)
        channel = inter.channel
        try:
            await channel.delete()
        except:
            pass


# ============================================================
# ПЕРЕИМЕНОВАНИЕ ТИКЕТА
# ============================================================
class RenameTicketModal(Modal):
    def __init__(self):
        components = [TextInput(label="Новое название", placeholder="Например: Дискорд-нитро-1м",
                                custom_id="new_name", min_length=2, max_length=80)]
        super().__init__(title="✏️ Изменение названия тикета", components=components, custom_id="rename_ticket_modal")

    async def callback(self, inter):
        new_raw = inter.text_values["new_name"].strip()
        new_name = new_raw.lower().replace(" ", "-")
        new_name = re.sub(r"[^a-zа-яё0-9\-_]", "", new_name)[:80]
        if not new_name:
            return await inter.response.send_message("❌ Введите корректное название.", ephemeral=True)
        channel = inter.channel
        old_name = channel.name
        try:
            await channel.edit(name=new_name)
        except Exception as e:
            return await inter.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)
        try:
            await channel.send(content=f"> **Тикет переименован** — новый заказ: **{new_raw}**")
        except:
            pass
        await inter.response.send_message(f"✅ Название: `{old_name}` → `{new_name}`.", ephemeral=True)
        await log_discord(
            title="✏️ Название тикета изменено",
            description=f"> **Юзер:** {inter.author.mention}\n> **Тикет:** {channel.mention}\n> **Было:** `{old_name}`\n> **Стало:** `{new_name}`",
            color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )


class TicketActionSelect(disnake.ui.StringSelect):
    def __init__(self):
        super().__init__(
            placeholder="Выберите действие...", min_values=1, max_values=1,
            options=[
                disnake.SelectOption(label="Счет на оплату", description="Сгенерировать счёт",
                                     emoji="<:Rekvi:1539656975091105892>", value="requisites"),
                disnake.SelectOption(label="Политика", description="Правила магазина",
                                     emoji="<:Politic:1539657020695650384>", value="policy"),
                disnake.SelectOption(label="Изменить название тикета", description="Для удобства",
                                     emoji="<:image:1550869363266027641>", value="rename"),
            ],
            custom_id="ticket_action_select"
        )

    async def callback(self, inter):
        value = inter.data.values[0]
        if value == "requisites":
            if not any(r.id == 1154757071330365490 for r in inter.author.roles):
                return await inter.response.send_message("⛔ Только для менеджеров.", ephemeral=True)
            await inter.response.send_modal(InvoiceModal())
        elif value == "policy":
            await self.send_policy(inter)
        elif value == "rename":
            if not _is_paid_ticket(inter.channel):
                return await inter.response.send_message(
                    "⛔ Только для оплаченных тикетов.", ephemeral=True)
            assigned_manager_id = get_ticket_manager(inter.channel.id)
            is_admin = has_admin_command_roles(inter.author)
            if not is_admin:
                if assigned_manager_id is None:
                    return await inter.response.send_message("⛔ Менеджер ещё не назначен.", ephemeral=True)
                if inter.author.id != assigned_manager_id:
                    return await inter.response.send_message(
                        f"⛔ Менеджер: <@{assigned_manager_id}>", ephemeral=True)
            await inter.response.send_modal(RenameTicketModal())

    async def send_policy(self, inter):
        policy_path = os.path.join(CATALOG_DIR, "menu_policy.json")
        try:
            if not os.path.exists(policy_path):
                return await inter.response.send_message("❌ Файл не найден.", ephemeral=True)
            with open(policy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.send_message(embeds=embeds)
            await log_discord(
                title="📜 Просмотр политики",
                description=f"> **Юзер:** {inter.author.mention}",
                color=0x00ff00, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        except Exception as e:
            logger.exception("policy error: %s", e)
            await inter.response.send_message("❌ Ошибка.", ephemeral=True)


class SelectView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketActionSelect())


# ============================================================
# СЧЁТ
# ============================================================
class InvoiceModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Товар / Услуга", placeholder="Discord Nitro 1 Month",
                      custom_id="product", min_length=2, max_length=80),
            TextInput(label="Сумма", placeholder="445", custom_id="amount",
                      min_length=1, max_length=10),
            TextInput(label="Скидка % (опц.)", placeholder="10", custom_id="discount",
                      required=False, max_length=3),
        ]
        super().__init__(title="Создание счёта", components=components, custom_id="invoice_modal")

    async def callback(self, inter):
        await inter.response.defer(ephemeral=True)
        import asyncio as _asyncio
        from modules.receipt import generate_receipt_png, generate_receipt_id

        product_name = inter.text_values["product"].strip()
        amount_str = inter.text_values["amount"].strip()
        discount_str = inter.text_values.get("discount", "").strip()

        if not amount_str.isdigit():
            return await inter.edit_original_response(content="❌ Сумма — число.")
        amount = int(amount_str)
        if amount <= 0:
            return await inter.edit_original_response(content="❌ >0.")

        discount_percent = 0
        if discount_str:
            if not discount_str.isdigit():
                return await inter.edit_original_response(content="❌ Скидка — число.")
            discount_percent = int(discount_str)
            if discount_percent < 0 or discount_percent > 100:
                return await inter.edit_original_response(content="❌ 0-100%.")

        manager_id = get_ticket_manager(inter.channel.id)
        manager = inter.guild.get_member(manager_id) if manager_id else None
        manager_name = str(manager) if manager else "—"

        owner_id = get_ticket_owner(inter.channel.id)
        owner = inter.guild.get_member(owner_id) if owner_id else None
        customer_name = owner.display_name if owner else inter.channel.name

        order_id = generate_receipt_id()
        buf = await _asyncio.to_thread(
            generate_receipt_png,
            manager_name=manager_name, customer_name=customer_name,
            product_name=product_name, amount=amount,
            discount_percent=discount_percent, order_id=order_id
        )
        total = amount - int(amount * discount_percent / 100)
        file = disnake.File(buf, filename=f"receipt_{order_id}.png")
        embed = disnake.Embed(title=f"Счёт для оплаты создан: к оплате {total} Р", color=6776679)
        embed.set_image(url=f"attachment://receipt_{order_id}.png")
        await inter.channel.send(embed=embed, file=file)
        await inter.edit_original_response(content="✅ Счёт отправлен.")
        await log_discord(
            title="🧾 Создан счёт",
            description=f"> **Менеджер:** {inter.author.mention}\n> **Товар:** {product_name}\n> **Сумма:** {amount} Р\n> **Итого:** {total} Р",
            color=0x00aaff, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )


# ============================================================
# ПРОМОКОД
# ============================================================
class PromoCodeModal(Modal):
    def __init__(self, original_view):
        self.original_view = original_view
        components = [TextInput(label="Промокод", placeholder="Введите код",
                                custom_id="promo_code", min_length=1, max_length=50)]
        super().__init__(title="🎟️ Ввод промокода", components=components, custom_id="promo_code_modal")

    async def callback(self, inter):
        code = inter.text_values["promo_code"].strip().upper()
        codes = get_promo_codes()
        if code not in codes:
            return await inter.response.send_message("❌ Промокод не найден.", ephemeral=True)
        value = codes[code]
        channel = inter.channel
        target_msg = None
        async for msg in channel.history(limit=50):
            if msg.author == inter.bot.user and msg.embeds and len(msg.embeds) >= 2:
                target_msg = msg
                break
        if not target_msg:
            return await inter.response.send_message("❌ Не найдено сообщение с заказом.", ephemeral=True)
        embed_dict = target_msg.embeds[1].to_dict()
        for field in embed_dict.get("fields", []):
            if "скидка" in field.get("name", "").lower():
                field["value"] = f"```{code} — {value}```"
                break
        new_embed = disnake.Embed.from_dict(embed_dict)
        embeds = list(target_msg.embeds)
        embeds[1] = new_embed
        await target_msg.edit(embeds=embeds)
        try:
            for child in self.original_view.children:
                child.disabled = True
            await inter.message.edit(view=self.original_view)
        except:
            pass
        await inter.response.send_message(f"✅ Промокод **{code}** активирован!\n> Скидка: `{value}`", ephemeral=True)


# ============================================================
# ЗАКРЫТИЕ / ОЦЕНКА
# ============================================================
class TicketRatingView(View):
    def __init__(self):
        super().__init__(timeout=None)
        btn_rate = Button(label="ㅤОценить работу менеджераㅤ", style=ButtonStyle.gray,
                          custom_id="ticket:rate_manager", emoji=PartialEmoji(name="Otziv", id=1541808692314243172), row=0)
        btn_rate.callback = self.rate_callback
        self.add_item(btn_rate)

        btn_close = Button(label="ㅤЗакрыть заказㅤ", style=ButtonStyle.gray,
                           custom_id="ticket:close_order", emoji=PartialEmoji(name="OffTicket", id=1539657125716824185), row=0)
        btn_close.callback = self.close_callback
        self.add_item(btn_close)

    async def rate_callback(self, inter):
        channel = inter.channel
        user_id = get_ticket_owner(channel.id)
        if user_id and inter.author.id != user_id:
            return await inter.response.send_message("⛔ Только владелец.", ephemeral=True)
        manager_id = get_ticket_manager(channel.id)
        if not manager_id:
            return await inter.response.send_message("❌ Менеджер не назначен.", ephemeral=True)
        await inter.response.send_modal(RatingModal(channel, manager_id))

    async def close_callback(self, inter):
        channel = inter.channel
        user_id = get_ticket_owner(channel.id)
        if user_id and inter.author.id != user_id and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Только владелец/админ.", ephemeral=True)
        await inter.response.send_message("Закрывается...", ephemeral=True)
        await asyncio.sleep(3)
        try:
            manager_id = get_ticket_manager(channel.id)
            if manager_id and _is_paid_ticket(channel):
                increment_manager_closed(manager_id)
                add_closed_order(manager_id, channel.id)
            clear_ticket_owner(channel)
            await channel.delete()
            from modules.commands_panels import send_manager_top
            await send_manager_top()
        except Exception as e:
            logger.error(f"close error: {e}")


class RatingModal(Modal):
    def __init__(self, channel, manager_id):
        self.channel = channel
        self.manager_id = manager_id
        components = [TextInput(label="Оценка 1-5", placeholder="5", custom_id="rating",
                                min_length=1, max_length=1)]
        super().__init__(title="Оценка менеджера", components=components)

    async def callback(self, inter):
        r = inter.text_values["rating"].strip()
        if not r.isdigit() or int(r) < 1 or int(r) > 5:
            return await inter.response.send_message("❌ 1-5.", ephemeral=True)
        rating = int(r)
        if self.manager_id:
            add_manager_rating(self.manager_id, rating)
            await inter.response.send_message(f"✅ Оценка {rating}/5 сохранена.", ephemeral=True)
            from modules.commands_panels import send_manager_top
            await send_manager_top()


# ============================================================
# ОСНОВНОЙ TICKET VIEW
# ============================================================
class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

        btn_close = Button(label="ㅤЗакрытьㅤ", style=ButtonStyle.gray,
                           custom_id="ticket:close", emoji=PartialEmoji(name="OffTicket", id=1539657125716824185), row=0)
        btn_close.callback = self.close_callback
        self.add_item(btn_close)

        btn_pay = Button(label="ㅤОплатитьㅤ", style=ButtonStyle.gray,
                         custom_id="ticket:pay", emoji=PartialEmoji(name="Oplacheno", id=1539657164778512496), row=0)
        btn_pay.callback = self.pay_callback
        self.add_item(btn_pay)

        btn_discounts = Button(label="ㅤㅤСкидкиㅤㅤ", style=ButtonStyle.gray,
                               custom_id="ticket:discounts", emoji=PartialEmoji(name="skidka", id=1540819242625146961), row=0)
        btn_discounts.callback = self.discounts_callback
        self.add_item(btn_discounts)

    async def close_callback(self, inter):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        channel = inter.channel
        manager_id = get_ticket_manager(channel.id)
        if manager_id and inter.author.id != manager_id and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Другой менеджер.", ephemeral=True)
        owner_id = get_ticket_owner(channel.id)
        if not owner_id:
            await inter.response.send_message("Закрывается...", ephemeral=True)
            await asyncio.sleep(3)
            try:
                clear_ticket_owner(channel)
                await channel.delete()
                from modules.commands_panels import send_manager_top
                await send_manager_top()
            except:
                pass
        else:
            await self.send_rating_embed(inter)

    async def send_rating_embed(self, inter):
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
            description=f"> {user_mention}, заказ выполнен! Оставьте отзыв в <#1462074763437543435>.\n\n"
                        f"> Тикет обработал менеджер {manager_mention}. Можно дать оценку по кнопке ниже.",
            color=6776679
        )
        embed2.set_image(url=IMG_STRIPE_TICKETS)
        view = TicketRatingView()
        await channel.send(embeds=[embed1, embed2], view=view)

    async def pay_callback(self, inter):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        channel = inter.channel
        manager_id = get_ticket_manager(channel.id)
        if manager_id and inter.author.id != manager_id and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Другой менеджер.", ephemeral=True)
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
            return await inter.response.send_message("Уже оплачен.", ephemeral=True)
        ed = msg.embeds[1].to_dict()
        ed["color"] = 0x676767
        ed["description"] = (
            f"Статус - Заказ оплачен\n"
            f"> Подтверждено: {inter.author.mention}\n"
            f"> Время: <t:{int(time.time())}:f>"
        )
        paid_view = TicketPaidView()
        await msg.edit(embeds=[msg.embeds[0], disnake.Embed.from_dict(ed)], view=paid_view)
        paid_category = inter.guild.get_channel(CONFIG["PAID_CATEGORY_ID"])
        if paid_category:
            await channel.edit(category=paid_category)
        embed = disnake.Embed(title="💚 Заказ оплачен", description=f"> **Подтвердил:** {inter.author.mention}", color=0x2ecc71)
        embed.set_image(url=IMG_STRIPE_TICKETS)
        await channel.send(embed=embed)
        await inter.response.send_message("✅ Отмечено.", ephemeral=True)
        await log_discord(
            title="💰 Заказ оплачен",
            description=f"> **Канал:** {channel.mention}\n> **Подтвердил:** {inter.author.mention}",
            color=0x2ecc71, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    async def discounts_callback(self, inter):
        channel = inter.channel
        owner_id = get_ticket_owner(channel.id)
        if not owner_id or inter.author.id != owner_id:
            return await inter.response.send_message("⛔ Только владелец.", ephemeral=True)
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
            return await inter.response.send_message("❌ Скидка уже применена.", ephemeral=True)
        all_purchases = await get_user_purchases(inter.author.id, only_unused=True)
        discounts = [p for p in all_purchases if p.get('type') == 'discounts']
        slid_embeds = _load_slid_embeds() or [disnake.Embed(title="📦 Ваши скидки", color=6776679)]
        view = View(timeout=300)
        btn_promo = Button(label="Ввести промокод", style=ButtonStyle.gray,
                           custom_id=f"promo_input_{inter.author.id}",
                           emoji=PartialEmoji(name="prom1", id=1539646792139014234), row=0)

        async def promo_callback(inter2, _view=view):
            if inter2.author.id != inter.author.id:
                return await inter2.response.send_message("⛔ Не ваш тикет.", ephemeral=True)
            await inter2.response.send_modal(PromoCodeModal(original_view=_view))

        btn_promo.callback = promo_callback
        view.add_item(btn_promo)
        current_row = 0
        current_col = 1
        for idx, p in enumerate(discounts):
            if current_col >= 3:
                current_row += 1
                current_col = 0
            label = p['value']
            if len(label) > 80:
                label = label[:77] + "..."
            btn = Button(label=label, style=ButtonStyle.gray,
                         custom_id=f"apply_discount_{inter.author.id}_{idx}", row=current_row)
            btn.callback = self.create_discount_callback(idx, inter, discounts)
            view.add_item(btn)
            current_col += 1
        await inter.response.send_message(embeds=slid_embeds, view=view, ephemeral=True)

    def create_discount_callback(self, discount_index, original_inter, discounts):
        async def callback(inter):
            if inter.author.id != original_inter.author.id:
                return await inter.response.send_message("⛔ Не ваш товар.", ephemeral=True)
            if discount_index >= len(discounts):
                return await inter.response.send_message("❌ Уже применена.", ephemeral=True)
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
                return await inter.response.send_message("❌ Уже применена.", ephemeral=True)
            item_value = discounts[discount_index]['value']
            full = await get_user_purchases(inter.author.id, only_unused=False)
            target_index = None
            for i, p in enumerate(full):
                if p['value'] == item_value and p.get('type') == 'discounts' and not p.get('used'):
                    target_index = i
                    break
            if target_index is None:
                return await inter.response.send_message("❌ Не найдена.", ephemeral=True)
            ok = await remove_purchase(inter.author.id, target_index)
            if not ok:
                return await inter.response.send_message("❌ Ошибка.", ephemeral=True)
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
            await inter.response.send_message(f"✅ Скидка **{item_value}** применена!", ephemeral=True)
        return callback


class TicketPaidView(View):
    def __init__(self):
        super().__init__(timeout=None)
        btn_close = Button(label="ㅤЗакрытьㅤ", style=ButtonStyle.gray,
                           custom_id="ticket_paid:close", emoji=PartialEmoji(name="OffTicket", id=1539657125716824185), row=0)
        btn_close.callback = self.close_callback
        self.add_item(btn_close)
        btn_pay = Button(label="ㅤОплатитьㅤ", style=ButtonStyle.gray,
                         custom_id="ticket_paid:pay_done", emoji=PartialEmoji(name="Oplacheno", id=1539657164778512496), row=0, disabled=True)
        self.add_item(btn_pay)
        btn_discounts = Button(label="ㅤㅤСкидкиㅤㅤ", style=ButtonStyle.gray,
                               custom_id="ticket_paid:discounts_done", emoji=PartialEmoji(name="skidka", id=1540819242625146961), row=0, disabled=True)
        self.add_item(btn_discounts)

    async def close_callback(self, inter):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        channel = inter.channel
        manager_id = get_ticket_manager(channel.id)
        if manager_id and inter.author.id != manager_id and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Другой менеджер.", ephemeral=True)
        owner_id = get_ticket_owner(channel.id)
        if not owner_id:
            await inter.response.send_message("Закрывается...", ephemeral=True)
            await asyncio.sleep(3)
            try:
                manager_id = get_ticket_manager(channel.id)
                if manager_id and _is_paid_ticket(channel):
                    increment_manager_closed(manager_id)
                    add_closed_order(manager_id, channel.id)
                clear_ticket_owner(channel)
                await channel.delete()
                from modules.commands_panels import send_manager_top
                await send_manager_top()
            except:
                pass
        else:
            owner = channel.guild.get_member(owner_id)
            manager = channel.guild.get_member(manager_id) if manager_id else None
            user_mention = owner.mention if owner else f"<@{owner_id}>"
            manager_mention = manager.mention if manager else "Не назначен"
            embed1 = disnake.Embed(color=6776679)
            embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1541805596842664017/image.png?ex=6a8eeddb&is=6a8d9c5b&hm=bd497621b27b7c095b9b6cd3af8fa2d5135f68ad247ca03a2e3305c4350107e7&")
            embed2 = disnake.Embed(
                title="Отзыв после выполнения товара.\n",
                description=f"> {user_mention}, заказ выполнен! Оставьте отзыв в <#1462074763437543435>.\n\n"
                            f"> Тикет обработал менеджер {manager_mention}.",
                color=6776679
            )
            embed2.set_image(url=IMG_STRIPE_TICKETS)
            view = TicketRatingView()
            await channel.send(embeds=[embed1, embed2], view=view)


class CoinsTicketButtons(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="ㅤПолитика выполнения заказаㅤ", style=disnake.ButtonStyle.gray,
                       custom_id="coins_ticket:policy",
                       emoji=PartialEmoji(name="Politic", id=1539657020695650384), row=0)
    async def policy(self, button, inter):
        policy_path = os.path.join(CATALOG_DIR, "menu_policy.json")
        try:
            with open(policy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.send_message(embeds=embeds)
        except Exception as e:
            logger.exception("policy error: %s", e)
            await inter.response.send_message("❌ Ошибка.", ephemeral=True)

    @disnake.ui.button(label="ㅤㅤЗакрытьㅤㅤ", style=disnake.ButtonStyle.gray,
                       custom_id="coins_ticket:close",
                       emoji=PartialEmoji(name="OffTicket", id=1539657125716824185), row=0)
    async def close(self, button, inter):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        channel = inter.channel
        manager_id = get_ticket_manager(channel.id)
        if manager_id and inter.author.id != manager_id and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Другой менеджер.", ephemeral=True)
        owner_id = get_ticket_owner(channel.id)
        if not owner_id:
            await inter.response.send_message("Закрывается...", ephemeral=True)
            await asyncio.sleep(3)
            try:
                clear_ticket_owner(channel)
                await channel.delete()
                from modules.commands_panels import send_manager_top
                await send_manager_top()
            except:
                pass
        else:
            owner = channel.guild.get_member(owner_id)
            manager = channel.guild.get_member(manager_id) if manager_id else None
            user_mention = owner.mention if owner else f"<@{owner_id}>"
            manager_mention = manager.mention if manager else "Не назначен"
            embed1 = disnake.Embed(color=6776679)
            embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1541805596842664017/image.png?ex=6a8eeddb&is=6a8d9c5b&hm=bd497621b27b7c095b9b6cd3af8fa2d5135f68ad247ca03a2e3305c4350107e7&")
            embed2 = disnake.Embed(
                title="Отзыв после выполнения товара.\n",
                description=f"> {user_mention}, заказ выполнен!",
                color=6776679
            )
            embed2.set_image(url=IMG_STRIPE_TICKETS)
            view = TicketRatingView()
            await channel.send(embeds=[embed1, embed2], view=view)


# ============================================================
# КАТАЛОГ
# ============================================================
class CatalogTypeSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="Реальные деньги", description="₽, USDT и т.д.",
                                 emoji="<:realmomne:1539649281575620618>", value="real"),
            disnake.SelectOption(label="Diamond Coin-ы", description="Внутренняя валюта",
                                 emoji="<:coins:1539649259245408340>", value="coins"),
        ]
        super().__init__(placeholder="Выберите тип товаров...", min_values=1, max_values=1,
                         options=options, custom_id="catalog_type_select")

    async def callback(self, inter):
        value = inter.data.values[0]
        if value == "real":
            embed = disnake.Embed(color=6776679, title="Выбор для покупки в каталоге",
                                  description="Ниже представлены категории.")
            embed.set_image(url=IMG_STRIPE_TICKETS)
            await inter.response.send_message(embed=embed, view=CatalogView(), ephemeral=True)
        elif value == "coins":
            await inter.response.send_message("Выберите категорию:", ephemeral=True, view=BuySelectView())


class CatalogTypeView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CatalogTypeSelect())


CATALOG_OPTIONS = [
    {"label": "・BuyAll", "description": "Покупка всего",
     "emoji": "<:buyall:1489833017047253032> ", "json_path": os.path.join(CATALOG_DIR, "menu_buyall.json")},
    {"label": "・Discord", "description": "Nitro и Boosts",
     "emoji": "<:Discord:1464831837300854936>", "json_path": os.path.join(CATALOG_DIR, "menu_discord.json")},
    {"label": "・Steam", "description": "Пополнение и очки",
     "emoji": "<:Steam:1464833200416100402>", "json_path": os.path.join(CATALOG_DIR, "menu_steam.json")},
    {"label": "・Telegram", "description": "Звёзды и подарки",
     "emoji": "<:Telegram:1465720888677896314>", "json_path": os.path.join(CATALOG_DIR, "menu_telegram.json")},
    {"label": "・Украшение Discord", "description": "Украшения и бейджи",
     "emoji": "<:Decoration:1465729329290936403>", "json_path": os.path.join(CATALOG_DIR, "menu_decoration.json")},
    {"label": "・Roblox", "description": "Робуксы и Plus",
     "emoji": "<:Roblox:1465752155251150911>", "json_path": os.path.join(CATALOG_DIR, "menu_roblox.json")},
    {"label": "・Epic Games", "description": "Fortnite и услуги",
     "emoji": "<:EpicGames:1465765441887797248>", "json_path": os.path.join(CATALOG_DIR, "menu_epic.json")},
    {"label": "・Supercell", "description": "Brawl Stars и Clash Royale",
     "emoji": "<:SuperCell:1465768886484996260>", "json_path": os.path.join(CATALOG_DIR, "menu_supercell.json")},
    {"label": "・Spotify", "description": "Подписка на музыку",
     "emoji": "<:Spotify:1465770796411785330>", "json_path": os.path.join(CATALOG_DIR, "menu_spotify.json")},
    {"label": "・Дизайн", "description": "Дизайн от Diamond",
     "emoji": "<:Design:1465771436580012106>", "json_path": os.path.join(CATALOG_DIR, "menu_design.json")},
    {"label": "・Бот для Дискорда", "description": "Бот под ключ",
     "emoji": "<:Bot:1465771816080380109>", "json_path": os.path.join(CATALOG_DIR, "menu_bot.json")},
]


class CatalogSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [disnake.SelectOption(label=item["label"], description=item["description"],
                                        emoji=item["emoji"], value=item["json_path"])
                   for item in CATALOG_OPTIONS]
        super().__init__(placeholder="Выберите категорию...", min_values=1, max_values=1,
                         options=options, custom_id="catalog_select")

    async def callback(self, inter):
        json_path = self.values[0]
        try:
            if not os.path.exists(json_path):
                return await inter.response.send_message("❌ Файл не найден.", ephemeral=True)
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.send_message(embeds=embeds, ephemeral=True)
        except Exception as e:
            logger.exception("CatalogSelect error: %s", e)


class CatalogView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CatalogSelect())


# ============================================================
# КАТАЛОГ DC + НОВЫЕ КАТЕГОРИИ
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
        select = Select(placeholder="Выберите категорию...", options=options, custom_id="buy_category")
        select.callback = self.category_callback
        self.add_item(select)

    async def category_callback(self, inter):
        await inter.response.defer(ephemeral=True)
        category = inter.data.values[0]
        catalog = load_shop_catalog()
        items = catalog.get(category, {}).get("items", {})
        if not items:
            return await inter.edit_original_response(content="❌ В категории пока нет товаров.")
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
        await inter.edit_original_response(content="Выберите товар:", view=view)

    async def item_callback(self, inter):
        await inter.response.defer(ephemeral=True)
        value = inter.data.values[0]
        try:
            category, item_key = value.split("_", 1)
        except ValueError:
            return await inter.edit_original_response(content="❌ Ошибка товара.")
        catalog = load_shop_catalog()
        item = catalog.get(category, {}).get("items", {}).get(item_key)
        if not item:
            return await inter.edit_original_response(content="❌ Товар не найден.")

        if category in ("boosts", "casino"):
            await self.process_boosts_item(inter, category, item_key, item)
            return

        if category == "gifts":
            await inter.response.send_modal(GiftRecipientModal(item, category))
            return

        if category == "discounts":
            await self.process_discount_direct(inter, item_key, item)
            return

        embed = disnake.Embed(
            title="🛒 Информация о товаре:",
            description=(
                f"> **Название:** {item['name']}\n\n"
                f"> **Описание:** {item['description']}\n\n"
                "Как покупаем:"
            ),
            color=6776679
        )
        embed.set_image(url=IMG_STRIPE_TICKETS)

        select = Select(
            placeholder="Как купить товар?",
            min_values=1, max_values=1,
            options=[
                SelectOption(label="Купить себе", description="Для себя",
                             emoji="<:people:1538395694648529009>", value="self"),
                SelectOption(label="Подарить товар", description="Для другого",
                             emoji="<:gist:1541657784926339153>", value="gift"),
            ],
            custom_id="buy_way_select"
        )
        select.callback = self.create_select_callback(inter, category, item_key, item)
        view = View(timeout=300)
        view.add_item(select)
        await inter.edit_original_response(content=None, embed=embed, view=view)

    async def process_boosts_item(self, inter, category, item_key, item):
        user_id = inter.author.id
        price = item["price"]

        can, reason = can_activate(user_id, item_key)
        if not can:
            return await inter.edit_original_response(content=reason)

        balance = await get_user_balance(user_id)
        if balance < price:
            return await inter.edit_original_response(
                content=f"❌ Недостаточно DC. Нужно: **{price}**, у вас: **{balance}**."
            )

        success = await remove_dc(user_id, price, f"Покупка: {item['name']}")
        if not success:
            return await inter.edit_original_response(content="❌ Ошибка списания DC.")

        if item_key == "casino_jackpot_ticket":
            add_jackpot_bank(price)

        item_with_cat = {**item, "_category": category}
        result_text = await do_activate(user_id, item_key, item_with_cat)

        ttl = ""
        if item.get("duration_hours", 0) > 0:
            ttl = f"{item['duration_hours']}ч"
        elif item.get("uses", -1) > 0:
            ttl = f"{item['uses']} исп."

        embed = disnake.Embed(
            title="✅ Активировано!",
            description=(
                f"> **{item['name']}**\n"
                f"> {item['description']}\n\n"
                f"> {result_text}\n"
                f"> **Списано:** `{price} DC`"
            ),
            color=0x2ecc71
        )
        embed.set_image(url=IMG_STRIPE_TICKETS)
        await inter.edit_original_response(content=None, embed=embed)

        await log_discord(
            title="⚡ Активация товара",
            description=f"> **Юзер:** {inter.author.mention}\n> **Товар:** {item['name']}\n> **Цена:** {price} DC\n> **TTL:** {ttl or 'мгновенно'}",
            color=0x00aaff
        )

    async def process_discount_direct(self, inter, item_key, item):
        user_id = inter.author.id
        price = item["price"]

        balance = await get_user_balance(user_id)
        if balance < price:
            return await inter.edit_original_response(
                content=f"❌ Недостаточно DC. Нужно: **{price}**, у вас: **{balance}**."
            )

        success = await remove_dc(user_id, price, f"Покупка скидки: {item['name']}")
        if not success:
            return await inter.edit_original_response(content="❌ Ошибка списания DC.")

        await add_purchase(user_id, "discounts", item["name"])

        embed = disnake.Embed(
            title="✅ Скидка куплена!",
            description=(
                f"> **{item['name']}**\n"
                f"> {item['description']}\n\n"
                f"> Активируйте в тикете по кнопке **«Скидки»**\n"
                f"> **Списано:** `{price} DC`"
            ),
            color=0x2ecc71
        )
        embed.set_image(url=IMG_STRIPE_TICKETS)
        await inter.edit_original_response(content=None, embed=embed)

        await log_discord(
            title="🛒 Куплена скидка",
            description=f"> **Юзер:** {inter.author.mention}\n> **Товар:** {item['name']}\n> **Цена:** {price} DC",
            color=0x00aaff
        )

    def create_select_callback(self, original_inter, category, item_key, item):
        async def callback(inter):
            if inter.author.id != original_inter.author.id:
                return await inter.response.send_message("⛔ Не ваш выбор.", ephemeral=True)
            value = inter.data.values[0]
            if value == "self":
                await self.process_buy(inter, category, item_key, item, None)
            elif value == "gift":
                await inter.response.send_modal(GiftRecipientModal(item, category))
        return callback

    async def process_buy(self, inter, category, item_key, item, recipient_id=None):
        user_id = inter.author.id if recipient_id is None else recipient_id
        price = item["price"]
        balance = await get_user_balance(inter.author.id)
        if balance < price:
            return await inter.response.send_message(f"❌ Мало DC. Нужно **{price}**, у вас **{balance}**.", ephemeral=True)

        if category == "roles" and item.get("role_id"):
            role = inter.guild.get_role(item["role_id"])
            if role and role in inter.author.roles:
                return await inter.response.send_message(f"❌ У вас уже есть **{role.name}**.", ephemeral=True)

        success = await remove_dc(inter.author.id, price, f"Покупка: {item['name']}" + (f" (подарок <@{recipient_id}>)" if recipient_id else ""))
        if not success:
            return await inter.response.send_message("❌ Ошибка списания.", ephemeral=True)

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
                            f"✅ Роль **{item['name']}** куплена и выдана {target_member.mention}!\n"
                            f"📝 Отзыв: <#1462074763437543435>.",
                            ephemeral=True
                        )
                        return
                except Exception as e:
                    await add_dc(inter.author.id, price, "Возврат (ошибка роли)")
                    return await inter.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

        if recipient_id:
            await inter.response.send_message(
                f"✅ Вы купили **{item['name']}** и подарили <@{recipient_id}>!",
                ephemeral=True
            )
        else:
            await inter.response.send_message(
                f"✅ Вы купили **{item['name']}** за **{price} DC**!\n"
                f"📝 Отзыв: <#1462074763437543435>.",
                ephemeral=True
            )

    async def back_callback(self, inter):
        await inter.response.defer(ephemeral=True)
        await inter.edit_original_response(content="Выберите категорию:", view=BuySelectView())


# ============================================================
# МОДАЛКА ПОДАРКА
# ============================================================
class GiftRecipientModal(Modal):
    def __init__(self, item, category):
        self.item = item
        self.category = category
        components = [TextInput(label="ID получателя", placeholder="Число (ID юзера)",
                                custom_id="recipient_id", min_length=15, max_length=25)]
        super().__init__(title="🎁 Подарить", components=components)

    async def callback(self, inter):
        user_id = inter.author.id
        price = self.item["price"]
        amount = self.item.get("gift_amount")

        rid_str = inter.text_values["recipient_id"].strip()
        if not rid_str.isdigit():
            return await inter.response.send_message("❌ ID — число.", ephemeral=True)
        recipient_id = int(rid_str)

        if recipient_id == user_id:
            return await inter.response.send_message("❌ Нельзя самому себе.", ephemeral=True)

        if self.category == "gifts":
            balance = await get_user_balance(user_id)
            if balance < price:
                return await inter.response.send_message(
                    f"❌ Мало DC. Нужно **{price}**, у вас **{balance}**.", ephemeral=True)
            ok = await remove_dc(user_id, price, f"Подарок {amount} DC → {recipient_id}")
            if not ok:
                return await inter.response.send_message("❌ Ошибка списания.", ephemeral=True)
            success, msg = await process_gift_dc(inter.author, recipient_id, amount, price)
            await inter.response.send_message(("✅ " if success else "❌ ") + msg, ephemeral=True)
            return

        view = BuySelectView()
        catalog = load_shop_catalog()
        real_key = "unknown"
        for cat_key, cat_data in catalog.items():
            for k, v in cat_data.get("items", {}).items():
                if v.get("name") == self.item.get("name"):
                    real_key = k
                    break
        await view.process_buy(inter, self.category, real_key, self.item, recipient_id)


# ============================================================
# ПАНЕЛЬ ТИКЕТОВ
# ============================================================
class TicketPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="ㅤㅤКупитьㅤㅤ", style=disnake.ButtonStyle.gray,
                       custom_id="panel:buy", emoji=PartialEmoji(name="shopg", id=1539646815530651718))
    async def buy(self, button, inter):
        embed = disnake.Embed(color=6776679, title="Выбор категории по оплате",
                              description="В какой валюте купить? Если вопрос — выбери пункт ниже.")
        embed.set_image(url=IMG_STRIPE_TICKETS)
        view = BuyTypeView()
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)

    @disnake.ui.button(label="ㅤПромокодыㅤ", style=disnake.ButtonStyle.gray,
                       custom_id="panel:promo", emoji=PartialEmoji(name="prom1", id=1539646792139014234))
    async def promo(self, button, inter):
        await inter.response.send_message(
            "🎟️ Промокоды: <#1462070136856117258>", ephemeral=True)

    @disnake.ui.button(label="ㅤКаталогㅤ", style=disnake.ButtonStyle.gray,
                       custom_id="panel:catalog", emoji=PartialEmoji(name="catal", id=1539646769053306980))
    async def catalog(self, button, inter):
        embed = disnake.Embed(title="Выбор категории товаров",
                              description="Выберите метод ниже.", color=6776679)
        embed.set_image(url=IMG_STRIPE_TICKETS)
        view = CatalogTypeView()
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)


async def handle_interaction(inter):
    pass
