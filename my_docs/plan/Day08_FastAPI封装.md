# Day 08：FastAPI 封装

## 今日目标

把命令行 MVP 封装成 FastAPI 服务，让项目具备工程化展示能力。今天的关键是 API 设计清晰，而不是做复杂前端。

## 学习输入

- `code/C8/main.py`
- FastAPI 请求响应模型基础用法

## 预计完成工作

1. 实现文件：

```text
course_rag/app/main.py
course_rag/app/schemas.py
```

2. 至少提供接口：
   - `GET /health`
   - `POST /ingest`
   - `POST /ask`
   - `POST /search`
3. 设计 `/ask` 响应格式：

```json
{
  "answer": "回答文本",
  "citations": [
    {
      "source": "文件名",
      "section": "章节",
      "page": 1,
      "text": "命中的片段"
    }
  ],
  "retrieval": {
    "strategy": "hybrid",
    "top_k": 5
  }
}
```

4. `/search` 接口单独返回检索结果，用于调试 dense / bm25 / hybrid。
5. 启动服务：

```bash
uvicorn app.main:app --reload
```

## 验收标准

- `GET /health` 返回正常。
- Swagger 页面可以完成一次问答。
- `/search` 能单独展示检索结果。
- API 响应中包含 citations，不只是纯文本答案。

## 当日输出

- `course_rag/app/main.py`
- `course_rag/app/schemas.py`
- Swagger 问答截图或请求样例。
- `my_docs/Day08_FastAPI封装记录.md`

## 注意事项

今天不建议做复杂前端。Swagger 足够支撑第一版展示，比粗糙前端更稳。
