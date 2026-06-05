# Course RAG 当前工作流

最后更新：2026-06-05

本文档总结 `course_rag` 当前系统从资料入库、检索到回答生成的主流程。后续如果改动索引、检索、rerank、生成、API 参数或返回结构，需要同步更新本文档。

## 1. 服务入口

FastAPI 入口位于 `course_rag/app/main.py`：

- `POST /ask`：检索资料、组装上下文，并按需调用 LLM 生成答案。
- `POST /search`：只返回检索结果和 citation，不调用 LLM。
- `POST /ingest`：加载或重建本地索引。
- `GET /health`：返回服务和索引状态。

默认运行环境：

```powershell
.\rag\Scripts\python.exe
```

默认启动服务：

```powershell
.\rag\Scripts\python.exe -X utf8 -m uvicorn course_rag.app.main:app --reload
```

当前默认 `/ask` 和 `/search` 使用 Milvus。启动 FastAPI 前，建议先确认 Docker
Desktop、Milvus standalone 和 `course_rag_v2_text` collection 已就绪。

## 2. 离线索引构建

索引构建由 `course_rag/app/rag/indexing.py` 负责。当前流程是：

```text
课程资料
-> data_manifest.jsonl
-> loaders.py 读取 PDF / Markdown / DOCX / 图片等资料
-> 统一转换为 EvidenceDocument
-> 父子 chunk 切分
-> BAAI/bge-small-zh-v1.5 embedding
-> FAISS IndexFlatIP
-> 保存 chunks / parents / parent_child_map / index_meta
```

Milvus 是当前默认在线 dense 检索后端。Milvus collection 从
`vector_index_v2_text/` 的 FAISS baseline 产物导入，复用同一批 chunk、parent、
metadata 和 512 维文本向量；不包含页面图向量、图片向量或视觉检索模型。
FAISS 文件仍保留，作为 Milvus 导入源、低资源开发和对比评测 fallback。

当前索引配置：

| 项 | 当前值 |
| --- | --- |
| 索引目录 | `course_rag/vector_index_v2_text/` |
| embedding 模型 | `BAAI/bge-small-zh-v1.5` |
| 向量维度 | 512 |
| 相似度 | 归一化 embedding + inner product，可按 cosine similarity 理解 |
| chunk 参数 | `chunk_size=500`，`chunk_overlap=80` |
| 当前 vectors | 9138 |
| parent 数 | 5840 |
| parent-child 映射 | 9138 |
| 默认数据库后端 | Milvus collection `course_rag_v2_text`，默认连接 `http://localhost:19530` |
| fallback baseline | FAISS，显式传 `index_backend="faiss"` 使用 |

当前本机 Milvus 状态：

| 项 | 当前值 |
| --- | --- |
| Docker Compose 配置 | `course_rag/deploy/milvus/docker-compose.yml` |
| Milvus 版本 | `milvusdb/milvus:v2.5.27` |
| 依赖容器 | `milvus-etcd`、`milvus-minio` |
| 容器状态 | 三个容器已实际启动并验证为 `healthy` |
| Milvus 端口 | `19530` |
| 健康检查端口 | `9091` |
| collection | `course_rag_v2_text` |
| collection entity_count | 9138 |
| API 健康检查 | `/health` 返回 `status=ok`、`milvus_connected=true` |

## 3. 统一证据层

系统不会把原始文件直接切 chunk，而是先把不同来源的资料统一成 `EvidenceDocument`。这样 citation、过滤和调试都可以使用同一套 metadata。

当前 evidence 类型：

| 类型 | evidence_kind | 来源与说明 |
| --- | --- | --- |
| 文本 | `native_text` | PDF 文本层、Markdown、DOCX 等普通文本 |
| 图片元数据 | `image_metadata` | 独立图片文件，记录文件名、课程、类别、路径等 |
| Markdown 图片引用 | `image_ref` | Markdown 中引用的图片，并带所在章节和前后文 |
| OCR 文本 | `ocr_text` | RapidOCR 离线识别图片或低文本 PDF 页得到的文字 |
| 表格 | `table_markdown` | Docling 表格结构优先，Markdown/PDF 类表格文本兜底 |
| 图片 caption | `caption` | 已接入但默认关闭，不生成也不纳入默认索引 |

