# -*- coding: utf-8 -*-
"""Тесты моделей AI-менеджера.

Проверяет доступные модели тремя тестами:
  chat   — базовый диалог на русском;
  tools  — вызов функции create_invoice (как в боте);
  vision — чтение суммы с синтетического чека об оплате.

Запуск (из корня проекта):
    python scripts/test_models.py                     # дешёвые модели, все тесты
    python scripts/test_models.py --pool vision       # только чековые модели
    python scripts/test_models.py --models "qwen/qwen3-4b:free,google/gemini-2.0-flash-001"
    python scripts/test_models.py --tests vision --concurrency 1
    python scripts/test_models.py --dump-receipt receipt_test.png

Ключ и адрес берутся из env или из .env в корне проекта:
    AI_MANAGER_API_KEY, AI_MANAGER_BASE_URL
"""
import argparse
import asyncio
import base64
import io
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv(path: Path) -> None:
    """Минимальный парсер .env без внешних зависимостей."""
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as e:
        print(f"⚠️ .env не прочитан: {e}")


_load_dotenv(ROOT / ".env")

from scripts.models import CHEAP_MODELS, DIALOG_MODELS, VISION_MODELS, pool  # noqa: E402

BASE_URL = os.getenv("AI_MANAGER_BASE_URL", "https://api.zveno.ai/v1").rstrip("/")
API_KEY = os.getenv("AI_MANAGER_API_KEY", "").strip()

# ── Тестовый чек: сумма, которую должна прочитать модель ──
RECEIPT_TEST_AMOUNT = 2500

# Держим синхронно с RECEIPT_SYSTEM_PROMPT в modules/ai_manager.py
RECEIPT_SYSTEM_PROMPT = """Ты читаешь скриншот или PDF из банковского приложения.
Верни ТОЛЬКО JSON, без markdown и пояснений:
{"doc_type": "payment_confirmation|invoice|other", "amount": <число или null>, "currency": "RUB"}

Правила:
- payment_confirmation — подтверждение перевода: видно «Выполнено», «Успешно», «Перевод совершён», «Оплачено», «Чек», «Квитанция».
- invoice — счёт на оплату или реквизиты: заголовки «Счёт», «Реквизиты», «Шаг 1 · Оплата», кнопки «Оплатить», «Перевести».
- всё остальное (переписка, товар, мем, просто баланс) — other.
- amount — итоговая сумма именно перевода. Не бери баланс, комиссию, номер карты, номер телефона, дату.
- Если сумму не видно или не уверен — null, не угадывай."""

# Держим синхронно с TOOLS_OPENAI в modules/ai_manager.py
TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "create_invoice",
            "description": "Выставить счёт. Можно передать ОДИН ИЛИ НЕСКОЛЬКО товаров в массиве items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_name": {"type": "string"},
                                "quantity": {"type": "integer", "default": 1},
                                "price": {"type": "number"},
                            },
                            "required": ["item_name", "price"],
                        },
                    },
                    "discount_percent": {"type": "integer", "default": 0},
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": "Позвать продавца.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]

STATUS_LABELS = {
    "ok": "OK",
    "no_text": "нет ответа",
    "no_tool": "без tool call",
    "bad_output": "кривой JSON",
    "no_vision": "нет vision",
    "wrong_amount": "неверная сумма",
    "wrong_type": "не чек",
    "error": "ошибка",
}


