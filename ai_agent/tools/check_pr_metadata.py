"""
auto-archive PR metadata 校验（Day 22）。

CI 步骤：在 release-build.yml 的 auto-archive PR 创建之后跑：
1. 读 PR body（``gh pr view --body``）
2. 验证含全部必填字段
3. 缺字段 → exit 1，挂住 merge

这是 GitHub 缺少"PR template checkbox 必填"原生支持下的 workaround。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import List, Tuple


# Day 22 强制：auto-archive PR 必须含这些短语（PR template 提供）
REQUIRED_PHRASES: List[str] = [
    "🚨 Maintainer Review Required",
    "## Summary",
    "## 涉及文件",
    "## Checklist",
]


def fetch_pr_body(repo: str, pr_number: int) -> str:
    """从 ``gh`` CLI 读 PR body。"""
    out = subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "body"],
        capture_output=True, text=True, timeout=15,
    )
    if out.returncode != 0:
        raise RuntimeError(f"gh pr view failed: {out.stderr}")
    return json.loads(out.stdout).get("body", "")


def check_body(body: str) -> Tuple[bool, List[str]]:
    """检查 body 是否含全部 required 短语。

    Returns:
        (passed, missing_phrases)
    """
    missing = [p for p in REQUIRED_PHRASES if p not in body]
    return (len(missing) == 0, missing)


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="check_pr_metadata", description="auto-archive PR metadata 校验")
    parser.add_argument("--repo", required=True, help="owner/repo（如 octocat/Hello-World）")
    parser.add_argument("--pr", type=int, required=True, help="PR 编号")
    args = parser.parse_args(argv)

    try:
        body = fetch_pr_body(args.repo, args.pr)
    except Exception as e:
        print(f"[fail] {e}", file=sys.stderr)
        return 2

    passed, missing = check_body(body)
    if passed:
        print(f"[ok] PR #{args.pr} has all required sections")
        return 0

    print(f"[fail] PR #{args.pr} missing {len(missing)} required sections:", file=sys.stderr)
    for m in missing:
        print(f"  - {m}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())