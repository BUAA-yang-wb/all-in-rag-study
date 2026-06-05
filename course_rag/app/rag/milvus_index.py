"""Milvus text-vector backend for the Course RAG V2 index.

This module deliberately reuses the existing FAISS baseline artifacts
(`chunks.jsonl`, `parents.jsonl`, `parent_child_map.json`, and `index_meta.json`)
as the source of truth for evidence, chunk, and parent-context metadata. Milvus
is the default online dense-vector store; BM25 and RRF stay in the local
retrieval layer. FAISS remains the import source and explicit fallback baseline.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

try:
    from .chunking import ChunkedDocument, ParentDocument
    from .indexing import (
        DEFAULT_EMBEDDING_MODEL,
        DEFAULT_INDEX_DIR,
        CourseVectorIndex,
        default_model_cache_root,
        encode_texts,
        format_search_results,
        load_embedding_model,
        load_vector_index,
        preview_text,
        resolve_path,
        safe_repo_relative,
        summarize_chunk_source,
    )
except ImportError:
    from chunking import ChunkedDocument, ParentDocument  # type: ignore
    from indexing import (  # type: ignore
        DEFAULT_EMBEDDING_MODEL,
        DEFAULT_INDEX_DIR,
        CourseVectorIndex,
        default_model_cache_root,
        encode_texts,
        format_search_results,
        load_embedding_model,
        load_vector_index,
        preview_text,
        resolve_path,
        safe_repo_relative,
        summarize_chunk_source,
    )


logger = logging.getLogger(__name__)

DEFAULT_MILVUS_URI = "http://localhost:19530"
DEFAULT_MILVUS_COLLECTION = "course_rag_v2_text"
DEFAULT_MILVUS_BATCH_SIZE = 256
VECTOR_FIELD = "dense_vector"
PRIMARY_FIELD = "chunk_id"

VARCHAR_LIMITS = {
    "chunk_id": 128,
    "parent_doc_id": 128,
    "evidence_id": 128,
    "source_doc_id": 128,
    "modality": 64,
    "evidence_kind": 128,
    "parser_backend": 128,
    "course": 256,
    "category": 512,
    "page": 64,
    "source": 4096,
    "source_name": 1024,
    "asset_path": 4096,
    "section_path": 2048,
    "page_content": 8192,
    "metadata_json": 65535,
}
OUTPUT_FIELDS = [
    "chunk_id",
    "parent_doc_id",
    "evidence_id",
    "source_doc_id",
    "modality",
    "evidence_kind",
    "parser_backend",
    "course",
    "category",
    "page",
    "source",
    "source_name",
    "asset_path",
    "section_path",
    "page_content",
]


@dataclass(frozen=True)
class MilvusConfig:
    """Connection and collection settings for the Milvus backend."""

    uri: str = DEFAULT_MILVUS_URI
    collection_name: str = DEFAULT_MILVUS_COLLECTION


@dataclass
class _IndexStats:
    ntotal: int


class MilvusTextIndex:
    """Milvus-backed dense search with local chunk and parent metadata."""

    def __init__(
        self,
        *,
        config: MilvusConfig,
        chunks: list[ChunkedDocument],
        parents: list[ParentDocument],
        parent_child_map: dict[str, str],
        metadata: dict[str, Any],
        model_name: str,
        model_cache_root: Path | None = None,
        entity_count: int | None = None,
    ) -> None:
        self.config = config
        self.chunks = chunks
        self.parents = parents
        self.parent_child_map = parent_child_map
        self.metadata = {
            **metadata,
            "index_backend": "milvus",
            "milvus_uri": config.uri,
            "milvus_collection": config.collection_name,
        }
        self.model_name = model_name
        self.model_cache_root = model_cache_root
        self._embedding_model: Any | None = None
        self._client: Any | None = None
        self._chunk_by_id = {
            str(chunk.metadata.get("chunk_id")): chunk
            for chunk in chunks
            if chunk.metadata.get("chunk_id") not in {None, ""}
        }
        self.index = _IndexStats(ntotal=entity_count if entity_count is not None else len(chunks))

    @property
    def embedding_model(self) -> Any:
        if self._embedding_model is None:
            self._embedding_model = load_embedding_model(
                self.model_name,
                model_cache_root=self.model_cache_root,
            )
        return self._embedding_model

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = create_milvus_client(self.config.uri)
        return self._client

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Return Top-K chunks with Milvus dense scores and source metadata."""

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
        )[0].tolist()
        hits = self.client.search(
            collection_name=self.config.collection_name,
            data=[query_vector],
            anns_field=VECTOR_FIELD,
            limit=min(top_k, self.index.ntotal),
            output_fields=OUTPUT_FIELDS,
            search_params={"metric_type": "COSINE", "params": {}},
        )

        results: list[dict[str, Any]] = []
        for rank, hit in enumerate(first_result_set(hits), 1):
            chunk_id = hit_chunk_id(hit)
            chunk = self._chunk_by_id.get(chunk_id)
            if chunk is None:
                logger.warning("Milvus returned unknown chunk_id: %s", chunk_id)
                continue
            score = hit_score(hit)
            results.append(
                {
                    "rank": rank,
                    "score": score,
                    "chunk": chunk.to_dict(),
                    "source": summarize_chunk_source(chunk),
                    "preview": preview_text(chunk.page_content),
                }
            )
            if len(results) >= top_k:
                break
        return results


