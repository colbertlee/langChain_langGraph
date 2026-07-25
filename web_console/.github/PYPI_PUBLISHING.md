# PyPI 发布完整指南

把 AI Agent 包发到 PyPI 两种方式：手动（首次推荐）+ Trusted Publishing（CI 推荐）。

## 方式 A：手动首次发布（建议先用这个）

### 1. 注册账号

- 主 PyPI：https://pypi.org/account/register/
- TestPyPI：https://test.pypi.org/account/register/（强烈推荐，先在 test 上验证）

### 2. 创建 API Token

- 登录 PyPI → Account Settings → API tokens
- **Add API token**
  - Token name: `ai-agent-local-dev`
  - Scope: **Entire account**（首次）
- **复制 token**（形如 `pypi-AgEIcHlwaS...`）—— 只显示一次！

### 3. 配置 token

```bash
# 一次性：装 twine
py -3.11 -m pip install --upgrade build twine

# 配 token（可选；不配的话 twine 会每次问）
py -3.11 -m twine configure
# PyPI username: __token__
# PyPI password: pypi-AgEIcHlwaS...

# 或：写入 ~/.pypirc（多账户）
cat > ~/.pypirc << 'EOF'
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-AgEIcHlwaS...

[testpypi]
username = __token__
password = pypi-AgEIcHlwaS...  # TestPyPI 的 token
repository = https://test.pypi.org/legacy/
EOF
```

### 4. 首次发到 TestPyPI

```bash
cd ai_agent

# 清理 + 构建
rm -rf build/ dist/ *.egg-info/
py -3.11 -m build

# 输出：
#   dist/ai_agent-0.1.0.tar.gz          # ~50KB
#   dist/ai_agent-0.1.0-py3-none-any.whl   # ~30KB

# 检查包结构（必须在上传前跑）
py -3.11 -m twine check dist/*

# 上传到 TestPyPI
py -3.11 -m twine upload --repository testpypi dist/*
# 输出：Uploading ai_agent-0.1.0... to https://test.pypi.org/legacy/ai_agent/0.1.0/
#       View at: https://test.pypi.org/project/ai-agent/0.1.0/
```

### 5. 在 TestPyPI 验证

```bash
# 在新虚拟环境装
py -3.11 -m venv /tmp/test-pypi-env
source /tmp/test-pypi-env/bin/activate    # bash
# 或：/tmp/test-pypi-env/Scripts/Activate.ps1   # PowerShell

pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ ai-agent
# 上面的 --extra-index-url 让 deps 仍从主 PyPI 拉

# 验证 CLI
ai-agent --help
ai-agent-test --help
ai-agent-lint --help
```

### 6. 发到主 PyPI

```bash
cd ai_agent
py -3.11 -m twine upload dist/*
# 输出：View at: https://pypi.org/project/ai-agent/
```

用户即可：

```bash
pip install ai-agent
ai-agent
```

### 7. 故障排查

| 现象 | 排查 |
|---|---|
| `403 Forbidden` | token 没权限；用 entire-account |
| `400 File already exists` | 版本已发；bump 后重发 |
| `twine check` 报 invalid | `pyproject.toml` description 含 README 引用问题 |
| `Metadata out of date` | `[project]` 缺 description 或 readme |
| `Invalid classifier` | classifier 拼错（参考 https://pypi.org/classifiers/） |
| 测试装时报 `No matching distribution` | 检查 `--index-url` 是否正确 |

---

## 方式 B：PyPI Trusted Publishing（CI 推荐，**免 secret**）

### 概念

传统方式需要把 PyPI token 存到 GitHub Secrets。**Trusted Publishing** 用 OIDC（OpenID Connect）：
- GitHub Actions 直接向 PyPI 出示自己的 OIDC token
- PyPI 验证 token 后允许 publish
- **不需要 token secret**（更安全）

### 1. 在 PyPI 配置 trusted publisher

登录 PyPI → 项目 `ai-agent` → **Publishing** → **Add a new pending publisher**：

