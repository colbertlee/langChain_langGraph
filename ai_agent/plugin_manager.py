"""
Plugin Manager（插件生态）

提供：
- PluginManifest    manifest 文件格式（name / version / author / dependencies / capabilities / hooks）
- PluginEntry      已注册的插件（含实例 + 状态）
- PluginManager    安装 / 启用 / 禁用 / 加载 / 升级
- Hook 系统        on_startup / on_message / pre_delegate / post_delegate / on_error

P3-17
"""

import importlib
import json
import os
import sys
import time
import uuid
import logging
import inspect
import asyncio
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============================================================
# PluginHook
# ============================================================

class PluginHook(str, Enum):
    """插件钩子点"""
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"
    ON_MESSAGE = "on_message"
    PRE_DELEGATE = "pre_delegate"
    POST_DELEGATE = "post_delegate"
    ON_ERROR = "on_error"
    ON_TASK_COMPLETED = "on_task_completed"


class PluginStatus(str, Enum):
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class PluginManifest:
    """插件 manifest"""
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    license: str = "MIT"
    # 入口（Python module 路径或文件路径）
    entry_point: str = ""
    # 依赖
    dependencies: List[str] = field(default_factory=list)  # 其它 plugin name
    python_requires: str = ">=3.9"
    # 提供能力
    capabilities: List[str] = field(default_factory=list)   # 新增 capability 名
    hooks: List[str] = field(default_factory=list)         # 实现哪些 HookPoint
    # 配置
    config_schema: Dict[str, Any] = field(default_factory=dict)
    # 元数据
    homepage: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "PluginManifest":
        # 过滤未知字段
        valid = {f.name for f in __import__("dataclasses").fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in valid})

    @classmethod
    def from_file(cls, path: str) -> "PluginManifest":
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if path.endswith(".json"):
            with open(path, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        elif path.endswith(".yaml") or path.endswith(".yml"):
            try:
                import yaml
                with open(path, "r", encoding="utf-8") as f:
                    return cls.from_dict(yaml.safe_load(f))
            except ImportError:
                raise ImportError("PyYAML required for .yaml manifests")
        raise ValueError(f"unsupported manifest format: {path}")

    def save_to_file(self, path: str) -> None:
        if path.endswith(".json"):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        else:
            raise ValueError(f"unsupported format: {path}")


# ============================================================
# PluginEntry
# ============================================================

@dataclass
class PluginEntry:
    """已安装插件"""
    manifest: PluginManifest
    instance: Any = None  # 插件实例
    status: PluginStatus = PluginStatus.INSTALLED
    installed_at: float = field(default_factory=time.time)
    loaded_at: Optional[float] = None
    error: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "manifest": self.manifest.to_dict(),
            "status": self.status.value,
            "installed_at": self.installed_at,
            "loaded_at": self.loaded_at,
            "error": self.error,
            "config": self.config,
            "has_instance": self.instance is not None,
        }


# ============================================================
# PluginManager
# ============================================================

