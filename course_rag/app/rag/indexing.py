"""Build and query a local FAISS vector index for the course RAG corpus."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import faiss
import numpy as np

try:
    from .chunking import (
        ChunkedDocument,
        ChunkingConfig,
        ParentDocument,
        chunk_documents,
    )
    from .loaders import (
        DEFAULT_MANIFEST_PATH as LOADER_DEFAULT_MANIFEST_PATH,
        load_documents,
        parse_strategy_arg,
    )
except ImportError:
    from chunking import (  # type: ignore
        ChunkedDocument,
        ChunkingConfig,
        ParentDocument,
        chunk_documents,
    )
    from loaders import (  # type: ignore
        DEFAULT_MANIFEST_PATH as LOADER_DEFAULT_MANIFEST_PATH,
        load_documents,
        parse_strategy_arg,
    )


logger = logging.getLogger(__name__)

COURSE_RAG_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = COURSE_RAG_ROOT.parent
DEFAULT_INDEX_DIR = COURSE_RAG_ROOT / "vector_index"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
INDEX_FILE_NAME = "index.faiss"
CHUNKS_FILE_NAME = "chunks.jsonl"
PARENTS_FILE_NAME = "parents.jsonl"
PARENT_CHILD_MAP_FILE_NAME = "parent_child_map.json"
META_FILE_NAME = "index_meta.json"


class CourseVectorIndex:
    """FAISS index plus the chunk metadata needed for traceable retrieval."""

    def __init__(
        self,
        *,
        index: faiss.Index,
        chunks: list[ChunkedDocument],
        parents: list[ParentDocument],
        parent_child_map: dict[str, str],
        metadata: dict[str, Any],
        model_name: str,
        model_cache_root: Path | None = None,
    ) -> None:
        self.index = index
        self.chunks = chunks
        self.parents = parents
        self.parent_child_map = parent_child_map
        self.metadata = metadata
        self.model_name = model_name
        self.model_cache_root = model_cache_root
        self._embedding_model: Any | None = None

    @property
    def embedding_model(self) -> Any:
        if self._embedding_model is None:
            self._embedding_model = load_embedding_model(
                self.model_name,
                model_cache_root=self.model_cache_root,
            )
        return self._embedding_model

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Return Top-K chunks with FAISS scores and source metadata."""

        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not self.chunks or self.index.ntotal == 0:
            return []

        query_vector = encode_texts(
            self.embedding_model,
            [query],
            batch_size=1,
            show_progress_bar=False,
        )
        k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query_vector, k)

        results: list[dict[str, Any]] = []
        for rank, (score, index_id) in enumerate(zip(scores[0], indices[0]), 1):
            if index_id < 0:
                continue
            chunk = self.chunks[int(index_id)]
            results.append(
                {
                    "rank": rank,
                    "score": float(score),
                    "chunk": chunk.to_dict(),
                    "source": summarize_chunk_source(chunk),
                    "preview": preview_text(chunk.page_content),
                }
            )
        return results


def build_or_load_vector_index(
    *,
    index_dir: Path = DEFAULT_INDEX_DIR,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    manifest_path: Path = REPO_ROOT / LOADER_DEFAULT_MANIFEST_PATH,
    priority: str = "mvp",
    strategies: str = "supported",
    backend: str = "auto",
    limit: int | None = None,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
    use_parent_context: bool = True,
    rebuild: bool = False,
    batch_size: int = 32,
    strict: bool = False,
    show_progress_bar: bool = True,
) -> CourseVectorIndex:
    """Load an existing FAISS index or build one from the current corpus."""

    resolved_index_dir = resolve_path(index_dir)
    model_cache_root = default_model_cache_root()

    if not rebuild and has_saved_index(resolved_index_dir):
        return load_vector_index(
            index_dir=resolved_index_dir,
            model_name=model_name,
            model_cache_root=model_cache_root,
        )

    return build_vector_index(
        index_dir=resolved_index_dir,
        model_name=model_name,
        manifest_path=resolve_path(manifest_path),
        priority=priority,
        strategies=strategies,
        backend=backend,
        limit=limit,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        use_parent_context=use_parent_context,
        batch_size=batch_size,
        strict=strict,
        show_progress_bar=show_progress_bar,
        model_cache_root=model_cache_root,
    )


def build_vector_index(
    *,
    index_dir: Path,
    model_name: str,
    manifest_path: Path,
    priority: str,
    strategies: str,
    backend: str,
    limit: int | None,
    chunk_size: int,
    chunk_overlap: int,
    use_parent_context: bool,
    batch_size: int,
    strict: bool,
    show_progress_bar: bool,
    model_cache_root: Path,
) -> CourseVectorIndex:
    """Build a new FAISS index and persist it to disk."""

    logger.info("Loading documents from manifest: %s", manifest_path)
    documents = load_documents(
        manifest_path=manifest_path,
        repo_root=REPO_ROOT,
        priority=priority,
        strategies=parse_strategy_arg(strategies),
        limit=limit,
        backend=backend,
        strict=strict,
    )
    config = ChunkingConfig(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        use_parent_context=use_parent_context,
    )
    chunking_result = chunk_documents(documents, config=config)
    if not chunking_result.chunks:
        raise ValueError("No chunks were produced; cannot build a vector index")

    model = load_embedding_model(model_name, model_cache_root=model_cache_root)
    texts = [chunk.page_content for chunk in chunking_result.chunks]
    embeddings = encode_texts(
        model,
        texts,
        batch_size=batch_size,
        show_progress_bar=show_progress_bar,
    )

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": model_name,
        "embedding_dimension": int(embeddings.shape[1]),
        "similarity": "cosine_via_normalized_inner_product",
        "faiss_index_type": "IndexFlatIP",
        "manifest_path": safe_repo_relative(manifest_path),
        "priority": priority,
        "strategies": strategies,
        "backend": backend,
        "limit": limit,
        "chunking_config": asdict(config),
        "chunk_stats": chunking_result.stats,
    }
    vector_index = CourseVectorIndex(
        index=index,
        chunks=chunking_result.chunks,
        parents=chunking_result.parents,
        parent_child_map=chunking_result.parent_child_map,
        metadata=metadata,
        model_name=model_name,
        model_cache_root=model_cache_root,
    )
    vector_index._embedding_model = model
    save_vector_index(vector_index, index_dir)
    return vector_index


