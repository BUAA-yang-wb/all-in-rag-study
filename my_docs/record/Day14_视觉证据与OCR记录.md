# Day14 视觉证据与 OCR 记录

## 本阶段目标

本阶段完成 V2 阶段 4-6 的主要代码接入：让图片、Markdown 图片引用、OCR 文本和可选 VLM caption 都能作为 `EvidenceDocument` 进入现有文本索引。

当前阶段不把 VLM 放入在线 `/ask` 或 `/search` 链路，也不默认全量生成 caption。在线问答只检索已经离线构建并写入索引的 evidence。

## 采用策略

视觉资料统一先转成 evidence：

```text
图片 / Markdown image_refs / PDF 候选页
-> image_metadata / image_ref / ocr_text / optional caption
-> EvidenceDocument
-> ParentDocument / ChunkedDocument
-> FAISS + hybrid + rerank
```

OCR 默认使用当前项目虚拟环境中已安装的 RapidOCR。已下载的 PP-OCRv5 Paddle 模型只作为后续可选 provider，不作为当前默认依赖。

PDF OCR 目标采用页级策略：

- 默认不运行 OCR/caption 时，不扫描 PDF 页、不渲染页图。
- 启用 `--run-ocr` 或 `--run-caption` 后，才对 PDF 做页级检查。
- 文件级低文本 PDF 的已扫描页面全量作为候选页。
- 普通文本层 PDF 只把单页去空白文本字符数低于阈值的页面作为候选页。
- 默认页级阈值是 80，可通过 `--pdf-page-low-text-chars` 调整。

## 实现内容

- 新增 `course_rag/app/rag/visual_evidence.py`，负责图片 evidence、Markdown image_refs、PDF 页图、OCR evidence 和可选 caption evidence。
- `indexing.py` 默认纳入 `priority=mvp,v2`，并把 text evidence 与 visual evidence 合并为 `evidence_v2.jsonl` 后重建索引。
- `/ingest` 增加 `run_ocr`、`ocr_provider`、`run_caption`、`caption_provider`、`visual_limit`、`ocr_max_pdf_pages`、`pdf_page_low_text_chars` 和 `caption_max_items`。
- 前端 evidence 列表增加图片路径展示，便于从检索结果回到原始图片或 PDF 页图。
- VLM caption provider 已接入为可选能力，默认 `caption_provider=none`，不会自动运行。

## 运行与验证

语法检查：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app course_rag\eval
```

默认重建索引：

```powershell
.\rag\Scripts\python.exe course_rag\app\rag\indexing.py --rebuild
```

小样本 OCR 验证：

```powershell
.\rag\Scripts\python.exe course_rag\app\rag\indexing.py --rebuild --run-ocr --visual-limit 2 --ocr-max-pdf-pages 2 --no-evidence-cache --no-progress
```

本阶段未默认构建全量 OCR/caption 缓存。全量 OCR 会消耗较长时间，应作为离线任务单独执行；caption 仍需先配置 llama.cpp CLI、GGUF 和 mmproj 路径。
