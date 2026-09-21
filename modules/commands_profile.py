# -*- coding: utf-8 -*-
import os, json, asyncio
from datetime import datetime, timezone

import disnake
from disnake import ButtonStyle, SelectOption, PartialEmoji
from disnake.ui import Button, Modal, Select, TextInput, View

from core.utils import (
    CONFIG, FILES, ADD_DIR, logger,
    load_json, log_discord,
    get_dc_cache,
    clean_embed_for_discohook,
)
from modules.dc import get_user_purchases

# Padding-символ (Hangul Filler) — занимает место, но невидим
P = "\u3164"


def load_embed_from_file(filename: str):
    path = os.path.join(ADD_DIR, filename)
    if not os.path.exists(path):
        return [disnake.Embed(title="❌ Файл не найден", description=f"`{filename}`", color=0xff0000)]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
    except Exception as e:
        logger.error(f"load_embed err {filename}: {e}")
        return [disnake.Embed(title="❌ Ошибка", description=str(e), color=0xff0000)]


def _role_info(count: int):
    thresholds = [
        (0,  "none",      "Клуб"),
        (1,  "bronze",    "Silver Buyer"),
        (3,  "silver",    "Gold Buyer"),
        (5,  "gold",      "Diamond Buyer"),
        (9,  "diamond",   "Emerald Buyer"),
        (13, "emerald",   "Amethyst Buyer"),
        (18, "amethyst",  "Legendary Buyer"),
        (24, "legendary", "Покупатель Века"),
        (26, "pka",       "Покупатель Века"),
    ]
    cur = thresholds[0]
    for t in thresholds:
        if count >= t[0]:
            cur = t
        else:
            break
    return cur[1], cur[2]


_IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6ab152a3&is=6ab00123&hm=c5c2963ca1ebbe6eb37f673fcef993cacf375c5a80490205c230d4c4adfe8b58&"


# ============================================================
# КАРТОЧКА ПРОФИЛЯ + 3 КНОПКИ
# ============================================================
IMG_INV_TOP   = "https://cdn.discordapp.com/attachments/1527006158282555412/1551572210811011142/image.png?ex=6ab275b9&is=6ab12439&hm=7d8e471545619f792391577a7a0bf5335995f759c5c8b09534ac840b881fc806&"
IMG_ROLES_TOP = "https://cdn.discordapp.com/attachments/1527006158282555412/1551572020427366481/image.png?ex=6ab2758c&is=6ab1240c&hm=2fec780d4d97c17f705cba8dceac2434a1e521ec92c60d43569f730d613076ca&"


class ProfileCardView(View):
    def __init__(self):
        super().__init__(timeout=300)

    @disnake.ui.button(
        label="Инвентарь DC",
        style=ButtonStyle.gray,
        custom_id="pcard:inv",
        emoji=PartialEmoji(name="prize", id=1539657202170859561)
    )
    async def inv_btn(self, button, inter: disnake.MessageInteraction):
        purchases = await get_user_purchases(inter.author.id, only_unused=True)

        # embed1 — шапка с картинкой
        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url=IMG_INV_TOP)

        # embed2 — данные
        if not purchases:
            desc = (
                "> У вас пока нет купленных товаров за **Diamond Coin**.\n"
                "> Загляните в каталог магазина, чтобы найти что-то по вкусу!"
            )
        else:
            lines = []
            for p in purchases[:30]:
                t = p.get("type", "—")
                v = p.get("value", "—")
                lines.append(f"> 💎 **{v}** — `{t}`")
            desc = "\n".join(lines)
            if len(purchases) > 30:
                desc += f"\n\n> …и ещё **{len(purchases) - 30}** позиций"

        embed2 = disnake.Embed(
            title="Ваш инвентарь Diamond Coin",
            description=desc,
            color=6776679,
            timestamp=datetime.now(timezone.utc)
        )
        embed2.set_image(url=_IMG_STRIPE)

        await inter.response.send_message(embeds=[embed1, embed2], ephemeral=True)

    @disnake.ui.button(
        label=f"{P}Кастомные роли",
        style=ButtonStyle.gray,
        custom_id="pcard:roles",
        emoji=PartialEmoji(name="image", id=1550869363266027641)
    )
    async def roles_btn(self, button, inter: disnake.MessageInteraction):
        guild = inter.guild
        member = inter.author

        excluded = set()
        for rid in CONFIG.get("ROLE_IDS", {}).values():
            excluded.add(rid)
        excluded.update({
            1127428607606796290, 1154757071330365490, 1471844291595731016,
            1471190371181789234, 1457964854441672806, 1423360115335106570,
            1539523399611580476,
        })
        limit_role = guild.get_role(1127428607606796290)
        max_pos = limit_role.position if limit_role else 9999

        custom = []
        for r in sorted(member.roles, key=lambda x: -x.position):
            if r.is_default() or r.managed:
                continue
            if r.id in excluded:
                continue
            if r.position >= max_pos:
                continue
            custom.append(r)

        # embed1 — шапка с картинкой
        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url=IMG_ROLES_TOP)

        # embed2 — данные
        if not custom:
            desc = (
                "> У вас нет кастомных ролей.\n"
                "> Приобретите **кастомную роль** в каталоге магазина!"
            )
        else:
            lines = []
            for r in custom[:40]:
                color_hex = f"#{r.color.value:06x}" if r.color.value else "#888888"
                lines.append(f"> <@&{r.id}> — `{color_hex}` · позиция `#{r.position}`")
            desc = "\n".join(lines)
            if len(custom) > 40:
                desc += f"\n\n> …и ещё **{len(custom) - 40}** ролей"

        embed2 = disnake.Embed(
            title="Ваши кастомные роли",
            description=desc,
            color=6776679,
            timestamp=datetime.now(timezone.utc)
        )
        embed2.set_image(url=_IMG_STRIPE)

        await inter.response.send_message(embeds=[embed1, embed2], ephemeral=True)

    @disnake.ui.button(
        label=f"{P}О валюте",
        style=ButtonStyle.gray,
        custom_id="pcard:coin",
        emoji=PartialEmoji(name="pravil", id=1544388874497687622)
    )
    async def coin_btn(self, button, inter: disnake.MessageInteraction):
        embeds = load_embed_from_file("vallue.json")
        await inter.response.send_message(embeds=embeds, ephemeral=True)

