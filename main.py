#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

# Добавляем пути к модулям (чтобы import core и modules работали)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core.bot import bot, CONFIG, log_discord
from core.utils import logger
from modules.commands_admin import setup_commands_admin

if __name__ == "__main__":
    # Регистрируем команды из модуля админ
    setup_commands_admin(bot)

    if not CONFIG["BOT_TOKEN"]:
        logger.error("BOT_TOKEN не установлен в переменных окружения")
        print("❌ Ошибка: не установлен BOT_TOKEN")
        sys.exit(1)

    try:
        bot.run(CONFIG["BOT_TOKEN"])
    except Exception as e:
        logger.exception("Ошибка запуска бота: %s", e)
        raise
