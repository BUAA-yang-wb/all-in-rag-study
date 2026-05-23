# BUAA RAG Project Workflow

## Standard Task Procedure

Use this procedure for development, debugging, explanation, and project-packaging tasks.

1. Classify the request by day or RAG module.
2. Read `my_docs/plan/00_RAG两周学习计划索引.md`.
3. Read the matching daily plan from `my_docs/plan/`.
4. Read the mapped tutorial docs and example code from `references/project-map.md`.
5. Inspect the current `course_rag/` implementation if it exists.
6. Implement or explain using the smallest project-useful change.
7. Verify with a targeted command, API call, smoke test, or manual inspection.
8. Summarize what changed, what was verified, and what should come next.

## Context Discipline

- Do not read every `docs/` chapter or every `code/` example.
- Prefer `code/C8` for end-to-end architecture and module boundaries.
- Prefer `code/C4` only for retrieval/rerank-related work.
- Prefer `code/C6` only for evaluation-related work.
- Treat `docs/` as conceptual support and `code/` as implementation pattern reference.

## Development Rules

- Keep the final project independent under `course_rag/`; do not modify `code/C8` unless the user explicitly asks to patch the tutorial code.
- Preserve traceability from answer to source file, section, page, and chunk whenever possible.
- Keep model/API configuration externalized through config files or `.env`; never hardcode API keys.
- Prefer runnable MVPs over broad refactors.
- Add evaluation or debug visibility when implementing retrieval behavior.
- Keep README and resume claims aligned with verified functionality.

## Default Module Order

Follow this build order unless the user asks for a specific module:

```text
loaders
-> chunking
-> indexing
-> retrieval
-> generation
-> FastAPI
-> evaluation
-> Docker/README/resume
```

## Avoid by Default

Do not prioritize these in the first two-week project unless explicitly requested:

- Graph RAG
- Multimodal RAG
- Text2SQL
- Neo4j
- Large Milvus deployment
- Model training or fine-tuning
- Complex frontend work

## Answer Shape

For implementation tasks, include:

- Current plan/day/module being used.
- Relevant source files inspected.
- Implementation summary.
- Verification command or result.
- Next project-useful step.

For explanation tasks, include:

- How the concept appears in `all-in-rag`.
- How it maps to `course_rag/`.
- What to remember for interviews or resume discussion.
