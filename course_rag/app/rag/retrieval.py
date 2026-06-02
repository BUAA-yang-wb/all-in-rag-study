"""Hybrid retrieval over the persisted course FAISS index."""

from __future__ import annotations

import re
import unicodedata
from threading import Lock
from typing import Any, Literal
from weakref import WeakKeyDictionary

import numpy as np
from rank_bm25 import BM25Okapi

from .indexing import CourseVectorIndex, preview_text, summarize_chunk_source


RetrievalStrategy = Literal["hybrid", "dense", "bm25"]
DEFAULT_RETRIEVAL_STRATEGY: RetrievalStrategy = "hybrid"
DEFAULT_RRF_K = 60
DEFAULT_CANDIDATE_MULTIPLIER = 4
DEFAULT_MIN_CANDIDATES = 30

TOKEN_PATTERN = re.compile(
    r"[A-Za-z]+(?:/[A-Za-z]+)*(?:\d+)?|\d+(?:\.\d+)*|[\u4e00-\u9fff]+"
)
ALNUM_PATTERN = re.compile(r"^([a-z]+)(\d+)$")

_RETRIEVER_CACHE: WeakKeyDictionary[CourseVectorIndex, "CourseRetriever"] = WeakKeyDictionary()
_CACHE_LOCK = Lock()


