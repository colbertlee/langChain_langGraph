"""
业务 metrics 数据源（Day 25）。

提供业务面板数据：chat 数 / user 数 / revenue。数据源 JSON 在：
- ``tests-archive/business_metrics.json`` （默认）

格式::

    [
      {"ts": "2026-07-26T00:00", "chat_count": 1234, "user_count": 567, "revenue_usd": 89.12},
      {"ts": "2026-07-27T00:00", "chat_count": 1500, "user_count": 600, "revenue_usd": 110.00},
      ...
    ]

字段说明：
- ``ts``: ISO 时间戳（必填）
- ``chat_count``: 当日 chat 总数（int）
- ``user_count``: 累计用户数（int）
- ``revenue_usd``: 当日 revenue（float，美元）
- 其他字段会被忽略

提供 4 种聚合：
- ``sum``（默认）：每日 / 周 / 月求和（适合 chat_count / revenue）
- ``last``：取最后一条（适合 user_count 这种累计值）
- ``max``：取最大值
- ``avg``：取平均

CLI::

    # 用例
    python tools/business_metrics.py --show          # 打印当前数据
    python tools/business_metrics.py --aggregate    # 按日聚合
    python tools/business_metrics.py --inject mock  # 注入 mock 数据（演示用）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


DEFAULT_PATH = ROOT / "tests-archive" / "business_metrics.json"

# 哪些字段用 sum 聚合（流量类）
SUM_FIELDS = {"chat_count", "revenue_usd"}
# 哪些字段用 last 聚合（累计类）
LAST_FIELDS = {"user_count"}


def load(path: Optional[Path] = None) -> List[dict]:
    """读业务 metrics。"""
    p = path or DEFAULT_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return data
    except Exception:
        return []


def save(data: List[dict], path: Optional[Path] = None) -> None:
    """写业务 metrics。"""
    p = path or DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def aggregate_daily(data: List[dict]) -> List[dict]:
    """按日聚合：chat_count / revenue_usd 求和；user_count 取最后一条。"""
    if not data:
        return []

    buckets: dict = {}
    for row in data:
        ts = row.get("ts", "")
        # 抽日期部分 YYYY-MM-DD
        day = ts[:10] if len(ts) >= 10 else "unknown"
        if day not in buckets:
            buckets[day] = {"ts": day, "_sum_fields": {}, "_last_fields": {}}
        b = buckets[day]
        # sum 字段
        for f in SUM_FIELDS:
            if f in row:
                b["_sum_fields"][f] = b["_sum_fields"].get(f, 0) + row[f]
        # last 字段（覆盖）
        for f in LAST_FIELDS:
            if f in row:
                b["_last_fields"][f] = row[f]
        # 其他字段保留

    out = []
    for day in sorted(buckets.keys()):
        b = buckets[day]
        merged = {"ts": day}
        merged.update(b["_sum_fields"])
        merged.update(b["_last_fields"])
        out.append(merged)

    return out


def inject_mock(n: int = 7) -> List[dict]:
    """生成 n 天的 mock 数据（演示用）。"""
    import random
    random.seed(42)
    base = 100
    data = []
    for i in range(n):
        day = f"2026-07-{20 + i:02d}"
        data.append({
            "ts": f"{day}T00:00",
            "chat_count": base + random.randint(50, 200),
            "user_count": 50 + i * 3,
            "revenue_usd": round(random.uniform(50, 200), 2),
        })
    return data


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="business_metrics")
    parser.add_argument("--path", help="数据 JSON 路径")
    parser.add_argument("--show", action="store_true", help="打印当前数据")
    parser.add_argument("--aggregate", action="store_true", help="按日聚合后打印")
    parser.add_argument("--inject", help="注入 mock 数据：mock=<n_days> 或 mock")

    args = parser.parse_args(argv)

    path = Path(args.path) if args.path else None

    if args.inject:
        if args.inject == "mock" or args.inject.startswith("mock="):
            try:
                n = int(args.inject.split("=")[1]) if "=" in args.inject else 7
            except (ValueError, IndexError):
                n = 7
            data = inject_mock(n)
            save(data, path)
            print(f"[ok] injected {n} days mock data to {path or DEFAULT_PATH}")
            return 0

    data = load(path)
    if args.aggregate:
        data = aggregate_daily(data)

    if args.show or not args.aggregate:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(json.dumps(data, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())