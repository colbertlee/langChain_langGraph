# 贡献指南 · Contributing

感谢你考虑为本项目做贡献!无论是修一个 typo、写新工具、改后端架构,还是补一份文档,我们都欢迎。

---

## 1. 行为准则
请保持友善与专业。所有交流默认使用**中文**(issue / PR / 评论),英文 PR 也接受。
详见 [CODE_OF_CONDUCT.md](.github/CODE_OF_CONDUCT.md)(如未提供,请遵循 GitHub 社区准则)。

---

## 2. 我能贡献什么

| 类型 | 难度 | 适合人群 |
|---|---|---|
| 📖 文档错别字 / 翻译 / 示例补全 | ⭐ | 新人 |
| 🐛 Issue 复现 / Bug Report | ⭐ | 用户 |
| 🧪 补单元测试 / E2E | ⭐⭐ | 测试工程师 |
| 🛠 新增 LangChain / MCP 工具 | ⭐⭐ | 应用开发者 |
| 🧠 新增 Skill / Sub-Agent | ⭐⭐⭐ | Agent 业务方 |
| 🏗 后端架构(容错 / 记忆 / 多 Agent) | ⭐⭐⭐⭐ | 资深 |
| 🎨 前端组件 / 视觉 | ⭐⭐ | 前端 |
| 📦 打包脚本 / CI / 发版 | ⭐⭐⭐ | DevOps |

新手友好 issue 标签:`good first issue` `help wanted` `documentation`。

---

## 3. 开发环境

### 3.1 后端
- Python 3.11 或 3.12(推荐)
- `cd ai_agent && pip install -r requirements.txt -r requirements-dev.txt`
- 安装 pre-commit:`pip install pre-commit && pre-commit install`

### 3.2 前端
- Node 20 LTS
- `cd web_console && npm ci`

### 3.3 验证环境
```bash
# 后端测试 + lint
cd ai_agent
ai-agent-lint              # ruff check
ai-agent-format            # ruff format
ai-agent-test              # pytest + coverage

# 前端测试 + lint
cd web_console
npm run check              # tsc --noEmit
npm test
npm run lint:workflows     # actionlint

# 桌面包冒烟(可选)
cd ai_agent && ./test_all.ps1
```

---

## 4. 代码规范

### 4.1 Python
- 风格:`ruff`(配置见 `ai_agent/pyproject.toml` 的 `[tool.ruff]`)
- 类型注解:所有新函数必须有参数与返回类型
- docstring:Google 风格,至少一段说明 + Args / Returns
- 命名:模块 `snake_case`、类 `PascalCase`、常量 `UPPER_SNAKE`
- 导入顺序:stdlib → third-party → local(`ruff` 自动)

### 4.2 TypeScript
- `strict: true`(`tsconfig.json` 默认)
- 不使用 `any`(必要场景用 `unknown` + 窄化)
- React 组件用函数式 + Hooks
- 样式优先 Tailwind utility class

