# RAG 项目面试复盘

## 项目定位

项目名称：北航课程资料 RAG 智能问答系统

一句话介绍：这是一个面向课程课件、往年试题、答案、课堂笔记和截图资料的本地 RAG 问答系统，通过统一 evidence 建模、SQLite docstore、Milvus 混合检索、metadata routing、rerank 和来源引用，解决学习资料分散、检索低效、LLM 回答缺少可追溯依据的问题。

适合投递方向：AI 应用开发 / RAG 工程 / LLM 应用实习。

## 简历 Bullet 最终版

- 基于 FastAPI、SQLite docstore、Milvus、BGE Embedding 构建面向课程资料的 RAG 智能问答系统，支持 PDF、Markdown、TXT、DOCX、图片元数据、OCR 文本和表格证据入库，并通过 citation 返回可追溯来源。
- 设计 `EvidenceDocument` 统一证据层，将文本、表格、OCR、图片引用等资料统一保留 `course/source/page/evidence_kind` 等 metadata，支撑按课程、文件、页码、模态和证据类型的定向检索。
- 将 SQLite 作为本地 source of truth，保存 documents、evidence、parents、chunks、metadata 和 ingest run；Milvus 只作为检索索引，保存 chunk_id、dense vector、BM25 sparse/full-text 字段和过滤字段。
- 实现 Milvus 内 dense + BM25 sparse/full-text 混合检索链路，使用 RRF 融合多路召回结果，并接入 metadata routing、父子 chunk 上下文和可选 rerank，提升课程资料问答中的召回稳定性和排序可解释性。
- 构建小型课程问答评测集，覆盖文本、表格、OCR、图片定位、metadata routing 和资料不足拒答；当前 fast 诊断在 21 条样本上跑通，`error_rate=0`、`evidence_hit@k=0.8421`、`citation_validity=0.9524`。

## 3 分钟项目讲述稿

我做的项目是一个面向课程资料的 RAG 智能问答系统，主要解决复习时资料分散和答案不可追溯的问题。课程资料里既有课件 PDF、往年试题、答案，也有 Markdown 笔记、DOCX、截图和表格。普通 PDF QA demo 往往只处理纯文本，遇到指定文件、指定页、表格或截图内容时效果不稳定，所以我把项目重点放在证据建模、检索链路、存储结构和评测闭环上。

系统离线部分先通过 data manifest 管理资料，再用 PyPDF、Docling、native reader 和 RapidOCR 把不同格式统一转换成 `EvidenceDocument`。每条 evidence 都保留课程、类别、文件名、页码、模态、证据类型等 metadata。之后做父子 chunk 切分，child chunk 用于检索，parent context 用于回答上下文。当前存储上分成两层：SQLite docstore 是本地真源，保存 documents、evidence、parents、chunks 和 ingest run；Milvus 是唯一在线检索索引，保存 chunk_id、dense vector、BM25 sparse/full-text 字段和常用过滤字段。

在线查询时，系统默认走 hybrid retrieval。问题会同时进入 Milvus dense vector 检索和 Milvus BM25 sparse/full-text 检索，dense 负责语义召回，BM25 负责关键词、文件名、题号和术语匹配，再用 RRF 融合排序。融合前后会结合 metadata routing，如果用户指定课程、文件、页码、表格或 OCR 类型，能下推到 Milvus 的过滤先下推；如果过滤没有结果，会回退到更宽候选，避免规则过强导致无答案。最后可选接入 `BAAI/bge-reranker-base` 精排，并回 SQLite 取 parent context 和 citation。`/search` 可以只看检索证据，`/ask` 可以进一步调用 LLM 生成带引用的答案。

我在这个项目里的二次开发主要包括三块。第一是 evidence-first 数据建模，把文本、OCR、表格和图片引用放进同一套证据结构。第二是工程化存储和检索链路，把 SQLite 和 Milvus 职责拆清楚，并把 dense、BM25 和 hybrid 统一到 Milvus 内执行。第三是评测体系，不只看答案像不像，还分层看 evidence 命中、召回、MRR、引用覆盖、资料不足拒答和 LLM groundedness。

