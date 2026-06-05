"""Layered evaluation runner for the current Course RAG system."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from course_rag.app.rag.generation import (  # noqa: E402
    DEFAULT_API_KEY_ENV,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    GenerationConfig,
    answer_question,
    load_dotenv_if_available,
)
from course_rag.app.rag.docstore import DEFAULT_DOCSTORE_PATH  # noqa: E402
from course_rag.app.rag.indexing import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL,
)
from course_rag.app.rag.milvus_index import (  # noqa: E402
    DEFAULT_MILVUS_COLLECTION,
    DEFAULT_MILVUS_URI,
    build_or_load_milvus_text_index,
)


EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET_PATH = EVAL_DIR / "golden_set.jsonl"
DEFAULT_RESULTS_DIR = EVAL_DIR / "results"
DEFAULT_DOC_PATH = REPO_ROOT / "course_rag" / "docs" / "RAG_EVALUATION.md"
ABSTENTION_TERMS = (
    "资料不足",
    "没有检索到",
    "无法基于",
    "无法回答",
    "未找到",
    "不足以",
    "不能确定",
    "没有相关",
)
GENERATION_CONFIG_FIELDS = {field.name for field in fields(GenerationConfig)}
PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "fast": {
        "use_llm": False,
        "use_rerank": False,
        "judge": "none",
        "top_k": 5,
        "candidate_k": 40,
    },
    "default": {
        "use_llm": True,
        "use_rerank": True,
        "judge": "llm",
        "top_k": 5,
        "candidate_k": 100,
    },
    "answer": {
        "use_llm": True,
        "use_rerank": True,
        "judge": "llm",
        "top_k": 5,
        "candidate_k": 100,
    },
}


def main() -> None:
    configure_stdio()
    args = parse_args()
    report = run_evaluation(args)
    DEFAULT_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = report["run"]["timestamp"].replace(":", "").replace("-", "")
    json_path = args.results_dir / f"eval_v2_{timestamp}.json"
    md_path = args.results_dir / f"eval_v2_{timestamp}.md"
    write_json(json_path, report)
    markdown = render_markdown_report(report)
    write_text(md_path, markdown)
    if args.write_doc:
        write_evaluation_doc(args.doc_path, report, markdown)
    print(f"Saved JSON report: {json_path}")
    print(f"Saved Markdown report: {md_path}")
    if args.write_doc:
        print(f"Updated evaluation doc: {args.doc_path}")


def run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv_if_available()
    samples = load_jsonl(args.dataset)
    if args.limit is not None:
        samples = samples[: args.limit]

    profile = dict(PROFILE_DEFAULTS[args.profile])
    if args.no_llm:
        profile["use_llm"] = False
        profile["judge"] = "none"
    if args.judge is not None:
        profile["judge"] = args.judge
    profile["milvus_uri"] = args.milvus_uri
    profile["milvus_collection"] = args.milvus_collection

    api_key_available = bool(os.getenv(args.api_key_env))
    llm_disabled_reason: str | None = None
    if profile.get("use_llm") and not api_key_available:
        if args.strict_llm:
            raise RuntimeError(f"Missing API key environment variable: {args.api_key_env}")
        profile["use_llm"] = False
        profile["judge"] = "none"
        llm_disabled_reason = f"Missing API key environment variable: {args.api_key_env}"

    vector_index = load_milvus_index(args)

    judge = None
    if profile.get("judge") == "llm":
        judge = LlmJudge(
            model=args.llm_model,
            base_url=args.llm_base_url,
            api_key_env=args.api_key_env,
        )

    case_reports: list[dict[str, Any]] = []
    for sample in samples:
        case_reports.append(
            evaluate_sample(
                sample,
                profile=profile,
                vector_index=vector_index,
                judge=judge,
                args=args,
            )
        )

    metrics = aggregate_metrics(case_reports)
    return {
        "run": {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "profile": args.profile,
            "retrieval_backend": "milvus",
            "dataset": safe_path(args.dataset),
            "sample_count": len(samples),
            "docstore_path": safe_path(args.docstore_path),
            "embedding_model": args.embedding_model,
            "llm_model": args.llm_model,
            "llm_base_url": args.llm_base_url,
            "api_key_env": args.api_key_env,
            "api_key_available": api_key_available,
            "use_llm": bool(profile.get("use_llm")),
            "judge": profile.get("judge"),
            "llm_disabled_reason": llm_disabled_reason,
            "index": {
                "vectors": vector_index.index.ntotal,
                "metadata": vector_index.metadata,
            },
        },
        "metrics": metrics,
        "comparison": None,
        "cases": case_reports,
    }


def load_milvus_index(args: argparse.Namespace) -> Any:
    return build_or_load_milvus_text_index(
        docstore_path=args.docstore_path,
        model_name=args.embedding_model,
        uri=args.milvus_uri,
        collection_name=args.milvus_collection,
    )


def evaluate_sample(
    sample: dict[str, Any],
    *,
    profile: dict[str, Any],
    vector_index: Any,
    judge: "LlmJudge | None",
    args: argparse.Namespace,
) -> dict[str, Any]:
    request = build_request(sample.get("request", {}), profile)
    config = GenerationConfig(**request)
    started = time.perf_counter()
    result: dict[str, Any] | None = None
    error: str | None = None
    try:
        result = answer_question(
            sample["question"],
            docstore_path=args.docstore_path,
            embedding_model=args.embedding_model,
            config=config,
            vector_index=vector_index,
        )
    except Exception as exc:  # noqa: BLE001 - evaluation must continue per case.
        error = str(exc)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    scores = score_case(sample, result or {}, error=error, latency_ms=latency_ms)
    judge_result: dict[str, Any] | None = None
    if judge is not None and result is not None and not error:
        judge_result = judge.evaluate(sample, result)
        for metric_name in ("groundedness", "relevance", "completeness"):
            value = judge_result.get(metric_name)
            scores[f"judge_{metric_name}"] = value if isinstance(value, (int, float)) else None
        if judge_result.get("error"):
            scores["judge_error"] = 1.0
        else:
            scores["judge_error"] = 0.0

    return {
        "id": sample.get("id"),
        "task_type": sample.get("task_type"),
        "question": sample.get("question"),
        "tags": sample.get("tags", []),
        "negative": bool(sample.get("negative", False)),
        "request": request,
        "expected_evidence": sample.get("expected_evidence", []),
        "expected_facts": sample.get("expected_facts", []),
        "result": compact_result(result) if result is not None else None,
        "judge": judge_result,
        "scores": scores,
        "error": error,
        "latency_ms": latency_ms,
        "issues": case_issues(sample, scores, result, error),
    }


def build_request(sample_request: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    merged = {key: value for key, value in profile.items() if key in GENERATION_CONFIG_FIELDS}
    for key, value in sample_request.items():
        target_key = "retrieval_strategy" if key == "strategy" else key
        if target_key in GENERATION_CONFIG_FIELDS:
            merged[target_key] = value
    return merged


def retrieval_chunk_ids(retrieval: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("chunk_id"))
        for item in retrieval
        if item.get("chunk_id") not in {None, ""}
    ]


def overlap_ratio(left: list[str], right: list[str]) -> float | None:
    if not left and not right:
        return None
    denominator = max(len(left), len(right), 1)
    return round(len(set(left) & set(right)) / denominator, 4)


def score_case(
    sample: dict[str, Any],
    result: dict[str, Any],
    *,
    error: str | None,
    latency_ms: float,
) -> dict[str, Any]:
    retrieval = result.get("retrieval", []) if result else []
    citations = result.get("citations", []) if result else []
    answer = str(result.get("answer", "")) if result else ""
    expected_evidence = sample.get("expected_evidence", [])
    expected_facts = sample.get("expected_facts", [])
    negative = bool(sample.get("negative", False))
    top_k = int(sample.get("request", {}).get("top_k") or 5)
    top_retrieval = retrieval[:top_k]

    expected_matches = [
        first_match_position(expected, top_retrieval)
        for expected in expected_evidence
    ]
    matched_positions = [position for position in expected_matches if position is not None]
    evidence_hit = 1.0 if matched_positions else 0.0
    evidence_recall = (
        len(matched_positions) / len(expected_evidence)
        if expected_evidence
        else None
    )
    mrr = 1.0 / min(matched_positions) if matched_positions else (None if not expected_evidence else 0.0)
    relevant_contexts = count_relevant_contexts(top_retrieval, expected_evidence)
    context_precision = (
        relevant_contexts / len(top_retrieval)
        if top_retrieval and expected_evidence
        else None
    )

    fact_hits = [fact for fact in expected_facts if contains_fact(answer, fact)]
    answer_fact_coverage = (
        len(fact_hits) / len(expected_facts)
        if expected_facts
        else None
    )
    abstention_success = None
    if negative:
        abstention_success = 1.0 if contains_abstention(answer) else 0.0

    routing = result.get("routing", {}) if result else {}
    expected_routing = sample.get("expected_routing")
    routing_filter_success = None
    if expected_routing:
        routing_filter_success = (
            1.0
            if routing_matches(routing, expected_routing.get("applied_filters", {}))
            else 0.0
        )
    routing_fallback = 1.0 if routing.get("filter_fallback") else 0.0
    expected_modality_hit = modality_hit(sample, top_retrieval)

    citation_validity = citation_validity_score(citations)
    citation_coverage = citation_coverage_score(sample, citations)
    llm_error = result.get("llm_error") if result else None

    return {
        "evidence_hit_at_k": evidence_hit if expected_evidence else None,
        "evidence_recall_at_k": evidence_recall,
        "mrr": mrr,
        "context_precision_at_k": context_precision,
        "routing_filter_success": routing_filter_success,
        "routing_fallback_rate": routing_fallback,
        "expected_modality_hit": expected_modality_hit,
        "citation_validity": citation_validity,
        "citation_coverage": citation_coverage,
        "answer_fact_coverage": answer_fact_coverage,
        "abstention_success": abstention_success,
        "error_rate": 1.0 if error else 0.0,
        "llm_error_rate": 1.0 if llm_error else 0.0,
        "latency_ms": latency_ms,
        "used_llm": 1.0 if result.get("used_llm") else 0.0,
        "rerank_used": 1.0 if result.get("rerank_used") else 0.0,
    }


def first_match_position(expected: dict[str, Any], retrieval: list[dict[str, Any]]) -> int | None:
    for index, item in enumerate(retrieval, 1):
        if evidence_matches(item, expected):
            return index
    return None


def count_relevant_contexts(
    retrieval: list[dict[str, Any]],
    expected_evidence: list[dict[str, Any]],
) -> int:
    if not expected_evidence:
        return 0
    return sum(
        1
        for item in retrieval
        if any(evidence_matches(item, expected) for expected in expected_evidence)
    )


def evidence_matches(item: dict[str, Any], expected: dict[str, Any]) -> bool:
    if expected.get("evidence_id"):
        if normalize_value(item.get("evidence_id")) == normalize_value(expected.get("evidence_id")):
            return True

    comparable_keys = (
        "source_name",
        "page",
        "evidence_kind",
        "modality",
        "course",
        "category",
        "asset_path",
    )
    checks = [
        values_match(item.get(key), expected.get(key))
        for key in comparable_keys
        if expected.get(key) not in {None, ""}
    ]
    return bool(checks) and all(checks)


def values_match(actual: Any, expected: Any) -> bool:
    if expected in {None, ""}:
        return True
    actual_text = normalize_value(actual)
    expected_text = normalize_value(expected)
    if actual_text == expected_text:
        return True
    if "/" in expected_text or "\\" in expected_text:
        return actual_text.replace("\\", "/").endswith(expected_text.replace("\\", "/"))
    return False


def normalize_value(value: Any) -> str:
    return str(value).strip().replace("\\", "/").lower()


def contains_fact(answer: str, fact: Any) -> bool:
    return normalize_text(fact) in normalize_text(answer)


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value)).lower()


def contains_abstention(answer: str) -> bool:
    return any(term in answer for term in ABSTENTION_TERMS)


def routing_matches(routing: dict[str, Any], expected_filters: dict[str, Any]) -> bool:
    if not expected_filters:
        return True
    applied = routing.get("applied_filters", {}) or {}
    return all(values_match(applied.get(key), value) for key, value in expected_filters.items())


def modality_hit(sample: dict[str, Any], retrieval: list[dict[str, Any]]) -> float | None:
    expected_modality = sample.get("expected_modality")
    expected_kinds = {
        item.get("evidence_kind")
        for item in sample.get("expected_evidence", [])
        if item.get("evidence_kind")
    }
    if not expected_modality and not expected_kinds:
        return None
    for item in retrieval:
        if expected_modality and values_match(item.get("modality"), expected_modality):
            return 1.0
        if expected_kinds and item.get("evidence_kind") in expected_kinds:
            return 1.0
    return 0.0


def citation_validity_score(citations: list[dict[str, Any]]) -> float:
    if not citations:
        return 0.0
    valid = 0
    for citation in citations:
        has_location = bool(citation.get("source_name") or citation.get("source"))
        has_text = bool(citation.get("chunk_preview") or citation.get("text"))
        has_score = citation.get("score") is not None
        if has_location and has_text and has_score:
            valid += 1
    return valid / len(citations)


def citation_coverage_score(sample: dict[str, Any], citations: list[dict[str, Any]]) -> float | None:
    expected_evidence = sample.get("expected_evidence", [])
    if expected_evidence:
        return 1.0 if any(
            evidence_matches(citation, expected)
            for citation in citations
            for expected in expected_evidence
        ) else 0.0
    if sample.get("negative"):
        return None
    return 1.0 if citations else 0.0


def aggregate_metrics(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    metric_names = sorted(
        {
            key
            for case in case_reports
            for key in case.get("scores", {})
            if isinstance(case.get("scores", {}).get(key), (int, float))
        }
    )
    overall = aggregate_metric_subset(case_reports, metric_names)
    by_task_type: dict[str, Any] = {}
    task_types = sorted({str(case.get("task_type")) for case in case_reports})
    for task_type in task_types:
        subset = [case for case in case_reports if str(case.get("task_type")) == task_type]
        by_task_type[task_type] = aggregate_metric_subset(subset, metric_names)
    return {
        "overall": overall,
        "by_task_type": by_task_type,
    }


def aggregate_metric_subset(
    case_reports: list[dict[str, Any]],
    metric_names: list[str],
) -> dict[str, Any]:
    summary: dict[str, Any] = {"case_count": len(case_reports)}
    for metric_name in metric_names:
        values = [
            case["scores"][metric_name]
            for case in case_reports
            if isinstance(case.get("scores", {}).get(metric_name), (int, float))
        ]
        if not values:
            continue
        if metric_name == "latency_ms":
            summary["latency_ms_avg"] = round(statistics.mean(values), 1)
            summary["latency_ms_p95"] = round(percentile(values, 0.95), 1)
        else:
            summary[metric_name] = round(statistics.mean(values), 4)
    return summary


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return float(ordered[index])


def case_issues(
    sample: dict[str, Any],
    scores: dict[str, Any],
    result: dict[str, Any] | None,
    error: str | None,
) -> list[str]:
    issues: list[str] = []
    if error:
        issues.append(f"runner_error: {error}")
    if scores.get("evidence_hit_at_k") == 0.0:
        issues.append("expected evidence not found in top-k")
    if scores.get("routing_filter_success") == 0.0:
        issues.append("expected routing filters were not applied")
    if scores.get("expected_modality_hit") == 0.0:
        issues.append("expected modality/evidence kind not found")
    if scores.get("citation_coverage") == 0.0:
        issues.append("citations did not cover expected evidence")
    if scores.get("answer_fact_coverage") not in {None, 1.0}:
        issues.append("answer missed expected facts")
    if scores.get("abstention_success") == 0.0:
        issues.append("negative sample did not abstain")
    if result and result.get("llm_error"):
        issues.append(f"llm_error: {result['llm_error']}")
    return issues


class LlmJudge:
    """Small DeepSeek-compatible LLM judge for answer-level RAG metrics."""

    def __init__(self, *, model: str, base_url: str, api_key_env: str) -> None:
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key environment variable: {api_key_env}")
        from langchain_openai import ChatOpenAI

        self.llm = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=0.0,
            max_tokens=700,
        )

    def evaluate(self, sample: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        contexts = "\n\n".join(
            f"[{item.get('id')}] {item.get('source_name') or item.get('source')} "
            f"page={item.get('page')} kind={item.get('evidence_kind')}\n"
            f"{item.get('context_preview') or item.get('chunk_preview') or item.get('text') or ''}"
            for item in result.get("retrieval", [])
        )
        prompt = f"""你是 RAG 评测裁判。请只输出 JSON，不要输出 Markdown。

