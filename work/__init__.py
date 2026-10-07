# -*- coding: utf-8 -*-
"""Инвайт-панель адвайтеров."""
from work.core import (
    init_advertiser_tables,
    ensure_advertiser_link,
    get_advertiser_by_code,
    register_invite_leave,
    reward_check_task,
    start_advertiser_tasks,
)
from work.views import (
    AdvertiserPanelView,
    AdvertiserActionsView,
    build_panel_embeds,
)


def init_advertiser(bot):
    init_advertiser_tables()