# ============================================================
# ТЕСТОВЫЙ ЧЕК
# ============================================================
def _font(size: int) -> ImageFont.ImageFont:
    candidates = [
        ROOT / "add" / "ProximaNova-ExtraBold.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for path in candidates:
        try:
            if Path(path).exists():
                return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    return ImageFont.load_default()


def build_receipt_image(amount: int = RECEIPT_TEST_AMOUNT) -> Image.Image:
    """Рисует синтетическое подтверждение перевода с известной суммой."""
    w, h = 720, 980
    img = Image.new("RGB", (w, h), "#0d1117")
    d = ImageDraw.Draw(img)

    d.rounded_rectangle((24, 24, w - 24, h - 24), radius=26, fill="#161b22", outline="#30363d", width=2)

    # зелёная галочка
    d.ellipse((70, 70, 168, 168), fill="#238636")
    d.line((100, 120, 116, 138), fill="#ffffff", width=8)
    d.line((116, 138, 146, 98), fill="#ffffff", width=8)

    d.text((192, 78), "ПЕРЕВОД ВЫПОЛНЕН", font=_font(28), fill="#3fb950")
    d.text((192, 120), "Т-Банк · 19.11.2026 12:34", font=_font(17), fill="#8b949e")

    d.text((64, 218), "Сумма перевода", font=_font(19), fill="#8b949e")
    amount_text = f"{amount:,}".replace(",", " ") + " руб."
    d.text((64, 248), amount_text, font=_font(56), fill="#ffffff")

    rows = [
        ("Получатель", "Иван И."),
        ("Счёт получателя", "•••• 9345"),
        ("Отправитель", "Пётр П."),
        ("Статус", "Выполнено"),
        ("Операция №", "D-1763550000-482"),
        ("Комиссия", "0 руб."),
    ]
    y = 380
    for label, value in rows:
        d.text((64, y), label, font=_font(18), fill="#8b949e")
        d.text((330, y), value, font=_font(19), fill="#e6edf3")
        d.line((64, y + 34, w - 64, y + 34), fill="#21262d", width=1)
        y += 62

    d.text((64, h - 108), "Чек сформирован автоматически", font=_font(15), fill="#6e7681")
    return img


def receipt_jpeg_b64(amount: int = RECEIPT_TEST_AMOUNT) -> str:
    buf = io.BytesIO()
    build_receipt_image(amount).save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


# ============================================================
# HTTP
# ============================================================
async def _post(
    session: aiohttp.ClientSession,
    payload: dict,
    timeout: float,
    json_mode_retry: bool = False,
) -> Tuple[Optional[dict], int, Optional[str]]:
    """POST /chat/completions. Возвращает (data, ms, error)."""
    url = f"{BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    body = payload
    for _ in range(2):
        started = time.perf_counter()
        try:
            async with session.post(
                url, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                text = await resp.text()
                ms = int((time.perf_counter() - started) * 1000)
                if resp.status != 200:
                    if resp.status == 400 and json_mode_retry and "response_format" in body:
                        body = dict(body)
                        body.pop("response_format", None)
                        continue
                    return None, ms, f"HTTP {resp.status}: {text[:160]}"
                try:
                    data = json.loads(text)
                except Exception:
                    return None, ms, "ответ не JSON"
                if not data.get("choices"):
                    return None, ms, "пустой choices"
                return data, ms, None
        except asyncio.TimeoutError:
            return None, int((time.perf_counter() - started) * 1000), "timeout"
        except Exception as e:
            return None, int((time.perf_counter() - started) * 1000), str(e)[:160]
    return None, 0, "request failed"


def _content(data: dict) -> str:
    try:
        return (data["choices"][0].get("message", {}).get("content") or "").strip()
    except Exception:
        return ""


def _result(status: str, ms: int = 0, note: str = "") -> dict:
    return {"status": status, "ms": ms, "note": note[:200]}


# ============================================================
# ТЕСТЫ
# ============================================================
async def test_chat(session, model: str, timeout: float) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Отвечай кратко, по-русски."},
            {"role": "user", "content": "Напиши одно слово: ОК"},
        ],
        "temperature": 0,
        "max_tokens": 30,
    }
    data, ms, err = await _post(session, payload, timeout)
    if err:
        return _result("error", ms, err)
    text = _content(data)
    if not text:
        return _result("no_text", ms, "пустой content")
    return _result("ok", ms, text[:60])


async def test_tools(session, model: str, timeout: float) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Ты продавец магазина. Для заказа вызывай create_invoice."},
            {"role": "user", "content": "Выставь счёт на Discord Nitro за 460 рублей."},
        ],
        "tools": TOOLS_OPENAI,
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 300,
    }
    data, ms, err = await _post(session, payload, timeout)
    if err:
        return _result("error", ms, err)

    try:
        msg = data["choices"][0].get("message", {})
        calls = msg.get("tool_calls") or []
    except Exception:
        calls = []

    if not calls:
        text = _content(data)
        return _result("no_tool", ms, (text[:80] if text else "модель ответила текстом"))

    fn = calls[0].get("function", {}) or {}
    name = fn.get("name") or ""
    raw_args = fn.get("arguments") or "{}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except Exception:
        return _result("bad_output", ms, f"{name}: arguments не JSON")

    if name != "create_invoice":
        return _result("no_tool", ms, f"вызвана {name or '?'}")

    items = args.get("items") if isinstance(args, dict) else None
    if not items:
        return _result("bad_output", ms, "create_invoice без items")
    first = items[0] if isinstance(items, list) else {}
    return _result("ok", ms, f"{first.get('item_name', '?')} / {first.get('price', '?')}")


