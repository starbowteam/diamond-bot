# -*- coding: utf-8 -*-
"""
Объединённый модуль служебных панелей и админ-функций.
"""
import os
import json
import io
import re
import time
from datetime import datetime, timezone
from typing import Optional, List

import disnake
from disnake import ButtonStyle, SelectOption, PartialEmoji
from disnake.ui import Button, Modal, Select, TextInput, View
from disnake.ext import commands

from core.utils import (
    CONFIG, FILES, BASE_DIR, DATA_DIR, CATALOG_DIR, ADD_DIR,
    db, cur,
    logger,
    load_json, save_json, now_ts,
    log_discord, log_command,
    has_admin_command_roles,
    clean_embed_for_discohook, parse_emoji,
    get_promo_codes, add_promo_code, remove_promo_code, clear_promo_codes,
    reload_promo,
    get_closed_orders, remove_closed_order,
)
from modules.dc import (
    add_dc, remove_dc,
    get_user_purchases, remove_purchase,
    get_dc_cache, save_dc_cache,
    sync_dc_to_json
)
from modules.commands_profile import load_embed_from_file


STAFF_PANEL_CHANNEL_ID  = 1551276116679860314
HOME_CHANNEL_ID         = 1532398684074016870
TAROLOGY_CHANNEL_ID     = 1536796929873420308
WORK_CHANNEL_ID         = 1532435807242289314
TICKET_PANEL_CHANNEL_ID = 1462136361711829053

IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6ab152a3&is=6ab00123&hm=c5c2963ca1ebbe6eb37f673fcef993cacf375c5a80490205c230d4c4adfe8b58&"


def load_board_embed() -> list:
    path = os.path.join(ADD_DIR, "board.json")
    if not os.path.exists(path):
        return [disnake.Embed(
            title="📋 Доска объявлений",
            description="> Здесь будет важная информация. Пока данных нет.",
            color=6776679
        )]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
    except Exception as e:
        logger.error(f"Ошибка загрузки board.json: {e}")
        return [disnake.Embed(title="❌ Ошибка", description="Не удалось загрузить доску.", color=0xff0000)]


# ============================================================
# ═══ СЕКЦИЯ 1: ЭКОНОМИКА ═══
# ============================================================
promo_codes = get_promo_codes()


def reload_promo_cache():
    global promo_codes
    promo_codes = get_promo_codes()


class DCSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="・Начисление", description="Начисление валюты",
                                 emoji="<:__:1538399607699021895>", value="give"),
            disnake.SelectOption(label="・Списать", description="Снятие валюты",
                                 emoji="<:minus:1538399627521429534>", value="take"),
            disnake.SelectOption(label="・Покупки", description="Ручное управление покупками",
                                 emoji="<:cart:1538399645238165624>", value="purchases"),
        ]
        super().__init__(placeholder="Выберите действие...", min_values=1, max_values=1,
                         options=options, custom_id="dc_select")

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


class DCView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DCSelect())


class GiveDcModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="ID пользователя или @упоминание", custom_id="user",
                      placeholder="Введите ID или @username", min_length=2, max_length=50),
            TextInput(label="Количество DC", custom_id="amount",
                      placeholder="Число", min_length=1, max_length=10),
            TextInput(label="Причина (необязательно)", custom_id="reason", required=False,
                      placeholder="Причина начисления", max_length=200),
        ]
        super().__init__(title="Начислить DC", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        user_input = inter.text_values["user"].strip()
        try:
            amount = int(inter.text_values["amount"].strip())
            if amount <= 0:
                raise ValueError
        except Exception:
            return await inter.response.send_message("❌ Введите корректное количество >0.", ephemeral=True)
        reason = inter.text_values.get("reason", "").strip() or "Начисление через панель"
        user_id = None
        if user_input.isdigit():
            user_id = int(user_input)
        else:
            m = re.search(r'<@!?(\d+)>', user_input)
            if m:
                user_id = int(m.group(1))
        if not user_id:
            return await inter.response.send_message("❌ Не удалось определить пользователя.", ephemeral=True)
        await add_dc(user_id, amount, reason, notify=True)
        await inter.response.send_message(f"✅ Начислено {amount} DC пользователю <@{user_id}>.", ephemeral=True)


class TakeDcModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="ID пользователя или @упоминание", custom_id="user",
                      placeholder="Введите ID или @username", min_length=2, max_length=50),
            TextInput(label="Количество DC", custom_id="amount",
                      placeholder="Число", min_length=1, max_length=10),
            TextInput(label="Причина (необязательно)", custom_id="reason", required=False,
                      placeholder="Причина списания", max_length=200),
        ]
        super().__init__(title="Снять DC", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        user_input = inter.text_values["user"].strip()
        try:
            amount = int(inter.text_values["amount"].strip())
            if amount <= 0:
                raise ValueError
        except Exception:
            return await inter.response.send_message("❌ Введите корректное количество >0.", ephemeral=True)
        reason = inter.text_values.get("reason", "").strip() or "Списание через панель"
        user_id = None
        if user_input.isdigit():
            user_id = int(user_input)
        else:
            m = re.search(r'<@!?(\d+)>', user_input)
            if m:
                user_id = int(m.group(1))
        if not user_id:
            return await inter.response.send_message("❌ Не удалось определить пользователя.", ephemeral=True)
        success = await remove_dc(user_id, amount, reason, notify=True)
        if success:
            await inter.response.send_message(f"✅ Снято {amount} DC у <@{user_id}>.", ephemeral=True)
        else:
            await inter.response.send_message(f"❌ Недостаточно DC у <@{user_id}>.", ephemeral=True)


class ManagePurchasesModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="ID пользователя", custom_id="user_id",
                      placeholder="Введите числовой ID пользователя", min_length=1, max_length=30),
        ]
        super().__init__(title="Управление покупками", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        user_input = inter.text_values["user_id"].strip()
        if not user_input.isdigit():
            return await inter.response.send_message("❌ Введите корректный ID.", ephemeral=True)
        user_id = int(user_input)
        purchases = await get_user_purchases(user_id, only_unused=True)
        if not purchases:
            return await inter.response.send_message(f"❌ У <@{user_id}> нет неиспользованных покупок.", ephemeral=True)
        select = Select(placeholder="Выберите покупку для удаления...", options=[])
        for idx, p in enumerate(purchases):
            label = f"{p['type']} {p['value']}"
            if len(label) > 100:
                label = label[:97] + "..."
            select.options.append(SelectOption(
                label=label, value=str(idx),
                description=f"Дата: {datetime.fromtimestamp(p['date']).strftime('%d.%m.%Y')}"
            ))
        view = View()
        view.add_item(select)

        async def select_callback(inter2: disnake.MessageInteraction):
            idx = int(inter2.data.values[0])
            success = await remove_purchase(user_id, idx)
            if success:
                await inter2.response.send_message("✅ Покупка удалена.", ephemeral=True)
            else:
                await inter2.response.send_message("❌ Ошибка удаления.", ephemeral=True)

        select.callback = select_callback
        await inter.response.send_message(
            f"Выберите покупку <@{user_id}> для удаления:", ephemeral=True, view=view
        )


# ============================================================
# ═══ СЕКЦИЯ 2: ПРОМОКОДЫ ═══
# ============================================================
class PromoSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="・Создать промокод", description="Добавление",
                                 emoji="<:__:1538399607699021895>", value="add"),
            disnake.SelectOption(label="・Удалить промокод", description="Удаление",
                                 emoji="<:minus:1538399627521429534>", value="remove"),
            disnake.SelectOption(label="・Список промокодов", description="Все существующие промокоды",
                                 emoji="<:list:1538400957803798588>", value="list"),
        ]
        super().__init__(placeholder="Выберите действие...", min_values=1, max_values=1,
                         options=options, custom_id="promo_select")

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
            await inter.response.send_message(
                "Выберите промокод для удаления:", ephemeral=True, view=PromoRemoveSelectView()
            )
        elif value == "list":
            reload_promo_cache()
            if not promo_codes:
                await inter.response.send_message("Промокодов нет.", ephemeral=True)
                return
            text = "\n".join([f"{c} → {v}" for c, v in promo_codes.items()])
            await inter.response.send_message(f"```\n{text}\n```", ephemeral=True)


class PromoView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PromoSelect())


class PromoAddModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Код промокода", custom_id="code",
                      placeholder="Например VSEMPROMO25", min_length=2, max_length=50),
            TextInput(label="Скидка (например 10%)", custom_id="value",
                      placeholder="10%", min_length=1, max_length=20),
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
        await log_discord("➕ Промокод добавлен",
                          f"Админ {inter.author.mention} добавил `{code}` → {value}", color=0x00ff00)


class PromoRemoveSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        reload_promo_cache()
        options = []
        if not promo_codes:
            options.append(SelectOption(label="Нет промокодов", value="none", default=True))
        else:
            for code, value in promo_codes.items():
                label = f"{code} - {value}"
                if len(label) > 100:
                    label = label[:97] + "..."
                options.append(SelectOption(label=label, value=code))
        select = Select(placeholder="Выберите промокод для удаления...",
                        options=options, custom_id="promo_remove_select")
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
            await log_discord("➖ Промокод удалён",
                              f"Админ {inter.author.mention} удалил `{code}`", color=0xff6600)
        else:
            await inter.response.send_message("❌ Промокод не найден.", ephemeral=True)


# ============================================================
# ═══ СЕКЦИЯ 3: АДМИН-ПАНЕЛЬ ═══
# ============================================================
class ClearModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="ID канала", placeholder="Введите числовой ID канала",
                      custom_id="channel_id", min_length=1, max_length=30),
            TextInput(label="Количество сообщений", placeholder="От 1 до 100",
                      custom_id="amount", min_length=1, max_length=3),
        ]
        super().__init__(title="🧹 Очистка канала", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        cid_str = inter.text_values["channel_id"].strip()
        amt_str = inter.text_values["amount"].strip()
        if not cid_str.isdigit():
            return await inter.response.send_message("❌ ID канала должен быть числом.", ephemeral=True)
        try:
            amount = int(amt_str)
        except ValueError:
            return await inter.response.send_message("❌ Количество должно быть числом.", ephemeral=True)
        if amount < 1 or amount > 100:
            return await inter.response.send_message("❌ Количество 1-100.", ephemeral=True)
        channel = inter.guild.get_channel(int(cid_str))
        if not channel:
            return await inter.response.send_message("❌ Канал не найден.", ephemeral=True)
        if not isinstance(channel, disnake.TextChannel):
            return await inter.response.send_message("❌ Не текстовый канал.", ephemeral=True)
        bot_member = inter.guild.get_member(inter.bot.user.id)
        if not channel.permissions_for(bot_member).manage_messages:
            return await inter.response.send_message("❌ Нет прав на удаление.", ephemeral=True)
        try:
            deleted = await channel.purge(limit=amount, bulk=True)
            await inter.response.send_message(
                f"✅ Удалено **{len(deleted)}** сообщений в {channel.mention}.", ephemeral=True
            )
            await log_discord(
                title="🧹 Очистка канала",
                description=f"> **Админ:** {inter.author.mention}\n> **Канал:** {channel.mention}\n> **Удалено:** {len(deleted)}",
                color=0xff6600
            )
        except Exception as e:
            logger.exception("Очистка err: %s", e)
            await inter.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)


class GetJsonModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Ссылка на сообщение", custom_id="link",
                      placeholder="https://discord.com/channels/.../...", min_length=10, max_length=200),
        ]
        super().__init__(title="Получить JSON сообщения", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        link = inter.text_values["link"].strip()
        try:
            parts = link.strip("/").split("/")
            gid, chid, mid = map(int, parts[-3:])
        except Exception:
            return await inter.response.send_message("❌ Неверная ссылка.", ephemeral=True)
        try:
            from core.bot import bot
            channel = bot.get_channel(chid) or await bot.fetch_channel(chid)
            msg = await channel.fetch_message(mid)
        except Exception as e:
            return await inter.response.send_message(f"Ошибка: {e}", ephemeral=True)
        payload = {"content": msg.content or " ",
                   "embeds": [clean_embed_for_discohook(e.to_dict()) for e in msg.embeds]}
        buf = io.StringIO(json.dumps(payload, ensure_ascii=False, indent=2))
        await inter.response.send_message(file=disnake.File(fp=buf, filename="message.json"), ephemeral=True)
        await log_discord("📥 Выгрузка JSON",
                          f"Админ {inter.author.mention} выгрузил JSON из {channel.mention}", color=0x00ff00)


class AdminSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="・Пересчет отзывов", description="Корректировка отзывов",
                                 emoji="<:bannersc1:1538401325522489395>", value="recalc"),
            disnake.SelectOption(label="・Обновление баннера", description="Корректировка баннера",
                                 emoji="<:restart:1538401342391853118>", value="banner"),
            disnake.SelectOption(label="・Выгрузка JSON", description="Сообщение - Скрипт",
                                 emoji="<:jsons:1538401299459080263>", value="json"),
            disnake.SelectOption(label="・Очистка", description="Удаление сообщений в чате",
                                 emoji="<:clear:1538561439491686410>", value="clear"),
        ]
        super().__init__(placeholder="Выберите действие...", min_values=1, max_values=1,
                         options=options, custom_id="admin_select")

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


