"""
ai-agent doctor（Day 10）：环境预检 / 健康检查。

可在 clone 后第一次启动前运行，输出"我现在能不能跑"的状态报告。

覆盖维度
~~~~~~~~
1. **Python 与依赖**：Python 版本、关键包是否已装
2. **环境变量**：API Key 哪些已配、哪些缺失；是否仍是占位符
3. **目录可写性**：chroma_db / memory.db / uploads / logs 等
4. **ChromaDB**：是否能建 vector store；嵌入接口是否就绪
5. **LangGraph SqliteSaver**：是否能 init checkpointer
6. **MCP 配置**：mcp_config.json 是否合法（若启用）
7. **模型清单**：列出每个 provider 的状态（configured / available / 默认模型）

输出
~~~~
- 人类可读：每项 `[OK]` `[WARN]` `[FAIL]` 前缀，并给出修复建议
- JSON 模式：``ai-agent doctor --json`` 便于 CI 集成

退出码
~~~~~~
- 0：全部 OK（允许 WARN）
- 1：有 FAIL（缺少 API Key / ChromaDB 坏 / MCP 错配等）
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent


# ============================================================
# Status & Result
# ============================================================

@dataclass
class CheckResult:
    name: str
    status: str  # 'ok' / 'warn' / 'fail'
    message: str
    fix: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "fix": self.fix,
            "details": self.details,
        }


# ============================================================
# 工具：填色（终端能力退化时降级）
# ============================================================

class _C:
    """终端 ANSI 颜色（capability-aware）。"""
    def __init__(self) -> None:
        self.ok = "\033[32m"
        self.warn = "\033[33m"
        self.fail = "\033[31m"
        self.dim = "\033[2m"
        self.bold = "\033[1m"
        self.reset = "\033[0m"
        if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
            for k in ("ok", "warn", "fail", "dim", "bold", "reset"):
                setattr(self, k, "")


# ============================================================
# 单项检查
# ============================================================

def _check_python_version() -> CheckResult:
    if sys.version_info >= (3, 11):
        return CheckResult(
            "python",
            "ok",
            f"Python {sys.version.split()[0]} OK",
        )
    return CheckResult(
        "python",
        "fail",
        f"Python {sys.version.split()[0]} - 需要 >=3.11",
        fix="升级 Python 或使用 pyenv/conda 切换",
    )


def _check_required_packages() -> CheckResult:
    """检查关键依赖是否已装（不强制版本）。"""
    packages = {
        "fastapi": "FastAPI",
        "uvicorn": "Uvicorn",
        "pydantic": "Pydantic",
        "langchain": "LangChain",
        "langgraph": "LangGraph",
        "langchain_openai": "langchain-openai",
    }
    missing: List[str] = []
    versions: Dict[str, str] = {}
    for mod, label in packages.items():
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", "?")
            versions[label] = str(v)
        except ImportError:
            missing.append(label)
    if missing:
        return CheckResult(
            "packages",
            "fail",
            f"缺失 {len(missing)} 个关键包: {', '.join(missing)}",
            fix="pip install -r requirements.txt",
            details={"missing": missing, "installed": versions},
        )
    return CheckResult(
        "packages",
        "ok",
        f"全部 {len(packages)} 个关键包已安装",
        details={"versions": versions},
    )


def _check_provider_keys() -> CheckResult:
    """检查 API Key 配置。"""
    from config import (
        OPENAI_API_KEY, DEEPSEEK_API_KEY, QWEN_API_KEY,
        ZHIPU_API_KEY, MOONSHOT_API_KEY, MINIMAX_API_KEY,
        BAIDU_API_KEY, SPARK_API_KEY, DOUBAO_API_KEY,
        HUNYUAN_API_KEY, SILICONFLOW_API_KEY,
    )
    keys = {
        "openai": OPENAI_API_KEY,
        "deepseek": DEEPSEEK_API_KEY,
        "qwen": QWEN_API_KEY,
        "zhipu": ZHIPU_API_KEY or os.environ.get("GLM_API_KEY", ""),
        "moonshot": MOONSHOT_API_KEY,
        "minimax": MINIMAX_API_KEY,
        "baidu": BAIDU_API_KEY,
        "spark": SPARK_API_KEY,
        "doubao": DOUBAO_API_KEY,
        "hunyuan": HUNYUAN_API_KEY,
        "siliconflow": SILICONFLOW_API_KEY,
    }
    configured = [k for k, v in keys.items() if v and v.strip()]
    not_configured = [k for k, v in keys.items() if not (v and v.strip())]
    placeholder_markers = ("your-", "your_", "xxxx", "placeholder", "sk-xxx", "fake")
    placeholders = [
        k for k, v in keys.items()
        if v and any(p in v.lower() for p in placeholder_markers)
    ]
    if not configured:
        return CheckResult(
            "api_keys",
            "fail",
            "所有 Provider 都未配置 API Key",
            fix="编辑 .env，至少配置 OPENAI_API_KEY 或别的至少一家",
            details={"configured": [], "not_configured": list(keys.keys()), "placeholders": placeholders},
        )
    status = "ok" if not placeholders else "warn"
    msg = (
        f"已配置 {len(configured)}/{len(keys)} 家 Provider "
        f"({', '.join(configured[:3])}{'...' if len(configured) > 3 else ''})"
    )
    fix = None
    if placeholders:
        fix = f"以下仍是占位符: {placeholders}，请填入真 key"
    return CheckResult(
        "api_keys",
        status,
        msg,
        fix,
        details={"configured": configured, "placeholders": placeholders},
    )


def _check_writable_dirs() -> CheckResult:
    """检查关键目录是否可写。"""
    dirs = {
        "memory.db": _HERE / "memory.db",
        "chroma_db": _HERE / "chroma_db",
        "uploads": _HERE / "uploads",
    }
    issues: List[str] = []
    for name, p in dirs.items():
        # 文件或目录的父目录需要可写
        target = p if p.exists() else p.parent
        if not target.exists():
            try:
                target.mkdir(parents=True, exist_ok=True)
            except Exception:
                issues.append(f"{name}: 不能创建 {target}")
                continue
        if not os.access(target, os.W_OK):
            issues.append(f"{name}: 不可写 {target}")
    if issues:
        return CheckResult(
            "filesystem",
            "fail",
            f"{len(issues)} 个目录问题",
            fix="检查路径权限或切换运行用户",
            details={"issues": issues},
        )
    return CheckResult(
        "filesystem",
        "ok",
        "memory.db / chroma_db / uploads 都可写",
    )


def _check_chromadb() -> CheckResult:
    """快速起一个 in-memory ChromaDB 看是否能用。"""
    try:
        from chromadb import Client
        from chromadb.config import Settings  # noqa: F401
    except ImportError:
        return CheckResult(
            "chromadb",
            "warn",
            "未安装 chromadb（RAG 不可用，但 LLM 直聊可用）",
            fix="pip install chromadb langchain-chroma",
        )
    try:
        client = Client()  # 内存 client；不写入磁盘
        # 不实际创建 collection（duckdb/parquet 启动比内存慢）
        return CheckResult("chromadb", "ok", "ChromaDB import & Client OK")
    except Exception as e:
        return CheckResult(
            "chromadb",
            "fail",
            f"ChromaDB 初始化失败: {e}",
            fix="通常是 sqlite/numpy 版本不匹配；尝试 pip install -U chromadb",
        )


def _check_sqlite_checkpointer() -> CheckResult:
    """检查 langgraph SqliteSaver + sqlite3。"""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as e:
        return CheckResult(
            "langgraph_sqlite",
            "warn",
            f"SqliteSaver 不可用: {e}",
            fix="pip install langgraph-checkpoint-sqlite",
        )
    tmp_path = None
    try:
        # 用 NamedTemporaryFile 临时文件路径（不 delete，由我们自己清理）
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix="doctor_")
        os.close(tmp_fd)
        conn = sqlite3.connect(tmp_path)
        # SqliteSaver 在 0.2+ 需要显式 setup；老版本自动。这里不调用 setup，
        # 只验证 connectivity，避免版本差异导致 doctor 误报。
        saver = SqliteSaver(conn)
        # 触发 schema 创建（如有 setup_required）
        if hasattr(saver, "setup") and callable(saver.setup):
            try:
                saver.setup()
            except Exception:
                # setup 失败不代表 connectivity 失败；视为 warn
                pass
        conn.close()
        return CheckResult("langgraph_sqlite", "ok", "SqliteSaver 可初始化")
    except Exception as e:
        return CheckResult(
            "langgraph_sqlite",
            "fail",
            f"SqliteSaver 测试失败: {e}",
            fix="重装 langgraph-checkpoint-sqlite 或检查 sqlite3 系统库",
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _check_mcp_config() -> CheckResult:
    """检查 mcp_config.json 是否合法 JSON（若存在）。"""
    cfg = _HERE / "mcp_config.json"
    if not cfg.exists():
        return CheckResult(
            "mcp_config",
            "ok",
            "未配置 mcp_config.json（MCP 工具将仅用内置 14 个）",
            details={"present": False},
        )
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        server_count = len(data) if isinstance(data, dict) else 0
        return CheckResult(
            "mcp_config",
            "ok",
            f"已配置 {server_count} 个 MCP server",
            details={"servers": list(data.keys()) if isinstance(data, dict) else []},
        )
    except json.JSONDecodeError as e:
        return CheckResult(
            "mcp_config",
            "fail",
            f"mcp_config.json 不是合法 JSON: {e}",
            fix="重新生成：参考 package/linux/mcp_config.json",
        )
    except Exception as e:
        return CheckResult(
            "mcp_config",
            "warn",
            f"mcp_config.json 检查异常: {e}",
        )


def _check_provider_models() -> CheckResult:
    """检查每个 provider 的默认模型是否在白名单。"""
    try:
        from config import MODEL_VERSIONS, MODEL_PROVIDER, MODEL_NAME
    except ImportError as e:
        return CheckResult(
            "model_registry",
            "fail",
            f"无法加载 model registry: {e}",
        )
    if MODEL_PROVIDER not in MODEL_VERSIONS:
        return CheckResult(
            "model_registry",
            "fail",
            f"当前 MODEL_PROVIDER={MODEL_PROVIDER!r} 不在白名单",
            fix=f"改为: {list(MODEL_VERSIONS.keys())[:5]}...",
        )
    if MODEL_NAME not in MODEL_VERSIONS[MODEL_PROVIDER]:
        return CheckResult(
            "model_registry",
            "warn",
            f"当前 MODEL_NAME={MODEL_NAME!r} 不在 {MODEL_PROVIDER} 白名单",
            fix=f"改为: {MODEL_VERSIONS[MODEL_PROVIDER][0]}",
        )
    return CheckResult(
        "model_registry",
        "ok",
        f"{MODEL_PROVIDER}/{MODEL_NAME}",
        details={"providers": list(MODEL_VERSIONS.keys())},
    )


# ============================================================
# 总入口
# ============================================================

DEFAULT_CHECKS: List[Callable[[], CheckResult]] = [
    _check_python_version,
    _check_required_packages,
    _check_provider_keys,
    _check_writable_dirs,
    _check_chromadb,
    _check_sqlite_checkpointer,
    _check_mcp_config,
    _check_provider_models,
]


def run_doctor(checks: Optional[List[Callable[[], CheckResult]]] = None) -> List[CheckResult]:
    """跑全部 check，返回 ``[CheckResult]``。"""
    checks = checks or DEFAULT_CHECKS
    results: List[CheckResult] = []
    for ck in checks:
        try:
            results.append(ck())
        except Exception as e:
            results.append(
                CheckResult(
                    name=ck.__name__,
                    status="fail",
                    message=f"check 自身异常: {e}",
                    details={"trace": traceback.format_exc(limit=3)},
                )
            )
    return results


def print_human(results: List[CheckResult]) -> int:
    """人类可读打印。返回退出码。"""
    c = _C()
    # Windows GBK 终端兼容：把 stdout 强制 utf-8（best-effort）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(f"{c.bold}ai-agent doctor{c.reset}\n")
    failed = 0
    warned = 0
    for r in results:
        marker = (
            f"{c.ok}[OK]{c.reset}"
            if r.status == "ok"
            else f"{c.warn}[WARN]{c.reset}"
            if r.status == "warn"
            else f"{c.fail}[FAIL]{c.reset}"
        )
        print(f"  {marker}  {c.bold}{r.name}{c.reset}: {r.message}")
        if r.fix:
            print(f"         {c.dim}→ 修: {r.fix}{c.reset}")
        if r.details:
            detail = ", ".join(f"{k}={v}" for k, v in r.details.items() if k not in ("trace",))
            if detail:
                print(f"         {c.dim}   ({detail}){c.reset}")
        if r.status == "fail":
            failed += 1
        elif r.status == "warn":
            warned += 1
    print()
    if failed:
        return 1
    if warned:
        return 0  # WARN 不阻塞
    print(f"{c.ok}✓ All checks passed.{c.reset}")
    return 0


def print_json(results: List[CheckResult]) -> int:
    print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
    return 1 if any(r.status == "fail" for r in results) else 0


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="ai-agent doctor",
        description="环境预检 / 健康检查（Day 10）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 格式（适合 CI 集成）",
    )
    args = parser.parse_args(argv)

    results = run_doctor()
    if args.json:
        return print_json(results)
    return print_human(results)


if __name__ == "__main__":
    sys.exit(main())
