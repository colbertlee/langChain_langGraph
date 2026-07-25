# 包发布指南（PyPI + Scoop + Homebrew + Docker GHCR + npm）

发布一个版本需要更新 **5 个发布渠道**。本指南按顺序说明。

## 0. 前置准备

### 一次性：注册账号

| 渠道 | 注册 | 备注 |
|---|---|---|
| **PyPI** | https://pypi.org/account/register/ | 主 Python 包索引 |
| **TestPyPI** | https://test.pypi.org/account/register/ | 预发布测试（推荐） |
| **GitHub Container Registry** | 用 GitHub 账号自动 | docker-ci.yml 已配 |
| **Scoop** | 用 GitHub 账号 | 需独立 bucket repo（用户操作） |
| **Homebrew** | 用 GitHub 账号 | 需独立 tap repo（用户操作） |
| **npm** | https://www.npmjs.com/signup | 暂不需要（前端从 GitHub Pages 装） |

### 一次性：配置 PyPI token

```bash
# 创建 token：https://pypi.org/manage/account/token/
# scope 选 "Entire account"（首次），后续可改 per-project
# 复制 pypi-AgEIcHlwaS... 这串

# 用 API token 登录
py -3.11 -m pip install twine
py -3.11 -m twine login
# Username: __token__
# Password: pypi-AgEIcHlwaS...
```

### 一次性：准备 Scoop bucket 仓库

```bash
# 在 GitHub 上创建新 repo（Public）：
#   github.com/colbertlee/scoop-bucket

mkdir scoop-bucket && cd scoop-bucket
git init
mkdir -p bucket
# 复制 .github/scoop/ai-agent.json → bucket/ai-agent.json
git add . && git commit -m "Initial Scoop bucket"
git remote add origin git@github.com:colbertlee/scoop-bucket.git
git push -u origin main
```

### 一次性：准备 Homebrew tap 仓库

```bash
# 创建 repo: github.com/colbertlee/homebrew-tap
# 复制 .github/homebrew-tap/ai-agent.rb → Formula/ai-agent.rb
mkdir homebrew-tap && cd homebrew-tap
git init && mkdir Formula
cp ../langChain_langGraph/web_console/.github/homebrew-tap/ai-agent.rb Formula/ai-agent.rb
git add . && git commit -m "Initial tap"
git remote add origin git@github.com:colbertlee/homebrew-tap.git
git push -u origin main
```

---

## 1. 版本号管理（bumpversion）

```bash
cd ai_agent

# 装 bumpversion（一次性）
pip install bumpversion

# 试运行
bumpversion --dry-run --verbose patch
# 应输出：
#   -> 0.1.0  # current version
#   -> 0.1.1  # new version

# 真实 bump（自动 commit + tag）
bumpversion patch    # 0.1.0 → 0.1.1
bumpversion minor    # 0.1.1 → 0.2.0
bumpversion major    # 0.2.0 → 1.0.0

# 这会：
#   1. 改 pyproject.toml version
#   2. 在 README.md 加版本号
#   3. 在 CHANGELOG.md 加 placeholder section
#   4. git commit -am "chore(release): bump version v0.1.1"
#   5. git tag v0.1.1
```

## 2. 推送触发完整 CI

```bash
git push origin main --follow-tags
```

GitHub Actions 自动：
- ✅ 跑 backend + frontend 测试
- ✅ Build Docker 镜像
- ✅ 测 4 个关键端点
- ✅ Push 到 GHCR: `ghcr.io/colbertlee/ai-agent-console:v0.1.1` + `:latest`
- ✅ Update README badges

## 3. 发布到 PyPI

### 方式 A：手动（用户首次发布 / 测试发布）

```bash
cd ai_agent

# 1. 清理旧 build
rm -rf build/ dist/ *.egg-info/

# 2. 打包（sdist + wheel）
py -3.11 -m pip install --upgrade build twine
py -3.11 -m build

# 输出：
#   dist/ai_agent-0.1.1.tar.gz
#   dist/ai_agent-0.1.1-py3-none-any.whl

# 3. 验证包结构
py -3.11 -m twine check dist/*

# 4. 先在 TestPyPI 测
py -3.11 -m twine upload --repository testpypi dist/*
# 在 https://test.pypi.org/project/ai-agent/ 验证可装

# 5. 真发布到 PyPI
py -3.11 -m twine upload dist/*
```

完成后用户：

```bash
pip install ai-agent
ai-agent    # 启动 Web 服务
```

### 方式 B：CI 自动（推荐）— 通过 tag 触发

`release.yml` workflow 在 push tag `v*.*.*` 时自动：

1. 跑测试（sanity check）
2. 构建 sdist + wheel
3. 验证 twine
4. **发布到 PyPI**（用 `pypa/gh-action-pypi-publish@v1.12.4`）
5. 同时 push Docker 到 GHCR
6. 创建 GitHub Release
7. 通知 Slack/Discord

**配置 PyPI trusted publishing**（推荐，免 secret）：

1. PyPI 项目 → **Publishing** → **Add a new pending publisher**
2. 填：
   - Owner: `colbertlee`
   - Repository: `langChain_langGraph`
   - Workflow filename: `release.yml`
   - Environment name: `pypi`（已在 workflow 配）
3. 在 GitHub repo → Settings → **Environments** → 创建 `pypi` environment
   - 加 protection rule（required reviewers 等）

**或者用传统 API token**：

