# scripts — модели AI-менеджера

Здесь живёт всё, что связано с выбором и проверкой моделей.

| Файл | Что делает |
|---|---|
| `models.py` | единый список моделей: `DIALOG_MODELS`, `VISION_MODELS`, `CHEAP_MODELS`, `PREMIUM_MODELS`, `ALL_MODELS` |
| `test_models.py` | проверяет модели по трём тестам: диалог, tool call, чтение чека |
| `model_report.json` / `.md` | отчёты последнего прогона (создаются скриптом) |

Бот (`modules/ai_manager.py`) импортирует `DIALOG_MODELS` и `VISION_MODELS` отсюда,
поэтому менять модели нужно **только в `models.py`** (или через env).

## Настройка

Ключ берётся из переменных окружения или из `.env` в корне проекта:

```env
AI_MANAGER_API_KEY=...
AI_MANAGER_BASE_URL=https://api.zveno.ai/v1
```

Переопределение пулов без правки кода:

```env
DIALOG_MODELS="google/gemini-2.0-flash-001,deepseek/deepseek-v4.1-flash"
VISION_MODELS="google/gemini-3-flash-preview,google/gemini-2.0-flash-001"
```

## Запуск тестов

```bash
cd diamond-bot-main

# все дешёвые модели (free + лёгкие платные), все три теста
python scripts/test_models.py

# только чековые модели
python scripts/test_models.py --pool vision --tests vision

# конкретные модели
python scripts/test_models.py --models "qwen/qwen3-4b:free,google/gemini-2.0-flash-001"

# аккуратно, без параллельных запросов (если free-модели отдают 429)
python scripts/test_models.py --concurrency 1

# только диалог и инструменты, без записи отчётов
python scripts/test_models.py --tests chat,tools --no-report

# сохранить тестовый чек, чтобы посмотреть глазами
python scripts/test_models.py --dump-receipt receipt_test.png
```

## Что означают тесты

| Тест | Проверка |
|---|---|
| `chat` | модель отвечает по-русски, не пустой `content` |
| `tools` | модель вызывает `create_invoice` с валидным JSON (`items`) — как в боте |
| `vision` | модель читает синтетический чек на **2 500 руб.** и возвращает `payment_confirmation` + сумму |

Статусы:

- `OK` — тест пройден;
- `нет ответа` — пустой `content`;
- `без tool call` — модель ответила текстом вместо вызова функции;
- `нет vision` — модель не принимает картинки (HTTP 400/422) или ответила пусто;
- `неверная сумма` / `не чек` — прочитала, но не то;
- `ошибка` — сеть/401/429/timeout (текст ошибки в отчёте).

## Чтение результата

В консоли — таблица по моделям и время ответа, плюс итог вида:

```
Итого: chat 9/13, tools 5/13, vision 3/13
```

Полные детали (текст ошибок, распознанные значения) — в `scripts/model_report.json`
и `scripts/model_report.md`.

## Практика

- Free-модели (`:free`) часто отвечают `429` — это нормально, для бота они стоят
  фолбэками, а не основными.
- Модель без `vision` в `VISION_MODELS` ставить бессмысленно: чек уйдёт продавцу.
- После проверки скопируй рабочие ID в `DIALOG_MODELS` / `VISION_MODELS`
  в `models.py` — бот подхватит их при следующем старте.
