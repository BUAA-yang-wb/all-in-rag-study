# Course RAG V2 实施计划

最后更新：2026-06-04

本文档记录 `course_rag` V2 阶段增强功能的实施计划和完成状态。阶段 1-5 和阶段 7 已进入当前默认索引；阶段 6 VLM caption 保持默认关闭，不默认生成或索引 caption evidence。

## 1. 当前状态

当前 MVP 阶段已经完成文本 RAG 主链路，系统可以通过 FastAPI 和前端完成课程资料问答与检索调试。

当前主流程为：

```text
LoadedDocument
-> EvidenceDocument(text/native_text)
-> Image evidence / OCR evidence / optional caption evidence
-> ParentDocument / ChunkedDocument
-> BAAI/bge-small-zh-v1.5 + FAISS
-> BM25 hybrid + RRF
-> metadata routing + filter/boost
-> 默认 bge-reranker-base rerank
-> FastAPI /ask /search
-> 前端问答与检索工作台
```

当前已经具备：

- 文档加载：Markdown、文本层 PDF、DOCX 等文本资料。
- 父子 chunk：child chunk 用于检索，parent document 用于生成上下文。
- 检索：dense、BM25、hybrid 三种策略，默认 hybrid。
- 精排：默认开启 `BAAI/bge-reranker-base`。
- routing：已支持课程、文件、页码、证据类型等可选过滤与调试返回。
- API：`/ask`、`/search`、`/ingest`、`/health`。
- 评测：已有 30 条文本 RAG 离线评测集。
- V2 text evidence：已支持 `EvidenceDocument`、稳定 `evidence_id`、citation 扩展字段和默认 text evidence 索引。
- V2 visual evidence：已支持独立图片、Markdown `image_refs`、RapidOCR OCR 缓存和可选 caption provider；当前默认索引已包含图片 metadata/image_ref 和 OCR evidence，未包含 caption evidence。
- V2 table evidence：已支持 Docling JSON 表格优先、Markdown/PDF 类表格文本兜底的混合抽取策略。

当前文本链路已经足够作为 V2 的稳定 baseline。V2 不应一开始就替换 embedding、迁移 Milvus 或重做所有模块，而应围绕当前真实缺口逐步增强。

当前已构建索引的实际状态：

| 项 | 当前值 |
| --- | --- |
| 索引更新时间 | 2026-06-04 09:55:42 |
| priority 范围 | `mvp,v2` |
| evidence 总数 | 5724 |
| native_text evidence | 4243 |
| image_metadata evidence | 177 |
| image_ref evidence | 167 |
| OCR evidence | 998 |
| table evidence | 139 |
| caption evidence | 0；默认关闭 |
| chunk / parent 数量 | 9138 chunks / 5840 parents |
| 来源文件数 | 263 |

本地环境约束：

- GPU：NVIDIA GeForce RTX 3050 Laptop GPU，显存 4GB。
- 当前已缓存模型：`BAAI/bge-small-zh-v1.5`、`BAAI/bge-reranker-base`、Docling 相关模型。
- 已下载 V2 候选模型：`Qwen/Qwen3-VL-2B-Instruct-GGUF` Q4 GGUF 与 mmproj，以及 `PP-OCRv5_mobile_det`、`PP-OCRv5_mobile_rec`。
- OCR 默认使用当前虚拟环境已安装的 RapidOCR；PP-OCRv5 Paddle 模型后续作为可选 provider。
- VLM caption provider 已作为可选离线能力接入；当前未把 VLM 作为在线问答依赖。
- 由于显存较小，V2 不应把 VLM 放到在线 `/ask` 主链路中实时推理，应优先作为离线证据构建工具。

## 2. V2 主要缺口

当前 `data_manifest_summary.json` 中，资料规模大致为：

- `priority=mvp`：71 个资料，已进入当前 V2 evidence 索引。
- `priority=v2`：192 个资料，当前已进入文本、图片 metadata/image_ref、OCR 和 table evidence 索引层；caption 仍默认关闭。
- `docling_image`：177 个，主要是图片、截图和图像型资料。
- 文件级低文本 PDF：21 个，需要页级 OCR 或视觉理解；OCR 候选页不再只按整个文件判断。
- 含图片引用的 Markdown：18 个，需要把正文上下文与图片 evidence 关联。