async def recalc_reviews(inter: disnake.MessageInteraction):
    try:
        from core.bot import update_review_counter
        await update_review_counter(silent=True)
        await inter.edit_original_response(content="✅ Отзывы пересчитаны и роли обновлены!")
    except Exception as e:
        await inter.edit_original_response(content=f"❌ Ошибка: {e}")


# ============================================================
# ═══ СЕКЦИЯ 4: СПРАВОЧНИК ═══
# ============================================================
class HomeSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="・Работа в Diamond", description="Карьера・Заработная плата",
                                 emoji="<:working:1538767619602120744>", value="work"),
            disnake.SelectOption(label="・Экосистема Diamond", description="Наши сайты・Лучшая жизнь",
                                 emoji="<:site:1538768985602916352>", value="eco"),
            disnake.SelectOption(label="・Роли покупателей", description="Достоинства・Разделение прав",
                                 emoji="<:roles:1540046665984249878>", value="roles"),
            disnake.SelectOption(label="・Доска", description="Знай о важном・Информация",
                                 emoji="<:banne1:1538551829246513312>", value="board"),
        ]
        super().__init__(placeholder="Выберите раздел...", min_values=1, max_values=1,
                         options=options, custom_id="home_select")

    async def callback(self, inter: disnake.MessageInteraction):
        await log_discord(
            title="📖 Выбор в справочнике",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff
        )
        value = inter.data.values[0]
        if value == "work":
            await inter.response.send_message(embeds=load_embed_from_file("work.json"), ephemeral=True)
        elif value == "eco":
            await inter.response.send_message(embeds=load_embed_from_file("eco.json"), ephemeral=True)
        elif value == "roles":
            await inter.response.send_message(embeds=load_embed_from_file("role.json"), ephemeral=True)
        elif value == "board":
            await inter.response.send_message(embeds=load_board_embed(), ephemeral=True)


class HomeView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(HomeSelect())


async def send_home_panel():
    from core.bot import bot
    await bot.wait_until_ready()
    channel = bot.get_channel(HOME_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(HOME_CHANNEL_ID)
        except Exception:
            channel = None
    if not channel:
        logger.warning("Home panel channel not found")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except Exception:
                pass
            break

    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1538771484778958898/image.png?ex=6a83e41e&is=6a82929e&hm=78e0190f6955969d2c2f630b4e9d560557c5c08d4f0c5caf8b32fbfd520332ab&")
    embed2 = disnake.Embed(
        title="Справочник посетителя Diamond",
        description="Справочник посетителя Diamond, в нем можно ознакомиться о нас, нашей экосистемой, узнать о важном, способе получения валюты сервера, достоинствах ролей покупателя и многом другом!",
        color=6776679
    )
    embed2.set_image(url=IMG_STRIPE)
    await channel.send(embeds=[embed1, embed2], view=HomeView())
    await log_discord(
        title="📖 Справочник отправлен",
        description=f"> Сообщение отправлено в {channel.mention}",
        color=0x00ff00
    )


# ============================================================
# ═══ СЕКЦИЯ 5: TAROLOGY ═══
# ============================================================
class TarologySelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="・Контакты для связи", description="Связь для заказа",
                                 emoji="<:people:1538395694648529009>", value="contacts"),
            disnake.SelectOption(label="・Подробности и акции", description="Узнайте больше, о данной сфере и бонусах",
                                 emoji="<:CARDS:1538780592425017454>", value="details"),
        ]
        super().__init__(placeholder="Узнать о раскладах", min_values=1, max_values=1,
                         options=options, custom_id="tarology_select")

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
            embed.set_image(url=IMG_STRIPE)
            await inter.response.send_message(embed=embed, ephemeral=True)
        elif value == "details":
            embed = disnake.Embed(
                title="🔮 Подробности и акции.",
                description=(
                    "> Данный канал создан для того, чтобы помочь вам влиться в сферу заработка с помощью раскладов.\n\n"
                    "> При покупке расклада (стоимость — 40₽) вы получаете расклад на любую интересующую вас тему с высокой точностью. А при оставлении отзыва в Early Tarology и в Diamond — вы получаете кэшбэк в виде Diamond Coins в размере 20 шт."
                ),
                color=6776679
            )
            embed.set_image(url=IMG_STRIPE)
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
        try:
            channel = await bot.fetch_channel(TAROLOGY_CHANNEL_ID)
        except Exception:
            channel = None
    if not channel:
        logger.warning("Tarology channel not found")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except Exception:
                pass
            break

    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://media.discordapp.net/attachments/1527006158282555412/1536977317912518677/image.png?ex=6a834bec&is=6a81fa6c&hm=a2a91a7975af349270ec5d97d17f7814e87de0da7943103eceb10dbbb3725978&=&format=webp&quality=lossless&width=1536&height=597")

    embed2 = disnake.Embed(
        title="Early Tarology от Diamond Lady",
        description="> Данный канал, путь в мистику и веру. Расклады неимоверно точные, она приугадала почти все, что произошло в магазине за Пол-Года до событий. Цены низкие, качество высокое. Информация - ниже по категориям.",
        color=6776679
    )
    embed2.set_image(url=IMG_STRIPE)
    await channel.send(embeds=[embed1, embed2], view=TarologyView())
    await log_discord(title="🔮 Панель Early Tarology отправлена",
                      description=f"> Сообщение отправлено в {channel.mention}", color=0x00ff00)


