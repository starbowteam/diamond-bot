# -*- coding: utf-8 -*-
"""Discord UI для панели питомцев."""
import asyncio

import disnake
from disnake import ButtonStyle, SelectOption
from disnake.ui import View, Button, Select, Modal, TextInput

from core.utils import logger, CONFIG
from pet import core as pcore
from pet import render as prender


P = "\u3164"


def _pad(text: str, left: int = 2, right: int = 2) -> str:
    return f"{P * left}{text}{P * right}"


# ============================================================
# ПАНЕЛЬ В КАНАЛЕ
# ============================================================
class PetPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label=_pad("Питомцы"), style=ButtonStyle.gray,
                       custom_id="pet_panel:my", emoji="🐾", row=0)
    async def my_pets(self, button, inter: disnake.MessageInteraction):
        await _open_my_pets(inter)

    @disnake.ui.button(label=_pad("Каталог"), style=ButtonStyle.gray,
                       custom_id="pet_panel:catalog", emoji="📖", row=0)
    async def catalog(self, button, inter: disnake.MessageInteraction):
        await _open_catalog(inter)

    @disnake.ui.button(label=_pad("Топ", 2, 1), style=ButtonStyle.gray,
                       custom_id="pet_panel:top", emoji="🏆", row=0)
    async def top(self, button, inter: disnake.MessageInteraction):
        await _open_top(inter)


# ============================================================
# МОИ ПИТОМЦЫ — только Забрать накопленное / Покормить питомца
# ============================================================
class MyPetsView(View):
    def __init__(self):
        super().__init__(timeout=300)

    @disnake.ui.button(label=_pad("Забрать накопленное", 2, 2),
                       style=ButtonStyle.gray,
                       custom_id="pet_my:claim", emoji="💰", row=0)
    async def claim(self, button, inter: disnake.MessageInteraction):
        await _claim_income(inter)

    @disnake.ui.button(label=_pad("Покормить питомца", 2, 2),
                       style=ButtonStyle.gray,
                       custom_id="pet_my:feed", emoji="🍖", row=0)
    async def feed(self, button, inter: disnake.MessageInteraction):
        await _feed_active(inter)


