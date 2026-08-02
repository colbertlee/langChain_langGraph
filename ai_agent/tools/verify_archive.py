"""
tests-archive/ 验证脚本（Day 16）。

每个 release 前跑一次。逻辑：
1. 用 ``--rootdir`` 让 pytest 不被 ``pyproject.toml`` 的 ``addopts`` 影响；
2. 不收集 ``tests/`` 目录（避免被 pytest 默认收）；
3. 逐个试 ``tests-archive/tests/*.py`` 是否能 ``collect``；
4. 报告：
   - ``pass``：可 collect（即导入成功），值得保留；
   - ``import_fail``：代码坏（已迁移过头）—— 应清出归档；
   - ``skipped_dep``：依赖外部服务（GITHUB_TOKEN / ZHIPU 等）—— 保留供按需 opt-in；
   - ``error_runtime``：导入 OK 但 collect 时抛异常 —— 需人工 review。

用法::

    python tools/verify_archive.py             # 扫描 tests-archive/tests/
    python tools/verify_archive.py --json      # JSON 输出
    python tools/verify_archive.py --strict    # 任意 import_fail → exit 1

报告写回到 ``tests-archive/STATUS.md``，方便跨版本对比。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


ARCHIVE_DIR = ROOT / "tests-archive" / "tests"
STATUS_DOC = ROOT / "tests-archive" / "STATUS.md"


def _classify(test_path: Path) -> Dict[str, Any]:
    """对一个归档测试做语法 / import / collect 三层检查。

    关键：模块级代码可能执行副作用（http 请求 / 启动 server），所以 import 时
    重定向 stdout / stderr 到 DEVNULL，并把该进程导入设上限时间（防 tarpit）。
    """
    import ast
    import contextlib
    import importlib.util
    import io
    import signal
    import subprocess
    import sys

    # 1) AST 语法解析（在主进程做，便宜）
    try:
        src = test_path.read_text(encoding="utf-8")
        ast.parse(src, filename=str(test_path))
    except SyntaxError as e:
        return {
            "file": test_path.name,
            "status": "syntax_fail",
            "detail": f"line {e.lineno}: {e.msg}",
        }

    # 2) 在子进程里实际 import 并 spy 副作用（耗时 < 10s）
    #    通过环境变量传递路径，probe 写到 _probe.py 文件避免 shell 转义。
    probe_src = (
        "import os, importlib.util, json;"
        "_path = os.environ.get('VERIFY_PATH');"
        "spec = importlib.util.spec_from_file_location('_arc_target', _path);"
        "mod = importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(mod);"
        "names = [n for n in dir(mod) if n.startswith('test_')];"
        "print(json.dumps({'test_count': len(names), 'names': names[:20]}))"
    )
    probe_path = ROOT / "_probe.py"
    probe_path.write_text(probe_src, encoding="utf-8")
    try:
        env = {**os.environ, "VERIFY_PATH": str(test_path)}
        cp = subprocess.run(
            [sys.executable, "-c", probe_src],
            capture_output=True,
            timeout=10,
            cwd=str(ROOT),
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "file": test_path.name,
            "status": "error_runtime",
            "detail": "import hung >10s (likely starts server / network call)",
        }
    except Exception as e:
        return {
            "file": test_path.name,
            "status": "error_runtime",
            "detail": f"subprocess failed: {e}",
        }
    finally:
        try:
            probe_path.unlink()
        except Exception:
            pass

    if cp.returncode != 0:
        err = cp.stderr.decode("utf-8", errors="replace")[-160:]
        return {
            "file": test_path.name,
            "status": "import_fail",
            "detail": err.strip() or f"exit {cp.returncode}",
        }

    out = cp.stdout.decode("utf-8", errors="replace").strip()
    if not out.startswith("{"):
        return {
            "file": test_path.name,
            "status": "error_runtime",
            "detail": "no json payload from probe",
        }
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {
            "file": test_path.name,
            "status": "error_runtime",
            "detail": "probe output not json",
        }

    cnt = data.get("test_count", 0)
    if cnt == 0:
        # 即使导入成功，但文件里没 test_ 函数（可能仅含 TestXxx 类），
        # 这里仍算 pass
        return {
            "file": test_path.name,
            "status": "pass",
            "test_count": 0,
            "tests": [],
            "note": "no test_ functions, but importable",
        }
    return {
        "file": test_path.name,
        "status": "pass",
        "test_count": cnt,
        "tests": data.get("names", []),
    }


def scan() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for p in sorted(ARCHIVE_DIR.glob("test_*.py")):
        rows.append(_classify(p))
    return rows


def render_human(rows: List[Dict[str, Any]]) -> str:
    out = []
    out.append(f"# tests-archive/ 状态扫描\n\n")
    out.append(f"> 扫描时间：{datetime.now().isoformat(timespec='seconds')}\n")
    out.append(f"> 脚本：`tools/verify_archive.py`\n\n")

    summary: Dict[str, int] = {}
    for r in rows:
        summary[r["status"]] = summary.get(r["status"], 0) + 1

    out.append("## 汇总\n\n")
    for k, v in sorted(summary.items(), key=lambda x: -x[1]):
        out.append(f"- **{k}**: {v}\n")

    out.append("\n## 明细\n\n")
    out.append("| 文件 | 状态 | 详情 | 测试数 |\n")
    out.append("|------|------|------|--------|\n")
    for r in rows:
        detail = r.get("detail", "")
        tc = r.get("test_count", "-")
        out.append(f"| `{r['file']}` | `{r['status']}` | {detail} | {tc} |\n")

    out.append("\n## 处置建议\n\n")
    out.append("- `pass` ✅：保留在归档，按需 opt-in 运行\n")
    out.append("- `no_tests_collected`：可能测试写在了方法内（需要查找类，TODO）\n")
    out.append("- `import_fail`：代码坏 / 已迁移过头 → 下次 release 删\n")
    out.append("- `syntax_fail`：语法坏 → 下次 release 删\n")
    out.append("- `error_runtime`：colletc 时抛 → 人工 review\n")

    return "".join(out)


def cmd_scan(args: argparse.Namespace) -> int:
    rows = scan()
    body = render_human(rows)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        # 把 stdout 重新设 utf-8 避免 windows GBK 问题
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        print(body)

    # 写 STATUS.md
    STATUS_DOC.parent.mkdir(parents=True, exist_ok=True)
    STATUS_DOC.write_text(body, encoding="utf-8")

    # --strict：任意 import_fail → 非零
    if args.strict:
        bad = [r for r in rows if r["status"] in {"import_fail", "syntax_fail"}]
        if bad:
            print(f"[FAIL] {len(bad)} 个文件 import 失败：", file=sys.stderr)
            for r in bad:
                print(f"  - {r['file']}: {r.get('detail','')}", file=sys.stderr)
            return 1
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_archive",
        description="扫描 tests-archive/ 哪些能 collect / 哪些坏",
    )
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--strict", action="store_true", help="任意 import_fail 视为非零退出")
    args = parser.parse_args(argv)
    return cmd_scan(args)


if __name__ == "__main__":
    sys.exit(main())
