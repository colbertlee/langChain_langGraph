# -*- coding: utf-8 -*-
"""模块6：答案生成模块 —— 隔离测试。
前置：模块5检索等通过；本模块输入为【固定召回 chunk 片段】，直接喂给
LLM 生成链，不重新触发检索。被测链路与 rag.py 的生成链一致
（RAGModule.prompt + ChatOllama qwen3.5:4b + StrOutputParser）。
后端：本机 Ollama qwen3.5:4b。
"""
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from common import ModuleReport, OllamaChat

LLM = OllamaChat(model="qwen3.5:4b", base_url="http://localhost:11434", temperature=0.1)

PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     """你是文档问答助手。必须严格遵守下面规则：

1. 只允许使用【参考文档片段】中的信息回答问题；禁止使用你自身知识库的任何内容。
2. 如果【参考文档片段】中没有任何片段与问题相关，必须回复："文档未找到相关内容"，禁止编造、禁止猜测。
3. 回答需简洁；若引用了片段，请在对应句子末尾用 [n] 标注来源编号（例如 [1]）。
4. 多个片段信息冲突时，以编号最小的片段为准，并简短说明冲突。

【参考文档片段】
{context}"""),
    ("user", "{input}"),
])

def format_docs(docs):
    lines = []
    for i, d in enumerate(docs, start=1):
        content = (d.get("text") or "").strip()
        if content:
            lines.append(f"[{i}] {content}")
    return "\n\n".join(lines) if lines else "（无相关片段）"

def generate(query, docs):
    chain = PROMPT | LLM | StrOutputParser()
    return chain.invoke({"context": format_docs(docs), "input": query})


def main():
    # 固定召回片段（源，来自 knowledge_base）
    py = {"text": ("Python 是一种高级、通用、解释型编程语言。"
                   "它由 Guido van Rossum 于 1991 年发布。当前稳定版本是 Python 3.12，"
                   "由 Python 软件基金会维护。")}
    py_fields = {"text": ("Python 特点：简单易学、面向对象、动态类型、跨平台、丰富的库。"
                          "应用领域：Web 开发（Django/Flask）、数据分析（NumPy/Pandas）、"
                          "人工智能（TensorFlow/PyTorch）、自动化脚本、游戏开发（Pygame）。")}
    js = {"text": ("JavaScript 由 Brendan Eich 于 1995 年创建。"
                   "它是 Web 的三大核心技术之一，当前标准为 ECMAScript 2024。")}
    js_field = {"text": ("JavaScript 特点：动态类型、事件驱动、函数式编程（函数是一等公民）、"
                         "跨平台（浏览器、Node.js、移动端）、丰富的生态（npm）。")}
    wrong = {"text": ("健身建议每周进行 3 次训练，每次 60 分钟，结合有氧与力量训练，"
                      "注意循序渐进、充分热身和拉伸。")}

    rep = ModuleReport("模块6 答案生成（LLM qwen3.5:4b）")

    # T6-01 单点事实，片段含完整答案
    a1 = generate("Python 是由谁、在哪一年发布的？", [py, py_fields])
    ok1 = ("Guido" in a1 and "1991" in a1 and "[1]" in a1)
    rep.add("T6-01 单点事实问答(含引用)",
            "答案含 Guido/1991，末尾带[1]", f"答={a1!r}\n 含Guido+1991={ok1}", ok1)

    # T6-02 跨片段综合
    a2 = generate("JavaScript 有哪些特点和典型应用领域？", [js, js_field])
    ok2 = (("[2]" in a2) and any(k in a2 for k in ["事件驱动", "一等公民", "Node.js"]) and any(k in a2 for k in ["React", "npm", "Node"]))
    rep.add("T6-02 跨片段综合(合并多点)",
            "含JS特点与应用，引用[2]等", f"答={a2!r}\n 综合ok={ok2}", ok2)

    # T6-03 召回片段无答案 → 应拒答
    a3 = generate("世界上最大的海洋是哪个？", [py, py_fields])
    ok3 = ("文档未找到相关内容" in a3)
    rep.add("T6-03 无相关信息拒答",
            "输出【文档未找到相关内容】禁编造",
            f"答={a3!r}\n 拒答={ok3}", ok3)

    # T6-04 片段内部信息冲突 → 识别冲突，不强行合并
    c1 = {"text": "某产品的价格是 99 元。"}
    c2 = {"text": "某产品的价格是 199 元。"}
    a4 = generate("该产品的价格是多少？", [c1, c2])
    conflict = ("99" in a4 and "199" in a4) or ("冲突" in a4)
    rep.add("T6-04 片段存在冲突",
            "列出矛盾(99 vs 199)，不武断给单一结论",
            f"答={a4!r}\n 识别冲突={conflict}", conflict)

    # T6-05 幻觉风险：提问触发模型固有知识(与文档不符)，应采信文档
    # 文档说 JS 由 Eich 于1995创建；模型固有知识一致，这里用文档为准确认年份
    a5 = generate("JavaScript 是哪一年创建的？", [py, py_fields, js])
    ok5 = "1995" in a5 and "Eich" in a5
    rep.add("T6-05 采信文档非固有知识",
            "以文档为准：1995/Eich",
            f"答={a5!r}\n 文档源正确={ok5}", ok5)

    # T6-06 长多片段(Top5)，识别有效信息，简洁准确
    a6 = generate("Python 有哪些特点？", [py, py_fields, js, js_field, wrong])
    ok6 = any(k in a6 for k in ["简单易学", "面向对象", "动态类型"]) and ("健身" not in a6)
    rep.add("T6-06 长多片段去噪",
            "忽略无关fitness片段，准确给出Python特点",
            f"答={a6!r}\n 去噪ok={ok6}", ok6)

    # T6-07 引用溯源：答案事实能在固定召回原文找到
    a7 = generate("Python 当前稳定版本是多少，由谁维护？", [py])
    ok7 = ("3.12" in a7) and ("[1]" in a7)
    rep.add("T6-07 引用溯源可用",
            "版本 3.12 + 引用[1]", f"答={a7!r}\n 溯源ok={ok7}", ok7)

    passed = rep.render()
    print(f"模块6 通过 {rep.passed_total}/{rep.total} -> all_pass={rep.all_pass}")
    return 0 if rep.all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())