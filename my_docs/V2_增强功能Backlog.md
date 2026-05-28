# V2 增强功能 Backlog

## 目标架构

V2 的目标不是只把图片 OCR 后塞进文本库，也不是一开始完全改成纯多模态检索，而是采用“文本证据 + 视觉证据”的混合 RAG：

```text
原始课程资料
-> 文档解析与证据抽取
-> EvidenceDocument 统一证据层
-> 文本 chunk / 视觉单元
-> 文本向量 + 稀疏向量 + 视觉向量
-> 混合检索 + 重排
-> 文本/多模态生成
-> 带 source/page/asset_path 的答案引用
```

这条路线更适合课程资料：PDF 和 Markdown 里既有大量文字，也有截图、图示、表格、页面布局。纯文本 RAG 会丢视觉信息；纯视觉 RAG 成本高、调试难，也不适合所有文字密集资料。

## 1. 加载与解析策略

### 文本型资料

- Markdown：继续原生读取，保留标题层级，同时提取 `image_refs`。
- 文本层 PDF：继续用 pypdf 按页抽取，保留页码。
- DOCX/PPTX/复杂 PDF：使用 Docling 解析成 Markdown/JSON。

### 少文本 PDF 页

少文本页不要直接整份 PDF 重跑 Docling。推荐做页级增强：

```text
pypdf page text
-> page quality detector
-> low_text_page / image_heavy_page / table_like_page
-> 只增强命中的页
```

增强方式：

- `low_text_page`：渲染该页为图片，做 OCR。
- `image_heavy_page`：生成页面图片，做 VLM caption 或视觉索引。
- `table_like_page`：优先 Docling table structure，输出 Markdown table。
- Docling 用于结构、表格、布局和必要 OCR，不把它当成“万能图像理解器”。

### Markdown 内嵌图片和独立图片

每张图片至少生成两类证据：

- OCR 文本：解决截图、扫描文字、公式旁文字。
- 图片说明：用 VLM caption 描述图示关系、流程、状态转换、图表含义。

图片证据必须继承上下文：

```text
原 md source
所在标题 section_path
图片路径 asset_path
图片前后短文本
```

## 2. EvidenceDocument 统一证据层

V2 建议在 `LoadedDocument` 和 `ChunkedDocument` 中间增加统一证据层。字段建议：

```text
evidence_id
source
page
asset_path
course
category
modality: text | pdf_page | image | table
evidence_kind: native_text | ocr_text | caption | layout_text | table_markdown
parser_backend: pypdf | docling | ocr | vlm_caption
page_content
context_before
context_after
pipeline_version
source_hash
```

这样后续无论来自 PDF 正文、截图 OCR、图像 caption、表格 Markdown，都可以统一进入 chunk、索引、检索和答案引用。

## 3. Chunk 策略

### 文本 chunk

- 普通文本：继续 parent-child chunk。
- PDF：parent 以页为主，child 约 400-600 中文字符，保留页码。
- Markdown：parent 以标题章节为主，child 约 400-600 字符。

### 图片和少文本页 chunk

图片不要直接按普通正文切。建议一个图片形成一个 parent：

```text
[图片上下文]
[OCR 文本]
[VLM 图片说明]
[可选：相关 Markdown 标题路径]
```

如果内容很短，不再切 child；如果 OCR 很长，再按段落切 child，但所有 child 指向同一个图片 parent。

### 表格 chunk

表格不要简单打散成碎片。建议：

- 小表格：整表作为一个 parent。
- 大表格：按行组或逻辑分区切，保留表头。
- 同时保存 `table_markdown` 和原始页码/图片路径。

## 4. Embedding 策略

### 文本检索模型

V2 推荐把默认文本 embedding 升级为 `BAAI/bge-m3`，原因：

- 支持中文/英文混合课程资料。
- 支持 dense、sparse、multi-vector 三类检索能力。
- 1024 维，最长 8192 tokens，适合较长页面和章节。

`Qwen/Qwen3-Embedding-0.6B` 作为对比候选：它支持 100+ 语言、32K 上下文、最高 1024 维，并支持 instruction-aware 查询。它更适合后续做效果对比，但本地推理成本通常高于 bge-m3。

### 视觉检索模型

对于图片、页面截图、视觉布局强的 PDF 页，建议单独建立视觉索引。候选路线：

- ColPali / ColQwen 类页面图像检索模型：适合直接把 PDF 页或图片作为视觉文档检索。
- OCR/caption 文本索引：作为低成本、可解释的文本证据。

最终推荐不是二选一，而是：

