"""
AIAgent - 基于 LangChain 1.x + LangGraph 的多功能 AI Agent。

设计原则（固化）：
1. 防御性降级：依赖项缺失时走兜底分支，不抛未捕获异常。
2. 单一真相源：系统提示中的工具描述从 self.tools 动态生成，添加工具零成本。
3. 职责分离：意图识别交由 SecurityModule.check_input 完成；上层仅消费结果。
4. DRY：run 与 run_stream 共享前置/后置管线。
5. 不可变快照：流式输出基于"已 yield 字节数"做差分，避免 sanitize 改长度导致错乱。
6. 方法语义匹配：set_api_key 真实支持 provider 参数，向后兼容旧调用。
7. LangChain 1.x API：直接使用 create_agent 返回的 CompiledStateGraph，
   无 AgentExecutor；输入为 {"messages": [...]}，checkpointer 由 create_agent 接收。
8. LangChain 1.x hooks/middleware：默认注入 LoggingMiddleware / ToolCallCounterMiddleware /
   ContextTrimMiddleware，详见 agent_middleware.py；通过 create_agent(..., middleware=...) 接入。
"""

import os
import sqlite3
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from config import (
    OPENAI_API_KEY, DEEPSEEK_API_KEY, QWEN_API_KEY, MINIMAX_API_KEY,
    ZHIPU_API_KEY, MOONSHOT_API_KEY, BAIDU_API_KEY, BAIDU_SECRET_KEY,
    SPARK_API_KEY, SPARK_SECRET_KEY, SPARK_APP_ID,
    DOUBAO_API_KEY, HUNYUAN_API_KEY, SILICONFLOW_API_KEY, GLM_API_KEY,
    MODEL_NAME, MODEL_PROVIDER, TEMPERATURE, LOG_LEVEL, MODEL_VERSIONS,
    PROVIDER_META,
)
from tools import get_all_tools, set_rag_instance
from rag import RAGModule
from security import SecurityModule, set_security_instance, get_security_instance
from streaming import StreamDeltaTracker
from llm_reliability import (
    ResilientLLMInvoker, ModelFallbackChain, FallbackCandidate,
    RetryConfig, FailLogRepository, GracefulDegradation,
    PrimaryStandbyConfig, StandbyWarmupService,
    get_invoker, reset_invoker, InvokeResult,
)
from context_manager import get_context_manager
from memory_store import get_memory_store, MemoryImportance
from prompt_registry import get_prompt_registry, PromptTemplate
from user_prompt_registry import get_user_prompt_registry


logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("agent.log"),
            logging.StreamHandler(),
        ],
    )


# 意图到记忆重要性的映射（替代 agent.py 中散落的字符串匹配）
_INTENT_TO_IMPORTANCE: Dict[str, int] = {
    "query": MemoryImportance.HIGH.value,
    "analysis": MemoryImportance.HIGH.value,
    "compare": MemoryImportance.HIGH.value,
    "calculate": MemoryImportance.MEDIUM.value,
    "command": MemoryImportance.MEDIUM.value,
    "greeting": MemoryImportance.LOW.value,
    "general": MemoryImportance.MEDIUM.value,
}


def _build_provider_base_url(provider: str) -> Optional[str]:
    """根据 provider 返回对应的 base_url；OpenAI 返回 None 使用官方端点。

    已支持的 OpenAI 兼容协议 provider：
    - openai        官方 OpenAI（base_url 留空走默认）
    - deepseek      https://api.deepseek.com/v1
    - qwen          https://dashscope.aliyuncs.com/compatible-mode/v1
    - zhipu         https://open.bigmodel.cn/api/paas/v4
    - moonshot      https://api.moonshot.cn/v1
    - minimax       https://api.minimax.chat/v1
    - doubao        https://ark.cn-beijing.volces.com/api/v3（火山方舟 ARK）
    - hunyuan       https://hunyuan.tencent.com/v3（OpenAI 兼容入口）
    - siliconflow   https://api.siliconflow.cn/v1
    """
    mapping = {
        "deepseek": "https://api.deepseek.com/v1",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4",
        "moonshot": "https://api.moonshot.cn/v1",
        "minimax": "https://api.minimax.chat/v1",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3",
        "hunyuan": "https://api.hunyuan.tencent.com/v1",
        "siliconflow": "https://api.siliconflow.cn/v1",
    }
    return mapping.get(provider)


def _strip_cot_wrapper(text: str) -> str:
    """剥掉思考段开头包装"## 思考"和结尾"## 回答"分隔符。

    ``StreamDeltaTracker.feed`` 拿到的是 split 后的 cot 段，原始结构里包着
    "## 思考\n...\n## 回答" 样式分隔符；前端只关心新增文字。
    """
    if not text:
        return text
    s = text
    # 把前缀 "## 思考"（可能带换行）替换掉
    for marker in ("## 思考\n", "## 思考"):
        if s.startswith(marker):
            s = s[len(marker):]
            break
    # 把后缀 "## 回答" 之前的部分保留
    if "## 回答" in s:
        s = s.split("## 回答", 1)[0]
    return s


# ============================================================
# Day 6-7：Turn 公共管线数据结构
# ============================================================

@dataclass
class PreparedTurn:
    """``_prepare_turn()`` 产物：把对话前/后置管线合并到一处。

    字段：
    - ``intent`` / ``importance``：意图与重要性（一致性指标，所有路径共享）
    - ``final_input``：已经走完 *记忆 / 上下文 / user prompt 模板* 的最终 user
      文本，可直接包成 ``HumanMessage`` 喂给 agent
    - ``payload``：已构造好的 LangChain 1.x 格式 ``{"messages": [...]}``
    """
    intent: str = "general"
    importance: int = 3
    final_input: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)


def _api_key_for_provider(provider: str) -> str:
    """根据 provider 取出对应的 API Key。

    注意：智谱 provider 既可使用 `ZHIPU_API_KEY`，也可使用别名 `GLM_API_KEY`。
    """
    mapping = {
        "openai": OPENAI_API_KEY,
        "deepseek": DEEPSEEK_API_KEY,
        "qwen": QWEN_API_KEY,
        "zhipu": ZHIPU_API_KEY or GLM_API_KEY,
        "moonshot": MOONSHOT_API_KEY,
        "minimax": MINIMAX_API_KEY,
        "baidu": BAIDU_API_KEY,
        "spark": SPARK_API_KEY,
        "doubao": DOUBAO_API_KEY,
        "hunyuan": HUNYUAN_API_KEY,
        "siliconflow": SILICONFLOW_API_KEY,
    }
    return mapping.get(provider, OPENAI_API_KEY)


