#!/bin/bash
# run.sh — запуск обоих ботов.
# Логи идут в консоль, каждый процесс — со своим префиксом.

cd "$(dirname "$0")" || exit 1

# Цвета
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

# Мусорный фильтр (то же, что было)
FILTER='grep --line-buffered -v -E "Unknown interaction|error code: 10062|InteractionTimedOut|Interaction took more than|500 Internal Server Error|Task exception was never retrieved|ClientConnectorError|ServerDisconnectedError|aiohttp.client_exceptions"'

# Основной бот
PYTHONUNBUFFERED=1 stdbuf -oL -eL python main.py 2>&1 \
    | sed "s/^/${GREEN}[MAIN]${NC} /" \
    | eval $FILTER &

MAIN_PID=$!

# AI-бот
PYTHONUNBUFFERED=1 stdbuf -oL -eL python ai_main.py 2>&1 \
    | sed "s/^/${CYAN}[AI]${NC}   /" \
    | eval $FILTER &

AI_PID=$!

# Ждём оба процесса, если один падает — гасим второй
wait -n $MAIN_PID $AI_PID
kill $MAIN_PID $AI_PID 2>/dev/null
wait
