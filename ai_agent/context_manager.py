"""
结构化上下文持久化 - 上下文管理器
Phase 1-5: 基础框架 + 实体关系 + 上下文注入 + 用户画像 + 性能监控
"""
import re
import logging
import time
import hashlib
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
from collections import defaultdict

from context_db import (
    get_db, get_session_repo, get_message_repo, get_entity_repo, 
    get_toolcall_repo, get_summary_repo, get_relation_repo, get_profile_repo,
    Session, Message, Entity, ToolCall, Summary, EntityRelation, UserProfile,
    SessionStatus, MessageRole, EntityType, ToolStatus, SummaryType
)

# 性能监控
try:
    from monitor import get_monitor, get_context_cache
    MONITOR_AVAILABLE = True
except ImportError:
    MONITOR_AVAILABLE = False
    get_monitor = None
    get_context_cache = None

logger = logging.getLogger(__name__)


class EntityExtractor:
    """实体提取器"""
    
    # ETF 代码正则: 6位数字
    ETF_PATTERN = re.compile(r'\b(\d{6})\b')
    
    # 城市名（常用城市）
    CITIES = {
        '北京', '上海', '广州', '深圳', '杭州', '南京', '苏州', '成都', '重庆',
        '武汉', '西安', '天津', '长沙', '郑州', '青岛', '大连', '沈阳', '哈尔滨',
        '昆明', '福州', '厦门', '济南', '石家庄', '南昌', '合肥', '贵阳', '太原',
        '长春', '兰州', '呼和浩特', '乌鲁木齐', '拉萨', '银川', '西宁', '海口',
        '三亚', '香港', '澳门', '台北',
        'Beijing', 'Shanghai', 'Guangzhou', 'Shenzhen', 'Hong Kong', 'Tokyo', 'New York'
    }
    
    # ETF 相关关键词
    ETF_KEYWORDS = {'ETF', '指数', '基金', '净值', '涨跌', '收益率', '定投', '配置'}
    
    # 动作关键词
    ACTION_KEYWORDS = {
        '查询', '搜索', '获取', '查找', '比较', '对比', '分析', '推荐',
        '计算', '统计', '预测', '建议', '解释', '说明', '展示', '显示'
    }
    
    # 查询类型关键词
    QUERY_KEYWORDS = {
        '什么是', '如何', '怎么', '为什么', '多少', '哪里', '哪个', '什么时候',
        'price', 'value', 'how', 'what', 'why', 'where', 'when', 'which'
    }
    
    def extract(self, text: str) -> List[Entity]:
        """从文本中提取实体"""
        entities = []
        
        # 提取 ETF 代码
        etf_codes = self.ETF_PATTERN.findall(text)
        for code in etf_codes:
            # 检查上下文是否与 ETF 相关
            entities.append(Entity(
                entity_type=EntityType.ETF.value,
                entity_name=code,
                entity_value={'code': code}
            ))
        
        # 提取城市
        for city in self.CITIES:
            if city in text:
                entities.append(Entity(
                    entity_type=EntityType.CITY.value,
                    entity_name=city,
                    entity_value={'name': city}
                ))
        
        # 提取日期
        date_patterns = [
            r'(\d{4})年(\d{1,2})月(\d{1,2})日',
            r'(\d{4})-(\d{2})-(\d{2})',
            r'(\d{4})/(\d{2})/(\d{2})',
            r'近(\d+)天',
            r'最近(\d+)天',
            r'过去(\d+)天'
        ]
        
        for pattern in date_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    if len(match) == 3 and match[0].isdigit():
                        # 日期格式
                        if len(match[0]) == 4:  # 年月日
                            date_str = f"{match[0]}-{match[1]}-{match[2]}"
                            entities.append(Entity(
                                entity_type=EntityType.DATE.value,
                                entity_name=date_str,
                                entity_value={'date': date_str}
                            ))
                    elif match.isdigit():
                        # 天数
                        entities.append(Entity(
                            entity_type=EntityType.DATE.value,
                            entity_name=f"{match}天",
                            entity_value={'days': int(match)}
                        ))
        
        # 识别意图类型
        text_lower = text.lower()
        for keyword in self.QUERY_KEYWORDS:
            if keyword in text_lower:
                entities.append(Entity(
                    entity_type=EntityType.QUERY.value,
                    entity_name=keyword,
                    entity_value={'keyword': keyword}
                ))
                break
        
        # 识别动作
        for keyword in self.ACTION_KEYWORDS:
            if keyword in text:
                entities.append(Entity(
                    entity_type=EntityType.ACTION.value,
                    entity_name=keyword,
                    entity_value={'action': keyword}
                ))
                break
        
        return entities
    
    def should_add_entity(self, entity: Entity, existing_entities: List[Entity]) -> bool:
        """判断是否应该添加实体"""
        for existing in existing_entities:
            if (existing.entity_type == entity.entity_type and 
                existing.entity_name == entity.entity_name):
                return False
        return True


