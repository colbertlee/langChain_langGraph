"""code_interpreter — v2.1 受限 Python 执行沙箱

设计：
  - subprocess 隔离 + 超时（默认 10s）+ 输入关闭（不让 stdin 等读）
  - 启动前清空 sandbox 目录；执行后扫描新增的图片（*.png / *.jpg / *.svg）
    自动复制到 _UPLOAD_ROOT 并返回 url
  - 资源限制（Windows 上 resource 模块不可用，用 timeout + 简单 stdout/stderr
    截断；Linux 上可启用 resource.RLIMIT_AS/RLIMIT_CPU）

接口：
  python_interpreter(code: str, timeout: int = 10) -> dict
    返回：
      {
        "stdout": str,
        "stderr": str,
        "exit_code": int,
        "timed_out": bool,
        "images": [  # 自动捕获的图
          {"path": "/abs/path", "url": "/uploads/...", "filename": "..."}
        ],
        "duration_ms": int,
      }
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 上传根目录（与 app.py 共用）—— 这里用 import 兜底
try:
    from app import _UPLOAD_ROOT as _UPLOAD_DIR  # type: ignore
except Exception:
    # 单测/独立使用时临时目录
    _UPLOAD_DIR = Path(tempfile.gettempdir()) / "ai_agent_uploads"
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


def _write_code(code: str, workdir: Path) -> Path:
    """把 code 写到 workdir/code.py（避免 shell 转义问题）。"""
    f = workdir / "code.py"
    f.write_text(code, encoding="utf-8")
    return f


def _scan_images(workdir: Path, before: set[str]) -> list[dict]:
    """扫描 workdir 中 before 之后新增的图片，返回 [{path, url, filename}]。"""
    out: list[dict] = []
    if not workdir.exists():
        return out
    for p in workdir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        if p.name in before:
            continue
        # 复制到 uploads 目录，命名规则与 /api/upload 一致
        try:
            unique = f"pyimg-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}{p.suffix.lower()}"
            dest = _UPLOAD_DIR / unique
            shutil.copy2(p, dest)
            out.append(
                {
                    "path": str(p.resolve()),
                    "filename": p.name,
                    "url": f"/uploads/{unique}",
                }
            )
        except Exception as e:
            logger.warning(f"capture image {p} failed: {e}")
    return out


def python_interpreter(code: str, timeout: int = 10, workdir: Optional[Path] = None) -> dict:
    """在 sandbox subprocess 中执行 Python 代码。

    Args:
        code: Python 源代码
        timeout: 秒（默认 10）
        workdir: 临时工作目录（默认用 tempfile.mkdtemp）

    Returns:
        dict（见模块 docstring）
    """
    started = time.time()
    if workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="pyexec-"))
    workdir.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in workdir.iterdir() if p.is_file()}
    script = _write_code(code, workdir)

    # 构造隔离环境变量：去掉 OPENAI_API_KEY / TAVILY_API_KEY 等敏感信息
    safe_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # Windows 需要
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "HOME": os.environ.get("HOME", ""),
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLBACKEND": "Agg",  # matplotlib 无显示器
    }
    # Python 解释器
    py = sys.executable or "python"

    stdout_data = ""
    stderr_data = ""
    exit_code = -1
    timed_out = False

    try:
        # Windows 上需 shell=False，CREATE_NEW_PROCESS_GROUP 用于强制 kill
        kwargs: dict = {
            "cwd": str(workdir),
            "env": safe_env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.DEVNULL,
            "text": True,
            "timeout": timeout,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        proc = subprocess.run([py, str(script)], **kwargs)
        stdout_data = proc.stdout or ""
        stderr_data = proc.stderr or ""
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        # Windows 上 timeout 不会自动 kill，要手动 kill
        if e.stdout:
            stdout_data = (e.stdout.decode("utf-8", "ignore") if isinstance(e.stdout, bytes) else e.stdout)
        if e.stderr:
            stderr_data = (e.stderr.decode("utf-8", "ignore") if isinstance(e.stderr, bytes) else e.stderr)
        stderr_data += f"\n[TimeoutError] 执行超过 {timeout}s 已被中止"
    except Exception as e:
        stderr_data = f"[execution error] {type(e).__name__}: {e}"
        exit_code = -1

    # 截断超大输出
    MAX_OUT = 16_000
    if len(stdout_data) > MAX_OUT:
        stdout_data = stdout_data[:MAX_OUT] + "\n... (stdout 截断)"
    if len(stderr_data) > MAX_OUT:
        stderr_data = stderr_data[:MAX_OUT] + "\n... (stderr 截断)"

    images = _scan_images(workdir, before)
    duration_ms = int((time.time() - started) * 1000)
    return {
        "stdout": stdout_data,
        "stderr": stderr_data,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "images": images,
        "duration_ms": duration_ms,
    }


def format_result_md(result: dict) -> str:
    """把 python_interpreter 结果格式化为 Markdown（便于注入 Agent context）。"""
    lines: list[str] = []
    lines.append(f"### Python 执行结果")
    lines.append(f"- exit_code: `{result.get('exit_code')}`")
    if result.get("timed_out"):
        lines.append("- ⚠️ 执行超时被中止")
    if result.get("duration_ms") is not None:
        lines.append(f"- 耗时: {result['duration_ms']}ms")
    out = (result.get("stdout") or "").strip()
    if out:
        lines.append("\n**stdout:**\n```\n" + out + "\n```")
    err = (result.get("stderr") or "").strip()
    if err:
        lines.append("\n**stderr:**\n```\n" + err + "\n```")
    imgs = result.get("images") or []
    if imgs:
        lines.append(f"\n**生成图片 ({len(imgs)}):**")
        for img in imgs:
            lines.append(f"- ![{img.get('filename')}]({img.get('url')})")
    return "\n".join(lines)


__all__ = ["python_interpreter", "format_result_md", "IMAGE_EXTS"]
