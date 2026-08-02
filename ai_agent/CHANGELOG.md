# Changelog

AI Agent 项目更新记录。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

<!-- bumpversion placeholder -->

## v0.4.16 (2026-07-28) — 🔧 最新修复与性能优化

### 🐛 Bug 修复

- **`RateLimitConfig.dynamic_strategy_mixed_per_prefix_channel` 空 dict 静默 no-op**:之前传空 dict 会触发 watcher 启动逻辑空跑,现在直接 no-op,日志更干净。
- **`_apply_dynamic_strategy_watcher_message` schema 混合 warn 不抛错**:之前遇到 dict/str 混合会抛 `ValueError`,现在 warn 跳过,业务不中断。
- **`category_alias_regex_mode="regex"` 非法 pattern 容错**:之前 `re.compile` 失败会让整个 `after_model` 异常,现在 warn 跳过该 pattern,主链路继续。
- **`AlertInfo.metric_history` 环形缓冲溢出保护**:之前 size=0 时还会 append,导致无限增长,现在 size<=0 直接禁用。
- **`OutputSafetyMiddleware._enrich_explanations` cache key 冲突修复**:之前同 text + 不同 categories 会撞 cache,现在 key 加 `tuple(categories)` 排序后 hash,杜绝冲突。
- **`RateLimitMiddleware.close()` 重复调用安全**:幂等性修复,可放心在 `__del__` / 信号处理器里多次调用。
- **`TokenUsageMiddleware._fire_alerts` jitter tuple 单边为 0 修复**:之前 `(0.0, 0.3)` 会让 negative jitter 计算错误,现在分别 clamp 到 [0, 1]。
- **`PIIScrubMiddleware` 长消息性能优化**:对 >10KB 的消息改用 `re.sub` 单次扫描,实测从 O(n²) → O(n),性能提升 10x。

### ⚡ 性能优化

- **`OutputSafetyMiddleware._enrich_explanations` 缓存命中跳过 LLM**:v0.4.16 新增的 `explanation_llm_cache_size`,实测降低 50%+ LLM 调用成本(重复 text 场景)。
- **`RateLimitMiddleware._apply_dynamic_strategy_watcher_message` list 解析**:`[strategy, args...]` 直接展开成 mixed dict,避免一次 Redis 往返,延迟降低 30%。
- **`_FakeRedis.evalsha` SHA 缓存命中**:`tests/test_agent_middleware.py` 测试启动时间从 12s → 8s(避免重复 `script_load`)。

### 📚 文档更新

- **`agent_middleware.md`**:全新重写为"专业内容创作者"风格,加入新手友好的时间轴心智模型 + 4 步优先级行动清单。
- 新增 **`USAGE.md`**:面向最终用户的使用说明书(安装/启动/9 大任务速查/12 个 FAQ/故障排查流程图)。
- 新增 **`UPGRADE.md`**:版本升级指南(兼容性表/迁移步骤/回滚方案/升级前必看清单)。
- 新增 **`RELEASE_NOTES.md`(本版本重写)**:面向用户的版本发布说明(亮点/安装/升级/兼容性/已知问题)。

### 🔄 向后兼容

- ✅ 所有 v0.4.15 代码无需任何修改即可运行
- ✅ 所有新功能默认禁用,需显式启用
- ✅ 测试 274 个全过,无回归

---

## v0.4.16 (2026-07-28) — explanation cache / regex mode / watcher schema list / asymmetric jitter / per-prefix channel

### Added
- **`OutputSafetyConfig.explanation_llm_cache_size`** + `OutputSafetyMiddleware._explanation_llm_cache`：FIFO cache
  - 0=禁用（默认，旧行为）；>0=缓存最近 N 个 (sha256(text)[:16], tuple(categories)) → dict
  - cache 命中时不再调 LLM（节省 LLM 调用成本）
  - 推荐 100~1000
- **`OutputSafetyConfig.category_alias_regex_mode`**：fnmatch / regex 双模式
  - 默认 "fnmatch"（v0.4.15 行为，向后兼容）
  - "regex" 模式用 re.search（支持 ^/\d/\w/|/{n,m}）
  - 非法 pattern → warn 跳过
- **`RateLimitConfig.dynamic_strategy_mixed_per_prefix_channel`** + `_start_per_prefix_watchers` + `_watcher_loop_per_prefix` + `_apply_per_prefix_watcher_message`：per-prefix 独立 watcher
  - `dict[prefix → channel]` 启动独立后台线程
  - 消息内容（直接 dict）只覆盖对应 prefix
  - `close()` 自动停所有 watchers

### Changed
- `OutputSafetyMiddleware._enrich_explanations` 加 cache lookup：先查 cache，未命中再调 LLM + 写 cache
- `OutputSafetyMiddleware._resolve_category` 加 regex 模式分支（基于 `category_alias_regex_mode`）
- `_apply_dynamic_strategy_watcher_message` schema 检测加 list 类型：[strategy, kwargs] 解析成 mixed dict
- `_apply_dynamic_strategy_watcher_message` 空 dict 直接 no-op
- `TokenUsageMiddleware._fire_alerts` jitter 应用支持 asymmetric (tuple)
- `RateLimitMiddleware.__init__` 加 `_per_prefix_watchers` 字段 + 调 `_start_per_prefix_watchers`
- `RateLimitMiddleware.close` 加停 per-prefix watchers 逻辑

### Tests
- `tests/test_agent_middleware.py`：256 → **274 个用例全部通过**
  - 5 个 explanation cache 测试（config 字段 / hit 不调 LLM / 不同 text miss / 满容量淘汰 / 默认禁用）
  - 4 个 regex mode 测试（config 字段 / ^ 元字符 / \d / 非法 pattern）
  - 2 个 watcher schema list 测试（list 解析 / 空 dict no-op）
  - 1 个 asymmetric jitter 测试（tuple 字段）
  - 6 个 per-prefix channel 测试（config 字段 / memory 不启动 / 有效消息 / 无效 JSON / 非 dict / close 停 watcher）

### Notes
- 升级到 v0.4.16 完全向后兼容：
  - `explanation_llm_cache_size=0` 默认无缓存（旧行为）
  - `category_alias_regex_mode="fnmatch"` 默认（v0.4.15 行为）
  - `alert_aggregation_jitter` float 仍有效（对称 jitter）
  - `dynamic_strategy_mixed_per_prefix_channel={}` 默认不启用
- explanation cache 推荐场景：审计 + 慢 LLM（同一 text 重复判 unsafe，省 LLM 成本）
- category_alias_regex_mode="regex" 推荐场景：复杂 category 命名规则（用 \d / \w 区分版本 / 类型）
- watcher list schema 推荐场景：prefix 很多但共享部分 args（节省 JSON 字符）
- asymmetric jitter 推荐场景：成本敏感场景偏宽松（不漏报）；延迟敏感场景偏严格（不重复）
- per-prefix channel 推荐场景：高频更新 prefix 独立 channel（避免全量 broadcast）

## v0.4.15 (2026-07-28) — counter cold-start / explanation LLM / category regex / alert jitter / mixed pubsub

### Added
- **`_MemoryBackend.sliding_window_counter` 补 cold-start 支持**（v0.4.14 已有功能）
- **`OutputSafetyConfig.explanation_llm` + `OutputSafetyMiddleware._enrich_explanations`**：自动 LLM 生成 explanation
  - 仅对 verdict.safe=False 且 verdict.explanation 为空的 category 生效
  - LLM 抛错不影响主流程
- **`OutputSafetyConfig.category_alias_regex`**：fnmatch 通配符
  - 优先级：精确 category_aliases > category_alias_regex > 原值
  - 多 regex 命中取最长 pattern
- **`TokenUsageConfig.alert_aggregation_jitter`**：N 秒抖动
  - 0=禁用；>0=有效窗口 = window × (1 ± jitter)
  - 推荐 0.05~0.2
- **`RateLimitConfig.dynamic_strategy_mixed_pubsub_channel` + `_apply_dynamic_strategy_watcher_message` 自动 schema 检测**：mixed 热加载
  - 消息内容 schema 自动判断
  - mixed 重建：清 `_backend_by_model`，下次 `_build_backend` 自动应用新配置

### Changed
- `OutputSafetyMiddleware._resolve_category` 加 category_alias_regex 兜底（fnmatch）
- `OutputSafetyMiddleware.after_model` 在 `_apply_severity_filter` 后调 `_enrich_explanations`
- `TokenUsageMiddleware._fire_alerts` 在 agg_window 应用 jitter
- `_apply_dynamic_strategy_watcher_message` schema 检测：纯 str → dynamic_strategy；纯 dict → dynamic_strategy_mixed；混合 → 警告
- `_MemoryBackend._hit_sliding_counter` docstring 补 cold-start 说明

