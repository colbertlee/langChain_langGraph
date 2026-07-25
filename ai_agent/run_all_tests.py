"""
一键跑所有测试套件
"""

import subprocess
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


TEST_FILES = [
    ("negotiation", "test_negotiation.py"),
    ("negotiation_integration", "test_negotiation_integration.py"),
    ("reliability", "test_reliability.py"),
    ("observability", "test_observability.py"),
    ("capability", "test_capability.py"),
    ("task_intent", "test_task_intent.py"),
    ("streaming_permission", "test_streaming_permission.py"),
    ("hitl_webui", "test_hitl_webui.py"),
    ("planner_memory", "test_planner_memory.py"),
    ("p2_extra", "test_p2_extra.py"),
    ("p3_all", "test_p3_all.py"),
    ("full_integration", "test_full_system_integration.py"),
]


def main():
    print("\n" + "#"*70)
    print(f" Running {len(TEST_FILES)} test suites")
    print("#"*70 + "\n")

    start = time.time()
    passed = []
    failed = []

    for name, fname in TEST_FILES:
        path = os.path.join(os.path.dirname(__file__), fname)
        if not os.path.exists(path):
            print(f"  [{name}] SKIP - {fname} not found")
            continue
        print(f"  [{name}] Running {fname}...", flush=True)
        try:
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-u", fname],
                capture_output=True,
                text=True,
                timeout=180,
                cwd=os.path.dirname(__file__),
            )
            # 找 "All X tests passed" 或 "passed" 标志
            output = result.stdout + result.stderr
            if result.returncode == 0:
                # 提取数字
                import re
                # 多种模式：All X tests passed / Integration tests done / All tests done
                m = re.search(r"All (\d+)/?(\d*) tests? passed", output)
                if m:
                    n = int(m.group(1))
                    print(f"    PASS ({n} tests)")
                    passed.append((name, n))
                elif "All tests done" in output or "Integration tests done" in output:
                    # 找 PASS / OK 计数
                    n_passes = len(re.findall(r"\[OK\]", output)) + len(re.findall(r"PASS -", output))
                    print(f"    PASS ({n_passes} tests)")
                    passed.append((name, n_passes))
                elif "PASS" in output:
                    n_passes = len(re.findall(r"PASS", output))
                    print(f"    PASS ({n_passes} pass markers)")
                    passed.append((name, n_passes))
                else:
                    print(f"    PASS")
                    passed.append((name, 0))
            else:
                print(f"    FAIL (returncode={result.returncode})")
                # 显示最后几行
                lines = output.strip().split("\n")
                for line in lines[-5:]:
                    print(f"      {line}")
                failed.append((name, result.returncode))
        except subprocess.TimeoutExpired:
            print(f"    TIMEOUT")
            failed.append((name, -1))
        except Exception as e:
            print(f"    ERROR: {e}")
            failed.append((name, -1))

    elapsed = time.time() - start
    total_passed = sum(n for _, n in passed)
    print("\n" + "#"*70)
    print(f" SUMMARY ({elapsed:.1f}s)")
    print(f"  Suites: {len(passed)} passed, {len(failed)} failed")
    print(f"  Total tests: {total_passed} passed")
    if failed:
        print(f"  Failed suites:")
        for n, c in failed:
            print(f"    - {n} (code={c})")
    print("#"*70)

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())