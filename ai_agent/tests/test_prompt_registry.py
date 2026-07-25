"""Prompt Registry 单元测试（阶段 A1/A2）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from prompt_registry import (
    PromptRegistry,
    PromptTemplate,
    get_prompt_registry,
    reset_prompt_registry,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_prompt_registry()
    yield
    reset_prompt_registry()


def test_registry_has_default_templates():
    reg = get_prompt_registry()
    tpl = reg.get_active_template("default")
    assert tpl is not None
    assert tpl.version == "2.0.0"  # 默认 v2 开启 CoT
    # cot 段非空
    assert "## 思考" in tpl.cot_instructions


def test_render_default_with_tools():
    reg = get_prompt_registry()
    out = reg.render(tools=["- a: A tool", "- b: B tool"])
    # 工具列表应当出现在输出
    assert "- a: A tool" in out
    assert "- b: B tool" in out
    # v2 默认带 CoT
    assert "## 思考" in out


def test_render_without_tools():
    reg = get_prompt_registry()
    out = reg.render(tools=None)
    assert "暂无可用工具" in out


def test_register_new_version():
    reg = get_prompt_registry()
    custom = PromptTemplate(
        name="custom",
        version="1.0.0",
        system_block="我是自定义助手。",
        tool_block_template="工具：\n{tools}",
        cot_instructions="",
        variables=["tools"],
    )
    reg.register(custom)
    out = reg.render(name="custom", tools=["- x: X"])
    assert "我是自定义助手" in out
    assert "- x: X" in out
    # active 默认指向刚注册的版本
    assert reg.get_active_template("custom").version == "1.0.0"


def test_rollback_to_older_version():
    reg = get_prompt_registry()
    assert reg.get_active_template("default").version == "2.0.0"
    # 回滚到 v1
    assert reg.rollback("default", "1.0.0") is True
    assert reg.get_active_template("default").version == "1.0.0"
    # 输出不再含 CoT
    out = reg.render(tools=["- z: Z"])
    assert "## 思考" not in out


def test_rollback_unknown_version():
    reg = get_prompt_registry()
    assert reg.rollback("default", "9.9.9") is False
    # active 保持不变
    assert reg.get_active_template("default").version == "2.0.0"


def test_rollback_unknown_template():
    reg = get_prompt_registry()
    assert reg.rollback("ghost", "1.0.0") is False


def test_list_templates():
    reg = get_prompt_registry()
    listed = reg.list_templates()
    names = [t["name"] for t in listed]
    assert "default" in names
    default_entry = next(t for t in listed if t["name"] == "default")
    assert default_entry["active_version"] == "2.0.0"
    versions = [v["version"] for v in default_entry["versions"]]
    assert "1.0.0" in versions and "2.0.0" in versions


def test_render_fallback_when_unknown_name():
    reg = get_prompt_registry()
    # 未知 name 应回退到 default
    out = reg.render(name="non-existent", tools=["- q: Q"])
    assert "- q: Q" in out


def test_role_block_template_with_variables():
    reg = get_prompt_registry()
    code = PromptTemplate(
        name="coder",
        version="1.0.0",
        system_block="你是代码助手。",
        role_block="语言: {language}",
        tool_block_template="工具：\n{tools}",
        variables=["language", "tools"],
    )
    reg.register(code)
    out = reg.render(name="coder", variables={"language": "Python"}, tools=["- x: X"])
    assert "语言: Python" in out
    assert "你是代码助手" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))