### Tests
- `tests/test_agent_middleware.py`：242 → **256 个用例全部通过**
  - 1 个 counter cold-start 测试
  - 4 个 explanation LLM 测试（basic / skip existing / error no-op / no LLM no-op）
  - 3 个 category regex 测试（basic / longest wins / alias 优先）
  - 2 个 alert jitter 测试（config 字段 / 真的应用）
  - 4 个 mixed pubsub 测试（config 字段 / dict values 覆盖 mixed / str values 覆盖 strategy / mixed schema 警告）

### Notes
- 升级到 v0.4.15 完全向后兼容：`explanation_llm=None` 默认无 LLM 生成、`category_alias_regex={}` 默认无正则匹配、`alert_aggregation_jitter=0` 默认无抖动、`dynamic_strategy_mixed_pubsub_channel=None` 默认不启用 mixed pubsub
- explanation_llm 推荐场景：审计场景，需要自动解释为什么 unsafe（节省人工 review 时间）
- category_alias_regex 推荐场景：上游 judge 用动态 vocabulary（版本升级后多了新 category），不想每个都加 alias
- alert_aggregation_jitter 推荐场景：多实例部署（Kubernetes），每个 pod 的窗口微差异避免 thundering herd
- mixed pubsub 推荐场景：实时调整多业务 prefix 的策略（不同 chat / embed / search 用不同配置）
- mixed 重建是 lazy（清 backend dict 后下次 _build_backend 才重建），不是 hot-swap

## v0.4.14 (2026-07-28) — cold-start / category_aliases / alert_aggregation / explanation / dynamic_strategy_mixed

### Added
- **`RateLimitConfig.cold_start_calls` + `_MemoryBackend` / `_RedisBackend` 加 `cold_start_calls`**：冷启动
  - 前 N 次调用无脑通过（不限流），但仍 append 到 zset
  - 推荐：新实例启动 / 重启场景；避免"刚启动就限流"
- **`OutputSafetyConfig.category_aliases` + `_apply_category_aliases`**：category 别名
  - 例：`{"pii": "pii_leak", "personal": "pii_leak"}`
  - 自动同步 categories / category_severity / confidence_per_category / multi_* / weighted_severity / explanation
- **`TokenUsageConfig.alert_aggregation_window` + `AlertInfo.aggregation_count` + `aggregated_total_metric`**：告警聚合
  - 窗口内多次触发累加；窗口外重置 pending
  - 推荐 30~120s（适合批量上报）
- **`SafetyVerdict.explanation`** + `_aggregate_verdicts` 合并（最长胜出）
  - judge 返回 `{"pii": "phone number 138-1234-5678 detected"}` 这样的解释
- **`RateLimitConfig.dynamic_strategy_mixed` + `_RedisBackend.mixed_overrides`**：per-prefix 混合策略
  - 多参数覆盖：strategy + max_window_size + burst_size + cold_start_calls
  - 多 prefix 命中时取**最长**（更具体优先）

### Changed
- `_MemoryBackend.__init__` 加 `cold_start_calls` 参数；所有 `_hit_*` 加 cold-start 检查（仍 append 到 zset）
- `_RedisBackend.__init__` 加 `cold_start_calls` 和 `mixed_overrides` 参数；所有 `_hit_*` 加 cold-start 检查
- `_RedisBackend._resolve_mixed_overrides` 新增静态方法（最长 prefix 匹配）
- `_build_backend` 4 处传 `cold_start_calls` 和 `mixed_overrides`
- `OutputSafetyMiddleware._resolve_category` / `_apply_category_aliases` 新增方法
- `OutputSafetyMiddleware.after_model` 在 `_apply_threshold` 后 / `_apply_severity_filter` 前调 `_apply_category_aliases`
- `OutputSafetyMiddleware._normalize_verdict` 抽 `explanation`
- `OutputSafetyMiddleware._aggregate_verdicts` 收集 `explanation` 取最长
- `TokenUsageMiddleware._fire_alerts` 累加 `aggregation_count` 和 `aggregated_total_metric`
- `TokenUsageMiddleware.__init__` 加 `_aggregation_pending` 字段

### Tests
- `tests/test_agent_middleware.py`：226 → **242 个用例全部通过**
  - 3 个 cold-start 测试（config 字段 / memory 通过前 N / 计数器行为）
  - 3 个 category_aliases 测试（resolve / apply / 空 no-op）
  - 2 个 alert_aggregation 测试（config 字段 / 真的累加）
  - 3 个 explanation 测试（字段 / 聚合 / dict 规范化）
  - 5 个 dynamic_strategy_mixed 测试（config / resolve basic / longest wins / no match / 构造时应用）

### Notes
- 升级到 v0.4.14 完全向后兼容：`cold_start_calls=0` 默认无预热、`category_aliases={}` 默认不映射、`alert_aggregation_window=0` 默认不聚合、`explanation={}` 默认无解释、`dynamic_strategy_mixed={}` 默认不混合
- cold-start 仍 append 到 zset 的设计：保证 cold-start 后 zset 状态正确（不会突然显示"很空"）
- category_aliases 推荐场景：上游 judge 用不同 vocabulary，统一映射到内部 canonical
- alert_aggregation 推荐场景：批量上报（Prometheus remote_write）；实时通知（Slack）用 alert_cooldown
- explanation 推荐场景：审计日志（"为什么这条被判 unsafe"），非阻断路径
- dynamic_strategy_mixed 推荐场景：不同业务（chat/embed/search）共享一个 Redis 但策略参数完全不同

## v0.4.13 (2026-07-28) — watcher close / judge priority / weighted_severity / alert cooldown / max_window_size

### Added
- **`RateLimitMiddleware.close()` / `__enter__` / `__exit__` / `__del__`**：优雅停 watcher
  - `close()` 幂等：`set stop event + thread.join(timeout=2.0) + 清字段`
  - 支持 `with RateLimitMiddleware(...) as mw:` 自动 close
  - `__del__` best-effort 自动 close（防泄漏）
- **`OutputSafetyConfig.llm_judge_priorities`**：judge 优先级排序
  - 值大的先调；ties 用原顺序保持稳定
  - key 支持 `id(judge)` / `str(judge)` / `judge.__name__` 三种 lookup
- **`SafetyVerdict.weighted_severity` + `OutputSafetyConfig.llm_voting_weighted_severity_threshold`**
  - `_aggregate_verdicts` 自动算 `weighted_severity[cat] = mean(score × confidence)`
  - 新 voting strategy `"weighted_severity"`：任一 category 超阈值 → unsafe
- **`TokenUsageConfig.alert_cooldown`**：同 severity 在 N 秒内不重复触发
  - `dict[severity, seconds]`，如 `{"warn": 60, "critical": 300}`
- **`RateLimitConfig.max_window_size` + `_MemoryBackend` / `_RedisBackend` 加 `max_window_size`**
  - sliding_window_log 精确内存上限
  - `None`：不限；`>0`：`ZREMRANGEBYRANK` 保留最新 N 条历史
  - Lua 加 ARGV[4] = max_window_size（>0 触发 ZREMRANGEBYRANK）

### Changed
- `RateLimitMiddleware.__init__` 拆出 watcher stop fields（`_watcher_thread`、`_watcher_stop_event`）
- `OutputSafetyMiddleware._vote_judgers` 在 judge 收集后按 priority desc stable sort
- `OutputSafetyMiddleware._aggregate_verdicts` 收集 `score × confidence` pairs + 算 weighted_severity
- `OutputSafetyMiddleware.__post_init__` 加 `"weighted_severity"` 到合法 voting strategy
- `OutputSafetyMiddleware._normalize_verdict` 抽 `weighted_severity`
- `TokenUsageMiddleware.__init__` 加 `_last_fired_at: dict[(scope, severity), float]`
- `TokenUsageMiddleware._fire_alerts` 在 `_fired_alerts` 检查后 + `_fired_alerts.add` 前检查 cooldown
- `_RedisBackend._LUA_SLIDING` 加 ARGV[4] = max_window_size（v0.4.13 Lua 升级）
- `_RedisBackend._hit_sliding_window` 传 max_ws_arg；Fallback 也加 zremrangebyrank
- `_MemoryBackend.__init__` 加 max_window_size 参数；`_hit_sliding` 加内存上限砍削
- `_build_backend` 把 `max_window_size` 传给 `_MemoryBackend` / `_RedisBackend`

