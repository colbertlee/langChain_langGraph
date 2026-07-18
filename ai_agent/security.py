import re
from typing import List, Dict, Callable


class SecurityModule:
    def __init__(self):
        self.guardrails: List[Dict[str, Callable]] = []
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
            r'\\.env',
            r'config\\.ini',
            r'database[_-]?url',
            r'postgres://',
            r'mysql://',
            r'sqlite://',
        ]
        self.dangerous_patterns = [
            r'rm -rf',
            r'del /f /s /q',
            r'format ',
            r'shutdown',
            r'restart',
            r'exec\(',
            r'eval\(',
            r'import os',
            r'import subprocess',
            r'subprocess\.',
            r'os\.system',
            r'os\.popen',
            r'__import__',
            r'open\(',
            r'write\(',
        ]

    def add_guardrail(self, name: str, func: Callable):
        self.guardrails.append({"name": name, "func": func})

    def check_input(self, user_input: str) -> Dict[str, bool]:
        result = {"blocked": False, "reason": ""}

        for pattern in self.dangerous_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                result["blocked"] = True
                result["reason"] = f"包含危险命令: {pattern}"
                return result

        for guardrail in self.guardrails:
            guard_result = guardrail["func"](user_input)
            if guard_result["blocked"]:
                return guard_result

        return result

    def check_output(self, output: str) -> Dict[str, bool]:
        result = {"blocked": False, "reason": ""}

        for pattern in self.sensitive_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                result["blocked"] = True
                result["reason"] = "输出包含敏感信息"
                return result

        return result

    def check_tool_execution(self, tool_name: str, parameters: Dict) -> Dict[str, bool]:
        dangerous_tools = ["write_file", "run_code", "delete_file"]

        if tool_name in dangerous_tools:
            return {
                "blocked": True,
                "reason": f"工具 '{tool_name}' 需要用户确认才能执行"
            }

        if tool_name == "read_file":
            file_path = parameters.get("file_path", "")
            if ".." in file_path or file_path.startswith("/"):
                return {
                    "blocked": True,
                    "reason": "不允许访问上级目录或绝对路径"
                }

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