### 资料类型处理策略

不同资料进入索引前会走不同的处理路径，目标是尽量保留可检索文本、原始位置和可追溯引用。

| 资料类型 | 当前处理方式 | 简短理由 |
| --- | --- | --- |
| 文本层 PDF | 优先用 `pypdf` 按页抽取文本，生成 `native_text`；页码写入 metadata | 课程课件和试卷大多有文本层，按页保留能让 citation 回到具体页 |
| 低文本 PDF / 扫描页 | 显式运行 OCR 时，按页判断文本量，低文本页渲染成图片后交给 RapidOCR，生成 `ocr_text` | 避免对所有 PDF 页做昂贵 OCR，只补文本层不足的页面 |
| Markdown | 读取正文生成 `native_text`；同时解析 Markdown 图片引用，生成 `image_ref` | Markdown 正文适合直接检索，图片引用需要带上所在章节和前后文，方便问图相关问题 |
| DOCX | 通过 Docling 转成 Markdown/JSON，再作为文本 evidence 入库 | DOCX 结构比纯文本复杂，先转成统一 Markdown 形态，后续 chunk 逻辑更稳定 |
| 独立图片 | 不直接做视觉向量；默认生成 `image_metadata`，记录文件名、课程、类别和 `asset_path` | 当前在线链路是文本检索，先让图片至少能按文件名、路径和上下文被发现 |
| 图片 OCR | 显式运行 OCR 后，对独立图片、Markdown 图片引用和候选 PDF 页图生成 `ocr_text` | OCR 解决“图片里写了什么”，结果缓存后进入普通文本检索链路 |
| 表格 | 优先读取 Docling JSON 中的结构化表格；缺失时从 Markdown/PDF 文本中抽连续类表格行，统一转成 Markdown 表格 | 表格直接混在普通文本 chunk 中容易丢表头或列关系，单独 evidence 更适合表格问答和引用 |
| VLM caption | provider 已接入，但默认不生成、不读取、不索引；需要时显式运行 caption 离线任务 | 本地 VLM 成本和质量不稳定，默认关闭可以避免慢任务和幻觉污染索引 |

PDF OCR 候选页采用页级策略。默认重建不会扫描或渲染 PDF 页；只有显式 `--run-ocr` 时，才会检查页面文本量。对于已标记为低文本的 PDF，会把已扫描范围内页面作为候选；普通文本层 PDF 只处理去空白字符数低于 `--pdf-page-low-text-chars` 的页面，默认阈值是 80。

表格抽取是保守策略：Docling 表格质量较高时优先使用；文本兜底只接受连续 2 行以上、2 列以上的表格形态。小表整表入库，大表按最多 20 行切分，并在每个切片保留表头，避免检索命中时丢失列含义。

默认重建会生成文本、图片和表格 evidence；如果已有 OCR 缓存，也会读取 OCR evidence 进入索引。默认不会运行 OCR，也不会读取或索引 caption 缓存。

常用缓存文件：

```text
course_rag/data/processed/evidence_text.jsonl
course_rag/data/processed/evidence_image.jsonl
course_rag/data/processed/evidence_ocr.jsonl
course_rag/data/processed/evidence_table.jsonl
course_rag/data/processed/evidence_v2.jsonl
```

重建默认索引：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\app\rag\indexing.py --rebuild --no-progress
```

显式更新 OCR 缓存并重建索引：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\app\rag\indexing.py --rebuild --run-ocr --ocr-provider rapidocr --pdf-page-low-text-chars 80 --no-progress
```

OCR 是离线任务，不在 `/ask` 或 `/search` 中实时运行。低文本 PDF 页会先渲染到 `course_rag/data/processed/page_images/`，再交给 RapidOCR。caption 需要显式 `--run-caption --caption-provider llama-cpp-cli` 并配置本地 VLM 运行时；当前默认关闭。

