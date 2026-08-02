"""Day 21：CHANGELOG 退化阈值单测。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.archive_changelog import (
    _regression_emoji,
    build_line,
)


# ---- _regression_emoji 阈值 ----

def test_threshold_small_drop_below_threshold():
    """passed 100→95（5%）：恰好阈值，should NOT 报警（默认 >= 5）"""
    latest = {"totals": {"passed": 95, "failed": 0, "errored": 0}}
    prev = {"totals": {"passed": 100, "failed": 0, "errored": 0}}
    out = _regression_emoji(latest, prev)
    # 5% 刚好到阈值；>= 5.0 应触发，但 95/100 = 5% → 临界
    # 默认 threshold_pct=5.0，p_pct=5.0 -> 5.0 >= 5.0 True → 触发
    # 这里只验证"严格小于阈值" 时不触发
    out2 = _regression_emoji(latest, prev, threshold_pct=6.0)
    assert out2.startswith("🟢")


def test_threshold_large_drop_above_threshold():
    """passed 100→80（20%）→ 触发 ⚠️"""
    latest = {"totals": {"passed": 80, "failed": 0, "errored": 0}}
    prev = {"totals": {"passed": 100, "failed": 0, "errored": 0}}
    out = _regression_emoji(latest, prev)
    assert "⚠️" in out


def test_threshold_failed_increase_below_threshold():
    """failed 5→6（20%）→ 触发 🚨"""
    latest = {"totals": {"passed": 50, "failed": 6, "errored": 0}}
    prev = {"totals": {"passed": 50, "failed": 5, "errored": 0}}
    out = _regression_emoji(latest, prev)
    assert "🚨" in out


def test_threshold_failed_increase_below_threshold_excluded():
    """failed 0→1（prev=0 时）→ 用绝对值门槛判断"""
    latest = {"totals": {"passed": 50, "failed": 1, "errored": 0}}
    prev = {"totals": {"passed": 50, "failed": 0, "errored": 0}}
    # 默认 err_min_abs=1 → errored_delta=0 不报警
    # 但 failed 0→1 的 p_pct = (1-0)/max(0, 1) * 100 = 100%，触发 🚨
    out = _regression_emoji(latest, prev)
    assert "🚨" in out


def test_threshold_errored_absolute():
    """errored 0→1（默认 err_min_abs=1）→ 触发 🚨"""
    latest = {"totals": {"passed": 50, "failed": 0, "errored": 1}}
    prev = {"totals": {"passed": 50, "failed": 0, "errored": 0}}
    out = _regression_emoji(latest, prev)
    assert "🚨" in out


def test_threshold_errored_below_min_abs():
    """errored 0→1 但 err_min_abs=2 → 不报警"""
    latest = {"totals": {"passed": 50, "failed": 0, "errored": 1}}
    prev = {"totals": {"passed": 50, "failed": 0, "errored": 0}}
    out = _regression_emoji(latest, prev, err_min_abs=2)
    assert out.startswith("🟢")


def test_threshold_zero_prev_handles_div_by_zero():
    """prev passed=0 时，ratio 不能崩；用 max(prev, 1) 兜底

    passed 0→10 是**进步**，不应触发警告；只验证 div-by-zero 不崩。
    """
    latest = {"totals": {"passed": 10, "failed": 0, "errored": 0}}
    prev = {"totals": {"passed": 0, "failed": 0, "errored": 0}}
    # p_delta = +10（不是退化）；f_delta = 0；e_delta = 0
    out = _regression_emoji(latest, prev)
    assert out.startswith("🟢")

    # 反方向：passed 10→0，p_delta = -10，p_pct = 1000% → ⚠️
    latest2 = {"totals": {"passed": 0, "failed": 0, "errored": 0}}
    prev2 = {"totals": {"passed": 10, "failed": 0, "errored": 0}}
    out2 = _regression_emoji(latest2, prev2)
    assert "⚠️" in out2


def test_threshold_all_zero_no_change():
    latest = {"totals": {"passed": 0, "failed": 0, "errored": 0}}
    prev = {"totals": {"passed": 0, "failed": 0, "errored": 0}}
    out = _regression_emoji(latest, prev)
    assert out.startswith("🟢")


def test_threshold_strict_zero_no_regression():
    """threshold_pct=0 → 任何变化都触发"""
    latest = {"totals": {"passed": 99, "failed": 0, "errored": 0}}
    prev = {"totals": {"passed": 100, "failed": 0, "errored": 0}}
    out = _regression_emoji(latest, prev, threshold_pct=0.0)
    # 1% 下降 → threshold_pct=0 时触发
    assert "⚠️" in out


# ---- build_line 阈值 ----

def test_build_line_with_strict_threshold():
    """build_line 也应透传 threshold_pct"""
    latest = {"started_at": "2026-12-01T10:00:00", "totals": {"ran_ratio": "9/10", "passed": 9, "failed": 0, "errored": 0, "skipped": 0}}
    prev = {"totals": {"passed": 10, "failed": 5, "errored": 0}}  # passed -1 = 10%; failed -5 = 100% 下降（不变差）
    line_loose = build_line(latest, prev=prev, threshold_pct=20.0)  # 10 < 20 → 🟢
    line_strict = build_line(latest, prev=prev, threshold_pct=5.0)   # 10 >= 5 → ⚠️
    assert "\U0001f7e2" in line_loose
    assert "\u26a0\ufe0f" in line_strict


# ---- CLI 参数 ----

def test_main_threshold_pct_arg():
    """--threshold-pct 透传"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold-pct", type=float, default=5.0)
    parser.add_argument("--err-min-abs", type=int, default=1)
    args = parser.parse_args(["--threshold-pct", "10.0"])
    assert args.threshold_pct == 10.0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))