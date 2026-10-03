# -*- coding: utf-8 -*-
"""
Логика оценки менеджера + закрытие тикета через отзыв.
Картинки постим В КАНАЛ (не эфемерно) — кнопки видны всем.
Права на нажатие проверяются в callback.
"""
import asyncio
from datetime import datetime, timezone

import disnake
from disnake import ButtonStyle, PartialEmoji
from disnake.ui import View, Button, Modal, TextInput

from core.utils import (
    CONFIG, logger,
    log_discord,
    get_ticket_owner, get_ticket_manager,
    remove_ticket_owner,
    save_ticket_review, get_ticket_review, clear_ticket_review,
    clear_ticket_manager,
    increment_manager_closed, add_closed_order, add_manager_rating,
    cur, db,
)
from modules.tickets_render import (
    render_policy,
    render_rating_step1,
    render_rating_step2,
    render_review_only,
)


# ============================================================
# КОНСТАНТЫ
# ============================================================
ADMIN_OVERRIDE_ID = 796293832751972352   # админ — может всё

# \u2800 (BRAILLE PATTERN BLANK) — шире \u3164 (HANGUL FILLER),
# поэтому кнопка тянется на бОльшую ширину и соразмерна эмбеду.
P = "\u2800"
_BTN_LABEL_MAX = 78   # почти лимит Discord (80), но не в упор


EMOJI_OTZIV = PartialEmoji(name="Otziv", id=1541808692314243172)
EMOJI_OFF = PartialEmoji(name="OffTicket", id=1539657125716824185)


# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _btn_label(text: str, total: int = _BTN_LABEL_MAX) -> str:
    """
    Растягивает текст до нужной ширины кнопки.
    Паддинг СИММЕТРИЧНЫЙ — текст ровно по центру.
    """
    text = text.strip()
    if len(text) >= total:
        return text[:total]

    padding = total - len(text)
    left = padding // 2
    right = padding - left   # если padding нечётный — right на 1 больше

    return f"{P * left}{text}{P * right}"


def _clear_ticket_owner(channel: disnake.TextChannel):
    uid = get_ticket_owner(channel.id)
    if uid:
        remove_ticket_owner(channel.id)


async def _send_image_to_channel(inter: disnake.MessageInteraction,
                                  buf, filename: str, view: View = None):
    """Постит картинку В КАНАЛ (не эфемерно). Кнопки видны всем."""
    try:
        file = disnake.File(buf, filename=filename)
        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{filename}")

        kwargs = {"embed": embed, "file": file}
        if view is not None:
            kwargs["view"] = view

        await inter.channel.send(**kwargs)
    except Exception as e:
        logger.exception(f"_send_image_to_channel: {e}")
        try:
            await inter.channel.send(f"❌ Ошибка отправки: `{str(e)[:200]}`")
        except Exception:
            pass


async def _has_review_in_channel(channel: disnake.TextChannel, user_id: int) -> bool:
    """Проверяет, оставил ли юзер сообщение в канале отзывов."""
    review_channel = channel.guild.get_channel(CONFIG["REVIEW_COUNT_CHANNEL"])
    if not review_channel:
        return False
    try:
        created_at = channel.created_at
        async for msg in review_channel.history(after=created_at, limit=300):
            if msg.author.bot:
                continue
            if msg.author.id == user_id:
                return True
    except Exception as e:
        logger.warning(f"_has_review_in_channel err: {e}")
    return False


async def _ephemeral(inter: disnake.MessageInteraction, content: str):
    try:
        if inter.response.is_done():
            await inter.followup.send(content=content, ephemeral=True)
        else:
            await inter.response.send_message(content=content, ephemeral=True)
    except Exception as e:
        logger.warning(f"_ephemeral: {e}")


async def _check_and_run_close(inter: disnake.MessageInteraction) -> bool:
    """Финальное закрытие — проверяет отзыв, потом удаляет тикет."""
    channel = inter.channel
    owner_id = get_ticket_owner(channel.id)
    if not owner_id:
        await _ephemeral(inter, "❌ У тикета нет владельца.")
        return False

    has_review = await _has_review_in_channel(channel, owner_id)
    if not has_review:
        await _ephemeral(
            inter,
            f"❌ **Сначала оставь отзыв в канале** `отзывы`.\n"
            f"> После этого сможешь завершить заказ.",
        )
        return False

    await _ephemeral(inter, "✅ Всё готово! Закрываю тикет...")
    await asyncio.sleep(2)

    try:
        manager_id = get_ticket_manager(channel.id)

        is_paid = channel.category and channel.category.id == CONFIG.get("PAID_CATEGORY_ID")
        is_rub  = channel.category and channel.category.id == CONFIG.get("TICKET_CATEGORY_ID")

        if manager_id and (is_paid or is_rub):
            try:
                increment_manager_closed(manager_id)
                add_closed_order(manager_id, channel.id)
            except Exception as e:
                logger.warning(f"increment_manager_closed: {e}")

        try:
            if manager_id:
                from clan.achievements import check_and_unlock
                from core.bot import bot
                row = cur.execute(
                    "SELECT closed_tickets FROM manager_stats WHERE user_id=?",
                    (manager_id,)
                ).fetchone()
                total_closed = row["closed_tickets"] if row else 0
                await check_and_unlock(manager_id, "staff_tickets", value=total_closed, bot=bot)
        except Exception as e:
            logger.warning(f"staff tickets ach: {e}")

        _clear_ticket_owner(channel)
        clear_ticket_manager(channel.id)
        clear_ticket_review(channel.id)

        await channel.delete()

        await log_discord(
            title="🗑️ Тикет закрыт",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {channel.name}",
            color=0xff6600,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )

        try:
            from modules.commands_staff import send_manager_top
            await send_manager_top()
        except Exception as e:
            logger.warning(f"send_manager_top: {e}")

        return True
    except Exception as e:
        logger.exception(f"_check_and_run_close: {e}")
        return False


