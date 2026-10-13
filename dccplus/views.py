# -*- coding: utf-8 -*-
"""Discord UI для DCC+."""
import asyncio

import disnake
from disnake import ButtonStyle, SelectOption, PartialEmoji
from disnake.ui import View, Button, Select, Modal, TextInput

from core.utils import logger, CONFIG
from dccplus import core as dcc
from dccplus import render as dr


P = "\u3164"


def _pad(text: str, left: int = 2, right: int = 2) -> str:
    return f"{P * left}{text}{P * right}"


# ───────── ЭМОДЗИ КНОПОК (юникод — работают всегда) ─────────
E_MAIN    = "📈"
E_TRADE   = "🔄"
E_STAKE   = "🔒"
E_TOP     = "🏆"
E_HISTORY = "📜"


# ═══════════════════════════════════════════
# ГЛАВНАЯ ПАНЕЛЬ (в канале)
# ═══════════════════════════════════════════
class DCCPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label=_pad("Курс"), style=ButtonStyle.gray,
                       custom_id="dcc:main", emoji=E_MAIN, row=0)
    async def main(self, button, inter: disnake.MessageInteraction):
        await _open_main(inter)

    @disnake.ui.button(label=_pad("Обмен"), style=ButtonStyle.gray,
                       custom_id="dcc:trade", emoji=E_TRADE, row=0)
    async def trade(self, button, inter: disnake.MessageInteraction):
        await _open_trade(inter)

    @disnake.ui.button(label=_pad("Стейк"), style=ButtonStyle.gray,
                       custom_id="dcc:stake", emoji=E_STAKE, row=0)
    async def stake(self, button, inter: disnake.MessageInteraction):
        await _open_stake(inter)

    @disnake.ui.button(label=_pad("Топ"), style=ButtonStyle.gray,
                       custom_id="dcc:top", emoji=E_TOP, row=0)
    async def top(self, button, inter: disnake.MessageInteraction):
        await _open_top(inter)

    @disnake.ui.button(label=_pad("История"), style=ButtonStyle.gray,
                       custom_id="dcc:history", emoji=E_HISTORY, row=0)
    async def history(self, button, inter: disnake.MessageInteraction):
        await _open_history(inter)


