"""
``tools/`` 子包 marker（Day 16/17 修复）。

当项目根有 ``tools.py`` 同名模块时，``import tools`` 默认解析为 package
（Python 解析顺序：package > module）。这导致 ``from tools import run_code``
（archive 旧测试用过）找不到。

修复：在本 ``__init__.py`` 末尾**主动 import** 单文件 ``tools.py``（把它改名临时），并
把它的所有公开符号暴露到本包的 namespace。

实现思路
~~~~~~~
由于 ``tools.py`` 与 ``tools/`` 同名，``import tools`` 永远先解析为 package。
所以本 __init__.py 里用 ``import importlib.util`` 直接 exec ``../tools.py``
的源码，并把它的 globals 注入本包。

这样 ``import tools`` 之后：
- ``tools.run_code`` ← 来自 tools.py
- ``tools.archive_legacy`` ← 来自 tools/archive_legacy.py
- ``tools.verify_archive`` ← 来自 tools/verify_archive.py
- ``tools.doctor_chatops`` ← 来自 tools/doctor_chatops.py
- ``tools.archive_acceptance`` ← 来自 tools/archive_acceptance.py
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_TOOLS_PY = _ROOT / "tools.py"


def _bootstrap_tools_py() -> None:
    """执行 ``../tools.py`` 并把它的 globals 注入当前包的 namespace。"""
    if not _TOOLS_PY.exists():
        return
    spec = importlib.util.spec_from_file_location(
        "_tools_module_from_py", str(_TOOLS_PY)
    )
    if spec is None or spec.loader is None:
        return
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        # 如果 tools.py 自身抛（比如没装某依赖），archive 测试 import 失败就走它们
        # 自己的 import 错误日志。这里静默不影响子包 import。
        return
    # 把 tools.py 的所有非下划线开头的 globals 注入本包
    for k, v in vars(mod).items():
        if k.startswith("_"):
            continue
        if k in globals():
            continue
        globals()[k] = v


_bootstrap_tools_py()