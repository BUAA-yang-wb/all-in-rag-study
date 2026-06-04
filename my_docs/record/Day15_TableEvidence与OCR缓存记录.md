# Day15 Table Evidence 与 OCR 缓存记录

## 本阶段目标

本阶段完成 V2 阶段 5 和阶段 7 的落地：全量构建 `mvp,v2` 范围内 OCR 离线缓存，并把表格作为独立 `EvidenceDocument` 进入默认文本索引。

阶段 6 的 VLM caption 保持默认关闭：不默认生成 caption，也不默认读取旧 caption 缓存进入索引。

## 采用策略

OCR 仍使用当前虚拟环境中可直接运行的 RapidOCR。全量构建时使用：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\app\rag\indexing.py --rebuild --run-ocr --ocr-provider rapidocr --pdf-page-low-text-chars 80 --no-progress
```

OCR 生成后写入 `course_rag/data/processed/evidence_ocr.jsonl`。后续默认重建不重新跑 OCR，但会读取已有 OCR 缓存并纳入索引。

表格证据采用混合抽取：

```text
LoadedDocument / Docling JSON
-> Docling table structure 优先
-> Markdown/PDF 类表格文本兜底
-> table_markdown EvidenceDocument
-> 当前 parent-child chunk + FAISS 索引
```

小表整表入库；大表按最多 20 行切分，并在每个切片中保留表头。

## 实现内容

- 新增 `course_rag/app/rag/table_evidence.py`，生成 `modality=table`、`evidence_kind=table_markdown` 的表格证据。
- 新增 `course_rag/data/processed/evidence_table.jsonl` 缓存。
- `indexing.py` 默认追加 table evidence，并在 `index_meta.json` 中记录 `table_evidence_stats`。
- `/ingest` 增加 `include_table_evidence`，CLI 增加 `--no-table-evidence`。
- `visual_evidence.py` 改为 OCR 识别过程中增量写入缓存，降低长任务中断损失。
- `visual_evidence.py` 在 `run_caption=false` 时不读取 caption 缓存，确保 VLM caption 默认关闭。
- `chunking.py` 的 parent id 纳入 `evidence_id`、`modality`、`evidence_kind` 和 `asset_path`，避免 native text 与 OCR 文本完全相同时发生 chunk id 碰撞。

## 运行与验证

语法检查：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app course_rag\eval
```

全量 OCR 构建曾在 embedding 阶段前超时，但 OCR 与 table 缓存已写入。随后复用缓存完成默认索引重建：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\app\rag\indexing.py --rebuild --ocr-provider rapidocr --pdf-page-low-text-chars 80 --no-progress
```

当前索引统计：

- vectors：9138
- evidence 总数：5724
- native_text：4243
- image_metadata：177
- image_ref：167
- ocr_text：998
- table_markdown：139
- caption：0
- parent_child_mappings：9138

`/search` 验证：

- `evidence_kind="ocr_text"` 返回 OCR citation。
- `modality="table"` 返回 table citation。

后续建议优先扩展 V2 评测集，并抽样检查 OCR/table evidence 质量。
