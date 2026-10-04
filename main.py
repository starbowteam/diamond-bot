#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа. Запускает ДВА бота:
  · Основного (BOT_TOKEN) — в этом процессе
  · AI-помощника (AI_TOKEN) — отдельным subprocess-ом

Оба стартуют от одной команды `python main.py`.
При остановке main.py — AI тоже корректно гасится.
"""
import os
import sys
import atexit
import signal
import subprocess

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

from core.bot import bot, CONFIG
from core.utils import logger
from modules.commands_staff import setup_commands_staff


# ============================================================
# AI — отдельный процесс
# ============================================================
_ai_proc: subprocess.Popen = None


def _start_ai_subprocess():
    """Запускает ai_main.py отдельным процессом. Возвращает Popen или None."""
    global _ai_proc

    if not os.getenv("AI_TOKEN"):
        print("⚠️ AI_TOKEN не установлен — AI-бот не будет запущен")
        return None

    try:
        _ai_proc = subprocess.Popen(
            [sys.executable, "-u", "ai_main.py"],
            cwd=BASE_DIR,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        print(f"✅ AI-бот запущен отдельным процессом (PID: {_ai_proc.pid})")
        return _ai_proc
    except Exception as e:
        logger.exception(f"Не удалось запустить AI: {e}")
        print(f"⚠️ AI не запущен: {e}")
        return None


def _stop_ai_subprocess():
    """Гасит AI-процесс, если он ещё жив."""
    if _ai_proc is None:
        return
    if _ai_proc.poll() is not None:
        return
    try:
        _ai_proc.terminate()
        try:
            _ai_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ai_proc.kill()
            _ai_proc.wait(timeout=3)
        print("🛑 AI-бот остановлен")
    except Exception as e:
        logger.warning(f"_stop_ai_subprocess: {e}")


def _sigterm_handler(signum, frame):
    _stop_ai_subprocess()
    sys.exit(0)


# ============================================================
# RUN
# ============================================================
if __name__ == "__main__":
    setup_commands_staff(bot)

    if not CONFIG["BOT_TOKEN"]:
        logger.error("BOT_TOKEN не установлен в переменных окружения")
        print("❌ Ошибка: не установлен BOT_TOKEN")
        sys.exit(1)

    # Запускаем AI отдельным процессом
    _start_ai_subprocess()

    # Гарантируем остановку AI при выходе main
    atexit.register(_stop_ai_subprocess)
    signal.signal(signal.SIGTERM, _sigterm_handler)

    # Запускаем основного бота
    try:
        bot.run(CONFIG["BOT_TOKEN"])
    except KeyboardInterrupt:
        print("\n🛑 Остановлено пользователем")
    except Exception as e:
        logger.exception("Ошибка запуска бота: %s", e)
        raise
    finally:
        _stop_ai_subprocess()