评分范围 0 到 1：
- groundedness: 答案是否被检索资料支持，不能编造。
- relevance: 答案是否回答了问题。
- completeness: 答案是否覆盖 expected_facts。

问题：
{sample.get("question")}

expected_facts:
{json.dumps(sample.get("expected_facts", []), ensure_ascii=False)}

检索资料：
{contexts}

答案：
{result.get("answer", "")}

输出 JSON 格式：
{{"groundedness":0.0,"relevance":0.0,"completeness":0.0,"notes":"一句中文说明"}}
"""
        try:
            response = self.llm.invoke(prompt)
            content = str(getattr(response, "content", response)).strip()
            payload = parse_json_object(content)
            return {
                "groundedness": clamp_score(payload.get("groundedness")),
                "relevance": clamp_score(payload.get("relevance")),
                "completeness": clamp_score(payload.get("completeness")),
                "notes": str(payload.get("notes", ""))[:500],
            }
        except Exception as exc:  # noqa: BLE001 - judge failure should not stop eval.
            return {"error": str(exc)}


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def clamp_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, score))


def compact_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "question": result.get("question"),
        "answer": result.get("answer"),
        "used_llm": result.get("used_llm"),
        "llm_error": result.get("llm_error"),
        "retrieval_strategy": result.get("retrieval_strategy"),
        "retrievers": result.get("retrievers", []),
        "use_rerank": result.get("use_rerank"),
        "rerank_used": result.get("rerank_used"),
        "rerank_model": result.get("rerank_model"),
        "rerank_device": result.get("rerank_device"),
        "rerank_error": result.get("rerank_error"),
        "routing": result.get("routing", {}),
        "pipeline": result.get("pipeline", []),
        "index": result.get("index", {}),
        "citations": result.get("citations", []),
        "retrieval": result.get("retrieval", []),
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    run = report["run"]
    lines = [
        "# Course RAG Evaluation Report",
        "",
        f"- Time: `{run['timestamp']}`",
        f"- Profile: `{run['profile']}`",
        f"- Retrieval backend: `{run['retrieval_backend']}`",
        f"- Docstore: `{run['docstore_path']}`",
        f"- Samples: `{run['sample_count']}`",
        f"- Use LLM: `{run['use_llm']}`",
        f"- Judge: `{run['judge']}`",
        f"- API key available: `{run['api_key_available']}`",
    ]
    if run.get("llm_disabled_reason"):
        lines.append(f"- LLM disabled reason: `{run['llm_disabled_reason']}`")
    lines.extend(["", "## Overall Metrics", "", metrics_table(report["metrics"]["overall"])])
    lines.extend(["", "## Metrics By Task Type", ""])
    lines.append("| task_type | case_count | evidence_hit@k | evidence_recall@k | mrr | answer_fact_coverage | citation_coverage | llm_error_rate | latency_ms_avg |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for task_type, metrics in report["metrics"]["by_task_type"].items():
        lines.append(
            "| {task_type} | {case_count} | {hit} | {recall} | {mrr} | {facts} | {citations} | {llm_error} | {latency} |".format(
                task_type=task_type,
                case_count=metrics.get("case_count", 0),
                hit=fmt_metric(metrics.get("evidence_hit_at_k")),
                recall=fmt_metric(metrics.get("evidence_recall_at_k")),
                mrr=fmt_metric(metrics.get("mrr")),
                facts=fmt_metric(metrics.get("answer_fact_coverage")),
                citations=fmt_metric(metrics.get("citation_coverage")),
                llm_error=fmt_metric(metrics.get("llm_error_rate")),
                latency=fmt_metric(metrics.get("latency_ms_avg")),
            )
        )
    comparison = report.get("comparison")
    if comparison:
        lines.extend(["", "## Backend Comparison", ""])
        lines.append(
            f"- Primary backend: `{comparison['primary_backend']}`; "
            f"compare backend: `{comparison['compare_backend']}`"
        )
        lines.append(f"- Average Top-K overlap: `{fmt_metric(comparison.get('overlap_at_k_avg'))}`")
        lines.append(f"- Changed Top-1 rate: `{fmt_metric(comparison.get('changed_top1_rate'))}`")
        lines.append(f"- Comparison error rate: `{fmt_metric(comparison.get('error_rate'))}`")
        changed = comparison.get("changed_top1_case_ids") or []
        if changed:
            lines.append(f"- Changed Top-1 cases: `{', '.join(map(str, changed[:20]))}`")
        errors = comparison.get("error_case_ids") or []
        if errors:
            lines.append(f"- Comparison error cases: `{', '.join(map(str, errors[:20]))}`")
    failures = [case for case in report["cases"] if case.get("issues")]
    lines.extend(["", "## Failure Samples", ""])
    if not failures:
        lines.append("No failures recorded by deterministic checks.")
    else:
        for case in failures[:20]:
            lines.append(f"- `{case['id']}` ({case['task_type']}): {'; '.join(case['issues'])}")
    lines.extend(["", "## Notes", ""])
    lines.append("- `llm_error_rate` counts answer-generation fallback errors, not runner crashes.")
    lines.append("- Exact evidence matching prefers `evidence_id`; otherwise it matches metadata such as source/page/evidence_kind.")
    return "\n".join(lines) + "\n"


def metrics_table(metrics: dict[str, Any]) -> str:
    rows = [
        ("case_count", metrics.get("case_count")),
        ("evidence_hit@k", metrics.get("evidence_hit_at_k")),
        ("evidence_recall@k", metrics.get("evidence_recall_at_k")),
        ("mrr", metrics.get("mrr")),
        ("context_precision@k", metrics.get("context_precision_at_k")),
        ("routing_filter_success", metrics.get("routing_filter_success")),
        ("routing_fallback_rate", metrics.get("routing_fallback_rate")),
        ("expected_modality_hit", metrics.get("expected_modality_hit")),
        ("citation_validity", metrics.get("citation_validity")),
        ("citation_coverage", metrics.get("citation_coverage")),
        ("answer_fact_coverage", metrics.get("answer_fact_coverage")),
        ("abstention_success", metrics.get("abstention_success")),
        ("judge_groundedness", metrics.get("judge_groundedness")),
        ("judge_relevance", metrics.get("judge_relevance")),
        ("judge_completeness", metrics.get("judge_completeness")),
        ("error_rate", metrics.get("error_rate")),
        ("llm_error_rate", metrics.get("llm_error_rate")),
        ("latency_ms_avg", metrics.get("latency_ms_avg")),
        ("latency_ms_p95", metrics.get("latency_ms_p95")),
    ]
    lines = ["| metric | value |", "| --- | ---: |"]
    for name, value in rows:
        if value is not None:
            lines.append(f"| {name} | {fmt_metric(value)} |")
    return "\n".join(lines)


def write_evaluation_doc(path: Path, report: dict[str, Any], markdown_report: str) -> None:
    content = f"""# Course RAG 评测体系