因此 V2 的核心问题不是“文本检索模型不够强”，而是大量课程资料还没有被抽取成可检索、可引用、可追溯的证据。

需要重点补齐：

- 图片、截图、流程图、状态图。
- 低文本 PDF、扫描页、页面截图。
- 表格、试卷、复杂课件布局。
- Markdown 中引用的图片与所在章节上下文。
- citation 对页码、图片路径、证据类型的追溯能力。
- 宽泛问题、指定课程、指定文件、指定页码、题号类问题的 metadata routing。

## 3. V2 总体策略

V2 推荐先引入统一证据层 `EvidenceDocument`，放在 loader 与 chunk/index 之间。

目标架构：

```text
原始课程资料
-> loader / parser
-> EvidenceDocument 统一证据层
-> 文本证据 / 图片证据 / OCR 证据 / VLM caption / 表格证据
-> chunk 与索引
-> metadata routing + hybrid retrieval + rerank
-> 文本生成 / 后续多模态生成
-> 可追溯 citation
```

离线构建与在线检索分工：

```text
离线构建阶段
原始资料
-> 解析为 EvidenceDocument
-> OCR / VLM caption / table markdown 缓存
-> chunk
-> 文本索引：native_text + ocr_text + table_markdown + optional caption
-> 后续可选视觉索引：page_image / image

在线查询阶段
用户问题
-> query routing
-> metadata 过滤或加权
-> dense + BM25 hybrid
-> RRF 融合
-> rerank
-> evidence/group 去重
-> 组装上下文
-> 返回 answer + citations + retrieval detail
```

VLM 在 V2 中的定位：

- VLM 只默认用于离线生成 `caption` 或 `layout_text` evidence，不默认进入在线问答路径。
- OCR 负责“图里写了什么字”，VLM 负责“图、流程、页面布局表达了什么”。
- VLM 输出必须缓存，并保留原始 `asset_path`，不能只保存 caption。
- 在线 `/ask` 优先检索已经生成好的 OCR/caption/table evidence，再交给文本 LLM 回答。
- 只有后续明确需要多模态生成时，才考虑把命中的原图或页图传给 VLM/多模态 LLM。

VLM 模型选择：

- 本地优先使用：已下载的 `Qwen/Qwen3-VL-2B-Instruct-GGUF` Q4 量化版本。
- 选择原因：当前本机只有 4GB 显存，7B VLM 不适合本地运行；4B/3B Transformers 方案也可能需要额外量化依赖和更高显存余量；GGUF 量化版本更适合作为离线 caption 生成器。
- 效果优先但不适合作为本机默认：`Qwen/Qwen2.5-VL-7B-Instruct`，文档视觉能力更强，但约 8B 参数，对当前本地显存不现实。
- 可作为后续实验：`Qwen/Qwen3-VL-4B-Instruct` 或 `Qwen/Qwen2.5-VL-3B-Instruct` 的量化部署，但不作为第一优先级。
- 如果后续使用外部 API 或云端 GPU，可以再切换到 7B 或更强 VLM；本地默认仍应保留无 VLM fallback。

`EvidenceDocument` 的作用：

- 把文本、PDF 页、图片、表格统一成同一种可处理对象。
- 让 citation 可以追溯到 `source + page` 或 `asset_path`。
- 后续替换索引后端、接入 OCR/VLM/Milvus 时，不需要重写 loader 与生成层的核心语义。
- 支持对不同证据类型采用不同 chunk、索引、召回和展示策略。

建议字段：

```text
evidence_id
source_doc_id
source
source_name
course
category
page
section
section_path
asset_path
modality: text | pdf_page | image | table
evidence_kind: native_text | ocr_text | caption | layout_text | table_markdown
parser_backend
page_content
context_before
context_after
source_hash
pipeline_version
```

不同资料进入检索的方式：

