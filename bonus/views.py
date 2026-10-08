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


# ============================================================
# ХЕЛПЕР: ПАДДИНГ ПОДПИСЕЙ ДО РОВНОЙ ДЛИНЫ
# ============================================================
def _btn_pad(text: str, total: int) -> str:
    """Добивает подпись невидимыми пробелами до ровно `total` символов."""
    base = len(text)
    extra = max(0, total - base)
    left = extra // 2
    right = extra - left
    return f"{P * left}{text}{P * right}"


def _btn_labels_total(labels, total):
    """Раскидывает невидимые пробелы так, чтобы СУММА длин == total."""
    base = sum(len(s) for s in labels)
    extra = max(0, total - base)
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


# Сумарно 78 символов на 2 кнопки — «вровень с эмбедом»
_L_AGAIN, _L_MYCASES = _btn_labels_total(["Купить ещё", "Мои кейсы"], 32)


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


# ============================================================
# СЕЛЕКТ ПАНЕЛИ
# ============================================================
class BonusSelect(Select):
    def __init__(self):
        options = [
            SelectOption(label="Акция дня", description="Скидка дня на товар — торопись",
                         emoji="🔥", value="deal"),
            SelectOption(label="Реферальная система", description="Приглашай друзей — получай DC",
                         emoji="👥", value="ref"),
            SelectOption(label="Кейсы", description="Испытай удачу — забери ценный приз",
                         emoji="🎰", value="cases"),
        ]
        super().__init__(
            placeholder="🎁 Выбери раздел бонусов...",
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


# ============================================================
# ЭФЕМЕРНЫЕ ЭКРАНЫ
# ============================================================
async def _open_screen(inter, screen):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    if inter.author.id != SUPREME_USER_ID and not bcore.has_bonus_access(inter.author):
        try:
            await inter.followup.send(
                "⛔ Доступ только с ролью <@&1284697274655576186>.",
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
        await inter.edit_original_response(
            embeds=embeds, file=file, attachments=[], view=view,
        )
    except Exception as e:
        logger.exception(f"bonus switch: {e}")


async def _build_payload(inter, screen):
    user_id = inter.author.id

    # ─── АКЦИЯ ДНЯ ───
    if screen == "deal":
        balance = await get_user_balance(user_id)
        from modules.actions import refresh_daily_deal
        deal = refresh_daily_deal()
        import time as _t
        slot_sec = 5 * 3600
        next_ts = ((int(_t.time()) // slot_sec) + 1) * slot_sec
        hours_left = max((next_ts - int(_t.time())) // 3600, 0)

        buf = await asyncio.to_thread(
            brender.render_daily_deal, user_id, balance, deal, hours_left,
        )
        fname = f"bonus_deal_{user_id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")

        view = DealView(deal) if deal else DealNoDealView()
        return [e], file, view

    # ─── РЕФ ───
    if screen == "ref":
        link = await bcore.ensure_user_ref_link(inter.bot, user_id)
        if not link:
            return None, None, None

        stats = bcore.get_user_ref_stats(user_id)
        buf = await asyncio.to_thread(
            brender.render_ref_panel, user_id, inter.author.display_name, stats,
            link.get("invite_url"),
        )
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
                f"> За каждого друга, кто проживёт **1 час** и больше — "
                f"получаешь **100 DC** + **100 DC** в копилку клана."
            ),
            color=6776679,
        )
        e2.set_image(url=IMG_STRIPE)

        view = View(timeout=300)
        return [e1, e2], file, view

    # ─── КЕЙСЫ ───
    if screen == "cases":
        balance = await get_user_balance(user_id)
        stats = bcore.get_case_stats(user_id)
        buf = await asyncio.to_thread(
            brender.render_cases, user_id, inter.author.display_name, balance, stats,
        )
        fname = f"bonus_cases_{user_id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")

        view = CasesSelectView()
        return [e], file, view

    # ─── МОИ КЕЙСЫ ───
    if screen == "mycases":
        stats = bcore.get_case_stats(user_id)
        history = bcore.get_case_history(user_id, limit=8)
        buf = await asyncio.to_thread(
            brender.render_my_cases, user_id, inter.author.display_name, stats, history,
        )
        fname = f"bonus_mycases_{user_id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")

        view = MyCasesBackView()
        return [e], file, view

    return None, None, None


