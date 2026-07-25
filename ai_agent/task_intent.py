"""
任务意图注册表（Single Source of Truth）

集中管理：
1. 能力定义：capability name → {description, keywords, tags}
2. 任务类型：task_type → 关联能力、默认行为
3. 意图别名：将同义词、变体映射到标准意图
4. 协商/竞价关键词：让所有意图检测走同一套逻辑

之前的硬编码：
- multi_agent.py:_simple_analysis 中的 keywords 字典
- WorkerAgent.__init__ 中的 capabilities 列表
- multi_agent_integration.py 中的 negotiation_hint 识别

现在统一在此注册，调用方只通过 TaskIntentRegistry 检索。

使用流程：
    registry = get_task_intent_registry()
    # 1. 注册新能力
    registry.register_capability("translate", keywords=["翻译", "translate"], ...)
    # 2. 注册任务类型
    registry.register_task_type("analysis_report", default_capability="analysis", ...)
    # 3. 检索意图
    intent = registry.detect_intent("搜索一下最新的 AI 论文")
    # → TaskIntent(task_type="information_retrieval",
    #              capabilities=["search"], negotiation_hint=None)
"""

import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Iterable
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class Capability:
    """能力定义"""
    name: str
    description: str = ""
    # 关键词（中英文都支持）
    keywords: List[str] = field(default_factory=list)
    # 别名（指代该能力的其他表达）
    aliases: List[str] = field(default_factory=list)
    # 该能力通常关联的 task_type
    typical_task_types: List[str] = field(default_factory=list)
    # 该能力所推荐 Worker 的 tags
    preferred_worker_tags: List[str] = field(default_factory=list)
    # 元数据
    avg_latency_ms: float = 2000.0
    avg_cost: float = 10.0

    def matches(self, text: str) -> bool:
        """判定文本是否提到该能力"""
        t = text.lower()
        for kw in self.keywords + self.aliases:
            if kw.lower() in t:
                return True
        return False


@dataclass
class TaskType:
    """任务类型"""
    name: str
    description: str = ""
    default_capability: str = "general"
    keywords: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    needs_decomposition: bool = False
    typical_decomposition: List[str] = field(default_factory=list)  # 子任务 capability 列表
    priority: str = "normal"  # low / normal / high / critical

    def matches(self, text: str) -> bool:
        t = text.lower()
        for kw in self.keywords + self.aliases:
            if kw.lower() in t:
                return True
        return False


@dataclass
class TaskIntent:
    """识别出的任务意图"""
    task_type: str
    capabilities: List[str] = field(default_factory=list)
    needs_decomposition: bool = False
    decomposition: List[str] = field(default_factory=list)
    negotiation_hint: Optional[str] = None  # None / "negotiate" / "auction"
    priority: str = "normal"
    matched_keywords: Dict[str, List[str]] = field(default_factory=dict)  # capability -> matched_kws

    def to_dict(self) -> Dict:
        return {
            "task_type": self.task_type,
            "capabilities": self.capabilities,
            "needs_decomposition": self.needs_decomposition,
            "decomposition": self.decomposition,
            "negotiation_hint": self.negotiation_hint,
            "priority": self.priority,
            "matched_keywords": self.matched_keywords,
        }


# ============================================================
# 协商/竞价 提示词
# ============================================================

NEGOTIATION_KEYWORDS = ["协商", "谈判", "议价", "negotiate", "讨价还价", "达成一致", "bargain"]
AUCTION_KEYWORDS = ["竞拍", "竞价", "招标", "拍卖", "auction", "bid"]


# ============================================================
# 默认配置
# ============================================================

