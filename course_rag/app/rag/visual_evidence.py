"""Offline visual evidence builders for Course RAG V2.

The online RAG path only consumes indexed text. This module turns images,
Markdown image references, rendered PDF pages, OCR output, and optional VLM
captions into ``EvidenceDocument`` objects that can enter the existing text
indexing pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

try:
    from .evidence import (
        EvidenceDocument,
        evidence_id_payload,
        read_evidence_jsonl,
        source_name_from_source,
        stable_hash,
        write_evidence_jsonl,
    )
    from .loaders import (
        DEFAULT_MANIFEST_PATH,
        normalize_manifest_record,
        parse_priority_filter,
    )
except ImportError:
    from evidence import (  # type: ignore
        EvidenceDocument,
        evidence_id_payload,
        read_evidence_jsonl,
        source_name_from_source,
        stable_hash,
        write_evidence_jsonl,
    )
    from loaders import (  # type: ignore
        DEFAULT_MANIFEST_PATH,
        normalize_manifest_record,
        parse_priority_filter,
    )


logger = logging.getLogger(__name__)

DEFAULT_IMAGE_EVIDENCE_CACHE_PATH = Path("course_rag/data/processed/evidence_image.jsonl")
DEFAULT_OCR_EVIDENCE_CACHE_PATH = Path("course_rag/data/processed/evidence_ocr.jsonl")
DEFAULT_CAPTION_EVIDENCE_CACHE_PATH = Path("course_rag/data/processed/evidence_caption.jsonl")
DEFAULT_PAGE_IMAGE_ROOT = Path("course_rag/data/processed/page_images")
DEFAULT_IMAGE_EVIDENCE_PIPELINE_VERSION = "image_evidence_v1"
DEFAULT_OCR_PIPELINE_VERSION = "ocr_evidence_v1"
DEFAULT_CAPTION_PIPELINE_VERSION = "caption_evidence_v1"
DEFAULT_OCR_PROVIDER = "rapidocr"
DEFAULT_CAPTION_PROVIDER = "none"
DEFAULT_PDF_PAGE_LOW_TEXT_CHARS = 80

IMAGE_MODALITY = "image"
PDF_PAGE_MODALITY = "pdf_page"
IMAGE_METADATA_KIND = "image_metadata"
IMAGE_REF_KIND = "image_ref"
OCR_TEXT_KIND = "ocr_text"
CAPTION_KIND = "caption"

MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")
HTML_IMAGE_PATTERN = re.compile(
    r"<img\b[^>]*\bsrc=[\"'](?P<target>[^\"']+)[\"'][^>]*>",
    flags=re.IGNORECASE,
)
MARKDOWN_HEADING_PATTERN = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


@dataclass(frozen=True)
class VisualEvidenceConfig:
    """Configuration for offline visual evidence generation."""

    manifest_path: Path = DEFAULT_MANIFEST_PATH
    repo_root: Path = Path.cwd()
    priority: str = "mvp,v2"
    include_image_metadata: bool = True
    include_markdown_image_refs: bool = True
    run_ocr: bool = False
    ocr_provider: str = DEFAULT_OCR_PROVIDER
    run_caption: bool = False
    caption_provider: str = DEFAULT_CAPTION_PROVIDER
    image_cache_path: Path = DEFAULT_IMAGE_EVIDENCE_CACHE_PATH
    ocr_cache_path: Path = DEFAULT_OCR_EVIDENCE_CACHE_PATH
    caption_cache_path: Path = DEFAULT_CAPTION_EVIDENCE_CACHE_PATH
    page_image_root: Path = DEFAULT_PAGE_IMAGE_ROOT
    image_pipeline_version: str = DEFAULT_IMAGE_EVIDENCE_PIPELINE_VERSION
    ocr_pipeline_version: str = DEFAULT_OCR_PIPELINE_VERSION
    caption_pipeline_version: str = DEFAULT_CAPTION_PIPELINE_VERSION
    visual_limit: int | None = None
    ocr_max_pdf_pages: int | None = None
    pdf_page_low_text_chars: int = DEFAULT_PDF_PAGE_LOW_TEXT_CHARS
    caption_max_items: int | None = None
    write_caches: bool = True


@dataclass
class VisualEvidenceResult:
    """Visual evidence rows plus diagnostics for index metadata."""

    evidence_documents: list[EvidenceDocument]
    image_evidence: list[EvidenceDocument] = field(default_factory=list)
    ocr_evidence: list[EvidenceDocument] = field(default_factory=list)
    caption_evidence: list[EvidenceDocument] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VisualTarget:
    """One image-like input that can be OCRed or captioned."""

    asset_path: str
    local_path: Path | None
    metadata: dict[str, Any]
    context_text: str


@dataclass(frozen=True)
class PdfPageProfile:
    """Text-layer diagnostics for one PDF page."""

    record: dict[str, Any]
    page: int
    text_chars: int
    is_low_text_page: bool
    reason: str


def build_visual_evidence(config: VisualEvidenceConfig) -> VisualEvidenceResult:
    """Build image metadata, cached OCR, and optional caption evidence."""

    repo_root = config.repo_root.resolve()
    manifest_path = resolve_repo_path(config.manifest_path, repo_root)
    records = read_manifest_records(manifest_path, priority=config.priority)

    image_evidence: list[EvidenceDocument] = []
    if config.include_image_metadata:
        image_evidence.extend(
            build_manifest_image_evidence(
                records,
                repo_root=repo_root,
                pipeline_version=config.image_pipeline_version,
                limit=config.visual_limit,
            )
        )
    if config.include_markdown_image_refs:
        image_evidence.extend(
            build_markdown_image_ref_evidence(
                records,
                repo_root=repo_root,
                pipeline_version=config.image_pipeline_version,
                limit=config.visual_limit,
            )
        )

    if config.write_caches:
        write_evidence_jsonl(resolve_repo_path(config.image_cache_path, repo_root), image_evidence)

    targets = build_visual_targets(image_evidence, repo_root=repo_root)
    pdf_page_targets, pdf_profile_stats = build_pdf_page_targets(
        records,
        repo_root=repo_root,
        page_image_root=resolve_repo_path(config.page_image_root, repo_root),
        enabled=config.run_ocr or config.run_caption,
        max_pages_per_pdf=config.ocr_max_pdf_pages,
        low_text_chars=config.pdf_page_low_text_chars,
        limit=config.visual_limit,
    )
    targets.extend(pdf_page_targets)

    ocr_evidence = build_ocr_evidence(
        targets,
        repo_root=repo_root,
        cache_path=resolve_repo_path(config.ocr_cache_path, repo_root),
        provider_name=config.ocr_provider,
        pipeline_version=config.ocr_pipeline_version,
        run_ocr=config.run_ocr,
        write_cache=config.write_caches,
    )
    caption_evidence = build_caption_evidence(
        targets,
        repo_root=repo_root,
        cache_path=resolve_repo_path(config.caption_cache_path, repo_root),
        provider_name=config.caption_provider,
        pipeline_version=config.caption_pipeline_version,
        run_caption=config.run_caption,
        max_items=config.caption_max_items,
        write_cache=config.write_caches,
    )

    evidence_documents = [*image_evidence, *ocr_evidence, *caption_evidence]
    return VisualEvidenceResult(
        evidence_documents=evidence_documents,
        image_evidence=image_evidence,
        ocr_evidence=ocr_evidence,
        caption_evidence=caption_evidence,
        stats={
            "image_evidence": len(image_evidence),
            "ocr_evidence": len(ocr_evidence),
            "caption_evidence": len(caption_evidence),
            "visual_targets": len(targets),
            "run_ocr": config.run_ocr,
            "ocr_provider": config.ocr_provider,
            "pdf_page_low_text_chars": config.pdf_page_low_text_chars,
            "pdf_page_profile": pdf_profile_stats,
            "run_caption": config.run_caption,
            "caption_provider": config.caption_provider,
            "ocr_cache_path": safe_repo_relative(resolve_repo_path(config.ocr_cache_path, repo_root), repo_root),
            "caption_cache_path": safe_repo_relative(resolve_repo_path(config.caption_cache_path, repo_root), repo_root),
        },
    )


def read_manifest_records(manifest_path: Path, *, priority: str) -> list[dict[str, Any]]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    selected_priorities = parse_priority_filter(priority)
    records: list[dict[str, Any]] = []
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = normalize_manifest_record(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on manifest line {line_number}: {exc}") from exc
            if selected_priorities is not None and record.get("priority") not in selected_priorities:
                continue
            records.append(record)
    return records


def build_manifest_image_evidence(
    records: Iterable[dict[str, Any]],
    *,
    repo_root: Path,
    pipeline_version: str,
    limit: int | None,
) -> list[EvidenceDocument]:
    evidence: list[EvidenceDocument] = []
    for record in records:
        if record.get("parse_strategy") != "docling_image":
            continue
        if limit is not None and len(evidence) >= limit:
            break
        source = str(record.get("source") or "")
        if not source:
            continue
        local_path = resolve_repo_path(Path(source), repo_root)
        metadata = base_visual_metadata(
            record,
            source=source,
            source_name=source_name_from_source(source),
            asset_path=safe_repo_relative(local_path, repo_root),
            modality=IMAGE_MODALITY,
            evidence_kind=IMAGE_METADATA_KIND,
            parser_backend="visual_metadata",
            pipeline_version=pipeline_version,
        )
        metadata["source_hash"] = file_hash_or_source_hash(local_path, source)
        metadata["evidence_id"] = visual_evidence_id(metadata)
        page_content = "\n".join(
            part
            for part in (
                "图片资料",
                f"文件名：{metadata.get('source_name')}",
                f"课程：{metadata.get('course')}",
                f"类别：{metadata.get('category')}",
                f"图片路径：{metadata.get('asset_path')}",
                f"备注：{record.get('notes')}" if record.get("notes") else "",
            )
            if part
        )
        metadata["text_length"] = len(page_content)
        evidence.append(EvidenceDocument(page_content=page_content, metadata=metadata))
    return evidence


def build_markdown_image_ref_evidence(
    records: Iterable[dict[str, Any]],
    *,
    repo_root: Path,
    pipeline_version: str,
    limit: int | None,
) -> list[EvidenceDocument]:
    evidence: list[EvidenceDocument] = []
    for record in records:
        if str(record.get("file_type", "")).lower() not in {"md", "markdown"}:
            continue
        if int(record.get("image_ref_count") or 0) <= 0:
            continue
        source = str(record.get("source") or "")
        if not source:
            continue
        markdown_path = resolve_repo_path(Path(source), repo_root)
        if not markdown_path.exists():
            continue
        text = markdown_path.read_text(encoding="utf-8", errors="ignore")
        for ref_index, ref in enumerate(iter_markdown_image_refs(text, markdown_path, repo_root)):
            if limit is not None and len(evidence) >= limit:
                return evidence
            asset_path = ref["asset_path"]
            local_asset = resolve_local_asset(asset_path, repo_root)
            section_path = section_path_at_offset(text, ref["start"])
            context_before, context_after = context_around_ref(text, ref["start"], ref["end"])
            metadata = base_visual_metadata(
                record,
                source=source,
                source_name=source_name_from_source(source),
                asset_path=asset_path,
                modality=IMAGE_MODALITY,
                evidence_kind=IMAGE_REF_KIND,
                parser_backend="markdown_image_ref",
                pipeline_version=pipeline_version,
            )
            metadata.update(
                {
                    "section": section_path[-1] if section_path else None,
                    "section_path": " > ".join(section_path) if section_path else None,
                    "context_before": context_before or None,
                    "context_after": context_after or None,
                    "image_ref_index": ref_index,
                    "image_alt": ref.get("alt") or None,
                    "image_target": ref.get("target"),
                    "source_hash": file_hash_or_source_hash(local_asset, asset_path),
                }
            )
            metadata["evidence_id"] = visual_evidence_id(metadata, extra={"image_ref_index": ref_index})
            page_content = "\n".join(
                part
                for part in (
                    "Markdown 图片引用",
                    f"图片路径：{asset_path}",
                    f"alt 文本：{ref.get('alt')}" if ref.get("alt") else "",
                    f"所在文档：{metadata.get('source_name')}",
                    f"章节：{metadata.get('section_path')}" if metadata.get("section_path") else "",
                    f"前文：{context_before}" if context_before else "",
                    f"后文：{context_after}" if context_after else "",
                )
                if part
            )
            metadata["text_length"] = len(page_content)
            evidence.append(EvidenceDocument(page_content=page_content, metadata=metadata))
    return evidence


def build_visual_targets(
    evidence_documents: Iterable[EvidenceDocument],
    *,
    repo_root: Path,
) -> list[VisualTarget]:
    targets: list[VisualTarget] = []
    for evidence in evidence_documents:
        asset_path = evidence.metadata.get("asset_path")
        if not asset_path:
            continue
        local_path = resolve_local_asset(str(asset_path), repo_root)
        if local_path is None:
            continue
        if local_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        targets.append(
            VisualTarget(
                asset_path=str(asset_path),
                local_path=local_path,
                metadata=dict(evidence.metadata),
                context_text=evidence.page_content,
            )
        )
    return targets


def build_pdf_page_targets(
    records: Iterable[dict[str, Any]],
    *,
    repo_root: Path,
    page_image_root: Path,
    enabled: bool,
    max_pages_per_pdf: int | None,
    low_text_chars: int,
    limit: int | None,
) -> tuple[list[VisualTarget], dict[str, Any]]:
    if not enabled:
        return [], {
            "enabled": False,
            "pdf_files_scanned": 0,
            "pdf_pages_scanned": 0,
            "pdf_page_targets": 0,
            "low_text_chars": low_text_chars,
        }

    targets: list[VisualTarget] = []
    scanned_files = 0
    scanned_pages = 0
    file_level_low_text_pages = 0
    page_level_low_text_pages = 0
    for record in records:
        if str(record.get("file_type", "")).lower() != "pdf":
            continue
        source = str(record.get("source") or "")
        if not source:
            continue
        pdf_path = resolve_repo_path(Path(source), repo_root)
        if not pdf_path.exists():
            continue
        try:
            profiles = profile_pdf_pages(
                record,
                pdf_path=pdf_path,
                max_pages=max_pages_per_pdf,
                low_text_chars=low_text_chars,
            )
        except Exception as exc:  # noqa: BLE001 - visual evidence must be best effort.
            logger.warning("Failed to profile PDF pages %s: %s", source, exc)
            continue

        scanned_files += 1
        scanned_pages += len(profiles)
        selected_profiles = [profile for profile in profiles if profile.is_low_text_page]
        file_level_low_text_pages += sum(
            1 for profile in selected_profiles if profile.reason == "file_level_low_text"
        )
        page_level_low_text_pages += sum(
            1 for profile in selected_profiles if profile.reason == "page_text_below_threshold"
        )
        if not selected_profiles:
            continue

        try:
            rendered_pages = render_selected_pdf_pages(
                pdf_path,
                output_dir=page_image_root / str(record.get("doc_id") or pdf_path.stem),
                repo_root=repo_root,
                pages=[profile.page for profile in selected_profiles],
            )
        except Exception as exc:  # noqa: BLE001 - visual evidence must be best effort.
            logger.warning("Failed to render selected PDF pages %s: %s", source, exc)
            continue
        profile_by_page = {profile.page: profile for profile in selected_profiles}
        for page_number, image_path in rendered_pages:
            if limit is not None and len(targets) >= limit:
                return targets, build_pdf_profile_stats(
                    enabled=True,
                    scanned_files=scanned_files,
                    scanned_pages=scanned_pages,
                    targets=len(targets),
                    low_text_chars=low_text_chars,
                    file_level_low_text_pages=file_level_low_text_pages,
                    page_level_low_text_pages=page_level_low_text_pages,
                )
            profile = profile_by_page[page_number]
            asset_path = safe_repo_relative(image_path, repo_root)
            metadata = base_visual_metadata(
                record,
                source=source,
                source_name=source_name_from_source(source),
                asset_path=asset_path,
                modality=PDF_PAGE_MODALITY,
                evidence_kind="page_image",
                parser_backend="pypdfium2",
                pipeline_version=DEFAULT_IMAGE_EVIDENCE_PIPELINE_VERSION,
            )
            metadata.update(
                {
                    "page": page_number,
                    "section": f"Page {page_number}",
                    "section_path": f"Page {page_number}",
                    "pdf_page_text_chars": profile.text_chars,
                    "pdf_page_low_text_reason": profile.reason,
                    "pdf_page_low_text_chars": low_text_chars,
                    "pdf_file_is_text_extractable": record.get("is_text_extractable"),
                    "source_hash": file_hash_or_source_hash(image_path, asset_path),
                }
            )
            metadata["evidence_id"] = visual_evidence_id(metadata)
            targets.append(
                VisualTarget(
                    asset_path=asset_path,
                    local_path=image_path,
                    metadata=metadata,
                    context_text=f"PDF 页面图：{metadata.get('source_name')} page {page_number}",
                )
            )
    return targets, build_pdf_profile_stats(
        enabled=True,
        scanned_files=scanned_files,
        scanned_pages=scanned_pages,
        targets=len(targets),
        low_text_chars=low_text_chars,
        file_level_low_text_pages=file_level_low_text_pages,
        page_level_low_text_pages=page_level_low_text_pages,
    )


def build_pdf_profile_stats(
    *,
    enabled: bool,
    scanned_files: int,
    scanned_pages: int,
    targets: int,
    low_text_chars: int,
    file_level_low_text_pages: int,
    page_level_low_text_pages: int,
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "pdf_files_scanned": scanned_files,
        "pdf_pages_scanned": scanned_pages,
        "pdf_page_targets": targets,
        "low_text_chars": low_text_chars,
        "file_level_low_text_pages": file_level_low_text_pages,
        "page_level_low_text_pages": page_level_low_text_pages,
    }


def profile_pdf_pages(
    record: dict[str, Any],
    *,
    pdf_path: Path,
    max_pages: int | None,
    low_text_chars: int,
) -> list[PdfPageProfile]:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    if max_pages is not None:
        page_count = min(page_count, max_pages)

    file_level_low_text = record.get("is_text_extractable") is False
    profiles: list[PdfPageProfile] = []
    for page_index in range(page_count):
        page_number = page_index + 1
        try:
            text = reader.pages[page_index].extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - page-level profiling should continue.
            logger.warning("Failed to extract PDF page text %s page %s: %s", pdf_path, page_number, exc)
            text = ""
        text_chars = len("".join(text.split()))
        if file_level_low_text:
            is_low_text = True
            reason = "file_level_low_text"
        elif text_chars < low_text_chars:
            is_low_text = True
            reason = "page_text_below_threshold"
        else:
            is_low_text = False
            reason = "page_text_sufficient"
        profiles.append(
            PdfPageProfile(
                record=record,
                page=page_number,
                text_chars=text_chars,
                is_low_text_page=is_low_text,
                reason=reason,
            )
        )
    return profiles


def build_ocr_evidence(
    targets: Iterable[VisualTarget],
    *,
    repo_root: Path,
    cache_path: Path,
    provider_name: str,
    pipeline_version: str,
    run_ocr: bool,
    write_cache: bool,
) -> list[EvidenceDocument]:
    materialized_targets = list(targets)
    cached = cached_evidence_by_key(cache_path)
    if not run_ocr:
        return dedupe_evidence_by_id(cached.values())

    target_keys = {ocr_cache_key(target, provider_name, pipeline_version) for target in materialized_targets}
    selected = [cached[key] for key in target_keys if key in cached]
    missing_targets = [
        target
        for target in materialized_targets
        if ocr_cache_key(target, provider_name, pipeline_version) not in cached
    ]

    if run_ocr and missing_targets:
        try:
            provider = create_ocr_provider(provider_name)
        except Exception as exc:  # noqa: BLE001 - keep indexing usable.
            logger.warning("OCR provider %s is unavailable: %s", provider_name, exc)
            provider = None
        if provider is not None:
            text_cache: dict[str, tuple[str, list[dict[str, Any]]]] = {}
            for target in missing_targets:
                if target.local_path is None:
                    continue
                asset_key = stable_hash(
                    {
                        "provider": provider_name,
                        "source_hash": target.metadata.get("source_hash"),
                        "asset_path": target.asset_path,
                    }
                )
                if asset_key not in text_cache:
                    text_cache[asset_key] = provider.extract_text(target.local_path)
                text, lines = text_cache[asset_key]
                if not text.strip():
                    continue
                selected.append(
                    ocr_target_to_evidence(
                        target,
                        text=text,
                        lines=lines,
                        provider_name=provider_name,
                        pipeline_version=pipeline_version,
                    )
                )

    deduped = dedupe_evidence_by_id(selected)
    if write_cache and run_ocr:
        write_evidence_jsonl(cache_path, deduped)
    return deduped


def build_caption_evidence(
    targets: Iterable[VisualTarget],
    *,
    repo_root: Path,
    cache_path: Path,
    provider_name: str,
    pipeline_version: str,
    run_caption: bool,
    max_items: int | None,
    write_cache: bool,
) -> list[EvidenceDocument]:
    del repo_root
    materialized_targets = list(targets)
    if max_items is not None:
        materialized_targets = materialized_targets[:max_items]
    cached = cached_evidence_by_key(cache_path)
    if not run_caption:
        return dedupe_evidence_by_id(cached.values())

    target_keys = {caption_cache_key(target, provider_name, pipeline_version) for target in materialized_targets}
    selected = [cached[key] for key in target_keys if key in cached]
    missing_targets = [
        target
        for target in materialized_targets
        if caption_cache_key(target, provider_name, pipeline_version) not in cached
    ]

    if run_caption and provider_name not in {"", "none"} and missing_targets:
        try:
            provider = create_caption_provider(provider_name)
        except Exception as exc:  # noqa: BLE001 - captions are optional.
            logger.warning("Caption provider %s is unavailable: %s", provider_name, exc)
            provider = None
        if provider is not None:
            for target in missing_targets:
                if target.local_path is None:
                    continue
                caption = provider.caption(target.local_path, target.context_text)
                if not caption.strip():
                    continue
                selected.append(
                    caption_target_to_evidence(
                        target,
                        caption=caption,
                        provider_name=provider_name,
                        pipeline_version=pipeline_version,
                    )
                )

    deduped = dedupe_evidence_by_id(selected)
    if write_cache and run_caption:
        write_evidence_jsonl(cache_path, deduped)
    return deduped


def ocr_target_to_evidence(
    target: VisualTarget,
    *,
    text: str,
    lines: list[dict[str, Any]],
    provider_name: str,
    pipeline_version: str,
) -> EvidenceDocument:
    metadata = dict(target.metadata)
    metadata.update(
        {
            "modality": target.metadata.get("modality") or IMAGE_MODALITY,
            "evidence_kind": OCR_TEXT_KIND,
            "parser_backend": provider_name,
            "pipeline_version": pipeline_version,
            "ocr_provider": provider_name,
            "ocr_line_count": len(lines),
            "ocr_lines": lines[:50],
            "cache_key": ocr_cache_key(target, provider_name, pipeline_version),
            "text_length": len(text),
        }
    )
    metadata["evidence_id"] = visual_evidence_id(metadata)
    return EvidenceDocument(page_content=text, metadata=metadata)


def caption_target_to_evidence(
    target: VisualTarget,
    *,
    caption: str,
    provider_name: str,
    pipeline_version: str,
) -> EvidenceDocument:
    metadata = dict(target.metadata)
    metadata.update(
        {
            "modality": target.metadata.get("modality") or IMAGE_MODALITY,
            "evidence_kind": CAPTION_KIND,
            "parser_backend": provider_name,
            "pipeline_version": pipeline_version,
            "caption_provider": provider_name,
            "cache_key": caption_cache_key(target, provider_name, pipeline_version),
            "text_length": len(caption),
        }
    )
    metadata["evidence_id"] = visual_evidence_id(metadata)
    return EvidenceDocument(page_content=caption, metadata=metadata)


class RapidOcrProvider:
    """RapidOCR wrapper using the version installed in the project venv."""

    def __init__(self) -> None:
        from rapidocr import RapidOCR

        self.engine = RapidOCR()

    def extract_text(self, image_path: Path) -> tuple[str, list[dict[str, Any]]]:
        result = self.engine(image_path)
        txts = list(getattr(result, "txts", ()) or ())
        scores = list(getattr(result, "scores", ()) or ())
        boxes = getattr(result, "boxes", None)
        lines: list[dict[str, Any]] = []
        for index, text in enumerate(txts):
            line = {
                "text": str(text),
                "score": float(scores[index]) if index < len(scores) else None,
            }
            if boxes is not None and index < len(boxes):
                try:
                    line["box"] = boxes[index].tolist()
                except AttributeError:
                    line["box"] = boxes[index]
            lines.append(line)
        return "\n".join(str(text) for text in txts if str(text).strip()), lines


class LlamaCppCliCaptionProvider:
    """Best-effort Qwen3-VL caption provider through llama.cpp's mtmd CLI."""

    def __init__(self) -> None:
        self.executable = os.environ.get("COURSE_RAG_LLAMA_MTMD_CLI") or shutil.which(
            "llama-mtmd-cli"
        )
        if not self.executable:
            raise RuntimeError(
                "llama-mtmd-cli not found. Set COURSE_RAG_LLAMA_MTMD_CLI or install llama.cpp CLI."
            )
        self.model_path = os.environ.get("COURSE_RAG_QWEN3_VL_GGUF")
        self.mmproj_path = os.environ.get("COURSE_RAG_QWEN3_VL_MMPROJ")
        if not self.model_path or not self.mmproj_path:
            raise RuntimeError(
                "Set COURSE_RAG_QWEN3_VL_GGUF and COURSE_RAG_QWEN3_VL_MMPROJ for caption generation."
            )

    def caption(self, image_path: Path, context_text: str) -> str:
        prompt = (
            "请用中文简洁描述这张课程资料图片。重点说明图中可见文字、结构、流程关系、"
            "表格或题目信息。不要编造看不见的内容。"
        )
        if context_text:
            prompt += f"\n相关上下文：{context_text[:800]}"
        command = [
            self.executable,
            "-m",
            self.model_path,
            "--mmproj",
            self.mmproj_path,
            "--image",
            str(image_path),
            "-p",
            prompt,
            "--temp",
            "0.1",
            "-n",
            "512",
        ]
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "llama-mtmd-cli failed")
        return completed.stdout.strip()


