"""Agent Preset 配置存储（v2.1）。

设计目标：
  - 用户可创建 / 编辑 / 删除 Agent 预设；系统内置 3 个不可删的预设。
  - 数据持久化到 SQLite，单文件、零依赖、跨平台。
  - 所有方法都是线程安全的（SQLite 默认同连接串行化 + check_same_thread=False）。
  - 提供纯函数 to_dict / from_dict 便于测试 & 序列化。

数据模型（AgentPreset）：
    id            str   —— 主键，前端生成或后端 uuid
    name          str   —— 显示名，必填
    description   str   —— 简短说明，可选
    avatar        str   —— emoji 或 icon 名
    system_prompt str   —— 多行 System Prompt
    temperature   float —— 0.0 - 2.0，默认 0.7
    tools         list[str] —— 工具名列表（与 tools_v2 / tools.py 注册的工具对齐）
    builtin       bool  —— True 表示系统内置，不可删
    created_at    float —— epoch 秒
    updated_at    float —— epoch 秒
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

# ============================================================
# 数据模型
# ============================================================


@dataclass
class AgentPreset:
    id: str
    name: str
    description: str = ""
    avatar: str = "🤖"
    system_prompt: str = ""
    temperature: float = 0.7
    tools: list[str] = field(default_factory=list)
    builtin: bool = False
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())

    # -----------------------------
    # 序列化
    # -----------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        # list 转 JSON 字符串便于 SQLite 持久化与跨语言兼容
        d["tools"] = list(self.tools or [])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AgentPreset":
        return cls(
            id=str(d["id"]),
            name=str(d.get("name", "Untitled")),
            description=str(d.get("description", "")),
            avatar=str(d.get("avatar", "🤖")),
            system_prompt=str(d.get("system_prompt", "")),
            temperature=float(d.get("temperature", 0.7)),
            tools=list(d.get("tools") or []),
            builtin=bool(d.get("builtin", False)),
            created_at=float(d.get("created_at") or time.time()),
            updated_at=float(d.get("updated_at") or time.time()),
        )

    # -----------------------------
    # 字段验证
    # -----------------------------
    def validate(self) -> None:
        """字段验证；非法时抛 ValueError。"""
        if not self.name or not self.name.strip():
            raise ValueError("name 不能为空")
        if not (0.0 <= float(self.temperature) <= 2.0):
            raise ValueError("temperature 必须在 [0.0, 2.0] 之间")
        # tools 必须是 list[str]
        for t in self.tools or []:
            if not isinstance(t, str) or not t.strip():
                raise ValueError(f"tools 含非法项: {t!r}")


# ============================================================
# SQLite 存储
# ============================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_presets (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    avatar        TEXT NOT NULL DEFAULT '🤖',
    system_prompt TEXT NOT NULL DEFAULT '',
    temperature   REAL NOT NULL DEFAULT 0.7,
    tools         TEXT NOT NULL DEFAULT '[]',  -- JSON 数组
    builtin       INTEGER NOT NULL DEFAULT 0,   -- 0/1
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_presets_builtin ON agent_presets(builtin);
"""


def _default_db_path() -> Path:
    """数据库默认放在 _HERE/agent_presets.db，可用 AGENT_PRESETS_DB 覆盖。"""
    here = Path(__file__).resolve().parent
    return Path(os.environ.get("AGENT_PRESETS_DB", str(here / "agent_presets.db")))


def _seed_presets() -> list[AgentPreset]:
    """系统内置 3 个不可删除的预设。"""
    now = time.time()
    return [
        AgentPreset(
            id="builtin-general",
            name="通用助手",
            description="适用于日常问答、写作、翻译等通用场景",
            avatar="🤖",
            system_prompt=(
                "你是一个友好、严谨的通用助手。请用简洁清晰的语言回答问题，"
                "如果不确定就如实告诉用户。"
            ),
            temperature=0.7,
            tools=[],
            builtin=True,
            created_at=now,
            updated_at=now,
        ),
        AgentPreset(
            id="builtin-refactor",
            name="代码重构专家",
            description="擅长 Python/JavaScript/TypeScript 重构与 code review",
            avatar="🛠️",
            system_prompt=(
                "你是一名资深软件工程师，专精代码重构与 code review。\n"
                "回答时请：1) 先指出问题；2) 给出最小可行修改；3) 列出潜在风险。"
            ),
            temperature=0.3,
            tools=["python_exec", "code_review", "file_io"],
            builtin=True,
            created_at=now,
            updated_at=now,
        ),
        AgentPreset(
            id="builtin-analyst",
            name="数据分析师",
            description="擅长数据分析、统计与可视化",
            avatar="📊",
            system_prompt=(
                "你是一名数据分析师。请基于用户提供的数据给出可解释的分析结论，"
                "必要时主动询问数据样本与目标指标。"
            ),
            temperature=0.5,
            tools=["python_interpreter", "web_search"],
            builtin=True,
            created_at=now,
            updated_at=now,
        ),
    ]


