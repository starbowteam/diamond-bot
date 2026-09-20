# -*- coding: utf-8 -*-
import os
import json
import io
import re
from datetime import datetime, timezone
from typing import Optional, List

import disnake
from disnake import ButtonStyle, SelectOption
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
    reload_promo
)
from modules.dc import (
    add_dc, remove_dc,
    get_user_purchases, remove_purchase,
    get_dc_cache, save_dc_cache,
    sync_dc_to_json
)
from modules.commands_profile import load_embed_from_file

# ============================================================
# КАНАЛ С СЛУЖЕБНЫМИ ПАНЕЛЯМИ
# ============================================================
STAFF_PANEL_CHANNEL_ID = 1551276116679860314

# ============================================================
# ЗАГРУЗКА ПРОМОКОДОВ
# ============================================================
promo_codes = get_promo_codes()

def reload_promo_cache():
    global promo_codes
    promo_codes = get_promo_codes()


# ============================================================
# ПАНЕЛЬ ЭКОНОМИКИ (panel_dc) — БЕЗ ЗП/АВАНСА
# ============================================================
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


class DCView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DCSelect())


# ============================================================
# МОДАЛКИ ДЛЯ DC-ПАНЕЛИ
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
# ПАНЕЛЬ ПРОМОКОДОВ
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
# АДМИН-ПАНЕЛЬ
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

    async def callback(self, inter: disnake.ModalInteraction):
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


async def recalc_reviews(inter: disnake.MessageInteraction):
    try:
        await update_review_counter(silent=True)
        await inter.edit_original_response(content="✅ Отзывы пересчитаны и роли обновлены!")
    except Exception as e:
        await inter.edit_original_response(content=f"❌ Ошибка: {e}")


# ============================================================
# ОТПРАВКА ВСЕХ СЛУЖЕБНЫХ ПАНЕЛЕЙ В КАНАЛ
# ============================================================
async def send_staff_panels():
    """Отправляет 3 панели (Экономика / Промокоды / Админ) в канал STAFF_PANEL_CHANNEL_ID."""
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

    # Чистим прошлые сообщения бота
    async for msg in channel.history(limit=50):
        if msg.author == bot.user:
            try:
                await msg.delete()
            except Exception:
                pass

    # --- 1. Экономическая панель DC ---
    dc_embed1 = disnake.Embed(color=6776679)
    dc_embed1.set_image(url="https://media.discordapp.net/attachments/1527006158282555412/1538202627005874318/image.png?ex=6a81d254&is=6a8080d4&hm=638d4a0af652ad4a72f25c2d193abff8e74879cf2dd173079a863484559c1dca&=&format=webp&quality=lossless")
    dc_embed2 = disnake.Embed(
        title="Экономическая панель Diamond Coins",
        description="> В данном разделе, происходит ручная корректировка валютного дела, связанного с акциями, и самой валютой, ниже - кнопки. Нажимай с умом.",
        color=6776679
    )
    dc_embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307371667506/image.png?ex=6a8133e3&is=6a7fe263&hm=2af0f26a823ea59af3001dc16ce84920759e966bc40824095314e6cd1d9b38ca&")
    await channel.send(embeds=[dc_embed1, dc_embed2], view=DCView())

    # --- 2. Панель промокодов ---
    promo_embed1 = disnake.Embed(color=6776679)
    promo_embed1.set_image(url="https://media.discordapp.net/attachments/1527006158282555412/1537853007754957021/image.png?ex=6a808cb8&is=6a7f3b38&hm=9a8ed29d187e151fe6fe207910dd8665d74b9e2ab794c62e364e72e17079d7f6&=&format=webp&quality=lossless")
    promo_embed2 = disnake.Embed(
        title="Управление промокодами",
        description="> Используй данную панель, для управления промокодами.",
        color=6776679
    )
    promo_embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a808b23&is=6a7f39a3&hm=38fda4f54c273fb8cada8c1332a7f5fe77041eed1e642797bd7e8d92094252b7&")
    await channel.send(embeds=[promo_embed1, promo_embed2], view=PromoView())

    # --- 3. Админ-панель ---
    admin_embed1 = disnake.Embed(color=6776679)
    admin_embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851161233596556/image.png?ex=6a808b00&is=6a7f3980&hm=e19375ab0a3d1eae8df69da1ddcc71ded19ed8a6c53267f930e7bc8550a82796&")
    admin_embed2 = disnake.Embed(
        title="Панель управление сервером",
        description="> С помощью данной панели, происходит управление сервером, старые команды, были заменены одной панелью, что дает доступ, в одном виде. Ниже - предоставлены кнопки. Используй с умом.",
        color=6776679
    )
    admin_embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307759390/image.png?ex=6a808b23&is=6a7f39a3&hm=38fda4f54c273fb8cada8c1332a7f5fe77041eed1e642797bd7e8d92094252b7&")
    await channel.send(embeds=[admin_embed1, admin_embed2], view=AdminView())

    await log_discord(
        title="🛠️ Служебные панели обновлены",
        description=f"> Панели (Экономика DC / Промокоды / Админ) отправлены в {channel.mention}",
        color=0x00ff00
    )


# ============================================================
# КОМАНДА /say
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
# КОМАНДА /dc_file (было: /gw_dc)
# ============================================================
@commands.slash_command(
    name="dc_file",
    description="Начислить DC всем ID из текстового файла (админ)"
)
async def dc_file(
    ctx,
    amount: int = commands.Param(description="Количество DC для каждого получателя"),
    file: disnake.Attachment = commands.Param(description="Текстовый файл с ID (по одному на строку)")
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
                await add_dc(uid, amount, f"Начисление из файла ({amount} DC)")
                success_count += 1
            except Exception as e:
                logger.error(f"Ошибка начисления {amount} DC пользователю {uid}: {e}")
                fail_count += 1

        await ctx.send(
            f"✅ Начисление завершено!\n"
            f"👥 Всего получателей: {len(user_ids)}\n"
            f"✅ Успешно начислено: {success_count}\n"
            f"❌ Ошибок: {fail_count}\n"
            f"💎 Всего выдано: {success_count * amount} DC",
            ephemeral=True
        )

        await log_discord(
            title="💎 Начисление DC из файла",
            description=(
                f"> **Админ:** {ctx.author.mention}\n"
                f"> **Количество:** {amount} DC на человека\n"
                f"> **Получателей:** {len(user_ids)}\n"
                f"> **Всего выдано:** {success_count * amount} DC"
            ),
            color=0xffaa00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    except Exception as e:
        logger.exception(f"Ошибка в команде dc_file: {e}")
        await ctx.send(f"❌ Произошла ошибка: {e}", ephemeral=True)


# ============================================================
# РЕГИСТРАЦИЯ СЛЭШ-КОМАНД
# ============================================================
def setup_commands_admin(bot):
    bot.add_slash_command(say)
    bot.add_slash_command(dc_file)
