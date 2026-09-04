"""
v2.0 slim 工具集（6 个复合 @tool）

设计原则：
- 每个复合工具用 subcommand: Literal[...] 分发子命令
- description 字段显式列出 subcommand 选项（不依赖 parse_docstring）
- 危险 subcommand（code_exec.shell / vcs.commit）通过 approval.py 后置钩子拦截
- 路径/命令输入统一走 security.py 的 validate_safe_path / safe_eval_expression 校验

注意：不要在 @tool 装饰器里设置 parse_docstring=True。
      本文件中各函数的 docstring 是中文说明，包含 "- "read":" 等字面列表，
      LangChain 会把它们当成函数参数名校验，导致 schema 构建失败。
"""
from __future__ import annotations

import os
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Literal, Optional, Any

from langchain_core.tools import tool

# 复用核心安全模块（核心闭环，不动）
from security import (
    validate_safe_path,
    safe_eval_expression,
    get_security_instance,
)
from config import SERPAPI_API_KEY


# ============================================================
# 1. file_ops — 文件操作
# ============================================================

@tool(
    name_or_callable="file_ops",
    description=(
        "统一的文件操作复合工具，subcommand 可选：read / write / list / glob / delete。"
        "所有路径必须经过 security.validate_safe_path 校验，"
        "禁止访问 .env / .git / .ssh / node_modules 等敏感位置。"
    ),
)
def file_ops(
    subcommand: Literal["read", "write", "list", "glob", "delete"],
    path: str,
    content: Optional[str] = None,
    pattern: Optional[str] = None,
    append: bool = False,
    recursive: bool = False,
) -> str:
    """统一的文件操作复合工具。"""
    op = "delete" if subcommand == "delete" else ("write" if subcommand == "write" else "read")
    ok, reason = validate_safe_path(path, operation=op)
    if not ok:
        return f"❌ {reason}"

    base = Path(path)
    if subcommand == "read":
        try:
            text = base.read_text(encoding="utf-8")
            if len(text) > 5000:
                return text[:5000] + "\n...（文件过长，已截断）"
            return text
        except FileNotFoundError:
            return f"❌ 文件不存在: {path}"
    if subcommand == "write":
        if content is None:
            raise ValueError("file_ops.write 需要 content 参数")
        base.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        base.write_text(content, encoding="utf-8")
        return f"✅ WRITE {path} ({len(content)} chars)"
    if subcommand == "list":
        items = sorted(base.rglob("*") if recursive else base.iterdir())
        return "\n".join(str(p) for p in items) or "<empty>"
    if subcommand == "glob":
        if pattern is None:
            raise ValueError("file_ops.glob 需要 pattern 参数")
        matches = list(base.glob(pattern)) if not recursive else list(base.rglob(pattern))
        return "\n".join(str(p) for p in matches) or "<empty>"
    if subcommand == "delete":
        if base.is_file():
            base.unlink()
            return f"✅ DELETE {path}"
        return f"❌ 仅支持删除文件: {path}"
    raise NotImplementedError(f"file_ops.{subcommand}: Frozen in v2.0 slim")


# ============================================================
# 2. web_search — 网络检索与抓取
# ============================================================

@tool(
    name_or_callable="web_search",
    description=(
        "网络搜索与网页抓取复合工具，subcommand 可选：search / fetch，"
        "依赖 SERPAPI_API_KEY。"
    ),
)
def web_search(
    subcommand: Literal["search", "fetch"],
    query: str,
    url: Optional[str] = None,
    num: int = 5,
) -> str:
    """网络搜索与网页抓取复合工具。"""
    if subcommand == "search":
        try:
            from serpapi import GoogleSearch  # type: ignore
        except ImportError:
            return "请安装 serpapi 包: pip install serpapi"
        if not SERPAPI_API_KEY:
            return "请先配置 SERPAPI_API_KEY 环境变量"
        search = GoogleSearch({"q": query, "api_key": SERPAPI_API_KEY, "num": num})
        results = search.get_dict()
        if "organic_results" in results:
            summaries = []
            for r in results["organic_results"][:num]:
                summaries.append(f"{r.get('title','')}\n{r.get('snippet','')}\n{r.get('link','')}")
            return "\n\n".join(summaries)
        return "未找到相关结果"
    if subcommand == "fetch":
        return f"web_search.fetch 暂未实现，建议改用 search 子命令。query={query}, url={url}"
    raise NotImplementedError(f"web_search.{subcommand}: Frozen in v2.0 slim")


# ============================================================
# 3. code_exec — 代码与 Shell 执行
# ============================================================

