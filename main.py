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
import signal
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

# Импортируем ботов и их токены
from core.bot import bot as main_bot, CONFIG
from core.utils import logger
from modules.commands_staff import setup_commands_staff

# Отключаем лишний спам от disnake в консоли
logging.getLogger("disnake").setLevel(logging.WARNING)

# Безопасный импорт AI
try:
    from modules.ai import bot as ai_bot, AI_TOKEN
except ImportError as e:
    logger.error(f"Ошибка импорта AI: {e}")
    ai_bot = None
    AI_TOKEN = None

# Безопасный импорт AI-менеджера
try:
    from modules.ai_manager import bot as ai_manager_bot, AI_MANAGER_TOKEN, AI_MANAGER_API_KEY
except ImportError as e:
    logger.error(f"Ошибка импорта AI Manager: {e}")
    ai_manager_bot = None
    AI_MANAGER_TOKEN = None
    AI_MANAGER_API_KEY = None

async def start_all():
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

    # 2. AI-консультант
    if ai_bot and AI_TOKEN:
        tasks.append(ai_bot.start(AI_TOKEN))
        print("⏳ Запуск AI-консультанта...")
    else:
        print("⚠️ AI_TOKEN не установлен — AI-консультант не запущен")

    # 3. AI-менеджер
    if ai_manager_bot and AI_MANAGER_TOKEN and AI_MANAGER_API_KEY:
        tasks.append(ai_manager_bot.start(AI_MANAGER_TOKEN))
        print("⏳ Запуск AI-менеджера...")
    else:
        print("⚠️ AI_MANAGER_TOKEN или AI_MANAGER_API_KEY не установлен — AI-менеджер не запущен")

    if not tasks:
        print("❌ Нет активных ботов для запуска.")
        return

    # Запускаем все задачи параллельно. 
    # return_exceptions=True не даст одному упавшему боту убить остальные.
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Если мы дошли сюда, значит один из ботов упал или завершился
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            logger.error(f"Бот упал с ошибкой: {res}")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    main_task = loop.create_task(start_all())

    def shutdown():
        print("\n🛑 Остановка всех ботов...")
        for task in asyncio.all_tasks(loop):
            task.cancel()
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            pass # Для Windows

    try:
        loop.run_until_complete(main_task)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        print("\n🛑 Остановлено пользователем")
    except Exception as e:
        logger.exception(f"Критическая ошибка: {e}")
    finally:
        print("Завершение работы...")
        loop.close()

if __name__ == "__main__":
    main()
