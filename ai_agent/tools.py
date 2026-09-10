import os
import warnings
from typing import Optional

from langchain_core.tools import tool

from security import (
    safe_eval_expression,
    validate_safe_path,
    get_security_instance,
)

_rag_instance = None


def set_rag_instance(rag):
    global _rag_instance
    _rag_instance = rag


def get_rag_instance():
    """P0-4 — 旧 RAG 单例访问器（已迁移至 rag_service.get_rag_service()）。

    ⚠️ Deprecated：保留仅为向后兼容 v1 路径与早期测试；
    新代码请使用 `rag_service.get_rag_service().search(session_id, query)`。
    计划在 v2.5 移除。
    """
    warnings.warn(
        "tools.get_rag_instance() 已废弃，请改用 rag_service.get_rag_service()。"
        "旧路径走的是全局共享的 RAGModule（无 session 隔离），新链路支持 per-session Chroma KB。",
        DeprecationWarning,
        stacklevel=2,
    )
    return _rag_instance





@tool
def query_knowledge_base(
    query: str,
    *,
    config: Optional[dict] = None,
    **kwargs,
) -> str:
    """
    查询知识库文档（P0-4：已迁移到 rag_service 单一链路）

    参数:
        query: 查询问题
        config: LangGraph RunnableConfig（自动从 configurable.thread_id 取 session_id）
        kwargs: 透传 session_id / thread_id（StructuredTool 调用形式）

    返回:
        Markdown 文本：检索结果列表（带 file_name / chunk_id / score）
        若未命中：'未找到与 xxx 相关的知识库内容。'
    """
    from rag_service import _extract_session_id, get_rag_service
    sid = _extract_session_id(kwargs=kwargs, config=config)
    if not query or not str(query).strip():
        return "❌ 查询语句不能为空"

    try:
        svc = get_rag_service()
        results = svc.search(session_id=sid, query=str(query), top_k=3, min_score=0.0)
    except Exception as e:
        # P0-4：检索失败时返回可读错误（不让 ReAct loop 抛异常死掉）
        return f"❌ 知识库检索失败: {e}"

    if not results:
        return f"[query_knowledge_base] 未找到与 '{query}' 相关的知识库内容。"

    # 复用 v21_tools 的 Markdown 渲染（保持与 knowledge_search 一致输出风格）
    try:
        from v21_tools.rag_tool import render_results_markdown
        return render_results_markdown(results, query=str(query))
    except Exception:
        # 降级：自己手写 Markdown
        lines = [f"[query_knowledge_base] 检索到 {len(results)} 条相关片段："]
        for i, r in enumerate(results, 1):
            file_name = r.get("file_name") or r.get("file_id") or "unknown"
            score = r.get("score", 0.0)
            chunk_id = r.get("chunk_id", -1)
            text = (r.get("text") or "").strip()
            if len(text) > 800:
                text = text[:800] + "..."
            lines.append(
                f"\n--- [{i}] {file_name} · chunk#{chunk_id} · score={float(score):.3f} ---\n{text}"
            )
        return "\n".join(lines)


@tool
def load_knowledge_base(
    file_path: str,
    *,
    config: Optional[dict] = None,
    **kwargs,
) -> str:
    """
    加载文档到知识库（P0-4：已迁移到 rag_service.RAGService.index_file）

    参数:
        file_path: 文档文件路径（txt/pdf/docx/md/csv 都可，已注册到 file_parser）
        config: LangGraph RunnableConfig（自动从 configurable.thread_id 取 session_id）
        kwargs: 透传 session_id / thread_id

    返回:
        '✅ 文档已索引: xxx, chunks=N' 或错误说明
    """
    from rag_service import _extract_session_id, get_rag_service

    sid = _extract_session_id(kwargs=kwargs, config=config)
    if not os.path.exists(file_path):
        return f"❌ 文件不存在: {file_path}"

    # 安全校验：与 read_file 一致，禁止敏感路径
    ok, reason = validate_safe_path(file_path, operation="read")
    if not ok:
        return f"❌ {reason}"

    # file_id 约定：用文件名（无后缀）
    file_id = os.path.splitext(os.path.basename(file_path))[0]

    try:
        svc = get_rag_service()
        result = svc.index_file(
            session_id=sid,
            file_id=file_id,
            file_name=os.path.basename(file_path),
        )
    except Exception as e:
        return f"❌ 加载失败: {e}"

    if not result or not result.get("success"):
        err = (result or {}).get("error", "unknown")
        return f"❌ 文档加载失败: {err}"

    return (
        f"✅ 文档已索引: {result.get('file_name', file_path)}, "
        f"chunks={result.get('chunk_count', 0)}, "
        f"text_length={result.get('text_length', 0)}"
    )


