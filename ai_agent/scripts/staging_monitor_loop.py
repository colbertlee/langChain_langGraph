"""
Staging 24h 监控循环（v2.0 slim）

每 5 分钟跑一次 tests/test_staging_monitor.py（15 项核心探针），
把结果追加到 logs/staging/probe.log，失败时调用 webhook。

用法：
    python scripts/staging_monitor_loop.py            # 默认 5 min 间隔，永久循环
    python scripts/staging_monitor_loop.py --once     # 只跑一次
    python scripts/staging_monitor_loop.py --interval 60  # 60 秒间隔
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "staging"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "probe.log"
JUNIT_DIR = LOG_DIR / "junit"
JUNIT_DIR.mkdir(parents=True, exist_ok=True)

ALERT_WEBHOOK = os.environ.get("STAGING_ALERT_WEBHOOK", "")  # 可选


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def run_probe(once: bool = False) -> int:
    """跑一次探针，返回 exit code。"""
    junit_path = JUNIT_DIR / f"probe-{now_ts()}.xml"
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_staging_monitor.py",
        "--no-cov", "-q",
        "--timeout=60",
        f"--junitxml={junit_path}",
    ]
    print(f"[{now_iso()}] running: {' '.join(cmd)}", flush=True)
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    log_line = json.dumps({
        "ts": now_iso(),
        "exit": proc.returncode,
        "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-300:] if proc.stderr else "",
        "junit": str(junit_path),
    }, ensure_ascii=False)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")

    status = "PASS" if proc.returncode == 0 else f"FAIL(exit={proc.returncode})"
    print(f"[{now_iso()}] {status}", flush=True)
    if proc.returncode != 0:
        print(f"  stderr: {proc.stderr[-300:] if proc.stderr else ''}", flush=True)
        if ALERT_WEBHOOK:
            _fire_webhook(status, junit_path)

    return proc.returncode


def _fire_webhook(status: str, junit_path: Path) -> None:
    """触发 webhook 告警（可选）。"""
    try:
        import urllib.request
        payload = json.dumps({
            "text": f"[ai_agent staging] {status} at {now_iso()}",
            "junit": str(junit_path),
        }).encode("utf-8")
        req = urllib.request.Request(
            ALERT_WEBHOOK,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        print(f"[{now_iso()}] webhook fired", flush=True)
    except Exception as e:
        print(f"[{now_iso()}] webhook failed: {e}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="只跑一次")
    p.add_argument("--interval", type=int, default=300, help="循环间隔秒数（默认 300）")
    args = p.parse_args()

    print(f"=== staging monitor loop ===")
    print(f"ROOT: {ROOT}")
    print(f"LOG_FILE: {LOG_FILE}")
    print(f"interval: {args.interval}s")
    print(f"webhook: {ALERT_WEBHOOK or '(none)'}")
    print(f"============================")

    if args.once:
        return run_probe(once=True)

    while True:
        try:
            run_probe()
        except Exception as e:
            print(f"[{now_iso()}] probe error: {e}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())