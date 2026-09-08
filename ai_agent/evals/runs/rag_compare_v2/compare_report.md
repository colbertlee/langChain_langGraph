# RAG A/B Comparison Report

- Top-K: **5**
- Cases: **30**

## Overall

| Metric | Without Rerank | With Rerank | Δ |
|---|---|---|---|
| recall@5 | 100.00% | 100.00% | +0.00% |
| MRR | 0.8917 | 0.9250 | +0.0333 |
| Avg latency | 2348.2ms | 2927.3ms | +579ms |

## By difficulty

| Difficulty | Count | recall (no rerank) | recall (rerank) | MRR (no rerank) | MRR (rerank) |
|---|---|---|---|---|---|
| easy | 9 | 100.00% | 100.00% | 1.0000 | 1.0000 |
| hard | 9 | 100.00% | 100.00% | 0.7685 | 0.8611 |
| medium | 12 | 100.00% | 100.00% | 0.9028 | 0.9167 |

## Verdict

Rerank 影响微弱 (+0.00%)，可结合延迟决定是否启用。
代价：平均多 579ms 延迟（Cross-Encoder 本地推理）。