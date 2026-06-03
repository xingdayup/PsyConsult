import os
import re
import time
from threading import RLock
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_neo4j import Neo4jGraph
from langchain_neo4j import GraphCypherQAChain
from langchain_core.prompts import PromptTemplate
from langchain_core.tools import tool

# 加载环境变量
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path, override=True)

# 全局单例，避免每次调用工具时重复连接数据库
_graph_chain_instance = None
_graph_instance = None
_graph_lock = RLock()

def _log_elapsed(scope: str, label: str, start: float) -> float:
    now = time.perf_counter()
    print(f"⏱️ [{scope}] {label}: {now - start:.2f}s")
    return now

def _use_llm_graph_cypher() -> bool:
    value = os.getenv("ENABLE_LLM_GRAPH_CYPHER", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}

def _get_graph_instance():
    """获取 Neo4jGraph 单例。只连接图谱，不创建 LLM Cypher Chain。"""
    global _graph_instance
    if _graph_instance is not None:
        return _graph_instance

    with _graph_lock:
        if _graph_instance is not None:
            return _graph_instance

        total_start = time.perf_counter()
        step_start = total_start
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://YOUR_NEO4J_HOST:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")

        print("🔌 [Init] 正在连接 Neo4j 数据库...")
        print(f"🔎 [Neo4j] uri={neo4j_uri} user={neo4j_user}")
        graph = Neo4jGraph(
            url=neo4j_uri,
            username=neo4j_user,
            password=os.getenv("NEO4J_PASSWORD", "YOUR_NEO4J_PASSWORD")
        )
        step_start = _log_elapsed("neo4j:init", "创建 Neo4jGraph 客户端", step_start)

        graph.refresh_schema()
        _log_elapsed("neo4j:init", "refresh_schema 扫描图谱结构", step_start)
        _log_elapsed("neo4j:init", "Neo4j 图谱连接总耗时", total_start)
        _graph_instance = graph
        return _graph_instance

def _get_graph_chain():
    """获取 GraphCypherQAChain 单例"""
    global _graph_chain_instance, _graph_instance
    if _graph_chain_instance is not None:
        return _graph_chain_instance

    with _graph_lock:
        if _graph_chain_instance is not None:
            return _graph_chain_instance

        total_start = time.perf_counter()
        step_start = total_start
        graph = _get_graph_instance()
        step_start = _log_elapsed("neo4j:chain", "获取 Neo4jGraph 实例", step_start)

        from config import get_settings
        llm = ChatOpenAI(**get_settings().get_model_config(), temperature=0)
        step_start = _log_elapsed("neo4j:init", "初始化 Cypher 生成 LLM", step_start)

        CYPHER_GENERATION_TEMPLATE = """Task:Generate Cypher statement to query a clinical knowledge graph.
Instructions:
Use only the provided relationship types and properties in the schema.
Do not use any other relationship types or properties that are not provided.

Schema:
{schema}

Important Rules:
1. 节点标签: Disease, Symptom, Drug, SideEffect, Treatment 等。
2. 注意属性访问: 如果你使用了 RETURN 语句返回某个属性，必须在前面的 MATCH 中给节点赋予一个变量名！
   错误示例: MATCH (:Disease {{id: "6A70"}}) RETURN name_cn
   正确示例: MATCH (d:Disease {{id: "6A70"}}) RETURN d.name_cn
3. 注意实体类型: Disease 是疾病（ICD-11编码），Symptom 是症状，Drug 是药物，SideEffect 是副作用，Treatment 是治疗方案。
4. 关系类型: HAS_SYMPTOM (Disease→Symptom), FIRST_LINE/SECOND_LINE (Disease→Treatment), CAUSES (Drug→SideEffect), INTERACTS_WITH (Drug↔Drug), USES_DRUG (Treatment→Drug)。
5. 查询返回格式: 返回的信息应尽可能详细，如果返回节点，请使用 RETURN node，而不是只返回 ID。

The question is:
{question}"""

        cypher_prompt = PromptTemplate(
            template=CYPHER_GENERATION_TEMPLATE,
            input_variables=["schema", "question"]
        )
        step_start = _log_elapsed("neo4j:chain", "构建 Cypher Prompt", step_start)

        _graph_chain_instance = GraphCypherQAChain.from_llm(
            llm=llm,
            graph=graph,
            cypher_prompt=cypher_prompt,
            verbose=False, # 工具调用时关闭详细日志，保持输出整洁
            return_intermediate_steps=False,
            allow_dangerous_requests=True,
        )
        step_start = _log_elapsed("neo4j:chain", "创建 GraphCypherQAChain", step_start)
        _log_elapsed("neo4j:chain", "GraphCypherQAChain 初始化总耗时", total_start)
    return _graph_chain_instance

def _extract_keywords(query: str) -> list[str]:
    lower_query = query.lower()
    tokens = re.findall(r"[a-z0-9._-]+", lower_query)
    cn_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", query)
    keywords = []
    for token in tokens + cn_tokens:
        if len(token.strip()) >= 2 and token not in keywords:
            keywords.append(token.strip())
    if not keywords:
        keywords.append(lower_query[:20] if lower_query else "ecs")
    return keywords[:8]