class AIAgent:
    """多功能 AI Agent 主类（LangChain 1.x 适配版）。

    设计要点：
    - security 在 __init__ 即被初始化（防御性降级），不依赖 init_agent。
    - tools 在 __init__ 即被加载（轻量），但内部依赖（如 rag）延迟到 init_agent。
    - checkpointer 在 init_checkpointer 中创建，create_agent 直接接收。
    - 系统提示在 init_agent 中基于 self.tools 动态生成。
    - run / run_stream 使用 1.x 的 {"messages": [...]} 输入格式。
    """

    def __init__(self):
        self.model_provider = MODEL_PROVIDER
        self.model_name = MODEL_NAME
        self.model: Optional[Any] = None
        self.rag: Optional[RAGModule] = None
        self.security: SecurityModule = get_security_instance()
        self.tools = get_all_tools()
        self.checkpointer: Optional[SqliteSaver] = None
        # LangChain 1.x：create_agent 直接返回可执行对象
        self.agent: Optional[Any] = None
        self._checkpointer_conn: Optional[sqlite3.Connection] = None
        self._system_prompt: Optional[str] = None

        # 结构化上下文管理器
        self.context_manager = get_context_manager()
        self.current_session_id = str(uuid.uuid4())

        # 短期/长期记忆
        self.memory_store = get_memory_store()

        # 主备（Primary/Standby）配置
        # 默认：当前 provider 为主；其余 fallback 链的第一个作为 standby
        self._standby_configs: List[FallbackCandidate] = []
        self._switching_strategy: str = "automatic"
        self._standby_warmup: Optional[StandbyWarmupService] = None

        # 五层容错栈（多级智能体容错机制）
        self._fallback_chain = self._build_fallback_chain(
            primary_provider=self.model_provider,
            primary_model=self.model_name,
        )
        self.invoker: ResilientLLMInvoker = get_invoker(
            fallback_chain=self._fallback_chain
        )
        self.fail_log: FailLogRepository = self.invoker.fail_log

        # sub-agent 注册表（capability -> WorkerAgent）
        self._sub_agents: Dict[str, "WorkerAgent"] = {}

        self._ensure_session()
        self._init_checkpointer()

    # ==========================================
    # 兼容性：保留旧字段名 agent_executor
    # ==========================================

    @property
    def agent_executor(self) -> Optional[Any]:
        """向后兼容旧 API（api.py / test_*.py 中可能引用）。"""
        return self.agent

    # ==========================================
    # 初始化与配置
    # ==========================================

    def _init_checkpointer(self) -> None:
        """初始化 LangGraph 持久化检查点。"""
        try:
            conn = sqlite3.connect("memory.db", check_same_thread=False)
            self._checkpointer_conn = conn
            self.checkpointer = SqliteSaver(conn)
        except Exception as e:
            logger.warning(f"Failed to init checkpointer: {e}")
            self.checkpointer = None

    def _get_model(self, provider: Optional[str] = None, model_name: Optional[str] = None):
        """根据 provider 获取对应的模型实例。

        优先走 OpenAI 兼容协议（langchain_openai.ChatOpenAI）。
        Baidu/Spark 暂用 langchain_community 的客户端（保留旧逻辑）。
        """
        provider = provider or self.model_provider
        model_name = model_name or self.model_name

        base_url = _build_provider_base_url(provider)

        # OpenAI 兼容 provider：openai + 全部国产模型（除 baidu/spark 外）
        if provider in {
            "openai", "deepseek", "qwen", "zhipu", "moonshot", "minimax",
            "doubao", "hunyuan", "siliconflow",
        }:
            api_key = _api_key_for_provider(provider)
            kwargs = {"model": model_name, "temperature": TEMPERATURE, "api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            return ChatOpenAI(**kwargs)

        if provider == "baidu":
            from langchain_community.chat_models import ErnieBotChat
            return ErnieBotChat(
                model_name=model_name,
                api_key=BAIDU_API_KEY,
                secret_key=BAIDU_SECRET_KEY,
            )

        if provider == "spark":
            from langchain_community.chat_models import SparkLLM
            return SparkLLM(
                model=model_name,
                app_id=SPARK_APP_ID,
                api_key=SPARK_API_KEY,
                api_secret=SPARK_SECRET_KEY,
            )

        # 兜底：使用 OpenAI
        return ChatOpenAI(model=model_name, temperature=TEMPERATURE, api_key=OPENAI_API_KEY)

    def _build_system_prompt(self) -> str:
        """基于 self.tools 动态生成系统提示（避免硬编码工具列表导致脱节）。

        阶段 A1 改造：
        - 走 `prompt_registry.render_active`，把硬编码的 system prompt
          替换为"system + role + tool + (可选)cot"三段模板拼接；
        - 行为兼容：默认 v1.0.0 等价于旧字符串；v2.0.0 引入 CoT。
        """
        tool_lines: List[str] = []
        for t in self.tools or []:
            desc = (t.description or "").strip().replace("\n", " ")
            if len(desc) > 200:
                desc = desc[:200] + "..."
            tool_lines.append(f"- {t.name}: {desc}")

        registry = get_prompt_registry()
        return registry.render_active(variables={}, tools=tool_lines)

    def init_agent(self, provider: Optional[str] = None, model_name: Optional[str] = None) -> bool:
        """初始化 Agent（LangChain 1.x）。"""
        if provider:
            self.model_provider = provider
        if model_name:
            self.model_name = model_name

        api_key = _api_key_for_provider(self.model_provider)
        if not api_key:
            logger.warning(f"API key not configured for provider: {self.model_provider}")
            return False

        try:
            self.model = self._get_model(self.model_provider, self.model_name)

            self.rag = RAGModule(self.model, api_key=api_key)
            set_rag_instance(self.rag)
            set_security_instance(self.security)

            # 重新加载 tools（确保包含 rag 等可能新增的工具）
            self.tools = get_all_tools()
            self._system_prompt = self._build_system_prompt()

            # LangChain 1.x: create_agent 直接接收 checkpointer / middleware，
            # 返回 CompiledStateGraph（不再需要 AgentExecutor 包装）
            from agent_middleware import build_default_middleware
            middleware = build_default_middleware()
            self.agent = create_agent(
                model=self.model,
                tools=self.tools,
                system_prompt=self._system_prompt,
                checkpointer=self.checkpointer,
                middleware=middleware or None,
            )

            logger.info(f"Agent initialized with {self.model_provider}/{self.model_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            return False

    def set_model(self, provider: str, model_name: Optional[str] = None) -> bool:
        """切换模型提供商和模型。"""
        self.model_provider = provider
        if model_name:
            self.model_name = model_name
        elif provider in MODEL_VERSIONS and MODEL_VERSIONS[provider]:
            self.model_name = MODEL_VERSIONS[provider][0]

        self.model = None
        self.agent = None
        return self.init_agent(provider, self.model_name)

    def set_api_key(self, api_key: str, provider: Optional[str] = None) -> bool:
        """设置 API Key（用于临时切换）。

        Args:
            api_key: 新的 API Key。
            provider: 目标 provider；为空时回退到 openai。

        Returns:
            是否成功初始化 agent。
        """
        provider = provider or "openai"
        env_key = f"{provider.upper()}_API_KEY"
        os.environ[env_key] = api_key
        self.model_provider = provider
        if provider in MODEL_VERSIONS and MODEL_VERSIONS[provider]:
            self.model_name = MODEL_VERSIONS[provider][0]
        return self.init_agent(provider, self.model_name)

    def get_api_key_status(self) -> Dict[str, Any]:
        api_key_map = {
            "openai": bool(OPENAI_API_KEY),
            "deepseek": bool(DEEPSEEK_API_KEY),
            "qwen": bool(QWEN_API_KEY),
            "zhipu": bool(ZHIPU_API_KEY or GLM_API_KEY),
            "moonshot": bool(MOONSHOT_API_KEY),
            "minimax": bool(MINIMAX_API_KEY),
            "baidu": bool(BAIDU_API_KEY),
            "spark": bool(SPARK_API_KEY),
            "doubao": bool(DOUBAO_API_KEY),
            "hunyuan": bool(HUNYUAN_API_KEY),
            "siliconflow": bool(SILICONFLOW_API_KEY),
        }
        return {
            "configured": api_key_map.get(self.model_provider, False),
            "has_agent": self.agent is not None,
            "provider": self.model_provider,
            "model": self.model_name,
            "available_providers": list(api_key_map.keys()),
            "provider_keys": api_key_map,
        }

    def get_available_models(self) -> Dict[str, Any]:
        """返回模型清单 + 各 provider 的展示元信息。

        结构：
            {
                "providers": [
                    {"id": "openai", "label": "OpenAI", "group": "global",
                     "desc": "...", "configured": True,
                     "models": ["gpt-4o-mini", ...]},
                    ...
                ],
                "models_by_provider": {...},  # 兼容旧字段
                "current_provider": "openai",
                "current_model": "gpt-4o-mini",
                "provider_meta": {...},
            }
        """
        key_status = self.get_api_key_status().get("provider_keys", {})
        providers_list = []
        models_by_provider: Dict[str, List[str]] = {}
        # 排序：global 在前，china 在后；同组按 label 字典序
        _GROUP_ORDER = {"global": 0, "china": 1, "other": 2}
        ordered = sorted(
            MODEL_VERSIONS.keys(),
            key=lambda k: (
                _GROUP_ORDER.get(PROVIDER_META.get(k, {}).get("group", "other"), 9),
                PROVIDER_META.get(k, {}).get("label", k),
            ),
        )
        for prov_id in ordered:
            meta = PROVIDER_META.get(prov_id, {})
            configured = bool(key_status.get(prov_id, False))
            models = list(MODEL_VERSIONS.get(prov_id, []))
            models_by_provider[prov_id] = models
            providers_list.append({
                "id": prov_id,
                "label": meta.get("label", prov_id),
                "group": meta.get("group", "other"),
                "desc": meta.get("desc", ""),
                "configured": configured,
                "models": models,
            })
        return {
            "providers": providers_list,
            "models_by_provider": models_by_provider,
            "current_provider": self.model_provider,
            "current_model": self.model_name,
            "provider_meta": PROVIDER_META,
        }

    # ==========================================
    # 容错机制（Fallback Chain + Agent 工厂）
    # ==========================================

    def _build_fallback_chain(
        self,
        primary_provider: str,
        primary_model: str,
    ) -> ModelFallbackChain:
        """构造 fallback 链：当前 provider 优先，其余按固定兜底顺序。

        兜底顺序：openai → deepseek → qwen → moonshot → zhipu → minimax
        （覆盖国内/国外主流 provider，单一故障不会全栈瘫痪）
        """
        ordered_providers = [
            "openai", "deepseek", "qwen", "moonshot", "zhipu", "minimax",
            "doubao", "hunyuan", "siliconflow",
        ]
        # 主 provider 放第一位
        if primary_provider in ordered_providers:
            ordered_providers.remove(primary_provider)
        ordered_providers.insert(0, primary_provider)

        candidates: List[FallbackCandidate] = []
        for prov in ordered_providers:
            if prov not in MODEL_VERSIONS or not MODEL_VERSIONS[prov]:
                continue
            # 主 provider 用 primary_model；其余取该系列第一个可用版本
            model = primary_model if prov == primary_provider else MODEL_VERSIONS[prov][0]
            candidates.append(FallbackCandidate(provider=prov, model=model))

        if not candidates:
            # 兜底：只有 openai
            candidates = [FallbackCandidate("openai", primary_model)]

        logger.info(
            f"Fallback chain built: {' -> '.join(c.provider + '/' + c.model for c in candidates)}"
        )
        return ModelFallbackChain(candidates)

    def _build_agent_for_provider(self, provider: str, model: str) -> Any:
        """根据 provider/model 构建（或重建）agent 实例。

        设计要点：
        - 主 provider 命中：复用 self.agent（已 init），避免重复构建
        - 其它 provider：动态构建临时 agent（不修改 self.agent）
        - 系统提示沿用 self._system_prompt（已基于 tools 生成）
        """
        if (
            provider == self.model_provider
            and model == self.model_name
            and self.agent is not None
        ):
            return self.agent

        # 临时 fallback agent：用对应 provider/model
        logger.info(f"Building fallback agent for {provider}/{model}")
        try:
            tmp_model = self._get_model(provider, model)
            from agent_middleware import build_default_middleware
            return create_agent(
                model=tmp_model,
                tools=self.tools or [],
                system_prompt=self._system_prompt or "You are a helpful assistant.",
                checkpointer=self.checkpointer,
                middleware=build_default_middleware() or None,
            )
        except Exception as e:
            # 把建图失败包装成 LLMError，让 invoker 走 fallback
            from llm_reliability import LLMError, LLMErrorKind
            raise LLMError(
                LLMErrorKind.UNAVAILABLE,
                f"Failed to build agent for {provider}/{model}: {e}",
                provider=provider,
                model=model,
            )

    def get_fail_log_summary(self) -> Dict[str, Any]:
        """获取失败日志聚合摘要（用于调试面板/健康检查）。"""
        recent = self.fail_log.recent(limit=20)
        stats = self.fail_log.fingerprint_stats()
        breakers = {p: b.status() for p, b in self.invoker.breakers.items()}
        return {
            "recent_failures": recent,
            "fingerprint_stats": stats,
            "breaker_states": breakers,
        }

    def reset_breakers(self):
        """手动重置所有熔断器（运维 / 测试用）。"""
        for b in self.invoker.breakers.values():
            b.state = "closed"
            b.consecutive_failures = 0
            b.open_until = 0.0
            b.last_error = None

    # ==========================================
    # 主备（Primary/Standby）模型切换
    # ==========================================

    def set_primary_standby(
        self,
        primary: Optional[Dict[str, str]] = None,
        standbys: Optional[List[Dict[str, str]]] = None,
        switching_strategy: str = "automatic",
        enable_warmup: bool = False,
        warmup_interval: float = 300.0,
    ) -> Dict[str, Any]:
        """声明式配置主备模型。

        Args:
            primary: {"provider": "openai", "model": "gpt-4o-mini"}；
                     为空时保持当前主。
            standbys: 备选列表，按顺序 fallback；
                     为空时使用当前 fallback 链的其余项。
            switching_strategy:
                - "automatic"（默认）：故障时自动切换
                - "manual"：仅手动切换（运维场景）
            enable_warmup: 是否启动 standby 后台预热（建议仅生产环境开启）
            warmup_interval: 预热间隔（秒）

        Returns:
            配置后的状态（含 primary/standbys/active_model）

        Example:
            agent.set_primary_standby(
                primary={"provider": "openai", "model": "gpt-4o-mini"},
                standbys=[
                    {"provider": "deepseek", "model": "deepseek-chat"},
                    {"provider": "qwen", "model": "qwen-turbo"},
                ],
                enable_warmup=True,
            )
        """
        # 1. 解析 primary
        if primary is not None:
            new_primary_provider = primary.get("provider", self.model_provider)
            new_primary_model = primary.get("model", self.model_name)
        else:
            new_primary_provider = self.model_provider
            new_primary_model = self.model_name

        # 2. 解析 standbys
        if standbys is not None:
            new_standbys = [
                FallbackCandidate(s["provider"], s["model"]) for s in standbys
            ]
        else:
            # 用 fallback 链里除主之外的第一项作为默认 standby
            chain_candidates = self._fallback_chain.candidates
            new_standbys = [
                c for c in chain_candidates
                if not (c.provider == new_primary_provider and c.model == new_primary_model)
            ]

        self.model_provider = new_primary_provider
        self.model_name = new_primary_model
        self._standby_configs = new_standbys
        self._switching_strategy = switching_strategy

        # 3. 重建 fallback chain 与 invoker
        new_chain = ModelFallbackChain(
            [FallbackCandidate(new_primary_provider, new_primary_model)] + new_standbys
        )
        # 注意：reset_invoker 会丢弃单例；新 chain 重新拿
        reset_invoker()
        self.invoker = get_invoker(fallback_chain=new_chain)
        self.fail_log = self.invoker.fail_log

        # 4. 重新构建主 provider 的 agent
        if self.agent is None or switching_strategy == "manual":
            self.init_agent(new_primary_provider, new_primary_model)

        # 5. 启动预热（可选）
        if enable_warmup and new_standbys:
            self._start_standby_warmup(new_standbys[0], warmup_interval)

        logger.info(
            f"Primary/Standby configured: primary={new_primary_provider}/{new_primary_model}, "
            f"standbys={[(s.provider, s.model) for s in new_standbys]}, "
            f"strategy={switching_strategy}"
        )

        return self.get_standby_status()

    def _start_standby_warmup(
        self, standby: FallbackCandidate, interval: float
    ):
        """启动 standby 预热线程。"""
        # 先停掉旧的
        if self._standby_warmup is not None:
            self._standby_warmup.stop()
        self._standby_warmup = StandbyWarmupService(
            standby=standby,
            ping_interval=interval,
        )
        self._standby_warmup.start(
            agent_factory=self._build_agent_for_provider,
            text_extractor=self._extract_ai_text,
        )

    def stop_standby_warmup(self):
        """停止 standby 预热。"""
        if self._standby_warmup is not None:
            self._standby_warmup.stop()
            self._standby_warmup = None

    def get_active_model(self) -> Dict[str, str]:
        """获取当前活跃模型（用户视角）。

        注意："活跃"指的是配置上的主模型；实际调用时若主模型熔断，
        会自动 fallback 到 standby（用户在响应里能看到）。
        """
        return {
            "provider": self.model_provider,
            "model": self.model_name,
        }

    def get_standby_status(self) -> Dict[str, Any]:
        """获取主备状态（用于 UI / 健康检查）。"""
        breaker_states = {p: b.status() for p, b in self.invoker.breakers.items()}
        active = self.get_active_model()
        # 当前 fallback 链上"未熔断"的第一个 = 实际可用模型
        candidates = self._fallback_chain.candidates
        actually_active = active
        for cand in candidates:
            b = self.invoker.breakers.get(cand.provider)
            if b is None or b.allow():
                actually_active = {"provider": cand.provider, "model": cand.model}
                break
        return {
            "primary": active,
            "standbys": [
                {"provider": s.provider, "model": s.model}
                for s in self._standby_configs
            ],
            "actually_active": actually_active,
            "switching_strategy": self._switching_strategy,
            "breaker_states": breaker_states,
            "warmup": self._standby_warmup.status() if self._standby_warmup else None,
        }

    def manual_switch_to(self, provider: str, model: Optional[str] = None) -> bool:
        """手动切换到指定 provider/model。

        用途：
        - 运维强制切换（如某 provider 价格调整）
        - 跨区域灾备
        - 测试/演示
        """
        model = model or (MODEL_VERSIONS[provider][0] if provider in MODEL_VERSIONS else self.model_name)
        return self.init_agent(provider, model)

    # ==========================================
    # Sub-Agent（轻量子任务委派）
    # ==========================================

    def register_sub_agent(
        self,
        capability: str,
        name: Optional[str] = None,
        executor: Optional[Callable[[str], str]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """注册 sub-agent（轻量同步委派）。

        与 multi_agent.WorkerAgent 的区别：
        - WorkerAgent 走 MessageBus / Orchestrator，适合多 Agent 异步编排
        - sub-agent 同步执行，复用 AIAgent 的工具栈/记忆/上下文；
          适合"主 agent 需要并行拆任务，但不想引入 asyncio"的场景

        Args:
            capability: 能力标识（如 "search" / "analyze" / "summarize"）
            name: 显示名
            executor: 任务执行函数；签名 (description: str) -> str；
                      为空时默认调用 self.run(description)
            tags: 标签，便于检索

        Returns:
            sub-agent ID
        """
        # 懒导入避免循环依赖
        try:
            from multi_agent import WorkerAgent
        except ImportError as e:
            raise RuntimeError(
                "sub-agent 依赖 multi_agent.WorkerAgent，请确保 multi_agent.py 可导入"
            ) from e

        agent_id = str(uuid.uuid4())

        # 默认 executor：复用 self.run（共享工具/记忆/上下文）
        if executor is None:
            def _default_executor(description: str) -> str:
                return self.run(description)
            executor = _default_executor

        worker = WorkerAgent(
            agent_id=agent_id,
            name=name or f"SubAgent-{capability}",
            capabilities=[capability],
            executor=executor,
            tags=tags or [capability],
        )
        self._sub_agents[capability] = worker
        logger.info(f"Sub-agent registered: {capability} -> {agent_id}")
        return agent_id

    def unregister_sub_agent(self, capability: str) -> bool:
        """注销 sub-agent。"""
        if capability in self._sub_agents:
            del self._sub_agents[capability]
            return True
        return False

    def list_sub_agents(self) -> List[str]:
        """列出已注册的 sub-agent capabilities。"""
        return list(self._sub_agents.keys())

    def delegate_subtask(
        self,
        capability: str,
        description: str,
        timeout: float = 60.0,
    ) -> str:
        """委派子任务到指定 sub-agent（同步）。

        Args:
            capability: 已注册的能力
            description: 任务描述（将作为 user_input 传给 sub-agent）
            timeout: 单次超时

        Returns:
            sub-agent 的执行结果；失败时返回错误字符串

        Example:
            agent.register_sub_agent("summarize")
            result = agent.delegate_subtask(
                "summarize",
                "请用 50 字总结这段文字：...",
            )
        """
        if capability not in self._sub_agents:
            return f"❌ 未注册的 capability: {capability}（已注册: {self.list_sub_agents()}）"
        worker = self._sub_agents[capability]
        try:
            # 复用 worker._executor（同步）
            return worker._executor(description)
        except Exception as e:
            logger.error(f"Sub-agent '{capability}' failed: {e}")
            return f"❌ Sub-agent '{capability}' 执行失败: {e}"

    # ==========================================
    # 会话管理
    # ==========================================

    def _ensure_session(self) -> None:
        try:
            session = self.context_manager.get_session(self.current_session_id)
            if not session:
                self.context_manager.create_session(session_id=self.current_session_id)
        except Exception as e:
            logger.warning(f"Failed to ensure session: {e}")

    def set_session(self, session_id: str) -> None:
        self.current_session_id = session_id
        self._ensure_session()

    def create_new_session(self) -> str:
        self.current_session_id = str(uuid.uuid4())
        self._ensure_session()
        return self.current_session_id

    # ==========================================
    # 公共管线（DRY）
    # ==========================================

    def _resolve_session(self, session_id: Optional[str]) -> None:
        if session_id:
            self.set_session(session_id)

    def _ensure_agent_ready(self) -> Optional[str]:
        """确保 agent 就绪。返回错误信息（如未就绪），否则返回 None。"""
        if not self.agent:
            self.init_agent()
        if not self.agent:
            return (
                "❌ 错误: 请先配置 API Key。\n\n"
                "点击右上角的 ⚙️ 按钮配置 API Key。"
            )
        return None

    def _check_safety(self, user_input: str) -> Optional[str]:
        """对输入做安全检查。返回错误信息（如被阻止），否则返回 None。"""
        try:
            security_check = self.security.check_input(user_input)
        except Exception as e:
            logger.warning(f"Security check failed (degrade to allow): {e}")
            return None
        if security_check.get("blocked"):
            logger.warning(f"Input blocked: {security_check.get('reason')}")
            return f"❌ 输入被阻止: {security_check.get('reason')}"
        return None

    def _detect_intent(self, user_input: str) -> tuple[str, int]:
        """调用 SecurityModule 做意图检测，返回 (intent, importance)。"""
        try:
            intent = self.security.check_input(user_input).get("detected_intent", "general")
            return intent, self._importance_for_intent(intent)
        except Exception as e:
            logger.warning(f"Intent detect failed: {e}")
            return "general", MemoryImportance.MEDIUM.value

    def _record_user_turn(self, user_input: str, intent: str, importance: int) -> None:
        """记录用户输入到结构化上下文与短期记忆。"""
        try:
            self.context_manager.add_message(
                session_id=self.current_session_id,
                role="user",
                content=user_input,
                metadata={"intent": intent},
            )
        except Exception as e:
            logger.warning(f"Failed to record user msg to context: {e}")

        try:
            self.memory_store.add(
                content=f"用户: {user_input}",
                session_id=self.current_session_id,
                importance=importance,
                intent=intent,
            )
        except Exception as e:
            logger.warning(f"Failed to add user msg to memory store: {e}")

    def _build_enhanced_input(self, user_input: str) -> str:
        """基于上下文与记忆构建增强输入（仍以字符串形式拼接，便于上层注入）。"""
        parts: List[str] = []
        try:
            memory_context = self.memory_store.get_context(user_input, self.current_session_id)
            if memory_context:
                parts.append(memory_context)
        except Exception as e:
            logger.warning(f"Failed to fetch memory context: {e}")

        try:
            context = self.context_manager.build_context(
                self.current_session_id,
                user_input=user_input,
            )
            if context:
                parts.append(context)
        except Exception as e:
            logger.warning(f"Failed to build context: {e}")

        if parts:
            return f"{chr(10).join(parts)}\n\n用户问题: {user_input}"
        return user_input

    def _apply_user_prompt_template(self, user_input: str, enhanced_input: str) -> str:
        """在送进 LLM 之前，对 user-side 消息字符串再走一层 User Prompt 模板。

        职责：
        - 注入 few-shot 示例（如果有）；
        - 在指定注入位插入上下文片段（已由 _build_enhanced_input 产出）；
        - 应用安全重写（脱敏/去越狱语/截断）。

        行为契约：
        - 模板关闭（v1.0.0 / user_only）或异常时，原样返回 enhanced_input；
        - 模板开启时，渲染结果完整替换 LLM 看到的 user message 文本；
          因为 enhanced_input 已包含"上下文 + 用户问题"，把它作为 context
          喂给 user prompt 模板即可；模板会做最后的安全重写与组装。

        失败降级：异常时打印 warning 并返回 enhanced_input，不影响主流程。
        """
        try:
            reg = get_user_prompt_registry()
            template = reg.get_active_template("default")
            # 兼容 v1.0.0（user_only + security_rewrite.enabled=False）：
            # 此时模板不会拼装 few-shot 也不会注入 context —— 原样返回。
            if template is None:
                return enhanced_input
            if (
                template.structure == "user_only"
                and not template.few_shots
                and not template.security_rewrite.enabled
            ):
                return enhanced_input
            rendered = reg.render(
                name="default",
                user_input=user_input,
                context=enhanced_input,
            )
            if not rendered or not rendered.strip():
                return enhanced_input
            return rendered
        except Exception as e:
            logger.warning(f"user prompt template failed, fallback to raw enhanced_input: {e}")
            return enhanced_input

    def _importance_for_intent(self, intent: str) -> int:
        return _INTENT_TO_IMPORTANCE.get(intent, MemoryImportance.MEDIUM.value)

    # ==========================================
    # Day 6-7：Turn 公共管线（DRY 重构）
    # ==========================================

    def _prepare_turn(
        self,
        user_input: str,
        session_id: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[PreparedTurn]]:
        """Turn 公共前置管线：解析 session / 安全 / 意图 / 输入增强。

        Returns:
            ``(error, turn)``：
            - ``error`` 非空时调用方应直接 yield/return 该错误并停止；
            - ``error`` 为空时 ``turn`` 一定非空，可直接交给 LLM 调用。

        Run 与 run_stream 都先调用本方法，之后各自的 LLM 调用路径才开始分叉。
        """
        # 1. 解析 session
        self._resolve_session(session_id)

        # 2. 空输入早退（**此分支 error 不经过管线，但调用方约定为 error**）
        if not user_input or not user_input.strip():
            return "❌ 错误: 输入不能为空", None

        logger.info(f"User input: {user_input}")

        # 3. agent 就绪
        err = self._ensure_agent_ready()
        if err:
            return err, None

        # 4. 输入安全
        err = self._check_safety(user_input)
        if err:
            return err, None

        # 5. 意图检测
        intent, importance = self._detect_intent(user_input)

        # 6. 记录用户轮（不分 run / stream 两种路径都做）
        self._record_user_turn(user_input, intent, importance)

        # 7. 构造最终 user 文本 → payload
        enhanced_input = self._build_enhanced_input(user_input)
        final_input = self._apply_user_prompt_template(user_input, enhanced_input)
        payload = {"messages": [HumanMessage(content=final_input)]}

        return None, PreparedTurn(
            intent=intent,
            importance=importance,
            final_input=final_input,
            payload=payload,
        )

    def _finalize_turn(
        self,
        output: str,
        intent: str,
        importance: int,
        *,
        skip_sanitize: bool = False,
    ) -> str:
        """Turn 公共后置管线：最终输出安全检查 + 记忆写入。

        Args:
            output: LLM 原始输出（同步）或最终累积文本（流式）。
            intent / importance: 来自 ``_prepare_turn``。
            skip_sanitize: 流式场景下用户已经在中间件上做了即时 sanitize；
                            同步场景下走完整 sanitize_output 链路。

        Returns:
            安全的、可直接返回给用户的最终输出文本。
        """
        # 1. 持久化到上下文 + 记忆（无论 sanitize 走不走都先记录原文）
        self._record_assistant_turn(output, intent, importance)

        # 2. 输出安全检查
        if skip_sanitize:
            return output

        try:
            output_check = self.security.check_output(output or "")
            if output_check.get("blocked"):
                logger.warning("Final output blocked by security")
                return "❌ 输出被阻止: 包含敏感信息"
            return self.security.sanitize_output(output)
        except Exception as e:
            logger.warning(f"Output sanitize failed: {e}")
            return output

    def _record_assistant_turn(self, output: str, intent: str, importance: int) -> None:
        """记录助手输出到上下文与记忆，并按需触发整合。"""
        if not output:
            return
        try:
            self.context_manager.add_message(
                session_id=self.current_session_id,
                role="assistant",
                content=output,
            )
        except Exception as e:
            logger.warning(f"Failed to record assistant msg to context: {e}")

        try:
            truncated = output if len(output) <= 500 else output[:500] + "..."
            self.memory_store.add(
                content=f"助手: {truncated}",
                session_id=self.current_session_id,
                importance=importance,
                intent=intent,
            )
        except Exception as e:
            logger.warning(f"Failed to add assistant msg to memory store: {e}")

        # 修复 C8：让 consolidate 真的被触发。每 5 次助手轮询调度一次，
        # 避免每次 run 都全表扫描。失败降级，不影响主流程。
        if not hasattr(self, "_turn_counter"):
            self._turn_counter = 0
        self._turn_counter += 1
        if self._turn_counter % 5 == 0:
            try:
                self.memory_store.consolidate(self.current_session_id)
            except Exception as e:
                logger.warning(f"Memory consolidate failed: {e}")

    def _sanitize_for_output(self, text: str) -> str:
        """对最终输出做安全检查与脱敏。"""
        if not text:
            return text
        try:
            output_check = self.security.check_output(text)
            if output_check.get("blocked"):
                logger.warning("Output blocked: contains sensitive information")
                return "❌ 输出被阻止: 包含敏感信息"
            return self.security.sanitize_output(text)
        except Exception as e:
            logger.warning(f"Output sanitize failed: {e}")
            return text

    def _format_error(self, exc: Exception) -> str:
        msg = str(exc)
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            return "❌ 错误: 请求超时，请检查网络连接或稍后重试。"
        if "api key" in msg.lower() or "unauthorized" in msg.lower():
            return (
                "❌ 错误: API Key 无效或未配置。\n\n"
                "请在 .env 文件中添加：\nOPENAI_API_KEY=your_api_key_here"
            )
        return f"❌ 错误: {msg}"

    @staticmethod
    def _extract_ai_text(state: Dict[str, Any]) -> str:
        """从 1.x create_agent 返回的 state 中抽取最后一条 AIMessage 的文本。"""
        messages = state.get("messages") if isinstance(state, dict) else None
        if not messages:
            return ""
        # 从后向前查找 AIMessage
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    # 1.x 部分模型以分段列表返回
                    parts: List[str] = []
                    for part in content:
                        if isinstance(part, dict) and "text" in part:
                            parts.append(part["text"])
                        elif isinstance(part, str):
                            parts.append(part)
                    return "".join(parts)
        return ""

    @staticmethod
    def _extract_ai_text_from_chunk(chunk: Any) -> str:
        """从 stream(chunk) 中抽取 AI 文本；兼容 values / messages / updates 三种 stream_mode。"""
        if not isinstance(chunk, dict):
            return ""
        # stream_mode="values": chunk 本身是 state
        if "messages" in chunk:
            return AIAgent._extract_ai_text(chunk)
        # stream_mode="messages": chunk 是 (message, metadata) 元组或类似结构
        return ""

    # ==========================================
    # 同步 / 流式入口
    # ==========================================

    def run(self, user_input: str, session_id: Optional[str] = None) -> str:
        """同步运行入口。

        五层容错栈：
            Timeout → Retry → Fallback → FailLog → Graceful Degradation

        关键不变量：
        - 永远返回非空字符串（即使全部失败也返回降级回答）
        - agent 未配置时返回配置错误（前置拦截，不进入 fallback）
        - 输入安全检查失败时立即返回（不消耗 LLM 配额）

        Day 6-7：所有前置管线已在 ``_prepare_turn`` 公共方法实现。
        """
        # 1. 公共前置管线
        err, turn = self._prepare_turn(user_input, session_id)
        if err:
            return err

        # 2. 准备降级时的素材（记忆 + 上下文片段）
        memory_hint = self._safe_memory_hint(user_input)
        context_hint = self._safe_context_hint()

        # 3. 走容错栈（text_extractor 让 invoker 正确抽 AI 文本）
        result: InvokeResult = self.invoker.invoke(
            agent_factory=self._build_agent_for_provider,
            payload=turn.payload,
            config={"configurable": {"thread_id": self.current_session_id}},
            session_id=self.current_session_id,
            memory_hint=memory_hint,
            context_hint=context_hint,
            user_input=user_input,
            text_extractor=self._extract_ai_text,
        )

        # 4. 处理结果（公共后置管线负责 sanitize + 持久化）
        if result.success:
            logger.info(
                f"[OK] provider={result.provider_used}/{result.model_used} "
                f"attempts={result.attempts} fallbacks={result.fallbacks_used}"
            )
            return self._finalize_turn(result.text, turn.intent, turn.importance)

        # 降级路径：result.text 已是骨架回答（同样走最终化管线）
        logger.warning(
            f"[DEGRADED] trace_id={result.trace_id} "
            f"attempts={result.attempts} last_error={result.last_error_kind}"
        )
        return self._finalize_turn(result.text, turn.intent, turn.importance)

    def _extract_ai_text_from_state(self, state: Any) -> str:
        """从 state dict 中抽取 AI 文本（备用辅助方法）。"""
        if state is None:
            return ""
        if isinstance(state, dict):
            return self._extract_ai_text(state)
        return ""

    def _safe_memory_hint(self, user_input: str) -> str:
        """降级时使用的记忆片段（最多 500 chars，失败返回空）。"""
        try:
            ctx = self.memory_store.get_context(user_input, self.current_session_id)
            return (ctx or "")[:500]
        except Exception:
            return ""

    def _safe_context_hint(self) -> str:
        """降级时使用的上下文片段（最多 500 chars）。"""
        try:
            ctx = self.context_manager.build_context(
                self.current_session_id, max_tokens=1000, user_input=""
            )
            return (ctx or "")[:500]
        except Exception:
            return ""

    def run_stream(self, user_input: str, session_id: Optional[str] = None) -> Iterator[str]:
        """流式运行入口。

        流式容错策略（与同步不同）：
        - 单 provider 内不做整体重试（流式已开始产出 token，重试浪费）
        - 遇错时切到下一个 fallback，从头重启 stream
        - 全部 fallback 都失败时 yield 降级回答

        阶段 A3/A4/A5 + Day 6-7：
        - 前置/后置管线走 ``_prepare_turn`` / ``_finalize_turn`` 公共方法，
          与 ``run`` 完全一致；
        - yield 结构化 dict（``data`` 是文本增量），事件类型同 A3/A4/A5 旧约定。
        """
        # helper：避免每处都写 dict
        def _evt(type_: str, **kwargs) -> Dict[str, Any]:
            return {"type": type_, "data": kwargs.pop("data", ""), **kwargs}

        # 0a. 解析 session / logger（前置管线之外的副作用）
        self._resolve_session(session_id)
        if not user_input or not user_input.strip():
            yield _evt("error", data="❌ 错误: 输入不能为空")
            return
        logger.info(f"Streaming user input: {user_input}")
        yield _evt("start", data=user_input)

        # 0b. 通用前置管线（与 run 共享）
        # 注意：start 已在 0a 发出；前置管线失败时仅 yield 类型事件（safety / error）。
        err, turn = self._prepare_turn(user_input, session_id)
        if err:
            err_str = str(err)
            if "输入被阻止" in err_str or "injection" in err_str.lower():
                yield _evt("safety", data=err_str)
            else:
                yield _evt("error", data=err_str)
            return
        if turn is None:
            # 防御性：走到这里意味着 _prepare_turn 设计缺陷
            yield _evt("error", data="❌ 内部错误: turn 为空")
            return

        # 稳健增量追踪（Day 1-2 改造）：
        # 旧实现用 `last_yielded_len` 长度计数器 + sanitize 文本，会因 sanitize
        # 改长度（脱敏等）导致后续切片错位。新实现基于"已 yield 文本前缀 diff"，
        # 对 sanitize 改长度天然鲁棒；详见 streaming.py。
        tracker = StreamDeltaTracker()
        full_output = ""
        safety_blocked = False

        def _safe_sanitize(text: str) -> str:
            """对增量做脱敏；任何异常都降级为原样返回（不影响主流程）。"""
            if not text:
                return text
            try:
                return self.security.sanitize_output(text) or text
            except Exception:
                return text

        try:
            for event, payload_val in self.invoker.stream(
                agent_factory=self._build_agent_for_provider,
                payload=turn.payload,
                config={"configurable": {"thread_id": self.current_session_id}},
                session_id=self.current_session_id,
            ):
                if event == "chunk":
                    # A3：tool_call 事件（与文本无关）
                    tool_name = self._extract_tool_name(payload_val)
                    if tool_name:
                        yield _evt("tool_call", data="", name=tool_name)

                    current_text = self._extract_ai_text(payload_val)
                    if not current_text:
                        continue

                    # 前缀 diff：对 sanitize 改长度天然鲁棒
                    thinking_inc, answer_inc, reset_flag = tracker.feed(
                        current_text,
                        sanitizer=_safe_sanitize,
                        cot_splitter=self._split_cot,
                    )

                    if reset_flag == "RESET":
                        # 上游整段重置：告知前端丢掉之前缓存，从头渲染
                        yield _evt("reset", data="")
                    if thinking_inc:
                        # 把 "## 思考" / "## 回答" 包装剥掉给前端（只传增量文本）
                        yield _evt("thinking", data=_strip_cot_wrapper(thinking_inc))
                    if answer_inc:
                        yield _evt("chunk", data=answer_inc)

                    full_output = tracker.full_output
                elif event == "error":
                    logger.warning(f"Stream chunk error: {payload_val}; trying next fallback")
                    yield _evt("error", data=str(payload_val))
                    # 一旦遇到 provider 错误，下一个 fallback 会从零开始；
                    # 我们也要重置 tracker，否则新旧文本混合。
                    tracker.reset()
                    full_output = ""
                    continue
                elif event == "degraded":
                    # 全部 fallback 失败：降级回答（一次性 yield）
                    yield _evt("chunk", data=payload_val)
                    full_output = payload_val
                    yield _evt("complete", data=full_output, status="degraded")
                    break
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield _evt("error", data=self._format_error(e))
            return

        # 最终安全检查（输出端）：与 _finalize_turn 逻辑等价但要 yield 事件
        try:
            output_check = self.security.check_output(full_output or "")
            if output_check.get("blocked"):
                logger.warning("Final output blocked by security")
                yield _evt("safety", data="❌ 输出被阻止: 包含敏感信息")
                safety_blocked = True
        except Exception as e:
            logger.warning(f"Final safety check failed: {e}")

        if safety_blocked:
            # 即便 blocked，也要把"已收到的文本"存入记忆以便审计/复盘
            self._record_assistant_turn(full_output, turn.intent, turn.importance)
            return

        # 后置管线（无 sanitize：流式场景逐增量已 sanitize 过，且最后再做 block 检查）
        self._record_assistant_turn(full_output, turn.intent, turn.importance)
        yield _evt("complete", data=full_output)
        logger.info("Streaming completed")

    # ==========================================
    # 阶段 A3/A4 辅助方法（CoT 拆分 / tool name 抽取）
    # ==========================================

    @staticmethod
    def _extract_tool_name(state: Any) -> Optional[str]:
        """从 LangGraph 1.x 的 state 中抽取最近一次工具调用名。

        兼容：state["messages"][-1] 是 ToolMessage 或 AIMessage(含 tool_calls)。
        """
        try:
            messages = state.get("messages") if isinstance(state, dict) else None
            if not messages:
                return None
            last = messages[-1]
            # 1) AIMessage.tool_calls: list[{"name": "...", ...}]
            tool_calls = getattr(last, "tool_calls", None)
            if tool_calls:
                name = tool_calls[0].get("name") if isinstance(tool_calls[0], dict) else getattr(tool_calls[0], "name", None)
                if name:
                    return name
            # 2) 直接的 name 属性（ToolMessage）
            name = getattr(last, "name", None)
            if name and name != "ai":
                return name
        except Exception:
            return None
        return None

    @staticmethod
    def _split_cot(full_text: str) -> tuple[str, str]:
        """根据 "## 思考 ##" / "## 回答 ##" 分段。

        Returns:
            (cot, answer)
        """
        if "## 思考" not in full_text:
            return "", full_text
        try:
            head, _, rest = full_text.partition("## 思考")
            cot_part, _, answer_part = rest.partition("## 回答")
            cot = (head + "## 思考" + cot_part).strip()
            answer = answer_part.strip() or ""
            return cot, answer
        except Exception:
            return "", full_text

    @staticmethod
    def _slice_thinking_increment(delta: str) -> str:
        """从增量里提取位于"## 思考"段落内的文字。"""
        if "## 思考" not in delta:
            return ""
        try:
            _, _, rest = delta.partition("## 思考")
            cot, sep, _ = rest.partition("## 回答")
            return ("## 思考" + cot + sep) if sep else ("## 思考" + cot)
        except Exception:
            return ""

    # ==========================================
    # 历史与查询
    # ==========================================

    def clear_history(self) -> str:
        """清除对话历史。

        使用 LangGraph 1.x 提供的 delete_thread 替代不存在的 clear()。
        """
        cleared = []

        # 1. 清理 LangGraph checkpointer
        if self.checkpointer is not None:
            try:
                self.checkpointer.delete_thread(self.current_session_id)
                cleared.append("LangGraph 检查点")
            except Exception as e:
                logger.warning(f"Failed to clear checkpointer: {e}")

        # 2. 创建新会话（重置结构化上下文）
        try:
            self.create_new_session()
            cleared.append("结构化上下文")
        except Exception as e:
            logger.warning(f"Failed to create new session: {e}")

        # 3. 重置短期/长期记忆
        try:
            self.memory_store.reset()
            cleared.append("记忆存储")
        except Exception as e:
            logger.warning(f"Failed to reset memory store: {e}")

        if cleared:
            return f"✅ 对话历史已清除: {', '.join(cleared)}"
        return "⚠️ 历史清除部分失败，请查看日志"

    def get_tools_list(self) -> List[str]:
        if self.tools is None:
            return []
        return [tool.name for tool in self.tools]

    # ==========================================
    # 结构化上下文 API（委托给 context_manager）
    # ==========================================

    def get_session_analytics(self) -> Any:
        return self.context_manager.get_session_analytics(self.current_session_id)

    def get_context_summary(self) -> Any:
        return self.context_manager.get_summary(self.current_session_id)

    def get_entities(self, entity_type: Optional[str] = None) -> Any:
        return self.context_manager.get_entities(self.current_session_id, entity_type)

    def list_all_sessions(self, status: Optional[str] = None, limit: int = 20) -> Any:
        return self.context_manager.list_sessions(status=status, limit=limit)


# ============================================================
# Harness 的 agent 侧"壳"（PR1）
# ------------------------------------------------------------
# 目标：给评测/测试一个稳定的入口 ``run_task``，不暴露 LangGraph 内部。
# 本 PR 只包一层 ``run``：
# - 捕获异常 → Trajectory.error
# - 记录 _finalize_turn 之后的 final 文本（必须 sanitize 后的输出）
# - Hooks / Budget / dry_run 形参预留，**默认空实现**（PR3 才会真正消费）
# 事件/工具观测点由后续 PR 注入，**本 PR 不引任何外部依赖**。
# ============================================================

@dataclass
class Event:
    """agent 在执行过程中发出的事件。

    kind 取值（PR1 暂不产生，仍由后续 PR 注入）：
    - ``"llm_call"`` / ``"llm_result"``
    - ``"tool_call"`` / ``"tool_result"``
    - ``"final"`` / ``"error"``
    """
    kind: str
    name: str = ""
    payload: Any = None
    ts_ms: float = 0.0


@dataclass
class Hooks:
    """harness 注入的回调集合。PR1 全部为可选，不传则 agent 内部不触发任何回调。"""
    on_event: Optional[Callable[[Event], None]] = None
    on_tool_call: Optional[Callable[[str, Dict[str, Any]], None]] = None
    on_score: Optional[Callable[[Dict[str, Any]], None]] = None
    # PR15：可选的"事件注入容器"——hooks 想让 ``llm_result`` 等事件加入
    # ``Trajectory.events`` 时，往这里 append；``run_task`` 会在主 events 后拼接。
    extra_events: Optional[List[Event]] = None


@dataclass
class Budget:
    """harness 注入的预算。PR1 **仅 timeout 实际生效**；token/cost 留给后续 PR。"""
    timeout_s: float = 0.0   # 0 = 不限
    max_tokens: int = 0     # 0 = 不限
    max_cost_usd: float = 0.0  # 0 = 不限


@dataclass
class Used:
    """用例实际消耗。"""
    elapsed_s: float = 0.0
    tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class Trajectory:
    """一次 task 的完整轨迹。"""
    events: List[Event] = field(default_factory=list)
    final: Any = None
    used: Used = field(default_factory=Used)
    error: Optional[str] = None


def run_task(
    self,
    user_input: str,
    *,
    hooks: Optional[Hooks] = None,
    budget: Optional[Budget] = None,
    session_id: Optional[str] = None,
    dry_run: bool = False,
) -> Trajectory:
    """harness / tests 共用的统一入口（PR10 接入 Budget.timeout_s）。

    行为契约：
    - 成功：``trajectory.final`` = ``run()`` 返回的字符串（已 sanitize）
    - 异常：``trajectory.error`` = 异常字符串，``trajectory.final`` = 空
    - 超时（``budget.timeout_s > 0``）：``trajectory.error`` 标 ``"TimeoutError: timeout_s=..."``，
      事件序列加 ``timeout``。
    - 超额（``budget.max_tokens`` / ``budget.max_cost_usd``）：``trajectory.error``
      标 ``"BudgetExhaustedError: ..."``，事件序列加 ``budget_exceeded``。
    - ``hooks.on_event`` 在每次发事件时被调用（PR7 真正接入）；
      即便 hooks 为 None，事件也会进 ``trajectory.events``。
    - **PR11** ``dry_run=True``：直接返回 ``trajectory.final=""`` + 事件 ``dry_run``，
      **不调 ``run()``**、不发任何 LLM / I/O。

    注意点
    ~~~~~~

    - 超时实现是软超时：``run()`` 同步阻塞，靠后台线程探针周期性设位、
      主循环在长流程间检查位并抛 ``TimeoutError``。**不会**中断运行中的 LLM HTTP 请求；
      仅在 ``run()`` 自然返回（成功 / 失败）之后做"事后超时"判断。
    - 这个策略对 harness 足够：目标是 cap agent 的**总时长**，
      而非强制中断单个 HTTP 请求。

    注意：``run`` 本身已内置五层容错栈（Timeout/Retry/Fallback/FailLog/Graceful），
    本方法只做"异常兜底 + 时间度量 + 事件埋点 + 软超时"——不重复容错。
    """
    events: List[Event] = []
    t0 = time.monotonic()

    def _emit(kind: str, name: str = "", payload: Any = None) -> None:
        """统一出口：写 events + 触发 hooks.on_event（如果提供）。"""
        ts_ms = (time.monotonic() - t0) * 1000.0
        ev = Event(kind=kind, name=name, payload=payload, ts_ms=ts_ms)
        events.append(ev)
        if hooks is not None and hooks.on_event is not None:
            try:
                hooks.on_event(ev)
            except Exception:  # noqa: BLE001 — hooks 异常不应影响主流程
                logger.exception("[run_task] hooks.on_event raised; ignored")

    # 入参事件先于 run() 发出，便于 harness 看到"起点"
    _emit("turn_start", name="run_task", payload={"input": user_input})

    # PR11：dry_run 短路。直接返回空 final，不调 run()、不发 LLM。
    if dry_run:
        elapsed = time.monotonic() - t0
        _emit("dry_run", name="run_task", payload={"input": user_input})
        return Trajectory(
            events=events,
            final="",
            used=Used(elapsed_s=elapsed),
            error=None,
        )

    # PR10：软超时。运行 run() 期间，至少每 50ms 探一次超时位。
    timeout_s = float(getattr(budget, "timeout_s", 0.0) or 0.0)
    timed_out = [False]

    def _timeout_watchdog() -> None:
        # 后台线程：等到 timeout_s 后置位。
        # 主线程在 run() 之后如何响应见下文。
        target = t0 + timeout_s
        while time.monotonic() < target:
            time.sleep(0.05)
        timed_out[0] = True

    watchdog = None
    if timeout_s > 0:
        import threading
        watchdog = threading.Thread(target=_timeout_watchdog, daemon=True)
        watchdog.start()

    try:
        final_text = self.run(user_input, session_id=session_id)
    except Exception as exc:  # noqa: BLE001 — 必须兜底，harness 不允许抛
        elapsed = time.monotonic() - t0
        _emit("error", name="run", payload=repr(exc))
        return Trajectory(
            events=events + _take_extra_events(hooks),
            final="",
            used=Used(elapsed_s=elapsed),
            error=f"{type(exc).__name__}: {exc}",
        )

    elapsed = time.monotonic() - t0
    if timed_out[0]:
        # run() 跑完了，但已经超时 → 标注为 TimeoutError 容错答。
        _emit("timeout", name="run_task", payload={"timeout_s": timeout_s})
        return Trajectory(
            events=events + _take_extra_events(hooks),
            final="",
            used=Used(elapsed_s=elapsed),
            error=f"TimeoutError: timeout_s={timeout_s:.3f}",
        )

    # 成功路径：附带 sanitize 后的 final 文本
    _emit("final", name="run", payload=final_text)

    # PR15：tokens / cost_usd 真实化。
    # 任何 ``llm_result`` 事件（``run()`` 内部可通过 hooks 注入）会带
    # ``payload["tokens"]`` / ``payload["cost_usd"]``；以**最后一个**事件为准。
    # 没有 llm_result 事件时，回退到 PR12 的粗估（4 chars ≈ 1 token，cost=0）。
    # 注意：extra_events 由 hooks 注入，可能在 run_task 期间才 append；
    # 这里用 _take_extra_events 但**先消耗后借出**（bridge 借出=False），
    # 这样统计完再让后续返回值带走。
    bridge: List[Event] = []
    if hooks is not None and getattr(hooks, "extra_events", None):
        bridge = list(hooks.extra_events)
    all_events = events + bridge
    llm_tokens = None
    llm_cost = None
    for ev in all_events:
        if ev.kind == "llm_result" and isinstance(ev.payload, dict):
            t = ev.payload.get("tokens")
            c = ev.payload.get("cost_usd")
            if t is not None:
                llm_tokens = int(t)
            if c is not None:
                llm_cost = float(c)
    used_tokens = llm_tokens if llm_tokens is not None else len(final_text) // 4
    used_cost = llm_cost if llm_cost is not None else 0.0
    used = Used(elapsed_s=elapsed, tokens=used_tokens, cost_usd=used_cost)

    # PR12：budget.max_tokens / max_cost_usd 短路。
    over_reason = _check_budget_exhausted(budget, used)
    if over_reason is not None:
        _emit("budget_exceeded", name="run_task", payload=over_reason)
        return Trajectory(
            events=events + _take_extra_events(hooks),
            final="",
            used=used,
            error=f"BudgetExhaustedError: {over_reason}",
        )

    return Trajectory(
        events=events + _take_extra_events(hooks),
        final=final_text,
        used=used,
        error=None,
    )


def _take_extra_events(hooks: Optional[Hooks]) -> List[Event]:
    """PR15：把 hooks 里 extra_events 列表的事件搬到主 events 后面。

    用法：harness 想让 agent.run_task 之外的"统计事件"（如 ``llm_result``）
    也出现在 ``Trajectory.events`` 时，构造 ``Hooks(extra_events=[...])``，
    并在自己的代码里 append 到这个列表。``run_task`` 会在每次返回前取走。

    重复调用说明：
    - 每次 ``run_task`` 返回前调用一次（仅消费一次）。
    - 同一 Hooks 实例被多个 ``run_task`` 复用时，第二次调用的 ``extra_events``
      如果已被前一次消费，应由调用方重新填充。
    """
    if hooks is None:
        return []
    extras = getattr(hooks, "extra_events", None)
    if not extras:
        return []
    # 取走 = 复制后清空（避免下次复用 stale 数据）
    out = list(extras)
    extras.clear()
    return out


def _check_budget_exhausted(budget: Optional[Budget], used: Used) -> Optional[Dict[str, Any]]:
    """PR12：budget 短路。返回 None 表示未超额；否则返回描述 dict。

    规则：
    - ``max_tokens`` = 0 → 不限；
    - ``max_cost_usd`` = 0 → 不限；
    - 任何一个超额 → 返回超额原因（payload），由 ``run_task`` 转成 error。
    """
    if budget is None:
        return None
    max_tokens = int(getattr(budget, "max_tokens", 0) or 0)
    max_cost_usd = float(getattr(budget, "max_cost_usd", 0.0) or 0.0)
    if max_tokens > 0 and used.tokens > max_tokens:
        return {
            "kind": "tokens",
            "used": used.tokens,
            "limit": max_tokens,
        }
    if max_cost_usd > 0 and used.cost_usd > max_cost_usd:
        return {
            "kind": "cost",
            "used": used.cost_usd,
            "limit": max_cost_usd,
        }
    return None


# 把 run_task 绑到 AIAgent 类上（PR1 行为：默认不接任何外部逻辑，
# 仅在 ``run`` 外面包一层护栏 + Trajectory 收集）
AIAgent.run_task = run_task


# 显式导出，便于 PR2 从 harness_api 里 import
__all__ = [
    "Event",
    "Hooks",
    "Budget",
    "Used",
    "Trajectory",
    "AIAgent",
]