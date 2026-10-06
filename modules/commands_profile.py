# -*- coding: utf-8 -*-
import os
import json
import asyncio
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
from modules.dc import (
    get_user_purchases,
    claim_daily_gift,
    get_daily_gift_status,
)

P = "\u3164"

_IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"
_IMG_PANEL_BANNER = "https://cdn.discordapp.com/attachments/1527006158282555412/1556735380877746368/image.png?backend=b2&ex=6ac53e4d&is=6ac3eccd&hm=2f257e6fbd905bcfc836b4cecef7048e3608a14cb0af356a7e8868ca1c6ed110&"

IMG_INV_TOP   = "https://cdn.discordapp.com/attachments/1527006158282555412/1551572210811011142/image.png?ex=6ab275b9&is=6ab12439&hm=7d8e471545619f792391577a7a0bf5335995f759c5c8b09534ac840b881fc806&"
IMG_ROLES_TOP = "https://cdn.discordapp.com/attachments/1527006158282555412/1551572020427366481/image.png?ex=6ab2758c&is=6ab1240c&hm=2fec780d4d97c17f705cba8dceac2434a1e521ec92c60d43569f730d613076ca&"

# ─── Флаг поддержки Components V2 ───
V2_AVAILABLE = (
    hasattr(disnake.ui, "Container")
    and hasattr(disnake.ui, "TextDisplay")
    and hasattr(disnake.ui, "MediaGallery")
    and hasattr(disnake.ui, "ActionRow")
)


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
        (1,  "bronze",    "Bronze Buyer"),
        (6,  "silver",    "Silver Buyer"),
        (11, "gold",      "Gold Buyer"),
        (16, "diamond",   "Diamond Buyer"),
        (21, "crystalis", "Crystalis Buyer"),
        (26, "pka",       "Покупатель Века"),
    ]
    cur = thresholds[0]
    for t in thresholds:
        if count >= t[0]:
            cur = t
        else:
            break
    return cur[1], cur[2]


# ============================================================
# ХЕЛПЕРЫ
# ============================================================
async def _send_ephemeral_file(inter: disnake.MessageInteraction,
                                buf, filename: str,
                                error_prefix: str = "❌ Ошибка"):
    try:
        file = disnake.File(buf, filename=filename)
        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{filename}")
        if inter.response.is_done():
            await inter.followup.send(embed=embed, file=file, ephemeral=True)
        else:
            await inter.response.send_message(embed=embed, file=file, ephemeral=True)
    except Exception as e:
        logger.exception(f"_send_ephemeral_file: {e}")
        try:
            if inter.response.is_done():
                await inter.followup.send(
                    content=f"{error_prefix}: `{str(e)[:200]}`", ephemeral=True,
                )
            else:
                await inter.response.send_message(
                    content=f"{error_prefix}: `{str(e)[:200]}`", ephemeral=True,
                )
        except Exception:
            pass


async def _send_ephemeral_text(inter: disnake.MessageInteraction, content: str):
    try:
        if inter.response.is_done():
            await inter.followup.send(content=content, ephemeral=True)
        else:
            await inter.response.send_message(content=content, ephemeral=True)
    except Exception as e:
        logger.warning(f"_send_ephemeral_text: {e}")


