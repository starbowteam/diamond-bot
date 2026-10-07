# -*- coding: utf-8 -*-
"""Инвайт-панель адвайтеров."""
from work.core import (
    init_advertiser_tables,
    register_invite_join,
    register_invite_leave,
    reward_check_task,
)
from work.views import AdvertiserPanelView, AdvertiserActionsView, build_panel_embeds


def init_advertiser(bot):
    init_advertiser_tables()
