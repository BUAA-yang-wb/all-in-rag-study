# Day 04：实现多格式文档加载

## 今日目标

实现课程资料的统一加载层，支持 Markdown / TXT / PDF，并为后续 chunk、索引和引用溯源提供稳定元数据。

## 学习输入

- `code/C2/01_unstructured_example.py`
- `code/C8/rag_modules/data_preparation.py`

## 预计完成工作

1. 实现文件：

```text
course_rag/app/rag/loaders.py
```

2. 支持 Markdown 加载：
   - 保留标题结构。
   - 保留原始 source 路径。
   - 提取文件名作为默认课程资料名。
3. 支持 TXT 加载：
   - 按段落或全文加载。
   - 处理空行和异常编码。
4. 支持文本型 PDF 加载：
   - 先不处理扫描版 OCR。
   - 尽量保留页码信息。
5. 为每个 document 增加稳定 `doc_id`，建议基于相对路径 hash。
6. 输出统一 Document 结构，字段至少包括：
   - `page_content`
   - `source`
   - `doc_id`
   - `file_type`
   - `course`
   - `page`

## 验收标准

- 能读取 `course_rag/data/samples/` 中的 md/txt/pdf。
- 能打印文档数量、总字符数、文件类型分布。
- 对解析失败的文件有清晰错误日志。
- 每个文档都能追溯到原始文件。

## 当日输出

- `course_rag/app/rag/loaders.py`
- 一个加载测试命令或脚本。
- `my_docs/Day04_文档加载实现记录.md`

## 风险处理

PDF 解析效果差时，先只承诺支持文本型 PDF。扫描版 OCR 放到后续优化，不要让它阻塞主线。
