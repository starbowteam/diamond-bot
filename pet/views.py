# -*- coding: utf-8 -*-
"""Discord UI для панели питомцев."""
import asyncio
from datetime import datetime, timezone

import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption
from disnake.ui import View, Button, Select

from core.utils import logger, load_json, CONFIG
from pet import core as pcore
from pet import render as prender


P = "\u3164"

# Кнопки стали короче в 2 раза (было 28)
BTN_LEN = 14


def _btn_pad(text, total=BTN_LEN):
    """
    Паддинг невидимыми пробелами до total символов.
    Если текст уже длиннее — возвращаем как есть.
    """
    base = len(text)
    if base >= total:
        return text
    extra = total - base
    left = extra // 2
    right = extra - left
    return f"{P * left}{text}{P * right}"


def _btn_labels_total(labels, total):
    """
    Раскидывает невидимые пробелы так, чтобы СУММА длин всех кнопок == total.
    Если сумма уже больше — возвращаем как есть.
    """
    base = sum(len(s) for s in labels)
    if base >= total:
        return labels
    extra = total - base
    n = len(labels)
    if n == 0:
        return labels
    per = extra // n
    rem = extra % n
    result = []
    for i, s in enumerate(labels):
        pad = per + (1 if i < rem else 0)
        left = pad // 2
        right = pad - left
        result.append(f"{P * left}{s}{P * right}")
    return result


# Панель: 3 кнопки, суммарно 14 символов (было 28)
_L_PETS, _L_CATALOG, _L_TOP = _btn_labels_total(
    ["Питомцы", "Каталог", "Топ"], BTN_LEN
)


# ============================================================
# ПАНЕЛЬ В КАНАЛЕ
# ============================================================
class PetPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label=_L_PETS, style=ButtonStyle.gray,
                       custom_id="pet_panel:my", emoji="🐾", row=0)
    async def my_pets(self, button, inter: disnake.MessageInteraction):
        await _open_my_pets(inter)

    @disnake.ui.button(label=_L_CATALOG, style=ButtonStyle.gray,
                       custom_id="pet_panel:catalog", emoji="📖", row=0)
    async def catalog(self, button, inter: disnake.MessageInteraction):
        await _open_catalog(inter)

    @disnake.ui.button(label=_L_TOP, style=ButtonStyle.gray,
                       custom_id="pet_panel:top", emoji="🏆", row=0)
    async def top(self, button, inter: disnake.MessageInteraction):
        await _open_top(inter)


# ============================================================
# ЭКРАН "МОИ ПИТОМЦЫ"
# ============================================================
class MyPetsSelect(Select):
    def __init__(self, pets):
        options = []
        for p in pets[:25]:
            cat = pcore.CATALOG.get(p["pet_key"], {})
            label = f"{cat.get('name', '—')} · ур. {p['level']}"
            if len(label) > 90:
                label = label[:87] + "..."
            desc = f"{pcore.RARITY_LABEL.get(cat.get('rarity', 'common'), '')} · {pcore.hourly_rate(p['pet_key'], p['level']):.1f} DC/ч"
            options.append(SelectOption(
                label=label,
                description=desc[:100],
                value=p["pet_key"],
            ))
        super().__init__(placeholder="Выбери питомца → карточка",
                         min_values=1, max_values=1,
                         options=options, custom_id="pet_my:select")


class MyPetsView(View):
    def __init__(self, pets):
        super().__init__(timeout=300)
        self.pets = pets

        if pets:
            self.add_item(MyPetsSelect(pets))

    @disnake.ui.button(label=_btn_pad("Забрать"), style=ButtonStyle.success,
                       custom_id="pet_my:claim", emoji="💰", row=1)
    async def claim(self, button, inter: disnake.MessageInteraction):
        await _claim_income(inter)

    @disnake.ui.button(label=_btn_pad("Покормить"), style=ButtonStyle.gray,
                       custom_id="pet_my:feed", emoji="🍖", row=1)
    async def feed(self, button, inter: disnake.MessageInteraction):
        await _feed_active(inter)

    @disnake.ui.button(label=_btn_pad("Назад"), style=ButtonStyle.gray,
                       custom_id="pet_my:back", emoji="⬅️", row=1)
    async def back(self, button, inter: disnake.MessageInteraction):
        await _close_ephemeral(inter)


# ============================================================
# ЭКРАН "КАТАЛОГ"
# ============================================================
class CatalogSelect(Select):
    def __init__(self, owned_keys):
        options = []
        for key, cat in pcore.CATALOG.items():
            owned = key in owned_keys
            label = f"{cat['name']} · {cat['price_dc']} DC"
            if len(label) > 90:
                label = label[:87] + "..."
            if owned:
                desc = "Уже у тебя"
            else:
                desc = f"{pcore.RARITY_LABEL[cat['rarity']]} · +{cat['passive_dc']} DC/ч"
            options.append(SelectOption(
                label=label,
                description=desc[:100],
                value=key,
            ))
        super().__init__(placeholder="Выбери питомца для покупки",
                         min_values=1, max_values=1,
                         options=options, custom_id="pet_cat:select")


class CatalogView(View):
    def __init__(self, owned_keys):
        super().__init__(timeout=300)
        self.owned_keys = owned_keys
        self.add_item(CatalogSelect(owned_keys))

    @disnake.ui.button(label=_btn_pad("Назад"), style=ButtonStyle.gray,
                       custom_id="pet_cat:back", emoji="⬅️", row=1)
    async def back(self, button, inter: disnake.MessageInteraction):
        await _close_ephemeral(inter)


