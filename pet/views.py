# -*- coding: utf-8 -*-
"""Discord UI для панели питомцев."""
import asyncio

import disnake
from disnake import ButtonStyle, SelectOption
from disnake.ui import View, Button, Select, Modal, TextInput

from core.utils import logger, CONFIG
from pet import core as pcore
from pet import render as prender


P = "\u3164"  # невидимый пробел


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
# СЕЛЕКТ "МОИ ПИТОМЦЫ"
# ============================================================
class MyPetsSelect(Select):
    def __init__(self, pets):
        options = []
        for p in pets[:25]:
            cat = pcore.CATALOG.get(p["pet_key"], {})
            label = f"{cat.get('name', '—')} · ур. {p['level']}"
            if len(label) > 90:
                label = label[:87] + "..."
            desc = (
                f"{pcore.RARITY_LABEL.get(cat.get('rarity', 'common'), '')} · "
                f"{pcore.hourly_rate(p['pet_key'], p['level']):.1f} DC/ч"
            )
            options.append(SelectOption(
                label=label,
                description=desc[:100],
                value=p["pet_key"],
            ))
        super().__init__(
            placeholder="Выбери питомца → карточка",
            min_values=1, max_values=1,
            options=options, custom_id="pet_my:select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await _on_select_my(inter)


class MyPetsView(View):
    def __init__(self, pets):
        super().__init__(timeout=300)
        self.pets = pets
        if pets:
            self.add_item(MyPetsSelect(pets))

    @disnake.ui.button(label=_pad("Забрать", 1, 2), style=ButtonStyle.success,
                       custom_id="pet_my:claim", emoji="💰", row=1)
    async def claim(self, button, inter: disnake.MessageInteraction):
        await _claim_income(inter)

    @disnake.ui.button(label=_pad("Покормить"), style=ButtonStyle.gray,
                       custom_id="pet_my:feed", emoji="🍖", row=1)
    async def feed(self, button, inter: disnake.MessageInteraction):
        await _feed_active(inter)


# ============================================================
# СЕЛЕКТ "КАТАЛОГ"
# ============================================================
class CatalogSelect(Select):
    def __init__(self, owned_keys):
        options = []
        for key, cat in pcore.CATALOG.items():
            owned = key in owned_keys
            price = cat["price_dc"]
            label = f"{cat['name']} · {price} DC"
            if len(label) > 90:
                label = label[:87] + "..."
            if owned:
                desc = "Уже у тебя"
            else:
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
            placeholder="Выбери питомца → купить или подарить",
            min_values=1, max_values=1,
            options=options, custom_id="pet_cat:select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        await _on_select_catalog(inter)


class CatalogView(View):
    def __init__(self, owned_keys):
        super().__init__(timeout=300)
        self.owned_keys = owned_keys
        self.add_item(CatalogSelect(owned_keys))


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
                    label=f"ID получателя · цена {price} DC",
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
        await inter.followup.send(
            f"🎁 Питомец **{cat.get('name', '—')}** подарен "
            f"<@{recipient_id}>!\n> **Списано:** `{price} DC` (с комиссией 10%)",
            ephemeral=True,
        )

        # Обновляем каталог
        balance = _get_balance(inter.author.id)
        owned = [p["pet_key"] for p in pcore.get_user_pets(inter.author.id)]
        buf = await asyncio.to_thread(
            prender.render_catalog, inter.author.id, balance, owned, None
        )
        await _display_screen(inter, buf, f"pet_cat_{inter.author.id}.png",
                              CatalogView(owned))


# ============================================================
# КНОПКИ ПОСЛЕ ВЫБОРА ПИТОМЦА В КАТАЛОГЕ
# ============================================================
class CatalogPetActionView(View):
    def __init__(self, pet_key: str, can_buy: bool, owned: bool):
        super().__init__(timeout=300)
        self.pet_key = pet_key

        cat = pcore.CATALOG.get(pet_key, {})
        price = cat.get("price_dc", 0)
        gift_price_val = pcore.gift_price(pet_key)

        # Купить — если не куплено и хватает DC
        if not owned:
            btn_buy = Button(
                label=_pad(f"Купить {price}", 1, 1),
                style=ButtonStyle.success,
                custom_id=f"pet_buy:{pet_key}",
                emoji="💎",
                row=0,
                disabled=not can_buy,
            )
            btn_buy.callback = self.buy
            self.add_item(btn_buy)

            # Подарить — всегда доступно, если не куплено
            btn_gift = Button(
                label=_pad(f"Подарить {gift_price_val}", 1, 1),
                style=ButtonStyle.primary,
                custom_id=f"pet_gift:{pet_key}",
                emoji="🎁",
                row=0,
            )
            btn_gift.callback = self.gift
            self.add_item(btn_gift)

        # Показать карточку питомца (превью)
        btn_preview = Button(
            label=_pad("Карточка"),
            style=ButtonStyle.gray,
            custom_id=f"pet_preview:{pet_key}",
            emoji="📄",
            row=0,
        )
        btn_preview.callback = self.preview
        self.add_item(btn_preview)

    async def buy(self, inter: disnake.MessageInteraction):
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

        result = await pcore.buy_pet(inter.bot, inter.author.id, self.pet_key)
        if not result.get("ok"):
            return await inter.followup.send(
                f"❌ {result.get('error', 'Ошибка')}", ephemeral=True
            )

        cat = pcore.CATALOG.get(self.pet_key, {})
        await inter.followup.send(
            f"✅ Питомец **{cat.get('name', '—')}** куплен!", ephemeral=True
        )

        balance = _get_balance(inter.author.id)
        owned = [p["pet_key"] for p in pcore.get_user_pets(inter.author.id)]
        buf = await asyncio.to_thread(
            prender.render_catalog, inter.author.id, balance, owned, None
        )
        await _display_screen(inter, buf, f"pet_cat_{inter.author.id}.png",
                              CatalogView(owned))

    async def gift(self, inter: disnake.MessageInteraction):
        try:
            await inter.response.send_modal(GiftPetModal(self.pet_key))
        except Exception as e:
            logger.warning(f"gift modal: {e}")

    async def preview(self, inter: disnake.MessageInteraction):
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

        user_id = inter.author.id
        balance = _get_balance(user_id)
        cat = pcore.CATALOG.get(self.pet_key, {})

        # Фейковый питомец для превью
        fake_pet = {
            "pet_key": self.pet_key,
            "level": 1,
            "xp": 0,
            "pending_dc": 0,
            "last_income": 0,
            "purchased_at": 0,
            "is_active": False,
        }
        buf = await asyncio.to_thread(
            prender.render_pet_card, user_id, balance, fake_pet, None
        )
        fname = f"pet_preview_{user_id}_{self.pet_key}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")

        # Возвращаемся к каталогу с подсветкой
        view = _PreviewBackView()
        await inter.followup.send(embed=e, file=file, view=view, ephemeral=True)