class CourseRetriever:
    """Dense, BM25, and RRF-fused retrieval for a loaded course index."""

    def __init__(self, vector_index: CourseVectorIndex) -> None:
        self.vector_index = vector_index
        self._bm25_corpus = [
            tokenize_for_bm25(build_bm25_document_text(chunk.to_dict()))
            for chunk in vector_index.chunks
        ]
        self._bm25 = BM25Okapi(self._bm25_corpus)

    def search(
        self,
        query: str,
        *,
        strategy: RetrievalStrategy = DEFAULT_RETRIEVAL_STRATEGY,
        top_k: int = 5,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> list[dict[str, Any]]:
        """Search with the selected retrieval strategy."""

        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if rrf_k <= 0:
            raise ValueError("rrf_k must be positive")

        if strategy == "dense":
            return self.dense_search(query, top_k=top_k)
        if strategy == "bm25":
            return self.bm25_search(query, top_k=top_k)
        if strategy == "hybrid":
            return self.hybrid_search(query, top_k=top_k, rrf_k=rrf_k)
        raise ValueError(f"unsupported retrieval strategy: {strategy}")

    def dense_search(self, query: str, *, top_k: int) -> list[dict[str, Any]]:
        results = self.vector_index.search(query, top_k=top_k)
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

    def bm25_search(self, query: str, *, top_k: int) -> list[dict[str, Any]]:
        tokens = tokenize_for_bm25(query)
        if not tokens or not self.vector_index.chunks:
            return []

        scores = self._bm25.get_scores(tokens)
        if len(scores) == 0:
            return []

        ranked_indices = np.argsort(scores)[::-1]
        results: list[dict[str, Any]] = []
        for index_id in ranked_indices:
            score = float(scores[int(index_id)])
            if score <= 0:
                break

            chunk = self.vector_index.chunks[int(index_id)]
            rank = len(results) + 1
            result = {
                "rank": rank,
                "score": score,
                "chunk": chunk.to_dict(),
                "source": summarize_chunk_source(chunk),
                "preview": preview_text(chunk.page_content),
            }
            results.append(
                enrich_retrieval_result(
                    result,
                    strategy="bm25",
                    retrievers=["bm25"],
                    bm25_rank=rank,
                    bm25_score=score,
                )
            )
            if len(results) >= top_k:
                break

        return results

    def hybrid_search(
        self,
        query: str,
        *,
        top_k: int,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> list[dict[str, Any]]:
        candidate_k = min(
            len(self.vector_index.chunks),
            max(top_k * DEFAULT_CANDIDATE_MULTIPLIER, DEFAULT_MIN_CANDIDATES),
        )
        dense_results = self.dense_search(query, top_k=candidate_k)
        bm25_results = self.bm25_search(query, top_k=candidate_k)

        fused: dict[str, dict[str, Any]] = {}
        add_rrf_results(fused, dense_results, retriever="dense", rrf_k=rrf_k)
        add_rrf_results(fused, bm25_results, retriever="bm25", rrf_k=rrf_k)

        ranked = sorted(
            fused.values(),
            key=lambda item: (
                -float(item["rrf_score"]),
                min_rank(item),
                chunk_key(item["result"]),
            ),
        )

        results: list[dict[str, Any]] = []
        for final_rank, item in enumerate(ranked[:top_k], 1):
            result = dict(item["result"])
            result.update(
                {
                    "rank": final_rank,
                    "score": float(item["rrf_score"]),
                    "retrieval_strategy": "hybrid",
                    "retrievers": sorted(item["retrievers"]),
                    "dense_rank": item.get("dense_rank"),
                    "dense_score": item.get("dense_score"),
                    "bm25_rank": item.get("bm25_rank"),
                    "bm25_score": item.get("bm25_score"),
                    "rrf_score": float(item["rrf_score"]),
                }
            )
            results.append(result)

        return results


def get_course_retriever(vector_index: CourseVectorIndex) -> CourseRetriever:
    """Return a cached retriever for the loaded vector index."""

    with _CACHE_LOCK:
        retriever = _RETRIEVER_CACHE.get(vector_index)
        if retriever is None:
            retriever = CourseRetriever(vector_index)
            _RETRIEVER_CACHE[vector_index] = retriever
        return retriever


def default_candidate_k(top_k: int) -> int:
    return max(top_k * DEFAULT_CANDIDATE_MULTIPLIER, DEFAULT_MIN_CANDIDATES)


def build_bm25_document_text(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata", {})
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
        for part in [chunk.get("page_content", ""), *metadata_parts]
        if part not in {None, ""}
    )


def tokenize_for_bm25(text: str) -> list[str]:
    """Tokenize Chinese course text without adding a segmenter dependency."""

    normalized = unicodedata.normalize("NFKC", str(text)).lower()
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer(normalized):
        term = match.group(0)
        if contains_cjk(term):
            tokens.extend(chinese_ngrams(term))
            continue

        tokens.append(term)
        if "/" in term:
            parts = [part for part in term.split("/") if part]
            tokens.extend(parts)
            tokens.append("".join(parts))

        alnum_match = ALNUM_PATTERN.match(term)
        if alnum_match:
            tokens.extend(alnum_match.groups())

    return tokens


def chinese_ngrams(text: str) -> list[str]:
    if len(text) <= 1:
        return [text]

    grams: list[str] = []
    for width in (2, 3):
        if len(text) >= width:
            grams.extend(text[index : index + width] for index in range(len(text) - width + 1))
    return grams


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


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


def add_rrf_results(
    fused: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
    *,
    retriever: Literal["dense", "bm25"],
    rrf_k: int,
) -> None:
    for result in results:
        rank = int(result.get("rank") or 0)
        if rank <= 0:
            continue

        key = chunk_key(result)
        item = fused.setdefault(
            key,
            {
                "result": result,
                "retrievers": set(),
                "rrf_score": 0.0,
                "dense_rank": None,
                "dense_score": None,
                "bm25_rank": None,
                "bm25_score": None,
            },
        )
        item["retrievers"].add(retriever)
        item["rrf_score"] += 1.0 / (rrf_k + rank)
        item[f"{retriever}_rank"] = rank
        item[f"{retriever}_score"] = result.get("score")


def chunk_key(result: dict[str, Any]) -> str:
    metadata = result.get("chunk", {}).get("metadata", {})
    return str(
        metadata.get("chunk_id")
        or metadata.get("chunk_index")
        or f"{metadata.get('source')}:{metadata.get('page')}:{result.get('rank')}"
    )


def min_rank(item: dict[str, Any]) -> int:
    ranks = [
        rank
        for rank in (item.get("dense_rank"), item.get("bm25_rank"))
        if isinstance(rank, int)
    ]
    return min(ranks) if ranks else 1_000_000
