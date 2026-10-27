# -*- coding: utf-8 -*-
import os
import json
import asyncio
import time as _time
import re
from datetime import datetime, timezone
from typing import Optional, List

import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption, ui, Colour, MediaGalleryItem
from disnake.ui import Button, Modal, Select, TextInput, View

from core.utils import (
    CONFIG, ADD_DIR, CATALOG_DIR, logger,
    load_json, save_json, now_ts, log_discord,
    has_admin_command_roles, has_review_moderation_roles,
    clean_embed_for_discohook, parse_emoji,
    add_ticket_owner, remove_ticket_owner, get_ticket_owner,
    get_user_tickets_count_in_category,
    get_promo_codes,
    set_ticket_cooldown, get_ticket_cooldown, get_ticket_cooldown_info,
    is_supreme,
    cur, db,
)
from modules.dc import (
    add_dc, remove_dc, add_purchase,
    get_user_purchases, remove_purchase,
    get_dc_cache, save_dc_cache,
    get_user_balance,
    load_shop_catalog
)

from modules.tickets import (
    show_policy,
    ReceiptView,
)

_IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"
IMG_ORDER_PAID = "https://cdn.discordapp.com/attachments/1527006158282555412/1564315441784955022/image.png?ex=6ae0d1c8&is=6adf8048&hm=4c7130aae2147b4c389a7602582dd6a9a899f7ed293c6a0e51025bc68fc2ee27&"
IMG_BANNER = "https://cdn.discordapp.com/attachments/1527006158282555412/1556735388092203191/image.png?backend=b2&ex=6ac53e4f&is=6ac3eccf&hm=990684ba1d817e183ea64f7483e8ef0b3476bd86ff3f8645cab1b129fa492580&"

HIDDEN_FROM_TICKETS_ROLE_ID = 1513935883475226796
PAY_CONFIRM_DELAY_SECONDS = 60
QUESTIONS_CATEGORY_ID = 1544363672128987196
REVIEW_CHANNEL_ID = 1462074763437543435

# ============================================================
# ЗАЩИТА ОТ БАГОЮЗА
# ============================================================
_BUY_LOCKS = {}
_BUY_LOCK_TIMEOUT = 15

def _acquire_buy_lock(uid: int) -> bool:
    now = _time.time()
    if uid in _BUY_LOCKS and now - _BUY_LOCKS[uid] < _BUY_LOCK_TIMEOUT:
        return False
    _BUY_LOCKS[uid] = now
    return True

def _release_buy_lock(uid: int):
    _BUY_LOCKS.pop(uid, None)

# ============================================================
# ОТВЕТ НА ИНТЕРАКЦИЮ БЕЗ ОШИБКИ 10062
# ============================================================
_BG_TASKS: set = set()

def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task

async def _ack(inter, *, ephemeral: bool = False, with_message: bool = False) -> bool:
    try:
        if not inter.response.is_done():
            await inter.response.defer(ephemeral=ephemeral, with_message=with_message)
        return True
    except disnake.InteractionResponded:
        return True
    except disnake.NotFound as e:
        logger.warning(f"_ack: интеракция просрочена, ответ невозможен — {e}")
        return False
    except Exception as e:
        logger.warning(f"_ack: не удалось подтвердить интеракцию — {e}")
        return False

async def _safe_edit(inter, **kwargs) -> bool:
    try:
        if inter.response.is_done():
            await inter.edit_original_response(**kwargs)
        else:
            await inter.response.edit_message(**kwargs)
        return True
    except disnake.InteractionResponded:
        try:
            await inter.edit_original_response(**kwargs)
            return True
        except Exception as e:
            logger.warning(f"_safe_edit: {e}")
    except disnake.NotFound as e:
        logger.warning(f"_safe_edit: интеракция просрочена — {e}")
    except Exception as e:
        logger.warning(f"_safe_edit: {e}")
    return False

async def _ephemeral_reply(inter, content: str) -> bool:
    try:
        await inter.edit_original_response(content=content)
        return True
    except Exception:
        try:
            await inter.followup.send(content=content, ephemeral=True)
            return True
        except Exception as e:
            logger.warning(f"_ephemeral_reply: {e}")
            return False

# ============================================================
# ХЕЛПЕРЫ
# ============================================================
def _load_slid_embeds() -> list:
    base_project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base_project, "actions", "slid.json"),
        os.path.join(ADD_DIR, "slid.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            except Exception as e:
                logger.error(f"Ошибка чтения {path}: {e}")
    return []

def clear_ticket_owner(channel: disnake.TextChannel):
    user_id = get_ticket_owner(channel.id)
    if user_id:
        remove_ticket_owner(channel.id)

def _is_paid_ticket(channel: disnake.TextChannel) -> bool:
    if not channel.category:
        return False
    return channel.category.id == CONFIG["PAID_CATEGORY_ID"]

def _is_coins_ticket(channel: disnake.TextChannel) -> bool:
    if not channel.category:
        return False
    return channel.category.id == CONFIG["COINS_CATEGORY_ID"]

def _get_auto_role_names() -> set:
    try:
        catalog = load_shop_catalog()
        names = set()
        for cat_key, cat_data in catalog.items():
            if cat_key != "roles":
                continue
            for item_key, item_data in cat_data.get("items", {}).items():
                if item_data.get("role_id"):
                    names.add(item_data["name"])
        return names
    except Exception as e:
        logger.warning(f"_get_auto_role_names err: {e}")
        return set()

def _filter_purchases_for_ticket(purchases: list) -> list:
    auto_role_names = _get_auto_role_names()
    result = []
    for p in purchases:
        ptype = p.get("type", "")
        pvalue = p.get("value", "")
        if ptype == "roles" and pvalue in auto_role_names:
            continue
        result.append(p)
    return result

def _build_ticket_overwrites(guild: disnake.Guild, user: disnake.Member) -> dict:
    overwrites = {
        guild.default_role: disnake.PermissionOverwrite(view_channel=False),
        user: disnake.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
    }
    hidden_role = guild.get_role(HIDDEN_FROM_TICKETS_ROLE_ID)
    if hidden_role:
        overwrites[hidden_role] = disnake.PermissionOverwrite(view_channel=False)

    for rid in CONFIG["TICKET_VIEW_ROLES"]:
        role = guild.get_role(rid)
        if role:
            overwrites[role] = disnake.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )
    for rid in CONFIG["TICKET_MANAGE_ROLES"]:
        role = guild.get_role(rid)
        if role:
            overwrites[role] = disnake.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )
    return overwrites