class PluginManager:
    """
    插件管理器

    提供：
    - install(manifest)            登记 manifest
    - enable(plugin_name)          加载 + 启用
    - disable(plugin_name)         卸载 + 禁用
    - uninstall(plugin_name)       移除
    - emit_hook(hook, *args, **kwargs)  触发钩子
    - register_hook(hook, fn)      注册钩子回调（不动 module 的内部机制）
    """

    def __init__(self):
        self._plugins: Dict[str, PluginEntry] = {}  # name -> entry
        self._hooks: Dict[PluginHook, List[Callable]] = defaultdict(list)
        # 版本管理：name -> 版本
        self._active_versions: Dict[str, str] = {}

    # ----------------- 安装 / 启用 -----------------

    def install(
        self,
        manifest: PluginManifest,
        config: Optional[Dict] = None,
    ) -> PluginEntry:
        """登记 manifest"""
        existing = self._plugins.get(manifest.name)
        if existing and existing.manifest.version == manifest.version:
            return existing

        entry = PluginEntry(
            manifest=manifest,
            config=config or {},
        )
        self._plugins[manifest.name] = entry
        logger.info(f"[Plugin] installed {manifest.name}@v{manifest.version}")
        return entry

    def install_from_file(
        self,
        manifest_path: str,
        config: Optional[Dict] = None,
    ) -> PluginEntry:
        manifest = PluginManifest.from_file(manifest_path)
        return self.install(manifest, config=config)

    def enable(self, plugin_name: str) -> PluginEntry:
        entry = self._plugins.get(plugin_name)
        if not entry:
            raise KeyError(f"plugin {plugin_name} not installed")

        if entry.status == PluginStatus.ENABLED:
            return entry

        manifest = entry.manifest

        # 依赖检查
        for dep in manifest.dependencies:
            dep_entry = self._plugins.get(dep)
            if not dep_entry or dep_entry.status != PluginStatus.ENABLED:
                raise RuntimeError(f"dependency {dep} not enabled")

        # 加载 module
        try:
            if manifest.entry_point:
                module = importlib.import_module(manifest.entry_point)
                # 找 entry class（约定：module.PLUGIN_CLASS 或 module.Plugin）
                cls = getattr(module, "PLUGIN_CLASS", None) or getattr(module, "Plugin", None)
                if cls:
                    entry.instance = cls(entry.config)
                    # 调 on_load（如果存在）
                    if hasattr(entry.instance, "on_load"):
                        r = entry.instance.on_load()
                        if asyncio.iscoroutine(r):
                            asyncio.get_event_loop().run_until_complete(r)
            entry.status = PluginStatus.ENABLED
            entry.loaded_at = time.time()
            entry.error = None
            self._active_versions[plugin_name] = manifest.version
            logger.info(f"[Plugin] enabled {plugin_name}@v{manifest.version}")
        except Exception as e:
            entry.status = PluginStatus.ERROR
            entry.error = f"{type(e).__name__}: {e}"
            logger.error(f"[Plugin] failed to enable {plugin_name}: {e}")
            raise

        # 注册 hooks
        for hook_name in manifest.hooks:
            try:
                hook_enum = PluginHook(hook_name)
            except ValueError:
                continue
            if entry.instance and hasattr(entry.instance, hook_name):
                self._hooks[hook_enum].append(getattr(entry.instance, hook_name))

        return entry

    def disable(self, plugin_name: str) -> PluginEntry:
        entry = self._plugins.get(plugin_name)
        if not entry:
            return entry
        if entry.status != PluginStatus.ENABLED:
            return entry

        # 注销 hooks
        for hook_list in self._hooks.values():
            hook_list[:] = [
                f for f in hook_list
                if not (hasattr(f, '__self__',) and getattr(f.__self__, '_plugin_name', None) == plugin_name)
            ]
        if entry.instance and hasattr(entry.instance, "on_unload"):
            try:
                r = entry.instance.on_unload()
                if asyncio.iscoroutine(r):
                    asyncio.get_event_loop().run_until_complete(r)
            except Exception:
                pass
        entry.instance = None
        entry.status = PluginStatus.DISABLED
        self._active_versions.pop(plugin_name, None)
        logger.info(f"[Plugin] disabled {plugin_name}")
        return entry

    def uninstall(self, plugin_name: str) -> bool:
        if plugin_name in self._plugins:
            self.disable(plugin_name)
            self._plugins.pop(plugin_name, None)
            return True
        return False

    # ----------------- 升级 / 回滚 -----------------

    def upgrade(
        self,
        plugin_name: str,
        new_manifest: PluginManifest,
        config: Optional[Dict] = None,
    ) -> PluginEntry:
        """升级到新版本"""
        if plugin_name != new_manifest.name:
            raise ValueError(f"name mismatch: {plugin_name} vs {new_manifest.name}")
        old_entry = self._plugins.get(plugin_name)
        was_enabled = old_entry and old_entry.status == PluginStatus.ENABLED

        if was_enabled:
            self.disable(plugin_name)

        entry = self.install(new_manifest, config or (old_entry.config if old_entry else None))

        if was_enabled:
            self.enable(plugin_name)
        logger.info(
            f"[Plugin] upgraded {plugin_name} "
            f"{old_entry.manifest.version if old_entry else '-'} -> {new_manifest.version}"
        )
        return entry

    def rollback(self, plugin_name: str) -> bool:
        """简化的回滚：禁用当前 + 重新启用（如果有备份 manifest）"""
        # 实际需要备份历史 manifests 才能回滚；这里只 disable
        entry = self._plugins.get(plugin_name)
        if entry:
            self.disable(plugin_name)
            return True
        return False

    # ----------------- 钩子触发 -----------------

    def register_hook(
        self,
        hook: PluginHook,
        callback: Callable,
    ) -> None:
        """手动注册钩子回调（非 plugin 模块的方式）"""
        self._hooks[hook].append(callback)

    async def emit_hook(self, hook: PluginHook, *args, **kwargs) -> List[Any]:
        """触发钩子，并行调用所有回调"""
        results = []
        callbacks = list(self._hooks.get(hook, []))
        async def _run(cb):
            try:
                if asyncio.iscoroutinefunction(cb):
                    return await cb(*args, **kwargs)
                else:
                    return cb(*args, **kwargs)
            except Exception as e:
                logger.warning(f"hook {hook} callback failed: {e}")
                return None
        results = await asyncio.gather(*[_run(cb) for cb in callbacks])
        return [r for r in results if r is not None]

    def emit_hook_sync(self, hook: PluginHook, *args, **kwargs) -> List[Any]:
        """同步触发钩子"""
        results = []
        for cb in self._hooks.get(hook, []):
            try:
                r = cb(*args, **kwargs)
                if asyncio.iscoroutine(r):
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # fire-and-forget
                            loop.create_task(r)
                        else:
                            r = loop.run_until_complete(r)
                    except RuntimeError:
                        pass
                if r is not None:
                    results.append(r)
            except Exception as e:
                logger.warning(f"hook {hook} sync callback failed: {e}")
        return results

    # ----------------- 查询 -----------------

    def get(self, plugin_name: str) -> Optional[PluginEntry]:
        return self._plugins.get(plugin_name)

    def list_installed(self) -> List[PluginEntry]:
        return list(self._plugins.values())

    def list_enabled(self) -> List[PluginEntry]:
        return [e for e in self._plugins.values() if e.status == PluginStatus.ENABLED]

    def find_by_capability(self, capability: str) -> List[PluginEntry]:
        """找提供某 capability 的插件"""
        return [
            e for e in self._plugins.values()
            if capability in e.manifest.capabilities and e.status == PluginStatus.ENABLED
        ]

    # ----------------- 持久化 -----------------

    def save_state(self, path: str) -> None:
        """保存已安装插件 manifest + config"""
        data = {
            "plugins": [
                {
                    "manifest": e.manifest.to_dict(),
                    "config": e.config,
                }
                for e in self._plugins.values()
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_state(self, path: str) -> int:
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        n = 0
        for p in data.get("plugins", []):
            try:
                manifest = PluginManifest.from_dict(p["manifest"])
                self.install(manifest, config=p.get("config", {}))
                n += 1
            except Exception as e:
                logger.warning(f"Failed to load plugin state: {e}")
        return n

    # ----------------- 状态 -----------------

    def stats(self) -> Dict[str, Any]:
        return {
            "installed": len(self._plugins),
            "enabled": sum(1 for e in self._plugins.values() if e.status == PluginStatus.ENABLED),
            "disabled": sum(1 for e in self._plugins.values() if e.status == PluginStatus.DISABLED),
            "error": sum(1 for e in self._plugins.values() if e.status == PluginStatus.ERROR),
            "hooks": {h.value: len(cbs) for h, cbs in self._hooks.items()},
        }


# ============================================================
# 全局单例
# ============================================================

_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager


def reset_plugin_manager() -> None:
    global _plugin_manager
    _plugin_manager = None