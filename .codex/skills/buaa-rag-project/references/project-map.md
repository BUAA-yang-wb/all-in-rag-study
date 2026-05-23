# BUAA RAG Project Map

Use this map to load only task-relevant context. Do not read the whole repository unless the user explicitly asks for a full review.

## Core Paths

- Plan index: `my_docs/plan/00_RAG两周学习计划索引.md`
- Daily plans: `my_docs/plan/Day*.md`
- Tutorial docs: `docs/chapter1` through `docs/chapter9`
- Example code: `code/C1` through `code/C9`
- Final project target: `course_rag/`
- Background context: `my_docs/RAG项目学习背景说明.md`

## Daily Plan Files

| Day | Goal | Plan file |
| --- | --- | --- |
| 01 | Project overview and minimal RAG chain | `my_docs/plan/Day01_项目总览与最小链路.md` |
| 02 | Reproduce `code/C8` complete project | `my_docs/plan/Day02_复现C8完整项目.md` |
| 03 | Course-material scenario and data schema | `my_docs/plan/Day03_课程资料场景与数据规范.md` |
| 04 | Multi-format document loading | `my_docs/plan/Day04_多格式文档加载.md` |
| 05 | Chunking and parent-child documents | `my_docs/plan/Day05_Chunk切分与父子文档策略.md` |
| 06 | Embedding and vector index | `my_docs/plan/Day06_Embedding与向量索引.md` |
| 07 | First QA MVP | `my_docs/plan/Day07_第一版可问答MVP.md` |
| 08 | FastAPI packaging | `my_docs/plan/Day08_FastAPI封装.md` |
| 09 | Hybrid retrieval and RRF | `my_docs/plan/Day09_混合检索与RRF对比.md` |
| 10 | Rerank integration | `my_docs/plan/Day10_Rerank接入与配置化.md` |
| 11 | Evaluation dataset and metrics | `my_docs/plan/Day11_评测集与指标.md` |
| 12 | Docker and engineering cleanup | `my_docs/plan/Day12_Docker与工程化整理.md` |
| 13 | README, architecture, project packaging | `my_docs/plan/Day13_README与项目包装.md` |
| 14 | Resume wording and interview review | `my_docs/plan/Day14_简历表达与面试复盘.md` |

## Module-to-Source Map

| User task | Read first | Then read |
| --- | --- | --- |
| Minimal RAG chain | Day01 | `docs/chapter1/03_get_start_rag.md`, `code/C1/` |
| C8 reproduction or architecture | Day02 | `docs/chapter8/`, `code/C8/main.py`, `code/C8/rag_modules/` |
| Data scenario or metadata schema | Day03 | `code/C8/rag_modules/data_preparation.py`, `docs/chapter2/04_data_load.md` |
| Document loading | Day04 | `docs/chapter2/04_data_load.md`, `code/C2/`, `code/C8/rag_modules/data_preparation.py` |
| Chunking | Day05 | `docs/chapter2/05_text_chunking.md`, `code/C2/02_character_splitter.py`, `code/C2/03_recursive_character_splitter.py`, `code/C8/rag_modules/data_preparation.py` |
| Embedding or FAISS | Day06 | `docs/chapter3/06_vector_embedding.md`, `docs/chapter3/08_vector_db.md`, `code/C8/rag_modules/index_construction.py` |
| Generation or prompt | Day07 | `docs/chapter5/16_formatted_generation.md`, `code/C8/rag_modules/generation_integration.py` |
| FastAPI | Day08 | `code/C8/main.py`, existing `course_rag/app/` if present |
| BM25, hybrid retrieval, RRF | Day09 | `docs/chapter4/11_hybrid_search.md`, `code/C4/01_hybrid_search.py`, `code/C8/rag_modules/retrieval_optimization.py` |
| Rerank | Day10 | `code/C4/07_rerank_and_refine.py` |
| Evaluation | Day11 | `docs/chapter6/18_system_evaluation.md`, `docs/chapter6/19_common_tools.md`, `code/C6/01_llamaindex_evaluation_example.py` |
| Docker or dependencies | Day12 | `code/docker-compose.yml`, `code/C8/requirements.txt` |
| README and packaging | Day13 | Existing `course_rag/README.md`, evaluation outputs |
| Resume and interview prep | Day14 | `my_docs/RAG项目学习背景说明.md`, final README/eval results |

## Important C8 Files

- `code/C8/main.py`: End-to-end orchestration.
- `code/C8/config.py`: Paths, embedding model, LLM model, top_k, generation settings.
- `code/C8/rag_modules/data_preparation.py`: Markdown loading, metadata enhancement, parent-child chunking.
- `code/C8/rag_modules/index_construction.py`: HuggingFace embeddings, FAISS index, persistence.
- `code/C8/rag_modules/retrieval_optimization.py`: Dense retrieval, BM25, RRF fusion.
- `code/C8/rag_modules/generation_integration.py`: Query routing, rewrite, prompts, LLM generation.