本地 Milvus 使用 Docker Compose standalone 部署。启动顺序：

```powershell
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_up.ps1
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_rebuild_index.ps1
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_check.ps1
```

其中 `milvus_up.ps1` 只会调用 Docker CLI，不会自动启动 Docker Desktop。如果 Docker
daemon 不可用，需要先手动打开 Docker Desktop。首次启动会拉取 Milvus、etcd 和
MinIO 镜像；当前本机已完成镜像拉取、容器启动和 collection 导入。Milvus、etcd、
MinIO 的本地数据保存在 `course_rag/deploy/milvus/volumes/`，停止容器不会删除数据。

直接使用 Python CLI 做构建或检查：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\app\rag\milvus_index.py --drop-existing
.\rag\Scripts\python.exe -X utf8 course_rag\app\rag\milvus_index.py --check --query "FIRST FOLLOW 表格"
```

截至当前索引，evidence 统计为：

| evidence_kind | 数量 |
| --- | ---: |
| `native_text` | 4243 |
| `image_metadata` | 177 |
| `image_ref` | 167 |
| `ocr_text` | 998 |
| `table_markdown` | 139 |
| `caption` | 0 |
| 合计 | 5724 |

## 4. 在线检索流程

`/ask` 和 `/search` 都走同一套检索主链路，核心逻辑在 `course_rag/app/rag/generation.py`、`retrieval.py`、`routing.py` 和 `rerank.py`。

```text
用户问题
-> 加载 Milvus collection 与本地 chunk/parent metadata
-> dense / BM25 / hybrid 召回
-> metadata routing 过滤或加权
-> rerank 精排
-> 过滤短 chunk
-> 按 parent 去重
-> 组装上下文和 citation
-> /ask 调用 LLM，/search 直接返回检索结果
```

当前默认检索策略是 `hybrid`：

- dense：用 `BAAI/bge-small-zh-v1.5` 编码问题，在所选后端中检索；默认后端是 Milvus，可显式传 `index_backend="faiss"` 使用 FAISS fallback。
- BM25：用 `rank-bm25` 在内存中基于 chunk 正文和部分 metadata 检索。
- hybrid：dense 和 BM25 分别召回后，用 RRF 融合排序。

默认候选数量：

```text
candidate_k = max(top_k * 4, 30)
```

默认 rerank 开启，模型为 `BAAI/bge-reranker-base`。如果本地没有 reranker 缓存，系统会保留原检索排序并返回 `rerank_error`，不会中断请求。需要关闭时传：

```json
{
  "use_rerank": false
}
```

默认 Milvus 请求示例：

```json
{
  "query": "FIRST FOLLOW 表格",
  "milvus_uri": "http://localhost:19530",
  "milvus_collection": "course_rag_v2_text"
}
```

显式使用 FAISS fallback：

```json
{
  "query": "FIRST FOLLOW 表格",
  "index_backend": "faiss"
}
```

## 5. Metadata Routing

请求可以显式传入 metadata 过滤条件：

- `course`
- `category`
- `source_name`
- `page`
- `modality`
- `evidence_kind`

系统也会从问题中识别课程、文件名、页码、图片/表格/题号等意图。高置信 metadata 会先尝试过滤；如果过滤后没有候选，会回退到原始候选，避免规则误判导致无结果。

图片、OCR、表格类问题不会强制只搜某一种 evidence，而是通过 routing 记录意图并做轻量加权。调试信息会返回：

- `candidate_count_before`
- `candidate_count_after`
- `applied_filters`
- `filter_fallback`
- `matched_intents`

## 6. 上下文与生成

检索命中的是 child chunk；默认生成时使用对应 parent 文档作为上下文，以减少 chunk 过碎导致的信息缺失。

上下文裁剪规则：

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `max_context_chars` | 6000 | prompt 总上下文上限 |
| `max_context_chars_per_source` | 1600 | 单个来源上下文上限 |
| `min_chunk_chars` | 20 | 过短 chunk 过滤阈值 |

`/ask` 默认会调用兼容 OpenAI 接口的 DeepSeek 服务：

| 项 | 当前配置 |
| --- | --- |
| provider | DeepSeek-compatible API |
| 默认模型 | `deepseek-v4-pro` |
| 默认 base URL | `https://api.deepseek.com` |
| API key 环境变量 | `DEEPSEEK_API_KEY_RAGLEARN` |
| temperature | 0.1 |
| max_tokens | 1500 |

