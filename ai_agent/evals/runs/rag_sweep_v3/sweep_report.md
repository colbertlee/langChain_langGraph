# RAG Weights Sweep Report

- Top-K: **5**
- Configs: **10**

## Results

| # | Config | recall@K | MRR | Latency |
|---|---|---|---|---|
| 1 | `vector_only_rerank` | 96.67% | 0.8944 | 4622.8ms ⭐ |
| 2 | `v0.7_b0.3_rerank` | 96.67% | 0.8944 | 3838.1ms |
| 3 | `v0.5_b0.5_rerank` | 96.67% | 0.8944 | 3832.7ms |
| 4 | `v0.3_b0.7_rerank` | 96.67% | 0.8944 | 7149.5ms |
| 5 | `bm25_only_rerank` | 96.67% | 0.8944 | 6970.6ms |
| 6 | `v0.3_b0.7_rerank_no` | 96.67% | 0.8511 | 2349.7ms |
| 7 | `v0.5_b0.5_rerank_no` | 93.33% | 0.8444 | 2351.7ms |
| 8 | `bm25_only_rerank_no` | 93.33% | 0.8417 | 2357.8ms |
| 9 | `vector_only_rerank_no` | 93.33% | 0.7889 | 2359.3ms |
| 10 | `v0.7_b0.3_rerank_no` | 93.33% | 0.7889 | 2354.5ms |

## All configs (run order)

| Config | recall@K | MRR | Latency |
|---|---|---|---|
| `vector_only_rerank_no` | 93.33% | 0.7889 | 2359.3ms |
| `vector_only_rerank` | 96.67% | 0.8944 | 4622.8ms |
| `v0.7_b0.3_rerank_no` | 93.33% | 0.7889 | 2354.5ms |
| `v0.7_b0.3_rerank` | 96.67% | 0.8944 | 3838.1ms |
| `v0.5_b0.5_rerank_no` | 93.33% | 0.8444 | 2351.7ms |
| `v0.5_b0.5_rerank` | 96.67% | 0.8944 | 3832.7ms |
| `v0.3_b0.7_rerank_no` | 96.67% | 0.8511 | 2349.7ms |
| `v0.3_b0.7_rerank` | 96.67% | 0.8944 | 7149.5ms |
| `bm25_only_rerank_no` | 93.33% | 0.8417 | 2357.8ms |
| `bm25_only_rerank` | 96.67% | 0.8944 | 6970.6ms |

## Recommendation

**Best: `vector_only_rerank`** → recall=96.67%, MRR=0.8944