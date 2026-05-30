# AGENTS.md

本文件记录本仓库的长期协作规则。除非用户明确临时覆盖，后续处理本项目任务时应优先遵守这些规则。

## 项目学习与开发工作流

本项目的学习与开发路径是：

1. 参考 `my_docs/plan/` 下的 DayXX 计划。
2. 阅读 `docs/` 下对应学习文档。
3. 调研当前相关方向的主流方法、较新实践或常见工程方案。
4. 必要时阅读 `code/` 下对应示例代码；`code/`、`data/`、`Extra-chapter/` 默认不主动读取，只有计划、文档或用户明确需要时再读取相关文件。
5. 结合用户当前需求、业务场景和项目现状，选择适合 `course_rag/` 的实现方案。
6. 在 `course_rag/` 下实现或改进项目功能。
7. 完成后更新 `my_docs/record/` 下对应记录文档。
8. 如果改动影响 RAG 主流程，同步更新 `course_rag/docs/RAG_WORKFLOW.md`。

`my_docs/plan/` 中的文件是初始学习计划，不是强制实现规格。实际执行时应结合用户当前需求、业务场景、主流方法和项目完成度灵活调整。

## 目录边界

主要工作目录是 `course_rag/`。

常用文档目录：

- `my_docs/plan/`：学习计划，仅作参考。
- `my_docs/record/`：实际完成记录，需要随阶段成果更新。
- `course_rag/docs/`：项目内部说明文档，尤其是 `RAG_WORKFLOW.md`。
- `docs/`：默认学习资料来源。

默认不要主动读取以下目录：

- `Extra-chapter/`
- 根目录 `code/`
- 根目录 `data/`

根目录图片和展示资源默认忽略，例如：

- `内测群二维码.png`
- `emoji.png`
- `logo.svg`
- `project01.png`
- `project01_graph.png`

## Python 环境

当前项目虚拟环境位于：

```powershell
.\rag\
```

运行 Python、测试、FastAPI、脚本时默认使用：

```powershell
.\rag\Scripts\python.exe
```

不要假设存在 `course_rag/.venv`、`.venv` 或系统 Python 环境。

如果需要启动服务，默认命令是：

```powershell
.\rag\Scripts\python.exe -X utf8 -m uvicorn course_rag.app.main:app --reload
```

## 文档更新规则

修改 `course_rag/` 下代码后，按影响范围更新文档：

- 影响 RAG 主流程、模型、索引、检索、rerank、生成、API 参数或返回结构时，更新 `course_rag/docs/RAG_WORKFLOW.md`。
- 完成某一天计划中的阶段任务时，更新或新增 `my_docs/record/DayXX_*.md`。
- 不主动修改 `my_docs/plan/`，除非用户明确要求调整计划文件。

文档内容保持简洁，优先记录：

- 当前采用什么策略及简要原理（这部分介绍的稍微多一些）。
- 如有必要，介绍使用什么模型或库。
- 该阶段做了什么。
- 如何运行或验证（尽量简洁）。

不要把文档写成过长的原理讲解。

## 代码修改规则

改代码前先检查现有实现，不凭计划文件直接重写。

优先沿用当前项目结构：

- FastAPI 入口：`course_rag/app/main.py`
- API schema：`course_rag/app/schemas.py`
- RAG 模块：`course_rag/app/rag/`
- 工作流文档：`course_rag/docs/RAG_WORKFLOW.md`

保持改动聚焦，不做无关重构。

不要主动修改或删除用户已有改动。遇到未提交改动时，应先识别是否与当前任务相关。

## 验证规则

代码改动后优先使用当前虚拟环境验证：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app
```

涉及 API 时，优先用 FastAPI `TestClient` 做轻量验证；只有需要人工访问页面或 Swagger 时才启动 uvicorn。

涉及 LLM 的验证默认避免真实外部调用，可使用：

```json
{
  "use_llm": false
}
```

如果必须调用外部 API、下载模型或安装依赖，需要先说明影响并等待用户确认。

## 编码与中文文档

中文 Markdown 和代码注释使用 UTF-8。

在 PowerShell 中读取中文文件时优先使用：

```powershell
Get-Content -Encoding UTF8
```

避免因默认编码导致中文乱码。