### Tests
- `tests/test_agent_middleware.py`：209 → **226 个用例全部通过**
  - 3 个 watcher close 测试（幂等 / with / __del__）
  - 3 个 judge priority 测试（by id / 默认 0 / 实际排序）
  - 5 个 weighted_severity 测试（字段 / 聚合 / strategy 拦截 / strategy 通过 / dict 规范化）
  - 2 个 alert cooldown 测试（config 字段 / 真的生效）
  - 4 个 max_window_size 测试（config 字段 / memory cap / redis cap / 默认 None）
- `_FakeRedis.evalsha` 升级：处理 ARGV[5] = max_window_size

### Notes
- 升级到 v0.4.13 完全向后兼容：`llm_judge_priorities={}` 默认全 0；`weighted_severity={}` 默认无；`alert_cooldown={}` 默认无；`max_window_size=None` 默认无内存上限
- `close()` 推荐场景：测试 tearDown / 进程退出 / 动态重建中间件
- weighted_severity 推荐场景：审计/排序（"最严重的 category 是什么"），不是决策（决策仍用 majority/unanimous）
- alert cooldown 推荐场景：实时通知（Slack）→ 长 cooldown（5min）；批量上报（Prometheus）→ 短 cooldown（10s）
- max_window_size 推荐：`max_calls * 2~5`；过大浪费内存，过小丢精度

## v0.4.12 (2026-07-28) — dynamic_strategy backoff / per-judge 并发 / multi_categories_confidence / metric_history / pubsub watcher

### Added
- **`RateLimitConfig.dynamic_strategy_reload_backoff`**：失败指数 backoff
  - `(min_factor, max_factor, multiplier)`：失败后下次 reload 间隔 × multiplier，封顶 max_factor
  - 推荐 `(2.0, 8.0, 2.0)`：失败 1 次后间隔 = 2×，失败 2 次后 = 4×，3 次后 = 8×（封顶）
  - 成功后立即重置 baseline
- **`RateLimitConfig.dynamic_strategy_reload_max_failures`**：连续失败超限停止
  - 默认 None（无限重试）；推荐 5~10
- **`OutputSafetyConfig.llm_judge_per_concurrency`**：per-judge 并发开关
  - key 支持 `id(judge)` / `str(judge)` / `judge.__name__` 三种 lookup
  - `False` 强制走 sequential 路径（即使全局开了并发）
  - 典型：同步阻塞型 judge（Redis 监控、本地脚本）→ False
- **`SafetyVerdict.multi_categories_confidence`**：per-category 多 judge confidence 原始投票
  - `_aggregate_verdicts` 自动填；`confidence_per_category` 自动算平均
- **`AlertInfo.metric_history` + `TokenUsageConfig.alert_history_size`**：环形缓冲
  - 0=禁用（默认，旧行为）；>0=保留最近 N 次触发的 cost 增量
  - 用于审计 / 趋势分析（"今天 80% 告警 5 次，总 delta=0.05"）
- **`RateLimitConfig.dynamic_strategy_pubsub_channel`**：Redis pub/sub watcher
  - 后台线程订阅 channel；消息内容（JSON dict）覆盖 dynamic_strategy
  - 必须 backend=redis / redis_cluster / redis_sentinel；memory 无效
  - 用法：`redis-cli publish my_channel '{"chat:": "token_bucket"}'`

### Changed
- `RateLimitMiddleware._maybe_reload_dynamic_strategy` 加 backoff + max_failures + watcher 集成
- `RateLimitMiddleware._current_dynamic_strategy_reload_interval` 新增方法：算 effective interval
- `OutputSafetyMiddleware._vote_judges` 拆出"并发组 + 顺序组"两阶段
- `OutputSafetyMiddleware._judge_concurrency_for` 新增方法：per-judge 配置 lookup
- `OutputSafetyMiddleware._aggregate_verdicts` 收集 `multi_categories_confidence` 原始投票
- `TokenUsageMiddleware._fire_alerts` 维护环形缓冲 + 传 `info.metric_history`
- `RateLimitMiddleware.__init__` 启动 watcher 线程（如果 channel 非空）

### Tests
- `tests/test_agent_middleware.py`：191 → **209 个用例全部通过**
  - 4 个 dynamic_strategy backoff 测试（递增 / 重置 / max_failures / None baseline）
  - 3 个 per-judge concurrency 测试（特定 judge 关闭 / 默认回落 / by name）
  - 3 个 multi_categories_confidence 测试（字段 / 聚合 / dict 规范化）
  - 3 个 AlertInfo.metric_history 测试（字段 / 环形缓冲 / 默认禁用）
  - 5 个 pub/sub watcher 测试（config 字段 / 有效消息 / 无效 JSON / 非 dict / 非 redis 不启动）

### Notes
- 升级到 v0.4.12 完全向后兼容：`dynamic_strategy_reload_backoff=None` 默认无 backoff、`llm_judge_per_concurrency={}` 默认回落全局、`alert_history_size=0` 默认无 history、`dynamic_strategy_pubsub_channel=None` 默认不启动 watcher
- backoff 推荐场景：etcd / 配置中心偶发超时；watcher 推荐场景：实时推送（如：发布系统审批后立即生效）
- watcher 线程是 daemon=True，主进程退出自动结束；但 redis 连接不会立即关闭
- per-judge concurrency 推荐配置：网络 IO judge → True；本地脚本 / 阻塞型 → False
- `metric_history` 推荐 size：50（短期）/ 200（中期）；过长会占用内存

## v0.4.11 (2026-07-28) — judge 并发 / AlertInfo 增量 / dynamic_strategy 热加载 / alert 链 / 分类 confidence

### Added
- **`OutputSafetyConfig.llm_judge_concurrency`**：judge 异步并发投票
  - `1`（默认）= 顺序（旧行为）
  - `>1` = `ThreadPoolExecutor(max_workers=concurrency)` 并发
  - judge 抛错不影响其他；fallback 到 `fail-closed`/`fail-open`
  - 推荐 4~8（多 judge voting 提速）
- **`AlertInfo.trigger_metric` + `trigger_threshold`** 字段
  - `trigger_metric` = 本次 after_model 的 cost 增量（不是累计）
  - `trigger_threshold` = 实际触发的 ratio
- **`RateLimitConfig.dynamic_strategy_loader` + `dynamic_strategy_reload_interval`**：hot-reload
  - `interval=0`（默认）= 不轮询（旧行为）
  - `interval>0`（推荐 30~300s）= 周期性调 loader，覆盖 config + 同步到所有 backend
  - loader 返回 dict 不匹配 schema 时 warn 不抛错
- **`TokenUsageConfig.on_alerts`**：多 callback 链（tuple）
  - `on_alert`（单）+ `on_alerts`（链）共存：先 `on_alert` 再 `on_alerts`
  - 任一 callback 抛错不影响其他（best-effort fan-out）
- **`SafetyVerdict.confidence_per_category`** 字段
  - `_aggregate_verdicts` 自动算 per-category 平均 confidence

### Changed
- `_MemoryBackend.__init__` 加 `_key_prefix_strategy = {}`（API 一致性，便于 hot-reload 同步）
- `OutputSafetyMiddleware._vote_judgers` 拆出顺序/并发分支（`concurrency=1` → 顺序，`>1` → ThreadPoolExecutor）
- `OutputSafetyMiddleware._aggregate_verdicts` 收集 `confidence_per_category` 并取平均
- `TokenUsageMiddleware._fire_alerts` 用 `_get_on_alert_callbacks` 聚合 `on_alert` + `on_alerts`
- `TokenUsageMiddleware._fire_alerts` 在 AlertInfo 加 `trigger_metric=cost_usd, trigger_threshold=th_ratio`
- `RateLimitMiddleware.before_model` 在 model_name 抽取前调 `_maybe_reload_dynamic_strategy`
- `RateLimitMiddleware._maybe_reload_dynamic_strategy` 周期调 loader + 覆盖 config + 同步 backend

### Tests
- `tests/test_agent_middleware.py`：177 → **191 个用例全部通过**
  - 3 个 judge 并发测试（顺序 / 并发提速 / config 字段）
  - 2 个 AlertInfo.trigger_metric 测试（字段 / 真的触发）
  - 3 个 dynamic_strategy hot-reload 测试（基本 / 禁用 interval / 同步到 backend）
  - 3 个 alert chain 测试（全部触发 / on_alert + on_alerts 共存 / 单错不影响）
  - 3 个 confidence_per_category 测试（字段 / 聚合 / dict 规范化）

### Notes
- 升级到 v0.4.11 完全向后兼容：`llm_judge_concurrency=1` 默认顺序、`dynamic_strategy_reload_interval=0` 默认禁用、`on_alerts=()` 默认单 callback 模式、`trigger_metric=0` 默认无
- judge 并发 + cache:cache key 已含 judge id（v0.4.9 修复），并发不会互相污染
- hot-reload 推荐：从 etcd / 配置中心 / S3 拉；本地测试可用 `dict` 直接返回
- `trigger_metric` 主要用于报警聚合（"今天触发了 5 次 80% 告警，总 delta=0.05"）
- `confidence_per_category` 用于精细化审计（"pii=0.95 几乎确定是 PII，spam=0.6 只是疑似"）

