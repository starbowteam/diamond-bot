# -*- coding: utf-8 -*-
import os
import json
import time
import random
import disnake
from disnake import SelectOption
from disnake.ui import View, Select, Button
from disnake import ButtonStyle, Embed
from datetime import datetime, timezone

from core.utils import (
    BASE_DIR, DATA_DIR, CONFIG, logger, log_discord,
    clean_embed_for_discohook,
    load_json, save_json,
    get_dc_cache, save_dc_cache, sync_dc_to_json
)
from modules.dc import (
    load_shop_catalog,
    get_user_balance, remove_dc, add_purchase,
    add_dc, get_user_dc_data
)

ACTIONS_DIR = os.path.join(BASE_DIR, "actions")

# JSON-хранилища
DAILY_DEAL_FILE = os.path.join(DATA_DIR, "daily_deal.json")
FLASH_SALE_FILE = os.path.join(DATA_DIR, "flash_sale.json")

# Категории (Premium убран)
CATEGORIES = [
    {
        "label": "・Акционный товар",
        "description": "Каждый день, новый товар. Успевай!",
        "emoji": "<:box:1536972791432220712>",
        "file": None
    }
]


# ============================================================
# ХРАНИЛИЩЕ: DAILY DEAL
# ============================================================
def load_daily_deal() -> dict:
    """Возвращает {'item': {...}, 'date': 'YYYY-MM-DD'} или пустой dict."""
    return load_json(DAILY_DEAL_FILE, {})


def save_daily_deal(data: dict):
    save_json(DAILY_DEAL_FILE, data)


def generate_random_deal(discount: int) -> dict | None:
    """Генерирует случайный товар из каталога со скидкой discount%."""
    catalog = load_shop_catalog()
    items = []
    for cat_key, cat_data in catalog.items():
        for item_key, item_data in cat_data.get("items", {}).items():
            items.append((cat_key, item_key, item_data))

    if not items:
        return None

    cat_key, item_key, item_data = random.choice(items)
    original_price = item_data["price"]
    new_price = max(int(original_price * (100 - discount) / 100), 1)

    return {
        "cat_key": cat_key,
        "item_key": item_key,
        "item_data": item_data,
        "original_price": original_price,
        "discount": discount,
        "new_price": new_price,
        "category_label": catalog[cat_key]["label"],
    }


