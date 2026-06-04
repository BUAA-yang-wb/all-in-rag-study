"""Manifest-driven document loaders for the BUAA course RAG corpus.

Day04 uses a Docling-first parsing pipeline:

``data_manifest.jsonl -> native/Docling routing -> parsed cache -> LoadedDocument``

Markdown/TXT files keep native readers because their source structure is already
useful. Text-layer PDFs use PyPDF page extraction for coverage and citation.
DOCX/PPTX/low-text PDFs are routed to Docling. A ``basic`` backend is kept only
as an explicit emergency fallback for quick local smoke tests when Docling is
not installed yet.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote
from xml.etree import ElementTree


logger = logging.getLogger(__name__)

DEFAULT_MANIFEST_PATH = Path("course_rag/data/processed/data_manifest.jsonl")
DEFAULT_PARSED_CACHE_ROOT = Path("course_rag/data/processed/parsed_cache")
DEFAULT_MODEL_CACHE_ROOT = Path("course_rag/data/processed/model_cache")
PDF_TEXT_REPAIR_MIN_CHARS = 1_000
PDF_TEXT_REPAIR_MIN_GAIN_RATIO = 1.25

NATIVE_STRATEGIES = {"markdown_native", "plain_text_native"}
PDF_TEXT_STRATEGIES = {"pdf_text_layer"}
DOCLING_STRATEGIES = {"docling_document", "docling_image"}
SUPPORTED_STRATEGIES = NATIVE_STRATEGIES | PDF_TEXT_STRATEGIES | DOCLING_STRATEGIES
STRATEGY_ALIASES = {
    "markdown": "markdown_native",
    "plain_text": "plain_text_native",
    "text_pdf": "pdf_text_layer",
    "docx": "docling_document",
    "scanned_pdf_or_low_text": "docling_document",
    "image_asset_v2": "docling_image",
}

_DOCLING_CONVERTER: Any | None = None


@dataclass
class LoadedDocument:
    """Normalized document used before text chunking."""

    page_content: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_content": self.page_content,
            "metadata": self.metadata,
        }


def read_manifest(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    priority: str = "mvp",
    strategies: set[str] | None = None,
    limit: int | None = None,
    skip_low_text_pdfs: bool = False,
) -> list[dict[str, Any]]:
    """Read manifest records filtered by priority and parse strategy."""

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    selected_strategies = strategies or SUPPORTED_STRATEGIES
    selected_priorities = parse_priority_filter(priority)
    records: list[dict[str, Any]] = []

    with manifest_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw_record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on manifest line {line_no}: {exc}") from exc

            record = normalize_manifest_record(raw_record)
            if selected_priorities is not None and record.get("priority") not in selected_priorities:
                continue
            if record.get("parse_strategy") not in selected_strategies:
                continue
            if skip_low_text_pdfs and is_low_text_pdf_record(record):
                continue

            records.append(record)
            if limit is not None and len(records) >= limit:
                break

    return records


def parse_priority_filter(priority: str) -> set[str] | None:
    """Return selected manifest priorities, or None for all priorities."""

    if priority == "all":
        return None
    selected = {item.strip() for item in priority.split(",") if item.strip()}
    return selected or {"mvp"}


def is_low_text_pdf_record(record: dict[str, Any]) -> bool:
    return (
        str(record.get("file_type", "")).lower() == "pdf"
        and record.get("is_text_extractable") is False
    )


def normalize_manifest_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize older Day04 manifest records to the Docling-first schema."""

    normalized = dict(record)
    strategy = normalize_strategy(str(normalized.get("parse_strategy", "skip")))
    normalized["parse_strategy"] = strategy
    if not normalized.get("parser_backend"):
        normalized["parser_backend"] = infer_parser_backend(strategy)
    return normalized


def normalize_strategy(strategy: str) -> str:
    return STRATEGY_ALIASES.get(strategy, strategy)


def infer_parser_backend(strategy: str) -> str:
    if strategy in NATIVE_STRATEGIES:
        return "native"
    if strategy in PDF_TEXT_STRATEGIES:
        return "pypdf"
    if strategy in DOCLING_STRATEGIES:
        return "docling"
    return "none"


