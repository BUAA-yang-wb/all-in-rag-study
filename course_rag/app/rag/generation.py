"""Question answering over the local course RAG vector index."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .indexing import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_INDEX_DIR,
    CourseVectorIndex,
    build_or_load_vector_index,
)
from .milvus_index import (
    DEFAULT_MILVUS_COLLECTION,
    DEFAULT_MILVUS_URI,
    MilvusTextIndex,
    build_or_load_milvus_text_index,
)
from .retrieval import (
    DEFAULT_RETRIEVAL_STRATEGY,
    DEFAULT_RRF_K,
    CourseRetriever,
    RetrievalStrategy,
    default_candidate_k,
    get_course_retriever,
)
from .rerank import (
    DEFAULT_RERANK_BATCH_SIZE,
    DEFAULT_RERANK_DEVICE,
    DEFAULT_RERANK_MODEL,
    DEFAULT_RERANK_TOP_N,
    RerankConfig,
    rerank_results,
)
from .routing import (
    MetadataFilters,
    apply_metadata_routing,
    build_query_route,
    build_routed_retrieval_query,
)


DEFAULT_LLM_MODEL = "deepseek-v4-pro"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com"
DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY_RAGLEARN"
IndexBackend = Literal["faiss", "milvus"]


@dataclass(frozen=True)
class GenerationConfig:
    """Runtime settings for one RAG answer request."""

    index_backend: IndexBackend = "milvus"
    milvus_uri: str = DEFAULT_MILVUS_URI
    milvus_collection: str = DEFAULT_MILVUS_COLLECTION
    top_k: int = 5
    candidate_k: int | None = None
    retrieval_strategy: RetrievalStrategy = DEFAULT_RETRIEVAL_STRATEGY
    rrf_k: int = DEFAULT_RRF_K
    min_chunk_chars: int = 20
    max_context_chars: int = 6_000
    max_context_chars_per_source: int = 1_600
    preview_chars: int = 220
    use_rerank: bool = True
    rerank_top_n: int = DEFAULT_RERANK_TOP_N
    rerank_model: str = DEFAULT_RERANK_MODEL
    rerank_batch_size: int = DEFAULT_RERANK_BATCH_SIZE
    rerank_device: str = DEFAULT_RERANK_DEVICE
    rerank_local_files_only: bool = True
    use_parent_context: bool = True
    use_llm: bool = True
    llm_model: str = DEFAULT_LLM_MODEL
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    api_key_env: str = DEFAULT_API_KEY_ENV
    temperature: float = 0.1
    max_tokens: int = 1_500
    use_metadata_routing: bool = True
    course: str | None = None
    category: str | None = None
    source_name: str | None = None
    page: int | str | None = None
    modality: str | None = None
    evidence_kind: str | None = None


def answer_question(
    question: str,
    *,
    index_dir: Path = DEFAULT_INDEX_DIR,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    config: GenerationConfig | None = None,
    vector_index: Any | None = None,
    retriever: CourseRetriever | None = None,
) -> dict[str, Any]:
    """Retrieve course contexts, generate an answer, and return citations."""

    if not question.strip():
        raise ValueError("question must not be empty")

    selected_config = config or GenerationConfig()
    active_index = vector_index or load_index_for_backend(
        index_backend=selected_config.index_backend,
        index_dir=index_dir,
        embedding_model=embedding_model,
        milvus_uri=selected_config.milvus_uri,
        milvus_collection=selected_config.milvus_collection,
    )

    active_retriever = retriever or get_course_retriever(active_index)
    candidate_k = selected_config.candidate_k or default_candidate_k(selected_config.top_k)
    route = build_query_route(
        question,
        active_index,
        explicit_filters=MetadataFilters(
            course=selected_config.course,
            category=selected_config.category,
            source_name=selected_config.source_name,
            page=selected_config.page,
            modality=selected_config.modality,
            evidence_kind=selected_config.evidence_kind,
        ),
        enabled=selected_config.use_metadata_routing,
    )
    if (
        selected_config.use_metadata_routing
        and route.active
        and selected_config.candidate_k is None
    ):
        candidate_k = min(len(active_index.chunks), max(candidate_k, 100))

    retrieval_query = build_routed_retrieval_query(question, route)
    raw_results = active_retriever.search(
        retrieval_query,
        strategy=selected_config.retrieval_strategy,
        top_k=candidate_k,
        rrf_k=selected_config.rrf_k,
    )
    raw_results, routing_debug = apply_metadata_routing(raw_results, route)
    had_rerank_candidates = bool(raw_results)
    rerank_error: str | None = None
    rerank_used = False
    rerank_model: str | None = None
    rerank_device: str | None = None
    if selected_config.use_rerank and raw_results:
        rerank_outcome = rerank_results(
            question,
            raw_results,
            config=RerankConfig(
                model_name=selected_config.rerank_model,
                top_n=selected_config.rerank_top_n,
                batch_size=selected_config.rerank_batch_size,
                device=selected_config.rerank_device,
                local_files_only=selected_config.rerank_local_files_only,
            ),
        )
        raw_results = rerank_outcome.results
        rerank_error = rerank_outcome.error
        rerank_used = rerank_outcome.used
        rerank_model = rerank_outcome.model_name
        rerank_device = rerank_outcome.device

    contexts = select_contexts(
        active_index,
        raw_results,
        top_k=selected_config.top_k,
        min_chunk_chars=selected_config.min_chunk_chars,
        use_parent_context=selected_config.use_parent_context,
        preview_chars=selected_config.preview_chars,
    )
    contexts = trim_contexts(
        contexts,
        max_total_chars=selected_config.max_context_chars,
        max_chars_per_source=selected_config.max_context_chars_per_source,
    )

    llm_error: str | None = None
    used_llm = False
    if selected_config.use_llm and contexts:
        try:
            answer = generate_with_llm(question, contexts, selected_config)
            used_llm = True
        except Exception as exc:  # noqa: BLE001 - CLI should still return useful evidence.
            llm_error = str(exc)
            answer = build_retrieval_only_answer(question, contexts, llm_error=llm_error)
    else:
        answer = build_retrieval_only_answer(question, contexts, llm_error=llm_error)

    return {
        "question": question,
        "answer": answer,
        "citations": [context["citation"] for context in contexts],
        "retrieval": [
            {
                **context["citation"],
                "context_preview": preview_text(
                    context["context_text"],
                    max_chars=selected_config.preview_chars,
                ),
            }
            for context in contexts
        ],
        "used_llm": used_llm,
        "llm_error": llm_error,
        "retrieval_strategy": selected_config.retrieval_strategy,
        "retrievers": retrievers_for_strategy(selected_config.retrieval_strategy),
        "use_rerank": selected_config.use_rerank,
        "rerank_used": rerank_used,
        "rerank_model": rerank_model or selected_config.rerank_model,
        "rerank_device": rerank_device or selected_config.rerank_device,
        "rerank_error": rerank_error,
        "routing": routing_debug,
        "pipeline": [
            f"load_{index_backend_name(active_index, selected_config)}_index",
            *retrieval_pipeline_steps(
                selected_config.retrieval_strategy,
                index_backend=index_backend_name(active_index, selected_config),
            ),
            *metadata_routing_pipeline_steps(routing_debug),
            *rerank_pipeline_steps(
                use_rerank=selected_config.use_rerank,
                rerank_used=rerank_used,
                rerank_error=rerank_error,
                had_results=had_rerank_candidates,
            ),
            "filter_short_chunks",
            "deduplicate_by_parent",
            "assemble_context",
            "llm_generation" if used_llm else "retrieval_only_fallback",
        ],
        "index": {
            "index_dir": safe_path(index_dir),
            "vectors": active_index.index.ntotal,
            "embedding_model": active_index.metadata.get("embedding_model"),
            "backend": index_backend_name(active_index, selected_config),
            "collection_name": active_index.metadata.get("milvus_collection"),
            "milvus_uri": active_index.metadata.get("milvus_uri"),
        },
    }


def load_index_for_backend(
    *,
    index_backend: IndexBackend,
    index_dir: Path,
    embedding_model: str,
    milvus_uri: str,
    milvus_collection: str,
) -> Any:
    if index_backend == "faiss":
        return build_or_load_vector_index(
            index_dir=index_dir,
            model_name=embedding_model,
            show_progress_bar=False,
        )
    if index_backend == "milvus":
        return build_or_load_milvus_text_index(
            index_dir=index_dir,
            model_name=embedding_model,
            uri=milvus_uri,
            collection_name=milvus_collection,
        )
    raise ValueError(f"unsupported index_backend: {index_backend}")


def select_contexts(
    vector_index: CourseVectorIndex,
    raw_results: list[dict[str, Any]],
    *,
    top_k: int,
    min_chunk_chars: int,
    use_parent_context: bool,
    preview_chars: int,
) -> list[dict[str, Any]]:
    """Select citation-bearing contexts from raw vector search results."""

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    contexts = _select_contexts_once(
        vector_index,
        raw_results,
        top_k=top_k,
        min_chunk_chars=min_chunk_chars,
        use_parent_context=use_parent_context,
        preview_chars=preview_chars,
    )
    if contexts:
        return contexts

    return _select_contexts_once(
        vector_index,
        raw_results,
        top_k=top_k,
        min_chunk_chars=0,
        use_parent_context=use_parent_context,
        preview_chars=preview_chars,
    )


def _select_contexts_once(
    vector_index: CourseVectorIndex,
    raw_results: list[dict[str, Any]],
    *,
    top_k: int,
    min_chunk_chars: int,
    use_parent_context: bool,
    preview_chars: int,
) -> list[dict[str, Any]]:
    parent_by_id = {
        parent.metadata.get("parent_doc_id"): parent
        for parent in vector_index.parents
    }
    contexts: list[dict[str, Any]] = []
    seen_context_ids: set[str] = set()

    for result in raw_results:
        chunk = result["chunk"]
        chunk_text = chunk.get("page_content", "")
        chunk_metadata = chunk.get("metadata", {})
        if visible_text_len(chunk_text) < min_chunk_chars:
            continue

        parent_id = chunk_metadata.get("parent_doc_id")
        parent = parent_by_id.get(parent_id)
        if use_parent_context and parent is not None:
            context_id = str(parent_id)
            context_text = parent.page_content
            context_metadata = parent.metadata
        else:
            context_id = str(chunk_metadata.get("chunk_id") or result.get("rank"))
            context_text = chunk_text
            context_metadata = chunk_metadata

        if context_id in seen_context_ids:
            continue
        seen_context_ids.add(context_id)

        citation_index = len(contexts) + 1
        contexts.append(
            {
                "context_text": context_text,
                "citation": build_citation(
                    citation_index,
                    result,
                    chunk_text=chunk_text,
                    chunk_metadata=chunk_metadata,
                    context_metadata=context_metadata,
                    preview_chars=preview_chars,
                ),
            }
        )
        if len(contexts) >= top_k:
            break

    return contexts


def build_citation(
    citation_index: int,
    result: dict[str, Any],
    *,
    chunk_text: str,
    chunk_metadata: dict[str, Any],
    context_metadata: dict[str, Any],
    preview_chars: int,
) -> dict[str, Any]:
    source = context_metadata.get("source") or chunk_metadata.get("source")
    page = context_metadata.get("page", chunk_metadata.get("page"))
    section_path = context_metadata.get("section_path") or chunk_metadata.get("section_path")
    section = context_metadata.get("section") or chunk_metadata.get("section")

    return {
        "id": citation_index,
        "rank": result.get("rank"),
        "score": round(float(result.get("score", 0.0)), 4),
        "evidence_id": metadata_value("evidence_id", context_metadata, chunk_metadata),
        "source_doc_id": metadata_value("source_doc_id", context_metadata, chunk_metadata),
        "modality": metadata_value("modality", context_metadata, chunk_metadata),
        "evidence_kind": metadata_value("evidence_kind", context_metadata, chunk_metadata),
        "asset_path": metadata_value("asset_path", context_metadata, chunk_metadata),
        "parser_backend": metadata_value("parser_backend", context_metadata, chunk_metadata),
        "context_before": metadata_value("context_before", context_metadata, chunk_metadata),
        "context_after": metadata_value("context_after", context_metadata, chunk_metadata),
        "source": source,
        "source_name": context_metadata.get("source_name") or chunk_metadata.get("source_name"),
        "course": context_metadata.get("course") or chunk_metadata.get("course"),
        "category": context_metadata.get("category") or chunk_metadata.get("category"),
        "page": page,
        "section": section,
        "section_path": section_path,
        "chunk_id": chunk_metadata.get("chunk_id"),
        "parent_doc_id": chunk_metadata.get("parent_doc_id"),
        "chunk_preview": preview_text(chunk_text, max_chars=preview_chars),
        "retrieval_strategy": result.get("retrieval_strategy"),
        "retrievers": result.get("retrievers") or [],
        "dense_rank": result.get("dense_rank"),
        "dense_score": round_optional(result.get("dense_score"), digits=4),
        "bm25_rank": result.get("bm25_rank"),
        "bm25_score": round_optional(result.get("bm25_score"), digits=4),
        "rrf_score": round_optional(result.get("rrf_score"), digits=6),
        "pre_rerank_rank": result.get("pre_rerank_rank"),
        "pre_rerank_score": round_optional(result.get("pre_rerank_score"), digits=4),
        "rerank_rank": result.get("rerank_rank"),
        "rerank_score": round_optional(result.get("rerank_score"), digits=4),
        "rerank_model": result.get("rerank_model"),
        "pre_routing_rank": result.get("pre_routing_rank"),
        "pre_routing_score": round_optional(result.get("pre_routing_score"), digits=4),
        "metadata_filter_match": result.get("metadata_filter_match"),
        "metadata_boost": round_optional(result.get("metadata_boost"), digits=4),
        "matched_filters": result.get("matched_filters") or [],
        "matched_intents": result.get("matched_intents") or [],
    }


def metadata_value(
    key: str,
    context_metadata: dict[str, Any],
    chunk_metadata: dict[str, Any],
) -> Any:
    return context_metadata.get(key) if context_metadata.get(key) is not None else chunk_metadata.get(key)


def trim_contexts(
    contexts: list[dict[str, Any]],
    *,
    max_total_chars: int,
    max_chars_per_source: int,
) -> list[dict[str, Any]]:
    """Bound the prompt context while preserving citation order."""

    trimmed: list[dict[str, Any]] = []
    total_chars = 0
    for context in contexts:
        text = context["context_text"].strip()
        if len(text) > max_chars_per_source:
            text = text[: max_chars_per_source - 3].rstrip() + "..."
        remaining = max_total_chars - total_chars
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[: max(0, remaining - 3)].rstrip() + "..."

        copied = dict(context)
        copied["context_text"] = text
        trimmed.append(copied)
        total_chars += len(text)

    return trimmed


def generate_with_llm(
    question: str,
    contexts: list[dict[str, Any]],
    config: GenerationConfig,
) -> str:
    """Call the configured DeepSeek-compatible chat model."""

    load_dotenv_if_available()
    api_key = os.getenv(config.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing API key environment variable: {config.api_key_env}")

    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=config.llm_model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        api_key=api_key,
        base_url=config.llm_base_url,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是课程资料 RAG 问答助手。只根据给定资料回答。"
                "如果资料不足以回答，就明确说资料不足，并说明已经检索到的相关线索。"
                "不要编造课程资料中没有的信息。回答中必须使用 [1]、[2] 这样的编号标注引用来源。",
            ),
            (
                "human",
                "用户问题：{question}\n\n检索资料：\n{context}\n\n"
                "请给出完整的中文回答（默认简洁一些，除非用户要求详细），并在相关结论后标注引用编号。",
            ),
        ]
    )
    chain = prompt | llm | StrOutputParser()
    return chain.invoke(
        {
            "question": question,
            "context": format_context_for_prompt(contexts),
        }
    ).strip()


def format_context_for_prompt(contexts: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for context in contexts:
        citation = context["citation"]
        parts.append(
            "\n".join(
                [
                    f"[{citation['id']}] {format_source_location(citation)}",
                    f"score={citation['score']}",
                    context["context_text"],
                ]
            )
        )
    return "\n\n---\n\n".join(parts)


def build_retrieval_only_answer(
    question: str,
    contexts: list[dict[str, Any]],
    *,
    llm_error: str | None,
) -> str:
    if not contexts:
        return (
            "没有检索到足够相关的课程片段，暂时无法基于资料回答。"
            f"\n\n问题：{question}"
        )

    reason = "未调用 LLM" if llm_error is None else f"LLM 调用失败：{llm_error}"
    lines = [
        f"{reason}。下面返回最相关的检索片段，供调试和人工判断：",
        "",
    ]
    for context in contexts:
        citation = context["citation"]
        lines.append(f"[{citation['id']}] {format_source_location(citation)}")
        lines.append(citation["chunk_preview"])
        lines.append("")
    return "\n".join(lines).strip()


def format_source_location(citation: dict[str, Any]) -> str:
    source_name = citation.get("source_name") or citation.get("source") or "unknown source"
    parts = [str(source_name)]
    if citation.get("page") not in {None, ""}:
        parts.append(f"page {citation['page']}")
    section = citation.get("section_path") or citation.get("section")
    if section:
        parts.append(str(section))
    return " | ".join(parts)


def preview_text(text: str, *, max_chars: int = 220) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def visible_text_len(text: str) -> int:
    return len("".join(str(text).split()))


def retrieval_pipeline_steps(
    strategy: RetrievalStrategy,
    *,
    index_backend: str,
) -> list[str]:
    dense_step = (
        "milvus_candidate_search"
        if index_backend == "milvus"
        else "faiss_candidate_search"
    )
    if strategy == "dense":
        return ["encode_query", dense_step]
    if strategy == "bm25":
        return ["bm25_tokenize_query", "bm25_candidate_search"]
    return [
        "encode_query",
        dense_step,
        "bm25_candidate_search",
        "rrf_fusion",
    ]


def rerank_pipeline_steps(
    *,
    use_rerank: bool,
    rerank_used: bool,
    rerank_error: str | None,
    had_results: bool,
) -> list[str]:
    if not use_rerank or not had_results:
        return []
    if rerank_used:
        return ["rerank_candidates"]
    if rerank_error:
        return ["rerank_failed_fallback"]
    return []


def metadata_routing_pipeline_steps(routing: dict[str, Any]) -> list[str]:
    if not routing.get("enabled") or not routing.get("active"):
        return []

    steps = ["metadata_route_query"]
    if routing.get("filter_applied"):
        steps.append("metadata_filter_candidates")
    if routing.get("filter_fallback"):
        steps.append("metadata_filter_fallback")
    if routing.get("boosted_count"):
        steps.append("metadata_boost_candidates")
    return steps


def retrievers_for_strategy(strategy: RetrievalStrategy) -> list[str]:
    if strategy == "dense":
        return ["dense"]
    if strategy == "bm25":
        return ["bm25"]
    return ["dense", "bm25"]


def index_backend_name(
    vector_index: Any,
    config: GenerationConfig,
) -> str:
    if isinstance(vector_index, MilvusTextIndex):
        return "milvus"
    return str(vector_index.metadata.get("index_backend") or config.index_backend or "faiss")


def round_optional(value: Any, *, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def safe_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)
