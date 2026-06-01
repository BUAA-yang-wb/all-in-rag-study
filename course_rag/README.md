# Course RAG

`course_rag/` 是当前仓库中的课程资料 RAG 应用目录，包含 FastAPI 后端、Vue 前端、RAG 核心模块、项目文档和本地索引数据。

## 目录结构

```text
course_rag/
├─ app/                  # FastAPI 后端入口与 RAG 服务代码
│  ├─ main.py            # API 入口，提供 /health、/ingest、/ask、/search，并托管构建后的前端
│  ├─ schemas.py         # API 请求和响应模型
│  ├─ rag/               # 文档加载、chunk、索引、检索、rerank、生成等核心流程
│  └─ static/frontend/   # Vue 前端 npm run build 后的静态产物
├─ frontend/             # Vue 3 + Vite + TypeScript 前端工程
│  ├─ src/api/           # 前端 API 请求封装
│  ├─ src/components/    # 问答、检索、状态栏、引用列表等组件
│  ├─ src/styles/        # 前端样式分层
│  └─ package.json       # 前端 npm 命令和依赖
├─ docs/                 # Course RAG 内部说明文档
├─ eval/                 # 评测相关文件
├─ scripts/              # 数据处理、索引构建等辅助脚本
├─ data/                 # 本地课程资料和处理中间数据
├─ vector_index/         # 本地 FAISS 向量索引
└─ requirements.txt      # Python 后端依赖
```

## 启动命令

开发时前后端分别启动。

后端 FastAPI：

```powershell
.\rag\Scripts\python.exe -X utf8 -m uvicorn course_rag.app.main:app --reload
```

前端 Vue/Vite：

```powershell
cd course_rag\frontend
npm run dev
```

如果 PowerShell 中 `npm` 被拦截，可以改用：

```powershell
npm.cmd run dev
```

开发地址：

- 后端 API：`http://127.0.0.1:8000`
- 前端页面：`http://127.0.0.1:5173`