class _PreviewBackView(View):
    def __init__(self):
        super().__init__(timeout=300)

    @disnake.ui.button(label=_pad("К каталогу"), style=ButtonStyle.gray,
                       custom_id="pet_preview_back:cat", emoji="⬅️", row=0)
    async def back(self, button, inter: disnake.MessageInteraction):
        await _open_catalog(inter)


# ============================================================
# КАРТОЧКА ИЗ "МОИ ПИТОМЦЫ"
# ============================================================
class MyPetCardView(View):
    def __init__(self, pet_key: str, is_active: bool):
        super().__init__(timeout=300)
        self.pet_key = pet_key

        if not is_active:
            btn = Button(
                label=_pad("Активным"),
                style=ButtonStyle.primary,
                custom_id=f"pet_setactive:{pet_key}",
                emoji="⭐",
                row=0,
            )
            btn.callback = self.set_active
            self.add_item(btn)

        btn_back = Button(
            label=_pad("К питомцам"),
            style=ButtonStyle.gray,
            custom_id=f"pet_back:my",
            emoji="⬅️",
            row=0,
        )
        btn_back.callback = self.back
        self.add_item(btn_back)

    async def set_active(self, inter: disnake.MessageInteraction):
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass
        result = pcore.set_active_pet(inter.author.id, self.pet_key)
        if not result.get("ok"):
            return await inter.followup.send(
                f"❌ {result.get('error', 'Ошибка')}", ephemeral=True
            )
        await inter.followup.send("⭐ Питомец сделан активным!", ephemeral=True)
        await _open_my_pets(inter)

    async def back(self, inter: disnake.MessageInteraction):
        await _open_my_pets(inter)


# ============================================================
# ТОП
# ============================================================
class TopView(View):
    def __init__(self):
        super().__init__(timeout=300)


# ============================================================
# ХЕЛПЕР ОТПРАВКИ
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


