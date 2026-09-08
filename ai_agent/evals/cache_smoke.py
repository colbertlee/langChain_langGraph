"""
缓存冒烟测试：同一 query 跑两次，第二次应该命中缓存、延迟显著降低
"""
import os
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ollama 模型
os.environ.setdefault("OLLAMA_MODEL", "nomic-embed-text")

from rag import RAGModule  # noqa


def main():
    rag = RAGModule(model=None, embedding_model_type="ollama", use_cache=True)

    kb_dir = ROOT / "knowledge_base"
    files = [str(p) for p in kb_dir.rglob("*.txt")]
    rag.load_documents(files, use_rerank=True, rerank_top_n=5)

    queries = [
        "Python 是什么？",
        "Python 用于 Web 开发的框架有哪些？",
        "Python 是什么？",        # 重复
        "Python 是什么？",        # 再重复
        "Python 在 AI 领域用哪些框架？",
        "Python 用于 Web 开发的框架有哪些？",  # 重复
    ]

    print("\n--- Cold pass (no cache) ---")
    for i, q in enumerate(queries, 1):
        t0 = time.time()
        docs = rag.retrieve(q, top_k=5)
        elapsed = int((time.time() - t0) * 1000)
        print(f"  [{i}] {elapsed:4d}ms  q={q!r}")
        # 显式列缓存状态（每 2 条 query 打印一次）
        if i % 2 == 0:
            print("      cache:", rag.cache_stats())

    print("\n--- Final cache stats ---")
    print(rag.cache_stats())


if __name__ == "__main__":
    main()
