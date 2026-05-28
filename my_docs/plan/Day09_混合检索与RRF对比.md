# Day 09：实现混合检索与 RRF 对比

## 今日目标

实现并对比 dense、BM25、hybrid 三种检索策略，让项目从普通向量检索 demo 升级为有检索优化能力的 RAG 系统。

## 学习输入

- `docs/chapter4/11_hybrid_search.md`
- `code/C4/01_hybrid_search.py`
- `code/C8/rag_modules/retrieval_optimization.py`

## 预计完成工作

1. 实现或完善文件：

```text
course_rag/app/rag/retrieval.py
```

2. 支持三种检索策略：
   - `dense`：只用向量检索。
   - `bm25`：只用关键词检索。
   - `hybrid`：BM25 + Dense + RRF。
3. 在 `/search` 接口中允许传入：

```json
{
  "query": "问题",
  "strategy": "hybrid",
  "top_k": 5
}
```

4. 实现 RRF 融合，记录每个候选 chunk 的来源和最终分数。
5. 对同一组问题比较三种策略的 Top-K 结果。
6. 保存 2 到 3 个能体现 hybrid 优势的案例。

## 验收标准

- 同一问题可以运行 dense、bm25、hybrid 三种策略。
- 能解释 BM25 和 embedding 检索的互补性。
- 能解释 RRF 为什么适合融合不同检索器结果。
- README 草稿中加入 2 到 3 个检索对比案例。

## 当日输出

- `course_rag/app/rag/retrieval.py`
- 三种检索策略的对比样例。
- `my_docs/Day09_混合检索记录.md`

## 面试表达重点

普通 PDF QA 往往只做向量检索。你的项目应强调“关键词召回 + 语义召回 + RRF 融合”，并能说明在哪些问题上 hybrid 更稳。
