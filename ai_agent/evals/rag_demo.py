"""
rag_demo.py — 方案A：最小可运行 RAG Demo（自包含，用于定位跑偏根因）
========================================================================
流水线：txt 读取 → 文本清洗 → 段落优先切片 → BGE Embedding
        → BM25 + 向量 混合检索 → RRF 融合 → bge-reranker 重排
        → 强约束 Prompt → LLM 生成 → Self-Check 事实溯源

设计原则（对应"分离测试"）：
  * --mode recall  只打印召回片段，不调用 LLM —— 单独验检索
  * --mode chunks  打印全部切片 —— 单独验切片质量
  * --mode full    完整链路（无 API Key 时自动只打印 Prompt+召回）

零依赖保证：
  * sentence-transformers 不可用 / 未下载模型 → 自动降级内置 TF-IDF 向量（召回仍可测）
  * 未配置 LLM API Key → 跳过生成，仅打印强约束 Prompt + 召回片段

用法：
  cd ai_agent
  python -m evals.rag_demo --kb knowledge_base --mode recall
  python -m evals.rag_demo --kb knowledge_base --query "Python 什么时候发布的？" --mode full
  python -m evals.rag_demo --kb knowledge_base --mode chunks --show-chunks 3
"""
import argparse
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

# ============================================================
# 1) 文本清洗
# ============================================================

def clean_text(text: str) -> str:
    """去 BOM/NUL/CRLF 归一化/全角空格/制表符/连续 3+ 换行；保留 \\n\\n 段落边界。"""
    if not text:
        return text
    text = text.lstrip("\ufeff").replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufffd", " ")
    text = text.replace("\u3000", " ").replace("\t", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)      # 只压缩 3+ 换行，2 个换行是段落边界
    text = re.sub(r"[ \t]{2,}", " ", text)
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        text = text.replace(ch, "")
    return text.strip()


# ============================================================
# 2) 段落优先切片
# ============================================================

def rough_tokens(text: str) -> float:
    """粗略 token 估算：中文按 1 字≈1 token，英文按 1.5 token/词。"""
    zh = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[a-zA-Z0-9]+", text))
    return zh + en * 1.5


def _split_sentences(para: str):
    """句子边界拆分（保留标点）。"""
    return [p for p in re.split(r"(?<=[。！？!?；;])|\n", para) if p.strip()]


def overlap_tail(text: str, n: int) -> str:
    """取末尾 n 字符做 overlap，尽量从句子边界开始。"""
    s = text[-n:]
    idx = s.find("。")
    return s[idx + 1:] if 0 < idx < len(s) // 2 else s


