"""
Skill 系统 - 可插拔的技能框架

灵感来源：deer-flow 的 Skill System
参考：https://github.com/bytedance/deer-flow/tree/main/skills
"""
import os
import json
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class Skill:
    """技能定义"""
    name: str                          # 技能名称
    description: str                   # 技能描述
    category: str                       # 分类
    prompt_template: str               # 系统提示词模板
    tools: List[str]                   # 需要的工具列表
    enabled: bool = True               # 是否启用
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据

@dataclass
class SkillResult:
    """技能执行结果"""
    skill_name: str
    success: bool
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class SkillRegistry:
    """技能注册表"""
    
    _instance = None
    _skills: Dict[str, Skill] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._skills = {}
        return cls._instance
    
    def register(self, skill: Skill) -> None:
        """注册技能"""
        self._skills[skill.name] = skill
        logging.info("[Skill] Registered: {} ({})".format(skill.name, skill.category))
    
    def get(self, name: str) -> Optional[Skill]:
        """获取技能"""
        return self._skills.get(name)
    
    def list_all(self) -> List[Skill]:
        """列出所有技能"""
        return list(self._skills.values())
    
    def list_by_category(self, category: str) -> List[Skill]:
        """按分类列出技能"""
        return [s for s in self._skills.values() if s.category == category]
    
    def list_enabled(self) -> List[Skill]:
        """列出启用的技能"""
        return [s for s in self._skills.values() if s.enabled]
    
    def enable(self, name: str) -> bool:
        """启用技能"""
        if name in self._skills:
            self._skills[name].enabled = True
            return True
        return False
    
    def disable(self, name: str) -> bool:
        """禁用技能"""
        if name in self._skills:
            self._skills[name].enabled = False
            return True
        return False


