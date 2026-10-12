# -*- coding: utf-8 -*-
"""Discord UI для панели питомцев — только селекты, все эфемерки заменяются."""
import asyncio

import disnake
from disnake import ButtonStyle, SelectOption
from disnake.ui import View, Select, Modal, TextInput

from core.utils import logger
from pet import core as pcore
from pet import render as prender


# ============================================================
# ХЕЛПЕР: единая отправка/редактирование
# ============================================================
def _is_ephemeral_message(inter: disnake.MessageInteraction) -> bool:
    try:
        msg = inter.message
        if msg is None:
            return False
        flags = getattr(msg, "flags", None)
        return bool(getattr(flags, "ephemeral", False)) if flags else False
    except Exception:
        return False


async def _display(inter, buf, fname: str, view: View):
    """
    Всегда редактирует текущее эфемерное сообщение.
    Если первый вызов из панели канала — отправляет новое эфемерное.
    """
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
# ПАНЕЛЬ В КАНАЛЕ
# ============================================================
class PetPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="ㅤㅤ🐾 Питомцыㅤㅤ", style=ButtonStyle.gray,
                       custom_id="pet_panel:my", row=0)
    async def my_pets(self, button, inter: disnake.MessageInteraction):
        await _open_my_pets(inter)

    @disnake.ui.button(label="ㅤㅤ📖 Каталогㅤㅤ", style=ButtonStyle.gray,
                       custom_id="pet_panel:catalog", row=0)
    async def catalog(self, button, inter: disnake.MessageInteraction):
        await _open_catalog(inter)

    @disnake.ui.button(label="ㅤㅤ🏆 Топㅤㅤ", style=ButtonStyle.gray,
                       custom_id="pet_panel:top", row=0)
    async def top(self, button, inter: disnake.MessageInteraction):
        await _open_top(inter)


