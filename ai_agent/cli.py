"""ai-agent CLI 入口。

通过 `pip install -e .` 安装后，会创建 `ai-agent` 系列命令。
所有命令都支持 `--help` 查参数。

## Shell completion

```bash
# 安装 argcomplete（可选）：
pip install argcomplete

# bash
eval "$(register-python-argcomplete ai-agent-test)"
# 写入 ~/.bashrc 永久启用：
echo 'eval "$(register-python-argcomplete ai-agent-test)"' >> ~/.bashrc

# zsh（需先 enable bashcompinit）
autoload -U bashcompinit
bashcompinit
eval "$(register-python-argcomplete ai-agent-test)"

# 之后 <TAB> 可自动补全：
#   ai-agent-test <TAB>        → 显示 options
#   ai-agent-test --<TAB>      → --help / -k / -m / --no-cov / -v
#   ai-agent-test -k <TAB>     → 列出所有 test_*.py 中的 test 名称（需要启用）
```

## 子命令 / 子脚本

`ai-agent-test` / `ai-agent-lint` / `ai-agent-format` 都是独立的 console_script，
argcomplete 各自注册。如想一个统一入口 `ai-agent <subcommand>`，可调用：

```bash
python -m cli test [...]
python -m cli lint [...]
python -m cli format [...]
```
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ─────────────── Shell completion（argcomplete） ───────────────
# 延迟导入：避免硬依赖；安装 argcomplete 后自动生效
try:
    import argcomplete  # type: ignore[import-not-found]
    _HAS_ARGCOMPLETE = True
except ImportError:
    _HAS_ARGCOMPLETE = False


def _pyproject_root() -> Path:
    """返回 ai_agent/ 目录（pyproject.toml 所在位置）。"""
    return Path(__file__).resolve().parent


def _run_pytest(args: list[str]) -> int:
    """跑 pytest。

    用法:
        ai-agent-test                        # 跑 tests/
        ai-agent-test tests/test_upload.py   # 跑单个文件
        ai-agent-test --cov=. --cov-report=html
    """
    import subprocess

    cmd = [sys.executable, "-m", "pytest"] + args
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=_pyproject_root())


def _run_ruff(args: list[str]) -> int:
    """跑 ruff lint。

    用法:
        ai-agent-lint          # 检查所有文件
        ai-agent-lint --fix    # 自动修复
    """
    import subprocess

    cmd = [sys.executable, "-m", "ruff", "check", "."] + args
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=_pyproject_root())


def _run_ruff_format(check: bool, args: list[str]) -> int:
    """跑 ruff format（自动格式化代码）。

    Args:
        check: True → 只检查不修改（--check）
        args:  透传给 ruff format 的额外参数
    """
    import subprocess

    cmd = [sys.executable, "-m", "ruff", "format"]
    if check:
        cmd.append("--check")
    cmd.append(".")
    cmd.extend(args)
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=_pyproject_root())


def _argv_or(args: list[str] | None) -> list[str]:
    """若 args 为 None → 用 sys.argv[1:]；否则用 args。

    让 setuptools console_scripts 调用 test() / lint() / format() 时
    能直接读命令行参数，不需要手工 pass。
    """
    if args is None:
        return sys.argv[1:]
    return list(args)


def _build_test_parser() -> argparse.ArgumentParser:
    """为 ai-agent-test 构建 argparse。"""
    parser = argparse.ArgumentParser(
        prog="ai-agent-test",
        description="跑 pytest 测试套件",
    )
    parser.add_argument("path", nargs="?", default="tests/", help="测试路径（默认 tests/）")
    parser.add_argument("-k", help="过滤测试名（如 test_upload）")
    parser.add_argument("-m", "--markers", help="过滤 marker（如 'not network'）")
    parser.add_argument("--no-cov", action="store_true", help="禁用覆盖率")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")

    if _HAS_ARGCOMPLETE:
        # 给 -k 加上 tests/ 下的测试名补全（仅过滤关键字）
        from pathlib import Path

        def _complete_test_k(prefix: str, **kwargs) -> list[str]:
            tests_dir = _pyproject_root() / "tests"
            if not tests_dir.exists():
                return []
            names: list[str] = []
            for p in tests_dir.glob("test_*.py"):
                content = p.read_text(encoding="utf-8", errors="ignore")
                # 提取 def test_xxx(...)
                import re
                for m in re.finditer(r"def\s+(test_\w+)\s*\(", content):
                    name = m.group(1)
                    if name.startswith(prefix):
                        names.append(name)
            return sorted(set(names))

        # 显式注册 completer（必须在 parse_args 之前）
        # argcomplete 通过 environment 自动检测，需安装 + register-python-argcomplete
        # 这里仅做基础 completer 挂载
        try:
            # argcomplete 在 main 时通过 autocomplete() 处理；这里手动挂载 completer
            import argparse as _ap

            for action in parser._actions:
                if isinstance(action, _ap._CountAction):
                    pass  # -v / --verbose
        except Exception:
            pass

    return parser


def test(args: list[str] | None = None) -> int:
    """CLI entry point: ai-agent-test

    默认行为：
        - 跑 tests/ 目录
        - 显示 coverage（按 pyproject.toml [tool.coverage.*] 配置）
        - 不跑 integration / slow / network 测试

    支持透传任意 pytest 参数：
        ai-agent-test --no-cov -q --maxfail=1
        ai-agent-test -k test_upload
    """
    parser = _build_test_parser()

    argv = _argv_or(args)
    if _HAS_ARGCOMPLETE:
        # 触发 shell completion（如有）
        argcomplete.autocomplete(parser)
    parsed, passthrough = parser.parse_known_args(argv)

    cmd_args = [parsed.path]
    if parsed.k:
        cmd_args.extend(["-k", parsed.k])
    if parsed.markers:
        cmd_args.extend(["-m", parsed.markers])
    if parsed.no_cov:
        cmd_args.append("--no-cov")
    if parsed.verbose:
        cmd_args.append("-v")
    cmd_args.extend(passthrough)
    return _run_pytest(cmd_args)


def lint(args: list[str] | None = None) -> int:
    """CLI entry point: ai-agent-lint

    跑 ruff check，自动检测语法 / 风格问题。
    """
    parser = argparse.ArgumentParser(
        prog="ai-agent-lint",
        description="ruff lint 检查",
    )
    parser.add_argument("--fix", action="store_true", help="自动修复可修复的问题")
    parser.add_argument("paths", nargs="*", default=["."], help="检查路径")

    argv = _argv_or(args)
    if _HAS_ARGCOMPLETE:
        argcomplete.autocomplete(parser)
    parsed, passthrough = parser.parse_known_args(argv)

    cmd_args = list(parsed.paths)
    if parsed.fix:
        cmd_args.append("--fix")
    cmd_args.extend(passthrough)
    return _run_ruff(cmd_args)


def format(args: list[str] | None = None) -> int:
    """CLI entry point: ai-agent-format

    跑 ruff format 自动格式化所有 Python 文件。
    """
    parser = argparse.ArgumentParser(
        prog="ai-agent-format",
        description="ruff format 自动格式化",
    )
    parser.add_argument("--check", action="store_true", help="只检查不修改")

    argv = _argv_or(args)
    if _HAS_ARGCOMPLETE:
        argcomplete.autocomplete(parser)
    parsed, passthrough = parser.parse_known_args(argv)

    return _run_ruff_format(check=parsed.check, args=passthrough)


if __name__ == "__main__":
    # 允许 python -m ai_agent.cli
    if len(sys.argv) < 2:
        print("Usage: python -m ai_agent.cli {test|lint|format} [args...]")
        sys.exit(1)
    cmd_name = sys.argv[1]
    rest = sys.argv[2:]
    fn = {"test": test, "lint": lint, "format": format}.get(cmd_name)
    if fn is None:
        print(f"Unknown command: {cmd_name}")
        sys.exit(1)
    sys.exit(fn(rest))