async def test_vision(session, model: str, timeout: float, image_b64: str) -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": RECEIPT_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Прочитай документ и верни JSON."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]},
        ],
        "temperature": 0,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }
    data, ms, err = await _post(session, payload, timeout, json_mode_retry=True)
    if err:
        lowered = err.lower()
        code = 0
        m = re.match(r"http (\d{3})", lowered)
        if m:
            code = int(m.group(1))
        if code in (400, 415, 422) or "image" in lowered or "vision" in lowered:
            return _result("no_vision", ms, err)
        return _result("error", ms, err)

    text = _content(data)
    if not text:
        return _result("no_vision", ms, "пустой ответ")

    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except Exception:
        return _result("bad_output", ms, text[:80])

    if not isinstance(parsed, dict):
        return _result("bad_output", ms, "ответ не объект")

    doc_type = parsed.get("doc_type")
    raw_amount = parsed.get("amount")
    try:
        amount = float(str(raw_amount).replace(" ", "").replace(",", "."))
    except Exception:
        amount = None

    if amount is None:
        return _result("wrong_amount", ms, f"amount={raw_amount!r}")
    if abs(amount - RECEIPT_TEST_AMOUNT) > 1:
        return _result("wrong_amount", ms, f"прочитала {amount:g} вместо {RECEIPT_TEST_AMOUNT}")
    if doc_type != "payment_confirmation":
        return _result("wrong_type", ms, f"doc_type={doc_type}")
    return _result("ok", ms, f"{doc_type} / {amount:g}")


# ============================================================
# ПРОГОН
# ============================================================
async def run_model(session, model: str, tests: List[str], timeout: float, image_b64: str, sem: asyncio.Semaphore) -> dict:
    row = {}
    async with sem:
        if "chat" in tests:
            row["chat"] = await test_chat(session, model, timeout)
        if "tools" in tests:
            row["tools"] = await test_tools(session, model, timeout)
        if "vision" in tests:
            row["vision"] = await test_vision(session, model, timeout, image_b64)
    return row


def _fmt(cell: dict) -> str:
    if not cell:
        return "—"
    label = STATUS_LABELS.get(cell["status"], cell["status"])
    return f"{label} {cell['ms']}ms"


def print_table(results: Dict[str, dict], tests: List[str]) -> None:
    header = "МОДЕЛЬ".ljust(42) + "".join(t.upper().ljust(22) for t in tests)
    print("\n" + header)
    print("-" * len(header))
    for model, row in results.items():
        line = model.ljust(42) + "".join(_fmt(row.get(t, {})).ljust(22) for t in tests)
        print(line)
        notes = [
            f"{t}: {row[t]['note']}"
            for t in tests
            if row.get(t, {}).get("note") and row.get(t, {}).get("status") != "ok"
        ]
        for note in notes:
            print(" " * 4 + "↳ " + note)


