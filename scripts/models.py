# -*- coding: utf-8 -*-
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
# model_id чековой модели пишется в ai_manager.log, чтобы было видно, кто распознал.
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
# Список с панели моделей. Нужен только для ручных замен и тестов.
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
        raise ValueError(f"Неизвестный пул '{name}'. Доступны: {', '.join(pools)}")
    return list(dict.fromkeys(pools[name]))
