#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Главный запуск Diamond Shop."""
import os
import sys
import atexit
import signal
import logging
import traceback
import asyncio
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ============================================================
# 1. ГЛОБАЛЬНЫЙ ПЕРЕХВАТ ОШИБОК В ТЕРМИНАЛ
# ============================================================
def global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    print("\n" + "="*60, file=sys.stderr)
    print("🔴 ГЛОБАЛЬНАЯ ОШИБКА (СИНХРОННАЯ):", file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    print("="*60 + "\n", file=sys.stderr)

sys.excepthook = global_exception_handler

def async_exception_handler(loop, context):
    exception = context.get('exception')
    if exception:
        print("\n" + "="*60, file=sys.stderr)
        print("🔴 ГЛОБАЛЬНАЯ ОШИБКА (АСИНХРОННАЯ):", file=sys.stderr)
        traceback.print_exception(type(exception), exception, exception.__traceback__, file=sys.stderr)
        print("="*60 + "\n", file=sys.stderr)
    else:
        print(f"🔴 АСИНХРОННАЯ ОШИБКА БЕЗ ИСКЛЮЧЕНИЯ: {context.get('message')}", file=sys.stderr)

try:
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(async_exception_handler)
except Exception:
    pass

# ============================================================
# 2. ЗАПУСК МОДУЛЕЙ
# ============================================================
try:
    from modules.others import run_fix
    _stripe_stats = run_fix(verbose=False)
    if _stripe_stats["changed"] > 0:
        print(f"🔧 fix_stripe: обновлено {_stripe_stats['total_replacements']} ссылок")
except Exception as e:
    print(f"⚠️ fix_stripe: {e}")

from core.bot import bot, CONFIG
from core.utils import logger
from modules.commands_staff import setup_commands_staff

_ai_proc, _ai_manager_proc = None, None

def _start_subprocess(mode: str, name: str, env_key: str):
    if not os.getenv(env_key): 
        return None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", f"modules.{mode}"], 
            cwd=BASE_DIR, 
            stdout=sys.stdout, 
            stderr=sys.stderr
        )
        print(f"✅ {name} запущен (PID: {proc.pid})")
        return proc
    except Exception as e:
        logger.exception(f"Не удалось запустить {name}: {e}")
        return None

def _stop_subprocess(proc, name: str):
    if proc is None or proc.poll() is not None: return
    try:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: 
            proc.kill()
            proc.wait(timeout=3)
        print(f"🛑 {name} остановлен")
    except Exception: pass

def _stop_all():
    _stop_subprocess(_ai_proc, "AI-консультант")
    _stop_subprocess(_ai_manager_proc, "AI-менеджер")

def _sigterm_handler(signum, frame):
    _stop_all()
    sys.exit(0)

# ============================================================
# 3. СТАРТ
# ============================================================
if __name__ == "__main__":
    setup_commands_staff(bot)
    if not CONFIG["BOT_TOKEN"]: 
        print("❌ Ошибка: не установлен BOT_TOKEN")
        sys.exit(1)

    try:
        from core.catalog import auto_init
        print(f"📦 Каталог: {auto_init()} товаров")
    except Exception as e: 
        logger.warning(f"auto_init catalog: {e}")

    try:
        from modules.cases import init_cases_tables
        init_cases_tables()
    except Exception as e: 
        logger.warning(f"init_cases_tables: {e}")

    _ai_proc = _start_subprocess("ai", "AI-консультант", "AI_TOKEN")
    _ai_manager_proc = _start_subprocess("ai_manager", "AI-менеджер", "AI_MANAGER_TOKEN")

    atexit.register(_stop_all)
    signal.signal(signal.SIGTERM, _sigterm_handler)

    try: 
        bot.run(CONFIG["BOT_TOKEN"])
    except KeyboardInterrupt: 
        print("\n🛑 Остановлено вручную")
    except Exception as e: 
        logger.exception("Ошибка запуска бота: %s", e)
        traceback.print_exc()
    finally: 
        _stop_all()