def create_ocr_provider(provider_name: str) -> Any:
    normalized = provider_name.strip().lower()
    if normalized == "rapidocr":
        return RapidOcrProvider()
    raise ValueError(f"Unsupported OCR provider: {provider_name}")


def create_caption_provider(provider_name: str) -> Any:
    normalized = provider_name.strip().lower().replace("_", "-")
    if normalized in {"llama-cpp", "llama-cpp-cli", "llama_cpp"}:
        return LlamaCppCliCaptionProvider()
    raise ValueError(f"Unsupported caption provider: {provider_name}")


def cached_evidence_by_key(path: Path) -> dict[str, EvidenceDocument]:
    if not path.exists():
        return {}
    cached: dict[str, EvidenceDocument] = {}
    for evidence in read_evidence_jsonl(path):
        key = evidence.metadata.get("cache_key")
        if key:
            cached[str(key)] = evidence
    return cached


def ocr_cache_key(target: VisualTarget, provider_name: str, pipeline_version: str) -> str:
    return stable_hash(
        {
            "kind": OCR_TEXT_KIND,
            "provider": provider_name,
            "pipeline_version": pipeline_version,
            "source": target.metadata.get("source"),
            "page": target.metadata.get("page"),
            "asset_path": target.asset_path,
            "source_hash": target.metadata.get("source_hash"),
            "section_path": target.metadata.get("section_path"),
        }
    )


