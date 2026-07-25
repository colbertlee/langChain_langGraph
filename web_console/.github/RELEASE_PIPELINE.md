# Release Pipeline 完整指南

本文档覆盖本项目的完整发布流水线：**从开发者提交 commit → 用户拿到带 PEP 740 provenance 的 PyPI 包**。

---

## 1. 全景图

```
┌─────────────────────────────────────────────────────────────────────┐
│  开发者按 Conventional Commits 提交（feat/fix/perf/...）               │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ PR merge → main
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  release-please.yml (manifest 模式)                                  │
│  ├─ 解析 conventional commits                                         │
│  ├─ 计算 next version (feat → minor, fix → patch, ! → major)          │
│  ├─ 自动开（或更新）"Release PR"                                     │
│  └─ PR 内容：pyproject.toml bump + ai_agent/CHANGELOG.md 更新          │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ 维护者 review + merge Release PR
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  release-please.yml 自动执行：                                       │
│  ├─ commit "chore(main): release X.Y.Z"                              │
│  ├─ 创建 git tag vX.Y.Z                                              │
│  └─ 创建 GitHub Release (published, 非 draft)                         │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ git tag push 触发
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  release.yml（6+1 jobs）                                              │
│  1. build              → sdist + wheel + twine check                  │
│  2. publish-pypi       → PyPI (OIDC + PEP 740 provenance)             │
│  3. publish-testpypi   → TestPyPI（手动触发时）                       │
│  4. attest-verify      → 拉 PyPI JSON API + 校验 PEP 740 attestation │
│  5. publish-docker     → GHCR (ghcr.io/.../ai-agent-console:vX.Y.Z)  │
│  6. github-release     → softprops publish GitHub Release            │
│  7. update-package-manifests → 自动开 Scoop/Brew PR                   │
│  8. notify             → Slack + Discord + Step Summary               │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ 用户
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  pip install ai-agent                                                │
│  - 包名：ai-agent                                                     │
│  - PyPI 页：https://pypi.org/project/ai-agent/  (有 "Verified" 标签)   │
│  - provenance attestation：包含 GitHub repo + commit SHA + workflow    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 触发方式

### 2.1 自动（推荐）：通过 Release PR

1. 开发者按 [Conventional Commits](https://www.conventionalcommits.org/) 提交：
   ```bash
   git commit -m "feat: 添加基金净值查询工具"
   git commit -m "fix: 修复 context_db.py find_or_create 边界 case"
   git commit -m "feat!: 重写 fallback chain（BREAKING CHANGE）"
   ```

2. 合并 PR → main → `release-please.yml` 自动开 "Release PR"。

3. 维护者 review + merge Release PR → 自动：
   - `pyproject.toml` 的 `version` 更新
   - `ai_agent/CHANGELOG.md` 追加新 section
   - 创建 git tag `vX.Y.Z`
   - 创建 GitHub Release
   - 触发 `release.yml`（6+1 jobs）

### 2.2 手动：直接打 tag

```bash
git tag v0.2.0
git push origin v0.2.0
# → release.yml 直接跑
```

适用于：
- 紧急修复（不想等 release-please）
- 一次性版本（如 1.0.0 里程碑）

### 2.3 手动：workflow_dispatch

`Actions` → `Release` → `Run workflow`：
- 不需要 tag
- 可在测试 PyPI 验证
- 跳过部分需要 tag 的 jobs

---

## 3. PEP 740 Provenance Attestation

### 3.1 什么是 PEP 740

PEP 740 是 PyPI 的供应链安全标准（2024 年正式上线）：
- 包发布时附带 **provenance attestation**（生成来源证明）
- 包含 4 项信息：
  1. **构建来源**：GitHub repo URL + commit SHA
  2. **构建方式**：具体的 workflow 文件名 + ref
  3. **构建者身份**：GitHub Actions OIDC token（不可伪造）
  4. **构建时间**：ISO 8601 UTC timestamp
- 格式：[Sigstore](https://www.sigstore.dev/) 的 in-toto attestation（公开验证标准）
- 用户在 PyPI 项目页能看到 "Verified" 标签

### 3.2 本项目的 attestation 配置

[`release.yml`](workflows/release.yml) 的 `publish-pypi` job：

```yaml
- uses: pypa/gh-action-pypi-publish@v1.12.4
  with:
    packages-dir: dist/
    # OIDC trusted publishing（不需要 PYPI_API_TOKEN）
  permissions:
    id-token: write
    attestations: write