# ============================================================
# КАТАЛОГ — селект с доступными
# ============================================================
class CatalogSelect(Select):
    def __init__(self, available):
        options = []
        for key, cat in available[:25]:
            price = cat["price_dc"]
            label = f"{cat['name']} · {price} DC"
            if len(label) > 90:
                label = label[:87] + "..."
            desc = (
                f"{pcore.RARITY_LABEL[cat['rarity']]} · "
                f"+{cat['passive_dc']} DC/ч · {cat['description'][:50]}"
            )
            options.append(SelectOption(
                label=label,
                description=desc[:100],
                value=key,
            ))
        super().__init__(
            placeholder="Выбери питомца чтобы купить или подарить",
            min_values=1, max_values=1,
            options=options, custom_id="pet_cat:select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await _on_select_catalog(inter)


class CatalogView(View):
    def __init__(self, available):
        super().__init__(timeout=300)
        self.available = available
        if available:
            self.add_item(CatalogSelect(available))


# ============================================================
# КАРТОЧКА ТОВАРА
# ============================================================
class CardActionSelect(Select):
    def __init__(self, pet_key: str):
        cat = pcore.CATALOG.get(pet_key, {})
        price = cat.get("price_dc", 0)
        gp = pcore.gift_price(pet_key)

        super().__init__(
            placeholder="Что сделать с питомцем?",
            min_values=1, max_values=1,
            options=[
                SelectOption(
                    label=f"Купить себе · {price} DC",
                    description="Питомец сразу появится в твоей коллекции",
                    emoji="💎",
                    value="buy",
                ),
                SelectOption(
                    label=f"Подарить · {gp} DC",
                    description="Отправить питомца другому юзеру (комиссия +10%)",
                    emoji="🎁",
                    value="gift",
                ),
            ],
            custom_id=f"pet_card_action:{pet_key}",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        pet_key = self.custom_id.split(":")[-1]
        action = inter.data.values[0]

        if action == "buy":
            await _card_buy(inter, pet_key)
        elif action == "gift":
            await _card_gift(inter, pet_key)


class CatalogCardView(View):
    def __init__(self, pet_key: str, can_buy: bool):
        super().__init__(timeout=300)
        self.pet_key = pet_key
        self.add_item(CardActionSelect(pet_key))


# ============================================================
# МОДАЛКА ПОДАРКА
# ============================================================
class GiftPetModal(Modal):
    def __init__(self, pet_key: str):
        self.pet_key = pet_key
        cat = pcore.CATALOG.get(pet_key, {})
        price = pcore.gift_price(pet_key)
        super().__init__(
            title=f"Подарить: {cat.get('name', '—')}",
            components=[
                TextInput(
                    label=f"ID получателя · итого {price} DC",
                    placeholder="Например: 123456789012345678",
                    custom_id="recipient_id",
                    min_length=1,
                    max_length=32,
                )
            ],
            custom_id=f"pet_gift_modal:{pet_key}",
        )

    async def callback(self, inter: disnake.ModalInteraction):
        raw = (self.text_values.get("recipient_id") or "").strip()
        if not raw.isdigit():
            return await inter.response.send_message(
                "❌ ID должен состоять только из цифр.", ephemeral=True
            )

        recipient_id = int(raw)

        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

        result = await pcore.gift_pet(
            inter.bot, inter.author.id, recipient_id, self.pet_key
        )

        if not result.get("ok"):
            await inter.followup.send(
                f"❌ {result.get('error', 'Ошибка')}", ephemeral=True
            )
            return

        cat = pcore.CATALOG.get(self.pet_key, {})
        price = result.get("price", 0)
        base_price = cat.get("price_dc", 0)

        user_id = inter.author.id
        balance = _get_balance(user_id)

        buf = await asyncio.to_thread(
            prender.render_success_gift,
            user_id, balance, self.pet_key, price, base_price, recipient_id,
        )
        fname = f"pet_gift_ok_{user_id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")

        try:
            await inter.edit_original_response(
                content=None, embed=e, file=file, attachments=[], view=None,
            )
        except Exception:
            try:
                await inter.followup.send(embed=e, file=file, ephemeral=True)
            except Exception as ex:
                logger.warning(f"gift success render: {ex}")


# ============================================================
# ТОП
# ============================================================
class TopView(View):
    def __init__(self):
        super().__init__(timeout=300)


# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _is_ephemeral_message(inter: disnake.MessageInteraction) -> bool:
    try:
        msg = inter.message
        if msg is None:
            return False
        flags = getattr(msg, "flags", None)
        if flags is None:
            return False
        return bool(getattr(flags, "ephemeral", False))
    except Exception:
        return False


async def _display_screen(inter: disnake.MessageInteraction,
                          buf, fname: str, view: View):
    file = disnake.File(buf, filename=fname)
    e = disnake.Embed(color=6776679)
    e.set_image(url=f"attachment://{fname}")

    if _is_ephemeral_message(inter):
        try:
            await inter.edit_original_response(
                content=None, embed=e, file=file, attachments=[], view=view
            )
            return
        except Exception as ex:
            logger.warning(f"pet edit_original: {ex}")

    try:
        await inter.followup.send(embed=e, file=file, view=view, ephemeral=True)
    except Exception as ex:
        logger.warning(f"pet followup: {ex}")


def _get_balance(user_id: int) -> int:
    from core.utils import get_dc_cache
    return get_dc_cache(user_id).get("balance", 0)


def _get_available_pets(user_id: int):
    owned = {p["pet_key"] for p in pcore.get_user_pets(user_id)}
    return [(k, c) for k, c in pcore.CATALOG.items() if k not in owned]


# ============================================================
# ОТКРЫТИЕ
# ============================================================
async def _open_my_pets(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    balance = _get_balance(user_id)
    pets = pcore.get_user_pets(user_id)
    buf = await asyncio.to_thread(prender.render_my_pets, user_id, balance, pets)
    await _display_screen(inter, buf, f"pet_my_{user_id}.png", MyPetsView())


async def _open_catalog(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    balance = _get_balance(user_id)
    available = _get_available_pets(user_id)
    buf = await asyncio.to_thread(
        prender.render_catalog, user_id, balance, available, None
    )
    await _display_screen(inter, buf, f"pet_cat_{user_id}.png", CatalogView(available))


async def _open_top(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    balance = _get_balance(user_id)
    top = pcore.get_top_users(limit=10)
    place = pcore.get_user_place(user_id)
    best_pet = pcore.get_user_best_pet(user_id)
    buf = await asyncio.to_thread(
        prender.render_top, user_id, balance, top, place, best_pet
    )
    await _display_screen(inter, buf, f"pet_top_{user_id}.png", TopView())


# ============================================================
# ДЕЙСТВИЯ
# ============================================================
async def _claim_income(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    amount = await pcore.claim_income(user_id)
    if amount <= 0:
        await inter.followup.send("💰 Накоплений пока нет.", ephemeral=True)
        return
    await inter.followup.send(f"💰 Получено **+{amount} DC**!", ephemeral=True)
    await _open_my_pets(inter)


async def _feed_active(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    result = await pcore.feed_active_pet(user_id)
    if not result.get("ok"):
        await inter.followup.send(
            f"❌ {result.get('error', 'Ошибка')}", ephemeral=True
        )
        return
    xp = result["xp"]
    msg = f"🍖 Питомец покормлен! **+{xp} XP**"
    if result.get("bonus_xp"):
        msg += f" (бонус за streak +{result['bonus_xp']})"
    await inter.followup.send(msg, ephemeral=True)
    await _open_my_pets(inter)


async def _on_select_catalog(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    pet_key = inter.data.values[0]
    user_id = inter.author.id

    if pcore.has_pet(user_id, pet_key):
        await inter.followup.send(
            "❌ У тебя уже есть этот питомец.", ephemeral=True
        )
        await _open_catalog(inter)
        return

    cat = pcore.CATALOG.get(pet_key, {})
    balance = _get_balance(user_id)
    can_buy = balance >= cat.get("price_dc", 0)

    buf = await asyncio.to_thread(
        prender.render_item_card, user_id, balance, pet_key
    )
    fname = f"pet_item_{user_id}_{pet_key}.png"
    view = CatalogCardView(pet_key, can_buy)
    await _display_screen(inter, buf, fname, view)


async def _card_buy(inter: disnake.MessageInteraction, pet_key: str):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    user_id = inter.author.id

    if pcore.has_pet(user_id, pet_key):
        await inter.followup.send("❌ У тебя уже есть этот питомец.", ephemeral=True)
        await _open_catalog(inter)
        return

    cat = pcore.CATALOG.get(pet_key, {})
    price = cat.get("price_dc", 0)

    result = await pcore.buy_pet(inter.bot, user_id, pet_key)
    if not result.get("ok"):
        await inter.followup.send(
            f"❌ {result.get('error', 'Ошибка')}", ephemeral=True
        )
        return

    balance = _get_balance(user_id)
    buf = await asyncio.to_thread(
        prender.render_success_buy, user_id, balance, pet_key, price
    )
    fname = f"pet_buy_ok_{user_id}.png"
    await _display_screen(inter, buf, fname, TopView())


async def _card_gift(inter: disnake.MessageInteraction, pet_key: str):
    try:
        await inter.response.send_modal(GiftPetModal(pet_key))
    except Exception as e:
        logger.warning(f"gift modal: {e}")
