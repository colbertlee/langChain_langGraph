"""Step A audit-deps：声明 vs 实际 import 差集。仅做摸排，不改任何文件。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(r"e:\langChain_langGraph")
OUT = REPO / "output" / "2026-10-20" / "audit-deps.md"

# 1) 提取 Python 声明（requirements*.txt + pyproject.toml）
decl_py: set[str] = set()
for fname in ("requirements.txt", "requirements-dev.txt", "pyproject.toml"):
    p = REPO / "ai_agent" / fname
    if not p.exists():
        continue
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)", s)
        if m:
            decl_py.add(m.group(1).lower().replace("-", "_").replace(".", "_"))
# 去掉 stdlib / 关键字噪声
decl_py -= {"python"}

# 2) 实际 import（递归扫 ai_agent/ 全部 .py）
imports: set[str] = set()
for p in (REPO / "ai_agent").rglob("*.py"):
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for m in re.finditer(r"^\s*(?:from\s+([A-Za-z0-9_.]+)|import\s+([A-Za-z0-9_.]+))", text, re.M):
        mod = (m.group(1) or m.group(2)).split(".")[0]
        if mod:
            imports.add(mod.lower())

# 3) Node：声明 vs import（仅当 node_modules 存在才做）
node_pkg = REPO / "web_console" / "package.json"
node_modules = REPO / "web_console" / "node_modules"
node_section_lines: list[str] = []
if node_pkg.exists():
    try:
        pkg = json.loads(node_pkg.read_text(encoding="utf-8"))
        decl_node = set((pkg.get("dependencies") or {}).keys()) | set(
            (pkg.get("devDependencies") or {}).keys()
        )
        decl_node_lower = {n.lower() for n in decl_node}
    except Exception as e:
        node_section_lines.append(f"- package.json 解析失败: {e}")
        decl_node_lower = set()
    if node_modules.exists():
        ts_files = list((REPO / "web_console" / "src").rglob("*.ts")) + list(
            (REPO / "web_console" / "src").rglob("*.tsx")
        )
        used_node: set[str] = set()
        # 仅识别 npm scope / 普通包名形态
        for tp in ts_files:
            try:
                t = tp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for m in re.finditer(r"from\s+['\"]([^'\"]+)['\"]", t):
                spec = m.group(1)
                if spec.startswith(".") or spec.startswith("/"):
                    continue
                # @scope/pkg or pkg
                seg = spec.split("/")
                name = seg[0] if not seg[0].startswith("@") else "/".join(seg[:2])
                used_node.add(name.lower())
        unused_node = sorted(decl_node_lower - used_node)
        undeclared_node = sorted(used_node - decl_node_lower)
        node_section_lines.append(
            f"- declared(deps+devDeps): {len(decl_node_lower)}"
        )
        node_section_lines.append(f"- used in src/: {len(used_node)}")
        node_section_lines.append("")
        node_section_lines.append("**未使用的 Node 依赖（声明 → 未 import）**")
        node_section_lines.append("")
        if unused_node:
            for n in unused_node:
                node_section_lines.append(f"- `{n}`")
        else:
            node_section_lines.append("- （无）")
        node_section_lines.append("")
        node_section_lines.append("**使用但未声明的 Node 依赖**")
        node_section_lines.append("")
        if undeclared_node:
            for n in undeclared_node:
                node_section_lines.append(f"- `{n}`")
        else:
            node_section_lines.append("- （无）")
    else:
        node_section_lines.append("- N/A：`web_console/node_modules` 未安装，跳过 import 差集分析（避免 node/npx 失败）")
else:
    node_section_lines.append("- N/A：未找到 `web_console/package.json`")

# 4) Python 差集
unused_py = sorted(d for d in decl_py if d not in imports)
undeclared_py = sorted(i for i in imports if i not in decl_py)
# 过滤 stdlib 一部分明显名称（粗筛）
STDLIB_HINT = {
    "os", "sys", "re", "json", "time", "datetime", "pathlib", "typing", "asyncio",
    "logging", "functools", "itertools", "collections", "subprocess", "threading",
    "unittest", "traceback", "io", "tempfile", "shutil", "glob", "argparse",
    "copy", "hashlib", "urllib", "http", "email", "math", "random", "string",
    "dataclasses", "enum", "abc", "contextlib", "warnings", "weakref", "types",
}
undeclared_py = [m for m in undeclared_py if m not in STDLIB_HINT]

# 5) 写报告
lines: list[str] = []
lines.append("# audit-deps")
lines.append("---")
lines.append(f"generated_at: {REPO and 'see mtime'}")
lines.append(f"scope: ai_agent/ (Python) + web_console/ (Node)")
lines.append("")
lines.append("## Python 依赖")
lines.append("")
lines.append(f"- 声明（requirements*.txt + pyproject.toml 去重）: {len(decl_py)}")
lines.append(f"- 实际 import（递归 ai_agent/**/*.py）: {len(imports)}")
lines.append("")
lines.append("**声明但未使用（Top）**")
lines.append("")
if unused_py:
    for n in unused_py:
        lines.append(f"- `{n}`")
else:
    lines.append("- （无）")
lines.append("")
lines.append("**使用但未声明（已粗筛 stdlib，Top 50）**")
lines.append("")
for n in undeclared_py[:50]:
    lines.append(f"- `{n}`")
if len(undeclared_py) > 50:
    lines.append(f"- … 共 {len(undeclared_py)} 项，仅列前 50")
elif not undeclared_py:
    lines.append("- （无）")
lines.append("")
lines.append("## Node 依赖")
lines.append("")
lines.extend(node_section_lines)
lines.append("")
lines.append("_摸排口径：Python import 用 `^(?:from|import)` 首段；Node import 用 `from '...'` 字面量；scope 包按 `@scope/pkg` 整体匹配；package-lock 不计入声明集。_")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {OUT} bytes={OUT.stat().st_size}")
