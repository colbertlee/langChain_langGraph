#!/usr/bin/env bash
# =============================================================================
# deploy.sh — AI Agent Console 一键部署脚本 (v2.0.11)
#
# 等价于：
#   docker compose up -d --build
#
# 步骤：
#   0. 前置检查（docker / docker compose / .env）
#   1. 拉取最新代码（可选：--pull / --no-pull 控制）
#   2. 构建并启动 api + web（Nginx 反向代理）
#   3. 健康检查轮询
#
# 用法：
#   ./deploy.sh                 # 构建并启动
#   ./deploy.sh --no-build      # 跳过构建，直接启动已构建镜像
#   ./deploy.sh --pull          # 先 git pull，再构建启动
#   ./deploy.sh --logs          # 启动后跟随日志
#   ./deploy.sh --down          # 停止并清理（保留卷）
#   ./deploy.sh --down -v       # 停止并删除卷（⚠ 清空数据）
#
# 环境要求：
#   - docker ≥ 24
#   - docker compose v2（plugin，非 legacy docker-compose）
#   - 根目录存在 .env（不存在会提示复制 .env.example）
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ──────────────── 颜色输出 ────────────────
if [[ -t 1 ]]; then
    C_RESET=$'\033[0m'; C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
else
    C_RESET=""; C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""
fi
info()  { printf "%s[INFO]%s  %s\n" "$C_BLUE"   "$C_RESET" "$*"; }
ok()    { printf "%s[PASS]%s  %s\n" "$C_GREEN"  "$C_RESET" "$*"; }
warn()  { printf "%s[WARN]%s  %s\n" "$C_YELLOW" "$C_RESET" "$*"; }
err()   { printf "%s[FAIL]%s  %s\n" "$C_RED"    "$C_RESET" "$*" >&2; }

# ──────────────── 参数解析 ────────────────
DO_BUILD=1
DO_PULL=0
DO_LOGS=0
DO_DOWN=0
DO_DOWN_VOLUMES=0

for arg in "$@"; do
    case "$arg" in
        --no-build)   DO_BUILD=0 ;;
        --build)      DO_BUILD=1 ;;
        --pull)       DO_PULL=1 ;;
        --logs)       DO_LOGS=1 ;;
        --down)       DO_DOWN=1 ;;
        -v|--volumes) DO_DOWN_VOLUMES=1 ;;
        -h|--help)
            sed -n '2,25p' "$0"
            exit 0
            ;;
        *)
            err "未知参数: $arg"; exit 1 ;;
    esac
done

# ──────────────── 0. 前置检查 ────────────────
command -v docker >/dev/null 2>&1 || { err "docker 未安装"; exit 1; }
docker compose version >/dev/null 2>&1 || { err "docker compose v2 未安装"; exit 1; }

info "Docker 版本:    $(docker --version)"
info "Compose 版本:   $(docker compose version --short)"

# ──────────────── .env 检查 ────────────────
if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        warn ".env 不存在，是否从 .env.example 复制？（回车跳过 / 输入 y 复制）"
        read -r ans
        if [[ "${ans:-}" == "y" || "${ans:-}" == "Y" ]]; then
            cp .env.example .env
            ok "已复制 .env.example → .env，请编辑填入 API Key 后再次执行"
            exit 0
        else
            err "未找到 .env，且未复制模板。请先 cp .env.example .env 并填入 Key"
            exit 1
        fi
    else
        err "未找到 .env 与 .env.example"
        exit 1
    fi
fi

# ──────────────── 1. git pull（可选） ────────────────
if [[ "$DO_PULL" == "1" ]]; then
    if command -v git >/dev/null 2>&1 && [[ -d .git ]]; then
        info "git pull --ff-only"
        git pull --ff-only || warn "git pull 失败（可能存在本地修改），继续部署"
    else
        warn "非 git 仓库或 git 不可用，跳过 pull"
    fi
fi

# ──────────────── 2. 启动 ────────────────
if [[ "$DO_DOWN" == "1" ]]; then
    info "停止所有服务..."
    if [[ "$DO_DOWN_VOLUMES" == "1" ]]; then
        warn "⚠ 同时删除数据卷（ai_agent_data / ai_agent_uploads）"
        docker compose down -v
    else
        docker compose down
    fi
    ok "已停止"
    exit 0
fi

if [[ "$DO_BUILD" == "1" ]]; then
    info "构建并启动 (docker compose up -d --build)"
else
    info "启动已构建镜像 (docker compose up -d)"
fi
docker compose up -d --build

# ──────────────── 3. 健康检查 ────────────────
info "等待 api 服务健康（最多 60s）..."
for i in $(seq 1 30); do
    if docker compose ps api 2>/dev/null | grep -q "(healthy)"; then
        ok "api 健康（${i}*2s）"
        break
    fi
    if [[ $i -eq 30 ]]; then
        warn "api 未在 60s 内 healthy，查看状态:"
        docker compose ps
        warn "继续启动流程；如有问题可执行 'docker compose logs api' 排查"
        break
    fi
    sleep 2
done

info "等待 web 服务健康（最多 30s）..."
for i in $(seq 1 15); do
    if docker compose ps web 2>/dev/null | grep -q "(healthy)"; then
        ok "web 健康（${i}*2s）"
        break
    fi
    if [[ $i -eq 15 ]]; then
        warn "web 未在 30s 内 healthy，查看状态:"
        docker compose ps
        break
    fi
    sleep 2
done

# ──────────────── 摘要 ────────────────
echo ""
ok "部署完成。访问入口："
echo "  - HTTP:   http://localhost/"
echo "  - API:    http://localhost/api/health  (经 Nginx 反代)"
echo "  - 后端:   端口 8000 仅容器内可见，未对外暴露"
echo ""
info "常用命令："
echo "  docker compose logs -f web    # Nginx 访问日志"
echo "  docker compose logs -f api    # FastAPI 应用日志"
echo "  docker compose ps             # 服务状态"
echo "  docker compose exec api sh    # 进后端容器调试"
echo "  ./deploy.sh --down            # 停止服务（保留数据卷）"
echo "  ./deploy.sh --down -v         # 停止并清空数据（⚠ 谨慎）"
echo ""

if [[ "$DO_LOGS" == "1" ]]; then
    info "跟随日志 (Ctrl+C 退出)..."
    docker compose logs -f
fi
