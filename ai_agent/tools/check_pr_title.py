"""
auto-archive PR title 校验（Day 23）。

GitHub Forms（issue forms）只在 Issue 上生效，PR template 不原生支持。
作为补偿，校验 PR title 格式：

    auto-archive: <动作> <简短描述>

例子：
    ✅ auto-archive: clean 3 errored files
    ✅ auto-archive: restore test_rag.py
    ✅ auto-archive(v2.1.0): backfill _obsolete
    ❌ Auto-archive: clean files        # 大小写不对
    ❌ cleanup                            # 缺少前缀

Day 23：CI 在 PR open / edit 时跑这个脚本，校验失败 → branch protection 阻止 merge。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import List, Tuple


# PR title 必须匹配：``auto-archive(<tag>)?: <verb> <description>``
# - 必须全小写 ``auto-archive`` 前缀
# - 可选 ``(vX.Y.Z)`` 用于 release-tag 关联
# - verb 从白名单中选（小写）
# - description 长度 5-100
#
# Day 24：verb 白名单扩展（revert/archive/rebase/upgrade）
ALLOWED_VERBS = (
    "clean",
    "restore",
    "backfill",
    "migrate",
    "prune",
    "cleanup",
    "revert",
    "archive",
    "rebase",
    "upgrade",
    "downgrade",
    "consolidate",
)

TITLE_PATTERN = re.compile(
    r"^auto-archive(\([^)\s]+\))?:\s+"
    r"(?P<verb>" + "|".join(ALLOWED_VERBS) + r")\s+"
    r".{5,100}$",
)


def check_title(title: str) -> Tuple[bool, List[str]]:
    """校验 title 格式。

    Returns:
        (passed, errors)
    """
    errors: List[str] = []
    if not title:
        errors.append("title is empty")
        return False, errors

    m = TITLE_PATTERN.match(title)
    if not m:
        errors.append(
            f"title must match: 'auto-archive(<tag>)?: <verb> <description>' "
            f"(verbs: {', '.join(ALLOWED_VERBS)}, lowercase required)"
        )
    return len(errors) == 0, errors


def fetch_pr_title(repo: str, pr_number: int) -> str:
    """从 gh CLI 读 PR title。"""
    out = subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "title"],
        capture_output=True, text=True, timeout=15,
    )
    if out.returncode != 0:
        raise RuntimeError(f"gh pr view failed: {out.stderr}")
    return json.loads(out.stdout).get("title", "")


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="check_pr_title")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    args = parser.parse_args(argv)

    try:
        title = fetch_pr_title(args.repo, args.pr)
    except Exception as e:
        print(f"[fail] {e}", file=sys.stderr)
        return 2

    passed, errors = check_title(title)
    if passed:
        print(f"[ok] PR #{args.pr} title: {title!r}")
        return 0

    print(f"[fail] PR #{args.pr} title={title!r}", file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())