def load_documents(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    repo_root: Path | None = None,
    priority: str = "mvp",
    strategies: set[str] | None = None,
    limit: int | None = None,
    backend: str = "auto",
    cache_root: Path = DEFAULT_PARSED_CACHE_ROOT,
    strict: bool = False,
    skip_low_text_pdfs: bool = False,
) -> list[LoadedDocument]:
    """Load documents described by the manifest.

    Args:
        manifest_path: JSONL manifest generated by build_data_manifest.py.
        repo_root: Repository root used to resolve manifest source paths.
        priority: Manifest priority to load. Use "all" to disable filtering.
        strategies: Parse strategies to load.
        limit: Optional record limit for smoke tests.
        backend: ``auto`` uses manifest routing, ``docling`` forces Docling for
            Docling-compatible records, and ``basic`` uses local fallbacks.
        cache_root: Parsed Docling Markdown/JSON cache directory.
        strict: Raise on individual file load failures when true.
    """

    if backend not in {"auto", "docling", "basic"}:
        raise ValueError(f"Unsupported backend: {backend}")

    root = (repo_root or Path.cwd()).resolve()
    records = read_manifest(
        manifest_path=manifest_path,
        priority=priority,
        strategies=strategies,
        limit=limit,
        skip_low_text_pdfs=skip_low_text_pdfs,
    )

    documents: list[LoadedDocument] = []
    for record in records:
        try:
            documents.extend(
                load_record(
                    record,
                    repo_root=root,
                    backend=backend,
                    cache_root=(root / cache_root).resolve(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - keep batch loading robust.
            message = f"Failed to load {record.get('source')}: {exc}"
            if strict:
                raise RuntimeError(message) from exc
            logger.warning(message)

    return documents


def load_record(
    record: dict[str, Any],
    repo_root: Path,
    backend: str,
    cache_root: Path,
) -> list[LoadedDocument]:
    """Load one manifest record into one or more normalized documents."""

    source = record.get("source")
    if not source:
        raise ValueError("Manifest record missing source")

    file_path = (repo_root / source).resolve()
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    strategy = record.get("parse_strategy")
    if strategy == "markdown_native":
        return [load_markdown(file_path, record)]
    if strategy == "plain_text_native":
        return [load_plain_text(file_path, record)]
    if strategy == "pdf_text_layer":
        return load_pdf_text_layer_documents(file_path, record, repo_root, cache_root)
    if strategy in DOCLING_STRATEGIES:
        if backend == "basic":
            return load_basic_document(file_path, record)
        return load_docling_documents(file_path, record, repo_root, cache_root)

    raise ValueError(f"Unsupported parse strategy for loader: {strategy}")


def load_markdown(path: Path, record: dict[str, Any]) -> LoadedDocument:
    text = path.read_text(encoding="utf-8", errors="ignore")
    image_refs = extract_markdown_image_refs(text, path)
    metadata = base_metadata(record, path)
    metadata.update(
        {
            "page": None,
            "section": None,
            "loader": "native_markdown",
            "parsed_markdown_path": None,
            "parsed_json_path": None,
            "image_refs": image_refs,
            "image_ref_count": len(image_refs),
            "text_length": len(text),
        }
    )
    return LoadedDocument(page_content=text, metadata=metadata)


def load_plain_text(path: Path, record: dict[str, Any]) -> LoadedDocument:
    text = path.read_text(encoding="utf-8", errors="ignore")
    metadata = base_metadata(record, path)
    metadata.update(
        {
            "page": None,
            "section": None,
            "loader": "native_plain_text",
            "parsed_markdown_path": None,
            "parsed_json_path": None,
            "image_refs": [],
            "image_ref_count": 0,
            "text_length": len(text),
        }
    )
    return LoadedDocument(page_content=text, metadata=metadata)


def load_pdf_text_layer_documents(
    path: Path,
    record: dict[str, Any],
    repo_root: Path,
    cache_root: Path,
) -> list[LoadedDocument]:
    page_texts = extract_pdf_page_texts(path)
    if not page_texts:
        raise ValueError("PDF text layer produced no non-empty pages")

    cache_dir = cache_root / str(record.get("doc_id") or path.stem)
    cache_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = cache_dir / "document.md"
    markdown_path.write_text(
        format_pdf_text_layer_markdown(page_texts),
        encoding="utf-8",
        newline="\n",
    )

    documents: list[LoadedDocument] = []
    total_chars = sum(len(text) for _, text in page_texts)
    for page_index, text in page_texts:
        metadata = base_metadata(record, path)
        metadata.update(
            {
                "page": page_index,
                "section": None,
                "loader": "pypdf_text_layer",
                "parsed_markdown_path": safe_repo_relative(markdown_path, repo_root),
                "docling_markdown_path": None,
                "parsed_json_path": None,
                "image_refs": [],
                "image_ref_count": 0,
                "text_length": len(text),
                "text_normalized": True,
                "normalization_strategy": "pdf_line_merge_v1",
                "pdf_text_layer_total_chars": total_chars,
            }
        )
        documents.append(LoadedDocument(page_content=text, metadata=metadata))
    return documents


def load_docling_documents(
    path: Path,
    record: dict[str, Any],
    repo_root: Path,
    cache_root: Path,
) -> list[LoadedDocument]:
    configure_local_model_cache(repo_root)
    converter = get_docling_converter()
    result = converter.convert(str(path))
    docling_document = result.document

    docling_markdown = docling_document.export_to_markdown()
    if not docling_markdown.strip():
        raise ValueError("Docling produced empty Markdown")

    cache_dir = cache_root / str(record.get("doc_id") or path.stem)
    cache_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = cache_dir / "document.md"
    docling_markdown_path = cache_dir / "document.docling.md"
    json_path = cache_dir / "document.json"

    docling_markdown_path.write_text(docling_markdown, encoding="utf-8", newline="\n")
    write_docling_json(docling_document, json_path)

    repaired_pages = repair_pdf_with_text_layer(path, record, docling_markdown)
    if repaired_pages:
        repaired_markdown = format_pdf_text_layer_markdown(repaired_pages)
        markdown_path.write_text(repaired_markdown, encoding="utf-8", newline="\n")
        return build_pdf_page_documents(
            repaired_pages,
            record,
            path,
            repo_root,
            markdown_path,
            docling_markdown_path,
            json_path,
            len(docling_markdown),
        )

    markdown_path.write_text(docling_markdown, encoding="utf-8", newline="\n")
    image_refs = extract_markdown_image_refs(docling_markdown, markdown_path)
    metadata = base_metadata(record, path)
    metadata.update(
        {
            "page": None,
            "section": None,
            "loader": "docling",
            "parsed_markdown_path": safe_repo_relative(markdown_path, repo_root),
            "docling_markdown_path": safe_repo_relative(docling_markdown_path, repo_root),
            "parsed_json_path": safe_repo_relative(json_path, repo_root),
            "image_refs": image_refs,
            "image_ref_count": len(image_refs),
            "text_length": len(docling_markdown),
        }
    )
    return [LoadedDocument(page_content=docling_markdown, metadata=metadata)]


def repair_pdf_with_text_layer(
    path: Path,
    record: dict[str, Any],
    docling_markdown: str,
) -> list[tuple[int, str]]:
    """Repair incomplete Docling PDF output with the PDF text layer.

    Some lecture-slide PDFs trigger Docling layout/preprocess memory failures on
    local CPU but still return a partial document. For text-extractable PDFs, a
    page-level text-layer fallback is safer than silently indexing truncated
    content.
    """

    if str(record.get("file_type", "")).lower() != "pdf":
        return []
    if record.get("is_text_extractable") is not True:
        return []

    page_texts = extract_pdf_page_texts(path)
    text_layer_chars = sum(len(text) for _, text in page_texts)
    if text_layer_chars < PDF_TEXT_REPAIR_MIN_CHARS:
        return []

    docling_chars = len(strip_markdown_noise(docling_markdown))
    if text_layer_chars >= max(
        PDF_TEXT_REPAIR_MIN_CHARS,
        int(docling_chars * PDF_TEXT_REPAIR_MIN_GAIN_RATIO),
    ):
        logger.info(
            "Repairing incomplete Docling PDF output with text layer: %s "
            "(docling_chars=%s, text_layer_chars=%s)",
            record.get("source"),
            docling_chars,
            text_layer_chars,
        )
        return page_texts

    return []


def extract_pdf_page_texts(path: Path) -> list[tuple[int, str]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf is not installed; cannot repair incomplete PDF text")
        return []

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 - best-effort repair path.
        logger.warning("Failed to open PDF with pypdf: %s", exc)
        return []

    page_texts: list[tuple[int, str]] = []
    for page_index, page in enumerate(reader.pages, 1):
        try:
            text = normalize_page_text(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 - keep other pages usable.
            logger.warning("Failed to extract PDF page %s from %s: %s", page_index, path, exc)
            continue
        if text:
            page_texts.append((page_index, text))
    return page_texts


def strip_markdown_noise(markdown: str) -> str:
    without_images = markdown.replace("<!-- image -->", "")
    return re.sub(r"\s+", "", without_images)


def format_pdf_text_layer_markdown(page_texts: list[tuple[int, str]]) -> str:
    parts = []
    for page_index, text in page_texts:
        parts.append(f"<!-- page: {page_index} -->\n\n## Page {page_index}\n\n{text}")
    return "\n\n".join(parts).strip() + "\n"


def build_pdf_page_documents(
    page_texts: list[tuple[int, str]],
    record: dict[str, Any],
    path: Path,
    repo_root: Path,
    markdown_path: Path,
    docling_markdown_path: Path,
    json_path: Path,
    docling_markdown_chars: int,
) -> list[LoadedDocument]:
    documents: list[LoadedDocument] = []
    total_text_layer_chars = sum(len(text) for _, text in page_texts)
    for page_index, text in page_texts:
        metadata = base_metadata(record, path)
        metadata.update(
            {
                "page": page_index,
                "section": None,
                "loader": "docling_pypdf_repair",
                "repair_backend": "pypdf",
                "repair_reason": "docling_pdf_output_coverage_too_low",
                "docling_markdown_chars": docling_markdown_chars,
                "text_layer_chars": total_text_layer_chars,
                "parsed_markdown_path": safe_repo_relative(markdown_path, repo_root),
                "docling_markdown_path": safe_repo_relative(docling_markdown_path, repo_root),
                "parsed_json_path": safe_repo_relative(json_path, repo_root),
                "image_refs": [],
                "image_ref_count": 0,
                "text_length": len(text),
                "text_normalized": True,
                "normalization_strategy": "pdf_line_merge_v1",
            }
        )
        documents.append(LoadedDocument(page_content=text, metadata=metadata))
    return documents


def configure_local_model_cache(repo_root: Path) -> None:
    """Keep Docling/Hugging Face model artifacts inside ignored project data.

    Some local Python setups point Hugging Face caches to protected global paths.
    The course corpus is already local/private, so storing parser model artifacts
    under ``course_rag/data/processed`` keeps the project reproducible without
    requiring administrator permissions.
    """

    cache_root = (repo_root / DEFAULT_MODEL_CACHE_ROOT).resolve()
    hf_home = cache_root / "huggingface"
    hf_hub_cache = hf_home / "hub"
    hf_home.mkdir(parents=True, exist_ok=True)
    hf_hub_cache.mkdir(parents=True, exist_ok=True)

    os.environ["HF_HOME"] = str(hf_home)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(hf_hub_cache)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def write_docling_json(docling_document: Any, output_path: Path) -> None:
    if hasattr(docling_document, "export_to_dict"):
        payload = docling_document.export_to_dict()
    elif hasattr(docling_document, "model_dump"):
        payload = docling_document.model_dump()
    else:
        payload = {"repr": repr(docling_document)}

    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def get_docling_converter() -> Any:
    global _DOCLING_CONVERTER
    if _DOCLING_CONVERTER is not None:
        return _DOCLING_CONVERTER

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        raise RuntimeError(
            "Docling is not installed. Create a Python >=3.10 environment and "
            "install dependencies with `python -m pip install -r "
            "course_rag/requirements.txt`, or run this loader with "
            "`--backend basic` for an emergency fallback."
        ) from exc

    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = should_enable_docling_ocr()
    pdf_options.do_table_structure = True

    _DOCLING_CONVERTER = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
        }
    )
    return _DOCLING_CONVERTER


def should_enable_docling_ocr() -> bool:
    """Enable OCR only when explicitly requested.

    Course slides usually contain an extractable text layer. Keeping OCR off in
    the default MVP avoids very slow CPU runs and memory spikes while still
    preserving Docling's layout/table-aware parsing path.
    """

    return os.environ.get("COURSE_RAG_DOCLING_OCR", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def load_basic_document(path: Path, record: dict[str, Any]) -> list[LoadedDocument]:
    """Explicit fallback for smoke tests before Docling is installed."""

    file_type = str(record.get("file_type", "")).lower()
    if file_type == "pdf":
        return load_basic_pdf(path, record)
    if file_type == "docx":
        return [load_basic_docx(path, record)]
    if file_type in {"md", "markdown"}:
        return [load_markdown(path, record)]
    if file_type == "txt":
        return [load_plain_text(path, record)]
    raise ValueError(f"Basic backend does not support file type: {file_type}")


def load_basic_pdf(path: Path, record: dict[str, Any]) -> list[LoadedDocument]:
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext is required for basic PDF loading")

    command = [
        "pdftotext",
        "-enc",
        "UTF-8",
        "-layout",
        str(path),
        "-",
    ]
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=120,
    )
    if completed.returncode != 0 and not completed.stdout:
        raise RuntimeError(completed.stderr.strip() or "pdftotext failed")

    documents: list[LoadedDocument] = []
    for page_index, page_text in enumerate(completed.stdout.split("\f"), 1):
        cleaned = normalize_page_text(page_text)
        if not cleaned:
            continue
        metadata = base_metadata(record, path)
        metadata.update(
            {
                "page": page_index,
                "section": None,
                "loader": "basic_pdf",
                "parsed_markdown_path": None,
                "parsed_json_path": None,
                "image_refs": [],
                "image_ref_count": 0,
                "text_length": len(cleaned),
                "text_normalized": True,
                "normalization_strategy": "pdf_line_merge_v1",
            }
        )
        documents.append(LoadedDocument(page_content=cleaned, metadata=metadata))

    if not documents:
        raise ValueError("PDF produced no non-empty text pages")
    return documents


def load_basic_docx(path: Path, record: dict[str, Any]) -> LoadedDocument:
    paragraphs = extract_docx_paragraphs(path)
    text = "\n\n".join(paragraphs).strip()
    if not text:
        raise ValueError("DOCX produced no paragraph text")

    metadata = base_metadata(record, path)
    metadata.update(
        {
            "page": None,
            "section": None,
            "loader": "basic_docx",
            "parsed_markdown_path": None,
            "parsed_json_path": None,
            "image_refs": [],
            "image_ref_count": 0,
            "text_length": len(text),
            "paragraph_count": len(paragraphs),
        }
    )
    return LoadedDocument(page_content=text, metadata=metadata)


def base_metadata(record: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "doc_id": record.get("doc_id"),
        "source": record.get("source"),
        "source_name": path.name,
        "source_stem": path.stem,
        "course": record.get("course"),
        "category": record.get("category"),
        "file_type": record.get("file_type"),
        "visibility": record.get("visibility"),
        "priority": record.get("priority"),
        "parser_backend": record.get("parser_backend"),
        "parse_strategy": record.get("parse_strategy"),
        "size_mb": record.get("size_mb"),
        "notes": record.get("notes", ""),
    }


def safe_repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def extract_markdown_image_refs(text: str, markdown_path: Path) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    markdown_pattern = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")
    html_pattern = re.compile(
        r"<img\b[^>]*\bsrc=[\"'](?P<target>[^\"']+)[\"'][^>]*>",
        flags=re.IGNORECASE,
    )

    for match in markdown_pattern.finditer(text):
        refs.append(build_image_ref(match.group("target"), markdown_path, match.group("alt")))

    for match in html_pattern.finditer(text):
        refs.append(build_image_ref(match.group("target"), markdown_path, ""))

    return refs


def build_image_ref(target: str, markdown_path: Path, alt: str) -> dict[str, str]:
    original_target = target.strip()
    cleaned_target = unquote(original_target.strip("<>").strip().replace("\\", "/"))
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", cleaned_target):
        resolved = cleaned_target
    else:
        resolved = (markdown_path.parent / cleaned_target).resolve().as_posix()

    return {
        "alt": alt.strip(),
        "target": original_target,
        "normalized_target": cleaned_target,
        "resolved": resolved,
    }


def extract_docx_paragraphs(path: Path) -> list[str]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except KeyError as exc:
        raise ValueError("DOCX missing word/document.xml") from exc

    root = ElementTree.fromstring(xml_bytes)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        texts = [
            node.text or ""
            for node in paragraph.findall(".//w:t", namespace)
        ]
        paragraph_text = "".join(texts).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)
    return paragraphs


def normalize_page_text(text: str) -> str:
    """Normalize text extracted from one PDF page.

    PyPDF may emit hard line breaks after every character or short phrase,
    especially for slide PDFs. This cleanup repairs obvious wrapped lines while
    preserving page boundaries, list items, and table-like rows for Day05.
    """

    raw_lines = [
        normalize_inline_whitespace(line.strip())
        for line in text.replace("\x00", "").splitlines()
    ]
    if not any(raw_lines):
        return ""

    content_lines = [line for line in raw_lines if line]
    fragmented_page = looks_like_fragmented_page(content_lines)

    blocks: list[str] = []
    current = ""
    for line in raw_lines:
        if not line:
            if current:
                blocks.append(current)
                current = ""
            continue

        if not current:
            current = line
            continue

        if should_merge_pdf_lines(current, line, fragmented_page):
            current = join_pdf_lines(current, line)
        else:
            blocks.append(current)
            current = line

    if current:
        blocks.append(current)

    normalized = "\n".join(block for block in blocks if block.strip()).strip()
    return re.sub(r"\n{3,}", "\n\n", normalized)


def normalize_inline_whitespace(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def looks_like_fragmented_page(lines: list[str]) -> bool:
    if len(lines) < 4:
        return False

    lengths = [visible_text_len(line) for line in lines]
    if not lengths:
        return False

    short_lines = sum(1 for length in lengths if length <= 6)
    very_short_lines = sum(1 for length in lengths if length <= 2)
    avg_len = sum(lengths) / len(lengths)

    return (
        very_short_lines >= 4
        or short_lines / len(lengths) >= 0.45
        or avg_len <= 8
    )


def should_merge_pdf_lines(previous: str, current: str, fragmented_page: bool) -> bool:
    if is_structural_pdf_line(current):
        return False
    if is_table_like_pdf_line(previous) or is_table_like_pdf_line(current):
        return False
    if previous.endswith("-") and starts_with_ascii_letter(current):
        return True

    previous_len = visible_text_len(previous)
    current_len = visible_text_len(current)

    if fragmented_page:
        return not ends_with_strong_boundary(previous)

    if previous_len <= 2 or current_len <= 2:
        return not ends_with_strong_boundary(previous)
    if previous_len <= 6 and current_len <= 12:
        return not ends_with_strong_boundary(previous)
    if current_len <= 6 and not ends_with_strong_boundary(previous):
        return True

    return False


def join_pdf_lines(previous: str, current: str) -> str:
    if previous.endswith("-") and starts_with_ascii_letter(current):
        return previous[:-1] + current
    separator = " " if needs_join_space(previous, current) else ""
    return previous + separator + current


def visible_text_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def is_structural_pdf_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if re.match(r"^(#{1,6}\s+|[-*+•]\s+|\d+[.)、]\s+|[（(]?\d+[）)]\s*)", stripped):
        return True
    if re.match(r"^第[一二三四五六七八九十百千万\d]+[章节讲部分]\b", stripped):
        return True
    return False


def is_table_like_pdf_line(line: str) -> bool:
    if "|" in line or "\t" in line:
        return True
    return bool(re.search(r"\S+\s{2,}\S+\s{2,}\S+", line))


def ends_with_strong_boundary(text: str) -> bool:
    return bool(re.search(r"[。！？!?；;：:]\s*$", text))


def starts_with_ascii_letter(text: str) -> bool:
    return bool(text) and text[0].isascii() and text[0].isalpha()


def needs_join_space(previous: str, current: str) -> bool:
    if not previous or not current:
        return False
    left = previous[-1]
    right = current[0]
    if right in ".,;:!?，。！？；：、)]}）】》":
        return False
    return left.isascii() and right.isascii() and left.isalnum() and right.isalnum()


def summarize_documents(documents: Iterable[LoadedDocument]) -> dict[str, Any]:
    docs = list(documents)
    by_loader = Counter(doc.metadata.get("loader", "unknown") for doc in docs)
    by_backend = Counter(doc.metadata.get("parser_backend", "unknown") for doc in docs)
    by_strategy = Counter(doc.metadata.get("parse_strategy", "unknown") for doc in docs)
    by_course = Counter(doc.metadata.get("course", "unknown") for doc in docs)
    by_file_type = Counter(doc.metadata.get("file_type", "unknown") for doc in docs)
    total_chars = sum(len(doc.page_content) for doc in docs)
    source_count = len({doc.metadata.get("source") for doc in docs})

    return {
        "documents": len(docs),
        "source_files": source_count,
        "total_chars": total_chars,
        "avg_chars": round(total_chars / len(docs), 1) if docs else 0,
        "by_loader": dict(sorted(by_loader.items())),
        "by_parser_backend": dict(sorted(by_backend.items())),
        "by_parse_strategy": dict(sorted(by_strategy.items())),
        "by_course": dict(sorted(by_course.items())),
        "by_file_type": dict(sorted(by_file_type.items())),
    }


def parse_strategy_arg(value: str) -> set[str]:
    if value == "supported":
        return SUPPORTED_STRATEGIES
    return {
        normalize_strategy(item.strip())
        for item in value.split(",")
        if item.strip()
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Manifest JSONL generated by build_data_manifest.py.",
    )
    parser.add_argument(
        "--priority",
        default="mvp",
        help="Priority to load. Use 'all' to disable priority filtering.",
    )
    parser.add_argument(
        "--strategies",
        default="supported",
        help="Comma-separated parse strategies, old aliases, or 'supported'.",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "docling", "basic"],
        default="auto",
        help="Parsing backend. Default follows manifest routing.",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_PARSED_CACHE_ROOT,
        help="Directory for Docling Markdown/JSON cache.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional manifest record limit for smoke tests.",
    )
    parser.add_argument(
        "--preview",
        type=int,
        default=3,
        help="Number of loaded documents to preview.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail fast on individual file load errors.",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    documents = load_documents(
        manifest_path=args.manifest,
        priority=args.priority,
        strategies=parse_strategy_arg(args.strategies),
        limit=args.limit,
        backend=args.backend,
        cache_root=args.cache_root,
        strict=args.strict,
    )
    print(json.dumps(summarize_documents(documents), ensure_ascii=False, indent=2))

    for doc in documents[: args.preview]:
        preview = doc.page_content[:160].replace("\n", "\\n")
        print(
            json.dumps(
                {
                    "source": doc.metadata.get("source"),
                    "page": doc.metadata.get("page"),
                    "loader": doc.metadata.get("loader"),
                    "parser_backend": doc.metadata.get("parser_backend"),
                    "parse_strategy": doc.metadata.get("parse_strategy"),
                    "course": doc.metadata.get("course"),
                    "category": doc.metadata.get("category"),
                    "chars": len(doc.page_content),
                    "parsed_markdown_path": doc.metadata.get("parsed_markdown_path"),
                    "parsed_json_path": doc.metadata.get("parsed_json_path"),
                    "image_ref_count": doc.metadata.get("image_ref_count", 0),
                    "preview": preview,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
