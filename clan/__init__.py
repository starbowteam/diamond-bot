# -*- coding: utf-8 -*-
"""Клановая лига Diamond — точка входа пакета."""
from clan.core import init_clan_core
from clan.quests import init_clan_quests
from clan.achievements import init_achievements
from clan.panels import init_clan_panels, start_clan_tasks
from clan._cleanup_achievements import run_cleanup_achievements


def init_clan_league(bot):
    """Инициализация всей лиги. Вызывается один раз из bot.on_ready()."""

    # ⚠️ ОДНОРАЗОВО: чистка старых достижений.
    # Удали эту строку (и файл clan/_cleanup_achievements.py)
    # после первого успешного запуска.
    run_cleanup_achievements()

    init_clan_core()
    init_clan_quests()
    init_achievements()
    init_clan_panels()
    start_clan_tasks(bot)
