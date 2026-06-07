# 第五章：知识工具详解

## 5.1 概述

临床 CDS 系统的知识来源分为四层：

| 知识层 | 技术实现 | 查询工具 | 数据特点 |
|--------|----------|----------|----------|
| 知识图谱 | Neo4j 图数据库 | `graph_tool.py` | 结构化实体-关系（ICD-11、药物、症状） |
| 症状同义词 | JSON 文件映射 | `synonym_tool.py` | 口语→标准术语翻译 |
| 向量 RAG | Milvus 向量库 | `vector_tool.py` | 指南原文、诊断标准、药物说明书 |
| MCP 工具 | FastMCP stdio 服务器 | `clinical_tools.py` | 量表评分（PHQ-9/GAD-7）、药品标签查询 |

四个 Agent 节点按需分配这些工具，构成完整的知识检索体系。

---

## 5.2 Neo4j 知识图谱 Schema

### 数据模型定义

所有实体和关系使用 Python `@dataclass` 定义，清晰约束了图谱的结构。

**文件：** `agent/core/graph/models.py`（第 1-69 行）

#### 五类节点

| 标签 | 关键字段 | 示例 |
|------|----------|------|
| `Disease` | `id` (ICD-11 编码), `name_cn`, `name_en`, `description` | `{id: "6A70", name_cn: "抑郁发作"}` |
| `Symptom` | `id`, `name_cn`, `category` (核心/附加) | `{id: "insomnia", name_cn: "失眠", category: "核心"}` |
| `Drug` | `id`, `name_cn`, `generic_name`, `drug_class`, `indication`, `dosage`, `contraindications` | `{id: "sertraline", name_cn: "舍曲林", drug_class: "SSRI"}` |
| `SideEffect` | `id`, `name_cn`, `frequency` (常见/偶见/罕见) | `{id: "nausea", name_cn: "恶心", frequency: "常见"}` |
| `Treatment` | `id`, `name_cn`, `line` (一线/二线/增效), `guideline_source` | `{id: "ssri_mono", name_cn: "SSRI 单药治疗", line: "一线"}` |

对应的 `@dataclass` 定义（以 Disease 和 Relation 为例）：

```python
@dataclass
class Disease:
    """疾病实体（ICD-11）。"""
    id: str                                    # icd11_code, e.g. "6A70"
    name_cn: str                               # 中文名, e.g. "抑郁发作"
    name_en: str = ""                          # 英文名
    description: str = ""                      # 简要描述
```

#### 六类关系

| 关系类型 | 方向 | 属性 |
|----------|------|------|
| `HAS_SYMPTOM` | Disease → Symptom | `{criterion: "核心" | "附加"}` |
| `FIRST_LINE` | Disease → Treatment | — |
| `SECOND_LINE` | Disease → Treatment | — |
| `CAUSES` | Drug → SideEffect | — |
| `INTERACTS_WITH` | Drug ↔ Drug | `{risk: "禁忌" | "谨慎" | "注意"}` |
| `USES_DRUG` | Treatment → Drug | — |

对应的 `Relation` 定义：

```python
@dataclass
class Relation:
    """实体间的关系。"""
    source_id: str
    target_id: str
    relation_type: Literal[
        "HAS_SYMPTOM", "FIRST_LINE", "SECOND_LINE",
        "CAUSES", "INTERACTS_WITH", "USES_DRUG",
    ]
    properties: dict = field(default_factory=dict)
```

### 唯一性约束

**文件：** `agent/core/graph/client.py`（第 92-114 行）

```python
async def create_constraints(self) -> None:
    constraints = [
        ("Disease", "id"),
        ("Symptom", "id"),
        ("Drug", "id"),
        ("SideEffect", "id"),
        ("Treatment", "id"),
    ]
    for label, property_name in constraints:
        query = (
            f"CREATE CONSTRAINT {label.lower()}_{property_name} "
            f"IF NOT EXISTS FOR (n:{label}) "
            f"REQUIRE n.{property_name} IS UNIQUE"
        )
        await self.execute_query(query)
```