- 普通文本、Markdown 正文、文本层 PDF、DOCX：生成 `modality=text`、`evidence_kind=native_text`，继续沿用当前 parent-child chunk、dense + BM25 + rerank 流程。
- Markdown 内置图片：Markdown 正文生成 text evidence；`image_refs` 单独生成 image evidence，绑定所在 `section_path`、相邻正文和 `asset_path`；后续为该图片补 OCR evidence 和 caption evidence。
- PDF 扫描页 / 低文本页：启用 OCR 或 caption 后按页检查文本层；文件级低文本 PDF 的已扫描页面全量作为候选页，普通文本层 PDF 只把低于阈值的单页作为候选页；候选页渲染为 page image 后生成 OCR/caption/table evidence。
- 独立 PNG/JPG 截图：生成 `modality=image` evidence，先保存路径、文件名和上下文；后续补 OCR 与 VLM caption。
- 表格：生成 `modality=table`、`evidence_kind=table_markdown`，小表整表入库，大表按行组切分并保留表头。

在线 query routing 策略：

- 概念、定义、原理类问题：默认检索 text/native_text，同时允许 OCR/caption/table evidence 参与召回。
- 指定课程、文件、页码、题号类问题：优先做 metadata filter 或 boost，提高 `course`、`source_name`、`page`、`category` 权重。
- 图片、截图、流程图、状态图、页面类问题：提高 `modality=image|pdf_page` 和 `evidence_kind=caption|layout_text|ocr_text` 权重。
- 表格、对比、统计类问题：提高 `modality=table`、`evidence_kind=table_markdown|caption` 权重。
- routing 失败时必须回退到当前默认 `hybrid + rerank`，避免规则误判导致无结果。

检索返回策略：

- `citations` 继续作为最终回答引用，保持现有字段兼容，同时新增 V2 evidence 字段。
- `retrieval` 继续作为调试信息，展示命中的 evidence 类型、dense/BM25/RRF/rerank 分数、上下文 preview。
- 图片、PDF 页图、表格类 evidence 必须返回 `asset_path` 或 `source + page`，便于用户回到原始资料核对。
- 回答中仍使用 `[1] [2]` 编号引用；citation 展示时应标明证据类型，例如“文本”“图片说明”“OCR 文本”“表格”。

建议扩展返回字段：

```text
evidence_id
source_doc_id
modality
evidence_kind
asset_path
parser_backend
context_before
context_after
```

## 4. 分阶段实施顺序

### 阶段 1：EvidenceDocument 与 citation 字段规划（已完成）

目标：

- 定义 V2 的统一证据对象和 citation 扩展字段。
- 明确哪些字段必须稳定，哪些字段允许为空。
- 保持 `/ask`、`/search` 返回结构向后兼容。

主要改动点：

- 新增 evidence 数据结构。
- 设计 `LoadedDocument -> EvidenceDocument` 的兼容转换。
- 扩展 citation 计划字段：`evidence_id`、`modality`、`evidence_kind`、`asset_path`、`parser_backend`。
- 确定 evidence 文件缓存格式，优先使用 JSONL，便于调试和后续重建。

验收标准：

- 已能把现有 MVP 文本资料转换为 text evidence。
- 已为每条 evidence 生成稳定 `evidence_id`。
- citation 已保留旧字段，并附加 evidence 字段。
- Day11 文本评测已验证无退化。

风险：

- 过早设计过复杂 schema 会拖慢后续实现。
- `evidence_id` 如果依赖不稳定字段，会导致索引重建后引用难以对齐。

### 阶段 2：现有文本链路兼容迁移到 evidence 层（已完成）

目标：

- 让现有文本资料先经过 evidence 层，再进入 chunk/index。
- 已切换为当前默认文本链路。

主要改动点：

- Markdown、文本层 PDF、DOCX 的正文先转换为 text evidence。
- 原有 parent-child chunk 策略继续保留。
- `source`、`page`、`section_path` 等元数据从 evidence 透传到 chunk。
- 默认索引目录已切换为 `course_rag/vector_index_v2_text/`。

验收标准：

- `/search` 和 `/ask` 在 `use_llm=false` 下已能返回带 evidence 字段的文本证据。
- Day11 文本评测已验证无退化。
- 前端 evidence 列表已支持展示 evidence 调试字段。

风险：

- 元数据透传遗漏会影响 citation。
- 兼容迁移阶段不应同时更换 embedding 或索引后端，否则难以定位回归来源。

### 阶段 3：metadata routing 与课程/文件/页码过滤（已完成）

目标：