| 字段 | 填 |
|---|---|
| Owner | `colbertlee` |
| Repository name | `langChain_langGraph` |
| Workflow filename | `release.yml` |
| Environment name | `pypi` |

保存。

### 2. 在 GitHub 创建 environment

仓库 → **Settings** → **Environments** → **New environment**

- Name: `pypi`
- 可选：加 protection rules（required reviewers / wait timer）
- 保存

### 3. release.yml 已配

[release.yml](../workflows/release.yml) `publish-pypi` job 用 `pypa/gh-action-pypi-publish@v1.12.4`：

```yaml
- name: Publish to PyPI
  uses: pypa/gh-action-pypi-publish@v1.12.4
  with:
    packages-dir: dist/
  # 不需要 password / token
```

`pypa/gh-action-pypi-publish` 默认用 `OIDC` 模式（如果环境配了 trusted publisher）。

### 4. 测试

```bash
# 打 tag → 自动 release
git tag v0.1.0
git push --tags

# 看 workflow：release.yml → publish-pypi
# 1. 验证 OIDC token
# 2. publish 到 PyPI
```

### 5. TestPyPI 也可以 trusted publishing

如要给 TestPyPI 也配 trusted publishing：

- 在 TestPyPI 上同样配置（同样的 owner / repo / workflow filename）
- release.yml `publish-testpypi` job：
  ```yaml
  - uses: pypa/gh-action-pypi-publish@v1.12.4
    with:
      packages-dir: dist/
      repository-url: https://test.pypi.org/legacy/
  ```

### 6. 故障排查

| 现象 | 排查 |
|---|---|
| OIDC 验证失败：invalid_token | GitHub 环境名要完全匹配 |
| `pypi-AgEIcHlwaS... invalid or expired` | 用错 token（应换成 OIDC） |
| Workflow 报 403 | Environment 没在 PyPI 项目中配 trusted publisher |
| `Invalid or non-existent authentication` | PyPI 项目的 owner 写错（应写用户名 `colbertlee` 不是 `colbert`） |
| CI 跑通但 PyPI 没新版本 | 检查 `twine check` 是否真失败 |

---

## 完整 checklist

### 首次发布

- [ ] 注册 PyPI 账号
- [ ] 注册 TestPyPI 账号
- [ ] 创建 API token（test + prod）
- [ ] 配 `~/.pypirc`
- [ ] `py -3.11 -m build`
- [ ] `py -3.11 -m twine check dist/*`
- [ ] `py -3.11 -m twine upload --repository testpypi dist/*`
- [ ] 新 venv 验证 TestPyPI 安装
- [ ] `py -3.11 -m twine upload dist/*`
- [ ] 验证 https://pypi.org/project/ai-agent/

### 配 Trusted Publishing（之后）

- [ ] PyPI 项目 Publishing → Add pending publisher（owner/repo/workflow/env）
- [ ] GitHub repo → Environments → 创建 `pypi`
- [ ] 打 tag `v0.1.0` → 推 → 等 release.yml
- [ ] 验证 PyPI 出现新版本
- [ ] （可选）GitHub Actions → Environment `pypi` → 设 required reviewers

### 升级发布

```bash
git tag v0.2.0
git push --tags
# release.yml 自动：
#   ✓ build
#   ✓ publish-pypi
#   ✓ publish-docker
#   ✓ github-release
#   ✓ notify
```

## 工具链速查

| 工具 | 用途 |
|---|---|
| `py -3.11 -m build` | 构建 sdist + wheel |
| `py -3.11 -m twine check` | 验证包 |
| `py -3.11 -m twine upload` | 上传 |
| `pip install --index-url https://test.pypi.org/simple/ ai-agent` | 装 TestPyPI |
| `pip install ai-agent` | 装正式版 |
| https://pypi.org/project/ai-agent/ | 项目页 |
| https://pypistats.org/packages/ai-agent | 下载统计 |
