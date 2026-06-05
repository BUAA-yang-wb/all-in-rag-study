# Day14 简历表达与面试复盘记录

## 本阶段目标

本阶段按照 `my_docs/plan/Day14_简历表达与面试复盘.md` 的方向，把已经完成的 `course_rag` 项目转化为可投递简历和面试讲述材料。重点是基于项目真实能力表达，而不是照搬教程式 RAG 描述。

## 输出文件

- `my_docs/RAG项目面试复盘.md`
- `my_docs/record/Day14_简历表达与面试复盘记录.md`

本阶段不修改代码、不修改 API、不更新 `course_rag/docs/RAG_WORKFLOW.md`，因为没有改变 RAG 主流程、索引、检索、rerank、生成、API 参数或返回结构。

## 采用的表达策略

投递方向定位为 AI 应用 / RAG 实习，简历 bullet 采用可直接粘贴的一页简历风格，不写过长 STAR 段落。

表达重点放在：

- Evidence-first 数据建模。
- Milvus 在线检索后端与 FAISS baseline/fallback。
- BM25 + Dense Vector 混合检索。
- RRF 融合、metadata routing、rerank、parent context 和 citation。
- 端到端评测和 Milvus/FAISS 对比结果。

避免使用无法证明的表述，例如“生产级”“高并发”“大规模知识库”“完整多模态 RAG”。

## 使用的真实项目事实

当前项目能力：

- FastAPI 提供 `/health`、`/ingest`、`/search`、`/ask`。
- 默认在线向量后端为 Milvus standalone，collection 为 `course_rag_v2_text`。
- FAISS baseline 保留为 Milvus 导入源和显式 fallback。
- 当前索引包含 9138 个 chunk、5840 个 parent、5724 条 evidence。
- evidence 类型包括 `native_text`、`ocr_text`、`table_markdown`、`image_metadata`、`image_ref`。
- VLM caption provider 已接入但默认关闭，当前索引中 `caption=0`。

端到端评测结果来自：

```text
course_rag/eval/results/eval_v2_20260604T152114.md
```

关键指标：

- 样本数：21
- `evidence_hit@k`：1.0
- `evidence_recall@k`：0.9211
- `citation_coverage`：1.0
- `answer_fact_coverage`：0.9868
- `llm_error_rate`：0

Milvus 与 FAISS 对比结果来自：

```text
course_rag/eval/results/eval_v2_20260605T114759.md
```

关键指标：

- Top-K overlap 平均值：0.9895
- Top-1 变化率：0
- 对比错误率：0

## 面试准备内容

`my_docs/RAG项目面试复盘.md` 中整理了：

- 项目定位和一句话介绍。
- 5 条简历 bullet 最终版。
- 3 分钟项目讲述稿。
- 10 个高频 RAG 面试问题回答提纲。
- 面试中可以主动强调的点。
- 不建议在简历中使用的夸大表述。
- 可追问细节准备表。

## 后续建议

- 根据具体岗位 JD，把简历 bullet 的侧重点微调为 AI 应用、后端工程或算法检索。
- 面试前用 README 和复盘文档各讲一遍，确保 3 分钟版本能自然讲完。
- 如果后续补充前端截图或新评测结果，再同步更新 README 和本复盘文档。
