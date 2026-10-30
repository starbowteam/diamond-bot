#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа. Запускает ТРИ бота:
  · Основной (BOT_TOKEN)
  · AI-консультант (AI_TOKEN)
  · AI-менеджер (AI_MANAGER_TOKEN)
"""
import os
import sys
import atexit
import signal
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

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


_ai_proc: subprocess.Popen = None
_ai_manager_proc: subprocess.Popen = None


def _start_subprocess(script: str, name: str, env_key: str):
    if not os.getenv(env_key):
        print(f"⚠️ {env_key} не установлен — {name} не будет запущен")
        return None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", script],
            cwd=BASE_DIR,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        print(f"✅ {name} запущен (PID: {proc.pid})")
        return proc
    except Exception as e:
        logger.exception(f"Не удалось запустить {name}: {e}")
        return None


def _stop_subprocess(proc, name: str):
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        print(f"🛑 {name} остановлен")
    except Exception as e:
        logger.warning(f"_stop_subprocess({name}): {e}")


def _stop_all():
    _stop_subprocess(_ai_proc, "AI-консультант")
    _stop_subprocess(_ai_manager_proc, "AI-менеджер")


def _sigterm_handler(signum, frame):
    _stop_all()
    sys.exit(0)


if __name__ == "__main__":
    setup_commands_staff(bot)

    if not CONFIG["BOT_TOKEN"]:
        logger.error("BOT_TOKEN не установлен")
        print("❌ Ошибка: не установлен BOT_TOKEN")
        sys.exit(1)

    _ai_proc = _start_subprocess("ai_main.py", "AI-консультант", "AI_TOKEN")
    _ai_manager_proc = _start_subprocess("ai_manager_main.py", "AI-менеджер", "AI_MANAGER_TOKEN")

    atexit.register(_stop_all)
    signal.signal(signal.SIGTERM, _sigterm_handler)

    try:
        bot.run(CONFIG["BOT_TOKEN"])
    except KeyboardInterrupt:
        print("\n🛑 Остановлено пользователем")
    except Exception as e:
        logger.exception("Ошибка запуска бота: %s", e)
        raise
    finally:
        _stop_all()