最后更新：{report['run']['timestamp']}

本文档记录当前 `course_rag` 新评测体系的设计、运行方式和最近一次实际评测结果。

## 1. 评测目标

当前系统是 evidence-first RAG：文本、图片元数据、Markdown 图片引用、OCR 文本和表格 evidence 会统一进入索引。评测因此按层诊断，而不是只看最终答案：

- 检索是否找到了期望 evidence。
- metadata routing 是否正确应用课程、文件、页码、模态和 evidence 类型过滤。
- rerank、父子上下文和 citation 是否保留可追溯来源。
- 外部 LLM 生成是否 grounded，并覆盖关键事实。
- 资料不足问题是否明确拒答。

## 2. 数据与命令

金标数据：

```text
course_rag/eval/golden_set.jsonl
```

默认评测命令：

```powershell
.\\rag\\Scripts\\python.exe -X utf8 course_rag\\eval\\run_eval.py --profile default
```

快速离线诊断：

```powershell
.\\rag\\Scripts\\python.exe -X utf8 course_rag\\eval\\run_eval.py --profile fast
```

默认外部 LLM 沿用主系统 DeepSeek-compatible 配置：`{DEFAULT_LLM_MODEL}`、`{DEFAULT_LLM_BASE_URL}`、`{DEFAULT_API_KEY_ENV}`。如果环境变量缺失，脚本自动降级为离线检索/引用诊断。