DEFAULT_CAPABILITIES = [
    Capability(
        name="search",
        description="信息检索 / 搜索",
        keywords=["搜索", "查找", "找一下", "搜一下", "search", "find", "query"],
        aliases=["信息检索", "lookup"],
        typical_task_types=["information_retrieval", "research"],
        preferred_worker_tags=["fast", "broad-coverage"],
        avg_latency_ms=1500.0,
        avg_cost=8.0,
    ),
    Capability(
        name="code",
        description="编程 / 写代码 / debug",
        keywords=["代码", "写代码", "编程", "code", "debug", "implement"],
        aliases=["编程", "开发"],
        typical_task_types=["code_generation", "code_review", "debugging"],
        preferred_worker_tags=["accurate", "thorough"],
        avg_latency_ms=8000.0,
        avg_cost=25.0,
    ),
    Capability(
        name="analysis",
        description="分析 / 研究",
        keywords=["研究", "分析", "调查", "research", "analyze", "analysis"],
        aliases=["调研", "research"],
        typical_task_types=["data_analysis", "research"],
        preferred_worker_tags=["accurate", "deep"],
        avg_latency_ms=5000.0,
        avg_cost=15.0,
    ),
    Capability(
        name="write",
        description="写作 / 内容创作",
        keywords=["写", "创作", "生成", "撰写", "write", "compose", "draft"],
        aliases=["写文档", "文档"],
        typical_task_types=["content_creation", "documentation"],
        preferred_worker_tags=["creative"],
        avg_latency_ms=4000.0,
        avg_cost=12.0,
    ),
    Capability(
        name="calculate",
        description="计算 / 统计",
        keywords=["计算", "统计", "算", "求和", "calculate", "compute", "sum"],
        aliases=["数学运算"],
        typical_task_types=["computation"],
        preferred_worker_tags=["fast", "accurate"],
        avg_latency_ms=500.0,
        avg_cost=2.0,
    ),
    Capability(
        name="translate",
        description="翻译",
        keywords=["翻译", "convert", "translate"],
        aliases=["转换语言"],
        typical_task_types=["translation"],
        preferred_worker_tags=["accurate"],
        avg_latency_ms=2000.0,
        avg_cost=5.0,
    ),
    Capability(
        name="general",
        description="通用能力（兜底）",
        keywords=[],
        aliases=[],
        typical_task_types=["general"],
        preferred_worker_tags=[],
        avg_latency_ms=3000.0,
        avg_cost=10.0,
    ),
]

DEFAULT_TASK_TYPES = [
    TaskType(
        name="information_retrieval",
        description="信息检索任务",
        default_capability="search",
        keywords=["搜索", "查询", "找", "search"],
        aliases=["knowledge_lookup"],
        needs_decomposition=False,
    ),
    TaskType(
        name="code_generation",
        description="代码生成",
        default_capability="code",
        keywords=["写代码", "实现", "开发", "code"],
        aliases=["generate_code", "implement"],
        needs_decomposition=False,
    ),
    TaskType(
        name="research",
        description="深入研究",
        default_capability="analysis",
        keywords=["研究", "调研", "分析", "research"],
        aliases=["deep_research"],
        needs_decomposition=True,
        typical_decomposition=["search", "analysis", "write"],
    ),
    TaskType(
        name="content_creation",
        description="内容创作",
        default_capability="write",
        keywords=["写", "创作", "起草", "write"],
        needs_decomposition=False,
    ),
    TaskType(
        name="data_analysis",
        description="数据分析",
        default_capability="analysis",
        keywords=["分析数据", "统计", "分析", "analyze"],
        needs_decomposition=True,
        typical_decomposition=["calculate", "analysis"],
    ),
    TaskType(
        name="computation",
        description="数学计算",
        default_capability="calculate",
        keywords=["计算", "求值", "算"],
        needs_decomposition=False,
    ),
    TaskType(
        name="translation",
        description="翻译",
        default_capability="translate",
        keywords=["翻译", "translate"],
        needs_decomposition=False,
    ),
    TaskType(
        name="general",
        description="通用任务",
        default_capability="general",
        keywords=[],
        needs_decomposition=False,
    ),
]


# ============================================================
# TaskIntentRegistry
# ============================================================