def _fallback_graph_keyword_search(query: str) -> str:
    total_start = time.perf_counter()
    step_start = total_start
    graph = _get_graph_instance()
    step_start = _log_elapsed("neo4j:fallback", "获取图谱连接", step_start)
    if graph is None:
        return "图谱关键词检索不可用，请稍后重试。"

    keywords = _extract_keywords(query)
    step_start = _log_elapsed("neo4j:fallback", f"提取关键词 {keywords}", step_start)
    
    # Neo4j 无法在 ANY/WHERE 中动态解包 $keywords 列表用于 CONTAINS 匹配，
    # 因此这里我们采用在 Python 中拼接 OR 语句的简单模式
    
    where_clauses = []
    for k in keywords:
        where_clauses.append(f"toLower(coalesce(n.id, '')) CONTAINS '{k}' OR toLower(coalesce(n.name, '')) CONTAINS '{k}' OR toLower(coalesce(n.description, '')) CONTAINS '{k}'")
    node_where = " OR ".join(where_clauses)
    
    node_cypher = f"""
    MATCH (n)
    WHERE {node_where}
    RETURN labels(n) AS labels, coalesce(n.id, n.name, '') AS node_key, properties(n) AS props
    LIMIT 8
    """
    
    rel_where_clauses = []
    for k in keywords:
        rel_where_clauses.append(f"toLower(coalesce(a.id, '')) CONTAINS '{k}' OR toLower(coalesce(a.name, '')) CONTAINS '{k}' OR toLower(coalesce(b.id, '')) CONTAINS '{k}' OR toLower(coalesce(b.name, '')) CONTAINS '{k}'")
    rel_where = " OR ".join(rel_where_clauses)

    rel_cypher = f"""
    MATCH (a)-[r]->(b)
    WHERE {rel_where}
    RETURN labels(a) AS from_labels, coalesce(a.id, a.name, '') AS from_node,
           type(r) AS rel, labels(b) AS to_labels, coalesce(b.id, b.name, '') AS to_node
    LIMIT 8
    """

    try:
        nodes = graph.query(node_cypher)
        step_start = _log_elapsed("neo4j:fallback", f"节点关键词查询 rows={len(nodes)}", step_start)
        relations = graph.query(rel_cypher)
        step_start = _log_elapsed("neo4j:fallback", f"关系关键词查询 rows={len(relations)}", step_start)
    except Exception as exc:
        _log_elapsed("neo4j:fallback", "关键词兜底查询失败", total_start)
        return f"图谱关键词检索失败: {str(exc)}"

    if not nodes and not relations:
        _log_elapsed("neo4j:fallback", "关键词兜底查询总耗时", total_start)
        return "未查询到相关图谱信息。"

    parts = ["图谱关键词检索结果："]
    if nodes:
        parts.append("命中节点：")
        for row in nodes:
            labels = ",".join(row.get("labels", []))
            node_key = row.get("node_key", "")
            props = row.get("props", {})
            parts.append(f"- [{labels}] {node_key} {props}")
    if relations:
        parts.append("命中关系：")
        for row in relations:
            from_labels = ",".join(row.get("from_labels", []))
            to_labels = ",".join(row.get("to_labels", []))
            parts.append(f"- [{from_labels}] {row.get('from_node', '')} -[{row.get('rel', '')}]-> [{to_labels}] {row.get('to_node', '')}")
    _log_elapsed("neo4j:fallback", "关键词兜底查询总耗时", total_start)
    return "\n".join(parts)

@tool
def query_knowledge_graph(query: str) -> str:
    """
    查询精神科临床知识图谱。
    当需要查询疾病-症状关联、药物-副作用关系、药物相互作用、治疗方案-药物关系等结构化医学知识时，使用此工具。
    输入参数 query 必须是明确的自然语言查询句子。
    """
    total_start = time.perf_counter()
    step_start = total_start
    print(f"🔎 [Neo4jTool] query={query[:120]!r}")
    if not _use_llm_graph_cypher():
        print("⚡ [Neo4jTool] 使用快速关键词图谱查询；如需 LLM Cypher，设置 ENABLE_LLM_GRAPH_CYPHER=true")
        fallback_result = _fallback_graph_keyword_search(query)
        _log_elapsed("neo4j:tool", "快速图谱查询总耗时", total_start)
        return fallback_result

    try:
        chain = _get_graph_chain()
        step_start = _log_elapsed("neo4j:tool", "获取 GraphCypherQAChain", step_start)
        result = chain.invoke({"query": query})
        step_start = _log_elapsed("neo4j:tool", "GraphCypherQAChain.invoke", step_start)
        answer = result.get('result', "未找到相关图谱信息。")
        print(f"📦 [Neo4jTool] result_chars={len(answer)}")
        _log_elapsed("neo4j:tool", "图谱工具总耗时", total_start)
        return answer
    except Exception as e:
        step_start = _log_elapsed("neo4j:tool", f"GraphCypherQAChain 失败，进入关键词兜底: {type(e).__name__}", step_start)
        fallback_result = _fallback_graph_keyword_search(query)
        _log_elapsed("neo4j:tool", "图谱工具含兜底总耗时", total_start)
        if fallback_result and "失败" not in fallback_result:
            return fallback_result
        return f"查询图谱时发生错误: {str(e)}；关键词兜底结果：{fallback_result}"
