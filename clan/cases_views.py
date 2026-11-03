# -*- coding: utf-8 -*-
"""UI для кейсов внутри клан-игр."""
import asyncio
import disnake
from disnake import ButtonStyle, PartialEmoji, SelectOption
from disnake.ui import View, Button, Select

from core.utils import logger
from modules.dc import get_user_balance
from clan import cases as ccore
from clan import cases_render as crender

P = "\u3164"
E_SHOP  = PartialEmoji(name="shop1", id=1555654407776112750)
E_PRIZE = PartialEmoji(name="prize", id=1539657202170859561)

E_CASE_1 = PartialEmoji(name="odin",    id=1557754584158441574)
E_CASE_2 = PartialEmoji(name="dva",     id=1557754603389583370)
E_CASE_3 = PartialEmoji(name="tri",     id=1557754619252179066)
E_CASE_4 = PartialEmoji(name="chetiry", id=1557754636100833340)
E_CASE_5 = PartialEmoji(name="puiat",   id=1557754652316139592)

CASE_EMOJI = {1: E_CASE_1, 2: E_CASE_2, 3: E_CASE_3, 4: E_CASE_4, 5: E_CASE_5}

def _btn_pad(text: str, total: int) -> str:
    base = len(text)
    extra = max(0, total - base)
    left = extra // 2
    right = extra - left
    return f"{P * left}{text}{P * right}"

def _btn_labels_total(labels, total):
    base = sum(len(s) for s in labels)
    extra = max(0, total - base)
    n = len(labels)
    if n == 0: return labels
    per = extra // n
    rem = extra % n
    result = []
    for i, s in enumerate(labels):
        pad = per + (1 if i < rem else 0)
        left = pad // 2
        right = pad - left
        result.append(f"{P * left}{s}{P * right}")
    return result

_L_AGAIN, _L_MYCASES = _btn_labels_total(["Купить ещё", "Мои кейсы"], 32)

class CaseSelect(Select):
    def __init__(self):
        options = []
        for case in ccore.CASES:
            desc = (case.get("desc") or "").strip()
            if len(desc) > 95: desc = desc[:92] + "..."
            options.append(SelectOption(
                label=f"{case['name']} · {case['price']} DC",
                description=desc or f"Кейс за {case['price']} DC",
                emoji=CASE_EMOJI.get(case["num"]),
                value=str(case["num"]),
            ))
        super().__init__(
            placeholder="Выбери кейс для открытия...",
            min_values=1, max_values=1,
            options=options, custom_id="clan_case_select",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        try:
            case_num = int(inter.data.values[0])
        except Exception:
            return
        await _open_case(inter, case_num)


class CasesSelectView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(CaseSelect())


class CaseAfterView(View):
    def __init__(self):
        super().__init__(timeout=300)
        btn_again = Button(label=_L_AGAIN, style=ButtonStyle.secondary, custom_id="clan_after:again", emoji=E_SHOP, row=0)
        btn_again.callback = self._again
        self.add_item(btn_again)

        btn_my = Button(label=_L_MYCASES, style=ButtonStyle.secondary, custom_id="clan_after:mycases", emoji=E_PRIZE, row=0)
        btn_my.callback = self._mycases
        self.add_item(btn_my)

    async def _again(self, inter):
        await _switch_to_cases(inter)

    async def _mycases(self, inter):
        await _switch_to_mycases(inter)


class MyCasesBackView(View):
    def __init__(self):
        super().__init__(timeout=300)
        btn = Button(label=_btn_pad("К кейсам", 33), style=ButtonStyle.secondary, custom_id="clan_mycases:back", row=0)
        btn.callback = self._back
        self.add_item(btn)

    async def _back(self, inter):
        await _switch_to_cases(inter)

# ============================================================
# ЭКРАНЫ
# ============================================================
async def show_cases_screen(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    stats = ccore.get_case_stats(user_id)

    buf = await asyncio.to_thread(crender.render_cases, user_id, inter.author.display_name, balance, stats)
    fname = f"cases_{user_id}.png"
    file = disnake.File(buf, filename=fname)
    e = disnake.Embed(color=6776679)
    e.set_image(url=f"attachment://{fname}")

    try:
        await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=CasesSelectView())
    except Exception:
        await inter.followup.send(embeds=[e], file=file, view=CasesSelectView(), ephemeral=True)


async def _switch_to_cases(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    user_id = inter.author.id
    balance = await get_user_balance(user_id)
    stats = ccore.get_case_stats(user_id)

    buf = await asyncio.to_thread(crender.render_cases, user_id, inter.author.display_name, balance, stats)
    fname = f"cases_{user_id}.png"
    file = disnake.File(buf, filename=fname)
    e = disnake.Embed(color=6776679)
    e.set_image(url=f"attachment://{fname}")

    await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=CasesSelectView())


async def _switch_to_mycases(inter: disnake.MessageInteraction):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    user_id = inter.author.id
    stats = ccore.get_case_stats(user_id)
    history = ccore.get_case_history(user_id, limit=8)
    
    buf = await asyncio.to_thread(crender.render_my_cases, user_id, inter.author.display_name, stats, history)
    fname = f"mycases_{user_id}.png"
    file = disnake.File(buf, filename=fname)
    e = disnake.Embed(color=6776679)
    e.set_image(url=f"attachment://{fname}")

    await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=MyCasesBackView())


async def _open_case(inter: disnake.MessageInteraction, case_num: int):
    try:
        await inter.response.defer(ephemeral=True)
    except Exception:
        pass

    case = ccore.CASES_BY_NUM.get(case_num)
    if not case:
        return await inter.followup.send("❌ Кейс не найден", ephemeral=True)

    balance = await get_user_balance(inter.author.id)
    if balance < case["price"]:
        return await inter.followup.send(f"❌ Нужно **{case['price']} DC**, у тебя **{balance} DC**.", ephemeral=True)

    try:
        buf = await asyncio.to_thread(crender.render_spin, case)
        fname = f"spin_{inter.author.id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=None)
    except Exception as e:
        logger.exception(f"spin render: {e}")

    await asyncio.sleep(2.0)

    result = await ccore.open_case(inter.bot, inter.author.id, case_num)
    if not result["ok"]:
        return await inter.followup.send(f"❌ {result.get('error', 'Ошибка')}", ephemeral=True)

    new_balance = await get_user_balance(inter.author.id)
    try:
        buf = await asyncio.to_thread(crender.render_result, case, result["prize"], result["desc"], new_balance)
        fname = f"result_{inter.author.id}.png"
        file = disnake.File(buf, filename=fname)
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{fname}")
        await inter.edit_original_response(embeds=[e], file=file, attachments=[], view=CaseAfterView())
    except Exception as e:
        logger.exception(f"result render: {e}")
        await inter.followup.send(f"🎉 Выпало: **{result['desc']}**", ephemeral=True)
