# Day10 Rerank 接入记录

## 本阶段目标

Day10 的核心目标是在 Day09 的混合检索之后加入可选 rerank，让系统从“召回排序”升级为“召回 + 精排”的两阶段检索流程。

当前项目已经有：

- dense 检索：`BAAI/bge-small-zh-v1.5` + FAISS
- 关键词检索：BM25
- 融合排序：RRF
- 父子文档策略：child chunk 检索，parent 文档生成

因此本阶段不再重做检索系统，而是在 RRF 之后增加 rerank：

```text
用户问题
-> dense + BM25 召回
-> RRF 融合候选
-> Cross-Encoder rerank 精排
-> 短文本过滤 / parent 去重
-> 组装上下文
-> 生成答案或返回检索片段
```

## 为什么需要 Rerank

Embedding 检索适合做“召回”，目标是从大量 chunk 里快速找出一批可能相关的候选。它的优势是快，可以预先把文档编码成向量，查询时只需要编码问题并做向量相似度搜索。

但 embedding 检索的问题是：query 和 document 是分开编码的，模型只能通过两个向量的距离判断相关性。对一些细粒度问题、术语问题、否定表达或长 chunk 中的局部信息，单向量相似度可能不够精确。

RRF 解决的是“多路召回结果怎么融合”的问题。它不理解文本内容，只根据 dense 和 BM25 的排名做融合：

```text
score = sum(1 / (rrf_k + rank))
```

Rerank 解决的是“候选结果内部谁更适合放在前面”的问题。它会把 query 和每个候选 chunk 拼在一起输入模型，由模型直接判断这对文本的相关性。

所以当前项目里的分工是：

| 阶段 | 作用 | 当前方案 |
| --- | --- | --- |
| 召回 | 快速找出候选 | dense + BM25 |
| 融合 | 合并多路候选排序 | RRF |
| 精排 | 对候选做更细判断 | Cross-Encoder rerank |
| 生成 | 基于最终上下文回答 | DeepSeek-compatible LLM |

## 模型选择

本阶段选择 `BAAI/bge-reranker-base` 作为默认 rerank 模型。

选择原因：

- 支持中英文，适合当前中文课程资料。
- 约 278M 参数，比 `BAAI/bge-reranker-v2-m3` 更适合本地学习项目。
- 可以通过 `sentence-transformers` 的 `CrossEncoder` 接入，不需要额外引入 `FlagEmbedding`。
- 当前设备有 NVIDIA RTX 3050 Laptop GPU，安装 CUDA 版 PyTorch 后可以用 GPU 推理。

暂不选择 `BAAI/bge-reranker-v2-m3`，因为它约 568M 参数，对 4GB 显存更吃紧，作为后续效果优先方案更合适。

当前环境已经从 CPU 版 PyTorch 切换到 CUDA 版：

```text
torch 2.5.1+cu121
torchvision 0.20.1+cu121
torchaudio 2.5.1+cu121
```

`BAAI/bge-reranker-base` 已下载到本地缓存：

```text
course_rag/data/processed/model_cache/huggingface/
```

## 阶段结论

当前项目已经从“支持配置化 rerank 接口”推进到“本地 GPU reranker 可用”。

比较准确的项目表述是：

> 在 BM25 + dense hybrid 检索和 RRF 融合之后，接入可选 Cross-Encoder reranker，对候选 chunk 进行二阶段精排，并保留 rerank 前后排序调试字段。

后续如果要继续优化，优先做评测集和指标对比，而不是继续换更大的 rerank 模型。
