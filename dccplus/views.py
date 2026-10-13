# -*- coding: utf-8 -*-
"""Discord UI для DCC+.

Всё управление — через селекты. Кнопок нет вообще.

Логика сообщений:
  · 1 публичная панель в канале (DCCPanelView).
  · Любой клик по селекту открывает ephemeral сообщение.
  · Все дальнейшие действия ПЕРЕЗАПИСЫВАЮТ это же ephemeral.
  · Исключение — модалки (ввод своей суммы): после модалки
    создаётся новое ephemeral, иначе Discord не даёт редактировать.
"""
import asyncio

import disnake
from disnake import SelectOption
from disnake.ui import View, Select, Modal, TextInput

from core.utils import logger, CONFIG
from dccplus import core as dcc
from dccplus import render as dr


# ═══════════════════════════════════════════
# РАЗДЕЛЫ DCC+
# ═══════════════════════════════════════════
SECTIONS = [
    ("main",    "📈 Курс",         "График, эмиссия, холдеры"),
    ("assets",  "💼 Мои активы",   "Портфель, PnL, стейки"),
    ("trade",   "💎 Обмен",        "Купить или продать DCC+"),
    ("stake",   "🔒 Стейк",        "Заблокировать DCC+ под %"),
    ("top",     "🏆 Топ",          "Топ-холдеры по DCC+"),
    ("history", "📜 История",      "Курс за 7 дней, сделки"),
]


# ═══════════════════════════════════════════
# УТИЛИТЫ
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
    """Показывает картинку. Если уже ephemeral — перезаписывает его."""
    try:
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
    except Exception as e:
        logger.exception(f"dcc _display: {e}")


# ═══════════════════════════════════════════
# СЕЛЕКТ РАЗДЕЛОВ — ОБЩИЙ ДЛЯ ВСЕХ ЭКРАНОВ
# ═══════════════════════════════════════════
class SectionSelect(Select):
    def __init__(self):
        options = [
            SelectOption(label=label, description=desc, value=key)
            for key, label, desc in SECTIONS
        ]
        super().__init__(
            placeholder="Выбери раздел DCC+...",
            min_values=1, max_values=1,
            options=options,
            custom_id="dcc_section_select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        section = inter.data.values[0]
        await _open_section(inter, section)


# ═══════════════════════════════════════════
# ГЛАВНАЯ ПАНЕЛЬ (публичная, в канале)
# ═══════════════════════════════════════════
class DCCPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SectionSelect())


# ═══════════════════════════════════════════
# VIEW ДЛЯ ГЛАВНОЙ / АКТИВОВ / ТОПА / ИСТОРИИ
# ═══════════════════════════════════════════
class MainView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(SectionSelect())