def build_or_load_milvus_text_index(
    *,
    index_dir: Path = DEFAULT_INDEX_DIR,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    uri: str = DEFAULT_MILVUS_URI,
    collection_name: str = DEFAULT_MILVUS_COLLECTION,
) -> MilvusTextIndex:
    """Load local metadata and connect it to an existing Milvus collection."""

    resolved_index_dir = resolve_path(index_dir)
    model_cache_root = default_model_cache_root()
    faiss_index = load_vector_index(
        index_dir=resolved_index_dir,
        model_name=model_name,
        model_cache_root=model_cache_root,
    )
    config = MilvusConfig(uri=uri, collection_name=collection_name)
    client = create_milvus_client(uri)
    try:
        has_collection = client.has_collection(collection_name)
    except Exception as exc:  # noqa: BLE001 - expose actionable local setup help.
        raise RuntimeError(milvus_connection_error(uri, exc)) from exc
    if not has_collection:
        raise FileNotFoundError(
            f"Milvus collection not found: {collection_name}. "
            r"Start Milvus with `powershell -ExecutionPolicy Bypass -File "
            r"course_rag\scripts\milvus_up.ps1`, then build it with "
            r"`powershell -ExecutionPolicy Bypass -File "
            r"course_rag\scripts\milvus_rebuild_index.ps1`."
        )
    entity_count = milvus_entity_count(client, collection_name)
    if entity_count != len(faiss_index.chunks):
        logger.warning(
            "Milvus entity count differs from local chunk count: %s vs %s",
            entity_count,
            len(faiss_index.chunks),
        )
    client.load_collection(collection_name)
    milvus_index = MilvusTextIndex(
        config=config,
        chunks=faiss_index.chunks,
        parents=faiss_index.parents,
        parent_child_map=faiss_index.parent_child_map,
        metadata=faiss_index.metadata,
        model_name=faiss_index.model_name,
        model_cache_root=model_cache_root,
        entity_count=entity_count,
    )
    milvus_index._client = client
    return milvus_index