@tool
def read_file(file_path: str) -> str:
    """
    读取文件内容

    参数:
        file_path: 文件路径（相对路径，不允许访问上级目录 / 绝对路径 / 敏感位置）

    安全：使用 security.validate_safe_path，禁止 .env / .git / .ssh / node_modules 等敏感路径
    """
    ok, reason = validate_safe_path(file_path, operation="read")
    if not ok:
        return f"❌ {reason}"

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if len(content) > 5000:
                return content[:5000] + "\n...（文件过长，只显示前5000字符）"
            return content
    except FileNotFoundError:
        return f"❌ 文件不存在: {file_path}"
    except PermissionError:
        return f"❌ 没有权限读取文件: {file_path}"
    except Exception as e:
        return f"❌ 读取错误: {str(e)}"


@tool
def write_file(file_path: str, content: str, append: bool = False) -> str:
    """
    写入文件内容

    参数:
        file_path: 文件路径（相对路径）
        content: 要写入的内容
        append: 是否追加写入（默认False）
    """
    ok, reason = validate_safe_path(file_path, operation="write")
    if not ok:
        return f"❌ {reason}"

    try:
        mode = 'a' if append else 'w'
        with open(file_path, mode, encoding='utf-8') as f:
            f.write(content)
        action = "追加" if append else "写入"
        return f"✅ 文件 {file_path} {action}成功"
    except PermissionError:
        return f"❌ 没有权限写入文件: {file_path}"
    except Exception as e:
        return f"❌ 写入错误: {str(e)}"


@tool
def delete_file(file_path: str) -> str:
    """
    删除文件（谨慎使用）

    参数:
        file_path: 待删除文件路径（相对路径）

    安全：使用 validate_safe_path 拦截敏感路径（.env / .git / .ssh / node_modules 等）；
    不会删除根目录或空目录条目。
    """
    ok, reason = validate_safe_path(file_path, operation="delete")
    if not ok:
        return f"❌ {reason}"

    if not os.path.exists(file_path):
        return f"❌ 文件不存在: {file_path}"
    if os.path.isdir(file_path):
        return f"❌ 不允许删除目录: {file_path}"

    try:
        os.remove(file_path)
        return f"✅ 文件 {file_path} 已删除"
    except PermissionError:
        return f"❌ 没有权限删除文件: {file_path}"
    except Exception as e:
        return f"❌ 删除错误: {str(e)}"


@tool
def list_files(directory: str = ".") -> str:
    """
    列出目录下的文件

    参数:
        directory: 目录路径（默认当前目录）
    """
    ok, reason = validate_safe_path(directory, operation="read")
    if not ok:
        return f"❌ {reason}"

    try:
        files = os.listdir(directory)
        if not files:
            return "目录为空"
        return "\n".join(files)
    except FileNotFoundError:
        return f"❌ 目录不存在: {directory}"
    except PermissionError:
        return f"❌ 没有权限访问目录: {directory}"
    except Exception as e:
        return f"❌ 列出文件错误: {str(e)}"


@tool
def run_code(code: str) -> str:
    """
    执行简单的 Python 代码（仅安全表达式）

    参数:
        code: Python 表达式（不允许 import、exec、eval、属性访问等危险操作）

    安全：使用 AST 白名单求值（security.safe_eval_expression）。
    与 calculate 不同：run_code 接受任意数学表达式并把结果当字符串返回。
    """
    try:
        result = safe_eval_expression(code)
        return f"✅ 执行结果: {result}"
    except ValueError as e:
        return f"❌ {e}"
    except SyntaxError:
        return "❌ 语法错误"
    except Exception as e:
        return f"❌ 执行错误: {str(e)}"











def get_all_tools():
    """⚠️ Deprecated（v2.4 起）：请改用 `tools_registry.resolve_tools_for_runtime()`。

    历史：
      - v1 时代顶层 tools.py 的 7 个细粒度工具（query_kb / load_kb / read_file / ...）；
      - v2.10 起 LangGraph 主 agent 已迁移到 v2_slim.tools_v2（6 个复合工具）；
        本入口实际不再被 agent.py / app.py 调用，但保留以兼容早期测试与脚本。

    新代码：
      - 想拿「运行时实际可用工具」→ `tools_registry.resolve_tools_for_runtime()`
      - 想拿「前端 /api/tools 契约」→ `tools_registry.get_tool_specs()`
    """
    warnings.warn(
        "tools.get_all_tools() 已废弃（v2.4），请改用 tools_registry.resolve_tools_for_runtime()。",
        DeprecationWarning,
        stacklevel=2,
    )
    return [
        query_knowledge_base,
        load_knowledge_base,
        read_file,
        write_file,
        delete_file,
        list_files,
        run_code,
    ]