# ============================================================
# ЭКРАН "МОИ ПИТОМЦЫ" — селект с 2 действиями
# ============================================================
class MyPetsActionSelect(Select):
    def __init__(self, has_pets: bool, pending: int, has_active: bool):
        options = []
        if has_pets:
            options.append(SelectOption(
                label=f"Забрать доход · {pending} DC",
                description="Получить накопленное на баланс",
                emoji="💰",
                value="claim",
            ))
            options.append(SelectOption(
                label="Покормить активного",
                description="+100 XP за 200 DC · кулдаун 4 часа",
                emoji="🍖",
                value="feed",
                default=False,
            ))
        else:
            options.append(SelectOption(
                label="Нет питомцев",
                description="Открой каталог, чтобы купить первого",
                emoji="🐾",
                value="none",
            ))

        super().__init__(
            placeholder="Выбери действие с питомцами...",
            min_values=1, max_values=1,
            options=options, custom_id="pet_my_act:select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        action = inter.data.values[0]
        if action == "claim":
            await _claim_income(inter)
        elif action == "feed":
            await _feed_active(inter)


class MyPetsView(View):
    def __init__(self, has_pets: bool, pending: int, has_active: bool):
        super().__init__(timeout=300)
        self.add_item(MyPetsActionSelect(has_pets, pending, has_active))


# ============================================================
# ЭКРАН "КАТАЛОГ" — селект ТОЛЬКО с доступными питомцами
# ============================================================
class CatalogSelect(Select):
    def __init__(self, available_keys):
        options = []
        for key in available_keys:
            cat = pcore.CATALOG.get(key)
            if not cat:
                continue
            label = f"{cat['name']} · {cat['price_dc']} DC"
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

        if not options:
            options = [SelectOption(label="Всё куплено", value="none", default=True)]

        super().__init__(
            placeholder="Выбери питомца — откроется карточка...",
            min_values=1, max_values=1,
            options=options, custom_id="pet_cat:select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        pet_key = inter.data.values[0]
        if pet_key == "none":
            try:
                await inter.response.defer(ephemeral=True)
            except Exception:
                pass
            return
        await _open_catalog_item(inter, pet_key)


class CatalogView(View):
    def __init__(self, available_keys):
        super().__init__(timeout=300)
        self.add_item(CatalogSelect(available_keys))


# ============================================================
# КАРТОЧКА ТОВАРА — селект с 2 действиями
# ============================================================
class CatalogItemActionSelect(Select):
    def __init__(self, pet_key: str):
        self.pet_key = pet_key
        cat = pcore.CATALOG.get(pet_key, {})
        price = cat.get("price_dc", 0)
        gift_price_val = pcore.gift_price(pet_key)

        options = [
            SelectOption(
                label=f"Купить себе · {price} DC",
                description="Оформить питомца на свой аккаунт",
                emoji="💎",
                value="buy",
            ),
            SelectOption(
                label=f"Подарить · {gift_price_val} DC",
                description="Отправить питомца другому участнику (+10% комиссия)",
                emoji="🎁",
                value="gift",
            ),
            SelectOption(
                label="Назад в каталог",
                description="Вернуться к списку питомцев",
                emoji="⬅️",
                value="back",
            ),
        ]

        super().__init__(
            placeholder="Что сделать с питомцем?",
            min_values=1, max_values=1,
            options=options, custom_id=f"pet_item_act:{pet_key}",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        action = inter.data.values[0]
        if action == "buy":
            await _do_buy(inter, self.pet_key)
        elif action == "gift":
            try:
                await inter.response.send_modal(GiftPetModal(self.pet_key))
            except Exception as e:
                logger.warning(f"gift modal: {e}")
        elif action == "back":
            await _open_catalog(inter)


class CatalogItemView(View):
    def __init__(self, pet_key: str):
        super().__init__(timeout=300)
        self.add_item(CatalogItemActionSelect(pet_key))


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

        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

        result = await pcore.gift_pet(
            inter.bot, inter.author.id, int(raw), self.pet_key
        )

        if not result.get("ok"):
            return await inter.followup.send(
                f"❌ {result.get('error', 'Ошибка')}", ephemeral=True
            )

        cat = pcore.CATALOG.get(self.pet_key, {})
        price = result.get("price", 0)
        await inter.followup.send(
            f"🎁 Питомец **{cat.get('name', '—')}** подарен <@{raw}>!\n"
            f"> **Списано:** `{price} DC` (с комиссией 10%)",
            ephemeral=True,
        )

        # Возврат в каталог — редактируем текущее эфемерное
        await _open_catalog(inter)


# ============================================================
# ЭКРАН "ТОП"
# ============================================================
class TopView(View):
    def __init__(self):
        super().__init__(timeout=300)


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
    total_pending = sum((p.get("pending_dc") or 0) for p in pets)
    active = next((p for p in pets if p.get("is_active")), None)

    buf = await asyncio.to_thread(
        prender.render_my_pets, user_id, balance, pets, swap_cd
    )

    view = MyPetsView(
        has_pets=bool(pets),
        pending=total_pending,
        has_active=bool(active),
    )
    await _display(inter, buf, f"pet_my_{user_id}.png", view)


async def _open_catalog(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    user_id = inter.author.id
    balance = _get_balance(user_id)
    owned = [p["pet_key"] for p in pcore.get_user_pets(user_id)]
    available = [k for k in pcore.CATALOG.keys() if k not in owned]

    buf = await asyncio.to_thread(
        prender.render_catalog, user_id, balance, owned, available
    )
    view = CatalogView(available)
    await _display(inter, buf, f"pet_cat_{user_id}.png", view)


async def _open_catalog_item(inter: disnake.MessageInteraction, pet_key: str):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    user_id = inter.author.id
    balance = _get_balance(user_id)
    cat = pcore.CATALOG.get(pet_key, {})

    fake_pet = {
        "pet_key": pet_key,
        "level": 1,
        "xp": 0,
        "pending_dc": 0,
        "last_income": 0,
        "purchased_at": 0,
        "is_active": False,
    }

    buf = await asyncio.to_thread(
        prender.render_pet_card, user_id, balance, fake_pet, None, True
    )
    view = CatalogItemView(pet_key)
    await _display(inter, buf, f"pet_item_{user_id}_{pet_key}.png", view)


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
    await _display(inter, buf, f"pet_top_{user_id}.png", TopView())


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

    # Обновляем экран "мои питомцы" — редактируем эфемерное
    pets = pcore.get_user_pets(user_id)
    balance = _get_balance(user_id)
    swap_cd = pcore.get_swap_cooldown_left(user_id)
    total_pending = sum((p.get("pending_dc") or 0) for p in pets)
    active = next((p for p in pets if p.get("is_active")), None)

    buf = await asyncio.to_thread(
        prender.render_my_pets, user_id, balance, pets, swap_cd
    )
    view = MyPetsView(bool(pets), total_pending, bool(active))
    await _display(inter, buf, f"pet_my_{user_id}.png", view)


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

    # Обновляем экран
    pets = pcore.get_user_pets(user_id)
    balance = _get_balance(user_id)
    swap_cd = pcore.get_swap_cooldown_left(user_id)
    total_pending = sum((p.get("pending_dc") or 0) for p in pets)
    active = next((p for p in pets if p.get("is_active")), None)

    buf = await asyncio.to_thread(
        prender.render_my_pets, user_id, balance, pets, swap_cd
    )
    view = MyPetsView(bool(pets), total_pending, bool(active))
    await _display(inter, buf, f"pet_my_{user_id}.png", view)


async def _do_buy(inter: disnake.MessageInteraction, pet_key: str):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    result = await pcore.buy_pet(inter.bot, inter.author.id, pet_key)

    if not result.get("ok"):
        return await inter.followup.send(
            f"❌ {result.get('error', 'Ошибка')}", ephemeral=True
        )

    cat = pcore.CATALOG.get(pet_key, {})
    await inter.followup.send(
        f"✅ Питомец **{cat.get('name', '—')}** куплен!", ephemeral=True
    )

    # Возвращаемся в каталог
    await _open_catalog(inter)