class TaskIntentRegistry:
    """
    任务意图注册表（单一可靠性真相源）

    集中管理：
    - Capability：能力定义 + 关键词
    - TaskType：任务类型定义 + 关联能力
    - 协商/竞价关键词

    提供 detect_intent() 把用户输入解析为 TaskIntent。
    """

    def __init__(
        self,
        capabilities: Optional[Iterable[Capability]] = None,
        task_types: Optional[Iterable[TaskType]] = None,
    ):
        self._capabilities: Dict[str, Capability] = {}
        self._task_types: Dict[str, TaskType] = {}
        self._alias_to_capability: Dict[str, str] = {}  # 别名 -> capability name
        self._alias_to_task_type: Dict[str, str] = {}  # 别名 -> task type name
        self._lock = Lock()

        for cap in capabilities or DEFAULT_CAPABILITIES:
            self.register_capability(cap)
        for tt in task_types or DEFAULT_TASK_TYPES:
            self.register_task_type(tt)

    # ----------------- 注册 -----------------

    def register_capability(self, capability: Capability) -> None:
        """注册一个能力"""
        with self._lock:
            self._capabilities[capability.name] = capability
            for alias in capability.aliases:
                self._alias_to_capability[alias.lower()] = capability.name
        logger.info(f"[IntentRegistry] Registered capability: {capability.name}")

    def register_task_type(self, task_type: TaskType) -> None:
        """注册一个任务类型"""
        with self._lock:
            self._task_types[task_type.name] = task_type
            for alias in task_type.aliases:
                self._alias_to_task_type[alias.lower()] = task_type.name
        logger.info(f"[IntentRegistry] Registered task_type: {task_type.name}")

    # ----------------- 查询 -----------------

    def get_capability(self, name: str) -> Optional[Capability]:
        # 先查 alias
        alias_match = self._alias_to_capability.get(name.lower())
        if alias_match:
            return self._capabilities.get(alias_match)
        return self._capabilities.get(name)

    def get_task_type(self, name: str) -> Optional[TaskType]:
        alias_match = self._alias_to_task_type.get(name.lower())
        if alias_match:
            return self._task_types.get(alias_match)
        return self._task_types.get(name)

    def list_capabilities(self) -> List[Capability]:
        return list(self._capabilities.values())

    def list_task_types(self) -> List[TaskType]:
        return list(self._task_types.values())

    # ----------------- 意图检测 -----------------

    def detect_capabilities(self, text: str) -> Tuple[List[str], Dict[str, List[str]]]:
        """
        从文本中检测涉及的能力

        Returns:
            (能力名列表, matched_keywords_dict)
        """
        matched = []
        keyword_hits = {}
        t = text.lower()

        for cap in self._capabilities.values():
            hit_keywords = []
            for kw in cap.keywords + cap.aliases:
                if kw.lower() in t:
                    hit_keywords.append(kw)
            if hit_keywords:
                matched.append(cap.name)
                keyword_hits[cap.name] = hit_keywords

        return matched, keyword_hits

    def detect_negotiation_hint(self, text: str) -> Optional[str]:
        """检测协商/竞价意图。返回 'negotiate', 'auction', or None"""
        t = text.lower()
        if any(kw.lower() in t for kw in NEGOTIATION_KEYWORDS):
            return "negotiate"
        if any(kw.lower() in t for kw in AUCTION_KEYWORDS):
            return "auction"
        return None

    def detect_task_type(self, text: str) -> Optional[TaskType]:
        """从文本中检测任务类型"""
        # priority: 先匹配典型 task_type 再 match capability
        t = text.lower()
        for tt in self._task_types.values():
            if tt.matches(text):
                return tt
        return None

    def detect_intent(self, text: str) -> TaskIntent:
        """
        完整意图识别：把文本解析为 TaskIntent

        流程：
        1. 尝试匹配已知 task_type
        2. 用 capability 关键词补充 capabilities
        3. 尝试检测 negotiation_hint
        4. 决定 needs_decomposition
        """
        # 1. task type
        task_type = self.detect_task_type(text)
        if task_type is None:
            task_type = self._task_types["general"]
            tt_name = "general"
        else:
            tt_name = task_type.name

        # 2. capabilities
        matched_caps, kw_hits = self.detect_capabilities(text)
        if not matched_caps:
            matched_caps = [task_type.default_capability]
        # 始终确保 default_capability 包含在内
        if task_type.default_capability not in matched_caps:
            matched_caps.append(task_type.default_capability)

        # 3. negotiation hint
        negotiation_hint = self.detect_negotiation_hint(text)
        if negotiation_hint == "negotiate" and "negotiation" not in matched_caps:
            matched_caps.append("negotiation")
        elif negotiation_hint == "auction" and "auction" not in matched_caps:
            matched_caps.append("auction")

        # 4. decomposition
        needs_decomp = task_type.needs_decomposition or len(matched_caps) > 1
        decomposition = task_type.typical_decomposition if needs_decomp else []

        return TaskIntent(
            task_type=tt_name,
            capabilities=matched_caps,
            needs_decomposition=needs_decomp,
            decomposition=decomposition,
            negotiation_hint=negotiation_hint,
            priority=task_type.priority,
            matched_keywords=kw_hits,
        )

    # ----------------- 兼容性辅助 -----------------

    @staticmethod
    def simple_analysis(
        text: str,
        registry: Optional["TaskIntentRegistry"] = None,
    ) -> Dict[str, Any]:
        """
        兼容旧 _simple_analysis 调用的 helper

        返回结构对齐 multi_agent.py:_simple_analysis 中返回的 dict：
            {
                "task_type": str,
                "required_capabilities": List[str],
                "needs_decomposition": bool,
                "negotiation_hint": Optional[str]
            }
        """
        reg = registry or get_task_intent_registry()
        intent = reg.detect_intent(text)
        return {
            "task_type": intent.task_type,
            "required_capabilities": intent.capabilities,
            "needs_decomposition": intent.needs_decomposition,
            "negotiation_hint": intent.negotiation_hint,
        }


# ============================================================
# 全局单例
# ============================================================

_task_intent_registry: Optional[TaskIntentRegistry] = None


def get_task_intent_registry() -> TaskIntentRegistry:
    """获取全局 TaskIntentRegistry 单例"""
    global _task_intent_registry
    if _task_intent_registry is None:
        _task_intent_registry = TaskIntentRegistry()
    return _task_intent_registry


def reset_task_intent_registry() -> None:
    """重置全局单例（测试用）"""
    global _task_intent_registry
    _task_intent_registry = None