```

PyPI 自动生成 attestation 并附在每个 wheel/sdist 上。

### 3.3 验证 attestation

#### 3.3.1 通过 PyPI Web UI

1. 打开 https://pypi.org/project/ai-agent/
2. 选具体版本（如 0.2.0）
3. 下载文件
4. 看 "View Attestations" 链接

#### 3.3.2 通过 sigstore CLI（本地验证）

```bash
# 1. 装 sigstore
pip install sigstore

# 2. 下载 wheel
pip download ai-agent==0.2.0 --no-deps --dest dist/

# 3. 验证 attestation
python -m sigstore verify identity \
  --cert-identity 'https://github.com/colbertlee/langChain_langGraph/.github/workflows/release.yml@refs/tags/v0.2.0' \
  --cert-oidc-issuer 'https://token.actions.githubusercontent.com' \
  dist/ai_agent-0.2.0-py3-none-any.whl
```

预期输出：
```
Verifying identity for dist/ai_agent-0.2.0-py3-none-any.whl...
Identity verified: certificate is signed by GitHub Actions OIDC
✅ Successfully verified ai_agent-0.2.0-py3-none-any.whl
```

#### 3.3.3 通过 CI 自动验证

`release.yml` 的 `attest-verify` job 会：
1. 从 PyPI JSON API 拉每个文件的 attestation
2. 校验 attestation 存在
3. （可选）下载 wheel + 跑 `sigstore verify identity`
4. 输出 Step Summary

详见 [workflows/release.yml §attest-verify](workflows/release.yml)。

---

## 4. 三层安全扫描

[`backend-ci.yml`](workflows/backend-ci.yml) 的 `security` job 跑三层扫描：

| Layer | 工具 | 数据库 | 覆盖范围 |
|---|---|---|---|
| 1 | `pip-audit` | PyPI Advisory | Python prod deps |
| 2 | `OSV-Scanner` | Google OSV（跨语言聚合） | 所有 lockfile + 传递依赖 |
| 3 | GitHub Advisory | 通过 OSV 间接覆盖 | 同 layer 2 |

**为什么需要三层？**
- `pip-audit`：PyPI 官方，但只覆盖 Python ecosystem
- `OSV-Scanner`：跨语言，自动生成 SARIF 上传到 GitHub Security Tab
- GitHub Advisory：OSV 已经包含（OSV 是聚合源），不必重复查

触发漏洞时自动创建 issue：见 [`.github/dependabot.yml`](dependabot.yml)。

### 4.1 本地运行

```bash
# pip-audit
pip install pip-audit
cd ai_agent
pip-audit -r requirements.txt

