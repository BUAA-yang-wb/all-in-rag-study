"""Lightweight metadata routing for Course RAG retrieval candidates."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from .indexing import CourseVectorIndex


PAGE_PATTERNS = (
    re.compile(r"(?:第\s*)?(\d{1,4})\s*页"),
    re.compile(r"\bpage\s*[:#-]?\s*(\d{1,4})\b", flags=re.IGNORECASE),
    re.compile(r"\bp\.?\s*[:#-]?\s*(\d{1,4})\b", flags=re.IGNORECASE),
)
QUESTION_NUMBER_PATTERN = re.compile(r"(?:第\s*)?\d{1,3}\s*(?:题|问)")
COMPACT_TOKEN_PATTERN = re.compile(r"[0-9a-zA-Z\u4e00-\u9fff]+")

COURSE_ALIASES = {
    "编译原理": ("编译原理", "编译技术", "编译"),
    "计网": ("计网", "计算机网络"),
}

IMAGE_TERMS = ("图片", "图像", "截图", "图示", "流程图", "状态图", "页面图", "页图")
TABLE_TERMS = ("表格", "对比表", "统计表")


@dataclass(frozen=True)
class MetadataFilters:
    """Optional metadata filters accepted by /ask and /search."""

    course: str | None = None
    category: str | None = None
    source_name: str | None = None
    page: int | str | None = None
    modality: str | None = None
    evidence_kind: str | None = None

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> "MetadataFilters":
        return cls(
            course=clean_optional_text(values.get("course")),
            category=clean_optional_text(values.get("category")),
            source_name=clean_optional_text(values.get("source_name")),
            page=clean_optional_page(values.get("page")),
            modality=clean_optional_text(values.get("modality")),
            evidence_kind=clean_optional_text(values.get("evidence_kind")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "course": self.course,
                "category": self.category,
                "source_name": self.source_name,
                "page": self.page,
                "modality": self.modality,
                "evidence_kind": self.evidence_kind,
            }.items()
            if value not in {None, ""}
        }

    def has_values(self) -> bool:
        return bool(self.to_dict())


@dataclass(frozen=True)
class QueryRoute:
    """Routing decision derived from explicit filters and query text."""

    enabled: bool
    explicit_filters: MetadataFilters
    inferred_filters: MetadataFilters
    intents: list[str]
    matched_source_name: str | None = None

    @property
    def active(self) -> bool:
        return self.enabled and (
            self.explicit_filters.has_values()
            or self.inferred_filters.has_values()
            or bool(self.intents)
        )

    def debug_base(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "active": self.active,
            "explicit_filters": self.explicit_filters.to_dict(),
            "inferred_filters": self.inferred_filters.to_dict(),
            "applied_filters": {},
            "intents": self.intents,
            "matched_source_name": self.matched_source_name,
            "filter_applied": False,
            "filter_fallback": False,
            "candidate_count_before": 0,
            "candidate_count_after": 0,
            "boosted_count": 0,
            "notes": [],
        }


def build_query_route(
    query: str,
    vector_index: CourseVectorIndex,
    *,
    explicit_filters: MetadataFilters | None = None,
    enabled: bool = True,
) -> QueryRoute:
    """Infer high-confidence routing filters and query intents."""

    selected_explicit = explicit_filters or MetadataFilters()
    if not enabled:
        return QueryRoute(
            enabled=False,
            explicit_filters=selected_explicit,
            inferred_filters=MetadataFilters(),
            intents=[],
        )

    inferred: dict[str, Any] = {}
    if not selected_explicit.course:
        inferred["course"] = infer_course(query)
    if not selected_explicit.category:
        inferred["category"] = infer_category(query)
    if not selected_explicit.source_name:
        inferred["source_name"] = infer_source_name(query, vector_index)
    if not selected_explicit.page:
        inferred["page"] = infer_page(query)

    selected_inferred = MetadataFilters.from_mapping(inferred)
    return QueryRoute(
        enabled=True,
        explicit_filters=selected_explicit,
        inferred_filters=selected_inferred,
        intents=detect_intents(query, selected_explicit, selected_inferred),
        matched_source_name=selected_inferred.source_name,
    )


def build_routed_retrieval_query(query: str, route: QueryRoute) -> str:
    """Append explicit metadata terms so BM25 can surface filtered candidates."""

    if not route.enabled or not route.active:
        return query

    terms: list[str] = []
    for filters in (route.explicit_filters, route.inferred_filters):
        values = filters.to_dict()
        for key in ("course", "category", "source_name", "page"):
            value = values.get(key)
            if value not in {None, ""}:
                terms.append(str(value))

    unique_terms = dedupe_keep_order(terms)
    if not unique_terms:
        return query
    return f"{query}\n{' '.join(unique_terms)}"


def apply_metadata_routing(
    results: list[dict[str, Any]],
    route: QueryRoute,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filter or boost retrieval candidates according to a query route."""

    debug = route.debug_base()
    debug["candidate_count_before"] = len(results)
    debug["candidate_count_after"] = len(results)

    if not route.enabled or not route.active or not results:
        return results, debug

    explicit = route.explicit_filters.to_dict()
    inferred = route.inferred_filters.to_dict()
    selected_results = results
    applied_filters: dict[str, Any] = {}
    notes: list[str] = []

    if explicit:
        selected_results = filter_results(results, explicit)
        applied_filters.update(explicit)
        debug["filter_applied"] = True
        if not selected_results:
            debug["candidate_count_after"] = 0
            debug["applied_filters"] = applied_filters
            notes.append("explicit_filters_returned_no_candidates")
            debug["notes"] = notes
            return [], debug

    if inferred:
        base_results = selected_results
        inferred_results = filter_results(base_results, inferred)
        if inferred_results:
            selected_results = inferred_results
            applied_filters.update(inferred)
            debug["filter_applied"] = True
        else:
            debug["filter_fallback"] = True
            notes.append("inferred_filters_fallback_to_broader_candidates")

    boosted_results = boost_results(selected_results, route, applied_filters=applied_filters)
    boosted_count = sum(
        1
        for result in boosted_results
        if float(result.get("metadata_boost") or 1.0) > 1.0
    )
    ranked = rerank_by_current_score(boosted_results)

    debug["applied_filters"] = applied_filters
    debug["candidate_count_after"] = len(ranked)
    debug["boosted_count"] = boosted_count
    debug["notes"] = notes
    return ranked, debug


