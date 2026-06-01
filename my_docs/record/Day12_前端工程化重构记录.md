# Day12 前端工程化重构记录

## 本次实现

- 将原 `course_rag/app/static/index.html` 单文件前端改为 Vue 3 + Vite + TypeScript 工程。
- 新增 `course_rag/frontend/`，前端源码按 API、类型、组件、样式分层。
- Vite 构建产物输出到 `course_rag/app/static/frontend/`，由 FastAPI 继续托管。
- FastAPI 的 RAG API 不变，仍使用 `/health`、`/ingest`、`/ask`、`/search`。

## 前端策略

当前前端定位为“学习笔记风”的课程资料问答工作台。页面重点不是营销展示，而是让用户清楚看到：

- 服务和索引是否可用。
- 当前问题、生成答案和 LLM 状态。
- 引用来源、页码、章节、score 和 rerank/RRF 调试信息。
- `/search` 的检索证据，便于比较 dense、BM25、hybrid 和 rerank 效果。

高级参数放在折叠面板中，默认不打断主要问答流程，但可以直接调整 `strategy`、`rrf_k`、`candidate_k`、`rerank_top_n`、`rerank_model`、上下文长度、`temperature`、`max_tokens` 等已有 API 参数。

## 运行方式

开发时需要分别启动后端和前端：

```powershell
.\rag\Scripts\python.exe -X utf8 -m uvicorn course_rag.app.main:app --reload
```

```powershell
cd course_rag/frontend
npm run dev
```

构建后只需要启动 FastAPI：

```powershell
cd course_rag/frontend
npm run build
```

```powershell
.\rag\Scripts\python.exe -X utf8 -m uvicorn course_rag.app.main:app --reload
```

构建产物位于：

```text
course_rag/app/static/frontend/
```

## 验证

推荐验证命令：

```powershell
cd course_rag/frontend
npm run typecheck
npm run build
```

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app
```

涉及 `/ask` 手工验证时，优先使用 `use_llm=false`，避免真实外部 LLM 调用。
