# Day 10：接入 rerank 并配置化

## 今日目标

在混合检索之后加入可选 rerank，让系统支持“先召回、再精排”的标准 RAG 检索流程。rerank 不应阻塞主线，优先做成可配置模块。

## 学习输入

- `code/C4/07_rerank_and_refine.py`

## 预计完成工作

1. 新增或完善 rerank 模块：

```text
course_rag/app/rag/rerank.py
```

2. 可选模型方向：
   - `bge-reranker` 类模型。
   - 轻量 cross-encoder。
   - 如果本地模型太慢，先保留接口和配置开关。
3. 修改检索 pipeline：

```text
召回 top_n 候选
-> RRF 融合
-> rerank 取 top_k
-> 生成答案
```

4. 增加配置项：

```yaml
use_rerank: false
rerank_top_n: 20
final_top_k: 5
```

5. 保存 3 个 rerank 前后的排序对比。

## 验收标准

- 配置文件中可切换 `use_rerank: true/false`。
- rerank 关闭时系统仍能正常工作。
- 至少有 3 个 rerank 前后排序对比样例。
- 能解释 rerank 和 embedding 检索的区别。

## 当日输出

- `course_rag/app/rag/rerank.py`
- 配置项更新。
- `my_docs/Day10_Rerank记录.md`

## 风险处理

如果 rerank 模型下载或推理太慢，不要强行卡住。可以先完成可插拔接口，并在 README 中写成“支持配置化接入 reranker”。只有真正跑通并有对比结果时，简历里才写“接入 reranker 并优化排序”。