# ═══════════════════════════════════════════
# VIEW ДЛЯ ОБМЕНА
# ═══════════════════════════════════════════
class TradeActionSelect(Select):
    def __init__(self):
        options = [
            SelectOption(label="Купить на 1 000 DC",  value="buy_1000"),
            SelectOption(label="Купить на 5 000 DC",  value="buy_5000"),
            SelectOption(label="Купить на 10 000 DC", value="buy_10000"),
            SelectOption(label="Купить на 50 000 DC", value="buy_50000"),
            SelectOption(label="✏️ Своя сумма покупки", value="buy_custom"),
            SelectOption(label="Продать 1 DCC+",   value="sell_1"),
            SelectOption(label="Продать 5 DCC+",   value="sell_5"),
            SelectOption(label="Продать 10 DCC+",  value="sell_10"),
            SelectOption(label="Продать 50 DCC+",  value="sell_50"),
            SelectOption(label="✏️ Своя сумма продажи", value="sell_custom"),
        ]
        super().__init__(
            placeholder="Что сделать с DCC+?",
            min_values=1, max_values=1,
            options=options,
            custom_id="dcc_trade_action",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        v = inter.data.values[0]

        if v == "buy_custom":
            return await inter.response.send_modal(BuyModal())
        if v == "sell_custom":
            return await inter.response.send_modal(SellModal())

        action, _, raw = v.partition("_")
        if action == "buy":
            await _do_buy(inter, int(raw))
        else:
            await _do_sell(inter, float(raw))


class TradeView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(SectionSelect())
        self.add_item(TradeActionSelect())


# ═══════════════════════════════════════════
# VIEW ДЛЯ СТЕЙКА
# ═══════════════════════════════════════════
class StakePlanSelect(Select):
    def __init__(self):
        options = [
            SelectOption(label="7 дней · +5%",  description="Быстрый стейк, минимальный процент", value="7"),
            SelectOption(label="14 дней · +14%", description="Оптимальный баланс срока и профита", value="14"),
            SelectOption(label="30 дней · +35%", description="Максимум профита, держим долго",     value="30"),
        ]
        super().__init__(
            placeholder="Выбери срок стейка...",
            min_values=1, max_values=1,
            options=options,
            custom_id="dcc_stake_plan",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        days = int(inter.data.values[0])
        await inter.response.send_modal(StakeModal(days))


class StakeView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(SectionSelect())
        self.add_item(StakePlanSelect())


# ═══════════════════════════════════════════
# МОДАЛКИ (правильное обращение — inter.text_values)
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
        raw = (inter.text_values.get("dc_amount") or "").strip()
        if not raw.isdigit():
            return await inter.response.send_message("❌ Введи число.", ephemeral=True)
        await _do_buy(inter, int(raw))


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
        raw = (inter.text_values.get("dcc_amount") or "").strip().replace(",", ".")
        try:
            dcc_amount = float(raw)
        except Exception:
            return await inter.response.send_message("❌ Введи число.", ephemeral=True)
        await _do_sell(inter, dcc_amount)


class StakeModal(Modal):
    def __init__(self, days: int):
        self.days = days
        pct = int(dcc.STAKE_PLANS.get(days, 0) * 100)
        super().__init__(
            title=f"Стейк на {days} дней (+{pct}%)",
            components=[
                TextInput(
                    label=f"Сколько DCC+ застейкать (от {int(dcc.STAKE_MIN)})",
                    placeholder="Например: 100",
                    custom_id="amount",
                    min_length=1, max_length=16,
                ),
            ],
            custom_id=f"dcc_stake_modal_{days}",
        )

    async def callback(self, inter: disnake.ModalInteraction):
        raw = (inter.text_values.get("amount") or "").strip().replace(",", ".")
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

        # После модалки создаём новый экран (редактировать её сообщение нельзя)
        user_id = inter.author.id
        try:
            buf = await asyncio.to_thread(dr.render_stake, user_id)
            fname = f"dcc_stake_{user_id}.png"
            file = disnake.File(buf, filename=fname)
            e = disnake.Embed(color=0x4dd0e1)
            e.set_image(url=f"attachment://{fname}")
            e.description = (
                f"🔒 **Стейк на {self.days} дней создан!**\n"
                f"> Застейкано: `{amount:.4f} DCC+`\n"
                f"> Профит: `+{int(r['profit_pct']*100)}%`\n"
                f"> Разлок: <t:{r['unlock_at']}:F>"
            )
            await inter.followup.send(
                embed=e, file=file, view=StakeView(), ephemeral=True
            )
        except Exception as ex:
            logger.warning(f"stake success render: {ex}")
            await inter.followup.send(
                f"🔒 Стейк создан на {self.days} дней, `{amount:.4f} DCC+`",
                ephemeral=True,
            )


# ═══════════════════════════════════════════
# ДЕЙСТВИЯ (общий рендер для селекта и модалки)
# ═══════════════════════════════════════════
async def _render_main_with_flash(inter, flash_text: str):
    """Рисует главный экран с подсветкой действия (успех/ошибка)."""
    user_id = inter.author.id
    buf = await asyncio.to_thread(dr.render_main, user_id)
    fname = f"dcc_main_{user_id}.png"

    file = disnake.File(buf, filename=fname)
    e = disnake.Embed(color=0x4dd0e1)
    e.set_image(url=f"attachment://{fname}")
    if flash_text:
        e.description = flash_text

    view = MainView()

    if _is_ephemeral(inter):
        try:
            await inter.edit_original_response(
                content=None, embed=e, file=file, attachments=[], view=view
            )
            return
        except Exception as ex:
            logger.warning(f"dcc main edit_original: {ex}")

    try:
        await inter.followup.send(embed=e, file=file, view=view, ephemeral=True)
    except Exception as ex:
        logger.warning(f"dcc main followup: {ex}")


async def _do_buy(inter, dc_amount: int):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    r = await dcc.buy_dccplus(inter.author.id, dc_amount)
    if not r.get("ok"):
        return await inter.followup.send(f"❌ {r.get('error')}", ephemeral=True)

    flash = (
        f"✅ **Куплено {r['dcc_amount']:.4f} DCC+** "
        f"за `{dc_amount} DC` по курсу `{r['price']:.2f}`"
    )
    await _render_main_with_flash(inter, flash)


async def _do_sell(inter, dcc_amount: float):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    r = await dcc.sell_dccplus(inter.author.id, dcc_amount)
    if not r.get("ok"):
        return await inter.followup.send(f"❌ {r.get('error')}", ephemeral=True)

    flash = (
        f"✅ **Продано {r['dcc_amount']:.4f} DCC+** — "
        f"получено `{r['net_dc']} DC` (комиссия `{r['fee']:.0f}`)"
    )
    await _render_main_with_flash(inter, flash)


# ═══════════════════════════════════════════
# ОТКРЫТИЕ РАЗДЕЛОВ (единая точка)
# ═══════════════════════════════════════════
async def _open_section(inter, section: str):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    user_id = inter.author.id

    try:
        if section == "main":
            buf = await asyncio.to_thread(dr.render_main, user_id)
            await _display(inter, buf, f"dcc_main_{user_id}.png", MainView())

        elif section == "assets":
            buf = await asyncio.to_thread(dr.render_my_assets, user_id)
            await _display(inter, buf, f"dcc_assets_{user_id}.png", MainView())

        elif section == "trade":
            buf = await asyncio.to_thread(dr.render_trade, user_id, "buy", 0, 0.0)
            await _display(inter, buf, f"dcc_trade_{user_id}.png", TradeView())

        elif section == "stake":
            buf = await asyncio.to_thread(dr.render_stake, user_id)
            await _display(inter, buf, f"dcc_stake_{user_id}.png", StakeView())

        elif section == "top":
            buf = await asyncio.to_thread(dr.render_top, user_id)
            await _display(inter, buf, f"dcc_top_{user_id}.png", MainView())

        elif section == "history":
            buf = await asyncio.to_thread(dr.render_history, user_id)
            await _display(inter, buf, f"dcc_hist_{user_id}.png", MainView())

    except Exception as e:
        logger.exception(f"dcc _open_section({section}): {e}")
        try:
            await inter.followup.send(f"❌ Ошибка: {e}", ephemeral=True)
        except Exception:
            pass
