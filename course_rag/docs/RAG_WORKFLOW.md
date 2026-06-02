# Course RAG 工作流

最后更新：2026-06-02

本文档记录 `course_rag` 当前 RAG 系统从用户输入问题到返回答案的主流程。后续改进检索、rerank、生成或接口时，需要同步更新本文档。

## 当前入口

主要服务入口是 FastAPI：

- `POST /ask`：执行检索、上下文组装和答案生成。
- `POST /search`：只执行检索和上下文返回，不调用 LLM。
- `POST /ingest`：加载或重建本地向量索引。
- `GET /health`：返回服务和索引状态。

默认虚拟环境：

```powershell
.\rag\Scripts\python.exe
```

## 离线索引构建流程

索引构建由 `course_rag/app/rag/indexing.py` 负责。

```text
课程资料
-> 数据清单
-> 文档加载
-> V2 EvidenceDocument 证据层
-> 父子 chunk 切分
-> embedding 编码
-> FAISS 索引保存
-> chunk / parent 元数据保存
```

| 阶段 | 当前实现 |
| --- | --- |
| 数据范围 | `course_rag/data/processed/data_manifest.jsonl` 中 priority 为 `mvp` 的资料 |
| 文档加载 | `loaders.py`，按文件类型读取 PDF、Markdown、DOCX 等资料 |
| chunk 策略 | `chunking.py`，父文档保留较大上下文，子 chunk 用于检索 |
| 默认 chunk 参数 | `chunk_size=500`，`chunk_overlap=80` |
| embedding 模型 | `BAAI/bge-small-zh-v1.5` |
| 向量维度 | 512 |
| 向量索引 | FAISS `IndexFlatIP` |
| 相似度策略 | embedding 归一化后使用 inner product，可按 cosine similarity 理解 |
| 索引目录 | `course_rag/vector_index_v2_text/` |
| 元数据文件 | `chunks.jsonl`、`parents.jsonl`、`parent_child_map.json`、`index_meta.json` |

### V2 Text Evidence 证据层

V2 首批改动新增了 `course_rag/app/rag/evidence.py`，用于把现有 `LoadedDocument` 转换为统一的 `EvidenceDocument` 后再进入原有 chunk/index 流程。

当前只启用文本证据：

```text
LoadedDocument
-> EvidenceDocument(modality=text, evidence_kind=native_text)
-> LoadedDocument 兼容形态
-> ParentDocument / ChunkedDocument
-> 当前 FAISS + hybrid + rerank 流程
```

当前默认索引目录为：

```text
course_rag/vector_index_v2_text/
```

默认重建会生成 text evidence；如需显式重建：

```powershell
.\rag\Scripts\python.exe course_rag\app\rag\indexing.py --rebuild
```

生成的 text evidence 缓存默认写入：

```text
course_rag/data/processed/evidence_text.jsonl
```

`evidence_id` 基于来源、页码、section、证据类型等稳定字段生成，不依赖 chunk 文本内容；chunk 和 parent 会透传 `evidence_id`、`source_doc_id`、`modality`、`evidence_kind`、`asset_path`、`parser_backend` 等字段。

## 在线问答流程

`POST /ask` 的主流程由 `course_rag/app/rag/generation.py` 负责。

```text
用户问题
-> 请求参数解析
-> 加载本地索引
-> 混合检索召回候选
-> metadata routing 过滤或加权
-> 默认 rerank 精排（可关闭）
-> 短 chunk 过滤
-> parent 去重
-> 父文档上下文组装
-> prompt 构造
-> LLM 生成
-> 答案、引用、检索调试信息返回
```

## 1. 请求参数解析

请求模型位于 `course_rag/app/schemas.py`。

`/ask` 当前主要参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `question` | 必填 | 用户问题 |
| `top_k` | 5 | 最终返回的引用数量 |
| `candidate_k` | 空 | 检索候选数量；为空时由系统计算 |
| `strategy` | `hybrid` | 检索策略，可选 `hybrid`、`dense`、`bm25` |
| `rrf_k` | 60 | RRF 融合参数 |
| `use_rerank` | `true` | 是否启用 cross-encoder rerank；默认开启 |
| `rerank_top_n` | 20 | 送入 reranker 的候选数量 |
| `rerank_model` | `BAAI/bge-reranker-base` | 默认 reranker 模型 |
| `rerank_device` | `auto` | 自动选择 CUDA 或 CPU |
| `rerank_local_files_only` | `true` | 默认只读本地缓存，避免自动下载模型 |
| `use_parent_context` | `true` | 使用父文档作为生成上下文 |
| `use_llm` | `true` | 是否调用 LLM |
| `use_metadata_routing` | `true` | 是否启用课程、文件、页码等 metadata routing |
| `course` / `category` | 空 | 可选显式过滤课程或资料类别 |
| `source_name` / `page` | 空 | 可选显式过滤文件名或页码 |
| `modality` / `evidence_kind` | 空 | 可选显式过滤 evidence 类型 |
| `max_context_chars` | 6000 | prompt 上下文总长度上限 |
| `max_context_chars_per_source` | 1600 | 单个来源上下文长度上限 |

## 2. 索引加载

在线问答默认加载 `course_rag/vector_index_v2_text/`。

加载内容：

- FAISS 向量索引：`index.faiss`
- 子 chunk：`chunks.jsonl`
- 父文档：`parents.jsonl`
- 父子映射：`parent_child_map.json`
- 索引配置：`index_meta.json`

索引对象为 `CourseVectorIndex`，在服务进程中缓存复用。

## 3. 检索召回

检索模块位于 `course_rag/app/rag/retrieval.py`。

