# -*- coding: utf-8 -*-
"""Офлайн-тесты фолбэка моделей — без API-ключа и без сети.

Проверяют поведение из реального лога:

    WARNING | LLM google/gemini-2.0-flash-001: HTTP 404

  · если первая модель отдаёт 404, бот переходит к следующей;
  · мёртвая модель уходит в карантин и НЕ дёргается на следующем сообщении;
  · диалог идёт через DIALOG_MODELS, а чтение чека — через OCR_MODELS;
  · проверка на мат/спам тоже умеет переключаться на рабочую модель.

Запуск из корня проекта:
    python scripts/test_model_fallback.py
    python -m unittest scripts.test_model_fallback -v
"""
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

import modules.ai_manager as ai  # noqa: E402


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(buf, "PNG")
    return buf.getvalue()


class FakeAttachment:
    content_type = "image/png"
    filename = "receipt.png"

    def __init__(self):
        self._raw = _png_bytes()
        self.size = len(self._raw)

    async def read(self) -> bytes:
        return self._raw


class FallbackTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ai._MODEL_COOLDOWN.clear()
        ai._LAST_GOOD_MODEL = None
        ai.AI_MANAGER_API_KEY = "test-key"
        self.calls = []

    async def test_dialog_falls_back_after_404(self):
        async def fake_call(model, system_prompt, messages):
            self.calls.append(model)
            if model == "dead-model":
                return {"error": "HTTP 404"}
            return {"text": "ответ", "funcs": []}

        ai._call_single_model = fake_call
        ai.DIALOG_MODELS = ["dead-model", "live-model"]

        first = await ai.call_llm("system", [], "привет")
        self.assertEqual(first["text"], "ответ")
        self.assertEqual(self.calls, ["dead-model", "live-model"])

        second = await ai.call_llm("system", [], "ещё вопрос")
        self.assertEqual(second["text"], "ответ")
        # На втором сообщении мёртвая модель уже пропущена.
        self.assertEqual(self.calls, ["dead-model", "live-model", "live-model"])

    async def test_404_quarantines_longer_than_rate_limit(self):
        ai.mark_model_failed("dead-model", "HTTP 404")
        ai.mark_model_failed("busy-model", "HTTP 429")
        ai.mark_model_failed("flaky-model", "TimeoutError")

        dead = ai.model_cooldown_left("dead-model")
        busy = ai.model_cooldown_left("busy-model")
        flaky = ai.model_cooldown_left("flaky-model")

        # 404 — модель удалена: карантин на часы.
        self.assertGreater(dead, ai.COOLDOWN_MODEL_MISSING - 60)
        # 429 — временный лимит: отпускаем быстрее, чем общий сбой.
        self.assertLess(busy, dead)
        self.assertLess(busy, flaky)

        self.assertIn("dead-model", ai._MODEL_COOLDOWN)
        self.assertNotIn("live-model", ai._MODEL_COOLDOWN)

    async def test_active_models_skips_quarantined(self):
        ai._MODEL_COOLDOWN["dead-model"] = ai.time.monotonic() + 600
        self.assertEqual(ai.active_models(["dead-model", "live-model"]), ["live-model"])

        ai._MODEL_COOLDOWN["live-model"] = ai.time.monotonic() + 600
        # Если в карантине все — пробуем весь пул, чтобы не остаться без ответа.
        self.assertEqual(ai.active_models(["dead-model", "live-model"]), ["dead-model", "live-model"])

    async def test_receipt_uses_ocr_pool(self):
        async def fake_vision(model, b64):
            self.calls.append(model)
            return {"doc_type": "payment_confirmation", "amount": 2500}

        def fake_media_kind(attachment):
            return "image"

        def fake_jpeg(image):
            return "b64"

        ai._vision_call = fake_vision
        ai._media_kind = fake_media_kind
        ai._to_jpeg_b64 = fake_jpeg
        ai.DIALOG_MODELS = ["dialog-model"]
        ai.OCR_MODELS = ["ocr-model"]

        data = await ai.read_receipt(FakeAttachment())

        self.assertEqual(data["amount"], 2500)
        self.assertEqual(data["model"], "ocr-model")
        self.assertEqual(self.calls, ["ocr-model"])

    async def test_abuse_check_uses_dialog_pool(self):
        async def fake_simple(model, prompt, max_tokens=10, timeout=None):
            self.calls.append(model)
            return {"text": "ABUSE"}

        ai._simple_call = fake_simple
        ai.DIALOG_MODELS = ["dialog-model"]

        is_abuse, reason = await ai.check_abuse_llm(["ты плохой"])

        self.assertTrue(is_abuse)
        self.assertEqual(reason, "abuse")
        self.assertEqual(self.calls, ["dialog-model"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
