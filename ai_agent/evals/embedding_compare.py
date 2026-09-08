"""
Embedding 模型对比：v1 vs v2-moe vs qwen3-embedding
跑同一份评估集，看哪个 recall/MRR 最高
"""
import os
import sys
import time
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import RAGModule


# 默认对比 3 个模型，可用 --model / --models 覆盖
ALL_MODELS = [
    ("nomic-embed-text", "nomic-v1"),
    ("nomic-embed-text-v2-moe", "nomic-v2-moe"),
    ("qwen3-embedding:4b", "qwen3-4b"),
]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", default=None,
                        help="指定单个模型 ollama tag（可多次传），不传则跑全部 3 个")
    parser.add_argument("--queries", default=None,
                        help="评估集 JSONL（默认 v3）")
    args = parser.parse_args()

    if args.model:
        # 短标签映射
        label_map = {m[0]: m[1] for m in ALL_MODELS}
        MODELS = []
        for m in args.model:
            label = label_map.get(m, m.replace(":", "_").replace("-", "_"))
            MODELS.append((m, label))
    else:
        MODELS = ALL_MODELS

    kb_dir = ROOT / "knowledge_base"
    files = [str(p) for p in kb_dir.rglob("*.txt")]

    # 评估集
    queries_path = Path(args.queries) if args.queries else (ROOT / "evals" / "rag_eval_set_v3.jsonl")
    cases = []
    with queries_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                cases.append(json.loads(line))

    # 复用 evaluate + aggregate（import from rag_eval）
    sys.path.insert(0, str(ROOT / "evals"))
    from rag_eval import evaluate, aggregate

    rows = []
    for ollama_model, label in MODELS:
        print("\n" + "=" * 60)
        print(f"[{label}] ollama_model={ollama_model}")
        print("=" * 60)
        # 必须在创建 RAGModule 前设置环境变量
        os.environ["OLLAMA_MODEL"] = ollama_model

        rag = RAGModule(model=None, embedding_model_type="ollama", use_cache=False)
        t0 = time.time()
        ok = rag.load_documents(files, use_rerank=True, rerank_top_n=5)
        if not ok:
            print(f"[SKIP] {ollama_model} load failed")
            continue
        load_time = int((time.time() - t0) * 1000)
        print(f"[INFO] Indexed {len(rag.all_split_docs)} chunks in {load_time}ms")

        t0 = time.time()
        results = evaluate(rag, cases, top_k=5)
        eval_time = int((time.time() - t0) * 1000)

        summary = aggregate(results)
        summary["label"] = label
        summary["ollama_model"] = ollama_model
        summary["load_time_ms"] = load_time
        summary["eval_time_ms"] = eval_time
        rows.append((label, summary))

        print(f"[{label}] recall@5={summary['recall_at_k']:.2%}  "
              f"MRR={summary['mrr']:.4f}  load={load_time}ms  eval={eval_time}ms")

    print("\n" + "=" * 60)
    print("===== Embedding Model Comparison =====")
    print("=" * 60)
    print(f"{'Model':25s} {'recall@5':>10s} {'MRR':>8s} {'Load':>8s} {'Eval':>8s}")
    print("-" * 60)
    for label, s in sorted(rows, key=lambda x: x[1]["mrr"], reverse=True):
        print(f"{label:25s} {s['recall_at_k']:>9.2%} {s['mrr']:>8.4f} "
              f"{s['load_time_ms']:>6d}ms {s['eval_time_ms']:>6d}ms")

    if rows:
        best = max(rows, key=lambda x: x[1]["mrr"])
        print(f"\n⭐ Best: {best[0]} (MRR={best[1]['mrr']:.4f})")


if __name__ == "__main__":
    main()