为每类节点的 `id` 字段创建 UNIQUE 约束，保证实体唯一性。

### 数据摄入流程

**文件：** `agent/core/graph/ingestor.py`（第 131-151 行）

```python
async def ingest_all(
    self,
    diseases: list[Disease] | None = None,
    symptoms: list[Symptom] | None = None,
    drugs: list[Drug] | None = None,
    side_effects: list[SideEffect] | None = None,
    treatments: list[Treatment] | None = None,
    relations: list[Relation] | None = None,
) -> dict[str, int]:
    await self.client.create_constraints()

    stats = {}
    stats["diseases"] = await self.ingest_diseases(diseases or [])
    stats["symptoms"] = await self.ingest_symptoms(symptoms or [])
    stats["drugs"] = await self.ingest_drugs(drugs or [])
    stats["side_effects"] = await self.ingest_side_effects(side_effects or [])
    stats["treatments"] = await self.ingest_treatments(treatments or [])
    stats["relations"] = await self.ingest_relations(relations or [])

    return stats
```

#### UNWIND + MERGE 批处理模式

以症状摄入为例：

```python
async def ingest_symptoms(self, symptoms: list[Symptom]) -> int:
    query = """
    UNWIND $items AS item
    MERGE (n:Symptom {id: item.id})
    SET n.name_cn = item.name_cn, n.category = item.category, n.updated_at = datetime()
    RETURN count(n) AS count
    """
    result = await self.client.execute_query(
        query, {"items": [s.__dict__ for s in symptoms]}
    )
```

模式解析：
- `UNWIND $items` — 将 Python 列表展开为多行
- `MERGE` — 不存在则创建，存在则匹配（UPSERT 语义）
- `SET` — 更新属性（保证幂等性）
- 参数化查询 — 防止 Cypher 注入

关系摄入使用同样的模式，但多了一步 MATCH 两端的节点：

```python
async def ingest_relations(self, relations: list[Relation]) -> int:
    # 按类型分组
    relations_by_type: dict[str, list[Relation]] = {}
    for rel in relations:
        relations_by_type.setdefault(rel.relation_type, []).append(rel)

    for rel_type, rels in relations_by_type.items():
        query = f"""
        UNWIND $relations AS rel
        MATCH (a {{id: rel.source_id}})
        MATCH (b {{id: rel.target_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        SET r += rel.properties, r.updated_at = datetime()
        RETURN count(r) AS count
        """
```

### LLM 辅助的实体抽取

**文件：** `agent/core/graph/parser.py`（第 87-153 行）

`KnowledgeGraphParser` 使用 LLM 从医学文档中自动抽取实体和关系，输出 JSON 后反序列化为 `models.py` 中的 dataclass：

```python
class KnowledgeGraphParser:
    def __init__(self, llm: BaseChatModel | None = None) -> None:
        settings = get_settings()
        self.llm = llm or ChatTongyi(**settings.get_model_config())

    async def parse_text(self, text: str) -> dict[str, list[Any]]:
        prompt = get_extraction_prompt(text)
        response = await self.llm.ainvoke(prompt)
        content = response.content

        # 处理 LLM 输出的 JSON 代码块
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content.strip()

        data = json.loads(json_str)
        result = self._convert_to_models(data)
        return result
```

---

## 5.3 graph_tool.py：双模式图谱查询

这是系统中最复杂的工具，支持**关键词快速查询**和**LLM Cypher 生成**两种模式。

### @tool 装饰器模式

**文件：** `agent/tools/graph_tool.py`（第 198-229 行）