1. https://pypi.org/manage/account/token/ 创建 token
2. GitHub repo → Settings → Secrets → `PYPI_API_TOKEN` = `pypi-AgEIcHlwaS...`
3. `release.yml` 会自动用 `PYPI_API_TOKEN` 环境变量

### 故障排查

| 现象 | 排查 |
|---|---|
| `403 Forbidden` | token 没权限；用 entire-account token |
| `400 File already exists` | 已发过这个版本；bump 重新发 |
| `twine check` 报错 | `pyproject.toml` description 格式问题 |
| `metadata out of date` | `[project]` 字段缺 `description` 或 `readme` |
| `invalid classifier` | classifiers 列表某项拼错 |
| trusted publishing 失败 | 环境名必须完全匹配 |

## 4. 发布 Docker 镜像

docker-ci.yml 已自动 push 到 GHCR。如果失败手动跑：

```bash
# 计算 GHCR tag
VERSION=$(grep '^version = ' ai_agent/pyproject.toml | cut -d'"' -f2)

# 本地构建 + tag
docker build -f web_console/Dockerfile -t ai-agent-console:$VERSION .

# 登录 GHCR
echo $GITHUB_TOKEN | docker login ghcr.io -u colbertlee --password-stdin

# 推送
docker tag ai-agent-console:$VERSION ghcr.io/colbertlee/ai-agent-console:$VERSION
docker tag ai-agent-console:$VERSION ghcr.io/colbertlee/ai-agent-console:latest
docker push ghcr.io/colbertlee/ai-agent-console:$VERSION
docker push ghcr.io/colbertlee/ai-agent-console:latest
```

完成后用户：

```bash
docker pull ghcr.io/colbertlee/ai-agent-console:v0.1.1
docker run -d -p 8000:8000 -e OPENAI_API_KEY=sk-xxx ghcr.io/colbertlee/ai-agent-console:v0.1.1
```

## 5. 发布到 Scoop

需要更新 sha256：

```bash
# 下载 release tarball
TARBALL="https://github.com/colbertlee/langChain_langGraph/archive/refs/tags/v0.1.1.tar.gz"
curl -L -o /tmp/ai-agent-v0.1.1.tar.gz $TARBALL

# 计算 sha256
SHA256=$(sha256sum /tmp/ai-agent-v0.1.1.tar.gz | cut -d' ' -f1)
echo $SHA256
# e.g. abc123...

# 替换 manifest 中的 hash
sed -i "s/REPLACE_WITH_SHA256_OF_TARBALL/$SHA256/" .github/scoop/ai-agent.json
sed -i "s/0.1.0/0.1.1/" .github/scoop/ai-agent.json

# 提交到 scoop-bucket repo
cd ../scoop-bucket
cp ../langChain_langGraph/web_console/.github/scoop/ai-agent.json bucket/ai-agent.json
git add bucket/ai-agent.json
git commit -m "ai-agent: update to v0.1.1"
git push
```

完成后用户：

```powershell
# Windows PowerShell
scoop bucket add colbertlee https://github.com/colbertlee/scoop-bucket
scoop install ai-agent
ai-agent
```

## 6. 发布到 Homebrew

类似 Scoop：

```bash
# 下载 + sha256
curl -L -o /tmp/ai-agent-v0.1.1.tar.gz $TARBALL
SHA256=$(shasum -a 256 /tmp/ai-agent-v0.1.1.tar.gz | cut -d' ' -f1)

# 替换 formula
cd ../homebrew-tap
sed -i "s/REPLACE_WITH_SHA256_OF_TARBALL/$SHA256/" Formula/ai-agent.rb
sed -i "s/v0.1.0/v0.1.1/" Formula/ai-agent.rb
git add Formula/ai-agent.rb
git commit -m "ai-agent: update to v0.1.1"
git push
```

用户：

```bash
brew update
brew install colbertlee/tap/ai-agent
# 或
brew upgrade ai-agent
```

## 7. 自动发布（CI）

把上述流程封装成 workflow：[release.yml](release.yml)

```bash
# 触发：打 tag 后自动跑
git tag v0.1.1
git push --tags
```

会自动：
- Build + publish 到 PyPI（如果设了 PYPI_API_TOKEN secret）
- Build + push 到 GHCR（docker-ci.yml 已配）
- Update Scoop + Brew（可选，PR 形式）

---

## 故障排查

| 现象 | 排查 |
|---|---|
| `twine upload` 401 | 检查 token；用 `__token__` 作 username |
| `twine upload` 403 | token scope 不够；需 `Entire account` 或 per-project |
| Docker build 太大 > 800MB | 检查 requirements.txt；用 `pip install --no-cache-dir` |
| `bumpversion` 不改文件 | 检查 file pattern 是否匹配 |
| Scoop manifest install 失败 | 检查 hash 是否正确 |
| brew install 失败 | 跑 `brew audit --new ai-agent` 诊断 |

## 总结：发布新版本 checklist

- [ ] `bumpversion patch` (或 minor/major)
- [ ] 手动填写 CHANGELOG.md
- [ ] `git push --follow-tags`
- [ ] 等 CI 全绿
- [ ] `py -3.11 -m build && py -3.11 -m twine upload dist/*`
- [ ] `git tag v0.1.1 && git push --tags` 触发 release
- [ ] 计算 sha256 → 更新 Scoop + Brew 仓库
- [ ] 验证 PyPI / Docker / Scoop / Brew 都可装
- [ ] 发 GitHub Release notes（release-drafter 自动）
