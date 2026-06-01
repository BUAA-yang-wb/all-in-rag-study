export type RetrievalStrategy = "hybrid" | "dense" | "bm25";

export interface Citation {
  id: number;
  rank?: number | null;
  score: number;
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
}

export interface IndexInfo {
  index_dir: string;
  vectors: number;
  embedding_model?: string | null;
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
}

export type NoticeType = "info" | "success" | "warning" | "error";