def refresh_daily_deal(force: bool = False) -> dict | None:
    """Обновляет товар дня (если сегодня ещё не обновляли или force=True)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = load_daily_deal()

    if not force and data.get("date") == today and data.get("item"):
        return data["item"]

    deal = generate_random_deal(discount=50)
    if not deal:
        return None

    save_daily_deal({"date": today, "item": deal})
    logger.info(f"Товар дня обновлён: {deal['item_data']['name']}")
    return deal


# ============================================================
# ХРАНИЛИЩЕ: FLASH SALE
# ============================================================
def load_flash_sale() -> dict:
    """Возвращает {'active': bool, 'item': {...}, 'started_at': int, 'message_id': int, 'channel_id': int}."""
    return load_json(FLASH_SALE_FILE, {
        "active": False, "item": None,
        "started_at": 0, "message_id": 0, "channel_id": 0
    })


def save_flash_sale(data: dict):
    save_json(FLASH_SALE_FILE, data)


def get_flash_sale_item() -> dict | None:
    """Возвращает активный flash-item или None."""
    data = load_flash_sale()
    if data.get("active") and data.get("item"):
        # проверяем не истёк ли
        if time.time() - data.get("started_at", 0) < 2 * 3600:
            return data["item"]
    return None


# ============================================================
# ЗАГРУЗКА EMBED'ОВ ИЗ ФАЙЛОВ
# ============================================================
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


# ============================================================
# VIEW ДЛЯ ПОКУПКИ АКЦИИ
# ============================================================
class FlashBuyView(View):
    def __init__(self, flash_item, user_id):
        super().__init__(timeout=300)
        self.flash_item = flash_item
        self.user_id = user_id
        self.add_item(Button(
            label=f"Купить {flash_item['item_data']['name']} за {flash_item['new_price']} DC",
            style=ButtonStyle.gray,
            custom_id=f"flash_buy|{flash_item['cat_key']}|{flash_item['item_key']}|{flash_item['new_price']}"
        ))


# ============================================================
# СЕЛЕКТ ДЛЯ ACTIONS
# ============================================================
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
            # Показываем daily deal + flash sale если активен
            daily = refresh_daily_deal()
            flash_item = get_flash_sale_item()

            if not daily:
                return await inter.response.send_message("❌ Нет доступных товаров для акции.", ephemeral=True)

            # Основной embed — товар дня
            embed = disnake.Embed(
                title="🔥 Акционный товар дня",
                description=(
                    f"**Товар:** {daily['item_data']['name']}\n"
                    f"**Категория:** {daily['category_label']}\n"
                    f"**Старая цена:** ~~{daily['original_price']} <:moneyPhotoroom:1531701289518628964>~~\n"
                    f"**Новая цена:** **{daily['new_price']} <:moneyPhotoroom:1531701289518628964>**\n"
                    f"**Скидка:** {daily['discount']}%\n"
                ),
                color=0xff6600,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1532256186026426408/pisk.png?ex=6a7cab06&is=6a7b5986&hm=d6bea516ccf8362ee32747c2028ee41914139ddb974ff851e6d6cc3950ca9ab2&")

            embeds = [embed]
            view = FlashBuyView(daily, inter.author.id)

            # Если активен flash — добавляем второй embed + второй view
            if flash_item:
                flash_embed = disnake.Embed(
                    title="⚡ МЕГА-СКИДКА! (только сейчас)",
                    description=(
                        f"**Товар:** {flash_item['item_data']['name']}\n"
                        f"**Категория:** {flash_item['category_label']}\n"
                        f"**Старая цена:** ~~{flash_item['original_price']} <:moneyPhotoroom:1531701289518628964>~~\n"
                        f"**Новая цена:** **{flash_item['new_price']} <:moneyPhotoroom:1531701289518628964>**\n"
                        f"**Скидка:** {flash_item['discount']}%\n"
                        f"**Истекает:** через 2 часа"
                    ),
                    color=0xff0000,
                    timestamp=datetime.now(timezone.utc)
                )
                flash_embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1532256186026426408/pisk.png?ex=6a7cab06&is=6a7b5986&hm=d6bea516ccf8362ee32747c2028ee41914139ddb974ff851e6d6cc3950ca9ab2&")
                embeds.append(flash_embed)
                view.add_item(Button(
                    label=f"⚡ Купить {flash_item['item_data']['name']} за {flash_item['new_price']} DC",
                    style=ButtonStyle.danger,
                    custom_id=f"flash_buy|{flash_item['cat_key']}|{flash_item['item_key']}|{flash_item['new_price']}"
                ))

            await inter.response.send_message(embeds=embeds, view=view, ephemeral=True)

            await log_discord(
                title="📂 Просмотр акции",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Товар дня:** {daily['item_data']['name']}" +
                            (f"\n> **⚡ Flash:** {flash_item['item_data']['name']}" if flash_item else ""),
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


# ============================================================
# ОБРАБОТКА ПОКУПКИ АКЦИИ
# ============================================================
async def handle_flash_interaction(inter: disnake.MessageInteraction):
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
                    description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {item_data['name']}\n> **Цена:** {price} DC",
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
        description=f"> **Пользователь:** {inter.author.mention}\n> **Товар:** {item_data['name']}\n> **Цена:** {price} DC",
        color=0xff6600
    )


# ============================================================
# ОТПРАВКА ACTIONS ПАНЕЛИ
# ============================================================
async def send_actions_panel():
    """Отправляет меню Actions (обновляет старое)."""
    from core.bot import bot
    await bot.wait_until_ready()

    channel = bot.get_channel(CONFIG["ACTIONS_CHANNEL_ID"])
    if not channel:
        channel = await bot.fetch_channel(CONFIG["ACTIONS_CHANNEL_ID"])
    if not channel:
        logger.warning("Actions channel not found")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except:
                pass
            break

    main_embeds = load_action_embed("menu_actions.json")
    await channel.send(embeds=main_embeds, view=ActionView())
    await log_discord(
        title="🔄 Меню Actions обновлено",
        description="> Панель действий переотправлена.",
        color=0x00ff00
    )


async def refresh_actions_panel():
    """Обновляет панель Actions (для обратной совместимости)."""
    await send_actions_panel()
