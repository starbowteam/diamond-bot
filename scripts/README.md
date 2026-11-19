# scripts — модели AI-менеджера и аналитика

Здесь живёт всё, что связано с выбором/проверкой моделей и с отчётами.

| Файл | Что делает |
|---|---|
| `models.py` | единый список моделей: `DIALOG_MODELS`, `OCR_MODELS`, `CHEAP_MODELS`, `PREMIUM_MODELS`, `ALL_MODELS` |
| `test_models.py` | проверяет модели по трём тестам: диалог, tool call, чтение чека |
| `test_model_config.py` | офлайн-тесты пулов: весь каталог в диалоге, OCR отдельно, чек читается OCR-пулом |
| `test_model_fallback.py` | офлайн-тесты фолбэка: 404 → следующая модель, мёртвая модель уходит в карантин |
| `list_provider_models.py` | показывает, какие модели из каталога реально доступны у провайдера |
| `apply_model_pools.py` | патчит уже развёрнутый `modules/ai_manager.py`: константы → пулы из `models.py` |
| `shop_analytics.py` | собирает HTML-отчёт по магазину (heatmap, выручка, чеки, клиенты, цены) |
| `model_report.json` / `.md` | отчёты последнего прогона (создаются скриптом) |

Бот (`modules/ai_manager.py`) импортирует `DIALOG_MODELS` и `OCR_MODELS` отсюда,
поэтому менять модели нужно **только в `models.py`** (или через env).

`DIALOG_MODELS` по умолчанию содержит **весь каталог** провайдера (17 моделей):
первая рабочая отвечает, остальные — фолбэки. `OCR_MODELS` — отдельный пул для
проверки чеков; переключение на него происходит молча, клиент его не видит.

### Если в логе `LLM ...: HTTP 404`

Это значит, что модели **нет у провайдера** (удалили, переименовали, нет доступа).
Бот не падает: он ставит её в карантин на 6 часов и сразу идёт к следующей.
Но первую после рестарта всё равно пробует, поэтому такую модель лучше убрать.

Проверить, какие ID реально живые:

```bash
python scripts/list_provider_models.py --probe --write-env
```

Скрипт покажет `✅`/`❌` по каждой модели и выведет готовые строки
`DIALOG_MODELS=...` / `OCR_MODELS=...`, где остались только рабочие.

## Настройка

Ключ берётся из переменных окружения или из `.env` в корне проекта:

```env
AI_MANAGER_API_KEY=...
AI_MANAGER_BASE_URL=https://api.zveno.ai/v1
```

Переопределение пулов без правки кода:

```env
DIALOG_MODELS="google/gemini-2.0-flash-001,deepseek/deepseek-v4.1-flash"
OCR_MODELS="google/gemini-3-flash-preview,google/gemini-2.0-flash-001"
# VISION_MODELS="..." — старое имя, тоже поддерживается
```

## Запуск тестов

```bash
cd diamond-bot-main

# проверка конфигурации без API-ключа
python scripts/test_model_config.py
python scripts/test_model_fallback.py
python scripts/test_models.py --check-config

# какие модели реально живые у провайдера
python scripts/list_provider_models.py --probe --write-env

# весь каталог моделей (17 шт.), все три теста
python scripts/test_models.py

# только диалоговый пул или только OCR-пул
python scripts/test_models.py --pool dialog
python scripts/test_models.py --pool ocr --tests vision

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

## Развёртывание пулов на сервере

Если на сервере (например, `/app`) всё ещё лежит старый `ai_manager.py`
с двумя константами — не правьте его руками, запустите патчер из корня проекта:

```bash
python scripts/apply_model_pools.py                 # dry-run: показать diff
python scripts/apply_model_pools.py --apply         # применить + бэкап .bak-*
python scripts/apply_model_pools.py --root /app --apply
```

Скрипт:

1. создаёт `scripts/models.py`, если его нет (существующий не трогает);
2. заменяет `DIAMOND_AI_MODEL = "..."` на `DIAMOND_AI_MODEL = DIALOG_MODELS[0]`;
3. удаляет `LAST_RESORT_MODEL` и переключает `call_llm()` на `for model in DIALOG_MODELS`;
4. импортирует `OCR_MODELS` для отдельной проверки чеков;
5. проверяет синтаксис и только потом пишет файл, сохранив `ai_manager.py.bak-<дата>`.

Повторный запуск безопасен: если патч уже применён, скрипт так и скажет.

## HTML-аналитика магазина

```bash
# реальная база data/diamond.db → data/reports/shop_report.html
python scripts/shop_analytics.py

# демо-данные (если база ещё пустая) и открыть в браузере
python scripts/shop_analytics.py --demo --open

# за 6 месяцев в свой файл
python scripts/shop_analytics.py --months 6 --out report.html
```

В отчёте: календарь активности в стиле GitHub, выручка по месяцам, средний чек,
заказы и уникальные покупатели, приток/отток клиентов, покупательская способность
(индекс средней цены позиции), таблица товаров с изменением цены и месячная сводка.

Источники данных (все читаются изБД в режиме read-only):

- `ai_manager_sessions` — новые счета: `invoice_amount > 0` выставлен,
  непустой `receipt_url` при `invoice_sent = 0` принят (оплата).
- `closed_orders` + `ticket_owners` — закрытые и открытые тикеты:
  число открытий/закрытий по месяцам, среднее время закрытия.
- `ai_manager_sessions` (старые строки без `invoice_amount`) — старые чеки AI-менеджера.
- `dc_cache.purchases` — покупки до появления AI-менеджера.
- `shop_sales` — импортированные продажи, если таблица есть в БД.

Суммы старых покупок в БД не сохранялись, поэтому они учитываются в количестве
(отдельный блок «Тикеты и старые покупки»), но не добавляются в выручку.
Отчёт устойчив к отсутствующим таблицам/колонкам: показывает замечание,
но всегда собирается. Файл один, без CDN и JS, открывается офлайн.

В Telegram-панели: команда `/report [месяцев]`, кнопка «📈 Аналитика» в меню
или «📈 HTML-отчёт по магазину» в «Утилитах». Файл приходит документом.

## Практика

- Free-модели (`:free`) часто отвечают `429` — это нормально, бот автоматически
  переходит к следующей модели из `DIALOG_MODELS`.
- Модель без `vision` в `OCR_MODELS` ставить бессмысленно: чек уйдёт продавцу.
- После проверки скопируй рабочие ID в `DIALOG_MODELS` / `OCR_MODELS`
  в `models.py` — бот подхватит их при следующем старте.