```python
@tool
def query_knowledge_graph(query: str) -> str:
    """
    查询精神科临床知识图谱。
    当需要查询疾病-症状关联、药物-副作用关系、药物相互作用、
    治疗方案-药物关系等结构化医学知识时，使用此工具。
    输入参数 query 必须是明确的自然语言查询句子。
    """
    if not _use_llm_graph_cypher():
        # 默认模式：快速关键词查询
        return _fallback_graph_keyword_search(query)

    try:
        # LLM Cypher 模式
        chain = _get_graph_chain()
        result = chain.invoke({"query": query})
        return result.get('result', "未找到相关图谱信息。")
    except Exception as e:
        # LLM 失败 → 降级到关键词兜底
        fallback_result = _fallback_graph_keyword_search(query)
        if fallback_result and "失败" not in fallback_result:
            return fallback_result
        return f"查询图谱时发生错误: {str(e)}；关键词兜底结果：{fallback_result}"
```

### 线程安全的单例模式

**文件：** `agent/tools/graph_tool.py`（第 17-19、30-58 行）

```python
_graph_chain_instance = None
_graph_instance = None
_graph_lock = RLock()  # 可重入锁

def _get_graph_instance():
    """获取 Neo4jGraph 单例。"""
    global _graph_instance
    if _graph_instance is not None:
        return _graph_instance

    with _graph_lock:
        if _graph_instance is not None:
            return _graph_instance

        # 连接 Neo4j
        graph = Neo4jGraph(
            url=neo4j_uri,
            username=neo4j_user,
            password=os.getenv("NEO4J_PASSWORD", "YOUR_NEO4J_PASSWORD")
        )
        graph.refresh_schema()
        _graph_instance = graph
        return _graph_instance
```

使用 `RLock`（可重入锁）保证线程安全，支持 `_get_graph_chain` → `_get_graph_instance` 的嵌套调用。

### 默认模式：关键词快速查询

**文件：** `agent/tools/graph_tool.py`（第 117-196 行）

#### 关键词提取

```python
def _extract_keywords(query: str) -> list[str]:
    lower_query = query.lower()
    tokens = re.findall(r"[a-z0-9._-]+", lower_query)    # 英文数字 token
    cn_tokens = re.findall(r"[一-鿿]{2,}", query) # 中文 token（≥2 字符）
    keywords = []
    for token in tokens + cn_tokens:
        if len(token.strip()) >= 2 and token not in keywords:
            keywords.append(token.strip())
    if not keywords:
        keywords.append(lower_query[:20] if lower_query else "ecs")
    return keywords[:8]
```

规则：提取英文+数字+中文混合关键词，去重，最多 8 个。

#### Cypher 查询

```python
def _fallback_graph_keyword_search(query: str) -> str:
    keywords = _extract_keywords(query)

    # 节点查询：CONTAINS 匹配 id/name/description
    node_where = " OR ".join(
        f"toLower(coalesce(n.id, '')) CONTAINS '{k}' OR "
        f"toLower(coalesce(n.name, '')) CONTAINS '{k}' OR "
        f"toLower(coalesce(n.description, '')) CONTAINS '{k}'"
        for k in keywords
    )
    node_cypher = f"""
    MATCH (n)
    WHERE {node_where}
    RETURN labels(n) AS labels, coalesce(n.id, n.name, '') AS node_key, properties(n) AS props
    LIMIT 8
    """

    # 关系查询：CONTAINS 匹配两端节点的 id/name
    rel_cypher = f"""
    MATCH (a)-[r]->(b)
    WHERE {rel_where}
    RETURN labels(a) AS from_labels, coalesce(a.id, a.name, '') AS from_node,
           type(r) AS rel, labels(b) AS to_labels, coalesce(b.id, b.name, '') AS to_node
    LIMIT 8
    """
```

返回格式包含节点标签、key 和属性，便于 LLM 理解。

### LLM Cypher 模式（ENABLE_LLM_GRAPH_CYPHER）

**文件：** `agent/tools/graph_tool.py`（第 60-115 行）

