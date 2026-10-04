#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа. Запускает ДВА бота в одном процессе:
  · Основного (BOT_TOKEN) — магазин
  · AI-помощника (AI_TOKEN) — консультант в одном канале

Оба работают параллельно через asyncio.gather.
"""
import os
import sys
import asyncio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ─── Автозамена ссылок страйпа при каждом запуске ───
try:
    from modules.others import run_fix
    _stripe_stats = run_fix(verbose=False)
    if _stripe_stats["changed"] > 0:
        print(f"🔧 fix_stripe: обновлено {_stripe_stats['total_replacements']} ссылок в {_stripe_stats['changed']} файлах")
except Exception as e:
    print(f"⚠️ fix_stripe: {e}")

# ─── Импорт ботов ───
from core.bot import bot as main_bot, CONFIG
from core.utils import logger
from modules.commands_staff import setup_commands_staff


async def _run_all():
    # Регистрация слэш-команд основного бота
    setup_commands_staff(main_bot)

    if not CONFIG["BOT_TOKEN"]:
        logger.error("BOT_TOKEN не установлен в переменных окружения")
        print("❌ Ошибка: не установлен BOT_TOKEN")
        sys.exit(1)

    # Собираем задачи
    tasks = [main_bot.start(CONFIG["BOT_TOKEN"])]
    names = ["MAIN"]

    # AI — только если есть токен
    ai_token = os.getenv("AI_TOKEN")
    if ai_token:
        try:
            from modules.ai import ai_bot
            tasks.append(ai_bot.start(ai_token))
            names.append("AI")
            print("✅ Запускаю двух ботов: MAIN + AI")
        except Exception as e:
            logger.exception(f"AI не запущен: {e}")
            print(f"⚠️ AI не запущен: {e}")
    else:
        print("⚠️ AI_TOKEN не установлен — запускаю только основного бота")

    # Оборачиваем каждый в отдельную корутину, чтобы падение одного
    # не убивало другого
    async def _safe_start(name: str, coro):
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"[{name}] бот упал: {e}")

    await asyncio.gather(
        *[_safe_start(n, t) for n, t in zip(names, tasks)],
        return_exceptions=False,
    )


if __name__ == "__main__":
    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        print("\n🛑 Остановлено пользователем")
    except Exception as e:
        logger.exception("Ошибка запуска: %s", e)
        raise
