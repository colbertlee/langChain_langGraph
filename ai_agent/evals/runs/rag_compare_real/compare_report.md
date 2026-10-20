# RAG A/B Comparison Report

- Top-K: **5**
- Cases: **25**

## Overall

| Metric | Without Rerank | With Rerank | Δ |
|---|---|---|---|
| recall@5 | 100.00% | 100.00% | +0.00% |
| MRR | 0.9800 | 0.9400 | -0.0400 |
| Avg latency | 1.7ms | 467.4ms | +466ms |

## By difficulty

| Difficulty | Count | recall (no rerank) | recall (rerank) | MRR (no rerank) | MRR (rerank) |
|---|---|---|---|---|---|
| easy | 9 | 100.00% | 100.00% | 0.9444 | 1.0000 |
| hard | 4 | 100.00% | 100.00% | 1.0000 | 1.0000 |
| medium | 12 | 100.00% | 100.00% | 1.0000 | 0.8750 |

## Verdict

Rerank 影响微弱 (+0.00%)，可结合延迟决定是否启用。
代价：平均多 466ms 延迟（Cross-Encoder 本地推理）。