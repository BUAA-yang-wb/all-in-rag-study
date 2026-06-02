export type RetrievalStrategy = "hybrid" | "dense" | "bm25";

export interface Citation {
  id: number;
  rank?: number | null;
  score: number;
  evidence_id?: string | null;
  source_doc_id?: string | null;
  modality?: string | null;
  evidence_kind?: string | null;
  asset_path?: string | null;
  parser_backend?: string | null;
  context_before?: string | null;
  context_after?: string | null;
  source?: string | null;
  source_name?: string | null;
  course?: string | null;
  category?: string | null;
  page?: number | string | null;
  section?: string | null;
  section_path?: string | null;
  chunk_id?: string | null;
  parent_doc_id?: string | null;
  text?: string | null;
  chunk_preview?: string | null;
  context_preview?: string | null;
  retrieval_strategy?: string | null;
  retrievers?: string[];
  dense_rank?: number | null;
  dense_score?: number | null;
  bm25_rank?: number | null;
  bm25_score?: number | null;
  rrf_score?: number | null;
  pre_rerank_rank?: number | null;
  pre_rerank_score?: number | null;
  rerank_rank?: number | null;
  rerank_score?: number | null;
  rerank_model?: string | null;
  pre_routing_rank?: number | null;
  pre_routing_score?: number | null;
  metadata_filter_match?: boolean | null;
  metadata_boost?: number | null;
  matched_filters?: string[];
  matched_intents?: string[];
}

export interface IndexInfo {
  index_dir: string;
  vectors: number;
  embedding_model?: string | null;
}

export interface RoutingInfo {
  enabled?: boolean;
  active?: boolean;
  explicit_filters?: Record<string, string | number | boolean | null>;
  inferred_filters?: Record<string, string | number | boolean | null>;
  applied_filters?: Record<string, string | number | boolean | null>;
  intents?: string[];
  matched_source_name?: string | null;
  filter_applied?: boolean;
  filter_fallback?: boolean;
  candidate_count_before?: number;
  candidate_count_after?: number;
  boosted_count?: number;
  notes?: string[];
}

export interface HealthResponse {
  status: string;
  index_exists: boolean;
  index_loaded: boolean;
  index?: IndexInfo | null;
}

export interface IngestResponse {
  status: string;
  message: string;
  index?: IndexInfo | null;
}

export interface AskRequest {
  question: string;
  top_k: number;
  candidate_k?: number;
  strategy: RetrievalStrategy;
  rrf_k: number;
  use_rerank: boolean;
  rerank_top_n: number;
  rerank_model: string;
  rerank_batch_size: number;
  rerank_device: string;
  rerank_local_files_only: boolean;
  use_llm: boolean;
  use_parent_context: boolean;
  min_chunk_chars: number;
  max_context_chars: number;
  max_context_chars_per_source: number;
  preview_chars: number;
  temperature: number;
  max_tokens: number;
  use_metadata_routing: boolean;
  course?: string;
  category?: string;
  source_name?: string;
  page?: number | string;
  modality?: string;
  evidence_kind?: string;
}

export interface AskResponse {
  question: string;
  answer: string;
  citations: Citation[];
  retrieval: Citation[];
  used_llm: boolean;
  llm_error?: string | null;
  retrieval_strategy: string;
  retrievers: string[];
  use_rerank: boolean;
  rerank_used: boolean;
  rerank_model?: string | null;
  rerank_device?: string | null;
  rerank_error?: string | null;
  routing: RoutingInfo;
  pipeline: string[];
  index: IndexInfo;
}

export interface SearchRequest {
  query: string;
  top_k: number;
  candidate_k?: number;
  strategy: RetrievalStrategy;
  rrf_k: number;
  use_rerank: boolean;
  rerank_top_n: number;
  rerank_model: string;
  rerank_batch_size: number;
  rerank_device: string;
  rerank_local_files_only: boolean;
  use_parent_context: boolean;
  min_chunk_chars: number;
  preview_chars: number;
  use_metadata_routing: boolean;
  course?: string;
  category?: string;
  source_name?: string;
  page?: number | string;
  modality?: string;
  evidence_kind?: string;
}

export interface SearchResponse {
  query: string;
  citations: Citation[];
  retrieval: Citation[];
  strategy: string;
  retrievers: string[];
  use_rerank: boolean;
  rerank_used: boolean;
  rerank_model?: string | null;
  rerank_device?: string | null;
  rerank_error?: string | null;
  routing: RoutingInfo;
  top_k: number;
  pipeline: string[];
  index: IndexInfo;
}

export interface AskFormState {
  question: string;
  top_k: number;
  candidate_k: number | null;
  strategy: RetrievalStrategy;
  rrf_k: number;
  use_rerank: boolean;
  rerank_top_n: number;
  rerank_model: string;
  rerank_batch_size: number;
  rerank_device: string;
  rerank_local_files_only: boolean;
  use_llm: boolean;
  use_parent_context: boolean;
  min_chunk_chars: number;
  max_context_chars: number;
  max_context_chars_per_source: number;
  preview_chars: number;
  temperature: number;
  max_tokens: number;
  use_metadata_routing: boolean;
  course: string;
  category: string;
  source_name: string;
  page: string;
  modality: string;
  evidence_kind: string;
}

export interface SearchFormState {
  query: string;
  top_k: number;
  candidate_k: number | null;
  strategy: RetrievalStrategy;
  rrf_k: number;
  use_rerank: boolean;
  rerank_top_n: number;
  rerank_model: string;
  rerank_batch_size: number;
  rerank_device: string;
  rerank_local_files_only: boolean;
  use_parent_context: boolean;
  min_chunk_chars: number;
  preview_chars: number;
  use_metadata_routing: boolean;
  course: string;
  category: string;
  source_name: string;
  page: string;
  modality: string;
  evidence_kind: string;
}

export type NoticeType = "info" | "success" | "warning" | "error";
