"""Chunk loaded course documents for retrieval and parent-context generation.

Day05 keeps the loader/chunker boundary simple:

``LoadedDocument -> ParentDocument -> ChunkedDocument``

Small child chunks are intended for vector retrieval. Parent documents keep a
larger, traceable context unit for generation after retrieval. For Markdown-like
documents this parent unit is a heading section; for PDF text-layer documents it
is the page-level ``LoadedDocument`` emitted by the loader.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

try:  # Package import when used from application code.
    from .loaders import (
        DEFAULT_MANIFEST_PATH,
        LoadedDocument,
        load_documents,
        parse_strategy_arg,
    )
except ImportError:  # Script import when run as python course_rag/app/rag/chunking.py.
    from loaders import (  # type: ignore
        DEFAULT_MANIFEST_PATH,
        LoadedDocument,
        load_documents,
        parse_strategy_arg,
    )

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


logger = logging.getLogger(__name__)

DEFAULT_HEADERS_TO_SPLIT_ON = (
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
    ("####", "Header 4"),
)
DEFAULT_RECURSIVE_SEPARATORS = (
    "\n\n",
    "\n",
    "。",  # Chinese sentence boundary.
    "！",
    "？",
    "；",
    "，",
    ". ",
    "! ",
    "? ",
    "; ",
    ", ",
    " ",
    "",
)
MARKDOWN_FILE_TYPES = {"md", "markdown", "docx", "pptx"}
PAGE_HEADING_PATTERN = re.compile(
    r"(?:<!--\s*page:\s*(?P<comment_page>\d+)\s*-->\s*)?"
    r"(?P<header>##\s+Page\s+(?P<header_page>\d+)\s*)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ChunkingConfig:
    """Configuration for parent/child chunking."""

    chunk_size: int = 500
    chunk_overlap: int = 80
    use_parent_context: bool = True
    headers_to_split_on: tuple[tuple[str, str], ...] = DEFAULT_HEADERS_TO_SPLIT_ON
    recursive_separators: tuple[str, ...] = DEFAULT_RECURSIVE_SEPARATORS

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if self.chunk_overlap < 0:
            raise ValueError("chunk_overlap must be non-negative")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")


@dataclass
class ParentDocument:
    """Larger context unit used after retrieval."""

    page_content: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"page_content": self.page_content, "metadata": self.metadata}


@dataclass
class ChunkedDocument:
    """Small retrieval unit with traceable parent metadata."""

    page_content: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"page_content": self.page_content, "metadata": self.metadata}


@dataclass
class ChunkingResult:
    """Complete chunking output for indexing and generation."""

    chunks: list[ChunkedDocument]
    parents: list[ParentDocument]
    parent_child_map: dict[str, str]
    stats: dict[str, Any]
    config: ChunkingConfig

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "parents": [parent.to_dict() for parent in self.parents],
            "parent_child_map": self.parent_child_map,
            "stats": self.stats,
            "config": asdict(self.config),
        }


def chunk_documents(
    documents: Iterable[LoadedDocument],
    config: ChunkingConfig | None = None,
) -> ChunkingResult:
    """Chunk loader output into retrieval chunks plus parent context documents."""

    selected_config = config or ChunkingConfig()
    recursive_splitter = build_recursive_splitter(selected_config)

    chunks: list[ChunkedDocument] = []
    parents: list[ParentDocument] = []
    parent_child_map: dict[str, str] = {}

    global_chunk_index = 0
    for document_index, document in enumerate(documents):
        source_parents = build_parent_documents(
            document=document,
            document_index=document_index,
            config=selected_config,
        )

        for parent in source_parents:
            parents.append(parent)
            child_texts = split_child_text(parent.page_content, recursive_splitter)
            for chunk_in_parent_index, child_text in enumerate(child_texts):
                child_metadata = build_child_metadata(
                    parent_metadata=parent.metadata,
                    child_text=child_text,
                    global_chunk_index=global_chunk_index,
                    chunk_in_parent_index=chunk_in_parent_index,
                    config=selected_config,
                )
                chunk = ChunkedDocument(
                    page_content=child_text,
                    metadata=child_metadata,
                )
                chunks.append(chunk)
                parent_child_map[child_metadata["chunk_id"]] = child_metadata[
                    "parent_doc_id"
                ]
                global_chunk_index += 1

    stats = summarize_chunks(chunks, parents, parent_child_map)
    return ChunkingResult(
        chunks=chunks,
        parents=parents,
        parent_child_map=parent_child_map,
        stats=stats,
        config=selected_config,
    )


def build_parent_documents(
    document: LoadedDocument,
    document_index: int,
    config: ChunkingConfig,
) -> list[ParentDocument]:
    """Build generation-context parent nodes from one loaded document."""

    text = normalize_chunk_text(document.page_content)
    if not text:
        return []

    metadata = dict(document.metadata)
    if should_split_as_markdown(metadata):
        return build_markdown_parent_documents(text, metadata, document_index, config)

    page_marked_parents = build_page_marked_parent_documents(text, metadata, document_index)
    if page_marked_parents:
        return page_marked_parents

    return [
        build_parent_document(
            text=text,
            source_metadata=metadata,
            document_index=document_index,
            parent_index=0,
            parent_source_type="loaded_document",
            section_path=derive_default_section_path(metadata),
        )
    ]


def should_split_as_markdown(metadata: dict[str, Any]) -> bool:
    file_type = str(metadata.get("file_type", "")).lower()
    strategy = str(metadata.get("parse_strategy", "")).lower()
    loader = str(metadata.get("loader", "")).lower()
    if strategy == "markdown_native":
        return True
    if file_type in MARKDOWN_FILE_TYPES and strategy == "docling_document":
        return True
    return file_type in MARKDOWN_FILE_TYPES and loader in {"native_markdown", "docling"}


def build_markdown_parent_documents(
    text: str,
    metadata: dict[str, Any],
    document_index: int,
    config: ChunkingConfig,
) -> list[ParentDocument]:
    markdown_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=list(config.headers_to_split_on),
        strip_headers=False,
    )

    try:
        markdown_sections = markdown_splitter.split_text(text)
    except Exception as exc:  # noqa: BLE001 - fallback keeps the corpus usable.
        logger.warning("Markdown header split failed for %s: %s", metadata.get("source"), exc)
        markdown_sections = []

    parents: list[ParentDocument] = []
    if not markdown_sections:
        return [
            build_parent_document(
                text=text,
                source_metadata=metadata,
                document_index=document_index,
                parent_index=0,
                parent_source_type="markdown_fallback",
                section_path=derive_default_section_path(metadata),
            )
        ]

    for parent_index, section in enumerate(markdown_sections):
        parent_text = normalize_chunk_text(section.page_content)
        if not parent_text:
            continue
        section_metadata = dict(metadata)
        section_metadata.update(section.metadata)
        parents.append(
            build_parent_document(
                text=parent_text,
                source_metadata=section_metadata,
                document_index=document_index,
                parent_index=parent_index,
                parent_source_type="markdown_section",
                section_path=derive_section_path(section_metadata),
            )
        )

    if parents:
        return parents

    return [
        build_parent_document(
            text=text,
            source_metadata=metadata,
            document_index=document_index,
            parent_index=0,
            parent_source_type="markdown_fallback",
            section_path=derive_default_section_path(metadata),
        )
    ]


def build_page_marked_parent_documents(
    text: str,
    metadata: dict[str, Any],
    document_index: int,
) -> list[ParentDocument]:
    """Split PDF markdown caches that contain explicit Page headings."""

    if str(metadata.get("file_type", "")).lower() != "pdf":
        return []
    if metadata.get("page") is not None:
        return []

    matches = list(PAGE_HEADING_PATTERN.finditer(text))
    if not matches:
        return []

    parents: list[ParentDocument] = []
    for parent_index, match in enumerate(matches):
        start = match.start()
        end = matches[parent_index + 1].start() if parent_index + 1 < len(matches) else len(text)
        page_text = normalize_chunk_text(text[start:end])
        if not page_text:
            continue

        page = match.group("comment_page") or match.group("header_page")
        page_metadata = dict(metadata)
        page_metadata["page"] = int(page)
        parents.append(
            build_parent_document(
                text=page_text,
                source_metadata=page_metadata,
                document_index=document_index,
                parent_index=parent_index,
                parent_source_type="pdf_markdown_page",
                section_path=(f"Page {page}",),
            )
        )

    return parents


def build_parent_document(
    text: str,
    source_metadata: dict[str, Any],
    document_index: int,
    parent_index: int,
    parent_source_type: str,
    section_path: tuple[str, ...],
) -> ParentDocument:
    source_doc_id = source_metadata.get("doc_id") or stable_hash(
        {"source": source_metadata.get("source"), "document_index": document_index}
    )
    section = section_path[-1] if section_path else source_metadata.get("section")
    parent_id = stable_hash(
        {
            "kind": "parent",
            "source_doc_id": source_doc_id,
            "source": source_metadata.get("source"),
            "page": source_metadata.get("page"),
            "parent_index": parent_index,
            "section_path": list(section_path),
            "content": text,
        }
    )

    parent_metadata = dict(source_metadata)
    parent_metadata.update(
        {
            "doc_type": "parent",
            "source_doc_id": source_doc_id,
            "parent_doc_id": parent_id,
            "parent_index": parent_index,
            "parent_source_type": parent_source_type,
            "section": section,
            "section_path": " > ".join(section_path),
            "text_length": len(text),
        }
    )
    return ParentDocument(page_content=text, metadata=parent_metadata)


def build_recursive_splitter(config: ChunkingConfig) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separators=list(config.recursive_separators),
        length_function=len,
        keep_separator=True,
    )


def split_child_text(
    parent_text: str,
    recursive_splitter: RecursiveCharacterTextSplitter,
) -> list[str]:
    pieces = [
        normalize_chunk_text(piece)
        for piece in recursive_splitter.split_text(parent_text)
    ]
    return [piece for piece in pieces if piece]


def build_child_metadata(
    parent_metadata: dict[str, Any],
    child_text: str,
    global_chunk_index: int,
    chunk_in_parent_index: int,
    config: ChunkingConfig,
) -> dict[str, Any]:
    chunk_id = stable_hash(
        {
            "kind": "child",
            "parent_doc_id": parent_metadata["parent_doc_id"],
            "chunk_in_parent_index": chunk_in_parent_index,
            "chunk_size": config.chunk_size,
            "chunk_overlap": config.chunk_overlap,
            "content": child_text,
        }
    )
    metadata = dict(parent_metadata)
    metadata.update(
        {
            "doc_type": "child",
            "chunk_id": chunk_id,
            "chunk_index": global_chunk_index,
            "chunk_in_parent_index": chunk_in_parent_index,
            "chunk_size": len(child_text),
            "chunk_size_target": config.chunk_size,
            "chunk_overlap": config.chunk_overlap,
            "chunk_strategy": "parent_recursive_character",
            "generation_context": "parent"
            if config.use_parent_context
            else "chunk",
        }
    )
    return metadata


def resolve_generation_contexts(
    result: ChunkingResult,
    retrieved_chunks: Iterable[ChunkedDocument],
    use_parent_context: bool | None = None,
) -> list[ParentDocument | ChunkedDocument]:
    """Return parent contexts or raw chunks for retrieved child chunks."""

    should_use_parent = (
        result.config.use_parent_context if use_parent_context is None else use_parent_context
    )
    if not should_use_parent:
        return list(retrieved_chunks)

    parent_by_id = {
        parent.metadata.get("parent_doc_id"): parent
        for parent in result.parents
    }
    contexts: list[ParentDocument | ChunkedDocument] = []
    seen_parent_ids: set[str] = set()
    for chunk in retrieved_chunks:
        parent_id = chunk.metadata.get("parent_doc_id")
        if not parent_id or parent_id in seen_parent_ids:
            continue
        parent = parent_by_id.get(parent_id)
        if parent is not None:
            contexts.append(parent)
            seen_parent_ids.add(parent_id)
    return contexts


def summarize_chunks(
    chunks: list[ChunkedDocument],
    parents: list[ParentDocument],
    parent_child_map: dict[str, str],
) -> dict[str, Any]:
    lengths = [len(chunk.page_content) for chunk in chunks]
    by_source = Counter(
        str(chunk.metadata.get("source", "unknown"))
        for chunk in chunks
    )
    by_file_type = Counter(
        str(chunk.metadata.get("file_type", "unknown"))
        for chunk in chunks
    )
    by_parent_source_type = Counter(
        str(parent.metadata.get("parent_source_type", "unknown"))
        for parent in parents
    )

    return {
        "chunks": len(chunks),
        "parents": len(parents),
        "parent_child_mappings": len(parent_child_map),
        "source_files": len({chunk.metadata.get("source") for chunk in chunks}),
        "total_chars": sum(lengths),
        "avg_chars": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "max_chars": max(lengths) if lengths else 0,
        "min_chars": min(lengths) if lengths else 0,
        "longest_chunk": summarize_one_chunk(max(chunks, key=lambda item: len(item.page_content)))
        if chunks
        else None,
        "shortest_chunk": summarize_one_chunk(min(chunks, key=lambda item: len(item.page_content)))
        if chunks
        else None,
        "chunks_by_source": dict(sorted(by_source.items())),
        "chunks_by_file_type": dict(sorted(by_file_type.items())),
        "parents_by_source_type": dict(sorted(by_parent_source_type.items())),
    }


def summarize_one_chunk(chunk: ChunkedDocument) -> dict[str, Any]:
    return {
        "chunk_id": chunk.metadata.get("chunk_id"),
        "parent_doc_id": chunk.metadata.get("parent_doc_id"),
        "source": chunk.metadata.get("source"),
        "page": chunk.metadata.get("page"),
        "section": chunk.metadata.get("section"),
        "chars": len(chunk.page_content),
    }


def derive_section_path(metadata: dict[str, Any]) -> tuple[str, ...]:
    headers = [
        str(metadata[key]).strip()
        for _, key in DEFAULT_HEADERS_TO_SPLIT_ON
        if metadata.get(key)
    ]
    if headers:
        return tuple(headers)
    return derive_default_section_path(metadata)


def derive_default_section_path(metadata: dict[str, Any]) -> tuple[str, ...]:
    if metadata.get("section"):
        return (str(metadata["section"]),)
    if metadata.get("page") is not None:
        return (f"Page {metadata['page']}",)
    if metadata.get("source_stem"):
        return (str(metadata["source_stem"]),)
    if metadata.get("source_name"):
        return (str(metadata["source_name"]),)
    return ("document",)


def normalize_chunk_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def stable_hash(payload: Any, length: int = 16) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:length]


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
        help="Parsing backend passed through to loaders.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional manifest record limit for smoke tests.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Target child chunk size in characters.",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=80,
        help="Character overlap between adjacent child chunks.",
    )
    parser.add_argument(
        "--no-parent-context",
        action="store_true",
        help="Resolve generation contexts to child chunks instead of parents.",
    )
    parser.add_argument(
        "--preview",
        type=int,
        default=5,
        help="Number of chunks to preview.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory to write chunk stats, chunks, parents, and parent-child map.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail fast on individual loader errors.",
    )
    return parser.parse_args()


def main() -> None:
    configure_stdio()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    documents = load_documents(
        manifest_path=args.manifest,
        priority=args.priority,
        strategies=parse_strategy_arg(args.strategies),
        limit=args.limit,
        backend=args.backend,
        strict=args.strict,
    )
    config = ChunkingConfig(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        use_parent_context=not args.no_parent_context,
    )
    result = chunk_documents(documents, config=config)
    print(json.dumps(result.stats, ensure_ascii=False, indent=2))

    if args.output_dir is not None:
        write_chunking_outputs(result, args.output_dir)
        print(f"Wrote chunking outputs: {args.output_dir}")

    for chunk in result.chunks[: args.preview]:
        preview = chunk.page_content[:180].replace("\n", "\\n")
        print(
            json.dumps(
                {
                    "chunk_id": chunk.metadata.get("chunk_id"),
                    "parent_doc_id": chunk.metadata.get("parent_doc_id"),
                    "source": chunk.metadata.get("source"),
                    "page": chunk.metadata.get("page"),
                    "section": chunk.metadata.get("section"),
                    "section_path": chunk.metadata.get("section_path"),
                    "chars": len(chunk.page_content),
                    "generation_context": chunk.metadata.get("generation_context"),
                    "preview": preview,
                },
                ensure_ascii=False,
            )
        )


def write_chunking_outputs(result: ChunkingResult, output_dir: Path) -> None:
    """Write JSON/JSONL artifacts for Day05 inspection and debugging."""

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "chunk_stats.json", result.stats)
    write_json(output_dir / "parent_child_map.json", result.parent_child_map)
    write_jsonl(output_dir / "chunks.jsonl", (chunk.to_dict() for chunk in result.chunks))
    write_jsonl(output_dir / "parents.jsonl", (parent.to_dict() for parent in result.parents))
    write_json(output_dir / "chunking_config.json", asdict(result.config))


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    main()