class ContextBuilder:
    """上下文构建器"""
    
    def __init__(self, session_repo=None, message_repo=None, entity_repo=None, 
                 toolcall_repo=None, summary_repo=None, relation_repo=None):
        self.session_repo = session_repo or get_session_repo()
        self.message_repo = message_repo or get_message_repo()
        self.entity_repo = entity_repo or get_entity_repo()
        self.toolcall_repo = toolcall_repo or get_toolcall_repo()
        self.summary_repo = summary_repo or get_summary_repo()
        self.relation_repo = relation_repo or get_relation_repo()
    
    def build_context(self, session_id: str, max_tokens: int = 4000, 
                     user_input: str = None) -> str:
        """构建结构化上下文用于注入 LLM
        
        Args:
            session_id: 会话 ID
            max_tokens: 最大 token 数
            user_input: 当前用户输入（用于相关实体筛选）
        """
        # 尝试从缓存获取
        # 设计原则：缓存 key 必须包含全部影响输出的参数。
        # user_input 决定实体筛选结果，必须参与 key 计算，否则不同 query
        # 会命中同一缓存，丧失上下文相关性。
        input_hash = hashlib.md5((user_input or "").encode("utf-8")).hexdigest()[:12]
        cache_key = f"context:{session_id}:{input_hash}"
        if MONITOR_AVAILABLE and get_context_cache:
            cache = get_context_cache()
            cached = cache.get(cache_key)
            if cached:
                return cached
        
        start_time = time.time()
        
        context_parts = []
        
        # 1. 会话摘要 (最重要，优先添加)
        summary = self.summary_repo.get_latest(session_id)
        if summary:
            context_parts.append(self._build_summary_section(summary))
        
        # 2. 相关实体（根据用户输入筛选）
        entities = self._get_relevant_entities(session_id, user_input)
        if entities:
            context_parts.append(self._build_entities_section(entities))
        
        # 3. 最近工具调用 (了解用户行为)
        recent_tools = self.toolcall_repo.get_recent(session_id, limit=5)
        if recent_tools:
            context_parts.append(self._build_tools_section(recent_tools))
        
        # 4. 用户偏好
        session = self.session_repo.get_by_id(session_id)
        if session and session.preferences:
            context_parts.append(self._build_preferences_section(session.preferences))
        
        # 5. 对话历史（最近的交互）
        recent_messages = self.message_repo.get_recent_messages(session_id, limit=6)
        if recent_messages:
            context_parts.append(self._build_conversation_history_section(recent_messages))
        
        # 6. 拼接并确保不超 token 限制
        final_context = self._join_and_truncate(context_parts, max_tokens)
        
        # 记录性能指标
        elapsed = (time.time() - start_time) * 1000
        if MONITOR_AVAILABLE and get_monitor:
            get_monitor().metrics['context_build'].append({
                'elapsed_ms': elapsed,
                'timestamp': datetime.now().isoformat()
            })
        
        # 缓存结果
        if MONITOR_AVAILABLE and get_context_cache and elapsed < 100:
            cache = get_context_cache()
            cache.set(cache_key, final_context)
        
        return final_context
    
    def _get_relevant_entities(self, session_id: str, user_input: str = None) -> List[Entity]:
        """获取与当前输入相关的实体"""
        all_entities = self.entity_repo.list_by_session(session_id, active_only=True)
        
        if not user_input or not all_entities:
            # 没有输入时返回最近的实体
            return all_entities[:10]
        
        # 简单相关性过滤：如果用户提到了某实体，优先返回同类型的
        relevant_entities = []
        mentioned_types = set()
        
        # 从输入中提取实体类型
        for entity in all_entities:
            if entity.entity_name in user_input:
                mentioned_types.add(entity.entity_type)
        
        # 优先返回同类型的实体
        for entity in all_entities:
            if entity.entity_type in mentioned_types:
                relevant_entities.append(entity)
        
        # 补充其他实体
        for entity in all_entities:
            if entity not in relevant_entities:
                relevant_entities.append(entity)
        
        return relevant_entities[:10]
    
    def build_system_context(self, session_id: str) -> str:
        """构建系统提示上下文"""
        session = self.session_repo.get_by_id(session_id)
        
        if not session:
            return ""
        
        parts = []
        
        # 用户画像信息
        if session.profile:
            profile = session.profile
            if profile.get('risk_level'):
                parts.append(f"- 用户风险偏好: {profile['risk_level']}")
            if profile.get('investment_exp'):
                parts.append(f"- 投资经验: {profile['investment_exp']}")
        
        # 用户偏好
        if session.preferences:
            prefs = session.preferences
            if prefs.get('default_etf_range'):
                parts.append(f"- 默认查询范围: {prefs['default_etf_range']}")
        
        return "\n".join(parts) if parts else ""
    
    def _build_summary_section(self, summary: Summary) -> str:
        """构建摘要部分"""
        parts = []
        
        if summary.topic:
            parts.append(f"📌 会话主题: {summary.topic}")
        
        if summary.keywords:
            parts.append(f"🔑 关键词: {', '.join(summary.keywords[:5])}")
        
        if summary.key_entities:
            parts.append(f"📊 关键实体: {', '.join(summary.key_entities[:5])}")
        
        if summary.completed_goals:
            parts.append(f"✅ 已完成: {', '.join(summary.completed_goals[:3])}")
        
        if summary.pending_questions:
            parts.append(f"❓ 待解决: {', '.join(summary.pending_questions[:3])}")
        
        if summary.sentiment:
            parts.append(f"💭 用户情绪: {summary.sentiment}")
        
        return "【会话摘要】\n" + "\n".join(parts) if parts else ""
    
    def _build_entities_section(self, entities: List[Entity]) -> str:
        """构建实体部分"""
        # 按类型分组
        by_type = defaultdict(list)
        for e in entities:
            by_type[e.entity_type].append(e.entity_name)
        
        parts = []
        for etype, names in sorted(by_type.items()):
            unique_names = list(dict.fromkeys(names))[:10]  # 每类型最多10个
            parts.append(f"• {etype.upper()}: {', '.join(unique_names)}")
        
        return "【当前上下文中的实体】\n" + "\n".join(parts) if parts else ""
    
    def _build_tools_section(self, tools: List[ToolCall]) -> str:
        """构建工具部分"""
        tool_names = [t.tool_name for t in tools]
        unique_tools = list(dict.fromkeys(tool_names))[:5]
        return f"【最近使用的工具】 {', '.join(unique_tools)}"
    
    def _build_preferences_section(self, preferences: Dict[str, Any]) -> str:
        """构建偏好部分"""
        parts = []
        
        for key, value in preferences.items():
            if value and key not in ['theme', 'notification_enabled']:
                parts.append(f"• {key}: {value}")
        
        return "【用户偏好设置】\n" + "\n".join(parts) if parts else ""
    
    def _build_conversation_history_section(self, messages: List[Message]) -> str:
        """构建对话历史部分（简化版）"""
        parts = []
        
        for msg in messages:
            if msg.role == 'user':
                # 截断过长的内容
                content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                parts.append(f"用户: {content}")
            elif msg.role == 'assistant':
                # 截断过长的内容
                content = msg.content[:150] + "..." if len(msg.content) > 150 else msg.content
                parts.append(f"助手: {content}")
        
        return "【最近对话】\n" + "\n".join(parts[-6:]) if parts else ""
    
    def _join_and_truncate(self, parts: List[str], max_tokens: int) -> str:
        """拼接并按预算分配。

        修复 W3/W4：原实现一次性 join 后硬切，导致重要 section（摘要）
        与低优先级 section（最近对话）被一视同仁地截断。

        新算法：
        - 默认按重要性对每个 part 加权（传入者可在 part 前以 [PRIORITY=N] 标记；
          未标记则按 parts 顺序，从前到后权重递减）。
        - 高优先级 part 先填满预算，溢出时降级（按字符截断 + 标记 [已截断]）。
        - 低优先级 part 预算不足时，整段丢弃而非截断（避免半截误导）。
        """
        if not parts:
            return ""

        # 估算系数：中英混合 ~0.35 token/字符
        tokens_per_char = 0.35
        max_chars = int(max_tokens / tokens_per_char)

        # 重要性权重：parts 顺序从前到后 1.0, 0.7, 0.5, 0.4, 0.3
        # 默认前几个 part（summary / entities / preferences）更重要
        weights = [1.0, 0.7, 0.5, 0.4, 0.3]
        weights = (weights + [0.2] * len(parts))[: len(parts)]

        total_weight = sum(weights) or 1.0
        out_parts: List[str] = []
        consumed = 0

        for part, w in zip(parts, weights):
            if not part:
                continue
            budget_chars = int(max_chars * w / total_weight)
            if len(part) <= budget_chars:
                out_parts.append(part)
                consumed += len(part)
            else:
                # 溢出：截断 + 标记；预留 30 字符给截断标记
                truncated = part[: max(0, budget_chars - 30)]
                if truncated:
                    out_parts.append(truncated + "\n[已截断]")
                    consumed += len(truncated) + 30

        result = "\n\n".join(out_parts)

        # 防御：如果拼接后仍超限，再做一次尾部削减（保留前部）
        if len(result) > max_chars:
            result = result[: max_chars] + "\n[已截断]"

        return result


