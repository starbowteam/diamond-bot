# -*- coding: utf-8 -*-
"""Бонус-панель: акция дня, рефералы, кейсы."""
from bonus.core import (
    init_bonus_tables,
    ensure_user_ref_link,
    get_user_by_ref_code,
    get_user_ref_stats,
    start_bonus_tasks,
    announce_deal_change,
    BONUS_CHANNEL_ID,
)
from bonus.views import BonusPanelView, build_panel_embeds


def init_bonus(bot):
    init_bonus_tables()
    start_bonus_tasks(bot)
