# 升级指南(Upgrade Guide)

> **副标题**:从旧版本平滑升级到最新版本(v0.4.16)的官方权威指南。
> **适用读者**:运维 / 后端 / 平台负责人 · **预计阅读**:15 分钟 · **难度**:⭐⭐⭐

---

## 📋 文档元信息

| 项 | 值 |
|---|---|
| 🎯 **目标读者** | 运维 / 后端 / 平台负责人 / Tech Lead |
| ⏱️ **预计阅读** | 15 分钟(速读 5 分钟) |
| 📊 **难度评级** | ⭐⭐⭐(需懂 Python + Docker) |
| 🎯 **本文档目标** | 让你**无损、可回滚、可验证**地完成版本升级 |
| ⚠️ **风险等级** | 🟢 低(v0.4.x 之间) / 🟡 中(v0.3.x → 0.4.x) / 🔴 高(v0.1.x → 0.4.x) |

---

## 🎯 TL;DR(60 秒速读)

```bash
# 90% 用户的升级流程(从 v0.4.x 任意版本)
pip install --upgrade ai-agent              # 升级
pytest tests/ -v                            # 验证(应 274+ passed)
python app.py                               # 启动
curl http://localhost:8000/api/version      # 确认版本号
```

**✅ 完成。** v0.4.x 系列完全向后兼容,无需改任何业务代码。

---

## 📖 阅读路径

| 你是谁? | 看哪些章节 |
|---|---|
| 🆕 **第一次升级** | §1 → §2 → §7 → §8 |
| 🏢 **生产环境运维** | §1 → §3 → §6 → §9 |
| 🆘 **升级出问题** | §7(回滚)→ §8(常见问题) |
| 🔬 **想理解原理** | §4(版本演进)→ §6(升级机制) |

---

## 1. 升级兼容性矩阵

> 📊 **看一眼就知道能否直接升**。

| 从哪个版本 | 兼容性 | 升级难度 | 是否需改代码 | 预计停机 |
|---|---|---|---|---|
| **v0.4.15 → v0.4.16** | ✅ 完全兼容 | 🟢 1 分钟 | ❌ 不需要 | 0(滚动升级) |
| v0.4.13/14 → v0.4.16 | ✅ 完全兼容 | 🟢 1 分钟 | ❌ 不需要 | 0 |
| v0.4.10/11/12 → v0.4.16 | ✅ 完全兼容 | 🟢 1 分钟 | ❌ 不需要 | 0 |
| v0.4.7~9 → v0.4.16 | ✅ 完全兼容 | 🟢 1 分钟 | ❌ 不需要(可选配置升级) | 0 |
| v0.4.0~6 → v0.4.16 | ✅ 完全兼容 | 🟡 5 分钟 | ❌ 不需要 | 0~5 分钟 |
| v0.3.x → v0.4.16 | ✅ 完全兼容 | 🟡 5 分钟 | ❌ 不需要(中间件是新增功能) | 0 |
| v0.2.x → v0.4.16 | ✅ 完全兼容 | 🟡 10 分钟 | ⚠️ 入口改为 `app.py` | 5~10 分钟 |
| **v0.1.x → v0.4.16** | ⚠️ 需迁移 | 🔴 30 分钟 | ⚠️ 见 §5 | 15~30 分钟 |

> 🎓 **原理小卡片**:"完全兼容" = 所有 v0.4.0 ~ v0.4.15 的代码、配置、数据文件在 v0.4.16 上无需修改即可运行。这是 semver 的"次版本号不变"原则。

---

## 2. 快速升级(90% 用户适用) ⭐⭐

> ⏱️ 5 分钟可完成。**前提:你已经在用 v0.4.x 任意版本**。

### Step 1 · 备份(防止意外)

