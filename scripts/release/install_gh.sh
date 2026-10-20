#!/usr/bin/env bash
# scripts/release/install_gh.sh
# 为 Windows / Linux / macOS 一键安装 GitHub CLI (gh) 并完成认证。
#
# 背景:
#   本仓库的发布流水线 (scripts/release/release_cli.py) 与 GitHub 写操作
#   (PR 创建、分支删除、Release 上传资产) 推荐通过 gh CLI 调用。
#   gh 未安装或未认证时会阻断整个 SOP §4-7, 此前在本仓库 v2.5.0 收尾时
#   多次出现 "gh: command not found" 阻断。
#
# 用法:
#   ./install_gh.sh                    # 仅安装,不认证
#   ./install_gh.sh --auth             # 安装 + 触发 gh auth login 交互流程
#   GH_TOKEN=ghp_xxx ./install_gh.sh --auth --token  # 跳过交互直接用 PAT 认证
#   INSTALLER=scoop/choco/apt/dnf/brew ./install_gh.sh
#
# 选项:
#   --auth                          安装后启动 gh auth login (交互)
#   --token <pat>                   使用 PAT 直接认证 (避免交互,CI/单 owner 仓库推荐)
#   --check-only                    只检查 gh 是否就绪,不做任何修改 (供脚本前置判断)
#   -h | --help                     显示帮助
#
# 退出码:
#   0  成功(已就绪或安装完成)
#   1  调用参数错误
#   2  平台不支持
#   3  安装失败
#   4  认证失败
#
# 参考:docs/VERSION_MANAGEMENT.md §4 (推送与认证)

set -euo pipefail

# ============================================================
# 常量
# ============================================================
GH_MIN_VERSION="2.40.0"
REPO_OWNER="colbertlee"
REPO_NAME="langChain_langGraph"
REPO_FULL="${REPO_OWNER}/${REPO_NAME}"

# ============================================================
# 工具函数
# ============================================================
log()   { echo "[install_gh] $*"; }
warn()  { echo "[install_gh] WARN: $*" >&2; }
fail()  { echo "[install_gh] FAIL: $*" >&2; exit "${2:-1}"; }

version_ge() {
  # 纯 bash 比较 "X.Y.Z" 版本号,避免依赖 sort -V
  local a="$1" b="$2"
  IFS=. read -r a1 a2 a3 <<<"$a"
  IFS=. read -r b1 b2 b3 <<<"$b"
  a3="${a3:-0}"; b3="${b3:-0}"
  (( a1 > b1 )) && return 0
  (( a1 < b1 )) && return 1
  (( a2 > b2 )) && return 0
  (( a2 < b2 )) && return 1
  (( a3 >= b3 )) && return 0
  return 1
}

detect_os() {
  local os
  case "$(uname -s 2>/dev/null || echo Windows)" in
    Linux*)  os="linux" ;;
    Darwin*) os="macos" ;;
    CYGWIN*|MINGW*|MSYS*|Windows*) os="windows" ;;
    *)       os="unknown" ;;
  esac
  echo "$os"
}

detect_installer() {
  # 按优先级探测可用包管理器
  local os="$1"
  if [[ "$os" == "windows" ]]; then
    if command -v scoop >/dev/null 2>&1; then echo "scoop"; return; fi
    if command -v choco >/dev/null 2>&1; then echo "choco"; return; fi
    if command -v winget >/dev/null 2>&1; then echo "winget"; return; fi
    echo "none"
  else
    if command -v brew >/dev/null 2>&1; then echo "brew"; return; fi
    if command -v apt-get >/dev/null 2>&1; then echo "apt"; return; fi
    if command -v dnf >/dev/null 2>&1; then echo "dnf"; return; fi
    if command -v yum >/dev/null 2>&1; then echo "yum"; return; fi
    echo "none"
  fi
}

# ============================================================
# 安装
# ============================================================
install_via_scoop() { scoop install gh; }
install_via_choco() { choco install gh --yes; }
install_via_winget(){ winget install --id GitHub.cli --silent --accept-package-agreements --accept-source-agreements; }
install_via_brew()  { brew install gh; }
install_via_apt()   {
  # 官方源 (推荐):https://github.com/cli/cli/blob/trunk/docs/install_linux.md
  (type -p wget >/dev/null || sudo apt-get install -y wget) || true
  wget -qO /tmp/gh-keyring.gpg https://cli.github.com/packages/githubcli-archive-keyring.gpg
  sudo gpg --dearmor < /tmp/gh-keyring.gpg | sudo tee /usr/share/keyrings/githubcli-archive-keyring.gpg >/dev/null
  sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y gh
}
install_via_dnf() {
  sudo dnf install -y 'dnf-command(config-manager)'
  sudo dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo
  sudo dnf install -y gh
}
install_via_yum() { install_via_dnf; }

