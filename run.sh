#!/bin/bash
# run.sh — запуск обоих ботов через main.py
# AI-бот теперь стартует из main.py, отдельного ai_main.py больше нет

cd "$(dirname "$0")" || exit 1

PYTHONUNBUFFERED=1 stdbuf -oL -eL python main.py 2>&1 | grep --line-buffered -v -E \
"Unknown interaction|error code: 10062|InteractionTimedOut|Interaction took more than|500 Internal Server Error|error code: 10062|Task exception was never retrieved|ClientConnectorError|ServerDisconnectedError|aiohttp.client_exceptions|NotFound: 404 Not Found \(error code: 10062\)|The above exception was the direct cause"
