# Day13 README 与项目包装记录

## 本阶段目标

本阶段按照 `my_docs/plan/Day13_README与项目包装.md` 的方向，对 `course_rag` 做面向实习面试的项目包装。重点不是继续改 RAG 主流程，而是让陌生面试官能快速理解项目解决什么问题、采用什么架构、如何运行、如何验证，以及当前效果如何。

## 采用策略

原有 `course_rag/README.md` 更偏运行手册，能说明 Milvus、FastAPI 和评测命令，但对面试展示不够友好。本阶段将 README 改为“中文面试版”：

- 前半部分突出项目背景、技术亮点、系统架构和当前索引状态。
- 中段保留快速开始、API 调用、检索策略和可复现验证命令。
- 后半部分整理真实评测指标、示例问答、数据隐私和后续优化。

截图部分先只预留 `course_rag/docs/assets/` 目录说明，不插入不存在的图片链接，避免公开展示时出现破图。

## 输出文件

- `course_rag/README.md`
- `course_rag/docs/assets/README.md`
- `my_docs/record/Day13_项目包装记录.md`

本阶段不修改 `my_docs/plan/`，也不修改 `course_rag/docs/RAG_WORKFLOW.md`。原因是本次只做文档包装，不改变索引、检索、rerank、生成、API 参数或返回结构。

## README 中呈现的真实结果

端到端 LLM 评测采用已有结果：

```text
course_rag/eval/results/eval_v2_20260604T152114.md
```

关键指标：

- 样本数：21
- `evidence_hit@k`：1.0000
- `evidence_recall@k`：0.9211
- `mrr`：0.7939
- `citation_coverage`：1.0000
- `answer_fact_coverage`：0.9868
- `abstention_success`：1.0000
- `error_rate`：0
- `llm_error_rate`：0

Milvus 与 FAISS 对比采用已有结果：

```text
course_rag/eval/results/eval_v2_20260605T114759.md
```

关键指标：

- 主后端：Milvus
- 对比后端：FAISS
- Top-K overlap 平均值：0.9895
- Top-1 变化率：0
- 对比错误率：0

## 示例问答来源

README 中的 6 条样例来自：

```text
course_rag/eval/results/eval_v2_20260604T152114.json
```

覆盖类型：

- 文本检索
- 表格 evidence
- OCR evidence
- 图片定位
- metadata routing
- 资料不足拒答

这些样例只做摘要展示，不编造答案，也不展开大段原始课程资料。

## 后续建议

- 补充一张 Swagger 或前端截图到 `course_rag/docs/assets/`。
- 继续优化 OCR evidence 排序和多证据召回。
- 优化 `context_precision@k`，减少无关上下文进入 LLM。
- 针对复杂概念问答优化 prompt 和 parent context 组织。
