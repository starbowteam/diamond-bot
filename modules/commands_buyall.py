# -*- coding: utf-8 -*-
"""
BuyAll — отдельная витрина для покупки любых товаров.
Отдельный канал, отдельная кнопка, отдельный тикет за реальные деньги.
"""
import disnake
from disnake import ButtonStyle, PartialEmoji
from disnake.ui import View

from core.utils import CONFIG, logger, log_discord


P = "\u3164"   # hair space — растягивает кнопку


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

E_SHOP = PartialEmoji(name="shopg", id=1539646815530651718)


# ============================================================
# VIEW
# ============================================================
class BuyAllView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label=f"{P * 28}Оформить покупку{P * 28}",
        style=ButtonStyle.success,
        custom_id="buyall:create_ticket",
        emoji=E_SHOP,
        row=0,
    )
    async def create(self, button: disnake.Button, inter: disnake.MessageInteraction):
        # Просто создаёт тикет за реальные деньги — весь остальной флоу
        # (счёт, менеджер, оплата, оценка) уже реализован в create_real_ticket
        from modules.commands_tickets import create_real_ticket
        await create_real_ticket(inter)


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

    # Удаляем прошлое сообщение бота с компонентами
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
