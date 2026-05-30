# Day 07：完成第一版可问答 MVP

## 今日目标

把加载、切分、索引、检索、生成串起来，形成自己的课程资料 RAG MVP。今天结束后，项目应该能对样例资料进行问答。

## 学习输入

- `code/C8/rag_modules/generation_integration.py`
- `docs/chapter5/16_formatted_generation.md`

## 预计完成工作

1. 实现文件：

```text
course_rag/app/rag/generation.py
course_rag/app/main_cli.py
```

2. 设计面向课程资料的 prompt，要求：
   - 优先基于检索内容回答。
   - 信息不足时明确说明。
   - 输出引用来源。
   - 不要编造课程资料中没有的内容。
3. 实现命令行问答，例如：

```bash
python -m app.main_cli "这门课的期末复习重点是什么？"
```

4. 回答中返回：
   - answer
   - citations
   - source
   - chunk text preview

## 验收标准

- 能对自己的样例资料进行问答。
- 回答中包含引用来源。
- 检索结果可以被单独打印，便于调试。
- 能说清楚一次问答请求经过了哪些模块。

## 当日输出

- `course_rag/app/rag/generation.py`
- `course_rag/app/main_cli.py`
- 5 个问答样例。
- `my_docs/Day07_RAG_MVP记录.md`

## 第 1 周里程碑

```text
已经有一个自己的课程资料 RAG MVP，而不是只运行 all-in-rag 原项目。
```

如果今天没有完成 LLM 生成，也要先完成“检索 + 引用片段返回”的 debug 模式。