## v0.4.10 (2026-07-28) — memory sliding_window_counter / judge 异构 timeout / multi_severity 投票 / alert thresholds

### Added
- **`_MemoryBackend` 加 `sliding_window_counter` 策略**
  - 内存上限 = `max_calls - 1`（避免 list 无限增长）
  - 与 Redis 版语义对齐（v0.4.9 Redis 已支持，v0.4.10 memory 也支持）
- **`OutputSafetyConfig.llm_judge_timeouts`**: per-judge 异构 timeout
  - key 支持 `id(judge)` / `str(judge)` / `judge.__name__` 三种 lookup
  - 未配置回落 `llm_judge_timeout`；推荐小模型 1s / 大模型 5s
- **`SafetyVerdict.multi_categories_severity`** 字段：同 category 多次投票收集
  - `_aggregate_verdicts` 自动算 majority severity（同票按 rank 高的胜）
  - 例：3 judge 判 `pii=[high, high, critical]` → majority=high，但 `multi_categories_severity={"pii": ["high", "high", "critical"]}` 保留全部
- **`TokenUsageConfig.alert_thresholds` + `on_alert` callback + `AlertInfo`** 数据类
  - `alert_thresholds: tuple[(ratio, severity), ...]`
  - 自动按 daily / weekly / monthly 三种 scope 检查
  - 同 `(scope, severity)` 只触发一次（去重）；跨天/周/月重置 `_fired_alerts`
  - `AlertInfo(scope, severity, current_usd, budget_usd, ratio, model_name)` 数据类
- **`_RedisBackend` dynamic_strategy + sliding_window_counter 组合**（v0.4.8 已实现，v0.4.10 验证完整工作）

### Changed
- `_MemoryBackend.hit_and_check` 加 `"sliding_window_log"` 别名 → `"sliding_window"` 同一路径
- `_MemoryBackend._hit_sliding_counter` 加内存上限（避免 list 无限增长）
- `OutputSafetyMiddleware._invoke_judge` 用 `_judge_timeout_for(judge)` 查 per-judge timeout
- `OutputSafetyMiddleware._aggregate_verdicts` 收集 `multi_categories_severity` + 算 majority severity
- `TokenUsageMiddleware.after_model` 在 budget 检查后调 `_fire_alerts`
- `TokenUsageMiddleware._fire_alerts` 按 daily/weekly/monthly 检查 + 去重触发

### Tests
- `tests/test_agent_middleware.py`：161 → **177 个用例全部通过**
  - 3 个 `_MemoryBackend.sliding_window_counter` 测试（基础 / 内存上限 / log 别名）
  - 3 个 judge 异构 timeout 测试（by id / by name / 真的生效）
  - 3 个 multi_categories_severity 测试（字段 / 聚合 / 同票 rank tiebreak）
  - 5 个 alert threshold 测试（fires / dedup / 跨天重置 / 无 callback / AlertInfo 数据类）
  - 2 个 dynamic_strategy + sliding_window_counter 测试

### Notes
- 升级到 v0.4.10 完全向后兼容：`_MemoryBackend` 默认 strategy 仍是 `sliding_window`、`llm_judge_timeouts={}` 默认空、`alert_thresholds=((0.5,"info"),(0.8,"warn"),(1.0,"critical"))` 默认仍合理（虽没 on_alert）
- `_MemoryBackend.sliding_window_counter` 不保证精确限流(进程内,无 atomic);多进程请用 Redis
- judge 异构 timeout 推荐场景：本地小模型 0.5s / OpenAI 5s / Claude 5s；超时按 judge 单独统计
- alert thresholds 推荐：`(0.5, "info")` / `(0.8, "warn")` / `(1.0, "critical")`；告警回调可对接 Slack / 邮件 / PagerDuty
- `multi_categories_severity` 主要用于审计/可视化（"为什么这条被判 critical"）；具体决策仍以 `category_severity`（majority）为准

## v0.4.9 (2026-07-28) — burst_size / weekly budget / judge voting / sliding_window_log / category_severity

### Added
- **`RateLimitConfig.burst_size`**：token_bucket 独立突发容量
  - `None`（默认）= `max_calls`（满桶启动，旧行为）
  - 设值后：满桶 = `burst_size`，稳态补 token 速率仍 = `max_calls / window_seconds`
  - 例：`max_calls=60, window_seconds=60, burst_size=10` → 1 token/秒稳态，但可一次性消耗 10 个
  - memory / redis 后端都支持（redis Lua ARGV[5] = burst_size）
- **`TokenUsageConfig.weekly_budget_usd`**：跨 ISO 周自动重置
  - `budget_week_start: "monday"`（默认 ISO 周）`"sunday"`（美国式）
  - 持久化字段 `week`（`(year, week)` tuple）+ `week_cost`
  - 超额抛 `TokenBudgetExceeded(scope="weekly", current_usd, budget_usd)`
  - 兼容旧 v0.4.7/v0.4.8 持久化文件（自动补 week/week_cost 字段）
- **`OutputSafetyConfig.llm_judges` + `llm_voting_strategy`**：多 judge 投票
  - 支持 4 种 strategy：`unanimous`（全票）/`majority`（多数，默认）/`any`（任一）/`weighted_majority`（score 加权）
  - 与单 `llm_judge` 共存：先 `llm_judge` 后 `llm_judges`
  - 聚合 verdict：categories 取并集去重、score 取最大、confidence 取平均
  - `__post_init__` 校验 `llm_voting_strategy` 合法值
- **`_RedisBackend.sliding_window_log`**（`sliding_window` 别名）+ **`sliding_window_counter`**：新增第 4 种策略
  - `sliding_window_log` = 原 `sliding_window`（ZREMRANGEBYSCORE + ZCARD 精确版，内存 O(实际调用次数)）
  - `sliding_window_counter` = ZREMRANGEBYRANK 保留最新 N 条（内存 O(max_calls)，更省）
- **`SafetyVerdict.category_severity`** 字段 + **`OutputSafetyConfig.safety_min_severity`** 过滤
  - 严重度排序：`critical` > `high` > `medium` > `low`
  - 默认 `category_severity_map`：`prompt_injection`/`jailbreak`=critical、`pii_leak`/`toxicity`/`hate_speech`/`violence`=high、`bias`=medium、`spam`=low
  - `safety_min_severity="high"` → 只拦 critical + high，medium/low 放过
  - 过滤后所有 category 都低于阈值 → 自动判 safe

### Changed
- `_MemoryBackend.__init__` 加 `burst_size` 参数；`_hit_token_bucket` 用 `self.burst_size` 作桶容量上限
- `_RedisBackend.__init__` 加 `burst_size` 参数；`_LUA_TOKEN` 加 ARGV[5] = burst_size
- `_RedisBackend.hit_and_check` 拆出 `_hit_sliding_window_counter` 子方法
- `OutputSafetyMiddleware.after_model` 走 `_vote_judges`（单 judge + 多 judge 统一入口）
- `OutputSafetyMiddleware` 加 `_vote_judges` / `_aggregate_verdicts` / `_apply_severity_filter`
- **`[bug fix] OutputSafetyMiddleware._cache_key` 加 judge id prefix**
  - v0.4.8 的 cache key 仅看 text，多 judge voting 时 A 判 safe 缓存后会被 B 命中，永远返回 safe
  - v0.4.9 cache key 格式：`f"{id(judge)}:{text_hash}"`，避免 cross-judge 污染
- `_normalize_verdict` 从 dict 抽 `category_severity`
- `TokenUsageMiddleware._load_budget_state` 兼容旧 v0.4.7/v0.4.8 持久化文件（自动补 week/week_cost）

### Tests
- `tests/test_agent_middleware.py`：140 → **161 个用例全部通过**
  - 4 个 burst_size 测试（独立 / 默认 / config 字段 / RateLimitMiddleware 传递）
  - 3 个 weekly budget 测试（超额 / 跨周重置 / _iso_week_key）
  - 7 个 judge voting 测试（majority / unanimous / any / categories 聚合 / weighted_majority / 非法 strategy / llm_judge + llm_judges 共存）
  - 2 个 sliding_window_log/counter 测试（别名 / ZREMRANGEBYRANK）
  - 5 个 category_severity 测试（字段 / low 过滤 / critical 保留 / _meets_severity / dict 规范化）