- 优先解决宽泛问题、指定课程、指定文件、指定页码、题号类问题。
- 在多模态前先增强当前文本检索的可控性。

主要改动点：

- 增加轻量 query routing，识别课程名、文件名、页码、题号、图片/表格意图。
- API 已增加可选过滤字段：`course`、`category`、`source_name`、`page`、`modality`、`evidence_kind`。
- 检索时对显式 metadata 命中的候选过滤，对自动识别条件支持失败回退。
- 已记录 routing 调试信息，便于前端和评测分析。

验收标准：

- 指定课程或文件的问题已能限制到对应 metadata 范围。
- 指定页码问题已能优先返回对应页码候选。
- 自动 routing 失败时已能回退到当前 hybrid 检索。

风险：

- 规则过强可能误过滤相关资料。
- 文件名匹配需要处理中文、空格、全角符号和部分文件名输入。

### 阶段 4：图片 evidence 与 Markdown image_refs（已完成）

目标：

- 让独立 PNG/JPG 和 Markdown 中引用的图片成为一等 evidence。
- 先保存图片路径、上下文和基础元数据，不急于生成复杂视觉向量。

主要改动点：

- 已为 `docling_image` 资料生成 `image/image_metadata` evidence。
- 已解析 Markdown `image_refs`，把图片与所在章节上下文绑定为 `image/image_ref` evidence。
- `asset_path` 使用 repo-relative 路径，避免不同机器上的绝对路径失效。
- 图片 evidence 的 `page_content` 由 alt 文本、文件名、课程分类和相邻正文组成。
- 同一图片可派生 OCR evidence 和 caption evidence，并通过相同 `asset_path` 或 `source_doc_id` 关联。

验收标准：

- 图片资料可以在 evidence 缓存中看到。
- 每个图片 evidence 都有 `asset_path`、`source`、`course`、`category`。
- Markdown 引用图片能带上所在 section 上下文。
- `/search` 返回图片相关 evidence 时包含 `asset_path`、`modality`、`evidence_kind`。

风险：

- 仅靠文件名和 alt 文本召回效果有限。
- 图片路径需要使用 repo-relative 路径，避免不同机器上绝对路径失效。

### 阶段 5：OCR 接入与低文本 PDF 页级处理（已完成）

目标：

- 解决“图片里写了什么”和“扫描页文字无法检索”的问题。
- 先处理截图、独立图片、文件级低文本 PDF 和普通 PDF 中的低文本单页。

主要改动点：

- 已接入本地 OCR provider，默认使用当前虚拟环境中可直接运行的 RapidOCR。
- 已支持 PDF 页级候选判断：文件级低文本 PDF 的已扫描页面全量进入候选；普通文本层 PDF 只选择单页文本字符数低于阈值的页面。
- 当前默认页级阈值是去空白后 `<80` 个字符，可通过 `--pdf-page-low-text-chars` 或 `/ingest.pdf_page_low_text_chars` 调整。
- 候选页才会用 `pypdfium2` 渲染为图片，再生成 OCR evidence；默认不运行 OCR/caption 时不会扫描和渲染 PDF 页。
- OCR 结果作为 `evidence_kind=ocr_text` 进入文本索引。
- OCR 输出写入 `course_rag/data/processed/evidence_ocr.jsonl`，避免每次重建索引重复跑模型。
- PDF 页图路径写入 `asset_path`，citation 同时保留原 PDF 的 `source_name`、`page`、`pdf_page_text_chars` 和低文本原因。
- 已下载的 `PP-OCRv5_mobile_det` 和 `PP-OCRv5_mobile_rec` 暂作为后续可选 provider，不作为当前默认阻塞项。

验收标准：

- 典型截图和扫描页应能抽取可检索文字。
- OCR evidence 应能返回 `source + page` 或 `asset_path`。
- OCR provider 不可用时，系统能跳过并记录错误，不影响文本索引。

当前状态：

- OCR provider、缓存、PDF 页级候选、API/CLI 参数已经接入。
- 已完成 `mvp,v2` 范围 OCR 离线缓存构建，当前 `evidence_ocr.jsonl` 有 998 条 `ocr_text` evidence。
- 默认重建 `run_ocr=false`，不会重新跑 OCR，但会读取已有 OCR 缓存并纳入索引。
- OCR evidence 已能通过 `/search` 的 `evidence_kind="ocr_text"` 检索返回。

