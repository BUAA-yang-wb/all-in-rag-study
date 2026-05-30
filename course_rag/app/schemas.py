"""Pydantic schemas for the course RAG FastAPI service."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Citation(BaseModel):
    id: int
    rank: int | None = None
    score: float
    source: str | None = None
    source_name: str | None = None
    course: str | None = None
    category: str | None = None
    page: int | str | None = None
    section: str | None = None
    section_path: str | None = None
    chunk_id: str | None = None
    parent_doc_id: str | None = None
    text: str | None = Field(default=None, description="Matched chunk preview.")
    chunk_preview: str | None = None


class RetrievalItem(Citation):
    context_preview: str | None = None


class IndexInfo(BaseModel):
    index_dir: str
    vectors: int
    embedding_model: str | None = None


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    candidate_k: int | None = Field(default=None, ge=1, le=100)
    use_llm: bool = True
    use_parent_context: bool = True
    min_chunk_chars: int = Field(default=20, ge=0)
    max_context_chars: int = Field(default=6000, ge=500)
    max_context_chars_per_source: int = Field(default=1600, ge=200)
    preview_chars: int = Field(default=220, ge=50, le=1000)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1500, ge=128, le=4096)


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: list[Citation]
    retrieval: list[RetrievalItem]
    used_llm: bool
    llm_error: str | None = None
    pipeline: list[str]
    index: IndexInfo


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    candidate_k: int | None = Field(default=None, ge=1, le=100)
    use_parent_context: bool = True
    min_chunk_chars: int = Field(default=20, ge=0)
    preview_chars: int = Field(default=220, ge=50, le=1000)


class SearchResponse(BaseModel):
    query: str
    citations: list[Citation]
    retrieval: list[RetrievalItem]
    strategy: str
    top_k: int
    pipeline: list[str]
    index: IndexInfo


class IngestRequest(BaseModel):
    rebuild: bool = False


class IngestResponse(BaseModel):
    status: str
    message: str
    index: IndexInfo | None = None


class HealthResponse(BaseModel):
    status: str
    index_exists: bool
    index_loaded: bool
    index: IndexInfo | None = None


def citation_with_text(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep Day07 chunk_preview while exposing Day08's text field."""

    normalized = dict(payload)
    normalized.setdefault("text", normalized.get("chunk_preview"))
    return normalized
