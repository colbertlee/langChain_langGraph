#!/usr/bin/env bash
# ============================================================
#  AI Agent - Stop script (macOS / Linux)
#  Kills whichever process is bound to -Port (default 8000),
#  i.e. the uvicorn backend started by `python app.py` or the
#  packaged `ai-agent web`.
# ============================================================
set -euo pipefail

PORT="${1:-8000}"

free_port_pids() {
    local port="$1"
    # Try multiple tools to be portable across macOS/Linux.
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    elif command -v fuser >/dev/null 2>&1; then
        fuser -n tcp "$port" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true
    else
        # ss on Linux as a last resort.
        ss -lntp 2>/dev/null \
            | awk -v p=":$port" '$4 ~ p {print $0}' \
            | grep -oE 'pid=[0-9]+' \
            | cut -d= -f2 \
            | sort -u || true
    fi
}

pids="$(free_port_pids "$PORT" || true)"
if [[ -z "${pids// /}" ]]; then
    echo "[stop] Port $PORT is free."
    exit 0
fi

echo "[stop] Port $PORT held by PID(s): $pids"
for pid in $pids; do
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    echo "    PID $pid: $cmd"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
    fi
done

# Wait up to 3s for the socket to be released.
for _ in $(seq 1 10); do
    sleep 0.3
    if [[ -z "$(free_port_pids "$PORT" || true)" ]]; then
        echo "[stop] Port $PORT released."
        exit 0
    fi
done

# Force kill stragglers.
for pid in $pids; do
    if kill -0 "$pid" 2>/dev/null; then
        echo "[stop] Forcing PID $pid"
        kill -9 "$pid" 2>/dev/null || true
    fi
done
sleep 0.5

if [[ -n "$(free_port_pids "$PORT" || true)" ]]; then
    echo "[stop] Port $PORT still occupied." >&2
    exit 1
fi
echo "[stop] Port $PORT released."