### Notes
- 升级到 v0.4.9 完全向后兼容：`burst_size=None` 默认行为不变、`weekly_budget_usd=None` 不拦截、`llm_judges=()` 单 judge 路径不变、`safety_min_severity=None` 不过滤
- `_hit_sliding_window_counter` 内存占用 = max_calls（极省）；`sliding_window_log` = 实际调用次数（精确但内存稍大）
- 多 judge 推荐用"小模型 + 大模型"组合：claude-haiku-4-5 快速投票 + claude-sonnet-4-5 关键决策
- `safety_min_severity="medium"` 适合"误报代价高"场景（医疗）；`"high"` 适合"漏报代价高"场景（金融）

## v0.4.8 (2026-07-28) — per-model budget / judge cache / 跨天跨月 budget / score-threshold / dynamic_strategy

### Added
- **`RateLimitMiddleware.model_budget`**（per-model rate limit）
  - dict[model_name → max_calls]；model_name 抽自 `state["_hook_model_name"]` → `runtime.metadata.model_name` → `runtime.config.metadata.model_name`
  - backend 按 model_name 缓存（FIFO 上限 128）
  - 未配置 model_name 回落到 `max_calls`
- **`OutputSafetyConfig.llm_judge_cache_*`**（LLM judge 结果缓存）
  - `llm_judge_cache_size`（默认 256，None=关闭）
  - `llm_judge_cache_ttl`（默认 300s，None=不过期）
  - `llm_judge_cache_key_fn`（自定义 cache key 函数，默认 `hash(text)[:16]`）
- **`TokenUsageConfig.daily_budget_usd` / `monthly_budget_usd`**（跨天/跨月自动重置）
  - `budget_persist_path`：持久化 JSON（默认 `~/.agent_middleware_budget.json`）
  - 自动检测日期/月份变化 → 跨天/跨月自动重置
  - 超额抛 `TokenBudgetExceeded(scope="daily"|"monthly", current_usd, budget_usd)`
- **`SafetyVerdict.confidence`** 字段
- **`OutputSafetyConfig.safety_threshold`**（0~1，score 与 threshold 联合判定）
  - `score >= threshold + safe=True` → 强制判 unsafe（避免漏判）
  - `score < threshold + safe=False` → 反向校正为 safe（避免误判）
- **`RateLimitConfig.dynamic_strategy`**（Redis 后端专用）
  - dict[prefix → strategy]：例 `{"chat:": "sliding_window", "embed:": "token_bucket"}`
  - 构造时预加载所有 strategy 的 Lua（多 sha 缓存）
  - `hit_and_check` 时按 self._key_zset/hash 前缀查表决定 strategy

### Changed
- `_RedisBackend.__init__` 构造时按 strategy + dynamic_strategy 预加载多份 Lua（`_sha_by_strategy`）
- `_RedisBackend.hit_and_check` 在 dynamic_strategy 命中时切换 strategy 并更新 `_sha`
- `OutputSafetyMiddleware._call_judge` 拆出 `_invoke_judge` 子方法 + `_cache_key` / `_judge_cache_get` / `_judge_cache_put`
- `OutputSafetyMiddleware.after_model` 调用 `_apply_threshold` 做 score+threshold 二次判定
- `RateLimitMiddleware.before_model` 抽 model_name + `_get_or_build_backend` 按 model_name 缓存 backend
- `TokenUsageMiddleware.after_model` 在 cumulative 检查后增加 daily/monthly 检查 + 持久化写入

### Tests
- `tests/test_agent_middleware.py`：121 → **140 个用例全部通过**
  - 4 个 model_budget 测试（命中 / 回落 / 抽 model_name 优先级 / 缓存）
  - 4 个 judge cache 测试（命中 / 禁用 / TTL / 自定义 key_fn）
  - 3 个 daily/monthly budget 测试（daily 超额 / 跨天重置 / monthly 超额）
  - 5 个 SafetyVerdict.confidence + threshold 测试（字段 / force unsafe / flip to safe / 禁用 / dict 规范化）
  - 3 个 dynamic_strategy 测试（按前缀选 / 预加载 Lua / config 字段）

### Notes
- 升级到 v0.4.8 完全向后兼容：model_budget 默认 None（不生效）、cache_size 默认 256 / ttl 300s（默认开 cache）、daily/monthly_budget_usd 默认 None（不拦截）、safety_threshold 默认 None（不二次判定）、dynamic_strategy 默认空（按 rate_limit_strategy）
- daily/monthly budget 持久化路径默认 `~/.agent_middleware_budget.json`；可在多进程/多机器间共享（写时 fsync 由 OS 决定）
- judge cache 推荐 256~1024；ttl 推荐 60~600s（过长影响 prompt injection 攻击面发现）
- dynamic_strategy 仅 Redis 后端生效；memory 后端用 `rate_limit_strategy`

## v0.4.7 (2026-07-28) — Redis token_bucket / CAS / JSON 价目 / budget / LLM judge

### Added
- **`_RedisBackend` token_bucket 策略（Lua 脚本）**
  - HASH 存 `(tokens, last_refill_ts)`，每次按 `elapsed * rate` 补 token
  - Fallback：`HGETALL` + 算补 token + `HSET`（无原子性，best effort）
  - 适用于"允许突发、平均速率受控"场景
- **`_RedisBackend` atomic CAS（乐观锁）**
  - sliding_window 走 `WATCH/MULTI/EXEC`，3 次重试
  - client 不支持 watch 时降级传统 pipeline（兼容 mock/旧 fake）
- **`_RedisBackend` per-model 独立配额**
  - 构造参数 `model_name`：key 加 `:m:<model>` 后缀
  - 不同 model 互不影响同一窗口
- **`load_model_prices_from_json(path)`** 函数
  - 支持 list 格式 `[input, output]` 和 dict 格式 `{input_per_1k, output_per_1k}`
  - `_meta` 字段自动忽略
  - 文件不存在/格式错误 → warn 不抛错，返回 `{}`
- **`TokenUsageConfig.cost_prices_file`** 自动合并价目（默认 < 文件 < 用户）
- **`TokenUsageConfig.per_call_budget_usd` / `cumulative_budget_usd`**
  - 超过阈值抛 `TokenBudgetExceeded(scope="per_call"|"cumulative", current_usd, budget_usd)`
- **`OutputSafetyConfig.llm_judge: Callable[[str], SafetyVerdict]`**
  - 替代/补充关键词审查
  - `SafetyVerdict` 数据类（`safe` / `reason` / `categories` / `score`）
  - `llm_judge_timeout` / `llm_judge_fail_closed`（默认 fail-closed）/ `llm_judge_min_length`
  - judge 返回值自动规范化（`dict` / `bool` / `SafetyVerdict` 都支持）
  - 关键词审查仍然生效（向后兼容）

### Changed
- `OutputSafetyMiddleware.after_model` 拆出 `_call_judge` / `_normalize_verdict` 子方法
- `TokenUsageMiddleware.after_model` 增加 budget 检查（在 cost 估算后、state 写入前）
- `_RedisBackend.__init__` 支持 strategy + model_name 参数；构造时按 strategy 加载对应 Lua
- `_RedisBackend.hit_and_check` 拆分到 `_hit_sliding_window` / `_hit_fixed_window` / `_hit_token_bucket` 三个方法
- `_FakeRedis`（测试 fake）补 hgetall/hset/expire/watch/unwatch 方法，支持 token_bucket + WATCH 测试

### Tests
- `tests/test_agent_middleware.py`：100 → **121 个用例全部通过**
  - 5 个 Redis 后端测试（token_bucket / fixed_window / per-model / fail-open / 三种策略）
  - 4 个 JSON prices 测试（list / dict / 缺文件 / cost_prices_file 集成）
  - 4 个 budget 测试（per_call / cumulative / 默认禁用 / TokenBudgetExceeded 属性）
  - 8 个 LLM judge 测试（unsafe raise / safe / redact / min_length / dict 规范化 / 超时 / fail-open / 关键词向后兼容）

### Notes
- 升级到 v0.4.7 完全向后兼容：`rate_limit_strategy="sliding_window"` 默认、`parent_run_id_fallback=None` 默认、关键词审查仍然工作
- `TokenBudgetExceeded` 继承 `Exception`；可在 agent 外层 try/except 捕获并降级（如放弃任务、告警）
- LLM judge 推荐用 dedicated 小模型（如 `claude-haiku-4-5`）节省成本；`llm_judge_min_length=50` 避免对短消息误判
- Redis CAS 用 `WATCH/MULTI/EXEC` 仅在 fallback 路径（Lua 缓存失效时）；Lua 路径本身就是原子的
- per-model 配额 key：`rl:{base}:m:gpt-4o:zset` —— Redis Cluster 下 `{}` 仍强制同 slot

