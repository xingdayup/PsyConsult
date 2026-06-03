import os
import json
from typing import List
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter
from neo4j import GraphDatabase
from dotenv import load_dotenv

# 加载 .env 环境变量
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path)

# ==========================================
# 1. 定义更通用的 Pydantic 数据模型
# ==========================================
class Property(BaseModel):
    key: str = Field(description="属性的键名，例如 vCPU, memory, storage_type, bandwidth_limit, error_code 等")
    value: str = Field(description="属性的值，例如 4, 16GiB, ESSD, 10Gbps, 404 等")

class Node(BaseModel):
    id: str = Field(description="节点的唯一标识符，应尽量简短明确。如 ecs.g8a.xlarge, 华北2（北京）, 包年包月")
    label: str = Field(description="节点类型标签。如 Product, Region, InstanceType, Storage, Image, BillingRule, ErrorCode, Feature 等")
    properties: List[Property] = Field(description="节点的属性列表", default_factory=list)

class Edge(BaseModel):
    source: str = Field(description="源节点 ID")
    target: str = Field(description="目标节点 ID")
    type: str = Field(description="关系类型，使用大写下划线格式，如 CONTAINS, SUPPORTS, HAS_LIMIT, REQUIRES, RESOLVED_BY, BELONGS_TO 等")

class KnowledgeGraph(BaseModel):
    nodes: List[Node] = Field(description="从文档中提取的所有核心实体节点列表")
    edges: List[Edge] = Field(description="从文档中提取的实体之间的关系映射列表")

