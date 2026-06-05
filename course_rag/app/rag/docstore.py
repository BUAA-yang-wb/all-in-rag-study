"""SQLite document store for Course RAG chunks, parents, and evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .chunking import ChunkedDocument, ParentDocument
except ImportError:
    from chunking import ChunkedDocument, ParentDocument  # type: ignore


COURSE_RAG_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCSTORE_PATH = COURSE_RAG_ROOT / "data" / "rag_store.sqlite"
DOCSTORE_SCHEMA_VERSION = "docstore_v1"


@dataclass(frozen=True)
class DocstoreSnapshot:
    """Loaded SQLite state needed by retrieval and generation."""

    chunks: list[ChunkedDocument]
    parents: list[ParentDocument]
    parent_child_map: dict[str, str]
    metadata: dict[str, Any]
    counts: dict[str, int]
    docstore_path: Path


def save_docstore_snapshot(
    docstore_path: Path,
    *,
    source_documents: Iterable[Any],
    evidence_documents: Iterable[Any],
    chunks: list[ChunkedDocument],
    parents: list[ParentDocument],
    parent_child_map: dict[str, str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Replace the docstore with one coherent ingest snapshot."""

    resolved_path = resolve_docstore_path(docstore_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = stable_hash(
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "chunks": len(chunks),
            "parents": len(parents),
        },
        length=20,
    )
    saved_metadata = {
        **metadata,
        "docstore_schema_version": DOCSTORE_SCHEMA_VERSION,
        "docstore_path": safe_path(resolved_path),
        "ingest_run_id": run_id,
    }

    conn = sqlite3.connect(resolved_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        init_docstore_schema(conn)
        clear_docstore(conn)
        insert_ingest_run(
            conn,
            run_id=run_id,
            status="running",
            metadata=saved_metadata,
            counts={},
        )
        document_count = insert_documents(conn, source_documents)
        evidence_count = insert_evidence(conn, evidence_documents)
        parent_count = insert_parents(conn, parents)
        chunk_count = insert_chunks(conn, chunks)
        map_count = insert_parent_child_map(conn, parent_child_map)
        counts = {
            "documents": document_count,
            "evidence": evidence_count,
            "parents": parent_count,
            "chunks": chunk_count,
            "chunk_parent_mappings": map_count,
        }
        insert_ingest_run(
            conn,
            run_id=run_id,
            status="ok",
            metadata={**saved_metadata, **counts},
            counts=counts,
        )
        conn.commit()
    finally:
        conn.close()

    return {"ingest_run_id": run_id, **counts, "docstore_path": safe_path(resolved_path)}


def load_docstore_snapshot(docstore_path: Path = DEFAULT_DOCSTORE_PATH) -> DocstoreSnapshot:
    resolved_path = resolve_docstore_path(docstore_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"SQLite docstore not found: {resolved_path}")

    conn = sqlite3.connect(resolved_path)
    try:
        conn.row_factory = sqlite3.Row
        init_docstore_schema(conn)
        parent_rows = conn.execute(
            "SELECT text, metadata_json FROM parents ORDER BY ordinal"
        ).fetchall()
        chunk_rows = conn.execute(
            "SELECT text, metadata_json FROM chunks ORDER BY ordinal"
        ).fetchall()
        map_rows = conn.execute(
            "SELECT chunk_id, parent_doc_id FROM chunk_parent_map ORDER BY chunk_id"
        ).fetchall()
        run_row = conn.execute(
            "SELECT metadata_json FROM ingest_runs WHERE status='ok' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        counts = docstore_counts(conn)
    finally:
        conn.close()

    parents = [
        ParentDocument(page_content=row["text"], metadata=loads_json(row["metadata_json"]))
        for row in parent_rows
    ]
    chunks = [
        ChunkedDocument(page_content=row["text"], metadata=loads_json(row["metadata_json"]))
        for row in chunk_rows
    ]
    parent_child_map = {
        str(row["chunk_id"]): str(row["parent_doc_id"])
        for row in map_rows
    }
    metadata = loads_json(run_row["metadata_json"]) if run_row is not None else {}
    metadata.setdefault("docstore_schema_version", DOCSTORE_SCHEMA_VERSION)
    metadata.setdefault("docstore_path", safe_path(resolved_path))

    return DocstoreSnapshot(
        chunks=chunks,
        parents=parents,
        parent_child_map=parent_child_map,
        metadata=metadata,
        counts=counts,
        docstore_path=resolved_path,
    )


def inspect_docstore(docstore_path: Path = DEFAULT_DOCSTORE_PATH) -> dict[str, Any]:
    resolved_path = resolve_docstore_path(docstore_path)
    if not resolved_path.exists():
        return {
            "exists": False,
            "readable": False,
            "docstore_path": safe_path(resolved_path),
            "error": f"SQLite docstore not found: {resolved_path}",
        }
    try:
        snapshot = load_docstore_snapshot(resolved_path)
    except Exception as exc:  # noqa: BLE001 - health should report diagnostics.
        return {
            "exists": True,
            "readable": False,
            "docstore_path": safe_path(resolved_path),
            "error": str(exc),
        }
    return {
        "exists": True,
        "readable": True,
        "docstore_path": safe_path(resolved_path),
        **snapshot.counts,
        "metadata": snapshot.metadata,
        "error": None,
    }


def has_docstore_snapshot(docstore_path: Path = DEFAULT_DOCSTORE_PATH) -> bool:
    try:
        snapshot = load_docstore_snapshot(docstore_path)
    except Exception:  # noqa: BLE001 - boolean helper.
        return False
    return bool(snapshot.chunks and snapshot.parents)


def init_docstore_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ingest_runs (
            run_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            documents INTEGER NOT NULL DEFAULT 0,
            evidence INTEGER NOT NULL DEFAULT 0,
            parents INTEGER NOT NULL DEFAULT 0,
            chunks INTEGER NOT NULL DEFAULT 0,
            chunk_parent_mappings INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS documents (
            document_id TEXT PRIMARY KEY,
            source TEXT,
            source_name TEXT,
            course TEXT,
            category TEXT,
            file_type TEXT,
            text TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            document_id TEXT,
            source_doc_id TEXT,
            source TEXT,
            source_name TEXT,
            course TEXT,
            category TEXT,
            page TEXT,
            modality TEXT,
            evidence_kind TEXT,
            parser_backend TEXT,
            text TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            content_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS parents (
            parent_doc_id TEXT PRIMARY KEY,
            document_id TEXT,
            source_doc_id TEXT,
            source TEXT,
            source_name TEXT,
            course TEXT,
            category TEXT,
            page TEXT,
            section_path TEXT,
            text TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            ordinal INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            parent_doc_id TEXT NOT NULL,
            document_id TEXT,
            source_doc_id TEXT,
            evidence_id TEXT,
            source TEXT,
            source_name TEXT,
            course TEXT,
            category TEXT,
            page TEXT,
            modality TEXT,
            evidence_kind TEXT,
            parser_backend TEXT,
            text TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            ordinal INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chunk_parent_map (
            chunk_id TEXT PRIMARY KEY,
            parent_doc_id TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_doc_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_name, page);
        CREATE INDEX IF NOT EXISTS idx_chunks_filters ON chunks(course, category, modality, evidence_kind);
        CREATE INDEX IF NOT EXISTS idx_evidence_filters ON evidence(course, category, modality, evidence_kind);
        """
    )


def clear_docstore(conn: sqlite3.Connection) -> None:
    for table in (
        "chunk_parent_map",
        "chunks",
        "parents",
        "evidence",
        "documents",
        "ingest_runs",
    ):
        conn.execute(f"DELETE FROM {table}")


def insert_ingest_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    status: str,
    metadata: dict[str, Any],
    counts: dict[str, int],
) -> None:
    conn.execute(
        """
        INSERT INTO ingest_runs (
            run_id, created_at, status, metadata_json, documents, evidence,
            parents, chunks, chunk_parent_mappings
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            status=excluded.status,
            metadata_json=excluded.metadata_json,
            documents=excluded.documents,
            evidence=excluded.evidence,
            parents=excluded.parents,
            chunks=excluded.chunks,
            chunk_parent_mappings=excluded.chunk_parent_mappings
        """,
        (
            run_id,
            datetime.now(timezone.utc).isoformat(),
            status,
            dumps_json(metadata),
            counts.get("documents", 0),
            counts.get("evidence", 0),
            counts.get("parents", 0),
            counts.get("chunks", 0),
            counts.get("chunk_parent_mappings", 0),
        ),
    )


def insert_documents(conn: sqlite3.Connection, documents: Iterable[Any]) -> int:
    rows = []
    seen: set[str] = set()
    for document in documents:
        text = text_of(document)
        metadata = metadata_of(document)
        document_id = document_id_from_metadata(metadata, text)
        if document_id in seen:
            continue
        seen.add(document_id)
        rows.append(
            (
                document_id,
                text_or_none(metadata.get("source")),
                text_or_none(metadata.get("source_name")),
                text_or_none(metadata.get("course")),
                text_or_none(metadata.get("category")),
                text_or_none(metadata.get("file_type")),
                text,
                dumps_json(metadata),
                content_hash(text, metadata),
                datetime.now(timezone.utc).isoformat(),
            )
        )
    conn.executemany(
        """
        INSERT INTO documents (
            document_id, source, source_name, course, category, file_type, text,
            metadata_json, content_hash, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def insert_evidence(conn: sqlite3.Connection, evidence_documents: Iterable[Any]) -> int:
    rows = []
    seen: set[str] = set()
    for evidence in evidence_documents:
        text = text_of(evidence)
        metadata = metadata_of(evidence)
        evidence_id = str(
            metadata.get("evidence_id")
            or stable_hash({"kind": "evidence", "metadata": metadata, "text": text})
        )
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        document_id = document_id_from_metadata(metadata, text)
        rows.append(
            (
                evidence_id,
                document_id,
                text_or_none(metadata.get("source_doc_id")),
                text_or_none(metadata.get("source")),
                text_or_none(metadata.get("source_name")),
                text_or_none(metadata.get("course")),
                text_or_none(metadata.get("category")),
                text_or_none(metadata.get("page")),
                text_or_none(metadata.get("modality")),
                text_or_none(metadata.get("evidence_kind")),
                text_or_none(metadata.get("parser_backend")),
                text,
                dumps_json(metadata),
                content_hash(text, metadata),
            )
        )
    conn.executemany(
        """
        INSERT INTO evidence (
            evidence_id, document_id, source_doc_id, source, source_name, course,
            category, page, modality, evidence_kind, parser_backend, text,
            metadata_json, content_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def insert_parents(conn: sqlite3.Connection, parents: list[ParentDocument]) -> int:
    rows = []
    for ordinal, parent in enumerate(parents):
        metadata = parent.metadata
        parent_id = str(metadata.get("parent_doc_id") or stable_hash(parent.to_dict()))
        rows.append(
            (
                parent_id,
                document_id_from_metadata(metadata, parent.page_content),
                text_or_none(metadata.get("source_doc_id")),
                text_or_none(metadata.get("source")),
                text_or_none(metadata.get("source_name")),
                text_or_none(metadata.get("course")),
                text_or_none(metadata.get("category")),
                text_or_none(metadata.get("page")),
                text_or_none(metadata.get("section_path")),
                parent.page_content,
                dumps_json(metadata),
                content_hash(parent.page_content, metadata),
                ordinal,
            )
        )
    conn.executemany(
        """
        INSERT INTO parents (
            parent_doc_id, document_id, source_doc_id, source, source_name,
            course, category, page, section_path, text, metadata_json,
            content_hash, ordinal
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def insert_chunks(conn: sqlite3.Connection, chunks: list[ChunkedDocument]) -> int:
    rows = []
    for ordinal, chunk in enumerate(chunks):
        metadata = chunk.metadata
        chunk_id = str(metadata.get("chunk_id") or stable_hash(chunk.to_dict()))
        rows.append(
            (
                chunk_id,
                str(metadata.get("parent_doc_id") or ""),
                document_id_from_metadata(metadata, chunk.page_content),
                text_or_none(metadata.get("source_doc_id")),
                text_or_none(metadata.get("evidence_id")),
                text_or_none(metadata.get("source")),
                text_or_none(metadata.get("source_name")),
                text_or_none(metadata.get("course")),
                text_or_none(metadata.get("category")),
                text_or_none(metadata.get("page")),
                text_or_none(metadata.get("modality")),
                text_or_none(metadata.get("evidence_kind")),
                text_or_none(metadata.get("parser_backend")),
                chunk.page_content,
                dumps_json(metadata),
                content_hash(chunk.page_content, metadata),
                ordinal,
            )
        )
    conn.executemany(
        """
        INSERT INTO chunks (
            chunk_id, parent_doc_id, document_id, source_doc_id, evidence_id,
            source, source_name, course, category, page, modality, evidence_kind,
            parser_backend, text, metadata_json, content_hash, ordinal
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def insert_parent_child_map(conn: sqlite3.Connection, parent_child_map: dict[str, str]) -> int:
    rows = [(str(chunk_id), str(parent_id)) for chunk_id, parent_id in parent_child_map.items()]
    conn.executemany(
        "INSERT INTO chunk_parent_map (chunk_id, parent_doc_id) VALUES (?, ?)",
        rows,
    )
    return len(rows)


def docstore_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "documents": count_rows(conn, "documents"),
        "evidence": count_rows(conn, "evidence"),
        "parents": count_rows(conn, "parents"),
        "chunks": count_rows(conn, "chunks"),
        "chunk_parent_mappings": count_rows(conn, "chunk_parent_map"),
    }


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    value = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return int(value or 0)


def metadata_of(item: Any) -> dict[str, Any]:
    metadata = getattr(item, "metadata", None)
    if isinstance(metadata, dict):
        return dict(metadata)
    if isinstance(item, dict) and isinstance(item.get("metadata"), dict):
        return dict(item["metadata"])
    return {}


def text_of(item: Any) -> str:
    if hasattr(item, "page_content"):
        return str(getattr(item, "page_content") or "")
    if isinstance(item, dict):
        return str(item.get("page_content") or item.get("text") or "")
    return ""


def document_id_from_metadata(metadata: dict[str, Any], text: str) -> str:
    return str(
        metadata.get("source_doc_id")
        or metadata.get("doc_id")
        or stable_hash(
            {
                "kind": "document",
                "source": metadata.get("source"),
                "source_name": metadata.get("source_name"),
                "text": text[:1000],
            }
        )
    )


def content_hash(text: str, metadata: dict[str, Any]) -> str:
    return stable_hash({"text": text, "metadata": metadata}, length=40)


def stable_hash(payload: Any, length: int = 16) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:length]


def dumps_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def loads_json(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    value = json.loads(payload)
    return value if isinstance(value, dict) else {}


def text_or_none(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)


def resolve_docstore_path(path: Path) -> Path:
    return path if path.is_absolute() else (COURSE_RAG_ROOT.parent / path).resolve()


def safe_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)
