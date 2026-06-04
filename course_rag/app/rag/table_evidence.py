"""Offline table evidence builders for Course RAG V2."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    from .evidence import (
        EvidenceDocument,
        evidence_id_payload,
        source_name_from_source,
        stable_hash,
        write_evidence_jsonl,
    )
    from .loaders import LoadedDocument
except ImportError:
    from evidence import (  # type: ignore
        EvidenceDocument,
        evidence_id_payload,
        source_name_from_source,
        stable_hash,
        write_evidence_jsonl,
    )
    from loaders import LoadedDocument  # type: ignore


DEFAULT_TABLE_EVIDENCE_CACHE_PATH = Path("course_rag/data/processed/evidence_table.jsonl")
DEFAULT_TABLE_PIPELINE_VERSION = "table_evidence_v1"
DEFAULT_MAX_TABLE_ROWS_PER_EVIDENCE = 20

TABLE_MODALITY = "table"
TABLE_MARKDOWN_KIND = "table_markdown"
DOCLING_TABLE_BACKEND = "docling_table"
TEXT_TABLE_BACKEND = "text_table_heuristic"

MARKDOWN_TABLE_SEPARATOR_PATTERN = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
ALIGNED_TABLE_SPLIT_PATTERN = re.compile(r"\s{2,}")


@dataclass(frozen=True)
class TableEvidenceConfig:
    """Configuration for table evidence extraction."""

    repo_root: Path = Path.cwd()
    cache_path: Path = DEFAULT_TABLE_EVIDENCE_CACHE_PATH
    pipeline_version: str = DEFAULT_TABLE_PIPELINE_VERSION
    max_rows_per_evidence: int = DEFAULT_MAX_TABLE_ROWS_PER_EVIDENCE
    include_docling_tables: bool = True
    include_text_heuristic: bool = True
    write_cache: bool = True


@dataclass
class TableEvidenceResult:
    """Table evidence rows plus diagnostics for index metadata."""

    evidence_documents: list[EvidenceDocument]
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TextTableBlock:
    """One table-like text span extracted from a loaded document."""

    rows: list[list[str]]
    start_line: int
    end_line: int
    context_before: str | None
    context_after: str | None


def build_table_evidence(
    documents: Iterable[LoadedDocument],
    *,
    config: TableEvidenceConfig | None = None,
) -> TableEvidenceResult:
    """Extract table evidence from Docling JSON first, then text fallbacks."""

    selected_config = config or TableEvidenceConfig()
    materialized_documents = list(documents)
    evidence: list[EvidenceDocument] = []
    docling_table_keys: set[tuple[str | None, int | str | None]] = set()

    if selected_config.include_docling_tables:
        docling_evidence = build_docling_table_evidence(
            materialized_documents,
            config=selected_config,
        )
        evidence.extend(docling_evidence)
        docling_table_keys = {
            table_source_key(item.metadata)
            for item in docling_evidence
        }

    if selected_config.include_text_heuristic:
        evidence.extend(
            build_text_table_evidence(
                materialized_documents,
                config=selected_config,
                skip_source_keys=docling_table_keys,
            )
        )

    deduped = dedupe_evidence_by_id(evidence)
    if selected_config.write_cache:
        write_evidence_jsonl(
            resolve_repo_path(selected_config.cache_path, selected_config.repo_root),
            deduped,
        )

    return TableEvidenceResult(
        evidence_documents=deduped,
        stats=summarize_table_evidence(deduped),
    )


def build_docling_table_evidence(
    documents: Iterable[LoadedDocument],
    *,
    config: TableEvidenceConfig,
) -> list[EvidenceDocument]:
    evidence: list[EvidenceDocument] = []
    for document in documents:
        metadata = document.metadata
        parsed_json_path = metadata.get("parsed_json_path")
        if not parsed_json_path:
            continue
        json_path = resolve_repo_path(Path(str(parsed_json_path)), config.repo_root)
        if not json_path.exists():
            continue
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for table_index, table in enumerate(payload.get("tables") or []):
            rows = normalize_table_rows(table_rows_from_docling_table(table))
            if not valid_table_rows(rows):
                continue
            page = table_page(table) or metadata.get("page")
            for chunk_index, chunk_rows in enumerate(
                split_table_rows(rows, max_rows=config.max_rows_per_evidence)
            ):
                table_metadata = build_table_metadata(
                    metadata,
                    page=page,
                    table_index=table_index,
                    table_chunk_index=chunk_index,
                    table_rows=len(rows),
                    table_cols=max_column_count(rows),
                    parser_backend=DOCLING_TABLE_BACKEND,
                    pipeline_version=config.pipeline_version,
                    context_before=None,
                    context_after=None,
                )
                page_content = format_table_evidence_content(table_metadata, chunk_rows)
                table_metadata["text_length"] = len(page_content)
                table_metadata["source_hash"] = stable_hash(
                    {
                        "source": table_metadata.get("source"),
                        "page": page,
                        "table_index": table_index,
                        "table_chunk_index": chunk_index,
                    }
                )
                table_metadata["evidence_id"] = table_evidence_id(table_metadata)
                evidence.append(EvidenceDocument(page_content=page_content, metadata=table_metadata))
    return evidence


def build_text_table_evidence(
    documents: Iterable[LoadedDocument],
    *,
    config: TableEvidenceConfig,
    skip_source_keys: set[tuple[str | None, int | str | None]],
) -> list[EvidenceDocument]:
    evidence: list[EvidenceDocument] = []
    for document in documents:
        metadata = document.metadata
        if table_source_key(metadata) in skip_source_keys:
            continue
        blocks = extract_text_table_blocks(document.page_content)
        for table_index, block in enumerate(blocks):
            rows = normalize_table_rows(block.rows)
            if not valid_table_rows(rows):
                continue
            for chunk_index, chunk_rows in enumerate(
                split_table_rows(rows, max_rows=config.max_rows_per_evidence)
            ):
                table_metadata = build_table_metadata(
                    metadata,
                    page=metadata.get("page"),
                    table_index=table_index,
                    table_chunk_index=chunk_index,
                    table_rows=len(rows),
                    table_cols=max_column_count(rows),
                    parser_backend=TEXT_TABLE_BACKEND,
                    pipeline_version=config.pipeline_version,
                    context_before=block.context_before,
                    context_after=block.context_after,
                )
                table_metadata.update(
                    {
                        "table_start_line": block.start_line,
                        "table_end_line": block.end_line,
                    }
                )
                page_content = format_table_evidence_content(table_metadata, chunk_rows)
                table_metadata["text_length"] = len(page_content)
                table_metadata["source_hash"] = stable_hash(
                    {
                        "source": table_metadata.get("source"),
                        "page": table_metadata.get("page"),
                        "table_index": table_index,
                        "table_chunk_index": chunk_index,
                        "start_line": block.start_line,
                    }
                )
                table_metadata["evidence_id"] = table_evidence_id(table_metadata)
                evidence.append(EvidenceDocument(page_content=page_content, metadata=table_metadata))
    return evidence


def table_rows_from_docling_table(table: dict[str, Any]) -> list[list[str]]:
    data = table.get("data") or {}
    grid = data.get("grid") or []
    if grid:
        return [
            [cell_text(cell) for cell in row]
            for row in grid
            if isinstance(row, list)
        ]

    cells = data.get("table_cells") or []
    if not cells:
        return []
    num_rows = int(data.get("num_rows") or 0)
    num_cols = int(data.get("num_cols") or 0)
    for cell in cells:
        num_rows = max(num_rows, int(cell.get("end_row_offset_idx") or 0))
        num_cols = max(num_cols, int(cell.get("end_col_offset_idx") or 0))
    if num_rows <= 0 or num_cols <= 0:
        return []

    rows = [["" for _ in range(num_cols)] for _ in range(num_rows)]
    for cell in cells:
        row_index = int(cell.get("start_row_offset_idx") or 0)
        col_index = int(cell.get("start_col_offset_idx") or 0)
        if 0 <= row_index < num_rows and 0 <= col_index < num_cols:
            rows[row_index][col_index] = cell_text(cell)
    return rows


def cell_text(cell: Any) -> str:
    if cell is None:
        return ""
    if isinstance(cell, dict):
        value = cell.get("text", "")
    else:
        value = str(cell)
    return clean_cell_text(value)


def table_page(table: dict[str, Any]) -> int | None:
    for provenance in table.get("prov") or []:
        page = provenance.get("page_no")
        if page not in {None, ""}:
            try:
                return int(page)
            except (TypeError, ValueError):
                return None
    return None


def extract_text_table_blocks(text: str) -> list[TextTableBlock]:
    lines = text.splitlines()
    blocks: list[TextTableBlock] = []
    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        if is_markdown_table_line(line):
            start = line_index
            table_lines: list[str] = []
            while line_index < len(lines) and is_markdown_table_line(lines[line_index]):
                table_lines.append(lines[line_index])
                line_index += 1
            rows = parse_markdown_table_lines(table_lines)
            if valid_table_rows(rows):
                blocks.append(
                    TextTableBlock(
                        rows=rows,
                        start_line=start + 1,
                        end_line=line_index,
                        context_before=context_before_line(lines, start),
                        context_after=context_after_line(lines, line_index),
                    )
                )
            continue

        if is_aligned_table_line(line):
            start = line_index
            table_lines = []
            while line_index < len(lines) and is_aligned_table_line(lines[line_index]):
                table_lines.append(lines[line_index])
                line_index += 1
            rows = parse_aligned_table_lines(table_lines)
            if valid_table_rows(rows):
                blocks.append(
                    TextTableBlock(
                        rows=rows,
                        start_line=start + 1,
                        end_line=line_index,
                        context_before=context_before_line(lines, start),
                        context_after=context_after_line(lines, line_index),
                    )
                )
            continue

        line_index += 1
    return blocks


def is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    if "|" not in stripped:
        return False
    cells = split_markdown_table_line(stripped)
    return len(cells) >= 2 and any(cells)


def parse_markdown_table_lines(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        if MARKDOWN_TABLE_SEPARATOR_PATTERN.match(line):
            continue
        cells = split_markdown_table_line(line)
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def split_markdown_table_line(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [clean_cell_text(cell) for cell in stripped.split("|")]


def is_aligned_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    columns = ALIGNED_TABLE_SPLIT_PATTERN.split(stripped)
    if len(columns) < 2:
        return False
    return sum(1 for column in columns if clean_cell_text(column)) >= 2


def parse_aligned_table_lines(lines: list[str]) -> list[list[str]]:
    return [
        [clean_cell_text(cell) for cell in ALIGNED_TABLE_SPLIT_PATTERN.split(line.strip())]
        for line in lines
    ]


def normalize_table_rows(rows: list[list[str]]) -> list[list[str]]:
    normalized = [[clean_cell_text(cell) for cell in row] for row in rows]
    normalized = [row for row in normalized if any(cell for cell in row)]
    if not normalized:
        return []

    max_cols = max(len(row) for row in normalized)
    padded = [row + [""] * (max_cols - len(row)) for row in normalized]
    keep_cols = [
        col_index
        for col_index in range(max_cols)
        if any(row[col_index] for row in padded)
    ]
    if not keep_cols:
        return []
    return [[row[col_index] for col_index in keep_cols] for row in padded]


def valid_table_rows(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return False
    if max_column_count(rows) < 2:
        return False
    non_empty_cells = sum(1 for row in rows for cell in row if cell)
    non_empty_rows = sum(1 for row in rows if any(row))
    return non_empty_cells >= 4 and non_empty_rows >= 2


def split_table_rows(rows: list[list[str]], *, max_rows: int) -> Iterable[list[list[str]]]:
    if len(rows) <= max_rows:
        yield rows
        return

    chunk_size = max(1, max_rows - 1)
    header = rows[0]
    for start in range(1, len(rows), chunk_size):
        yield [header, *rows[start : start + chunk_size]]


def build_table_metadata(
    source_metadata: dict[str, Any],
    *,
    page: int | str | None,
    table_index: int,
    table_chunk_index: int,
    table_rows: int,
    table_cols: int,
    parser_backend: str,
    pipeline_version: str,
    context_before: str | None,
    context_after: str | None,
) -> dict[str, Any]:
    metadata = dict(source_metadata)
    source = metadata.get("source")
    metadata.setdefault("source_doc_id", metadata.get("doc_id") or stable_hash({"source": source}))
    metadata.setdefault("source_name", source_name_from_source(source))
    metadata.update(
        {
            "page": page,
            "asset_path": None,
            "modality": TABLE_MODALITY,
            "evidence_kind": TABLE_MARKDOWN_KIND,
            "parser_backend": parser_backend,
            "pipeline_version": pipeline_version,
            "context_before": context_before,
            "context_after": context_after,
            "table_index": table_index,
            "table_chunk_index": table_chunk_index,
            "table_rows": table_rows,
            "table_cols": table_cols,
            "table_max_rows_per_evidence": DEFAULT_MAX_TABLE_ROWS_PER_EVIDENCE,
        }
    )
    return metadata


def format_table_evidence_content(metadata: dict[str, Any], rows: list[list[str]]) -> str:
    parts = [
        "表格证据",
        f"文件：{metadata.get('source_name')}",
    ]
    if metadata.get("page") not in {None, ""}:
        parts.append(f"页码：{metadata.get('page')}")
    if metadata.get("section_path"):
        parts.append(f"章节：{metadata.get('section_path')}")
    parts.append(
        f"表格序号：{metadata.get('table_index')}，切片：{metadata.get('table_chunk_index')}"
    )
    parts.append(rows_to_markdown_table(rows))
    return "\n".join(part for part in parts if part).strip()


def rows_to_markdown_table(rows: list[list[str]]) -> str:
    normalized = normalize_table_rows(rows)
    if not normalized:
        return ""
    col_count = max_column_count(normalized)
    padded = [row + [""] * (col_count - len(row)) for row in normalized]
    header = [escape_markdown_cell(cell) for cell in padded[0]]
    body = [[escape_markdown_cell(cell) for cell in row] for row in padded[1:]]
    separator = ["---"] * col_count
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def table_evidence_id(metadata: dict[str, Any]) -> str:
    payload = evidence_id_payload(
        metadata=metadata,
        modality=TABLE_MODALITY,
        evidence_kind=TABLE_MARKDOWN_KIND,
    )
    payload.update(
        {
            "table_index": metadata.get("table_index"),
            "table_chunk_index": metadata.get("table_chunk_index"),
            "parser_backend": metadata.get("parser_backend"),
        }
    )
    return stable_hash(payload)


def summarize_table_evidence(evidence_documents: Iterable[EvidenceDocument]) -> dict[str, Any]:
    evidence = list(evidence_documents)
    by_backend = Counter(str(item.metadata.get("parser_backend", "unknown")) for item in evidence)
    by_course = Counter(str(item.metadata.get("course", "unknown")) for item in evidence)
    return {
        "table_evidence": len(evidence),
        "source_files": len({item.metadata.get("source") for item in evidence}),
        "total_chars": sum(len(item.page_content) for item in evidence),
        "by_parser_backend": dict(sorted(by_backend.items())),
        "by_course": dict(sorted(by_course.items())),
    }


def table_source_key(metadata: dict[str, Any]) -> tuple[str | None, int | str | None]:
    source_doc_id = metadata.get("source_doc_id") or metadata.get("doc_id")
    return (
        str(source_doc_id) if source_doc_id not in {None, ""} else None,
        metadata.get("page"),
    )


def context_before_line(lines: list[str], start: int, width: int = 320) -> str | None:
    text = "\n".join(lines[max(0, start - 4) : start]).strip()
    return trim_context(text, width)


def context_after_line(lines: list[str], end: int, width: int = 320) -> str | None:
    text = "\n".join(lines[end : min(len(lines), end + 4)]).strip()
    return trim_context(text, width)


def trim_context(text: str, width: int) -> str | None:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return None
    if len(compact) <= width:
        return compact
    return compact[:width].rstrip()


def clean_cell_text(value: Any) -> str:
    text = str(value or "").replace("\t", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|")


def max_column_count(rows: list[list[str]]) -> int:
    return max((len(row) for row in rows), default=0)


def dedupe_evidence_by_id(evidence_documents: Iterable[EvidenceDocument]) -> list[EvidenceDocument]:
    deduped: dict[str, EvidenceDocument] = {}
    for evidence in evidence_documents:
        evidence_id = str(evidence.metadata.get("evidence_id") or stable_hash(evidence.to_dict()))
        deduped.setdefault(evidence_id, evidence)
    return list(deduped.values())


def resolve_repo_path(path: Path, repo_root: Path) -> Path:
    if path.is_absolute():
        return path
    return repo_root / path


def safe_repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
