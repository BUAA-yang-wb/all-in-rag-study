# Day 02：复现 `code/C8` 完整项目

## 今日目标

复现 `code/C8` 的完整文本 RAG 项目，理解它的模块划分。今天的重点是读懂并跑通现有项目，为后续二次开发做准备。

## 学习输入

- `docs/chapter8/01_env_architecture.md`
- `docs/chapter8/02_data_preparation.md`
- `docs/chapter8/03_index_retrieval.md`
- `docs/chapter8/04_generation_sys.md`
- `code/C8/main.py`
- `code/C8/config.py`
- `code/C8/rag_modules/*.py`

## 预计完成工作

1. 安装 `code/C8/requirements.txt` 中的核心依赖。
2. 配置必要的 API Key，例如 `MOONSHOT_API_KEY`。
3. 尝试运行：

```bash
cd code/C8
python main.py
```

4. 阅读并标注 4 个核心模块：
   - `DataPreparationModule`
   - `IndexConstructionModule`
   - `RetrievalOptimizationModule`
   - `GenerationIntegrationModule`
5. 记录每个模块的输入、输出、关键方法。
6. 理解 `code/C8` 的父子文档策略：小块用于检索，大块用于生成。
7. 至少提出 3 个可以二次开发的改造点，例如：
   - 数据从菜谱改为课程资料。
   - 增加 PDF/TXT 加载。
   - 返回引用来源。
   - 增加 FastAPI。
   - 增加评测脚本。

## 验收标准

- 能解释 `code/C8` 为什么使用父子文档策略。
- 能解释 BM25 + 向量检索 + RRF 的位置。
- 能独立找到数据加载、索引构建、检索融合、LLM 生成分别在哪些文件中。
- 能说明 `code/C8` 哪些逻辑可以复用，哪些必须改造成自己的项目。

## 当日输出

- `my_docs/Day02_C8模块拆解.md`
- 一张模块调用关系图，文字版即可。
- 3 到 5 条明确的二次开发改造点。

## 注意事项

如果运行失败，不要卡太久。今天最重要的是读懂结构，运行问题可以记录后续集中解决。
