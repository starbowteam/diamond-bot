#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Приводит modules/ai_manager.py к пулам моделей из scripts/models.py.

Зачем: в старом ai_manager.py модели зашиты двумя константами:

    DIAMOND_AI_MODEL = "google/gemini-3-flash-preview"
    LAST_RESORT_MODEL = "qwen/qwen-2.5-72b-instruct"

Скрипт заменяет их на импорт из scripts/models.py, убирает LAST_RESORT_MODEL
и переключает цикл call_llm() на DIALOG_MODELS. Файл моделей создаётся, если
его нет. Все изменения — только после проверки синтаксиса и с бэкапом.

Использование (в контейнере/на сервере, из корня проекта):

    python scripts/apply_model_pools.py            # показать, что изменится (dry-run)
    python scripts/apply_model_pools.py --apply    # применить (создаст .bak-*)
    python scripts/apply_model_pools.py --root /app --apply

После применения перезапустите бота. Модели можно менять без правки кода:
    DIALOG_MODELS="model-1,model-2"
    VISION_MODELS="model-1,model-2"
"""
from __future__ import annotations

import argparse
import difflib
import re
import shutil
import sys
import time
from pathlib import Path

MODELS_PY = '''# -*- coding: utf-8 -*-
"""Единый конфиг моделей AI-менеджера.

Один источник правды:
  · бот (modules/ai_manager.py) берёт отсюда DIALOG_MODELS / VISION_MODELS;
  · тесты (scripts/test_models.py) берут отсюда же списки CHEAP_MODELS / ALL_MODELS.

Переопределение без правки кода (env или .env в корне проекта):
  DIALOG_MODELS="model-1,model-2"
  VISION_MODELS="model-1,model-2"
  RECEIPT_VISION_MODEL="model"      # старое имя, оставлено для совместимости
