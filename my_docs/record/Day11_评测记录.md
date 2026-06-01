# Day11 评测集与指标记录

## 本阶段目标

Day11 的目标是先为当前文本 RAG 建立一个可重复运行的小型离线评测基线，而不是马上推进 V2 多模态增强。

当前项目已经具备：

- dense 检索：`BAAI/bge-small-zh-v1.5` + FAISS
- hybrid 检索：dense + BM25 + RRF
- 可选 rerank：`BAAI/bge-reranker-base`
- FastAPI `/ask` 和 `/search` 的统一检索入口

因此本阶段用评测集对比 `dense`、`hybrid`、`hybrid + rerank`，为后续是否继续优化检索、是否推进 EvidenceDocument / OCR / VLM 提供依据。

## 实现内容

新增评测目录：

```text
course_rag/eval/
```

主要文件：

- `eval_dataset.jsonl`：30 条人工评测问题，覆盖编译原理和计网。
- `run_eval.py`：离线评测脚本，直接复用当前 RAG 主流程。
- `README.md`：运行命令、指标含义和默认实验配置。

评测脚本默认不调用外部 LLM：

```text
use_llm=false
```

rerank 实验默认只读本地模型缓存：

```text
rerank_local_files_only=true
```

如果本地没有 reranker，脚本会记录 `rerank_error`，不会自动下载模型。

## 指标说明

| 指标 | 说明 | 衡量部分 |
| --- | --- | --- |
| `Recall@5` | Top 5 citation 中是否命中任一 gold source | 检索召回 |
| `MRR` | 第一个正确来源的倒数排名 | 排序质量 |
| `Citation Hit Rate` | 最终 citation 是否包含正确来源 | 可引用证据命中 |

当前 `gold_answer_keywords` 只作为人工分析字段保留，不做答案语义评分。这样可以避免引入 LLM-as-judge，也避免真实外部调用。

## 运行方式

语法检查：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app course_rag\eval
```

快速验证：

```powershell
.\rag\Scripts\python.exe course_rag\eval\run_eval.py --limit 3
```

完整评测：

```powershell
.\rag\Scripts\python.exe course_rag\eval\run_eval.py
```

完整结果会输出到：

```text
course_rag/eval/results/day11_text_rag_eval.json
course_rag/eval/results/day11_text_rag_eval.md
```

## 本次评测结果

本次完整评测共 30 条问题，结果如下：

| 实验 | Questions | Recall@5 | MRR | Citation Hit Rate | Rerank Used | Rerank Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `dense` | 30 | 0.8667 | 0.7389 | 0.8667 | 0 | 0 |
| `hybrid` | 30 | 0.9667 | 0.8583 | 0.9667 | 0 | 0 |
| `hybrid-rerank` | 30 | 1.0000 | 0.8478 | 1.0000 | 30 | 0 |

从结果看：

- `hybrid` 相比 `dense` 明显提升 `Recall@5` 和 `MRR`，说明 BM25 + RRF 对课程术语、文件定位和考试题类问题有帮助。
- `hybrid-rerank` 在当前 30 条评测上做到 `Recall@5=1.0000` 和 `Citation Hit Rate=1.0000`，说明 rerank 后最终 citation 覆盖更稳。
- `hybrid-rerank` 的 `MRR` 略低于 `hybrid`，说明 reranker 并不总是把正确来源排到最前，需要后续继续扩大评测集确认。
- `network-012` 这类“指定某份试题”的问题，`dense` 和 `hybrid` 容易被 `串讲+习题课 25.pdf` 抢走 Top1，后续可考虑课程/文件名意图识别或 metadata 过滤。

## 阶段结论

本阶段已经补齐文本 RAG 的评测闭环。下一步不宜盲目推进更大的 V2 改造，应该先基于 miss case 判断：如果问题集中在文件名、课程、题型定位，应优先补 query routing 和 metadata 过滤；如果问题来自图片、表格或扫描页，再推进 EvidenceDocument、OCR/VLM 和视觉证据。