如果传 `use_llm=false`，系统只返回检索片段，不调用外部 LLM。LLM 调用失败时，也会返回 retrieval-only fallback，并保留 `llm_error`。

## 7. 返回结果

`/ask` 主要返回：

- `answer`
- `citations`
- `retrieval`
- `routing`
- `pipeline`
- `index`
- `llm_error`
- `rerank_error`

`citations` 用于答案引用展示，`retrieval` 用于调试检索命中。当前 citation 和 retrieval 会尽量保留以下 evidence 字段：

- `evidence_id`
- `source_doc_id`
- `modality`
- `evidence_kind`
- `asset_path`
- `parser_backend`
- `source_name`
- `page`
- `section_path`
- `context_before`
- `context_after`

`index` 调试信息会返回当前后端。默认 Milvus 返回 `backend="milvus"`、
`collection_name` 和 `milvus_uri`；显式 FAISS fallback 返回 `backend="faiss"`。
`/health` 额外返回 `milvus_configured`、`milvus_connected`、`milvus_collection`
和 `milvus_error`，用于判断 Docker/Milvus/collection 是否就绪。

回答中仍使用 `[1]`、`[2]` 形式引用资料。资料不足时，prompt 要求模型明确说明资料不足，而不是编造。

## 8. 验证方式

语法检查：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app course_rag\eval
```

检索验证建议使用 `/search`，它本身不调用外部 LLM：

```json
{
  "query": "FIRST FOLLOW 表格",
  "top_k": 3,
  "modality": "table"
}
```

OCR 检索可用：

```json
{
  "query": "状态图",
  "top_k": 3,
  "evidence_kind": "ocr_text"
}
```

Milvus 与 FAISS 快速对比：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast --index-backend milvus --compare-index-backend faiss --no-write-doc
```

当前已完成的 Milvus 主线验证：

| 验证项 | 结果 |
| --- | --- |
| Python 语法检查 | `compileall course_rag\app course_rag\eval` 通过 |
| Milvus dry-run | 读取到 9138 chunks、5840 parents、512 维向量 |
| Milvus rebuild | `inserted=9138`、`entity_count=9138` |
| Milvus check | 可返回合法 citation |
| `/health` | `status=ok`、`milvus_connected=true` |
| 默认 `/search` | 返回 `index.backend="milvus"` |
| 默认 `/ask(use_llm=false)` | 返回 `index.backend="milvus"` |
| 显式 FAISS fallback | 返回 `index.backend="faiss"` |
| fast eval | Milvus 无运行错误 |
| Milvus vs FAISS | Top-K overlap 平均值 `0.9895`，Top-1 变化率 `0.0` |

## 9. 当前 Pipeline

默认 `strategy="hybrid"` 时：

```text
load_milvus_index
-> encode_query
-> milvus_candidate_search
-> bm25_candidate_search
-> rrf_fusion
-> metadata_route_query
-> metadata_filter_candidates / metadata_filter_fallback
-> metadata_boost_candidates
-> rerank_candidates
-> filter_short_chunks
-> deduplicate_by_parent
-> assemble_context
-> llm_generation / retrieval_only_fallback
```

显式使用 FAISS fallback 时，pipeline 中的 `load_milvus_index` 和
`milvus_candidate_search` 会变为 `load_faiss_index` 和 `faiss_candidate_search`；
BM25、RRF、metadata routing、rerank 和 parent context 逻辑保持不变。