## 3. 指标

- 检索：`evidence_hit@k`、`evidence_recall@k`、`mrr`、`context_precision@k`
- 路由：`routing_filter_success`、`routing_fallback_rate`、`expected_modality_hit`
- 引用：`citation_validity`、`citation_coverage`
- 生成：`answer_fact_coverage`、`abstention_success`
- LLM 裁判：`judge_groundedness`、`judge_relevance`、`judge_completeness`
- 稳定性：`error_rate`、`llm_error_rate`、`latency_ms_avg`

## 4. 最近一次结果

{markdown_report}
"""
    write_text(path, content)


def fmt_metric(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def safe_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the current Course RAG system.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--doc-path", type=Path, default=DEFAULT_DOC_PATH)
    parser.add_argument("--docstore-path", type=Path, default=DEFAULT_DOCSTORE_PATH)
    parser.add_argument("--milvus-uri", default=DEFAULT_MILVUS_URI)
    parser.add_argument("--milvus-collection", default=DEFAULT_MILVUS_COLLECTION)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--profile", choices=sorted(PROFILE_DEFAULTS), default="default")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-llm", action="store_true", help="Disable external LLM generation and judge.")
    parser.add_argument("--judge", choices=("llm", "none"), default=None)
    parser.add_argument("--strict-llm", action="store_true", help="Fail if the API key is missing.")
    parser.add_argument("--no-write-doc", dest="write_doc", action="store_false")
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--llm-base-url", default=DEFAULT_LLM_BASE_URL)
    parser.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    parser.set_defaults(write_doc=True)
    return parser.parse_args()


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    main()
