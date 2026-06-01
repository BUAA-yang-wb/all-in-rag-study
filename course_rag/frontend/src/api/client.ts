import type {
  AskRequest,
  AskResponse,
  HealthResponse,
  IngestResponse,
  SearchRequest,
  SearchResponse,
} from "@/types/api";

async function requestJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  const text = await response.text();
  const payload = text ? parseJson(text) : null;

  if (!response.ok) {
    const detail = readErrorDetail(payload) || response.statusText;
    throw new Error(`HTTP ${response.status}: ${detail}`);
  }

  return payload as T;
}

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function readErrorDetail(payload: unknown): string | null {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail?: unknown }).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  return null;
}

export function fetchHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/health");
}

export function loadIndex(): Promise<IngestResponse> {
  return requestJson<IngestResponse>("/ingest", {
    method: "POST",
    body: JSON.stringify({ rebuild: false }),
  });
}

export function askQuestion(payload: AskRequest): Promise<AskResponse> {
  return requestJson<AskResponse>("/ask", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function searchEvidence(payload: SearchRequest): Promise<SearchResponse> {
  return requestJson<SearchResponse>("/search", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
