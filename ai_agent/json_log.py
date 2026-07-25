"""
json_log - 结构化 JSON 日志（C3）

背景：
- 13.4.2 工具调用正确率测试需要可机读日志；
- 当前 logging 是文本格式（agent.log / 控制台），无法直接入库分析；
- 本模块提供：
    1) JsonFormatter：把 LogRecord 序列化为 JSON（保留 logger/level/time/msg + extra 字段）；
    2) configure_json_logging()：一行替换 logging.basicConfig，把所有日志变成 JSON；
    3) get_logger(name)：统一 logger 入口，自动追加 context（如 session_id/trace_id）。

使用示例：
    from json_log import configure_json_logging, get_logger
    configure_json_logging(level="INFO", log_file="agent.log.json")
    log = get_logger(__name__)
    log.info("tool called", extra={"tool": "search_web", "args": {"q": "..."}})
    # => {"ts": "2026-01-01T...", "level": "INFO", "logger": "...", "msg": "tool called", "tool": "search_web", ...}
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging import LogRecord
from typing import Any, Dict, Optional


# 保留这些内置字段，避免重复输出
_RESERVED_LOG_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    """把 LogRecord 序列化为单行 JSON。"""

    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra

    def format(self, record: LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # 异常
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info
        # extra 字段
        if self.include_extra:
            for key, val in record.__dict__.items():
                if key in _RESERVED_LOG_ATTRS:
                    continue
                if key.startswith("_"):
                    continue
                try:
                    json.dumps(val)
                    payload[key] = val
                except (TypeError, ValueError):
                    payload[key] = repr(val)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def configure_json_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    also_console: bool = True,
) -> None:
    """把 root logger 的 handler 全部替换为 JSON 输出。

    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        log_file: JSON 日志文件路径；为 None 表示不写文件
        also_console: 是否同时输出到 stderr（便于本地调试）
    """
    global _configured
    root = logging.getLogger()
    # 清掉已有 handler，避免重复
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = JsonFormatter()

    if also_console:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(formatter)
        root.addHandler(sh)

    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """统一 logger 入口；首次调用会自动配置 JSON 输出。"""
    if not _configured:
        configure_json_logging()
    return logging.getLogger(name)


def bind_context(logger: logging.Logger, **ctx) -> logging.Logger:
    """给 logger 绑定上下文，后续日志自动带上这些字段。

    Returns:
        新 logger（用 LoggerAdapter 包装）
    """
    return logging.LoggerAdapter(logger, ctx)


__all__ = [
    "JsonFormatter",
    "configure_json_logging",
    "get_logger",
    "bind_context",
]