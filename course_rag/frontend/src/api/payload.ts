import type {
  AskFormState,
  AskRequest,
  SearchFormState,
  SearchRequest,
} from "@/types/api";

type MetadataPayload = Pick<
  AskRequest,
  | "use_metadata_routing"
  | "course"
  | "category"
  | "source_name"
  | "page"
  | "modality"
  | "evidence_kind"
>;

type MetadataForm = Pick<
  AskFormState,
  | "use_metadata_routing"
  | "course"
  | "category"
  | "source_name"
  | "page"
  | "modality"
  | "evidence_kind"
>;

export function optionalNumber(value: Event): number | null {
  const input = value.target as HTMLInputElement;
  return input.value === "" ? null : Number(input.value);
}

export function buildAskRequest(form: AskFormState): AskRequest {
  const payload: AskRequest = {
    question: form.question.trim(),
    milvus_uri: normalizedMilvusUri(form.milvus_uri),
    milvus_collection: normalizedMilvusCollection(form.milvus_collection),
    top_k: form.top_k,
    strategy: form.strategy,
    rrf_k: form.rrf_k,
    use_rerank: form.use_rerank,
    rerank_top_n: form.rerank_top_n,
    rerank_model: form.rerank_model.trim(),
    rerank_batch_size: form.rerank_batch_size,
    rerank_device: form.rerank_device.trim(),
    rerank_local_files_only: form.rerank_local_files_only,
    use_llm: form.use_llm,
    use_parent_context: form.use_parent_context,
    min_chunk_chars: form.min_chunk_chars,
    max_context_chars: form.max_context_chars,
    max_context_chars_per_source: form.max_context_chars_per_source,
    preview_chars: form.preview_chars,
    temperature: form.temperature,
    max_tokens: form.max_tokens,
    use_metadata_routing: form.use_metadata_routing,
  };

  if (form.candidate_k !== null) {
    payload.candidate_k = form.candidate_k;
  }
  addMetadataFilters(payload, form);

  return payload;
}

export function buildSearchRequest(form: SearchFormState): SearchRequest {
  const payload: SearchRequest = {
    query: form.query.trim(),
    milvus_uri: normalizedMilvusUri(form.milvus_uri),
    milvus_collection: normalizedMilvusCollection(form.milvus_collection),
    top_k: form.top_k,
    strategy: form.strategy,
    rrf_k: form.rrf_k,
    use_rerank: form.use_rerank,
    rerank_top_n: form.rerank_top_n,
    rerank_model: form.rerank_model.trim(),
    rerank_batch_size: form.rerank_batch_size,
    rerank_device: form.rerank_device.trim(),
    rerank_local_files_only: form.rerank_local_files_only,
    use_parent_context: form.use_parent_context,
    min_chunk_chars: form.min_chunk_chars,
    preview_chars: form.preview_chars,
    use_metadata_routing: form.use_metadata_routing,
  };

  if (form.candidate_k !== null) {
    payload.candidate_k = form.candidate_k;
  }
  addMetadataFilters(payload, form);

  return payload;
}

function addMetadataFilters(payload: MetadataPayload, form: MetadataForm) {
  addTrimmed(payload, "course", form.course);
  addTrimmed(payload, "category", form.category);
  addTrimmed(payload, "source_name", form.source_name);
  addTrimmed(payload, "page", form.page);
  addTrimmed(payload, "modality", form.modality);
  addTrimmed(payload, "evidence_kind", form.evidence_kind);
}

function addTrimmed<T extends keyof MetadataPayload>(
  payload: MetadataPayload,
  key: T,
  value: string,
) {
  const cleaned = value.trim();
  if (cleaned) {
    payload[key] = cleaned as MetadataPayload[T];
  }
}

function normalizedMilvusUri(value: string): string {
  return value.trim() || "http://localhost:19530";
}

function normalizedMilvusCollection(value: string): string {
  return value.trim() || "course_rag_v2_text";
}