def caption_cache_key(target: VisualTarget, provider_name: str, pipeline_version: str) -> str:
    return stable_hash(
        {
            "kind": CAPTION_KIND,
            "provider": provider_name,
            "pipeline_version": pipeline_version,
            "source": target.metadata.get("source"),
            "page": target.metadata.get("page"),
            "asset_path": target.asset_path,
            "source_hash": target.metadata.get("source_hash"),
            "section_path": target.metadata.get("section_path"),
        }
    )


def base_visual_metadata(
    record: dict[str, Any],
    *,
    source: str,
    source_name: str | None,
    asset_path: str,
    modality: str,
    evidence_kind: str,
    parser_backend: str,
    pipeline_version: str,
) -> dict[str, Any]:
    return {
        "doc_id": record.get("doc_id"),
        "source_doc_id": record.get("doc_id") or stable_hash({"source": source}),
        "source": source,
        "source_name": source_name,
        "source_stem": Path(source_name or source).stem,
        "course": record.get("course"),
        "category": record.get("category"),
        "file_type": record.get("file_type"),
        "visibility": record.get("visibility"),
        "priority": record.get("priority"),
        "parse_strategy": record.get("parse_strategy"),
        "asset_path": asset_path,
        "modality": modality,
        "evidence_kind": evidence_kind,
        "parser_backend": parser_backend,
        "pipeline_version": pipeline_version,
        "page": None,
        "section": None,
        "section_path": None,
        "context_before": None,
        "context_after": None,
    }


