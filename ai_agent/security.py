import re

class SecurityModule:
    def __init__(self):
        self.sensitive = [r"password", r"api[_-]?key", r"token", r"secret"]
    
    def check_input(self, text):
        return {"blocked": True, "reason": p} if any(re.search(p, text, re.I) for p in [r"rm -rf", r"exec\(", r"eval\("]) else {"blocked": False}
    
    def sanitize_output(self, text):
        for p in self.sensitive: text = re.sub(p, "[REDACTED]", text, flags=re.I)
        return text

_security = None
def set_security_instance(i): global _security; _security = i
def get_security_instance(): global _security; return _security or SecurityModule()