```python
def _get_graph_chain():
    """获取 GraphCypherQAChain 单例（懒加载）。"""
    graph = _get_graph_instance()
    llm = ChatOpenAI(**get_settings().get_model_config(), temperature=0)

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

    _graph_chain_instance = GraphCypherQAChain.from_llm(
        llm=llm,
        graph=graph,
        cypher_prompt=cypher_prompt,
        verbose=False,
        return_intermediate_steps=False,
        allow_dangerous_requests=True,
    )
    return _graph_chain_instance
```

关键细节：
- `temperature=0` — 保证 Cypher 生成确定性
- `allow_dangerous_requests=True` — langchain 的安全开关，因本系统使用受控环境
- `refresh_schema()` — 初始化时自动扫描图谱结构注入 prompt

### 支持两种模式的开关

```python
def _use_llm_graph_cypher() -> bool:
    value = os.getenv("ENABLE_LLM_GRAPH_CYPHER", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}
```

默认关闭（关键词模式），需要时通过环境变量开启 LLM Cypher 模式。

### 降级路径

```
LLM Cypher 模式
  ├── 成功 → 返回结果
  └── 异常 → 关键词兜底（_fallback_graph_keyword_search）
               ├── 成功 → 返回结果
               └── 失败 → 返回错误信息
```

---

## 5.4 synonym_tool.py：症状同义词

将患者口语化表达（如"睡不着""没胃口"）映射为标准医学术语和 ICD-11 编码。

### 模块级懒加载

**文件：** `agent/tools/synonym_tool.py`（第 8-19 行）

```python
_SYNONYMS = None

def _load_synonyms():
    global _SYNONYMS
    if _SYNONYMS is not None:
        return _SYNONYMS
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "symptom_synonyms.json"
    )
    with open(path, "r", encoding="utf-8") as f:
        _SYNONYMS = json.load(f)
    return _SYNONYMS
```

只在首次调用时加载一次 JSON 文件，后续复用全局缓存。

### 匹配逻辑

**文件：** `agent/tools/synonym_tool.py`（第 22-42 行）

```python
@tool
def query_synonyms(phrase: str) -> str:
    """查询口语化症状描述对应的标准医学术语和 ICD-11 编码。"""
    synonyms = _load_synonyms()
    phrase_lower = phrase.strip().lower()

    # 精确匹配
    if phrase_lower in synonyms:
        return json.dumps(synonyms[phrase_lower], ensure_ascii=False)

    # 子串匹配（双向）
    matches = []
    for key, value in synonyms.items():
        if key in phrase_lower or phrase_lower in key:
            matches.append(value)

    if matches:
        return json.dumps(matches, ensure_ascii=False)
    return json.dumps({
        "term": phrase, "icd11": None, "message": "未找到匹配的标准术语"
    }, ensure_ascii=False)
```

两步匹配：精确匹配 → 子串匹配。

### 配置文件格式

**文件：** `agent/config/symptom_synonyms.json`（推断格式）

```json
{
  "睡不着": {"term": "失眠", "icd11": "7A00", "scale_item": "PHQ-9条目3"},
  "没胃口": {"term": "食欲下降", "icd11": "5B81", "scale_item": "PHQ-9条目5"},
  "不想动": {"term": "精神运动性迟滞", "icd11": "6A70.1", "scale_item": "PHQ-9条目8"},
  "心慌": {"term": "心悸", "icd11": "MC81", "scale_item": "GAD-7条目4"}
}
```

---

## 5.5 vector_tool.py：Milvus RAG

提供向量语义搜索，用于检索 ICD-11 诊断标准原文、中国精神科指南摘要、药物说明书等非结构化文档。

### 线程安全的单例

**文件：** `agent/tools/vector_tool.py`（第 59-97 行）

```python
_milvus_instance = None
_milvus_lock = Lock()

def _get_milvus_store():
    global _milvus_instance
    if _milvus_instance is not None:
        return _milvus_instance

    with _milvus_lock:
        if _milvus_instance is not None:
            return _milvus_instance

        api_key = _get_embedding_api_key()
        if not api_key:
            raise RuntimeError("未配置 DashScope embedding key。")

        embeddings = DashScopeEmbeddings(
            dashscope_api_key=api_key,
            model="text-embedding-v2"
        )

        _milvus_instance = Milvus(
            embedding_function=embeddings,
            connection_args={"uri": milvus_uri},
            collection_name="cloud_product_docs",
            auto_id=True,
            drop_old=False
        )
    return _milvus_instance
```

