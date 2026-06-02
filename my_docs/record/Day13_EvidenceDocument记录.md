# Day13 EvidenceDocument 证据层记录

## 本阶段目标

本阶段开始 V2 第一批改动：先建立统一证据层，但不接入 OCR、VLM caption、Milvus 或新的 embedding 模型。

当前文本 RAG baseline 已经比较稳定，V2 的主要缺口是图片、扫描页、表格等资料未来需要统一表达为可检索、可引用、可追溯的 evidence。因此本阶段先让现有 MVP 文本资料经过 `EvidenceDocument`，并将 V2 text evidence 索引切换为默认文本链路。

## 采用策略

新增 `EvidenceDocument` 作为 loader 与 chunk/index 之间的兼容层。

当前只生成文本证据：

```text
LoadedDocument
-> EvidenceDocument(modality=text, evidence_kind=native_text)
-> LoadedDocument 兼容形态
-> ParentDocument / ChunkedDocument
-> FAISS + hybrid + rerank
```

`evidence_id` 使用来源、页码、section、证据类型、parser backend 等稳定字段生成，不依赖 chunk 内容。这样后续调整 chunk 参数时，证据引用不会跟着全部变化。

证据缓存采用 JSONL：

```text
course_rag/data/processed/evidence_text.jsonl
```

V2 text evidence 索引使用当前默认目录：

```text
course_rag/vector_index_v2_text/
```

## 实现内容

- 新增 `course_rag/app/rag/evidence.py`，定义 `EvidenceDocument`、文本 evidence 转换、JSONL 读写和统计。
- `indexing.py` 默认启用 text evidence，并保留 `--no-evidence`、`--evidence-cache`、`--evidence-pipeline-version` 等调试参数。
- chunk、retrieval、generation 继续沿用原有流程，只透传 evidence metadata。
- `/ask` 和 `/search` 的 citation/retrieval 增加可选字段：`evidence_id`、`source_doc_id`、`modality`、`evidence_kind`、`asset_path`、`parser_backend`、`context_before`、`context_after`。
- 前端证据列表增加 evidence 相关类型和调试 chip。
- 评测脚本增加 `--index-dir` 和 `--result-prefix`，用于对比不同索引或保存阶段评测结果。

## 运行与验证

语法检查：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app course_rag\eval
```

重建默认 V2 text evidence 索引：

```powershell
.\rag\Scripts\python.exe course_rag\app\rag\indexing.py --rebuild
```

对比评测：

```powershell
.\rag\Scripts\python.exe course_rag\eval\run_eval.py --experiment hybrid-rerank --result-prefix day13_default_v2_eval
```

本阶段不需要安装 OCR/VLM 运行时，也不调用外部 API。
