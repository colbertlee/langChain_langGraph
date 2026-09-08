# RAG Weights Sweep Report

- Top-K: **5**
- Configs: **10**

## Results

| # | Config | recall@K | MRR | Latency |
|---|---|---|---|---|
| 1 | `vector_only_rerank` | 100.00% | 0.9250 | 3819.8ms ⭐ |
| 2 | `v0.7_b0.3_rerank` | 100.00% | 0.9250 | 2879.5ms |
| 3 | `v0.5_b0.5_rerank` | 100.00% | 0.9250 | 2867.3ms |
| 4 | `v0.3_b0.7_rerank` | 100.00% | 0.9250 | 2861.9ms |
| 5 | `bm25_only_rerank` | 100.00% | 0.9250 | 2882.6ms |
| 6 | `bm25_only_rerank_no` | 100.00% | 0.9000 | 2329.9ms |
| 7 | `v0.5_b0.5_rerank_no` | 100.00% | 0.8706 | 2339.3ms |
| 8 | `v0.3_b0.7_rerank_no` | 100.00% | 0.8694 | 2335.4ms |
| 9 | `vector_only_rerank_no` | 100.00% | 0.8678 | 2328.3ms |
| 10 | `v0.7_b0.3_rerank_no` | 100.00% | 0.8678 | 2337.3ms |

## All configs (run order)

| Config | recall@K | MRR | Latency |
|---|---|---|---|
| `vector_only_rerank_no` | 100.00% | 0.8678 | 2328.3ms |
| `vector_only_rerank` | 100.00% | 0.9250 | 3819.8ms |
| `v0.7_b0.3_rerank_no` | 100.00% | 0.8678 | 2337.3ms |
| `v0.7_b0.3_rerank` | 100.00% | 0.9250 | 2879.5ms |
| `v0.5_b0.5_rerank_no` | 100.00% | 0.8706 | 2339.3ms |
| `v0.5_b0.5_rerank` | 100.00% | 0.9250 | 2867.3ms |
| `v0.3_b0.7_rerank_no` | 100.00% | 0.8694 | 2335.4ms |
| `v0.3_b0.7_rerank` | 100.00% | 0.9250 | 2861.9ms |
| `bm25_only_rerank_no` | 100.00% | 0.9000 | 2329.9ms |
| `bm25_only_rerank` | 100.00% | 0.9250 | 2882.6ms |

## Recommendation

**Best: `vector_only_rerank`** → recall=100.00%, MRR=0.9250