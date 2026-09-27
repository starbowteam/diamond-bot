#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Автозамена ссылок страйпа при каждом запуске
try:
    from fix_stripe import run_fix
    _stripe_stats = run_fix(verbose=False)
    if _stripe_stats["changed"] > 0:
        print(f"🔧 fix_stripe: обновлено {_stripe_stats['total_replacements']} ссылок в {_stripe_stats['changed']} файлах")
except Exception as e:
    print(f"⚠️ fix_stripe: {e}")

from core.bot import bot, CONFIG
from core.utils import logger
from modules.commands_staff import setup_commands_staff

if __name__ == "__main__":
    setup_commands_staff(bot)

    if not CONFIG["BOT_TOKEN"]:
        logger.error("BOT_TOKEN не установлен в переменных окружения")
        print("❌ Ошибка: не установлен BOT_TOKEN")
        sys.exit(1)

    try:
        bot.run(CONFIG["BOT_TOKEN"])
    except Exception as e:
        logger.exception("Ошибка запуска бота: %s", e)
        raise
