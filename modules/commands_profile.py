# -*- coding: utf-8 -*-
import os
import json
import time
import asyncio
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
    clean_embed_for_discohook,
    get_ticket_manager,
)
from modules.dc import (
    add_dc, remove_dc, add_purchase,
    get_user_purchases, remove_purchase,
    get_user_balance,
    load_shop_catalog,
)


# ============================================================
# ХЕЛПЕР: загрузка JSON эмбеда из add/
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


# ============================================================
# ОПРЕДЕЛЕНИЕ РОЛИ ПО КОЛИЧЕСТВУ ОТЗЫВОВ
# ============================================================
def _get_role_info_by_count(count: int):
    thresholds = [
        (0,  "none",      "Клуб",                       0,   "Напишите первый отзыв"),
        (1,  "bronze",    "Silver Buyer",               20,  "Осталось 2 отзыва"),
        (3,  "silver",    "Gold Buyer",                 40,  "Осталось 2 отзыва"),
        (5,  "gold",      "Diamond Buyer",              55,  "Осталось 4 отзыва"),
        (9,  "diamond",   "Emerald Buyer",              70,  "Осталось 4 отзыва"),
        (13, "emerald",   "Amethyst Buyer",             80,  "Осталось 5 отзывов"),
        (18, "amethyst",  "Legendary Buyer",            90,  "Осталось 6 отзывов"),
        (24, "legendary", "Покупатель Века",            95,  "Осталось 2 отзыва"),
        (26, "pka",       "—",                         100,  "Вы достигли вершины!"),
    ]
    current = thresholds[0]
    for i, t in enumerate(thresholds):
        if count >= t[0]:
            current = t
        else:
            break
    return current[1], current[2], current[3], current[4]


# ============================================================
# ГЕНЕРАЦИЯ И ОТПРАВКА КАРТОЧКИ ПРОФИЛЯ
# ============================================================
async def show_profile_card(inter: disnake.MessageInteraction, user: disnake.Member):
    await inter.response.defer(with_message=True, ephemeral=True)

    from modules.profile_card import generate_profile_card

    try:
        counts = load_json(FILES["review_counts"], {})
        review_count = counts.get(str(user.id), 0)

        role_key, next_name, progress_pct, progress_text = _get_role_info_by_count(review_count)

        dc = get_dc_cache(user.id)
        balance = dc.get("balance", 0)
        history_raw = dc.get("history", []) or []

        now_ts = int(time.time())
        month_ago = now_ts - 30 * 86400

        total_earned = sum(h.get("amount", 0) for h in history_raw if h.get("amount", 0) > 0)
        earned_month = sum(h.get("amount", 0) for h in history_raw if h.get("amount", 0) > 0 and h.get("date", 0) >= month_ago)
        spent_month = sum(abs(h.get("amount", 0)) for h in history_raw if h.get("amount", 0) < 0 and h.get("date", 0) >= month_ago)

        try:
            purchases = await get_user_purchases(user.id, only_unused=True)
        except Exception:
            purchases = []

        inventory = []
        for p in purchases[:3]:
            ptype = p.get("type", "")
            name = p.get("value", "")[:16]
            if ptype == "roles":
                accent = (20, 155, 208)
            elif ptype == "discounts":
                accent = (46, 204, 113)
            elif ptype in ("design", "design_avatar", "design_banner"):
                accent = (247, 201, 145)
            elif ptype in ("ads",):
                accent = (255, 107, 107)
            elif ptype in ("custom",):
                accent = (216, 142, 223)
            else:
                accent = (20, 155, 208)
            inventory.append({
                "_ptype": ptype,
                "name": name,
                "qty": f"куплено {datetime.fromtimestamp(p.get('date', 0)).strftime('%d.%m.%Y')}",
                "accent": accent,
            })

        history = []
        for h in reversed(history_raw[-6:]):
            date_str = datetime.fromtimestamp(h.get("date", 0)).strftime("%d.%m.%Y")
            history.append({
                "date": date_str,
                "amount": h.get("amount", 0),
            })

        custom_roles = []
        try:
            guild = inter.guild

            excluded = set()
            for rid in CONFIG.get("ROLE_IDS", {}).values():
                excluded.add(rid)
            excluded.update({
                1127428607606796290,
                1154757071330365490,
                1471844291595731016,
                1471190371181789234,
                1457964854441672806,
                1423360115335106570,
                1539523399611580476,
            })

            limit_role = guild.get_role(1127428607606796290)
            max_pos = limit_role.position if limit_role else 9999

            for r in sorted(user.roles, key=lambda x: -x.position):
                if r.is_default():
                    continue
                if r.managed:
                    continue
                if r.id in excluded:
                    continue
                if r.position >= max_pos:
                    continue
                custom_roles.append({
                    "id": r.id,
                    "name": r.name,
                    "pos": f"#{r.position}",
                    "color": r.color.to_rgb() if r.color.value else (136, 136, 136),
                })
        except Exception as e:
            logger.warning(f"Custom roles error: {e}")

        avatar_bytes = None
        try:
            avatar_bytes = await user.display_avatar.replace(size=256, format="png").read()
        except Exception as e:
            logger.warning(f"Avatar fetch error: {e}")

        streak = 0
        if dc.get("last_bonus", 0) >= now_ts - 86400:
            streak = 1

        buf, meta = await generate_profile_card(
            user_name=user.display_name,
            user_id=user.id,
            avatar_bytes=avatar_bytes,
            role_key=role_key,
            reviews=review_count,
            next_role_name=next_name,
            progress_pct=progress_pct,
            progress_text=progress_text,
            balance=balance,
            total_earned=total_earned,
            earned_month=earned_month,
            spent_month=spent_month,
            purchases_count=len(purchases),
            streak=streak,
            inventory=inventory,
            history=history,
            custom_roles=custom_roles,
        )

        filename = f"profile_{user.id}.png"
        file = disnake.File(buf, filename=filename)

        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{filename}")

        if meta["cached"]:
            embed.set_footer(text="⚡ Из кэша · Карточка обновляется при изменениях")
        else:
            embed.set_footer(text=f"✨ Сгенерировано за {meta['duration']:.1f} сек · Кэш 10 минут")

        await inter.edit_original_response(content=None, embed=embed, file=file)

        asyncio.create_task(log_discord(
            title="📇 Карточка профиля",
            description=(
                f"> **Пользователь:** {inter.author.mention}\n"
                f"> **Источник:** {'кэш' if meta['cached'] else f'рендер ({meta[\"duration\"]:.1f}с)'}"
            ),
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        ))

    except Exception as e:
        logger.exception(f"Ошибка рендера карточки профиля: {e}")
        try:
            await inter.edit_original_response(
                content=f"❌ Не удалось сгенерировать карточку.\n`{str(e)[:200]}`"
            )
        except Exception:
            pass


