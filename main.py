#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Главный запуск Diamond Shop.
Включает в себя:
  1. Авто-очистку рендеров от дублей (clean_render_utils).
  2. Глобальный перехват ошибок в терминал.
  3. Запуск основного бота.
  4. Запуск фоновых процессов (AI, AI Manager).
"""
import os
import sys
import re
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

# Применяем хэндлер к текущему event loop
try:
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(async_exception_handler)
except Exception:
    pass

# ============================================================
# 2. АВТО-ОЧИСТКА РЕНДЕРОВ
# ============================================================
TARGET_RENDER_FILES = [
    "modules/shop/render.py", "modules/shop/render_gift.py", "modules/shop/render_profile.py",
    "modules/shop/render_quests.py", "modules/casino_render.py", "modules/tickets.py",
    "modules/achievements_panel.py", "modules/profile_card.py", "modules/autoorder.py",
    "clan/render.py", "bonus/render.py", "pet/render.py"
]

SKIP_KEYWORDS = [
    "def _font(", "def _fa(", "def _tw(", "def _ellipsis(", "def _wrap(", "def _fmt(",
    "def _icon(", "def _alpha_fill(", "def _gradient_box(", "def _draw_stack_panel(", "def _draw_dashed_rect(",
    "def _lighten(", "def _darken(", "FONT_BOLD = ", "FONT_FA = ", "_FONT_CACHE = ", "_FA_CACHE = ",
    "BG = ", "CARD_TOP = ", "STACK_BG = ", "STACK_BRD = ", "STACK_HDR = ", "INNER_BG = ", "INNER_BRD = ",
    "TEXT = ", "TEXT_SOFT = ", "MUTED = ", "DIM = ", "DARK = ", "SILVER = ", "SILVER_HI = ", "SILVER_DIM = ",
    "SILVER_BG = ", "GREEN = ", "RED = ", "BLUE = ", "PURPLE = ", "GOLD = ", "BRONZE = ", "GREEN_BG = ",
    "RED_BG = ", "BLUE_BG = ", "PURPLE_BG = ", "GOLD_BG = ", "CARD_BRD = ", "EMBED_COLOR = ", "COLOR_GREY = ",
    "I_GEM = ", "I_STAR = ", "I_CROWN = ", "I_TROPHY = ", "I_MEDAL = ", "I_AWARD = ", "I_COINS = ",
    "I_SACK = ", "I_MONEY = ", "I_MONEY2 = ", "I_BAG = ", "I_BRIEF = ", "I_CHART = ", "I_BANK = ",
    "I_USERS = ", "I_USER = ", "I_USER_SEC = ", "I_USER_TIE = ", "I_HAND = ", "I_HANDD = ",
    "I_CLOCK = ", "I_CALENDAR = ", "I_CALC = ", "I_LIST = ", "I_LISTC = ", "I_INFO = ", "I_CHECK = ",
    "I_XMARK = ", "I_PERCENT = ", "I_HISTORY = ", "I_FIRE = ", "I_GIFT = ", "I_DICE = ", "I_DICE5 = ",
    "I_DICE6 = ", "I_MESSAGE = ", "I_COMMENT = ", "I_COMMENTS = ", "I_MIC = ", "I_HEADPH = ", "I_SCROLL = ",
    "I_PEN = ", "I_PEN_NIB = ", "I_PENF = ", "I_SEARCH = ", "I_GAMEPAD = ", "I_CUBE = ", "I_GAUGE = ",
    "I_SHIELD = ", "I_BOLT = ", "I_LOCK = ", "I_SPADE = ", "I_HEART = ", "I_DIAMOND = ", "I_CLUB = ",
    "I_QUESTION = ", "I_ROTATE = ", "I_ROTATE_L = ", "I_ARROW_L = ", "I_ARROW_D = ", "I_ELL = ",
    "I_CIRCLE_M = ", "I_PLUS = ", "I_TRASH = ", "I_EYE = ", "I_IMAGE = ", "I_PALETTE = ", "I_MASKS = ",
    "I_BULLHORN = ", "I_TICKET = ", "I_RECEIPT = ", "I_BUILDING = ", "I_MOBILE = ", "I_CREDIT = ",
    "I_BAN = ", "I_HEAD = ", "I_MOUSE = ", "I_CART = ", "I_BOX = ", "I_CHECK_C = ", "I_XMARK_C = ",
    "I_HANDSHAKE = ", "I_CROW = ", "I_SEEDLING = ", "I_GAVEL = ", "I_BOOK = ", "I_LAYERS = ",
    "I_BEZIER = ", "I_SMILE = "
]

def run_auto_cleaner():
    print("🧹 Проверка рендеров на дубли...")
    for filepath in TARGET_RENDER_FILES:
        full_path = os.path.join(BASE_DIR, filepath)
        if not os.path.exists(full_path):
            continue
            
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "from core.render import" in content:
            continue # Уже почищено ранее

        lines = content.split("\n")
        out_lines = []
        in_block = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("from PIL import") or stripped.startswith("import PIL"):
                out_lines.append(line)
                continue
            if any(stripped.startswith(k) for k in SKIP_KEYWORDS) and not stripped.startswith("def _draw_"):
                in_block = True
                continue
            if in_block:
                if line.startswith("def ") or line.startswith("class ") or line.startswith("@"):
                    in_block = False
                    out_lines.append(line)
                continue
            out_lines.append(line)

        final_code = "\n".join(out_lines)
        
        # Вставляем импорт
        search_str = "\nimport "
        if final_code.rfind("\nfrom ") > final_code.rfind(search_str):
            search_str = "\nfrom "
            
        last_import_idx = final_code.rfind(search_str)
        if last_import_idx != -1:
            insert_idx = final_code.find("\n", last_import_idx + 1)
            if insert_idx == -1: insert_idx = len(final_code)
            final_code = final_code[:insert_idx] + "\nfrom core.render import *\n" + final_code[insert_idx:]
        else:
            final_code = "from core.render import *\n" + final_code

        while "\n\n\n\n" in final_code: 
            final_code = final_code.replace("\n\n\n\n", "\n\n\n")

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(final_code)
        print(f"  ✅ Очищен: {filepath}")
    print("🧹 Проверка завершена!\n")

# ============================================================
# 3. ЗАПУСК ОСТАЛЬНЫХ МОДУЛЕЙ
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
        # Перенаправляем вывод дочерних процессов прямо в терминал
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
# 4. СТАРТ
# ============================================================
if __name__ == "__main__":
    # 1. Чистим рендеры перед стартом
    run_auto_cleaner()

    # 2. Запускаем основной бот
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

    # 3. Запускаем дочерние процессы
    _ai_proc = _start_subprocess("ai", "AI-консультант", "AI_TOKEN")
    _ai_manager_proc = _start_subprocess("ai_manager", "AI-менеджер", "AI_MANAGER_TOKEN")

    atexit.register(_stop_all)
    signal.signal(signal.SIGTERM, _sigterm_handler)

    # 4. Поехали
    try: 
        bot.run(CONFIG["BOT_TOKEN"])
    except KeyboardInterrupt: 
        print("\n🛑 Остановлено вручную")
    except Exception as e: 
        logger.exception("Ошибка запуска бота: %s", e)
        traceback.print_exc()
    finally: 
        _stop_all()
