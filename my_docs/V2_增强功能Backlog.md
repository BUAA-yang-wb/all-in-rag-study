# V2 增强功能 Backlog

## 使用规则

这个文件只记录 MVP 暂缓但不能忘的增强项。默认 Day04-Day10 不展开 V2；Day11 评测后再决定是否在 Day12 选 1 个小项做增强。

优先级含义：

- P0：评测或演示明显受影响，Day12 可考虑做。
- P1：有简历亮点或部分问题需要，MVP 后优先做。
- P2：探索项，两周后再做。

## 当前推荐路线

MVP 默认路线保持：

```text
文本型 PDF -> pypdf 按页抽取
Markdown -> 原生读取
DOCX/PPTX/复杂文档 -> Docling
```

Docling 页级增强推荐采用：

```text
优先：Docling page_range 小批量解析问题页
兜底：如果 page_range 仍不稳定，再把 PDF 拆成单页临时文件解析
```

理由：

- `page_range` 不需要生成大量临时 PDF，工程更干净。
- 更容易保留原始 `source + page` 元数据。
- 适合只增强低文本页、图片页、表格页，而不是全量 4000 多页解析。
- 单页拆分更隔离，但文件管理、缓存、清理和 metadata 复杂度更高，应作为 fallback。

## Backlog

### P0. PDF 问题页识别

状态：todo  
触发：Day11 评测前后。  
内容：基于每页文本长度、短行比例、图片占位、表格特征，标记 `low_text_page`、`image_heavy_page`、`table_like_page`。  
验收：输出问题页清单，metadata 可回到 `source + page`。

### P1. PDF 页级增强

状态：todo  
触发：问题页影响问答效果，或需要 README/简历亮点。  
推荐：对 P0 标记页使用 Docling `page_range` 小批量解析；失败时再拆单页 PDF fallback。  
验收：至少一份课件的问题页生成 enhanced text，并保留原始 pypdf 文本、增强文本、解析状态。

### P1. Markdown 图片 OCR / Caption

状态：todo  
触发：课堂笔记截图相关问题召回差。  
内容：读取 Markdown `image_refs`，让图片继承所在标题/章节上下文，再做 OCR 或 VLM caption。  
验收：至少 10 张课堂笔记截图生成可追踪文本，metadata 回到原 Markdown 和图片路径。

### P2. 扫描版 / 低文本 PDF OCR

状态：todo  
触发：确认低文本 PDF 对项目问答价值高。  
内容：优先 RapidOCR/PaddleOCR；必要时尝试 Docling OCR。  
验收：至少一份低文本 PDF 生成可检索文本，并保留 `source + page`。

### P2. 表格页专项解析

状态：todo  
触发：表格类问题在评测中召回失败。  
内容：对 `table_like_page` 比较 Docling、pdfplumber 或其他表格解析方式。  
验收：至少一种表格页能转成结构清晰的 Markdown 表格或键值文本。

### P2. 多模态检索

状态：todo  
触发：MVP、README、评测全部完成后。  
内容：先做 caption 文本入库，不直接做复杂图文向量检索。  
验收：至少能回答一个必须依赖图片说明的问题，并返回图片来源。
