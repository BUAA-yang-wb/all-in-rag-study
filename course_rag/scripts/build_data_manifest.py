"""Build a privacy-safe local data manifest for the course RAG corpus.

The manifest is the single routing table for Day04 loading. It scans
``course_rag/data`` and classifies each file by course, category, type,
priority, parser backend, and parsing strategy.

Default policy:
- Markdown/TXT use native local readers.
- Text-layer PDFs use PyPDF page extraction for coverage and citation.
- DOCX/PPTX and low-text PDFs use Docling as the structured parser.
- Images are registered for v2 multimodal/OCR work but not included in MVP.
- Homework/answer-like material is excluded from MVP by default.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha1
from pathlib import Path
from typing import Iterable


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}
TEXT_EXTENSIONS = {".md", ".txt"}
DOCLING_DOCUMENT_EXTENSIONS = {".docx", ".pptx"}
PDF_TEXT_THRESHOLD = 500
LARGE_PDF_MB = 50

COURSEWARE_CATEGORY = "\u8bfe\u4ef6"
CLASS_NOTE_CATEGORY = "\u8bfe\u5802\u603b\u7ed3\u7b14\u8bb0"
HOMEWORK_CATEGORY = "\u4f5c\u4e1a"
REVIEW_CATEGORY = "\u590d\u4e60"
ANSWER_KEYWORD = "\u7b54\u6848"


@dataclass
class ManifestRecord:
    doc_id: str
    source: str
    course: str
    category: str
    file_type: str
    size_bytes: int
    size_mb: float
    visibility: str
    priority: str
    parser_backend: str
    parse_strategy: str
    contains_images: bool
    image_ref_count: int
    is_text_extractable: bool | None
    text_chars_sample: int | None
    notes: str


def repo_relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def stable_id(relative_path: str) -> str:
    return sha1(relative_path.encode("utf-8")).hexdigest()[:16]


def read_text_len(path: Path, limit_chars: int = 200_000) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return len(f.read(limit_chars))
    except OSError:
        return 0


def count_markdown_image_refs(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    markdown_refs = re.findall(r"!\[[^\]]*\]\([^)]+\)", text)
    html_refs = re.findall(r"<img\b", text, flags=re.IGNORECASE)
    return len(markdown_refs) + len(html_refs)


def sample_pdf_text_chars(path: Path, pages: int, timeout_seconds: int) -> int | None:
    """Estimate whether a PDF has a usable text layer.

    Docling remains the default parser either way. This signal is only used for
    MVP prioritization because low-text scanned PDFs are slower and noisier.
    """

    if not shutil.which("pdftotext"):
        return None

    command = [
        "pdftotext",
        "-f",
        "1",
        "-l",
        str(pages),
        "-enc",
        "UTF-8",
        "-layout",
        str(path),
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if completed.returncode != 0 and not completed.stdout:
        return None
    return len("".join(completed.stdout.split()))


def infer_course_and_category(path: Path, data_root: Path) -> tuple[str, str]:
    rel_parts = path.resolve().relative_to(data_root.resolve()).parts
    course = rel_parts[0] if rel_parts else "unknown"
    category = rel_parts[1] if len(rel_parts) >= 3 else "root"
    if category.lower() in {"processed", "samples"}:
        category = category.lower()
    return course, category


def infer_visibility(relative_path: str) -> str:
    return "public" if "/samples/" in f"/{relative_path}" else "private"


def classify_record(
    path: Path,
    data_root: Path,
    repo_root: Path,
    pdf_sample_pages: int,
    pdf_timeout_seconds: int,
) -> ManifestRecord:
    relative_path = repo_relative(path, repo_root)
    course, category = infer_course_and_category(path, data_root)
    suffix = path.suffix.lower()
    file_type = suffix.lstrip(".") or "unknown"
    size_bytes = path.stat().st_size
    size_mb = round(size_bytes / (1024 * 1024), 3)
    visibility = infer_visibility(relative_path)

    contains_images = suffix in IMAGE_EXTENSIONS
    image_ref_count = 0
    is_text_extractable: bool | None = None
    text_chars_sample: int | None = None
    parser_backend = "none"
    parse_strategy = "skip"
    priority = "skip"
    notes: list[str] = []

    if suffix == ".md":
        image_ref_count = count_markdown_image_refs(path)
        contains_images = image_ref_count > 0
        text_chars_sample = read_text_len(path)
        is_text_extractable = text_chars_sample > 0
        parser_backend = "native"
        parse_strategy = "markdown_native"
        priority = "mvp" if category == CLASS_NOTE_CATEGORY else "v2"
        if category == HOMEWORK_CATEGORY:
            priority = "skip"
            notes.append("homework_or_personal_material")

    elif suffix == ".txt":
        text_chars_sample = read_text_len(path)
        is_text_extractable = text_chars_sample > 0
        parser_backend = "native"
        parse_strategy = "plain_text_native"
        priority = "mvp" if is_text_extractable else "skip"

    elif suffix in {".docx", ".pptx"}:
        parser_backend = "docling"
        parse_strategy = "docling_document"
        priority = "mvp" if category != HOMEWORK_CATEGORY else "skip"
        if category == HOMEWORK_CATEGORY:
            notes.append("homework_or_personal_material")

    elif suffix == ".pdf":
        text_chars_sample = sample_pdf_text_chars(
            path,
            pdf_sample_pages,
            pdf_timeout_seconds,
        )
        is_text_extractable = (
            text_chars_sample is not None and text_chars_sample > PDF_TEXT_THRESHOLD
        )

        if is_text_extractable:
            parser_backend = "pypdf"
            parse_strategy = "pdf_text_layer"
        else:
            parser_backend = "docling"
            parse_strategy = "docling_document"

        if category == HOMEWORK_CATEGORY:
            priority = "skip"
            notes.append("homework_or_personal_material")
        elif is_text_extractable and category == COURSEWARE_CATEGORY and size_mb <= LARGE_PDF_MB:
            priority = "mvp"
        elif is_text_extractable and category in {REVIEW_CATEGORY, "root"}:
            priority = "v2"
        else:
            priority = "v2"

        if is_text_extractable is False:
            notes.append("low_text_extractability")
            if priority == "mvp":
                priority = "v2"
        if size_mb > LARGE_PDF_MB:
            notes.append("large_pdf")
            if not is_text_extractable:
                priority = "skip"

    elif suffix in IMAGE_EXTENSIONS:
        parser_backend = "docling"
        parse_strategy = "docling_image"
        is_text_extractable = False
        text_chars_sample = 0
        priority = "v2"

    else:
        notes.append("unsupported_file_type")

    lower_name = path.name.lower()
    if ANSWER_KEYWORD in path.name or "answer" in lower_name:
        notes.append("may_contain_exam_answer")
        if priority == "mvp":
            priority = "v2"

    return ManifestRecord(
        doc_id=stable_id(relative_path),
        source=relative_path,
        course=course,
        category=category,
        file_type=file_type,
        size_bytes=size_bytes,
        size_mb=size_mb,
        visibility=visibility,
        priority=priority,
        parser_backend=parser_backend,
        parse_strategy=parse_strategy,
        contains_images=contains_images,
        image_ref_count=image_ref_count,
        is_text_extractable=is_text_extractable,
        text_chars_sample=text_chars_sample,
        notes=";".join(notes),
    )


def iter_source_files(data_root: Path) -> Iterable[Path]:
    for path in sorted(data_root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(data_root).parts
        if rel_parts and rel_parts[0].lower() == "processed":
            continue
        yield path


def write_jsonl(records: list[ManifestRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def build_summary(records: list[ManifestRecord]) -> dict:
    by_course = Counter(record.course for record in records)
    by_category = Counter(record.category for record in records)
    by_type = Counter(record.file_type for record in records)
    by_priority = Counter(record.priority for record in records)
    by_backend = Counter(record.parser_backend for record in records)
    by_strategy = Counter(record.parse_strategy for record in records)

    mb_by_priority: dict[str, float] = defaultdict(float)
    for record in records:
        mb_by_priority[record.priority] += record.size_mb

    return {
        "total_files": len(records),
        "total_mb": round(sum(record.size_mb for record in records), 3),
        "by_course": dict(sorted(by_course.items())),
        "by_category": dict(sorted(by_category.items())),
        "by_file_type": dict(sorted(by_type.items())),
        "by_priority": dict(sorted(by_priority.items())),
        "by_parser_backend": dict(sorted(by_backend.items())),
        "by_parse_strategy": dict(sorted(by_strategy.items())),
        "mb_by_priority": {
            key: round(value, 3) for key, value in sorted(mb_by_priority.items())
        },
        "mvp_files": sum(1 for record in records if record.priority == "mvp"),
        "docling_document_files": sum(
            1 for record in records if record.parse_strategy == "docling_document"
        ),
        "docling_image_files": sum(
            1 for record in records if record.parse_strategy == "docling_image"
        ),
        "text_extractable_pdfs": sum(
            1
            for record in records
            if record.file_type == "pdf" and record.is_text_extractable is True
        ),
        "low_text_pdfs": sum(
            1
            for record in records
            if record.file_type == "pdf" and record.is_text_extractable is False
        ),
        "image_aware_markdown_files": sum(
            1
            for record in records
            if record.file_type == "md" and record.image_ref_count > 0
        ),
    }


def write_summary(summary: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("course_rag/data"),
        help="Directory containing local course files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("course_rag/data/processed/data_manifest.jsonl"),
        help="Manifest JSONL output path. Keep this under ignored data/ by default.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("course_rag/data/processed/data_manifest_summary.json"),
        help="Summary JSON output path.",
    )
    parser.add_argument(
        "--pdf-sample-pages",
        type=int,
        default=10,
        help="Number of first pages used to estimate PDF text extractability.",
    )
    parser.add_argument(
        "--pdf-timeout-seconds",
        type=int,
        default=20,
        help="Per-PDF pdftotext timeout.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path.cwd()
    data_root = args.data_root
    if not data_root.exists():
        raise FileNotFoundError(f"Data root does not exist: {data_root}")

    records = [
        classify_record(
            path=path,
            data_root=data_root,
            repo_root=repo_root,
            pdf_sample_pages=args.pdf_sample_pages,
            pdf_timeout_seconds=args.pdf_timeout_seconds,
        )
        for path in iter_source_files(data_root)
    ]

    write_jsonl(records, args.output)
    summary = build_summary(records)
    write_summary(summary, args.summary_output)

    print(f"Wrote manifest: {args.output}")
    print(f"Wrote summary: {args.summary_output}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