# ============================================================
# ═══ СЕКЦИЯ 6: ТИКЕТ-ПАНЕЛЬ ═══
# ============================================================
async def send_ticket_panel():
    from core.bot import bot
    from modules.commands_tickets import TicketPanelView
    await bot.wait_until_ready()
    channel = bot.get_channel(TICKET_PANEL_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(TICKET_PANEL_CHANNEL_ID)
        except Exception:
            channel = None
    if not channel:
        logger.warning("Ticket panel channel not found")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except Exception:
                pass
            break

    embed_path = os.path.join(CATALOG_DIR, "menu_embed.json")
    embed = disnake.Embed(
        title="🛒 Панель покупок",
        description=(
            "> Нажмите **Купить**, чтобы создать тикет для заказа.\n"
            "> Нажмите **Промокоды**, чтобы узнать о текущих акциях.\n"
            "> Нажмите **Каталог**, чтобы посмотреть ассортимент товаров."
        ),
        color=6776679
    )
    embed.set_image(url=IMG_STRIPE)
    if os.path.exists(embed_path):
        try:
            with open(embed_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("embeds") and len(data["embeds"]) > 0:
                embed = disnake.Embed.from_dict(clean_embed_for_discohook(data["embeds"][0]))
        except Exception as e:
            logger.error(f"menu_embed.json err: {e}")

    await channel.send(embed=embed, view=TicketPanelView())
    await log_discord(
        title="🛒 Панель тикетов отправлена",
        description=f"> Сообщение отправлено в {channel.mention}",
        color=0x00ff00,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )


# ============================================================
# ═══ СЕКЦИЯ 7: КОДЕКС МАГАЗИНА (Work) ═══
# ============================================================
class WorkSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="・Зарплата", description="О заработной плате работников",
                                 emoji="<:shopf:1541881304981966920>", value="salary"),
            disnake.SelectOption(label="・Топ Sales Manager", description="Статистика менеджеров продаж",
                                 emoji="<:diagram:1541881258873983046>", value="top"),
            disnake.SelectOption(label="・Правила по тикетам", description="Строго для прочтения Sales-Manager-ам.",
                                 emoji="<:banne1:1538551829246513312>", value="tickets"),
            disnake.SelectOption(label="・Списать заказ в таблице", description="Убрать заказ из статистики менеджера",
                                 emoji="<:12ss1:1551641380307337216>", value="spisat"),
        ]
        super().__init__(placeholder="Выберите раздел...", min_values=1, max_values=1,
                         options=options, custom_id="work_select")

    async def callback(self, inter: disnake.MessageInteraction):
        await log_discord(
            title="📂 Выбор в панели Кодекса",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff
        )
        value = inter.data.values[0]
        if value == "salary":
            await inter.response.send_message(embeds=load_embed_from_file("zp.json"), ephemeral=True)
        elif value == "top":
            await self.send_top(inter)
        elif value == "tickets":
            await inter.response.send_message(embeds=load_embed_from_file("ticket.json"), ephemeral=True)
        elif value == "spisat":
            if not has_admin_command_roles(inter.author):
                return await inter.response.send_message(
                    "⛔ Списать заказ может только администратор.", ephemeral=True
                )
            await inter.response.send_modal(SpisatZakazModal())

    async def send_top(self, inter):
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
            tr = s["total_rating"] if s else 0
            rc = s["ratings_count"] if s else 0
            avg = tr / rc if rc else 0
            data.append((m, closed, avg))
        data.sort(key=lambda x: (-x[1], -x[2]))

        lines = [f"> {m.mention} - **{closed}** закрытых заказов. [Рейтинг: **{avg:.1f}**]" for m, closed, avg in data]
        best = data[0] if data else None

        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1541810014463729724/image.png?ex=6a8ef1f8&is=6a8da078&hm=21f7a8bd88c0787fbefd0568f073761b139879ac3fa156962f5b0abded608351&")

        description = "> Предоставлены актуальные данные работы, после каждого выполненого заказа - таблица обновляется.\n\n"
        description += "\n".join(lines) + "\n" if lines else "> Пока нет данных.\n"

        embed2 = disnake.Embed(title="Таблиц работников на роли Sales Manager.\n",
                               description=description, color=6776679)
        embed2.set_image(url=IMG_STRIPE)
        if best:
            embed2.add_field(
                name="По актуальным данным, работником недели является ",
                value=f"<@&1154757071330365490> - {best[0].mention}, уверенное повышение!",
                inline=False
            )
        await inter.response.send_message(embeds=[embed1, embed2], ephemeral=True)