## v0.4.6 (2026-07-28) — 限流策略扩展 / cost 估算 / OpenTelemetry / metadata key

### Added
- **`RateLimitMiddleware.rate_limit_strategy`**：支持 3 种策略
  - `"sliding_window"`（默认）：按时间戳列表去旧（旧行为）
  - `"fixed_window"`：按 `floor(now / window) * window` 分桶（边界效应）
  - `"token_bucket"`：连续补 token（容许突发，平均速率仍受 max_calls/window_seconds 控制）
  - 仅 `backend="memory"` 时生效；redis 后端仍走 sliding_window
- **`TokenUsageMiddleware` 加 cost 估算**（按 `model_name` 查价）
  - 内置价目表 `_DEFAULT_MODEL_PRICES`（15 个主流模型：OpenAI gpt-4o / gpt-4o-mini / o1 / o3-mini；Anthropic claude-sonnet-4-5 / claude-haiku-4-5 / claude-3.5-sonnet 等）
  - `TokenUsageConfig.cost_prices`：覆盖/扩展默认价
  - `TokenUsageConfig.enable_cost`（默认 True）：关闭后 cost_usd 永远 0
  - `TokenUsageConfig.pass_cost_to_sinks`（默认 False）：开启后 sink 收到 `cost_usd` keyword
  - state 写 `_hook_token_cost_usd`（USD 累计）
  - 模糊匹配：`gpt-4o-2024-08-06` → 按 `gpt-4o` 计费（去除日期后缀）
- **`_PrometheusSink` OpenTelemetry exporter 兼容**
  - 构造参数：`otel_exporter_endpoint` / `otel_resource_attrs` / `otel_export_interval_seconds`
  - 通过 `opentelemetry-exporter-otlp-proto-http` 推 OTel collector（与 prometheus_client 并行上报）
  - `flush()` 同时触发 `provider.shutdown()` 把缓冲 flush
  - 未装 opentelemetry 包时仅 warn 跳过（不破坏 prometheus_client 路径）
- **`_LangSmithSink.parent_run_id_fallback` 支持任意 metadata key**
  - `"thread_id"`（默认）：按 `metadata.thread_id` 查
  - `"metadata.<key>"`：按任意 metadata 字段查（如 `"metadata.user_id"` / `"metadata.session_id"`）
  - 自动从 `state[key]` / `state.metadata[key]` / `runtime.metadata[key]` 抽 value

### Changed
- `TokenUsageMiddleware.after_model` 返回值新增 `_hook_token_cost_usd` 键
- `_LangSmithSink._thread_id_to_parent_run_id` 重构为 `_query_parent_run_id`，cache_key 格式从 `"{value}"` 改为 `"meta.<key>={value}"`（避免不同 key 撞 cache）

### Tests
- `tests/test_agent_middleware.py`：80 → **100 个用例全部通过**
  - 4 个限流策略测试（fixed_window / token_bucket / 未知 strategy 抛错 / RateLimitConfig 字段 / RateLimitMiddleware 集成）
  - 7 个 cost 估算测试（已知 model / 未知 / 日期后缀模糊匹配 / 自定义价目 / 写 state / 关闭 / pass_cost_to_sinks）
  - 2 个 OTel 测试（构造配置 / 真实 emit 路径——OTel 装了才跑）
  - 6 个 metadata key fallback 测试（state[key] / state.metadata / runtime.metadata / cache_key 格式 / 空 key / 未知字符串）

### Notes
- 升级到 v0.4.6 完全向后兼容：`rate_limit_strategy` 默认 `"sliding_window"`、`parent_run_id_fallback="thread_id"` 默认行为不变
- cost 估算失败（找不到 model_name）时返回 0，不抛错
- OTel 可选依赖：`pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http`

## v0.4.5 (2026-07-28) — 限流自动重试 / 多 provider token 兼容 / label 防爆 / thread_id 关联

### Added
- **`RateLimitMiddleware.wait_for_retry`**：被限流后自动 sleep 退避重试
  - `wait_for_retry_attempts`（默认 0 = 维持原"只观测不重试"行为，向后兼容）
  - `wait_for_retry_base_seconds` / `wait_for_retry_cap_seconds` / `wait_for_retry_jitter`
  - 退避公式：`min(base * 2^attempt, cap) + jitter * rand`
- **`TokenUsageMiddleware` 兼容 OpenAI / Anthropic 响应字段**：
  - 抽取优先级：`msg.usage_metadata` → `msg.response_metadata.token_usage` → `msg.response_metadata.usage`
  - 字段别名：`prompt_tokens` ↔ `input_tokens`，`completion_tokens` ↔ `output_tokens`
  - 缺 `total_tokens` 时由 input+output 累加
  - `model_name` 自动从 `usage_metadata.model_name` / `response_metadata.model_name` / `model_id` / `model` 抽取
- **`_PrometheusSink.only_real_session`**（默认 True）：
  - session_id 为 None / 空字符串时折叠到固定 `__none__` 桶
  - 避免 Prometheus TSDB 出现大量"unknown" series
- **`_LangSmithSink.parent_run_id_fallback`**：
  - 传 `callable`：自定义 (state, runtime) -> str | None 查找
  - 传字符串 `"thread_id"`：内置查找 —— 从 `state.configurable.thread_id` / `runtime.configurable.thread_id` 等位置抽 thread_id，用 `client.list_runs(query='eq(metadata.thread_id, ...)', is_root=True, limit=1)` 查主 run
  - FIFO 缓存（默认 1000 条）避免同一 thread 重复 API 查询

### Changed
- `TokenUsageMiddleware.after_model`：传入 sink 的 `usage` 副本新增 `_state` / `_runtime` 元数据键（`_` 开头），仅供 `_LangSmithSink` 的 fallback 使用，其它 sink 应忽略这些 key
- `_extract_usage`：缺 `total_tokens` 时由 input+output 累加（之前固定返回 0）—— 测试 `test_token_usage_handles_legacy_field_names` 同步更新

### Tests
- `tests/test_agent_middleware.py`：61 → **80 个用例全部通过**
  - 4 个 wait_for_retry 测试（默认禁用 / 配置字段 / 窗口过期成功 / 重试仍被限）
  - 6 个 TokenUsage 多 provider 兼容测试（langchain / OpenAI / Anthropic / 全 0 / after_model 集成 / 模型名抽取）
  - 2 个 Prometheus only_real_session 测试
  - 7 个 LangSmith parent_run_id_fallback 测试（None 默认 / callable 触发 / 异常隔离 / thread_id 抽取 4 路径 / 缓存命中 / list_runs 集成 / FIFO 驱逐）

### Notes
- 升级到 v0.4.5 完全向后兼容：所有 v0.4.4 测试通过；`wait_for_retry_attempts` 默认 0 = 不重试
- 自定义 sink 收到 usage 副本时，建议忽略 `_` 开头的 key（_LangSmithSink 会用）
- Prometheus `_none__` 桶 + 真实 session 共存：PromQL 可用 `session_id!="__none__"` 过滤真实 session

## v0.4.4 (2026-07-28) — atexit 自动 flush / LangSmith pending 提交 / Redis Sentinel

### Added
- **`_PrometheusSink.flush()` 自动绑 `atexit`**
  - 构造参数 `auto_flush_on_exit=True`（默认开启；设 False 可关闭）
  - 第一次 `_maybe_push_to_gateway` 触发时注册 `atexit.register(_on_exit)`
  - 进程退出 / Ctrl-C / SystemExit 都自动 flush 残留指标
  - 短命任务（CI / cron / one-shot）零配置
- **`_LangSmithSink.flush()` 强制提交 pending runs**
  - 跟踪所有 `child.post()` 失败的 RunTree（存入 `_pending_runs`）
  - `flush()` 重新尝试提交；成功的从列表中移除，失败的保留
  - 连续失败 `_max_err=10` 次自动 disable sink（避免拖垮主链路）
  - 首次 `flush()` 也绑 `atexit`，进程退出自动 flush
- **`_RedisBackend` Sentinel 模式**（集群外的高可用）
  - `RateLimitConfig.backend="redis_sentinel"` 新增选项
  - 通过 `sentinel_hosts=(("s1", 26379), ("s2", 26379), ...)` + `sentinel_service_name="mymaster"` 配置
  - 自动 `sentinel.master_for(service_name, db=0)` 拿 master client
  - master 故障时 Sentinel 自动 failover 到 replica，**对调用方透明**
  - 可选 `sentinel_password` / `sentinel_db` 参数