# ============================================================
# УПРАВЛЕНИЕ ПОКУПКАМИ
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
# МОДАЛКА: РАСЧЁТ СКИДКИ
# ============================================================
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

        embed = disnake.Embed(title="🧾 Результат расчёта скидки", color=0x2ecc71)
        embed.add_field(name="Исходная цена", value=f"`{price:.2f} ₽`", inline=True)
        embed.add_field(name="Скидка", value=f"`{discount:.0f}%`", inline=True)
        embed.add_field(name="Экономия", value=f"`{savings:.2f} ₽`", inline=True)
        embed.add_field(name="✅ Итоговая цена", value=f"**`{final_price:.2f} ₽`**", inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# ВЫБОР В ПАНЕЛИ ПРОФИЛЬ
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
                label="・О валюте",
                description="Трата валюты・Её получение",
                emoji="<:buy:1538395716920148079>",
                value="currency"
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
        asyncio.create_task(log_discord(
            title="👤 Выбор в панели профиля",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`",
            color=0x00aaff
        ))

        value = inter.data.values[0]
        if value == "profile":
            await show_profile_card(inter, inter.author)
        elif value == "purchases":
            await inter.response.defer(ephemeral=True)
            purchases = await get_user_purchases(inter.author.id, only_unused=True)
            if not purchases:
                return await inter.followup.send("❌ У вас нет неиспользованных покупок.", ephemeral=True)
            embed = disnake.Embed(
                title="О какой покупке ты хочешь узнать?",
                description="> Выбери нужный товар ниже.",
                color=6776679
            )
            embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a887423&is=6a8722a3&hm=42c31ce6b67f4dbe9bc8e19eecfa29d805c871131064ccf76672953bff3573d6&")
            view = PurchaseSelectView(inter.author.id, purchases)
            await inter.followup.send(embed=embed, view=view, ephemeral=True)
        elif value == "currency":
            await inter.response.defer(ephemeral=True)
            embeds = load_embed_from_file("vallue.json")
            await inter.followup.send(embeds=embeds, ephemeral=True)
        elif value == "discount":
            await inter.response.send_modal(DiscountModal())


class ProfileView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProfileSelect())


# ============================================================
# ОТПРАВКА ПАНЕЛИ ПРОФИЛЬ
# ============================================================
PROFILE_CHANNEL_ID = 1540018373503483934


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
        description="> В данном разделе, ты можешь - увидить свой профиль, свои покупки, возможно - отменить их, и получить возрат, но - 75%! Узнать, как купить что либо за Diamond Coin и многое другое! Не забудь о расчете скидок, для своих покупок!",
        color=6776679
    )
    embed2.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6a887423&is=6a8722a3&hm=42c31ce6b67f4dbe9bc8e19eecfa29d805c871131064ccf76672953bff3573d6&")
    await channel.send(embeds=[embed1, embed2], view=ProfileView())
    await log_discord(
        title="👤 Панель Профиль отправлена",
        description=f"> Сообщение отправлено в {channel.mention}",
        color=0x00ff00
    )
