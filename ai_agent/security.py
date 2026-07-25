import re
import ast
from typing import List, Dict, Callable, Tuple, Optional, Set


# 意图识别关键词表（基于中文常见用法 + 简单英文）
_INTENT_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("query", (
        "查询", "搜索", "找", "查", "看看", "告诉我", "是什么", "什么是",
        "多少", "哪里", "哪个", "how", "what", "where", "when", "which",
    )),
    ("compare", (
        "比较", "对比", "vs", "差别", "区别", "compare",
    )),
    ("analysis", (
        "分析", "预测", "趋势", "波动", "评估", "analyze", "predict",
    )),
    ("calculate", (
        "计算", "算", "等于", "=", "calculate",
    )),
    ("greeting", (
        "你好", "hi", "hello", "嗨", "在吗",
    )),
    ("command", (
        "执行", "运行", "写入", "创建", "删除", "run", "write", "create", "delete",
    )),
]


def _detect_intent(text: str) -> str:
    """根据关键词检测用户意图。返回意图标签；无法识别时返回 'general'。"""
    if not text:
        return "general"
    lowered = text.lower()
    for intent, keywords in _INTENT_RULES:
        for kw in keywords:
            if kw.lower() in lowered:
                return intent
    return "general"


# ============================================================
# Prompt Injection 检测（C5）
# ============================================================

# 经典 prompt injection 触发语（中文 + 英文常见模式）
# 设计要点：只在"看起来像指令"的语境里匹配，避免误报（聊天中提到这些词是允许的）
_INJECTION_PATTERNS: List[Tuple[str, str, float]] = [
    # (regex, label, severity)
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts?)", "ignore_previous", 0.95),
    (r"(disregard|forget)\s+(everything|all)", "disregard_all", 0.85),
    (r"system\s*:\s*you\s+are", "fake_system_role", 0.9),
    (r"<\|im_start\|>|<\|im_end\|>", "special_tokens", 0.99),
    (r"###\s*instruction\s*:", "instruction_marker", 0.7),
    (r"(reveal|show|print|output)\s+(your\s+)?(system\s+)?prompt", "prompt_leak", 0.9),
    (r"忽略.{0,8}(之前|以上|上文|先前).{0,12}(指令|提示|规则)", "ignore_zh", 0.95),
    (r"你是.{0,6}(新的|另一个|从现在开始)", "role_reassign_zh", 0.7),
    (r"(现在|从此).{0,8}(开始|之后).{0,6}(扮演|假装|成为)", "role_reassign_zh2", 0.7),
    (r"(jailbreak|DAN\s*mode|developer\s*mode)", "jailbreak_keyword", 0.9),
]

# 高危命令模式：仅在"代码/命令执行语境"下生效，避免误判普通文本
_DANGEROUS_CODE_PATTERNS: List[Tuple[str, str]] = [
    # (regex, label)
    (r"\brm\s+-rf\b", "rm_rf"),
    (r"\bdel\s+/f\s+/s\s+/q\b", "del_force"),
    (r"\bformat\s+[a-zA-Z]:", "format"),
    (r"\bshutdown\b", "shutdown"),
    (r"\brestart\b", "restart"),
    (r"subprocess\.(call|run|Popen)", "subprocess_call"),
    (r"\bos\.system\b|\bos\.popen\b", "os_call"),
    (r"\b__import__\b", "dunder_import"),
    (r"\beval\s*\(|\bexec\s*\(", "eval_exec"),
]


def detect_prompt_injection(text: str) -> Dict[str, object]:
    """检测用户输入是否含 prompt injection 攻击模式。

    Returns:
        {
            "is_injection": bool,         # 是否判定为攻击
            "confidence": float,          # 0~1，最高匹配项的 severity
            "matches": List[Dict],        # 命中的模式列表（label + 片段）
            "reason": str,                # 人类可读的拒绝原因
        }
    """
    if not text:
        return {"is_injection": False, "confidence": 0.0, "matches": [], "reason": ""}

    matches: List[Dict[str, str]] = []
    max_conf = 0.0
    for pattern, label, severity in _INJECTION_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            matches.append({"label": label, "match": m.group(0)[:80]})
            max_conf = max(max_conf, severity)

    is_injection = max_conf >= 0.7
    reason = f"检测到 prompt injection 模式: {matches[0]['label']}" if is_injection else ""
    return {
        "is_injection": is_injection,
        "confidence": max_conf,
        "matches": matches,
        "reason": reason,
    }


def detect_dangerous_code(text: str) -> Dict[str, object]:
    """检测文本是否含高危命令/代码模式（用于 content 过滤）。

    与 prompt_injection 的区别：
    - injection 检测"试图操纵 LLM"的语义
    - dangerous_code 检测"实际可能造成破坏"的代码/命令
    """
    if not text:
        return {"is_dangerous": False, "matches": []}
    matches: List[Dict[str, str]] = []
    for pattern, label in _DANGEROUS_CODE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            matches.append({"label": label, "match": m.group(0)[:80]})
    return {"is_dangerous": bool(matches), "matches": matches}


# ============================================================
# 路径安全校验（A2）
# ============================================================

