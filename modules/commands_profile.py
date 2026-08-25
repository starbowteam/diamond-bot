# -*- coding: utf-8 -*-
import os
import json
import time
from datetime import datetime, timezone
from typing import Optional, List

import disnake
from disnake import ButtonStyle, SelectOption
from disnake.ui import Button, Modal, Select, TextInput, View

from core.utils import (
    CONFIG, FILES, ADD_DIR, logger,
    load_json, save_json, log_discord,
    get_dc_cache, save_dc_cache,
    get_roles_for_count,
    clean_embed_for_discohook
)
from modules.dc import (
    add_dc, remove_dc, add_purchase,
    get_user_purchases, remove_purchase,
    get_user_balance,
    load_shop_catalog
)

# ============================================================
# ПРОФИЛЬ
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
            price = 0
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
        purchases = await get_user_purchases(self.user_id, only_unused=False)
        if self.purchase_index >= len(purchases):
            return await inter.response.send_message("❌ Этот товар уже был возвращён или применён.", ephemeral=True)
        p = purchases[self.purchase_index]
        success = await remove_purchase(self.user_id, self.purchase_index)
        if not success:
            return await inter.response.send_message("❌ Ошибка при возврате товара.", ephemeral=True)
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
# ПЕРЕДАЧА ПОДАРКА
# ============================================================
async def handle_transfer(inter: disnake.MessageInteraction):
    user_id = inter.author.id
    purchases = await get_user_purchases(user_id, only_unused=True)
    if not purchases:
        return await inter.response.send_message("❌ У вас нет неиспользованных товаров для передачи.", ephemeral=True)

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
    select = Select(placeholder="Выберите товар для передачи...", options=options, custom_id="transfer_select")
    view = View(timeout=300)
    view.add_item(select)

    async def select_callback(inter2: disnake.MessageInteraction):
        if inter2.author.id != user_id:
            return await inter2.response.send_message("⛔ Это не ваш товар.", ephemeral=True)
        idx = int(inter2.data.values[0])
        if idx >= len(purchases):
            return await inter2.response.send_message("❌ Товар не найден.", ephemeral=True)
        await inter2.response.send_modal(TransferRecipientModal(idx, purchases, inter2.author))

    select.callback = select_callback
    await inter.response.send_message("Выберите товар, который хотите передать:", ephemeral=True, view=view)

class TransferRecipientModal(Modal):
    def __init__(self, purchase_index, purchases, author):
        self.purchase_index = purchase_index
        self.purchases = purchases
        self.author = author
        components = [
            TextInput(
                label="Введите ID получателя",
                placeholder="Например, 123456789012345678",
                custom_id="recipient_id",
                min_length=1,
                max_length=30
            )
        ]
        super().__init__(title="Передача подарка", components=components)

    async def callback(self, inter: disnake.MessageInteraction):
        recipient_input = inter.text_values["recipient_id"].strip()
        if not recipient_input.isdigit():
            return await inter.response.send_message("❌ Введите корректный ID (только цифры).", ephemeral=True)
        recipient_id = int(recipient_input)
        if recipient_id == inter.author.id:
            return await inter.response.send_message("❌ Вы не можете передать товар самому себе.", ephemeral=True)
        guild = inter.guild
        recipient_member = guild.get_member(recipient_id)
        if not recipient_member:
            return await inter.response.send_message("❌ Пользователь с таким ID не найден на сервере.", ephemeral=True)
        if recipient_member.bot:
            return await inter.response.send_message("❌ Нельзя передавать товар ботам.", ephemeral=True)

        purchases = await get_user_purchases(self.author.id, only_unused=False)
        if self.purchase_index >= len(purchases):
            return await inter.response.send_message("❌ Этот товар уже был передан или использован.", ephemeral=True)
        p = purchases[self.purchase_index]
        success = await remove_purchase(self.author.id, self.purchase_index)
        if not success:
            return await inter.response.send_message("❌ Ошибка удаления товара у отправителя.", ephemeral=True)
        await add_purchase(recipient_id, p['type'], p['value'])
        await log_discord(
            title="🎁 Передача подарка",
            description=(
                f"> **Отправитель:** {inter.author.mention}\n"
                f"> **Получатель:** {recipient_member.mention}\n"
                f"> **Товар:** `{p['value']}`"
            ),
            color=0x00ff00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )
        await inter.response.send_message(
            f"✅ Товар **{p['value']}** успешно передан {recipient_member.mention}!",
            ephemeral=True
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
# ПАНЕЛЬ ПРОФИЛЬ (селект)
# ============================================================
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
                label="・Передать подарок",
                description="Простая передача・радость обоим",
                emoji="<:transfer:1541653944726716497>",
                value="transfer"
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
            purchases = await get_user_purchases(inter.author.id, only_unused=True)
            if not purchases:
                return await inter.response.send_message("❌ У вас нет неиспользованных покупок.", ephemeral=True)
            embed = disnake.Embed(
                title="О какой покупке ты хочешь узнать?",
                description="> Выбери нужный товар ниже.",
                color=6776679
            )
            embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a887423&is=6a8722a3&hm=42c31ce6b67f4dbe9bc8e19eecfa29d805c871131064ccf76672953bff3573d6&")
            view = PurchaseSelectView(inter.author.id, purchases)
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)
        elif value == "transfer":
            await handle_transfer(inter)
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
# ОТПРАВКА ПАНЕЛИ ПРОФИЛЬ
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
# ФУНКЦИЯ ЗАГРУЗКИ ЭМБЕДОВ ИЗ ADD
# ============================================================
def load_embed_from_file(filename: str) -> list[disnake.Embed]:
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

PROFILE_CHANNEL_ID = 1540018373503483934
