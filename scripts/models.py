# -*- coding: utf-8 -*-
"""Единый конфиг моделей AI-менеджера.

Один источник правды:
  · бот (modules/ai_manager.py) берёт отсюда DIALOG_MODELS / OCR_MODELS;
  · тесты (scripts/test_models.py) берут отсюда же списки CHEAP_MODELS / ALL_MODELS.

Логика:
  · DIALOG_MODELS — весь доступный каталог. Первая рабочая модель отвечает,
    остальные используются как фолбэки.
  · OCR_MODELS — отдельный пул для чтения чеков (vision). Во время проверки
    чека бот незаметно переключается сюда, пользователь этого не видит.

Переопределение без правки кода (env или .env в корне проекта):
  DIALOG_MODELS="model-1,model-2"
  OCR_MODELS="model-1,model-2"
  VISION_MODELS="model-1,model-2"   # старое имя, оставлено для совместимости
  RECEIPT_VISION_MODEL="model"      # ещё одно старое имя
"""
import os
from typing import List


def _models(env_name: str, default: str) -> List[str]:
    raw = (os.getenv(env_name) or "").strip() or default
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models:
        models = [m.strip() for m in default.split(",") if m.strip()]
    return models


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

# Все модели из панели провайдера, без дублей. Бесплатные и дешёвые идут первыми,
# премиальные — в конце как последний фолбэк.
ALL_MODELS: List[str] = list(dict.fromkeys(CHEAP_MODELS + PREMIUM_MODELS))


# ── ОБЩЕНИЕ В ТИКЕТАХ (заказы) ──
# По умолчанию задействуем весь каталог: если модель недоступна/упала,
# call_llm() автоматически пробует следующую.
_DIALOG_DEFAULT = ",".join(ALL_MODELS)
DIALOG_MODELS: List[str] = _models("DIALOG_MODELS", _DIALOG_DEFAULT)


# ── ПРОВЕРКА ЧЕКОВ (OCR / vision) ──
# Отдельный пул: диалоговые модели сюда не попадают. Проверка чека идёт
# молча — клиент видит только реакцию ⏳ и итоговый вердикт.
_OCR_DEFAULT = (
    "google/gemini-3-flash-preview,"
    "google/gemini-2.0-flash-001,"
    "nvidia/nemotron-3.5-super-vl:free"
)
OCR_MODELS: List[str] = _models(
    "OCR_MODELS",
    os.getenv("VISION_MODELS", "").strip()
    or os.getenv("RECEIPT_VISION_MODEL", "").strip()
    or _OCR_DEFAULT,
)

# Обратная совместимость со старыми скриптами/деплоями.
VISION_MODELS: List[str] = OCR_MODELS


def pool(name: str) -> List[str]:
    """Возвращает пул по имени: cheap | dialog | ocr | vision | premium | all."""
    name = (name or "").lower().strip()
    pools = {
        "cheap": CHEAP_MODELS,
        "dialog": DIALOG_MODELS,
        "ocr": OCR_MODELS,
        "vision": OCR_MODELS,
        "premium": PREMIUM_MODELS,
        "all": ALL_MODELS,
    }
    if name not in pools:
        raise ValueError(f"Неизвестный пул '{name}'. Доступны: {', '.join(pools)}")
    return list(dict.fromkeys(pools[name]))