install_gh() {
  local os="$1" inst="$2"
  log "平台=$os,选择安装器=$inst"
  case "$inst" in
    scoop) install_via_scoop ;;
    choco) install_via_choco ;;
    winget) install_via_winget ;;
    brew)  install_via_brew  ;;
    apt)   install_via_apt   ;;
    dnf)   install_via_dnf   ;;
    yum)   install_via_yum   ;;
    none)
        warn "未找到 scoop/choco/winget(Windows) 或 brew/apt/dnf/yum(unix)"
        warn "请手动安装:https://cli.github.com/manual/installation"
        return 1
        ;;
    *) fail "未知安装器 '$inst'" 1 ;;
  esac
}

# ============================================================
# 认证
# ============================================================
auth_with_token() {
  local token="$1"
  log "使用 PAT 直接认证 (跳过交互)"
  # echo "$token" | gh auth login --with-token
  echo "$token" | gh auth login --hostname github.com --with-token
}

auth_interactive() {
  log "启动 gh auth login 交互流程 (按提示选择 GitHub.com + HTTPS + Paste token)"
  gh auth login --hostname github.com
}

# ============================================================
# 检查
# ============================================================
check_gh() {
  if ! command -v gh >/dev/null 2>&1; then
    return 1
  fi
  local ver
  ver="$(gh --version | awk 'NR==1{print $3}')"
  if [[ -z "$ver" ]]; then return 1; fi
  version_ge "$ver" "$GH_MIN_VERSION" || {
    warn "gh $ver < 要求版本 $GH_MIN_VERSION"
    return 0  # 版本低也视为"已安装",不强制升级
  }
}

check_auth() {
  if ! gh auth status >/dev/null 2>&1; then
    return 1
  fi
}

verify_repo_access() {
  log "校验对 ${REPO_FULL} 的访问..."
  gh repo view "${REPO_FULL}" --json nameWithOwner --jq '.nameWithOwner' >/dev/null
}

# ============================================================
# 主流程
# ============================================================
usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  cat <<EOF

示例:
  ./install_gh.sh
  ./install_gh.sh --check-only
  GH_TOKEN=ghp_xxx ./install_gh.sh --auth --token "\$GH_TOKEN"
EOF
}

main() {
  local do_auth=0
  local do_check_only=0
  local token_arg=""

  while (( $# > 0 )); do
    case "$1" in
      --auth)       do_auth=1 ;;
      --check-only) do_check_only=1 ;;
      --token)      shift; token_arg="${1:-}" ;;
      -h|--help)    usage; exit 0 ;;
      *)            fail "未知参数: $1" 1 ;;
    esac
    shift
  done

  log "=== gh CLI 安装与认证 ==="
  log "最低版本要求:$GH_MIN_VERSION"
  log "目标仓库:${REPO_FULL}"

  # ---- 仅检查模式 ----
  if (( do_check_only == 1 )); then
    if check_gh; then log "✓ gh 已安装:$(gh --version | awk 'NR==1')"
    else log "✗ gh 未安装或不可执行"; exit 3; fi
    if check_auth; then log "✓ gh 已认证"
    else log "✗ gh 未认证就绪"; exit 4; fi
    verify_repo_access && log "✓ 可访问 ${REPO_FULL}"
    exit 0
  fi

  # ---- 安装阶段 ----
  local os inst installed=0
  os="$(detect_os)"
  log "检测到操作系统:$os"

  if check_gh; then
    log "✓ gh 已存在,跳过安装"
    installed=1
  else
    if [[ -n "${INSTALLER:-}" ]]; then
      inst="$INSTALLER"
    else
      inst="$(detect_installer "$os")"
    fi
    log "自动选择的安装器:$inst"

    case "$os" in
      windows|linux|macos) ;;
      *) fail "不支持的操作系统 '$os'" 2 ;;
    esac

    if install_gh "$os" "$inst"; then
      # 某些安装器(如 scoop/brew)安装后不会刷新 PATH,显式 hash -r
      hash -r
      if check_gh; then
        log "✓ 安装成功:$(gh --version | awk 'NR==1')"
        installed=1
      else
        fail "安装成功但 gh 仍不可执行 (PATH 未刷新?)" 3
      fi
    else
      fail "安装失败" 3
    fi
  fi

  # ---- 认证阶段 ----
  if (( do_auth == 1 )); then
    if check_auth; then
      log "✓ gh 已处于已认证状态"
    else
      if [[ -n "$token_arg" ]]; then
        auth_with_token "$token_arg" || fail "auth login 失败" 4
      else
        auth_interactive || fail "auth login 失败" 4
      fi
    fi

    verify_repo_access && log "✓ 对 ${REPO_FULL} 的 API 访问验证通过"
    gh auth status || true
  fi

  log "=== 完成 ==="
  log "后续可直接使用:"
  log "  gh pr create --base master --head <branch>"
  log "  python scripts/release/release_cli.py status"
}

main "$@"