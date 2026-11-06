#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Единая точка входа. Запускает ТРИ бота в одном процессе:
  · Основной (BOT_TOKEN)
  · AI-консультант (AI_TOKEN)
  · AI-менеджер (AI_MANAGER_TOKEN)
"""
import os
import sys
import asyncio
import logging

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ─── Автозамена ссылок страйпа ───
try:
    from modules.others import run_fix
    _stripe_stats = run_fix(verbose=False)
    if _stripe_stats["changed"] > 0:
        print(f"🔧 fix_stripe: обновлено {_stripe_stats['total_replacements']} ссылок в {_stripe_stats['changed']} файлах")
except Exception as e:
    print(f"⚠️ fix_stripe: {e}")

# Импортируем только основного бота и утилиты на верхнем уровне
from core.bot import bot as main_bot, CONFIG
from core.utils import logger
from modules.commands_staff import setup_commands_staff

# Отключаем спам от disnake в консоли
logging.getLogger("disnake").setLevel(logging.WARNING)

async def start_all():
    # Настраиваем команды для основного бота
    setup_commands_staff(main_bot)

    if not CONFIG["BOT_TOKEN"]:
        logger.error("BOT_TOKEN не установлен")
        print("❌ Ошибка: не установлен BOT_TOKEN")
        sys.exit(1)

    # ─── Автоинициализация каталога ───
    try:
        from core.catalog import auto_init
        _catalog_count = auto_init()
        print(f"📦 Каталог Автозаказа: {_catalog_count} товаров")
    except Exception as e:
        logger.warning(f"auto_init catalog: {e}")

    tasks = []
    
    # 1. Основной бот
    tasks.append(main_bot.start(CONFIG["BOT_TOKEN"]))
    print("⏳ Запуск основного бота...")

    # 2. AI-консультант (импорт внутри запущенного цикла!)
    try:
        from modules.ai import bot as ai_bot, AI_TOKEN
        if ai_bot and AI_TOKEN:
            tasks.append(ai_bot.start(AI_TOKEN))
            print("⏳ Запуск AI-консультанта...")
        else:
            print("⚠️ AI_TOKEN не установлен — AI-консультант не запущен")
    except ImportError as e:
        logger.error(f"Ошибка импорта AI: {e}")

    # 3. AI-менеджер (импорт внутри запущенного цикла!)
    try:
        from modules.ai_manager import bot as ai_manager_bot, AI_MANAGER_TOKEN, AI_MANAGER_API_KEY
        if ai_manager_bot and AI_MANAGER_TOKEN and AI_MANAGER_API_KEY:
            tasks.append(ai_manager_bot.start(AI_MANAGER_TOKEN))
            print("⏳ Запуск AI-менеджера...")
        else:
            print("⚠️ AI_MANAGER_TOKEN или API_KEY не установлен — AI-менеджер не запущен")
    except ImportError as e:
        logger.error(f"Ошибка импорта AI Manager: {e}")

    if not tasks:
        print("❌ Нет активных ботов для запуска.")
        return

    print("✅ Все боты отправлены на подключение. Ожидание событий...\n")
    
    # Запускаем параллельно. Если один упадет, остальные продолжат работу.
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Если один из ботов упал, логируем это
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            logger.error(f"Один из ботов упал с ошибкой: {res}")

def main():
    try:
        # asyncio.run сам создает нужный цикл, запускает корутину и корректно закрывает цикл
        asyncio.run(start_all())
    except KeyboardInterrupt:
        print("\n🛑 Остановлено пользователем (Ctrl+C)")
    except Exception as e:
        logger.exception(f"Критическая ошибка при запуске: {e}")

if __name__ == "__main__":
    main()