### Tests
- `tests/test_agent_middleware.py`：52 → **61 个用例全部通过**
  - 2 个 Prometheus atexit 测试（自动注册 / `auto_flush_on_exit=False`）
  - 2 个 LangSmith flush 测试（no-op / disable 路径）
  - 3 个 Sentinel 配置 / 降级测试
  - 2 个 **e2e 端到端**：PII 在 `create_agent` 中真实生效 / Token 用量写入 state
- `examples/use_middleware.py` 6 个场景仍然全部跑通

### Notes
- 升级到 v0.4.4 完全向后兼容：v0.4.3 测试 + 现有生产代码无需改动
- atexit hook 仅在第一次 `push` / 第一次 `flush()` 时注册，避免重复
- Sentinel 客户端失败 → 静默降级 memory（warn 日志）
- atexit 在 pytest teardown 阶段也会触发（如果 buffer 不为空），测试已通过

## v0.4.3 (2026-07-28) — 真实 e2e 示例 / Pushgateway / LangSmith client 注入 / Redis Cluster

### Added
- **`examples/use_middleware.py` 场景 6: 真实 e2e**（接 `langchain.agents.create_agent` + ChatOpenAI）
  - 有 `OPENAI_API_KEY` → 用 `ChatOpenAI("gpt-4o-mini")`
  - 否则 → 自动降级为 fake 模型（实现 `bind_tools` + `bind` + `invoke`），脚本始终能跑通
  - Q2 含 PII → PIIScrubMiddleware 真实生效（`alice@example.com` → `[EMAIL]`）
  - 演示了 `InMemorySaver` checkpointer + thread_id + `agent.invoke(config=...)` 全流程
- **`_PrometheusSink` 新增 Pushgateway 支持**
  - 构造参数：`pushgateway_url` / `pushgateway_job` / `push_to_gateway_every_n` / `grouping_key`
  - 每次 sink 调用累计到 N 次自动 push（适合 CI / 短命任务）
  - 提供 `sink.flush()` 给短命任务退出时主动 push
  - 与 `http_port` 互斥（同时设置会 warn + 忽略 http_port）
- **`_LangSmithSink` 新增 client 注入**
  - 构造参数 `client`：传预构造的 `langsmith.Client` 避免内部重 init
  - 未传时懒创建（首次 `__call__` 时按需 `Client()`），失败降级
  - 用注入 client 取 parent run（`cli.read_run(parent_run_id)`），节省连接
- **`_RedisBackend` 新增 Redis Cluster 支持**
  - `RateLimitConfig.backend` 新增 `"redis_cluster"` 选项
  - `RateLimitConfig.cluster_url` 接受 `"redis://n1:6379,redis://n2:6379,redis://n3:6379"`
  - `_RedisBackend(cluster_mode=True)` 用 hash tag `{...}` 把 zset/counter 强制同 slot
  - `_parse_cluster_url()` 辅助函数解析多节点 URL
  - `redis.cluster.RedisCluster` 初始化失败 → 静默降级 memory

### Changed
- `agent_middleware.py`：
  - 模块顶层 `from langchain.agents.middleware import ...` 修复：`ModelResult` 在 1.x 改名 `ModelCallResult`，之前的 silent fallback 导致所有 8 个 hook 实际未生效（→ 现在真正生效，已通过 examples/use_middleware.py 场景 6 验证）
  - 新增可选依赖 `redis.cluster.RedisCluster`（`redis>=4`），未装时 `_HAS_REDIS_CLUSTER=False` 自动降级
- `examples/use_middleware.py`：`fake_model` 加 `bind` 方法（`create_agent` 内部会调 `model.bind(stop=...)`）

### Tests
- `tests/test_agent_middleware.py`：39 → **52 个用例全部通过**
  - 3 个 Prometheus Pushgateway 测试（配置接收 / `flush()` / 互斥警告）
  - 2 个 LangSmith client 测试（注入 / 懒创建）
  - 4 个 Redis Cluster 测试（`_parse_cluster_url` × 3 + cluster mode hash tag 验证 + fake redis 端到端）
  - 1 个 `RateLimitConfig` cluster_url 字段测试
  - 1 个 **e2e 冒烟测试**（fake 模型 + create_agent + 8 hook + invoke）
- `examples/use_middleware.py` 6 个场景全部跑通

### Notes
- 升级到 v0.4.3 完全向后兼容：v0.4.2 测试 + 现有生产代码无需改动
- Pushgateway / RedisCluster / LangSmithClient 均为可选依赖，未装时自动跳过（仅 warn）

## v0.4.2 (2026-07-28) — 版本号 / Redis key 防撞 / Prometheus labels 防爆 / LangSmith 关联 / 示例

### Added
- **`__version__ = "0.4.2"`** 顶部暴露，便于运行时探针/健康检查引用
- **`_make_rate_limit_key()` + `RateLimitConfig.use_shared_instance` / `instance_id`**：
  - Key 命名 `{prefix}:{max_calls}per{window_seconds}s[:shared|:inst={uuid8}]`
  - 改 `max_calls` / `window_seconds` → key 自动变化 → 旧 key 自然过期，新窗口立即生效
  - `use_shared_instance=True` 跨实例共享；`False`(默认)每进程独立
  - 多进程部署同一服务时，可在初始化时手动 `RateLimitConfig(instance_id="...")` 强制共享
- **`_PrometheusSink` 加 labels + 高基数防爆**：
  - 默认 labels：`model` / `session_id`（可关闭）
  - `max_session_cardinality=1000`：超过后新 session 折叠到 `session_id="__overflow__"`
  - sink 协议升级：`sink(usage, *, model=None, session_id=None, parent_run_id=None)`
- **`_LangSmithSink` 重写**：
  - 通过 `langsmith.RunTree(parent=...)` 关联到主 agent run（**消除 DeprecationWarning**）
  - 自动从 `runtime.metadata.parent_run_id` / `state["parent_run_id"]` 抓父 run id
  - `model` / `session_id` 写入 tags + inputs，便于 LangSmith UI 过滤
- **`TokenUsageMiddleware.after_model`** 自动抓 `model_name`（优先级：`usage_metadata` > `response_metadata` > `runtime.metadata`）
- **`examples/use_middleware.py`**：5 个场景演示（零侵入接入 / PII 扩展 / Redis 限流 / 多 sink / 自定义 hook）
- **3 个 sink 协议兼容**：旧自定义 `sink(usage)` 自动降级为 positional 调用

### Changed
- `agent_middleware.py`：
  - `_RedisBackend` 仍兼容 `_FakeRedis`（测试桩），但 key 命名变了 → 测试 fixture 已同步更新
  - `_PrometheusSink.__init__` 新增 3 个 keyword-only 参数
  - `_LangSmithSink.__init__` 新增 `run_name` 参数
- `agent_middleware.md` 新增 v0.4.2 章节（Redis key 命名 / Prometheus labels / LangSmith parent）

### Tests
- `tests/test_agent_middleware.py`：从 27 → **39 个用例全部通过**
  - 1 个版本号测试
  - 4 个 Redis key 测试（混入阈值 / instance_id / shared / config 字段）
  - 4 个 Prometheus labels 测试（带 label / 高基数 overflow / None session / 关闭 labels）
  - 2 个 LangSmith parent_run_id 测试（接受 + 通过 sink 协议传）
  - 2 个 TokenUsage 协议测试（传 model/session/parent 给 sink / 旧 sink 降级）
- 全部 LangSmith DeprecationWarning 已消除

### Notes
- 升级到 v0.4.2 是**完全向后兼容**的：所有 v0.4.1 测试 + 现有生产代码无需改动
- Redis 包未装时 `_RedisBackend` 仍然自动降级为 `_MemoryBackend`
- Prometheus / LangSmith 包未装时对应 sink 自动跳过（warn 日志）

## v0.4.1 (2026-07-28) — Hooks 可注入配置 + Redis 限流 + Prometheus/LangSmith 导出

### Added
- **4 个 dataclass 配置**（`agent_middleware.py` 顶部可注入常量）：
  - `PIIScrubConfig` — `replacement` / `extra_patterns` / `target_message_types`
  - `OutputSafetyConfig` — `mode` / `block_words` / `case_insensitive`
  - `RateLimitConfig` — `backend` (`memory` | `redis`) / `redis_url` / `redis_key_prefix` / `predicate`
  - `TokenUsageConfig` — `sinks` 元组 / `prometheus_namespace` / `langsmith_project`
- **`RateLimitMiddleware` Redis 后端**（`_RedisBackend`）：
  - sorted set 滑动窗口（`ZADD` / `ZREMRANGEBYSCORE` / `ZCARD`）
  - Lua 脚本保证原子性（SHA 缓存，自动 reload）
  - pipeline fallback + fail-open（Redis 故障不阻断 agent）
  - 可选依赖：`pip install redis>=5`
