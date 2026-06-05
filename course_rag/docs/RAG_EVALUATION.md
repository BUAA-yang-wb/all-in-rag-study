# Course RAG 评测体系

最后更新：2026-06-05T11:47:59

本文档记录当前 `course_rag` 新评测体系的设计、运行方式、Milvus 主线验证结果和最近一次端到端 LLM 评测结果。当前评测不再复用旧评测集，而是围绕现有系统的 evidence-first RAG 流程重新设计。

## 1. 评测目标

当前系统会把文本、表格、OCR、图片说明、Markdown 图片引用等内容统一组织成 evidence 后进入索引。因此评测不只判断“答案像不像”，而是分层检查 RAG 链路：

- 检索是否找到期望 evidence。
- metadata routing 是否正确使用课程、文件、页码、模态、evidence 类型等过滤条件。
- rerank、父子上下文和 citation 是否保留可追溯来源。
- 外部 LLM 生成的回答是否基于召回上下文，并覆盖关键事实。
- 当资料不足时，系统是否能拒答或明确说明资料不足。

## 2. 数据与运行方式

金标数据位于：

```text
course_rag/eval/golden_set.jsonl
```

默认评测命令：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile default
```

快速离线诊断命令：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast
```

默认 profile 会启用外部 LLM，沿用主系统 DeepSeek-compatible 配置：`deepseek-v4-pro`、`https://api.deepseek.com`、`DEEPSEEK_API_KEY_RAGLEARN`。如果环境变量缺失，脚本会自动降级为离线检索和引用诊断。

默认评测使用 Milvus 后端。需要先启动 Docker Desktop、运行
`course_rag\scripts\milvus_up.ps1`，并用 `course_rag\scripts\milvus_rebuild_index.ps1`
构建 collection。需要低资源或离线 fallback 时，可显式选择 FAISS：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast --index-backend faiss --no-write-doc
```

如果需要在同一份报告中比较 FAISS 与 Milvus 的 Top-K 差异，可使用：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast --index-backend milvus --compare-index-backend faiss --no-write-doc
```

## 3. 当前 Milvus 主线验证

本轮验证时间：`2026-06-05T11:47:59`。

