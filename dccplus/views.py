# -*- coding: utf-8 -*-
"""Discord UI для DCC+.

Всё управление — через селекты. Кнопок нет.

Логика сообщений:
  · 1 публичная панель в канале (DCCPanelView).
  · Любой клик по селекту открывает ephemeral.
  · Операции ПЕРЕЗАПИСЫВАЮТ тот же ephemeral.
  · Исключение — модалки: после них создаётся новое ephemeral.

Защита от протухших интеракций:
  · Все ответы на interaction идут через _safe_* обёртки.
  · Ошибки типа «Unknown interaction / timeout / 404» тихо глотаются,
    чтобы не засорять лог.
"""
import asyncio

import disnake
from disnake import SelectOption
from disnake.ui import View, Select, Modal, TextInput

from core.utils import logger
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
# ХЕЛПЕРЫ: мёртвая интеракция / ephemeral / view
# ═══════════════════════════════════════════
_DEAD_MARKERS = (
    "unknown interaction",
    "unknown message",
    "interaction has already been acknowledged",
    "interactiontimedout",
    "interaction timed out",
    "interaction took more than",
    "10062",  # Discord code: Unknown Interaction
    "10008",  # Discord code: Unknown Message
    "404",
)


def _is_dead_interaction_error(ex: Exception) -> bool:
    """True — если ошибка означает, что интеракция протухла / удалена."""
    if isinstance(ex, disnake.NotFound):
        return True
    s = str(ex).lower()
    return any(m in s for m in _DEAD_MARKERS)


def _log_soft(label: str, ex: Exception):
    """Мёртвые ошибки тихо проглатываем, остальные — в лог."""
    if _is_dead_interaction_error(ex):
        return
    logger.warning(f"{label}: {ex}")


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


def _has_components(view) -> bool:
    if view is None:
        return False
    try:
        return len(view.children) > 0
    except Exception:
        return False


async def _safe_defer(inter, ephemeral: bool = True) -> bool:
    """
    Пытается отложить интеракцию. Возвращает False, если она уже мертва.
    """
    try:
        if inter.response.is_done():
            return True
        await inter.response.defer(ephemeral=ephemeral)
        return True
    except disnake.InteractionResponded:
        return True
    except Exception as ex:
        _log_soft("dcc defer", ex)
        return False


async def _safe_followup(inter, **kwargs):
    """Безопасно шлёт followup. Молча скипает мёртвые интеракции."""
    try:
        fw = getattr(inter, "followup", None)
        if fw is None:
            return False
        await fw.send(**kwargs)
        return True
    except Exception as ex:
        _log_soft("dcc followup", ex)
        return False


async def _safe_edit_original(inter, **kwargs) -> bool:
    """Безопасно редактирует исходное ephemeral. True — если удалось."""
    try:
        await inter.edit_original_response(**kwargs)
        return True
    except Exception as ex:
        _log_soft("dcc edit_original", ex)
        return False


async def _render_into_ephemeral(inter, buf, fname: str, view, flash: str = ""):
    """
    Показывает картинку:
      · Если сообщение уже ephemeral → перезаписывает его.
      · Иначе → отправляет новое ephemeral.
      · Если интеракция мертва — тихо выходим (ничего не делаем).
    """
    file = disnake.File(buf, filename=fname)
    e = disnake.Embed(color=0x4dd0e1)
    e.set_image(url=f"attachment://{fname}")
    if flash:
        e.description = flash

    use_view = view if _has_components(view) else None

    # 1) Пробуем перезаписать текущее ephemeral
    if _is_ephemeral(inter):
        ok = await _safe_edit_original(
            inter,
            content=None, embed=e, file=file,
            attachments=[], view=use_view,
        )
        if ok:
            return
        # если не получилось — не сдаёмся, пробуем followup ниже

    # 2) Fallback — отправляем followup
    await _safe_followup(
        inter,
        embed=e, file=file, view=use_view, ephemeral=True,
    )


# ═══════════════════════════════════════════
# СЕЛЕКТ РАЗДЕЛОВ — только на публичной панели
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
# VIEW ДЛЯ MAIN / ASSETS / TOP / HISTORY — без компонентов
# ═══════════════════════════════════════════
class EmptyView(View):
    def __init__(self):
        super().__init__(timeout=300)


# ═══════════════════════════════════════════
# VIEW ДЛЯ ОБМЕНА — только селект действий
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
            try:
                await inter.response.send_modal(BuyModal())
            except Exception as ex:
                _log_soft("dcc buy modal", ex)
            return

        if v == "sell_custom":
            try:
                await inter.response.send_modal(SellModal())
            except Exception as ex:
                _log_soft("dcc sell modal", ex)
            return

        action, _, raw = v.partition("_")
        if action == "buy":
            await _do_buy(inter, int(raw))
        else:
            await _do_sell(inter, float(raw))


class TradeView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(TradeActionSelect())