# ============================================================
# КАРТОЧКА (после выбора в каталоге)
# ============================================================
class CatalogPetView(View):
    def __init__(self, pet_key: str, can_buy: bool):
        super().__init__(timeout=300)
        self.pet_key = pet_key

        btn_buy = Button(
            label=_btn_pad("Купить"),
            style=ButtonStyle.success,
            custom_id=f"pet_buy:{pet_key}",
            emoji="💎",
            row=0,
            disabled=not can_buy,
        )
        btn_buy.callback = self.buy
        self.add_item(btn_buy)

        btn_back = Button(
            label=_btn_pad("Назад"),
            style=ButtonStyle.gray,
            custom_id=f"pet_cat_back:{pet_key}",
            emoji="⬅️",
            row=0,
        )
        btn_back.callback = self.back
        self.add_item(btn_back)

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
        await inter.followup.send(
            f"✅ Питомец **{pcore.CATALOG[self.pet_key]['name']}** куплен!",
            ephemeral=True
        )
        # Обновляем панель каталога — редактируем текущее эфемерное
        balance = _get_balance(inter.author.id)
        owned = [p["pet_key"] for p in pcore.get_user_pets(inter.author.id)]
        buf = await asyncio.to_thread(prender.render_catalog, inter.author.id, balance, owned)
        fname = f"pet_cat_{inter.author.id}.png"
        await _display_screen(inter, buf, fname, CatalogView(owned))

    async def back(self, inter: disnake.MessageInteraction):
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
                label=_btn_pad("Активным"),
                style=ButtonStyle.primary,
                custom_id=f"pet_setactive:{pet_key}",
                emoji="⭐",
                row=0,
            )
            btn.callback = self.set_active
            self.add_item(btn)

        btn_back = Button(
            label=_btn_pad("Назад"),
            style=ButtonStyle.gray,
            custom_id=f"pet_myback:{pet_key}",
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

    @disnake.ui.button(label=_btn_pad("Назад"), style=ButtonStyle.gray,
                       custom_id="pet_top:back", emoji="⬅️", row=0)
    async def back(self, button, inter: disnake.MessageInteraction):
        await _close_ephemeral(inter)


# ============================================================
# ГЛАВНЫЙ ХЕЛПЕР — правильно показать экран
# ============================================================
def _is_ephemeral_message(inter: disnake.MessageInteraction) -> bool:
    """Определяет, было ли сообщение, на котором нажали, эфемерным."""
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
    """
    Универсальная функция.
    · Если нажали на панель в канале (не эфемерно) → followup ephemeral
    · Если нажали внутри эфемерного → редактируем это же эфемерное
    """
    # Уже сделали defer в вызывающем коде
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


# ============================================================
# ОБРАБОТЧИКИ
# ============================================================
def _get_balance(user_id):
    from core.utils import get_dc_cache
    return get_dc_cache(user_id).get("balance", 0)


async def _open_my_pets(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    balance = _get_balance(user_id)
    pets = pcore.get_user_pets(user_id)
    swap_cd = pcore.get_swap_cooldown_left(user_id)
    buf = await asyncio.to_thread(prender.render_my_pets, user_id, balance, pets, swap_cd)
    await _display_screen(inter, buf, f"pet_my_{user_id}.png", MyPetsView(pets))


async def _open_catalog(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    balance = _get_balance(user_id)
    owned = [p["pet_key"] for p in pcore.get_user_pets(user_id)]
    buf = await asyncio.to_thread(prender.render_catalog, user_id, balance, owned)
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
    buf = await asyncio.to_thread(prender.render_top, user_id, balance, top, place)
    await _display_screen(inter, buf, f"pet_top_{user_id}.png", TopView())


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
        await inter.followup.send(f"❌ {result.get('error', 'Ошибка')}", ephemeral=True)
        return
    xp = result["xp"]
    msg = f"🍖 Питомец покормлен! **+{xp} XP**"
    if result.get("bonus_xp"):
        msg += f" (включая бонус за streak +{result['bonus_xp']})"
    await inter.followup.send(msg, ephemeral=True)
    await _open_my_pets(inter)


async def _close_ephemeral(inter: disnake.MessageInteraction):
    try:
        await inter.response.edit_message(content="Меню закрыто.", embed=None, attachments=[], view=None)
    except Exception:
        try:
            await inter.response.defer()
        except Exception:
            pass


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
    buf = await asyncio.to_thread(prender.render_pet_card, user_id, balance, pet, place)
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

    fake_pet = {
        "pet_key": pet_key,
        "level": 1,
        "xp": 0,
        "pending_dc": 0,
        "last_income": 0,
        "purchased_at": 0,
        "is_active": False,
    }
    buf = await asyncio.to_thread(prender.render_pet_card, user_id, balance, fake_pet, None)
    fname = f"pet_preview_{user_id}_{pet_key}.png"
    await _display_screen(inter, buf, fname, CatalogPetView(pet_key, can_buy))


# Привязываем колбэки к селектам
def _wire_selects():
    MyPetsSelect.callback = _on_select_my
    CatalogSelect.callback = _on_select_catalog


_wire_selects()
