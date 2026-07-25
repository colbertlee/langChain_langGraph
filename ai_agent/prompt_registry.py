"""Prompt Registry — 提示词模板化与版本化管理（阶段 A1 + A2）。

设计目标：
- 把"硬编码 system prompt"升级为**可注册、可版本化**的模板；
- 模板分三段：`system`（全局身份）+ `role`（当前角色人设）+ `tools`（动态工具清单）；
- 支持变量注入（`format(template, **kwargs)` 风格）；
- 同一名字可以登记多个版本，`active_version` 决定默认渲染版本；
- 提供 `rollback(name, version)` 让上层在出错时回退到上一个稳定版；
- 暴露 `list_templates()` / `get_active_template(name)` 给 HTTP API 用于 UI 展示。

使用方式：
    from prompt_registry import get_prompt_registry

    reg = get_prompt_registry()
    system = reg.render(
        name="default",
        variables={"intent": "query"},
        tools=tool_lines,
    )
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 模板数据模型
# ============================================================


@dataclass
class PromptTemplate:
    """单个版本的提示词模板。

    Attributes:
        name: 模板名（如 "default" / "code_helper"）
        version: 版本号（字符串，自管，约定 semver："1.0.0"）
        author: 作者/团队（仅做展示）
        changelog: 变更说明（仅做展示）
        system_block: 全局身份段（不变的"你是一个..."）
        role_block: 角色人设段（按角色/场景切换）
        tool_block_template: 工具清单模板（含 `{tools}` 占位符）
        cot_instructions: 思维链指令（注入到末尾，告诉模型先思考再回答）
        variables: 该模板支持的变量名集合（用于校验）
    """

    name: str
    version: str = "1.0.0"
    author: str = "system"
    changelog: str = ""

    # 模板段（任一段为空字符串都视作跳过该段）
    system_block: str = ""
    role_block: str = ""
    tool_block_template: str = "可用工具列表：\n{tools}\n"

    # 阶段 A4：可由外部开关关闭
    cot_instructions: str = ""

    # 期望变量（用于 render 校验，缺失时打 warning 不抛异常）
    variables: List[str] = field(default_factory=list)

    # 元数据
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "changelog": self.changelog,
            "system_block": self.system_block,
            "role_block": self.role_block,
            "tool_block_template": self.tool_block_template,
            "cot_instructions": self.cot_instructions,
            "variables": list(self.variables),
            "created_at": self.created_at,
        }


# ============================================================
# 默认模板（兼容旧 _build_system_prompt 的输出）
# ============================================================


def _build_default_template_v1() -> PromptTemplate:
    """与原 _build_system_prompt 行为一致的 v1.0.0 模板。

    行为契约：
    - 不强制要求 CoT（旧行为）；
    - tools 列表为空时显示"（暂无可用工具）"；
    - 不暴露任何带 `## 思考 ##` 指令的字段。
    """
    return PromptTemplate(
        name="default",
        version="1.0.0",
        author="system",
        changelog="兼容原 _build_system_prompt 的行为，作为回滚兜底版本。",
        system_block=(
            "你是一个智能助手，能够根据用户需求选择合适的工具完成任务。\n"
            "回答要友好、简洁、准确。如果不需要使用工具，可以直接回答用户。\n\n"
        ),
        role_block="",
        tool_block_template="可用工具列表：\n{tools}\n",
        cot_instructions="",
        variables=["tools"],
    )


def _build_default_template_v2() -> PromptTemplate:
    """v2.0.0：引入 CoT + 角色人设分段。

    差异：
    - system 段拆出"风格 / 安全 / 输出格式"三个子段；
    - role 段可被上层覆盖（plan 模式 / code 模式）；
    - 默认开启 CoT（`## 思考 ##`），阶段 A4 启用；
    - 工具清单前增加"何时调用工具"的判断提示。
    """
    return PromptTemplate(
        name="default",
        version="2.0.0",
        author="system",
        changelog="阶段 A：拆分三段模板 + 显式 CoT 注入。",
        system_block=(
            "你是一个智能助手，能够根据用户需求选择合适的工具完成任务。\n\n"
            "【风格】回答要友好、简洁、准确；如无必要，不要堆砌客套话。\n"
            "【安全】拒绝执行危险指令（如 rm -rf、删除系统文件、暴露他人隐私）。\n"
            "【输出格式】默认使用 Markdown；超过 3 步的操作先给出思路再执行。\n\n"
        ),
        role_block="",
        tool_block_template=(
            "【何时调用工具】当且仅当回答需要外部事实或副作用时调用；闲聊/概念解释直接答。\n"
            "可用工具列表：\n{tools}\n"
        ),
        cot_instructions=(
            "【思维链】复杂任务先输出 '## 思考 ##' 段落（含拆解、依赖、风险），"
            "再输出 '## 回答 ##' 段落。不要把思考过程暴露给最终用户的口语部分。"
        ),
        variables=["tools", "intent"],
    )


# ============================================================
# 注册表
# ============================================================


class PromptRegistry:
    """提示词模板注册中心（线程安全）。

    - 同名模板可登记多版本；`active_versions[name]` 记录当前激活版本；
    - `register(template)` 时若版本已存在则覆盖（用于热修复）；
    - `rollback(name, version)` 把激活版本切到历史版本；
    - `render(name, variables, tools)` 输出最终 system prompt。
    """

    def __init__(self):
        self._lock = threading.RLock()
        # name -> version -> PromptTemplate
        self._versions: Dict[str, Dict[str, PromptTemplate]] = {}
        self._active: Dict[str, str] = {}

        # 初始化默认版本
        v1 = _build_default_template_v1()
        v2 = _build_default_template_v2()
        self.register(v1)
        self.register(v2)
        self._active["default"] = v2.version  # 默认用 v2（开启 CoT）

        logger.info(
            f"PromptRegistry initialized: default active={v2.version}, "
            f"available_versions={[v.version for v in [v1, v2]]}"
        )

    # ----------------- 注册 / 版本管理 -----------------

    def register(self, template: PromptTemplate) -> None:
        """注册一个模板版本。"""
        with self._lock:
            bucket = self._versions.setdefault(template.name, {})
            existed = template.version in bucket
            bucket[template.version] = template
            # 若该名字尚未设激活版本，默认指向首个注册版本
            if template.name not in self._active:
                self._active[template.name] = template.version
            logger.info(
                f"Prompt registered: name={template.name} version={template.version} "
                f"overwrite={existed}"
            )

    def rollback(self, name: str, version: str) -> bool:
        """把指定模板切回历史版本。

        Returns:
            是否成功；失败（版本不存在）时返回 False 且不动 active。
        """
        with self._lock:
            if name not in self._versions:
                logger.warning(f"rollback: unknown template {name}")
                return False
            if version not in self._versions[name]:
                logger.warning(
                    f"rollback: unknown version {version} for template {name}"
                )
                return False
            self._active[name] = version
            logger.info(f"Prompt rolled back: {name} -> {version}")
            return True

    def set_active(self, name: str, version: str) -> bool:
        """显式设置当前激活版本（与 rollback 等价，语义更清晰）。"""
        return self.rollback(name, version)

    # ----------------- 渲染 -----------------

    def render(
        self,
        name: str = "default",
        variables: Optional[Dict[str, str]] = None,
        tools: Optional[List[str]] = None,
    ) -> str:
        """渲染最终 system prompt。

        Args:
            name: 模板名；未注册时回退到 "default"。
            variables: 注入到 role/tool 模板段的变量；如缺失只 warn 不抛异常。
            tools: 工具清单（每项为 "- name: desc" 字符串）。

        Returns:
            拼接完成的 system prompt（含 CoT 指令，若启用）。
        """
        variables = variables or {}
        template = self._get_active(name)

        parts: List[str] = []
        if template.system_block:
            parts.append(template.system_block)
        if template.role_block:
            # 角色段也支持变量注入
            try:
                parts.append(template.role_block.format(**variables))
            except KeyError as e:
                logger.warning(f"role_block missing variable: {e}")
                parts.append(template.role_block)

        if template.tool_block_template:
            tools_text = "\n".join(tools) if tools else "（暂无可用工具）"
            try:
                parts.append(template.tool_block_template.format(tools=tools_text))
            except KeyError as e:
                logger.warning(f"tool_block_template missing variable: {e}")
                parts.append(template.tool_block_template)

        if template.cot_instructions:
            parts.append("\n" + template.cot_instructions + "\n")

        # 校验 variables（仅警告，不抛异常）
        missing = [v for v in template.variables if v not in variables and v != "tools"]
        if missing:
            logger.debug(f"template {name}@${template.version} missing vars: {missing}")

        return "".join(parts).strip() + "\n"

    def render_active(self, variables=None, tools=None) -> str:
        """渲染当前 default 模板（agent 默认调用入口）。"""
        return self.render(name="default", variables=variables, tools=tools)

    # ----------------- 查询 -----------------

    def _get_active(self, name: str) -> PromptTemplate:
        with self._lock:
            if name in self._versions and self._active.get(name) in self._versions[name]:
                return self._versions[name][self._active[name]]
            # fallback 到 default
            if "default" in self._versions:
                active = self._active.get("default", "1.0.0")
                return self._versions["default"].get(active) or next(
                    iter(self._versions["default"].values())
                )
            # 终极兜底
            return _build_default_template_v1()

    def get_active_template(self, name: str = "default") -> Optional[PromptTemplate]:
        with self._lock:
            if name not in self._versions:
                return None
            ver = self._active.get(name)
            return self._versions[name].get(ver)

    def list_templates(self) -> List[Dict]:
        """列出所有模板与它们的版本/激活状态。"""
        with self._lock:
            out: List[Dict] = []
            for name, versions in self._versions.items():
                active = self._active.get(name, "")
                out.append({
                    "name": name,
                    "active_version": active,
                    "versions": [v.to_dict() for v in versions.values()],
                })
            return out


# ============================================================
# Singleton
# ============================================================

_REGISTRY: Optional[PromptRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_prompt_registry() -> PromptRegistry:
    """获取全局单例（线程安全）。"""
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = PromptRegistry()
    return _REGISTRY


def reset_prompt_registry() -> None:
    """重置注册中心（测试用）。"""
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = None