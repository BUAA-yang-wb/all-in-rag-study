# Day 12：Docker 与工程化整理

## 今日目标

整理依赖、配置和启动方式，让项目具备可复现运行能力。Docker 是加分项，但本地启动必须稳定。

## 学习输入

- `code/docker-compose.yml`
- `code/C8/requirements.txt`

## 预计完成工作

1. 补齐依赖文件：

```text
course_rag/requirements.txt
```

2. 增加环境变量样例：

```text
course_rag/.env.example
```

3. 统一配置读取方式，例如：
   - API Key
   - embedding 模型名
   - LLM 模型名
   - chunk size
   - top_k
   - 是否开启 rerank
4. 编写 Dockerfile：

```text
course_rag/Dockerfile
```

5. 编写 Docker Compose：

```text
course_rag/docker-compose.yml
```

6. README 中写清楚两套启动方式：
   - 本地 Python 启动。
   - Docker 启动。

## 验收标准

- 本地命令能稳定启动。
- Docker 启动如果因模型下载或网络问题失败，也要在 README 中写清楚限制和替代方案。
- 不把真实 API Key、私有课程资料、向量索引大文件提交到 GitHub。
- `.gitignore` 覆盖常见敏感文件和缓存目录。

## 当日输出

- `course_rag/requirements.txt`
- `course_rag/.env.example`
- `course_rag/Dockerfile`
- `course_rag/docker-compose.yml`
- `my_docs/Day12_工程化整理记录.md`

## 注意事项

Docker 不是主线里最重要的能力。如果它卡住，不要牺牲评测、README 和可运行 MVP。简历里只有在 Docker 真正可用时再写 Docker Compose。
