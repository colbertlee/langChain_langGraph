#!/usr/bin/env bash
# =============================================================================
# start-e2e-stack.sh — 前端 + 后端 E2E 联调栈一键编排
#
# 作用：
#   1. 后台启动前端 Vite dev server (5173)  - 如端口空闲才启动
#   2. 后台启动后端 uvicorn app:app       (8000)  - 如端口空闲才启动
#   3. 轮询等待两端端口就绪（最多 E2E_TIMEOUT 秒）
#   4. 自动运行沙箱 E2E 脚本 web_console/e2e_no_browser.mjs
#   5. 测试结束后优雅清理：先 SIGTERM，5s 后 SIGKILL
#
# 设计要点：
#   - 默认从仓库根目录运行；也可从 web_console/ 运行，脚本会自动推断 REPO_ROOT。
#   - 端口空闲时复用；KEEP_RUNNING=1 表示脚本退出后保留服务，默认清理。
#   - 日志写到 /tmp/e2e-stack-{frontend,backend}.log（Linux/macOS/Git-Bash）。
#
# 用法：
#   bash scripts/start-e2e-stack.sh                       # 默认（clean）
#   KEEP_RUNNING=1 bash scripts/start-e2e-stack.sh        # 跑完保留服务
#   SKIP_FRONTEND=1 bash scripts/start-e2e-stack.sh       # 只跑后端 + E2E
#   SKIP_BACKEND=1  bash scripts/start-e2e-stack.sh       # 只跑前端 + E2E
#   FRONTEND_PORT=5180 BACKEND_PORT=8080 bash scripts/...  # 自定义端口
#
# Exit codes:
#   0  E2E 全部 PASS（不论服务是否保留）
#   1  E2E 至少 1 项 FAIL
#   2  端口就绪超时
#   3  依赖缺失（node / npm / python / uvicorn）
# =============================================================================
set -u
set -o pipefail

# ---- 0. 路径与变量 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 仓库根目录 = 脚本所在目录的上两级（web_console/scripts -> web_console -> repo root）
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

FRONTEND_DIR="$REPO_ROOT/web_console"
BACKEND_DIR="$REPO_ROOT/ai_agent"

FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

KEEP_RUNNING="${KEEP_RUNNING:-0}"
SKIP_FRONTEND="${SKIP_FRONTEND:-0}"
SKIP_BACKEND="${SKIP_BACKEND:-0}"
E2E_SCRIPT="$FRONTEND_DIR/e2e_no_browser.mjs"
E2E_TIMEOUT="${E2E_TIMEOUT:-90}"   # 端口就绪总超时（秒）
PORT_PROBE_INTERVAL="${PORT_PROBE_INTERVAL:-1}"

# 日志路径（Linux/macOS 用 /tmp；Git-Bash on Windows 上也是 /tmp）
LOG_DIR="${TMPDIR:-/tmp}"
FRONTEND_LOG="$LOG_DIR/e2e-stack-frontend.log"
BACKEND_LOG="$LOG_DIR/e2e-stack-backend.log"

# 子进程 PID（trap 清理）
FRONTEND_PID=""
BACKEND_PID=""
EXIT_CODE=0

# ---- 1. 颜色输出 ----
if [[ -t 2 ]]; then
    C_RESET=$'\033[0m'
    C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'
    C_RED=$'\033[31m'
    C_BLUE=$'\033[34m'
else
    C_RESET=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_BLUE=""
