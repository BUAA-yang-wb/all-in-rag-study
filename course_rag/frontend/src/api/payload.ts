import type {
  AskFormState,
  AskRequest,
  SearchFormState,
  SearchRequest,
} from "@/types/api";

export function optionalNumber(value: Event): number | null {
  const input = value.target as HTMLInputElement;
  return input.value === "" ? null : Number(input.value);
}

export function buildAskRequest(form: AskFormState): AskRequest {
  const payload: AskRequest = {
    question: form.question.trim(),
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
  };

  if (form.candidate_k !== null) {
    payload.candidate_k = form.candidate_k;
  }

  return payload;
}

export function buildSearchRequest(form: SearchFormState): SearchRequest {
  const payload: SearchRequest = {
    query: form.query.trim(),
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
  };

  if (form.candidate_k !== null) {
    payload.candidate_k = form.candidate_k;
  }

  return payload;
}
