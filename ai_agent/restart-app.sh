#!/usr/bin/env bash
# ============================================================
#  AI Agent - Restart script (macOS / Linux)
#  1) Stop any process on -Port (default 8000)
#  2) Start `python app.py` in a new terminal window (best-effort)
#  3) Poll /api/health until ready (max 15s)
#
#  Usage:
#    ./restart-app.sh            # default port 8000
#    ./restart-app.sh 8080       # custom port
#    ./restart-app.sh -NoStart   # stop only (bash: --no-start)
# ============================================================
set -euo pipefail

PORT=8000
NO_START=0
for arg in "$@"; do
    case "$arg" in
        -NoStart|--no-start) NO_START=1 ;;
        -h|--help)
            sed -n '2,12p' "$0"; exit 0 ;;
        *) PORT="$arg" ;;
    esac
done

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 1) Stop
bash "$SCRIPT_DIR/stop-app.sh" "$PORT"

if [[ "$NO_START" -eq 1 ]]; then
    echo "[restart] -NoStart specified; exiting."
    exit 0
fi

# 2) Start in a new terminal window if possible.
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_PATH="$LOG_DIR/app-$STAMP.log"
export PORT="$PORT"

LAUNCH_CMD="cd '$SCRIPT_DIR' && PORT='$PORT' python3 app.py 2>&1 | tee '$LOG_PATH'"

case "${OS:-$(uname -s)}" in
    Darwin)
        # AppleScript: new Terminal window running the command.
        osascript <<EOF >/dev/null 2>&1 || true
tell application "Terminal"
    do script "$LAUNCH_CMD"
    activate
end tell
EOF
        ;;
    Linux)
        if command -v gnome-terminal >/dev/null 2>&1; then
            gnome-terminal -- bash -lc "$LAUNCH_CMD" >/dev/null 2>&1 &
        elif command -v xterm >/dev/null 2>&1; then
            xterm -e bash -lc "$LAUNCH_CMD" >/dev/null 2>&1 &
        elif command -v konsole >/dev/null 2>&1; then
            konsole -e bash -lc "$LAUNCH_CMD" >/dev/null 2>&1 &
        else
            echo "[restart] No GUI terminal found; falling back to nohup."
            nohup bash -lc "$LAUNCH_CMD" >/dev/null 2>&1 &
        fi
        ;;
    *)  # MINGW/Cygwin from Git Bash etc.
        if command -v mintty >/dev/null 2>&1; then
            mintty -t "AI Agent Web" bash -lc "$LAUNCH_CMD" >/dev/null 2>&1 &
        else
            nohup bash -lc "$LAUNCH_CMD" >/dev/null 2>&1 &
        fi
        ;;
esac

echo "[restart] Launching. Logs: $LOG_PATH"
echo "             Open http://127.0.0.1:$PORT/ in your browser."

# 3) Wait until /api/health responds (max ~15s).
ok=0
for _ in $(seq 1 30); do
    sleep 0.5
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/health" || true)"
    if [[ "$code" == "200" ]]; then
        ok=1
        break
    fi
done

if [[ "$ok" -eq 1 ]]; then
    echo "[restart] Backend is up at http://127.0.0.1:$PORT/"
    exit 0
fi

echo "[restart] Backend did not respond on /api/health within 15s. Tail the log:"
echo "           $LOG_PATH"
exit 2