async def _check_ticket_blocked(inter: disnake.MessageInteraction) -> bool:
    user_id = inter.author.id
    if is_supreme(user_id):
        return False

    until_ts = get_ticket_cooldown(user_id)
    if until_ts > 0:
        info = get_ticket_cooldown_info(user_id)
        reason = info.get("reason", "—") if info else "—"
        left_min = max(1, (until_ts - int(_time.time())) // 60)
        if not await _safe_edit(
            inter,
            content=(
                f"⚠️ **Вам запрещено создавать тикеты.**\n"
                f"> **Причина:** {reason}\n"
                f"> **Осталось:** ~`{left_min} мин`\n"
                f"> **Разблокировка:** <t:{until_ts}:R>\n\n"
                f"> Тикеты в категории вопросов — по-прежнему доступны."
            ),
            embeds=[], view=None
        ):
            try:
                await inter.followup.send(
                    content=(
                        f"⚠️ **Вам запрещено создавать тикеты.**\n"
                        f"> **Причина:** {reason}\n"
                        f"> **Осталось:** ~`{left_min} мин`\n"
                        f"> **Разблокировка:** <t:{until_ts}:R>"
                    ),
                    ephemeral=True
                )
            except Exception:
                pass
        return True
    return False

# ============================================================
# ЗАКРЫТИЕ ТИКЕТА
# ============================================================
async def _do_close_ticket(inter: disnake.MessageInteraction, check_reviews: bool = False):
    channel = inter.channel

    if not await _ack(inter, ephemeral=True, with_message=True):
        return

    await _ephemeral_reply(inter, content="Тикет закроется через 5 секунд...")
    await asyncio.sleep(5)

    try:
        clear_ticket_owner(channel)
        await channel.delete()

        await log_discord(
            title="🗑️ Тикет закрыт",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {channel.name}",
            color=0xff6600,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )
    except Exception as e:
        logger.error(f"Ошибка закрытия тикета: {e}")

# ============================================================
# ОБЪЕДИНЕННЫЙ VIEW (Components V2)
# ============================================================
class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)
        
        # --- РЯД 1 (ВНУТРИ КОНТЕЙНЕРА) ---
        self.btn_close = Button(label="Закрыть", style=ButtonStyle.secondary, custom_id="ticket:close",
                                emoji=PartialEmoji(name="OffTicket", id=1539657125716824185))
        self.btn_close.callback = self.close_callback

        self.btn_pay = Button(label="Оплатить", style=ButtonStyle.secondary, custom_id="ticket:pay",
                              emoji=PartialEmoji(name="Oplacheno", id=1539657164778512496))
        self.btn_pay.callback = self.pay_callback

        self.btn_disc = Button(label="Скидки", style=ButtonStyle.secondary, custom_id="ticket:discounts",
                               emoji=PartialEmoji(name="skidka", id=1540819242625146961))
        self.btn_disc.callback = self.discounts_callback

        # --- РЯД 2 (СНАРУЖИ) ---
        self.btn_req = Button(label="Счёт на оплату", style=ButtonStyle.secondary, custom_id="ticket:req",
                              emoji=PartialEmoji(name="Rekvi", id=1539656975091105892))
        self.btn_req.callback = self.req_callback

        self.btn_pol = Button(label="Политика", style=ButtonStyle.secondary, custom_id="ticket:policy",
                              emoji=PartialEmoji(name="Politic", id=1539657020695650384))
        self.btn_pol.callback = self.policy_callback

        self.btn_ren = Button(label="Изменить название", style=ButtonStyle.secondary, custom_id="ticket:rename",
                              emoji=PartialEmoji(name="image", id=1550869363266027641), disabled=True)
        self.btn_ren.callback = self.rename_callback

    async def close_callback(self, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав на закрытие.", ephemeral=True)
        await _do_close_ticket(inter, check_reviews=False)

    async def pay_callback(self, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав на подтверждение оплаты.", ephemeral=True)
        
        channel = inter.channel
        if _is_paid_ticket(channel):
            return await inter.response.send_message("Заказ уже оплачен.", ephemeral=True)

        try:
            age = _time.time() - channel.created_at.timestamp()
        except Exception:
            age = PAY_CONFIRM_DELAY_SECONDS
        if age < PAY_CONFIRM_DELAY_SECONDS:
            left = int(PAY_CONFIRM_DELAY_SECONDS - age)
            return await inter.response.send_message(
                f"⏳ **Слишком рано.**\n> Подтвердить оплату можно через **{left} сек** после создания тикета.",
                ephemeral=True
            )

        # Меняем текст в контейнере и отключаем кнопки
        new_view = TicketView()
        new_view.btn_pay.disabled = True
        new_view.btn_disc.disabled = True
        new_view.btn_ren.disabled = False
        
        old_text = inter.message.components[1].children[0].content
        new_text = old_text.replace("Оформляется", "Заказ оплачен").replace("Ожидайте подтверждения.", f"Подтверждено: {inter.author.mention}")
        
        container = ui.Container(
            ui.TextDisplay(new_text),
            ui.ActionRow(new_view.btn_close, new_view.btn_pay, new_view.btn_disc),
            accent_colour=Colour(0x2ecc71) # Зеленая полоска при оплате
        )
        row2 = ui.ActionRow(new_view.btn_req, new_view.btn_pol, new_view.btn_ren)
        
        # Обновляем сообщение
        await inter.message.edit(components=[inter.message.components[0], container, row2])

        paid_category = inter.guild.get_channel(CONFIG["PAID_CATEGORY_ID"])
        if paid_category:
            await channel.edit(category=paid_category)
            
        embed = disnake.Embed(title="💚 Заказ оплачен", description=f"> **Подтвердил:** {inter.author.mention}", color=0x2ecc71)
        embed.set_image(url=_IMG_STRIPE)
        await channel.send(embed=embed)

        try:
            owner_id = get_ticket_owner(channel.id)
            owner_member = inter.guild.get_member(owner_id) if owner_id else None
            if owner_member:
                embed_dm1 = disnake.Embed(color=6776679).set_image(url=IMG_ORDER_PAID)
                embed_dm2 = disnake.Embed(
                    title="💚 Ваш заказ подтверждён как оплачен!",
                    description=f"> Менеджер **{inter.author.display_name}** подтвердил оплату вашего заказа.\n\n> **Тикет:** {channel.mention}\n\n> Скоро мы приступим к его выполнению.",
                    color=0x2ecc71, timestamp=datetime.now(timezone.utc)
                ).set_image(url=_IMG_STRIPE)
                await owner_member.send(embeds=[embed_dm1, embed_dm2])
        except Exception:
            pass

        await inter.response.send_message("✅ Заказ отмечен как оплаченный.", ephemeral=True)
        await log_discord(title="💰 Заказ оплачен", description=f"> **Канал:** {channel.mention}\n> **Подтвердил:** {inter.author.mention}", color=0x2ecc71, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"])

    async def discounts_callback(self, inter: disnake.MessageInteraction):
        channel = inter.channel
        owner_id = get_ticket_owner(channel.id)
        if not owner_id or inter.author.id != owner_id:
            return await inter.response.send_message("⛔ Только создатель тикета.", ephemeral=True)
        
        discount_applied = False
        old_text = inter.message.components[1].children[0].content
        if "Не активирована" not in old_text:
            discount_applied = True
                
        if discount_applied:
            return await inter.response.send_message("❌ Скидка уже применена.", ephemeral=True)
            
        all_purchases = await get_user_purchases(inter.author.id, only_unused=True)
        discounts = [p for p in all_purchases if p.get('type') == 'discounts']
        slid_embeds = _load_slid_embeds()
        if not slid_embeds:
            slid_embeds = [disnake.Embed(title="📦 Ваши скидки", description="> Введи промокод или выбери купленную скидку.", color=6776679)]
        
        view = View(timeout=300)
        btn_promo = Button(
            label="Ввести промокод",
            style=ButtonStyle.gray,
            custom_id=f"promo_input_{inter.author.id}",
            emoji=PartialEmoji(name="prom1", id=1539646792139014234),
            row=0
        )

        async def promo_callback(inter2: disnake.MessageInteraction, _view=view):
            if inter2.author.id != inter.author.id:
                return await inter2.response.send_message("⛔ Это не ваш тикет.", ephemeral=True)
            await inter2.response.send_modal(PromoCodeModal(original_view=_view))

        btn_promo.callback = promo_callback
        view.add_item(btn_promo)
        
        current_row = 0
        current_col = 1
        for idx, p in enumerate(discounts):
            if current_col >= 3:
                current_row += 1
                current_col = 0
            label = p['value']
            if len(label) > 80:
                label = label[:77] + "..."
            btn = Button(label=label, style=ButtonStyle.gray, custom_id=f"apply_discount_{inter.author.id}_{idx}", row=current_row)
            btn.callback = self.create_discount_callback(idx, inter, discounts)
            view.add_item(btn)
            current_col += 1
            
        await inter.response.send_message(embeds=slid_embeds, view=view, ephemeral=True)

    def create_discount_callback(self, discount_index, original_inter, discounts):
        async def callback(inter: disnake.MessageInteraction):
            if inter.author.id != original_inter.author.id:
                return await inter.response.send_message("⛔ Это не ваш товар.", ephemeral=True)
            if discount_index >= len(discounts):
                return await inter.response.send_message("❌ Скидка уже применена.", ephemeral=True)
                
            channel = inter.channel
            item_value = discounts[discount_index]['value']
            full_purchases = await get_user_purchases(inter.author.id, only_unused=False)
            target_index = None
            for i, p in enumerate(full_purchases):
                if p['value'] == item_value and p.get('type') == 'discounts' and not p.get('used'):
                    target_index = i
                    break
                    
            if target_index is None:
                return await inter.response.send_message("❌ Скидка не найдена.", ephemeral=True)
                
            success = await remove_purchase(inter.author.id, target_index)
            if not success:
                return await inter.response.send_message("❌ Ошибка применения скидки.", ephemeral=True)
                
            # Обновляем текст в V2 контейнере
            old_text = inter.message.components[1].children[0].content
            new_text = old_text.replace("Не активирована", item_value)
            
            new_view = TicketView()
            if _is_paid_ticket(channel):
                new_view.btn_pay.disabled = True
                new_view.btn_disc.disabled = True
                new_view.btn_ren.disabled = False
                accent = Colour(0x2ecc71)
            else:
                accent = Colour(0x5865F2)

            container = ui.Container(
                ui.TextDisplay(new_text),
                ui.ActionRow(new_view.btn_close, new_view.btn_pay, new_view.btn_disc),
                accent_colour=accent
            )
            row2 = ui.ActionRow(new_view.btn_req, new_view.btn_pol, new_view.btn_ren)
            
            await inter.message.edit(components=[inter.message.components[0], container, row2])

            await inter.response.send_message(f"✅ Скидка **{item_value}** применена к заказу!", ephemeral=True)
            await log_discord(
                title="🛒 Применена скидка в тикете",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Тикет:** {channel.mention}\n> **Скидка:** {item_value}",
                color=0x00aaff,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        return callback

    async def req_callback(self, inter: disnake.MessageInteraction):
        if not any(r.id == 1154757071330365490 for r in inter.author.roles):
            return await inter.response.send_message("⛔ Доступно только менеджерам.", ephemeral=True)
        await inter.response.send_modal(InvoiceModal())

    async def policy_callback(self, inter: disnake.MessageInteraction):
        await show_policy(inter)

    async def rename_callback(self, inter: disnake.MessageInteraction):
        if not _is_paid_ticket(inter.channel):
            return await inter.response.send_message("⛔ **Доступно только для оплаченных тикетов.**\n> Дождитесь подтверждения оплаты.", ephemeral=True)
        await inter.response.send_modal(RenameTicketModal())

# ============================================================
# СОЗДАНИЕ ТИКЕТА — РЕАЛЬНЫЕ ДЕНЬГИ (V2)
# ============================================================
async def create_real_ticket(inter: disnake.MessageInteraction):
    user = inter.author
    guild = inter.guild

    if await _check_ticket_blocked(inter):
        return

    cat = guild.get_channel(CONFIG["TICKET_CATEGORY_ID"])
    if not cat:
        return await _safe_edit(inter, content="❌ Категория не найдена.", embeds=[], view=None)

    raw = user.display_name.lower().replace(" ", "-")
    raw = re.sub(r"[^a-zа-яё0-9\-_]", "", raw)
    channel_name = raw[:80] or f"order-{user.id}"

    overwrites = _build_ticket_overwrites(guild, user)

    await _safe_edit(inter, content="⏳ Создаём тикет...", embeds=[], view=None)

    try:
        ticket_channel = await cat.create_text_channel(name=channel_name, overwrites=overwrites)
    except Exception as e:
        logger.error(f"Не удалось создать тикет: {e}")
        return await inter.edit_original_response(content=f"❌ Ошибка создания: {e}")

    # 1. Отправляем приветствие ОБЫЧНЫМ сообщением
    try:
        await ticket_channel.send(
            f"> Добрый день, {user.mention}, ваш тикет создан. Ожидайте ответа от <@&1154757071330365490>\n"
            f"> После уточнения заказа - менеджер создаст вам счёт."
        )
    except Exception as e:
        logger.error(f"Ошибка отправки приветствия: {e}")

    # 2. Отправляем V2-компоненты
    current_time = int(_time.time())
    view = TicketView()
    
    # ИСПРАВЛЕНО: передаем элемент позиционно, без items=
    banner = ui.MediaGallery(MediaGalleryItem(media=IMG_BANNER))
    
    container = ui.Container(
        ui.TextDisplay(
            f"## Информация о заказе по данному тикету:\n"
            f"Статус - Оформляется\n"
            f"> Ожидайте подтверждения.\n"
            f"> Время заказа: <t:{current_time}:f>\n\n"
            f"**Заказчик:**\n```{user.display_name}```\n\n"
            f"**Скидка на товар:**\n```Не активирована```"
        ),
        ui.ActionRow(view.btn_close, view.btn_pay, view.btn_disc),
        accent_colour=Colour(0x5865F2)
    )
    
    row2 = ui.ActionRow(view.btn_req, view.btn_pol, view.btn_ren)

    try:
        await ticket_channel.send(components=[banner, container, row2])
    except Exception as e:
        logger.error(f"Ошибка отправки V2: {e}")

    add_ticket_owner(ticket_channel.id, user.id, cat.id)

    try:
        await inter.edit_original_response(
            content=f"> {user.mention}   ᶻ 𝘇 𐰁, тикет создан — {ticket_channel.mention}"
        )
    except Exception:
        try:
            await inter.followup.send(
                content=f"> {user.mention}   ᶻ 𝘇 𐰁, тикет создан — {ticket_channel.mention}",
                ephemeral=True
            )
        except Exception:
            pass

    log_ch = guild.get_channel(CONFIG["LOG_TICKET_CHANNEL_ID"])
    if log_ch:
        await log_ch.send(embed=disnake.Embed(
            title="📩 Тикет создан (реальные деньги)",
            description=f"> **Заказчик:** {user.mention}\n> **Канал:** {ticket_channel.mention}",
            timestamp=datetime.now(timezone.utc),
            color=0x00ff00
        ))

# ============================================================
# СОЗДАНИЕ ТИКЕТА — DC (V2)
# ============================================================
async def create_coins_ticket(inter: disnake.MessageInteraction, purchase: dict, purchase_index: int):
    user = inter.author
    guild = inter.guild

    if await _check_ticket_blocked(inter):
        return

    cat = guild.get_channel(CONFIG["COINS_CATEGORY_ID"])
    if not cat:
        return await _safe_edit(inter, content="❌ Категория не найдена.", embeds=[], view=None)

    item_name = purchase.get("value", "—")

    raw = item_name.lower().replace(" ", "-")
    raw = re.sub(r"[^a-zа-яё0-9\-_]", "", raw)
    channel_name = raw[:80] or f"item-{user.id}"

    overwrites = _build_ticket_overwrites(guild, user)

    await _safe_edit(inter, content="⏳ Создаём тикет...", embeds=[], view=None)

    try:
        ticket_channel = await cat.create_text_channel(name=channel_name, overwrites=overwrites)
    except Exception as e:
        logger.error(f"Не удалось создать DC-тикет: {e}")
        return await inter.edit_original_response(content=f"❌ Ошибка: {e}")

    try:
        await remove_purchase(user.id, purchase_index)
    except Exception as e:
        logger.warning(f"Не удалось удалить покупку #{purchase_index} у {user.id}: {e}")

    # 1. Отправляем приветствие ОБЫЧНЫМ сообщением
    try:
        await ticket_channel.send(
            f"> Добрый день, {user.mention}, ваш тикет на категорию **DC** — создан.\n"
            f"> Ожидайте ответа от <@&1154757071330365490>, приятных покупок в будущем."
        )
    except Exception as e:
        logger.error(f"Ошибка отправки приветствия: {e}")

    # 2. Отправляем V2-компоненты
    current_time = int(_time.time())
    view = TicketView()
    
    view.btn_pay.disabled = True
    view.btn_disc.disabled = True
    view.btn_req.disabled = True
    view.btn_ren.disabled = True

    # ИСПРАВЛЕНО: передаем элемент позиционно, без items=
    banner = ui.MediaGallery(MediaGalleryItem(media=IMG_BANNER))
    
    container = ui.Container(
        ui.TextDisplay(
            f"## Информация о заказе по данному тикету:\n"
            f"Статус - Оформляется\n"
            f"> Ожидайте подтверждения.\n"
            f"> Время заказа: <t:{current_time}:f>\n\n"
            f"**Нужный товар:**\n```{item_name}```"
        ),
        ui.ActionRow(view.btn_close),
        accent_colour=Colour(0x5865F2)
    )
    
    row2 = ui.ActionRow(view.btn_pol)

    try:
        await ticket_channel.send(components=[banner, container, row2])
    except Exception as e:
        logger.error(f"Ошибка отправки V2: {e}")

    add_ticket_owner(ticket_channel.id, user.id, cat.id)

    try:
        await inter.edit_original_response(
            content=(
                f"> {user.mention}   ᶻ 𝘇 𐰁, тикет на DC — создан.\n"
                f"> Перейти: {ticket_channel.mention}"
            )
        )
    except Exception:
        try:
            await inter.followup.send(
                content=(
                    f"> {user.mention}   ᶻ 𝘇 𐰁, тикет на DC — создан.\n"
                    f"> Перейти: {ticket_channel.mention}"
                ),
                ephemeral=True
            )
        except Exception:
            pass

    log_ch = guild.get_channel(CONFIG["LOG_TICKET_CHANNEL_ID"])
    if log_ch:
        await log_ch.send(embed=disnake.Embed(
            title="📩 Тикет создан (Diamond Coins)",
            description=f"> **Пользователь:** {user.mention}\n> **Канал:** {ticket_channel.mention}\n> **Товар:** `{item_name}`",
            timestamp=datetime.now(timezone.utc),
            color=0x00ff00
        ))

# ============================================================
# МОДАЛКА ИЗМЕНЕНИЯ НАЗВАНИЯ
# ============================================================
class RenameTicketModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="Новое название тикета",
                placeholder="Введите новое название",
                custom_id="new_name",
                min_length=2,
                max_length=80
            )
        ]
        super().__init__(title="✏️ Изменение названия тикета", components=components, custom_id="rename_ticket_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        new_name_raw = inter.text_values["new_name"].strip()
        new_name = new_name_raw.lower().replace(" ", "-")
        new_name = re.sub(r"[^a-zа-яё0-9\-_]", "", new_name)
        new_name = new_name[:80]
        if not new_name:
            return await inter.response.send_message("❌ Введите корректное название.", ephemeral=True)
        channel = inter.channel
        old_name = channel.name
        try:
            await channel.edit(name=new_name)
        except Exception as e:
            logger.error(f"Не удалось переименовать канал: {e}")
            return await inter.response.send_message(f"❌ Ошибка переименования: {e}", ephemeral=True)
        try:
            await channel.send(
                content=(
                    f"> **Тикет переименован** — новый заказ: **{new_name_raw}**\n"
                    f"> Выполнение заказа скоро начнётся, ожидайте."
                )
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение в тикет: {e}")
        await inter.response.send_message(
            f"✅ Название тикета изменено с `{old_name}` на `{new_name}`.",
            ephemeral=True
        )
        await log_discord(
            title="✏️ Название тикета изменено",
            description=(
                f"> **Пользователь:** {inter.author.mention}\n"
                f"> **Тикет:** {channel.mention}\n"
                f"> **Было:** `{old_name}`\n"
                f"> **Стало:** `{new_name}`\n"
                f"> **Новое название (raw):** {new_name_raw}"
            ),
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

# ============================================================
# МОДАЛКА СОЗДАНИЯ СЧЁТА
# ============================================================
class InvoiceModal(Modal):
    def __init__(self):
        components = [
            TextInput(label="Товар / Услуга", placeholder="Например: Discord Nitro 1 Month", custom_id="product", min_length=2, max_length=80),
            TextInput(label="Введите сумму для счёта", placeholder="Например: 445", custom_id="amount", min_length=1, max_length=10),
            TextInput(label="Скидка в %, если была (необязательно)", placeholder="Например: 10", custom_id="discount", required=False, max_length=3)
        ]
        super().__init__(title="Создание счёта", components=components, custom_id="invoice_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        from modules.tickets import generate_receipt_png, generate_receipt_id
        product_name = inter.text_values["product"].strip()
        amount_str = inter.text_values["amount"].strip()
        discount_str = inter.text_values.get("discount", "").strip()
        if not amount_str.isdigit():
            return await inter.edit_original_response(content="❌ Сумма должна быть числом.")
        amount = int(amount_str)
        if amount <= 0:
            return await inter.edit_original_response(content="❌ Сумма должна быть больше 0.")
        discount_percent = 0
        if discount_str:
            if not discount_str.isdigit():
                return await inter.edit_original_response(content="❌ Скидка должна быть числом.")
            discount_percent = int(discount_str)
            if discount_percent < 0 or discount_percent > 100:
                return await inter.edit_original_response(content="❌ Скидка 0-100%.")
        manager_id = get_ticket_owner(inter.channel.id)
        manager = inter.guild.get_member(manager_id) if manager_id else None
        manager_name = str(manager) if manager else "—"
        owner_id = get_ticket_owner(inter.channel.id)
        owner = inter.guild.get_member(owner_id) if owner_id else None
        customer_name = owner.display_name if owner else inter.channel.name
        order_id = generate_receipt_id()
        buf = await asyncio.to_thread(
            generate_receipt_png,
            manager_name=manager_name,
            customer_name=customer_name,
            product_name=product_name,
            amount=amount,
            discount_percent=discount_percent,
            order_id=order_id
        )
        total = amount - int(amount * discount_percent / 100)
        file = disnake.File(buf, filename=f"receipt_{order_id}.png")
        embed = disnake.Embed(title=f"Счёт для оплаты создан: к оплате {total} Р", color=6776679)
        embed.set_image(url=f"attachment://receipt_{order_id}.png")
        await inter.channel.send(embed=embed, file=file, view=ReceiptView())
        await inter.edit_original_response(content="✅ Счёт отправлен в тикет.")
        await log_discord(
            title="🧾 Создан счёт",
            description=(
                f"> **Менеджер:** {inter.author.mention}\n"
                f"> **Канал:** {inter.channel.mention}\n"
                f"> **Товар/Услуга:** {product_name}\n"
                f"> **Сумма:** {amount} Р\n"
                + (f"> **Скидка:** {discount_percent}%\n" if discount_percent > 0 else "")
                + f"> **Итого:** {total} Р"
            ),
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

# ============================================================
# МОДАЛКА ПРОМОКОДА
# ============================================================
class PromoCodeModal(Modal):
    def __init__(self, original_view: View):
        self.original_view = original_view
        components = [
            TextInput(label="Промокод", placeholder="Введите код промокода", custom_id="promo_code", min_length=1, max_length=50)
        ]
        super().__init__(title="🎟️ Ввод промокода", components=components, custom_id="promo_code_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        code = inter.text_values["promo_code"].strip().upper()
        codes = get_promo_codes()
        if code not in codes:
            return await inter.response.send_message("❌ Промокод не найден.", ephemeral=True)
        value = codes[code]
        channel = inter.channel
        target_msg = None
        async for msg in channel.history(limit=50):
            if msg.author == inter.bot.user and msg.embeds and len(msg.embeds) >= 2:
                target_msg = msg
                break
        if not target_msg:
            return await inter.response.send_message("❌ Сообщение с заказом не найдено.", ephemeral=True)
        embed_dict = target_msg.embeds[1].to_dict()
        for field in embed_dict.get("fields", []):
            if "скидка" in field.get("name", "").lower():
                field["value"] = f"```{code} — {value}```"
                break
        new_embed = disnake.Embed.from_dict(embed_dict)
        embeds = list(target_msg.embeds)
        embeds[1] = new_embed
        await target_msg.edit(embeds=embeds)
        try:
            for child in self.original_view.children:
                child.disabled = True
            await inter.message.edit(view=self.original_view)
        except Exception as e:
            logger.warning(f"Не удалось обновить view скидок: {e}")
        await inter.response.send_message(
            f"✅ Промокод **{code}** активирован!\n> **Скидка:** `{value}`\n\n> Ввести повторно уже нельзя.",
            ephemeral=True
        )
        await log_discord(
            title="🎟️ Промокод активирован",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Тикет:** {channel.mention}\n> **Код:** `{code}` — {value}",
            color=0x00ff00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

# ============================================================
# ВЫБОР СПОСОБА ОПЛАТЫ
# ============================================================
class BuySelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            SelectOption(
                label="Реальные деньги",
                description="Оплата в рублях, USDT и т.д.",
                emoji="<:realmomne:1539649281575620618>",
                value="real"
            ),
            SelectOption(
                label="Diamond Coins",
                description="Бонусная валюта сервера",
                emoji="<:coins:1539649259245408340>",
                value="coins"
            ),
            SelectOption(
                label="Задать вопрос",
                description="Узнать о нужном товаре",
                emoji="<:questi:1544371841118773328>",
                value="question"
            )
        ]
        super().__init__(
            placeholder="Выберите способ оплаты или задайте вопрос...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="buy_type_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        value = inter.data.values[0] if inter.data.values else ""

        if value == "question":
            try:
                await inter.response.send_modal(QuestionModal())
            except disnake.InteractionResponded:
                pass
            except disnake.NotFound as e:
                logger.warning(f"BuySelect: модалка не отправлена — {e}")
            return

        if not await _ack(inter):
            return

        _spawn(log_discord(
            title="🛒 Выбор типа покупки",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{value}`",
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        ))

        if value == "real":
            await create_real_ticket(inter)

        elif value == "coins":
            purchases = await get_user_purchases(inter.author.id, only_unused=True)
            purchases = [p for p in purchases if p.get('type') != 'discounts']
            purchases = _filter_purchases_for_ticket(purchases)

            if not purchases:
                return await _safe_edit(
                    inter,
                    content=(
                        "❌ У вас нет товаров для покупки за Diamond Coins.\n"
                        "> Сначала купите товар в каталоге за DC."
                    ),
                    embeds=[], view=None
                )

            embed = disnake.Embed(
                title="Выбор товара к тикету",
                description=(
                    "Выберите товар.\n"
                    "Один товар — один тикет."
                ),
                color=6776679
            )
            embed.set_image(url=_IMG_STRIPE)
            view = CoinsBuyView(purchases)
            await _safe_edit(inter, content=None, embeds=[embed], view=view)

class BuyTypeView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BuySelect())

# ============================================================
# СЕЛЕКТ ТОВАРОВ ЗА DC
# ============================================================
class CoinsBuySelect(disnake.ui.StringSelect):
    def __init__(self, purchases: list):
        self.purchases = purchases
        options = []
        for idx, p in enumerate(purchases):
            label = p.get("value", "—")
            if len(label) > 90:
                label = label[:87] + "..."
            date_str = datetime.fromtimestamp(p.get("date", 0)).strftime("%d.%m.%Y")
            options.append(disnake.SelectOption(
                label=label,
                description=f"Куплено: {date_str}",
                value=str(idx)
            ))
        super().__init__(
            placeholder="Выберите товар...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="coins_buy_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        idx = int(inter.data.values[0])

        if not await _ack(inter):
            return

        if idx >= len(self.purchases):
            return await _safe_edit(
                inter, content="❌ Товар не найден.", embeds=[], view=None
            )

        user_id = inter.author.id
        if not _acquire_buy_lock(user_id):
            return await inter.followup.send(
                "⏳ Уже обрабатывается...", ephemeral=True
            )
        try:
            user_purchases = await get_user_purchases(user_id, only_unused=False)
            target = self.purchases[idx]
            target_index = None
            for i, p in enumerate(user_purchases):
                if (p.get("value") == target.get("value")
                        and p.get("type") == target.get("type")
                        and not p.get("used")):
                    target_index = i
                    break
            if target_index is None:
                return await _safe_edit(
                    inter,
                    content="❌ Товар уже использован или не найден.",
                    embeds=[], view=None
                )
            await create_coins_ticket(inter, target, target_index)
        finally:
            _release_buy_lock(user_id)

class CoinsBuyView(View):
    def __init__(self, purchases: list):
        super().__init__(timeout=300)
        self.purchases = purchases
        self.add_item(CoinsBuySelect(purchases))

# ============================================================
# МОДАЛКА ВОПРОСА
# ============================================================
class QuestionModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label="Что за вопрос вы хотите задать?",
                placeholder="Например: Как давно вы занимаетесь магазином?",
                custom_id="question",
                min_length=3,
                max_length=500
            )
        ]
        super().__init__(title="Задать вопрос", components=components, custom_id="question_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        question = inter.text_values["question"]
        guild = inter.guild

        cat = guild.get_channel(QUESTIONS_CATEGORY_ID)
        if not cat:
            return await inter.edit_original_response(content="❌ Категория не найдена.")

        channel_name = inter.author.display_name.lower().replace(" ", "-")[:80]
        if not channel_name:
            channel_name = f"question-{inter.author.id}"

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            inter.author: disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        support_role = guild.get_role(1423360115335106570)
        if support_role:
            overwrites[support_role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        admin_role = guild.get_role(1127428607606796294)
        if admin_role:
            overwrites[admin_role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        ticket_channel = await cat.create_text_channel(name=channel_name, overwrites=overwrites)

        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1556735388092203191/image.png?backend=b2&ex=6ac53e4f&is=6ac3eccf&hm=990684ba1d817e183ea64f7483e8ef0b3476bd86ff3f8645cab1b129fa492580&")

        current_time = int(_time.time())
        embed2 = disnake.Embed(
            title="Что за вопрос был задан:",
            description=f"> Время: <t:{current_time}:f>\n> Ответ на вопрос от персонала.",
            color=6776679
        )
        embed2.set_image(url=_IMG_STRIPE)
        embed2.add_field(name="> Суть вопроса", value=f"```{question}```")

        view = QuestionTicketView()
        await ticket_channel.send(
            content=f"<@&1423360115335106570> - задан вопрос, постарайтесь ответить!",
            embeds=[embed1, embed2],
            view=view
        )

        await inter.edit_original_response(
            content=f"> {inter.author.mention}   ᶻ 𝘇 𐰁, тикет с вопросом создан — {ticket_channel.mention}"
        )

        await log_discord(
            title="❓ Новый вопрос",
            description=f"> **Пользователь:** {inter.author.mention}\n> **Канал:** {ticket_channel.mention}\n> **Вопрос:** {question}",
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

# ============================================================
# ВИД ДЛЯ КАНАЛА ВОПРОСА
# ============================================================
class QuestionTicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤКак правильно задать вопрос?ㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="question:howto",
        emoji=PartialEmoji(name="pravil", id=1544388874497687622),
        row=0
    )
    async def howto(self, button: Button, inter: disnake.MessageInteraction):
        embed1 = disnake.Embed(color=6776679)
        embed1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1544387485684203682/image.png?ex=6a98526d&is=6a9700ed&hm=e6eb0b7ec153c23c7d63cb3fe64a405c56dee64cc9edbe9792cd69bfe7e4fe3b&")
        embed2 = disnake.Embed(
            title="Как правильно задать вопрос?",
            description=(
                "> Чтобы правильно задать вопрос, нужно сформулировать его чётко, кратко и без скрытых подсказок, указав суть проблемы и ожидаемый результат.\n\n"
                "> Основные правила сильного вопроса\n\n"
                "`Определите цель: `Поймите, какая информация вам нужна.\n"
                "`Говорите просто: `Избегайте сложных терминов и длинных конструкций.\n"
                "`Избегайте наводок:` Не подталкивайте собеседника к нужному вам ответу.\n"
                "`Используйте открытые вопросы:` Начинайте со слов «что», «как» и тд. чтобы получить развёрнутый ответ.\n"
                "`Добавляйте контекст:` Если это технический вопрос или обращение на форум, опишите проблему, что вы уже сделали и какой результат ожидали."
            ),
            color=6776679
        )
        embed2.set_image(url=_IMG_STRIPE)
        await inter.response.send_message(embeds=[embed1, embed2])
        await log_discord(
            title="📖 Просмотр инструкции по вопросам",
            description=f"> **Канал:** {inter.channel.mention}\n> **Пользователь:** {inter.author.mention}",
            color=0x00aaff,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    @disnake.ui.button(
        label="ㅤㅤЗакрытьㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="question:close",
        emoji=PartialEmoji(name="OffTicket", id=1539657125716824185),
        row=0
    )
    async def close(self, button: Button, inter: disnake.MessageInteraction):
        if not any(r.id == 1423360115335106570 for r in inter.author.roles) and not has_admin_command_roles(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав на закрытие.", ephemeral=True)
        await inter.response.send_message("Канал закроется через 5 секунд...", ephemeral=True)
        await asyncio.sleep(5)
        channel = inter.channel
        try:
            await channel.delete()
        except Exception:
            pass
        await log_discord(
            title="❓ Вопрос закрыт",
            description=f"> **Канал:** {channel.name}\n> **Закрыл:** {inter.author.mention}",
            color=0xff6600,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

# ============================================================
# КНОПКИ ДЛЯ ТИКЕТОВ ЗА DC (Остались для совместимости)
# ============================================================
class CoinsTicketButtons(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤПолитика выполнения заказаㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="coins_ticket:policy",
        emoji=PartialEmoji(name="Politic", id=1539657020695650384),
        row=0
    )
    async def policy(self, button, inter: disnake.MessageInteraction):
        await show_policy(inter)

    @disnake.ui.button(
        label="ㅤㅤЗакрытьㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="coins_ticket:close",
        emoji=PartialEmoji(name="OffTicket", id=1539657125716824185),
        row=0
    )
    async def close(self, button, inter: disnake.MessageInteraction):
        if not has_admin_command_roles(inter.author) and not any(r.id in CONFIG["TICKET_MANAGE_ROLES"] for r in inter.author.roles):
            return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        
        await _do_close_ticket(inter, check_reviews=False)

# ============================================================
# ВЫБОР ТИПА КАТАЛОГА
# ============================================================
class CatalogTypeSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            SelectOption(label="Реальные деньги", description="Оплата в рублях, USDT и т.д.", emoji="<:realmomne:1539649281575620618>", value="real"),
            SelectOption(label="Diamond Coin-ы", description="Внутренняя валюта сервера", emoji="<:coins:1539649259245408340>", value="coins"),
        ]
        super().__init__(
            placeholder="Выберите тип товаров...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="catalog_type_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        value = inter.data.values[0]
        if value == "real":
            embed = disnake.Embed(
                color=6776679,
                title="Выбор для покупки в каталоге товаров",
                description="Ниже, представлены цены, на интересующие вас категории, ознакомьтесь."
            )
            embed.set_image(url=_IMG_STRIPE)
            await inter.response.edit_message(content=None, embeds=[embed], view=CatalogView())
        elif value == "coins":
            from modules.shop import open_shop
            await open_shop(inter)

class CatalogTypeView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CatalogTypeSelect())

# ============================================================
# КАТАЛОГ ДЛЯ РЕАЛЬНЫХ ДЕНЕГ
# ============================================================
CATALOG_OPTIONS = [
    {"label": "・Discord", "description": "Покупка Nitro и Boosts ・Статус и величие", "emoji": "<:Discord:1464831837300854936>", "json_path": os.path.join(CATALOG_DIR, "menu_discord.json")},
    {"label": "・Steam", "description": "Пополнение и очки ・Свобода к играм", "emoji": "<:Steam:1464833200416100402>", "json_path": os.path.join(CATALOG_DIR, "menu_steam.json")},
    {"label": "・Telegram", "description": "Звезды и Подарки ・Индивидуальность и защита", "emoji": "<:Telegram:1465720888677896314>", "json_path": os.path.join(CATALOG_DIR, "menu_telegram.json")},
    {"label": "・Украшение Discord", "description": "Украшения и Бейджики ・Изысканность и красота", "emoji": "<:Decoration:1465729329290936403>", "json_path": os.path.join(CATALOG_DIR, "menu_decoration.json")},
    {"label": "・Roblox", "description": "Донат и Помощь ・Красота и играбельность", "emoji": "<:Roblox:1465752155251150911>", "json_path": os.path.join(CATALOG_DIR, "menu_roblox.json")},
    {"label": "・Spotify", "description": "Подписка на музыку ・Громкость и красочность", "emoji": "<:Spotify:1465770796411785330>", "json_path": os.path.join(CATALOG_DIR, "menu_spotify.json")},
    {"label": "・Боты и Дизайн", "description": "Отличный дизайн ・Выбор для лучших", "emoji": "<:Design:1465771436580012106>", "json_path": os.path.join(CATALOG_DIR, "menu_bodesign.json")},
]

class CatalogSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(
                label=item["label"],
                description=item["description"],
                emoji=item["emoji"],
                value=item["json_path"]
            ) for item in CATALOG_OPTIONS
        ]
        super().__init__(
            placeholder="Выберите категорию...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="catalog_select"
        )

    async def callback(self, inter: disnake.MessageInteraction):
        json_path = self.values[0]
        try:
            if not os.path.exists(json_path):
                return await inter.response.edit_message(
                    content="❌ Файл с embed не найден.", embeds=[], view=None
                )
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            embeds = [disnake.Embed.from_dict(clean_embed_for_discohook(e)) for e in data.get("embeds", [])]
            await inter.response.edit_message(content=None, embeds=embeds, view=CatalogView())
            await log_discord(
                title="📂 Выбор категории (Каталог)",
                description=f"> **Пользователь:** {inter.author.mention}\n> **Категория:** `{json_path}`",
                color=0x00aaff,
                channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
            )
        except Exception as e:
            logger.exception("CatalogSelect callback error: %s", e)

class CatalogView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CatalogSelect())

# ============================================================
# ПАНЕЛЬ ТИКЕТОВ
# ============================================================
class TicketPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(
        label="ㅤㅤКупитьㅤㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:buy",
        emoji=PartialEmoji(name="shopg", id=1539646815530651718)
    )
    async def buy(self, button: disnake.Button, inter: disnake.MessageInteraction):
        embed = disnake.Embed(
            color=6776679,
            title="Выбор категории по оплате",
            description="В какой валюте вы хотите купить товар? Если у вас есть вопрос, вы можете его задать, выбрав соответствующий пункт ниже."
        )
        embed.set_image(url=_IMG_STRIPE)
        view = BuyTypeView()
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)

    @disnake.ui.button(
        label="ㅤПромокодыㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:promo",
        emoji=PartialEmoji(name="prom1", id=1539646792139014234)
    )
    async def promo(self, button: disnake.Button, inter: disnake.MessageInteraction):
        text = "Промокоды публикуются в <#1462070136856117258> — следи за новостями и забирай свою скидку."
        await inter.response.send_message(text, ephemeral=True)
        await log_discord(
            title="🎟️ Просмотр промокодов",
            description=f"> **Пользователь:** {inter.author.mention}",
            color=0x00ff00,
            channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
        )

    @disnake.ui.button(
        label="ㅤКаталогㅤ",
        style=disnake.ButtonStyle.gray,
        custom_id="panel:catalog",
        emoji=PartialEmoji(name="catal", id=1539646769053306980)
    )
    async def catalog(self, button: disnake.Button, inter: disnake.MessageInteraction):
        embed = disnake.Embed(
            title="Выбор категории товаров",
            description="В чем представлен ваш товар? Выберите метод ниже.",
            color=6776679
        )
        embed.set_image(url=_IMG_STRIPE)
        view = CatalogTypeView()
        await inter.response.send_message(embed=embed, view=view, ephemeral=True)

# ============================================================
# ОБРАБОТЧИК ИНТЕРАКЦИЙ
# ============================================================
async def handle_interaction(inter: disnake.MessageInteraction):
    pass