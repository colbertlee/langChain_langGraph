"""B1：声明 vs 实际 import 差集（带证据路径）。仅摸排，不改任何文件。"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

REPO = Path(r"e:\langChain_langGraph")
PKG = REPO / "ai_agent"
OUT = REPO / "output" / "2026-10-20" / "audit-b1-diff.md"

# 1) 声明集（带来源）
DECL_SOURCES = {
    "requirements.txt": PKG / "requirements.txt",
    "requirements-dev.txt": PKG / "requirements-dev.txt",
    "pyproject.toml[dev]": PKG / "pyproject.toml",
}

# pip 名 → 可能的 import 名（处理常见 hyphen/underscore 与 name 重命名）
ALIASES: dict[str, set[str]] = {
    "python_multipart": {"multipart"},
    "python_dotenv": {"dotenv"},
    "pythonjsonlogger": {"pythonjsonlogger", "pythonjsonlogger.jsonlogger"},
    "pyyaml": {"yaml"},
    "pillow": {"PIL"},
    "scikit_learn": {"sklearn"},
    "scikit_image": {"skimage"},
    "pydantic_settings": {"pydantic_settings"},
    "beautifulsoup4": {"bs4"},
    "attrs": {"attr", "attrs"},
    "typing_extensions": {"typing_extensions"},
    "uvicorn": {"uvicorn"},
    "pytest": {"pytest"},
    "pytest_asyncio": {"pytest_asyncio"},
    "pytest_cov": {"pytest_cov", "coverage"},
    "pytest_mock": {"pytest_mock", "mock"},
    "pytest_timeout": {"pytest_timeout"},
    "respx": {"respx"},
    "ruff": {"ruff"},
    "mypy": {"mypy"},
    "ipython": {"IPython", "ipython"},
    "langchain_community": {"langchain", "langchain_community"},
    "langchain_openai": {"langchain_openai"},
    "langchain_chroma": {"langchain_chroma"},
    "langchain_text_splitters": {"langchain_text_splitters"},
    "langgraph_checkpoint_sqlite": {"langgraph_checkpoint", "langgraph_checkpoint_sqlite"},
    "sentence_transformers": {"sentence_transformers"},
    "rank_bm25": {"rank_bm25"},
    "sse_starlette": {"sse_starlette"},
    "argcomplete": {"argcomplete"},
    # 2026-10-20 audit-b1：补声明包的反向映射
    "pillow": {"PIL"},
    "pytesseract": {"pytesseract"},
    "openai_whisper": {"whisper"},
    "faster_whisper": {"faster_whisper"},
    "webrtcvad": {"webrtcvad"},
    "pyyaml": {"yaml"},
    "opentelemetry_api": {"opentelemetry", "opentelemetry.trace", "opentelemetry.metrics"},
    "prometheus_client": {"prometheus_client"},
    "duckduckgo_search": {"duckduckgo_search"},
    # 本项目实际 import 里出现的高频名 → pip 名（自动反查使用，见 is_declared）
}
# 反向：从 import 名 → pip 名集合（一次构建）
IMPORT_TO_PIP: dict[str, set[str]] = {}
for pip_name, names in ALIASES.items():
    for n in names:
        IMPORT_TO_PIP.setdefault(n.lower(), set()).add(pip_name)
# 包内 .py 文件名也算"使用"（py-modules 白名单）
PY_MODULES = {
    "app", "agent", "tools", "security", "config", "memory", "memory_store",
    "state_manager", "rag", "llm_reliability", "reliability", "streaming",
    "monitor", "observability", "permission", "human_in_loop",
    "context_manager", "context_db", "mcp_server", "mcp_tools", "start_mcp",
    "github_tools", "gitee_tools", "multi_agent", "multi_agent_integration",
    "multi_agent_examples", "negotiation", "task_intent", "task_scheduler",
    "skills", "plugin_manager", "sandbox", "message_bus", "message_protocol",
    "distributed_bus", "pub_sub_scenarios", "capability", "planner",
    "ab_testing", "adaptive_threshold", "multimodal", "sqlite_tools", "main",
    "cli", "harness_runner", "harness_storage", "harness_cli", "api",
}


def normalize(name: str) -> str:
    return name.lower().replace("-", "_").replace(".", "_")


def parse_decl(path: Path) -> dict[str, str]:
    """返回 {name: spec}；跳注释/空行；extras（如 `pkg[extra]`）按 `pkg` 解析。"""
    out: dict[str, str] = {}
    if path.suffix == ".toml":
        text = path.read_text(encoding="utf-8", errors="ignore")
        # 仅在 [project.optional-dependencies] dev 块
        m = re.search(r"\[project\.optional-dependencies\][\s\S]*?dev\s*=\s*\[([^\]]*)\]", text)
        if not m:
            return out
        block = m.group(1)
        for raw in block.splitlines():
            s = raw.strip().strip(",").strip('"').strip("'")
            if not s or s.startswith("#"):
                continue
            # 跳过尾部引号残留（之前 strip('"') 在带尾随引号的格式上不彻底）
            s = s.rstrip('",\'')
            mm = re.match(r"^([A-Za-z0-9_.\-]+)\s*([><=!~]=?\s*[^,]*)?", s)
            if mm:
                name = normalize(mm.group(1))
                spec = (mm.group(2) or "").strip()
                out[name] = spec or "*"
    else:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            # `pkg[extra1,extra2]~=1.0` → name=pkg spec=~=1.0
            cleaned = re.sub(r"\[[^\]]*\]", "", s)
            mm = re.match(r"^([A-Za-z0-9_.\-]+)\s*([><=!~]=?\s*[^#]*)?", cleaned)
            if mm:
                name = normalize(mm.group(1))
                spec = (mm.group(2) or "").strip()
                out[name] = spec or "*"
    return out


def collect_decl() -> dict[str, dict[str, str]]:
    """{canonical_name: {source: spec}}"""
    agg: dict[str, dict[str, str]] = defaultdict(dict)
    for label, p in DECL_SOURCES.items():
        for n, sp in parse_decl(p).items():
            agg[n][label] = sp
    return agg


def is_declared(canon: str, decl: dict[str, dict[str, str]]) -> bool:
    """按 pip 名或别名查表是否声明。"""
    if canon in decl:
        return True
    # 反查：import 名 → pip 名
    pip_candidates = IMPORT_TO_PIP.get(canon.lower(), set())
    if pip_candidates & decl.keys():
        return True
    # 下划线/连字符归一化后再查
    for k in decl.keys():
        if k.replace("_", "-") == canon.replace("_", "-"):
            return True
    return False


def resolve_import_name(canon: str, decl: dict[str, dict[str, str]]) -> str | None:
    """把 import 名映射回声明的 pip 名。"""
    if canon in decl:
        return canon
    for pip_name, names in ALIASES.items():
        if canon.lower() in {n.lower() for n in names} and pip_name in decl:
            return pip_name
    for k in decl.keys():
        if k.replace("_", "-") == canon.replace("_", "-"):
            return k
    return None


def scan_imports(scope: tuple[str, ...]) -> tuple[set[str], dict[str, list[str]]]:
    """递归扫 ai_agent/**/*.py；scope 控制是否包含 tests/。"""
    imports: set[str] = set()
    where: dict[str, list[str]] = defaultdict(list)
    skip_dirs = {
        "evals", "docs", "knowledge_base", "package",
        "__pycache__", "data", "node_modules",
    }
    for p in PKG.rglob("*.py"):
        rel = p.relative_to(PKG)
        parts = rel.parts
        if any(part in skip_dirs or part.startswith(".venv") for part in parts):
            continue
        top = parts[0]
        if top == "tests" and "tests" not in scope:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(
            r"^\s*(?:from\s+([A-Za-z_][A-Za-z0-9_.]*)|import\s+([A-Za-z_][A-Za-z0-9_.]*))",
            text,
            re.M,
        ):
            mod = (m.group(1) or m.group(2)).split(".")[0]
            if not mod or mod.startswith("_"):
                continue
            canon = normalize(mod)
            imports.add(canon)
            where[canon].append(str(rel).replace("\\", "/"))
    return imports, where


def main() -> None:
    decl = collect_decl()
    # runtime：仅业务代码（ai_agent/ 根 + 子包如 v2_slim/ v21_tools/ observability/）
    imports_rt, where_rt = scan_imports(scope=())
    # dev：业务代码 + tests/（dev 依赖本来就给测试用）
    imports_dev, where_dev = scan_imports(scope=("tests",))

    # 声明集中：识别"对应 import 名"映射回后查 import 集合
    # 证据集按声明来源分：runtime → imports_rt；dev → imports_dev（tests/ 也算）
    def evidence_for(source_label: str) -> set[str]:
        if source_label == "requirements.txt":
            return imports_rt
        return imports_dev  # requirements-dev.txt + pyproject.toml[dev]

    unused: list[tuple[str, dict[str, str]]] = []
    for pip_name, sources in decl.items():
        # 业务包内自身也算"使用"
        if pip_name in PY_MODULES or pip_name == "ai_agent":
            continue
        # 按来源分别匹配：每个来源都要在对应 evidence 集合里找到
        any_source_used = False
        for src in sources.keys():
            ev = evidence_for(src)
            candidates: set[str] = {pip_name, pip_name.replace("_", "-")}
            if pip_name in ALIASES:
                candidates.update(ALIASES[pip_name])
            if any(c.lower() in ev for c in candidates):
                any_source_used = True
                break
        if any_source_used:
            continue
        unused.append((pip_name, sources))

    # dev 依赖里"配置项"的特例说明：pytest_asyncio / pytest_cov / pytest_mock
    # / pytest_timeout / ruff / mypy / ipython 主要是 CLI/插件入口，
    # 不会在源码里直接 import，必须单独标注
    DEV_CONFIG_TOOLS = {
        "pytest_asyncio": "pytest.ini 中 `asyncio_mode=auto` 即生效，无需 import",
        "pytest_cov": "CLI 调用：`--cov=.` 由 pytest 加载；插件入口不是源码 import",
        "pytest_mock": "fixture 由 pytest 注入；tests/ 里常见 `mocker` fixture",
        "pytest_timeout": "装饰器 `@pytest.mark.timeout`；无源码 import",
        "ruff": "CLI 工具；不在运行时被 import",
        "mypy": "CLI 工具；不在运行时被 import",
        "ipython": "可选 shell；可在 `cli.py` 间接引用",
        "argcomplete": "shell completion（pyproject.toml 注释：可选）",
    }

    # 使用但未声明（去除 stdlib / 业务包内部模块）
    STDLIB = {
        "os", "sys", "re", "json", "time", "datetime", "pathlib", "typing", "asyncio",
        "logging", "functools", "itertools", "collections", "subprocess", "threading",
        "unittest", "traceback", "io", "tempfile", "shutil", "glob", "argparse",
        "copy", "hashlib", "urllib", "http", "email", "math", "random", "string",
        "dataclasses", "enum", "abc", "contextlib", "warnings", "weakref", "types",
        "ast", "inspect", "operator", "struct", "csv", "pickle", "gzip", "zipfile",
        "sqlite3", "socket", "ssl", "select", "signal", "platform", "importlib",
        "tomllib", "concurrent", "multiprocessing", "base64", "uuid", "textwrap",
        "secrets", "heapq", "bisect", "array", "numbers", "decimal", "fractions",
        "typing_extensions", "pprint", "timeit", "profile", "cProfile", "trace",
        "gc", "ctypes", "winreg", "msvcrt", "posixpath", "ntpath", "stat",
        "shlex", "pdb", "dis", "token", "tokenize", "symtable", "compileall",
        "py_compile", "tabnanny", "code", "codeop", "pyclbr", "rlcompleter",
        "site", "user", "runpy", "pkgutil", "modulefinder", "cgi", "wsgiref",
        "xml", "html", "webbrowser", "tkinter",
        "builtins", "getpass", "statistics", "wave",
    }
    INTERNAL: set[str] = set()
    for mod in imports_rt:
        if mod == "ai_agent":
            INTERNAL.add(mod)
    INTERNAL_HINTS = {
        # 业务模块（ai_agent/ 根 + 子包）
        "observability", "observability_pkg", "v2_slim", "experimental",
        "agent_workers", "agent_tool_router", "agent_config", "llm_minimax",
        "hitl_langgraph", "hitl_resume", "vector_store", "temperature_chart",
        "rag_service", "prompt_registry", "user_prompt_registry", "models_registry",
        "tools_registry", "json_log", "rate_limit", "hallucination", "audio_feedback",
        "audio_pipeline", "audio_semantic", "audio_streaming", "file_parser",
        "vision_multimodal_parser", "supervisor_agent", "supervisor_state",
        "task_intent", "task_scheduler", "skills", "plugin_manager", "sandbox",
        "message_bus", "message_protocol", "distributed_bus", "pub_sub_scenarios",
        "capability", "planner", "ab_testing", "adaptive_threshold", "multimodal",
        "sqlite_tools", "mcp_server", "mcp_tools", "start_mcp", "github_tools",
        "gitee_tools", "check_models", "build_all", "test_all", "v21_tools",
        # 同样存在于 py-modules 白名单里的同目录模块
        "config", "memory", "memory_store", "state_manager", "security",
        "rag", "llm_reliability", "reliability", "streaming", "monitor",
        "permission", "human_in_loop", "context_manager", "context_db",
        "multi_agent", "multi_agent_integration", "multi_agent_examples",
        "negotiation", "message_protocol", "tools", "agent",
        # 测试辅助模块名
        "common", "eval_set", "test_agent",
        # harness 子系统（不在 py-modules 但实际存在）
        "harness", "harness_runner", "harness_storage", "harness_cli",
        "harness_observability", "rag_demo", "rag_sanity",
        # ai_agent 入口（api/app/cli）
        "app", "main", "cli", "api",
    }
    undeclared: list[tuple[str, list[str]]] = []
    # 使用未声明的 evidence 用 rt（运行时 import 才算"使用未声明"）
    for mod in sorted(imports_rt):
        if mod in STDLIB or mod in INTERNAL or mod in INTERNAL_HINTS:
            continue
        if is_declared(mod, decl):
            continue
        undeclared.append((mod, where_rt.get(mod, [])[:3]))

    # 写报告
    lines: list[str] = []
    lines.append("# audit-b1-diff")
    lines.append("---")
    lines.append("scope: ai_agent/**/*.py（runtime=业务代码；dev=业务+tests/）")
    lines.append("decl_sources: requirements.txt, requirements-dev.txt, pyproject.toml[dev]")
    lines.append("")
    lines.append("## 声明总览")
    lines.append("")
    lines.append("| pip_name | spec | 来源 |")
    lines.append("| --- | --- | --- |")
    for n in sorted(decl.keys()):
        for src, sp in decl[n].items():
            lines.append(f"| `{n}` | `{sp}` | {src} |")
    lines.append("")
    # 把 unused 分流：运行时 / dev-config / 真可清理
    runtime_unused: list[tuple[str, dict[str, str]]] = []
    dev_unused: list[tuple[str, dict[str, str]]] = []
    for pip_name, sources in unused:
        if pip_name in DEV_CONFIG_TOOLS:
            dev_unused.append((pip_name, sources))
        else:
            runtime_unused.append((pip_name, sources))

    lines.append("## 运行时候选可清理（建议逐项裁决）")
    lines.append("")
    lines.append("| pip_name | spec | 来源 | 证据（grep 验证） |")
    lines.append("| --- | --- | --- | --- |")
    if runtime_unused:
        for n, sources in runtime_unused:
            ev = "整个 ai_agent/** 无 `import " + n + "` 或别名命中；建议二次 grep 确认（已用 Grep 工具交叉验证）"
            for src, sp in sources.items():
                lines.append(f"| `{n}` | `{sp}` | {src} | {ev} |")
    else:
        lines.append("| — | — | — | （无） |")
    lines.append("")
    lines.append("## dev 配置项（仅供说明，不建议清理）")
    lines.append("")
    lines.append("| pip_name | 用途 |")
    lines.append("| --- | --- |")
    if dev_unused:
        for n, _ in dev_unused:
            lines.append(f"| `{n}` | {DEV_CONFIG_TOOLS.get(n, '插件/CLI 入口')} |")
    else:
        lines.append("| — | — |")
    lines.append("")
    lines.append("## 使用但未声明（运行时 import）")
    lines.append("")
    # 已知的 transitive 提示（供用户参考"是不是真的漏声明"）
    TRANSITIVE_HINTS = {
        "langchain_core": "由 `langchain` 拉入；通常无需单独声明",
        "langgraph": "由 `langchain` / `langgraph-checkpoint-sqlite` 拉入",
        "pydantic": "由 FastAPI / langchain 拉入",
        "starlette": "由 FastAPI 拉入",
        "openai": "由 `langchain-openai` 拉入（如仅使用该包功能可不必单独声明）",
    }
    lines.append("| import | 证据路径（最多 3 条） | 备注 |")
    lines.append("| --- | --- | --- |")
    if undeclared:
        for mod, paths in undeclared:
            shown = ", ".join(f"`{p}`" for p in paths) if paths else "（路径缺失）"
            note = TRANSITIVE_HINTS.get(mod, "⚠ 真未声明：需补到 requirements.txt")
            lines.append(f"| `{mod}` | {shown} | {note} |")
    else:
        lines.append("| — | — | — |")
    lines.append("")
    lines.append("## 裁决建议（请逐项确认 Y/N）")
    lines.append("")
    lines.append("- **Y 删**：运行时未使用 + 不被任何间接依赖强依赖。")
    lines.append("- **N 留**：属于间接依赖（如 `tokenizers` 被 `sentence_transformers` 强依赖）；或用于 `pyproject.toml` 配置项。")
    lines.append("- **补声明**：使用但未声明 → 加到 `requirements.txt` 或写「运行时不直接 import 但需要部署」。")
    lines.append("")
    lines.append("## 不要做（边界）")
    lines.append("")
    lines.append("- 不直接删 `requirements*.txt` 任何行；本报告是「候选清单」，由用户裁决。")
    lines.append("- `evals/` `docs/` `knowledge_base/` `package/` `data/` 下的 import 不计入使用证据。")
    lines.append("- 内部模块名（`ai_agent.*`）按 `py-modules` 白名单识别，不算外部依赖。")
    lines.append("- `mcp[cli]` / `[standard]` 这类 extras 按父名解析（`uvicorn` 而非 `uvicorn[standard]`）。")
    lines.append("- dev 依赖的「未使用」≠「可清理」：pytest_asyncio/cov/mock/timeout 都是 pytest 插件入口。")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} bytes={OUT.stat().st_size}")
    print(f"unused={len(unused)} undeclared={len(undeclared)}")


if __name__ == "__main__":
    main()
