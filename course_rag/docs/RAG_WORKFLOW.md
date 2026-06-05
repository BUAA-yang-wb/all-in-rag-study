# Course RAG 当前工作流

最后更新：2026-06-05

本文档记录 `course_rag` 当前从资料入库、索引构建、检索到回答生成的主链路。当前设计已经收敛为：

- SQLite docstore 是本地 source of truth。
- Milvus 是唯一在线检索索引，负责 dense、BM25 sparse/full-text 和 hybrid search。
- JSONL evidence 缓存只作为调试/复用产物，不再是主状态源。
- 旧本地向量索引目录不再被主链路读取。

## 1. 服务入口

FastAPI 入口位于 `course_rag/app/main.py`：

- `GET /health`：返回 SQLite docstore、Milvus 连接、collection 和 entity/chunk 对齐状态。
- `POST /ingest`：加载现有索引，或在 `rebuild=true` 时重建 SQLite docstore 并重建 Milvus collection。
- `POST /search`：只返回检索结果、citation、routing 和 pipeline，不调用 LLM。
- `POST /ask`：在检索结果上组装上下文，并按需调用 LLM 生成带引用答案。

默认运行环境：

```powershell
.\rag\Scripts\python.exe
```

默认启动服务：

```powershell
.\rag\Scripts\python.exe -X utf8 -m uvicorn course_rag.app.main:app --reload
```

## 2. 存储分层

当前采用“两层存储”：

| 层 | 作用 | 当前实现 |
| --- | --- | --- |
| docstore | 保存完整文档、evidence、parent、chunk、metadata、ingest run，是本地真源 | SQLite，默认 `course_rag/data/rag_store.sqlite` |
| retrieval index | 保存 chunk 检索索引和必要过滤字段，不作为完整文档真源 | Milvus collection `course_rag_v2_text` |

SQLite 表：

- `ingest_runs`：记录每次重建的 run id、状态、统计和元信息。
- `documents`：保存原始资料级 metadata 和内容 hash。
- `evidence`：保存统一 evidence 文本、来源、模态、页码和 metadata。
- `parents`：保存用于回答上下文的父级片段。
- `chunks`：保存用于检索的子 chunk。
- `chunk_parent_map`：保存 child chunk 到 parent context 的映射。

Milvus collection 字段：

- `chunk_id`：主键，与 SQLite `chunks.chunk_id` 对齐。
- `dense_vector`：`BAAI/bge-small-zh-v1.5` 生成的 dense embedding。
- `search_text`：开启 analyzer 的检索文本。
- `sparse_vector`：由 Milvus BM25 Function 从 `search_text` 自动生成。
- scalar filter 字段：`course`、`category`、`source_name`、`page`、`modality`、`evidence_kind` 等。
- `metadata`：用于调试的 JSON metadata 副本。

Milvus 只保存 chunk 级短文本和过滤字段；完整 parent context、citation 细节和调试 metadata 从 SQLite 读取。

## 3. Ingest 流程

重建主流程：

```text
课程资料
-> data_manifest.jsonl
-> loaders.py 读取 PDF / Markdown / TXT / DOCX / 图片
-> EvidenceDocument 统一证据层
-> 父子 chunk 切分
-> upsert SQLite docstore
-> encode chunk dense vectors
-> rebuild Milvus collection
```

常用脚本：

```powershell
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_up.ps1
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_rebuild_index.ps1
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_check.ps1
```

`milvus_rebuild_index.ps1` 默认会同时传入 `--rebuild-docstore` 和 `--drop-existing`，因此语义是完整重建 SQLite docstore 和 Milvus collection。

