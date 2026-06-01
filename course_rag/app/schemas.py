"""Pydantic schemas for the course RAG FastAPI service."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RetrievalStrategy = Literal["hybrid", "dense", "bm25"]


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
    retrieval_strategy: str | None = None
    retrievers: list[str] = Field(default_factory=list)
    dense_rank: int | None = None
    dense_score: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    pre_rerank_rank: int | None = None
    pre_rerank_score: float | None = None
    rerank_rank: int | None = None
    rerank_score: float | None = None
    rerank_model: str | None = None


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
    strategy: RetrievalStrategy = "hybrid"
    rrf_k: int = Field(default=60, ge=1, le=200)
    use_rerank: bool = True
    rerank_top_n: int = Field(default=20, ge=1, le=100)
    rerank_model: str = "BAAI/bge-reranker-base"
    rerank_batch_size: int = Field(default=8, ge=1, le=32)
    rerank_device: str = "auto"
    rerank_local_files_only: bool = True
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
    retrieval_strategy: str = "hybrid"
    retrievers: list[str] = Field(default_factory=list)
    use_rerank: bool = True
    rerank_used: bool = False
    rerank_model: str | None = None
    rerank_device: str | None = None
    rerank_error: str | None = None
    pipeline: list[str]
    index: IndexInfo


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    candidate_k: int | None = Field(default=None, ge=1, le=100)
    strategy: RetrievalStrategy = "hybrid"
    rrf_k: int = Field(default=60, ge=1, le=200)
    use_rerank: bool = True
    rerank_top_n: int = Field(default=20, ge=1, le=100)
    rerank_model: str = "BAAI/bge-reranker-base"
    rerank_batch_size: int = Field(default=8, ge=1, le=32)
    rerank_device: str = "auto"
    rerank_local_files_only: bool = True
    use_parent_context: bool = True
    min_chunk_chars: int = Field(default=20, ge=0)
    preview_chars: int = Field(default=220, ge=50, le=1000)


class SearchResponse(BaseModel):
    query: str
    citations: list[Citation]
    retrieval: list[RetrievalItem]
    strategy: str
    retrievers: list[str] = Field(default_factory=list)
    use_rerank: bool = True
    rerank_used: bool = False
    rerank_model: str | None = None
    rerank_device: str | None = None
    rerank_error: str | None = None
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
