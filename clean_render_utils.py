# -*- coding: utf-8 -*-
"""
Скрипт-автоматизатор. Очищает файлы рендеров от дублей шрифтов и палитры.
Запуск: python clean_render_utils.py
"""
import os
import re

TARGET_FILES = [
    "modules/shop/render.py", "modules/shop/render_gift.py", "modules/shop/render_profile.py",
    "modules/shop/render_quests.py", "modules/casino_render.py", "modules/tickets.py",
    "modules/achievements_panel.py", "modules/profile_card.py", "modules/autoorder.py",
    "clan/render.py", "bonus/render.py", "pet/render.py"
]

def clean_file(filepath):
    if not os.path.exists(filepath): return
    with open(filepath, "r", encoding="utf-8") as f: content = f.read()

    # Если уже почищен — пропускаем
    if "from core.render import *" in content or "from core.render import" in content: return

    lines = content.split("\n")
    out_lines = []
    in_block = False

    skip_keywords = [
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

    for line in lines:
        stripped = line.strip()

        # Пропускаем импорты Pillow, они нужны
        if stripped.startswith("from PIL import") or stripped.startswith("import PIL"):
            out_lines.append(line); continue

        # Если начинается блок с функцией — пропускаем всё тело функции
        if any(stripped.startswith(k) for k in skip_keywords) and not stripped.startswith("def _draw_"):
            in_block = True
            continue

        if in_block:
            if line.startswith("def ") or line.startswith("class ") or line.startswith("@"):
                in_block = False
                out_lines.append(line)
            continue

        out_lines.append(line)

    # Собираем обратно, добавляем импорт после последнего import
    final_code = "\n".join(out_lines)
    
    # Ищем последний import, чтобы вставить наш после него
    last_import_idx = final_code.rfind("\nimport ") if final_code.rfind("\nimport ") > final_code.rfind("\nfrom ") else final_code.rfind("\nfrom ")
    
    if last_import_idx != -1:
        insert_idx = final_code.find("\n", last_import_idx + 1)
        if insert_idx == -1: insert_idx = len(final_code)
        final_code = final_code[:insert_idx] + "\nfrom core.render import *\n" + final_code[insert_idx:]
    else:
        final_code = "from core.render import *\n" + final_code

    # Убираем пустые множественные переносы
    while "\n\n\n\n" in final_code: final_code = final_code.replace("\n\n\n\n", "\n\n\n")

    with open(filepath, "w", encoding="utf-8") as f: f.write(final_code)
    print(f"✅ Очищен: {filepath}")

if __name__ == "__main__":
    for f in TARGET_FILES: clean_file(f)
    print("🚀 Все рендеры очищены! Теперь они используют core/render.py")