class AgentPresetStore:
    """Agent Preset 的 SQLite 持久化存储。

    用法：
        store = AgentPresetStore()              # 默认 db
        store = AgentPresetStore(":memory:")    # 内存 db（便于测试）
        store.list()                              # 列出全部
        store.get(id)                             # 取单个
        store.create(payload)                     # 新建（自动分配 id）
        store.update(id, patch)                   # 部分更新
        store.delete(id)                          # 删除（拒绝 builtin）
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _default_db_path()
        self._lock = threading.RLock()
        # check_same_thread=False 允许跨线程访问；写操作用 self._lock 串行化
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit，手工控制事务
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema_and_seed()

    # -----------------------------
    # 初始化
    # -----------------------------
    def _init_schema_and_seed(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            # 检查是否已有 builtin
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM agent_presets WHERE builtin=1"
            ).fetchone()
            if int(row["n"]) == 0:
                for p in _seed_presets():
                    self._upsert_locked(p)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> "AgentPresetStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -----------------------------
    # 底层 CRUD
    # -----------------------------
    def _row_to_obj(self, row: sqlite3.Row) -> AgentPreset:
        return AgentPreset(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            avatar=row["avatar"],
            system_prompt=row["system_prompt"],
            temperature=float(row["temperature"]),
            tools=json.loads(row["tools"] or "[]"),
            builtin=bool(row["builtin"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def _upsert_locked(self, p: AgentPreset) -> None:
        self._conn.execute(
            """
            INSERT INTO agent_presets (
                id, name, description, avatar, system_prompt,
                temperature, tools, builtin, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                avatar=excluded.avatar,
                system_prompt=excluded.system_prompt,
                temperature=excluded.temperature,
                tools=excluded.tools,
                builtin=excluded.builtin,
                updated_at=excluded.updated_at
            """,
            (
                p.id,
                p.name,
                p.description,
                p.avatar,
                p.system_prompt,
                p.temperature,
                json.dumps(list(p.tools or []), ensure_ascii=False),
                1 if p.builtin else 0,
                p.created_at,
                p.updated_at,
            ),
        )

    # -----------------------------
    # 对外 API
    # -----------------------------
    def list(self) -> list[AgentPreset]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM agent_presets ORDER BY builtin DESC, updated_at DESC"
            ).fetchall()
            return [self._row_to_obj(r) for r in rows]

    def get(self, preset_id: str) -> Optional[AgentPreset]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM agent_presets WHERE id=?", (preset_id,)
            ).fetchone()
            return self._row_to_obj(row) if row else None

    def create(self, payload: dict) -> AgentPreset:
        with self._lock:
            now = time.time()
            p = AgentPreset.from_dict(
                {
                    **payload,
                    "id": payload.get("id") or f"u-{uuid.uuid4().hex[:12]}",
                    "builtin": False,  # 用户新建的永远不是 builtin
                    "created_at": now,
                    "updated_at": now,
                }
            )
            p.validate()
            # id 冲突 → 抛错
            if self.get(p.id):
                raise ValueError(f"preset id 已存在: {p.id}")
            self._upsert_locked(p)
            return p

    def update(self, preset_id: str, patch: dict) -> AgentPreset:
        with self._lock:
            current = self.get(preset_id)
            if not current:
                raise KeyError(f"preset 不存在: {preset_id}")
            patch = dict(patch or {})
            # 不可通过 patch 改的字段
            patch.pop("id", None)
            patch.pop("builtin", None)        # builtin 不可降级
            patch.pop("created_at", None)     # created_at 不可改
            merged = {**current.to_dict(), **patch}
            merged["id"] = preset_id
            merged["builtin"] = current.builtin
            merged["created_at"] = current.created_at
            merged["updated_at"] = time.time()
            p = AgentPreset.from_dict(merged)
            p.validate()
            self._upsert_locked(p)
            return p

    def delete(self, preset_id: str) -> bool:
        with self._lock:
            current = self.get(preset_id)
            if not current:
                return False
            if current.builtin:
                raise PermissionError(f"系统内置预设不可删除: {preset_id}")
            self._conn.execute(
                "DELETE FROM agent_presets WHERE id=?", (preset_id,)
            )
            return True

    def reset_to_seed(self) -> list[AgentPreset]:
        """重置为 3 个内置预设（保留已删除的非 builtin；不删任何记录）。
        主要用于测试。
        """
        with self._lock:
            for p in _seed_presets():
                self._upsert_locked(p)
            return self.list()


# ============================================================
# 模块级单例（方便 app.py 直接使用）
# ============================================================

_default_store: Optional[AgentPresetStore] = None
_default_lock = threading.Lock()


def get_preset_store() -> AgentPresetStore:
    """获取默认全局 PresetStore 单例。"""
    global _default_store
    with _default_lock:
        if _default_store is None:
            _default_store = AgentPresetStore()
        return _default_store


def reset_default_store_for_tests() -> None:
    """测试用：清空全局单例。"""
    global _default_store
    with _default_lock:
        if _default_store is not None:
            _default_store.close()
        _default_store = None


__all__ = [
    "AgentPreset",
    "AgentPresetStore",
    "get_preset_store",
    "reset_default_store_for_tests",
]