# ============================================================
# ОТКРЫТИЕ ЭКРАНОВ
# ============================================================
async def _open_my_pets(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    balance = _get_balance(user_id)
    pets = pcore.get_user_pets(user_id)
    swap_cd = pcore.get_swap_cooldown_left(user_id)
    buf = await asyncio.to_thread(
        prender.render_my_pets, user_id, balance, pets, swap_cd
    )
    await _display_screen(inter, buf, f"pet_my_{user_id}.png", MyPetsView(pets))


async def _open_catalog(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    balance = _get_balance(user_id)
    owned = [p["pet_key"] for p in pcore.get_user_pets(user_id)]
    buf = await asyncio.to_thread(
        prender.render_catalog, user_id, balance, owned, None
    )
    await _display_screen(inter, buf, f"pet_cat_{user_id}.png", CatalogView(owned))


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


# ============================================================
# СЕЛЕКТ-КАЛБЭКИ
# ============================================================
async def _on_select_my(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    pet_key = inter.data.values[0]
    user_id = inter.author.id
    pet = pcore.get_pet_by_key(user_id, pet_key)
    if not pet:
        return
    balance = _get_balance(user_id)
    place = pcore.get_user_place(user_id)
    buf = await asyncio.to_thread(
        prender.render_pet_card, user_id, balance, pet, place
    )
    fname = f"pet_card_{user_id}_{pet_key}.png"
    await _display_screen(
        inter, buf, fname,
        MyPetCardView(pet_key, bool(pet.get("is_active")))
    )


async def _on_select_catalog(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    pet_key = inter.data.values[0]
    user_id = inter.author.id
    owned = pcore.has_pet(user_id, pet_key)
    cat = pcore.CATALOG.get(pet_key, {})
    balance = _get_balance(user_id)
    can_buy = (not owned) and balance >= cat.get("price_dc", 0)

    # Рендерим каталог с подсветкой выбранного + view с действиями
    full_owned = [p["pet_key"] for p in pcore.get_user_pets(user_id)]
    buf = await asyncio.to_thread(
        prender.render_catalog, user_id, balance, full_owned, pet_key
    )
    fname = f"pet_cat_{user_id}_{pet_key}.png"

    view = _CatalogSelectWithActions(owned_list=full_owned,
                                     pet_key=pet_key,
                                     can_buy=can_buy,
                                     owned=owned)
    await _display_screen(inter, buf, fname, view)


# ============================================================
# ОБЪЕДИНЁННЫЙ VIEW: селект + кнопки действий
# ============================================================
class _CatalogSelectWithActions(View):
    def __init__(self, owned_list, pet_key, can_buy, owned):
        super().__init__(timeout=300)
        self.owned_list = owned_list
        self.pet_key = pet_key
        self.can_buy = can_buy
        self.owned = owned

        # Селект на первой строке
        self.add_item(CatalogSelect(owned_list))

        cat = pcore.CATALOG.get(pet_key, {})
        price = cat.get("price_dc", 0)
        gift_price_val = pcore.gift_price(pet_key)

        # Кнопки действий на второй строке
        if not owned:
            btn_buy = Button(
                label=_pad(f"Купить {price}", 1, 1),
                style=ButtonStyle.success,
                custom_id=f"pet_buy2:{pet_key}",
                emoji="💎",
                row=1,
                disabled=not can_buy,
            )
            btn_buy.callback = self._buy
            self.add_item(btn_buy)

            btn_gift = Button(
                label=_pad(f"Подарить {gift_price_val}", 1, 1),
                style=ButtonStyle.primary,
                custom_id=f"pet_gift2:{pet_key}",
                emoji="🎁",
                row=1,
            )
            btn_gift.callback = self._gift
            self.add_item(btn_gift)

        btn_preview = Button(
            label=_pad("Карточка"),
            style=ButtonStyle.gray,
            custom_id=f"pet_prev2:{pet_key}",
            emoji="📄",
            row=1,
        )
        btn_preview.callback = self._preview
        self.add_item(btn_preview)

    async def _buy(self, inter: disnake.MessageInteraction):
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass
        result = await pcore.buy_pet(inter.bot, inter.author.id, self.pet_key)
        if not result.get("ok"):
            return await inter.followup.send(
                f"❌ {result.get('error', 'Ошибка')}", ephemeral=True
            )
        cat = pcore.CATALOG.get(self.pet_key, {})
        await inter.followup.send(
            f"✅ Питомец **{cat.get('name', '—')}** куплен!", ephemeral=True
        )
        await _open_catalog(inter)

    async def _gift(self, inter: disnake.MessageInteraction):
        try:
            await inter.response.send_modal(GiftPetModal(self.pet_key))
        except Exception as e:
            logger.warning(f"gift modal: {e}")

    async def _preview(self, inter: disnake.MessageInteraction):
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

        user_id = inter.author.id
        balance = _get_balance(user_id)
        fake_pet = {
            "pet_key": self.pet_key,
            "level": 1,
            "xp": 0,
            "pending_dc": 0,
            "last_income": 0,
            "purchased_at": 0,
            "is_active": False,
        }
        buf = await asyncio.to_thread(
            prender.render_pet_card, user_id, balance, fake_pet, None
        )
        fname = f"pet_preview_{user_id}_{self.pet_key}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        await inter.followup.send(
            embed=e, file=file, view=_PreviewBackView(), ephemeral=True
        )
