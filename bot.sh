#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$DIR/bot.pid"
LOG_FILE="$DIR/bot.log"

if [ -f "$HOME/.venv/bin/python3" ]; then
    PYTHON="$HOME/.venv/bin/python3"
else
    PYTHON="python3"
fi

start() {
    # Убиваем любые зомби-процессы bot.py (запущенные не через bot.sh)
    ZOMBIES=$(pgrep -f "python.*bot\.py" 2>/dev/null | grep -v "$$" || true)
    if [ -n "$ZOMBIES" ]; then
        echo "Найдены лишние процессы: $ZOMBIES — останавливаю..."
        kill $ZOMBIES 2>/dev/null || true
        sleep 2
    fi
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Бот уже запущен (PID $(cat "$PID_FILE"))"
        exit 1
    fi
    cd "$DIR"
    nohup "$PYTHON" bot.py >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Бот запущен (PID $!)"
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        # Даже без PID-файла ищем и убиваем процесс
        ZOMBIES=$(pgrep -f "python.*bot\.py" 2>/dev/null || true)
        if [ -n "$ZOMBIES" ]; then
            kill $ZOMBIES 2>/dev/null && echo "Остановлены процессы: $ZOMBIES" || true
        else
            echo "Бот не запущен"
        fi
        return 0
    fi
    PID=$(cat "$PID_FILE")
    kill "$PID" 2>/dev/null && echo "Остановлен PID $PID" || echo "Процесс не найден"
    rm -f "$PID_FILE"
    # Ждём реальной остановки (до 10 сек)
    for i in $(seq 1 10); do
        kill -0 "$PID" 2>/dev/null || break
        sleep 1
    done
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Запущен (PID $(cat "$PID_FILE"))"
    else
        echo "Не запущен"
    fi
}

case "$1" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)  status ;;
    logs)    tail -f "$LOG_FILE" ;;
    *)       echo "Использование: $0 {start|stop|restart|status|logs}" ;;
esac
