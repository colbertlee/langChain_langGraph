# GitHub Container Registry (GHCR) 启用指南

docker-ci.yml 自动 push 镜像到 GHCR，需要一次性配置 visibility。

## 一次性配置（5 分钟）

### 1. 触发第一次 push

push 到 main 后，docker-ci.yml 自动：

1. 构建 Docker 镜像（buildx cache）
2. 启动容器冒烟测试
3. push 到 `ghcr.io/<owner>/ai-agent-console:latest` + `:${{ sha }}`

### 2. 默认 visibility 是 Private

GHCR 默认把新 package 设为 **Private**（仅 repo 成员可见）。
要公开（让其他用户 `docker pull`），需要手动改。

#### 方式 A：GitHub 网页（推荐）

1. 打开 GitHub 仓库 → 顶部 **Packages** 链接
   - 或直接访问 `https://github.com/<owner>?tab=packages`
2. 点击 **ai-agent-console** package
3. 右侧 **Package settings**
4. 滚动到底部 **Danger Zone** → **Change package visibility**
5. 选 **Public** → 输入 package 名确认
6. 确认

#### 方式 B：gh CLI

```bash
# 安装：winget install GitHub.cli
gh auth login

# 修改 visibility 为 public
gh api \
  --method PATCH \
  -H "Accept: application/vnd.github+json" \
  /user/packages/container/ai-agent-console \
  --field visibility=public
```

### 3. 验证公开可用

```bash
# 不需要登录即可 pull
docker pull ghcr.io/<owner>/ai-agent-console:latest

# 启动
docker run -d --rm \
  -p 8000:8000 \
  -e OPENAI_API_KEY=sk-xxx \
  ghcr.io/<owner>/ai-agent-console:latest

# 访问 http://localhost:8000/
```

### 4. README 加 pull badge（可选）

```markdown
[![Docker Image](https://ghcr.io/<owner>/ai-agent-console/badge)](https://ghcr.io/<owner>/ai-agent-console)
```

## 自动管理

docker-ci.yml 已配：

| 触发器 | 行为 |
|---|---|
| push 到 main | build + test + push + 记录 size |
| PR | build + test（不 push） |
| 手动 workflow_dispatch | build + test |

### 镜像 tag 规则

每次 push main 打两个 tag：

- `latest` —— 总是指向最新 main
- `${{ github.sha }}` —— 不可变，可追溯

### 镜像大小跟踪

`.docker-history/sizes.csv` 记录每次的尺寸（commit 到 main）。

## 故障排查

| 现象 | 排查 |
|---|---|
| `failed to authorize: failed to fetch oauth token` | GITHUB_TOKEN 权限不够；workflow 加 `packages: write` |
| `denied: installation not allowed to write` | 仓库设置 → Actions → Workflow permissions → 选 "Read and write permissions" |
| 镜像没出现在 Packages | 检查 Actions 日志；确认 push-ghcr job 成功 |
| pull 时 `unauthorized` | visibility 仍是 Private；按上面方式改 |
| 镜像太大 > 800MB | 检查 requirements.txt 是否装了大包；考虑 `pip install --no-deps` 后手动装 |

## 配置 GITHUB_TOKEN 权限（一次）

让 GitHub Actions 默认 token 能写 Packages：

1. 仓库 → **Settings** → **Actions** → **General**
2. **Workflow permissions**
3. 选 **Read and write permissions**
4. ✅ Allow GitHub Actions to create and approve pull requests（可选）
5. **Save**

> ⚠️ 公共仓库默认是 read-only；私有仓库需要手动改。

## 拉取镜像到本地（用户）

```bash
# 默认 public
docker pull ghcr.io/colbertlee/ai-agent-console:latest

# 私有：先登录
echo $GITHUB_TOKEN | docker login ghcr.io -u <username> --password-stdin
docker pull ghcr.io/colbertlee/ai-agent-console:latest
```

## 相关

- [Dockerfile](../../Dockerfile)
- [docker-compose.yml](../../docker-compose.yml)
- [docker-ci.yml](.github/workflows/docker-ci.yml)
