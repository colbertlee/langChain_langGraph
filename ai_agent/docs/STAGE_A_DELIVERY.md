# 阶段 A 交付总结（v0.2.0）

> 阶段 A 目标：**Prompt 工程化 + 流式中间状态可视化 + 流式安全事件**。
> 完成日期：2026-07-23

## 1. 改动一览

### 后端
| 文件 | 改动 |
|------|------|
| `ai_agent/prompt_registry.py` | 🆕 提示词模板注册中心：system/role/tool 三段 + 版本号/作者/changelog + rollback 接口 |
| `ai_agent/agent.py` | `_build_system_prompt` 走 registry；`run_stream` 改为产出结构化事件 `start/thinking/chunk/tool_call/safety/error/complete`；新增 CoT 拆分 / tool name 抽取辅助方法 |
| `ai_agent/app.py` | 🆕 `/api/prompts` 与 `/api/prompts/rollback`；`/web-static` 静态挂载（用于演示页） |

### 前端
| 文件 | 改动 |
|------|------|
| `ai_agent/web/index.html` | `applyStreamEvent` 统一事件分发；`renderTimeline` / `renderThinking` / `renderSafety` 渲染组件；CSS 新增 `.msg-timeline` / `.msg-thinking` / `.msg-safety` / `.prompt-row`；设置面板新增"Prompt 版本管理"；附带 `__demo_inject` 演示钩子（仅 `?demo=1` 启用） |
| `ai_agent/web/preview_stage_a.html` | 🆕 阶段 A 三大场景演示页 |
| `ai_agent/web/preview_index_wrap.html` | 🆕 iframe 包装器，触发演示数据注入 |

### 测试
| 文件 | 用例数 |
|------|--------|
| `ai_agent/tests/test_prompt_registry.py` | 10 |
| `ai_agent/tests/test_stream_events.py` | 7 |
| `ai_agent/tests/test_prompts_api.py` | 4 |

### 文档
| 文件 | 改动 |
|------|------|
| `ai_agent/docs/AGENT_ARCHITECTURE_ROADMAP.md` | 🆕 七大模块规划总览 |
| `ai_agent/CHANGELOG.md` | 🆕 v0.2.0 条目 |
| `ai_agent/FEATURES_GUIDE.md` | 新增"中间状态可视化"+"Prompt 版本管理"两节 |
| `ai_agent/docs/STAGE_A_DELIVERY.md` | 🆕 本文 |

### 截图
| 文件 | 内容 |
|------|------|
| `ai_agent/docs/screenshot_stage_a_demo.png` | 三大场景综合演示（工具调用/CoT/安全拦截/Prompt 版本） |
| `ai_agent/docs/screenshot_index_chat.png` | 真实 web/index.html 聊天视图，演示消息含完整三要素 |
| `ai_agent/docs/screenshot_index_settings.png` | 设置面板的"Prompt 版本管理"区域 |

---

## 2. 用户可感知的功能差异

### Before（v0.1.0）
- 流式回答时只能看到打字效果，工具调用只在"消息元数据"里写一行文字。
- 没有"思考过程"展示。
- 安全拦截静默阻断。
- Prompt 是硬编码字符串，修改需改代码并重新部署。

### After（v0.2.0）
- 流式回答时，下方出现 **彩色 pill** 显示每个工具调用。
- 当模型输出含 `## 思考` 段落时，前端把它折叠成"💭 思考过程（点击展开）"。
- 输入被安全模块拒绝时，出现 🛡️ 提示横幅。
- 设置面板 → Prompt 版本管理：一键在 `v1.0.0`（无 CoT 兼容版）和 `v2.0.0`（默认 CoT 版）之间切换；下次会话生效。

---

## 3. 测试覆盖

```
tests/test_prompt_registry.py ........................ 10 passed
tests/test_stream_events.py ..........................  7 passed
tests/test_prompts_api.py ............................  4 passed
tests/test_agent.py (regression) ..................... 55 passed
tests/test_app_sse.py / test_app_ws.py ...............  2 passed
```

> 全部新增 + 既有测试通过，无回归。

---

## 4. 后续阶段建议

按规划文档 [AGENT_ARCHITECTURE_ROADMAP.md](../AGENT_ARCHITECTURE_ROADMAP.md)：

- **阶段 B**（工具治理）：B1 入参 Schema 校验、B2 按需工具加载、B3 工具级权限、B4 沙箱分级、B5 动态加载
- **阶段 F**（安全纵深）：F1 注入评测、F2 工具 RBAC、F3 HITL Web 闭环、F4 审计日志、F5 敏感操作二次确认
- **阶段 E**（运维）：E1 Token 面板、E2 死循环告警、E3 UI 回滚联动、E4 Eval Harness、E5 OTel 导出

---

> 维护者：阶段 A 由 `agent.run_stream` + `prompt_registry` 承担。下次启动服务时，注册中心会自动初始化 `v1.0.0` + `v2.0.0` 两个版本。