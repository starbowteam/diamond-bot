# -*- coding: utf-8 -*-
"""
BuyAll — отдельная витрина для покупки любых товаров.
Одна кнопка, по 5 hair space с каждой стороны. Чистый ephemeral-ответ.
"""
import os
import re
import json
import time as _time

import disnake
from disnake import ButtonStyle
from disnake.ui import View

from core.utils import (
    CONFIG, logger, log_discord,
    add_ticket_owner, get_ticket_cooldown, get_ticket_cooldown_info,
    is_supreme,
)


P = "\u3164"   # hair space


# ============================================================
# КОНСТАНТЫ
# ============================================================
BUYALL_CHANNEL_ID = 1555657192185663518

BUYALL_EMBED_1_IMG = (
    "https://cdn.discordapp.com/attachments/1527006158282555412/"
    "1528795784987021542/image.png?ex=6a5f9986&is=6a5e4806&"
    "hm=e933175c6904901e18d5aa767e2407ca3406bf7d0113257fdd86c12b4218f9d4&"
)
BUYALL_EMBED_2_IMG = (
    "https://cdn.discordapp.com/attachments/1527006158282555412/"
    "1530459984117235753/pisk.png?ex=6a65a76e&is=6a6455ee&"
    "hm=967f621d4400a3d51669107323f800cc734ae25261184142b6b2857dfe1ec2d2&"
)


def _btn_label(text: str) -> str:
    return f"{P * 5}{text}{P * 5}"