风险：

- OCR 模型下载和 CPU 推理耗时较高；全量 OCR 缓存构建应作为离线任务执行。
- 当前只下载了 PP-OCRv5 模型文件，后续仍需安装 PaddleOCR / PaddlePaddle 等运行时。
- 课件截图、公式、流程图中的文字可能识别不稳定。
- `<80` 字符阈值是工程启发式：适合筛出封面、目录、扫描页、纯图页和题图页，但极短文本页不一定都需要 OCR，后续可结合图片/表格/版面特征继续收窄。
- OCR 只能解决可见文字，不能充分理解图示结构。

### 阶段 6：VLM caption 与视觉语义描述（默认关闭）

目标：

- 解决“图片表达了什么”“流程图/结构图是什么意思”“表格趋势是什么”这类 OCR 不擅长的问题。
- 通过离线批处理生成可检索 caption，不把 VLM 实时放入 `/ask` 主链路。

主要改动点：

- 已增加 VLM caption provider 抽象。
- 本地优先使用已下载的 `Qwen/Qwen3-VL-2B-Instruct-GGUF` Q4 量化版本，但 caption 只作为离线可选批处理。
- caption 作为 `evidence_kind=caption` 进入文本索引。
- 保留原图路径，后续多模态生成时可把图片一起传入模型。
- 生成结果写入 `course_rag/data/processed/evidence_caption.jsonl`；同一 `source_hash`、provider 和 `pipeline_version` 命中时不重复推理。
- VLM 不可用时跳过 caption，仅保留 image metadata 和 OCR evidence。
- 在线 `/ask` 与 `/search` 不实时生成 caption，只检索已经写入缓存并重建进索引的 caption evidence。

验收标准：

- 对典型流程图、页面截图、结构图应能生成可读 caption。
- 显式启用并重建 caption 后，caption evidence 应可以被 `/search` 检索到。
- VLM 不可用时可以只保留 OCR 和图片 metadata。
- 在线 `/ask` 不依赖 VLM 进程，也不会因 VLM 未安装而失败。

当前状态：

- caption provider 抽象和 `llama-cpp-cli` provider 已接入。
- 当前默认索引 `run_caption=false`、`caption_provider=none`，没有 caption evidence。
- 默认重建不会读取旧 caption 缓存，也不会把 caption evidence 纳入索引。
- 后续需要先配置 llama.cpp CLI、GGUF 和 mmproj 路径，再做小样本 caption 质量验证。

风险：

- 本地 VLM 对显存和依赖要求高。
- 当前只下载了 GGUF 模型文件，后续仍需接入 llama.cpp、Ollama 或 llama-cpp-python 等运行时。
- 外部 VLM API 会产生网络调用和费用，需要用户确认。
- caption 可能产生幻觉，必须保留原图 citation，不能只相信 caption。

### 阶段 7：table evidence（已完成）

目标：

- 把表格从普通正文中单独抽出，提升表格题、对比题和试卷题的检索质量。

主要改动点：

- 已新增 `course_rag/app/rag/table_evidence.py`。
- 已新增 `course_rag/data/processed/evidence_table.jsonl`。
- 当前采用混合抽取策略：优先复用 Docling JSON 的 table structure；缺失时从 Markdown 表格和 PDF 类表格文本保守兜底。
- 小表整表转 Markdown 入库；大表按最多 20 行切分，每个 evidence 保留表头。
- table evidence 保留页码、原始 source、表格序号、切片序号和上下文。

验收标准：

- 表格 evidence 可独立检索。
- citation 能标出表格所在 source/page。
- 表格内容不会被普通 chunk 切碎到失去表头。

当前状态：

- 当前 `evidence_table.jsonl` 有 139 条 `table_markdown` evidence。
- 其中 `docling_table` 5 条，`text_table_heuristic` 134 条。
- table evidence 已能通过 `/search` 的 `modality="table"` 检索返回。

风险：

- 复杂课件表格和扫描表格结构识别不稳定。
- 大表切分策略需要兼顾检索粒度和上下文完整性。

### 阶段 8：评测集扩展