# ==========================================
# 2. LLM 抽取逻辑 (适配 Qwen 及动态文档)
# ==========================================
def extract_knowledge_graph(file_path: str) -> dict:
    print(f"📄 正在读取文档: {file_path}")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 从环境变量读取配置 (适配您的 .env)
    api_key = os.getenv("DASHSCOPE_API_KEY")
    model_name = os.getenv("MODEL", "qwen-plus") # 默认使用 qwen-plus
    base_url = os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    
    if not api_key:
        raise ValueError("❌ 环境变量中未找到 DASHSCOPE_API_KEY")

    # 初始化大模型 (使用 Qwen 兼容 OpenAI 格式的调用)
    llm = ChatOpenAI(
        api_key=api_key,
        model=model_name,
        base_url=base_url,
        temperature=0, # 保证提取的确定性
    )
    
    # 绑定通用结构化输出
    structured_llm = llm.with_structured_output(KnowledgeGraph)

    # 设计通用 Prompt，增加对分块上下文的提示
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一个精神科医学知识图谱架构师。你的任务是阅读临床医学文档片段，并从中提取核心知识图谱。

        提取原则：
        1. **节点(Nodes)**：识别文档中的核心实体。
           - 实体可以是疾病(Disease)、症状(Symptom)、药物(Drug)、副作用(SideEffect)、治疗方案(Treatment)等。
           - 节点ID必须唯一，尽量使用标准的、全称的名称（如 "抑郁发作" 而不是 "抑郁"），以便与其他文档片段提取的节点合并。
           - 将实体的关键数值或描述作为属性(Properties)提取。
        2. **关系(Edges)**：识别实体间的约束和关联。
           - 关系类型应简洁且为大写(如 HAS_SYMPTOM, FIRST_LINE, CAUSES, INTERACTS_WITH, USES_DRUG)。
        3. **泛化性**：根据上下文灵活定义合理的节点标签和关系类型。

        注意：你当前阅读的可能是长文档的一个片段（Chunk）。请尽可能提取出完整的、孤立的实体和关系，不要遗漏当前片段中的重要信息。
        确保输出严格符合 JSON Schema。所有源(source)和目标(target)必须在提取的节点ID中存在。"""),
        ("human", "文档片段内容如下，请提取知识图谱：\n{text}")
    ])

    chain = prompt | structured_llm
    
    # ==========================================
    # 长文档分块逻辑 (Chunking)
    # ==========================================
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=2000,       # 每个分块最大字符数 (根据模型上下文窗口调整)
        chunk_overlap=200,     # 分块重叠字符数，保留上下文关联
        separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""]
    )
    
    chunks = text_splitter.split_text(content)
    print(f"🔪 文档已切分为 {len(chunks)} 个片段，开始逐块提取...")

    all_nodes = {}  # 使用 dict 去重，key 为 node_id
    all_edges = set() # 使用 set 去重，存储 tuple(source, type, target)
    
    for i, chunk in enumerate(chunks):
        print(f"⏳ 正在处理第 {i+1}/{len(chunks)} 个片段...")
        try:
            kg_result = chain.invoke({"text": chunk})
            
            # 合并节点 (去重并合并属性)
            for node in kg_result.nodes:
                node_id = node.id
                if node_id not in all_nodes:
                    all_nodes[node_id] = node
                else:
                    # 如果节点已存在，尝试合并新的属性
                    existing_props = {p.key: p.value for p in all_nodes[node_id].properties}
                    for new_prop in node.properties:
                        if new_prop.key not in existing_props:
                            all_nodes[node_id].properties.append(new_prop)
                            
            # 合并边 (去重)
            for edge in kg_result.edges:
                edge_tuple = (edge.source, edge.type, edge.target)
                all_edges.add(edge_tuple)
                
        except Exception as e:
            print(f"⚠️ 第 {i+1} 个片段提取失败，跳过: {e}")
            continue

    # 重新组装最终的 KnowledgeGraph
    final_kg = {
        "nodes": [node.dict() for node in all_nodes.values()],
        "edges": [{"source": e[0], "type": e[1], "target": e[2]} for e in all_edges]
    }
    
    output_json = file_path.replace('.md', '.json')
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(final_kg, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 所有片段提取并合并完成！共提取 {len(final_kg['nodes'])} 个节点，{len(final_kg['edges'])} 条关系。JSON 已保存至: {output_json}")
    return final_kg

# ==========================================
# 3. Neo4j 导入逻辑
# ==========================================
def import_to_neo4j(kg_data: dict):
    # 从 .env 读取 Neo4j 配置
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")
    
    print(f"🔌 正在连接 Neo4j 数据库 ({uri})...")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    
    with driver.session() as session:
        # 移除清空图谱的逻辑，改为增量导入 (Merge 机制)
        # print("🧹 清空已有图谱数据 (测试用)...")
        # session.run("MATCH (n) DETACH DELETE n")

        print("🛠️ 正在导入节点 (Nodes)...")
        for node in kg_data['nodes']:
            label = node['label'].replace(' ', '_').replace('-', '_') # 防止特殊字符
            node_id = node['id']
            # 将属性列表转换为字典
            props_dict = {p['key']: p['value'] for p in node['properties']}
            props_dict['id'] = node_id  # 确保 id 被设置为属性
            
            # 使用 Cypher 写入节点
            query = f"MERGE (n:{label} {{id: $id}}) SET n += $props"
            session.run(query, id=node_id, props=props_dict)

        print("🔗 正在导入关系 (Edges)...")
        for edge in kg_data['edges']:
            rel_type = edge['type'].replace(' ', '_').replace('-', '_').upper()
            source_id = edge['source']
            target_id = edge['target']
            
            query = f"""
            MATCH (source {{id: $source_id}})
            MATCH (target {{id: $target_id}})
            MERGE (source)-[r:{rel_type}]->(target)
            """
            session.run(query, source_id=source_id, target_id=target_id)
            
    driver.close()
    print("🎉 图谱数据导入 Neo4j 成功！")

# ==========================================
# 4. 主函数入口
# ==========================================
if __name__ == "__main__":
    import sys
    
    # 支持命令行传入文档路径
    if len(sys.argv) > 1:
        md_file_path = sys.argv[1]
    else:
        # 默认使用测试文档
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        md_file_path = os.path.join(BASE_DIR, "mock_data", "icd11_depression.md")
    
    if not os.path.exists(md_file_path):
        print(f"❌ 找不到文件: {md_file_path}")
        sys.exit(1)
        
    try:
        # 1. 执行大模型抽取
        kg_data = extract_knowledge_graph(md_file_path)
        
        # 2. 导入到 Neo4j
        import_to_neo4j(kg_data)
    except Exception as e:
        print(f"❌ 执行失败: {e}")