def load_vector_index(
    *,
    index_dir: Path,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    model_cache_root: Path | None = None,
) -> CourseVectorIndex:
    """Load a persisted FAISS index and its JSON metadata files."""

    index_path = index_dir / INDEX_FILE_NAME
    if not index_path.exists():
        raise FileNotFoundError(f"FAISS index not found: {index_path}")

    chunks = [
        ChunkedDocument(
            page_content=row["page_content"],
            metadata=row.get("metadata", {}),
        )
        for row in read_jsonl(index_dir / CHUNKS_FILE_NAME)
    ]
    parents = [
        ParentDocument(
            page_content=row["page_content"],
            metadata=row.get("metadata", {}),
        )
        for row in read_jsonl(index_dir / PARENTS_FILE_NAME)
    ]
    parent_child_map = read_json(index_dir / PARENT_CHILD_MAP_FILE_NAME)
    metadata = read_json(index_dir / META_FILE_NAME)
    saved_model_name = metadata.get("embedding_model")
    selected_model_name = saved_model_name or model_name or DEFAULT_EMBEDDING_MODEL

    index = faiss.read_index(str(index_path))
    if index.ntotal != len(chunks):
        raise ValueError(
            "Persisted FAISS index and chunks are inconsistent: "
            f"{index.ntotal} vectors vs {len(chunks)} chunks"
        )
    if saved_model_name and model_name and saved_model_name != model_name:
        logger.warning(
            "Ignoring requested embedding model %s because the saved index was "
            "built with %s. Use --rebuild to create a new index with another model.",
            model_name,
            saved_model_name,
        )

    return CourseVectorIndex(
        index=index,
        chunks=chunks,
        parents=parents,
        parent_child_map=parent_child_map,
        metadata=metadata,
        model_name=selected_model_name,
        model_cache_root=model_cache_root,
    )


def save_vector_index(vector_index: CourseVectorIndex, index_dir: Path) -> None:
    """Persist FAISS index, chunks, parent contexts, and metadata."""

    index_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(vector_index.index, str(index_dir / INDEX_FILE_NAME))
    write_jsonl(
        index_dir / CHUNKS_FILE_NAME,
        (chunk.to_dict() for chunk in vector_index.chunks),
    )
    write_jsonl(
        index_dir / PARENTS_FILE_NAME,
        (parent.to_dict() for parent in vector_index.parents),
    )
    write_json(index_dir / PARENT_CHILD_MAP_FILE_NAME, vector_index.parent_child_map)
    write_json(index_dir / META_FILE_NAME, vector_index.metadata)
    logger.info("Saved vector index to %s", index_dir)


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


def has_saved_index(index_dir: Path) -> bool:
    return all(
        (index_dir / filename).exists()
        for filename in (
            INDEX_FILE_NAME,
            CHUNKS_FILE_NAME,
            PARENTS_FILE_NAME,
            PARENT_CHILD_MAP_FILE_NAME,
            META_FILE_NAME,
        )
    )


def summarize_chunk_source(chunk: ChunkedDocument) -> dict[str, Any]:
    metadata = chunk.metadata
    return {
        "source": metadata.get("source"),
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


def summarize_vector_index(vector_index: CourseVectorIndex, index_dir: Path) -> dict[str, Any]:
    stats = vector_index.metadata.get("chunk_stats") or {}
    return {
        "index_dir": safe_repo_relative(resolve_path(index_dir)),
        "vectors": vector_index.index.ntotal,
        "embedding_model": vector_index.metadata.get("embedding_model"),
        "embedding_dimension": vector_index.metadata.get("embedding_dimension"),
        "source_files": stats.get("source_files"),
        "chunks": stats.get("chunks"),
        "parents": stats.get("parents"),
        "avg_chunk_chars": stats.get("avg_chars"),
        "chunks_by_file_type": stats.get("chunks_by_file_type"),
    }


def preview_text(text: str, max_chars: int = 220) -> str:
    compact = " ".join(text.split())
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
    parser.add_argument("--query", default=None, help="Question to search for.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of chunks to return.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild even if an index exists.")
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / LOADER_DEFAULT_MANIFEST_PATH)
    parser.add_argument("--priority", default="mvp")
    parser.add_argument("--strategies", default="supported")
    parser.add_argument("--backend", choices=["auto", "docling", "basic"], default="auto")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--chunk-overlap", type=int, default=80)
    parser.add_argument("--no-parent-context", action="store_true")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print search results as JSON.")
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable embedding progress bar.",
    )
    return parser.parse_args()


def main() -> None:
    configure_stdio()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    vector_index = build_or_load_vector_index(
        index_dir=args.index_dir,
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
        batch_size=args.batch_size,
        strict=args.strict,
        show_progress_bar=not args.no_progress,
    )

    print(
        json.dumps(
            summarize_vector_index(vector_index, args.index_dir),
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.query:
        results = vector_index.search(args.query, top_k=args.top_k)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(format_search_results(results))


if __name__ == "__main__":
    main()