# ============================================================
# ШАГ 1: ОЦЕНКА МЕНЕДЖЕРА
# ============================================================
class RatingStep1View(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=_btn_label("Оценить менеджера"),
        style=ButtonStyle.gray,
        custom_id="rating_step1:open",
        emoji=EMOJI_OTZIV,
    )
    async def open_rating(self, button: Button, inter: disnake.MessageInteraction):
        channel = inter.channel

        owner_id = get_ticket_owner(channel.id)
        if not owner_id:
            return await inter.response.send_message(
                "❌ У тикета нет владельца.", ephemeral=True,
            )
        if inter.author.id != owner_id and inter.author.id != ADMIN_OVERRIDE_ID:
            return await inter.response.send_message(
                "⛔ Оценить менеджера может только владелец тикета.", ephemeral=True,
            )

        manager_id = get_ticket_manager(channel.id)
        if not manager_id:
            return await inter.response.send_message(
                "❌ Менеджер не назначен.", ephemeral=True,
            )

        existing = get_ticket_review(channel.id)
        if existing:
            return await inter.response.send_message(
                "⛔ Ты уже оценил менеджера.", ephemeral=True,
            )

        try:
            await inter.response.send_modal(RatingStarsModal(channel, manager_id))
        except Exception as e:
            logger.warning(f"open_rating modal: {e}")


# ============================================================
# МОДАЛКА: 1-5 ЗВЁЗД
# ============================================================
class RatingStarsModal(Modal):
    def __init__(self, channel: disnake.TextChannel, manager_id: int):
        self.channel = channel
        self.manager_id = manager_id
        components = [
            TextInput(
                label="Оценка от 1 до 5",
                placeholder="Введи число от 1 до 5",
                custom_id="rating",
                min_length=1,
                max_length=1,
            )
        ]
        super().__init__(title="Оценка менеджера", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        raw = inter.text_values["rating"].strip()
        if not raw.isdigit() or int(raw) < 1 or int(raw) > 5:
            return await inter.response.send_message(
                "❌ Оценка должна быть от 1 до 5.", ephemeral=True,
            )
        rating = int(raw)
        if not self.manager_id:
            return await inter.response.send_message(
                "❌ Менеджер не назначен.", ephemeral=True,
            )

        try:
            add_manager_rating(self.manager_id, rating)
            save_ticket_review(self.channel.id, inter.author.id, self.manager_id, rating)
        except Exception as e:
            logger.exception(f"save rating: {e}")

        try:
            if rating == 5:
                row = cur.execute(
                    "SELECT COUNT(*) as c FROM ticket_reviews WHERE manager_id=? AND rating=5",
                    (self.manager_id,),
                ).fetchone()
                cnt = row["c"] if row else 0
                if cnt >= 10:
                    from clan.achievements import unlock_achievement
                    from core.bot import bot
                    await unlock_achievement(self.manager_id, "staff_perfect", bot=bot)
        except Exception as e:
            logger.warning(f"staff perfect ach: {e}")

        await log_discord(
            title="⭐ Оценка менеджера",
            description=(
                f"> **Менеджер:** <@{self.manager_id}>\n"
                f"> **Оценка:** {rating}/5\n"
                f"> **Тикет:** {self.channel.mention}"
            ),
            color=0xffaa00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )

        await inter.response.defer(ephemeral=True)

        try:
            buf = await asyncio.to_thread(
                render_rating_step2,
                inter.author.id,
                inter.author.display_name,
                rating,
                False,
            )
            fname = f"rating_step2_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
            await _send_image_to_channel(inter, buf, fname, RatingFinishView())
        except Exception as e:
            logger.exception(f"rating_step2 render: {e}")

        try:
            from modules.commands_staff import send_manager_top
            await send_manager_top()
        except Exception as e:
            logger.warning(f"send_manager_top: {e}")


# ============================================================
# ФИНАЛЬНАЯ КНОПКА «Завершить заказ»
# ============================================================
class RatingFinishView(View):
    """
    Кнопка «Завершить заказ» — используется и для step2 (после оценки),
    и для review_only (DC-тикеты).
    """
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=_btn_label("Завершить заказ"),
        style=ButtonStyle.gray,
        custom_id="review:finish",
        emoji=EMOJI_OFF,
    )
    async def finish(self, button: Button, inter: disnake.MessageInteraction):
        channel = inter.channel

        manager_id = get_ticket_manager(channel.id)
        is_admin = inter.author.id == ADMIN_OVERRIDE_ID

        try:
            from core.utils import has_admin_command_roles
            if has_admin_command_roles(inter.author):
                is_admin = True
        except Exception:
            pass

        if not is_admin and inter.author.id != manager_id:
            return await inter.response.send_message(
                "⛔ Завершить заказ может только админ или назначенный менеджер.",
                ephemeral=True,
            )

        if not inter.response.is_done():
            try:
                await inter.response.defer(ephemeral=True)
            except Exception:
                pass

        await _check_and_run_close(inter)


