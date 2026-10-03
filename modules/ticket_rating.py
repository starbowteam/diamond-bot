# -*- coding: utf-8 -*-
"""
Логика оценки менеджера + закрытие тикета через отзыв.
Кнопки Step 1 и Step 2 — эфемерные, длинные (hair spaces).
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
)


P = "\u3164"


# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _clear_ticket_owner(channel: disnake.TextChannel):
    """Локальная обёртка — не путаем с core.utils."""
    uid = get_ticket_owner(channel.id)
    if uid:
        remove_ticket_owner(channel.id)


async def _send_ephemeral_image(inter: disnake.MessageInteraction,
                                 buf, filename: str, view: View = None):
    """Отправляет эфемерную картинку с опциональной view."""
    try:
        file = disnake.File(buf, filename=filename)
        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{filename}")

        kwargs = {"embed": embed, "file": file, "ephemeral": True}
        if view is not None:
            kwargs["view"] = view

        if inter.response.is_done():
            await inter.followup.send(**kwargs)
        else:
            await inter.response.send_message(**kwargs)
    except Exception as e:
        logger.exception(f"_send_ephemeral_image: {e}")
        try:
            if inter.response.is_done():
                await inter.followup.send(
                    content=f"❌ Ошибка: `{str(e)[:200]}`", ephemeral=True,
                )
            else:
                await inter.response.send_message(
                    content=f"❌ Ошибка: `{str(e)[:200]}`", ephemeral=True,
                )
        except Exception:
            pass


async def _has_review_in_channel(channel: disnake.TextChannel, user_id: int) -> bool:
    """Проверяет, оставил ли юзер сообщение в канале отзывов после создания тикета."""
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
    """
    Финальная логика закрытия: проверяет отзыв в канале, если всё ок — удаляет тикет.
    Возвращает True если закрыл, False если нет (показал ошибку).
    """
    channel = inter.channel
    owner_id = get_ticket_owner(channel.id)
    if not owner_id:
        await _ephemeral(inter, "❌ У тикета нет владельца.")
        return False

    has_review = await _has_review_in_channel(channel, owner_id)
    if not has_review:
        await _ephemeral(
            inter,
            f"❌ **Сначала оставь отзыв в канале** `💎・отзывы`.\n"
            f"> После этого сможешь завершить заказ.",
        )
        return False

    # Всё ок — закрываем
    await _ephemeral(inter, "✅ Всё готово! Закрываю тикет...")
    await asyncio.sleep(2)

    try:
        manager_id = get_ticket_manager(channel.id)

        # Если это RUB/PAID-тикет — засчитать менеджеру
        is_paid = channel.category and channel.category.id == CONFIG.get("PAID_CATEGORY_ID")
        is_rub  = channel.category and channel.category.id == CONFIG.get("TICKET_CATEGORY_ID")

        if manager_id and (is_paid or is_rub):
            try:
                increment_manager_closed(manager_id)
                add_closed_order(manager_id, channel.id)
            except Exception as e:
                logger.warning(f"increment_manager_closed: {e}")

        # Ачивки персонала
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

        # Чистим и удаляем
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
        label=f"{P*40}Оценить менеджера{P*40}",
        style=ButtonStyle.success,
        custom_id="rating_step1:open",
        emoji="⭐",
    )
    async def open_rating(self, button: Button, inter: disnake.MessageInteraction):
        channel = inter.channel

        owner_id = get_ticket_owner(channel.id)
        if owner_id and inter.author.id != owner_id:
            return await inter.response.send_message(
                "⛔ Оценивать может только владелец тикета.", ephemeral=True,
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
            fname = f"rating_step2_{inter.author.id}.png"
            await _send_ephemeral_image(inter, buf, fname, RatingStep2View())
        except Exception as e:
            logger.exception(f"rating_step2 render: {e}")

        try:
            from modules.commands_staff import send_manager_top
            await send_manager_top()
        except Exception as e:
            logger.warning(f"send_manager_top: {e}")


# ============================================================
# ШАГ 2: ЗАВЕРШИТЬ ЗАКАЗ
# ============================================================
class RatingStep2View(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=f"{P*40}Завершить заказ{P*40}",
        style=ButtonStyle.success,
        custom_id="rating_step2:finish",
        emoji="✅",
    )
    async def finish(self, button: Button, inter: disnake.MessageInteraction):
        channel = inter.channel

        owner_id = get_ticket_owner(channel.id)
        if owner_id and inter.author.id != owner_id and not _is_admin(inter.author):
            return await inter.response.send_message(
                "⛔ Только владелец тикета или админ.", ephemeral=True,
            )

        if not inter.response.is_done():
            await inter.response.defer(ephemeral=True)

        await _check_and_run_close(inter)


def _is_admin(member: disnake.Member) -> bool:
    try:
        from core.utils import has_admin_command_roles
        return has_admin_command_roles(member)
    except Exception:
        return False


# ============================================================
# ГЛАВНЫЙ ФЛОУ
# ============================================================
async def show_rating_flow(inter: disnake.MessageInteraction):
    """
    Вызывается кнопкой «Закрыть» в RUB/PAID-тикетах.
    Проверяет статус и показывает step1 или step2.
    """
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

    if not existing:
        manager_name = "—"
        if manager_id:
            m = channel.guild.get_member(manager_id)
            manager_name = m.display_name if m else str(manager_id)

        try:
            buf = await asyncio.to_thread(
                render_rating_step1,
                inter.author.id,
                manager_name,
                channel.name,
                channel.id % 10000,
            )
            fname = f"rating_step1_{inter.author.id}.png"
            await _send_ephemeral_image(inter, buf, fname, RatingStep1View())
        except Exception as e:
            logger.exception(f"rating_step1 render: {e}")
            await _ephemeral(inter, f"❌ Ошибка рендера: `{str(e)[:200]}`")
        return

    rating = existing.get("rating", 0) if isinstance(existing, dict) else 0
    manager_name = "—"
    if manager_id:
        m = channel.guild.get_member(manager_id)
        manager_name = m.display_name if m else str(manager_id)

    has_review = await _has_review_in_channel(channel, owner_id)

    try:
        buf = await asyncio.to_thread(
            render_rating_step2,
            inter.author.id,
            manager_name,
            rating,
            has_review,
        )
        fname = f"rating_step2_{inter.author.id}.png"
        await _send_ephemeral_image(inter, buf, fname, RatingStep2View())
    except Exception as e:
        logger.exception(f"rating_step2 render: {e}")
        await _ephemeral(inter, f"❌ Ошибка рендера: `{str(e)[:200]}`")


# ============================================================
# DC-ТИКЕТ: ТОЛЬКО ОТЗЫВ
# ============================================================
async def show_dc_close(inter: disnake.MessageInteraction):
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
    if not has_review:
        return await _ephemeral(
            inter,
            f"❌ **Сначала оставь отзыв в канале** `💎・отзывы`.\n"
            f"> После этого сможешь завершить заказ.\n"
            f"> За одобренный отзыв начислим **+15 DC**.",
        )

    await _check_and_run_close(inter)


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
        await _send_ephemeral_image(inter, buf, fname)
    except Exception as e:
        logger.exception(f"show_policy: {e}")
        await _ephemeral(inter, f"❌ Ошибка рендера: `{str(e)[:200]}`")
