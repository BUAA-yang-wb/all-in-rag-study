# V2 增强功能 Backlog

本文档只记录 V2 阶段的方向性规划：哪些资料格式需要处理，以及为了提升整体 RAG 效果，推荐怎样调整架构、策略和模型。不作为立即实现清单。

## 当前状态

当前 `course_rag` 已完成文本 RAG 主流程：

```text
LoadedDocument
-> ParentDocument / ChunkedDocument
-> bge-small-zh-v1.5 + FAISS
-> BM25 hybrid + RRF
-> 可选 bge-reranker-base
-> FastAPI /ask /search
```

当前索引主要覆盖 `priority=mvp` 的文本资料。manifest 中还有大量 V2 资料未充分进入 RAG：

- `priority=mvp`：71 个资料，已进入当前文本索引。
- `priority=v2`：192 个资料，其中 177 个是图片类 `docling_image`。
- 需要重点补齐：图片、截图、低文本 PDF、扫描页、表格、页面布局和试卷类资料。

## V2 推荐目标架构

V2 不应只在现有框架上做小修小补，也不应只把图片 OCR 后当普通文本塞进库。更合理的目标是“文本证据 + 视觉证据 + 表格证据”的混合 RAG：

```text
原始课程资料
-> 解析与证据抽取
-> EvidenceDocument 统一证据层
-> 文本证据 / 表格证据 / 视觉证据
-> 文本索引 + 视觉索引
-> 查询路由 + 混合检索 + rerank
-> 文本生成 / 多模态生成
-> 可追溯引用：source / page / section / asset_path / evidence_id
```

核心调整：

- 增加 `EvidenceDocument`，放在 loader 和 chunk/index 之间。
- 图片、页面截图、扫描页不能只做 OCR；OCR 只能读出文字，不能稳定理解流程图、结构图、布局关系和图表含义。
- 视觉资料应同时生成 OCR 文本、VLM 语义描述，并保留原图/页图用于视觉检索或多模态生成。
- V2 最终推荐用 Milvus 作为向量数据库；FAISS 只作为当前 baseline 和文本-only fallback。

## 文件格式处理策略

| 资料类型 | V2 处理策略 | 推荐技术 |
| --- | --- | --- |
| Markdown | 原生读取正文；保留标题层级；提取 `image_refs`，把图片与所在章节上下文绑定。 | 当前 native loader + EvidenceDocument |
| 文本层 PDF | 按页抽取正文；页作为 parent；保留 page citation。 | `pypdf` + 现有 parent-child chunk |
| 低文本/扫描 PDF | 页级检测；低文本页渲染为图片；同时做 OCR、VLM 页面描述、表格/布局抽取。 | Docling / PaddleOCR / Qwen2.5-VL |
| PPTX / 复杂课件 | 优先保留页面结构；必要时按页渲染成图片，再走页面级 OCR + VLM。 | Docling + 页面渲染 + VLM |
| DOCX | 正文直接解析；表格单独抽取；图片作为 image evidence。 | Docling 或现有 docx fallback |
| PNG/JPG 截图 | 作为一等视觉证据，不直接切普通文本；生成 OCR 文本、VLM caption，并保存 `asset_path`。 | PaddleOCR + Qwen2.5-VL |
| 表格 | 单独形成 table evidence；小表整表入库，大表按行组切分但保留表头。 | Docling table structure / VLM 表格理解 |
| 图示/流程图/状态图 | 不依赖 OCR；必须用 VLM 生成结构化说明，必要时进入视觉索引。 | Qwen2.5-VL + ColPali/ColQwen |

## EvidenceDocument 设计

统一证据层建议字段：

```text
evidence_id
source / source_name
course / category
page / section_path / asset_path
modality: text | pdf_page | image | table
evidence_kind: native_text | ocr_text | caption | layout_text | table_markdown
parser_backend
page_content
context_before / context_after
source_hash / pipeline_version
```

用途：

- 文本、图片、表格、页面都先变成统一 evidence，再决定如何 chunk 和索引。
- citation 可以直接追溯到原文件、页码、章节或图片路径。
- 后续切换索引后端或模型时，不需要重写 loader 的核心语义。

## 模型与索引策略

### 文本索引