当前默认策略是 `hybrid`：

```text
dense 检索
+ BM25 检索
-> RRF 融合
-> 默认 rerank
-> 候选结果排序
```

| 策略 | 当前实现 |
| --- | --- |
| `dense` | 使用 `BAAI/bge-small-zh-v1.5` 编码问题，在 FAISS 中检索相似 chunk |
| `bm25` | 使用 `rank-bm25`，基于已加载 chunks 在内存中构建 BM25 索引 |
| `hybrid` | dense 和 BM25 分别召回候选，再按 RRF 分数融合 |

默认候选数量：

```text
candidate_k = max(top_k * 4, 30)
```

BM25 分词策略：

- 英文、数字、缩写和带 `/` 的术语会作为 token 保留。
- 中文文本使用 2-gram 和 3-gram。
- BM25 文本包含 chunk 正文和部分元数据字段。

RRF 分数：

```text
score = sum(1 / (rrf_k + rank))
```

检索结果会保留以下调试字段：

- `retrieval_strategy`
- `retrievers`
- `dense_rank`
- `dense_score`
- `bm25_rank`
- `bm25_score`
- `rrf_score`

### Metadata Routing

routing 模块位于 `course_rag/app/rag/routing.py`，默认在 `/ask` 和 `/search` 中启用。

当前策略：

- 显式请求字段 `course`、`category`、`source_name`、`page`、`modality`、`evidence_kind` 使用严格 metadata filter。
- 问题文本中高置信识别出的课程名、文件名、页码和期末试题类别会先尝试过滤；如果过滤后没有候选，则回退到原始 hybrid 候选。
- 图片、表格、题号类意图会记录到 `routing.intents`，当前 text evidence 索引只做调试和轻量加权，不强行过滤到图片或表格。
- routing 会返回 `candidate_count_before`、`candidate_count_after`、`applied_filters`、`filter_fallback` 等调试信息。

### 默认 Rerank 精排

rerank 模块位于 `course_rag/app/rag/rerank.py`，当前默认开启，可通过 `use_rerank=false` 关闭。

启用时流程为：

```text
RRF 候选结果
-> 取前 rerank_top_n 个 child chunk
-> 使用 cross-encoder 对 query + chunk 打分
-> 按 rerank_score 重排
-> 保留后续上下文选择流程
```

当前默认模型是 `BAAI/bge-reranker-base`。该模型只在 `use_rerank=true` 时懒加载。默认 `rerank_local_files_only=true`，如果本地缓存没有模型，会保留原检索排序并返回 `rerank_error`，不会中断 `/ask` 或 `/search`。

rerank 成功后，引用和检索调试字段会额外包含：

- `pre_rerank_rank`
- `pre_rerank_score`
- `rerank_rank`
- `rerank_score`
- `rerank_model`

## 4. 上下文选择

检索返回的是子 chunk。生成前会进入上下文选择阶段：

```text
候选 chunk
-> 过滤过短文本
-> 按 parent_doc_id 去重
-> 选择 parent 文档或 child chunk
-> 生成 citation
```

当前默认使用父文档上下文：

- 检索命中子 chunk。
- 如果 `use_parent_context=true`，生成时使用对应 parent 文档。
- citation 中仍保留命中 child chunk 的来源、页码、章节和 preview。

## 5. 上下文裁剪

上下文裁剪由 `trim_contexts()` 负责。

当前限制：

- 总上下文长度：`max_context_chars=6000`
- 单个来源长度：`max_context_chars_per_source=1600`

超过限制的文本会被截断后进入 prompt。

## 6. Prompt 与生成

生成模块使用 LangChain 调用兼容 OpenAI 接口的 DeepSeek 服务。

| 项 | 当前配置 |
| --- | --- |
| LLM provider | DeepSeek-compatible API |
| 默认模型 | `deepseek-v4-pro` |
| 默认 base URL | `https://api.deepseek.com` |
| API key 环境变量 | `DEEPSEEK_API_KEY_RAGLEARN` |
| temperature | 0.1 |
| max_tokens | 1500 |

Prompt 结构：

```text
system:
  只根据给定课程资料回答。
  资料不足时明确说明。
  回答中使用 [1]、[2] 形式标注引用来源。

human:
  用户问题
  检索资料
  回答要求
```

如果 `use_llm=false`，系统不调用 LLM，直接返回检索片段。

如果 LLM 调用失败，系统返回 retrieval-only fallback，并保留 `llm_error`。

## 7. 返回结果

`/ask` 返回：

- `question`
- `answer`
- `citations`
- `retrieval`
- `used_llm`
- `llm_error`
- `retrieval_strategy`
- `retrievers`
- `use_rerank`
- `rerank_used`
- `rerank_model`
- `rerank_device`
- `rerank_error`
- `routing`
- `pipeline`
- `index`

`citations` 用于答案引用展示。

`retrieval` 用于调试检索命中、上下文内容和融合分数。

V2 text evidence 索引会额外返回以下可选字段：

- `evidence_id`
- `source_doc_id`
- `modality`
- `evidence_kind`
- `asset_path`
- `parser_backend`
- `context_before`
- `context_after`

## 当前 Pipeline

默认 `strategy="hybrid"` 时：

```text
load_vector_index
-> encode_query
-> faiss_candidate_search
-> bm25_candidate_search
-> rrf_fusion
-> metadata_route_query
-> metadata_filter_candidates / metadata_filter_fallback
-> metadata_boost_candidates
-> rerank_candidates（默认开启；use_rerank=false 时跳过）
-> filter_short_chunks
-> deduplicate_by_parent
-> assemble_context
-> llm_generation / retrieval_only_fallback
```
