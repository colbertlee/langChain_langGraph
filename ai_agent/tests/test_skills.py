"""skills.py 单元测试。

覆盖：Skill / SkillResult dataclass、SkillRegistry 单例、SkillManager 内置技能、execute_skill、get_skill_prompt 等。
"""
import pytest
from unittest.mock import MagicMock, patch
import asyncio

import skills
from skills import (
    Skill,
    SkillResult,
    SkillRegistry,
    SkillManager,
    get_skill_manager,
)


# ─────────────────── Skill dataclass ───────────────────


class TestSkillDataclass:

    def test_skill_creation(self):
        skill = Skill(
            name="test_skill",
            description="Test description",
            category="test",
            prompt_template="Hello {name}",
            tools=["tool1", "tool2"],
        )
        assert skill.name == "test_skill"
        assert skill.description == "Test description"
        assert skill.category == "test"
        assert skill.prompt_template == "Hello {name}"
        assert skill.tools == ["tool1", "tool2"]
        assert skill.enabled is True
        assert skill.metadata == {}

    def test_skill_with_metadata(self):
        skill = Skill(
            name="x",
            description="x",
            category="x",
            prompt_template="x",
            tools=[],
            metadata={"version": "1.0", "author": "test"},
        )
        assert skill.metadata["version"] == "1.0"
        assert skill.metadata["author"] == "test"

    def test_skill_disabled_by_default_disabled(self):
        skill = Skill(
            name="x",
            description="x",
            category="x",
            prompt_template="x",
            tools=[],
            enabled=False,
        )
        assert skill.enabled is False


# ─────────────────── SkillResult dataclass ───────────────────


class TestSkillResult:

    def test_result_success(self):
        result = SkillResult(
            skill_name="x",
            success=True,
            content="output",
        )
        assert result.skill_name == "x"
        assert result.success is True
        assert result.content == "output"
        assert result.metadata == {}
        assert result.error is None

    def test_result_failure(self):
        result = SkillResult(
            skill_name="x",
            success=False,
            content="",
            error="something went wrong",
        )
        assert result.success is False
        assert result.error == "something went wrong"

    def test_result_with_metadata(self):
        result = SkillResult(
            skill_name="x",
            success=True,
            content="out",
            metadata={"prompt": "p", "tools": ["a"]},
        )
        assert result.metadata["prompt"] == "p"
        assert result.metadata["tools"] == ["a"]


# ─────────────────── SkillRegistry 单例 ───────────────────