# 不允许读写的位置（相对当前 cwd）
_FORBIDDEN_PATH_FRAGMENTS: Set[str] = {
    ".env", ".env.example",
    ".git", ".gitignore",
    ".ssh",
    "id_rsa", "id_ed25519",
    "node_modules",
    "__pycache__",
    ".venv", "venv",
    ".pytest_cache",
    ".coverage",
}

# 允许的后缀（白名单模式）
_ALLOWED_FILE_SUFFIXES: Set[str] = {
    ".txt", ".md", ".markdown", ".json", ".csv", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".log", ".html", ".xml", ".py", ".js",
    ".ts", ".tsx", ".jsx", ".css", ".sql", ".sh", ".png", ".jpg",
    ".jpeg", ".gif", ".svg", ".pdf",
}


def validate_safe_path(file_path: str, operation: str = "read") -> Tuple[bool, str]:
    """校验文件路径是否安全（不允许穿越/绝对路径/敏感位置/危险后缀）。

    Args:
        file_path: 待校验路径（相对路径）
        operation: 'read' / 'write' / 'delete'

    Returns:
        (ok, reason) —— ok=True 时 reason 为空
    """
    if not file_path:
        return False, "路径不能为空"
    # 1. 不允许绝对路径
    if os_isabs(file_path):
        return False, "不允许使用绝对路径"
    # 2. 不允许 ..
    parts = file_path.replace("\\", "/").split("/")
    if any(p == ".." for p in parts):
        return False, "不允许访问上级目录"
    # 3. 敏感位置
    lowered = file_path.lower()
    for frag in _FORBIDDEN_PATH_FRAGMENTS:
        if frag in lowered:
            return False, f"不允许访问敏感位置: {frag}"
    # 4. 后缀白名单（粗筛）
    suffix = ""
    if "." in parts[-1]:
        suffix = "." + parts[-1].rsplit(".", 1)[-1].lower()
    if suffix and suffix not in _ALLOWED_FILE_SUFFIXES:
        return False, f"不允许访问该类型文件: {suffix}"
    # 5. 删除操作额外检查：不能删根目录 + 必须有明确后缀
    if operation == "delete":
        if parts[-1] in {"", "."}:
            return False, "删除目标不明确"
    return True, ""


def os_isabs(p: str) -> bool:
    """最小化跨平台绝对路径判断（避免在 import 时强依赖 os）。"""
    if not p:
        return False
    if p.startswith("/") or p.startswith("\\"):
        return True
    # Windows: C:\ 或 D:/
    if len(p) >= 3 and p[1] == ":" and p[2] in ("/", "\\"):
        return True
    return False


# ============================================================
# AST 安全求值（A3）
# ============================================================

_SAFE_MATH_NAMES: Dict[str, object] = {
    # 基础数学
    "sin": __import__("math").sin,
    "cos": __import__("math").cos,
    "tan": __import__("math").tan,
    "sqrt": __import__("math").sqrt,
    "log": __import__("math").log,
    "log10": __import__("math").log10,
    "log2": __import__("math").log2,
    "exp": __import__("math").exp,
    "pow": pow,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "range": range,
    "pi": __import__("math").pi,
    "e": __import__("math").e,
    "tau": __import__("math").tau,
    "inf": float("inf"),
}

_SAFE_AST_NODES: Set[type] = {
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Call, ast.Name, ast.Load,
    ast.BoolOp, ast.And, ast.Or, ast.Compare, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Not, ast.Invert,
    ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Subscript,
    ast.IfExp, ast.Lambda, ast.Slice,
    # ast.Num / ast.Str / ast.Bytes / ast.NameConstant 已在 Python 3.8+ 合并为 ast.Constant
}


def safe_eval_expression(expr: str, extra_names: Optional[Dict[str, object]] = None) -> object:
    """AST 白名单的安全表达式求值。

    与 eval() 的区别：
    - 仅允许：数字 / 字符串常量 / 算术 / 比较 / 列表 / 元组 / 字典 / 函数调用（白名单内）
    - 禁止：Import / Attribute / Subscript（带 dunder）/ Starred / comprehension 中的循环变量
    - 函数调用名必须在白名单中（_SAFE_MATH_NAMES + extra_names）

    Raises:
        ValueError: 表达式不安全 / 含禁止节点
        SyntaxError: 语法错误
    """
    if not expr or not expr.strip():
        raise ValueError("表达式不能为空")
    tree = ast.parse(expr, mode="eval")

    # 节点白名单 + 函数名白名单
    allowed_func_names = set(_SAFE_MATH_NAMES.keys())
    if extra_names:
        allowed_func_names.update(extra_names.keys())

    for node in ast.walk(tree):
        # 禁止节点类型
        if type(node) not in _SAFE_AST_NODES:
            # 兼容旧版 Python：Number/Str 已在 _SAFE_AST_NODES 中通过 Constant 覆盖
            raise ValueError(f"不允许的语法节点: {type(node).__name__}")

        # 函数调用必须白名单
        if isinstance(node, ast.Call):
            func = node.func
            func_name: Optional[str] = None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                # 禁止任何属性访问（含 dunder）
                raise ValueError(f"不允许属性访问: {func.attr}")
            if func_name and func_name not in allowed_func_names:
                raise ValueError(f"禁止调用函数: {func_name}")

        # 禁止任何 dunder 常量（`__class__` 等）
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError(f"禁止访问 dunder: {node.id}")

    # 在严格受控命名空间求值
    safe_globals: Dict[str, object] = {"__builtins__": {}}
    safe_locals: Dict[str, object] = dict(_SAFE_MATH_NAMES)
    if extra_names:
        safe_locals.update(extra_names)

    return eval(compile(tree, "<safe_eval>", "eval"), safe_globals, safe_locals)  # noqa: S307


