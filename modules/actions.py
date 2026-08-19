# -*- coding: utf-8 -*-
import os
import json
import random
import disnake
from disnake import SelectOption
from disnake.ui import View, Select, Button
from disnake import ButtonStyle, Embed
from datetime import datetime, timezone

from core.utils import (
    BASE_DIR, logger, log_discord,
    CONFIG, clean_embed_for_discohook,
    get_dc_cache, save_dc_cache, sync_dc_to_json
)
from modules.dc import (
    load_shop_catalog,
    get_user_balance, remove_dc, add_purchase,
    add_dc, get_user_dc_data
)

ACTIONS_DIR = os.path.join(BASE_DIR, "actions")

# Категории (теперь только две: Premium и Акционный товар)
CATEGORIES = [
    {
        "label": "・Premium",
        "description": "Премиум ・Дополнения",
        "emoji": "<:prem:1536788419638988982>",
        "file": "menu_premium.json"
    },
    {
        "label": "・Акционный товар",
        "description": "Каждый день, новый товар. Успевай!",
        "emoji": "<:box:1536972791432220712>",
        "file": None
    }
]

# Глобальная переменная для хранения текущего акционного товара
current_flash_item = None

def load_action_embed(filename: str) -> list[Embed]:
    path = os.path.join(ACTIONS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        embeds = []
        for e in data.get("embeds", []):
            embeds.append(disnake.Embed.from_dict(clean_embed_for_discohook(e)))
        return embeds
    except Exception as e:
        logger.error(f"Не удалось загрузить {filename}: {e}")
        return [disnake.Embed(title="Ошибка", description="Не удалось загрузить категорию.", color=0xff0000)]

def generate_flash_item():
    """Генерирует случайный товар для акции (скидка 50%). Исключает скидки 7%, 10%, 15%, 20%, оставляет 3% и 5%."""
    catalog = load_shop_catalog()
    items = []
    for cat_key, cat_data in catalog.items():
        if cat_key == "discounts":
            for item_key, item_data in cat_data.get("items", {}).items():
                try:
                    percent = int(item_key)
                    if percent in (3, 5):
                        items.append((cat_key, item_key, item_data))
                except:
                    continue
        else:
            for item_key, item_data in cat_data.get("items", {}).items():
                items.append((cat_key, item_key, item_data))

    if not items:
        return None

    cat_key, item_key, item_data = random.choice(items)
    original_price = item_data["price"]
    new_price = int(original_price * 0.5)
    if new_price < 1:
        new_price = 1

    category_label = catalog[cat_key]["label"]

    return {
        "cat_key": cat_key,
        "item_key": item_key,
        "item_data": item_data,
        "original_price": original_price,
        "discount": 50,
        "new_price": new_price,
        "category_label": category_label
    }

def refresh_flash_item():
    """Обновляет акционный товар (сохраняет в глобальную переменную)."""
    global current_flash_item
    current_flash_item = generate_flash_item()
    return current_flash_item

class FlashBuyView(View):
    """View для кнопки покупки (эфемерное сообщение) – только Купить."""
    def __init__(self, flash_item, user_id):
        super().__init__(timeout=300)
        self.flash_item = flash_item
        self.user_id = user_id
        self.add_item(Button(
            label=f"Купить {flash_item['item_data']['name']} за {flash_item['new_price']} DC",
            style=ButtonStyle.gray,
            custom_id=f"flash_buy|{flash_item['cat_key']}|{flash_item['item_key']}|{flash_item['new_price']}"
        ))

class ActionSelect(Select):
    def __init__(self):
        options = []
        for cat in CATEGORIES:
            options.append(
                SelectOption(
                    label=cat["label"],
                    description=cat["description"],
                    emoji=cat["emoji"],
                    value=str(cat["file"])
                )
            )
        super().__init__(
            placeholder="Выберите категорию...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="action_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        value = inter.data.values[0]
        if value == "None":
            global current_flash_item
            if current_flash_item is None:
                current_flash_item = generate_flash_item()
            if current_flash_item is None:
                return await inter.response.send_message("❌ Нет доступных товаров для акции.", ephemeral=True)

            flash = current_flash_item
            embed = disnake.Embed(
                title="🔥 Акционный товар",
                description=(
                    f"**Товар:** {flash['item_data']['name']}\n"
                    f"**Категория:** {flash['category_label']}\n"
                    f"**Старая цена:** ~~{flash['original_price']} <:moneyPhotoroom:1531701289518628964>~~\n"
                    f"**Новая цена:** **{flash['new_price']} <:moneyPhotoroom:1531701289518628964>**\n"
                    f"**Скидка:** {flash['discount']}%\n"
                ),
                color=0xff6600,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1532256186026426408/pisk.png?ex=6a7cab06&is=6a7b5986&hm=d6bea516ccf8362ee32747c2028ee41914139ddb974ff851e6d6cc3950ca9ab2&")

            view = FlashBuyView(flash, inter.author.id)
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)

            await log_discord(
                title="📂 Просмотр акции",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {flash['item_data']['name']}",
                color=0x00aaff
            )
        else:
            embeds = load_action_embed(value)
            await inter.response.send_message(embeds=embeds, ephemeral=True)
            category_name = "Неизвестно"
            for cat in CATEGORIES:
                if cat["file"] == value:
                    category_name = cat["label"]
                    break
            await log_discord(
                title="📂 Просмотр категории (Actions)",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Категория:** {category_name}",
                color=0x00aaff
            )

class ActionView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ActionSelect())

async def handle_flash_interaction(inter: disnake.MessageInteraction):
    """Обрабатывает кнопки покупки акции (custom_id начинается с flash_buy|)"""
    custom_id = inter.data.get("custom_id")
    if not custom_id or not custom_id.startswith("flash_buy|"):
        return

    parts = custom_id.split("|")
    if len(parts) != 4:
        return
    cat_key = parts[1]
    item_key = parts[2]
    try:
        price = int(parts[3])
    except ValueError:
        return

    catalog = load_shop_catalog()
    cat_data = catalog.get(cat_key, {})
    item_data = cat_data.get("items", {}).get(item_key)
    if not item_data:
        return await inter.response.send_message("❌ Товар не найден.", ephemeral=True)

    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    if balance < price:
        return await inter.response.send_message(f"❌ Недостаточно DC. Нужно: {price}, у вас: {balance}", ephemeral=True)

    success = await remove_dc(user_id, price, f"Покупка по акции: {item_data['name']}")
    if not success:
        return await inter.response.send_message("❌ Ошибка списания DC.", ephemeral=True)

    if cat_key == "roles" and item_data.get("role_id"):
        role = inter.guild.get_role(item_data["role_id"])
        if role:
            try:
                await inter.author.add_roles(role)
                await inter.response.send_message(
                    f"✅ Вы купили **{item_data['name']}** по акции за **{price} DC**! Роль выдана. Не забудьте оставить отзыв в <#1462074763437543435>.",
                    ephemeral=True
                )
                await log_discord(
                    title="🔥 Покупка по акции (роль)",
                    description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {item_data['name']}\n> **Цена:** {price} DC\n> **Категория:** {cat_data.get('label', 'Неизвестно')}",
                    color=0xff6600
                )
                return
            except Exception as e:
                await add_dc(user_id, price, "Возврат DC (ошибка выдачи роли)")
                await inter.response.send_message(f"❌ Не удалось выдать роль: {e}", ephemeral=True)
                return
        else:
            await add_dc(user_id, price, "Возврат DC (роль не найдена)")
            return await inter.response.send_message("❌ Роль не найдена на сервере.", ephemeral=True)

    await add_purchase(user_id, cat_key, item_data["name"])
    await inter.response.send_message(
        f"✅ Вы купили **{item_data['name']}** по акции за **{price} DC**! Активируйте товар в <#1462136361711829053>.",
        ephemeral=True
    )
    await log_discord(
        title="🔥 Покупка по акции",
        description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {item_data['name']}\n> **Цена:** {price} DC\n> **Категория:** {cat_data.get('label', 'Неизвестно')}",
        color=0xff6600
    )

async def send_actions_panel():
    """Отправляет меню Actions (или обновляет его, удаляя старое)."""
    from core.bot import bot
    await bot.wait_until_ready()

    channel = bot.get_channel(CONFIG["ACTIONS_CHANNEL_ID"])
    if not channel:
        channel = await bot.fetch_channel(CONFIG["ACTIONS_CHANNEL_ID"])
    if not channel:
        logger.warning("Actions channel not found")
        return

    # Удаляем старое сообщение с селект-меню
    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except:
                pass
            break

    # Отправляем новое меню
    main_embeds = load_action_embed("menu_actions.json")
    await channel.send(embeds=main_embeds, view=ActionView())

    await log_discord(
        title="🔄 Меню Actions обновлено",
        description="> Панель действий переотправлена.",
        color=0x00ff00
    )

async def refresh_actions_panel():
    """Обновляет акционный товар и переотправляет меню Actions."""
    refresh_flash_item()  # обновляем глобальный товар
    await send_actions_panel()
