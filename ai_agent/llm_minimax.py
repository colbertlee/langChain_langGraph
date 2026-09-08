"""
llm_minimax - MiniMax 直连的薄包装 ChatModel（绕过 LangChain ChatOpenAI）

背景：
- LangChain ChatOpenAI 在 MiniMax 上有不可预测的慢响应（HTTP 200 OK 60s 内收到，
  但 LangChain 包装层到 _generate 返回之间又拖延 30s+），导致 invoke_timeout 触发。
- 直连 httpx 调用 MiniMax 5KB payload 仅 1.5-3.6s。
- 本模块用 httpx.Client 直连，提供 BaseChatModel 子类，签名/接口与 ChatOpenAI 一致，
  满足 LangGraph create_agent 的需求。

用法：
    from llm_minimax import ChatMiniMax
    llm = ChatMiniMax(model="MiniMax-M2.7", api_key=..., temperature=0.7)
    llm_with_tools = llm.bind_tools([my_tool])
    result = llm_with_tools.invoke([HumanMessage(content="...")])

兼容：
- create_agent(model=self, tools=..., system_prompt=..., checkpointer=...)
- tools 参数通过 bind_tools 注入；_generate 时从 kwargs["tools"] 取出
- 返回 AIMessage.content 字符串 + tool_calls（LangChain 标准结构）
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field

logger = logging.getLogger(__name__)


# 默认 base_url（OpenAI 兼容协议）
DEFAULT_BASE_URL = "https://api.minimax.chat/v1"

# httpx 超时：connect 10s, read 90s（MiniMax 偶尔 30s+ 也兜得住）
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0)


def _convert_message_to_oai(msg: BaseMessage) -> Dict[str, Any]:
    """把 LangChain BaseMessage 转成 OpenAI chat.completions 格式。"""
    role = msg.type
    # LangChain 的 type: human/ai/system/tool
    if role == "human":
        role = "user"
    elif role == "ai":
        role = "assistant"
    elif role == "system":
        role = "system"
    elif role == "tool":
        role = "tool"
    else:
        role = "user"

    out: Dict[str, Any] = {"role": role}

    content = msg.content
    if isinstance(content, str):
        out["content"] = content
    elif isinstance(content, list):
        # 多模态 blocks 暂简单拼字符串（MiniMax 暂未支持图片）
        out["content"] = "".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in content
        )
    else:
        out["content"] = str(content)

    # assistant 消息带 tool_calls（多轮 tool calling 需要）
    if role == "assistant":
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            out["tool_calls"] = [
                {
                    "id": tc.get("id") or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": (
                            tc["args"]
                            if isinstance(tc["args"], str)
                            else json.dumps(tc["args"], ensure_ascii=False)
                        ),
                    },
                }
                for i, tc in enumerate(tool_calls)
            ]

    # tool 消息需要 tool_call_id
    if role == "tool":
        tool_call_id = getattr(msg, "tool_call_id", None)
        if tool_call_id:
            out["tool_call_id"] = tool_call_id

    return out


def _convert_tools_to_oai(tools: Sequence[Any]) -> List[Dict[str, Any]]:
    """把 LangChain tools (BaseTool / dict / callable) 转成 OpenAI tools 格式。"""
    out: List[Dict[str, Any]] = []
    for t in tools:
        if isinstance(t, BaseTool):
            # 从 BaseTool 提取 name/description/args_schema
            try:
                params = (
                    t.args_schema.model_json_schema()
                    if t.args_schema is not None
                    else {"type": "object", "properties": {}}
                )
            except Exception:
                params = {"type": "object", "properties": {}}
            out.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": (t.description or "").strip(),
                    "parameters": params,
                },
            })
        elif isinstance(t, dict):
            # 已经是 OAI 格式
            if "type" in t and "function" in t:
                out.append(t)
            else:
                out.append({"type": "function", "function": t})
        else:
            # callable：用 LangChain 的 convert
            try:
                from langchain_core.utils.function_calling import convert_to_openai_function
                fn = convert_to_openai_function(t)
                out.append({"type": "function", "function": fn})
            except Exception as e:
                logger.warning(f"tool convert failed: {e}, skip {t}")
    return out


def _parse_oai_response(data: Dict[str, Any]) -> AIMessage:
    """把 MiniMax / OpenAI chat.completions 响应转成 AIMessage。"""
    choices = data.get("choices") or []
    if not choices:
        raise ValueError(f"no choices in response: {json.dumps(data)[:500]}")

    msg = choices[0].get("message") or {}
    content = msg.get("content") or ""
    tool_calls_raw = msg.get("tool_calls") or []

    tool_calls = []
    for tc in tool_calls_raw:
        fn = tc.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        # arguments 可能是 str 或 dict
        if isinstance(args_raw, dict):
            args = args_raw
        else:
            try:
                args = json.loads(args_raw)
            except Exception:
                args = {"_raw": args_raw}
        tool_calls.append({
            "id": tc.get("id") or "",
            "name": fn.get("name") or "",
            "args": args,
            "type": "tool_call",
        })

    return AIMessage(
        content=content if isinstance(content, str) else str(content),
        tool_calls=tool_calls,
        response_metadata={
            "model": data.get("model"),
            "usage": data.get("usage") or {},
            "finish_reason": choices[0].get("finish_reason"),
            "id": data.get("id"),
        },
    )


class ChatMiniMax(BaseChatModel):
    """MiniMax 直连的 ChatModel（OpenAI 兼容协议）。

    字段命名参考 langchain_openai.ChatOpenAI 保持兼容。
    """

    model: str = Field(default="MiniMax-M2.7", alias="model_name")
    api_key: str = Field(default="")
    base_url: str = Field(default=DEFAULT_BASE_URL)
    temperature: float = Field(default=0.7)
    max_tokens: Optional[int] = Field(default=None)
    timeout: float = Field(default=90.0, description="read timeout seconds")

    class Config:
        """Pydantic v1 config (BaseChatModel 内部仍是 v1 BaseModel)。"""
        arbitrary_types_allowed = True
        populate_by_name = True

    @property
    def _llm_type(self) -> str:
        return "minimax-chat"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
        }

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """Bind tools to this ChatModel.

        返回的 Runnable 在 invoke 时会把 tools 作为 kwarg 传给 _generate。
        """
        # 把 tools 和 tool_choice 一起 bind
        bind_kwargs: Dict[str, Any] = dict(kwargs)
        bind_kwargs["tools"] = list(tools)
        if tool_choice is not None:
            bind_kwargs["tool_choice"] = tool_choice
        return self.bind(**bind_kwargs)

    def _http_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=10.0, read=self.timeout, write=10.0, pool=10.0),
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        import time as _t
        _t0 = _t.time()
        # 1. 组装 OpenAI 格式 messages
        oai_messages = [_convert_message_to_oai(m) for m in messages]
        _t1 = _t.time()

        # 2. payload
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if stop:
            payload["stop"] = stop

        # 3. tools（bind_tools 时通过 kwargs["tools"] 传入）
        tools_kw = kwargs.get("tools")
        if tools_kw:
            payload["tools"] = _convert_tools_to_oai(tools_kw)
        # tool_choice 一般不指定，让模型自决

        # 4. HTTP 调用
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = "/chat/completions"

        _t2 = _t.time()
        with self._http_client() as client:
            try:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500] if e.response else ""
                raise RuntimeError(
                    f"MiniMax HTTP {e.response.status_code if e.response else '?'}: {body}"
                ) from e
            except httpx.TimeoutException as e:
                raise TimeoutError(f"MiniMax invoke timeout after {self.timeout}s") from e
            except Exception as e:
                raise RuntimeError(f"MiniMax invoke failed: {e}") from e
        _t3 = _t.time()

        # 5. 解析响应
        ai_msg = _parse_oai_response(data)
        _t4 = _t.time()
        logger.info(
            f"[ChatMiniMax] msgs_convert={(_t1-_t0)*1000:.0f}ms "
            f"http_post={(_t3-_t2)*1000:.0f}ms "
            f"parse={(_t4-_t3)*1000:.0f}ms "
            f"total={(_t4-_t0)*1000:.0f}ms"
        )
        generation = ChatGeneration(message=ai_msg)
        return ChatResult(generations=[generation])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        # 简单走 httpx.AsyncClient
        oai_messages = [_convert_message_to_oai(m) for m in messages]
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if stop:
            payload["stop"] = stop
        tools_kw = kwargs.get("tools")
        if tools_kw:
            payload["tools"] = _convert_tools_to_oai(tools_kw)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=10.0, read=self.timeout, write=10.0, pool=10.0),
        ) as client:
            resp = await client.post("/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        ai_msg = _parse_oai_response(data)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])
