# -*- coding: utf-8 -*-
import os
import json
import time
import random
import asyncio
import disnake
from disnake import SelectOption, PartialEmoji
from disnake.ui import View, Select, Button, Modal, TextInput
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
    add_dc, get_user_dc_data, get_user_purchases
)

ACTIONS_DIR = os.path.join(BASE_DIR, "actions")

# JSON-хранилища
DAILY_DEAL_FILE = os.path.join(DATA_DIR, "daily_deal.json")
FLASH_SALE_FILE = os.path.join(DATA_DIR, "flash_sale.json")
ROULETTE_STATS_FILE = os.path.join(DATA_DIR, "roulette_stats.json")

# Тайминги
DAILY_DEAL_REFRESH_HOURS = 5
FLASH_SALE_DURATION_HOURS = 1

# Скидки
DAILY_DEAL_DISCOUNT = 30
FLASH_SALE_DISCOUNT = 70

# Чередование: 5 обычных → 1 флеш
DAILY_DEALS_PER_CYCLE = 5

# ============================================================
# КАРТИНКИ
# ============================================================
IMG_ROULETTE_SPIN   = "https://cdn.discordapp.com/attachments/1527006158282555412/1550685793872248842/image.png?ex=6aaf3c2f&is=6aadeaaf&hm=67254a55d5004c897269e64255ad1a54e9a29689a383fda711316592a5bad350&"
IMG_ROULETTE_WIN    = "https://cdn.discordapp.com/attachments/1527006158282555412/1550685830727598130/image.png?ex=6aaf3c38&is=6aadeab8&hm=bda99953d1ea04a3799aa0378691ba4ba793ef2c2919ab7f9bdbef63a33cbc19&"
IMG_ROULETTE_LOSE   = "https://cdn.discordapp.com/attachments/1527006158282555412/1550685884456636527/image.png?ex=6aaf3c45&is=6aadeac5&hm=451731816ed61f6878fba789858bdf5aed0ef69cfe1bfd5ce5378a7f9a1e4a18&"
IMG_STRIPE          = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aaeafa3&is=6aad5e23&hm=9190ceac69655c6c96803bdfb25627b447bb205ef0e467f13abd39d43d5f165b&"


# ============================================================
# ХРАНИЛИЩЕ: DAILY DEAL
# ============================================================
def load_daily_deal() -> dict:
    return load_json(DAILY_DEAL_FILE, {})


def save_daily_deal(data: dict):
    save_json(DAILY_DEAL_FILE, data)


def generate_random_deal(discount: int):
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