def write_json_report(path: Path, results: Dict[str, dict], tests: List[str], pool_name: str) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": BASE_URL,
        "pool": pool_name,
        "tests": tests,
        "receipt_test_amount": RECEIPT_TEST_AMOUNT,
        "models": results,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_md_report(path: Path, results: Dict[str, dict], tests: List[str], pool_name: str) -> None:
    icons = {"ok": "✅", "no_vision": "⛔", "error": "❌", "no_tool": "⚠️"}
    lines = [
        f"# Проверка моделей — {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
        f"- Провайдер: `{BASE_URL}`",
        f"- Пул: `{pool_name}`",
        f"- Тестовая сумма чека: `{RECEIPT_TEST_AMOUNT} ₽`",
        "",
        "| Модель | " + " | ".join(t for t in tests) + " |",
        "|---|" + "---|" * len(tests),
    ]
    for model, row in results.items():
        cells = []
        for t in tests:
            cell = row.get(t)
            if not cell:
                cells.append("—")
                continue
            icon = icons.get(cell["status"], "⚠️")
            note = f" ({cell['note']})" if cell["note"] and cell["status"] != "ok" else ""
            cells.append(f"{icon} {cell['ms']} ms{note}")
        lines.append(f"| `{model}` | " + " | ".join(cells) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ============================================================
# CLI
# ============================================================
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Проверка моделей AI-менеджера")
    parser.add_argument("--pool", default="cheap", help="cheap | dialog | vision | premium | all (по умолчанию cheap)")
    parser.add_argument("--models", default="", help="свой список через запятую (перекрывает --pool)")
    parser.add_argument("--tests", default="chat,tools,vision", help="chat,tools,vision (по умолчанию все)")
    parser.add_argument("--timeout", type=float, default=60.0, help="таймаут одного запроса, сек")
    parser.add_argument("--concurrency", type=int, default=2, help="сколько моделей параллельно")
    parser.add_argument("--json-out", default=str(ROOT / "scripts" / "model_report.json"))
    parser.add_argument("--md-out", default=str(ROOT / "scripts" / "model_report.md"))
    parser.add_argument("--no-report", action="store_true", help="не писать файлы отчётов")
    parser.add_argument("--dump-receipt", default="", help="сохранить тестовый чек по указанному пути и выйти")
    return parser.parse_args()


async def main_async(args: argparse.Namespace, models: List[str], tests: List[str]) -> int:
    image_b64 = receipt_jpeg_b64() if "vision" in tests else ""
    sem = asyncio.Semaphore(max(1, args.concurrency))
    results: Dict[str, dict] = {}

    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(run_model(session, model, tests, args.timeout, image_b64, sem))
            for model in models
        ]
        for idx, model in enumerate(models, 1):
            try:
                row = await tasks[idx - 1]
            except Exception as e:
                row = {t: _result("error", 0, str(e)) for t in tests}
            results[model] = row
            cells = "  ".join(f"{t}={STATUS_LABELS.get(row.get(t, {}).get('status', ''), '—')}" for t in tests)
            print(f"[{idx:>2}/{len(models)}] {model.ljust(40)} {cells}")

    print_table(results, tests)

    if not args.no_report:
        json_path = Path(args.json_out)
        md_path = Path(args.md_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_report(json_path, results, tests, args.pool)
        write_md_report(md_path, results, tests, args.pool)
        print(f"\nОтчёты: {json_path} | {md_path}")

    ok_counts = {t: sum(1 for r in results.values() if r.get(t, {}).get("status") == "ok") for t in tests}
    print("\nИтого: " + ", ".join(f"{t} {ok}/{len(results)}" for t, ok in ok_counts.items()))

    return 0 if any(r.get("chat", {}).get("status") == "ok" for r in results.values()) else 1


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    args = parse_args()

    if args.dump_receipt:
        path = Path(args.dump_receipt)
        path.parent.mkdir(parents=True, exist_ok=True)
        build_receipt_image().save(path)
        print(f"Тестовый чек сохранён: {path}")
        return 0

    if args.models.strip():
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        pool_name = "custom"
    else:
        try:
            models = pool(args.pool)
        except ValueError as e:
            print(f"❌ {e}")
            return 2
        pool_name = args.pool
    args.pool = pool_name

    tests = [t.strip().lower() for t in args.tests.split(",") if t.strip()]
    unknown = [t for t in tests if t not in ("chat", "tools", "vision")]
    if unknown:
        print(f"❌ Неизвестные тесты: {', '.join(unknown)}")
        return 2

    if not API_KEY:
        print("❌ Не задан AI_MANAGER_API_KEY (env или .env в корне проекта)")
        return 2

    print(f"Провайдер: {BASE_URL}")
    print(f"Моделей: {len(models)} | тесты: {', '.join(tests)} | параллельно: {args.concurrency}")

    try:
        return asyncio.run(main_async(args, models, tests))
    except KeyboardInterrupt:
        print("\nОстановлено.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