async def show_profile_card(inter: disnake.MessageInteraction, user: disnake.Member):
    await inter.response.defer(with_message=True, ephemeral=True)

    from modules.profile_card import generate_profile_card

    counts = load_json(FILES["review_counts"], {})
    review_count = counts.get(str(user.id), 0)
    role_key, _ = _role_info(review_count)

    dc = get_dc_cache(user.id)
    balance = dc.get("balance", 0)
    history_raw = dc.get("history", []) or []
    history = list(reversed(history_raw[-5:]))

    avatar_bytes = None
    try:
        avatar_bytes = await user.display_avatar.replace(size=256, format="png").read()
    except Exception as e:
        logger.warning(f"avatar fetch err: {e}")

    joined_at = None
    if isinstance(user, disnake.Member) and user.joined_at:
        joined_at = user.joined_at

    try:
        buf = await asyncio.to_thread(
            generate_profile_card,
            user.display_name,
            user.id,
            avatar_bytes,
            role_key,
            review_count,
            balance,
            joined_at,
            history,
        )

        filename = f"profile_{user.id}.png"
        file = disnake.File(buf, filename=filename)

        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{filename}")

        await inter.edit_original_response(
            content=None, embed=embed, file=file,
            view=ProfileCardView()
        )

        asyncio.create_task(log_discord(
            title="📇 Карточка профиля",
            description=f"> **Пользователь:** {user.mention}",
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        ))
    except Exception as e:
        logger.exception(f"profile card err: {e}")
        try:
            await inter.edit_original_response(content=f"❌ Ошибка: `{str(e)[:200]}`")
        except Exception:
            pass


# ============================================================
# МОДАЛКА СКИДКИ
# ============================================================
class DiscountModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Исходная цена", placeholder="Сумма", custom_id="price", min_length=1, max_length=20),
            TextInput(label="Скидка (%)", placeholder="%", custom_id="discount_percent", min_length=1, max_length=10),
        ]
        super().__init__(title="Расчёт скидки", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        try:
            price = float(inter.text_values["price"].replace(",", ".").strip())
            discount = float(inter.text_values["discount_percent"].replace(",", ".").strip())
        except ValueError:
            return await inter.response.send_message("❌ Введите числа.", ephemeral=True)
        if discount < 0 or discount > 100:
            return await inter.response.send_message("❌ Скидка 0-100%.", ephemeral=True)
        final_price = price * (1 - discount / 100)
        savings = price - final_price
        embed = disnake.Embed(title="🧾 Результат расчёта", color=0x2ecc71)
        embed.add_field(name="Исходная", value=f"`{price:.2f} ₽`", inline=True)
        embed.add_field(name="Скидка", value=f"`{discount:.0f}%`", inline=True)
        embed.add_field(name="Экономия", value=f"`{savings:.2f} ₽`", inline=True)
        embed.add_field(name="✅ Итого", value=f"**`{final_price:.2f} ₽`**", inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# ПАНЕЛЬ ПРОФИЛЯ — СЕЛЕКТ
# ============================================================
class ProfilePanelSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            SelectOption(
                label="・Мой профиль",
                description="Открыть карточку профиля",
                emoji="<:people:1538395694648529009>",
                value="profile"
            ),
            SelectOption(
                label="・Расчёт скидки",
                description="Посчитать итоговую цену со скидкой",
                emoji="<:ckidsk:1538551877665427557>",
                value="discount"
            ),
        ]
        super().__init__(
            placeholder="Выберите действие...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="profile_panel_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        value = inter.data.values[0]
        if value == "profile":
            await show_profile_card(inter, inter.author)
        elif value == "discount":
            await inter.response.send_modal(DiscountModal())


class ProfilePanelView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProfilePanelSelect())



# В твоём коде было: 1540018373503483934 — оставь как было, если работает.
PROFILE_CHANNEL_ID = 1540018373503483934


async def send_profile_panel():
    from core.bot import bot
    await bot.wait_until_ready()
    channel = bot.get_channel(PROFILE_CHANNEL_ID) or await bot.fetch_channel(PROFILE_CHANNEL_ID)
    if not channel:
        logger.warning("Profile panel channel not found")
        return

    async for msg in channel.history(limit=50):
        if msg.author == bot.user and msg.components:
            try:
                await msg.delete()
            except Exception:
                pass
            break

    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1540035577997561968/image.png?ex=6a887d66&is=6a872be6&hm=1bcc66c5be7dda618d9041cea46a5f6e5bb7d6f26ce9ad5bfae8e7ccd93f0e51&")
    embed2 = disnake.Embed(
        title="Твой профиль на сервере Diamond Shop",
        description="> Здесь можно увидеть свой профиль, инвентарь, кастомные роли и рассчитать скидку.",
        color=6776679
    )
    embed2.set_image(url=_IMG_STRIPE)

    await channel.send(embeds=[embed1, embed2], view=ProfilePanelView())
    await log_discord(
        title="👤 Панель Профиль отправлена",
        description=f"> Сообщение отправлено в {channel.mention}",
        color=0x00ff00
    )