def filter_results(
    results: list[dict[str, Any]],
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        result
        for result in results
        if result_matches_filters(result, filters)
    ]


def result_matches_filters(result: dict[str, Any], filters: dict[str, Any]) -> bool:
    metadata = chunk_metadata(result)
    for key, expected in filters.items():
        if expected in {None, ""}:
            continue
        if not metadata_matches(metadata, key, expected):
            return False
    return True


def boost_results(
    results: list[dict[str, Any]],
    route: QueryRoute,
    *,
    applied_filters: dict[str, Any],
) -> list[dict[str, Any]]:
    route_filters = {
        **route.explicit_filters.to_dict(),
        **route.inferred_filters.to_dict(),
    }
    boosted: list[dict[str, Any]] = []
    for fallback_rank, result in enumerate(results, 1):
        metadata = chunk_metadata(result)
        matched_filters = [
            key
            for key, value in route_filters.items()
            if metadata_matches(metadata, key, value)
        ]
        matched_intents = matched_metadata_intents(metadata, route.intents)
        boost = 1.0 + 0.08 * len(matched_filters) + 0.04 * len(matched_intents)

        copied = dict(result)
        copied.setdefault("pre_routing_rank", result.get("rank") or fallback_rank)
        copied.setdefault("pre_routing_score", result.get("score"))
        copied["metadata_filter_match"] = bool(applied_filters) and result_matches_filters(
            result,
            applied_filters,
        )
        copied["matched_filters"] = matched_filters
        copied["matched_intents"] = matched_intents
        copied["metadata_boost"] = boost
        copied["score"] = float(result.get("score", 0.0)) * boost
        boosted.append(copied)
    return boosted


def rerank_by_current_score(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        results,
        key=lambda item: (
            -float(item.get("score") or 0.0),
            int(item.get("pre_routing_rank") or item.get("rank") or 1_000_000),
            route_chunk_key(item),
        ),
    )
    for rank, result in enumerate(ranked, 1):
        result["rank"] = rank
    return ranked


def infer_course(query: str) -> str | None:
    normalized = compact_text(query)
    for canonical, aliases in COURSE_ALIASES.items():
        if any(compact_text(alias) in normalized for alias in aliases):
            return canonical
    return None


def infer_category(query: str) -> str | None:
    normalized = compact_text(query)
    if "期末" in normalized and any(term in normalized for term in ("试题", "题目", "真题")):
        return "往届期末试题"
    if any(term in normalized for term in ("课堂总结", "课堂笔记", "总结笔记")):
        return "课堂总结笔记"
    if "复习" in normalized:
        return "复习"
    if any(term in normalized for term in ("课件", "讲义", "ppt")):
        return "课件"
    return None


def infer_source_name(query: str, vector_index: CourseVectorIndex) -> str | None:
    normalized_query = compact_text(query)
    if len(normalized_query) < 4:
        return None

    options = source_options(vector_index)
    for normalized, display_name in options:
        if len(normalized) >= 4 and normalized in normalized_query:
            return display_name
    return None


def infer_page(query: str) -> int | None:
    for pattern in PAGE_PATTERNS:
        match = pattern.search(query)
        if match:
            return int(match.group(1))
    return None