@tool(
    name_or_callable="code_exec",
    description=(
        "代码与 Shell 执行复合工具，subcommand 可选：python（AST 白名单，安全）"
        " / shell（subprocess，需要 HITL 审批）。"
    ),
)
def code_exec(
    subcommand: Literal["python", "shell"],
    code: str,
    timeout: int = 30,
) -> str:
    """代码与 Shell 执行复合工具。"""
    if subcommand == "python":
        try:
            normalized = code.replace("^", "**")
            return str(safe_eval_expression(normalized))
        except Exception as e:
            return f"计算错误: {e}"
    if subcommand == "shell":
        try:
            r = subprocess.run(
                code, shell=True, capture_output=True, text=True, timeout=timeout
            )
            return (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        except subprocess.TimeoutExpired:
            return f"❌ Shell 执行超时（{timeout}s）"
        except Exception as e:
            return f"❌ Shell 执行错误: {e}"
    raise NotImplementedError(f"code_exec.{subcommand}: Frozen in v2.0 slim")


# ============================================================
# 4. data_query — 数据查询（sql/csv/json）
# ============================================================

@tool(
    name_or_callable="data_query",
    description=(
        "结构化数据查询复合工具，subcommand 可选：sql / csv / json。"
    ),
)
def data_query(
    subcommand: Literal["sql", "csv", "json"],
    source: str,
    query: Optional[str] = None,
    limit: int = 100,
) -> str:
    """结构化数据查询复合工具。"""
    if not os.path.exists(source):
        return f"❌ 数据源不存在: {source}"
    try:
        if subcommand == "sql":
            conn = sqlite3.connect(source)
            cur = conn.execute(query or "SELECT 1")
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = [dict(zip(cols, r)) for r in cur.fetchmany(limit)]
            conn.close()
            return json.dumps(rows, ensure_ascii=False, default=str)
        if subcommand == "csv":
            import csv as _csv
            with open(source, "r", encoding="utf-8") as f:
                reader = _csv.DictReader(f)
                rows = list(reader)[:limit]
            return json.dumps(rows, ensure_ascii=False, default=str)
        if subcommand == "json":
            with open(source, "r", encoding="utf-8") as f:
                data = json.load(f)
            if query and query.startswith("$"):
                parts = query.lstrip("$").split(".")
                cur: Any = data
                for p in parts:
                    if not p:
                        continue
                    if "[" in p:
                        name, idx = p[:-1].split("[")
                        if name:
                            cur = cur[name]
                        cur = cur[int(idx)]
                    else:
                        cur = cur[p]
                data = cur
            return json.dumps(data, ensure_ascii=False, default=str)[:5000]
    except Exception as e:
        return f"❌ data_query.{subcommand} 错误: {e}"
    raise NotImplementedError(f"data_query.{subcommand}: Frozen in v2.0 slim")


# ============================================================
# 5. vcs — 版本控制（git）
# ============================================================

@tool(
    name_or_callable="vcs",
    description=(
        "Git 版本控制复合工具，subcommand 可选：status / diff / log / commit。"
        "commit 子命令需要 HITL 审批。"
    ),
)
def vcs(
    subcommand: Literal["status", "diff", "log", "commit"],
    path: str = ".",
    message: Optional[str] = None,
    max_count: int = 10,
) -> str:
    """Git 版本控制复合工具。"""
    try:
        if subcommand == "status":
            r = subprocess.run(["git", "-C", path, "status"], capture_output=True, text=True, timeout=10)
            return r.stdout or r.stderr
        if subcommand == "diff":
            r = subprocess.run(["git", "-C", path, "diff"], capture_output=True, text=True, timeout=10)
            return r.stdout or r.stderr
        if subcommand == "log":
            r = subprocess.run(
                ["git", "-C", path, "log", f"-n{max_count}", "--oneline"],
                capture_output=True, text=True, timeout=10,
            )
            return r.stdout or r.stderr
        if subcommand == "commit":
            if not message:
                raise ValueError("vcs.commit 需要 message 参数")
            r = subprocess.run(
                ["git", "-C", path, "commit", "-m", message],
                capture_output=True, text=True, timeout=15,
            )
            return r.stdout or r.stderr
    except Exception as e:
        return f"❌ vcs.{subcommand} 错误: {e}"
    raise NotImplementedError(f"vcs.{subcommand}: Frozen in v2.0 slim")


# ============================================================
# 6. chart — 图表生成（bar/line/pie）
# ============================================================

@tool(
    name_or_callable="chart",
    description=(
        "图表生成复合工具，subcommand 可选：bar / line / pie。"
        "输出 base64 PNG data URI 或保存到 output_path。"
    ),
)
def chart(
    subcommand: Literal["bar", "line", "pie"],
    data: list,
    x: Optional[str] = None,
    y: Optional[str] = None,
    title: str = "Chart",
    output_path: Optional[str] = None,
) -> str:
    """图表生成复合工具。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import base64
        from io import BytesIO
    except ImportError:
        return "请安装 matplotlib: pip install matplotlib"

    fig, ax = plt.subplots(figsize=(6, 4))
    try:
        if subcommand == "bar":
            xs = [d[x] if x else i for i, d in enumerate(data)]
            ys = [d[y] if y else d.get("value", 0) for d in data]
            ax.bar(xs, ys)
        elif subcommand == "line":
            xs = [d[x] if x else i for i, d in enumerate(data)]
            ys = [d[y] if y else d.get("value", 0) for d in data]
            ax.plot(xs, ys, marker="o")
        elif subcommand == "pie":
            labels = [d.get("label", str(i)) for i, d in enumerate(data)]
            sizes = [d.get("value", 1) for d in data]
            ax.pie(sizes, labels=labels, autopct="%1.1f%%")
        else:
            raise NotImplementedError(f"chart.{subcommand}: Frozen in v2.0 slim")
        ax.set_title(title)
        buf = BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        png = buf.getvalue()
        if output_path:
            Path(output_path).write_bytes(png)
            return f"✅ CHART saved: {output_path}"
        return "data:image/png;base64," + base64.b64encode(png).decode()
    except Exception as e:
        plt.close(fig)
        return f"❌ chart.{subcommand} 错误: {e}"


# ============================================================
# 聚合导出
# ============================================================

ALL_TOOLS_V2 = [file_ops, web_search, code_exec, data_query, vcs, chart]


def get_all_tools_v2() -> list:
    """返回 6 个复合工具列表。"""
    return list(ALL_TOOLS_V2)