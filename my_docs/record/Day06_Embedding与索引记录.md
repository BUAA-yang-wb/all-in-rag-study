# Day06 Embedding 与向量索引记录

## 本次实现

- 新增 `course_rag/app/rag/indexing.py`，接入现有 `loaders.py` 和 `chunking.py`，完成 chunk embedding、FAISS 索引构建、保存、加载和 Top-K 检索。
- 新增 `course_rag/main.py`，作为当前阶段的简单检索入口。
- 使用 `BAAI/bge-small-zh-v1.5`，输出向量维度为 512。
- 使用 FAISS `IndexFlatIP`，并在编码时归一化向量，因此分数可按余弦相似度理解。
- 索引缓存目录为 `course_rag/vector_index/`，已加入 `.gitignore`。

## 选型说明

- 当前课程资料以中文为主，`BAAI/bge-small-zh-v1.5` 体积较小、CPU 可运行，适合作为 Day06 基线。
- `bge-m3` 和 `Qwen3-Embedding-0.6B` 更强，但模型更大、索引维度更高，适合后续做检索效果对比。
- 当前项目是本地学习型 RAG，FAISS 足够完成语义检索和持久化；暂时不需要 Milvus、Qdrant 这类服务化向量数据库。

## 构建命令

```powershell
.\rag\Scripts\python.exe -m course_rag.app.rag.indexing --rebuild --query "编译过程有哪些阶段？" --top-k 3 --no-progress
```

第二次加载本地索引：

```powershell
.\rag\Scripts\python.exe -m course_rag.app.rag.indexing --query "LR0分析是什么？" --top-k 2 --no-progress
```

也可以通过主入口：

```powershell
.\rag\Scripts\python.exe course_rag\main.py --query "什么是源程序？" --top-k 3 --no-progress
```

## 索引统计

- 源文件数：71
- chunks：7350
- parents：4197
- 向量维度：512
- 文件类型分布：
  - PDF chunks：7202
  - Markdown chunks：134
  - DOCX chunks：14

## Top-K 检索样例

问题：`编译过程有哪些阶段？`

```text
[1] score=0.7849 course_rag/data/编译原理/课件/hcm-编译原理-第01讲-概论-20250909.pdf | 35 / Page 35
    编译过程是指将高级语言程序翻译为等价的目标程序的过程。编译过程词法分析语法分析语义分析、生成中间代码代码优化生成目标程序习惯上是将编译过程划分为5个基本阶段：

[2] score=0.7813 course_rag/data/编译原理/课件/hcm-编译原理-第05讲-词法分析-自动机-20240923.pdf | 2 / Page 2
    编译过程是指将高级语言程序翻译为等价的目标程序的过程。 词法分析语法分析语义分析、生成中间代码代码优化生成目标程序习惯上是将编译过程划分为5个基本阶段：

[3] score=0.7813 course_rag/data/编译原理/课件/hcm-编译原理-第04讲-词法分析-20250918.pdf | 2 / Page 2
    编译过程是指将高级语言程序翻译为等价的目标程序的过程。 词法分析语法分析语义分析、生成中间代码代码优化生成目标程序习惯上是将编译过程划分为5个基本阶段：
```

## 概念记录

- embedding 模型：把文本映射成固定维度的语义向量。
- 向量维度：每个 chunk 的语义坐标长度，本次为 512。
- 相似度检索：把用户问题也转为向量，在索引中找语义最接近的 chunk。
- 索引持久化：把 FAISS 向量索引和 chunk 元数据保存到本地，后续查询无需重新构建。