当前项目在 21 条人工样本上完成了 fast 诊断，覆盖文本、表格、OCR、图片定位、routing 和 negative case。最新 fast eval 中 `error_rate=0`、`llm_error_rate=0`，说明 SQLite docstore + Milvus 主链路可以稳定跑通；`evidence_hit@k=0.8421`、`evidence_recall@k=0.7632`、`citation_validity=0.9524`，说明基本可用但仍有质量优化空间。默认 LLM 评测需要在当前新链路上重新运行后再更新指标。

当前我也能清楚看到系统短板：OCR evidence 虽然能命中部分相关内容，但多证据覆盖和排序还不够稳定；`context_precision@k` 约 0.44，说明上下文中仍有无关片段，会增加 LLM 阅读负担；资料不足样本在离线检索回答下仍需要更稳的拒答策略。下一步会优先优化 OCR/table evidence 的表达、metadata routing 的召回回退和 rerank 输入，再优化上下文压缩。

## 高频面试问题回答提纲

### 1. RAG 完整链路是什么？

RAG 可以分成离线入库和在线问答两部分。

离线阶段：资料解析、清洗、metadata 保留、evidence 建模、chunk 切分、docstore 持久化、检索索引构建。

在线阶段：用户问题编码、Milvus dense/BM25/hybrid 召回、metadata 过滤或加权、rerank、上下文组装、LLM 生成和 citation 返回。

结合本项目，离线侧是 `data_manifest -> loaders -> EvidenceDocument -> parent/child chunks -> SQLite docstore -> Milvus collection`；在线侧是 `Milvus dense/BM25/hybrid -> RRF -> routing -> rerank -> SQLite parent context -> /search 或 /ask`。

### 2. 为什么需要 chunk？

课程资料通常很长，直接把整份 PDF 或整页课件送入 embedding 会导致语义过粗，也会超过 LLM 上下文限制。chunk 的作用是把资料切成适合检索的粒度，让问题能命中具体片段。

本项目采用 child chunk 检索、parent context 生成的方式：child 更细，方便召回；parent 更完整，避免生成时上下文被切得太碎。

### 3. chunk size 和 overlap 如何影响效果？

chunk 太小，召回更精确，但容易丢上下文，回答时缺少完整概念或表格关系。chunk 太大，上下文更完整，但向量语义会变粗，检索结果容易混入无关内容。

overlap 可以缓解边界信息被切断的问题，但 overlap 太大会增加索引体积和重复召回。本项目当前使用 `chunk_size=500`、`chunk_overlap=80`，是为了在课程资料场景下兼顾概念完整性和检索粒度。

### 4. embedding 检索和 BM25 有什么区别？

embedding 检索是语义匹配，适合“换一种说法”的问题，例如问“滑动窗口流量控制”时，不一定要求资料里出现完全相同的问句。

BM25 是词项匹配，更适合文件名、题号、专业术语、页码附近内容和表格关键词。例如 FIRST/FOLLOW、TCP SYN/ACK、具体试卷文件名这类问题，BM25 往往更稳。

### 5. 为什么混合检索通常比单一检索稳？

单一 dense 检索可能漏掉强关键词约束，单一 BM25 又无法处理语义改写。混合检索把两者优势结合起来。

本项目 dense 和 BM25 都由 Milvus 执行，再用 RRF 按排名融合。RRF 不依赖不同检索器的原始分数尺度，工程上更稳定，也便于调试每个候选来自哪个 retriever。

### 6. rerank 放在 pipeline 的什么位置？

rerank 通常放在召回之后、最终截断和上下文组装之前。先用 dense/BM25 快速召回一批候选，再用 reranker 对 query-document pair 做更精细的相关性判断。

本项目链路是 Milvus hybrid 召回和 RRF 融合后，结合 metadata routing，再对候选做可选 rerank，最后过滤短 chunk、按 parent 去重并组装上下文。

### 7. 如何做引用溯源？

关键是从入库开始保留 metadata，而不是生成答案时临时猜来源。本项目在 `EvidenceDocument` 阶段保留 `source_name`、`page`、`section_path`、`evidence_id`、`asset_path`、`evidence_kind` 等字段。chunk 和 parent 写入 SQLite docstore，Milvus 只保存检索所需字段；检索命中后回 SQLite 取完整上下文和 citation。

