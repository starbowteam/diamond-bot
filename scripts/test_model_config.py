# -*- coding: utf-8 -*-
"""Офлайн-тесты конфигурации моделей (без API-ключа).

Проверяют:
  · весь список моделей провайдера есть в ALL_MODELS и DIALOG_MODELS;
  · OCR-пул существует, отделён от диалогового и используется при проверке чеков;
  · call_llm() перебирает DIALOG_MODELS, а не одну зашитую модель;
  · старой константы LAST_RESORT_MODEL больше нет.

Запуск из корня проекта:
    python scripts/test_model_config.py
    python -m unittest scripts.test_model_config -v
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.models import (  # noqa: E402
    ALL_MODELS,
    DIALOG_MODELS,
    OCR_MODELS,
    VISION_MODELS,
    pool,
)

# Полный список с панели провайдера. Если провайдер добавит модель — добавь сюда
# и в scripts/models.py, тест сразу покажет расхождение.
PROVIDER_MODELS = {
    "google/gemini-3-flash-preview",
    "qwen/qwen-2.5-72b-instruct",
    "qwen/qwen3.8-2.4t-a95b",
    "aion-labs/aion-3.0",
    "aion-labs/aion-2.0",
    "deepseek/deepseek-v4.1-flash",
    "aion-labs/aion-3.0-mini",
    "dots-studio/dots-3-note-preview:free",
    "google/gemini-2.0-flash-001",
    "google/gemini-2.0-flash-exp:free",
    "liquid/lfm-2.5-2.6b:free",
    "meta-llama/llama-3.3-8b-instruct:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "qwen/qwen3-4b:free",
    "recursive/flint-v1.0:free",
    "xingchen-agi/xing4.0-29b-a4b:free",
}


class ModelPoolsTest(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "modules" / "ai_manager.py").read_text(encoding="utf-8")

    def test_catalog_contains_all_provider_models(self):
        self.assertEqual(PROVIDER_MODELS, set(ALL_MODELS))

    @unittest.skipIf(os.getenv("DIALOG_MODELS"), "DIALOG_MODELS переопределён через env")
    def test_dialog_pool_uses_entire_catalog(self):
        self.assertEqual(set(ALL_MODELS), set(DIALOG_MODELS))

    def test_ocr_pool_is_configured_and_separate(self):
        self.assertTrue(OCR_MODELS)
        self.assertEqual(OCR_MODELS, VISION_MODELS)
        self.assertEqual(OCR_MODELS, pool("ocr"))
        self.assertEqual(OCR_MODELS, pool("vision"))
        self.assertNotEqual(DIALOG_MODELS, OCR_MODELS)

    def test_receipt_reading_uses_ocr_pool(self):
        read_receipt = self.source.split("async def read_receipt", 1)[1].split(
            "async def check_receipt_amount", 1
        )[0]
        self.assertIn("for model in OCR_MODELS:", read_receipt)
        self.assertNotIn("for model in DIALOG_MODELS:", read_receipt)

    def test_dialog_uses_dialog_pool(self):
        call_llm = self.source.split("async def call_llm", 1)[1].split(
            "async def escalate", 1
        )[0]
        self.assertIn("for model in DIALOG_MODELS:", call_llm)

    def test_last_resort_constant_removed(self):
        self.assertNotIn("LAST_RESORT_MODEL", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
