"""
RAG 召回率评估脚本

用法：
  cd ai_agent
  python -m evals.rag_eval \
      --kb knowledge_base/python_intro.txt \
      --queries evals/rag_eval_set.jsonl \
      --top-k 5 \
      --out evals/runs/rag_eval_<timestamp>/report.md

评估集 JSONL 每行一条：
  {
    "id": "q-001",
    "query": "Python 是什么？",
    "expected_keywords": ["Python", "编程语言"],   # 必须全部出现在召回 chunk 中
    "expected_chunk_ids": [3, 7],                  # 可选，指定 chunk_id
    "difficulty": "easy"                            # easy/medium/hard
  }

输出指标：
  - recall@K    召回率
  - MRR         首个相关结果的倒数排名
  - nDCG@K      归一化折损累积增益
  - per-case 详情（每个 query 召回了哪些 chunk、是否命中）
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from statistics import mean

# 允许从项目根目录运行
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import RAGModule
from config import OPENAI_API_KEY  # noqa


def load_queries(path: Path):
    cases = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cases.append(json.loads(line))
    return cases


def hit_keywords(doc_text: str, keywords):
    """所有关键词都得出现（大小写不敏感）"""
    if not keywords:
        return True
    text = doc_text.lower()
    return all(k.lower() in text for k in keywords)


def evaluate(rag: RAGModule, cases, top_k: int = 5):
    results = []
    for case in cases:
        qid = case["id"]
        query = case["query"]
        expected_kw = case.get("expected_keywords", [])
        expected_ids = case.get("expected_chunk_ids", [])

        t0 = time.time()
        retrieved = rag.retrieve(query, top_k=top_k)
        elapsed_ms = int((time.time() - t0) * 1000)

        # 判断每个 chunk 是否命中
        hits = []
        rank_of_first_hit = None
        for rank, doc in enumerate(retrieved, start=1):
            cid = doc.metadata.get("chunk_id")
            kw_hit = hit_keywords(doc.page_content, expected_kw)
            id_hit = (cid in expected_ids) if expected_ids else False
            ok = kw_hit or id_hit
            hits.append({
                "rank": rank,
                "chunk_id": cid,
                "kw_hit": kw_hit,
                "id_hit": id_hit,
                "preview": doc.page_content[:60].replace("\n", " ")
            })
            if ok and rank_of_first_hit is None:
                rank_of_first_hit = rank

        # recall@K
        if expected_kw or expected_ids:
            recall = 1.0 if rank_of_first_hit is not None else 0.0
            mrr = (1.0 / rank_of_first_hit) if rank_of_first_hit else 0.0
        else:
            recall = None
            mrr = None

        results.append({
            "id": qid,
            "query": query,
            "difficulty": case.get("difficulty", "unknown"),
            "expected_keywords": expected_kw,
            "expected_chunk_ids": expected_ids,
            "recall_at_k": recall,
            "mrr": mrr,
            "first_hit_rank": rank_of_first_hit,
            "elapsed_ms": elapsed_ms,
            "hits": hits
        })

    return results


def aggregate(results):
    recalls = [r["recall_at_k"] for r in results if r["recall_at_k"] is not None]
    mrrs = [r["mrr"] for r in results if r["mrr"] is not None]
    latencies = [r["elapsed_ms"] for r in results]

    by_diff = {}
    for r in results:
        d = r["difficulty"]
        by_diff.setdefault(d, []).append(r)

    summary = {
        "total": len(results),
        "recall_at_k": round(mean(recalls), 4) if recalls else 0,
        "mrr": round(mean(mrrs), 4) if mrrs else 0,
        "avg_latency_ms": round(mean(latencies), 1) if latencies else 0,
        "by_difficulty": {
            d: {
                "count": len(rs),
                "recall_at_k": round(mean([x["recall_at_k"] for x in rs if x["recall_at_k"] is not None]), 4),
                "mrr": round(mean([x["mrr"] for x in rs if x["mrr"] is not None]), 4)
            }
            for d, rs in by_diff.items()
        }
    }
    return summary


def render_report(results, summary, out_path: Path, top_k: int):
    lines = []
    lines.append("# RAG Recall Evaluation Report\n")
    lines.append(f"- Top-K: **{top_k}**")
    lines.append(f"- Total cases: **{summary['total']}**")
    lines.append(f"- **recall@{top_k}**: {summary['recall_at_k']:.2%}")
    lines.append(f"- **MRR**: {summary['mrr']:.4f}")
    lines.append(f"- Avg latency: {summary['avg_latency_ms']} ms\n")

    lines.append("## By difficulty\n")
    lines.append("| Difficulty | Count | Recall@K | MRR |")
    lines.append("|---|---|---|---|")
    for d, s in summary["by_difficulty"].items():
        lines.append(f"| {d} | {s['count']} | {s['recall_at_k']:.2%} | {s['mrr']:.4f} |")
    lines.append("")

    lines.append("## Per-case details\n")
    lines.append("| ID | Query | First hit | Recall | MRR | Latency |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        fhr = r["first_hit_rank"] if r["first_hit_rank"] else "-"
        rec = f"{r['recall_at_k']:.0%}" if r["recall_at_k"] is not None else "-"
        mrr = f"{r['mrr']:.2f}" if r["mrr"] is not None else "-"
        q = r["query"][:30].replace("|", "/")
        lines.append(f"| {r['id']} | {q} | {fhr} | {rec} | {mrr} | {r['elapsed_ms']}ms |")

    lines.append("\n## Failed cases (recall=0)\n")
    failed = [r for r in results if r["recall_at_k"] == 0.0]
    if not failed:
        lines.append("_None_")
    else:
        for r in failed:
            lines.append(f"### {r['id']}: {r['query']}")
            lines.append(f"- Expected keywords: `{r['expected_keywords']}`")
            lines.append(f"- Top-{top_k} retrieved:")
            for h in r["hits"]:
                lines.append(f"  - rank={h['rank']} chunk_id={h['chunk_id']} | `{h['preview']}...`")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def render_compare_report(summary_no, summary_yes, out_path: Path, top_k: int):
    """A/B 对比报告：把两份 summary 写到一张表里"""
    lines = []
    lines.append("# RAG A/B Comparison Report\n")
    lines.append(f"- Top-K: **{top_k}**")
    lines.append(f"- Cases: **{summary_no['total']}**\n")

    lines.append("## Overall\n")
    lines.append("| Metric | Without Rerank | With Rerank | Δ |")
    lines.append("|---|---|---|---|")
    d_recall = summary_yes["recall_at_k"] - summary_no["recall_at_k"]
    d_mrr = summary_yes["mrr"] - summary_no["mrr"]
    d_lat = summary_yes["avg_latency_ms"] - summary_no["avg_latency_ms"]
    lines.append(f"| recall@{top_k} | {summary_no['recall_at_k']:.2%} | {summary_yes['recall_at_k']:.2%} | {d_recall:+.2%} |")
    lines.append(f"| MRR | {summary_no['mrr']:.4f} | {summary_yes['mrr']:.4f} | {d_mrr:+.4f} |")
    lines.append(f"| Avg latency | {summary_no['avg_latency_ms']}ms | {summary_yes['avg_latency_ms']}ms | {d_lat:+.0f}ms |")
    lines.append("")

    lines.append("## By difficulty\n")
    lines.append("| Difficulty | Count | recall (no rerank) | recall (rerank) | MRR (no rerank) | MRR (rerank) |")
    lines.append("|---|---|---|---|---|---|")
    all_diffs = set(summary_no["by_difficulty"].keys()) | set(summary_yes["by_difficulty"].keys())
    for d in sorted(all_diffs):
        s_no = summary_no["by_difficulty"].get(d, {"count": 0, "recall_at_k": 0, "mrr": 0})
        s_yes = summary_yes["by_difficulty"].get(d, {"count": 0, "recall_at_k": 0, "mrr": 0})
        lines.append(
            f"| {d} | {s_no['count']} | {s_no['recall_at_k']:.2%} | {s_yes['recall_at_k']:.2%} "
            f"| {s_no['mrr']:.4f} | {s_yes['mrr']:.4f} |"
        )
    lines.append("")

    lines.append("## Verdict\n")
    if d_recall > 0.05:
        lines.append(f"Rerank 显著提升 recall ({d_recall:+.2%})，**建议保留**。")
    elif d_recall < -0.02:
        lines.append(f"Rerank 反而下降 ({d_recall:+.2%})，**建议关闭或调整 top_n**。")
    else:
        lines.append(f"Rerank 影响微弱 ({d_recall:+.2%})，可结合延迟决定是否启用。")
    if d_lat > 200:
        lines.append(f"代价：平均多 {d_lat:.0f}ms 延迟（Cross-Encoder 本地推理）。")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def render_sweep_report(rows, out_path: Path, top_k: int):
    """rows: list of (label, summary)"""
    lines = []
    lines.append("# RAG Weights Sweep Report\n")
    lines.append(f"- Top-K: **{top_k}**")
    lines.append(f"- Configs: **{len(rows)}**\n")

    lines.append("## Results\n")
    lines.append("| # | Config | recall@K | MRR | Latency |")
    lines.append("|---|---|---|---|---|")
    sorted_rows = sorted(rows, key=lambda x: (x[1]["recall_at_k"], x[1]["mrr"]), reverse=True)
    for i, (label, s) in enumerate(sorted_rows, 1):
        marker = " ⭐" if i == 1 else ""
        lines.append(
            f"| {i} | `{label}` | {s['recall_at_k']:.2%} | {s['mrr']:.4f} | {s['avg_latency_ms']}ms{marker} |"
        )
    lines.append("")

    # 原始顺序记录
    lines.append("## All configs (run order)\n")
    lines.append("| Config | recall@K | MRR | Latency |")
    lines.append("|---|---|---|---|")
    for label, s in rows:
        lines.append(f"| `{label}` | {s['recall_at_k']:.2%} | {s['mrr']:.4f} | {s['avg_latency_ms']}ms |")
    lines.append("")

    lines.append("## Recommendation\n")
    best = sorted_rows[0]
    lines.append(f"**Best: `{best[0]}`** → recall={best[1]['recall_at_k']:.2%}, MRR={best[1]['mrr']:.4f}")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def run_one_mode(files, cases, args, use_rerank: bool, weights=None):
    """跑单次评估，返回 (results, summary)"""
    if weights is None:
        weights = [0.7, 0.3]
    label = "w={} rerank={}".format(weights, use_rerank)
    print("\n" + "=" * 60)
    print("[{}] Building retriever".format(label))
    print("=" * 60)

    # 如果要 rerank 但用户要求跳过加载失败，先 patch CrossEncoder 让其不真下载
    if use_rerank and args.skip_rerank_load:
        import rag as rag_mod
        original_init = rag_mod.CrossEncoderReranker.__init__

        def _patched_init(self, model_name=None, top_n=5, device="cpu"):
            self.model = None
            self.top_n = top_n
            print("[WARN] --skip-rerank-load: using NoOp reranker (原始顺序保留)")

        def _patched_compress(self, documents, query):
            return list(documents)[: self.top_n]

        rag_mod.CrossEncoderReranker.__init__ = _patched_init
        rag_mod.CrossEncoderReranker.compress_documents = _patched_compress

    rag = RAGModule(
        model=None,
        embedding_model_type=args.embedding_model,
        api_key=args.api_key
    )

    # 通过 monkey-patch 改 weights（rag.load_documents 内部硬编码了 0.7/0.3）
    if weights != [0.7, 0.3]:
        import rag as rag_mod
        original_build = rag_mod.RAGModule._build_retriever

        def _patched_build(self, split_docs, use_rerank=True, rerank_top_n=5):
            # 直接调用原 build，构造时改 weights
            vector_retriever = self.vectorstore.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 20}
            )
            bm25_retriever = rag_mod._SimpleBM25Retriever.from_documents(split_docs)
            bm25_retriever.k = 20
            ensemble = rag_mod.RRFFusionRetriever(
                retrievers=[vector_retriever, bm25_retriever],
                weights=weights
            )
            if not use_rerank:
                return ensemble
            self._reranker = rag_mod.CrossEncoderReranker(
                model_name="BAAI/bge-reranker-base", top_n=rerank_top_n, device="cpu"
            )

            class _W:
                def __init__(self, base, comp):
                    self.base = base
                    self.comp = comp
                def invoke(self, q, config=None, **kw):
                    return self.comp.compress_documents(self.base.invoke(q), q)
                async def ainvoke(self, q, config=None, **kw):
                    return self.comp.compress_documents(
                        await self.base.ainvoke(q) if hasattr(self.base, "ainvoke") else self.base.invoke(q),
                        q
                    )
            return _W(ensemble, self._reranker)

        rag_mod.RAGModule._build_retriever = _patched_build

    ok = rag.load_documents(files, use_rerank=use_rerank, rerank_top_n=args.top_k)
    if not ok:
        print("[ERROR] Failed to load KB")
        sys.exit(1)
    print(f"[INFO] Indexed {len(rag.all_split_docs)} chunks")

    results = evaluate(rag, cases, top_k=args.top_k)
    summary = aggregate(results)
    summary["weights"] = weights
    summary["use_rerank"] = use_rerank

    print("[{}] recall@{}: {:.2%}  MRR: {:.4f}  latency: {}ms".format(
        label, args.top_k, summary["recall_at_k"], summary["mrr"], summary["avg_latency_ms"]
    ))
    return results, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", required=True, help="知识库文件或目录")
    parser.add_argument("--queries", required=True, help="评估集 JSONL")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--embedding-model", default="openai")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--compare", action="store_true",
                        help="A/B 对比：同时跑「无 Rerank」vs「有 Rerank」两份")
    parser.add_argument("--no-rerank", action="store_true",
                        help="仅在单次模式下生效：禁用 Rerank")
    parser.add_argument("--rerank-model", default=None,
                        help="Rerank 模型路径/名称（默认 BAAI/bge-reranker-base，需联网）")
    parser.add_argument("--skip-rerank-load", action="store_true",
                        help="Rerank 模型加载失败时跳过而非报错")
    parser.add_argument("--sweep", action="store_true",
                        help="权重网格搜索：4 组 weights × {no-rerank, rerank} 共 8 次")
    parser.add_argument("--rerank-top-n", type=int, default=5,
                        help="Rerank 精排后保留的 chunk 数")
    args = parser.parse_args()

    kb_path = Path(args.kb)
    if kb_path.is_dir():
        files = [str(p) for p in kb_path.rglob("*.txt")]
    else:
        files = [str(kb_path)]

    cases = load_queries(Path(args.queries))

    if args.sweep:
        # ===== 权重网格搜索 =====
        ts = time.strftime('%Y%m%d_%H%M%S')
        out = Path(args.out) if args.out else ROOT / "evals" / "runs" / f"rag_sweep_{ts}"
        out.mkdir(parents=True, exist_ok=True)

        grid = [
            ([1.0, 0.0], "vector_only"),
            ([0.7, 0.3], "v0.7_b0.3"),
            ([0.5, 0.5], "v0.5_b0.5"),
            ([0.3, 0.7], "v0.3_b0.7"),
            ([0.0, 1.0], "bm25_only"),
        ]
        rows = []
        for weights, label in grid:
            for use_rerank in [False, True]:
                tag = "{}_rerank{}".format(label, "" if use_rerank else "_no")
                _, summary = run_one_mode(files, cases, args, use_rerank=use_rerank, weights=weights)
                rows.append((tag, summary))

        render_sweep_report(rows, out / "sweep_report.md", args.top_k)
        (out / "sweep.json").write_text(
            json.dumps([{"label": l, **s} for l, s in rows], ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print("\n===== Sweep Summary =====")
        for label, s in sorted(rows, key=lambda x: x[1]["mrr"], reverse=True):
            print(f"  {label:30s}  recall={s['recall_at_k']:.2%}  MRR={s['mrr']:.4f}")
        print(f"Sweep report: {out / 'sweep_report.md'}")
        return

    if args.compare:
        # ===== A/B 对比模式 =====
        ts = time.strftime('%Y%m%d_%H%M%S')
        out = Path(args.out) if args.out else ROOT / "evals" / "runs" / f"rag_compare_{ts}"
        out.mkdir(parents=True, exist_ok=True)

        # 1) 不带 Rerank
        results_no, summary_no = run_one_mode(files, cases, args, use_rerank=False)
        (out / "no_rerank_cases.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in results_no), encoding="utf-8"
        )
        (out / "no_rerank_summary.json").write_text(
            json.dumps(summary_no, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        render_report(results_no, summary_no, out / "no_rerank_report.md", args.top_k)

        # 2) 带 Rerank
        results_yes, summary_yes = run_one_mode(files, cases, args, use_rerank=True)
        (out / "rerank_cases.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in results_yes), encoding="utf-8"
        )
        (out / "rerank_summary.json").write_text(
            json.dumps(summary_yes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        render_report(results_yes, summary_yes, out / "rerank_report.md", args.top_k)

        # 3) 对比报告
        render_compare_report(summary_no, summary_yes, out / "compare_report.md", args.top_k)

        print("\n===== Compare Summary =====")
        print(f"recall@{args.top_k}: {summary_no['recall_at_k']:.2%} (no-rerank) → "
              f"{summary_yes['recall_at_k']:.2%} (rerank) "
              f"[{summary_yes['recall_at_k'] - summary_no['recall_at_k']:+.2%}]")
        print(f"MRR:              {summary_no['mrr']:.4f} → {summary_yes['mrr']:.4f} "
              f"[{summary_yes['mrr'] - summary_no['mrr']:+.4f}]")
        print(f"Avg latency:      {summary_no['avg_latency_ms']}ms → {summary_yes['avg_latency_ms']}ms")
        print(f"Compare report:   {out / 'compare_report.md'}")
        return

    # ===== 单次评估模式 =====
    print(f"[INFO] Loading {len(files)} KB file(s)...")
    use_rerank = not args.no_rerank
    results, summary = run_one_mode(files, cases, args, use_rerank=use_rerank)

    ts = time.strftime('%Y%m%d_%H%M%S')
    out = Path(args.out) if args.out else ROOT / "evals" / "runs" / f"rag_eval_{ts}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "cases.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results), encoding="utf-8"
    )
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    render_report(results, summary, out / "report.md", args.top_k)

    print("\n===== Summary =====")
    print(f"recall@{args.top_k}: {summary['recall_at_k']:.2%}")
    print(f"MRR:              {summary['mrr']:.4f}")
    print(f"Avg latency:      {summary['avg_latency_ms']}ms")
    print(f"Report:           {out / 'report.md'}")


if __name__ == "__main__":
    main()