```bash
# 1.1 备份 .env 和持久化数据
cp .env .env.backup-$(date +%Y%m%d)
cp -r logs logs.backup-$(date +%Y%m%d)

# 1.2 备份 SQLite 数据库
cp checkpoints.db checkpoints.db.backup-$(date +%Y%m%d)
cp memory.db memory.db.backup-$(date +%Y%m%d)

# 1.3 备份 Token 预算持久化(如有)
[ -f ~/.agent_middleware_budget.json ] && \
  cp ~/.agent_middleware_budget.json \
     ~/.agent_middleware_budget.json.backup-$(date +%Y%m%d)
```

> 💡 **为什么备份?** 即使声明"完全兼容",生产环境永远先备份。30 秒备份 vs 几小时数据恢复,你选哪个?

### Step 2 · 选择升级方式

#### 方式 A:pip(开发者推荐)

```bash
pip install --upgrade ai-agent
```

#### 方式 B:源码(贡献者 / 定制用户)

```bash
cd /path/to/langChain_langGraph
git fetch origin
git pull origin main          # 或切换到指定 tag:git checkout v0.4.16
pip install -e . --upgrade
```

#### 方式 C:Docker(运维推荐)

```bash
docker pull ghcr.io/colbertlee/ai-agent-console:v0.4.16

# 蓝绿部署:新版本跑 8001 端口,验证 OK 后切流量
docker run -d -p 8001:8000 \
  -e DEEPSEEK_API_KEY=sk-xxx \
  --name ai-agent-v0416 \
  ghcr.io/colbertlee/ai-agent-console:v0.4.16
```

> 🎓 **原理小卡片**:Docker 镜像是不可变的——`v0.4.16` 镜像永远不会变。这意味着你的测试结果 = 生产结果(可重现部署)。

### Step 3 · 验证(必须做!)

```bash
# 3.1 版本号
curl http://localhost:8000/api/version
# 期望包含 "0.4.16"

# 3.2 健康检查
curl http://localhost:8000/api/health
# 期望:{"status":"ok"}

# 3.3 全量测试
pytest tests/ -v
# 期望:大多数通过(可能因网络/环境跳过一些)

# 3.4 Middleware 测试(核心路径)
pytest tests/test_agent_middleware.py -v
# 期望:274 passed

# 3.5 Smoke test(端到端冒烟)
./test_package.sh     # 桌面包
./test_all.ps1        # Windows 全平台
```

### Step 4 · 切换流量(生产环境)

```bash
# 滚动升级 Kubernetes
kubectl set image deployment/ai-agent \
  ai-agent=ghcr.io/colbertlee/ai-agent-console:v0.4.16

# 或 docker-compose
docker-compose up -d

# 或 nginx upstream
# 先把新实例加进 upstream,观察 5 分钟
# → 没问题 → 把旧实例下线
```

✅ **升级完成!**

---

## 3. 生产环境升级最佳实践 ⭐⭐⭐

> 🏢 这一节专门写给生产环境运维。

### 3.1 蓝绿部署(零停机)

```bash
# 当前生产:v0.4.15 跑在 8000
# 新版本:v0.4.16 跑在 8001(灰度)

# 1. 启动 v0.4.16
docker run -d -p 8001:8000 \
  -e DEEPSEEK_API_KEY=sk-xxx \
  --name ai-agent-v0416 \
  ghcr.io/colbertlee/ai-agent-console:v0.4.16

# 2. 健康检查
curl http://localhost:8001/api/health

# 3. 切 10% 流量(nginx 配置)
upstream ai-agent {
    server localhost:8000;  # v0.4.15(90%)
    server localhost:8001;  # v0.4.16(10%)
}

# 4. 观察 30 分钟
# → 没问题 → 切 100% 到 8001
# → 有问题 → 回滚(见 §7)
```

### 3.2 灰度发布策略

```
阶段        流量比例    观察时长    通过标准
─────────────────────────────────────────
阶段 1      10%        30 分钟     错误率 < 0.1%
阶段 2      50%        1 小时      P95 延迟 < 5s
阶段 3      100%       持续监控    无新告警
```

### 3.3 升级前必须确认

