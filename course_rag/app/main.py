"""FastAPI service for the course RAG MVP."""

from __future__ import annotations

import sys
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .rag.generation import GenerationConfig, answer_question
from .rag.indexing import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_INDEX_DIR,
    CourseVectorIndex,
    build_or_load_vector_index,
    has_saved_index,
)
from .schemas import (
    AskRequest,
    AskResponse,
    HealthResponse,
    IndexInfo,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    citation_with_text,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
FRONTEND_DIST_DIR = STATIC_DIR / "frontend"

app = FastAPI(
    title="Course RAG API",
    description="FastAPI wrapper for the local course-material RAG MVP.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_index_lock = Lock()
_vector_index: CourseVectorIndex | None = None


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    """Serve the built Vue RAG workspace."""

    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(
            status_code=503,
            detail="Frontend build is missing. Run `npm run build` in course_rag/frontend.",
        )
    return FileResponse(index_file)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return service and vector-index status."""

    index_exists = has_saved_index(DEFAULT_INDEX_DIR)
    return HealthResponse(
        status="ok" if index_exists else "missing_index",
        index_exists=index_exists,
        index_loaded=_vector_index is not None,
        index=index_info(_vector_index) if _vector_index is not None else None,
    )


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """Answer a user question using retrieval plus optional LLM generation."""

    config = GenerationConfig(
        top_k=request.top_k,
        candidate_k=request.candidate_k,
        retrieval_strategy=request.strategy,
        rrf_k=request.rrf_k,
        use_rerank=request.use_rerank,
        rerank_top_n=request.rerank_top_n,
        rerank_model=request.rerank_model,
        rerank_batch_size=request.rerank_batch_size,
        rerank_device=request.rerank_device,
        rerank_local_files_only=request.rerank_local_files_only,
        min_chunk_chars=request.min_chunk_chars,
        max_context_chars=request.max_context_chars,
        max_context_chars_per_source=request.max_context_chars_per_source,
        preview_chars=request.preview_chars,
        use_parent_context=request.use_parent_context,
        use_llm=request.use_llm,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )
    try:
        result = answer_question(
            request.question,
            index_dir=DEFAULT_INDEX_DIR,
            embedding_model=DEFAULT_EMBEDDING_MODEL,
            config=config,
            vector_index=get_vector_index(),
        )
    except Exception as exc:  # noqa: BLE001 - convert service failures to API errors.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return AskResponse(**normalize_result(result))


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Return retrieval evidence without calling the LLM."""

    config = GenerationConfig(
        top_k=request.top_k,
        candidate_k=request.candidate_k,
        retrieval_strategy=request.strategy,
        rrf_k=request.rrf_k,
        use_rerank=request.use_rerank,
        rerank_top_n=request.rerank_top_n,
        rerank_model=request.rerank_model,
        rerank_batch_size=request.rerank_batch_size,
        rerank_device=request.rerank_device,
        rerank_local_files_only=request.rerank_local_files_only,
        min_chunk_chars=request.min_chunk_chars,
        preview_chars=request.preview_chars,
        use_parent_context=request.use_parent_context,
        use_llm=False,
    )
    try:
        result = answer_question(
            request.query,
            index_dir=DEFAULT_INDEX_DIR,
            embedding_model=DEFAULT_EMBEDDING_MODEL,
            config=config,
            vector_index=get_vector_index(),
        )
    except Exception as exc:  # noqa: BLE001 - convert service failures to API errors.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    normalized = normalize_result(result)
    return SearchResponse(
        query=request.query,
        citations=normalized["citations"],
        retrieval=normalized["retrieval"],
        strategy=normalized.get("retrieval_strategy", request.strategy),
        retrievers=normalized.get("retrievers", []),
        use_rerank=normalized.get("use_rerank", request.use_rerank),
        rerank_used=normalized.get("rerank_used", False),
        rerank_model=normalized.get("rerank_model"),
        rerank_device=normalized.get("rerank_device"),
        rerank_error=normalized.get("rerank_error"),
        top_k=request.top_k,
        pipeline=normalized["pipeline"],
        index=normalized["index"],
    )


@app.post("/ingest", response_model=IngestResponse)
def ingest(request: IngestRequest) -> IngestResponse:
    """Load the saved index or rebuild it from the current corpus."""

    try:
        vector_index = refresh_vector_index(rebuild=request.rebuild)
    except Exception as exc:  # noqa: BLE001 - convert service failures to API errors.
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    action = "rebuilt" if request.rebuild else "loaded"
    return IngestResponse(
        status="ok",
        message=f"Vector index {action}.",
        index=index_info(vector_index),
    )


def get_vector_index() -> CourseVectorIndex:
    global _vector_index
    if _vector_index is not None:
        return _vector_index

    with _index_lock:
        if _vector_index is None:
            _vector_index = build_or_load_vector_index(
                index_dir=DEFAULT_INDEX_DIR,
                model_name=DEFAULT_EMBEDDING_MODEL,
                show_progress_bar=False,
            )
    return _vector_index


def refresh_vector_index(*, rebuild: bool) -> CourseVectorIndex:
    global _vector_index
    with _index_lock:
        _vector_index = build_or_load_vector_index(
            index_dir=DEFAULT_INDEX_DIR,
            model_name=DEFAULT_EMBEDDING_MODEL,
            rebuild=rebuild,
            show_progress_bar=False,
        )
    return _vector_index


def normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    normalized["citations"] = [
        citation_with_text(citation)
        for citation in normalized.get("citations", [])
    ]
    normalized["retrieval"] = [
        citation_with_text(item)
        for item in normalized.get("retrieval", [])
    ]
    return normalized


def index_info(vector_index: CourseVectorIndex) -> IndexInfo:
    return IndexInfo(
        index_dir=safe_path(DEFAULT_INDEX_DIR),
        vectors=vector_index.index.ntotal,
        embedding_model=vector_index.metadata.get("embedding_model"),
    )


def safe_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def main() -> None:
    import uvicorn

    uvicorn.run("course_rag.app.main:app", host="127.0.0.1", port=8000, reload=False)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    configure_stdio()
    main()