def chunk_paragraph_first(text: str, chunk_size: int = 600,
                          overlap: int = 80, max_tokens: int = 500):
    """段落优先切片，禁止句中硬切。

    主切分标准是字符 chunk_size（小文件不会整块吞）；
    rough_tokens 仅作硬上限兜底（防止超 Embedding 模型上下文被截断）。
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf = [], ""
    for para in paras:
        # 单个段落本身超限 → 独立成块，仅在句子边界拆
        if rough_tokens(para) > max_tokens or len(para) > chunk_size:
            if buf:
                chunks.append(buf)
                buf = ""
            sub = ""
            for sent in _split_sentences(para):
                if sub and (rough_tokens(sub) + rough_tokens(sent) > max_tokens
                            or len(sub) + len(sent) > chunk_size):
                    chunks.append(sub)
                    sub = ""
                sub = (sub + "\n" + sent) if sub else sent
            if sub:
                chunks.append(sub)
            continue
        # 普通段落：并入当前块；按字符长度优先切开，带上小块 overlap
        if buf and (rough_tokens(buf) + rough_tokens(para) > max_tokens
                    or len(buf) + len(para) > chunk_size):
            chunks.append(buf)
            buf = overlap_tail(buf, overlap)
        buf = (buf + "\n\n" + para) if buf else para
    if buf:
        chunks.append(buf)
    return chunks


# ============================================================
# 3) Embedding（BGE 优先，TF-IDF 兜底）
# ============================================================

def _tokenize(text: str):
    """中英文混合分词：英文词 + 中文单字 + 二元（BM25 与 TF-IDF 共用）。"""
    text = text.lower()
    en = re.findall(r"[a-z0-9]+", text)
    zh = re.findall(r"[\u4e00-\u9fff]", text)
    big = ["".join(zh[i:i + 2]) for i in range(len(zh) - 1)]
    return en + zh + big


class TfidfEmbeddings:
    """零依赖兜底：中文混合 TF-IDF + L2 归一化。"""
    def __init__(self):
        self.vocab, self.idf, self._docs_tokens = {}, {}, []

    def fit(self, texts):
        self._docs_tokens = [_tokenize(t) for t in texts]
        df = defaultdict(int)
        for toks in self._docs_tokens:
            for t in set(toks):
                df[t] += 1
        n = len(self._docs_tokens)
        self.vocab = {t: i for i, t in enumerate(sorted(df))}
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}

    def _vec(self, tokens):
        vec = [0.0] * len(self.vocab)
        for t, c in Counter(tokens).items():
            if t in self.vocab:
                vec[self.vocab[t]] = c * self.idf[t]
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts):
        self.fit(texts)
        return [self._vec(t) for t in self._docs_tokens]

    def embed_query(self, text):
        return self._vec(_tokenize(text))


class BgeEmbeddings:
    """BGE 中文 Embedding。query 加指令前缀（BGE 官方建议），文档不加。"""
    QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        from sentence_transformers import SentenceTransformer
        print(f"[embed] 加载 {model_name}（首次运行需联网下载权重）...")
        self.model = SentenceTransformer(model_name)
        print("[embed] 加载完成")

    def _enc(self, texts):
        return self.model.encode(texts, normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=False)

    def embed_documents(self, texts):
        return self._enc(texts)

    def embed_query(self, text):
        return self._enc([self.QUERY_INSTRUCTION + text])[0]


# ============================================================
# 4) BM25 + 向量 RRF 融合检索
# ============================================================

class DemoIndex:
    def __init__(self, chunks, embedder):
        self.embedder = embedder
        self.chunks = chunks
        self.vectors = (np.array(embedder.embed_documents(chunks)) if np is not None else None)
        self.doc_tokens = [_tokenize(c) for c in chunks]
        self.doc_lens = [len(t) for t in self.doc_tokens]
        self.avg_len = (sum(self.doc_lens) / len(self.doc_lens)) if self.doc_lens else 1.0
        self.df = Counter(t for toks in self.doc_tokens for t in set(toks))
        self.n = len(chunks)

    def vector_top(self, qvec, k):
        if self.vectors is None:
            return []
        dots = self.vectors @ qvec
        idx = dots.argsort()[::-1][:k]
        return [(int(i), float(dots[i])) for i in idx]

    def bm25_top(self, query, k):
        qt = _tokenize(query)
        scored = []
        for i, (toks, dl) in enumerate(zip(self.doc_tokens, self.doc_lens)):
            tf = Counter(toks)
            s = 0.0
            for q in set(qt):
                f = tf.get(q, 0)
                if not f:
                    continue
                idf = math.log((self.n - self.df.get(q, 0) + 0.5) / (self.df.get(q, 0) + 0.5) + 1.0)
                denom = f + 1.5 * (1 - 0.75 + 0.75 * dl / self.avg_len)
                s += idf * f * (1.5 + 1) / denom
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [(i, s) for s, i in scored[:k]]

    def rrf_fuse(self, query, k_vec=12, k_bm=12, rrf_k=60, weights=(0.5, 0.5)):
        """RRF 融合：final = Σ w/(k+rank)。"""
        vres = self.vector_top(self.embedder.embed_query(query), k_vec)
        bres = self.bm25_top(query, k_bm)
        acc = defaultdict(float)
        for rank, (i, _) in enumerate(vres, 1):
            acc[i] += weights[0] / (rrf_k + rank)
        for rank, (i, _) in enumerate(bres, 1):
            acc[i] += weights[1] / (rrf_k + rank)
        return sorted(acc.items(), key=lambda x: x[1], reverse=True)


# ============================================================
# 5) Cross-Encoder Rerank
# ============================================================

def rerank_cross(query, results, chunks, top_n=5,
                 model_name="BAAI/bge-reranker-base"):
    """results: [(chunk_idx, rrf_score)] → 重排后 [(idx, rerank_score)]；不可用则原序返回。"""
    try:
        from sentence_transformers import CrossEncoder
        ce = CrossEncoder(model_name)
        pairs = [[query, chunks[i]] for i, _ in results]
        scores = [float(s) for s in ce.predict(pairs)]
    except Exception as e:
        print(f"[warn] rerank 不可用（{e}），保留 RRF 融合排序")
        return results[:top_n]
    scored = sorted(zip([i for i, _ in results], scores), key=lambda x: -x[1])
    return scored[:top_n]


# ============================================================
# 6) 强约束 Prompt + LLM 生成 + Self-Check
# ============================================================

STRONG_PROMPT = """你是文档问答助手，严格遵守下面所有规则：
1. 只能使用【参考文档片段】内提供的信息回答用户问题。绝对不能使用你自身知识库的内容；
2. 如果参考文档里没有足够信息回答问题，直接回复：【文档未找到相关内容】，禁止猜测、编造；
3. 回答内容必须可追溯到参考片段，禁止推理出原文不存在的结论；
4. 如果多个参考片段信息冲突，列出冲突点，并说明无法确定；
5. 回答时引用片段编号 [1][2]。