V2 如果追求更好的整体效果，推荐把文本索引升级方向定为 `BAAI/bge-m3`：

- 比当前 `bge-small-zh-v1.5` 更适合中英混合、长文本和多粒度检索。
- 支持 dense、sparse、multi-vector 思路，适合后续统一语义召回和关键词召回。
- 当前 `BM25 + bge-small + RRF` 可作为过渡方案，不必立刻删除。

rerank 可继续用当前 `BAAI/bge-reranker-base`；如果本地资源允许，再考虑更强 reranker。

### OCR 与视觉理解

图片处理不能停在 OCR：

- OCR：提取图片或扫描页中的可见文字，推荐本地优先使用 PaddleOCR / PP-OCRv5。
- VLM caption：理解图片含义、流程关系、图表趋势、页面布局，推荐本地优先尝试 Qwen2.5-VL 3B/7B。
- 视觉检索：对页面图、截图、流程图等建立视觉向量，候选方向是 ColPali / ColQwen。

推荐组合：

```text
OCR 文本 -> 文本索引，解决“图片里写了什么”
VLM caption -> 文本索引，解决“图片表达了什么”
原图/页图 -> 视觉索引，解决“哪张图最相关”
```

### 向量数据库

V2 最终推荐迁移到 Milvus，而不是继续只靠 FAISS：

- 支持向量检索和标量字段过滤，适合按课程、文件类型、页码、modality、evidence_kind 过滤。
- 支持 dense / sparse / multi-vector hybrid search，适合后续文本证据、稀疏关键词证据和视觉证据统一检索。
- Docker Compose standalone 部署方式更贴近真实工程项目，也更适合写进简历。
- 相比 FAISS，Milvus 更适合服务化、增量数据管理和后续多模态扩展。

建议迁移节奏：

```text
先保持 FAISS 跑通文本化 evidence
-> Docker Compose 部署 Milvus standalone
-> 建立 Milvus evidence collection
-> 文本向量迁移到 Milvus
-> 再加入 sparse / visual_page 等多向量检索能力
```

## 检索与生成策略

查询时先做轻量 query routing：

- 概念/定义类：走文本 dense + sparse/BM25 + rerank。
- 文件名、页码、题号、术语：提高关键词和 metadata 权重。
- 图片、截图、流程图、状态图、表格、页面类问题：同时召回 text evidence 和 visual evidence。

生成阶段按证据类型选择模型：

- 纯文本问题：继续走文本 LLM，使用 `[1] [2]` 引用。
- 命中 OCR/caption/table evidence：用文本 LLM 回答，但 citation 必须包含 evidence 类型。
- 命中图片或 PDF 页图：如果本地 VLM 可用，应把原图/页图一起传入，而不是只传 caption。
- 回答中必须能追溯到 `source + page` 或 `asset_path`。

## 近期实施顺序

1. 定义 `EvidenceDocument`，统一文本、图片、页面、表格证据。
2. 让现有文本 PDF/Markdown/DOCX 先经过 evidence 层，保持现有行为兼容。
3. 接入图片 evidence：`image_refs`、独立 PNG/JPG、截图，保留上下文和 `asset_path`。
4. 接入本地 OCR，优先处理截图、扫描页、低文本 PDF。
5. 接入 VLM caption，优先处理流程图、状态图、图表和页面布局。
6. 增加 table evidence，保留表头、页码和原始页面路径。
7. 扩展 citation，加入 `evidence_id`、`modality`、`evidence_kind`、`asset_path`。
8. 规划 Milvus evidence collection，并逐步迁移文本向量和视觉向量。
9. 试验 ColPali/ColQwen 页面图检索，用于视觉问题召回。

## 候选参考

- PaddleOCR / PP-OCRv5: https://paddlepaddle.github.io/PaddleOCR/
- Qwen2.5-VL: https://qwenlm.github.io/blog/qwen2.5-vl/
- BGE-M3: https://huggingface.co/BAAI/bge-m3
- ColPali / ColQwen: https://huggingface.co/docs/transformers/en/model_doc/colpali
- Milvus multi-vector hybrid search: https://milvus.io/docs/multi-vector-search.md
- Milvus Docker Compose: https://milvus.io/docs/install_standalone-docker-compose.md
