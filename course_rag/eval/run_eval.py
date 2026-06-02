"""Run a small offline evaluation for the current text-only Course RAG pipeline."""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from course_rag.app.rag.generation import GenerationConfig, answer_question
from course_rag.app.rag.indexing import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_INDEX_DIR,
    build_or_load_vector_index,
)
from course_rag.app.rag.retrieval import get_course_retriever


DEFAULT_DATASET = Path("course_rag/eval/eval_dataset.jsonl")
DEFAULT_OUTPUT_DIR = Path("course_rag/eval/results")
RESULT_JSON_NAME = "day11_text_rag_eval.json"
RESULT_MD_NAME = "day11_text_rag_eval.md"


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    strategy: str
    top_k: int = 5
    candidate_k: int = 30
    use_rerank: bool = False
    rerank_top_n: int = 20


EXPERIMENTS: dict[str, ExperimentConfig] = {
    "dense": ExperimentConfig(name="dense", strategy="dense"),
    "hybrid": ExperimentConfig(name="hybrid", strategy="hybrid"),
    "hybrid-rerank": ExperimentConfig(
        name="hybrid-rerank",
        strategy="hybrid",
        use_rerank=True,
        rerank_top_n=20,
    ),
}


@dataclass(frozen=True)
class GoldSource:
    source: str
    page: str | None = None