# OSV-Scanner
# 安装：https://google.github.io/osv-scanner/install/
osv-scanner --lockfile=requirements.txt --recursive
```

### 4.2 失败策略

- **critical / high**：CI fail（PR 不可 merge）
- **moderate**：仅警告（不阻断），Dependabot 自动开 issue
- **low / info**：仅上传 artifact，不阻断

---

## 5. 完整文件清单

### 5.1 Workflows

| 文件 | 触发 | 用途 |
|---|---|---|
| [ci.yml](workflows/ci.yml) | push/PR 到 main | 前端 CI（vitest + e2e + build） |
| [backend-ci.yml](workflows/backend-ci.yml) | ai_agent/** 变更 | 后端 CI（pytest + 3 层安全扫描） |
| [release-please.yml](workflows/release-please.yml) | push 到 main | 自动开 Release PR |
| [release-drafter.yml](workflows/release-drafter.yml) | push/PR | 维护 Draft Release（备用） |
| [release.yml](workflows/release.yml) | push tag `v*.*.*` | 完整发布（PyPI/Docker/GH/Notify） |
| [docker-ci.yml](workflows/docker-ci.yml) | Dockerfile 变更 | Docker 镜像 CI |
| [weekly-upgrades.yml](workflows/weekly-upgrades.yml) | 每周一次 | 依赖升级检查 |
| [deploy.yml](workflows/deploy.yml) | 手动 | 部署到生产 |

### 5.2 配置

| 文件 | 用途 |
|---|---|
| [.github/release-please-config.json](release-please-config.json) | release-please manifest 配置 |
| [.release-please-manifest.json](.release-please-manifest.json) | release-please 当前版本跟踪 |
| [.github/release-drafter.yml](release-drafter.yml) | release-drafter 分类规则 |
| [.github/dependabot.yml](dependabot.yml) | Dependabot 自动 PR |
| [.github/scoop/ai-agent.json](scoop/ai-agent.json) | Scoop manifest 模板 |
| [.github/homebrew-tap/ai-agent.rb](homebrew-tap/ai-agent.rb) | Homebrew formula 模板 |

### 5.3 文档

| 文件 | 用途 |
|---|---|
| [RELEASE_PIPELINE.md](RELEASE_PIPELINE.md) | 本文档 |
| [PYPI_PUBLISHING.md](PYPI_PUBLISHING.md) | PyPI Trusted Publishing 配置 |
| [GHCR_SETUP.md](GHCR_SETUP.md) | GHCR 镜像配置 |
| [PACKAGE_DISTRIBUTION.md](PACKAGE_DISTRIBUTION.md) | 全平台分发总览 |
| [SCOOP_BREW_TAP_SETUP.md](SCOOP_BREW_TAP_SETUP.md) | Scoop/Brew tap 配置 |

---

## 6. 首次发布 Checklist

### 6.1 一次性配置

- [ ] **PyPI 项目注册**：https://pypi.org/account/register/
- [ ] **PyPI 项目创建**（首次）：通过 `twine upload` 推到 `ai-agent`
- [ ] **PyPI Trusted Publishing**：项目 → Publishing → Add pending publisher
  - Owner: `colbertlee`
  - Repo: `langChain_langGraph`
  - Workflow: `release.yml`
  - Environment: `pypi`
- [ ] **GitHub Environment `pypi`**：仓库 → Settings → Environments
- [ ] **(可选) TestPyPI Trusted Publishing**：同上
- [ ] **(可选) Slack webhook** + GitHub Secret `SLACK_WEBHOOK_URL`
- [ ] **(可选) Discord webhook** + GitHub Secret `DISCORD_WEBHOOK_URL`
- [ ] **(可选) PAT_BOT** + GitHub Secret `PAT_BOT`（开 Scoop/Brew PR 用）

### 6.2 每次发版

- [ ] 所有 PR 都用 conventional commits 提交
- [ ] merge 后看 `Actions` → `Release Please` → 是否开了 Release PR
- [ ] review Release PR（CHANGELOG 内容是否准确）
- [ ] merge Release PR → 触发 `release.yml`
- [ ] 6+1 jobs 全绿：
  - [ ] build ✓
  - [ ] publish-pypi ✓
  - [ ] publish-testpypi ✓（手动触发时）
  - [ ] attest-verify ✓
  - [ ] publish-docker ✓
  - [ ] github-release ✓
  - [ ] update-package-manifests ✓（如果配了 PAT_BOT）
  - [ ] notify ✓
- [ ] 验证 https://pypi.org/project/ai-agent/X.Y.Z/ 有 "Verified" 标签
- [ ] （可选）验证 Scoop/Brew PR 被自动开

---

## 7. 故障排查

| 现象 | 原因 | 修复 |
|---|---|---|
| `release-please` 没开 PR | commit 不是 conventional 格式 | 改 commit message |
| PyPI 报 403 | Trusted Publishing 没配或 Environment 名错 | 检查 PyPI 项目 + GitHub Environment |
| `attest-verify` 失败 | OIDC token 过期或 attestation 没生成 | 重跑 release.yml；检查 `attestations: write` 权限 |
| Docker push 失败 | GHCR 没登录或权限不足 | 检查 `packages: write` |
| Scoop/Brew PR 没开 | 没配 PAT_BOT | 加 GitHub Secret `PAT_BOT` |
| Slack/Discord 通知没收到 | webhook URL 错 | 重新配置 secret |
| OSV-Scanner 报 critical 漏洞 | 依赖有 CVE | `pip install -U <pkg>` 后提交 |
| `pip-audit` 报高危 | PyPI 有 advisory | 同上 |

---

## 8. 参考链接

- PEP 740：https://peps.python.org/pep-0740/
- PyPI Trusted Publishing：https://docs.pypi.org/trusted-publishers/
- Sigstore：https://www.sigstore.dev/
- release-please：https://github.com/googleapis/release-please
- OSV-Scanner：https://google.github.io/osv-scanner/
- pip-audit：https://pypi.org/project/pip-audit/
- Conventional Commits：https://www.conventionalcommits.org/
- in-toto attestation：https://github.com/in-toto/attestation