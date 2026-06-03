import os
import json
import time
from threading import Lock
from dotenv import load_dotenv
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_milvus import Milvus
from pymilvus import connections
from langchain_core.tools import tool

# ==============================================================================
# 修复 pymilvus 2.6.x 与 langchain-milvus 0.3.x 之间的兼容性问题
# ==============================================================================
original_fetch = connections._fetch_handler
def patched_fetch(alias):
    try:
        return original_fetch(alias)
    except Exception:
        from pymilvus.client.connection_manager import ConnectionManager
        mgr = ConnectionManager.get_instance()
        for mc in mgr._registry.values():
            if f"cm-{id(mc.handler)}" == alias:
                return mc.handler
        for mc in mgr._dedicated.values():
            if f"cm-{id(mc.handler)}" == alias:
                return mc.handler
        raise
connections._fetch_handler = patched_fetch
# ==============================================================================

dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path, override=True)

_milvus_instance = None
_milvus_lock = Lock()

def _log_elapsed(scope: str, label: str, start: float) -> float:
    now = time.perf_counter()
    print(f"⏱️ [{scope}] {label}: {now - start:.2f}s")
    return now

def _get_embedding_api_key() -> str | None:
    explicit_key = (
        os.getenv("DASHSCOPE_EMBEDDING_API_KEY")
        or os.getenv("EMBEDDING_API_KEY")
    )
    if explicit_key:
        return explicit_key.strip()

    if os.getenv("LLM_API_KEY") and os.getenv("DASHSCOPE_API_KEY"):
        return os.getenv("DASHSCOPE_API_KEY").strip()

    base_url = (os.getenv("BASE_URL") or "").lower()
    if "dashscope.aliyuncs.com" in base_url:
        api_key = os.getenv("DASHSCOPE_API_KEY")
        return api_key.strip() if api_key else None
    return None

def _get_milvus_store():
    global _milvus_instance
    if _milvus_instance is not None:
        return _milvus_instance

    with _milvus_lock:
        if _milvus_instance is not None:
            return _milvus_instance

        api_key = _get_embedding_api_key()
        if not api_key:
            raise RuntimeError(
                "未配置 DashScope embedding key。若聊天模型使用 DeepSeek，请设置 "
                "DASHSCOPE_EMBEDDING_API_KEY 或 EMBEDDING_API_KEY 后再启用向量检索。"
            )

        milvus_host = os.getenv("MILVUS_HOST", "localhost")
        milvus_port = os.getenv("MILVUS_PORT", "19530")
        milvus_uri = f"http://{milvus_host}:{milvus_port}"

        total_start = time.perf_counter()
        step_start = total_start
        print(f"🔌 [Init] 正在连接 Milvus 向量数据库: {milvus_uri}")
        embeddings = DashScopeEmbeddings(
            dashscope_api_key=api_key,
            model="text-embedding-v2"
        )
        step_start = _log_elapsed("milvus:init", "初始化 DashScopeEmbeddings", step_start)

        _milvus_instance = Milvus(
            embedding_function=embeddings,
            connection_args={"uri": milvus_uri},
            collection_name="cloud_product_docs",
            auto_id=True,
            drop_old=False
        )
        _log_elapsed("milvus:init", "创建 Milvus VectorStore", step_start)
        _log_elapsed("milvus:init", "Milvus 向量工具初始化总耗时", total_start)
    return _milvus_instance

@tool
def query_vector_db(query: str) -> str:
    """
    通过语义搜索查询精神科临床指南和诊断标准（RAG）。
    当需要检索 ICD-11 诊断标准原文、中国精神科指南摘要、药物说明书详细内容时，使用此工具。
    """
    try:
        total_start = time.perf_counter()
        step_start = total_start
        print(f"🔎 [MilvusTool] query={query[:120]!r}")
        store = _get_milvus_store()
        step_start = _log_elapsed("milvus:tool", "获取 Milvus VectorStore", step_start)
        results = store.similarity_search_with_score(query, k=3)
        step_start = _log_elapsed("milvus:tool", f"similarity_search_with_score rows={len(results)}", step_start)
        
        if not results:
            _log_elapsed("milvus:tool", "向量工具总耗时", total_start)
            return "未在文档中检索到相关信息。"

        formatted_results = []
        for i, (doc, score) in enumerate(results):
            source = os.path.basename(doc.metadata.get('source', 'Unknown'))
            content = doc.page_content.strip()
            formatted_results.append(f"【来源: {source}】\n{content}")
            
        _log_elapsed("milvus:tool", "向量工具总耗时", total_start)
        return "\n\n".join(formatted_results)
    except Exception as e:
        return f"查询向量数据库时发生错误: {str(e)}"
