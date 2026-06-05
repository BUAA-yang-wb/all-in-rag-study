"""Milvus-backed dense, BM25, and hybrid retrieval."""

from __future__ import annotations

from threading import Lock
from typing import Any, Literal
from weakref import WeakKeyDictionary

try:
    from .milvus_index import MilvusTextIndex
except ImportError:
    from milvus_index import MilvusTextIndex  # type: ignore


RetrievalStrategy = Literal["hybrid", "dense", "bm25"]
DEFAULT_RETRIEVAL_STRATEGY: RetrievalStrategy = "hybrid"
DEFAULT_RRF_K = 60
DEFAULT_CANDIDATE_MULTIPLIER = 4
DEFAULT_MIN_CANDIDATES = 30

_RETRIEVER_CACHE: WeakKeyDictionary[MilvusTextIndex, "CourseRetriever"] = WeakKeyDictionary()
_CACHE_LOCK = Lock()


class CourseRetriever:
    """Thin strategy adapter over Milvus dense/BM25/hybrid retrieval."""

    def __init__(self, vector_index: MilvusTextIndex) -> None:
        self.vector_index = vector_index

    def search(
        self,
        query: str,
        *,
        strategy: RetrievalStrategy = DEFAULT_RETRIEVAL_STRATEGY,
        top_k: int = 5,
        rrf_k: int = DEFAULT_RRF_K,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search with the selected retrieval strategy."""

        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if rrf_k <= 0:
            raise ValueError("rrf_k must be positive")

        filter_expr = milvus_filter_expression(filters or {})
        if strategy == "dense":
            return self.dense_search(query, top_k=top_k, filter_expr=filter_expr)
        if strategy == "bm25":
            return self.bm25_search(query, top_k=top_k, filter_expr=filter_expr)
        if strategy == "hybrid":
            return self.hybrid_search(query, top_k=top_k, rrf_k=rrf_k, filter_expr=filter_expr)
        raise ValueError(f"unsupported retrieval strategy: {strategy}")

    def dense_search(self, query: str, *, top_k: int, filter_expr: str = "") -> list[dict[str, Any]]:
        results = self.vector_index.search(
            query,
            top_k=top_k,
            mode="dense",
            filter_expr=filter_expr,
        )
        return [
            enrich_retrieval_result(
                result,
                strategy="dense",
                retrievers=["dense"],
                dense_rank=result.get("rank"),
                dense_score=result.get("score"),
            )
            for result in results
        ]

    def bm25_search(self, query: str, *, top_k: int, filter_expr: str = "") -> list[dict[str, Any]]:
        results = self.vector_index.search(
            query,
            top_k=top_k,
            mode="bm25",
            filter_expr=filter_expr,
        )
        return [
            enrich_retrieval_result(
                result,
                strategy="bm25",
                retrievers=["bm25"],
                bm25_rank=result.get("rank"),
                bm25_score=result.get("score"),
            )
            for result in results
        ]

    def hybrid_search(
        self,
        query: str,
        *,
        top_k: int,
        rrf_k: int = DEFAULT_RRF_K,
        filter_expr: str = "",
    ) -> list[dict[str, Any]]:
        results = self.vector_index.search(
            query,
            top_k=top_k,
            mode="hybrid",
            rrf_k=rrf_k,
            filter_expr=filter_expr,
        )
        return [
            enrich_retrieval_result(
                result,
                strategy="hybrid",
                retrievers=["dense", "bm25"],
                rrf_score=result.get("score"),
            )
            for result in results
        ]


def get_course_retriever(vector_index: MilvusTextIndex) -> CourseRetriever:
    """Return a cached retriever for the loaded Milvus index."""

    with _CACHE_LOCK:
        retriever = _RETRIEVER_CACHE.get(vector_index)
        if retriever is None:
            retriever = CourseRetriever(vector_index)
            _RETRIEVER_CACHE[vector_index] = retriever
        return retriever


def default_candidate_k(top_k: int) -> int:
    return max(top_k * DEFAULT_CANDIDATE_MULTIPLIER, DEFAULT_MIN_CANDIDATES)


def enrich_retrieval_result(
    result: dict[str, Any],
    *,
    strategy: RetrievalStrategy,
    retrievers: list[str],
    dense_rank: int | None = None,
    dense_score: float | None = None,
    bm25_rank: int | None = None,
    bm25_score: float | None = None,
    rrf_score: float | None = None,
) -> dict[str, Any]:
    enriched = dict(result)
    enriched.update(
        {
            "retrieval_strategy": strategy,
            "retrievers": retrievers,
            "dense_rank": dense_rank,
            "dense_score": dense_score,
            "bm25_rank": bm25_rank,
            "bm25_score": bm25_score,
            "rrf_score": rrf_score,
        }
    )
    return enriched


def milvus_filter_expression(filters: dict[str, Any]) -> str:
    """Build a Milvus scalar filter from explicit metadata filters."""

    supported_fields = {
        "course",
        "category",
        "source_name",
        "page",
        "modality",
        "evidence_kind",
    }
    expressions: list[str] = []
    for key, value in filters.items():
        if key not in supported_fields or value in {None, ""}:
            continue
        expressions.append(f'{key} == "{escape_filter_value(value)}"')
    return " and ".join(expressions)


def escape_filter_value(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')
