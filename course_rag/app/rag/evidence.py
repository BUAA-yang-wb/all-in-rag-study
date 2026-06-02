"""Evidence documents for the V2 Course RAG ingestion path.

This module keeps the first V2 step deliberately small: text-only evidence
objects that can be converted back to the existing ``LoadedDocument`` shape.
OCR, VLM captions, image evidence, and table evidence can plug into the same
schema later without changing retrieval or citation semantics again.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    from .loaders import LoadedDocument
except ImportError:
    from loaders import LoadedDocument  # type: ignore


DEFAULT_TEXT_EVIDENCE_CACHE_PATH = Path("course_rag/data/processed/evidence_text.jsonl")
DEFAULT_TEXT_EVIDENCE_PIPELINE_VERSION = "text_evidence_v1"
DEFAULT_TEXT_MODALITY = "text"
DEFAULT_TEXT_EVIDENCE_KIND = "native_text"


@dataclass
class EvidenceDocument:
    """Unified V2 evidence object before chunking and indexing."""

    page_content: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_content": self.page_content,
            "metadata": self.metadata,
        }


def loaded_documents_to_text_evidence(
    documents: Iterable[LoadedDocument],
    *,
    pipeline_version: str = DEFAULT_TEXT_EVIDENCE_PIPELINE_VERSION,
) -> list[EvidenceDocument]:
    """Convert existing MVP loader output to text evidence documents."""

    evidence_documents: list[EvidenceDocument] = []
    seen_base_ids: dict[str, int] = {}
    for document_index, document in enumerate(documents):
        evidence_documents.append(
            loaded_document_to_text_evidence(
                document,
                document_index=document_index,
                pipeline_version=pipeline_version,
                seen_base_ids=seen_base_ids,
            )
        )
    return evidence_documents


def loaded_document_to_text_evidence(
    document: LoadedDocument,
    *,
    document_index: int,
    pipeline_version: str,
    seen_base_ids: dict[str, int],
) -> EvidenceDocument:
    """Build one text evidence object from one loaded document."""

    metadata = dict(document.metadata)
    source_doc_id = metadata.get("source_doc_id") or metadata.get("doc_id") or stable_hash(
        {"source": metadata.get("source")}
    )
    metadata["source_doc_id"] = source_doc_id
    metadata.setdefault("source_name", source_name_from_source(metadata.get("source")))
    metadata.setdefault("asset_path", None)
    metadata.setdefault("context_before", None)
    metadata.setdefault("context_after", None)

    base_id_payload = evidence_id_payload(
        metadata=metadata,
        modality=DEFAULT_TEXT_MODALITY,
        evidence_kind=DEFAULT_TEXT_EVIDENCE_KIND,
    )
    base_evidence_id = stable_hash(base_id_payload)
    occurrence = seen_base_ids.get(base_evidence_id, 0)
    seen_base_ids[base_evidence_id] = occurrence + 1
    if occurrence:
        evidence_id = stable_hash({**base_id_payload, "occurrence": occurrence})
    else:
        evidence_id = base_evidence_id

    metadata.update(
        {
            "evidence_id": evidence_id,
            "modality": DEFAULT_TEXT_MODALITY,
            "evidence_kind": DEFAULT_TEXT_EVIDENCE_KIND,
            "source_hash": metadata.get("source_hash")
            or stable_hash(
                {
                    "source": metadata.get("source"),
                    "page": metadata.get("page"),
                    "content": document.page_content,
                }
            ),
            "pipeline_version": pipeline_version,
            "evidence_document_index": document_index,
            "text_length": len(document.page_content),
        }
    )
    return EvidenceDocument(page_content=document.page_content, metadata=metadata)


def evidence_id_payload(
    *,
    metadata: dict[str, Any],
    modality: str,
    evidence_kind: str,
) -> dict[str, Any]:
    """Return the stable, content-independent fields used for evidence IDs."""

    return {
        "source_doc_id": metadata.get("source_doc_id"),
        "source": metadata.get("source"),
        "page": metadata.get("page"),
        "section": metadata.get("section"),
        "section_path": metadata.get("section_path"),
        "asset_path": metadata.get("asset_path"),
        "modality": modality,
        "evidence_kind": evidence_kind,
        "parser_backend": metadata.get("parser_backend"),
        "loader": metadata.get("loader"),
    }


def evidence_to_loaded_documents(
    evidence_documents: Iterable[EvidenceDocument],
) -> list[LoadedDocument]:
    """Convert evidence objects back to the existing chunker input shape."""

    return [
        LoadedDocument(
            page_content=evidence.page_content,
            metadata=dict(evidence.metadata),
        )
        for evidence in evidence_documents
    ]


def read_evidence_jsonl(path: Path) -> list[EvidenceDocument]:
    rows: list[EvidenceDocument] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            rows.append(
                EvidenceDocument(
                    page_content=payload.get("page_content", ""),
                    metadata=payload.get("metadata", {}),
                )
            )
    return rows


def write_evidence_jsonl(
    path: Path,
    evidence_documents: Iterable[EvidenceDocument],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for evidence in evidence_documents:
            handle.write(json.dumps(evidence.to_dict(), ensure_ascii=False) + "\n")


def summarize_evidence(evidence_documents: Iterable[EvidenceDocument]) -> dict[str, Any]:
    evidence = list(evidence_documents)
    by_modality = Counter(str(item.metadata.get("modality", "unknown")) for item in evidence)
    by_kind = Counter(str(item.metadata.get("evidence_kind", "unknown")) for item in evidence)
    by_course = Counter(str(item.metadata.get("course", "unknown")) for item in evidence)
    by_backend = Counter(str(item.metadata.get("parser_backend", "unknown")) for item in evidence)
    return {
        "evidence_documents": len(evidence),
        "source_files": len({item.metadata.get("source") for item in evidence}),
        "total_chars": sum(len(item.page_content) for item in evidence),
        "by_modality": dict(sorted(by_modality.items())),
        "by_evidence_kind": dict(sorted(by_kind.items())),
        "by_course": dict(sorted(by_course.items())),
        "by_parser_backend": dict(sorted(by_backend.items())),
    }


def source_name_from_source(source: Any) -> str | None:
    if source in {None, ""}:
        return None
    return str(source).replace("\\", "/").rsplit("/", 1)[-1]


def stable_hash(payload: Any, length: int = 16) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:length]
