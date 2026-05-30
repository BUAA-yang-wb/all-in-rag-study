# Day08 FastAPI 封装记录

## 本次实现

- 新增 `course_rag/app/main.py`，把 Day07 的问答链路封装为 FastAPI 服务。
- 新增 `course_rag/app/schemas.py`，定义请求与响应模型。
- 删除 `course_rag/app/main_cli.py` 和 `course_rag/main.py`，后续统一使用 API 入口。
- `course_rag/requirements.txt` 补充 `fastapi`、`uvicorn`。

## API 接口

- `GET /health`：检查服务、索引文件和内存缓存状态。
- `POST /ask`：输入问题，返回生成答案、引用和检索调试信息。
- `POST /search`：只返回检索片段，不调用 LLM。
- `POST /ingest`：加载现有索引；`rebuild=true` 时重建索引。

## 启动命令

```powershell
.\rag\Scripts\python.exe -m uvicorn course_rag.app.main:app --reload
```

Swagger 地址：

```text
http://127.0.0.1:8000/docs
```

也可以直接运行模块：

```powershell
.\rag\Scripts\python.exe -m course_rag.app.main
```

## 请求样例

### /ask

```json
{
  "question": "编译过程有哪些阶段？",
  "top_k": 5,
  "use_llm": true
}
```

### /search

```json
{
  "query": "运输层的主要功能是什么？",
  "top_k": 5
}
```

### /ingest

```json
{
  "rebuild": false
}
```

## 当前判断

- Day08 后主要入口是 FastAPI，不再是命令行脚本。
- `/ask` 的答案不是写死的，会根据用户输入实时检索并生成。
- `/search` 替代原 CLI 的检索调试能力。
- 宽泛问题仍可能存在跨课程混召回，后续需要课程过滤、查询改写或 rerank。