"""
import os
from typing import List


def _models(env_name: str, default: str) -> List[str]:
    raw = (os.getenv(env_name) or "").strip() or default
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models:
        models = [m.strip() for m in default.split(",") if m.strip()]
    return models


# ── ОБЩЕНИЕ В ТИКЕТАХ (заказы) ──
# Лёгкие/дешёвые модели: первая рабочая используется, остальные — фолбэки.
_DIALOG_DEFAULT = (
    "google/gemini-2.0-flash-001,"
    "google/gemini-2.0-flash-exp:free,"
    "deepseek/deepseek-v4.1-flash,"
    "qwen/qwen-2.5-72b-instruct"
)
DIALOG_MODELS: List[str] = _models("DIALOG_MODELS", _DIALOG_DEFAULT)

# ── ПРОВЕРКА ЧЕКОВ (vision) ──
# Дорогая, но точная модель читает скриншот/PDF. Фолбэки — только vision-модели.
_VISION_DEFAULT = (
    "google/gemini-3-flash-preview,"
    "google/gemini-2.0-flash-001,"
    "nvidia/nemotron-3.5-super-vl:free"
)
VISION_MODELS: List[str] = _models(
    "VISION_MODELS",
    os.getenv("RECEIPT_VISION_MODEL", "").strip() or _VISION_DEFAULT,
)

# ── ПОЛНЫЙ КАТАЛОГ ПРОВАЙДЕРА ──
FREE_MODELS: List[str] = [
    "google/gemini-2.0-flash-exp:free",
    "liquid/lfm-2.5-2.6b:free",
    "meta-llama/llama-3.3-8b-instruct:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "qwen/qwen3-4b:free",
    "recursive/flint-v1.0:free",
    "xingchen-agi/xing4.0-29b-a4b:free",
    "dots-studio/dots-3-note-preview:free",
]

CHEAP_MODELS: List[str] = [
    "google/gemini-2.0-flash-001",
    "deepseek/deepseek-v4.1-flash",
    "qwen/qwen-2.5-72b-instruct",
    "aion-labs/aion-3.0-mini",
] + FREE_MODELS

PREMIUM_MODELS: List[str] = [
    "google/gemini-3-flash-preview",
    "qwen/qwen3.8-2.4t-a95b",
    "aion-labs/aion-3.0",
    "aion-labs/aion-2.0",
]

ALL_MODELS: List[str] = list(dict.fromkeys(CHEAP_MODELS + PREMIUM_MODELS))


def pool(name: str) -> List[str]:
    """Возвращает пул по имени: cheap | dialog | vision | premium | all."""
    name = (name or "").lower().strip()
    pools = {
        "cheap": CHEAP_MODELS,
        "dialog": DIALOG_MODELS,
        "vision": VISION_MODELS,
        "premium": PREMIUM_MODELS,
        "all": ALL_MODELS,
    }
    if name not in pools:
        raise ValueError("Неизвестный пул '%s'. Доступны: %s" % (name, ", ".join(pools)))
    return list(dict.fromkeys(pools[name]))
'''

IMPORT_LINE = "from scripts.models import DIALOG_MODELS, VISION_MODELS  # noqa: E402"

RE_DIALOG_CONST = re.compile(
    r'^DIAMOND_AI_MODEL\s*=\s*["\'][^"\']+["\'][^\n]*$', re.MULTILINE
)
RE_LAST_RESORT = re.compile(
    r'^LAST_RESORT_MODEL\s*=\s*["\'][^"\']+["\'][^\n]*\n?', re.MULTILINE
)
RE_MODELS_TO_TRY = re.compile(
    r'\[\s*DIAMOND_AI_MODEL\s*,\s*LAST_RESORT_MODEL\s*\]'
)
RE_FOR_MODELS_TO_TRY = re.compile(r'for\s+model\s+in\s+models_to_try\s*:')

CONSTANTS_HEADER = re.compile(
    r'^# =+\n# КОНСТАНТЫ\n# =+\n', re.MULTILINE
)


def find_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    cwd = Path.cwd()
    if (cwd / "modules" / "ai_manager.py").exists():
        return cwd
    guess = Path(__file__).resolve().parent.parent
    if (guess / "modules" / "ai_manager.py").exists():
        return guess
    return cwd


def ensure_models_file(root: Path, force: bool) -> list[str]:
    log = []
    target = root / "scripts" / "models.py"
    target.parent.mkdir(parents=True, exist_ok=True)

    init_file = root / "scripts" / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")
        log.append(f"• {init_file} создан")

    if target.exists() and not force:
        log.append(f"• {target} уже есть — не трогаю")
        return log
    action = "перезаписан" if target.exists() else "создан"
    target.write_text(MODELS_PY, encoding="utf-8")
    log.append(f"• {target} {action}")
    return log


def patch_source(source: str) -> tuple[str, list[str]]:
    """Возвращает (новый текст, список выполненных замен)."""
    changes: list[str] = []
    text = source

    if RE_DIALOG_CONST.search(text):
        text = RE_DIALOG_CONST.sub(
            "DIAMOND_AI_MODEL = DIALOG_MODELS[0]  # только для анализа на мат/спам",
            text, count=1,
        )
        changes.append("DIAMOND_AI_MODEL → DIALOG_MODELS[0]")

    if RE_LAST_RESORT.search(text):
        text = RE_LAST_RESORT.sub("", text, count=1)
        changes.append("LAST_RESORT_MODEL удалён")

    if RE_MODELS_TO_TRY.search(text):
        text = RE_MODELS_TO_TRY.sub("DIALOG_MODELS", text)
        changes.append("[DIAMOND_AI_MODEL, LAST_RESORT_MODEL] → DIALOG_MODELS")

    if RE_FOR_MODELS_TO_TRY.search(text):
        text = RE_FOR_MODELS_TO_TRY.sub("for model in DIALOG_MODELS:", text)
        changes.append("цикл call_llm → for model in DIALOG_MODELS")

    if "from scripts.models import" not in text:
        header = CONSTANTS_HEADER.search(text)
        if header:
            text = text[:header.start()] + IMPORT_LINE + "\n\n" + text[header.start():]
        else:
            anchor = RE_DIALOG_CONST.search(text)
            if anchor:
                text = text[:anchor.start()] + IMPORT_LINE + "\n" + text[anchor.start():]
            else:
                text = IMPORT_LINE + "\n" + text
        changes.append("добавлен импорт scripts.models")

    return text, changes


def make_diff(old: str, new: str, path: Path) -> str:
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"{path.name} (сейчас)",
        tofile=f"{path.name} (после патча)",
        lineterm="", n=3,
    )
    return "\n".join(diff)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Патч modules/ai_manager.py: модели из scripts/models.py"
    )
    parser.add_argument("--root", help="корень проекта (по умолчанию — текущая папка)")
    parser.add_argument("--apply", action="store_true", help="записать изменения")
    parser.add_argument("--force-models", action="store_true",
                        help="перезаписать scripts/models.py")
    parser.add_argument("--force", action="store_true",
                        help="писать даже если LAST_RESORT_MODEL остался в коде")
    args = parser.parse_args(argv)

    root = find_root(args.root)
    target = root / "modules" / "ai_manager.py"

    print(f"Корень проекта: {root}")
    if not target.exists():
        print(f"❌ Не найден {target}")
        print("   Укажите корень: --root /app")
        return 2

    original = target.read_text(encoding="utf-8")
    patched, changes = patch_source(original)

    print("\nФайл моделей:")
    for line in ensure_models_file(root, args.force_models):
        print("  " + line)

    print("\nПатч ai_manager.py:")
    if not changes and patched == original:
        print("  ✅ уже применено — менять нечего")
        return 0

    for change in changes:
        print(f"  • {change}")

    leftover = [ln for ln in re.findall(r"^.*\bLAST_RESORT_MODEL\b.*$", patched, re.MULTILINE)
                if not ln.lstrip().startswith("#")]
    if leftover:
        print("\n  ⚠️ LAST_RESORT_MODEL ещё встречается в коде:")
        for line in leftover:
            print("     " + line.strip())
        if not args.force:
            print("     Патч не применён: уберите эти строки вручную или запустите с --force.")
            return 1
        print("     Продолжаю из-за --force (возможен NameError в рантайме).")

    try:
        compile(patched, str(target), "exec")
    except SyntaxError as exc:
        print(f"\n❌ После патча файл не компилируется: {exc}")
        print("   Ничего не записано.")
        return 1

    print("\nИзменения:")
    print(make_diff(original, patched, target) or "  (нет)")

    if not args.apply:
        print("\nЭто был dry-run. Применить: --apply")
        return 0

    backup = target.with_suffix(f".py.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(target, backup)
    target.write_text(patched, encoding="utf-8")
    print(f"\n✅ Записано: {target}")
    print(f"   Бэкап:   {backup}")
    print("   Перезапустите бота, чтобы модель-пулы применились.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
