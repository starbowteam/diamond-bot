# -*- coding: utf-8 -*-
import time
import re
import disnake
from disnake import ui, ButtonStyle, Modal, TextInput, TextInputStyle

from core.utils import logger, db, cur

ADS_CATEGORY_ID = 1568673531900727407
ADS_CHANNEL_ID = 1553694881564590143
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"

def init_ads_db():
    try:
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS active_ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id INTEGER,
            message_id INTEGER,
            is_personal INTEGER DEFAULT 0,
            expires_at INTEGER
        );
        """)
        db.commit()
    except Exception as e:
        logger.error(f"Ошибка создания таблицы active_ads: {e}")

# 👇 Эмбед для формы
def build_ad_embed(item_name: str) -> disnake.Embed:
    embed = disnake.Embed(
        title="📢 Оформление рекламы",
        description=(
            f"Вы приобрели: **{item_name}**\n\n"
            "Чтобы я подготовил пост, нажмите на кнопку ниже.\n\n"
            "> 📝 Вам нужно будет отправить **только текст** вашей рекламы.\n"
            "> ⚙️ Пинги и время размещения я настрою автоматически.\n"
            "> 📺 Если это личный канал — я попрошу его название."
        ),
        color=0x2b2d31
    )
    embed.set_image(url=IMG_STRIPE)
    return embed

# ============================================================
# ВЬЮ КНОПКИ
# ============================================================
class AdStartView(ui.View):
    def __init__(self, item_name: str):
        super().__init__(timeout=None)
        self.item_name = item_name

    @ui.button(label="📝 Заполнить бриф", style=ButtonStyle.primary, custom_id="ad_start_btn")
    async def start(self, button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(AdTextViewModal(item_name=self.item_name))

# ============================================================
# МОДАЛКИ
# ============================================================
class AdTextViewModal(Modal):
    def __init__(self, item_name: str):
        self.item_name = item_name
        super().__init__(title="Текст рекламы", components=[
            TextInput(label="Ваш рекламный текст", placeholder="Опишите проект, добавьте ссылки. Без пингов.", style=TextInputStyle.paragraph, custom_id="ad_text", min_length=5, max_length=2000)
        ])

    async def callback(self, inter: disnake.ModalInteraction):
        text = self.text_values["ad_text"]
        
        ping = ""
        if "@everyone" in self.item_name: ping = "@everyone"
        elif "@here" in self.item_name: ping = "@here"
        
        is_personal = "Личный канал" in self.item_name
        is_24h = "24ч" in self.item_name
        
        if is_personal:
            await inter.response.send_modal(AdChannelNameModal(ad_text=text, ping=ping))
        else:
            embed = disnake.Embed(description=text, color=0x2b2d31)
            embed.set_footer(text="Предпросмотр. Нажмите 'Опубликовать' для отправки.")
            
            view = AdPublishConfirmView(item_name=self.item_name, text=text, ping=ping, is_24h=is_24h)
            await inter.channel.send(content=f"> **Предпросмотр рекламы:**\n{ping}", embed=embed, view=view)
            await inter.response.send_message("✅ Предпросмотр отправлен в чат.", ephemeral=True)

class AdChannelNameModal(Modal):
    def __init__(self, ad_text: str, ping: str):
        self.ad_text = ad_text
        self.ping = ping
        super().__init__(title="Название личного канала", components=[
            TextInput(label="Введите название канала", placeholder="Например: реклама-моего-сервера", custom_id="chan_name", min_length=2, max_length=90)
        ])

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        raw_name = self.text_values["chan_name"].lower().replace(" ", "-")
        clean_name = re.sub(r"[^a-zа-яё0-9\-_]", "", raw_name)
        channel_name = f"├┃📚・{clean_name}"[:100]
        if not clean_name: channel_name = f"├┃📚・ad-{inter.author.id}"
        
        guild = inter.guild
        category = guild.get_channel(ADS_CATEGORY_ID)
        if not category: return await inter.followup.send("❌ Категория не найдена.", ephemeral=True)

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(read_messages=True, send_messages=False),
            guild.me: disnake.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        try:
            new_channel = await category.create_text_channel(name=channel_name, overwrites=overwrites)
        except Exception as e:
            return await inter.followup.send(f"❌ Ошибка создания: {e}", ephemeral=True)
        
        embed = disnake.Embed(description=self.ad_text, color=0x2b2d31)
        msg = await new_channel.send(content=self.ping, embed=embed)
        
        expires = int(time.time()) + (7 * 24 * 3600)
        cur.execute("INSERT INTO active_ads (user_id, channel_id, message_id, is_personal, expires_at) VALUES (?, ?, ?, ?, ?)", (inter.author.id, new_channel.id, msg.id, 1, expires))
        db.commit()

        success_embed = disnake.Embed(
            title="✅ Реклама успешно опубликована!",
            description=f"Ваш личный канал создан: {new_channel.mention}\n> **Срок:** 1 неделя.",
            color=0x2ecc71
        )
        success_embed.set_image(url=IMG_STRIPE)
        await inter.channel.send(embed=success_embed)
        await inter.edit_original_response(content="Канал создан.")

class AdPublishConfirmView(ui.View):
    def __init__(self, item_name, text, ping, is_24h):
        super().__init__(timeout=None)
        self.item_name = item_name
        self.text = text
        self.ping = ping
        self.is_24h = is_24h
        
    @ui.button(label="✅ Опубликовать", style=ButtonStyle.success, custom_id="ad_pub_confirm")
    async def publish(self, button, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        button.disabled = True
        await inter.message.edit(view=self)

        guild = inter.guild
        ad_channel = guild.get_channel(ADS_CHANNEL_ID)
        if not ad_channel: return await inter.followup.send("❌ Канал не найден.", ephemeral=True)

        embed = disnake.Embed(description=self.text, color=0x2b2d31)
        msg = await ad_channel.send(content=self.ping, embed=embed)
        
        expires = int(time.time()) + (24 * 3600) if self.is_24h else 0
        cur.execute("INSERT INTO active_ads (user_id, channel_id, message_id, is_personal, expires_at) VALUES (?, ?, ?, ?, ?)", (inter.author.id, ad_channel.id, msg.id, 0, expires))
        db.commit()

        success_embed = disnake.Embed(
            title="✅ Реклама успешно опубликована!",
            description=f"Ваш пост отправлен в канал: {ad_channel.mention}\n> **Срок:** {'24 часа' if self.is_24h else 'Навсегда'}.",
            color=0x2ecc71
        )
        success_embed.set_image(url=IMG_STRIPE)
        await inter.channel.send(embed=success_embed)
        await inter.edit_original_response(content="Готово.")