class WorkView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WorkSelect())


async def send_work_panel():
    from core.bot import bot
    await bot.wait_until_ready()
    channel = bot.get_channel(WORK_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(WORK_CHANNEL_ID)
        except Exception:
            channel = None
    if not channel:
        logger.warning("Work panel channel not found")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except Exception:
                pass
            break

    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1550864427455356938/image.png?ex=6aafe28d&is=6aae910d&hm=37683a13a82f6430ea83e49b010d5537d1cdc47b0563fb0d8ef9d50f2232d3c7&")
    embed2 = disnake.Embed(
        title="Кодекс магазина",
        description="> В данном разделе прописаны зарплаты сотрудников, рейтинг менеджеров, а также - устав, которому стоит придерживаться сотруднику по тикету.",
        color=6776679
    )
    embed2.set_image(url=IMG_STRIPE)
    await channel.send(embeds=[embed1, embed2], view=WorkView())
    await log_discord(title="📂 Панель «Кодекс магазина» отправлена",
                      description=f"> Сообщение отправлено в {channel.mention}", color=0x00ff00)


# ============================================================
# ═══ СЕКЦИЯ 8: СПИСАНИЕ ЗАКАЗА ═══
# ============================================================
class SpisatZakazModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="ID менеджера", placeholder="Введите ID менеджера",
                      custom_id="manager_id", min_length=1, max_length=30),
        ]
        super().__init__(title="Списание заказа", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        if not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        if not inter.text_values["manager_id"].strip().isdigit():
            return await inter.response.send_message("❌ Введите ID цифрами.", ephemeral=True)
        manager_id = int(inter.text_values["manager_id"].strip())
        orders = get_closed_orders(manager_id)
        if not orders:
            return await inter.response.send_message("❌ У менеджера нет закрытых заказов.", ephemeral=True)

        options = []
        for order in orders:
            closed_at = datetime.fromtimestamp(order["closed_at"]).strftime("%d.%m.%Y %H:%M")
            label = f"Заказ #{order['id']} – {closed_at}"
            if len(label) > 100:
                label = label[:97] + "..."
            options.append(SelectOption(label=label, value=str(order["id"]),
                                        description=f"Канал: {order['channel_id']}"))
        select = Select(placeholder="Выберите заказ для списания...",
                        options=options, custom_id="spisat_order_select")
        view = View(timeout=60)
        view.add_item(select)

        async def select_callback(inter2: disnake.MessageInteraction):
            order_id = int(inter2.data.values[0])
            remove_closed_order(order_id)
            cur.execute("UPDATE manager_stats SET closed_tickets = MAX(closed_tickets - 1, 0) WHERE user_id = ?",
                        (manager_id,))
            db.commit()
            await inter2.response.send_message("✅ Заказ списан. Статистика обновлена.", ephemeral=True)
            await send_work_panel()
            await log_discord(
                title="🗑️ Заказ списан",
                description=f"> **Админ:** {inter2.author.mention}\n> **Менеджер:** <@{manager_id}>\n> **Заказ:** #{order_id}",
                color=0xff6600
            )

        select.callback = select_callback
        await inter.response.send_message("Выберите заказ:", ephemeral=True, view=view)


# ============================================================
# ═══ СЕКЦИЯ 9: СЛУЖЕБНЫЕ ПАНЕЛИ В КАНАЛ ═══
# ============================================================
async def send_staff_panels():
    from core.bot import bot
    await bot.wait_until_ready()

    channel = bot.get_channel(STAFF_PANEL_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(STAFF_PANEL_CHANNEL_ID)
        except Exception as e:
            logger.warning(f"Staff panel channel not found: {e}")
            return
    if not channel:
        logger.warning("Staff panel channel not found")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user:
            try:
                await msg.delete()
            except Exception:
                pass

    dc_embed1 = disnake.Embed(color=6776679)
    dc_embed1.set_image(url="https://media.discordapp.net/attachments/1527006158282555412/1538202627005874318/image.png?ex=6a81d254&is=6a8080d4&hm=638d4a0af652ad4a72f25c2d193abff8e74879cf2dd173079a863484559c1dca&=&format=webp&quality=lossless")
    dc_embed2 = disnake.Embed(
        title="Экономическая панель Diamond Coins",
        description="> В данном разделе, происходит ручная корректировка валютного дела, связанного с акциями, и самой валютой, ниже - кнопки. Нажимай с умом.",
        color=6776679
    )
    dc_embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307371667506/image.png?ex=6a8133e3&is=6a7fe263&hm=2af0f26a823ea59af3001dc16ce84920759e966bc40824095314e6cd1d9b38ca&")
    await channel.send(embeds=[dc_embed1, dc_embed2], view=DCView())

    promo_embed1 = disnake.Embed(color=6776679)
    promo_embed1.set_image(url="https://media.discordapp.net/attachments/1527006158282555412/1537853007754957021/image.png?ex=6a808cb8&is=6a7f3b38&hm=9a8ed29d187e151fe6fe207910dd8665d74b9e2ab794c62e364e72e17079d7f6&=&format=webp&quality=lossless")
    promo_embed2 = disnake.Embed(
        title="Управление промокодами",
        description="> Используй данную панель, для управления промокодами.",
        color=6776679
    )
    promo_embed2.set_image(url=IMG_STRIPE)
    await channel.send(embeds=[promo_embed1, promo_embed2], view=PromoView())

    admin_embed1 = disnake.Embed(color=6776679)
    admin_embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851161233596556/image.png?ex=6a808b00&is=6a7f3980&hm=e19375ab0a3d1eae8df69da1ddcc71ded19ed8a6c53267f930e7bc8550a82796&")
    admin_embed2 = disnake.Embed(
        title="Панель управление сервером",
        description="> С помощью данной панели, происходит управление сервером, старые команды, были заменены одной панелью, что дает доступ, в одном виде. Ниже - предоставлены кнопки. Используй с умом.",
        color=6776679
    )
    admin_embed2.set_image(url=IMG_STRIPE)
    await channel.send(embeds=[admin_embed1, admin_embed2], view=AdminView())

    await log_discord(
        title="🛠️ Служебные панели обновлены",
        description=f"> Панели (Экономика DC / Промокоды / Админ) отправлены в {channel.mention}",
        color=0x00ff00
    )


# ============================================================
# ═══ СЕКЦИЯ 10: СЛЭШ-КОМАНДЫ ═══
# ============================================================
@commands.slash_command(name="say", description="Отправить сообщение от бота (админ)")
async def say(
    ctx,
    канал: disnake.TextChannel,
    тип_сообщения: str = commands.Param(choices=["text", "embed"]),
    текст: Optional[str] = None,
    файл: Optional[disnake.Attachment] = None,
):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)

    await ctx.response.defer(ephemeral=True)

    if тип_сообщения == "text":
        if not текст:
            return await ctx.edit_original_response(content="Введите текст.")
        await канал.send(текст)
        await ctx.edit_original_response(content="✅ Отправлено")
        await log_discord(
            title="📨 Say: текст",
            description=f"> **Админ:** {ctx.author.mention}\n> **Канал:** {канал.mention}",
            color=0x00ff00
        )
        return

    if тип_сообщения == "embed":
        if not текст and not файл:
            return await ctx.edit_original_response(content="Укажите JSON или файл.")
        if текст and файл:
            return await ctx.edit_original_response(content="Только один источник.")
        try:
            if файл:
                raw = await файл.read()
                data = json.loads(raw.decode("utf-8"))
            else:
                data = json.loads(текст)
            if "embeds" not in data:
                return await ctx.edit_original_response(content="Нет поля 'embeds'.")
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data["embeds"]]
            content = data.get("content", " ")
            await канал.send(content=content, embeds=embeds)
            await ctx.edit_original_response(content="✅ Embed отправлен")
            await log_discord(
                title="📨 Say: embed",
                description=f"> **Админ:** {ctx.author.mention}\n> **Канал:** {канал.mention}",
                color=0x00ff00
            )
        except Exception as e:
            logger.exception("say embed err: %s", e)
            await ctx.edit_original_response(content="❌ Ошибка.")


