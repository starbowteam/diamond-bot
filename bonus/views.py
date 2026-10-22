# -*- coding: utf-8 -*-
"""Панель бонусов: селекты + эфемерные экраны."""

import asyncio
import os

import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption
from disnake.ui import View, Button, Select

from core.utils import logger, load_json
from modules.dc import get_user_balance, add_purchase, remove_dc
from bonus import core as bcore
from bonus import render as brender


P = "\u3164"

IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"

SUPREME_USER_ID = 796293832751972352

E_DEAL  = PartialEmoji(name="b1kns", id=1557755707854422088)
E_REF   = PartialEmoji(name="wmore", id=1552330925684162580)
E_TOP   = PartialEmoji(name="d1edf", id=1552730601155596348)
E_ADV   = PartialEmoji(name="reklama", id=1555654392202535073)
E_SHOP  = PartialEmoji(name="shop1", id=1555654407776112750)

def _btn_pad(text: str, total: int) -> str:
    base = len(text)
    extra = max(0, total - base)
    left = extra // 2
    right = extra - left
    return f"{P * left}{text}{P * right}"

def build_panel_embeds():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embed.json")
    data = load_json(path, {})
    if not data or "embeds" not in data:
        return [disnake.Embed(
            title="🎁 Бонусы Diamond",
            description="> Выбери раздел ниже.",
            color=6776679,
        )]
    return [disnake.Embed.from_dict(e) for e in data["embeds"]]


class BonusSelect(Select):
    def __init__(self):
        options = [
            SelectOption(label="Акция дня", description="Скидка дня на товар — торопись",
                         emoji=E_DEAL, value="deal"),
            SelectOption(label="Мои рефералы", description="Приглашай друзей — получай DC",
                         emoji=E_REF, value="ref"),
            SelectOption(label="Топы", description="Топ рефералов и адвайтеров",
                         emoji=E_TOP, value="top"),
        ]
        super().__init__(
            placeholder="Выбери желаемый раздел бонусов...",
            min_values=1, max_values=1,
            options=options,
            custom_id="bonus:select",
        )

    async def callback(self, inter):
        value = inter.data.values[0]
        await _open_screen(inter, value)


class BonusPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BonusSelect())


async def _open_screen(inter, screen):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    if inter.author.id != SUPREME_USER_ID and not bcore.has_bonus_access(inter.author):
        try:
            await inter.followup.send(
                "⛔ Доступ только с ролью <@&1284697274655576186> или Адвайтер.",
                ephemeral=True,
            )
        except Exception:
            pass
        return

    embeds, file, view = await _build_payload(inter, screen)
    if not embeds:
        try:
            await inter.followup.send("❌ Ошибка рендера", ephemeral=True)
        except Exception:
            pass
        return

    try:
        await inter.followup.send(embeds=embeds, file=file, view=view, ephemeral=True)
    except Exception as e:
        logger.exception(f"bonus open_screen: {e}")


async def _switch(inter, screen):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    embeds, file, view = await _build_payload(inter, screen)
    if not embeds:
        return
    try:
        await inter.edit_original_response(embeds=embeds, file=file, attachments=[], view=view)
    except Exception as e:
        logger.exception(f"bonus switch: {e}")


