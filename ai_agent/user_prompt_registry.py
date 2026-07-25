"""User Prompt Registry — 用户侧提示词模板化与版本化管理。

对齐 system prompt 架构（见 prompt_registry.py），但承担不同的职责：
- System Prompt 告诉模型"你是什么身份"；
- User Prompt 承担三件事：
    1) **few-shot 示例注入**     — 在用户问句前/后拼装 ICL 演示对，引导输出风格；
    2) **历史上下文注入位**       — 决定"记忆 / 会话上下文 / RAG 片段"插在模板的哪个位置；
    3) **安全重写（脱敏/规范化）** — 在送进 LLM 之前把可能的注入/PII 风险数据擦掉。

设计目标：
- 与 prompt_registry 对称的"模板 + 注册中心 + 单例"形态；
- 模板多版本 + active_version + rollback；
- 持久化到 JSON 文件 (默认 `./prompts/user_prompts.json`)，重启可恢复；
- 暴露 `render(name, user_input, context, **kwargs)` —— 业务侧一行调用即可拿到最终拼装好的字符串；
- 安全重写策略采用**白名单** (禁词 + 模式替换)，失败降级不抛异常；
- 全部线程安全。

模板数据结构：

    UserPromptTemplate(
        name="default",
        version="2.0.0",
        structure="system_first" | "user_first" | "user_only",
        intro_template="",         # （可选）在 user input 之前插入的引导语
        few_shots=[                # Few-shot 示例列表
            {"role": "user",      "content": "...示例问题..."},
            {"role": "assistant", "content": "...示例回答..."},
        ],
        context_injection="before_user",   # 上下文注入位：
                                          # - "before_user"：在 few-shot 与 user 之间
                                          # - "after_user"  ：在 user 之后
                                          # - "before_few_shots"：在所有 few-shot 之前
                                          # - "off"          ：不注入
        security_rewrite={                 # 安全重写策略
            "enabled": True,
            "redact_patterns": ["***SSN***", r"\\d{4}\\s?\\d{4}\\s?\\d{4}\\s?\\d{4}"],
            "strip_injection_markers": True,   # 去掉 "忽略上文/忽略之前提示" 这类越狱触发语
            "max_length": 4000,
        },
        variables=[],                       # 期望变量（仅校验）
    )

使用：

    from user_prompt_registry import get_user_prompt_registry

    reg = get_user_prompt_registry()
    final = reg.render(
        name="default",
        user_input="帮我把 csv 转成 parquet",
        context="[会话上下文] 之前讨论的是销售数据",
    )
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 模板数据模型
# ============================================================


@dataclass
class FewShotExample:
    """一对 ICL 示例。"""

    role: str  # "user" | "assistant" | "system"
    content: str

    def to_dict(self) -> Dict:
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, d: Dict) -> "FewShotExample":
        return cls(role=str(d.get("role", "user")), content=str(d.get("content", "")))


@dataclass
class SecurityRewritePolicy:
    """安全重写策略。

    - enabled: 是否启用；关闭后所有字段被忽略；
    - redact_patterns: 形如 ["<label>", "<regex>", ...] 的列表；
      写"<label>"时按字面替换；写"<regex>"时按正则替换为 "[REDACTED]"；
    - strip_injection_markers: 是否去掉常见的提示词越狱触发语；
    - max_length: 整段 user input 的最大长度（截断而非报错）。
    """

    enabled: bool = True
    redact_patterns: List[str] = field(default_factory=list)
    strip_injection_markers: bool = True
    max_length: int = 4000

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "redact_patterns": list(self.redact_patterns),
            "strip_injection_markers": self.strip_injection_markers,
            "max_length": self.max_length,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "SecurityRewritePolicy":
        return cls(
            enabled=bool(d.get("enabled", True)),
            redact_patterns=[str(x) for x in d.get("redact_patterns", [])],
            strip_injection_markers=bool(d.get("strip_injection_markers", True)),
            max_length=int(d.get("max_length", 4000)),
        )


@dataclass
class UserPromptTemplate:
    """一个版本的 User Prompt 模板。

    Attributes:
        name: 模板名（如 "default" / "code_helper_v1"）
        version: 版本号字符串
        author: 作者/团队
        changelog: 变更说明
        structure: 拼装顺序；可选 "system_first" | "user_first" | "user_only"
                  - system_first: [intro] + [few_shots] + [context] + [user]
                  - user_first  : [intro] + [user] + [context] + [few_shots]（少见，多用于续写/补全）
                  - user_only   : 只拼装 user input，配合外部 system 提示
        intro_template: 模板化引导语，format(**variables)；可空
        few_shots: Few-shot 示例
        context_injection: 上下文注入位
        security_rewrite: 安全策略
        variables: 该模板支持的变量名
    """

    name: str
    version: str = "1.0.0"
    author: str = "system"
    changelog: str = ""
    structure: str = "system_first"

    intro_template: str = ""

    few_shots: List[FewShotExample] = field(default_factory=list)

    context_injection: str = "before_user"  # before_user | after_user | before_few_shots | off

    security_rewrite: SecurityRewritePolicy = field(default_factory=SecurityRewritePolicy)

    variables: List[str] = field(default_factory=list)

    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "changelog": self.changelog,
            "structure": self.structure,
            "intro_template": self.intro_template,
            "few_shots": [s.to_dict() for s in self.few_shots],
            "context_injection": self.context_injection,
            "security_rewrite": self.security_rewrite.to_dict(),
            "variables": list(self.variables),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "UserPromptTemplate":
        return cls(
            name=str(d.get("name", "default")),
            version=str(d.get("version", "1.0.0")),
            author=str(d.get("author", "system")),
            changelog=str(d.get("changelog", "")),
            structure=str(d.get("structure", "system_first")),
            intro_template=str(d.get("intro_template", "")),
            few_shots=[FewShotExample.from_dict(s) for s in d.get("few_shots", [])],
            context_injection=str(d.get("context_injection", "before_user")),
            security_rewrite=SecurityRewritePolicy.from_dict(d.get("security_rewrite", {})),
            variables=[str(v) for v in d.get("variables", [])],
            created_at=float(d.get("created_at", time.time())),
        )


# ============================================================
# 默认模板
# ============================================================


# 一些高频的越狱触发语（做"脱敏"用，不是真正的安全替代品）。
_INJECTION_PATTERNS = [
    r"(?i)ignore (all )?(previous|above|prior) (instructions|prompts?)",
    r"(?i)disregard (the )?(system|previous) (prompt|message)",
    r"(?i)forget (everything|all) (above|before)",
    r"(?i)\bDAN\b.*mode",
    r"(?i)jailbreak",
    r"(?i)忽略(以上|之前|上文)的(提示|指令|内容)",
    r"(?i)无视(以上|之前|上文)",
]


def _build_default_user_template_v1() -> UserPromptTemplate:
    """v1.0.0：纯透传 user input；不引入 few-shot / 不做安全重写。

    行为契约：与旧 _build_enhanced_input 的"无模板"路径一致；作为兜底版本。
    """
    return UserPromptTemplate(
        name="default",
        version="1.0.0",
        author="system",
        changelog="基础透传模板，与旧 _build_enhanced_input 的行为一致。",
        structure="user_only",
        intro_template="",
        few_shots=[],
        context_injection="off",
        security_rewrite=SecurityRewritePolicy(enabled=False),
        variables=[],
    )


def _build_default_user_template_v2() -> UserPromptTemplate:
    """v2.0.0：few-shot + 上下文注入 + 安全重写。

    - 默认开 CoT 风格的 2 个示例（闲聊/数据处理），引导模型先理解意图再回答；
    - 上下文注入到 few_shots 与 user input 之间（保持示例"独立"的位置关系）；
    - 安全重写：去除提示词越狱触发语 + 截断 4000 字。
    """
    return UserPromptTemplate(
        name="default",
        version="2.0.0",
        author="system",
        changelog="阶段 B：引入 few-shot + context 注入位 + 安全重写。",
        structure="system_first",
        intro_template="",
        few_shots=[
            FewShotExample(
                role="user",
                content="你好",
            ),
            FewShotExample(
                role="assistant",
                content="你好！我是 AI 助手，可以帮你查资料、写代码、做数据分析。请告诉我你需要什么。",
            ),
            FewShotExample(
                role="user",
                content="帮我把 sales.csv 转成 parquet",
            ),
            FewShotExample(
                role="assistant",
                content="好的，我先看一下文件结构，然后用工具完成转换。",
            ),
        ],
        context_injection="before_user",
        security_rewrite=SecurityRewritePolicy(
            enabled=True,
            redact_patterns=[],
            strip_injection_markers=True,
            max_length=4000,
        ),
        variables=["context", "user_input"],
    )


# ============================================================
# 安全重写器
# ============================================================


class UserPromptSanitizer:
    """对单段 user input 做安全重写（线程安全、无副作用、可重入）。"""

    def __init__(self, policy: SecurityRewritePolicy):
        self.policy = policy
        self._inject_re = [re.compile(p) for p in _INJECTION_PATTERNS]
        # 预编译 redact 正则（以"\\"开头视作正则）
        self._label_subs: List[tuple] = []  # (literal, None) 直接替换
        self._regex_subs: List[tuple] = []  # (compiled regex, replacement)
        for pat in policy.redact_patterns:
            if not pat:
                continue
            if pat.startswith("\\") or pat.startswith("^") or pat.startswith("["):
                try:
                    self._regex_subs.append((re.compile(pat), "[REDACTED]"))
                except re.error as e:
                    logger.warning(f"bad redact regex {pat!r}: {e}")
            else:
                self._label_subs.append((pat, ""))

    def rewrite(self, text: str) -> str:
        if not self.policy.enabled or not text:
            return text
        out = text
        # 1) 触发语剥离
        if self.policy.strip_injection_markers:
            for rgx in self._inject_re:
                out = rgx.sub("", out)
        # 2) 字面替换
        for literal, repl in self._label_subs:
            out = out.replace(literal, repl)
        # 3) 正则替换
        for rgx, repl in self._regex_subs:
            out = rgx.sub(repl, out)
        # 4) 长度截断
        if self.policy.max_length and len(out) > self.policy.max_length:
            out = out[: self.policy.max_length] + "…[truncated]"
        # 合并多余空行
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        return out


# ============================================================
# 注册中心
# ============================================================


class UserPromptRegistry:
    """User Prompt 模板注册中心（线程安全 + JSON 持久化）。"""

    def __init__(self, persist_path: Optional[str] = None):
        self._lock = threading.RLock()
        # name -> version -> UserPromptTemplate
        self._versions: Dict[str, Dict[str, UserPromptTemplate]] = {}
        self._active: Dict[str, str] = {}
        self._persist_path = persist_path or os.environ.get(
            "USER_PROMPT_REGISTRY_PATH",
            os.path.join(os.getcwd(), "prompts", "user_prompts.json"),
        )

        # 初始化默认
        v1 = _build_default_user_template_v1()
        v2 = _build_default_user_template_v2()
        self.register(v1)
        self.register(v2)
        self._active["default"] = v2.version

        # 从文件恢复（若有）
        self._load_from_disk()
        logger.info(
            f"UserPromptRegistry initialized: default active={self._active.get('default')}, "
            f"persist_path={self._persist_path}"
        )

    # ----------------- 注册 / 版本管理 -----------------

    def register(self, template: UserPromptTemplate) -> None:
        with self._lock:
            bucket = self._versions.setdefault(template.name, {})
            existed = template.version in bucket
            bucket[template.version] = template
            if template.name not in self._active:
                self._active[template.name] = template.version
            logger.info(
                f"User prompt registered: name={template.name} version={template.version} "
                f"overwrite={existed}"
            )

    def rollback(self, name: str, version: str) -> bool:
        with self._lock:
            if name not in self._versions or version not in self._versions[name]:
                return False
            self._active[name] = version
            self._persist()
            return True

    def set_active(self, name: str, version: str) -> bool:
        return self.rollback(name, version)

    # ----------------- 渲染 -----------------

    def render(
        self,
        name: str = "default",
        user_input: str = "",
        context: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> str:
        """渲染最终 user-side 字符串（送进 LLM 之前的 message content）。

        Args:
            name: 模板名；未注册时回退到 "default"
            user_input: 原始用户输入
            context: 上下文片段（记忆/RAG 等）；允许为空或 None
            variables: 注入到 intro_template 的额外变量

        Returns:
            拼装好的字符串（已应用安全重写）
        """
        variables = variables or {}
        tpl = self._get_active(name)

        # 安全重写（仅作用于 user_input；context 与 few_shots 视为受控内容，不动）
        sanitizer = UserPromptSanitizer(tpl.security_rewrite)
        safe_input = sanitizer.rewrite(user_input or "")
        ctx = (context or "").strip()

        parts: List[str] = []

        # intro（变量注入）
        if tpl.intro_template:
            try:
                parts.append(tpl.intro_template.format(**variables, user_input=safe_input))
            except KeyError as e:
                logger.warning(f"intro_template missing variable: {e}")
                parts.append(tpl.intro_template)

        # few_shots（仅 system_first 与 user_first 走示例；user_only 不放示例）
        if tpl.structure in ("system_first", "user_first"):
            for s in tpl.few_shots:
                parts.append(f"[{s.role}] {s.content}")

        # context 注入位
        if ctx:
            if tpl.context_injection == "before_few_shots":
                # 插到 few_shots 之前（即在 parts 头部插入）
                parts.insert(0 if not parts else 0, f"[上下文] {ctx}")
            elif tpl.context_injection == "after_user":
                parts.append(f"[上下文] {ctx}")
            elif tpl.context_injection == "before_user":
                parts.append(f"[上下文] {ctx}")
            # "off"：不插入

        # user_input 尾部
        parts.append(f"[user] {safe_input}")

        return "\n\n".join(p for p in parts if p).strip() + "\n"

    def render_active(
        self,
        user_input: str = "",
        context: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
    ) -> str:
        """渲染当前 default 模板（agent 默认调用入口）。"""
        return self.render(
            name="default", user_input=user_input, context=context, variables=variables
        )

    # ----------------- 查询 -----------------

    def _get_active(self, name: str) -> UserPromptTemplate:
        with self._lock:
            if name in self._versions and self._active.get(name) in self._versions[name]:
                return self._versions[name][self._active[name]]
            if "default" in self._versions:
                active = self._active.get("default", "2.0.0")
                return self._versions["default"].get(active) or next(
                    iter(self._versions["default"].values())
                )
            return _build_default_user_template_v1()

    def get_active_template(self, name: str = "default") -> Optional[UserPromptTemplate]:
        with self._lock:
            if name not in self._versions:
                return None
            ver = self._active.get(name)
            return self._versions[name].get(ver)

    def list_templates(self) -> List[Dict]:
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

    # ----------------- 持久化 -----------------

    def _persist(self) -> bool:
        """把当前注册表写到 JSON 文件。"""
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            payload = {
                "active_versions": dict(self._active),
                "templates": {
                    name: {ver: t.to_dict() for ver, t in versions.items()}
                    for name, versions in self._versions.items()
                },
            }
            tmp = self._persist_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._persist_path)
            return True
        except Exception as e:
            logger.warning(f"user_prompt_registry persist failed: {e}")
            return False

    def _load_from_disk(self) -> None:
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            logger.warning(f"failed to load user_prompt_registry from {self._persist_path}: {e}")
            return

        with self._lock:
            templates = payload.get("templates", {}) or {}
            for name, versions in templates.items():
                if not isinstance(versions, dict):
                    continue
                self._versions.setdefault(name, {})
                for ver, d in versions.items():
                    try:
                        tpl = UserPromptTemplate.from_dict(d)
                        self._versions[name][ver] = tpl
                    except Exception as e:
                        logger.warning(f"skip bad template {name}@{ver}: {e}")
            for name, ver in (payload.get("active_versions") or {}).items():
                if name in self._versions and ver in self._versions[name]:
                    self._active[name] = ver

    def export_json(self) -> Dict:
        """导出当前所有模板 + 激活版本（纯字典，便于备份/上传）。"""
        with self._lock:
            return {
                "active_versions": dict(self._active),
                "templates": {
                    name: {ver: t.to_dict() for ver, t in versions.items()}
                    for name, versions in self._versions.items()
                },
            }

    def import_json(self, payload: Dict) -> int:
        """从 export_json 形状的字典导入；返回成功导入的模板数。"""
        if not isinstance(payload, dict):
            return 0
        count = 0
        with self._lock:
            templates = payload.get("templates", {}) or {}
            for name, versions in templates.items():
                if not isinstance(versions, dict):
                    continue
                self._versions.setdefault(name, {})
                for ver, d in versions.items():
                    try:
                        tpl = UserPromptTemplate.from_dict(d)
                        self._versions[name][ver] = tpl
                        count += 1
                    except Exception as e:
                        logger.warning(f"import: skip bad template {name}@{ver}: {e}")
            for name, ver in (payload.get("active_versions") or {}).items():
                if name in self._versions and ver in self._versions[name]:
                    self._active[name] = ver
            self._persist()
        return count


# ============================================================
# Singleton
# ============================================================

_REGISTRY: Optional[UserPromptRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_user_prompt_registry() -> UserPromptRegistry:
    """获取全局单例（线程安全）。"""
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = UserPromptRegistry()
    return _REGISTRY


def reset_user_prompt_registry() -> None:
    """重置注册中心（测试用）。"""
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = None