使用 `Lock`（非可重入）而不是 `RLock`，因为此单例没有嵌套调用需求。

### 向量检索

**文件：** `agent/tools/vector_tool.py`（第 99-127 行）

```python
@tool
def query_vector_db(query: str) -> str:
    """
    通过语义搜索查询精神科临床指南和诊断标准（RAG）。
    当需要检索 ICD-11 诊断标准原文、中国精神科指南摘要、
    药物说明书详细内容时，使用此工具。
    """
    store = _get_milvus_store()
    results = store.similarity_search_with_score(query, k=3)

    if not results:
        return "未在文档中检索到相关信息。"

    formatted_results = []
    for i, (doc, score) in enumerate(results):
        source = os.path.basename(doc.metadata.get('source', 'Unknown'))
        content = doc.page_content.strip()
        formatted_results.append(f"【来源: {source}】\n{content}")

    return "\n\n".join(formatted_results)
```

关键细节：
- `k=3` — 返回 top-3 最相似文档块
- `similarity_search_with_score` — 返回文档对象和相似度分数
- 返回格式包含来源文件名

### pymilvus 兼容性补丁

**文件：** `agent/tools/vector_tool.py`（第 11-29 行）

```python
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
```

**为什么要这个补丁？** `pymilvus 2.6.x` 修改了内部连接管理的 API，而 `langchain-milvus 0.3.x` 仍然使用旧版本的 `_fetch_handler` 接口。补丁通过回退到手动遍历 `ConnectionManager` 的内部注册表来兼容新旧版本，使连接池查找正常工作。

### 集合名称：`cloud_product_docs`

需要注意的是，向量工具的集合名是 `cloud_product_docs`，与长期记忆的 `long_term_memory` 和语义缓存的 `qa_semantic_cache` 不同，它存储的是文档块（指南原文、说明说等），而非记忆或缓存条目。

### API Key 解析链

**文件：** `agent/tools/vector_tool.py`（第 42-57 行）

```python
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
```

与语义缓存的 key 解析链逻辑一致（使用 `os.getenv` 而非 settings 对象）。

---

## 5.6 MCP 工具系统

### MCPManager：连接生命周期

**文件：** `agent/core/mcp/mcp_manager.py`（第 13-131 行）

```python
class MCPManager:
    """MCP 服务器连接和工具发现的管理器。"""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self._client: MultiServerMCPClient | None = None
        self._tools: list[BaseTool] | None = None

    async def connect(self) -> None:
        """连接到所有配置的 MCP 服务器。"""
        servers_config = self._load_config()
        if not servers_config:
            return

        self._client = MultiServerMCPClient(servers_config)
        self._tools = await self._client.get_tools()
        logger.info("Discovered %d tools from MCP servers", len(self._tools))

    async def close(self) -> None:
        """关闭所有 MCP 连接。"""
        if self._client is not None:
            self._client = None
            self._tools = None

    async def get_tools(self) -> list[BaseTool]:
        """返回所有被发现的 LangChain BaseTool。"""
        if self._tools is None:
            raise RuntimeError("MCPManager is not connected.")
        return self._tools
```

三个主要方法：`connect`（建立连接+发现工具）、`get_tools`（返回工具列表）、`close`（清理资源）。

### MultiServerMCPClient 适配

`MCPManager` 封装了 `langchain-mcp-adapters` 的 `MultiServerMCPClient`：

- 输入：按 {server_name: config} 分组的服务器配置字典
- 输出：统一的 LangChain `BaseTool` 列表
- 通信：通过 `MultiServerMCPClient` 管理各服务器的 stdio 进程生命周期