```text
OCR/caption/table text -> bge-m3 text index
PDF page image / markdown image -> visual index
```

视觉索引用来召回“图像本身”，文本索引用来召回“图像的文字化解释”。两者互补。

## 5. 向量数据库策略

如果 V2 只做文本化证据，FAISS 还能继续用。但如果目标是完整支持图片、页面、多向量、metadata filter，最终建议迁移到 Qdrant。

推荐 Qdrant collection 设计：

```text
collection: course_rag_evidence

payload:
  evidence_id
  source
  page
  asset_path
  course
  category
  modality
  evidence_kind
  parser_backend
  parent_doc_id
  text
  pipeline_version
  embedding_model_versions

vectors:
  text_dense       # bge-m3 dense
  text_sparse      # bge-m3 sparse，可选
  visual_page      # ColPali/ColQwen multivector 或其他视觉向量
```

选择 Qdrant 的原因：

- 支持 payload 过滤，适合按课程、页码、资料类型、证据类型过滤。
- 支持 named vectors，可在同一证据点挂 text/image 等不同向量。
- 支持 multivectors，适合 ColBERT/ColPali 这类 late interaction 检索。
- 比 FAISS 更适合增量添加、删除、更新和服务化调用。

Milvus 暂不作为首选：它适合更大规模和分布式场景，目前项目规模用 Qdrant 更轻。

## 6. 检索策略

查询时不要只做一次向量搜索。建议流程：

```text
用户问题
-> query analysis
-> 文本 dense 检索
-> 稀疏/关键词检索
-> 视觉检索（当问题涉及图、截图、表、页面、流程关系时启用）
-> metadata filter
-> merge
-> rerank
-> context pack
```

具体规则：

- 普通概念问题：文本 dense + sparse。
- 精确术语、题号、文件名：提高 sparse/keyword 权重。
- “图中”“截图”“流程图”“状态转换图”“第几页”等问题：启用视觉检索。
- 表格问题：优先检索 `table_markdown`，必要时附原页面图片。
- 检索结果按 parent/evidence 合并，避免同一页多个重复 chunk 挤占 Top-K。

重排策略：

- 第一阶段：向量召回 Top 30-50。
- 第二阶段：文本 reranker 重排文本证据。
- 第三阶段：如果有视觉证据，让生成模型或 VLM 判断是否需要附图。

## 7. 生成策略

生成阶段按证据类型选择输入：

### 纯文本答案

输入：

```text
Top text parents
OCR/caption/table markdown
source/page/section metadata
```

输出要求：

- 引用来源。
- 明确页码或图片路径。
- 不确定时说明证据不足。

### 视觉相关答案

如果检索结果包含 `modality=image` 或 `modality=pdf_page`，生成阶段应把原图或页面截图一起传给多模态模型，而不是只传 caption。

输入：

```text
问题
文本证据
OCR/caption
原始图片或 PDF 页截图
metadata
```

原因：OCR/caption 可能遗漏箭头、结构关系、图表趋势、布局含义。真正需要解释图时，生成模型应能看到图。

## 8. 评测指标

V2 的技术选型必须用评测决定，建议分三类问题：

- 文本问题：概念、定义、知识点。
- 表格/页面问题：页码、题目、表格字段。
- 视觉问题：截图、流程图、状态图、图示关系。

核心指标：

- retrieval recall@k
- MRR / nDCG
- answer faithfulness
- citation accuracy
- visual evidence hit rate
- 构建耗时、查询耗时、索引大小

## 近期实施顺序

1. 实现 EvidenceDocument 输出格式。
2. 做 PDF page quality detector。
3. 接入 Markdown 图片 OCR/caption。
4. 接入少文本 PDF 页 OCR/Docling 增强。
5. 用 bge-m3 重建 text index，并加入 sparse/keyword 检索。
6. 用 Qdrant 试验 payload filter 和 named vectors。
7. 对视觉问题试验 ColPali/ColQwen 页面检索。
8. 让生成阶段支持“文本证据 + 原图/页图”输入。

## 参考资料

- ColPali: https://arxiv.org/abs/2407.01449
- VisRAG: https://arxiv.org/abs/2410.10594
- BGE-M3: https://huggingface.co/BAAI/bge-m3
- Qwen3-Embedding-0.6B: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- Docling supported formats: https://docling-project.github.io/docling/usage/supported_formats/
- Docling pipeline options: https://docling-project.github.io/docling/reference/pipeline_options/
- Qdrant vectors: https://qdrant.tech/documentation/manage-data/vectors/
