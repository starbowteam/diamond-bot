# -*- coding: utf-8 -*-
"""
Discord-view панели достижений.
2 кнопки: Назад / Вперёд. Суммарная длина подписей — 29 символов.
Без селекта. Каждая категория — отдельная страница.
На первой странице «Назад» возвращает профиль.
При открытии — тихий догон достижений для юзера.
"""
import asyncio
from datetime import datetime, timezone

import disnake
from disnake import ButtonStyle, PartialEmoji
from disnake.ui import View, Button

from core.utils import logger, load_json, FILES, get_dc_cache
from clan.achievements import (
    CATEGORY_ORDER,
    check_and_unlock,
    get_user_unlocked_set,
)
from modules.achievements_panel import generate_achievements_panel


P = "\u3164"
BTN_LABEL_TOTAL = 29


# ============================================================
# ХЕЛПЕР ПОДПИСЕЙ
# ============================================================
def _btn_labels_total(labels, total=BTN_LABEL_TOTAL):
    """Добивает подписи невидимыми пробелами так, чтобы СУММА == total."""
    base = sum(len(s) for s in labels)
    extra = max(0, total - base)
    n = len(labels)
    if n == 0:
        return labels
    per = extra // n
    rem = extra % n
    result = []
    for i, s in enumerate(labels):
        pad = per + (1 if i < rem else 0)
        left = pad // 2
        right = pad - left
        result.append(f"{P * left}{s}{P * right}")
    return result


_L_BACK, _L_FWD = _btn_labels_total(["Назад", "Вперёд"])


# ============================================================
# ЭМОДЗИ
# ============================================================
EMOJI_BACK = PartialEmoji(name="baa1", id=1557224983539749004)
EMOJI_FWD  = PartialEmoji(name="rid1", id=1557225225265332816 if False else 1557225020265332816)


# ============================================================
# ТИХИЙ ДОГОН
# ============================================================
async def _catchup_for_user(user_id: int):
    """
    Тихий догон: проверяем простые триггеры и доедаем всё,
    что юзер заслужил, но не получил (например, если зашёл
    до фикса или пересчёт не прошёл). Без ЛС, без логов.
    """
    # ── Баланс + первая покупка ──
    try:
        dc = get_dc_cache(user_id)
        bal = dc.get("balance", 0) or 0
        if bal > 0:
            await check_and_unlock(user_id, "balance", value=bal)
        if dc.get("purchases"):
            await check_and_unlock(user_id, "first_purchase", value=1)
    except Exception as e:
        logger.debug(f"catchup balance {user_id}: {e}")

    # ── Отзывы + роль-тир ──
    try:
        counts = load_json(FILES["review_counts"], {})
        rc = int(counts.get(str(user_id), 0) or 0)
        if rc > 0:
            await check_and_unlock(user_id, "reviews", value=rc)
            await check_and_unlock(user_id, "buyer_count", value=rc)
            await check_and_unlock(user_id, "first_review", value=1)
    except Exception as e:
        logger.debug(f"catchup reviews {user_id}: {e}")

    # ── Клан: вклад ──
    try:
        from clan.core import get_user_clan, get_user_contribution
        if get_user_clan(user_id):
            contrib = get_user_contribution(user_id)
            await check_and_unlock(user_id, "clan_deposit", value=contrib)
    except Exception as e:
        logger.debug(f"catchup clan {user_id}: {e}")

    # ── Казино: партии ──
    try:
        from modules.actions import load_roulette_stats
        st = load_roulette_stats()
        rolls = int(st.get("rolls", 0) or 0)
        if rolls > 0:
            await check_and_unlock(user_id, "casino_games", value=rolls)
    except Exception as e:
        logger.debug(f"catchup casino {user_id}: {e}")

    # ── Квесты ──
    try:
        from core.utils import cur
        row = cur.execute(
            "SELECT COUNT(*) AS c FROM quest_progress "
            "WHERE user_id=? AND completed_at IS NOT NULL",
            (user_id,)
        ).fetchone()
        qc = row["c"] if row else 0
        if qc > 0:
            await check_and_unlock(user_id, "quests", value=qc)
    except Exception as e:
        logger.debug(f"catchup quests {user_id}: {e}")


# ============================================================
# РЕНДЕР СТРАНИЦЫ
# ============================================================
async def render_category(inter: disnake.MessageInteraction,
                          category_key: str):
    """Обновляет сообщение: рендерит панель для указанной категории."""
    if category_key not in CATEGORY_ORDER:
        category_key = CATEGORY_ORDER[0]

    # 👇 тихий догон перед рендером
    try:
        await _catchup_for_user(inter.author.id)
    except Exception as e:
        logger.warning(f"ach catchup: {e}")

    try:
        buf = await asyncio.to_thread(
            generate_achievements_panel,
            inter.author.id,
            category_key,
        )
        fname = (
            f"ach_{inter.author.id}_"
            f"{int(datetime.now(timezone.utc).timestamp())}.png"
        )
        file = disnake.File(buf, filename=fname)
        embed = disnake.Embed(color=6776679)
        embed.set_image(url=f"attachment://{fname}")

        view = AchievementsPanelView(category_key)
        kwargs = dict(embed=embed, file=file, attachments=[], view=view)

        if inter.response.is_done():
            await inter.edit_original_response(**kwargs)
        else:
            await inter.response.edit_message(**kwargs)
    except Exception as e:
        logger.exception(f"render_category: {e}")
        try:
            if inter.response.is_done():
                await inter.followup.send(f"❌ {str(e)[:200]}", ephemeral=True)
            else:
                await inter.response.send_message(f"❌ {str(e)[:200]}", ephemeral=True)
        except Exception:
            pass


async def _return_to_profile(inter: disnake.MessageInteraction):
    """Возвращает карточку профиля с 3 кнопками — редактирует текущее сообщение."""
    try:
        from modules.commands_profile import (
            render_profile_into_interaction, ProfileCardView,
        )
        await render_profile_into_interaction(
            inter, inter.author, ProfileCardView(),
        )
    except Exception as e:
        logger.exception(f"_return_to_profile: {e}")


# ============================================================
# VIEW
# ============================================================
class AchievementsPanelView(View):
    def __init__(self, category_key: str = "base"):
        super().__init__(timeout=300)
        self.category_key = category_key

        idx = CATEGORY_ORDER.index(category_key) if category_key in CATEGORY_ORDER else 0
        self._idx = idx

        b_back = Button(
            label=_L_BACK,
            style=ButtonStyle.gray,
            custom_id="ach_panel:back",
            emoji=EMOJI_BACK,
            row=0,
        )
        b_back.callback = self._on_back
        self.add_item(b_back)

        b_fwd = Button(
            label=_L_FWD,
            style=ButtonStyle.gray,
            custom_id="ach_panel:fwd",
            emoji=EMOJI_FWD,
            row=0,
        )
        b_fwd.callback = self._on_fwd
        self.add_item(b_fwd)

    async def _on_back(self, inter: disnake.MessageInteraction):
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

        # На первой странице — возвращаем профиль
        if self._idx <= 0:
            await _return_to_profile(inter)
            return

        new_key = CATEGORY_ORDER[self._idx - 1]
        await render_category(inter, new_key)

    async def _on_fwd(self, inter: disnake.MessageInteraction):
        try:
            await inter.response.defer(ephemeral=True)
        except Exception:
            pass

        # На последней странице — заворачиваем на первую
        if self._idx >= len(CATEGORY_ORDER) - 1:
            new_key = CATEGORY_ORDER[0]
        else:
            new_key = CATEGORY_ORDER[self._idx + 1]

        await render_category(inter, new_key)