fi
info()  { printf "%s[INFO]%s %s\n" "$C_BLUE"   "$C_RESET" "$*"; }
ok()    { printf "%s[PASS]%s %s\n" "$C_GREEN"  "$C_RESET" "$*"; }
warn()  { printf "%s[WARN]%s %s\n" "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()   { printf "%s[FAIL]%s %s\n" "$C_RED"    "$C_RESET" "$*" >&2; }

# ---- 2. 工具函数 ----
have_cmd() { command -v "$1" >/dev/null 2>&1; }

probe_port() {
    local host="$1" port="$2"
    if have_cmd curl; then
        curl -fsS --max-time 2 "http://$host:$port" >/dev/null 2>&1
    elif have_cmd wget; then
        wget -q --timeout=2 --tries=1 -O /dev/null "http://$host:$port" 2>&1
    else
        if have_cmd nc; then
            nc -z -w 2 "$host" "$port" 2>/dev/null
        else
            # bash /dev/tcp（Git-Bash 也支持）
            (echo > "/dev/tcp/$host/$port") >/dev/null 2>&1
        fi
    fi
}

wait_for_port() {
    local label="$1" host="$2" port="$3" deadline
    deadline=$(( $(date +%s) + E2E_TIMEOUT ))
    info "等待 $label 端口 $host:$port 就绪…"
    while true; do
        if probe_port "$host" "$port"; then
            ok "$label 端口就绪 ($host:$port)"
            return 0
        fi
        if [[ "$(date +%s)" -ge "$deadline" ]]; then
            err "$label 端口在 ${E2E_TIMEOUT}s 内未就绪 ($host:$port)"
            return 1
        fi
        sleep "$PORT_PROBE_INTERVAL"
    done
}

cleanup() {
    local sig="${1:-TERM}"
    if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        info "停止 frontend (pid=$FRONTEND_PID, SIG$sig)"
        kill -$sig "$FRONTEND_PID" 2>/dev/null || true
    fi
    if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        info "停止 backend (pid=$BACKEND_PID, SIG$sig)"
        kill -$sig "$BACKEND_PID" 2>/dev/null || true
    fi
}

on_exit() {
    local code=$?
    if [[ "$KEEP_RUNNING" == "1" ]]; then
        info "KEEP_RUNNING=1：保留服务。frontend=$FRONTEND_PID backend=$BACKEND_PID"
        return
    fi
    cleanup TERM
    sleep 5
    cleanup KILL
    if [[ "$code" == "0" ]]; then
        ok "E2E 栈已清理（日志保留: $FRONTEND_LOG / $BACKEND_LOG）"
    else
        warn "E2E 栈已清理（日志: $FRONTEND_LOG / $BACKEND_LOG，退出码=$code）"
    fi
}
trap on_exit EXIT INT TERM

# ---- 3. 前置检查 ----
info "仓库根目录: $REPO_ROOT"
info "前端目录: $FRONTEND_DIR (port=$FRONTEND_PORT)"
info "后端目录: $BACKEND_DIR (port=$BACKEND_PORT)"

have_cmd node || { err "node 未安装"; exit 3; }
have_cmd npm  || { err "npm 未安装"; exit 3; }
have_cmd python || have_cmd python3 || { err "python 未安装"; exit 3; }
PYTHON_BIN="$(have_cmd python3 && echo python3 || echo python)"
have_cmd uvicorn || warn "uvicorn 未在 PATH（将使用 python -m uvicorn）"

[[ -f "$E2E_SCRIPT" ]] || { err "E2E 脚本不存在: $E2E_SCRIPT"; exit 3; }

# ---- 4. 启动前端 ----
if [[ "$SKIP_FRONTEND" != "1" ]]; then
    if probe_port "127.0.0.1" "$FRONTEND_PORT"; then
        ok "前端端口 $FRONTEND_PORT 已被占用，跳过启动"
    else
        [[ -d "$FRONTEND_DIR/node_modules" ]] || {
            info "前端未安装依赖，执行 npm ci…"
            ( cd "$FRONTEND_DIR" && npm ci ) || { err "npm ci 失败"; exit 3; }
        }
        info "启动前端: npm run dev (日志: $FRONTEND_LOG)"
        (
            cd "$FRONTEND_DIR"
            nohup npm run dev -- --port "$FRONTEND_PORT" >"$FRONTEND_LOG" 2>&1 &
            echo $! >"$LOG_DIR/e2e-stack-frontend.pid"
        )
        FRONTEND_PID="$(cat "$LOG_DIR/e2e-stack-frontend.pid" 2>/dev/null || echo "")"
        wait_for_port "frontend" "127.0.0.1" "$FRONTEND_PORT" || {
            err "前端启动失败，尾部日志："; tail -n 50 "$FRONTEND_LOG" >&2; exit 2
        }
    fi
else
    info "SKIP_FRONTEND=1，跳过前端"
fi

# ---- 5. 启动后端 ----
if [[ "$SKIP_BACKEND" != "1" ]]; then
    if probe_port "127.0.0.1" "$BACKEND_PORT"; then
        ok "后端端口 $BACKEND_PORT 已被占用，跳过启动"
    else
        info "启动后端: uvicorn app:app (日志: $BACKEND_LOG)"
        (
            cd "$BACKEND_DIR"
            nohup "$PYTHON_BIN" -m uvicorn app:app \
                    --host 127.0.0.1 --port "$BACKEND_PORT" \
                    --log-level info >"$BACKEND_LOG" 2>&1 &
            echo $! >"$LOG_DIR/e2e-stack-backend.pid"
        )
        BACKEND_PID="$(cat "$LOG_DIR/e2e-stack-backend.pid" 2>/dev/null || echo "")"
        wait_for_port "backend" "127.0.0.1" "$BACKEND_PORT" || {
            err "后端启动失败，尾部日志："; tail -n 50 "$BACKEND_LOG" >&2; exit 2
        }
    fi
else
    info "SKIP_BACKEND=1，跳过后端"
fi

# ---- 6. 运行 E2E ----
info "运行 E2E: node $E2E_SCRIPT"
EXIT_CODE=0
( cd "$FRONTEND_DIR" && node "$E2E_SCRIPT" ) || EXIT_CODE=$?

if [[ "$EXIT_CODE" == "0" ]]; then
    ok "E2E 全部通过"
else
    err "E2E 退出码=$EXIT_CODE（详见上方日志）"
fi

exit "$EXIT_CODE"