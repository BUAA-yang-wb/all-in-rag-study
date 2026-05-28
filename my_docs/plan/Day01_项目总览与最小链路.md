# Day 01：项目总览与最小链路

## 今日目标

建立对 `all-in-rag` 的整体认识，跑通或至少完整理解一个最小 RAG 链路。今天不追求功能完整，重点是知道 RAG 从文档到回答的每一步在做什么。

## 学习输入

- `README.md`
- `docs/chapter1/03_get_start_rag.md`
- `code/C1/`
- `docs/chapter8/01_env_architecture.md`

## 预计完成工作

1. 新建学习分支，例如 `study-rag`。
2. 建立 Python / Conda 环境，优先使用 Python 3.12 附近版本。
3. 阅读 README，明确项目结构：`docs/` 是教程，`code/` 是代码，`data/` 是样例数据。
4. 找到最小 RAG 示例，理解链路：

```text
文档加载
-> 文本切分
-> embedding
-> 向量存储
-> 用户提问
-> 相似度检索
-> 拼接 prompt
-> 大模型生成答案
-> 返回答案和引用来源
```

5. 尝试跑通最小 demo。如果因为 API Key、模型下载或依赖问题无法跑通，要记录具体错误。
6. 在 `my_docs/` 下记录第一天笔记，写清楚最小 RAG 链路和遇到的问题。

## 验收标准

- 能用自己的话画出 RAG 基础流程。
- 能说明 embedding、向量库、检索、prompt 的作用。
- 能跑通一个最小 demo，或至少能定位缺少的 API Key / 模型下载 / 依赖问题。
- 能说清楚 `all-in-rag` 是学习和参考底座，不是最终直接写进简历的项目。

## 当日输出

- `my_docs/Day01_RAG学习记录.md` 或同类学习记录。
- 一段自己写的最小 RAG 流程说明。
- 至少 1 个可复现命令或 1 条明确的报错记录。

## 当天不要做

- 不要开始 Graph RAG。
- 不要纠结所有 LangChain / LlamaIndex API。
- 不要一次性通读完整仓库。
