# Day03 课程资料数据设计记录

## 当前数据概况

数据根目录：

```text
course_rag/data/
```

当前数据已按本地私有资料处理，`course_rag/data` 已被 `.gitignore` 忽略，避免课程资料、作业、试题和生成的 manifest 被误提交。

扫描结果：

| 维度 | 结果 |
| --- | --- |
| 总文件数 | 298 |
| 总大小 | 707.692 MB |
| 课程 | 编译原理 278 个文件；计网 20 个文件 |
| 文件类型 | pdf 97；md 22；docx 2；png 173；jpg 4 |
| MVP 文件 | 71 |
| v2 文件 | 209 |
| skip 文件 | 18 |
| 可抽文本 PDF | 76 |
| 低文本/疑似扫描 PDF | 21 |
| 含图片引用的 Markdown | 18 |

生成文件：

```text
course_rag/data/processed/data_manifest.jsonl
course_rag/data/processed/data_manifest_summary.json
```

## 数据分层策略

当前不直接全量入库，而是通过 `data_manifest.jsonl` 控制后续 loader 的处理范围。

### MVP

第一阶段优先处理：

- 编译原理课堂总结 Markdown
- 编译原理课件 PDF
- 计网课件 PDF
- 少量 DOCX
- 可抽取文本的中小型 PDF

目标是尽快支撑：

- 课程概念解释
- 资料定位
- 复习重点查询
- 跨文档问答
- 引用来源返回

### v2

第二阶段增强：

- 图片资源
- Markdown 中关联图片
- 复习资料
- 部分低文本 PDF
- 后续可能加入的 PPT/PPTX
- OCR 或 VLM caption

### skip

默认跳过：

- 明显含个人信息或作业内容的文件
- 第一阶段不适合公开展示的答案类资料
- 超大且低文本可抽取性的教材/扫描 PDF
- 暂不支持的文件类型

## Manifest 字段

每条记录包含：

```json
{
  "doc_id": "稳定文档 ID",
  "source": "仓库相对路径",
  "course": "课程名",
  "category": "资料类别",
  "file_type": "pdf/md/docx/png/jpg",
  "size_bytes": 0,
  "size_mb": 0.0,
  "visibility": "private/public",
  "priority": "mvp/v2/skip",
  "parse_strategy": "markdown/text_pdf/docx/scanned_pdf_or_low_text/image_asset_v2/unsupported",
  "contains_images": false,
  "image_ref_count": 0,
  "is_text_extractable": true,
  "text_chars_sample": 0,
  "notes": ""
}
```

## 后续 Loader 规则

Day04 的文档加载模块应默认只处理：

```text
priority == "mvp"
```

各类解析策略：

| parse_strategy | 处理方式 |
| --- | --- |
| markdown | 按 Markdown 文本读取，保留标题结构和图片引用 |
| text_pdf | 按页抽取文本，保留 page citation |
| docx | 抽取段落文本，保留段落顺序 |
| scanned_pdf_or_low_text | v2，暂不进入 MVP，可后续接 OCR |
| image_asset_v2 | v2，先登记为图片资产，不直接入向量库 |
| unsupported | 跳过 |

## 项目亮点保留

这套数据处理方式比普通 PDF QA demo 更适合写进简历，因为它体现了：

- 多课程、多格式真实数据处理
- 数据隐私和公开样例隔离
- PDF 可抽取性检测
- manifest 驱动的解析策略
- 图片感知 Markdown，为后续多模态扩展预留空间
- MVP/v2/skip 分层，符合真实工程迭代方式

## 下一步

Day04 开发 `course_rag` 的 loader 时，直接读取：

```text
course_rag/data/processed/data_manifest.jsonl
```

只加载 `priority=mvp` 的记录，并根据 `parse_strategy` 分发到不同 loader。
