# Day 03：确定课程资料场景与数据规范

## 今日目标

把项目从“菜谱 RAG”切换到“课程资料 RAG”的真实场景，明确数据来源、隐私边界、文件格式和元数据规范。

## 学习输入

- `code/C8/rag_modules/data_preparation.py`
- `docs/chapter2/04_data_load.md`
- `docs/chapter2/05_text_chunking.md`

## 预计完成工作

1. 新增最终项目目录：

```text
course_rag/
```

2. 收集 10 到 30 份可用于本地测试的资料，优先级：
   - Markdown 学习笔记
   - TXT 文档
   - 文本型 PDF
   - 课程 PPT 转出的文本或 PDF
3. 整理公开样例数据，放到：

```text
course_rag/data/samples/
```

4. 私有课程资料只放本地，不上传公开 GitHub。避免提交课程内部资料、作业答案、未授权课件。
5. 设计元数据 schema：

```json
{
  "source": "文件路径",
  "doc_id": "稳定文档 ID",
  "course": "课程名",
  "file_type": "pdf/md/txt",
  "page": 1,
  "section": "章节标题",
  "chunk_id": "稳定 chunk ID"
}
```

6. 明确项目支持的问题类型：
   - 课程概念解释
   - 实验步骤查询
   - 资料定位
   - 复习重点归纳
   - 易混淆概念对比

## 验收标准

- `course_rag/data/samples/` 至少有 5 份可公开样例资料。
- 明确哪些资料只在本地使用，哪些可以放 GitHub。
- 写清楚元数据字段及其作用。
- 能解释为什么课程资料比普通 PDF QA demo 更适合写进简历。

## 当日输出

- `course_rag/` 初始目录。
- `course_rag/data/samples/` 样例数据。
- `my_docs/Day03_课程资料数据设计.md`
- 一份元数据 schema 说明。
