# Day 05：实现 chunk 切分与父子文档策略

## 今日目标

实现课程资料的 chunk 切分，并保留父子文档映射。核心目标是做到“检索时粒度足够细，生成时上下文足够完整”。

## 学习输入

- `docs/chapter2/05_text_chunking.md`
- `code/C2/02_character_splitter.py`
- `code/C2/03_recursive_character_splitter.py`
- `code/C8/rag_modules/data_preparation.py`

## 预计完成工作

1. 实现文件：

```text
course_rag/app/rag/chunking.py
```

2. Markdown 优先按标题切分。
3. PDF/TXT 使用 `RecursiveCharacterTextSplitter`。
4. 保留父子文档映射：

```text
child_chunk_id -> parent_doc_id
```

5. 小 chunk 用于检索，父文档或相邻上下文用于生成。
6. 支持配置项：
   - `chunk_size`
   - `chunk_overlap`
   - `use_parent_context`
7. 输出 chunk 统计：
   - chunk 总数
   - 平均长度
   - 最长 chunk
   - 最短 chunk
   - 每个文件产生的 chunk 数量

## 验收标准

- 每个 chunk 都能追溯到原文件和章节。
- 手动检查 5 个 chunk，确认没有明显乱码或无意义碎片。
- 能解释 chunk size 和 chunk overlap 对召回效果、上下文完整性、成本的影响。
- 能说明为什么课程资料场景适合保留章节标题和 source metadata。

## 当日输出

- `course_rag/app/rag/chunking.py`
- chunk 统计输出样例。
- `my_docs/Day05_Chunk策略记录.md`

## 关键理解

不要只追求 chunk 越细越好。chunk 太细可能丢上下文，chunk 太粗可能影响检索精度。父子文档策略是两者之间的折中。