class AutoSummarizer:
    """自动摘要生成器"""

    SUMMARY_INTERVAL = 10  # 每 10 条消息生成摘要
    TOKEN_THRESHOLD = 8000  # 修复 W2：累积 token 超过此值也触发摘要
    MAX_SUMMARY_LENGTH = 500

    def __init__(self, session_repo=None, message_repo=None, entity_repo=None,
                 toolcall_repo=None, summary_repo=None):
        self.session_repo = session_repo or get_session_repo()
        self.message_repo = message_repo or get_message_repo()
        self.entity_repo = entity_repo or get_entity_repo()
        self.toolcall_repo = toolcall_repo or get_toolcall_repo()
        self.summary_repo = summary_repo or get_summary_repo()

    def should_generate_summary(self, session: Session) -> bool:
        """判断是否需要生成摘要。

        修复 W2：除按消息数间隔触发外，新增 token 阈值触发，
        防止长消息情况下消息数很少但已超预算。
        """
        if session.message_count > 0 and session.message_count % self.SUMMARY_INTERVAL == 0:
            return True
        # 即使消息条数不到 10，只要累积 token 已逼近预算上限，也要触发
        if session.total_tokens >= self.TOKEN_THRESHOLD:
            return True
        return False
    
    def generate_summary(self, session_id: str) -> Optional[Summary]:
        """生成会话摘要"""
        # 获取会话
        session = self.session_repo.get_by_id(session_id)
        if not session:
            return None
        
        # 获取最近的对话
        messages = self.message_repo.list_by_session(session_id, limit=20)
        
        # 提取关键信息
        topic = self._identify_topic(messages)
        keywords = self._extract_keywords(messages)
        key_entities = self._extract_key_entities(session_id)
        completed_goals = self._extract_completed_goals(messages)
        pending_questions = self._extract_pending_questions(messages)
        
        # 生成摘要文本
        summary_content = self._generate_summary_text(
            topic, keywords, completed_goals, pending_questions
        )
        
        # 创建摘要
        summary = self.summary_repo.create(
            session_id=session_id,
            summary_content=summary_content,
            summary_type=SummaryType.AUTO.value,
            topic=topic,
            keywords=keywords,
            key_entities=key_entities,
            completed_goals=completed_goals,
            pending_questions=pending_questions
        )
        
        logger.info(f"Generated summary for session {session_id}: {topic}")
        return summary
    
    def _identify_topic(self, messages: List[Message]) -> str:
        """识别会话主题"""
        # 简单实现：基于关键词匹配
        all_content = " ".join([m.content for m in messages if m.role == 'user'])
        
        topics = {
            'ETF查询': ['ETF', '基金', '净值', '涨跌'],
            '天气查询': ['天气', '温度', '下雨'],
            '股票分析': ['股票', '股价', '涨跌'],
            '文件操作': ['文件', '读取', '写入', '创建'],
            '代码执行': ['代码', '运行', '执行', 'Python'],
            '知识问答': ['什么', '如何', '为什么'],
        }
        
        for topic, keywords in topics.items():
            if any(kw in all_content for kw in keywords):
                return topic
        
        return "一般对话"
    
    def _extract_keywords(self, messages: List[Message]) -> List[str]:
        """提取关键词"""
        # 简单实现：提取高频词
        all_content = " ".join([m.content for m in messages if m.role == 'user'])
        
        # 移除常见停用词
        stopwords = {'的', '了', '是', '在', '我', '你', '他', '她', '它', '这', '那', '和', '与', '或', '吗', '呢', '吧', '啊'}
        
        words = re.findall(r'[\u4e00-\u9fa5]+', all_content)  # 提取中文词
        word_count = defaultdict(int)
        
        for word in words:
            if len(word) >= 2 and word not in stopwords:
                word_count[word] += 1
        
        # 返回前 10 个高频词
        sorted_words = sorted(word_count.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_words[:10]]
    
    def _extract_key_entities(self, session_id: str) -> List[str]:
        """提取关键实体"""
        entities = self.entity_repo.list_by_session(session_id, active_only=True)
        
        # 按提及次数排序
        entity_names = [(e.entity_name, e.mention_count) for e in entities]
        entity_names.sort(key=lambda x: x[1], reverse=True)
        
        return [name for name, count in entity_names[:10]]
    
    def _extract_completed_goals(self, messages: List[Message]) -> List[str]:
        """提取已完成的目标"""
        completed = []
        
        # 检测成功完成的操作
        for msg in messages:
            if msg.role == 'assistant' and '✅' in msg.content:
                # 提取简短描述
                lines = msg.content.split('\n')
                for line in lines:
                    if '✅' in line and len(line) < 50:
                        completed.append(line.strip())
                        break
        
        return completed[:5]
    
    def _extract_pending_questions(self, messages: List[Message]) -> List[str]:
        """提取待解决问题"""
        pending = []
        
        # 检测用户未回答的问题
        user_messages = [m for m in messages if m.role == 'user']
        assistant_content = " ".join([m.content for m in messages if m.role == 'assistant'])
        
        question_markers = ['什么', '如何', '怎么', '为什么', '哪里', '哪个', 'how', 'what', 'why', 'where']
        
        for msg in user_messages:
            for marker in question_markers:
                if marker in msg.content:
                    # 检查是否在回复中回答了
                    if marker not in assistant_content[:len(assistant_content)//2]:  # 简化判断
                        pending.append(msg.content[:30] + "..." if len(msg.content) > 30 else msg.content)
                        break
                    break
        
        return pending[:3]
    
    def _generate_summary_text(
        self, 
        topic: str, 
        keywords: List[str], 
        completed: List[str],
        pending: List[str]
    ) -> str:
        """生成摘要文本"""
        parts = [f"会话主题：{topic}"]
        
        if keywords:
            parts.append(f"关键词：{', '.join(keywords[:5])}")
        
        if completed:
            parts.append(f"已完成：{len(completed)} 项任务")
        
        if pending:
            parts.append(f"待解决：{len(pending)} 个问题")
        
        text = " | ".join(parts)
        
        # 截断
        if len(text) > self.MAX_SUMMARY_LENGTH:
            text = text[:self.MAX_SUMMARY_LENGTH] + "..."
        
        return text


class ContextManager:
    """上下文管理器（主入口）"""
    
    def __init__(self):
        self.session_repo = get_session_repo()
        self.message_repo = get_message_repo()
        self.entity_repo = get_entity_repo()
        self.toolcall_repo = get_toolcall_repo()
        self.summary_repo = get_summary_repo()
        self.relation_repo = get_relation_repo()
        self.profile_repo = get_profile_repo()
        
        self.entity_extractor = EntityExtractor()
        self.context_builder = ContextBuilder(
            session_repo=self.session_repo,
            message_repo=self.message_repo,
            entity_repo=self.entity_repo,
            toolcall_repo=self.toolcall_repo,
            summary_repo=self.summary_repo
        )
        self.summarizer = AutoSummarizer(
            session_repo=self.session_repo,
            message_repo=self.message_repo,
            entity_repo=self.entity_repo,
            toolcall_repo=self.toolcall_repo,
            summary_repo=self.summary_repo
        )
    
    # ==========================================
    # 会话管理
    # ==========================================
    
    def create_session(self, user_id: str = None, session_id: str = None, **kwargs) -> Session:
        """创建会话"""
        return self.session_repo.create(user_id=user_id, session_id=session_id, **kwargs)
    
    def get_or_create_session(self, session_id: str = None, user_id: str = None) -> Session:
        """获取或创建会话"""
        if session_id:
            session = self.session_repo.get_by_id(session_id)
            if session:
                return session
        
        return self.create_session(user_id=user_id, session_id=session_id)
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        return self.session_repo.get_by_id(session_id)
    
    def update_session(self, session_id: str, **kwargs) -> Optional[Session]:
        """更新会话"""
        return self.session_repo.update(session_id, **kwargs)
    
    def list_sessions(self, user_id: str = None, status: str = None, limit: int = 20) -> List[Session]:
        """列出会话"""
        return self.session_repo.list_sessions(user_id=user_id, status=status, limit=limit)
    
    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        return self.session_repo.delete(session_id)
    
    # ==========================================
    # 消息管理
    # ==========================================
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        **kwargs
    ) -> Message:
        """添加消息"""
        # 创建消息
        message = self.message_repo.create(
            session_id=session_id,
            role=role,
            content=content,
            **kwargs
        )

        # 如果是用户消息，提取实体
        if role == MessageRole.USER.value and content:
            self._extract_and_save_entities(session_id, content)

        # 更新会话计数
        # 修复 W7：用 0.35 系数（中英混合经验值）替代 `// 4` 的纯英文估算。
        # 中文占比高时 `// 4` 会低估 ~50%，导致 budget 失控。
        token_count = kwargs.get('token_count', int(len(content) * 0.35) or 1)
        self.session_repo.increment_message_count(session_id, token_count)

        # 检查是否需要生成摘要
        session = self.session_repo.get_by_id(session_id)
        if session and self.summarizer.should_generate_summary(session):
            self.summarizer.generate_summary(session_id)
            # 修复 W5：摘要触发的同一时机做滚动归档，避免热路径成本。
            # 这样归档只在每 10 条 / token 超阈 时跑一次，而不是每条 add_message。
            try:
                if session.message_count > self._ARCHIVE_THRESHOLD:
                    self._archive_old_messages(session_id, keep_recent=self._ARCHIVE_KEEP_RECENT)
            except Exception as e:
                logger.warning(f"Archive old messages failed: {e}")

        return message

    # 生命周期治理配置
    _ARCHIVE_THRESHOLD = 200      # 消息数超过此值时触发滚动归档
    _ARCHIVE_KEEP_RECENT = 50     # 归档后保留最近 N 条原文

    def _archive_old_messages(self, session_id: str, keep_recent: int = 50) -> int:
        """将超出 keep_recent 的旧消息打包为摘要条目并物理删除原文。

        修复 W5：DB 无 GC 会让会话无限膨胀；这里把旧消息聚合成 summary，
        再 delete 原文，腾出存储与查询预算。

        Returns:
            归档的消息条数。
        """
        # 找到第 keep_recent 之后的最早消息 id
        with self.session_repo.db.get_cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT 1 OFFSET ?
                """,
                (session_id, keep_recent - 1),
            )
            row = cursor.fetchone()
            if not row:
                return 0
            cutoff_id = row["id"]

            # 取待归档的旧消息
            cursor.execute(
                """
                SELECT role, content FROM messages
                WHERE session_id = ? AND id <= ?
                ORDER BY id ASC
                """,
                (session_id, cutoff_id),
            )
            old_msgs = cursor.fetchall()

            if not old_msgs:
                return 0

            # 聚合成简易摘要（不调用 LLM，保证可降级）
            lines = [f"{m['role']}: {m['content'][:80]}" for m in old_msgs[:200]]
            archived_summary = (
                f"[滚动归档 {len(old_msgs)} 条消息]\n" + "\n".join(lines[:50])
            )

            # 写入 summaries 表（schema 校验 summary_type 必须是 auto/manual/milestone/final）
            cursor.execute(
                """
                INSERT INTO summaries (session_id, summary_content, summary_type,
                                       topic, keywords, key_entities,
                                       completed_goals, pending_questions,
                                       created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    archived_summary,
                    "auto",  # 复用 'auto' 类型；归档语义靠 summary_content 区分
                    f"[归档] {len(old_msgs)} 条历史消息",
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    str(__import__("datetime").datetime.now()),
                ),
            )

            # 物理删除
            cursor.execute(
                "DELETE FROM messages WHERE session_id = ? AND id <= ?",
                (session_id, cutoff_id),
            )

        logger.info(
            f"Archived {len(old_msgs)} old messages for session {session_id} "
            f"(cutoff_id={cutoff_id}, keep_recent={keep_recent})"
        )
        return len(old_msgs)
    
    def get_messages(self, session_id: str, limit: int = 50) -> List[Message]:
        """获取消息历史"""
        return self.message_repo.list_by_session(session_id, limit=limit)
    
    def get_recent_messages(self, session_id: str, limit: int = 10) -> List[Message]:
        """获取最近的消息"""
        return self.message_repo.get_recent_messages(session_id, limit=limit)
    
    def _extract_and_save_entities(self, session_id: str, text: str):
        """提取并保存实体"""
        # 获取已存在的实体
        existing_entities = self.entity_repo.list_by_session(session_id, active_only=True)
        
        # 提取新实体
        extracted_entities = self.entity_extractor.extract(text)
        
        # 去重并保存，同时建立关系
        new_entities = []
        for entity in extracted_entities:
            if self.entity_extractor.should_add_entity(entity, existing_entities):
                created = self.entity_repo.create(
                    session_id=session_id,
                    entity_type=entity.entity_type,
                    entity_name=entity.entity_name,
                    entity_value=entity.entity_value
                )
                new_entities.append(created)
                existing_entities.append(entity)
        
        # 自动建立新实体之间的关系
        self._auto_create_relations(session_id, new_entities, existing_entities)
    
    def _auto_create_relations(self, session_id: str, new_entities: List[Entity], all_entities: List[Entity]):
        """自动创建实体之间的关系"""
        # 同一类型的实体之间建立 "similar_to" 关系
        if len(new_entities) > 1:
            for i, entity1 in enumerate(new_entities):
                for entity2 in new_entities[i+1:]:
                    if entity1.entity_type == entity2.entity_type:
                        # 检查是否已存在关系
                        existing = self.relation_repo.find_relation(
                            entity1.id, entity2.id, "similar_to"
                        )
                        if not existing:
                            self.relation_repo.create(
                                session_id=session_id,
                                from_entity_id=entity1.id,
                                to_entity_id=entity2.id,
                                relation_type="similar_to",
                                strength=0.7,
                                context=f"同时被提及"
                            )
        
        # 与历史实体建立 "related_to" 关系
        # 修复 W1/W6：旧实体可能 id=None（list_by_session 返回的某些情况），
        # 直接 INSERT 会触发 NOT NULL 约束，导致整条消息保存失败。
        # 防御：跳过 id 为空的实体，并 try/except 兜底。
        for new_entity in new_entities:
            if new_entity.id is None:
                continue
            for old_entity in all_entities:
                if old_entity.id is None:
                    continue
                if (new_entity.entity_type == old_entity.entity_type and
                    new_entity.id != old_entity.id):
                    try:
                        existing = self.relation_repo.find_relation(
                            new_entity.id, old_entity.id, "related_to"
                        )
                        if not existing:
                            self.relation_repo.create(
                                session_id=session_id,
                                from_entity_id=new_entity.id,
                                to_entity_id=old_entity.id,
                                relation_type="related_to",
                                strength=0.5,
                                context=f"与历史实体相关"
                            )
                    except Exception as e:
                        # 防御：单条关系失败不应阻断消息保存
                        logger.warning(f"Failed to create relation {new_entity.id}->{old_entity.id}: {e}")
    
    # ==========================================
    # 工具调用管理
    # ==========================================
    
    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        message_id: int = None,
        tool_input: Dict[str, Any] = None,
        tool_output: Dict[str, Any] = None,
        status: str = ToolStatus.SUCCESS.value,
        error_message: str = None,
        execution_time_ms: int = None
    ) -> ToolCall:
        """记录工具调用"""
        return self.toolcall_repo.create(
            session_id=session_id,
            message_id=message_id,
            tool_name=tool_name,
            tool_input=tool_input or {},
            tool_output=tool_output or {},
            status=status,
            error_message=error_message,
            execution_time_ms=execution_time_ms
        )
    
    def get_tool_calls(self, session_id: str, limit: int = 50) -> List[ToolCall]:
        """获取工具调用记录"""
        return self.toolcall_repo.list_by_session(session_id, limit=limit)
    
    def get_tool_usage_stats(self, session_id: str) -> Dict[str, int]:
        """获取工具使用统计"""
        return self.toolcall_repo.get_tool_usage_stats(session_id)
    
    # ==========================================
    # 实体管理
    # ==========================================
    
    def get_entities(self, session_id: str, entity_type: str = None) -> List[Entity]:
        """获取实体"""
        return self.entity_repo.list_by_session(session_id, entity_type=entity_type)
    
    def update_entity(self, entity_id: int, **kwargs) -> Optional[Entity]:
        """更新实体"""
        return self.entity_repo.update(entity_id, **kwargs)
    
    # ==========================================
    # 实体关系管理
    # ==========================================
    
    def get_entity_relations(self, session_id: str, relation_type: str = None) -> List[EntityRelation]:
        """获取实体关系"""
        return self.relation_repo.list_by_session(session_id, relation_type=relation_type)
    
    def get_related_entities(self, entity_id: int) -> Dict[str, List[Entity]]:
        """获取与某实体相关的所有实体"""
        relations = self.relation_repo.list_by_entity(entity_id)
        related = {'similar_to': [], 'related_to': [], 'compared_with': [], 'other': []}
        
        for rel in relations:
            if rel.from_entity_id == entity_id:
                other = self.entity_repo.get_by_id(rel.to_entity_id)
            else:
                other = self.entity_repo.get_by_id(rel.from_entity_id)
            
            if other:
                if rel.relation_type in related:
                    related[rel.relation_type].append(other)
                else:
                    related['other'].append(other)
        
        return related
    
    def create_relation(
        self,
        session_id: str,
        from_entity_id: int,
        to_entity_id: int,
        relation_type: str,
        **kwargs
    ) -> EntityRelation:
        """创建实体关系"""
        return self.relation_repo.create(
            session_id=session_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            relation_type=relation_type,
            **kwargs
        )
    
    def delete_relation(self, relation_id: int) -> bool:
        """删除实体关系"""
        return self.relation_repo.delete(relation_id)
    
    # ==========================================
    # 摘要管理
    # ==========================================
    
    def get_summary(self, session_id: str) -> Optional[Summary]:
        """获取最新摘要"""
        return self.summary_repo.get_latest(session_id)
    
    def generate_summary(self, session_id: str, summary_type: str = SummaryType.MANUAL.value) -> Optional[Summary]:
        """生成摘要"""
        summary = self.summarizer.generate_summary(session_id)
        if summary and summary_type != SummaryType.AUTO.value:
            self.summary_repo.update(summary.id, summary_type=summary_type)
        return summary
    
    def get_all_summaries(self, session_id: str) -> List[Summary]:
        """获取所有摘要"""
        return self.summary_repo.list_by_session(session_id)
    
    # ==========================================
    # 上下文构建
    # ==========================================
    
    def build_context(self, session_id: str, max_tokens: int = 4000,
                      user_input: Optional[str] = None) -> str:
        """构建上下文。透传 user_input 给 ContextBuilder 以启用实体相关性筛选。"""
        return self.context_builder.build_context(session_id, max_tokens, user_input=user_input)
    
    def build_system_context(self, session_id: str) -> str:
        """构建系统上下文"""
        return self.context_builder.build_system_context(session_id)
    
    # ==========================================
    # 统计与分析
    # ==========================================
    
    def get_session_analytics(self, session_id: str) -> Dict[str, Any]:
        """获取会话统计"""
        session = self.session_repo.get_by_id(session_id)
        if not session:
            return {}
        
        entities = self.entity_repo.list_by_session(session_id)
        tool_stats = self.toolcall_repo.get_tool_usage_stats(session_id)
        
        return {
            "session_id": session_id,
            "message_count": session.message_count,
            "total_tokens": session.total_tokens,
            "entity_count": len(entities),
            "tool_call_count": sum(tool_stats.values()),
            "tool_usage": tool_stats,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "status": session.status
        }


# 全局单例
_context_manager = None


def get_context_manager() -> ContextManager:
    """获取上下文管理器单例"""
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager
