#!/usr/bin/env node
/**
 * 一键创建 scoop-bucket 和 homebrew-tap 仓库。
 *
 * 用法：
 *   GITHUB_TOKEN=ghp_xxx node scripts/create-package-repos.mjs
 *
 * 需配：
 *   - Classic PAT with `repo` + `workflow` scopes
 *   - 两个 repo 已在 GitHub 手动建好（Public）
 *
 * 流程：
 *   1. git clone （空）scoop-bucket → 添加 bucket/ai-agent.json → push
 *   2. git clone （空）homebrew-tap → 添加 Formula/ai-agent.rb → push
 */

import { execSync } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const ORG = 'colbertlee';
const SCOOP_REPO = `${ORG}/scoop-bucket`;
const BREW_REPO = `${ORG}/homebrew-tap`;
const SOURCE_REPO = `${ORG}/langChain_langGraph`;

const TOKEN = process.env.GITHUB_TOKEN;
if (!TOKEN) {
  console.error('❌ Missing GITHUB_TOKEN env var');
  console.error('   Usage: GITHUB_TOKEN=ghp_xxx node scripts/create-package-repos.mjs');
  process.exit(1);
}

const TMP = join(tmpdir(), 'pkg-setup-' + Date.now());
mkdirSync(TMP, { recursive: true });

const authUrl = (repo) =>
  `https://x-access-token:${TOKEN}@github.com/${repo}.git`;

function run(cmd, opts = {}) {
  console.log(`$ ${cmd}`);
  try {
    return execSync(cmd, { stdio: 'inherit', ...opts });
  } catch (e) {
    console.error(`❌ Command failed: ${cmd}`);
    throw e;
  }
}

function readSourceFile(rel) {
  // 脚本在 web_console/scripts/，源文件在 web_console/.github/...
  const path = join(import.meta.dirname, '..', rel);
  return readFileSync(path, 'utf-8');
}

// ─────────────── 1. Scoop bucket ───────────────
async function setupScoop() {
  console.log('\n📦 Setting up scoop-bucket...');
  const dir = join(TMP, 'scoop-bucket');
  run(`git clone ${authUrl(SCOOP_REPO)} ${dir}`);

  // bucket/ai-agent.json
  const manifest = readSourceFile('.github/scoop/ai-agent.json');
  mkdirSync(join(dir, 'bucket'), { recursive: true });
  writeFileSync(join(dir, 'bucket/ai-agent.json'), manifest);

  // README.md
  const readme = `# Scoop Bucket

Manifests for [Scoop](https://scoop.sh/).

## Usage

\`\`\`powershell
scoop bucket add ${ORG} https://github.com/${SCOOP_REPO}
scoop install ai-agent
\`\`\`

## Updating

When a new version is released:

1. Download release tarball:
   \`\`\`powershell
   Invoke-WebRequest -Uri "https://github.com/${SOURCE_REPO}/archive/refs/tags/vX.Y.Z.tar.gz" -OutFile "ai-agent.tar.gz"
   \`\`\`

2. Compute sha256:
   \`\`\`powershell
   (Get-FileHash -Algorithm SHA256 "ai-agent.tar.gz").Hash
   \`\`\`

3. Update \`bucket/ai-agent.json\` with new version + sha256

4. Commit + push
`;
  writeFileSync(join(dir, 'README.md'), readme);

  run(`cd ${dir} && git config user.name "github-actions[bot]" && git config user.email "github-actions[bot]@users.noreply.github.com"`);
  run(`cd ${dir} && git add .`);
  run(`cd ${dir} && git commit -m "feat: initial scoop bucket for ai-agent"`);
  run(`cd ${dir} && git push`);
  console.log('✅ scoop-bucket initialized');
}

// ─────────────── 2. Homebrew tap ───────────────
async function setupBrew() {
  console.log('\n🍺 Setting up homebrew-tap...');
  const dir = join(TMP, 'homebrew-tap');
  run(`git clone ${authUrl(BREW_REPO)} ${dir}`);

  // Formula/ai-agent.rb
  const formula = readSourceFile('.github/homebrew-tap/ai-agent.rb');
  mkdirSync(join(dir, 'Formula'), { recursive: true });
  writeFileSync(join(dir, 'Formula/ai-agent.rb'), formula);

  // README.md
  const readme = `# Homebrew Tap

Formulas for [Homebrew](https://brew.sh/).

## Usage

\`\`\`bash
brew tap ${ORG}/tap
brew install ai-agent
\`\`\`

## Updating

When a new version is released:

\`\`\`bash
# Compute sha256 of the new tarball
curl -L -o /tmp/ai-agent.tar.gz "https://github.com/${SOURCE_REPO}/archive/refs/tags/vX.Y.Z.tar.gz"
shasum -a 256 /tmp/ai-agent.tar.gz

# Update Formula/ai-agent.rb
# - url: bump version
# - sha256: replace placeholder
# Commit + push
\`\`\`
`;
  writeFileSync(join(dir, 'README.md'), readme);

  run(`cd ${dir} && git config user.name "github-actions[bot]" && git config user.email "github-actions[bot]@users.noreply.github.com"`);
  run(`cd ${dir} && git add .`);
  run(`cd ${dir} && git commit -m "feat: initial homebrew tap with ai-agent formula"`);
  run(`cd ${dir} && git push`);
  console.log('✅ homebrew-tap initialized');
}

// ─────────────── Main ───────────────
async function main() {
  console.log('🚀 Creating package distribution repos...');
  console.log(`   Source: ${SOURCE_REPO}`);
  console.log(`   Scoop:  ${SCOOP_REPO}`);
  console.log(`   Brew:   ${BREW_REPO}`);
  console.log(`   Temp:   ${TMP}`);
  console.log('');

  const target = process.argv[2];
  if (target === 'scoop') {
    await setupScoop();
  } else if (target === 'brew') {
    await setupBrew();
  } else if (target === 'all' || !target) {
    await setupScoop();
    await setupBrew();
  } else {
    console.error(`Unknown target: ${target}. Use 'scoop', 'brew', or 'all'.`);
    process.exit(1);
  }

  console.log('\n🎉 Done!');
  console.log(`Temp directory: ${TMP} (cleanup manually)`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