def main() -> None:
    args = parse_args()
    dataset_path = resolve_repo_path(args.dataset)
    output_dir = resolve_repo_path(args.output_dir)
    index_dir = resolve_repo_path(args.index_dir)
    selected_experiments = args.experiment or list(EXPERIMENTS)

    items = load_dataset(dataset_path)
    if args.limit is not None:
        items = items[: args.limit]
    if not items:
        raise SystemExit("No evaluation items to run.")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Loaded {len(items)} evaluation items from {dataset_path}")
    print(f"Loading vector index from {index_dir}")
    vector_index = build_or_load_vector_index(
        index_dir=index_dir,
        model_name=DEFAULT_EMBEDDING_MODEL,
        show_progress_bar=False,
    )
    retriever = get_course_retriever(vector_index)

    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": safe_path(dataset_path),
        "index_dir": safe_path(index_dir),
        "item_count": len(items),
        "experiments": [],
    }

    for experiment_name in selected_experiments:
        experiment = EXPERIMENTS[experiment_name]
        print(f"Running experiment: {experiment.name}")
        result["experiments"].append(
            run_experiment(
                experiment,
                items,
                vector_index=vector_index,
                retriever=retriever,
            )
        )

    json_name, markdown_name = result_filenames(args.result_prefix)
    json_path = output_dir / json_name
    markdown_path = output_dir / markdown_name
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown_report(result), encoding="utf-8")
    print(f"Wrote JSON report: {json_path}")
    print(f"Wrote Markdown report: {markdown_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate current text-only Course RAG retrieval quality.",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument(
        "--result-prefix",
        default=None,
        help="Optional output file prefix, for example 'day13_v2_text_eval'.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--experiment",
        action="append",
        choices=sorted(EXPERIMENTS),
        help="Run one experiment. Repeat the flag to run multiple experiments.",
    )
    return parser.parse_args()


def result_filenames(prefix: str | None) -> tuple[str, str]:
    if not prefix:
        return RESULT_JSON_NAME, RESULT_MD_NAME
    cleaned = prefix.strip()
    if not cleaned:
        return RESULT_JSON_NAME, RESULT_MD_NAME
    return f"{cleaned}.json", f"{cleaned}.md"


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT_DIR / path


def load_dataset(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            item = json.loads(stripped)
            validate_item(item, line_number=line_number)
            items.append(item)
    return items


def validate_item(item: dict[str, Any], *, line_number: int) -> None:
    required = {
        "id",
        "question",
        "type",
        "course",
        "gold_sources",
        "gold_answer_keywords",
    }
    missing = sorted(required - set(item))
    if missing:
        raise ValueError(f"line {line_number}: missing fields {missing}")
    if not isinstance(item["gold_sources"], list) or not item["gold_sources"]:
        raise ValueError(f"line {line_number}: gold_sources must be a non-empty list")


def run_experiment(
    experiment: ExperimentConfig,
    items: list[dict[str, Any]],
    *,
    vector_index: Any,
    retriever: Any,
) -> dict[str, Any]:
    config = GenerationConfig(
        top_k=experiment.top_k,
        candidate_k=experiment.candidate_k,
        retrieval_strategy=experiment.strategy,  # type: ignore[arg-type]
        use_rerank=experiment.use_rerank,
        rerank_top_n=experiment.rerank_top_n,
        rerank_local_files_only=True,
        use_llm=False,
    )
    details: list[dict[str, Any]] = []
    for item in items:
        try:
            response = answer_question(
                item["question"],
                config=config,
                vector_index=vector_index,
                retriever=retriever,
            )
            details.append(score_item(item, response))
        except Exception as exc:  # noqa: BLE001 - one bad item should not stop a run.
            details.append(score_error_item(item, error=str(exc)))

    return {
        "name": experiment.name,
        "config": {
            "top_k": experiment.top_k,
            "candidate_k": experiment.candidate_k,
            "strategy": experiment.strategy,
            "use_rerank": experiment.use_rerank,
            "rerank_top_n": experiment.rerank_top_n,
            "rerank_local_files_only": True,
            "use_llm": False,
        },
        "metrics": aggregate_metrics(details),
        "items": details,
    }


def score_item(item: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    citations = response.get("citations", [])
    rank, matched_gold, matched_citation = first_hit(citations, item["gold_sources"])
    hit = rank is not None
    return {
        "id": item["id"],
        "question": item["question"],
        "type": item["type"],
        "course": item["course"],
        "gold_sources": item["gold_sources"],
        "hit_rank": rank,
        "matched_gold_source": matched_gold,
        "matched_citation_source": matched_citation,
        "recall_at_5": 1.0 if hit and rank <= 5 else 0.0,
        "mrr": 1.0 / rank if hit else 0.0,
        "citation_hit": 1.0 if hit else 0.0,
        "citation_count": len(citations),
        "top_citations": compact_citations(citations),
        "routing": response.get("routing"),
        "rerank_used": bool(response.get("rerank_used")),
        "rerank_error": response.get("rerank_error"),
        "error": None,
    }


def score_error_item(item: dict[str, Any], *, error: str) -> dict[str, Any]:
    return {
        "id": item["id"],
        "question": item["question"],
        "type": item["type"],
        "course": item["course"],
        "gold_sources": item["gold_sources"],
        "hit_rank": None,
        "matched_gold_source": None,
        "matched_citation_source": None,
        "recall_at_5": 0.0,
        "mrr": 0.0,
        "citation_hit": 0.0,
        "citation_count": 0,
        "top_citations": [],
        "routing": None,
        "rerank_used": False,
        "rerank_error": None,
        "error": error,
    }


def aggregate_metrics(details: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(details)
    if total == 0:
        return {
            "questions": 0,
            "recall_at_5": 0.0,
            "mrr": 0.0,
            "citation_hit_rate": 0.0,
            "request_errors": 0,
            "rerank_used_count": 0,
            "rerank_error_count": 0,
        }
    return {
        "questions": total,
        "recall_at_5": round(mean(detail["recall_at_5"] for detail in details), 4),
        "mrr": round(mean(detail["mrr"] for detail in details), 4),
        "citation_hit_rate": round(mean(detail["citation_hit"] for detail in details), 4),
        "request_errors": sum(1 for detail in details if detail.get("error")),
        "rerank_used_count": sum(1 for detail in details if detail.get("rerank_used")),
        "rerank_error_count": sum(1 for detail in details if detail.get("rerank_error")),
    }


def mean(values: Any) -> float:
    materialized = list(values)
    return sum(float(value) for value in materialized) / len(materialized)


def first_hit(
    citations: list[dict[str, Any]],
    raw_gold_sources: list[Any],
) -> tuple[int | None, str | None, str | None]:
    gold_sources = [parse_gold_source(raw) for raw in raw_gold_sources]
    for rank, citation in enumerate(citations, 1):
        for gold in gold_sources:
            if citation_matches(citation, gold):
                return rank, format_gold_source(gold), citation_source_label(citation)
    return None, None, None


def parse_gold_source(raw: Any) -> GoldSource:
    if isinstance(raw, dict):
        source = str(raw.get("source_name") or raw.get("source") or "").strip()
        page = raw.get("page")
        return GoldSource(source=source, page=normalize_page(page))

    text = str(raw).strip()
    source = text
    page: str | None = None
    for marker in ("#page=", "#p=", "#page:", "#p:"):
        if marker in text:
            source, page_text = text.split(marker, 1)
            page = normalize_page(page_text)
            break
    return GoldSource(source=source.strip(), page=page)


def citation_matches(citation: dict[str, Any], gold: GoldSource) -> bool:
    if not source_matches(citation, gold.source):
        return False
    if gold.page is None:
        return True
    return normalize_page(citation.get("page")) == gold.page


def source_matches(citation: dict[str, Any], gold_source: str) -> bool:
    gold_full = normalize_source(gold_source)
    gold_name = normalize_source(basename(gold_source))
    candidates = [
        citation.get("source_name"),
        citation.get("source"),
        basename(str(citation.get("source") or "")),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        candidate_full = normalize_source(str(candidate))
        candidate_name = normalize_source(basename(str(candidate)))
        if gold_name == candidate_name or gold_full == candidate_full:
            return True
        if gold_name and gold_name in candidate_full:
            return True
        if candidate_name and candidate_name in gold_full:
            return True
    return False


def normalize_source(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.replace("\\", "/").casefold().split())


def basename(value: str) -> str:
    normalized = value.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1]


def normalize_page(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(int(float(text)))
    except ValueError:
        return unicodedata.normalize("NFKC", text).casefold()


def format_gold_source(gold: GoldSource) -> str:
    return gold.source if gold.page is None else f"{gold.source}#page={gold.page}"


def citation_source_label(citation: dict[str, Any]) -> str:
    source = citation.get("source_name") or citation.get("source") or "unknown"
    page = citation.get("page")
    return str(source) if page in {None, ""} else f"{source}#page={page}"


def compact_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for index, citation in enumerate(citations, 1):
        compact.append(
            {
                "position": index,
                "rank": citation.get("rank"),
                "score": citation.get("score"),
                "evidence_id": citation.get("evidence_id"),
                "modality": citation.get("modality"),
                "evidence_kind": citation.get("evidence_kind"),
                "source_name": citation.get("source_name"),
                "source": citation.get("source"),
                "page": citation.get("page"),
                "section_path": citation.get("section_path"),
                "retrieval_strategy": citation.get("retrieval_strategy"),
                "retrievers": citation.get("retrievers"),
                "metadata_boost": citation.get("metadata_boost"),
                "matched_filters": citation.get("matched_filters"),
                "rerank_score": citation.get("rerank_score"),
            }
        )
    return compact


def render_markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Day11 Text RAG Evaluation",
        "",
        f"- Generated at: `{result['generated_at']}`",
        f"- Dataset: `{result['dataset']}`",
        f"- Index: `{result.get('index_dir', '-')}`",
        f"- Questions: `{result['item_count']}`",
        "- LLM calls: disabled (`use_llm=false`)",
        "",
        "## Summary",
        "",
        "| Experiment | Questions | Recall@5 | MRR | Citation Hit Rate | Rerank Used | Rerank Errors | Request Errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for experiment in result["experiments"]:
        metrics = experiment["metrics"]
        lines.append(
            "| {name} | {questions} | {recall:.4f} | {mrr:.4f} | {hit:.4f} | {used} | {rerank_errors} | {request_errors} |".format(
                name=experiment["name"],
                questions=metrics["questions"],
                recall=metrics["recall_at_5"],
                mrr=metrics["mrr"],
                hit=metrics["citation_hit_rate"],
                used=metrics["rerank_used_count"],
                rerank_errors=metrics["rerank_error_count"],
                request_errors=metrics["request_errors"],
            )
        )

    lines.extend(
        [
            "",
            "## Metric Notes",
            "",
            "- `Recall@5`: whether any gold source appears in the top 5 returned citations.",
            "- `MRR`: reciprocal rank of the first matched gold source.",
            "- `Citation Hit Rate`: whether the final citation list contains any gold source.",
            "",
            "## Misses",
            "",
            "| Experiment | ID | Question | Gold Sources | Top1 Citation |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for experiment in result["experiments"]:
        misses = [
            item
            for item in experiment["items"]
            if item["recall_at_5"] == 0.0 or item.get("error")
        ][:10]
        if not misses:
            lines.append(f"| {experiment['name']} | - | No misses in this run. | - | - |")
            continue
        for item in misses:
            top1 = item["top_citations"][0] if item["top_citations"] else {}
            top1_label = top1.get("source_name") or top1.get("source") or item.get("error") or "-"
            lines.append(
                "| {experiment} | {id} | {question} | {gold} | {top1} |".format(
                    experiment=md_escape(experiment["name"]),
                    id=md_escape(item["id"]),
                    question=md_escape(item["question"]),
                    gold=md_escape(", ".join(str(source) for source in item["gold_sources"])),
                    top1=md_escape(str(top1_label)),
                )
            )
    lines.append("")
    return "\n".join(lines)


def md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def safe_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


if __name__ == "__main__":
    main()