# ═══════════════════════════════════════════
# VIEW ДЛЯ СТЕЙКА — только селект срока
# ═══════════════════════════════════════════
class StakePlanSelect(Select):
    def __init__(self):
        options = [
            SelectOption(label="7 дней · +5%",
                         description="Быстрый стейк, минимальный процент",
                         value="7"),
            SelectOption(label="14 дней · +14%",
                         description="Оптимальный баланс срока и профита",
                         value="14"),
            SelectOption(label="30 дней · +35%",
                         description="Максимум профита, держим долго",
                         value="30"),
        ]
        super().__init__(
            placeholder="Выбери срок стейка...",
            min_values=1, max_values=1,
            options=options,
            custom_id="dcc_stake_plan",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        days = int(inter.data.values[0])
        try:
            await inter.response.send_modal(StakeModal(days))
        except Exception as ex:
            _log_soft("dcc stake modal", ex)


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
            await _safe_followup(
                inter, content=f"❌ {r.get('error')}", ephemeral=True
            )
            return

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
            await _safe_followup(
                inter,
                embed=e, file=file, view=StakeView(), ephemeral=True,
            )
        except Exception as ex:
            logger.warning(f"stake success render: {ex}")
            await _safe_followup(
                inter,
                content=f"🔒 Стейк создан на {self.days} дней, `{amount:.4f} DCC+`",
                ephemeral=True,
            )


# ═══════════════════════════════════════════
# ДЕЙСТВИЯ
# ═══════════════════════════════════════════
async def _do_buy(inter, dc_amount: int):
    if not await _safe_defer(inter):
        return

    r = await dcc.buy_dccplus(inter.author.id, dc_amount)
    if not r.get("ok"):
        await _safe_followup(inter, content=f"❌ {r.get('error')}", ephemeral=True)
        return

    user_id = inter.author.id
    try:
        buf = await asyncio.to_thread(dr.render_trade, user_id, "buy", 0, 0.0)
        fname = f"dcc_trade_{user_id}.png"
        flash = (
            f"✅ **Куплено {r['dcc_amount']:.4f} DCC+** "
            f"за `{dc_amount} DC` по курсу `{r['price']:.2f}`"
        )
        await _render_into_ephemeral(inter, buf, fname, TradeView(), flash)
    except Exception as ex:
        logger.warning(f"buy success render: {ex}")


async def _do_sell(inter, dcc_amount: float):
    if not await _safe_defer(inter):
        return

    r = await dcc.sell_dccplus(inter.author.id, dcc_amount)
    if not r.get("ok"):
        await _safe_followup(inter, content=f"❌ {r.get('error')}", ephemeral=True)
        return

    user_id = inter.author.id
    try:
        buf = await asyncio.to_thread(dr.render_trade, user_id, "sell", 0, 0.0)
        fname = f"dcc_trade_{user_id}.png"
        flash = (
            f"✅ **Продано {r['dcc_amount']:.4f} DCC+** — "
            f"получено `{r['net_dc']} DC` (комиссия `{r['fee']:.0f}`)"
        )
        await _render_into_ephemeral(inter, buf, fname, TradeView(), flash)
    except Exception as ex:
        logger.warning(f"sell success render: {ex}")


# ═══════════════════════════════════════════
# ОТКРЫТИЕ РАЗДЕЛОВ
# ═══════════════════════════════════════════
async def _open_section(inter, section: str):
    if not await _safe_defer(inter):
        return

    user_id = inter.author.id

    try:
        if section == "main":
            buf = await asyncio.to_thread(dr.render_main, user_id)
            await _render_into_ephemeral(
                inter, buf, f"dcc_main_{user_id}.png", EmptyView()
            )

        elif section == "assets":
            buf = await asyncio.to_thread(dr.render_my_assets, user_id)
            await _render_into_ephemeral(
                inter, buf, f"dcc_assets_{user_id}.png", EmptyView()
            )

        elif section == "trade":
            buf = await asyncio.to_thread(dr.render_trade, user_id, "buy", 0, 0.0)
            await _render_into_ephemeral(
                inter, buf, f"dcc_trade_{user_id}.png", TradeView()
            )

        elif section == "stake":
            buf = await asyncio.to_thread(dr.render_stake, user_id)
            await _render_into_ephemeral(
                inter, buf, f"dcc_stake_{user_id}.png", StakeView()
            )

        elif section == "top":
            buf = await asyncio.to_thread(dr.render_top, user_id)
            await _render_into_ephemeral(
                inter, buf, f"dcc_top_{user_id}.png", EmptyView()
            )

        elif section == "history":
            buf = await asyncio.to_thread(dr.render_history, user_id)
            await _render_into_ephemeral(
                inter, buf, f"dcc_hist_{user_id}.png", EmptyView()
            )

    except Exception as e:
        logger.exception(f"dcc _open_section({section}): {e}")
        await _safe_followup(inter, content=f"❌ Ошибка: {e}", ephemeral=True)  
