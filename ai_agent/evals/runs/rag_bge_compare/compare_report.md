# RAG A/B Comparison Report

- Top-K: **5**
- Cases: **25**

## Overall

| Metric | Without Rerank | With Rerank | Δ |
|---|---|---|---|
| recall@5 | 100.00% | 100.00% | +0.00% |
| MRR | 0.9000 | 0.8400 | -0.0600 |
| Avg latency | 12ms | 8.6ms | -3ms |

## By difficulty

| Difficulty | Count | recall (no rerank) | recall (rerank) | MRR (no rerank) | MRR (rerank) |
|---|---|---|---|---|---|
| easy | 9 | 100.00% | 100.00% | 0.8333 | 0.7407 |
| hard | 4 | 100.00% | 100.00% | 1.0000 | 0.8750 |
| medium | 12 | 100.00% | 100.00% | 0.9167 | 0.9028 |

## Verdict

Rerank 影响微弱 (+0.00%)，可结合延迟决定是否启用。