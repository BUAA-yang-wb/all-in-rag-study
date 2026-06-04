# Course RAG Evaluation

本目录是 `course_rag` 当前系统的新评测体系。旧评测入口和旧数据集已替换，`results/` 中的历史报告只保留作记录，新脚本不会读取它们。

## 默认策略

默认评测完整问答链路：

- hybrid 检索
- metadata routing
- rerank
- parent context
- DeepSeek-compatible 外部 LLM 生成答案
- DeepSeek-compatible LLM-as-judge

默认外部配置沿用主系统：

| 项 | 默认值 |
| --- | --- |
| base URL | `https://api.deepseek.com` |
| model | `deepseek-v4-pro` |
| API key env | `DEEPSEEK_API_KEY_RAGLEARN` |

如果没有 `DEEPSEEK_API_KEY_RAGLEARN`，脚本会自动降级为不调用外部 LLM 的检索、路由、引用诊断，并在报告中记录原因。

## 数据集

金标文件：

```text
course_rag/eval/golden_set.jsonl
```

每行一个 JSON 样本，主要字段：

- `id`：稳定样本 ID。
- `task_type`：样本类型，如 `text_retrieval`、`table_evidence`、`ocr_evidence`、`image_locator`、`routing`、`negative`。
- `question`：用户问题。
- `request`：覆盖本次请求的 RAG 参数，字段对齐 `GenerationConfig`，也可使用 API 风格的 `strategy`。
- `expected_evidence`：期望证据，优先用 `evidence_id`，也可用 `source_name/page/evidence_kind/modality/asset_path` 组合匹配。
- `expected_facts`：答案中应覆盖的关键词或短语。
- `expected_routing`：期望 routing 应用的过滤条件。
- `negative`：资料不足或错误定位问题。

## 运行

编译检查：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app course_rag\eval
```

默认外部 LLM 评测：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile default
```

快速离线诊断：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast
```

输出：

```text
course_rag/eval/results/eval_v2_*.json
course_rag/eval/results/eval_v2_*.md
course_rag/docs/RAG_EVALUATION.md
```

## 指标

- 检索：`evidence_hit_at_k`、`evidence_recall_at_k`、`mrr`、`context_precision_at_k`
- 路由：`routing_filter_success`、`routing_fallback_rate`、`expected_modality_hit`
- 引用：`citation_validity`、`citation_coverage`
- 生成：`answer_fact_coverage`、`abstention_success`
- LLM 裁判：`judge_groundedness`、`judge_relevance`、`judge_completeness`
- 稳定性：`error_rate`、`llm_error_rate`、`latency_ms_avg`