# ============================================================
# ОБРАБОТЧИКИ КНОПОК КАРТОЧКИ ПРОФИЛЯ (используются и в V1, и в V2)
# ============================================================
async def _do_inv(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    purchases = await get_user_purchases(inter.author.id, only_unused=True)
    filtered = [p for p in purchases if p.get("type") != "discounts"]

    try:
        from modules.dc import get_user_balance
        balance = await get_user_balance(inter.author.id)
    except Exception:
        balance = get_dc_cache(inter.author.id).get("balance", 0)

    total_spent = 0
    try:
        dc_data = get_dc_cache(inter.author.id)
        for h in dc_data.get("history", []) or []:
            amt = h.get("amount", 0) or 0
            reason = h.get("reason", "") or ""
            if amt < 0 and reason.startswith("Покупка"):
                total_spent += abs(amt)
    except Exception:
        pass

    try:
        from modules.shop.render_profile import render_inventory
        buf = await asyncio.to_thread(
            render_inventory,
            inter.author.id, balance, total_spent, filtered,
        )
        fname = f"inv_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
        await _send_ephemeral_file(inter, buf, fname)
    except Exception as e:
        logger.exception(f"_do_inv render: {e}")
        await _send_ephemeral_text(inter, f"❌ Ошибка: `{str(e)[:200]}`")


async def _do_roles(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    guild = inter.guild
    member = inter.author

    excluded = set()
    for rid in CONFIG.get("ROLE_IDS", {}).values():
        excluded.add(rid)
    excluded.update({
        1127428607606796290, 1154757071330365490, 1471844291595731016,
        1471190371181789234, 1457964854441672806, 1423360115335106570,
        1539523399611580476,
        1208442450373513277, 1208442449425334372,
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

    roles_list = []
    for r in custom[:40]:
        roles_list.append({
            "id": r.id,
            "name": r.name,
            "color": r.color.value if r.color else 0,
            "position": r.position,
            "mention": r.mention,
        })

    try:
        from modules.dc import get_user_balance
        balance = await get_user_balance(inter.author.id)
    except Exception:
        balance = get_dc_cache(inter.author.id).get("balance", 0)

    total_spent = 0
    try:
        dc_data = get_dc_cache(inter.author.id)
        for h in dc_data.get("history", []) or []:
            amt = h.get("amount", 0) or 0
            reason = h.get("reason", "") or ""
            if amt < 0 and reason.startswith("Покупка"):
                total_spent += abs(amt)
    except Exception:
        pass

    try:
        from modules.shop.render_profile import render_custom_roles
        buf = await asyncio.to_thread(
            render_custom_roles,
            inter.author.id, balance, total_spent, roles_list,
        )
        fname = f"roles_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
        await _send_ephemeral_file(inter, buf, fname)
    except Exception as e:
        logger.exception(f"_do_roles render: {e}")
        await _send_ephemeral_text(inter, f"❌ Ошибка: `{str(e)[:200]}`")


async def _do_coin(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    try:
        from modules.dc import get_user_balance
        balance = await get_user_balance(inter.author.id)
    except Exception:
        balance = get_dc_cache(inter.author.id).get("balance", 0)

    total_spent = 0
    try:
        dc_data = get_dc_cache(inter.author.id)
        for h in dc_data.get("history", []) or []:
            amt = h.get("amount", 0) or 0
            reason = h.get("reason", "") or ""
            if amt < 0 and reason.startswith("Покупка"):
                total_spent += abs(amt)
    except Exception:
        pass

    try:
        from modules.shop.render_profile import render_about_coin
        buf = await asyncio.to_thread(
            render_about_coin,
            inter.author.id, balance, total_spent,
        )
        fname = f"coin_{inter.author.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
        await _send_ephemeral_file(inter, buf, fname)
    except Exception as e:
        logger.exception(f"_do_coin render: {e}")
        await _send_ephemeral_text(inter, f"❌ Ошибка: `{str(e)[:200]}`")


# ============================================================
# VIEW КАРТОЧКИ ПРОФИЛЯ (V1 fallback)
# ============================================================
class ProfileCardView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="Инвентарь DC",
        style=ButtonStyle.gray,
        custom_id="pcard:inv",
        emoji=PartialEmoji(name="prize", id=1539657202170859561)
    )
    async def inv_btn(self, button, inter: disnake.MessageInteraction):
        await _do_inv(inter)

    @disnake.ui.button(
        label=f"{P}Кастомные роли",
        style=ButtonStyle.gray,
        custom_id="pcard:roles",
        emoji=PartialEmoji(name="image", id=1550869363266027641)
    )
    async def roles_btn(self, button, inter: disnake.MessageInteraction):
        await _do_roles(inter)

    @disnake.ui.button(
        label=f"{P}О валюте",
        style=ButtonStyle.gray,
        custom_id="pcard:coin",
        emoji=PartialEmoji(name="pravil", id=1544388874497687622)
    )
    async def coin_btn(self, button, inter: disnake.MessageInteraction):
        await _do_coin(inter)


# ============================================================
# КАРТОЧКА ПРОФИЛЯ
# ============================================================
async def show_profile_card(
    inter: disnake.MessageInteraction,
    user: disnake.Member,
    show_view: bool = True,
    viewer: disnake.Member = None,
):
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

        filename = f"profile_{user.id}_{int(datetime.now(timezone.utc).timestamp())}.png"
        file = disnake.File(buf, filename=filename)

        # ─── V2: картинка + кнопки внутри контейнера ───
        if V2_AVAILABLE and show_view:
            try:
                container = disnake.ui.Container(
                    disnake.ui.MediaGallery(
                        disnake.MediaGalleryItem(url=f"attachment://{filename}")
                    ),
                    disnake.ui.ActionRow(
                        disnake.ui.Button(
                            label="Инвентарь DC",
                            style=ButtonStyle.gray,
                            custom_id="pcard_v2:inv",
                            emoji=PartialEmoji(name="prize", id=1539657202170859561),
                        ),
                        disnake.ui.Button(
                            label="Кастомные роли",
                            style=ButtonStyle.gray,
                            custom_id="pcard_v2:roles",
                            emoji=PartialEmoji(name="image", id=1550869363266027641),
                        ),
                        disnake.ui.Button(
                            label="О валюте",
                            style=ButtonStyle.gray,
                            custom_id="pcard_v2:coin",
                            emoji=PartialEmoji(name="pravil", id=1544388874497687622),
                        ),
                    ),
                    accent_colour=disnake.Colour.from_rgb(103, 118, 177),
                )
                await inter.edit_original_response(
                    components=[container],
                    file=file,
                    attachments=[],
                )
            except Exception as e:
                logger.exception(f"V2 card render failed, fallback to V1: {e}")
                V2_SAFE = False
                embed = disnake.Embed(color=6776679)
                embed.set_image(url=f"attachment://{filename}")
                view = ProfileCardView() if show_view else None
                await inter.edit_original_response(
                    embed=embed, file=file, attachments=[], view=view,
                )
        else:
            embed = disnake.Embed(color=6776679)
            embed.set_image(url=f"attachment://{filename}")
            view = ProfileCardView() if show_view else None
            await inter.edit_original_response(
                embed=embed, file=file, attachments=[], view=view,
            )

        if viewer and viewer.id != user.id:
            asyncio.create_task(log_discord(
                title="👁️ Просмотр чужого профиля",
                description=(
                    f"> **Кто смотрел:** {viewer.mention} (`{viewer}`)\n"
                    f"> **Чей профиль:** {user.mention} (`{user}`)\n"
                    f"> **ID цели:** `{user.id}`"
                ),
                color=0xf7c991,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            ))
        else:
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
# ЕЖЕДНЕВНЫЙ ПОДАРОК — PILLOW
# ============================================================
def _daily_gift_stats(user_id: int) -> dict:
    count = 0
    total = 0
    try:
        data = get_dc_cache(user_id)
        for h in data.get("history", []) or []:
            reason = (h.get("reason", "") or "").strip()
            amt = h.get("amount", 0) or 0
            if amt <= 0:
                continue
            if reason == "Ежедневный подарок" or reason.startswith("Ежедневный подарок"):
                count += 1
                total += amt
    except Exception as e:
        logger.warning(f"_daily_gift_stats {user_id}: {e}")
    return {"count": count, "total": total}


async def show_daily_gift(inter: disnake.MessageInteraction):
    user_id = inter.author.id

    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    result = await claim_daily_gift(user_id)

    stats = _daily_gift_stats(user_id)
    daily_count = stats["count"]
    daily_total = stats["total"]

    try:
        from modules.dc import get_user_balance
        balance = await get_user_balance(user_id)
    except Exception:
        balance = get_dc_cache(user_id).get("balance", 0)

    try:
        from modules.shop.render_gift import render_daily_gift
        buf = await asyncio.to_thread(
            render_daily_gift,
            user_id, balance, result, daily_count, daily_total,
        )

        fname = f"gift_{user_id}_{int(datetime.now(timezone.utc).timestamp())}.png"
        file = disnake.File(buf, filename=fname)

        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{fname}")

        try:
            await inter.followup.send(embed=embed, file=file, ephemeral=True)
        except Exception as e:
            logger.exception(f"show_daily_gift send: {e}")
            if result.get("ok"):
                txt = f"🎁 Сегодня тебе выпало **{result['amount']} DC**!"
            else:
                txt = "⏳ Ты уже забрал подарок сегодня. Возвращайся завтра!"
            await _send_ephemeral_text(inter, txt)
            return
    except Exception as e:
        logger.exception(f"show_daily_gift render: {e}")
        await _send_ephemeral_text(inter, f"❌ Ошибка рендера: `{str(e)[:200]}`")
        return

    if result.get("ok"):
        asyncio.create_task(log_discord(
            title="🎁 Ежедневный подарок",
            description=(
                f"> **Пользователь:** {inter.author.mention} (`{inter.author}`)\n"
                f"> **Начислено:** `+{result['amount']} DC`\n"
                f"> **Всего подарков:** `{daily_count}`\n"
                f"> **Всего DC с подарков:** `{daily_total} DC`\n"
                f"> **Следующий через 24ч:** <t:{result['next_ts']}:f>"
            ),
            color=0xffaa00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        ))


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


class OtherProfileModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="ID пользователя",
                placeholder="Введите ID (например, 123456789012345678)",
                custom_id="target_id",
                min_length=1,
                max_length=30
            )
        ]
        super().__init__(
            title="👤 Профиль другого пользователя",
            components=components,
            custom_id="other_profile_modal"
        )

    async def callback(self, inter: disnake.ModalInteraction):
        raw = inter.text_values["target_id"].strip()

        if not raw.isdigit():
            return await inter.response.send_message(
                "❌ ID должен состоять только из цифр.", ephemeral=True
            )

        target_id = int(raw)

        if target_id == inter.author.id:
            return await inter.response.send_message(
                "❌ Это ваш ID. Используйте пункт **«Мой профиль»**.", ephemeral=True
            )

        member = inter.guild.get_member(target_id)
        if not member:
            return await inter.response.send_message(
                f"❌ Пользователь с ID `{target_id}` не найден на сервере.",
                ephemeral=True
            )

        if member.bot:
            return await inter.response.send_message(
                "❌ Нельзя смотреть профиль бота.", ephemeral=True
            )

        await show_profile_card(
            inter,
            member,
            show_view=False,
            viewer=inter.author
        )


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
                label="・Чужой профиль",
                description="Карточка профиля другого пользователя.",
                emoji="<:wmore:1552330925684162580>",
                value="other_profile"
            ),
            SelectOption(
                label="・Ежедневный подарок",
                description="Забери свой подарок в DC и возвращайся каждый день.",
                emoji="<:S21:1552381035092648026>",
                value="daily_gift"
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
            await show_profile_card(inter, inter.author, show_view=True)
        elif value == "other_profile":
            await inter.response.send_modal(OtherProfileModal())
        elif value == "daily_gift":
            await show_daily_gift(inter)
        elif value == "discount":
            await inter.response.send_modal(DiscountModal())


class ProfilePanelView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProfilePanelSelect())


PROFILE_CHANNEL_ID = 1540018373503483934


# ============================================================
# ЛИСТЕНЕР ДЛЯ V2-КНОПОК КАРТОЧКИ ПРОФИЛЯ
# ============================================================
def setup_profile_v2_listeners(bot):
    """Регистрирует обработчики кнопок V2. Вызвать из bot.on_ready()."""

    @bot.listen("on_button_click")
    async def _profile_v2_buttons(inter: disnake.MessageInteraction):
        cid = getattr(inter.component, "custom_id", None)
        if cid == "pcard_v2:inv":
            await _do_inv(inter)
        elif cid == "pcard_v2:roles":
            await _do_roles(inter)
        elif cid == "pcard_v2:coin":
            await _do_coin(inter)


# ============================================================
# ОТПРАВКА ПАНЕЛИ
# ============================================================
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

    # ─── V2: селект внутри контейнера ───
    if V2_AVAILABLE:
        try:
            container = disnake.ui.Container(
                disnake.ui.MediaGallery(
                    disnake.MediaGalleryItem(url=_IMG_PANEL_BANNER)
                ),
                disnake.ui.TextDisplay(
                    content=(
                        "## Твой профиль на сервере Diamond Shop\n"
                        "> Здесь можно увидеть свой профиль, чужой профиль, "
                        "забрать ежедневный подарок, посмотреть инвентарь, "
                        "кастомные роли и рассчитать скидку."
                    )
                ),
                disnake.ui.MediaGallery(
                    disnake.MediaGalleryItem(url=_IMG_STRIPE)
                ),
                disnake.ui.ActionRow(ProfilePanelSelect()),
                accent_colour=disnake.Colour.from_rgb(103, 118, 177),
            )
            await channel.send(components=[container])
            logger.info("Панель профиля (V2) отправлена — селект внутри контейнера")
            await log_discord(
                title="👤 Панель Профиль отправлена (V2)",
                description=f"> Сообщение отправлено в {channel.mention}",
                color=0x00ff00,
            )
            return
        except Exception as e:
            logger.exception(f"send_profile_panel V2 failed, fallback V1: {e}")

    # ─── Fallback V1: старая версия ───
    embed1 = disnake.Embed(color=6776679)
    embed1.set_image(url=_IMG_PANEL_BANNER)
    embed2 = disnake.Embed(
        title="Твой профиль на сервере Diamond Shop",
        description="> Здесь можно увидеть свой профиль, чужой профиль, забрать ежедневный подарок, посмотреть инвентарь, кастомные роли и рассчитать скидку.",
        color=6776679,
    )
    embed2.set_image(url=_IMG_STRIPE)
    await channel.send(embeds=[embed1, embed2], view=ProfilePanelView())
    logger.info("Панель профиля (V1 fallback)")
    await log_discord(
        title="👤 Панель Профиль отправлена",
        description=f"> Сообщение отправлено в {channel.mention}",
        color=0x00ff00,
    )