- [ ] ✅ 备份完成(§2 Step 1)
- [ ] ✅ 测试套件通过(§2 Step 3)
- [ ] ✅ 监控告警已配置(`/api/metrics/prometheus`)
- [ ] ✅ 回滚方案已就绪(§7)
- [ ] ✅ 业务方已通知
- [ ] ✅ 变更窗口已预约(避开业务高峰)

---

## 4. 各版本变更详情 ⭐⭐⭐

### v0.4.16 (2026-07-28) — 当前最新版

> 🎯 **核心主题**:"Steady & Smart" — 持续打磨稳定性,引入更智能的缓存与正则配置。

#### ✨ 新增功能(默认禁用)

| 功能 | 用途 | 推荐配置 |
|---|---|---|
| `OutputSafetyConfig.explanation_llm_cache_size` | LLM 解释 LRU 缓存 | `500`(降本 50%+) |
| `OutputSafetyConfig.category_alias_regex_mode` | regex 模式匹配 category | `"regex"` |
| `TokenUsageConfig.alert_aggregation_jitter` tuple | 非对称告警抖动 | `(0.1, 0.3)` |
| `RateLimitConfig.dynamic_strategy_mixed_per_prefix_channel` | per-prefix 独立 watcher | chat/embed 分 channel |

#### 🔧 行为变更(向后兼容)

- ✅ `_apply_dynamic_strategy_watcher_message` 加 list schema 支持
- ✅ `_apply_dynamic_strategy_watcher_message` 空 dict → no-op
- ✅ `_enrich_explanations` 加 cache lookup(命中时跳过 LLM)
- ✅ `_fire_alerts` jitter 应用支持 asymmetric tuple

#### 🐛 修复(8 个边界 case)

1. `RateLimitConfig.dynamic_strategy_mixed_per_prefix_channel` 空 dict 静默 no-op
2. `_apply_dynamic_strategy_watcher_message` schema 混合 warn 不抛错
3. `category_alias_regex_mode="regex"` 非法 pattern 容错
4. `AlertInfo.metric_history` 环形缓冲溢出保护
5. `OutputSafetyMiddleware._enrich_explanations` cache key 冲突修复
6. `RateLimitMiddleware.close()` 重复调用幂等性
7. `TokenUsageMiddleware._fire_alerts` jitter tuple 单边为 0 修复
8. `PIIScrubMiddleware` 长消息 `re.sub` 单次扫描(O(n²) → O(n),+10x)

#### ⚠️ 破坏性变更

**无。** 所有 v0.4.15 代码无需任何修改。

---

### v0.4.3 (2026-07-28) — ⚠️ 重要 bug 修复

> 🐛 **强烈建议升级**。

#### Bug 详情

**v0.4.2 及之前**:LangChain 1.x `ModelResult` 改名 `ModelCallResult`,但 `agent_middleware.py` 仍引用旧名,导致 **8 个 hook 全部未生效**(silent fallback)。

**影响范围**:
- ❌ PII 脱敏不生效(隐私泄露风险)
- ❌ 限流不生效(可被刷)
- ❌ Token 用量统计不生效(账单不可控)
- ❌ 输出安全审查不生效

**v0.4.3 修复**:`from langchain.agents.middleware import ModelCallResult as ModelResult` 正确处理。

#### 迁移

升级到 v0.4.3+ 即生效,**无需改任何代码**。升级后会自动启用所有 hook。

> 🎓 **原理小卡片**:这是 `try/except ImportError` 模式的经典陷阱——`except` 块"安静地"把异常吞了,代码看似运行,实际 hook 全 disabled。**教训**:不要 silent fallback,至少 `logger.warning`。

---

### v0.4.0 (2026-07-28) — 引入 Middleware 系统

> 🏗️ **架构级升级**。

#### 新增

- `agent_middleware.py` — 8 个 LangChain 1.x hook(Logging/ToolCallCounter/ContextTrim/PIIScrub/RateLimit/AuditLog/TokenUsage/OutputSafety)
- `tests/test_agent_middleware.py` — 15 个用例

#### 迁移

- ✅ 默认 `agent.py` 自动接入,无需改代码
- ✅ 旧 LangChain 0.2.x 环境自动降级(`AgentMiddleware = object`)

