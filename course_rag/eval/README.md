# Day11 文本 RAG 评测

本目录用于对当前 `course_rag` 文本 RAG 主流程做离线评测。默认评测当前 V2 text evidence 文本索引，并启用 metadata routing；不评价图片、扫描 PDF、表格、VLM caption 或 Milvus 等后续 V2 能力。

## 运行

默认运行三组实验：

```powershell
.\rag\Scripts\python.exe course_rag\eval\run_eval.py
```

默认索引目录：

```text
course_rag/vector_index_v2_text/
```

快速验证：

```powershell
.\rag\Scripts\python.exe course_rag\eval\run_eval.py --limit 3
```

只运行某一组实验：

```powershell
.\rag\Scripts\python.exe course_rag\eval\run_eval.py --experiment hybrid
```

## 数据集

评测集位于：

```text
course_rag/eval/eval_dataset.jsonl
```

当前包含 30 条人工问题，其中编译原理 18 条、计网 12 条。每条数据包含：

- `id`
- `question`
- `type`
- `course`
- `gold_sources`
- `gold_answer_keywords`

`gold_sources` 默认按 `source_name` 或 `source` 文件名匹配；如果写成 `文件名#page=页码`，脚本会额外校验页码。本阶段的 `gold_answer_keywords` 只作为人工分析字段保留，不做 LLM 答案语义评分。

## 指标

| 指标 | 含义 | 主要衡量 |
| --- | --- | --- |
| `Recall@5` | Top 5 citation 中是否命中任一 gold source | 检索召回能力 |
| `MRR` | 第一个命中 gold source 的倒数排名 | 排序质量 |
| `Citation Hit Rate` | 最终返回的 citation 是否命中 gold source | 最终可引用证据命中率 |

## 默认实验

| 实验 | top_k | candidate_k | strategy | rerank |
| --- | ---: | ---: | --- | --- |
| `dense` | 5 | 30 | `dense` | no |
| `hybrid` | 5 | 30 | `hybrid` | no |
| `hybrid-rerank` | 5 | 30 | `hybrid` | yes, `rerank_top_n=20` |

默认 `GenerationConfig` 会启用 `use_metadata_routing=true`。如果问题文本中能高置信识别课程、文件或页码，评测结果 JSON 中会保留 `routing` 相关调试信息。

## 最新结果

本次 routing 评测使用 30 条问题，结果如下：

| 实验 | Questions | Recall@5 | MRR | Citation Hit Rate | Rerank Used | Rerank Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `dense` | 30 | 0.8667 | 0.7389 | 0.8667 | 0 | 0 |
| `hybrid` | 30 | 0.9667 | 0.8583 | 0.9667 | 0 | 0 |
| `hybrid-rerank` | 30 | 1.0000 | 0.8478 | 1.0000 | 30 | 0 |

完整结果写入：

- `course_rag/eval/results/day14_routing_eval.json`
- `course_rag/eval/results/day14_routing_eval.md`
