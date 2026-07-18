import re

class SecurityModule:
    def __init__(self):
        self.sensitive = [r"password", r"api[_-]?key", r"token", r"secret"]
        self.dangerous = [r"rm -rf", r"exec\(", r"eval\(", r"import os", r"subprocess"]

    def check_input(self, text):
        for p in self.dangerous:
            if re.search(p, text, re.I): return {"blocked": True, "reason": p}
        return {"blocked": False}

    def sanitize_output(self, text):
        for p in self.sensitive: text = re.sub(p, "[REDACTED]", text, flags=re.I)
        return text

_security = None
def set_security_instance(i): global _security; _security = i
def get_security_instance(): global _security; return _security or SecurityModule()