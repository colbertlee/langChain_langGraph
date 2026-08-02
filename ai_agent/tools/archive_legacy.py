"""
legacy 测试归档迁移工具（Day 15）。

为下一次 release 准备：
1. 把 ``tests/legacy/`` 内容物理迁到 ``tests-archive/tests/``；
2. 把 ``scripts/legacy_tests/`` 迁到 ``tests-archive/scripts/``；
3. 在 ``tests-archive/MIGRATION.md`` 生成清单；
4. 输出"哪些应该迁回 / 哪些应丢弃"的建议。

不要轻易删除测试。每次跑要观察反馈，再做归档动作。

用法::

    # 仅查看计划（不动文件）
    python tools/archive_legacy.py --plan

    # 物理迁移（执行拷贝到 tests-archive/）
    python tools/archive_legacy.py --migrate

    # 仅更新 MIGRATION.md（不拷贝文件）
    python tools/archive_legacy.py --report
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))


# 让路径常量"延迟"读取，便于测试 monkeypatch
def _root() -> Path:
    return _HERE.parent


LEGACY_TESTS_DIR = _ROOT / "tests" / "legacy"
LEGACY_SCRIPTS_DIR = _ROOT / "scripts" / "legacy_tests"
ARCHIVE_TESTS_DIR = _ROOT / "tests-archive" / "tests"
ARCHIVE_SCRIPTS_DIR = _ROOT / "tests-archive" / "scripts"
ARCHIVE_README = _ROOT / "tests-archive" / "README.md"
MIGRATION_DOC = _ROOT / "tests-archive" / "MIGRATION.md"


# ============================================================
# 单文件决策规则
# ============================================================

# 文件名（stem） → 状态 / 建议
# 状态语义：
#   "keep_test"   — 有测试价值、保留
#   "scripts_only"— 一次性脚本，归档到 scripts/
#   "obsolete"    — 已被取代 / 完全失效，建议丢
DECISION_MAP: Dict[str, str] = {
    # tests/legacy/
    "test_basic": "scripts_only",
    "test_bug_fixes": "keep_test",
    "test_capability": "keep_test",
    "test_context": "keep_test",
    "test_context_simple": "scripts_only",
    "test_full": "obsolete",
    "test_full_system_integration": "obsolete",
    "test_github_mcp": "obsolete",
    "test_github_push": "obsolete",
    "test_hitl_webui": "obsolete",
    "test_mcp": "keep_test",
    "test_memory_store": "keep_test",
    "test_multi_agent": "keep_test",
    "test_negotiation": "keep_test",
    "test_negotiation_integration": "obsolete",
    "test_observability": "keep_test",
    "test_p2_extra": "obsolete",
    "test_p3_all": "obsolete",
    "test_planner_memory": "keep_test",
    "test_rag": "keep_test",
    "test_reliability": "keep_test",
    "test_streaming_permission": "keep_test",
    "test_task_intent": "keep_test",
    "test_tools_full": "scripts_only",
    "test_zhipu_embedding": "scripts_only",
    # scripts/legacy_tests/
    "test_agent": "keep_test",
    "test_debug": "scripts_only",
    "test_gitee": "obsolete",
    "test_gitee_debug": "obsolete",
    "test_gitee_final": "obsolete",
    "test_github_tools": "keep_test",
    "test_primary_standby": "keep_test",
    "test_resilience_e2e": "keep_test",
    "test_simple": "keep_test",
    "test_sqlite": "keep_test",
}


def classify(file: Path) -> str:
    return DECISION_MAP.get(file.stem, "keep_test")


# ============================================================
# 报告 / 决策逻辑
# ============================================================

def _collect(legacy_dir: Path, archived_dir: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not legacy_dir.exists():
        return rows
    for p in sorted(legacy_dir.glob("*.py")):
        status = classify(p)
        target_dir = "tests-archive/tests/" if status != "scripts_only" else "tests-archive/scripts/"
        # 真正判断"已迁移"：目标目录里文件已存在
        actual_target = _ROOT / target_dir / p.name
        migrated = "[ok]" if actual_target.exists() else "[pending]"
        rows.append(
            {
                "name": p.name,
                "source": str(p.relative_to(_ROOT)),
                "decision": status,
                "target": target_dir,
                "migrated": migrated,
            }
        )
    return rows


def build_report() -> str:
    """生成 ``MIGRATION.md`` 内容字符串。"""
    lines: List[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"# Legacy Test 迁移报告\n\n> 自动生成于 {now}\n> 脚本：`tools/archive_legacy.py`\n")
    lines.append("## 决策符号\n")
    lines.append("- `keep_test`：保留为回归价值（应迁到 `tests-archive/tests/`）")
    lines.append("- `scripts_only`：一次性脚本（应迁到 `tests-archive/scripts/`）")
    lines.append("- `obsolete`：已被取代 / 完全失效（建议下次 release 删除）\n")

    lines.append("## tests/legacy/ → tests-archive/\n")
    lines.append("| 文件 | 状态 | 归档目标 | 已迁移 |")
    lines.append("|------|------|----------|--------|")
    for r in _collect(LEGACY_TESTS_DIR, ARCHIVE_TESTS_DIR):
        lines.append(
            f"| `{r['name']}` | {r['decision']} | "
            f"`{r['target']}` | {r['migrated']} |"
        )

    lines.append("\n## scripts/legacy_tests/ → tests-archive/scripts/\n")
    lines.append("| 文件 | 状态 | 归档目标 | 已迁移 |")
    lines.append("|------|------|----------|--------|")
    for r in _collect(LEGACY_SCRIPTS_DIR, ARCHIVE_SCRIPTS_DIR):
        lines.append(
            f"| `{r['name']}` | {r['decision']} | "
            f"`{r['target']}` | {r['migrated']} |"
        )

    # 总结
    n_total = len(_collect(LEGACY_TESTS_DIR, ARCHIVE_TESTS_DIR)) + len(
        _collect(LEGACY_SCRIPTS_DIR, ARCHIVE_SCRIPTS_DIR)
    )
    lines.append(f"\n## 总计\n\n- 共 **{n_total}** 个文件待归档\n")
    lines.append("## 何时清理 `tests-archive/`\n")
    lines.append("- 每个 release 前跑一次 `python tools/archive_legacy.py --report`")
    lines.append("- 已被取代的 `obsolete` 文件可以丢弃（人工 review 后删）")
    lines.append("- 归档目录的目标是 1-2 年内自然清空")
    return "\n".join(lines) + "\n"


def cmd_plan(_args: argparse.Namespace) -> int:
    """仅打印计划，不动文件。"""
    _safe_stdout()
    print(build_report())
    return 0


def _safe_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def cmd_report(_args: argparse.Namespace) -> int:
    """写``MIGRATION.md``，不迁移物理文件。"""
    MIGRATION_DOC.parent.mkdir(parents=True, exist_ok=True)
    MIGRATION_DOC.write_text(build_report(), encoding="utf-8")
    print(f"[ok] wrote {MIGRATION_DOC.relative_to(_ROOT)}")
    return 0


def _safe_copy(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    shutil.copy2(src, dst)
    return dst


def cmd_migrate(args: argparse.Namespace) -> int:
    """物理拷贝（不删除原文件）。带 ``--purge`` 才删除源头。"""
    moved = 0
    # tests/legacy/ → tests-archive/tests/
    if LEGACY_TESTS_DIR.exists():
        for p in sorted(LEGACY_TESTS_DIR.glob("*.py")):
            if classify(p) != "scripts_only":
                _safe_copy(p, ARCHIVE_TESTS_DIR)
                moved += 1
    # scripts/legacy_tests/ → tests-archive/scripts/
    if LEGACY_SCRIPTS_DIR.exists():
        for p in sorted(LEGACY_SCRIPTS_DIR.glob("*.py")):
            if classify(p) == "scripts_only":
                _safe_copy(p, ARCHIVE_SCRIPTS_DIR)
            else:
                _safe_copy(p, ARCHIVE_TESTS_DIR)
            moved += 1

    # 同步 README
    for src_dir, archive_subdir in [
        (LEGACY_TESTS_DIR, ARCHIVE_TESTS_DIR),
        (LEGACY_SCRIPTS_DIR, ARCHIVE_SCRIPTS_DIR),
    ]:
        for sub in ("README.md", "conftest.py"):
            sp = src_dir.parent / sub if sub == "conftest.py" else src_dir / sub
            if sp.exists():
                shutil.copy2(sp, archive_subdir / sub)

    print(f"[ok] copied {moved} files into tests-archive/")
    cmd_report(args)
    return 0


def cmd_purge(_args: argparse.Namespace) -> int:
    """删源（仅在 --migrate 后用）。"""
    deleted = 0
    for d in (LEGACY_TESTS_DIR, LEGACY_SCRIPTS_DIR):
        if d.exists():
            for p in d.glob("*.py"):
                if not p.name.startswith("__"):
                    p.unlink()
                    deleted += 1
    # conftest.py 与 README.md 保留（仍要 prevent 收集）
    print(f"[ok] deleted {deleted} source files (conftest.py + README.md 保留)")
    return 0


# ============================================================
# Day 19：auto-archive（按 acceptance summary 自动归档 errored 文件）
# ============================================================

ACCEPTANCE_DIR = _ROOT / "tests-archive" / "acceptance"


def _latest_acceptance_summary() -> Dict:
    """读最近一次 **有真实跑出结果** 的 acceptance summary（按 ts 倒序）。

    若最新一次跑出 ``errored == 0 && passed == 0``（即 0/0 空跑），跳过它，
    往前找直到找到至少有一次 pass / fail / errored 的 summary。
    """
    if not ACCEPTANCE_DIR.exists():
        return {}
    runs = sorted(
        [d for d in ACCEPTANCE_DIR.iterdir() if d.is_dir()], reverse=True
    )
    import json
    for d in runs:
        s = d / "summary.json"
        if not s.exists():
            continue
        try:
            data = json.loads(s.read_text(encoding="utf-8"))
        except Exception:
            continue
        t = data.get("totals", {})
        # 跳过全 0 的空跑
        if t.get("passed", 0) == 0 and t.get("failed", 0) == 0 and t.get("errored", 0) == 0:
            continue
        return data
    return {}


def _errored_files_from_summary(summary: Dict) -> List[str]:
    """从 summary 中提取 status == 'error' 的文件名列表。"""
    out: List[str] = []
    for f in summary.get("files", []):
        if f.get("status") == "error":
            out.append(f.get("file", ""))
    return [x for x in out if x]


def cmd_auto_archive(_args: argparse.Namespace) -> int:
    """按 acceptance summary 自动归档 errored 文件。

    流程：
    1. 读最新 acceptance summary；
    2. 提取所有 status == 'error' 的文件；
    3. 写入 ``tests-archive/auto_archive.md`` 清单 + git 提交摘要；
    4. 输出 git diff 供 CI 提交 PR 用。
    """
    summary = _latest_acceptance_summary()
    if not summary:
        print("[warn] no acceptance summary found, run tools/archive_acceptance.py first", file=sys.stderr)
        return 1

    errored = _errored_files_from_summary(summary)
    if not errored:
        print("[ok] no errored files in latest acceptance summary")
        return 0

    # 写一份 auto_archive.md 清单
    doc = _ROOT / "tests-archive" / "auto_archive.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# tests-archive/ Auto-Archive 清单\n\n"]
    lines.append(f"> 自动生成于 {datetime.now().isoformat(timespec='seconds')}\n")
    lines.append(f"> 取自 acceptance summary（{summary.get('started_at', '?')}）\n\n")
    lines.append(f"共 **{len(errored)}** 个 errored 文件建议归档清理：\n\n")
    lines.append("| 文件 | 行数 |\n")
    lines.append("|------|------|\n")
    for name in errored:
        path = ARCHIVE_TESTS_DIR / name
        if path.exists():
            line_count = sum(1 for _ in path.open("r", encoding="utf-8", errors="replace"))
        else:
            line_count = 0
        lines.append(f"| `{name}` | {line_count} |\n")
    doc.write_text("".join(lines), encoding="utf-8")
    print(f"[ok] wrote {doc.relative_to(_ROOT)}", file=sys.stderr)

    # 输出待删文件清单到 stdout（CI 用）
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import json as _json
    print(_json.dumps({
        "to_archive": errored,
        "auto_archive_doc": str(doc.relative_to(_ROOT)),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_archive_errored(args: argparse.Namespace) -> int:
    """实归档：把 errored 文件移到 ``tests-archive/_obsolete/``。

    比 cmd_purge 更安全：保留历史 copy 到带日期戳的目录，便于恢复。
    """
    summary = _latest_acceptance_summary()
    if not summary:
        print("[warn] no acceptance summary found", file=sys.stderr)
        return 1

    errored = _errored_files_from_summary(summary)
    if not errored:
        print("[ok] no errored files")
        return 0

    # 把 err_or_files 移到 tests-archive/_obsolete/<ts>/
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = _ROOT / "tests-archive" / "_obsolete" / ts
    target_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for name in errored:
        src = ARCHIVE_TESTS_DIR / name
        if src.exists():
            shutil.move(str(src), str(target_dir / name))
            moved += 1

    # 写 obsolete 清单
    index = target_dir / "README.md"
    index.write_text(
        f"# Obsoleted archive files\n\n"
        f"> 自动归档于 {datetime.now().isoformat(timespec='seconds')}\n\n"
        f"由 `archive_acceptance.py` + `archive_legacy.py --archive-errored` 触发。\n\n"
        f"共 {moved} 个文件从 archive 移到这里（**已清出 archive 主目录**）。\n\n"
        f"如需恢复：`git mv tests-archive/_obsolete/{ts}/<file> tests-archive/tests/`。\n",
        encoding="utf-8",
    )

    print(f"[ok] moved {moved} errored files to {target_dir.relative_to(_ROOT)}")
    print(f"[ok] wrote {index.relative_to(_ROOT)}")
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="archive_legacy",
        description="legacy 测试归档迁移工具（Day 15/19）",
    )
    parser.add_argument("--plan", action="store_true", help="打印计划，不动文件")
    parser.add_argument("--report", action="store_true", help="仅更新 MIGRATION.md")
    parser.add_argument("--migrate", action="store_true", help="物理迁移到 tests-archive/")
    parser.add_argument("--purge", action="store_true", help="迁移后删源（仅与 --migrate 联用）")
    # Day 19：自动归档 errored 测试
    parser.add_argument(
        "--auto-archive",
        action="store_true",
        help="按最新 acceptance summary 自动找出 errored 文件并写清单（不实际移动）",
    )
    parser.add_argument(
        "--archive-errored",
        action="store_true",
        help="实归档：把 errored 文件物理移到 tests-archive/_obsolete/<ts>/",
    )
    args = parser.parse_args(argv)

    if args.plan:
        return cmd_plan(args)
    if args.report:
        return cmd_report(args)
    if args.migrate:
        rc = cmd_migrate(args)
        if args.purge:
            cmd_purge(args)
        return rc
    if args.auto_archive:
        return cmd_auto_archive(args)
    if args.archive_errored:
        return cmd_archive_errored(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
