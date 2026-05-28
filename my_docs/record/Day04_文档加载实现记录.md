# Day04 文档加载实现记录

## 模块定位

Day04 负责把 `course_rag/data/` 下的课程资料转换成统一的 `LoadedDocument`，并为后续 chunk、索引、检索、问答引用提供稳定元数据。

当前文档加载层不追求“一个工具解析所有格式”，而是采用 **manifest 驱动的混合解析策略**：

```text
data_manifest.jsonl
-> 根据文件类型、文本可抽取性、优先级路由解析器
-> 输出统一 LoadedDocument
-> Day05 chunking
```

## 最终解析策略

| 数据类型 | 默认解析方式 | 原因 |
| --- | --- | --- |
| Markdown 课堂笔记 | 原生读取 `markdown_native` | 保留标题、列表、图片引用，最稳定 |
| 文本型 PDF 课件 | `pypdf` 按页抽取 `pdf_text_layer` | 内容覆盖完整，速度快，天然保留页码 citation |
| DOCX / PPTX / 复杂文档 | Docling `docling_document` | 能输出 Markdown/JSON，结构化能力更强 |
| 低文本 PDF / 扫描件 | v2：OCR 或 Docling OCR | 当前不阻塞 MVP |
| Markdown 中引用的图片 / 单独图片 | v2：OCR 或 VLM caption | 需要结合上下文处理，不适合孤立入库 |
| 表格密集页 / 图示密集页 | v2：专项解析 | 需要质量评估后按需增强 |

这套策略的核心目标是：

```text
内容完整性 > 页码可追踪 > 结构保留 > 多模态增强
```

对当前两周简历项目而言，先保证文本 RAG 主链路稳定跑通，再做少量高价值增强，比一开始追求全量多模态解析更现实。

## 为什么 PDF 不默认使用 Docling

最初尝试过让 PDF 也默认走 Docling，但在本地 CPU 环境下，部分课件 PDF 会触发 Docling PDF pipeline 的页面预处理失败：

```text
Stage preprocess failed ... std::bad_alloc
```

问题的关键不是 Docling 完全不可用，而是：

1. Docling 的 PDF pipeline 不只是抽文本，还会做页面渲染、layout 检测、表格结构、图片区域等更重的处理。
2. 课件 PDF 页数多、图片和版面元素多，本地 CPU/内存环境下容易出现局部页面处理失败。
3. Docling 可能仍返回一个 Markdown，但内容覆盖不完整，存在“静默截断”的风险。
4. 当前课程 PDF 多数有文本层，`pypdf` 按页抽取能更稳定地拿到完整文本和页码。

因此，当前默认路线是：

```text
文本型 PDF -> pypdf -> page-level LoadedDocument
DOCX/PPTX/复杂文档 -> Docling
低文本/扫描 PDF -> v2 再做 OCR/多模态增强
```

## pypdf 的风险与补救

`pypdf` 也不是完美解析器，它主要抽 PDF 内嵌文本层，存在这些风险：

- 图片、流程图、截图公式中的内容会丢失。
- 双栏或复杂布局的阅读顺序可能不稳定。
- 表格结构可能被展开成普通文本。
- 页眉页脚可能混入正文。

当前补救策略：

- 每页作为父文档，保留 `source + page`，降低跨页顺序错乱风险。
- Day05 按页内文本再做 chunk，避免把不同页硬拼在一起。
- 后续通过评测和人工抽查识别 `low_text_page`、`image_heavy_page`、`table_like_page`。
- 对这些问题页进入 V2 backlog，不阻塞 MVP。

## PDF 文本规范化

在实际检查 `pypdf` 解析结果时，发现部分课件页会出现严重硬换行，例如几个字甚至一个字占一行。这会影响 Day05 chunking 和后续 BM25 / embedding：

- chunk 容易被切得过碎，语义不完整。
- BM25 可能因为术语、短语被拆开而召回变差。
- embedding 对轻微换行不敏感，但对大量断字断句仍会降低语义表达质量。

因此当前在加载层加入 `pdf_line_merge_v1` 规范化策略：

```text
pypdf raw page text
-> normalize_page_text
-> LoadedDocument(page_content=clean_text)
-> Day05 chunking
```

当前规则偏保守，只处理明显的 PDF 抽取噪声：

- 合并连续短行、单字行、断词行。
- 中文行合并时默认不加空格。
- 英文/数字断行合并时按需加空格，连字符断词会去掉 `-`。
- 列表项、编号项、疑似表格行不强行合并。
- 保留 `source + page`，不跨页合并。

加载后的 PDF 文档 metadata 会标记：

```text
text_normalized = true
normalization_strategy = pdf_line_merge_v1
```

这属于 MVP 内必须做的数据清洗，不放到 v2。v2 只处理更复杂的图片页、扫描件、表格结构和多模态增强。

## 图片与多模态策略

当前数据中的图片主要是：

```text
课堂总结笔记 imags/ 下的截图
少量作业 jpg 图片
```

它们不是从 PDF 中拆出来的图片。PDF 中的图片目前没有单独抽取成文件。

图片不建议在 MVP 阶段孤立入库，因为图片脱离所在 Markdown 段落、章节、课程上下文后，检索价值不稳定。更合理的 v2 方案是：

```text
Markdown image_refs
-> 继承所在笔记/章节上下文
-> OCR 或 VLM caption
-> 生成 image-aware chunk
-> metadata 链回原 Markdown、图片路径、课程、章节
```

PDF 中的图片页同理，不直接把图片扔进向量库，而是按页挂载：

```text
PDF page
-> pypdf 文本
-> 判断文本少/图片密集
-> 渲染该页为图片
-> OCR 或 VLM caption
-> 合并为 page-level enhanced document
```

## 统一输出结构

无论底层解析器是什么，最终都输出统一结构：

```python
LoadedDocument(
    page_content="...",
    metadata={
        "doc_id": "...",
        "source": "...",
        "course": "...",
        "category": "...",
        "file_type": "...",
        "priority": "...",
        "parser_backend": "...",
        "parse_strategy": "...",
        "page": 1,
        "loader": "...",
        "parsed_markdown_path": "...",
        "parsed_json_path": "...",
        "text_length": 1234
    }
)
```

Day05 只依赖这个统一接口，不依赖具体解析库。


## 对 Day05 的影响

Day05 chunking 建议按来源分流：

- Markdown：按标题层级切分。
- PDF：先按页作为父文档，再做页内 recursive chunk。
- DOCX / Docling 文档：按 Markdown 标题、列表、表格结构切分。

这样能兼顾检索粒度、页码引用和后续 v2 增强。
