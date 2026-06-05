# Course RAG 评测体系

最后更新：2026-06-05

本文档记录当前 `course_rag` 评测体系的目标、运行方式和指标。当前评测固定使用 SQLite docstore + Milvus 检索链路。

## 1. 评测目标

当前系统是 evidence-first RAG：文本、表格、OCR、图片元数据、Markdown 图片引用会统一进入 SQLite docstore，并同步到 Milvus 检索索引。评测按层诊断，而不是只看最终答案：

- 检索是否找到期望 evidence。
- metadata routing 是否正确使用课程、文件、页码、模态和 evidence 类型过滤。
- Milvus dense、BM25 和 hybrid 召回是否返回可追溯 chunk。
- rerank、父子上下文和 citation 是否保留来源。
- 外部 LLM 生成是否基于召回上下文，并覆盖关键事实。
- 资料不足时是否明确拒答。

## 2. 数据与运行方式

金标数据：

```text
course_rag/eval/golden_set.jsonl
```

默认评测：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile default
```

快速离线诊断：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast --no-write-doc
```

指定 docstore：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast --docstore-path course_rag\data\rag_store.sqlite --no-write-doc
```

评测前需要：

```powershell
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_up.ps1
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_rebuild_index.ps1
```

`profile=fast` 不调用 LLM、不启用 rerank，适合检查 Milvus 检索、routing、citation 和延迟。`profile=default` 会启用 rerank 和外部 LLM；如果缺少 `DEEPSEEK_API_KEY_RAGLEARN`，脚本会自动降级为离线检索和引用诊断。

## 3. 指标

检索：

- `evidence_hit@k`：Top-K 是否至少命中一个期望 evidence。
- `evidence_recall@k`：期望 evidence 被 Top-K 覆盖的比例。
- `mrr`：第一个正确 evidence 的排名质量。
- `context_precision@k`：Top-K 上下文中有效 evidence 的占比。

路由：

- `routing_filter_success`：指定 metadata 约束时是否正确应用过滤。
- `routing_fallback_rate`：过滤无候选后触发回退的比例。
- `expected_modality_hit`：是否命中预期模态，例如文本、表格、OCR、图片引用。

引用与生成：

- `citation_validity`：citation 是否对应真实检索结果或 evidence。
- `citation_coverage`：需要引用支撑的问题是否返回 citation。
- `answer_fact_coverage`：回答是否覆盖金标关键事实。
- `abstention_success`：资料不足样本是否拒答。
- `judge_groundedness`、`judge_relevance`、`judge_completeness`：可选 LLM-as-judge 指标。

稳定性：

- `error_rate`
- `llm_error_rate`
- `latency_ms_avg`
- `latency_ms_p95`

## 4. 输出

每次运行会写入：

```text
course_rag/eval/results/eval_v2_<timestamp>.json
course_rag/eval/results/eval_v2_<timestamp>.md
```

不加 `--no-write-doc` 时，会同步刷新本文档为最近一次评测结果。

报告中的 `run.index.metadata` 会包含当前 Milvus collection、docstore path、schema version、embedding model 和 chunk/entity 统计，便于排查 SQLite 与 Milvus 是否使用同一批数据。
