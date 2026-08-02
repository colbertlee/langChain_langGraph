# evals/ — AI Agent 评测（Day 13-14）

## 跑

```bash
# 跑单个分类
python -m evals.runner run --case intent_routing
python -m evals.runner run --case safety
python -m evals.runner run --case calculator

# 跑全部
python -m evals.runner run --all

# 历史
python -m evals.runner history
python -m evals.runner history --limit 20

# 对比
python -m evals.runner diff 20250620_120000 20250620_180000
```

## 加入新维度

1. 在 ``cases/<name>.json`` 加用例集：
    ```json
    [{"name": "...", "category": "<new>", "input": "...", "expected_...": ...}]
    ```
2. 在 ``builtin_runners.py`` 注册 runner：
    ```python
    @EvalRegistry.register("<new>")
    def run_xxx(case): ...
    ```
3. ``python -m evals.runner run --case <new>`` 验证

## 设计

- 纯本地：默认不调用 LLM（CI 稳定）；
- 用例 schema 由各 category 自定义，runner 负责解释；
- 历史记录落到 ``runs/<timestamp>/``；
- 失败 → 非零退出（CI 报警）。