def detect_intents(
    query: str,
    explicit_filters: MetadataFilters,
    inferred_filters: MetadataFilters,
) -> list[str]:
    normalized = compact_text(query)
    intents: list[str] = []
    if any(compact_text(term) in normalized for term in IMAGE_TERMS):
        intents.append("visual")
    if any(compact_text(term) in normalized for term in TABLE_TERMS):
        intents.append("table")
    if QUESTION_NUMBER_PATTERN.search(query) or any(
        term in normalized
        for term in ("选择题", "简答题", "填空题", "计算题", "题号")
    ):
        intents.append("exam_question")
    if explicit_filters.course or inferred_filters.course:
        intents.append("course_scope")
    if explicit_filters.source_name or inferred_filters.source_name:
        intents.append("source_scope")
    if explicit_filters.page or inferred_filters.page:
        intents.append("page_scope")
    return dedupe_keep_order(intents)


def source_options(vector_index: CourseVectorIndex) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for chunk in vector_index.chunks:
        metadata = chunk.metadata
        display_name = (
            metadata.get("source_name")
            or basename(metadata.get("source"))
            or metadata.get("source_stem")
        )
        candidates = [
            metadata.get("source_name"),
            metadata.get("source_stem"),
            basename(metadata.get("source")),
            strip_extension(metadata.get("source_name")),
            strip_extension(basename(metadata.get("source"))),
        ]
        for candidate in candidates:
            normalized = compact_text(candidate)
            if normalized and display_name and normalized not in seen:
                seen[normalized] = str(display_name)

    return sorted(seen.items(), key=lambda item: (-len(item[0]), item[1]))


def metadata_matches(metadata: dict[str, Any], key: str, expected: Any) -> bool:
    if key == "course":
        return course_matches(metadata.get("course"), expected)
    if key == "category":
        return fuzzy_text_match(metadata.get("category"), expected)
    if key == "source_name":
        return source_matches(metadata, expected)
    if key == "page":
        return normalize_page(metadata.get("page")) == normalize_page(expected)
    if key in {"modality", "evidence_kind"}:
        return compact_text(metadata.get(key)) == compact_text(expected)
    return fuzzy_text_match(metadata.get(key), expected)


def course_matches(value: Any, expected: Any) -> bool:
    value_norm = compact_text(value)
    expected_norm = compact_text(expected)
    if not value_norm or not expected_norm:
        return False
    if value_norm == expected_norm:
        return True
    for aliases in COURSE_ALIASES.values():
        normalized_aliases = {compact_text(alias) for alias in aliases}
        if value_norm in normalized_aliases and expected_norm in normalized_aliases:
            return True
    return False


def source_matches(metadata: dict[str, Any], expected: Any) -> bool:
    expected_norm = compact_text(expected)
    if not expected_norm:
        return False
    candidates = [
        metadata.get("source_name"),
        metadata.get("source_stem"),
        metadata.get("source"),
        basename(metadata.get("source")),
        strip_extension(metadata.get("source_name")),
        strip_extension(basename(metadata.get("source"))),
    ]
    for candidate in candidates:
        candidate_norm = compact_text(candidate)
        if not candidate_norm:
            continue
        if expected_norm == candidate_norm:
            return True
        if expected_norm in candidate_norm or candidate_norm in expected_norm:
            return True
    return False


def fuzzy_text_match(value: Any, expected: Any) -> bool:
    value_norm = compact_text(value)
    expected_norm = compact_text(expected)
    if not value_norm or not expected_norm:
        return False
    return value_norm == expected_norm or expected_norm in value_norm or value_norm in expected_norm


def matched_metadata_intents(metadata: dict[str, Any], intents: list[str]) -> list[str]:
    matched: list[str] = []
    modality = compact_text(metadata.get("modality"))
    evidence_kind = compact_text(metadata.get("evidence_kind"))
    category = compact_text(metadata.get("category"))
    if "visual" in intents and (
        modality in {"image", "pdfpage"}
        or evidence_kind in {"caption", "layouttext", "ocrtext"}
    ):
        matched.append("visual")
    if "table" in intents and (
        modality == "table" or evidence_kind in {"tablemarkdown", "caption"}
    ):
        matched.append("table")
    if "exam_question" in intents and "期末试题" in category:
        matched.append("exam_question")
    return matched


def chunk_metadata(result: dict[str, Any]) -> dict[str, Any]:
    return result.get("chunk", {}).get("metadata", {}) or {}


def route_chunk_key(result: dict[str, Any]) -> str:
    metadata = chunk_metadata(result)
    return str(
        metadata.get("chunk_id")
        or metadata.get("chunk_index")
        or f"{metadata.get('source')}:{metadata.get('page')}:{result.get('rank')}"
    )


def clean_optional_text(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    return text or None


def clean_optional_page(value: Any) -> int | str | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return text


def normalize_page(value: Any) -> str | None:
    cleaned = clean_optional_page(value)
    if cleaned is None:
        return None
    if isinstance(cleaned, int):
        return str(cleaned)
    return compact_text(cleaned)


def compact_text(value: Any) -> str:
    if value in {None, ""}:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return "".join(COMPACT_TOKEN_PATTERN.findall(normalized))


def basename(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    normalized = str(value).replace("\\", "/")
    return normalized.rsplit("/", 1)[-1]


def strip_extension(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    name = str(value)
    suffix = PurePath(name).suffix
    if suffix:
        return name[: -len(suffix)]
    return name


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