def _current_deal_slot() -> int:
    return int(time.time() // (DAILY_DEAL_REFRESH_HOURS * 3600))


def refresh_daily_deal(force: bool = False):
    """
    Логика чередования: 5 обычных акций (30%) → 1 флеш-слот.
    Форсим обновление если скидка в сохранённой акции не совпадает с константой.
    """
    current_slot = _current_deal_slot()
    data = load_daily_deal()

    saved_item = data.get("item")
    # Если сохранённая акция имеет неправильный процент — форсим
    if saved_item and saved_item.get("discount") != DAILY_DEAL_DISCOUNT:
        logger.info(f"Скидка в сохранённой акции ({saved_item.get('discount')}%) != {DAILY_DEAL_DISCOUNT}%. Форсим обновление.")
        force = True

    # Слот не менялся и всё ок — возвращаем текущий
    if not force and data.get("slot") == current_slot:
        return saved_item

    counter = data.get("counter", 0)
    old_item = data.get("item")

    if counter >= DAILY_DEALS_PER_CYCLE:
        # Флеш-слот: обычная акция не меняется, флаг для запуска флеша
        save_daily_deal({
            "slot": current_slot,
            "item": old_item,
            "counter": 0,
            "flash_slot": True,
            "updated_at": int(time.time())
        })
        logger.info(f"Флеш-слот начался (slot={current_slot})")
        return old_item

    # Обычная акция (30%)
    counter += 1
    deal = generate_random_deal(discount=DAILY_DEAL_DISCOUNT)
    if not deal:
        return None

    save_daily_deal({
        "slot": current_slot,
        "item": deal,
        "counter": counter,
        "flash_slot": False,
        "updated_at": int(time.time())
    })
    logger.info(f"Товар дня обновлён (slot={current_slot}, counter={counter}, {DAILY_DEAL_DISCOUNT}%): {deal['item_data']['name']}")
    return deal


# ============================================================
# ХРАНИЛИЩЕ: FLASH SALE
# ============================================================
def load_flash_sale() -> dict:
    return load_json(FLASH_SALE_FILE, {
        "active": False, "item": None,
        "started_at": 0, "message_id": 0, "channel_id": 0
    })


def save_flash_sale(data: dict):
    save_json(FLASH_SALE_FILE, data)


def get_flash_sale_item():
    data = load_flash_sale()
    if data.get("active") and data.get("item"):
        # Если скидка не 70% — считаем невалидным
        if data["item"].get("discount") != FLASH_SALE_DISCOUNT:
            return None
        if time.time() - data.get("started_at", 0) < FLASH_SALE_DURATION_HOURS * 3600:
            return data["item"]
    return None


async def start_flash_sale(bot):
    """Генерирует и публикует флеш-акцию (вызывается из daily_deal_task)."""
    try:
        deal = generate_random_deal(discount=FLASH_SALE_DISCOUNT)
        if not deal:
            logger.warning("start_flash_sale: не удалось сгенерировать товар")
            return

        channel = bot.get_channel(CONFIG["ACTIONS_CHANNEL_ID"])
        if not channel:
            channel = await bot.fetch_channel(CONFIG["ACTIONS_CHANNEL_ID"])
        if not channel:
            logger.warning("start_flash_sale: канал actions не найден")
            return

        ping_text = f"<@&1127428607606796290> - ***Огромная скидка в акционных товарах, успей купить!***"

        embed = disnake.Embed(
            title="⚡ МЕГА-СКИДКА ТОЛЬКО СЕЙЧАС!",
            description=(
                f"**Товар:** {deal['item_data']['name']}\n"
                f"**Категория:** {deal['category_label']}\n"
                f"**Старая цена:** ~~{deal['original_price']} DC~~\n"
                f"**Новая цена:** **{deal['new_price']} DC**\n"
                f"**Скидка:** {FLASH_SALE_DISCOUNT}%\n\n"
                f"⏰ **Действует {FLASH_SALE_DURATION_HOURS} час!**"
            ),
            color=0xff0000,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1532256186026426408/pisk.png?ex=6a7cab06&is=6a7b5986&hm=d6bea516ccf8362ee32747c2028ee41914139ddb974ff851e6d6cc3950ca9ab2&")
        embed.set_footer(text="Купить можно в акционных товарах")

        msg = await channel.send(content=ping_text, embed=embed)

        save_flash_sale({
            "active": True,
            "item": deal,
            "started_at": int(time.time()),
            "message_id": msg.id,
            "channel_id": channel.id
        })
        logger.info(f"Flash sale запущен: {deal['item_data']['name']} ({FLASH_SALE_DISCOUNT}%)")
        await log_discord(
            title="⚡ Flash sale запущен",
            description=(
                f"> **Товар:** {deal['item_data']['name']}\n"
                f"> **Категория:** {deal['category_label']}\n"
                f"> **Скидка:** {FLASH_SALE_DISCOUNT}%\n"
                f"> **Длительность:** {FLASH_SALE_DURATION_HOURS} час"
            ),
            color=0xff0000
        )
    except Exception as e:
        logger.exception(f"start_flash_sale error: {e}")


# ============================================================
# СТАТИСТИКА РУЛЕТКИ
# ============================================================
def load_roulette_stats() -> dict:
    return load_json(ROULETTE_STATS_FILE, {"total_bets": 0, "total_won": 0, "total_lost": 0, "rolls": 0})


def save_roulette_stats(data: dict):
    save_json(ROULETTE_STATS_FILE, data)


# ============================================================
# ЗАГРУЗКА EMBED'ОВ
# ============================================================
def load_action_embed(filename: str):
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
# ВИД ДЛЯ ПОКУПКИ АКЦИИ
# ============================================================
class FlashBuyView(View):
    def __init__(self, flash_item, user_id, is_flash: bool = False):
        super().__init__(timeout=300)
        self.flash_item = flash_item
        self.user_id = user_id
        self.add_item(Button(
            label=f"Купить {flash_item['item_data']['name']} за {flash_item['new_price']} DC",
            style=ButtonStyle.danger if is_flash else ButtonStyle.gray,
            custom_id=f"flash_buy|{flash_item['cat_key']}|{flash_item['item_key']}|{flash_item['new_price']}"
        ))


# ============================================================
# РУЛЕТКА МОНЕТ
# ============================================================
ROULETTE_ROLLS = [
    {"name": "Проигрыш",        "mult": -1.0, "chance": 62.0, "color": 0xed4245, "emoji": "🎲", "desc": "Ты потерял ставку"},
    {"name": "Малый выигрыш",   "mult":  0.2, "chance": 18.0, "color": 0x95a5a6, "emoji": "🔹", "desc": "+20% от ставки"},
    {"name": "Средний выигрыш", "mult":  0.5, "chance": 12.0, "color": 0x149bd0, "emoji": "🔸", "desc": "+50% от ставки"},
    {"name": "Двойной",         "mult":  1.0, "chance":  5.0, "color": 0x2ecc71, "emoji": "💎", "desc": "х2 — удвоение ставки"},
    {"name": "Тройной",         "mult":  2.0, "chance":  2.0, "color": 0xf7c991, "emoji": "👑", "desc": "х3 — тройная ставка"},
    {"name": "JACKPOT",         "mult":  4.0, "chance":  0.7, "color": 0xffaa00, "emoji": "🎰", "desc": "х5 — джекпот!"},
    {"name": "MEGA JACKPOT",    "mult":  9.0, "chance":  0.3, "color": 0xff00aa, "emoji": "⭐", "desc": "х10 — мега-джекпот!!!"},
]


def roll_roulette() -> dict:
    total = sum(r["chance"] for r in ROULETTE_ROLLS)
    r = random.uniform(0, total)
    cur = 0
    for roll in ROULETTE_ROLLS:
        cur += roll["chance"]
        if r <= cur:
            return roll
    return ROULETTE_ROLLS[0]


def _build_spin_embeds() -> list:
    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url=IMG_ROULETTE_SPIN)
    embed2 = disnake.Embed(
        title="Идет прокрутка слота, ожидайте ⌛",
        description="> 🎰 Прокручиваем барабан, подбираем слоты, ставим ставку",
        color=6776679
    )
    embed2.set_image(url=IMG_STRIPE)
    return [embed1, embed2]


def _build_win_embeds(result: dict, bet: int, net: int, new_balance: int) -> list:
    total_payout = bet + net

    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url=IMG_ROULETTE_WIN)

    embed2 = disnake.Embed(
        title=f"{result['emoji']}  {result['name'].upper()}!",
        description=(
            f"> 🎰 Выпало: **{result['emoji']} {result['name']}**\n"
            f"> 📊 Множитель: **x{1 + result['mult']:.1f}**\n\n"
            f"> 💵 Твоя ставка: **{bet} DC**\n"
            f"> ✅ Возврат: **+{total_payout} DC**\n"
            f"> 📈 Чистый профит: **+{net} DC**\n"
            f"> 💎 Новый баланс: **{new_balance} DC**"
        ),
        color=result["color"],
        timestamp=datetime.now(timezone.utc)
    )
    embed2.add_field(name="📌  Детали", value=f"> `{result['desc']}`", inline=False)
    embed2.set_footer(text=f"Ставка: {bet} DC · Удача на твоей стороне!")
    embed2.set_image(url=IMG_STRIPE)
    return [embed1, embed2]


