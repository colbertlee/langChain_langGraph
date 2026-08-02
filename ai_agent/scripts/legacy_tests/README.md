# scripts/legacy_tests/ — 归档目录（Day 4-5）

本目录下是从早期开发期沉淀的快速验证脚本，**不会**被 pytest 自动收集
（不在 `tests/` 下，也未注册为 `pytest` 测试）。

- 已迁移到正式 `tests/` 的：`test_agent.py`、`test_simple.py` 等
- 调试残留（一次性脚本）：`test_debug.py`、`test_gitee*.py`、`test_github_tools.py`
- 后续：在下一个 release 时清理本目录（保留 `test_resilience_e2e.py` 一份，归档进 examples/）

## 使用方式

手动跑（不通过 pytest）：

```bash
python scripts/legacy_tests/test_resilience_e2e.py
```

CI 不会主动跑这里。