这样回答里的 `[1]`、`[2]` 能对应到具体文件、页码或图片路径，方便用户回到原始资料验证。

### 8. Recall@K 和 MRR 分别衡量什么？

Recall@K 衡量 Top-K 结果是否覆盖了应该找到的证据，重点是“找没找到”。如果一个问题需要多个证据，Recall@K 可以看覆盖比例。

MRR 衡量第一个正确证据排得靠不靠前，重点是“排得好不好”。如果正确证据排在第一位，MRR 更高；如果排到后面，虽然 Recall@K 可能命中，但用户体验和后续生成质量都会受影响。

### 9. 如果回答幻觉，如何定位是检索问题还是生成问题？

我会先看 `/search` 或 `/ask(use_llm=false)` 的检索结果。如果 Top-K 里没有正确 evidence，问题主要在解析、chunk、embedding、BM25、routing 或 rerank。此时看 evidence_hit、recall、MRR 和 routing debug。

如果检索结果已经包含正确 evidence，但 LLM 仍然答错或编造，问题更多在上下文组装、prompt、context 太长太杂或模型生成阶段。此时看 context_precision、citation 是否覆盖、answer_fact_coverage 和 groundedness。

### 10. 你的项目和普通 PDF QA demo 有什么区别？

普通 PDF QA demo 通常只做“PDF 文本 -> chunk -> 向量检索 -> LLM”，能跑通但可解释性和复杂资料支持有限。

本项目区别在于：第一，做了 evidence-first 数据建模，支持文本、表格、OCR、图片元数据和 Markdown 图片引用；第二，把 SQLite docstore 和 Milvus 检索索引分层，避免检索索引承担完整文档真源职责；第三，支持 Milvus dense/BM25/hybrid、RRF、metadata routing、rerank 和 parent context；第四，答案返回 citation，可以追溯到具体来源；第五，有小型评测集，能用 evidence hit、recall、MRR、citation coverage、abstention 等指标解释效果和问题。

## 面试中可以主动强调的点

- 我没有只做一个 LLM wrapper，而是把资料解析、docstore、检索索引、生成和评测做成了完整闭环。
- 我能解释每个模块的作用和取舍，例如为什么需要 BM25、为什么 metadata 要从入库开始保留、为什么 child chunk 检索但 parent context 生成。
- 我没有把项目夸成生产级系统，当前定位是本地课程资料 RAG；优势是链路完整、可复现、可调试、可评测。
- 我知道当前短板：OCR 排序、多证据覆盖、context precision、资料不足拒答和端到端延迟。

## 不建议在简历中这样写

- 不写“生产级高并发 RAG 平台”，当前没有高并发压测和线上部署证据。
- 不写“支持大规模知识库”，当前是本地课程资料和 9138 个 chunk。
- 不写“多模态 RAG 完整支持”，当前视觉内容主要通过 OCR、图片元数据和图片引用进入文本检索，不是视觉向量检索。
- 不写“评测集 30+”，当前真实人工样本是 21 条。
- 不写“VLM caption 默认参与检索”，caption provider 已接入但默认关闭，当前索引中 `caption=0`。

## 可追问细节准备

| 追问方向 | 回答要点 |
| --- | --- |
| 为什么选 BGE small | 中文效果可用，模型较轻，适合本地课程资料实验；维度 512，构建和查询成本可控。 |
| 为什么引入 Milvus | Milvus 更接近在线服务形态，支持 collection 管理、scalar filter、JSON 字段、BM25 sparse/full-text 和 hybrid search，便于后续扩展。 |
| 为什么引入 SQLite docstore | 检索索引不应该成为完整文档真源；SQLite 适合本地保存 documents/evidence/parent/chunk/metadata，便于重建、调试和回溯 citation。 |
| 为什么做 metadata routing | 课程问答经常有“只看某课程/某文件/某页/某类证据”的约束，仅靠向量相似度不够稳定。 |
| 为什么 `context_precision@k` 不高 | Top-K 中会混入相关但非目标片段，尤其 OCR 和跨章节概念；后续要优化 evidence 权重、候选过滤和 rerank 输入。 |
| 如何改进 OCR | 优化 OCR evidence 的 chunk 表达，加入 evidence 类型权重，对截图类问题增强 routing，并扩充 OCR 金标样本。 |
