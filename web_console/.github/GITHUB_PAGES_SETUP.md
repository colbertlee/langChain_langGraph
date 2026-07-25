# GitHub Pages 启用指南

deploy.yml 使用 `actions/deploy-pages@v4`，**需要先在 GitHub 仓库启用 Pages**。

## 一次性配置（5 步）

### 1. 打开仓库设置

GitHub 仓库 → **Settings** → 左侧 **Pages**

### 2. Source 选 "GitHub Actions"

在 **Build and deployment** → **Source**：
- 不要选 "Deploy from a branch"
- 选 **"GitHub Actions"**（这是 2024 年后的新选项）

### 3. 第一次 push 触发

push 到 main 后，Actions 会自动跑 `Deploy` workflow。
如果 build 通过，会在 `deploy` job 输出 Pages URL：
```
https://<owner>.github.io/<repo>/
```

### 4. （可选）自定义域名

Settings → Pages → **Custom domain**：
- 输入 `app.example.com`
- 在 DNS 添加 CNAME 记录指向 `<owner>.github.io`
- 勾选 **Enforce HTTPS**

### 5. （可选）环境保护

Settings → Environments → **github-pages** → 设置 protection rules：
- Required reviewers：merge 必须被审
- Wait timer：5 分钟后自动 deploy

## 验证部署成功

部署完成后看 GitHub：

```
Settings → Pages
   Your site is live at https://<owner>.github.io/<repo>/
```

访问此 URL 应看到 AI Agent Console 首页（主题色 #0A0A0B）。

## ⚠️ 私有仓库 / GitHub Free Plan 限制

| 仓库类型 | Pages 是否公开 | 备注 |
|---|---|---|
| Public repo | ✅ 公开 | GitHub Free OK |
| Private repo + GitHub Free | ❌ 不可用 | 需升级 GitHub Pro/Team |
| Private repo + GitHub Pro | ✅ 公开 | |

如果 Pages 不能启用，可改用 deploy.yml 中的 **S3 + CloudFront** 选项。

## S3 + CloudFront 部署（替代方案）

### 配置 GitHub Secrets / Variables

| 类型 | 名称 | 值 |
|---|---|---|
| Secret | `AWS_ACCESS_KEY_ID` | IAM user key |
| Secret | `AWS_SECRET_ACCESS_KEY` | IAM user secret |
| Secret | `AWS_REGION` | 例如 `us-east-1` |
| Variable | `AWS_S3_BUCKET` | 例如 `my-agent-console` |
| Variable | `CLOUDFRONT_DISTRIBUTION_ID` | 例如 `E1XXXXXXXXXX` |

### IAM user 最小权限

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::my-agent-console",
        "arn:aws:s3:::my-agent-console/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "cloudfront:CreateInvalidation",
      "Resource": "arn:aws:cloudfront::*:distribution/E1XXXXXXXXXX"
    }
  ]
}
```

### S3 bucket 配置

- Static website hosting: Enable
- Index document: `index.html`
- Error document: `404.html`
- Bucket policy: 允许 public read（仅 bucket 内的 object）

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "PublicReadGetObject",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::my-agent-console/*"
  }]
}
```

### CloudFront 配置

- Origin: S3 bucket website endpoint（不是 REST endpoint）
- Default root object: `index.html`
- Error pages:
  - 403 → `/index.html` (200)
  - 404 → `/index.html` (200)
- Cache policy: CachingOptimized

## 故障排查

| 现象 | 排查 |
|---|---|
| Pages 显示 404 | 等 1-2 分钟刷新；或 `gh workflow run deploy.yml` 重跑 |
| CSS/JS 404 | 检查 dist/assets/ 是否完整上传；可能 cache miss |
| SPA 路由刷新 404 | CloudFront / 404.html fallback 没配；Pages 端 OK（自动 404 → index.html）|
| CORS 错误 | 后端 web_ui.py 已加 CORSMiddleware；检查 /api 代理配置 |
