# Day07 RAG MVP 记录

## 本次实现

- 新增 `course_rag/app/rag/generation.py`，在现有 FAISS 检索基础上完成候选扩展、短 chunk 过滤、按 `parent_doc_id` 去重、父文档上下文组装、LLM 生成和检索 fallback。
- 新增 `course_rag/app/main_cli.py`，提供命令行问答入口。
- 生成结果统一返回 `answer`、`citations`、`retrieval`、`source`/`page`/`chunk_preview` 等调试信息。
- 默认使用 `course_rag/vector_index/` 中 Day06 已构建的索引，不重复执行加载、切分和索引构建。

## 当前链路

```text
CLI question
-> load_vector_index
-> encode_query
-> faiss_top_k_search
-> filter_short_chunks
-> deduplicate_by_parent
-> assemble_context
-> llm_generation / retrieval_only_fallback
-> answer + citations
```

## 运行命令

真实 LLM 问答：

```powershell
.\rag\Scripts\python.exe -m course_rag.app.main_cli "编译过程有哪些阶段？" --top-k 3
```

只看检索与引用片段：

```powershell
.\rag\Scripts\python.exe -m course_rag.app.main_cli "编译过程有哪些阶段？" --no-llm --debug-retrieval --top-k 3
```

JSON 输出：

```powershell
.\rag\Scripts\python.exe -m course_rag.app.main_cli "运输层的主要功能是什么？" --top-k 5 --json
```

## 问答样例

### 1. 编译过程有哪些阶段？

回答要点：编译过程是把高级语言程序翻译为等价目标程序的过程，资料中指出习惯上按 5 个基本阶段理解：词法分析、语法分析、语义分析/中间代码生成、代码优化、目标程序生成。

引用来源：

- `hcm-编译原理-第01讲-概论-20250909.pdf`，Page 35
- `hcm-编译原理-第06讲-语法分析-20250925.pdf`，Page 2
- `hcm-编译原理-第05讲-词法分析-自动机-20240923.pdf`，Page 2

### 2. LR0 分析是什么？

回答要点：LR0 分析是 LR 分析法的一种基础形式。资料中把 LR 分析描述为从左到右扫描、自底向上归约的规范归约方法，LR0 分析表构造需要先构造识别活前缀的 DFA，再由 DFA 构造分析表。

引用来源：

- `hcm-编译原理-第22讲-LR1和SLR分析-20251202.pdf`，Page 30 / 61 / 91
- `hcm-编译原理-第21讲-LR0分析-20251127.pdf`，Page 150 / 176

### 3. FIRST 集是什么？

回答要点：FIRST(α) 是 α 可能推导出的头符号集合，包含可作为开头的终结符；如果 α 可以推出空串，则 ε 也属于 FIRST(α)。它用于 LL 分析中根据当前输入符号选择产生式，避免回溯。

引用来源：

- `hcm-编译原理-第08讲-语法分析-LL分析法-20251009.pdf`，Page 12 / 13 / 16 / 20
- `hcm-编译原理-第06讲-语法分析-20250925.pdf`，Page 59

### 4. 运输层的主要功能是什么？

回答要点：运输层提供应用进程之间的逻辑通信，支持复用和分用、差错检测，并主要使用 TCP 和 UDP；资料还提到连接建立、丢包重传和流量控制等相关功能。

引用来源：

- `串讲+习题课 25.pdf`，Page 73
- `邓攀：2.计算机网络-体系结构.pdf`，Page 57 / 60
- `计算机网络-运输层.pdf`，Page 6

JSON 输出已验证，返回字段包括 `answer`、`citations`、`retrieval`、`used_llm`、`pipeline` 和 `index`。

### 5. 这门课的期末复习重点是什么？

回答要点：现有资料只检索到考试分值、课程要求和少量习题线索，无法给出完整复习大纲。生成结果能说明资料不足。

引用来源：

- `hcm-编译原理-第01讲-概论-20250909.pdf`，Page 82 / 83 / 84
- `hcm-编译原理-第21讲-LR0分析-20251127.pdf`，Page 177
- `邓攀：0.课程概述.pdf`，Page 3

质量观察：这个问题没有明确课程名，纯向量检索召回了编译原理和计网两门课的考试信息。后续需要课程过滤或查询改写来处理这类宽泛问题。

## 当前判断

- Day07 MVP 已能完成“检索 + 生成 + 引用返回”。
- 对明确知识点问题效果较好。
- 对“期末复习重点”这类宽泛问题，当前纯向量检索可能召回分散，需要后续补充课程过滤、BM25 或 rerank。
- 生成层已经保留 `--no-llm` 和 `--debug-retrieval`，便于判断问题出在检索还是生成。
