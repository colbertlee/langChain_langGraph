#!/usr/bin/env bash
# 生成 Playwright 视觉回归 baseline。
#
# 用法：
#   bash scripts/generate-visual-baseline.sh            # 本地 dev server 自动起
#   E2E_BASE_URL=https://staging bash scripts/...sh      # 用外部 URL
#
# 效果：删除旧 baseline → 跑 visual.spec.ts → 产生新 baseline → 提示提交

set -euo pipefail

cd "$(dirname "$0")/.."

echo "🎨 Playwright visual baseline generation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. 检查 Playwright 是否已装
if ! command -v npx >/dev/null 2>&1; then
  echo "❌ npx not found. Install Node.js 18+ first."
  exit 1
fi

# 2. 检查 chromium 是否已下载
if [ ! -d "$HOME/.cache/ms-playwright" ]; then
  echo "📦 Installing Chromium for Playwright..."
  npm run e2e:install
fi

# 3. 删除旧 baseline（如有）
SNAPSHOT_DIR="e2e/visual.spec.ts-snapshots"
if [ -d "$SNAPSHOT_DIR" ]; then
  echo "🗑️  Removing old baseline at $SNAPSHOT_DIR/"
  rm -rf "$SNAPSHOT_DIR"
fi

# 4. 跑 visual.spec.ts 自动生成 baseline
echo "📸 Generating baseline snapshots..."
echo ""

# CI 环境加 CI=1 让 Playwright 不弹交互
export CI=1
npx playwright test visual.spec.ts --update-snapshots

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -d "$SNAPSHOT_DIR" ]; then
  COUNT=$(find "$SNAPSHOT_DIR" -name "*.png" | wc -l | tr -d ' ')
  echo "✅ Generated $COUNT baseline PNG file(s)."
  echo ""
  echo "Next steps:"
  echo "  git add $SNAPSHOT_DIR/"
  echo "  git commit -m 'test: add visual regression baseline'"
  echo "  git push"
else
  echo "❌ Baseline directory not created. Check test output above."
  exit 1
fi