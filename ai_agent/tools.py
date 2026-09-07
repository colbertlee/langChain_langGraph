import os

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
    return _rag_instance





@tool
def query_knowledge_base(query: str) -> str:
    """
    查询知识库文档
    
    参数:
        query: 查询问题
    """
    rag = get_rag_instance()
    if not rag:
        return "知识库未初始化，请先加载文档"
    
    return rag.query(query)


@tool
def load_knowledge_base(file_path: str) -> str:
    """
    加载文档到知识库
    
    参数:
        file_path: 文档文件路径（txt格式）
    """
    rag = get_rag_instance()
    if not rag:
        return "知识库未初始化"
    
    if not os.path.exists(file_path):
        return f"文件不存在: {file_path}"
    
    try:
        success = rag.load_documents([file_path])
        return "文档加载成功" if success else "文档加载失败"
    except Exception as e:
        return f"加载失败: {str(e)}"


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
    # 只保留真正属于「Agent 该做的事」的工具。
    # 已剔除玩具/演示类：get_current_time / calculate / get_weather /
    #                     search_web / github_search / generate_chart /
    #                     get_etf_* / compare_etfs / etf_analysis
    return [
        query_knowledge_base,
        load_knowledge_base,
        read_file,
        write_file,
        delete_file,
        list_files,
        run_code,
    ]