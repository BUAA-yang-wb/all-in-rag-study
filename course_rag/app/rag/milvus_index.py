"""Milvus dense/BM25 hybrid retrieval over the SQLite Course RAG docstore."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

try:
    from .chunking import ChunkedDocument
    from .docstore import DEFAULT_DOCSTORE_PATH
    from .indexing import (
        DEFAULT_EMBEDDING_MODEL,
        CourseDocstoreIndex,
        build_or_load_docstore_index,
        default_model_cache_root,
        encode_texts,
        format_search_results,
        load_docstore_index,
        load_embedding_model,
        preview_text,
        resolve_path,
        safe_path,
        safe_repo_relative,
        summarize_chunk_source,
    )
except ImportError:
    from chunking import ChunkedDocument  # type: ignore
    from docstore import DEFAULT_DOCSTORE_PATH  # type: ignore
    from indexing import (  # type: ignore
        DEFAULT_EMBEDDING_MODEL,
        CourseDocstoreIndex,
        build_or_load_docstore_index,
        default_model_cache_root,
        encode_texts,
        format_search_results,
        load_docstore_index,
        load_embedding_model,
        preview_text,
        resolve_path,
        safe_path,
        safe_repo_relative,
        summarize_chunk_source,
    )


logger = logging.getLogger(__name__)

DEFAULT_MILVUS_URI = "http://localhost:19530"
DEFAULT_MILVUS_COLLECTION = "course_rag_v2_text"
DEFAULT_MILVUS_BATCH_SIZE = 256
DEFAULT_MILVUS_SCHEMA_VERSION = "milvus_text_hybrid_v1"
DENSE_VECTOR_FIELD = "dense_vector"
SPARSE_VECTOR_FIELD = "sparse_vector"
SEARCH_TEXT_FIELD = "search_text"
PRIMARY_FIELD = "chunk_id"
RetrievalMode = Literal["dense", "bm25", "hybrid"]

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
    "search_text": 8192,
}
SCALAR_FIELDS = [
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
]
OUTPUT_FIELDS = [PRIMARY_FIELD, *SCALAR_FIELDS]


@dataclass(frozen=True)
class MilvusConfig:
    """Connection and collection settings for the Milvus backend."""

    uri: str = DEFAULT_MILVUS_URI
    collection_name: str = DEFAULT_MILVUS_COLLECTION
    docstore_path: Path = DEFAULT_DOCSTORE_PATH


@dataclass
class _IndexStats:
    ntotal: int


class MilvusTextIndex:
    """Milvus retrieval index connected to a SQLite docstore snapshot."""

    def __init__(
        self,
        *,
        config: MilvusConfig,
        docstore_index: CourseDocstoreIndex,
        entity_count: int | None = None,
        embedding_dimension: int | None = None,
    ) -> None:
        self.config = config
        self.docstore_index = docstore_index
        self.chunks = docstore_index.chunks
        self.parents = docstore_index.parents
        self.parent_child_map = docstore_index.parent_child_map
        self.metadata = {
            **docstore_index.metadata,
            "retrieval_backend": "milvus",
            "milvus_schema_version": DEFAULT_MILVUS_SCHEMA_VERSION,
            "milvus_uri": config.uri,
            "milvus_collection": config.collection_name,
            "docstore_path": safe_path(config.docstore_path),
            "embedding_dimension": embedding_dimension
            or docstore_index.metadata.get("embedding_dimension"),
        }
        self.model_name = docstore_index.model_name
        self.model_cache_root = docstore_index.model_cache_root
        self._embedding_model: Any | None = None
        self._client: Any | None = None
        self._chunk_by_id = {
            str(chunk.metadata.get("chunk_id")): chunk
            for chunk in self.chunks
            if chunk.metadata.get("chunk_id") not in {None, ""}
        }
        self.index = _IndexStats(ntotal=entity_count if entity_count is not None else len(self.chunks))

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

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        mode: RetrievalMode = "hybrid",
        rrf_k: int = 60,
        filter_expr: str = "",
    ) -> list[dict[str, Any]]:
        """Return Top-K chunks with Milvus dense, BM25, or hybrid scores."""

        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not self.chunks or self.index.ntotal == 0:
            return []

        if mode == "dense":
            hits = self._dense_search(query, top_k=top_k, filter_expr=filter_expr)
        elif mode == "bm25":
            hits = self._bm25_search(query, top_k=top_k, filter_expr=filter_expr)
        elif mode == "hybrid":
            hits = self._hybrid_search(query, top_k=top_k, rrf_k=rrf_k, filter_expr=filter_expr)
        else:
            raise ValueError(f"unsupported retrieval mode: {mode}")
        return self._format_hits(hits, top_k=top_k)

    def _dense_search(self, query: str, *, top_k: int, filter_expr: str) -> Any:
        query_vector = encode_texts(
            self.embedding_model,
            [query],
            batch_size=1,
            show_progress_bar=False,
        )[0].tolist()
        return self.client.search(
            collection_name=self.config.collection_name,
            data=[query_vector],
            anns_field=DENSE_VECTOR_FIELD,
            limit=min(top_k, self.index.ntotal),
            output_fields=OUTPUT_FIELDS,
            filter=filter_expr,
            search_params={"metric_type": "COSINE", "params": {}},
        )

    def _bm25_search(self, query: str, *, top_k: int, filter_expr: str) -> Any:
        return self.client.search(
            collection_name=self.config.collection_name,
            data=[query],
            anns_field=SPARSE_VECTOR_FIELD,
            limit=min(top_k, self.index.ntotal),
            output_fields=OUTPUT_FIELDS,
            filter=filter_expr,
            search_params={"metric_type": "BM25", "params": {}},
        )

    def _hybrid_search(self, query: str, *, top_k: int, rrf_k: int, filter_expr: str) -> Any:
        from pymilvus import AnnSearchRequest, RRFRanker

        query_vector = encode_texts(
            self.embedding_model,
            [query],
            batch_size=1,
            show_progress_bar=False,
        )[0].tolist()
        limit = min(top_k, self.index.ntotal)
        expr = filter_expr or None
        requests = [
            AnnSearchRequest(
                data=[query_vector],
                anns_field=DENSE_VECTOR_FIELD,
                param={"metric_type": "COSINE", "params": {}},
                limit=limit,
                expr=expr,
            ),
            AnnSearchRequest(
                data=[query],
                anns_field=SPARSE_VECTOR_FIELD,
                param={"metric_type": "BM25", "params": {}},
                limit=limit,
                expr=expr,
            ),
        ]
        return self.client.hybrid_search(
            collection_name=self.config.collection_name,
            reqs=requests,
            ranker=RRFRanker(rrf_k),
            limit=limit,
            output_fields=OUTPUT_FIELDS,
        )

    def _format_hits(self, hits: Any, *, top_k: int) -> list[dict[str, Any]]:
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
    docstore_path: Path = DEFAULT_DOCSTORE_PATH,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    uri: str = DEFAULT_MILVUS_URI,
    collection_name: str = DEFAULT_MILVUS_COLLECTION,
) -> MilvusTextIndex:
    """Load SQLite metadata and connect it to an existing Milvus collection."""

    resolved_docstore_path = resolve_path(docstore_path)
    docstore_index = load_docstore_index(
        docstore_path=resolved_docstore_path,
        model_name=model_name,
        model_cache_root=default_model_cache_root(),
    )
    config = MilvusConfig(
        uri=uri,
        collection_name=collection_name,
        docstore_path=resolved_docstore_path,
    )
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
    if entity_count != len(docstore_index.chunks):
        logger.warning(
            "Milvus entity count differs from SQLite chunk count: %s vs %s",
            entity_count,
            len(docstore_index.chunks),
        )
    client.load_collection(collection_name)
    milvus_index = MilvusTextIndex(
        config=config,
        docstore_index=docstore_index,
        entity_count=entity_count,
        embedding_dimension=milvus_dense_dimension(client, collection_name),
    )
    milvus_index._client = client
    return milvus_index


def rebuild_milvus_text_index(
    *,
    docstore_path: Path = DEFAULT_DOCSTORE_PATH,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    uri: str = DEFAULT_MILVUS_URI,
    collection_name: str = DEFAULT_MILVUS_COLLECTION,
    batch_size: int = DEFAULT_MILVUS_BATCH_SIZE,
    drop_existing: bool = True,
    rebuild_docstore: bool = False,
    dry_run: bool = False,
    **docstore_kwargs: Any,
) -> dict[str, Any]:
    """Create or refresh a Milvus collection from the SQLite docstore."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    resolved_docstore_path = resolve_path(docstore_path)
    docstore_index = build_or_load_docstore_index(
        docstore_path=resolved_docstore_path,
        model_name=model_name,
        rebuild=rebuild_docstore,
        **docstore_kwargs,
    )
    if not docstore_index.chunks:
        raise ValueError("No chunks found in the SQLite docstore")

    model = load_embedding_model(docstore_index.model_name, model_cache_root=default_model_cache_root())
    texts = [chunk.page_content for chunk in docstore_index.chunks]
    embeddings = encode_texts(
        model,
        texts,
        batch_size=batch_size,
        show_progress_bar=not dry_run,
    )
    dimension = int(embeddings.shape[1])
    summary = {
        "backend": "milvus",
        "milvus_uri": uri,
        "collection_name": collection_name,
        "milvus_schema_version": DEFAULT_MILVUS_SCHEMA_VERSION,
        "docstore_path": safe_path(resolved_docstore_path),
        "ingest_run_id": docstore_index.metadata.get("ingest_run_id"),
        "embedding_model": docstore_index.model_name,
        "embedding_dimension": dimension,
        "documents": docstore_index.counts.get("documents"),
        "evidence_count": docstore_index.counts.get("evidence"),
        "chunks": len(docstore_index.chunks),
        "parents": len(docstore_index.parents),
        "drop_existing": drop_existing,
        "rebuild_docstore": rebuild_docstore,
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
    for rows in batched(build_milvus_rows(docstore_index.chunks, embeddings), batch_size):
        result = client.insert(collection_name=collection_name, data=rows)
        inserted += inserted_count(result, default=len(rows))
    client.flush(collection_name)
    client.load_collection(collection_name)
    entity_count = milvus_entity_count(client, collection_name)
    return {**summary, "entity_count": entity_count, "inserted": inserted}


def create_text_collection(client: Any, *, collection_name: str, dimension: int) -> None:
    from pymilvus import DataType, Function, FunctionType, MilvusClient

    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(PRIMARY_FIELD, DataType.VARCHAR, is_primary=True, max_length=VARCHAR_LIMITS["chunk_id"])
    schema.add_field(DENSE_VECTOR_FIELD, DataType.FLOAT_VECTOR, dim=dimension)
    schema.add_field(
        SEARCH_TEXT_FIELD,
        DataType.VARCHAR,
        max_length=VARCHAR_LIMITS["search_text"],
        enable_analyzer=True,
    )
    schema.add_field(SPARSE_VECTOR_FIELD, DataType.SPARSE_FLOAT_VECTOR)
    for field_name in SCALAR_FIELDS:
        schema.add_field(
            field_name,
            DataType.VARCHAR,
            max_length=VARCHAR_LIMITS[field_name],
        )
    schema.add_field("metadata", DataType.JSON)
    schema.add_function(
        Function(
            name="search_text_bm25",
            function_type=FunctionType.BM25,
            input_field_names=[SEARCH_TEXT_FIELD],
            output_field_names=[SPARSE_VECTOR_FIELD],
        )
    )

    index_params = MilvusClient.prepare_index_params()
    index_params.add_index(
        field_name=DENSE_VECTOR_FIELD,
        index_type="FLAT",
        metric_type="COSINE",
    )
    index_params.add_index(
        field_name=SPARSE_VECTOR_FIELD,
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={"inverted_index_algo": "DAAT_MAXSCORE", "bm25_k1": 1.2, "bm25_b": 0.75},
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
            "pymilvus is required for Milvus retrieval. "
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


def build_milvus_rows(
    chunks: list[ChunkedDocument],
    embeddings: Any,
) -> Iterable[dict[str, Any]]:
    for chunk, embedding in zip(chunks, embeddings):
        metadata = chunk.metadata
        chunk_id = str(metadata.get("chunk_id") or "")
        if not chunk_id:
            raise ValueError("Every chunk must have a stable chunk_id for Milvus")
        yield {
            PRIMARY_FIELD: clean_text(chunk_id, "chunk_id"),
            DENSE_VECTOR_FIELD: embedding.tolist(),
            SEARCH_TEXT_FIELD: clean_text(build_search_text(chunk), "search_text"),
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
            "metadata": json_safe_metadata(metadata),
        }


def build_search_text(chunk: ChunkedDocument) -> str:
    metadata = chunk.metadata
    metadata_parts = [
        metadata.get("modality"),
        metadata.get("evidence_kind"),
        metadata.get("source_name"),
        metadata.get("source"),
        metadata.get("asset_path"),
        metadata.get("course"),
        metadata.get("category"),
        metadata.get("section"),
        metadata.get("section_path"),
    ]
    return "\n".join(
        str(part)
        for part in [chunk.page_content, *metadata_parts]
        if part not in {None, ""}
    )


def json_safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(metadata, ensure_ascii=False, default=str))


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
    return str(entity.get(PRIMARY_FIELD) or hit.get("id") or "")


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


def milvus_dense_dimension(client: Any, collection_name: str) -> int | None:
    try:
        description = client.describe_collection(collection_name)
    except Exception:  # noqa: BLE001 - dimension is diagnostic only.
        return None
    for field in description.get("fields", []):
        if field.get("name") == DENSE_VECTOR_FIELD:
            params = field.get("params") or {}
            dim = params.get("dim")
            return int(dim) if dim is not None else None
    return None


def batched(rows: Iterable[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def summarize_milvus_index(vector_index: MilvusTextIndex) -> dict[str, Any]:
    return {
        "docstore_path": safe_repo_relative(resolve_path(vector_index.config.docstore_path)),
        "backend": "milvus",
        "milvus_uri": vector_index.config.uri,
        "collection_name": vector_index.config.collection_name,
        "milvus_schema_version": vector_index.metadata.get("milvus_schema_version"),
        "vectors": vector_index.index.ntotal,
        "documents": vector_index.docstore_index.counts.get("documents"),
        "evidence_count": vector_index.docstore_index.counts.get("evidence"),
        "chunks": len(vector_index.chunks),
        "parents": len(vector_index.parents),
        "embedding_model": vector_index.metadata.get("embedding_model"),
        "embedding_dimension": vector_index.metadata.get("embedding_dimension"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docstore-path", type=Path, default=DEFAULT_DOCSTORE_PATH)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--uri", default=DEFAULT_MILVUS_URI)
    parser.add_argument("--collection", default=DEFAULT_MILVUS_COLLECTION)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_MILVUS_BATCH_SIZE)
    parser.add_argument("--drop-existing", action="store_true")
    parser.add_argument("--rebuild-docstore", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true", help="Load and summarize an existing collection.")
    parser.add_argument("--query", default=None, help="Optional smoke-test query after build/load.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--strategy", choices=("dense", "bm25", "hybrid"), default="hybrid")
    parser.add_argument("--json", action="store_true", help="Print query results as JSON.")
    return parser.parse_args()


def main() -> None:
    configure_stdio()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args()
    if args.check:
        vector_index = build_or_load_milvus_text_index(
            docstore_path=args.docstore_path,
            model_name=args.model,
            uri=args.uri,
            collection_name=args.collection,
        )
        summary = summarize_milvus_index(vector_index)
    else:
        summary = rebuild_milvus_text_index(
            docstore_path=args.docstore_path,
            model_name=args.model,
            uri=args.uri,
            collection_name=args.collection,
            batch_size=args.batch_size,
            drop_existing=args.drop_existing,
            rebuild_docstore=args.rebuild_docstore,
            dry_run=args.dry_run,
        )
        vector_index = None
        if args.query and not args.dry_run:
            vector_index = build_or_load_milvus_text_index(
                docstore_path=args.docstore_path,
                model_name=args.model,
                uri=args.uri,
                collection_name=args.collection,
            )

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.query and not args.dry_run:
        if vector_index is None:
            vector_index = build_or_load_milvus_text_index(
                docstore_path=args.docstore_path,
                model_name=args.model,
                uri=args.uri,
                collection_name=args.collection,
            )
        results = vector_index.search(args.query, top_k=args.top_k, mode=args.strategy)
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
