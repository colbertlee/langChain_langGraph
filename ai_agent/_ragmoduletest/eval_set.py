# -*- coding: utf-8 -*-
"""RAG 模块独立测试 —— 评估集（仅基于 knowledge_base 8 个 txt 生成）。

三类 query：
  1. single  单点事实查询（答案落在单个片段内）
  2. cross   跨段落综合查询（答案需综合多处内容）
  3. absent  文档不存在的问题（用于模块6拒答 / 模块5假阳性检视）

每个 case 记录 ground-truth：file（应命中文档）+ src_terms（召回片段必须包含的判别性词）
"""
import os
from common import KB_DIR, read_raw_text

# ---------------------------------------------------------------------------
# 单点事实 + 跨段落综合查询（用于召回率评价 + 答案溯源）
# ---------------------------------------------------------------------------
RETRIEVAL_CASES = [
    # ---- python_intro.txt ----
    {"file": "python_intro.txt", "type": "single",
     "query": "Python 语言是由谁、在哪一年发布的？",
     "expected": "由 Guido van Rossum 于 1991 年发布",
     "src_terms": ["Guido", "1991"]},
    {"file": "python_intro.txt", "type": "single",
     "query": "Python 当前稳定的发布版本号是多少？",
     "expected": "Python 3.12（Python 2 已不再维护）",
     "src_terms": ["3.12", "Python 2"]},
    {"file": "python_intro.txt", "type": "single",
     "query": "Python 官方文档的网址是什么？",
     "expected": "docs.python.org",
     "src_terms": ["docs.python.org"]},
    {"file": "python_intro.txt", "type": "cross",
     "query": "Python 有哪些应用领域？",
     "expected": "Web开发(Django/Flask)、数据分析(NumPy/Pandas/Matplotlib)、人工智能(TensorFlow/PyTorch)、自动化脚本、游戏开发(Pygame)",
     "src_terms": ["Django", "TensorFlow", "Pygame"]},
    {"file": "python_intro.txt", "type": "cross",
     "query": "Python 语言的主要特点有哪些？",
     "expected": "简单易学、面向对象、动态类型、跨平台、丰富的库",
     "src_terms": ["动态类型", "跨平台", "简单易学"]},

    # ---- javascript_intro.txt ----
    {"file": "javascript_intro.txt", "type": "single",
     "query": "JavaScript 是由谁在哪一年创建的？",
     "expected": "由 Brendan Eich 于 1995 年创建",
     "src_terms": ["Brendan Eich", "1995"]},
    {"file": "javascript_intro.txt", "type": "single",
     "query": "JavaScript 当前的 ECMAScript 标准是哪个版本？",
     "expected": "ECMAScript 2024",
     "src_terms": ["ECMAScript 2024"]},
    {"file": "javascript_intro.txt", "type": "single",
     "query": "JavaScript 是哪类技术的核心之一？",
     "expected": "Web 的三大核心技术之一",
     "src_terms": ["三大核心"]},
    {"file": "javascript_intro.txt", "type": "cross",
     "query": "JavaScript 有哪些主要特点？",
     "expected": "动态类型、事件驱动、函数式编程(一等公民)、跨平台(浏览器/Node.js/移动端)、丰富生态(npm)",
     "src_terms": ["事件驱动", "一等公民", "Node.js"]},

    # ---- java_intro.txt ----
    {"file": "java_intro.txt", "type": "single",
     "query": "Java 由谁在哪一年、于哪个公司发布？",
     "expected": "James Gosling 和他的团队于 1995 年在 Sun Microsystems 发布",
     "src_terms": ["James Gosling", "1995", "Sun"]},
    {"file": "java_intro.txt", "type": "single",
     "query": "Java 当前 LTS 版本是哪个？",
     "expected": "Java 21",
     "src_terms": ["Java 21"]},
    {"file": "java_intro.txt", "type": "single",
     "query": "Java 的设计理念是什么？",
     "expected": "一次编写，到处运行",
     "src_terms": ["一次编写", "到处运行"]},
    {"file": "java_intro.txt", "type": "cross",
     "query": "Java 有哪些典型的应用领域？",
     "expected": "企业级(Spring/Hibernate)、Android、大数据(Hadoop/Spark)、金融系统",
     "src_terms": ["Android", "Hadoop", "金融"]},

    # ---- cooking_basics.txt ----
    {"file": "cooking_basics.txt", "type": "single",
     "query": "家常菜提到的常见锅具有哪些？",
     "expected": "铁锅、不粘锅、砂锅",
     "src_terms": ["铁锅", "砂锅"]},
    {"file": "cooking_basics.txt", "type": "single",
     "query": "中式烹饪强调什么？",
     "expected": "色香味俱全",
     "src_terms": ["色香味俱全"]},
    {"file": "cooking_basics.txt", "type": "cross",
     "query": "烹饪调味料包含哪些类别？",
     "expected": "基础(盐糖酱油料酒)、香料(花椒八角桂皮)、酱料(豆瓣酱甜面酱)、油类(花生油芝麻油)",
     "src_terms": ["豆瓣酱", "八角", "花生油"]},

    # ---- travel_guide.txt ----
    {"file": "travel_guide.txt", "type": "single",
     "query": "现代旅游业始于哪个世纪？",
     "expected": "19 世纪",
     "src_terms": ["19 世纪"]},
    {"file": "travel_guide.txt", "type": "single",
     "query": "旅游有哪些出行方式？",
     "expected": "飞机、高铁、自驾、跟团",
     "src_terms": ["高铁", "自驾", "跟团"]},
    {"file": "travel_guide.txt", "type": "cross",
     "query": "旅游目的地的类型有哪些？",
     "expected": "自然类(海岛湖泊森林)、文化类(古城博物馆)、主题类(主题公园动物园)、宗教类(寺庙教堂)",
     "src_terms": ["海岛", "博物馆", "寺庙", "主题公园"]},

    # ---- photography.txt ----
    {"file": "photography.txt", "type": "single",
     "query": "第一台实用相机于哪一年发明？",
     "expected": "1839 年",
     "src_terms": ["1839"]},
    {"file": "photography.txt", "type": "single",
     "query": "摄影常用的后期处理软件有哪些？",
     "expected": "Lightroom、Photoshop",
     "src_terms": ["Lightroom", "Photoshop"]},
    {"file": "photography.txt", "type": "cross",
     "query": "摄影的基础设置包括哪些？",
     "expected": "光圈、快门、ISO、白平衡、对焦",
     "src_terms": ["光圈", "快门", "ISO", "白平衡"]},

    # ---- fitness.txt ----
    {"file": "fitness.txt", "type": "single",
     "query": "新手建议每周健身几次、每次多久？",
     "expected": "每周 3 次，每次 60 分钟",
     "src_terms": ["每周 3 次", "60 分钟"]},
    {"file": "fitness.txt", "type": "single",
     "query": "健身的营养搭配中蛋白质、碳水、脂肪比例约为多少？",
     "expected": "3:5:2",
     "src_terms": ["3:5:2"]},
    {"file": "fitness.txt", "type": "cross",
     "query": "健身有哪些应用领域？",
     "expected": "增肌、减脂(HIIT)、塑形(瑜伽/普拉提)、康复(物理治疗)、格斗(拳击/跆拳道)",
     "src_terms": ["增肌", "HIIT", "普拉提", "拳击"]},

    # ---- gardening.txt ----
    {"file": "gardening.txt", "type": "single",
     "query": "家庭园艺中可以种植哪些水果/蔬菜？",
     "expected": "番茄、黄瓜、生菜",
     "src_terms": ["番茄", "黄瓜", "生菜"]},
    {"file": "gardening.txt", "type": "single",
     "query": "常见园艺病害包括哪些？",
     "expected": "白粉病、蚜虫、红蜘蛛",
     "src_terms": ["白粉病", "蚜虫", "红蜘蛛"]},
    {"file": "gardening.txt", "type": "cross",
     "query": "园艺的季节管理是怎样的？",
     "expected": "春季换盆、夏季遮阴、秋季修剪、冬季保暖",
     "src_terms": ["换盆", "遮阴", "修剪", "保暖"]},
]

# ---------------------------------------------------------------------------
# 文档不存在的问题（KB 中无任何相关内容）
# ---------------------------------------------------------------------------
ABSENT_CASES = [
    {"query": "Python 语言是哪个航空公司开发的？",
     "reason": "航班与编程教程无关，KB 无此内容"},
    {"query": "文档中提到 OceanBase 数据库的部署方法了吗？",
     "reason": "KB 全文无 OceanBase/部署内容"},
    {"query": "健身时应每次服用哪种特定补剂的具体剂量？",
     "reason": "KB fitness 仅提及营养比例 3:5:2，无补剂剂量"},
    {"query": "Tom 环球旅行的签证材料清单具体是什么？",
     "reason": "KB travel 仅列基础装备(证件衣物洗漱)，无签证材料清单"},
]


def build_src_spans() -> dict:
    """每个文件原文（供溯源评测），返回 {fname: text}。"""
    return {f: read_raw_text(f) for f in os.listdir(KB_DIR) if f.endswith(".txt")}


if __name__ == "__main__":
    print("single+2 cross:", sum(1 for c in RETRIEVAL_CASES if c["type"] in ("single", "cross")))
    print("absent:", len(ABSENT_CASES))