def visual_evidence_id(metadata: dict[str, Any], extra: dict[str, Any] | None = None) -> str:
    payload = evidence_id_payload(
        metadata=metadata,
        modality=str(metadata.get("modality") or ""),
        evidence_kind=str(metadata.get("evidence_kind") or ""),
    )
    if extra:
        payload.update(extra)
    return stable_hash(payload)


def iter_markdown_image_refs(text: str, markdown_path: Path, repo_root: Path) -> Iterable[dict[str, Any]]:
    for match in MARKDOWN_IMAGE_PATTERN.finditer(text):
        yield build_markdown_ref(
            match.group("target"),
            markdown_path,
            repo_root,
            alt=match.group("alt"),
            start=match.start(),
            end=match.end(),
        )
    for match in HTML_IMAGE_PATTERN.finditer(text):
        yield build_markdown_ref(
            match.group("target"),
            markdown_path,
            repo_root,
            alt="",
            start=match.start(),
            end=match.end(),
        )


def build_markdown_ref(
    target: str,
    markdown_path: Path,
    repo_root: Path,
    *,
    alt: str,
    start: int,
    end: int,
) -> dict[str, Any]:
    cleaned_target = unquote(target.strip().strip("<>").replace("\\", "/"))
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", cleaned_target):
        asset_path = cleaned_target
    else:
        resolved = (markdown_path.parent / cleaned_target).resolve()
        asset_path = safe_repo_relative(resolved, repo_root)
    return {
        "alt": alt.strip(),
        "target": target,
        "asset_path": asset_path,
        "start": start,
        "end": end,
    }


