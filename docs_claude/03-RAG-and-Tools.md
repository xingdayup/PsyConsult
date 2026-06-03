# 03 - RAG 系统与工具

## 三套检索工具

Agent 不是全知全能的——需要查资料、查图谱、查术语。系统提供了三套工具：

| 工具 | 文件 | 查什么 | 怎么查 |
|------|------|--------|--------|
| `query_vector_db` | `tools/vector_tool.py` | ICD-11 原文、中国指南、药物说明书 | Milvus 向量语义搜索 |
| `query_knowledge_graph` | `tools/graph_tool.py` | 疾病-症状-药物的结构化关系 | Neo4j Cypher 查询 |
| `query_synonyms` | `tools/synonym_tool.py` | 口语→标准医学术语的映射 | 本地 JSON 精确匹配 |

## 向量 RAG — Milvus

### 原理

AI 嵌入模型把每段文档转成一串 1536 个数字（向量）。语义相近的文字，向量在空间中的位置也近。"怎么退钱"和"退款规则"的向量距离近，"怎么退钱"和"怎么创建服务器"的向量距离远。

查询的时候，把用户的问题也转成向量，在 Milvus 里找距离最近的 top-3 个文档块。

### 数据源

`mock_data/` 下的 7 份临床 Markdown 文档——ICD-11 标准 × 5 + 药物手册 + 中国指南。

### 摄入流程

`test/milvus_rag.py` 做的事：
1. `DirectoryLoader` 读取目录下所有 `.md` 文件
2. `RecursiveCharacterTextSplitter` 切块（chunk_size=500，chunk_overlap=50）
3. DashScope `text-embedding-v2` 模型计算每个块的向量
4. 存入 Milvus collection `cloud_product_docs`

> 注：collection 名目前还是旧的 `cloud_product_docs`，后续应改为 `clinical_docs`。

### Agent 怎么用

`query_vector_db` 是 LangChain 的 `@tool` 装饰函数。Agent 的 ReAct 循环在需要查文档时自动调用它。DDL 搜索请求自己拿去嵌入、搜 Milvus、返回 `【来源: icd11_depression.md】...内容...` 格式的结果。

## 图谱 RAG — Neo4j

### GraphCypherQAChain

`tools/graph_tool.py` 里封装了 LangChain 的 `GraphCypherQAChain`。这是一个自动把自然语言翻译成 Cypher 查询的链条：

```
"抑郁的核心症状有哪些？"
  → LLM 生成 Cypher:
    MATCH (d:Disease {id:'6A70'})-[r:HAS_SYMPTOM]->(s:Symptom)
    WHERE r.criterion = '核心' RETURN s.name_cn
  → Neo4j 执行 → 返回结果
```

### 自定义 Cypher 提示词

关键设计：`CYPHER_GENERATION_TEMPLATE` 是精心编写的提示词，教 LLM 理解临床图谱的结构。

```
节点标签: Disease, Symptom, Drug, SideEffect, Treatment
关系: HAS_SYMPTOM, FIRST_LINE, SECOND_LINE, CAUSES, INTERACTS_WITH, USES_DRUG
Cypher 规则: 只读查询, 给节点变量名, 用 RETURN 返回属性...
```

这段提示词是 GraphCypherQAChain 能正确工作的基础——LLM 需要知道有哪些标签和关系类型才能生成正确的 Cypher。

### 关键词回退机制

GraphCypherQAChain 有时会失败——LLM 生成了语法错误的 Cypher，或者 schema 太复杂 LLM 理解错了。这时不会返回"查询失败"，而是自动降级到 `_fallback_graph_keyword_search`：

- 从问题中提取关键词
- 在 Neo4j 中做 `CONTAINS` 搜索：匹配节点 id/name/description，匹配关系类型
- 返回命中节点和关系的列表

这个兜底机制保证了图谱检索的鲁棒性——LLM 失败了也有结果。

## 同义词工具

`tools/synonym_tool.py` 是临床场景独有的新工具。加载 `config/symptom_synonyms.json`（20 条口语→术语映射）：

```json
{
  "睡不着": {"term": "失眠", "icd11": "MB21.0", "phq9_item": 3},
  "不想活了": {"term": "自杀观念", "icd11": "MB21.A", "phq9_item": 9},
  "幻听": {"term": "言语性幻听", "icd11": "6A20.0"},
  "反复洗手": {"term": "强迫行为", "icd11": "6B20.0"}
}
```

每条映射包含标准术语 + ICD-11 编码 + 对应量表条目。支持精确匹配和部分匹配两种模式。这是非 MCP 的本地 `@tool`，因为同义词映射表很小（20 条），不需要远程服务。

## 下一步

- 记忆系统：→ `04-Memory-System.md`
- Mock 数据：→ `06-Mock-Data.md`