目标：

- 为 V2 能力建立可重复验证的评测，而不是凭主观样例判断效果。

主要改动点：

- 在现有 Day11 文本评测基础上新增 V2 问题。
- 覆盖图片、扫描页、表格、指定文件、指定页码、题号、流程图类问题。
- 保留默认 `use_llm=false`，先评测检索和 citation。
- 新增指标：`Evidence Hit Rate`，判断是否命中正确 evidence 类型和证据位置。

验收标准：

- 至少新增 20 条 V2 评测问题。
- 能分别跑文本 baseline 和 V2 evidence 检索实验。
- 每次 V2 关键改动后可以对比结果。

风险：

- gold evidence 标注成本较高。
- V2 资料中图片和扫描页多，人工验证需要看原图或页图。

### 阶段 9：Milvus 与视觉检索实验

目标：

- 在 evidence 层稳定后，再把索引后端从本地 FAISS baseline 扩展到更工程化的 Milvus。
- 逐步验证视觉检索，不把 Milvus 作为 V2 第一阶段阻塞项。

主要改动点：

- 使用 Milvus standalone 作为后续向量数据库候选。
- collection 设计至少包含 metadata 标量字段、文本 dense 向量、文本 sparse/BM25 字段。
- 后续再加入页面图或图片向量。
- 视觉检索候选方向：ColPali / ColQwen 类页面图检索。

验收标准：

- FAISS baseline 仍可运行。
- Milvus 文本 evidence 检索结果能与 FAISS baseline 对比。
- 视觉检索只作为实验开关，不影响默认问答链路。

风险：

- Docker、Milvus 和多向量检索会提高环境复杂度。
- 过早迁移会掩盖 evidence 抽取质量问题。
- 视觉检索模型对本地显存和推理速度有要求。

## 5. 近期优先级

当前完成度判断：

- 阶段 1-3 已完成并稳定进入在线主链路。
- 阶段 4 已完成并进入默认索引，当前已有 177 条 `image_metadata` 和 167 条 `image_ref`。
- 阶段 5 已完成 OCR 缓存构建并进入默认索引，当前已有 998 条 `ocr_text`。
- 阶段 6 caption provider 已接入但默认关闭，当前索引没有 caption evidence。
- 阶段 7 已完成 table evidence 并进入默认索引，当前已有 139 条 `table_markdown`。
- 阶段 8 V2 评测集扩展、阶段 9 Milvus/视觉检索实验尚未开始。

近期不建议优先做：

- 直接替换 `BAAI/bge-small-zh-v1.5`。
- 直接迁移 Milvus。
- 直接上完整多模态生成。
- 在线 `/ask` 实时调用 VLM。
- 只把图片 OCR 后当普通文本塞进现有索引。

近期建议优先做：

1. 扩展 V2 评测集，覆盖图片、OCR、表格、指定页码和题号类问题。
2. 抽样检查 OCR/table evidence 的质量，清理明显误抽或低价值 evidence。
3. 根据评测结果调整 table 文本启发式规则和 OCR 页级阈值。
4. 如确实需要视觉语义理解，再配置并小样本验证 `Qwen3-VL-2B-Instruct-GGUF` caption。
5. 等 evidence 质量稳定后，再做 Milvus 和视觉检索实验。

这样可以先把已经进入索引的 OCR/table evidence 做成可评测、可迭代的稳定能力，再考虑更复杂的索引后端和视觉检索。

## 6. 验证规则

后续真正实施代码改动时，默认遵守以下验证规则：

- 优先使用当前虚拟环境：

```powershell
.\rag\Scripts\python.exe
```

- 代码语法检查：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app course_rag\eval
```

- 涉及 API 时，优先使用 FastAPI `TestClient` 做轻量验证。
- 涉及问答验证时，默认使用：

```json
{
  "use_llm": false
}
```

- 避免默认真实调用外部 LLM、OCR/VLM API、下载模型或安装依赖。
- V2 候选 OCR/VLM 模型文件已下载；OCR 默认可用 RapidOCR，VLM caption 仍需要按需安装或配置 llama.cpp 运行时。
- 如果必须下载模型、安装依赖、启动 Milvus 或调用外部 API，需要先说明影响并等待确认。