async def _build_payload(inter, screen):
    user_id = inter.author.id

    if screen == "deal":
        balance = await get_user_balance(user_id)
        from modules.actions import refresh_daily_deal
        deal = refresh_daily_deal()
        import time as _t
        slot_sec = 5 * 3600
        next_ts = ((int(_t.time()) // slot_sec) + 1) * slot_sec
        hours_left = max((next_ts - int(_t.time())) // 3600, 0)

        buf = await asyncio.to_thread(brender.render_daily_deal, user_id, balance, deal, hours_left)
        fname = f"bonus_deal_{user_id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        view = DealView(deal) if deal else DealNoDealView()
        return [e], file, view

    if screen == "ref":
        link = await bcore.ensure_user_ref_link(inter.bot, user_id)
        if not link:
            return None, None, None

        stats = bcore.get_user_ref_stats(user_id)
        buf = await asyncio.to_thread(brender.render_ref_panel, user_id, inter.author.display_name, stats, link.get("invite_url"))
        fname = f"bonus_ref_{user_id}.png"
        file = disnake.File(buf, filename=fname)

        e1 = disnake.Embed(color=6776679)
        e1.set_image(url=f"attachment://{fname}")

        url = link.get("invite_url", "—")
        e2 = disnake.Embed(
            title="📨 Твоя реферальная ссылка",
            description=(
                f"> Скопируй и делись:\n"
                f"```\n{url}\n```\n"
                f"> За каждого друга, кто проживёт **1 час** — получаешь **50 DC** + **50 DC** в копилку клана."
            ),
            color=6776679,
        )
        e2.set_image(url=IMG_STRIPE)
        view = View(timeout=300)
        return [e1, e2], file, view

    if screen == "top":
        # Возвращаем меню выбора топа
        e = disnake.Embed(
            title="🏆 Топы рефералов",
            description="> Выбери, какой топ ты хочешь посмотреть.",
            color=6776679
        )
        e.set_image(url=IMG_STRIPE)
        return [e], None, TopSelectView()

    if screen == "top_reg":
        top_list = bcore.get_top_referrals(is_advertiser=False, limit=10)
        buf = await asyncio.to_thread(brender.render_ref_top, user_id, inter.author.display_name, top_list, False)
        fname = f"bonus_top_reg_{user_id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        return [e], file, TopBackView()

    if screen == "top_adv":
        top_list = bcore.get_top_referrals(is_advertiser=True, limit=10)
        buf = await asyncio.to_thread(brender.render_ref_top, user_id, inter.author.display_name, top_list, True)
        fname = f"bonus_top_adv_{user_id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        return [e], file, TopBackView()

    return None, None, None


# ============================================================
# VIEW: АКЦИЯ ДНЯ
# ============================================================
class DealView(View):
    def __init__(self, deal):
        super().__init__(timeout=300)
        self.deal = deal
        price = deal.get("new_price", 0)
        lbl = _btn_pad(f"Купить за {price} DC", 36)

        btn = Button(label=lbl, style=ButtonStyle.secondary, custom_id="bonus_deal:buy", emoji=E_SHOP, row=0)
        btn.callback = self._buy
        self.add_item(btn)

    async def _buy(self, inter: disnake.MessageInteraction):
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

        item = self.deal.get("item_data", {})
        cat_key = self.deal.get("cat_key", "")
        item_key = self.deal.get("item_key", "")
        price = self.deal.get("new_price", 0)
        name = item.get("name", "—")
        role_id = item.get("role_id")

        guild = inter.guild
        member = inter.author

        if role_id and member is not None:
            try:
                if member.get_role(int(role_id)):
                    return await inter.followup.send(f"⛔ Роль «{name}» уже у тебя на аккаунте.", ephemeral=True)
            except Exception:
                pass

        balance = await get_user_balance(inter.author.id)
        if balance < price:
            return await inter.followup.send(f"❌ Недостаточно DC. Нужно {price}, у тебя {balance}.", ephemeral=True)

        ok = await remove_dc(inter.author.id, price, f"Акция дня: {name}")
        if not ok:
            return await inter.followup.send("❌ Ошибка списания", ephemeral=True)

        kind = "inventory"
        role_name = ""

        if cat_key == "roles" and role_id:
            kind = "role"
            try:
                role = guild.get_role(int(role_id))
                if role and role not in member.roles:
                    await member.add_roles(role, reason=f"Акция дня: {name}")
                role_name = role.name if role else name
            except Exception as e:
                logger.warning(f"deal auto role: {e}")
        elif item.get("boost_type"):
            kind = "boost"
            try:
                from core.utils import activate_item
                activate_item(
                    user_id=inter.author.id,
                    item_key=item_key,
                    item_type=cat_key,
                    value=float(item.get("value", 0) or 0),
                    duration_hours=int(item.get("duration_hours", 0) or 0),
                    uses=int(item.get("uses", -1)),
                )
            except Exception as e:
                logger.warning(f"deal boost: {e}")
        else:
            await add_purchase(inter.author.id, cat_key, name)

        try:
            await bcore.log_discord(
                title="🛒 Покупка по акции дня",
                description=f"> **Юзер:** {inter.author.mention}\n> **Товар:** {name}\n> **Цена:** {price} DC\n> **Тип:** {kind}",
                color=0x00aaff,
                channel_id=bcore.CONFIG["LOG_TICKET_CHANNEL_ID"],
            )
        except Exception:
            pass

        outcome = {"kind": kind, "name": name, "price": price, "role_name": role_name}

        try:
            from bonus import render_deal_success
            buf = await asyncio.to_thread(brender.render_deal_success, inter.author.id, self.deal, outcome)
            fname = f"bonus_deal_ok_{inter.author.id}.png"
            file = disnake.File(buf, filename=fname)
            e = disnake.Embed(color=6776679)
            e.set_image(url=f"attachment://{fname}")
            await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=None)
        except Exception as e:
            logger.exception(f"deal success render: {e}")
            await inter.followup.send(f"✅ Куплено! {name} · {price} DC", ephemeral=True)


class DealNoDealView(View):
    def __init__(self):
        super().__init__(timeout=300)


# ============================================================
# VIEW: ТОПЫ
# ============================================================
class TopSelect(Select):
    def __init__(self):
        options = [
            SelectOption(label="Топ рефералов", description="Обычные пользователи", emoji=E_TOP, value="top_reg"),
            SelectOption(label="Топ адвайтеров", description="Только для адвайтеров", emoji=E_ADV, value="top_adv"),
        ]
        super().__init__(placeholder="Какой топ показать?", min_values=1, max_values=1, options=options, custom_id="bonus_top_select")

    async def callback(self, inter: disnake.MessageInteraction):
        value = inter.data.values[0]
        await _switch(inter, value)


class TopSelectView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(TopSelect())


class TopBackView(View):
    def __init__(self):
        super().__init__(timeout=300)
        btn = Button(label=_btn_pad("Назад к топам", 30), style=ButtonStyle.secondary, custom_id="bonus_top:back", emoji=E_TOP)
        btn.callback = self._back
        self.add_item(btn)

    async def _back(self, inter):
        await _switch(inter, "top")
