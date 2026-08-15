#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.bot import bot, CONFIG
from core.utils import logger
from modules.commands import setup_commands

if __name__ == "__main__":
    # Регистрируем команды
    setup_commands(bot)

    if not CONFIG["BOT_TOKEN"]:
        logger.error("BOT_TOKEN не установлен в переменных окружения")
        sys.exit(1)

    try:
        bot.run(CONFIG["BOT_TOKEN"])
    except Exception as e:
        logger.exception("Ошибка запуска бота: %s", e)
        raise
