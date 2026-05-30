"""Optional cross-encoder reranking for retrieved course chunks."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any

import numpy as np

from .indexing import configure_model_cache, default_model_cache_root


DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-base"
DEFAULT_RERANK_TOP_N = 20
DEFAULT_RERANK_BATCH_SIZE = 8
DEFAULT_RERANK_DEVICE = "auto"
DEFAULT_RERANK_MAX_LENGTH = 512

_RERANKER_CACHE: dict[tuple[str, str, int, str, bool], Any] = {}
_CACHE_LOCK = Lock()


@dataclass(frozen=True)
class RerankConfig:
    """Runtime settings for optional reranking."""

    model_name: str = DEFAULT_RERANK_MODEL
    top_n: int = DEFAULT_RERANK_TOP_N
    batch_size: int = DEFAULT_RERANK_BATCH_SIZE
    device: str = DEFAULT_RERANK_DEVICE
    max_length: int = DEFAULT_RERANK_MAX_LENGTH
    local_files_only: bool = True


@dataclass(frozen=True)
class RerankOutcome:
    """Rerank result plus diagnostics for API responses."""

    results: list[dict[str, Any]]
    used: bool
    model_name: str | None = None
    device: str | None = None
    error: str | None = None


def rerank_results(
    query: str,
    results: list[dict[str, Any]],
    *,
    config: RerankConfig,
) -> RerankOutcome:
    """Rerank recalled chunks, falling back to the original order on failure."""

    if not results:
        return RerankOutcome(results=results, used=False)
    if config.top_n <= 0:
        raise ValueError("rerank_top_n must be positive")
    if config.batch_size <= 0:
        raise ValueError("rerank_batch_size must be positive")
    if config.max_length <= 0:
        raise ValueError("rerank_max_length must be positive")

    try:
        device = resolve_rerank_device(config.device)
        reranker = get_reranker(config, device=device)
        candidate_count = min(config.top_n, len(results))
        candidates = [
            with_pre_rerank_fields(result, fallback_rank=index + 1)
            for index, result in enumerate(results[:candidate_count])
        ]
        tail = [
            with_pre_rerank_fields(result, fallback_rank=index + candidate_count + 1)
            for index, result in enumerate(results[candidate_count:])
        ]
        pairs = [[query, build_rerank_document_text(result)] for result in candidates]
        scores = normalize_scores(
            reranker.predict(
                pairs,
                batch_size=config.batch_size,
                show_progress_bar=False,
            ),
            expected=len(candidates),
        )
        reranked = apply_rerank_scores(
            candidates,
            scores,
            model_name=config.model_name,
        )
        ranked = reranked + tail
        for rank, result in enumerate(ranked, 1):
            result["rank"] = rank
        return RerankOutcome(
            results=ranked,
            used=True,
            model_name=config.model_name,
            device=device,
        )
    except Exception as exc:  # noqa: BLE001 - rerank must not block retrieval.
        return RerankOutcome(
            results=results,
            used=False,
            model_name=config.model_name,
            device=config.device,
            error=str(exc),
        )


def get_reranker(config: RerankConfig, *, device: str) -> Any:
    """Load and cache a sentence-transformers CrossEncoder reranker."""

    cache_root = default_model_cache_root()
    configure_model_cache(cache_root)
    cache_key = (
        config.model_name,
        device,
        config.max_length,
        cache_root.as_posix(),
        config.local_files_only,
    )
    with _CACHE_LOCK:
        reranker = _RERANKER_CACHE.get(cache_key)
        if reranker is None:
            from sentence_transformers import CrossEncoder

            reranker = CrossEncoder(
                config.model_name,
                device=device,
                cache_folder=str(cache_root),
                local_files_only=config.local_files_only,
                max_length=config.max_length,
            )
            _RERANKER_CACHE[cache_key] = reranker
        return reranker


def resolve_rerank_device(device: str) -> str:
    """Resolve auto device selection without requiring CUDA at import time."""

    normalized = device.strip().lower()
    if normalized == "auto":
        try:
            import torch
        except ImportError:
            return "cpu"
        return "cuda" if torch.cuda.is_available() else "cpu"
    return normalized


def with_pre_rerank_fields(
    result: dict[str, Any],
    *,
    fallback_rank: int,
) -> dict[str, Any]:
    copied = dict(result)
    copied.setdefault("pre_rerank_rank", result.get("rank") or fallback_rank)
    copied.setdefault("pre_rerank_score", result.get("score"))
    return copied


def apply_rerank_scores(
    candidates: list[dict[str, Any]],
    scores: list[float],
    *,
    model_name: str,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for result, score in zip(candidates, scores):
        copied = dict(result)
        copied["score"] = float(score)
        copied["rerank_score"] = float(score)
        copied["rerank_model"] = model_name
        scored.append(copied)

    ranked = sorted(
        scored,
        key=lambda item: (
            -float(item["rerank_score"]),
            int(item.get("pre_rerank_rank") or 1_000_000),
            rerank_chunk_key(item),
        ),
    )
    for rank, result in enumerate(ranked, 1):
        result["rerank_rank"] = rank
    return ranked


def normalize_scores(raw_scores: Any, *, expected: int) -> list[float]:
    array = np.asarray(raw_scores)
    if array.ndim == 0:
        scores = [float(array.item())]
    elif array.ndim == 2 and array.shape[1] == 1:
        scores = [float(value) for value in array[:, 0]]
    else:
        scores = [float(value) for value in array.reshape(-1)]

    if len(scores) != expected:
        raise ValueError(
            f"reranker returned {len(scores)} scores for {expected} candidates"
        )
    return scores


def build_rerank_document_text(result: dict[str, Any]) -> str:
    chunk = result.get("chunk", {})
    metadata = chunk.get("metadata", {})
    metadata_parts = [
        metadata.get("source_name"),
        metadata.get("course"),
        metadata.get("category"),
        metadata.get("section_path") or metadata.get("section"),
    ]
    parts = [
        str(part)
        for part in [*metadata_parts, chunk.get("page_content", "")]
        if part not in {None, ""}
    ]
    return "\n".join(parts)


def rerank_chunk_key(result: dict[str, Any]) -> str:
    metadata = result.get("chunk", {}).get("metadata", {})
    return str(
        metadata.get("chunk_id")
        or metadata.get("chunk_index")
        or f"{metadata.get('source')}:{metadata.get('page')}:{result.get('rank')}"
    )
