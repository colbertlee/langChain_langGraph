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
"""

import json
import os
import sqlite3
import logging
import time
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional

from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver

# v2.2.1 — Human-in-the-Loop 拦截（延迟到运行时再 import，避免循环依赖）

from config import (
    OPENAI_API_KEY, DEEPSEEK_API_KEY, QWEN_API_KEY, MINIMAX_API_KEY,
    ZHIPU_API_KEY, MOONSHOT_API_KEY, BAIDU_API_KEY, BAIDU_SECRET_KEY,
    SPARK_API_KEY, SPARK_SECRET_KEY, SPARK_APP_ID,
    DOUBAO_API_KEY, HUNYUAN_API_KEY, SILICONFLOW_API_KEY, GLM_API_KEY,
    MODEL_NAME, MODEL_PROVIDER, TEMPERATURE, LOG_LEVEL, MODEL_VERSIONS,
    PROVIDER_META,
)
from tools import set_rag_instance
from rag import RAGModule
from security import SecurityModule, set_security_instance, get_security_instance
from llm_reliability import (
    ResilientLLMInvoker, ModelFallbackChain, FallbackCandidate,
    RetryConfig, FailLogRepository, GracefulDegradation,
    PrimaryStandbyConfig, StandbyWarmupService,
    get_invoker, reset_invoker, InvokeResult,
)
from context_manager import get_context_manager
from memory_store import MemoryImportance
from prompt_registry import get_prompt_registry, PromptTemplate
from user_prompt_registry import get_user_prompt_registry


# ==========================================================
# API Key 真实性判断（与 app.py 的 _is_placeholder_key 对齐）
# ==========================================================
# 目的：get_api_key_status / get_available_models 在判断某 provider 是否
#       "已配置"时，要排除 .env 模板里的占位符（your_xxx_here / sk-test 等）。
# 之前用 bool(API_KEY)，会把 "your_openai_api_key_here" 也判为 True，
# 导致前端 UI 显示「Key 已配置」但实际切换会失败。
#
# 与 app.py 的 _is_placeholder_key 保持一致的标记集合。
_PLACEHOLDER_MARKERS = (
    "your-", "your_", "xxxx", "placeholder", "<", ">",
    "sk-xxx", "sk-your", "sk-test", "sk-fake", "fake-key", "fake_key",
)


def _is_real_api_key(api_key: str) -> bool:
    """判定一个 API Key 字符串是否为「真实可用」。

    规则：
      - 空字符串 → False
      - 含占位符标记（your-/your_/sk-test 等） → False
      - 长度 < 8 → False（防误判）
      - 其他 → True

    与 app.py._is_placeholder_key 行为等价，但额外返回 bool 表示「是否可用」。
    """
    if not api_key or not isinstance(api_key, str):
        return False
    if len(api_key.strip()) < 8:
        return False
    low = api_key.strip().lower()
    for marker in _PLACEHOLDER_MARKERS:
        if marker in low:
            return False
    return True

# ==========================================================
# v2.0 slim 入口（v2.10+ 不再支持 LEGACY_MODE 切换）
# ==========================================================
# 历史：本模块曾通过 LEGACY_MODE 在老 tools/memory 与 v2_slim 入口之间切换。
# v2.10 起，LEGACY 路径与 _legacy.py 模块已全部移除，仅保留 v2 slim 入口。
# ==========================================================
from v2_slim.tools_v2 import get_all_tools_v2 as _resolve_tools
from tools_registry import resolve_tools_for_runtime as _resolve_tools_for_runtime
from v2_slim.memory_store_v2 import get_memory_store_v2 as _resolve_memory_store


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

logger.info("v2_slim runtime: tools/memory always v2_slim (LEGACY_MODE removed in v2.10)")


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


# P2-W7：助手输出写入长期记忆时的截断长度（可配置）
# 解析优先级：环境变量 MEMORY_SUMMARY_CHARS > 类属性 > 默认值 500
_DEFAULT_MEMORY_SUMMARY_CHARS = 500


def _resolve_memory_summary_chars() -> int:
    """解析助手输出截断长度。

    优先级：
      1. 环境变量 MEMORY_SUMMARY_CHARS（必须是 > 0 的整数）
      2. 类属性 AIAgent.MEMORY_SUMMARY_CHARS（默认 _DEFAULT_MEMORY_SUMMARY_CHARS）
      3. fallback 到 _DEFAULT_MEMORY_SUMMARY_CHARS
    """
    env_val = os.environ.get("MEMORY_SUMMARY_CHARS", "").strip()
    if env_val:
        try:
            n = int(env_val)
            if n > 0:
                return n
            logger.warning(
                f"MEMORY_SUMMARY_CHARS={env_val} 必须为正整数，fallback 到默认值"
            )
        except ValueError:
            logger.warning(
                f"MEMORY_SUMMARY_CHARS={env_val} 无法解析为整数，fallback 到默认值"
            )
    cls_default = getattr(
        AIAgent, "MEMORY_SUMMARY_CHARS", _DEFAULT_MEMORY_SUMMARY_CHARS
    )
    try:
        n = int(cls_default)
        if n > 0:
            return n
    except (TypeError, ValueError):
        pass
    return _DEFAULT_MEMORY_SUMMARY_CHARS


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


# ============================================================
# v2.2.1 — HITL 工具包装
# ============================================================


def _extract_session_meta(config: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """从 LangGraph config 抽取 session_id（兼容 configurable.thread_id / session_id 两种写法）。"""
    if not isinstance(config, dict):
        return {}
    cfg = config.get("configurable") or {}
    return {
        "thread_id": str(cfg.get("thread_id") or cfg.get("session_id") or ""),
    }


def _tool_call_fingerprint(tool_name: str, args: Any) -> str:
    """生成 (tool_name, sorted_args_json) 元组，跨进程稳定。"""
    try:
        normalized = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        normalized = str(args)
    return f"{tool_name}::{normalized}"


class _HITLWrappedTool:
    """把任意 LangChain Tool / StructuredTool 包一层，强制走 HITL 拦截。

    行为：
      - 首次 invoke(thread_id=..., args=...) → 检查 HITLStore
        * 已有 approved 决议（按 (session_id, tool_name, args) 指纹匹配）→ 真正执行 inner
        * 已有 rejected 决议 → 返回 "Action cancelled by user: {reason}"
        * 仍是 pending → 写一条新 pending（如果该指纹尚无 pending）并返回 sentinel 字符串
        * 完全没有 pending / decision 记录 → 创建 pending → 返回 sentinel
      - 后续 invoke（同 thread_id + 同指纹）→ 已 approved 真正执行 / 已 rejected 返回取消消息。

    兜底：若 config 中无 thread_id（agent 流里没传 config），直接执行 inner（保持向后兼容）。

    注意：本类不强制要求 inner 是 StructuredTool；只要它有 ``name``/``invoke``/``_run`` 即可。
    """

    _HITL_PENDING_SENTINEL = "__HITL_PENDING__"

    def __init__(self, inner: Any, *, requires_approval: Optional[bool] = None) -> None:
        self._inner = inner
        # 镜像工具属性（让 LangChain / LangGraph 仍把它当工具用）
        self.name = getattr(inner, "name", "wrapped_tool")
        self.description = getattr(inner, "description", "")
        self.args_schema = getattr(inner, "args_schema", None)
        # 标记：已经被包过一次（防止 _wrap_tools_with_hitl 二次包装）
        self._hitl_wrapped: bool = True
        # v2.2.1 — 标记本工具的策略；若未显式指定则按 hitl_langgraph.tool_requires_approval 推断
        self._requires_approval_flag = requires_approval

    # ----- LangChain 工具接口 -----
    def _run(self, *args: Any, **kwargs: Any) -> str:
        # 旧 BaseTool 路径
        return self.invoke(kwargs if not args else args[0], config=None)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self.invoke(kwargs if not args else args[0], config=None)

    # ----- 核心拦截 -----
    def invoke(self, input: Any, config: Optional[Dict[str, Any]] = None, **kwargs: Any) -> str:
        # 1) 抽取 args（LangChain StructuredTool.invoke(input, config=None)）
        if isinstance(input, dict):
            tool_args = dict(input)
        else:
            tool_args = dict(kwargs)
        # 2) 抽取 session
        meta = _extract_session_meta(config)
        thread_id = meta.get("thread_id") or ""
        # 3) 拦截判定
        try:
            from hitl_langgraph import (
                HITLStore,
                tool_requires_approval,
            )

            needs = self._requires_approval_flag
            if needs is None:
                needs = tool_requires_approval(self._inner)
            if not thread_id or not needs:
                # 无 thread_id 或 不需要审批：兜底直接执行
                return self._call_inner(input, config=config, **kwargs)
            store = HITLStore.instance()
            # 3a) 先查询现有决议（approved / rejected）—— 找 (session_id, tool_name, args 指纹) 匹配
            fp = _tool_call_fingerprint(self.name, tool_args)
            existing = self._find_decision(store, thread_id, fp)
            if existing is not None:
                if existing.status == "approved":
                    # 用用户修改后的 tool_args 执行
                    new_args = existing.decision_payload or tool_args
                    return self._call_inner(new_args, config=config)
                if existing.status == "rejected":
                    return (
                        f"Action cancelled by user: {existing.reject_reason or 'Action cancelled by user'}"
                    )
                # status == 'consumed' / 'pending'：继续往下走
            # 3b) 创建新的 pending
            from hitl_langgraph import intercept_tool_call

            decision, pending = intercept_tool_call(
                self._inner, tool_args, thread_id
            )
            if decision == "allow":
                return self._call_inner(input, config=config, **kwargs)
            # decision == "pending"
            return (
                f"{self._HITL_PENDING_SENTINEL} request_id={pending.request_id} "
                f"tool={pending.tool_name} thread_id={thread_id}"
            )
        except Exception as e:
            # 拦截失败 → 兜底直接执行（避免 HITL bug 导致整个 agent 崩）
            logger.warning(f"HITL wrap invoke failed, fallback to direct: {e}")
            return self._call_inner(input, config=config, **kwargs)

    def _find_decision(
        self, store: Any, thread_id: str, fingerprint: str
    ) -> Optional[Any]:
        """查询当前 session 内匹配 fingerprint 的最新 resolved decision。

        - approved: 用 decision_payload 重跑 inner
        - rejected: 返回取消消息
        - pending / consumed: 返回 None（继续创建新 pending）
        """
        try:
            all_items = store.list_all_for_session(thread_id)
        except Exception:
            return None
        # 按 created_at 倒序：找最近的匹配
        candidates = []
        for p in all_items:
            try:
                p_fp = _tool_call_fingerprint(
                    p.tool_name, p.tool_args
                )
            except Exception:
                continue
            if p_fp == fingerprint:
                candidates.append(p)
        if not candidates:
            return None
        # 找最新且状态为 approved / rejected 的
        candidates.sort(key=lambda x: getattr(x, "created_at", 0), reverse=True)
        for p in candidates:
            if p.status in ("approved", "rejected"):
                return p
        return None

    def _call_inner(
        self, input: Any, config: Optional[Dict[str, Any]] = None, **kwargs: Any
    ) -> str:
        inner = self._inner
        # 优先用 invoke 协议（LangChain 1.x 主流）
        invoke = getattr(inner, "invoke", None)
        if callable(invoke):
            try:
                result = invoke(input, config=config)
                return self._normalize_result(result)
            except TypeError:
                # 部分老 StructuredTool 不收 config
                result = invoke(input)
                return self._normalize_result(result)
        # 兜底：_run
        run = getattr(inner, "_run", None)
        if callable(run):
            if isinstance(input, dict):
                result = run(**input)
            else:
                result = run(input)
            return self._normalize_result(result)
        # 最兜底：直接调用
        if isinstance(input, dict):
            return str(inner(**input))
        return str(inner(input))

    @staticmethod
    def _normalize_result(result: Any) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            try:
                return json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                return str(result)
        return str(result)


class AIAgent:
    """多功能 AI Agent 主类（LangChain 1.x 适配版）。

    设计要点：
    - security 在 __init__ 即被初始化（防御性降级），不依赖 init_agent。
    - tools 在 __init__ 即被加载（轻量），但内部依赖（如 rag）延迟到 init_agent。
    - checkpointer 在 init_checkpointer 中创建，create_agent 直接接收。
    - 系统提示在 init_agent 中基于 self.tools 动态生成。
    - run / run_stream 使用 1.x 的 {"messages": [...]} 输入格式。
    """

    # P2-W7：助手输出写入长期记忆时的默认截断长度（写入 memory_store 前截断）。
    # 优先级：env MEMORY_SUMMARY_CHARS > 本类属性 > 500。
    # 运行时通过 _resolve_memory_summary_chars() 解析，子类可覆写本类属性。
    MEMORY_SUMMARY_CHARS: int = _DEFAULT_MEMORY_SUMMARY_CHARS

    def __init__(self):
        self.model_provider = MODEL_PROVIDER
        self.model_name = MODEL_NAME
        self.model: Optional[Any] = None
        self.rag: Optional[RAGModule] = None
        self.security: SecurityModule = get_security_instance()
        # P0-3：默认 tools 来源切换到 tools_registry（含 v2_slim 6 个 + knowledge_search）。
        # 保持与 _resolve_tools 完全相同的集合（仅多加 knowledge_search）—— _resolve_tools 保留
        # 是为了兼容旧路径（agent_tool_router.resolve_tools 仍需要它来构造 session 额外工具）。
        self.tools = self._wrap_tools_with_hitl(_resolve_tools_for_runtime())
        self.checkpointer: Optional[SqliteSaver] = None
        # LangChain 1.x：create_agent 直接返回可执行对象
        self.agent: Optional[Any] = None
        self._checkpointer_conn: Optional[sqlite3.Connection] = None
        self._system_prompt: Optional[str] = None

        # 结构化上下文管理器
        self.context_manager = get_context_manager()
        self.current_session_id = str(uuid.uuid4())

        # 短期/长期记忆（LEGACY 切换）
        self.memory_store = _resolve_memory_store()

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

    def _init_checkpointer(self, memory_fallback: Optional[bool] = None) -> None:
        """初始化 LangGraph 持久化检查点。

        逻辑判定顺序：
        1. 先尝试 SqliteSaver（生产路径）；
        2. 仅当 SqliteSaver 失败时，再检查"显式 opt-in 内存模式"开关：
           - 调用参数 memory_fallback=True，或
           - 环境变量 AI_AGENT_INMEM_CHECKPOINT ∈ {1, true, yes, on}
           满足任一条件 → 降级为 MemorySaver 并打 WARNING；
        3. 开关未开启 → 直接 raise RuntimeError 阻止启动（禁止静默降级）。

        关键不变量：
        - 默认情况下 SqliteSaver 必须成功；失败 = 显式崩溃。
        - 内存模式属于"显式 opt-in"行为，启动时会打 WARNING 日志告知用户
          持久化能力已禁用（避免误以为仍持久化）。
        """
        try:
            conn = sqlite3.connect("memory.db", check_same_thread=False)
            self._checkpointer_conn = conn
            self.checkpointer = SqliteSaver(conn)
            return
        except Exception as e:
            sqlite_err = e
            logger.warning(f"SqliteSaver init failed: {e}; checking fallback policy")

        # --- 失败分支：检查 opt-in 内存降级 ---
        env_opt_in = os.environ.get(
            "AI_AGENT_INMEM_CHECKPOINT", ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        arg_opt_in = bool(memory_fallback)
        if not (env_opt_in or arg_opt_in):
            # P1：未开启 opt-in，直接显式失败，禁止静默降级
            raise RuntimeError("SqliteSaver Checkpoint store unavailable")

        try:
            from langgraph.checkpoint.memory import MemorySaver
            self.checkpointer = MemorySaver()
            self._checkpointer_conn = None
            logger.warning(
                "Checkpointer 初始化失败，已显式降级为内存模式"
            )
        except Exception as e:
            raise RuntimeError(
                f"SqliteSaver Checkpoint store unavailable: {sqlite_err}; "
                f"MemorySaver fallback also failed: {e}"
            ) from e

    # ============================================================
    # v2.2.1 — HITL 工具拦截（轻量包装层）
    # ============================================================

    def _wrap_tools_with_hitl(self, tools: List[Any]) -> List[Any]:
        """对每个 tool 判定是否需要审批，若需要则用 _HITLWrappedTool 包裹。

        幂等性：已经被包过的 tool（``_hitl_wrapped == True``）不会被再次包。
        """
        if not tools:
            return tools
        out: List[Any] = []
        for t in tools:
            if t is None:
                continue
            if getattr(t, "_hitl_wrapped", False):
                # 已是 HITL 包装；保留原样
                out.append(t)
                continue
            try:
                from hitl_langgraph import tool_requires_approval

                if tool_requires_approval(t):
                    out.append(_HITLWrappedTool(t))
                else:
                    out.append(t)
            except Exception as e:
                # hitl_langgraph 不可用：保持原样（向后兼容）
                logger.debug(f"_wrap_tools_with_hitl: tool_requires_approval check skipped: {e}")
                out.append(t)
        return out

    # ============================================================
    # v2.1 — bind_tools_for_session / set_pending_vision_blocks
    # ============================================================

    _session_tool_map: Dict[str, List[str]] = {}
    """class-level: per-session 工具名列表（每次 bind_tools_for_session 覆盖）。"""

    _pending_vision_blocks: Dict[str, List[Dict[str, Any]]] = {}
    """class-level: per-session 待注入 HumanMessage 的视觉块（图片 / OCR 文本）。

    set_pending_vision_blocks(sid, blocks) → 写；下次 get_effective_tools / run_stream 时用掉。
    """

    def bind_tools_for_session(self, tool_names: List[str]) -> List[str]:
        """v2.1 — 为当前会话（self.current_session_id）绑定 tool 列表。

        行为：
          - 覆盖式更新：同一个 session 后调用的会完全替换前一次的工具集合
          - 不同 session 互不影响（self._session_tool_map 字典按 session_id 隔离）
          - 同时刷新 self.tools：把 session 工具追加到 self.tools 末尾（去重）
            —— 让外部直接读 agent.tools 也能看到绑定的工具
          - 通过 get_effective_tools() 动态合并（兼容更复杂场景）

        返回：本次实际写入的工具名列表（去重 + 过滤 None）。
        """
        sid = getattr(self, "current_session_id", None) or "default"
        names = [str(n) for n in (tool_names or []) if n]
        # 去重但保持顺序
        seen: set = set()
        uniq: List[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                uniq.append(n)
        type(self)._session_tool_map[sid] = uniq
        # 同步把 per-session tools 注入到 self.tools 末尾（不修改 base，只追加 session 专属）
        try:
            base = list(getattr(self, "tools", None) or [])
            base_names = {getattr(t, "name", None) for t in base}
            if uniq:
                from agent_tool_router import resolve_tools
                resolved = resolve_tools(uniq)
                for t in resolved:
                    tn = getattr(t, "name", None)
                    if tn and tn not in base_names:
                        base.append(t)
                        base_names.add(tn)
            self.tools = base
        except Exception as _e:
            logger.debug(f"bind_tools_for_session self.tools 同步失败: {_e}")
        # 若 model 已就绪 + 系统 prompt 已设，重建 self.agent（让 LangGraph ToolNode 反映新 tools）
        try:
            if getattr(self, "model", None) is not None and getattr(self, "_system_prompt", None) is not None:
                from langchain.agents import create_agent
                self.agent = create_agent(
                    model=self.model,
                    tools=self.tools,
                    system_prompt=self._system_prompt,
                    checkpointer=getattr(self, "checkpointer", None),
                )
        except Exception as _e:
            logger.debug(f"bind_tools_for_session self.agent 重建失败: {_e}")
        return uniq

    def get_effective_tools(self) -> List[Any]:
        """v2.1 — 实际生效的 tool 列表 = self.tools + per-session 额外 tools。

        - base 永远保留（self.tools）
        - per-session 列表从 self._session_tool_map[sid] 读
        - 同名工具不会重复出现（base 优先）
        """
        sid = getattr(self, "current_session_id", None) or "default"
        session_names = type(self)._session_tool_map.get(sid) or []
        base = list(self.tools or [])
        base_names = {getattr(t, "name", None) for t in base}
        extras: List[Any] = []
        if session_names:
            try:
                from agent_tool_router import resolve_tools
                resolved = resolve_tools(session_names)
            except Exception:
                resolved = []
            for t in resolved:
                if getattr(t, "name", None) not in base_names:
                    extras.append(t)
                    base_names.add(getattr(t, "name", None))
        return base + extras

    def set_temperature(self, temperature: float) -> bool:
        """v2.1 — 动态调整模型 temperature。

        实现：构造新 model 实例 + 调用 init_agent 重绑（保持与 switch_model 一致）。
        失败（如无 API key）→ 返回 False。
        """
        try:
            global TEMPERATURE
            TEMPERATURE = float(temperature)
            return True
        except Exception:
            return False

    def set_pending_vision_blocks(
        self, blocks: Optional[List[Dict[str, Any]]]
    ) -> None:
        """v2.1 — 为当前 session 缓存一次性的视觉块（图片 / OCR 文本）。

        blocks 中每条形如 {"type": "image" | "ocr", "content": "...", "filename": "img.png"}。
        这些块会在下一次 run_stream 的第一条 HumanMessage 中被消费（_consume_pending_vision_blocks）。
        """
        sid = getattr(self, "current_session_id", None) or "default"
        type(self)._pending_vision_blocks[sid] = list(blocks or [])

    def _consume_pending_vision_blocks(
        self, session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """v2.1 — 取出并清空当前 session 的待注入视觉块。"""
        sid = session_id or getattr(self, "current_session_id", None) or "default"
        return type(self)._pending_vision_blocks.pop(sid, [])

    @classmethod
    def reset_session_state_for_tests(cls) -> None:
        """v2.1 — 测试辅助：清空 class-level per-session 状态。"""
        cls._session_tool_map.clear()
        cls._pending_vision_blocks.clear()

    def _get_model(self, provider: Optional[str] = None, model_name: Optional[str] = None):
        """根据 provider 获取对应的模型实例。

        优先走 OpenAI 兼容协议（langchain_openai.ChatOpenAI）。
        Baidu/Spark 暂用 langchain_community 的客户端（保留旧逻辑）。
        """
        provider = provider or self.model_provider
        model_name = model_name or self.model_name

        base_url = _build_provider_base_url(provider)

        # OpenAI 兼容 provider：openai + 全量国产模型（除 baidu/spark 外）
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
            # P0-3：与 __init__ 同步走 tools_registry 单一真相。
            self.tools = self._wrap_tools_with_hitl(_resolve_tools_for_runtime())
            self._system_prompt = self._build_system_prompt()

            # LangChain 1.x: create_agent 直接接收 checkpointer，
            # 返回 CompiledStateGraph（不再需要 AgentExecutor 包装）
            self.agent = create_agent(
                model=self.model,
                tools=self.tools,
                system_prompt=self._system_prompt,
                checkpointer=self.checkpointer,
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
            "openai": _is_real_api_key(OPENAI_API_KEY),
            "deepseek": _is_real_api_key(DEEPSEEK_API_KEY),
            "qwen": _is_real_api_key(QWEN_API_KEY),
            "zhipu": _is_real_api_key(ZHIPU_API_KEY) or _is_real_api_key(GLM_API_KEY),
            "moonshot": _is_real_api_key(MOONSHOT_API_KEY),
            "minimax": _is_real_api_key(MINIMAX_API_KEY),
            "baidu": _is_real_api_key(BAIDU_API_KEY),
            "spark": _is_real_api_key(SPARK_API_KEY),
            "doubao": _is_real_api_key(DOUBAO_API_KEY),
            "hunyuan": _is_real_api_key(HUNYUAN_API_KEY),
            "siliconflow": _is_real_api_key(SILICONFLOW_API_KEY),
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
            return create_agent(
                model=tmp_model,
                tools=self.tools or [],
                system_prompt=self._system_prompt or "You are a helpful assistant.",
                checkpointer=self.checkpointer,
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
        """基于上下文与记忆构建增强输入（仍以字符串形式拼接，便于上层注入）。

        阶段性目标（P0 重构）：
        - 保留字符串返回，用于兼容 user prompt 模板（保持最小改动）；
        - 同时把上下文 / 记忆拆成独立 parts，供 _build_messages_payload 拼接
          为 SystemMessage + HumanMessage 结构化 payload。

        P1：memory_store.get_context 增加 max_tokens=1000 上限，防止长对话下
        检索结果膨胀导致 token 预算溢出。
        """
        parts: List[str] = []
        context_parts: List[str] = []
        try:
            memory_context = self.memory_store.get_context(
                user_input, self.current_session_id, max_tokens=1000
            )
            if memory_context:
                parts.append(memory_context)
                context_parts.append(memory_context)
        except Exception as e:
            logger.warning(f"Failed to fetch memory context: {e}")

        try:
            context = self.context_manager.build_context(
                self.current_session_id,
                user_input=user_input,
            )
            if context:
                parts.append(context)
                context_parts.append(context)
        except Exception as e:
            logger.warning(f"Failed to build context: {e}")

        if parts:
            return f"{chr(10).join(parts)}\n\n用户问题: {user_input}"
        return user_input

    def _build_messages_payload(
        self, user_input: str, final_input: str
    ) -> List[Any]:
        """构造结构化的 LangChain Message 列表（SystemMessage + HumanMessage）。

        背景：之前 _build_enhanced_input 把上下文 + 用户问题拼成单条 HumanMessage，
        导致 System Prompt 被上下文"用户问题"重写覆盖，多轮指令跟随退化。

        现在明确拆分：
        - SystemMessage：仅携带上下文与记忆片段（不出现用户问题）
        - HumanMessage：仅携带最终 user_input（不受上下文污染）

        返回 List[Any] 以避免在 import 阶段与 langchain_core 类型绑定冲突。
        """
        try:
            memory_context = self.memory_store.get_context(
                user_input, self.current_session_id, max_tokens=1000
            )
        except Exception as e:
            logger.warning(f"[P0] memory context failed: {e}")
            memory_context = ""

        try:
            ctx = self.context_manager.build_context(
                self.current_session_id, user_input=user_input
            )
        except Exception as e:
            logger.warning(f"[P0] context_manager failed: {e}")
            ctx = ""

        system_parts: List[str] = []
        # SystemMessage 仅承载 RAG 检索 / 历史记忆片段，不混入 user_input
        if memory_context:
            system_parts.append("【背景上下文与历史记忆】\n" + memory_context)
        if ctx:
            system_parts.append("【当前会话上下文】\n" + ctx)
        if system_parts:
            system_parts.append(
                "说明：以上仅是上下文参考。最终需求以 HumanMessage 中的「用户问题」为准。"
            )
        # 当没有上下文时，仍发送空 SystemMessage 以保留消息结构稳定
        system_content = "\n\n".join(system_parts) if system_parts else ""

        sys_msg = SystemMessage(content=system_content)
        # v2.1 — multimodal: 若当前 session 缓存了 vision blocks（图片 / OCR），
        # 把 HumanMessage.content 拼成 list[dict]（text + image_url）
        try:
            pending = self._consume_pending_vision_blocks()
        except Exception:
            pending = []
        if pending:
            content_list: List[Any] = [{"type": "text", "text": final_input}]
            for blk in pending:
                if not isinstance(blk, dict):
                    continue
                # blk 形如 {"type": "image_url", "image_url": {"url": "data:..."}}
                if blk.get("type") == "image_url" and isinstance(blk.get("image_url"), dict):
                    content_list.append({
                        "type": "image_url",
                        "image_url": {"url": blk["image_url"].get("url", "")},
                    })
                elif blk.get("type") == "image" and blk.get("data"):
                    mime = blk.get("mime_type") or "image/png"
                    content_list.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{blk['data']}"},
                    })
            hum_msg = HumanMessage(content=content_list)
        else:
            hum_msg = HumanMessage(content=final_input)
        return [sys_msg, hum_msg]

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

    def _record_assistant_turn(self, output: str, intent: str, importance: int) -> None:
        """记录助手输出到上下文与记忆，并按需触发整合。

        P2-W7：截断长度由 ``_resolve_memory_summary_chars()`` 决定（env > 类属性 > 500）。
        """
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

        # P2-W7：使用可配置截断长度（默认 500 chars，向后兼容）。
        max_chars = _resolve_memory_summary_chars()
        try:
            truncated = (
                output if len(output) <= max_chars else output[:max_chars] + "..."
            )
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
        """
        self._resolve_session(session_id)

        if not user_input or not user_input.strip():
            return "❌ 错误: 输入不能为空"

        logger.info(f"User input: {user_input}")

        err = self._ensure_agent_ready()
        if err:
            return err

        err = self._check_safety(user_input)
        if err:
            return err

        intent, importance = self._detect_intent(user_input)
        self._record_user_turn(user_input, intent, importance)

        # 构造 LangChain 1.x 兼容的输入
        enhanced_input = self._build_enhanced_input(user_input)
        final_input = self._apply_user_prompt_template(user_input, enhanced_input)
        # P0 重构：payload 改为结构化 Message list
        #   SystemMessage = 上下文 + 记忆（不含用户问题，避免指令污染）
        #   HumanMessage  = 最终 user_input（仅此）
        payload = {"messages": self._build_messages_payload(user_input, final_input)}

        # 准备降级时的素材（记忆 + 上下文片段）
        memory_hint = self._safe_memory_hint(user_input)
        context_hint = self._safe_context_hint()

        # 走容错栈（text_extractor 让 invoker 正确抽 AI 文本）
        result: InvokeResult = self.invoker.invoke(
            agent_factory=self._build_agent_for_provider,
            payload=payload,
            config={"configurable": {"thread_id": self.current_session_id}},
            session_id=self.current_session_id,
            memory_hint=memory_hint,
            context_hint=context_hint,
            user_input=user_input,
            text_extractor=self._extract_ai_text,
        )

        # 处理结果
        if result.success:
            # result.text 已经是 text_extractor 抽好的纯文本
            output = result.text
            self._record_assistant_turn(output, intent, importance)
            sanitized = self._sanitize_for_output(output)
            logger.info(
                f"[OK] provider={result.provider_used}/{result.model_used} "
                f"attempts={result.attempts} fallbacks={result.fallbacks_used}"
            )
            return sanitized

        # 降级路径：result.text 已是骨架回答
        logger.warning(
            f"[DEGRADED] trace_id={result.trace_id} "
            f"attempts={result.attempts} last_error={result.last_error_kind}"
        )
        self._record_assistant_turn(result.text, intent, importance)
        return result.text

    def _extract_ai_text_from_state(self, state: Any) -> str:
        """从 state dict 中抽取 AI 文本（备用辅助方法）。"""
        if state is None:
            return ""
        if isinstance(state, dict):
            return self._extract_ai_text(state)
        return ""

    def _safe_memory_hint(self, user_input: str) -> str:
        """降级时使用的记忆片段（最多 500 chars，失败返回空）。

        P1：同样追加 max_tokens=1000 预算，避免长对话下检索结果膨胀。
        """
        try:
            ctx = self.memory_store.get_context(
                user_input, self.current_session_id, max_tokens=1000
            )
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

        阶段 A3/A4/A5 改造 + P0-1 工具事件族补全：
        - 不再 yield 纯文本，而是 yield 一个结构化 dict（保持向后兼容：
          dict 里 `data` 字段是文本增量，前端可直接渲染）；
        - 事件类型：
            {"type": "start",     "data": ""}                       开始
            {"type": "safety",    "data": reason}                   输入被安全拦截
            {"type": "thinking",  "data": "..."}                    模型 CoT 段落（被前端折叠）
            {"type": "chunk",     "data": "..."}                    普通回答增量
            {"type": "tool_start","tool_call_id":..,"name":..,      工具开始执行（P0-1）
                            "args": {..}}
            {"type": "tool_result","tool_call_id":..,"result":..,   工具返回结果（P0-1）
                            "duration_ms": ..}
            {"type": "tool_end",  "tool_call_id":..,"status":..,    工具结束（P0-1）
                            "duration_ms": ..}
            {"type": "tool_call", "data": "", "name":..}            兼容事件（保留旧前端）
            {"type": "error",     "data": msg}                      错误
            {"type": "complete",  "data": full_output}              结束
        """
        self._resolve_session(session_id)

        # helper：避免每处都写 dict
        def _evt(type_: str, **kwargs) -> Dict[str, Any]:
            return {"type": type_, "data": kwargs.pop("data", ""), **kwargs}

        # P0-1：工具调用上下文（同一 tool_call_id 贯穿 tool_start → tool_result → tool_end）
        #  - active_tool_call_id  : 当前正在执行的工具 id（end 后置 None）
        #  - tool_start_at        : 工具开始时间戳（用于计算 duration_ms）
        #  - seen_tool_call_ids   : 已发射 tool_start 的 id 集合，避免重复
        #  - pending_tool_calls   : AIMessage.tool_calls → dict[id -> {name,args}] 的索引，
        #                           用于在 ToolMessage 到达时反查 name/args
        active_tool_call_id: Optional[str] = None
        tool_start_at: Optional[float] = None
        seen_tool_call_ids: set = set()
        pending_tool_calls: Dict[str, Dict[str, Any]] = {}

        if not user_input or not user_input.strip():
            yield _evt("error", data="❌ 错误: 输入不能为空")
            return

        logger.info(f"Streaming user input: {user_input}")

        yield _evt("start", data=user_input)

        err = self._ensure_agent_ready()
        if err:
            yield _evt("error", data=err)
            return

        err = self._check_safety(user_input)
        if err:
            # A5：安全拦截单独事件类型，方便前端高亮
            yield _evt("safety", data=err)
            return

        intent, importance = self._detect_intent(user_input)
        self._record_user_turn(user_input, intent, importance)

        enhanced_input = self._build_enhanced_input(user_input)
        final_input = self._apply_user_prompt_template(user_input, enhanced_input)
        # P0 重构：流式 payload 同样使用结构化 Message list
        payload = {"messages": self._build_messages_payload(user_input, final_input)}

        full_output = ""
        last_yielded_len = 0

        try:
            for event, payload_val in self.invoker.stream(
                agent_factory=self._build_agent_for_provider,
                payload=payload,
                config={"configurable": {"thread_id": self.current_session_id}},
                session_id=self.current_session_id,
            ):
                if event == "chunk":
                    # ------------------------------------------------------------------
                    # P0-1：工具事件族（tool_start / tool_result / tool_end）
                    #
                    # LangGraph 1.x 状态机里，"工具调用"分两个相邻消息：
                    #   1) AIMessage（带 tool_calls=[{id, name, args}]） → 工具"被请求"
                    #   2) ToolMessage（带 tool_call_id + content）        → 工具"已执行"
                    # 我们在每个 chunk 扫描最后一条消息：
                    #   - AIMessage：把每个新 id 注册进 pending_tool_calls，并 yield tool_start
                    #   - ToolMessage：用 tool_call_id 反查 name，从 pending 删掉，yield tool_result + tool_end
                    # tool_call_id 兜底：LangChain 在某些 path 下不生成 id → 用 uuid4().hex
                    # ------------------------------------------------------------------
                    try:
                        import uuid as _uuid

                        last_msg = None
                        if isinstance(payload_val, dict):
                            msgs = payload_val.get("messages")
                            if isinstance(msgs, list) and msgs:
                                last_msg = msgs[-1]
                        elif isinstance(payload_val, list) and payload_val:
                            last_msg = payload_val[-1]

                        if last_msg is not None:
                            # 1) AIMessage.tool_calls 触发 tool_start
                            tcs = getattr(last_msg, "tool_calls", None)
                            if tcs:
                                for tc in tcs:
                                    if not isinstance(tc, dict):
                                        continue
                                    tc_id = tc.get("id") or _uuid.uuid4().hex
                                    tc_name = tc.get("name") or ""
                                    tc_args = tc.get("args") or {}
                                    # 兼容：旧版可能没有 id，每次都生成新 id 会导致重复 start，
                                    # 这里用 (id + name) 去重。
                                    dedup_key = tc_id if tc.get("id") else f"{tc_name}#{len(seen_tool_call_ids)}"
                                    if dedup_key in seen_tool_call_ids:
                                        continue
                                    seen_tool_call_ids.add(dedup_key)
                                    pending_tool_calls[tc_id] = {
                                        "name": tc_name,
                                        "args": tc_args,
                                    }
                                    active_tool_call_id = tc_id
                                    tool_start_at = time.time()
                                    # P0-1：新事件 tool_start（前端用 tool_call_id 锁定卡片）
                                    yield _evt(
                                        "tool_start",
                                        tool_call_id=tc_id,
                                        name=tc_name,
                                        args=tc_args,
                                    )
                                    # 兼容：保留旧 tool_call 事件（不破坏旧前端）
                                    yield _evt("tool_call", data="", name=tc_name, tool_call_id=tc_id)

                            # 2) ToolMessage 触发 tool_result + tool_end
                            tc_id_attr = getattr(last_msg, "tool_call_id", None)
                            if tc_id_attr:
                                tc_meta = pending_tool_calls.pop(tc_id_attr, {})
                                tc_name = (
                                    tc_meta.get("name")
                                    or getattr(last_msg, "name", None)
                                    or "tool"
                                )
                                tc_result = getattr(last_msg, "content", "")
                                if not isinstance(tc_result, str):
                                    tc_result = str(tc_result)
                                duration_ms = (
                                    (time.time() - tool_start_at) * 1000.0
                                    if (tool_start_at is not None and active_tool_call_id == tc_id_attr)
                                    else None
                                )
                                yield _evt(
                                    "tool_result",
                                    tool_call_id=tc_id_attr,
                                    name=tc_name,
                                    result=tc_result,
                                    duration_ms=duration_ms,
                                )
                                yield _evt(
                                    "tool_end",
                                    tool_call_id=tc_id_attr,
                                    name=tc_name,
                                    status="success",
                                    duration_ms=duration_ms,
                                )
                                if active_tool_call_id == tc_id_attr:
                                    active_tool_call_id = None
                                    tool_start_at = None
                    except Exception as _te:
                        logger.debug(f"P0-1 tool event emit failed: {_te}")

                    # v2.2.1 — HITL 拦截事件：扫描当前 session 的待审批，发出 approval_required 帧
                    try:
                        from hitl_langgraph import emit_pending_to_sse, emit_timeout_events

                        for pending_evt in emit_pending_to_sse(self.current_session_id):
                            yield pending_evt
                        # v2.2.1 — 超时自动拒绝：扫描全局 pending 中的超时项
                        for timeout_evt in emit_timeout_events():
                            yield timeout_evt
                    except Exception as _he:
                        logger.debug(f"HITL pending scan failed: {_he}")

                    current_text = self._extract_ai_text(payload_val)
                    if not current_text:
                        continue

                    # A4：拆分 CoT 段（"## 思考 ##"）与回答段
                    delta_text = current_text[last_yielded_len:]
                    cot, answer = self._split_cot(current_text)
                    if cot and len(cot) > last_yielded_len:
                        # 简化策略：每次增量若仍包含"## 思考"前缀，则推一个 thinking 事件
                        think_inc = self._slice_thinking_increment(delta_text)
                        if think_inc:
                            yield _evt("thinking", data=think_inc)
                    if len(current_text) > last_yielded_len:
                        incremental = current_text[last_yielded_len:]
                        try:
                            sanitized_inc = self.security.sanitize_output(incremental)
                        except Exception:
                            sanitized_inc = incremental
                        if sanitized_inc:
                            yield _evt("chunk", data=sanitized_inc)
                        last_yielded_len = len(current_text)
                        full_output = current_text
                elif event == "error":
                    logger.warning(f"Stream chunk error: {payload_val}; trying next fallback")
                    yield _evt("error", data=str(payload_val))
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

        # 持久化前做一次最终安全检查（A5）
        try:
            output_check = self.security.check_output(full_output or "")
            if output_check.get("blocked"):
                logger.warning("Final output blocked by security")
                # 用 chunk 事件告知前端
                yield _evt("safety", data="❌ 输出被阻止: 包含敏感信息")
                return
        except Exception as e:
            logger.warning(f"Final safety check failed: {e}")

        self._record_assistant_turn(full_output, intent, importance)
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
        """P0-3：单一真相 → tools_registry.get_tool_names()。

        旧实现：`return [t.name for t in self.tools]`
        缺点：依赖 self.tools 字段是否已初始化；bind_tools_for_session 后会动态
              追加临时工具，列表波动 → 与前端 /api/tools 端点不同源。
        新实现：直接走 tools_registry，永远反映「运行时实际可用工具集合」。
        """
        try:
            from tools_registry import get_tool_names
            names = list(get_tool_names() or [])
            if names:
                return names
        except Exception as _e:
            logger.debug(f"get_tools_list via registry failed, fallback: {_e}")
        # fallback：旧行为（不破坏现有测试）
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