也可以直接运行 Python CLI：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\app\rag\indexing.py --rebuild
.\rag\Scripts\python.exe -X utf8 course_rag\app\rag\milvus_index.py --drop-existing --rebuild-docstore
```

默认 evidence 类型：

| 类型 | evidence_kind | 默认行为 |
| --- | --- | --- |
| 文本 | `native_text` | 默认入库 |
| 表格 | `table_markdown` | 默认入库 |
| 图片元数据 | `image_metadata` | 默认入库 |
| Markdown 图片引用 | `image_ref` | 默认入库 |
| OCR 文本 | `ocr_text` | 读取已有缓存；只有显式 `run_ocr=true` 才运行 OCR |
| 图片 caption | `caption` | provider 已接入但默认关闭 |

## 4. 在线检索流程

`/search` 和 `/ask` 共用 `generation.py`、`retrieval.py`、`routing.py`、`rerank.py`：

```text
用户问题
-> metadata routing 识别显式/推断过滤条件
-> Milvus dense / BM25 / hybrid search
-> 必要时回退未过滤候选
-> app 层 routing 过滤与轻量加权
-> rerank 精排
-> 过滤短 chunk
-> 按 parent 去重
-> 回 SQLite 取 parent context 与 citation
-> /search 返回证据，/ask 可选调用 LLM
```

检索策略：

| strategy | 行为 |
| --- | --- |
| `dense` | 只走 Milvus `dense_vector` 相似度检索 |
| `bm25` | 只走 Milvus BM25 sparse/full-text 检索 |
| `hybrid` | 同时走 dense 和 BM25，并用 Milvus `RRFRanker` 融合 |

默认策略是 `hybrid`，默认 `rrf_k=60`。当前保留后续切换 `WeightedRanker` 的空间，但主链路先使用 RRF，便于减少权重调参依赖。

默认候选数量：

```text
candidate_k = max(top_k * 4, 30)
```

metadata routing 会把可过滤字段尽量下推成 Milvus scalar filter。若下推过滤没有返回候选，会重新请求更宽的 Milvus 候选，再走 app 层 routing 的现有 fallback 逻辑，避免推断过滤误伤召回。

## 5. Rerank 与生成

默认 rerank 开启：

| 项 | 默认值 |
| --- | --- |
| rerank 模型 | `BAAI/bge-reranker-base` |
| `rerank_top_n` | 20 |
| `rerank_batch_size` | 8 |
| `rerank_local_files_only` | true |

如果本地没有 reranker 缓存，系统返回 `rerank_error` 并保留 Milvus 检索排序，不中断请求。

`/ask` 默认 LLM 配置：

| 项 | 默认值 |
| --- | --- |
| 默认模型 | `deepseek-v4-pro` |
| base URL | `https://api.deepseek.com` |
| API key 环境变量 | `DEEPSEEK_API_KEY_RAGLEARN` |
| temperature | 0.1 |
| max_tokens | 1500 |

离线验证建议传：

```json
{
  "use_llm": false
}
```

## 6. API 结构变化

当前公开接口固定使用 Milvus 检索索引和 SQLite docstore，不提供检索后端切换参数。

`IndexInfo` 当前从 Milvus + docstore 视角返回：

- `backend="milvus"`
- `collection_name`
- `milvus_uri`
- `vectors`
- `embedding_model`
- `docstore_path`
- `documents`
- `chunks`
- `parents`
- `evidence_count`

`/health` 额外返回：

- `docstore_exists`
- `docstore_readable`
- `docstore_path`
- `docstore_chunks`
- `docstore_error`
- `milvus_connected`
- `milvus_collection`
- `milvus_entity_count`
- `milvus_aligned_with_docstore`
- `milvus_error`

`/ingest` 返回：

- `ingest_run_id`
- `docstore` 写入/读取统计
- `milvus` rebuild/load 统计
- `index` 当前 Milvus/docstore 信息

## 7. 请求示例

检索：

```json
{
  "query": "FIRST FOLLOW 表格",
  "strategy": "hybrid",
  "top_k": 3,
  "use_rerank": false
}
```

指定 metadata：

```json
{
  "query": "2018-2019 21系编译期末答案中 FIRST/FOLLOW 表格相关内容在哪里？",
  "course": "编译原理",
  "category": "复习",
  "evidence_kind": "table_markdown",
  "top_k": 5
}
```

离线问答：

```json
{
  "question": "计网串讲课件里 OSI 参考模型自底向上有哪些层？",
  "course": "计网",
  "source_name": "串讲+习题课 25.pdf",
  "top_k": 5,
  "use_llm": false
}
```

完整重建：

```json
{
  "rebuild": true,
  "priority": "mvp,v2",
  "include_visual_evidence": true,
  "include_table_evidence": true,
  "run_ocr": false
}
```

## 8. 验证方式

静态检查：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app course_rag\eval
```

快速评测：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast --no-write-doc
```

API 验证建议：

- `GET /health`：确认 `docstore_readable=true`，且 `milvus_aligned_with_docstore=true`。
- `POST /ingest {"rebuild": true}`：确认返回 `ingest_run_id`、docstore 统计和 Milvus `entity_count`。
- `POST /search {"query": "...", "use_rerank": false}`：确认 `strategy` 为 `dense`、`bm25`、`hybrid` 时均能返回合法 `chunk_id`。
- `POST /ask {"question": "...", "use_llm": false}`：确认无需外部 LLM 即可返回 citation。

## 9. 后续路线

当前阶段只把存储和检索链路理顺，不切换 embedding 模型。

后续应基于评测再决定：

- 是否从 `BAAI/bge-small-zh-v1.5` 切换到 `BAAI/bge-m3`。这会触发全量重嵌入和模型缓存变化。
- 是否加入 HyDE/query expansion。默认不启用，因为依赖 LLM，可能增加延迟和查询漂移。
- 是否引入 ColBERT/late interaction。它更适合作为高质量检索实验项，不进入当前默认主链路。