@commands.slash_command(name="dc_file", description="Начислить DC всем ID из текстового файла (админ)")
async def dc_file(
    ctx,
    amount: int = commands.Param(description="Количество DC для каждого получателя"),
    file: disnake.Attachment = commands.Param(description="Текстовый файл с ID (по одному на строку)"),
):
    if not has_admin_command_roles(ctx.author):
        return await ctx.send("⛔ У вас нет прав.", ephemeral=True)

    await ctx.response.defer(ephemeral=True)

    if amount <= 0:
        return await ctx.edit_original_response(content="❌ Количество DC должно быть больше 0.")

    if not file.filename.endswith('.txt'):
        return await ctx.edit_original_response(content="❌ Файл должен быть .txt")

    try:
        raw = await file.read()
        text = raw.decode('utf-8')
        lines = text.strip().splitlines()
        user_ids = []
        skipped = 0
        for line in lines:
            line = line.strip()
            if line.isdigit():
                user_ids.append(int(line))
            elif line:
                skipped += 1

        if not user_ids:
            return await ctx.edit_original_response(content="❌ Не найдено ни одного корректного ID.")

        success_count = 0
        fail_count = 0
        now = int(time.time())
        reason = f"Начисление из файла ({amount} DC)"

        for uid in user_ids:
            try:
                data = get_dc_cache(uid)
                data["balance"] += amount
                data["history"].append({"date": now, "amount": amount, "reason": reason})
                if len(data["history"]) > 50:
                    data["history"] = data["history"][-50:]
                save_dc_cache(uid, data)
                success_count += 1
            except Exception as e:
                logger.error(f"dc_file: {uid}: {e}")
                fail_count += 1

        try:
            sync_dc_to_json()
        except Exception as e:
            logger.warning(f"dc_file sync err: {e}")

        await ctx.edit_original_response(content=(
            f"✅ **Начисление завершено!**\n"
            f"👥 Всего получателей: **{len(user_ids)}**\n"
            f"✅ Успешно: **{success_count}**\n"
            f"❌ Ошибок: **{fail_count}**\n"
            f"⚠️ Пропущено строк: **{skipped}**\n"
            f"💎 Всего выдано: **{success_count * amount} DC**"
        ))

        await log_discord(
            title="💎 Начисление DC из файла",
            description=(
                f"> **Админ:** {ctx.author.mention}\n"
                f"> **Количество:** {amount} DC на человека\n"
                f"> **Получателей:** {len(user_ids)}\n"
                f"> **Всего выдано:** {success_count * amount} DC\n"
                f"> **Ошибок:** {fail_count}"
            ),
            color=0xffaa00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )
    except Exception as e:
        logger.exception(f"dc_file err: {e}")
        try:
            await ctx.edit_original_response(content=f"❌ Ошибка: {e}")
        except Exception:
            pass


# ============================================================
# РЕГИСТРАЦИЯ
# ============================================================
def setup_commands_staff(bot):
    bot.add_slash_command(say)
    bot.add_slash_command(dc_file)


setup_commands_admin = setup_commands_staff