# ============================================================
# VIEW: АКЦИЯ ДНЯ
# ============================================================
class DealView(View):
    def __init__(self, deal):
        super().__init__(timeout=300)
        self.deal = deal
        price = deal.get("new_price", 0)
        lbl = _btn_pad(f"Купить за {price} DC", 45)

        btn = Button(
            label=lbl,
            style=ButtonStyle.secondary,
            custom_id="bonus_deal:buy",
            emoji=PartialEmoji(name="prize", id=1539657202170859561),
            row=0,
        )
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
                    return await inter.followup.send(
                        f"⛔ Роль «{name}» уже у тебя на аккаунте.",
                        ephemeral=True,
                    )
            except Exception:
                pass

        balance = await get_user_balance(inter.author.id)
        if balance < price:
            return await inter.followup.send(
                f"❌ Недостаточно DC. Нужно {price}, у тебя {balance}.",
                ephemeral=True,
            )

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
                description=(
                    f"> **Юзер:** {inter.author.mention}\n"
                    f"> **Товар:** {name}\n"
                    f"> **Цена:** {price} DC\n"
                    f"> **Тип:** {kind}"
                ),
                color=0x00aaff,
                channel_id=bcore.CONFIG["LOG_TICKET_CHANNEL_ID"],
            )
        except Exception:
            pass

        outcome = {
            "kind": kind,
            "name": name,
            "price": price,
            "role_name": role_name,
        }

        try:
            buf = await asyncio.to_thread(
                brender.render_deal_success, inter.author.id, self.deal, outcome,
            )
            fname = f"bonus_deal_ok_{inter.author.id}.png"
            file = disnake.File(buf, filename=fname)
            e = disnake.Embed(color=6776679)
            e.set_image(url=f"attachment://{fname}")

            await inter.edit_original_response(
                embeds=[e], file=file, attachments=[], view=None,
            )
        except Exception as e:
            logger.exception(f"deal success render: {e}")
            await inter.followup.send(
                f"✅ Куплено! {name} · {price} DC",
                ephemeral=True,
            )


class DealNoDealView(View):
    def __init__(self):
        super().__init__(timeout=300)


# ============================================================
# VIEW: ВЫБОР КЕЙСА (СЕЛЕКТ)
# ============================================================
CASE_EMOJI = {
    1: "🎁",
    2: "💰",
    3: "💎",
    4: "👑",
    5: "🏆",
}


class CaseSelect(Select):
    def __init__(self):
        from bonus.core import CASES
        options = []
        for case in CASES:
            desc = (case.get("desc") or "").strip()
            if len(desc) > 95:
                desc = desc[:92] + "..."
            options.append(SelectOption(
                label=f"{case['name']} · {case['price']} DC",
                description=desc or f"Кейс за {case['price']} DC",
                emoji=CASE_EMOJI.get(case["num"], "🎁"),
                value=str(case["num"]),
            ))
        super().__init__(
            placeholder="🎰 Выбери кейс для открытия...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="bonus_case_select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        try:
            case_num = int(inter.data.values[0])
        except Exception:
            return
        await _open_case(inter, case_num)


class CasesSelectView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(CaseSelect())


# ============================================================
# VIEW: ПОСЛЕ КЕЙСА (кнопки вровень с эмбедом, не серые)
# ============================================================
class CaseAfterView(View):
    def __init__(self):
        super().__init__(timeout=300)

        btn_again = Button(
            label=_L_AGAIN,
            style=ButtonStyle.success,
            custom_id="bonus_after:again",
            emoji=PartialEmoji(name="prize", id=1539657202170859561),
            row=0,
        )
        btn_again.callback = self._again
        self.add_item(btn_again)

        btn_my = Button(
            label=_L_MYCASES,
            style=ButtonStyle.primary,
            custom_id="bonus_after:mycases",
            emoji=PartialEmoji(name="cakleb", id=1553236134316875846),
            row=0,
        )
        btn_my.callback = self._mycases
        self.add_item(btn_my)

    async def _again(self, inter):
        await _switch(inter, "cases")

    async def _mycases(self, inter):
        await _switch(inter, "mycases")


class MyCasesBackView(View):
    def __init__(self):
        super().__init__(timeout=300)

        btn = Button(
            label=_btn_pad("К кейсам", 33),
            style=ButtonStyle.secondary,
            custom_id="bonus_mycases:back",
            row=0,
        )
        btn.callback = self._back
        self.add_item(btn)

    async def _back(self, inter):
        await _switch(inter, "cases")

# ============================================================
# ОТКРЫТИЕ КЕЙСА
# ============================================================
async def _open_case(inter, case_num: int):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    case = bcore.CASES_BY_NUM.get(case_num)
    if not case:
        return await inter.followup.send("❌ Кейс не найден", ephemeral=True)

    balance = await get_user_balance(inter.author.id)
    if balance < case["price"]:
        return await inter.followup.send(
            f"❌ Нужно **{case['price']} DC**, у тебя **{balance} DC**.",
            ephemeral=True,
        )

    try:
        buf = await asyncio.to_thread(brender.render_spin, case)
        fname = f"bonus_spin_{inter.author.id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=None)
    except Exception as e:
        logger.exception(f"spin render: {e}")

    await asyncio.sleep(2.0)

    result = await bcore.open_case(inter.bot, inter.author.id, case_num)
    if not result["ok"]:
        return await inter.followup.send(
            f"❌ {result.get('error', 'Ошибка')}", ephemeral=True,
        )

    new_balance = await get_user_balance(inter.author.id)
    try:
        buf = await asyncio.to_thread(
            brender.render_result,
            case, result["prize"], result["desc"], new_balance,
        )
        fname = f"bonus_result_{inter.author.id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        await inter.edit_original_response(
            embeds=[e], file=file, attachments=[], view=CaseAfterView(),
        )
    except Exception as e:
        logger.exception(f"result render: {e}")
        await inter.followup.send(
            f"🎉 Выпало: **{result['desc']}**", ephemeral=True,
        )
