# -*- coding: utf-8 -*-
"""Клановая лига Diamond — точка входа пакета."""
from clan.core import init_clan_core
from clan.quests import init_clan_quests
from clan.panels import init_clan_panels, start_clan_tasks


def init_clan_league(bot):
    """Инициализация всей лиги. Вызывается один раз из bot.on_ready()."""
    init_clan_core()
    init_clan_quests()
    init_clan_panels()
    start_clan_tasks(bot)
