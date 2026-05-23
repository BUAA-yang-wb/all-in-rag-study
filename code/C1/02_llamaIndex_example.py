import os
# os.environ['HF_ENDPOINT']='https://hf-mirror.com'
from dotenv import load_dotenv
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings 
from llama_index.llms.openai_like import OpenAILike
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# 加载环境变量（读取 .env 中的 API_KEY）
load_dotenv()

# ================= 1. 全局模型配置 =================
# 配置大语言模型 (LLM)，这里使用 OpenAILike 接口调用 DeepSeek
Settings.llm = OpenAILike(
    model="deepseek-v4-flash",
    api_key=os.getenv("DEEPSEEK_API_KEY_RAGLEARN"),
    api_base="https://api.deepseek.com",
    is_chat_model=True
)

# Settings.llm = OpenAI(
#     model="deepseek-chat",
#     api_key=os.getenv("DEEPSEEK_API_KEY"),
#     api_base="https://api.deepseek.com"
# )

# 配置词向量模型 (Embedding Model)，使用本地 HuggingFace 的 BGE 中文模型
Settings.embed_model = HuggingFaceEmbedding("BAAI/bge-small-zh-v1.5")

# ================= 2. 数据加载与索引构建 =================
# 读取指定的本地 Markdown 文件，转化为 LlamaIndex 的文档对象
docs = SimpleDirectoryReader(input_files=["../../data/C1/markdown/easy-rl-chapter1.md"]).load_data()

# 将文档切块并调用词向量模型转化为向量，存入内存中的向量索引 (VectorStoreIndex)
index = VectorStoreIndex.from_documents(docs)

# ================= 3. 检索与查询 =================
# 将构建好的索引对象转化为核心的查询引擎
query_engine = index.as_query_engine()

# 打印查询引擎底层使用的默认提示词模板 (text_qa_template, refine_template)
print(query_engine.get_prompts())

# 针对我们的问题进行检索拉取上下文，并交给大语言模型生成最终回答
print(query_engine.query("文中举了哪些例子?"))