# ============================================================
# SecurityModule
# ============================================================

class SecurityModule:
    def __init__(self):
        self.guardrails: List[Dict[str, Callable]] = []
        # 敏感信息正则（输出脱敏用）
        self.sensitive_patterns = [
            r'password',
            r'api[_-]?key',
            r'secret[_-]?key',
            r'token',
            r'access[_-]?token',
            r'session[_-]?id',
            r'cookie',
            r'private[_-]?key',
            r'ssh[_-]?key',
            r'\.env',
            r'config\.ini',
            r'database[_-]?url',
            r'postgres://',
            r'mysql://',
            r'sqlite://',
        ]

    def add_guardrail(self, name: str, func: Callable):
        self.guardrails.append({"name": name, "func": func})

    # ---- 输入校验 ----

    def check_input(self, user_input: str) -> Dict[str, object]:
        """检查输入安全性，并附带意图检测 + prompt injection 检测。

        返回字段：
            - blocked: 是否被阻止
            - reason: 阻止原因
            - detected_intent: 检测到的用户意图标签
            - injection: prompt injection 检测结果（dict）
        """
        result: Dict[str, object] = {
            "blocked": False,
            "reason": "",
            "detected_intent": _detect_intent(user_input),
            "injection": detect_prompt_injection(user_input),
        }

        # 1. prompt injection 检测（高置信度 → 阻断）
        inj = result["injection"]
        if isinstance(inj, dict) and inj.get("is_injection"):
            result["blocked"] = True
            result["reason"] = (
                f"输入含 prompt injection 模式（置信度 {inj['confidence']:.2f}）: "
                f"{inj['reason']}"
            )
            return result

        # 2. 危险命令检测
        dangerous = detect_dangerous_code(user_input)
        if dangerous.get("is_dangerous"):
            result["blocked"] = True
            labels = ",".join(m["label"] for m in dangerous["matches"][:3])
            result["reason"] = f"输入含危险命令: {labels}"
            return result

        # 3. 用户自定义 guardrail
        for guardrail in self.guardrails:
            guard_result = guardrail["func"](user_input)
            if guard_result.get("blocked"):
                guard_result.setdefault("detected_intent", result["detected_intent"])
                guard_result.setdefault("injection", result["injection"])
                return guard_result

        return result

    # ---- 输出校验 ----

    def check_output(self, output: str) -> Dict[str, bool]:
        result: Dict[str, bool] = {"blocked": False, "reason": ""}

        for pattern in self.sensitive_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                result["blocked"] = True
                result["reason"] = "输出包含敏感信息"
                return result

        return result

    # ---- 工具执行校验 ----

    def check_tool_execution(self, tool_name: str, parameters: Dict) -> Dict[str, bool]:
        dangerous_tools = ["write_file", "delete_file", "run_code"]

        if tool_name in dangerous_tools:
            # 写/删/执行类工具：路径校验（如有 file_path 参数）
            file_path = parameters.get("file_path")
            if isinstance(file_path, str) and file_path:
                op = "write" if tool_name == "write_file" else (
                    "delete" if tool_name == "delete_file" else "read"
                )
                ok, reason = validate_safe_path(file_path, operation=op)
                if not ok:
                    return {"blocked": True, "reason": reason}

            return {
                "blocked": True,
                "reason": f"工具 '{tool_name}' 需要用户确认才能执行",
            }

        if tool_name == "read_file":
            file_path = parameters.get("file_path", "")
            if isinstance(file_path, str) and file_path:
                ok, reason = validate_safe_path(file_path, operation="read")
                if not ok:
                    return {"blocked": True, "reason": reason}

        # run_code：先做语法白名单检查
        if tool_name == "run_code":
            code = parameters.get("code", "")
            if isinstance(code, str) and code:
                try:
                    safe_eval_expression(code)
                except Exception as e:
                    return {"blocked": True, "reason": f"代码未通过安全检查: {e}"}

        return {"blocked": False, "reason": ""}

    def sanitize_output(self, output: str) -> str:
        for pattern in self.sensitive_patterns:
            output = re.sub(pattern, "[REDACTED]", output, flags=re.IGNORECASE)
        return output


_security_instance = None


def get_security_instance() -> SecurityModule:
    global _security_instance
    if _security_instance is None:
        _security_instance = SecurityModule()
    return _security_instance


def set_security_instance(instance: SecurityModule):
    global _security_instance
    _security_instance = instance