# ============================================================
# ГЛАВНЫЙ ФЛОУ
# ============================================================
async def show_rating_flow(inter: disnake.MessageInteraction):
    """Показывает step1 / step2 / review_only в зависимости от статуса."""
    channel = inter.channel

    if not inter.response.is_done():
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

    owner_id = get_ticket_owner(channel.id)
    if not owner_id:
        return await _ephemeral(inter, "❌ У тикета нет владельца.")

    manager_id = get_ticket_manager(channel.id)
    existing = get_ticket_review(channel.id)

    # Нет менеджера И нет оценки → просто отзыв (review_only)
    if not manager_id and not existing:
        has_review = await _has_review_in_channel(channel, owner_id)
        try:
            buf = await asyncio.to_thread(
                render_review_only, owner_id, has_review,
            )
            fname = f"review_only_{int(datetime.now(timezone.utc).timestamp())}.png"
            await _send_image_to_channel(inter, buf, fname, RatingFinishView())
        except Exception as e:
            logger.exception(f"review_only render: {e}")
            await _ephemeral(inter, f"❌ Ошибка рендера: `{str(e)[:200]}`")
        return

    # Оценки нет, но менеджер есть → step1
    if not existing:
        manager_name = "—"
        if manager_id:
            m = channel.guild.get_member(manager_id)
            manager_name = m.display_name if m else str(manager_id)

        try:
            buf = await asyncio.to_thread(
                render_rating_step1,
                owner_id,
                manager_name,
                channel.name,
                channel.id % 10000,
            )
            fname = f"rating_step1_{int(datetime.now(timezone.utc).timestamp())}.png"
            await _send_image_to_channel(inter, buf, fname, RatingStep1View())
        except Exception as e:
            logger.exception(f"rating_step1 render: {e}")
            await _ephemeral(inter, f"❌ Ошибка рендера: `{str(e)[:200]}`")
        return

    # Оценка есть → step2
    rating = existing.get("rating", 0) if isinstance(existing, dict) else 0
    manager_name = "—"
    if manager_id:
        m = channel.guild.get_member(manager_id)
        manager_name = m.display_name if m else str(manager_id)

    has_review = await _has_review_in_channel(channel, owner_id)

    try:
        buf = await asyncio.to_thread(
            render_rating_step2,
            owner_id,
            manager_name,
            rating,
            has_review,
        )
        fname = f"rating_step2_{int(datetime.now(timezone.utc).timestamp())}.png"
        await _send_image_to_channel(inter, buf, fname, RatingFinishView())
    except Exception as e:
        logger.exception(f"rating_step2 render: {e}")
        await _ephemeral(inter, f"❌ Ошибка рендера: `{str(e)[:200]}`")


# ============================================================
# DC-ТИКЕТ: ТОЛЬКО ОТЗЫВ (с панелью!)
# ============================================================
async def show_dc_close(inter: disnake.MessageInteraction):
    """Для DC-тикетов — показываем панель «оставь отзыв» (без оценки)."""
    channel = inter.channel

    if not inter.response.is_done():
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

    owner_id = get_ticket_owner(channel.id)
    if not owner_id:
        return await _ephemeral(inter, "❌ У тикета нет владельца.")

    has_review = await _has_review_in_channel(channel, owner_id)

    try:
        buf = await asyncio.to_thread(render_review_only, owner_id, has_review)
        fname = f"review_only_{int(datetime.now(timezone.utc).timestamp())}.png"
        await _send_image_to_channel(inter, buf, fname, RatingFinishView())
    except Exception as e:
        logger.exception(f"show_dc_close render: {e}")
        await _ephemeral(inter, f"❌ Ошибка рендера: `{str(e)[:200]}`")


# ============================================================
# ПОЛИТИКА
# ============================================================
async def show_policy(inter: disnake.MessageInteraction):
    if not inter.response.is_done():
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

    try:
        buf = await asyncio.to_thread(render_policy, inter.author.id)
        fname = f"policy_{inter.author.id}.png"
        file = disnake.File(buf, filename=fname)
        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{fname}")
        await inter.followup.send(embed=embed, file=file, ephemeral=True)
    except Exception as e:
        logger.exception(f"show_policy: {e}")
        await _ephemeral(inter, f"❌ Ошибка рендера: `{str(e)[:200]}`")