# ============================================================
# VIEW
# ============================================================
class BuyAllView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=_btn_label("Оформить покупку"),
        style=ButtonStyle.gray,
        custom_id="buyall:create_ticket",
        row=0,
    )
    async def create(self, button: disnake.Button, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        await _create_buyall_ticket(inter)


# ============================================================
# СОЗДАНИЕ ТИКЕТА — всё в ephemeral
# ============================================================
async def _create_buyall_ticket(inter: disnake.MessageInteraction):
    user = inter.author
    guild = inter.guild

    # ---- 1. Проверка блокировки тикетов ----
    if not is_supreme(user.id):
        until_ts = get_ticket_cooldown(user.id)
        if until_ts > 0:
            info = get_ticket_cooldown_info(user.id)
            reason = info.get("reason", "—") if info else "—"
            left_min = max(1, (until_ts - int(_time.time())) // 60)
            await inter.edit_original_response(content=(
                f"⚠️ **Вам запрещено создавать тикеты.**\n"
                f"> **Причина:** {reason}\n"
                f"> **Осталось:** ~`{left_min} мин`\n"
                f"> **Разблокировка:** <t:{until_ts}:R>\n\n"
                f"> Тикеты в категории вопросов — по-прежнему доступны."
            ))
            return

    # ---- 2. Категория ----
    cat = guild.get_channel(CONFIG["TICKET_CATEGORY_ID"])
    if not cat:
        await inter.edit_original_response(
            content="❌ Категория тикетов не найдена. Сообщи администрации."
        )
        return

    # ---- 3. Переопределения прав ----
    from modules.commands_tickets import (
        _build_ticket_overwrites, TicketView, SelectView,
    )
    overwrites = _build_ticket_overwrites(guild, user)

    # ---- 4. Имя канала ----
    raw = user.display_name.lower().replace(" ", "-")
    raw = re.sub(r"[^a-zа-яё0-9\-_]", "", raw)
    channel_name = raw[:80] or f"order-{user.id}"

    # ---- 5. Уведомляем «создаю» ----
    await inter.edit_original_response(
        content="⏳ Создаю тикет, подожди пару секунд..."
    )

    # ---- 6. Создание канала ----
    try:
        ticket_channel = await cat.create_text_channel(
            name=channel_name, overwrites=overwrites
        )
    except Exception as e:
        logger.error(f"BuyAll: не удалось создать тикет: {e}")
        await inter.edit_original_response(
            content=f"❌ Не удалось создать тикет: `{str(e)[:200]}`"
        )
        return

    # ---- 7. Шаблон заказа ----
    try:
        with open(CONFIG["INFO_TEMPLATE_PATH"], "r", encoding="utf-8") as f:
            data = json.load(f)
        embeds_list = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]
    except Exception as e:
        logger.error(f"BuyAll: ошибка загрузки шаблона: {e}")
        embeds_list = [
            disnake.Embed(color=6776679),
            disnake.Embed(title="Информация о заказе", color=0x7c3131),
        ]

    embed_order_info = (
        embeds_list[1] if len(embeds_list) > 1
        else disnake.Embed(title="Информация о заказе", color=0x7c3131)
    )
    embed_order_info.clear_fields()
    embed_order_info.add_field(
        name="> Заказчик", value=f"```{user.display_name}```", inline=True
    )
    embed_order_info.add_field(
        name="> Источник", value="```BuyAll```", inline=True
    )

    current_time = int(_time.time())
    embed_order_info.description = (
        f"Статус - Не оплачен\n"
        f"> Ожидайте <@&1154757071330365490> для подтверждения.\n"
        f"> Время заказа: <t:{current_time}:f>"
    )

    await ticket_channel.send(
        content=(
            f"> Добрый день, {user.mention}, ваш тикет создан. "
            f"Ожидайте ответа от <@&1154757071330365490>\n"
            f"> После уточнения заказа - менеджер создаст вам счёт."
        ),
        embeds=[embeds_list[0], embed_order_info],
        view=TicketView(),
    )

    select_embed = disnake.Embed(
        title="Что именно нужно посмотреть?",
        description="Ниже, выбор - политика, счет, имя, варны.  \n\nВыберите нужный пункт.",
        color=6776679,
    )
    select_embed.set_image(url=(
        "https://cdn.discordapp.com/attachments/1527006158282555412/"
        "1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&"
        "hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"
    ))
    await ticket_channel.send(embed=select_embed, view=SelectView())

    # ---- 8. Владелец ----
    add_ticket_owner(ticket_channel.id, user.id, cat.id)

    # ---- 9. Финальный ephemeral-ответ ----
    await inter.edit_original_response(content=(
        f"✅ **Тикет создан**\n\n"
        f"> **Канал:** {ticket_channel.mention}\n"
        f"> **Статус:** ожидает менеджера\n"
        f"> **Ответ:** в течение **2 рабочих дней**\n\n"
        f"> Перейти в тикет: {ticket_channel.mention}\n"
        f"> Менеджер <@&1154757071330365490> подхватит заказ."
    ))

    # ---- 10. Лог ----
    try:
        await log_discord(
            title="📩 Тикет создан (BuyAll)",
            description=(
                f"> **Заказчик:** {user.mention} (`{user.id}`)\n"
                f"> **Канал:** {ticket_channel.mention}\n"
                f"> **Источник:** кнопка BuyAll"
            ),
            color=0x00ff00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"],
        )
    except Exception as e:
        logger.warning(f"BuyAll log err: {e}")


# ============================================================
# ОТПРАВКА ПАНЕЛИ
# ============================================================
async def send_buyall_panel():
    from core.bot import bot
    await bot.wait_until_ready()

    channel = bot.get_channel(BUYALL_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(BUYALL_CHANNEL_ID)
        except disnake.NotFound:
            logger.warning(
                f"BuyAll: канал {BUYALL_CHANNEL_ID} не найден, пропускаю"
            )
            return
        except Exception as e:
            logger.warning(f"BuyAll fetch err: {e}")
            return
    if not channel:
        return

    try:
        async for msg in channel.history(limit=50):
            if msg.author == bot.user and msg.components:
                try:
                    await msg.delete()
                except Exception:
                    pass
                break
    except Exception:
        pass

    e1 = disnake.Embed(color=6776679)
    e1.set_image(url=BUYALL_EMBED_1_IMG)

    e2 = disnake.Embed(
        title="Покупка по BuyAll",
        description=(
            "> Наша собственная система, по которой вы можете купить "
            "**абсолютно любой товар** — даже если его нет в каталоге.\n\n"
            "> **Что можно купить:**\n"
            "> · Игры, донаты, подписки, аккаунты\n"
            "> · Услуги, дизайн, рекламу, бусты\n"
            "> · Абсолютно любые другие товары — просто опиши в тикете\n\n"
            "> **Как оформить:** одно нажатие на кнопку ниже — тикет "
            "создаётся автоматически. Никаких форм и ожиданий — "
            "менеджер подберёт для тебя приятную цену."
        ),
        color=6776679,
    )
    e2.set_image(url=BUYALL_EMBED_2_IMG)

    await channel.send(embeds=[e1, e2], view=BuyAllView())

    await log_discord(
        title="🛒 Панель BuyAll отправлена",
        description=f"> Сообщение отправлено в {channel.mention}",
        color=0x00ff00,
    )