> 🎓 **架构洞察**:v0.4.0 引入的 Middleware 系统是后续 17 次迭代的基石。理解它就能理解整个 v0.4.x 的演进方向,详见 [`agent_middleware.md`](agent_middleware.md)。

---

### v0.3.0 (2026-07-23) — 阶段 B:4 个国产 Provider

#### 新增 Provider

| Provider | 说明 | 入口 |
|---|---|---|
| `doubao` | 字节豆包 / 火山方舟 ARK | `ark.cn-beijing.volces.com` |
| `hunyuan` | 腾讯混元 | `api.hunyuan.tencent.com` |
| `siliconflow` | 硅基流动(聚合多模型) | `api.siliconflow.cn` |
| `minimax` | MiniMax 01 / abab7 | `api.minimax.chat` |

#### 环境变量变更

新增 4 个 Key:
```env
DOUBAU_API_KEY=...
HUNYUAN_API_KEY=...
SILICONFLOW_API_KEY=...
MINIMAX_API_KEY=...
```

#### 迁移

- ✅ 旧的 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` 不受影响
- 可选填新 Key 解锁国产模型

---

### v0.2.0 (2026-07-23) — 阶段 A:流式中间状态

#### 新增

- `prompt_registry.py` — 模板化 + 版本化
- `/api/prompts` / `/api/prompts/rollback` API
- 前端:工具调用时间线 + 思考过程折叠面板

#### 迁移

- ✅ 旧的 `api.py` / `web_ui.py` 仍保留
- 🟡 新代码统一走 `app.py`

---

## 5. 重大版本迁移:v0.1.x → v0.4.x ⭐⭐⭐⭐

> 🔴 **本节是高风险操作**,涉及入口文件改名、配置结构变化。

### 5.1 升级步骤(30 分钟)

```bash
# ── Step 1:备份(2 分钟) ──
cp .env .env.backup
cp -r logs logs.backup
cp *.db *.db.backup 2>/dev/null || true

# ── Step 2:拉新代码(3 分钟) ──
cd /path/to/langChain_langGraph
git fetch origin
git checkout main
git pull origin main
pip install -r requirements.txt --upgrade

# ── Step 3:迁移入口文件 ──
# 旧入口:python api.py / python web_ui.py
# 新入口:python app.py(已统一)
# 旧入口仍保留向后兼容,但建议迁移

# ── Step 4:环境变量检查 ──
# 旧 .env 加 LLM_API_KEY,新版本要求 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 二选一
grep -E "API_KEY" .env

# ── Step 5:数据迁移(如有 v0.1.x 持久化文件) ──
# v0.1.x 用 SQLite,schema 不兼容需要重建
python scripts/migrate_v01_to_v04.py

# ── Step 6:测试 ──
pytest tests/ -v

# ── Step 7:启动 ──
python app.py
```

### 5.2 API 兼容层

| 旧版本 | 新版本 | 处理 |
|---|---|---|
| `python api.py` | `python app.py` | ⚠️ 改名,旧命令仍兼容 |
| `python web_ui.py` | `python app.py` | ⚠️ 改名,旧命令仍兼容 |
| `from agent_api import *` | `from app import *` | ❌ 重写 |
| `LLM_API_KEY=...` | `DEEPSEEK_API_KEY=...` 或其他 | ⚠️ 改名 |
| `config.json` | `.env` | ❌ 迁移 |

### 5.3 已知不兼容点

> ⚠️ **必须检查**以下点,否则启动会失败:

1. **Python 版本**:v0.4.x 要求 Python 3.11+,旧版用 3.10 的需要升级
2. **依赖升级**:`pip install --upgrade` 后部分 API 改名(详见 changelog)
3. **配置文件格式**:v0.1.x 用 `config.json`,v0.4.x 用 `.env`
4. **持久化路径**:v0.1.x 用 `./data/`,v0.4.x 用 `./` 根目录

---

## 6. 升级机制详解 ⭐⭐⭐⭐

> 🎓 想理解"为什么升级这么简单/这么难"。

### 6.1 向后兼容性的保障

| 保障机制 | 作用 |
|---|---|
| **Semver 严格遵循** | v0.4.x 之间不引入破坏性变更 |
| **可选依赖降级** | Redis/Prometheus/LangSmith 未装时静默跳过 |
| **默认行为不变** | 所有新功能 `default=None/0/{}` |
| **测试覆盖** | 274 个用例守护兼容性 |

### 6.2 数据格式兼容性

```python
# v0.4.x 系列内部数据 schema 完全不变:
- AgentState:dict[str, Any]
- SafetyVerdict:dataclass(safe, reason, categories, ...)
- TokenUsage:dict(input, output, total)
- RateLimit key:{prefix}:{max_calls}per{window_seconds}s

