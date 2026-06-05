# Course RAG

`course_rag/` 是本仓库中的课程资料 RAG 应用，包含 FastAPI 后端、Vue 前端、RAG 核心模块、Milvus 本地部署配置、评测脚本和项目说明文档。

当前主线状态：

- 默认在线检索后端：Milvus standalone，默认连接 `http://localhost:19530`。
- 默认 collection：`course_rag_v2_text`。
- 当前 collection entity 数：`9138`，与当前 `vector_index_v2_text/` 的 chunk 数一致。
- FAISS 索引仍保留，作为 Milvus 导入源和显式 fallback。
- 本阶段只做文本 evidence 检索，不包含页面图向量、图片向量、ColPali 或 ColQwen。

## 目录结构

```text
course_rag/
├─ app/                         # FastAPI 后端入口与 RAG 服务代码
│  ├─ main.py                   # API 入口，提供 /health、/ingest、/ask、/search
│  ├─ schemas.py                # API 请求和响应模型
│  ├─ rag/                      # 文档加载、evidence、chunk、索引、检索、rerank、生成
│  └─ static/frontend/          # Vue 前端 npm run build 后的静态产物
├─ deploy/milvus/               # Milvus standalone Docker Compose 配置
├─ docs/                        # Course RAG 内部说明文档
├─ eval/                        # golden set、评测脚本和评测结果
├─ frontend/                    # Vue 3 + Vite + TypeScript 前端工程
├─ scripts/                     # 数据处理和 Milvus 启停/检查脚本
├─ data/                        # 本地课程资料和处理中间数据，默认不提交
├─ vector_index_v2_text/        # 当前 FAISS baseline，默认不提交
└─ requirements.txt             # Python 后端依赖
```

## 环境约定

Python 虚拟环境位于仓库根目录：

```powershell
.\rag\Scripts\python.exe
```

不要默认使用系统 Python、`.venv` 或 `course_rag/.venv`。

Milvus 使用本地 Docker Compose standalone，会启动三个容器：

- `milvus-standalone`
- `milvus-etcd`
- `milvus-minio`

首次启动会拉取镜像；后续只要 Docker Desktop 和容器保持运行，在线查询会一直使用 Milvus。

## 快速启动

1. 打开 Docker Desktop，并等待 Docker daemon 正常运行。

2. 启动 Milvus：

```powershell
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_up.ps1
```

3. 首次启动或 FAISS baseline 更新后，重建 Milvus collection：

```powershell
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_rebuild_index.ps1
```

4. 检查 Milvus collection 和小样本查询：

```powershell
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_check.ps1
```

5. 启动 FastAPI：

```powershell
.\rag\Scripts\python.exe -X utf8 -m uvicorn course_rag.app.main:app --reload
```

后端地址：

```text
http://127.0.0.1:8000
```

Swagger：

```text
http://127.0.0.1:8000/docs
```

## 前端开发

```powershell
cd course_rag\frontend
npm.cmd run dev
```

开发地址：

```text
http://127.0.0.1:5173
```

如果已经执行过前端构建，FastAPI 也会托管 `course_rag/app/static/frontend/` 下的静态页面。

## API 使用

默认 `/search` 和 `/ask` 不传 `index_backend` 时走 Milvus：

```json
{
  "query": "FIRST FOLLOW 表格",
  "top_k": 3,
  "use_rerank": false
}
```

显式使用 FAISS fallback：

```json
{
  "query": "FIRST FOLLOW 表格",
  "index_backend": "faiss",
  "top_k": 3,
  "use_rerank": false
}
```

`/health` 会返回 Milvus 状态字段：

- `milvus_configured`
- `milvus_connected`
- `milvus_collection`
- `milvus_error`

Milvus 未启动或 collection 未构建时，默认请求会返回明确错误，不会静默回退到 FAISS。

## 验证命令

语法检查：

```powershell
.\rag\Scripts\python.exe -m compileall course_rag\app course_rag\eval
```

Milvus dry-run：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\app\rag\milvus_index.py --dry-run
```

快速评测：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast --index-backend milvus --no-write-doc
```

Milvus 与 FAISS 对比：

```powershell
.\rag\Scripts\python.exe -X utf8 course_rag\eval\run_eval.py --profile fast --index-backend milvus --compare-index-backend faiss --no-write-doc
```

当前已验证结果：

- Milvus collection entity_count：`9138`
- `/health`：`status=ok`，`milvus_connected=true`
- 默认 `/search`：`index.backend="milvus"`
- 显式 FAISS fallback：可用
- Milvus/FAISS Top-K overlap 平均值：`0.9895`
- Milvus/FAISS Top-1 变化率：`0.0`

## 停止服务

停止 FastAPI：关闭对应 uvicorn 终端，或停止其进程。

停止 Milvus 容器但保留数据：

```powershell
powershell -ExecutionPolicy Bypass -File course_rag\scripts\milvus_down.ps1
```

Milvus 数据保存在：

```text
course_rag/deploy/milvus/volumes/
```

该目录已加入 `.gitignore`，不会提交数据库数据。