### clinical_tools.py：FastMCP 工具服务器

**文件：** `agent/mcp_servers/clinical_tools.py`（第 1-123 行）

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ClinicalToolsServer")
```

#### 工具 1：calculate_scale_score

```python
@mcp.tool()
def calculate_scale_score(scale_type: str, answers: str) -> str:
    """计算心理量表得分和严重度分级。

    Args:
        scale_type: 支持 "PHQ-9" 或 "GAD-7"
        answers: 逗号分隔的分数列表，如 "2,2,1,0,2,1,2,0,1"
    """
    config = SCALE_SCORING[scale_type]
    scores = [int(x.strip()) for x in answers.split(",")]

    total = sum(scores)
    severity = "未知"
    for low, high, label in config["severity"]:
        if low <= total <= high:
            severity = label
            break

    return json.dumps({
        "status": "success",
        "data": {
            "scale_type": scale_type,
            "scores": scores,
            "total": total,
            "severity": severity,
        }
    }, ensure_ascii=False)
```

评分规则定义：

```python
SCALE_SCORING = {
    "PHQ-9": {
        "items": 9,
        "severity": [
            (0, 4, "无抑郁"),
            (5, 9, "轻度"),
            (10, 14, "中度"),
            (15, 19, "中重度"),
            (20, 27, "重度"),
        ],
    },
    "GAD-7": {
        "items": 7,
        "severity": [
            (0, 4, "无焦虑"),
            (5, 9, "轻度"),
            (10, 14, "中度"),
            (15, 21, "重度"),
        ],
    },
}
```

#### 工具 2：query_drug_label

```python
@mcp.tool()
def query_drug_label(drug_name: str) -> str:
    """查询精神科药物的说明书信息。"""
    mock_drugs = {
        "舍曲林": {
            "indication": "抑郁障碍、强迫症、惊恐障碍",
            "dosage": "起始 50mg/d，最大 200mg/d",
            "contraindications": "禁止与 MAOIs 联用",
            "side_effects": "恶心、腹泻、失眠、性功能障碍",
            "class": "SSRI",
        },
        # ... 帕罗西汀、文拉法辛、奥氮平
    }
    # 子串匹配
    for name, info in mock_drugs.items():
        if name in drug_lower or drug_lower in name:
            return json.dumps({"status": "success", "data": info},...)

    return json.dumps({"status": "not_found", "message": f"未找到药物'{drug_name}'的说明书"},...)