def build_milvus_collection_from_faiss(
    *,
    index_dir: Path = DEFAULT_INDEX_DIR,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    uri: str = DEFAULT_MILVUS_URI,
    collection_name: str = DEFAULT_MILVUS_COLLECTION,
    batch_size: int = DEFAULT_MILVUS_BATCH_SIZE,
    drop_existing: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create or refresh a Milvus collection from the saved FAISS baseline."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    resolved_index_dir = resolve_path(index_dir)
    faiss_index = load_vector_index(
        index_dir=resolved_index_dir,
        model_name=model_name,
        model_cache_root=default_model_cache_root(),
    )
    embeddings = reconstruct_faiss_embeddings(faiss_index)
    dimension = int(embeddings.shape[1])
    summary = {
        "index_dir": safe_repo_relative(resolved_index_dir),
        "backend": "milvus",
        "milvus_uri": uri,
        "collection_name": collection_name,
        "embedding_model": faiss_index.metadata.get("embedding_model"),
        "embedding_dimension": dimension,
        "chunks": len(faiss_index.chunks),
        "parents": len(faiss_index.parents),
        "drop_existing": drop_existing,
        "dry_run": dry_run,
    }
    if dry_run:
        return {**summary, "entity_count": None, "inserted": 0}

    client = create_milvus_client(uri)
    try:
        has_collection = client.has_collection(collection_name)
    except Exception as exc:  # noqa: BLE001 - expose actionable local setup help.
        raise RuntimeError(milvus_connection_error(uri, exc)) from exc
    if has_collection:
        if drop_existing:
            client.drop_collection(collection_name)
        else:
            raise ValueError(
                f"Milvus collection already exists: {collection_name}. "
                "Pass --drop-existing to rebuild it."
            )

    create_text_collection(client, collection_name=collection_name, dimension=dimension)
    inserted = 0
    for rows in batched(build_milvus_rows(faiss_index.chunks, embeddings), batch_size):
        result = client.insert(collection_name=collection_name, data=rows)
        inserted += inserted_count(result, default=len(rows))
    client.flush(collection_name)
    client.load_collection(collection_name)
    entity_count = milvus_entity_count(client, collection_name)
    return {**summary, "entity_count": entity_count, "inserted": inserted}


def create_text_collection(client: Any, *, collection_name: str, dimension: int) -> None:
    from pymilvus import DataType, MilvusClient

    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=VARCHAR_LIMITS["chunk_id"])
    schema.add_field(VECTOR_FIELD, DataType.FLOAT_VECTOR, dim=dimension)
    for field_name in (
        "parent_doc_id",
        "evidence_id",
        "source_doc_id",
        "modality",
        "evidence_kind",
        "parser_backend",
        "course",
        "category",
        "page",
        "source",
        "source_name",
        "asset_path",
        "section_path",
        "page_content",
        "metadata_json",
    ):
        schema.add_field(
            field_name,
            DataType.VARCHAR,
            max_length=VARCHAR_LIMITS[field_name],
        )

    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name=VECTOR_FIELD,
        index_type="FLAT",
        metric_type="COSINE",
    )
    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
    )


def create_milvus_client(uri: str) -> Any:
    try:
        from pymilvus import MilvusClient
    except ImportError as exc:
        raise RuntimeError(
            "pymilvus is required for index_backend='milvus'. "
            "Install it in the current virtual environment first."
        ) from exc
    try:
        return MilvusClient(uri=uri)
    except Exception as exc:  # noqa: BLE001 - expose actionable local setup help.
        raise RuntimeError(milvus_connection_error(uri, exc)) from exc


def milvus_connection_error(uri: str, exc: BaseException) -> str:
    return (
        f"Cannot connect to Milvus at {uri}. Start Docker Desktop first, then run "
        r"`powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_up.ps1` "
        r"and build the collection with `powershell -ExecutionPolicy Bypass -File "
        r"course_rag\scripts\milvus_rebuild_index.ps1`. "
        f"Original error: {exc}"
    )


def reconstruct_faiss_embeddings(vector_index: CourseVectorIndex) -> np.ndarray:
    total = int(vector_index.index.ntotal)
    if total != len(vector_index.chunks):
        raise ValueError(
            "FAISS vector count and chunk count differ: "
            f"{total} vectors vs {len(vector_index.chunks)} chunks"
        )
    if total == 0:
        raise ValueError("No vectors found in the saved FAISS index")
    try:
        embeddings = vector_index.index.reconstruct_n(0, total)
    except Exception:  # noqa: BLE001 - FAISS fallback for index implementations.
        embeddings = np.vstack(
            [vector_index.index.reconstruct(index_id) for index_id in range(total)]
        )
    return np.ascontiguousarray(embeddings.astype("float32"))