class SkillManager:
    """技能管理器"""
    
    def __init__(self):
        self.registry = SkillRegistry()
        self.logger = logging.getLogger(__name__)
        self._load_builtin_skills()
    
    def _load_builtin_skills(self):
        """加载内置技能"""
        # 深度研究技能
        self._register_deep_research_skill()
        
        # 代码文档技能
        self._register_code_doc_skill()
        
        # PPT 生成技能
        self._register_ppt_skill()
        
        # 论文审阅技能
        self._register_paper_review_skill()
        
        # 图表生成技能（基于现有的）
        self._register_chart_skill()
        
        self.logger.info("[Skill] Loaded {} builtin skills".format(
            len(self.registry.list_all())))
    
    def _register_deep_research_skill(self):
        """注册深度研究技能"""
        skill = Skill(
            name="deep_research",
            description="深度研究报告生成 - 对复杂主题进行深入研究和分析",
            category="research",
            prompt_template="""你是一个专业的研究分析师。请对以下主题进行深度研究：

主题：{topic}

要求：
1. 研究背景和概述
2. 核心概念和原理
3. 现状分析
4. 主要玩家/产品分析
5. 发展趋势和预测
6. 风险和挑战
7. 结论和建议

请提供详细、有据可查的研究报告。""",
            tools=["search_web", "query_knowledge_base"],
            metadata={
                "version": "1.0.0",
                "author": "AI Agent",
                "created": datetime.now().isoformat()
            }
        )
        self.registry.register(skill)
    
    def _register_code_doc_skill(self):
        """注册代码文档技能"""
        skill = Skill(
            name="code_documentation",
            description="自动生成代码文档 - 分析代码并生成规范的文档",
            category="development",
            prompt_template="""你是一个专业的技术文档工程师。请为以下代码生成文档：

代码路径：{file_path}

要求：
1. 文件概述
2. 主要类和函数说明
3. 参数和返回值
4. 使用示例
5. 注意事项

请生成符合规范的 Markdown 文档。""",
            tools=["read_file", "query_knowledge_base"],
            metadata={
                "version": "1.0.0",
                "author": "AI Agent",
                "created": datetime.now().isoformat()
            }
        )
        self.registry.register(skill)
    
    def _register_ppt_skill(self):
        """注册 PPT 生成技能"""
        skill = Skill(
            name="ppt_generation",
            description="PPT 大纲生成 - 生成 PPT 演示文稿的大纲结构",
            category="productivity",
            prompt_template="""你是一个专业的 PPT 设计顾问。请为以下主题设计演示文稿大纲：

主题：{topic}
目标受众：{audience}

要求：
1. 封面
2. 目录
3. 每个章节的要点（5-8 页）
4. 总结
5. Q&A

请生成 PPT 大纲，包含每页标题和关键要点。""",
            tools=["search_web"],
            metadata={
                "version": "1.0.0",
                "author": "AI Agent",
                "created": datetime.now().isoformat()
            }
        )
        self.registry.register(skill)
    
    def _register_paper_review_skill(self):
        """注册论文审阅技能"""
        skill = Skill(
            name="paper_review",
            description="学术论文审阅 - 分析和评价学术论文",
            category="academic",
            prompt_template="""你是一个资深的学术评审。请审阅以下论文：

论文摘要/内容：{content}

要求：
1. 研究问题
2. 方法论评估
3. 创新点
4. 局限性
5. 总体评价
6. 改进建议

请提供专业的学术评审意见。""",
            tools=["search_web", "query_knowledge_base"],
            metadata={
                "version": "1.0.0",
                "author": "AI Agent",
                "created": datetime.now().isoformat()
            }
        )
        self.registry.register(skill)
    
    def _register_chart_skill(self):
        """注册图表生成技能"""
        skill = Skill(
            name="chart_visualization",
            description="数据可视化图表 - 生成专业的数据可视化图表",
            category="data",
            prompt_template="""你是一个数据可视化专家。请为以下数据设计图表：

数据描述：{data_description}
图表类型：{chart_type}

请生成适合的图表代码或数据格式。""",
            tools=["generate_chart"],
            metadata={
                "version": "1.0.0",
                "author": "AI Agent",
                "created": datetime.now().isoformat()
            }
        )
        self.registry.register(skill)
    
    async def execute_skill(self, skill_name: str, context: Dict[str, Any]) -> SkillResult:
        """执行技能"""
        skill = self.registry.get(skill_name)
        
        if not skill:
            return SkillResult(
                skill_name=skill_name,
                success=False,
                content="",
                error="Skill not found: {}".format(skill_name)
            )
        
        if not skill.enabled:
            return SkillResult(
                skill_name=skill_name,
                success=False,
                content="",
                error="Skill is disabled: {}".format(skill_name)
            )
        
        try:
            # 构建提示词
            prompt = skill.prompt_template.format(**context)
            
            # 返回结果（实际执行由 Agent 调用 LLM 完成）
            return SkillResult(
                skill_name=skill_name,
                success=True,
                content="",
                metadata={
                    "prompt": prompt,
                    "required_tools": skill.tools,
                    "category": skill.category
                }
            )
            
        except Exception as e:
            return SkillResult(
                skill_name=skill_name,
                success=False,
                content="",
                error=str(e)
            )
    
    def get_skill_prompt(self, skill_name: str, **kwargs) -> Optional[str]:
        """获取技能提示词"""
        skill = self.registry.get(skill_name)
        if not skill:
            return None
        
        try:
            return skill.prompt_template.format(**kwargs)
        except KeyError as e:
            return None
    
    def list_skill_categories(self) -> List[str]:
        """列出所有分类"""
        categories = set()
        for skill in self.registry.list_all():
            categories.add(skill.category)
        return sorted(list(categories))
    
    def get_skill_info(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """获取技能信息"""
        skill = self.registry.get(skill_name)
        if not skill:
            return None
        
        return {
            "name": skill.name,
            "description": skill.description,
            "category": skill.category,
            "tools": skill.tools,
            "enabled": skill.enabled,
            "metadata": skill.metadata
        }


# 全局技能管理器
_skill_manager = None

def get_skill_manager() -> SkillManager:
    """获取全局技能管理器"""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager
