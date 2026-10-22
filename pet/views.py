# -*- coding: utf-8 -*-
import asyncio
import disnake
from disnake import ButtonStyle, PartialEmoji
from disnake.ui import View, Button, Modal, TextInput

from core.utils import logger, get_dc_cache
from clan.core import get_user_clan
from pet import core as pcore
from pet import render as prender

P = "\u3164"

E_FEED = PartialEmoji(name="drumstick", id=1539657202170859561)
E_TOP = PartialEmoji(name="prize", id=1539657202170859561)
E_ABOUT = PartialEmoji(name="info", id=1539657202170859561)
E_CLAIM = PartialEmoji(name="1d1ds", id=1552730624572391584)

class ClanPetMainView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label=f"Покормить{P}", style=ButtonStyle.gray, custom_id="cp_main:feed", emoji=E_FEED, row=0)
    async def feed(self, button, inter):
        await inter.response.send_modal(FeedPetModal())

    @disnake.ui.button(label=f"Забрать доход{P}", style=ButtonStyle.gray, custom_id="cp_main:claim", emoji=E_CLAIM, row=0)
    async def claim(self, button, inter):
        try: await inter.response.defer(ephemeral=True)
        except: pass
        
        clan = get_user_clan(inter.author.id)
        if not clan: return await inter.followup.send("❌ Ты не в клане.", ephemeral=True)
        
        amount = await pcore.claim_pet_income(clan["id"])
        if amount <= 0:
            return await inter.followup.send("❌ Питомец ещё ничего не накопил.", ephemeral=True)
            
        await inter.followup.send(f"✅ Собрано **{amount:,} DC** в копилку клана!", ephemeral=True)
        
        balance = get_dc_cache(inter.author.id).get("balance", 0)
        buf = await asyncio.to_thread(prender.render_pet_main, inter.author.id, clan["name"], clan["id"], balance)
        fname = f"cp_main_{inter.author.id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        await inter.edit_original_response(embed=e, file=file, attachments=[], view=self)

    @disnake.ui.button(label=f"Топ кормильцев{P}", style=ButtonStyle.gray, custom_id="cp_main:top", emoji=E_TOP, row=0)
    async def top(self, button, inter):
        try: await inter.response.defer(ephemeral=True)
        except: pass
        clan = get_user_clan(inter.author.id)
        if not clan: return await inter.followup.send("❌ Ты не в клане.", ephemeral=True)
        top_list = pcore.get_clan_pet_top(clan["id"])
        buf = await asyncio.to_thread(prender.render_pet_top, inter.author.id, clan["name"], clan["id"], top_list)
        fname = f"cp_top_{inter.author.id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        await inter.followup.send(embed=e, file=file, ephemeral=True)

    @disnake.ui.button(label=f"О питомце{P}", style=ButtonStyle.gray, custom_id="cp_main:about", emoji=E_ABOUT, row=0)
    async def about(self, button, inter):
        try: await inter.response.defer(ephemeral=True)
        except: pass
        clan = get_user_clan(inter.author.id)
        if not clan: return await inter.followup.send("❌ Ты не в клане.", ephemeral=True)
        buf = await asyncio.to_thread(prender.render_pet_about, inter.author.id, clan["name"], clan["id"])
        fname = f"cp_about_{inter.author.id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        await inter.followup.send(embed=e, file=file, ephemeral=True)

class FeedPetModal(Modal):
    def __init__(self):
        super().__init__(
            title="Покормить питомца",
            components=[TextInput(label="Сколько DC скормить?", placeholder="Например: 5000", custom_id="amount", min_length=1, max_length=10)]
        )

    async def callback(self, inter: disnake.ModalInteraction):
        raw = inter.text_values["amount"].strip()
        if not raw.isdigit():
            return await inter.response.send_message("❌ Введи целое число.", ephemeral=True)
            
        amount = int(raw)
        try: await inter.response.defer(ephemeral=True)
        except: pass

        result = await pcore.feed_clan_pet(inter.author.id, amount)
        if not result["ok"]:
            return await inter.followup.send(f"❌ {result['error']}", ephemeral=True)

        msg = f"✅ Ты скормил **{amount:,} DC** питомцу! Получено **+{result['xp_added']} XP**."
        if result["leveled_up"]: msg += f"\n🎉 **Питомец повысил уровень до {result['new_level']}!**"
            
        await inter.followup.send(msg, ephemeral=True)

        clan = get_user_clan(inter.author.id)
        balance = get_dc_cache(inter.author.id).get("balance", 0)
        buf = await asyncio.to_thread(prender.render_pet_main, inter.author.id, clan["name"], clan["id"], balance)
        fname = f"cp_main_{inter.author.id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        await inter.followup.send(embed=e, file=file, ephemeral=True)
