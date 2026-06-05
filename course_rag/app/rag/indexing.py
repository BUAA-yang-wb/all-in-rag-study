"""Build and load the SQLite-backed Course RAG corpus snapshot."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

try:
    from .chunking import ChunkedDocument, ChunkingConfig, ParentDocument, chunk_documents
    from .docstore import (
        DEFAULT_DOCSTORE_PATH,
        DOCSTORE_SCHEMA_VERSION,
        DocstoreSnapshot,
        has_docstore_snapshot,
        load_docstore_snapshot,
        save_docstore_snapshot,
    )
    from .evidence import (
        DEFAULT_TEXT_EVIDENCE_CACHE_PATH,
        DEFAULT_TEXT_EVIDENCE_PIPELINE_VERSION,
        EvidenceDocument,
        evidence_to_loaded_documents,
        loaded_documents_to_text_evidence,
        summarize_evidence,
        write_evidence_jsonl,
    )
    from .loaders import (
        DEFAULT_MANIFEST_PATH as LOADER_DEFAULT_MANIFEST_PATH,
        LoadedDocument,
        load_documents,
        parse_strategy_arg,
    )
    from .table_evidence import (
        DEFAULT_TABLE_EVIDENCE_CACHE_PATH,
        TableEvidenceConfig,
        build_table_evidence,
    )
    from .visual_evidence import (
        DEFAULT_CAPTION_EVIDENCE_CACHE_PATH,
        DEFAULT_CAPTION_PROVIDER,
        DEFAULT_IMAGE_EVIDENCE_CACHE_PATH,
        DEFAULT_OCR_EVIDENCE_CACHE_PATH,
        DEFAULT_OCR_PROVIDER,
        DEFAULT_PAGE_IMAGE_ROOT,
        DEFAULT_PDF_PAGE_LOW_TEXT_CHARS,
        VisualEvidenceConfig,
        build_visual_evidence,
    )
except ImportError:
    from chunking import ChunkedDocument, ChunkingConfig, ParentDocument, chunk_documents  # type: ignore
    from docstore import (  # type: ignore
        DEFAULT_DOCSTORE_PATH,
        DOCSTORE_SCHEMA_VERSION,
        DocstoreSnapshot,
        has_docstore_snapshot,
        load_docstore_snapshot,
        save_docstore_snapshot,
    )
    from evidence import (  # type: ignore
        DEFAULT_TEXT_EVIDENCE_CACHE_PATH,
        DEFAULT_TEXT_EVIDENCE_PIPELINE_VERSION,
        EvidenceDocument,
        evidence_to_loaded_documents,
        loaded_documents_to_text_evidence,
        summarize_evidence,
        write_evidence_jsonl,
    )
    from loaders import (  # type: ignore
        DEFAULT_MANIFEST_PATH as LOADER_DEFAULT_MANIFEST_PATH,
        LoadedDocument,
        load_documents,
        parse_strategy_arg,
    )
    from table_evidence import (  # type: ignore
        DEFAULT_TABLE_EVIDENCE_CACHE_PATH,
        TableEvidenceConfig,
        build_table_evidence,
    )
    from visual_evidence import (  # type: ignore
        DEFAULT_CAPTION_EVIDENCE_CACHE_PATH,
        DEFAULT_CAPTION_PROVIDER,
        DEFAULT_IMAGE_EVIDENCE_CACHE_PATH,
        DEFAULT_OCR_EVIDENCE_CACHE_PATH,
        DEFAULT_OCR_PROVIDER,
        DEFAULT_PAGE_IMAGE_ROOT,
        DEFAULT_PDF_PAGE_LOW_TEXT_CHARS,
        VisualEvidenceConfig,
        build_visual_evidence,
    )


logger = logging.getLogger(__name__)

COURSE_RAG_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = COURSE_RAG_ROOT.parent
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_COMBINED_EVIDENCE_CACHE_PATH = Path("course_rag/data/processed/evidence_v2.jsonl")


@dataclass
class CourseCorpus:
    """Freshly built corpus state before Milvus indexing."""

    source_documents: list[LoadedDocument]
    evidence_documents: list[EvidenceDocument]
    chunks: list[ChunkedDocument]
    parents: list[ParentDocument]
    parent_child_map: dict[str, str]
    metadata: dict[str, Any]
    model_name: str
    model_cache_root: Path | None = None


@dataclass
class _IndexStats:
    ntotal: int


class CourseDocstoreIndex:
    """SQLite docstore snapshot plus embedding model configuration."""

    def __init__(
        self,
        *,
        chunks: list[ChunkedDocument],
        parents: list[ParentDocument],
        parent_child_map: dict[str, str],
        metadata: dict[str, Any],
        model_name: str,
        model_cache_root: Path | None = None,
        docstore_path: Path = DEFAULT_DOCSTORE_PATH,
        counts: dict[str, int] | None = None,
    ) -> None:
        self.chunks = chunks
        self.parents = parents
        self.parent_child_map = parent_child_map
        self.metadata = metadata
        self.model_name = model_name
        self.model_cache_root = model_cache_root
        self.docstore_path = docstore_path
        self.counts = counts or {}
        self._embedding_model: Any | None = None
        self.index = _IndexStats(ntotal=len(chunks))

    @property
    def embedding_model(self) -> Any:
        if self._embedding_model is None:
            self._embedding_model = load_embedding_model(
                self.model_name,
                model_cache_root=self.model_cache_root,
            )
        return self._embedding_model


def build_or_load_docstore_index(
    *,
    docstore_path: Path = DEFAULT_DOCSTORE_PATH,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    manifest_path: Path = REPO_ROOT / LOADER_DEFAULT_MANIFEST_PATH,
    priority: str = "mvp,v2",
    strategies: str = "supported",
    backend: str = "auto",
    limit: int | None = None,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
    use_parent_context: bool = True,
    rebuild: bool = False,
    strict: bool = False,
    use_evidence: bool = True,
    evidence_cache_path: Path | None = None,
    evidence_pipeline_version: str = DEFAULT_TEXT_EVIDENCE_PIPELINE_VERSION,
    write_evidence_cache: bool = True,
    include_visual_evidence: bool = True,
    include_table_evidence: bool = True,
    combined_evidence_cache_path: Path | None = None,
    run_ocr: bool = False,
    ocr_provider: str = DEFAULT_OCR_PROVIDER,
    run_caption: bool = False,
    caption_provider: str = DEFAULT_CAPTION_PROVIDER,
    visual_limit: int | None = None,
    ocr_max_pdf_pages: int | None = None,
    pdf_page_low_text_chars: int = DEFAULT_PDF_PAGE_LOW_TEXT_CHARS,
    caption_max_items: int | None = None,
) -> CourseDocstoreIndex:
    """Load a SQLite docstore snapshot, or rebuild it from the current corpus."""

    resolved_docstore_path = resolve_path(docstore_path)
    model_cache_root = default_model_cache_root()
    if not rebuild and has_docstore_snapshot(resolved_docstore_path):
        return load_docstore_index(
            docstore_path=resolved_docstore_path,
            model_name=model_name,
            model_cache_root=model_cache_root,
        )

    corpus = build_course_corpus(
        model_name=model_name,
        manifest_path=resolve_path(manifest_path),
        priority=priority,
        strategies=strategies,
        backend=backend,
        limit=limit,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        use_parent_context=use_parent_context,
        strict=strict,
        model_cache_root=model_cache_root,
        use_evidence=use_evidence,
        evidence_cache_path=evidence_cache_path,
        evidence_pipeline_version=evidence_pipeline_version,
        write_evidence_cache=write_evidence_cache,
        include_visual_evidence=include_visual_evidence,
        include_table_evidence=include_table_evidence,
        combined_evidence_cache_path=combined_evidence_cache_path,
        run_ocr=run_ocr,
        ocr_provider=ocr_provider,
        run_caption=run_caption,
        caption_provider=caption_provider,
        visual_limit=visual_limit,
        ocr_max_pdf_pages=ocr_max_pdf_pages,
        pdf_page_low_text_chars=pdf_page_low_text_chars,
        caption_max_items=caption_max_items,
    )
    save_docstore_snapshot(
        resolved_docstore_path,
        source_documents=corpus.source_documents,
        evidence_documents=corpus.evidence_documents,
        chunks=corpus.chunks,
        parents=corpus.parents,
        parent_child_map=corpus.parent_child_map,
        metadata=corpus.metadata,
    )
    return load_docstore_index(
        docstore_path=resolved_docstore_path,
        model_name=model_name,
        model_cache_root=model_cache_root,
    )


def build_course_corpus(
    *,
    model_name: str,
    manifest_path: Path,
    priority: str,
    strategies: str,
    backend: str,
    limit: int | None,
    chunk_size: int,
    chunk_overlap: int,
    use_parent_context: bool,
    strict: bool,
    model_cache_root: Path,
    use_evidence: bool,
    evidence_cache_path: Path | None,
    evidence_pipeline_version: str,
    write_evidence_cache: bool,
    include_visual_evidence: bool,
    include_table_evidence: bool,
    combined_evidence_cache_path: Path | None,
    run_ocr: bool,
    ocr_provider: str,
    run_caption: bool,
    caption_provider: str,
    visual_limit: int | None,
    ocr_max_pdf_pages: int | None,
    pdf_page_low_text_chars: int,
    caption_max_items: int | None,
) -> CourseCorpus:
    """Build documents, evidence, parents, and chunks without writing vectors."""

    logger.info("Loading documents from manifest: %s", manifest_path)
    selected_strategies = parse_strategy_arg(strategies)
    text_strategies = set(selected_strategies)
    if include_visual_evidence:
        text_strategies.discard("docling_image")
    source_documents = load_documents(
        manifest_path=manifest_path,
        repo_root=REPO_ROOT,
        priority=priority,
        strategies=text_strategies,
        limit=limit,
        backend=backend,
        strict=strict,
        skip_low_text_pdfs=include_visual_evidence,
    )

    documents_for_chunking: list[LoadedDocument] = list(source_documents)
    evidence_documents: list[EvidenceDocument] = []
    evidence_stats: dict[str, Any] | None = None
    visual_stats: dict[str, Any] | None = None
    table_stats: dict[str, Any] | None = None
    resolved_text_evidence_cache_path: Path | None = None
    resolved_table_evidence_cache_path: Path | None = None
    resolved_combined_evidence_cache_path: Path | None = None

    if use_evidence:
        evidence_documents = loaded_documents_to_text_evidence(
            source_documents,
            pipeline_version=evidence_pipeline_version,
        )
        resolved_text_evidence_cache_path = resolve_path(
            evidence_cache_path or DEFAULT_TEXT_EVIDENCE_CACHE_PATH
        )
        if write_evidence_cache:
            write_evidence_jsonl(resolved_text_evidence_cache_path, evidence_documents)
            logger.info("Saved text evidence cache to %s", resolved_text_evidence_cache_path)

        if include_visual_evidence:
            visual_result = build_visual_evidence(
                VisualEvidenceConfig(
                    manifest_path=manifest_path,
                    repo_root=REPO_ROOT,
                    priority=priority,
                    run_ocr=run_ocr,
                    ocr_provider=ocr_provider,
                    run_caption=run_caption,
                    caption_provider=caption_provider,
                    image_cache_path=DEFAULT_IMAGE_EVIDENCE_CACHE_PATH,
                    ocr_cache_path=DEFAULT_OCR_EVIDENCE_CACHE_PATH,
                    caption_cache_path=DEFAULT_CAPTION_EVIDENCE_CACHE_PATH,
                    page_image_root=DEFAULT_PAGE_IMAGE_ROOT,
                    visual_limit=visual_limit,
                    ocr_max_pdf_pages=ocr_max_pdf_pages,
                    pdf_page_low_text_chars=pdf_page_low_text_chars,
                    caption_max_items=caption_max_items,
                    write_caches=write_evidence_cache,
                )
            )
            evidence_documents.extend(visual_result.evidence_documents)
            visual_stats = visual_result.stats

        if include_table_evidence:
            resolved_table_evidence_cache_path = resolve_path(DEFAULT_TABLE_EVIDENCE_CACHE_PATH)
            table_result = build_table_evidence(
                source_documents,
                config=TableEvidenceConfig(
                    repo_root=REPO_ROOT,
                    cache_path=DEFAULT_TABLE_EVIDENCE_CACHE_PATH,
                    write_cache=write_evidence_cache,
                ),
            )
            evidence_documents.extend(table_result.evidence_documents)
            table_stats = table_result.stats

        evidence_stats = summarize_evidence(evidence_documents)
        resolved_combined_evidence_cache_path = resolve_path(
            combined_evidence_cache_path or DEFAULT_COMBINED_EVIDENCE_CACHE_PATH
        )
        if write_evidence_cache:
            write_evidence_jsonl(resolved_combined_evidence_cache_path, evidence_documents)
            logger.info("Saved combined evidence cache to %s", resolved_combined_evidence_cache_path)
        documents_for_chunking = evidence_to_loaded_documents(evidence_documents)

    config = ChunkingConfig(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        use_parent_context=use_parent_context,
    )
    chunking_result = chunk_documents(documents_for_chunking, config=config)
    if not chunking_result.chunks:
        raise ValueError("No chunks were produced; cannot build the docstore snapshot")

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "retrieval_backend": "milvus",
        "docstore_schema_version": DOCSTORE_SCHEMA_VERSION,
        "embedding_model": model_name,
        "embedding_dimension": None,
        "similarity": "cosine_via_normalized_embeddings",
        "manifest_path": safe_repo_relative(manifest_path),
        "priority": priority,
        "strategies": strategies,
        "backend": backend,
        "limit": limit,
        "use_evidence": use_evidence,
        "include_visual_evidence": include_visual_evidence,
        "include_table_evidence": include_table_evidence,
        "run_ocr": run_ocr,
        "ocr_provider": ocr_provider if include_visual_evidence else None,
        "run_caption": run_caption,
        "caption_provider": caption_provider if include_visual_evidence else None,
        "visual_limit": visual_limit,
        "ocr_max_pdf_pages": ocr_max_pdf_pages,
        "pdf_page_low_text_chars": pdf_page_low_text_chars if include_visual_evidence else None,
        "caption_max_items": caption_max_items,
        "evidence_cache_path": safe_repo_relative(resolved_combined_evidence_cache_path)
        if resolved_combined_evidence_cache_path is not None
        else None,
        "text_evidence_cache_path": safe_repo_relative(resolved_text_evidence_cache_path)
        if resolved_text_evidence_cache_path is not None
        else None,
        "table_evidence_cache_path": safe_repo_relative(resolved_table_evidence_cache_path)
        if resolved_table_evidence_cache_path is not None
        else None,
        "evidence_pipeline_version": evidence_pipeline_version if use_evidence else None,
        "evidence_stats": evidence_stats,
        "visual_evidence_stats": visual_stats,
        "table_evidence_stats": table_stats,
        "chunking_config": asdict(config),
        "chunk_stats": chunking_result.stats,
        "source_documents": len(source_documents),
        "evidence_documents": len(evidence_documents),
    }
    return CourseCorpus(
        source_documents=source_documents,
        evidence_documents=evidence_documents,
        chunks=chunking_result.chunks,
        parents=chunking_result.parents,
        parent_child_map=chunking_result.parent_child_map,
        metadata=metadata,
        model_name=model_name,
        model_cache_root=model_cache_root,
    )


def load_docstore_index(
    *,
    docstore_path: Path = DEFAULT_DOCSTORE_PATH,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    model_cache_root: Path | None = None,
) -> CourseDocstoreIndex:
    snapshot = load_docstore_snapshot(resolve_path(docstore_path))
    saved_model_name = snapshot.metadata.get("embedding_model")
    selected_model_name = saved_model_name or model_name or DEFAULT_EMBEDDING_MODEL
    if saved_model_name and model_name and saved_model_name != model_name:
        logger.warning(
            "Ignoring requested embedding model %s because the docstore was built "
            "with %s. Rebuild the docstore to change embedding model.",
            model_name,
            saved_model_name,
        )
    return CourseDocstoreIndex(
        chunks=snapshot.chunks,
        parents=snapshot.parents,
        parent_child_map=snapshot.parent_child_map,
        metadata=snapshot.metadata,
        model_name=selected_model_name,
        model_cache_root=model_cache_root,
        docstore_path=snapshot.docstore_path,
        counts=snapshot.counts,
    )


def has_saved_docstore(docstore_path: Path = DEFAULT_DOCSTORE_PATH) -> bool:
    return has_docstore_snapshot(resolve_path(docstore_path))


def load_embedding_model(
    model_name: str,
    *,
    model_cache_root: Path | None = None,
) -> Any:
    """Load the sentence-transformers embedding model with local cache paths."""

    if model_cache_root is not None:
        configure_model_cache(model_cache_root)
    logger.info("Loading embedding model: %s", model_name)
    cache_folder = str(model_cache_root) if model_cache_root is not None else None
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device="cpu", cache_folder=cache_folder)


def encode_texts(
    model: Any,
    texts: list[str],
    *,
    batch_size: int,
    show_progress_bar: bool,
) -> np.ndarray:
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=show_progress_bar,
    )
    return np.ascontiguousarray(embeddings.astype("float32"))


def summarize_chunk_source(chunk: ChunkedDocument) -> dict[str, Any]:
    metadata = chunk.metadata
    return {
        "evidence_id": metadata.get("evidence_id"),
        "source_doc_id": metadata.get("source_doc_id"),
        "modality": metadata.get("modality"),
        "evidence_kind": metadata.get("evidence_kind"),
        "asset_path": metadata.get("asset_path"),
        "parser_backend": metadata.get("parser_backend"),
        "source": metadata.get("source"),
        "source_name": metadata.get("source_name"),
        "course": metadata.get("course"),
        "category": metadata.get("category"),
        "page": metadata.get("page"),
        "section": metadata.get("section"),
        "section_path": metadata.get("section_path"),
        "chunk_id": metadata.get("chunk_id"),
        "parent_doc_id": metadata.get("parent_doc_id"),
    }


def format_search_results(results: Iterable[dict[str, Any]]) -> str:
    lines: list[str] = []
    for result in results:
        source = result["source"]
        location_parts = [
            str(value)
            for value in (source.get("page"), source.get("section_path") or source.get("section"))
            if value not in {None, ""}
        ]
        location = f" | {' / '.join(location_parts)}" if location_parts else ""
        lines.append(
            f"[{result['rank']}] score={result['score']:.4f} "
            f"{source.get('source')}{location}\n"
            f"    {result['preview']}"
        )
    return "\n".join(lines)


def summarize_docstore_index(index: CourseDocstoreIndex) -> dict[str, Any]:
    stats = index.metadata.get("chunk_stats") or {}
    return {
        "docstore_path": safe_path(index.docstore_path),
        "backend": "milvus",
        "vectors": index.index.ntotal,
        "embedding_model": index.metadata.get("embedding_model"),
        "embedding_dimension": index.metadata.get("embedding_dimension"),
        "documents": index.counts.get("documents"),
        "evidence_count": index.counts.get("evidence"),
        "chunks": index.counts.get("chunks", len(index.chunks)),
        "parents": index.counts.get("parents", len(index.parents)),
        "chunk_parent_mappings": index.counts.get("chunk_parent_mappings"),
        "use_evidence": index.metadata.get("use_evidence", False),
        "include_visual_evidence": index.metadata.get("include_visual_evidence", False),
        "include_table_evidence": index.metadata.get("include_table_evidence", False),
        "evidence_cache_path": index.metadata.get("evidence_cache_path"),
        "evidence_pipeline_version": index.metadata.get("evidence_pipeline_version"),
        "visual_evidence_stats": index.metadata.get("visual_evidence_stats"),
        "table_evidence_stats": index.metadata.get("table_evidence_stats"),
        "source_files": stats.get("source_files"),
        "avg_chunk_chars": stats.get("avg_chars"),
        "chunks_by_file_type": stats.get("chunks_by_file_type"),
    }


def preview_text(text: str, max_chars: int = 220) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def safe_repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def safe_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def default_model_cache_root() -> Path:
    return COURSE_RAG_ROOT / "data" / "processed" / "model_cache" / "huggingface"


def configure_model_cache(model_cache_root: Path) -> None:
    hub_cache = model_cache_root / "hub"
    hub_cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(model_cache_root)
    os.environ["HF_HUB_CACHE"] = str(hub_cache)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(hub_cache)
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(model_cache_root)
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the SQLite docstore.")
    parser.add_argument("--docstore-path", type=Path, default=DEFAULT_DOCSTORE_PATH)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / LOADER_DEFAULT_MANIFEST_PATH)
    parser.add_argument("--priority", default="mvp,v2")
    parser.add_argument("--strategies", default="supported")
    parser.add_argument("--backend", choices=["auto", "docling", "basic"], default="auto")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--chunk-overlap", type=int, default=80)
    parser.add_argument("--no-parent-context", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--no-evidence",
        action="store_true",
        help="Bypass the V2 text evidence layer when rebuilding a legacy text corpus.",
    )
    parser.add_argument("--evidence-cache", type=Path, default=DEFAULT_TEXT_EVIDENCE_CACHE_PATH)
    parser.add_argument("--evidence-pipeline-version", default=DEFAULT_TEXT_EVIDENCE_PIPELINE_VERSION)
    parser.add_argument("--no-evidence-cache", action="store_true")
    parser.add_argument("--combined-evidence-cache", type=Path, default=DEFAULT_COMBINED_EVIDENCE_CACHE_PATH)
    parser.add_argument("--no-visual-evidence", action="store_true")
    parser.add_argument("--no-table-evidence", action="store_true")
    parser.add_argument("--run-ocr", action="store_true")
    parser.add_argument("--ocr-provider", default=DEFAULT_OCR_PROVIDER)
    parser.add_argument("--run-caption", action="store_true")
    parser.add_argument("--caption-provider", default=DEFAULT_CAPTION_PROVIDER)
    parser.add_argument("--visual-limit", type=int, default=None)
    parser.add_argument("--ocr-max-pdf-pages", type=int, default=None)
    parser.add_argument("--pdf-page-low-text-chars", type=int, default=DEFAULT_PDF_PAGE_LOW_TEXT_CHARS)
    parser.add_argument("--caption-max-items", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    configure_stdio()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    index = build_or_load_docstore_index(
        docstore_path=args.docstore_path,
        model_name=args.model,
        manifest_path=args.manifest,
        priority=args.priority,
        strategies=args.strategies,
        backend=args.backend,
        limit=args.limit,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        use_parent_context=not args.no_parent_context,
        rebuild=args.rebuild,
        strict=args.strict,
        use_evidence=not args.no_evidence,
        evidence_cache_path=args.evidence_cache,
        evidence_pipeline_version=args.evidence_pipeline_version,
        write_evidence_cache=not args.no_evidence_cache,
        include_visual_evidence=not args.no_visual_evidence,
        include_table_evidence=not args.no_table_evidence,
        combined_evidence_cache_path=args.combined_evidence_cache,
        run_ocr=args.run_ocr,
        ocr_provider=args.ocr_provider,
        run_caption=args.run_caption,
        caption_provider=args.caption_provider,
        visual_limit=args.visual_limit,
        ocr_max_pdf_pages=args.ocr_max_pdf_pages,
        pdf_page_low_text_chars=args.pdf_page_low_text_chars,
        caption_max_items=args.caption_max_items,
    )
    print(json.dumps(summarize_docstore_index(index), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
