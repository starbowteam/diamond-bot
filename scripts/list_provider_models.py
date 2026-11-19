#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Показывает, какие модели из каталога реально доступны у провайдера.

Зачем: провайдер может отдавать HTTP 404 на модель из списка (её удалили,
переименовали или нет доступа). Тогда бот на каждое сообщение сначала бьётся
в неё, ждёт ответ и только потом идёт к рабочей — в логе это выглядит так:

    WARNING | LLM google/gemini-2.0-flash-001: HTTP 404

Использование (из корня проекта):

    python scripts/list_provider_models.py             # GET /models + сверка с каталогом
    python scripts/list_provider_models.py --probe     # реальный мини-запрос к каждой модели
    python scripts/list_provider_models.py --probe --only-catalog
    python scripts/list_provider_models.py --probe --write-env

Ключ и адрес берутся из env или из .env в корне проекта:
    AI_MANAGER_API_KEY, AI_MANAGER_BASE_URL
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp

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

BASE_URL = os.getenv("AI_MANAGER_BASE_URL", "https://api.zveno.ai/v1").rstrip("/")
API_KEY = os.getenv("AI_MANAGER_API_KEY", "").strip()

from scripts.models import (  # noqa: E402
    ALL_MODELS,
    CHEAP_MODELS,
    DIALOG_MODELS,
    OCR_MODELS,
    PREMIUM_MODELS,
)

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


async def fetch_models(session: aiohttp.ClientSession) -> Tuple[Optional[set], str]:
    """GET /models. Возвращает (множество id, текст ошибки)."""
    url = f"{BASE_URL}/models"
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            data = await resp.json()
    except Exception as e:
        return None, str(e)

    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return None, "неожиданный формат ответа"

    ids = set()
    for item in items:
        if isinstance(item, dict):
            mid = item.get("id") or item.get("name")
            if mid:
                ids.add(str(mid))
        elif isinstance(item, str):
            ids.add(item)
    return ids, ""


async def probe_one(session: aiohttp.ClientSession, model: str, timeout: int,
                    sem: asyncio.Semaphore) -> Tuple[str, bool, str]:
    """Мини-запрос chat/completions. Возвращает (model, ok, статус)."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": 0,
        "max_tokens": 1,
    }
    url = f"{BASE_URL}/chat/completions"
    async with sem:
        try:
            async with session.post(
                url, json=payload, headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 200:
                    return model, True, "200 OK"
                text = (await resp.text())[:120].replace("\n", " ")
                return model, False, f"HTTP {resp.status} {text}".strip()
        except asyncio.TimeoutError:
            return model, False, f"таймаут {timeout}с"
        except Exception as e:
            return model, False, str(e)[:120]


async def main_async(args: argparse.Namespace) -> int:
    if not API_KEY:
        print("❌ Не задан AI_MANAGER_API_KEY (env или .env в корне проекта)")
        return 2

    print(f"Провайдер: {BASE_URL}")
    print(f"Каталог:   {len(ALL_MODELS)} моделей")
    print(f"Диалог:    {len(DIALOG_MODELS)} моделей")
    print(f"OCR:       {len(OCR_MODELS)} моделей")
    print()

    if args.only_catalog:
        catalog = list(dict.fromkeys(DIALOG_MODELS if args.pool == "dialog" else ALL_MODELS))
    else:
        catalog = list(ALL_MODELS)

    available: Optional[set] = None
    async with aiohttp.ClientSession() as session:
        if not args.no_list:
            available, err = await fetch_models(session)
            if available is None:
                print(f"⚠️ GET /models недоступен ({err}) — проверяю модели напрямую")
                print()
            else:
                print(f"GET /models: {len(available)} моделей у провайдера")
                print()

        probe_results: Dict[str, Tuple[bool, str]] = {}
        if args.probe:
            print(f"Пробую каждую модель запросом (параллельно: {args.concurrency}, таймаут {args.timeout}с)...")
            sem = asyncio.Semaphore(max(1, args.concurrency))
            tasks = [probe_one(session, m, args.timeout, sem) for m in catalog]
            for coro in asyncio.as_completed(tasks):
                model, ok, status = await coro
                probe_results[model] = (ok, status)
            print()

    ok_models: List[str] = []
    bad_models: List[str] = []

    for model in catalog:
        marks = []
        if available is not None:
            marks.append("в /models" if model in available else "НЕТ в /models")
        if probe_results:
            ok, status = probe_results[model]
            marks.append("запрос OK" if ok else f"запрос FAIL ({status})")
            if ok:
                ok_models.append(model)
            else:
                bad_models.append(model)
        elif available is not None and model in available:
            ok_models.append(model)

        icon = "✅" if (not probe_results or probe_results[model][0]) else "❌"
        if available is not None and model not in available:
            icon = "❌"
        detail = " · ".join(marks) if marks else "—"
        print(f"{icon} {model:<45} {detail}")

    print()
    if bad_models:
        print("Не отвечают (убери из DIALOG_MODELS/OCR_MODELS или почини id):")
        for model in bad_models:
            print("   - " + model)
        print()

    if args.write_env and ok_models:
        ocr_ok = [m for m in OCR_MODELS if m in ok_models]
        print("Готовые строки для .env (только рабочие модели):")
        print("DIALOG_MODELS=" + ",".join(ok_models))
        print("OCR_MODELS=" + ",".join(ocr_ok or OCR_MODELS))
        print()

    if probe_results:
        print(f"Итого: работают {len(ok_models)} из {len(catalog)}, не отвечают {len(bad_models)}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Какие модели реально доступны у провайдера")
    parser.add_argument("--probe", action="store_true", help="сделать мини-запрос к каждой модели")
    parser.add_argument("--no-list", action="store_true", help="не запрашивать GET /models")
    parser.add_argument("--only-catalog", action="store_true",
                        help="проверять только пул бота, а не весь ALL_MODELS")
    parser.add_argument("--pool", default="all", choices=["all", "dialog", "cheap", "premium", "ocr"],
                        help="какой пул проверять при --only-catalog")
    parser.add_argument("--timeout", type=int, default=20, help="таймаут одного запроса, сек")
    parser.add_argument("--concurrency", type=int, default=4, help="сколько запросов параллельно")
    parser.add_argument("--write-env", action="store_true", help="вывести готовые строки для .env")
    return parser.parse_args()


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
