# Day 06：实现 embedding 与向量索引

## 今日目标

实现课程资料 chunk 的向量化和 FAISS 本地索引持久化，让系统具备基本语义检索能力。

## 学习输入

- `docs/chapter3/06_vector_embedding.md`
- `docs/chapter3/08_vector_db.md`
- `code/C8/rag_modules/index_construction.py`

## 预计完成工作

1. 实现文件：

```text
course_rag/app/rag/indexing.py
```

2. 使用中文 embedding 模型，优先：

```text
BAAI/bge-small-zh-v1.5
```

3. 使用 FAISS 做本地向量索引。
4. 支持索引保存和加载：

```text
course_rag/vector_index/
```

5. 实现索引构建命令，例如：

```bash
python -m app.rag.indexing --data data/samples --rebuild
```

6. 实现一个简单搜索入口，输入问题后返回 Top-K chunk 和来源。

## 验收标准

- 首次运行能构建索引。
- 第二次运行能加载本地索引。
- 输入一个问题能返回 Top-K chunk 及来源。
- 能解释 embedding 模型、向量维度、相似度检索、索引持久化分别解决什么问题。

## 当日输出

- `course_rag/app/rag/indexing.py`
- `course_rag/vector_index/` 本地索引缓存。
- 一个 Top-K 检索输出样例。
- `my_docs/Day06_Embedding与索引记录.md`

## 风险处理

如果模型下载慢，先记录环境问题，并保留模型名配置项。主线目标是把索引构建流程写清楚，不要为了换复杂模型消耗太多时间。
