"""sanity: Self-Check 单元测试 + 端到端 query 落盘"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import RAGModule, _facts_grounded, clean_text  # noqa: E402


# ---- 1. clean_text ----
def test_clean_text():
    raw = "Python 入门指南\u3000\u3000\r\n\r\n\r\n1. 简介\n\n\n\nPython\t是一种解释型语言。\n\r\n   多个   空格"
    cleaned = clean_text(raw)
    assert "\u3000" not in cleaned and "\t" not in cleaned and "\r" not in cleaned
    assert "\n\n\n" not in cleaned
    print("[OK] clean_text")


# ---- 2. _facts_grounded 正确情况 ----
def test_facts_grounded_ok():
    docs = [
        type("D", (), {"page_content": "Python 由 Guido van Rossum 于 1991 年发布。"})(),
    ]
    answer = "Python 由 Guido van Rossum 于 1991 年发布。"
    r = _facts_grounded(answer, docs)
    print(f"[grounded_ok] {r}")
    assert r["verdict"] == "ok"
    assert r["grounded_facts"] >= 1


# ---- 3. _facts_grounded block: 答案全是幻觉 ----
def test_facts_grounded_block():
    docs = [
        type("D", (), {"page_content": "Python 由 Guido van Rossum 于 1991 年发布。"})(),
    ]
    answer = "Java 由 James Gosling 于 1995 年发布，主要用于 Android 开发。"
    r = _facts_grounded(answer, docs)
    print(f"[grounded_block] {r}")
    assert r["verdict"] == "block"
    assert len(r["unsupported"]) >= 1


# ---- 4. 端到端: query + 日志 + Self-Check ----
def test_query_with_log():
    import os, json
    log_path = ROOT / "evals" / "logs" / "qa_log.jsonl"
    if log_path.exists():
        log_path.unlink()  # 清旧日志

    rag = RAGModule(model=None, embedding_model_type="local")
    assert rag.load_documents([str(ROOT / "knowledge_base" / "python_intro.txt")])

    # simulate 一条 "正常" 答案 + 一条 "幻觉" 答案
    # 直接调 _log_qa 验证日志落盘
    docs = rag.retrieve("Python 是什么时候发布的", top_k=3)
    rag._log_qa(
        query="Python 是什么时候发布的？",
        rewritten="Python 发布时间",
        retrieved=[RAGModule._doc_to_log_dict(d) for d in docs],
        answer="Python 由 Guido van Rossum 于 1991 年发布。",
        self_check=_facts_grounded("Python 由 Guido van Rossum 于 1991 年发布。", docs),
        final_answer="Python 由 Guido van Rossum 于 1991 年发布。",
    )
    assert log_path.exists(), "日志文件未生成"
    last = log_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    rec = json.loads(last)
    print("[log] last record keys:", list(rec.keys()))
    assert rec["query"] == "Python 是什么时候发布的？"
    assert rec["self_check"]["verdict"] == "ok"
    print("[OK] 日志 + Self-Check 落盘")


if __name__ == "__main__":
    test_clean_text()
    test_facts_grounded_ok()
    test_facts_grounded_block()
    test_query_with_log()
    print("\n[ALL OK]")