# 跨版本兼容:
- v0.4.7+ 的 budget 持久化文件在 v0.4.16 上能直接读取(自动补全字段)
- v0.4.2+ 的 Redis 限流 key 在 v0.4.16 上能继续使用
```

> 🎓 **设计原则**:**永远不要 silent break 数据**。即使 schema 升级,也要写兼容层。

### 6.3 性能回归检测

> 升级前对比性能基准(本机测试):

```bash
# 升级前
pytest tests/test_performance.py -v --benchmark
# 记录:P50/P95/P99 延迟、token/s、QPS

# 升级后
pytest tests/test_performance.py -v --benchmark
# 对比:P95 偏差 < 10% 算正常
```

---

## 7. 回滚方案 ⭐⭐⭐

> 🆘 **升级后发现问题?3 步回滚**。

### 7.1 pip 用户

```bash
# 1. 卸载新版本
pip uninstall ai-agent -y

# 2. 装回旧版本
pip install ai-agent==0.4.15

# 3. 重启服务
python app.py
```

### 7.2 Docker 用户

```bash
# 1. 停止新版本
docker stop ai-agent-v0416 && docker rm ai-agent-v0416

# 2. 启动旧版本
docker run -d -p 8000:8000 \
  -e DEEPSEEK_API_KEY=sk-xxx \
  --name ai-agent \
  ghcr.io/colbertlee/ai-agent-console:v0.4.15
```

### 7.3 Kubernetes 用户

```bash
# 一键回滚
kubectl rollout undo deployment/ai-agent

# 或回滚到指定版本
kubectl rollout undo deployment/ai-agent --to-revision=2

# 查看历史
kubectl rollout history deployment/ai-agent
```

### 7.4 回滚注意事项

> ⚠️ **数据兼容性**:v0.4.x 之间回滚**无需数据迁移**(schema 一致)。

> ⚠️ **持久化预算文件**:如果从 v0.4.16 回滚到 v0.4.7 以下,新版写入的 `week_cost` 字段旧版读不到——但旧版会忽略未知字段,不报错。

---

## 8. 常见升级问题 ⭐⭐⭐

### 8.1 问题对照表

| 问题 | 原因 | 解决方案 |
|---|---|---|
| `ImportError: cannot import name 'ModelCallResult'` | LangChain 版本 < 1.0 | `pip install --upgrade langchain>=1.0.0` |
| `redis-py` 报错 | Redis 包未升级 | `pip install --upgrade redis>=5.0` |
| PII 脱敏突然生效 | v0.4.3 修复了 silent fallback | 配 `PIIScrubConfig(replacement="[REDACTED]")` 控制 |
| Prometheus 指标 label 变了 | v0.4.2 加 labels | 更新 Grafana dashboard |
| Token 预算持久化文件报错 | 旧版本字段缺失 | `rm ~/.agent_middleware_budget.json` |
| 启动报 "agent_middleware has no attribute X" | 旧版包缓存 | `pip install --force-reinstall ai-agent` |
| 测试启动变慢 | 测试用 `_FakeRedis` 重新初始化 | 升级 v0.4.16(SHA 缓存优化) |

### 8.2 升级后没看到新功能?

> 因为新功能默认禁用!需要显式配置:

```python
# 想用 LLM 解释缓存?
OutputSafetyConfig(explanation_llm_cache_size=500)

# 想用 regex 模式?
OutputSafetyConfig(category_alias_regex_mode="regex")

# 想用非对称告警抖动?
TokenUsageConfig(alert_aggregation_jitter=(0.1, 0.3))
```

### 8.3 性能没变化?

> 缓存和优化只在**特定场景**生效:

| 优化项 | 生效场景 |
|---|---|
| LLM 解释缓存 | 重复审查同一 text(审计场景) |
| 长消息 PII 优化 | 消息 > 10KB |
| Redis SHA 缓存 | 同一 backend 实例复用 |
| Token 预算持久化 | 跨进程/多机器 |

### 8.4 寻求帮助

> 🆘 **如果以上都没解决**:

1. 看 [`USAGE.md` §7 FAQ](USAGE.md#7-常见问题faq-)
2. 看 [`USAGE.md` §8 故障排查流程图](USAGE.md#8-故障排查流程图-)
3. 提 GitHub Issue:https://github.com/colbertlee/langChain_langGraph/issues
4. 联系维护者:见 README

---

## 9. 升级清单(可打印) ✅

> 升级前**逐项打勾**,避免遗漏。

### 升级前

- [ ] 已阅读本文档
- [ ] 已确认兼容性矩阵(§1)
- [ ] 已备份 .env / logs / *.db(§2 Step 1)
- [ ] 已预约变更窗口(避开业务高峰)
- [ ] 已通知业务方
- [ ] 已配置监控告警

### 升级中

- [ ] 执行升级命令(§2 Step 2)
- [ ] 健康检查通过(§2 Step 3)
- [ ] Middleware 测试 274 passed
- [ ] Smoke test 通过

### 升级后

- [ ] 版本号确认 v0.4.16
- [ ] 监控指标无异常
- [ ] 错误率 < 0.1%
- [ ] P95 延迟 < 5s
- [ ] 业务方确认无感知
- [ ] 回滚预案已就绪(待 1 周观察后下线旧版本)

---

## 10. 不同角色的升级建议

### 🛠️ 开发者(本地升级)

```bash
pip install --upgrade ai-agent
pytest tests/test_agent_middleware.py -v
# 期望:274 passed
```

### 🏢 运维(生产升级)

```bash
# 1. 阅读本文 §3 生产最佳实践
# 2. 蓝绿部署,先灰度 10%
# 3. 观察 30 分钟后切 100%
# 4. 保留旧版本镜像 1 周
```

### 🔧 Tech Lead(团队升级)

1. 在 staging 环境先升级
2. 跑完整业务回归(2~3 天)
3. 没回归问题再升级生产
4. 给团队发一份"升级要点邮件"

### 🎓 贡献者(源码升级)

```bash
git pull origin main
pip install -e ".[dev]" --upgrade
pytest tests/ -v
ruff check .
```

---

## 📚 相关文档

| 文档 | 用途 |
|---|---|
| [`README.md`](README.md) | 项目总览 |
| [`USAGE.md`](USAGE.md) | 使用说明书 |
| 🆕 [`RELEASE_NOTES.md`](RELEASE_NOTES.md) | 最新发布说明 |
| [`CHANGELOG.md`](CHANGELOG.md) | 完整变更日志(含本版本"🔧 最新修复"段) |
| [`FEATURES_GUIDE.md`](FEATURES_GUIDE.md) | 功能详解 |

---

## 💬 社区与反馈

- 🐛 **升级出错?**:https://github.com/colbertlee/langChain_langGraph/issues
- 💡 **升级建议?**:https://github.com/colbertlee/langChain_langGraph/issues/new?template=feature_request.yml
- 🔧 **文档改进?**:直接提 PR

---

> 🎯 **下一步**:看完本文档后,建议你先在 staging 环境跑一遍 §2 的"快速升级",再上生产。
> 记住:**备份永远不嫌多,回滚永远要预演**。
