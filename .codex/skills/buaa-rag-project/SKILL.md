---
name: buaa-rag-project
description: Use for the user's BUAA course-material RAG project based on datawhalechina/all-in-rag. Trigger when requests mention all-in-rag, 北航课程资料 RAG, my_docs/plan daily tasks, course_rag development, document loading, text chunking, embeddings, FAISS, BM25, RRF, rerank, evaluation metrics such as Recall@K/MRR/citation hit rate, FastAPI, Docker, README, resume bullets, or internship-oriented RAG project implementation.
---

# BUAA RAG Project

## Core Workflow

Before answering or editing, ground the task in the project plan and the relevant repository examples.

1. Confirm the workspace is `All_in_RAG`. If not, ask for the repository path.
2. Read `my_docs/plan/00_RAG两周学习计划索引.md` first when the task relates to the two-week RAG plan.
3. Identify the relevant day or module from the user request.
4. Read the matching daily plan in `my_docs/plan/`.
5. Read only the relevant `docs/chapter*` tutorial files and `code/C*` examples.
6. Inspect existing `course_rag/` files before proposing or changing implementation.
7. Keep the work tied to the final resume project: runnable code, citations, evaluation, API packaging, and clear README evidence.

Use `references/project-map.md` to choose the right plan, docs, and example code. Use `references/workflow.md` for task execution rules.

## Response Priorities

Prefer concrete project progress over broad theory:

- Explain how the requested task fits the final BUAA course-material RAG system.
- Reuse patterns from `all-in-rag`, especially `code/C8`, before inventing new architecture.
- Keep implementations minimal, modular, and testable.
- Preserve source metadata and citation traceability whenever documents, chunks, retrieval, or generation are involved.
- Include a verification step: command, expected output, API request, or manual check.
- Avoid Graph RAG, multimodal RAG, Text2SQL, Neo4j, and large Milvus deployment unless the user explicitly asks.

## Implementation Defaults

Use these defaults unless the user or existing code says otherwise:

- Project directory: `course_rag/`
- Backend: FastAPI
- Embedding model: `BAAI/bge-small-zh-v1.5`
- Vector store: FAISS
- Sparse retrieval: BM25
- Fusion: RRF
- Rerank: optional and config-gated
- Evaluation: Recall@K, MRR, citation hit rate
- Frontend: Swagger is enough for v1 unless the user asks for a UI

## When Developing Code

Follow the repo's existing constraints and the current Codex instructions:

- Read existing files first.
- Keep edits scoped to the requested module.
- Do not commit private course materials, API keys, generated vector indexes, or large model files.
- Add or update README/resume wording only after the implementation can be honestly supported.
- If a model download or API call blocks verification, add a local/debug fallback when practical and report the limitation.
