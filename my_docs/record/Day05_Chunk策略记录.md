# Day05 Chunk 策略记录

## 模块定位

Day05 负责把 Day04 输出的 `LoadedDocument` 切成适合检索和生成的文档单元。

当前不直接把完整文档送入向量库，而是采用 **父子文档策略**：

```text
LoadedDocument
-> ParentDocument 生成上下文
-> ChunkedDocument 检索单元
-> parent_child_map: child_chunk_id -> parent_doc_id
```

核心目标是：

```text
检索粒度足够细，生成上下文足够完整，来源信息可追溯
```

## 最终 Chunk 策略

| 数据类型 | 父节点 | 子 chunk 切分 | 原因 |
| --- | --- | --- | --- |
| Markdown 课堂笔记 | Markdown 标题章节 | 过长章节再递归切分 | 标题是天然语义边界，适合保留章节路径 |
| DOCX / Docling 文档 | Docling Markdown 标题；无标题时整篇文档 | 递归字符切分 | Docling 已转成 Markdown 风格文本，可复用标题策略 |
| 文本型 PDF 课件 | 每页一个父节点 | 页内递归字符切分 | 页码最适合 citation，页内再细分提升检索精度 |
| TXT / 无标题文本 | 加载后的文档本身 | 递归字符切分 | 缺少可靠结构，不强行制造章节 |

默认配置：

```text
chunk_size = 500
chunk_overlap = 80
use_parent_context = true
```

这组参数只是 MVP 起点。后续需要结合 embedding 模型、召回效果和生成成本继续调。

## 为什么使用父子文档策略

RAG 中“检索”和“生成”的最佳文本粒度不同：

- 检索需要小 chunk：主题更集中，向量语义更清晰。
- 生成需要大上下文：保留定义、例子、前后解释和引用信息。

如果直接检索大文档，多个主题会混在一个向量里，相关性容易被稀释。如果只把小 chunk 交给 LLM，又可能上下文不足。父子文档策略的折中是：

```text
向量库检索 child chunk
-> 根据 parent_child_map 找回 parent document
-> 用 parent document 参与答案生成
```

课程资料很适合这种方式，因为问题通常指向细粒度概念，但回答时需要章节、页码和前后说明。

## 为什么 Markdown 优先按标题切

Markdown 标题本身就是文档结构信息，例如：

```text
二. 编译过程与编译器构造 > 2. 五个阶段
```

保留标题路径的价值：

- chunk 能追溯到具体章节。
- 模型能理解片段所处语境。
- 后续展示来源时，比只显示文件名更清晰。

当前实现使用 `MarkdownHeaderTextSplitter` 识别 `#` 到 `####`，并保留标题文本。对超长章节，再交给递归字符切分器控制 chunk 大小。

## 为什么 PDF 以页作为父节点

Day04 加载层已经把文本型 PDF 拆成页级 `LoadedDocument`。因此 Day05 不再把 PDF 当作整份 Markdown 切标题，而是沿用“页”作为父节点。

原因：

- PDF 的页码是最稳定的引用单位。
- 整份 PDF 作为父节点太大，生成时容易带入大量无关内容。
- 一页通常能覆盖一个课件页面内的定义、例子、图注或公式说明。

页内仍使用 `RecursiveCharacterTextSplitter`，是因为一页不一定只有一个主题。短页通常只产生一个 chunk；长页或列表密集页会被继续拆细，提升向量检索精度。

## 为什么使用 RecursiveCharacterTextSplitter

当前项目主要是中文课程资料，含有段落、列表、公式说明和中英文混排。简单固定长度切分容易打断句子或术语。

递归字符切分的思路是按语义边界从粗到细尝试：

```text
段落 -> 换行 -> 中文句读 -> 英文标点 -> 空格 -> 字符
```

它的优点是：

- 优先保留段落和句子完整性。
- 遇到超长文本时仍能继续切到目标大小。
- 不依赖额外 embedding 模型，适合 MVP 阶段稳定落地。

当前额外加入了中文标点分隔符，如 `。`、`，`、`？`、`！`，避免中文长句只按空格切分。

## Metadata 设计

每个子 chunk 都保留：

```text
source
source_doc_id
parent_doc_id
chunk_id
page
section / section_path
chunk_index
chunk_in_parent_index
```

这些字段服务于四件事：

- 向量库索引。
- 检索结果展示。
- 从子 chunk 找回父文档。
- 回答时提供文件、章节或页码来源。

`chunk_id` 和 `parent_doc_id` 使用稳定 hash 生成，避免每次运行 ID 都变化，方便后续增量索引和调试。

## 当前实现文件

主要实现：

```text
course_rag/app/rag/chunking.py
```

主要对象：

```text
ChunkingConfig
ParentDocument
ChunkedDocument
ChunkingResult
chunk_documents()
resolve_generation_contexts()
```

依赖补充：

```text
langchain-text-splitters
```

## 验证结果简记

已用真实 loader 数据做过小批量验证：

| 验证项 | 结果 |
| --- | --- |
| Markdown 标题切分 | 能保留 `section_path` |
| DOCX / Docling 文档 | 能生成父子映射 |
| PDF 页级文档 | 能保留 `source + page` |
| 父子映射数量 | 与 chunk 数量一致 |
| 抽查 preview | 未发现明显乱码 |

其中 PDF 会出现极短 chunk，例如封面、尾页或过渡页。当前不默认过滤，等 Day06/Day11 结合检索质量和评测结果再决定是否加最小长度或低信息页过滤。

## 后续优化方向

- 根据具体 embedding 模型，把字符级参数调整为更接近 token 级的配置。
- 比较不同 `chunk_size` / `chunk_overlap` 对召回率、答案完整性和成本的影响。
- 在向量索引前增加低信息 chunk 过滤策略。
- 对图示密集页、表格密集页接入 OCR / VLM caption，生成增强型 page chunk。
