# Day09 混合检索记录

## 本次目标调整

Day09 原计划是对比 dense、BM25、hybrid 三种策略。结合当前项目状态，实际目标调整为：把默认检索能力从纯向量检索升级为 hybrid 检索，不再把三策略对比作为主线。

当前项目已有：

- FAISS 向量索引：`course_rag/vector_index/`
- embedding 模型：`BAAI/bge-small-zh-v1.5`
- 父子文档上下文：child chunk 检索，parent 文档生成
- FastAPI 入口：`/ask` 和 `/search`

因此 Day09 不引入 Milvus，不替换 embedding 模型，也不提前做 rerank。

## 实现方案

新增 `course_rag/app/rag/retrieval.py`，统一封装三种检索策略：

- `dense`：继续使用现有 FAISS 向量检索。
- `bm25`：基于 `rank-bm25`，从已加载的 chunks 构建内存 BM25 索引。
- `hybrid`：分别召回 dense 和 BM25 候选，再用 RRF 融合排序。

RRF 公式：

```text
score(d) = sum(1 / (rrf_k + rank_i(d)))
```

默认 `rrf_k=60`。RRF 不依赖 dense 分数和 BM25 分数的尺度，因此适合融合两类不同检索器。

## 选型判断

当前最适合项目的是 `BM25 + FAISS dense + RRF`：

- dense 对语义问题、近义表达效果好，当前明确知识点问题已经能稳定命中。
- BM25 对课程术语、缩写、页内关键词更稳，例如 `CSMA/CD`、`LR0`、`FIRST`。
- RRF 参数少、可解释，不需要训练，也不会引入额外模型推理成本。

更重的方案暂不采用：

- BGE-M3 可以同时生成 dense/sparse/multi-vector，但需要重建索引，模型更大，不适合作为 Day09 的最小优化。
- Qwen3 / BGE reranker 更适合 Day10 的“召回后精排”，不应混入 Day09。
- Milvus/Elasticsearch 对当前本地学习项目过重，FAISS + 内存 BM25 已足够。

## API 变化

`/ask` 和 `/search` 请求新增：

```json
{
  "strategy": "hybrid",
  "rrf_k": 60
}
```

默认策略为 `hybrid`。也可以传入 `dense` 或 `bm25` 做调试。

响应中的引用和检索项新增调试字段：

- `retrieval_strategy`
- `retrievers`
- `dense_rank`
- `dense_score`
- `bm25_rank`
- `bm25_score`
- `rrf_score`

## 验证建议

使用当前项目虚拟环境：

```powershell
.\rag\Scripts\python.exe -m uvicorn course_rag.app.main:app --reload
```

检索样例：

```json
{
  "query": "CSMA/CD是什么？",
  "top_k": 5
}
```

```json
{
  "query": "LR0分析表怎么构造？",
  "top_k": 5
}
```

```json
{
  "query": "这门课的期末复习重点是什么？",
  "top_k": 5
}
```

## 本次验证结果

语法检查：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app
```

通过。

FastAPI `POST /search` 验证：

- 默认不传 `strategy` 时返回 `hybrid`。
- 显式传入 `strategy="bm25"` 时返回 `bm25`。
- 响应中包含 `dense_rank`、`bm25_rank`、`rrf_score` 等调试字段。

样例结果：

| 查询 | Top1 来源 | 说明 |
| --- | --- | --- |
| `CSMA/CD是什么？` | `邓攀：4.计算机网络第8版课件-第3章-数据链路层.pdf` Page 56 | dense rank 1，BM25 rank 6，hybrid 稳定命中术语解释页 |
| `LR0分析表怎么构造？` | `hcm-编译原理-第21讲-LR0分析-20251127.pdf` Page 150 | dense rank 1，BM25 rank 1，RRF 后仍排第 1 |
| `这门课的期末复习重点是什么？` | `hcm-编译原理-第01讲-概论-20250909.pdf` Page 83 | hybrid 增加了期末试题类候选，但宽泛问题仍有跨课程混召回 |

FastAPI `POST /ask` 验证：

- 请求 `{"question":"CSMA/CD是什么？","top_k":2,"use_llm":false}` 返回 200。
- `retrieval_strategy` 为 `hybrid`。
- `retrievers` 为 `["dense", "bm25"]`。
- `used_llm=false`，说明验证过程未调用外部 LLM。

## 后续

- Day10 再接 reranker，形成 `hybrid recall -> rerank -> generation`。
- Day11 用评测集验证 `dense`、`hybrid`、`hybrid + rerank` 的指标差异。
- 宽泛问题如果仍然跨课程混召回，应优先补课程过滤或查询改写，而不是继续堆检索模型。
