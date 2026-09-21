# -*- coding: utf-8 -*-
"""Система подарков DC между юзерами."""
import disnake
from datetime import datetime, timezone

from core.utils import logger, log_discord, CONFIG
from modules.dc import get_user_balance, remove_dc, add_dc

GIFT_FEE_PERCENT = 5  # комиссия магазина
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6ab152a3&is=6ab00123&hm=c5c2963ca1ebbe6eb37f673fcef993cacf375c5a80490205c230d4c4adfe8b58&"


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
        # Возврат средств
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