### 4.3 Commit 风格
采用 [Conventional Commits](https://www.conventionalcommits.org/),便于 release-please 自动生成 CHANGELOG。

```
<type>(<scope>): <subject>

<body>

<footer>
```

常见 type:
| type | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修 bug |
| `docs` | 文档 |
| `style` | 格式(不影响代码) |
| `refactor` | 重构 |
| `test` | 测试 |
| `chore` | 构建 / CI / 依赖 |
| `perf` | 性能 |

示例:
```
feat(tools): 新增 translate_doc 工具

- 支持英中互译
- 复用现有 cache

Closes #42
```

---

## 5. 提交流程

### 5.1 Fork & Branch
```bash
# 1. fork 仓库(在 GitHub 上点 Fork)
git clone https://github.com/<your-name>/langChain_langGraph.git
cd langChain_langGraph
git remote add upstream https://github.com/colbertlee/langChain_langGraph.git

# 2. 切特性分支(命名: <type>/<short-desc>)
git checkout -b feat/add-translate-tool
```

### 5.2 改动并验证
```bash
# 写代码 + 写测试
git add .
git commit -m "feat(tools): 新增 translate_doc 工具"

# 跑全套检查
cd ai_agent && ai-agent-lint && ai-agent-test
cd ../web_console && npm run check && npm test
```

### 5.3 推送 & PR
```bash
git push origin feat/add-translate-tool
```
然后到 GitHub 开 PR,**填写模板**(.github/PULL_REQUEST_TEMPLATE.md):
- 关联的 issue
- 改动摘要
- 测试结果截图 / 日志
- Breaking change?(如有,在 `<footer>` 写 `BREAKING CHANGE: ...`)

### 5.4 评审
- 至少 1 个 maintainer approve 才能 merge
- CI 必须绿(后端 pytest + 前端 vitest + e2e)
- CODEOWNERS 自动指派 reviewer,见 [.github/CODEOWNERS](.github/CODEOWNERS)

---

## 6. 测试要求

| 改动类型 | 必须测试 |
|---|---|
| 新增 / 修改 API 端点 | `tests/test_app_*.py` 加用例 |
| 新增 / 修改 LLM 工具 | `tests/test_tools.py` 或新文件 |
| 修 bug | 必须加回归测试,先复现后修 |
| 修改记忆 / 容错 / 安全 | 必须含边界用例(空 / 超长 / 注入) |
| 前端组件 | Vitest 单测 + Playwright 关键路径 |
| 文档 | 不需要测试,但 PR 标题写 `docs:` |

覆盖率目标:**后端 ≥ 80%**(CI 显示在 PR 评论)。

---

## 7. 新增 LLM Provider

如果你想接入新的 LLM 服务,标准流程:
1. 在 `ai_agent/config.py` 的 `MODEL_VERSIONS` 注册 Provider + 模型
2. 若使用 OpenAI 兼容协议,直接复用 `OpenAICompatibleClient`
3. 若协议特殊(如百度、讯飞),新建 `ai_agent/<provider>_client.py` 并在 `config.py` 引用
4. 加 `tests/test_models_registry.py` 用例覆盖
5. 文档:更新 README §4.2 的 Provider 表
6. 提交 PR,标题 `feat(provider): 新增 <X> 支持`

---

## 8. 新增 LLM 工具 / MCP 工具

```python
# ai_agent/tools.py
from langchain_core.tools import tool

@tool
def my_tool(param: str) -> str:
    """工具描述(LangChain 用作 tool schema 的 description)。

    Args:
        param: 参数说明

    Returns:
        结果说明
    """
    return f"echo {param}"

# 记得在 get_all_tools() 里注册
```

MCP 工具参考 `ai_agent/mcp_tools.py` 的 `registry.register(MCPTool(...))`。

加测试 → `tests/test_tools.py`。

---

## 9. 新增 Skill

```python
# ai_agent/skills.py · _register_my_skill
skill = Skill(
    name="my_skill",
    description="技能描述",
    category="research|code|finance|...",
    prompt_template="...{input}...",
    tools=["tool_a", "tool_b"],
)
self.registry.register(skill)
```

加测试 → `tests/test_skills.py`。

---

## 10. 提 Issue 模板

- 🐛 Bug:`bug_report.yml`
- ✨ Feature:`feature_request.yml`
- ❓ Question:`question.yml`

提交前先搜现有 issue。

---

## 11. 发布流程(给维护者)

完整 runbook:[web_console/.github/FIRST_RELEASE_RUNBOOK.md](web_console/.github/FIRST_RELEASE_RUNBOOK.md)

简要:
1. `git checkout main && git pull`
2. `git tag v2.x.y && git push origin v2.x.y`
3. release-please 自动开 PR → 合并
4. `release.yml` 自动跑 PyPI / GHCR / 三平台桌面包
5. 通知 Slack / Discord

---

## 12. 许可证

贡献的代码默认采用 [MIT License](LICENSE)。提交 PR 即表示同意。

---

## 13. 联系方式

- GitHub Issues(首选)
- Discussions(问答 / 想法)
- Email:<colbert@example.com>(替换为实际邮箱)