# ═══════════════════════════════════════════
# СЕЛЕКТ ДЕЙСТВИЙ (главная + обмен)
# ═══════════════════════════════════════════
class MainActionSelect(Select):
    def __init__(self):
        options = [
            SelectOption(
                label="Мои активы",
                description="Портфель, PnL, стейки",
                emoji="💼",
                value="assets",
            ),
            SelectOption(
                label="Купить DCC+",
                description="Обменять DC → DCC+",
                emoji="💎",
                value="buy",
            ),
            SelectOption(
                label="Продать DCC+",
                description="Обменять DCC+ → DC (−3%)",
                emoji="💰",
                value="sell",
            ),
            SelectOption(
                label="Открыть стейк",
                description="Заблокировать DCC+ под %",
                emoji="🔒",
                value="stake",
            ),
        ]
        super().__init__(
            placeholder="Выбери действие...",
            min_values=1, max_values=1,
            options=options, custom_id="dcc_main_select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        v = inter.data.values[0]
        if v == "assets":
            await _open_assets(inter)
        elif v == "buy":
            await _open_trade(inter, mode="buy")
        elif v == "sell":
            await _open_trade(inter, mode="sell")
        elif v == "stake":
            await _open_stake(inter)


class MainView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(MainActionSelect())


# ═══════════════════════════════════════════
# СЕЛЕКТ ОБМЕНА (buy/sell + сумма)
# ═══════════════════════════════════════════
class TradeModeSelect(Select):
    def __init__(self, mode: str = "buy"):
        options = [
            SelectOption(
                label="💎 Купить DCC+",
                description="Обменять DC по текущему курсу",
                value="buy",
                default=(mode == "buy"),
            ),
            SelectOption(
                label="💰 Продать DCC+",
                description=f"Обменять DCC+ → DC (комиссия {int(dcc.SELL_COMMISSION*100)}%)",
                value="sell",
                default=(mode == "sell"),
            ),
        ]
        super().__init__(
            placeholder="Что сделать?",
            min_values=1, max_values=1,
            options=options, custom_id="dcc_trade_mode",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        mode = inter.data.values[0]
        await _open_trade(inter, mode=mode)


class TradeActionSelect(Select):
    def __init__(self, mode: str):
        if mode == "buy":
            options = [
                SelectOption(label="Купить на 1 000 DC", value="1000", emoji="💎"),
                SelectOption(label="Купить на 5 000 DC", value="5000", emoji="💎"),
                SelectOption(label="Купить на 10 000 DC", value="10000", emoji="💎"),
                SelectOption(label="Купить на 50 000 DC", value="50000", emoji="💎"),
                SelectOption(label="✏️ Своя сумма", value="custom", emoji="✏️"),
            ]
        else:
            options = [
                SelectOption(label="Продать 1 DCC+", value="1", emoji="💰"),
                SelectOption(label="Продать 5 DCC+", value="5", emoji="💰"),
                SelectOption(label="Продать 10 DCC+", value="10", emoji="💰"),
                SelectOption(label="Продать 50 DCC+", value="50", emoji="💰"),
                SelectOption(label="✏️ Своя сумма", value="custom", emoji="✏️"),
            ]
        super().__init__(
            placeholder="Выбери сумму...",
            min_values=1, max_values=1,
            options=options, custom_id=f"dcc_trade_action_{mode}",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        v = inter.data.values[0]
        mode = self.custom_id.split("_")[-1]

        if v == "custom":
            if mode == "buy":
                await inter.response.send_modal(BuyModal())
            else:
                await inter.response.send_modal(SellModal())
            return

        if mode == "buy":
            dc_amount = int(v)
            await _do_buy(inter, dc_amount)
        else:
            dcc_amount = float(v)
            await _do_sell(inter, dcc_amount)


class TradeView(View):
    def __init__(self, mode: str = "buy"):
        super().__init__(timeout=300)
        self.add_item(TradeModeSelect(mode))
        self.add_item(TradeActionSelect(mode))


# ═══════════════════════════════════════════
# СЕЛЕКТ СТЕЙКА
# ═══════════════════════════════════════════
class StakePlanSelect(Select):
    def __init__(self):
        options = [
            SelectOption(
                label=f"🔒 7 дней · +5%",
                description="Быстрый стейк, минимальный процент",
                value="7",
            ),
            SelectOption(
                label=f"💠 14 дней · +14%",
                description="Оптимальный баланс срока и профита",
                value="14",
            ),
            SelectOption(
                label=f"👑 30 дней · +35%",
                description="Максимум профита, держим долго",
                value="30",
            ),
        ]
        super().__init__(
            placeholder="Выбери срок стейка...",
            min_values=1, max_values=1,
            options=options, custom_id="dcc_stake_plan",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        days = int(inter.data.values[0])
        await inter.response.send_modal(StakeModal(days))


class StakeView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(StakePlanSelect())


# ═══════════════════════════════════════════
# МОДАЛКИ
# ═══════════════════════════════════════════
class BuyModal(Modal):
    def __init__(self):
        super().__init__(
            title="Купить DCC+",
            components=[
                TextInput(
                    label=f"Сколько DC потратить (от {dcc.MIN_BUY_DC})",
                    placeholder="Например: 5000",
                    custom_id="dc_amount",
                    min_length=1, max_length=10,
                ),
            ],
            custom_id="dcc_buy_modal",
        )

    async def callback(self, inter: disnake.ModalInteraction):
        raw = (self.text_values.get("dc_amount") or "").strip()
        if not raw.isdigit():
            return await inter.response.send_message("❌ Введи число.", ephemeral=True)
        dc_amount = int(raw)
        await _do_buy(inter, dc_amount, from_modal=True)


class SellModal(Modal):
    def __init__(self):
        super().__init__(
            title="Продать DCC+",
            components=[
                TextInput(
                    label="Сколько DCC+ продать",
                    placeholder="Например: 25.5",
                    custom_id="dcc_amount",
                    min_length=1, max_length=16,
                ),
            ],
            custom_id="dcc_sell_modal",
        )

    async def callback(self, inter: disnake.ModalInteraction):
        raw = (self.text_values.get("dcc_amount") or "").strip().replace(",", ".")
        try:
            dcc_amount = float(raw)
        except Exception:
            return await inter.response.send_message("❌ Введи число.", ephemeral=True)
        await _do_sell(inter, dcc_amount, from_modal=True)


class StakeModal(Modal):
    def __init__(self, days: int):
        self.days = days
        pct = int(dcc.STAKE_PLANS.get(days, 0) * 100)
        super().__init__(
            title=f"Стейк на {days} дней (+{pct}%)",
            components=[
                TextInput(
                    label=f"Сколько DCC+ застейкать (от {int(dcc.STAKE_MIN)})",
                    placeholder=f"Например: 100",
                    custom_id="amount",
                    min_length=1, max_length=16,
                ),
            ],
            custom_id=f"dcc_stake_modal_{days}",
        )

    async def callback(self, inter: disnake.ModalInteraction):
        raw = (self.text_values.get("amount") or "").strip().replace(",", ".")
        try:
            amount = float(raw)
        except Exception:
            return await inter.response.send_message("❌ Введи число.", ephemeral=True)

        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

        r = await dcc.create_stake(inter.author.id, amount, self.days)
        if not r.get("ok"):
            return await inter.followup.send(f"❌ {r.get('error')}", ephemeral=True)

        await inter.followup.send(
            f"🔒 Стейк на **{self.days} дней** создан!\n"
            f"> Застейкано: `{amount:.4f} DCC+`\n"
            f"> Профит: `+{int(r['profit_pct']*100)}%`\n"
            f"> Разлок: <t:{r['unlock_at']}:F>",
            ephemeral=True,
        )
        await _open_stake(inter)


# ═══════════════════════════════════════════
# ДЕЙСТВИЯ
# ═══════════════════════════════════════════
async def _do_buy(inter, dc_amount: int, from_modal: bool = False):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    r = await dcc.buy_dccplus(inter.author.id, dc_amount)
    if not r.get("ok"):
        return await inter.followup.send(f"❌ {r.get('error')}", ephemeral=True)

    await inter.followup.send(
        f"✅ Куплено!\n"
        f"> **DCC+:** `{r['dcc_amount']:.4f}`\n"
        f"> **Потрачено:** `{dc_amount} DC`\n"
        f"> **Курс:** `{r['price']:.2f} DC`",
        ephemeral=True,
    )
    await _open_main(inter)


async def _do_sell(inter, dcc_amount: float, from_modal: bool = False):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    r = await dcc.sell_dccplus(inter.author.id, dcc_amount)
    if not r.get("ok"):
        return await inter.followup.send(f"❌ {r.get('error')}", ephemeral=True)

    await inter.followup.send(
        f"✅ Продано!\n"
        f"> **DCC+:** `{r['dcc_amount']:.4f}`\n"
        f"> **Получено:** `{r['net_dc']} DC` (комиссия `{r['fee']:.0f}`)\n"
        f"> **Курс:** `{r['price']:.2f} DC`",
        ephemeral=True,
    )
    await _open_main(inter)


# ═══════════════════════════════════════════
# ОТКРЫТИЕ ЭКРАНОВ
# ═══════════════════════════════════════════
def _is_ephemeral(inter: disnake.MessageInteraction) -> bool:
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


async def _display(inter, buf, fname: str, view: View):
    file = disnake.File(buf, filename=fname)
    e = disnake.Embed(color=0x4dd0e1)
    e.set_image(url=f"attachment://{fname}")

    if _is_ephemeral(inter):
        try:
            await inter.edit_original_response(
                content=None, embed=e, file=file, attachments=[], view=view
            )
            return
        except Exception as ex:
            logger.warning(f"dcc edit_original: {ex}")

    try:
        await inter.followup.send(embed=e, file=file, view=view, ephemeral=True)
    except Exception as ex:
        logger.warning(f"dcc followup: {ex}")


async def _open_main(inter):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    buf = await asyncio.to_thread(dr.render_main, user_id)
    await _display(inter, buf, f"dcc_main_{user_id}.png", MainView())


async def _open_assets(inter):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    buf = await asyncio.to_thread(dr.render_my_assets, user_id)
    await _display(inter, buf, f"dcc_assets_{user_id}.png", MainView())


async def _open_trade(inter, mode: str = "buy"):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    buf = await asyncio.to_thread(dr.render_trade, user_id, mode, 0, 0.0)
    await _display(inter, buf, f"dcc_trade_{user_id}_{mode}.png",
                   TradeView(mode))


async def _open_stake(inter):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    buf = await asyncio.to_thread(dr.render_stake, user_id)
    await _display(inter, buf, f"dcc_stake_{user_id}.png", StakeView())


async def _open_top(inter):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    buf = await asyncio.to_thread(dr.render_top, user_id)
    await _display(inter, buf, f"dcc_top_{user_id}.png", MainView())


async def _open_history(inter):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass
    user_id = inter.author.id
    buf = await asyncio.to_thread(dr.render_history, user_id)
    await _display(inter, buf, f"dcc_hist_{user_id}.png", MainView())
