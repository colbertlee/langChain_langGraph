"""doctor.py 单元测试（Day 10 回归用）。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from doctor import (
    CheckResult,
    run_doctor,
    print_human,
    print_json,
    _check_python_version,
    _check_required_packages,
    _check_provider_keys,
    _check_writable_dirs,
    _check_chromadb,
    _check_sqlite_checkpointer,
    _check_mcp_config,
    _check_provider_models,
)


# ---- 结构 ----

def test_check_result_to_dict():
    r = CheckResult(name="x", status="ok", message="hello", details={"a": 1})
    d = r.to_dict()
    assert d["name"] == "x"
    assert d["status"] == "ok"
    assert d["details"]["a"] == 1


# ---- 各 check 单独跑 ----

def test_python_version_always_ok_or_fail(monkeypatch):
    """Python 版本要么 OK 要么 FAIL，永远不会抛异常。"""
    r = _check_python_version()
    assert r.status in ("ok", "fail")
    assert r.name == "python"


def test_required_packages_returns_check_result():
    r = _check_required_packages()
    assert r.status in ("ok", "fail")
    assert "details" in vars(r)


def test_provider_keys_check_works():
    r = _check_provider_keys()
    # 当前环境可能 ok / warn / fail，但结构合法
    assert r.status in ("ok", "warn", "fail")


def test_writable_dirs_check():
    r = _check_writable_dirs()
    # 当前项目目录应可写
    assert r.status in ("ok", "fail")


def test_chromadb_check():
    r = _check_chromadb()
    assert r.status in ("ok", "warn", "fail")


def test_sqlite_checkpointer_check():
    r = _check_sqlite_checkpointer()
    assert r.status in ("ok", "warn", "fail")


def test_mcp_config_check_handles_missing():
    r = _check_mcp_config()
    # 即使 mcp_config.json 不存在也应返回 ok
    assert r.status in ("ok", "warn", "fail")


def test_provider_models_check():
    r = _check_provider_models()
    assert r.status in ("ok", "warn", "fail")


# ---- 整体 ----

def test_run_doctor_returns_list():
    results = run_doctor()
    assert isinstance(results, list)
    assert len(results) >= 5  # 默认 8 个 check
    for r in results:
        assert r.name
        assert r.status in ("ok", "warn", "fail")


def test_run_doctor_with_custom_check():
    def custom_check():
        return CheckResult("custom", "ok", "all good")

    results = run_doctor([custom_check])
    assert results == [CheckResult("custom", "ok", "all good")]


def test_run_doctor_handles_check_exception():
    def boom():
        raise RuntimeError("explode")

    results = run_doctor([boom])
    assert len(results) == 1
    assert results[0].status == "fail"
    assert "explode" in results[0].message


# ---- 输出形态 ----

def test_print_json_outputs_valid_json(capsys):
    results = [
        CheckResult("a", "ok", "msg"),
        CheckResult("b", "fail", "bad", fix="do this"),
    ]
    rc = print_json(results)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["name"] == "a"
    # 有 FAIL → 退出 1
    assert rc == 1


def test_print_json_all_ok_returns_zero(capsys):
    results = [CheckResult("a", "ok", "msg"), CheckResult("b", "warn", "msg")]
    rc = print_json(results)
    assert rc == 0  # warn 不算 fail


def test_print_human_returns_code(capsys):
    results = [
        CheckResult("a", "ok", "ok msg"),
        CheckResult("b", "warn", "warn msg"),
        CheckResult("c", "fail", "fail msg", fix="repair"),
    ]
    rc = print_human(results)
    out = capsys.readouterr().out
    assert "[OK]" in out
    assert "[WARN]" in out
    assert "[FAIL]" in out
    assert "repair" in out
    assert rc == 1  # 有 fail


def test_print_human_no_fail_returns_zero(capsys):
    results = [CheckResult("a", "ok", "x"), CheckResult("b", "warn", "y")]
    rc = print_human(results)
    assert rc == 0


# ---- main 入口 ----

def test_main_no_args_runs(capsys):
    from doctor import main
    rc = main([])
    out = capsys.readouterr().out
    assert "ai-agent doctor" in out or "doctor" in out
    # 退出码可能是 0 或 1，取决于当前环境；不应抛
    assert rc in (0, 1)


def test_main_json_outputs_json(capsys):
    from doctor import main
    rc = main(["--json"])
    out = capsys.readouterr().out.strip()
    # 输出必须能解析为 JSON
    json.loads(out)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))
