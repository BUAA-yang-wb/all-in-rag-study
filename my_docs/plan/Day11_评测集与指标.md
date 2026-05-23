# Day 11：构建评测集与指标

## 今日目标

构建小型课程问答评测集，并用 Recall@K、MRR、引用命中率对不同检索策略进行对比。今天的目标是让项目具备“可验证效果”的证据。

## 学习输入

- `docs/chapter6/18_system_evaluation.md`
- `docs/chapter6/19_common_tools.md`
- `code/C6/01_llamaindex_evaluation_example.py`

## 预计完成工作

1. 创建评测集：

```text
course_rag/eval/eval_dataset.jsonl
```

2. 每条评测数据建议格式：

```json
{
  "question": "什么是注意力机制？",
  "gold_sources": ["深度学习笔记.md#注意力机制"],
  "gold_answer_keywords": ["query", "key", "value", "加权求和"]
}
```

3. 构建 30 到 50 个问题，类型建议：

| 类型 | 数量 | 示例 |
| --- | --- | --- |
| 概念解释 | 10 | 什么是注意力机制？ |
| 实验/作业流程 | 8 | 实验二需要提交哪些文件？ |
| 资料定位 | 8 | 哪里讲到了反向传播？ |
| 对比类问题 | 6 | CNN 和 Transformer 的区别是什么？ |
| 易混淆问题 | 5 | 课程中 softmax 用在哪些地方？ |

4. 实现评测脚本：

```text
course_rag/eval/run_eval.py
```

5. 计算指标：
   - `Recall@K`：正确来源是否出现在 Top-K 检索结果中。
   - `MRR`：第一个正确来源排名越靠前越好。
   - `Citation Hit Rate`：最终答案引用是否命中正确来源。
6. 对比至少 3 组实验：
   - dense
   - hybrid
   - hybrid + rerank

## 验收标准

- 至少有 30 个评测问题。
- 能生成 Markdown 或 JSON 评测报告。
- README 中有一张结果表。
- 能解释指标分别衡量 RAG pipeline 的哪一部分。

## 当日输出

- `course_rag/eval/eval_dataset.jsonl`
- `course_rag/eval/run_eval.py`
- `course_rag/eval/results/` 下的实验结果。
- `my_docs/Day11_评测记录.md`

## 建议实验表

| 实验 | chunk_size | top_k | strategy | rerank | Recall@5 | MRR | Citation Hit Rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 500 | 5 | dense | no | 待填 | 待填 | 待填 |
| hybrid | 500 | 5 | hybrid | no | 待填 | 待填 | 待填 |
| hybrid-rerank | 500 | 10->5 | hybrid | yes | 待填 | 待填 | 待填 |
| chunk-ablation | 800 | 5 | hybrid | no | 待填 | 待填 | 待填 |