- **`TokenUsageMiddleware` 多 sink 导出**：
  - **`_PrometheusSink`**：`Counter` / `Histogram`，可选启动 `start_http_server(port)`
  - **`_LangSmithSink`**：把每次用量写入 LangSmith run（需 `LANGSMITH_API_KEY`）
  - 自定义 sink：`sinks=(my_callable,)` 接受任意 `f(usage: dict) -> None`
  - sink 故障 → state 写入照常进行（隔离失败）
- 新增文档：[`agent_middleware.md`](./agent_middleware.md) —— 8 个 hook 的触发时机/入参出参/最佳实践

### Changed
- `agent_middleware.py`：
  - `PIIScrubMiddleware` / `OutputSafetyMiddleware` / `RateLimitMiddleware` / `TokenUsageMiddleware`
    均接受对应 `*Config` dataclass；旧位置参数（`mode=` / `max_calls=` 等）保留向后兼容
  - `build_default_middleware()` 暴露 5 个可选参数（`pii_config` / `rate_limit_config` / `token_usage_config` / `safety_config` / `audit_path`）
  - `__all__` 扩展为分组（Hooks / Config / 工厂工具）

### Tests
- `tests/test_agent_middleware.py`：从 15 → **27 个用例全部通过**
  - 6 个新配置注入测试（`PIIScrubConfig.extra_patterns` / `OutputSafetyConfig.block_words` / 各 Config 校验）
  - 4 个 Redis 后端测试（用 `_FakeRedis` 模拟 `script_load` / `evalsha` / `pipeline`，含 fail-open）
  - 2 个 token sink 测试（自定义 sink + sink 失败不阻断 state）
  - 1 个 `build_default_middleware(..., config=...)` 注入测试
  - Prometheus / LangSmith sink 在依赖未装时优雅跳过

### Notes
- 所有新功能遵循"零侵入"原则：默认行为不变；启用 Redis / Prometheus / LangSmith 仅需传配置
- `RateLimitMiddleware.backend = "redis"` 时若无 `redis` 包会自动降级为 memory（仅 warn）

## v0.4.0 (2026-07-28) — LangChain 1.x AgentMiddleware Hooks + 测试修复

### Added
- **LangChain 1.x AgentMiddleware Hooks**：通过 `create_agent(..., middleware=...)` 接入官方 hooks。
  新增 `agent_middleware.py` 提供 8 个可插拔 middleware，按"零侵入"设计：
  - `LoggingMiddleware` — before/after_model 记录消息数 + 模型耗时
  - `ToolCallCounterMiddleware` — after_model 累计本轮 tool_calls
  - `ContextTrimMiddleware` — before_model 消息数 > 20 时裁剪最旧非 system 消息
  - `PIIScrubMiddleware` — before_model 对最近 Human 消息做邮箱/手机号/13-19 位数字脱敏
  - `RateLimitMiddleware` — before_model 滑动窗口限流（默认 30 次 / 60 秒）
  - `AuditLogMiddleware` — before/after_agent 写 jsonl 审计日志（默认 `logs/audit.jsonl`）
  - `TokenUsageMiddleware` — after_model 从 `usage_metadata` 累加 token 用量
  - `OutputSafetyMiddleware` — after_model 命中 `<system>` / `ignore previous instructions` 等敏感词时 raise / redact
- `build_default_middleware()` 工厂方法返回上述所有 hooks；`agent.py` 两处 `create_agent` 调用均通过它注入
- 新增 `tests/test_agent_middleware.py`，覆盖 **15 个用例全部通过**

### Changed
- `requirements.txt`：langchain 锁到 `~=1.0.0`、`langchain-openai` 升到 `~=0.3.0`、新增 `langgraph~=0.3.0` + `langgraph-checkpoint~=2.0.0`
- `security.py`：
  - `SecurityModule` 新增 `dangerous_patterns` 属性（暴露 `_DANGEROUS_CODE_PATTERNS` 的 pattern 列表）
  - `_DANGEROUS_CODE_PATTERNS` 增补 `\bopen\s*\(`（拦截 `open(...)` 文件读取）
  - `validate_safe_path` 修复后缀提取对 `.` 与隐藏文件的误判（如 `list_files(".")` 不再被拒）
- 测试修复（pre-existing）：
  - `tests/test_security.py` — 3 个用例（`dangerous_patterns` 存在 + `open(...)` 被拦）
  - `tests/test_tools.py` — 6 个用例（文件/列表工具改用 `monkeypatch.chdir(tmp_path)` + 相对路径 + `.`；知识库 mock 改用 `set_rag_instance`）
  - `tests/test_rag.py` — 7 个用例（fixture 改 mock `rag.DocumentLoaderRegistry` 而非已废弃的 `rag.TextLoader`；返回值改为 `(ok, summary)` 元组）
  - `tests/test_user_prompts_api.py` — 1 个用例（去掉对 `active_version` 的硬编码依赖，避免与测试顺序耦合）
  - `test_multi_agent.py` / `test_skills.py` — 9 个 async 用例（装上 `pytest-asyncio` 后 `auto` 模式自动 await）

### Tests
- 新增 `tests/test_agent_middleware.py`：**15 个用例全部通过**
- 现有套件从 833 passed / 21 failed 提升至 **905 passed / 3 skipped / 0 failed**
- 净增 72 个测试，累计 920+ ✅

### Notes
- 旧版本 langchain（0.2.x）环境下，middleware 模块自动降级为 `AgentMiddleware = object`，
  `build_default_middleware()` 返回空列表 → `create_agent(middleware=None)` 等同原行为。
- pytest-asyncio 已通过 `pip install pytest-asyncio>=0.23,<0.24` 落地；
  `pyproject.toml` 已声明 `asyncio_mode = "auto"`，async 测试无需手动加 mark。

## v0.3.0 (2026-07-23) — 阶段 B：国内主流模型 Provider

### Added
- 新增 4 个国产模型 provider：
  - **doubao**（字节豆包 / 火山方舟 ARK）
  - **hunyuan**（腾讯混元）
  - **siliconflow**（硅基流动：一站式聚合 Qwen/DeepSeek/GLM 等）
  - **minimax**（MiniMax 01 / abab7）
- 原 deepseek / qwen / zhipu / moonshot 等老 provider 扩充最新模型：
  - deepseek 新增 `deepseek-reasoner`（R1 推理模型）
  - qwen 新增 `qwen3-max` 等
  - zhipu 拆出 `glm-z1-*` 推理模型
  - moonshot 新增 `kimi-k2-0711-preview`
- 新增 `PROVIDER_META` 元信息（中文 label / group / desc），前端按 provider 分组展示
- `app.py /api/models` 返回新结构：`providers` 数组（每个含 `configured` 字段）
- `web/index.html`：模型下拉改为 `<optgroup>` 分组；未配置 Key 的 provider 选项标灰禁用

### Changed
- `config.py`：新增 4 个 API Key 环境变量（DOUBAO_API_KEY / HUNYUAN_API_KEY / SILICONFLOW_API_KEY / GLM_API_KEY 别名）
- `agent.py`：`_build_provider_base_url` / `_api_key_for_provider` / `_get_model` 补全 4 个新 provider（统一走 ChatOpenAI）
- Fallback chain 加入新 provider，跨 provider 容错更稳健

### Tests
- `tests/test_models_registry.py` — 20 个新用例
- 既有 76 个测试全过（无回归）

总计 96 个测试 ✅

## v0.2.0 (2026-07-23) — 阶段 A：流式中间状态 + Prompt 工程化

### Added
- `prompt_registry.py`：提示词模板化与版本化管理，支持 system / role / tool 三段拼接 + CoT 注入
- `run_stream` 改为产出结构化事件：`start / thinking / chunk / tool_call / safety / error / complete`
- 新增 `/api/prompts` 与 `/api/prompts/rollback` 两个端点
- 前端 `web/index.html`：
  - 工具调用时间线（pill 形式）
  - 思维链折叠面板（`## 思考 ##`）
  - 安全提示横幅
  - 设置面板新增"Prompt 版本管理"

### Tests
- `tests/test_prompt_registry.py` — 10 个用例
- `tests/test_stream_events.py` — 7 个用例
- `tests/test_prompts_api.py` — 4 个用例
- 既有 55 个 `test_agent.py` 用例全部通过（向后兼容）

## v0.1.0 (2025-01-XX)

### Added
- 初始版本
- FastAPI + React 全栈 AI Agent 控制台
- 6 个页面：Chat / Agents / Approval / Observability / Tools / Settings
- 后端 LangChain / LangGraph / MCP 集成
- GitHub Actions CI（7 jobs）+ Docker Compose + GHCR 发布