def section_path_at_offset(text: str, offset: int) -> tuple[str, ...]:
    headings: dict[int, str] = {}
    running_offset = 0
    for raw_line in text.splitlines(keepends=True):
        if running_offset >= offset:
            break
        match = MARKDOWN_HEADING_PATTERN.match(raw_line.strip())
        if match:
            level = len(match.group("hashes"))
            headings = {key: value for key, value in headings.items() if key < level}
            headings[level] = match.group("title").strip()
        running_offset += len(raw_line)
    return tuple(headings[level] for level in sorted(headings))


def context_around_ref(text: str, start: int, end: int, width: int = 360) -> tuple[str, str]:
    before = clean_markdown_context(text[max(0, start - width) : start])
    after = clean_markdown_context(text[end : min(len(text), end + width)])
    return before, after


def clean_markdown_context(text: str) -> str:
    text = MARKDOWN_IMAGE_PATTERN.sub("", text)
    text = HTML_IMAGE_PATTERN.sub("", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    return " ".join(text.split()).strip()


def render_selected_pdf_pages(
    pdf_path: Path,
    *,
    output_dir: Path,
    repo_root: Path,
    pages: list[int],
) -> list[tuple[int, Path]]:
    del repo_root
    import pypdfium2 as pdfium

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(pdf_path))
    rendered: list[tuple[int, Path]] = []
    for page_number in sorted(set(pages)):
        page_index = page_number - 1
        if page_index < 0 or page_index >= len(pdf):
            continue
        image_path = output_dir / f"page_{page_number:04d}.png"
        if not image_path.exists():
            page = pdf[page_index]
            pil_image = page.render(scale=2).to_pil()
            pil_image.save(image_path)
        rendered.append((page_number, image_path.resolve()))
    return rendered


def resolve_local_asset(asset_path: str, repo_root: Path) -> Path | None:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", asset_path):
        return None
    path = Path(asset_path)
    if path.is_absolute():
        return path if path.exists() else None
    resolved = (repo_root / path).resolve()
    return resolved if resolved.exists() else None


def file_hash_or_source_hash(path: Path | None, fallback: str) -> str:
    if path is None or not path.exists() or not path.is_file():
        return stable_hash({"source": fallback})
    digest = stable_hash(
        {
            "path": str(path),
            "size": path.stat().st_size,
            "sha1": file_sha1(path),
        }
    )
    return digest


def file_sha1(path: Path) -> str:
    import hashlib

    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dedupe_evidence_by_id(evidence_documents: Iterable[EvidenceDocument]) -> list[EvidenceDocument]:
    deduped: dict[str, EvidenceDocument] = {}
    for evidence in evidence_documents:
        evidence_id = str(evidence.metadata.get("evidence_id") or stable_hash(evidence.to_dict()))
        deduped[evidence_id] = evidence
    return list(deduped.values())


def resolve_repo_path(path: Path, repo_root: Path) -> Path:
    if path.is_absolute():
        return path
    return (repo_root / path).resolve()


def safe_repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