运行命令：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast --index-backend milvus --compare-index-backend faiss --no-write-doc
```

运行配置：

| 项 | 值 |
| --- | --- |
| profile | `fast` |
| 主后端 | `milvus` |
| 对比后端 | `faiss` |
| 样本数 | 21 |
| 向量数 | 9138 |
| 是否调用 LLM | false |
| 是否使用 rerank | false |
| collection | `course_rag_v2_text` |

Milvus fast 指标：

| 指标 | 值 |
| --- | ---: |
| `evidence_hit@k` | 0.7895 |
| `evidence_recall@k` | 0.7632 |
| `mrr` | 0.6816 |
| `context_precision@k` | 0.463 |
| `routing_filter_success` | 1 |
| `routing_fallback_rate` | 0.1429 |
| `expected_modality_hit` | 0.9474 |
| `citation_validity` | 0.9048 |
| `citation_coverage` | 0.7895 |
| `error_rate` | 0 |
| `latency_ms_avg` | 1247.6 |

Milvus 与 FAISS 对比：

| 指标 | 值 |
| --- | ---: |
| Top-K overlap 平均值 | 0.9895 |
| Top-1 变化率 | 0 |
| 对比错误率 | 0 |

结论：Milvus 已经能作为当前默认在线检索后端运行。collection entity 数与当前 chunk 数一致，默认 `/search` 和 `/ask(use_llm=false)` 返回 `index.backend="milvus"`；FAISS 显式 fallback 仍可用。Top-K overlap 接近 1，说明 Milvus 后端没有破坏当前 FAISS baseline 的主要召回行为。

注意：`profile=fast` 关闭 LLM 和 rerank，主要用于检索链路、后端迁移和稳定性诊断；它的生成相关指标不能直接和下面的默认端到端 LLM 评测等价比较。

## 4. 指标说明

### 4.1 检索指标

- `evidence_hit@k`：Top-K 检索结果里是否至少命中一个期望 evidence。越接近 1，说明“有没有找对资料”的能力越稳定。
- `evidence_recall@k`：期望 evidence 被 Top-K 结果覆盖的比例。适合观察多证据问题是否召回完整。
- `mrr`：第一个正确 evidence 的排名质量。正确证据越靠前，分数越高。
- `context_precision@k`：Top-K 上下文中有效 evidence 的占比。该值低说明虽然能召回正确资料，但上下文里仍混入较多无关片段。

### 4.2 路由指标

- `routing_filter_success`：带 metadata 约束的问题是否正确应用过滤条件，例如指定课程、文件、页码或 evidence 类型。
- `routing_fallback_rate`：严格过滤没有结果后触发回退检索的比例。少量回退是正常的，过高则说明 metadata 或索引粒度需要优化。
- `expected_modality_hit`：是否命中预期模态，例如文本、表格、OCR、图片引用等。

### 4.3 引用指标

- `citation_validity`：回答中返回的 citation 是否能对应到真实检索结果或 evidence。
- `citation_coverage`：需要引用支撑的问题是否返回了 citation。越高说明答案更容易追溯来源。

### 4.4 生成指标

- `answer_fact_coverage`：回答是否覆盖金标中要求的关键事实。
- `abstention_success`：资料不足样本是否拒答，或明确说明当前资料无法支持答案。
- `judge_groundedness`：LLM 裁判判断答案是否基于检索上下文。
- `judge_relevance`：LLM 裁判判断答案是否切题。
- `judge_completeness`：LLM 裁判判断答案是否完整覆盖问题。

### 4.5 稳定性指标

- `error_rate`：评测过程中发生运行错误的样本比例。
- `llm_error_rate`：外部 LLM 生成阶段发生错误或降级的样本比例。
- `latency_ms_avg`：平均响应耗时，单位毫秒。
- `latency_ms_p95`：95 分位响应耗时，用于观察慢请求。

## 5. 最近一次端到端 LLM 评测配置

- 评测时间：`2026-06-04T15:21:14`
- 评测 profile：`default`
- 样本数量：`21`
- 是否启用外部 LLM：`True`
- 是否启用 LLM 裁判：`True`
- API key 是否可用：`True`

## 6. 端到端 LLM 总体结果

| 指标 | 分数 | 简要解读 |
| --- | ---: | --- |
| `case_count` | 21 | 本次共评测 21 条人工金标样本。 |
| `evidence_hit@k` | 1 | 每条需要检索的问题都至少命中了一个期望 evidence。 |
| `evidence_recall@k` | 0.9211 | 多证据覆盖率较高，但 OCR 类样本仍有漏召回。 |
| `mrr` | 0.7939 | 正确 evidence 大多排在较前位置，整体排序可用。 |
| `context_precision@k` | 0.4868 | 上下文里仍有不少非目标片段，检索精度还有优化空间。 |
| `routing_filter_success` | 1 | metadata routing 在本次样本中全部按预期生效。 |
| `routing_fallback_rate` | 0.1429 | 少量样本触发回退检索，比例可接受。 |
| `expected_modality_hit` | 1 | 文本、表格、OCR、图片等预期模态均能命中。 |
| `citation_validity` | 0.9524 | citation 基本有效，仍存在少量引用有效性不足。 |
| `citation_coverage` | 1 | 需要引用的问题均返回了来源。 |
| `answer_fact_coverage` | 0.9868 | 生成答案基本覆盖关键事实，仅少量样本遗漏细节。 |
| `abstention_success` | 1 | 资料不足问题可以正确拒答或说明无法回答。 |
| `judge_groundedness` | 0.9048 | LLM 裁判认为答案整体有较好上下文依据。 |
| `judge_relevance` | 0.9048 | 答案整体切题。 |
| `judge_completeness` | 0.9286 | 答案完整性较好，但仍有个别概念题不够完整。 |
| `error_rate` | 0 | 评测过程无运行错误。 |
| `llm_error_rate` | 0 | 外部 LLM 调用无失败或降级。 |
| `latency_ms_avg` | 8140.5 | 平均耗时约 8.1 秒。 |
| `latency_ms_p95` | 15567.5 | 慢请求约 15.6 秒，主要受外部 LLM 和 rerank 影响。 |

## 7. 端到端 LLM 分类型结果

| 类型 | 样本数 | 检索命中 | 检索覆盖 | 首个正确证据排名 | 答案事实覆盖 | 引用覆盖 | LLM 错误率 | 平均耗时 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 图片定位 | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 4379.3ms |
| 资料不足 | 2 | - | - | - | - | - | 0 | 1914.9ms |
| OCR 证据 | 3 | 1 | 0.5 | 0.3056 | 1 | 1 | 0 | 10561.7ms |
| metadata routing | 2 | 1 | 1 | 1 | 1 | 1 | 0 | 5139ms |
| 表格证据 | 3 | 1 | 1 | 0.7778 | 1 | 1 | 0 | 6940.4ms |
| 文本检索 | 9 | 1 | 1 | 0.8704 | 0.9722 | 1 | 0 | 10619.7ms |

## 8. 当前结果总结

整体看，当前系统已经具备较稳定的端到端 RAG 能力。文本、表格、图片引用、metadata routing 的命中表现较好；引用覆盖率为 1，说明回答基本都能给出可追溯来源；资料不足样本也能正确拒答，没有出现明显幻觉式回答。

主要短板集中在两点。第一，OCR 类样本虽然都能命中至少一个相关 evidence，但 `evidence_recall@k` 只有 0.5，`mrr` 也偏低，说明 OCR 内容可以被找出来，但排序和多证据覆盖还不够稳定。第二，`context_precision@k` 为 0.4868，说明检索上下文中仍混入较多非目标片段；这会增加外部 LLM 的阅读负担，也可能导致回答遗漏重点。

本次唯一明确失败样本是 `network_sliding_window_summary`。该样本属于文本概念问答，系统命中了相关资料，但最终答案遗漏了“确认帧/窗口滑动机制”等关键事实，因此被判定为答案事实覆盖不足。这说明当前检索链路已经能找到资料，但生成阶段对复杂概念的归纳完整性还需要继续优化。

下一步优先优化 OCR evidence 的排序和召回覆盖，其次优化 Top-K 上下文精度。可考虑对 OCR/table evidence 调整 chunk 表达、增加 evidence 类型权重，或在 rerank 阶段强化问题类型与 evidence_kind 的匹配。
