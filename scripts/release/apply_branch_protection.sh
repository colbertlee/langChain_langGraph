#!/usr/bin/env bash
# scripts/release/apply_branch_protection.sh
# 为 master / release/* 分支一键启用 GitHub 分支保护规则。
#
# 用法:
#   GH_TOKEN=ghp_xxx ./apply_branch_protection.sh master
#   GH_TOKEN=ghp_xxx ./apply_branch_protection.sh release/v2.0.7-cleanup-verified
#
# 前置条件:
#   - GH_TOKEN 需包含 repo scope
#   - 目标分支已存在并与本地一致
#
# 参考:docs/VERSION_MANAGEMENT.md §7.5

set -euo pipefail

REPO="${REPO:-colbertlee/langChain_langGraph}"
BRANCH="${1:-}"

if [[ -z "$BRANCH" ]]; then
  echo "用法: $0 <branch-name>" >&2
  echo "示例: $0 master" >&2
  echo "      $0 release/v2.0.7-cleanup-verified" >&2
  exit 1
fi

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "错误:GH_TOKEN 环境变量未设置" >&2
  exit 1
fi

case "$BRANCH" in
  master)
    PAYLOAD='{
      "required_status_checks": null,
      "enforce_admins": true,
      "required_pull_request_reviews": {
        "dismiss_stale_reviews": true,
        "require_code_owner_reviews": false,
        "required_approving_review_count": 1,
        "require_last_push_approval": true
      },
      "restrictions": null,
      "required_linear_history": true,
      "allow_force_pushes": false,
      "allow_deletions": false,
      "block_creations": false,
      "required_conversation_resolution": true,
      "lock_branch": false,
      "allow_fork_syncing": false
    }'
    ;;
  release/*)
    PAYLOAD='{
      "required_status_checks": null,
      "enforce_admins": false,
      "required_pull_request_reviews": null,
      "restrictions": null,
      "required_linear_history": false,
      "allow_force_pushes": false,
      "allow_deletions": false,
      "block_creations": false,
      "required_conversation_resolution": false,
      "lock_branch": false,
      "allow_fork_syncing": false
    }'
    ;;
  *)
    echo "错误:不支持的分支 '$BRANCH'" >&2
    echo "支持的模式:master | release/*" >&2
    exit 1
    ;;
esac

echo ">>> 正在为 ${REPO}@${BRANCH} 应用分支保护..."
RESP=$(curl -sS -w "\nHTTP_STATUS:%{http_code}" \
  -X PUT \
  -H "Authorization: token ${GH_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  "https://api.github.com/repos/${REPO}/branches/${BRANCH}/protection" \
  -d "${PAYLOAD}")

HTTP=$(echo "$RESP" | grep -o 'HTTP_STATUS:[0-9]*' | cut -d: -f2)
BODY=$(echo "$RESP" | sed '/HTTP_STATUS:/d')

if [[ "$HTTP" == "200" ]]; then
  echo "✓ 分支保护已启用 (HTTP ${HTTP})"
  echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
else
  echo "✗ 启用失败 (HTTP ${HTTP})" >&2
  echo "$BODY" >&2
  exit 2
fi