@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试前清空 registry。"""
    SkillRegistry._instance = None
    SkillRegistry._skills = {}
    yield
    SkillRegistry._instance = None
    SkillRegistry._skills = {}


class TestSkillRegistry:

    def test_singleton(self):
        r1 = SkillRegistry()
        r2 = SkillRegistry()
        assert r1 is r2

    def test_register_and_get(self):
        registry = SkillRegistry()
        skill = Skill(name="x", description="x", category="c", prompt_template="x", tools=[])
        registry.register(skill)
        assert registry.get("x") is skill

    def test_get_nonexistent_returns_none(self):
        registry = SkillRegistry()
        assert registry.get("nonexistent") is None

    def test_list_all(self):
        registry = SkillRegistry()
        skill1 = Skill(name="a", description="a", category="cat1", prompt_template="a", tools=[])
        skill2 = Skill(name="b", description="b", category="cat2", prompt_template="b", tools=[])
        registry.register(skill1)
        registry.register(skill2)
        all_skills = registry.list_all()
        assert len(all_skills) == 2
        assert skill1 in all_skills
        assert skill2 in all_skills

    def test_list_by_category(self):
        registry = SkillRegistry()
        s1 = Skill(name="a", description="a", category="cat1", prompt_template="a", tools=[])
        s2 = Skill(name="b", description="b", category="cat1", prompt_template="b", tools=[])
        s3 = Skill(name="c", description="c", category="cat2", prompt_template="c", tools=[])
        registry.register(s1)
        registry.register(s2)
        registry.register(s3)
        cat1 = registry.list_by_category("cat1")
        assert len(cat1) == 2
        assert s3 not in cat1

    def test_list_enabled(self):
        registry = SkillRegistry()
        s1 = Skill(name="a", description="a", category="c", prompt_template="a", tools=[], enabled=True)
        s2 = Skill(name="b", description="b", category="c", prompt_template="b", tools=[], enabled=False)
        registry.register(s1)
        registry.register(s2)
        enabled = registry.list_enabled()
        assert len(enabled) == 1
        assert s1 in enabled
        assert s2 not in enabled

    def test_enable(self):
        registry = SkillRegistry()
        skill = Skill(name="a", description="a", category="c", prompt_template="a", tools=[], enabled=False)
        registry.register(skill)
        assert registry.enable("a") is True
        assert skill.enabled is True

    def test_enable_nonexistent(self):
        registry = SkillRegistry()
        assert registry.enable("nonexistent") is False

    def test_disable(self):
        registry = SkillRegistry()
        skill = Skill(name="a", description="a", category="c", prompt_template="a", tools=[], enabled=True)
        registry.register(skill)
        assert registry.disable("a") is True
        assert skill.enabled is False

    def test_disable_nonexistent(self):
        registry = SkillRegistry()
        assert registry.disable("nonexistent") is False


# ─────────────────── SkillManager ───────────────────


class TestSkillManager:

    def test_init_loads_builtin_skills(self):
        mgr = SkillManager()
        all_skills = mgr.registry.list_all()
        assert len(all_skills) >= 5   # 至少有 5 个内置技能

    def test_builtin_deep_research(self):
        mgr = SkillManager()
        skill = mgr.registry.get("deep_research")
        assert skill is not None
        assert skill.category == "research"
        assert "search_web" in skill.tools

    def test_builtin_code_documentation(self):
        mgr = SkillManager()
        skill = mgr.registry.get("code_documentation")
        assert skill is not None
        assert skill.category == "development"
        assert "read_file" in skill.tools

    def test_builtin_ppt_generation(self):
        mgr = SkillManager()
        skill = mgr.registry.get("ppt_generation")
        assert skill is not None
        assert skill.category == "productivity"

    def test_builtin_paper_review(self):
        mgr = SkillManager()
        skill = mgr.registry.get("paper_review")
        assert skill is not None
        assert skill.category == "academic"

    def test_builtin_chart_visualization(self):
        mgr = SkillManager()
        skill = mgr.registry.get("chart_visualization")
        assert skill is not None
        assert skill.category == "data"
        assert "generate_chart" in skill.tools

    def test_all_builtin_enabled(self):
        mgr = SkillManager()
        for skill in mgr.registry.list_all():
            assert skill.enabled is True


# ─────────────────── execute_skill (async) ───────────────────


class TestExecuteSkill:

    @pytest.mark.asyncio
    async def test_execute_existing_skill(self):
        mgr = SkillManager()
        result = await mgr.execute_skill("deep_research", {"topic": "AI"})
        assert result.success is True
        assert "prompt" in result.metadata
        assert result.metadata["required_tools"] == ["search_web", "query_knowledge_base"]
        assert "AI" in result.metadata["prompt"]

    @pytest.mark.asyncio
    async def test_execute_nonexistent_skill(self):
        mgr = SkillManager()
        result = await mgr.execute_skill("nonexistent_xyz", {})
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_execute_disabled_skill(self):
        mgr = SkillManager()
        mgr.registry.disable("deep_research")
        result = await mgr.execute_skill("deep_research", {"topic": "AI"})
        assert result.success is False
        assert "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_skill_missing_context_key(self):
        mgr = SkillManager()
        # deep_research 需要 {topic}，不传会 KeyError
        result = await mgr.execute_skill("deep_research", {})
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_execute_ppt_skill(self):
        mgr = SkillManager()
        result = await mgr.execute_skill(
            "ppt_generation",
            {"topic": "AI Agent", "audience": "engineers"}
        )
        assert result.success is True
        assert "AI Agent" in result.metadata["prompt"]
        assert "engineers" in result.metadata["prompt"]


# ─────────────────── get_skill_prompt ───────────────────


class TestGetSkillPrompt:

    def test_get_prompt_success(self):
        mgr = SkillManager()
        prompt = mgr.get_skill_prompt("ppt_generation", topic="AI", audience="devs")
        assert prompt is not None
        assert "AI" in prompt
        assert "devs" in prompt

    def test_get_prompt_nonexistent(self):
        mgr = SkillManager()
        assert mgr.get_skill_prompt("nonexistent") is None

    def test_get_prompt_missing_key(self):
        mgr = SkillManager()
        # 缺 topic → KeyError → None
        result = mgr.get_skill_prompt("ppt_generation")
        assert result is None

    def test_get_prompt_partial_keys(self):
        mgr = SkillManager()
        # 只给 topic
        prompt = mgr.get_skill_prompt("deep_research", topic="LLM")
        assert prompt is not None
        assert "LLM" in prompt


# ─────────────────── list_skill_categories ───────────────────


class TestListCategories:

    def test_list_categories(self):
        mgr = SkillManager()
        categories = mgr.list_skill_categories()
        assert isinstance(categories, list)
        assert "research" in categories
        assert "development" in categories
        assert "academic" in categories
        assert "data" in categories
        assert "productivity" in categories

    def test_list_categories_no_duplicates(self):
        mgr = SkillManager()
        categories = mgr.list_skill_categories()
        assert len(categories) == len(set(categories))


# ─────────────────── get_skill_info ───────────────────


class TestGetSkillInfo:

    def test_get_info_success(self):
        mgr = SkillManager()
        info = mgr.get_skill_info("deep_research")
        assert info is not None
        assert info["name"] == "deep_research"
        assert info["category"] == "research"
        assert "tools" in info
        assert "enabled" in info
        assert "metadata" in info

    def test_get_info_nonexistent(self):
        mgr = SkillManager()
        assert mgr.get_skill_info("nonexistent") is None

    def test_get_info_reflects_enabled_state(self):
        mgr = SkillManager()
        mgr.registry.disable("deep_research")
        info = mgr.get_skill_info("deep_research")
        assert info["enabled"] is False


# ─────────────────── get_skill_manager (global) ───────────────────


class TestGlobalSkillManager:

    def test_get_singleton(self):
        mgr1 = get_skill_manager()
        mgr2 = get_skill_manager()
        assert mgr1 is mgr2

    def test_loaded_skills(self):
        mgr = get_skill_manager()
        assert len(mgr.registry.list_all()) >= 5


# ─────────────────── Edge cases ───────────────────


class TestEdgeCases:

    def test_register_overwrites(self):
        """同名 skill 应覆盖。"""
        registry = SkillRegistry()
        s1 = Skill(name="x", description="v1", category="c", prompt_template="v1", tools=[])
        s2 = Skill(name="x", description="v2", category="c", prompt_template="v2", tools=[])
        registry.register(s1)
        registry.register(s2)
        assert registry.get("x") is s2
        assert registry.get("x").description == "v2"

    def test_disable_then_enable(self):
        mgr = SkillManager()
        mgr.registry.disable("deep_research")
        assert mgr.registry.get("deep_research").enabled is False
        mgr.registry.enable("deep_research")
        assert mgr.registry.get("deep_research").enabled is True

    def test_skill_with_empty_tools(self):
        skill = Skill(
            name="no_tools",
            description="Skill that doesn't need tools",
            category="misc",
            prompt_template="just text",
            tools=[],
        )
        assert skill.tools == []

    def test_skill_with_special_chars_in_name(self):
        skill = Skill(
            name="skill_with_underscore_123",
            description="test",
            category="c",
            prompt_template="x",
            tools=[],
        )
        assert "_" in skill.name