def _build_lose_embeds(result: dict, bet: int, new_balance: int) -> list:
    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url=IMG_ROULETTE_LOSE)

    embed2 = disnake.Embed(
        title=f"{result['emoji']}  ПРОИГРЫШ",
        description=(
            f"> 🎰 Выпало: **{result['emoji']} {result['name']}**\n"
            f"> 📊 Множитель: **x0**\n\n"
            f"> 💵 Твоя ставка: **{bet} DC**\n"
            f"> 💸 Потеряно: **−{bet} DC**\n"
            f"> 💎 Новый баланс: **{new_balance} DC**"
        ),
        color=0xed4245,
        timestamp=datetime.now(timezone.utc)
    )
    embed2.add_field(name="📌  Детали", value="> `Не расстраивайся, повезёт в следующий раз!`", inline=False)
    embed2.set_footer(text=f"Ставка: {bet} DC · Попробуешь ещё?")
    embed2.set_image(url=IMG_STRIPE)
    return [embed1, embed2]


class RouletteModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="Ставка (DC)",
                placeholder="Введи сумму от 1 до твоего баланса",
                custom_id="bet",
                min_length=1,
                max_length=10
            )
        ]
        super().__init__(title="🎰 Рулетка монет", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        user_id = inter.author.id

        bet_str = inter.text_values["bet"].strip()
        if not bet_str.isdigit():
            return await inter.response.send_message("❌ Ставка должна быть целым числом.", ephemeral=True)
        bet = int(bet_str)
        if bet < 1:
            return await inter.response.send_message("❌ Минимальная ставка — 1 DC.", ephemeral=True)

        balance = await get_user_balance(user_id)
        if bet > balance:
            return await inter.response.send_message(
                f"❌ Недостаточно DC.\n> **Твой баланс:** `{balance} DC`\n> **Ставка:** `{bet} DC`",
                ephemeral=True
            )

        await inter.response.defer(ephemeral=True)

        success = await remove_dc(user_id, bet, "Ставка в рулетке монет")
        if not success:
            return await inter.edit_original_response(
                content="❌ Не удалось списать DC. Попробуй позже."
            )

        await inter.edit_original_response(embeds=_build_spin_embeds())
        await asyncio.sleep(2.2)

        result = roll_roulette()
        mult = result["mult"]

        if mult > 0:
            payout = bet + int(bet * mult)
            net = int(bet * mult)
            await add_dc(user_id, payout, f"Выигрыш в рулетке: {result['name']}")
            new_balance = await get_user_balance(user_id)

            view = RouletteRetryView(bet)
            await inter.edit_original_response(
                embeds=_build_win_embeds(result, bet, net, new_balance),
                view=view
            )

            stats = load_roulette_stats()
            stats["total_bets"] = stats.get("total_bets", 0) + bet
            stats["total_won"] = stats.get("total_won", 0) + net
            stats["rolls"] = stats.get("rolls", 0) + 1
            save_roulette_stats(stats)

            asyncio.create_task(log_discord(
                title=f"🎰 Рулетка: {result['name']}",
                description=(
                    f"> **Пользователь:** {inter.author.mention}\n"
                    f"> **Ставка:** `{bet} DC`\n"
                    f"> **Результат:** `x{1 + mult:.1f}`\n"
                    f"> **Чистый профит:** `+{net} DC`\n"
                    f"> **Новый баланс:** `{new_balance} DC`"
                ),
                color=result["color"]
            ))
        else:
            new_balance = await get_user_balance(user_id)

            view = RouletteRetryView(bet)
            await inter.edit_original_response(
                embeds=_build_lose_embeds(result, bet, new_balance),
                view=view
            )

            stats = load_roulette_stats()
            stats["total_bets"] = stats.get("total_bets", 0) + bet
            stats["total_lost"] = stats.get("total_lost", 0) + bet
            stats["rolls"] = stats.get("rolls", 0) + 1
            save_roulette_stats(stats)

            asyncio.create_task(log_discord(
                title="🎰 Рулетка: проигрыш",
                description=(
                    f"> **Пользователь:** {inter.author.mention}\n"
                    f"> **Ставка:** `{bet} DC`\n"
                    f"> **Результат:** `x0`\n"
                    f"> **Потеряно:** `−{bet} DC`\n"
                    f"> **Новый баланс:** `{new_balance} DC`"
                ),
                color=0xed4245
            ))


class RouletteRetryView(View):
    def __init__(self, last_bet: int):
        super().__init__(timeout=300)
        self.last_bet = last_bet

        btn_retry = Button(
            label="ㅤㅤㅤИграть ещеㅤㅤㅤ",
            style=ButtonStyle.gray,
            custom_id="roulette_retry",
            emoji=PartialEmoji(name="gamee", id=1550686072168517632),
            row=0
        )
        btn_retry.callback = self.retry_callback
        self.add_item(btn_retry)

        btn_double = Button(
            label="ㅤㅤㅤДвойная ставкаㅤㅤ",
            style=ButtonStyle.gray,
            custom_id="roulette_double",
            emoji=PartialEmoji(name="flash", id=1550686028522590309),
            row=0
        )
        btn_double.callback = self.double_callback
        self.add_item(btn_double)

    async def retry_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(RouletteModal())

    async def double_callback(self, inter: disnake.MessageInteraction):
        user_id = inter.author.id
        new_bet = self.last_bet * 2
        balance = await get_user_balance(user_id)

        if new_bet > balance:
            return await inter.response.send_message(
                f"❌ Недостаточно DC для двойной ставки.\n"
                f"> **Нужно:** `{new_bet} DC`\n> **У тебя:** `{balance} DC`",
                ephemeral=True
            )

        success = await remove_dc(user_id, new_bet, "Ставка в рулетке (двойная)")
        if not success:
            return await inter.response.send_message("❌ Ошибка списания DC.", ephemeral=True)

        await inter.response.defer(ephemeral=True)

        await inter.edit_original_response(embeds=_build_spin_embeds())
        await asyncio.sleep(2.2)

        result = roll_roulette()
        mult = result["mult"]

        if mult > 0:
            payout = new_bet + int(new_bet * mult)
            net = int(new_bet * mult)
            await add_dc(user_id, payout, f"Выигрыш в рулетке: {result['name']}")
            new_balance = await get_user_balance(user_id)

            view = RouletteRetryView(new_bet)
            await inter.edit_original_response(
                embeds=_build_win_embeds(result, new_bet, net, new_balance),
                view=view
            )

            asyncio.create_task(log_discord(
                title=f"🎰 Рулетка: {result['name']} (двойная)",
                description=(
                    f"> **Пользователь:** {inter.author.mention}\n"
                    f"> **Ставка:** `{new_bet} DC`\n"
                    f"> **Чистый профит:** `+{net} DC`\n"
                    f"> **Баланс:** `{new_balance} DC`"
                ),
                color=result["color"]
            ))
        else:
            new_balance = await get_user_balance(user_id)
            view = RouletteRetryView(new_bet)
            await inter.edit_original_response(
                embeds=_build_lose_embeds(result, new_bet, new_balance),
                view=view
            )

            asyncio.create_task(log_discord(
                title="🎰 Рулетка: проигрыш (двойная)",
                description=(
                    f"> **Пользователь:** {inter.author.mention}\n"
                    f"> **Ставка:** `{new_bet} DC`\n"
                    f"> **Новый баланс:** `{new_balance} DC`"
                ),
                color=0xed4245
            ))


# ============================================================
# СЕЛЕКТ ДЛЯ ACTIONS
# ============================================================
class ActionSelect(Select):
    def __init__(self):
        options = [
            SelectOption(
                label="・Акционный товар",
                description="Неимоверные скидки на товары!",
                emoji="<:box:1536972791432220712>",
                value="deals"
            ),
            SelectOption(
                label="・Рулетка монет",
                description="Поставь Diamond Coins на удачу!",
                emoji="<:ropulet:1550563615675781282>",
                value="roulette"
            ),
        ]
        super().__init__(
            placeholder="Выберите категорию...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="action_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        value = inter.data.values[0]

        if value == "deals":
            daily = refresh_daily_deal()
            flash_item = get_flash_sale_item()

            now_ts = int(time.time())
            slot_seconds = DAILY_DEAL_REFRESH_HOURS * 3600
            next_update_ts = ((now_ts // slot_seconds) + 1) * slot_seconds
            minutes_left = max((next_update_ts - now_ts) // 60, 0)

            embeds = []
            view = View(timeout=300)

            if daily:
                embed = disnake.Embed(
                    title="🔥 Акционный товар дня",
                    description=(
                        f"**Товар:** {daily['item_data']['name']}\n"
                        f"**Категория:** {daily['category_label']}\n"
                        f"**Старая цена:** ~~{daily['original_price']} <:moneyPhotoroom:1531701289518628964>~~\n"
                        f"**Новая цена:** **{daily['new_price']} <:moneyPhotoroom:1531701289518628964>**\n"
                        f"**Скидка:** {daily['discount']}%\n\n"
                        f"🕐 Обновится через **{minutes_left} мин**"
                    ),
                    color=0xff6600,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1532256186026426408/pisk.png?ex=6a7cab06&is=6a7b5986&hm=d6bea516ccf8362ee32747c2028ee41914139ddb974ff851e6d6cc3950ca9ab2&")
                embeds.append(embed)
                view.add_item(Button(
                    label=f"Купить {daily['item_data']['name']} за {daily['new_price']} DC",
                    style=ButtonStyle.gray,
                    custom_id=f"flash_buy|{daily['cat_key']}|{daily['item_key']}|{daily['new_price']}"
                ))

            if flash_item:
                fs_data = load_flash_sale()
                elapsed = now_ts - fs_data.get("started_at", now_ts)
                fs_left = max((FLASH_SALE_DURATION_HOURS * 3600 - elapsed) // 60, 0)

                flash_embed = disnake.Embed(
                    title="⚡ МЕГА-СКИДКА! (только сейчас)",
                    description=(
                        f"**Товар:** {flash_item['item_data']['name']}\n"
                        f"**Категория:** {flash_item['category_label']}\n"
                        f"**Старая цена:** ~~{flash_item['original_price']} <:moneyPhotoroom:1531701289518628964>~~\n"
                        f"**Новая цена:** **{flash_item['new_price']} <:moneyPhotoroom:1531701289518628964>**\n"
                        f"**Скидка:** {flash_item['discount']}%\n\n"
                        f"⏰ Истекает через **{fs_left} мин**"
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

            if not embeds:
                return await inter.response.send_message("❌ Нет доступных товаров для акции.", ephemeral=True)

            await inter.response.send_message(embeds=embeds, view=view, ephemeral=True)

            await log_discord(
                title="📂 Просмотр акции",
                description=f"> **Пользователь:** {inter.author.mention}",
                color=0x00aaff
            )

        elif value == "roulette":
            balance = await get_user_balance(inter.author.id)
            if balance < 1:
                return await inter.response.send_message(
                    "❌ У тебя нет DC для игры. Сначала заработай их активностью.",
                    ephemeral=True
                )
            await inter.response.send_modal(RouletteModal())


class ActionView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ActionSelect())


# ============================================================
# ОБРАБОТКА ПОКУПКИ АКЦИИ
# ============================================================
async def handle_flash_interaction(inter: disnake.MessageInteraction):
    custom_id = inter.data.get("custom_id")
    if not custom_id:
        return

    if custom_id in ("roulette_retry", "roulette_double"):
        return

    if not custom_id.startswith("flash_buy|"):
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

    existing = await get_user_purchases(user_id, only_unused=False)
    for p in existing:
        if p.get("from_action") and p.get("value") == item_data["name"]:
            return await inter.response.send_message(
                "❌ **Этот акционный товар уже куплен.**\n"
                "> Акцию можно использовать только **один раз**.\n"
                "> Возврат акционных товаров **невозможен**.",
                ephemeral=True
            )

    balance = await get_user_balance(user_id)
    if balance < price:
        return await inter.response.send_message(
            f"❌ Недостаточно DC. Нужно: **{price}**, у вас: **{balance}**.", ephemeral=True
        )

    success = await remove_dc(user_id, price, f"Покупка по акции: {item_data['name']}")
    if not success:
        return await inter.response.send_message("❌ Ошибка списания DC.", ephemeral=True)

    if cat_key == "roles" and item_data.get("role_id"):
        role = inter.guild.get_role(item_data["role_id"])
        if role:
            try:
                await inter.author.add_roles(role)
                await add_purchase(user_id, cat_key, item_data["name"], from_action=True)
                await inter.response.send_message(
                    f"✅ Вы купили **{item_data['name']}** по акции за **{price} DC**! Роль выдана.\n"
                    f"⚠️ Это **акционный** товар — возврату не подлежит.",
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

    await add_purchase(user_id, cat_key, item_data["name"], from_action=True)
    await inter.response.send_message(
        f"✅ Вы купили **{item_data['name']}** по акции за **{price} DC**! Активируйте товар в <#1462136361711829053>.\n"
        f"⚠️ Это **акционный** товар — возврату не подлежит.",
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
    await send_actions_panel()
