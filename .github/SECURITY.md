# Security Policy

## Supported Versions

当前维护的版本：

| Version | Supported          |
|---------|--------------------|
| main    | ✅ Active          |
| < main  | ❌ End-of-life     |

未在表中的 commit / tag 默认不接收安全更新。

## Reporting a Vulnerability

**请勿在公开 issue 报告安全漏洞**。

### 流程

1. **私有披露**：发邮件至 **colbert@example.com**（替换为项目所有者实际邮箱）
   - 主题：`[SECURITY] <简短描述>`
   - 正文：
     - 漏洞描述
     - 复现步骤（PoC）
     - 影响范围（哪个版本受影响）
     - 已知缓解措施（如有）
2. **确认收到**：48 小时内回复，分配 CVE / tracker ID
3. **协作修复**：保持私下沟通，72 小时内给出修复计划
4. **披露协调**：修复发布后协调披露时间（CVE / changelog）
5. **致谢**：如你愿意，会在 fix commit / advisory 中致谢

### 响应时间 SLA

| 严重程度 | 初次响应 | 修复目标 |
|---|---|---|
| Critical（RCE / auth bypass） | 24h | 7d |
| High（信息泄露 / 越权） | 48h | 30d |
| Medium（DoS / XSS） | 72h | 90d |
| Low（信息泄露 / 最佳实践） | 7d | best effort |

## 在哪报告

| 类型 | 渠道 |
|---|---|
| **安全漏洞** | 邮件：colbert@example.com（私密） |
| 一般 bug | [GitHub Issues](https://github.com/colbertlee/langChain_langGraph/issues) |
| 功能请求 | [GitHub Discussions](https://github.com/colbertlee/langChain_langGraph/discussions) |

## 已知安全机制

### 后端

- FastAPI `CORSMiddleware` 限定 origin（配置在 `ai_agent/web_ui.py`）
- `/api/upload` 文件大小限制（默认 10MB）+ MIME 白名单
- `/api/files/{name}` 严格路径校验防穿越
- 环境变量读 LLM API key（不入 git）
- LangChain 工具调用 sandbox（`ai_agent/sandbox.py`）

### 前端

- React 19 严格模式（dev）
- 内置 SRI 校验（npm 包 hash）
- localStorage 数据隔离（chat session 不含 LLM key）
- 视觉回归 baseline 不上传 secret（仅 PNG）

### CI/CD

- Dependabot 自动扫描 npm + pip
- `security` job：`npm audit --omit=dev`
- `security` job：`pip-audit`（后端）
- 失败条件：critical / high 漏洞 → PR blocked
- Slack / Discord webhook 通知

### Git 配置

- Branch protection 强制 PR review + status check 通过
- `enforce_admins: true` —— 管理员也不能绕过
- 禁止 force push / 禁止删 main 分支

## 安全更新订阅

- 仓库 → **Watch** → **Custom** → ✅ **Security alerts**
- GitHub 会在有 CVE 影响你的 deps 时自动发邮件

## 公开致谢

修复后的安全公告会发布在：

- GitHub Security Advisories（私密 → 修复后公开）
- CHANGELOG.md
- （可选）SECURITY.md "History" 节追加

## 参考

- [GitHub Security Advisories 文档](https://docs.github.com/en/code-security/security-advisories/working-with-repository-security-advisories/about-repository-security-advisories)
- [Coordinated Vulnerability Disclosure](https://cheatsheetseries.owasp.org/cheatsheets/Vulnerability_Disclosure_Cheat_Sheet.html)
- [CVE 申请流程](https://www.cve.org/)