def build_milvus_rows(
    chunks: list[ChunkedDocument],
    embeddings: np.ndarray,
) -> Iterable[dict[str, Any]]:
    for chunk, embedding in zip(chunks, embeddings):
        metadata = chunk.metadata
        chunk_id = str(metadata.get("chunk_id") or "")
        if not chunk_id:
            raise ValueError("Every chunk must have a stable chunk_id for Milvus")
        metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)
        yield {
            "chunk_id": clean_text(chunk_id, "chunk_id"),
            "dense_vector": embedding.tolist(),
            "parent_doc_id": clean_text(metadata.get("parent_doc_id"), "parent_doc_id"),
            "evidence_id": clean_text(metadata.get("evidence_id"), "evidence_id"),
            "source_doc_id": clean_text(metadata.get("source_doc_id"), "source_doc_id"),
            "modality": clean_text(metadata.get("modality"), "modality"),
            "evidence_kind": clean_text(metadata.get("evidence_kind"), "evidence_kind"),
            "parser_backend": clean_text(metadata.get("parser_backend"), "parser_backend"),
            "course": clean_text(metadata.get("course"), "course"),
            "category": clean_text(metadata.get("category"), "category"),
            "page": clean_text(metadata.get("page"), "page"),
            "source": clean_text(metadata.get("source"), "source"),
            "source_name": clean_text(metadata.get("source_name"), "source_name"),
            "asset_path": clean_text(metadata.get("asset_path"), "asset_path"),
            "section_path": clean_text(metadata.get("section_path"), "section_path"),
            "page_content": clean_text(chunk.page_content, "page_content"),
            "metadata_json": clean_text(metadata_json, "metadata_json"),
        }


def clean_text(value: Any, field_name: str) -> str:
    if value in {None, ""}:
        return ""
    text = str(value)
    max_chars = VARCHAR_LIMITS[field_name]
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def first_result_set(hits: Any) -> list[dict[str, Any]]:
    if not hits:
        return []
    first = hits[0]
    return list(first or [])


def hit_chunk_id(hit: dict[str, Any]) -> str:
    entity = hit.get("entity") or {}
    return str(entity.get("chunk_id") or hit.get("id") or "")


def hit_score(hit: dict[str, Any]) -> float:
    for key in ("distance", "score"):
        if hit.get(key) is not None:
            return float(hit[key])
    return 0.0


def inserted_count(result: dict[str, Any], *, default: int) -> int:
    if not isinstance(result, dict):
        return default
    if isinstance(result.get("insert_count"), int):
        return int(result["insert_count"])
    ids = result.get("ids")
    if isinstance(ids, list):
        return len(ids)
    return default


def milvus_entity_count(client: Any, collection_name: str) -> int:
    stats = client.get_collection_stats(collection_name)
    value = stats.get("row_count") or stats.get("entity_count")
    return int(value or 0)


def batched(rows: Iterable[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def summarize_milvus_index(vector_index: MilvusTextIndex, index_dir: Path) -> dict[str, Any]:
    return {
        "index_dir": safe_repo_relative(resolve_path(index_dir)),
        "backend": "milvus",
        "milvus_uri": vector_index.config.uri,
        "collection_name": vector_index.config.collection_name,
        "vectors": vector_index.index.ntotal,
        "chunks": len(vector_index.chunks),
        "parents": len(vector_index.parents),
        "embedding_model": vector_index.metadata.get("embedding_model"),
        "embedding_dimension": vector_index.metadata.get("embedding_dimension"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--uri", default=DEFAULT_MILVUS_URI)
    parser.add_argument("--collection", default=DEFAULT_MILVUS_COLLECTION)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_MILVUS_BATCH_SIZE)
    parser.add_argument("--drop-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true", help="Load and summarize an existing collection.")
    parser.add_argument("--query", default=None, help="Optional smoke-test query after build/load.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Print query results as JSON.")
    return parser.parse_args()


def main() -> None:
    configure_stdio()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    if args.check:
        vector_index = build_or_load_milvus_text_index(
            index_dir=args.index_dir,
            model_name=args.model,
            uri=args.uri,
            collection_name=args.collection,
        )
        summary = summarize_milvus_index(vector_index, args.index_dir)
    else:
        summary = build_milvus_collection_from_faiss(
            index_dir=args.index_dir,
            model_name=args.model,
            uri=args.uri,
            collection_name=args.collection,
            batch_size=args.batch_size,
            drop_existing=args.drop_existing,
            dry_run=args.dry_run,
        )
        vector_index = None
        if args.query and not args.dry_run:
            vector_index = build_or_load_milvus_text_index(
                index_dir=args.index_dir,
                model_name=args.model,
                uri=args.uri,
                collection_name=args.collection,
            )

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.query and not args.dry_run:
        if vector_index is None:
            vector_index = build_or_load_milvus_text_index(
                index_dir=args.index_dir,
                model_name=args.model,
                uri=args.uri,
                collection_name=args.collection,
            )
        results = vector_index.search(args.query, top_k=args.top_k)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(format_search_results(results))


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    main()