【参考文档片段】
{context}

用户问题：{query}"""


def format_context(indexes, chunks):
    return "\n\n".join(f"[{i + 1}] {chunks[idx]}" for i, (idx, _) in enumerate(indexes))


def generate(query, context_str, model_name, api_key, base_url):
    if not api_key:
        print("\n[llm] 未配置 API Key → 跳过生成。下面是要喂给 LLM 的强约束 Prompt：\n")
        print(STRONG_PROMPT.format(context=context_str, query=query))
        return None
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=model_name or "gpt-4o-mini", api_key=api_key,
                         base_url=base_url or None, temperature=0.1)
        return llm.invoke(STRONG_PROMPT.format(context=context_str, query=query)).content
    except Exception as e:
        print(f"[warn] LLM 生成失败：{e}")
        return None


def self_check(answer, chunks, indexes):
    """答案逐句去召回片段做关键词溯源（≥70% 命中=grounded）。"""
    if not answer:
        return {"verdict": "n/a", "grounded_ratio": 0.0, "unsupported": []}
    corpus = " ".join(chunks[i] for i, _ in indexes).lower()
    sents = [s.strip() for s in re.split(r"[。!?！？\n；;]+", answer) if len(s.strip()) >= 6]
    grounded, unsup = 0, []
    for s in sents:
        toks = [t for t in _tokenize(s) if len(t) >= 2]
        if not toks:
            continue
        hit = sum(1 for t in toks if t in corpus) / len(toks)
        if hit >= 0.7:
            grounded += 1
        else:
            unsup.append(s)
    total = grounded + len(unsup)
    ratio = (grounded / total) if total else 1.0
    verdict = "ok" if ratio >= 0.8 else ("warn" if ratio >= 0.5 else "block")
    return {"verdict": verdict, "grounded_ratio": round(ratio, 3), "unsupported": unsup}


# ============================================================
# 7) 主流程
# ============================================================

DIAG_HINT = """\n--- 诊断提示 ---
* 正确原文没进 top-N        → 问题在 切片/Embedding/检索：调小 chunk_size、换中文 Embedding、加大 BM25 权重
* 正确原文进了但排名靠后     → 调 Rerank top_n / RRF 权重
* chunk 单独读不懂、语义残缺 → 问题在 切片：检查段落边界，试试更大 overlap 或语义切片
* 召回对但 LLM 答错          → 问题在 Prompt/LLM：确认已用强约束模板，或换更强模型"""


def load_txts(kb_path):
    files = sorted(Path(kb_path).rglob("*.txt")) if Path(kb_path).is_dir() \
        else [Path(kb_path)]
    docs, seen = {}, {}
    for f in files:
        try:
            text = clean_text(f.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            print(f"[error] 读取 {f} 失败：{e}")
            continue
        if text:
            docs[f.name] = text
            seen[f.name] = f
    return docs


def main():
    ap = argparse.ArgumentParser(description="最小可运行 RAG Demo")
    ap.add_argument("--kb", default=str(Path(__file__).resolve().parents[1] / "knowledge_base"))
    ap.add_argument("--query", action="append", default=[],
                    help="诊断问题（可多次传；默认跑两个内置问题）")
    ap.add_argument("--mode", choices=["full", "recall", "chunks"], default="recall")
    ap.add_argument("--embed", choices=["bge", "tfidf"], default="bge")
    ap.add_argument("--chunk-size", type=int, default=600)
    ap.add_argument("--overlap", type=int, default=80)
    ap.add_argument("--max-tokens", type=int, default=500, help="chunk 上限，防 Embedding 截断")
    ap.add_argument("--vector-k", type=int, default=12)
    ap.add_argument("--bm25-k", type=int, default=12)
    ap.add_argument("--rrf-k", type=int, default=60)
    ap.add_argument("--weights", default="0.5,0.5")
    ap.add_argument("--rerank-top-n", type=int, default=5)
    ap.add_argument("--show-chunks", type=int, default=0, help="打印前 N 个切片供人工质检")
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", ""))
    ap.add_argument("--base-url", default=None)
    args = ap.parse_args()

    w1, w2 = (float(x) for x in args.weights.split(","))

    # ---- 1. 读文件 ----
    docs = load_txts(args.kb)
    if not docs:
        print(f"[error] {args.kb} 下没有可读的 txt")
        sys.exit(1)
    print(f"[1] 读取 {len(docs)} 个 txt：{list(docs)}")

    # ---- 2. 切片 ----
    all_chunks, chunk_src = [], []
    for name, text in docs.items():
        cs = chunk_paragraph_first(text, chunk_size=args.chunk_size,
                                   overlap=args.overlap, max_tokens=args.max_tokens)
        for c in cs:
            all_chunks.append(c)
            chunk_src.append(name)
    print(f"[2] 段落优先切片：共 {len(all_chunks)} 块（"
          f"avg={sum(len(c) for c in all_chunks) // max(len(all_chunks), 1)} chars，"
          f"max={max((len(c) for c in all_chunks), default=0)} chars）")

    if args.show_chunks:
        print(f"\n--- 切片质检：前 {args.show_chunks} 块（单独读，语义完整吗？）---")
        for i in range(min(args.show_chunks, len(all_chunks))):
            print(f"[{i}] <{chunk_src[i]}> {all_chunks[i][:200]}")
    if args.mode == "chunks":
        print(DIAG_HINT)
        return

    # ---- 3. Embedding ----
    if args.embed == "bge":
        try:
            embedder = BgeEmbeddings()
        except Exception as e:
            print(f"[warn] BGE 加载失败（{e}），降级 TF-IDF")
            embedder = TfidfEmbeddings()
    else:
        embedder = TfidfEmbeddings()
    print(f"[3] Embedding：{type(embedder).__name__}")

    # ---- 4. 建索引 ----
    index = DemoIndex(all_chunks, embedder)
    print(f"[4] 索引构建完成（{index.n} 块）")

    queries = args.query or ["Python 是什么时候发布的？", "Python 在 AI 领域用哪些框架？"]
    for q in queries:
        print(f"\n{'=' * 66}\n[Q] {q}\n{'=' * 66}")
        fused = index.rrf_fuse(q, args.vector_k, args.bm25_k, args.rrf_k, (w1, w2))
        reranked = rerank_cross(q, fused, all_chunks, top_n=args.rerank_top_n)
        print(f"[5] RRF 融合召回 top{len(fused)} → Rerank 取 top{len(reranked)}：")
        for rank, (idx, score) in enumerate(reranked, 1):
            preview = all_chunks[idx].replace("\n", " ")[:100]
            print(f"    #{rank} chunk_id={idx} <{chunk_src[idx]}> score={score:.3f} | {preview}")

        if args.mode == "full":
            context = format_context(reranked, all_chunks)
            answer = generate(q, context, args.model, args.api_key, args.base_url)
            if answer:
                check = self_check(answer, all_chunks, reranked)
                print(f"\n[6] 生成答案（self-check={check['verdict']}，grounded={check['grounded_ratio']}）：")
                print(answer)
                if check["unsupported"]:
                    print("\n[!] 无法溯源的句子（疑似幻觉）：")
                    for s in check["unsupported"]:
                        print(f"    - {s}")
    print(DIAG_HINT)


if __name__ == "__main__":
    main()