```

注意：当前使用 mock 数据（4 种药物），代码注释标注"后续可对接真实药物数据库"。

### MCP 服务器配置

**文件：** `agent/config/mcp_servers.json`

```json
{
  "mcpServers": {
    "clinical_tools": {
      "command": "python",
      "args": ["-m", "mcp_servers.clinical_tools"],
      "cwd": "agent",
      "transport": "stdio"
    }
  }
}
```

| 参数 | 值 | 说明 |
|------|-----|------|
| `command` | `python` | 执行命令 |
| `args` | `["-m", "mcp_servers.clinical_tools"]` | 以模块方式运行 |
| `cwd` | `agent` | 工作目录（确保 .env 和依赖可访问） |
| `transport` | `stdio` | 通过标准输入/输出通信（FastMCP stdio 模式） |

### 当前状态

MCP 工具系统在代码层面**基础设施已就绪**：
- MCPManager 能够加载配置、连接服务器、发现工具
- clinical_tools.py 注册了两个可用工具
- mcp_servers.json 提供了配置入口

但尚未接入 Agent 图的工作流。在 `agents/*.py` 的三个 ReAct Agent 中，所有工具通过 `import` 静态绑定，而非通过 MCP 发现：

```python
# diagnosis_agent.py (第 23 行)
self.tools = [query_synonyms, query_knowledge_graph, query_vector_db]
```

MCP 工具的接入需要通过 `MCPManager.get_tools()` 动态注入 Agent 的工具列表，这需要额外的集成工作。

---

## 5.7 工具分配对照表

**文件：** `agent/agents/diagnosis_agent.py`（第 23-24 行）、`agent/agents/treatment_agent.py`（第 23-24 行）、`agent/agents/drug_review_agent.py`（第 20-22 行）

| Agent | 工具列表 | 数量 | 设计理由 |
|-------|----------|------|----------|
| **Orchestrator**（路由） | 无（纯 LLM 判断） | 0 | 仅根据用户意图路由到下游 Agent |
| **Diagnosis**（鉴别诊断） | `query_synonyms` + `query_knowledge_graph` + `query_vector_db` | 3 | 需要口语→标准映射（同义词）、疾病-症状关系（图谱）、诊断标准原文（RAG） |
| **Treatment**（治疗推荐） | `query_vector_db` + `query_knowledge_graph` | 2 | 需要指南原文（RAG）和治疗方案-药物关系（图谱）；不需要同义词映射 |
| **DrugReview**（药物审查） | `query_knowledge_graph` | 1 | 仅需药物相互作用和副作用关系（图谱） |

### 工具调用限制

每个领域 Agent 使用 `create_react_agent` 构建，系统提示中限制最多 2 次工具调用，防止无限循环：

```python
# 各 Agent 的系统提示中均包含工具调用限制（措辞根据任务各有不同）:
# diagnosis_agent.py  L138: "⚠️ 你最多调用 2 次工具，之后必须输出最终结果"
# treatment_agent.py  L206: "⚠️ 工具调用限制：你最多调用 2 次工具，之后必须输出最终方案"
# drug_review_agent.py L275: "⚠️ 工具调用限制：你最多调用 2 次工具，之后必须输出最终审查报告"
```

### 三类 Agent 的共同架构

三个领域 Agent（Diagnosis/Treatment/DrugReview）共享相同的实现模式：

```
初始化：
  1. 实例化 LLM（ChatOpenAI, temperature=0.1）
  2. 绑定工具列表
  3. create_react_agent(llm, tools) → inner_agent

执行（__call__）：
  1. inner_agent.astream(stream_mode="messages")
  2. 通过 get_stream_writer() 实时推送 token/tool_call/tool_done
  3. 累积全部 token 后返回 AIMessage

降级：
  所有异常被内部捕获，返回错误消息而非崩溃
```

---

## 5.8 知识系统数据流总览

```
用户查询
  │
  ├── Orchestrator（意图路由）
  │     ├── 诊断相关 → Diagnosis Agent
  │     │     ├── query_synonyms（口语→ICD-11 术语）
  │     │     ├── query_knowledge_graph（疾病-症状关系）
  │     │     └── query_vector_db（诊断标准原文）
  │     │
  │     ├── 治疗相关 → Treatment Agent
  │     │     ├── query_vector_db（指南摘要、用药建议）
  │     │     └── query_knowledge_graph（治疗-药物关系）
  │     │
  │     └── 药物审查 → DrugReview Agent
  │           └── query_knowledge_graph（相互作用、副作用）
  │
  └── MCP 工具（基础设施就绪，待接入）
        ├── calculate_scale_score（PHQ-9/GAD-7 计分）
        └── query_drug_label（说明书查询）
```

### 数据来源

| 来源 | 技术 | 数据量 | 更新方式 |
|------|------|--------|----------|
| ICD-11 诊断标准 | Milvus RAG（cloud_product_docs） | 文档块级别 | 脚本导入 |
| 中国精神科防治指南 | Milvus RAG | 文档块级别 | 脚本导入 |
| 药物说明书 | Milvus RAG + Neo4j 图谱 | 多源 | 脚本导入 + 关系构建 |
| 疾病-症状-药物关系 | Neo4j 图谱 | 结构化节点/边 | `build_kg.py` 构建 |
| 症状同义词 | JSON 配置文件 | 数十条映射 | 手动编辑 |
| 量表评分 | MCP 工具（代码逻辑） | 2 个量表 | 代码内嵌 |
