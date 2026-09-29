# -*- coding: utf-8 -*-
"""Система подарков DC между юзерами."""
import disnake
from datetime import datetime, timezone

from core.utils import logger, log_discord, CONFIG
from modules.dc import get_user_balance, remove_dc, add_dc

GIFT_FEE_PERCENT = 5  # комиссия магазина
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"


async def process_gift_dc(
    sender: disnake.Member,
    recipient_id: int,
    amount: int,
    price_paid: int,
) -> tuple[bool, str]:
    """
    Проводит подарок:
    - sender уже списан на price_paid (снаружи)
    - recipient получает amount DC
    - recipient получает ЛС с эмбедом
    Возврат: (success, message)
    """
    guild = sender.guild
    recipient = guild.get_member(recipient_id)

    if not recipient:
        await add_dc(sender.id, price_paid, "Возврат — получатель не найден")
        return False, "Получатель не найден на сервере"

    if recipient.bot:
        await add_dc(sender.id, price_paid, "Возврат — получатель бот")
        return False, "Нельзя дарить ботам"

    if recipient.id == sender.id:
        await add_dc(sender.id, price_paid, "Возврат — сам себе")
        return False, "Нельзя подарить самому себе"

    # Начисляем получателю
    try:
        await add_dc(recipient.id, amount, f"Подарок от {sender.display_name}")
    except Exception as e:
        logger.exception(f"gift: add_dc error: {e}")
        await add_dc(sender.id, price_paid, "Возврат — ошибка начисления")
        return False, f"Ошибка начисления: {e}"

    # 👇 Хук квестов клан-лиги
    try:
        from clan.quests import on_gift_quest_hook
        await on_gift_quest_hook(sender.id, amount)
    except Exception as e:
        logger.warning(f"clan gift hook: {e}")

    # 👇 Достижение "Щедрый" — суммарные подарки
    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot

        # Считаем общую сумму подарков от юзера (по истории DC)
        from core.utils import get_dc_cache
        data = get_dc_cache(sender.id)
        total_gifted = 0
        for h in data.get("history", []):
            reason = h.get("reason", "")
            amt = h.get("amount", 0)
            if reason.startswith("Подарок от") and amt > 0:
                total_gifted += amt
        # Плюс только что сделанный
        total_gifted += amount

        await check_and_unlock(sender.id, "gift_total", value=total_gifted, bot=bot)
    except Exception as e:
        logger.warning(f"gift ach: {e}")

    # ЛС получателю
    try:
        dm_embed = disnake.Embed(
            title="🎁 Вам подарили Diamond Coins!",
            description=(
                f"> **Отправитель:** {sender.display_name}\n"
                f"> **Получено:** `+{amount} DC`\n\n"
                f"> Спасибо за то, что вы с нами! Оставить отзыв можно в <#1462074763437543435>."
            ),
            color=0x2ecc71,
            timestamp=datetime.now(timezone.utc)
        )
        dm_embed.set_image(url=IMG_STRIPE)
        await recipient.send(embed=dm_embed)
    except Exception as e:
        logger.warning(f"gift: не удалось отправить ЛС получателю {recipient.id}: {e}")

    # Лог в служебный канал
    await log_discord(
        title="🎁 Подарок DC",
        description=(
            f"> **Отправитель:** {sender.mention}\n"
            f"> **Получатель:** {recipient.mention}\n"
            f"> **Сумма:** `{amount} DC`\n"
            f"> **Комиссия:** `{price_paid - amount} DC`"
        ),
        color=0x00ff00,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return True, f"Подарок отправлен! Получатель: {recipient.mention}"
