# 数据、图谱与向量检索

## 数据来源目录

示例临床知识位于：

```text
mock_data/
├── china_guidelines.md
├── icd11_anxiety.md
├── icd11_bipolar.md
├── icd11_depression.md
├── icd11_ocd.md
├── icd11_schizophrenia.md
└── psychiatric_drugs.md
```

这些 Markdown 文件用于开发阶段的数据导入实验：

- ICD-11 精神障碍诊断标准。
- 中国精神科治疗指南摘要。
- 精神科常用药物资料。
- 药物副作用和相互作用相关知识。

## 当前系统中的数据存储

项目中实际使用了多个存储：

```text
Redis
  -> 短期对话记忆

Milvus
  -> 长期用户记忆 long_term_memory
  -> 文档 RAG cloud_product_docs
  -> 语义缓存 qa_semantic_cache

Neo4j
  -> 精神科知识图谱

本地 JSON
  -> 症状同义词 symptom_synonyms.json
```

## Redis 短期记忆

代码：

```text
agent/core/memory/short_term.py
```

用途：

- 保存最近对话历史。
- 按用户和会话隔离。
- 给下一轮 Agent 推理提供上下文。

key 格式：

```text
memory:short:{user_id}:{session_id}
```

默认配置：

```dotenv
REDIS_URL=redis://localhost:6379
REDIS_TTL=1800
```

消息超过阈值时会修剪，只保留最近消息，避免上下文过长。

## Milvus 长期记忆

代码：

```text
agent/core/memory/long_term.py
```

Collection：

```text
long_term_memory
```

字段：

- `id`
- `user_id`
- `content`
- `memory_type`
- `embedding`

用途：

- 存储长期用户偏好或临床关键信息。
- 通过向量检索找到与当前 query 相关的背景。
- 使用 `user_id` 过滤，保持不同用户之间隔离。

embedding：

- DashScope `text-embedding-v2`
- 维度 1536
- Milvus `FLOAT_VECTOR`
- COSINE 检索

## Milvus 文档 RAG

代码：

```text
agent/tools/vector_tool.py
agent/test/milvus_rag.py
```

Collection：

```text
cloud_product_docs
```

注意：集合名保留了旧名称，但当前项目用它存储精神科临床文档片段。

导入脚本：

```bash
cd agent
python test/milvus_rag.py
```

导入逻辑：

1. 从 `mock_data/` 读取所有 `.md` 文件。
2. 使用 `DirectoryLoader` 和 `TextLoader` 加载。
3. 使用 `RecursiveCharacterTextSplitter` 分块。
4. chunk 大小：500 字符。
5. chunk overlap：50 字符。
6. 使用 DashScope embedding。
7. 写入 Milvus。

当前脚本中 `drop_old=True`，意味着重新导入时会覆盖旧集合，适合开发阶段保持数据干净。

查询工具：

```python
query_vector_db(query: str) -> str
```

查询逻辑：

- 连接 Milvus。
- 调用 `similarity_search_with_score(query, k=3)`。
- 返回每个命中文档片段的来源文件名和内容。

## Milvus 语义缓存

代码：

```text
app/infra/cache.py
app/preload_cache.py
```

Collection：

```text
qa_semantic_cache
```

用途：

- 缓存高频标准问答。
- API 收到问题后优先查缓存。
- 命中缓存时跳过 Agent 推理，提高响应速度。

预热：

```bash
cd app
python preload_cache.py
```

预热脚本会写入一些高频问题：

- 抑郁发作 ICD-11 诊断标准。
- 舍曲林常用剂量和副作用。
- PHQ-9 评分分级。
- SSRI 和 SNRI 区别。

命中层级：

- `L1_EXACT`：归一化问题完全匹配。
- `L1_SEMANTIC`：语义向量距离小于阈值。

## Neo4j 知识图谱

图谱客户端：

```text
agent/core/graph/client.py
```

图谱实体模型：

```text
agent/core/graph/models.py
```

图谱解析器：

```text
agent/core/graph/parser.py
```

图谱摄入器：

```text
agent/core/graph/ingestor.py
```

工具查询：

```text
agent/tools/graph_tool.py
```

## 图谱实体

`models.py` 中定义了 5 类核心实体。

### Disease

疾病实体，例如：

- id：ICD-11 编码，如 `6A70`
- name_cn：中文名
- name_en：英文名
- description：简要描述

### Symptom

症状实体，例如：

- id：英文唯一标识
- name_cn：中文名
- category：核心或附加

### Drug

药物实体，例如：

- id：英文通用名
- name_cn：中文名
- generic_name：英文通用名
- drug_class：药物类别
- indication：适应症
- dosage：剂量范围
- contraindications：禁忌

### SideEffect

副作用实体：

- id
- name_cn
- frequency：常见、偶见或罕见

### Treatment

治疗方案实体：

- id
- name_cn
- line：一线、二线或增效
- guideline_source：指南来源

## 图谱关系

核心关系：

```text
HAS_SYMPTOM       Disease -> Symptom
FIRST_LINE        Disease -> Treatment
SECOND_LINE       Disease -> Treatment
CAUSES            Drug -> SideEffect
INTERACTS_WITH    Drug <-> Drug
USES_DRUG         Treatment -> Drug
```

## 图谱导入方式一：脚本式通用抽取

文件：

```text
agent/test/build_kg.py
```

运行：

```bash
cd agent
python test/build_kg.py ../mock_data/icd11_depression.md
```

不传参数时默认导入：

```text
mock_data/icd11_depression.md
```

脚本流程：

1. 读取 Markdown。
2. 按 2000 字符切块，重叠 200 字符。
3. 调用 Qwen 结构化输出抽取节点和关系。
4. 合并重复节点和关系。
5. 将抽取结果保存为同名 `.json`。
6. 使用 Neo4j driver 通过 `MERGE` 导入节点和关系。

## 图谱导入方式二：核心 graph 模块

更规范的模块化方式：

1. 使用 `KnowledgeGraphParser` 从文本中抽取模型对象。
2. 使用 `Neo4jClient` 建立异步连接。
3. 使用 `KnowledgeGraphIngestor` 创建约束并导入实体和关系。

涉及文件：

```text
agent/core/graph/parser.py
agent/core/graph/client.py
agent/core/graph/ingestor.py
agent/core/graph/models.py
```

这种方式更适合作为正式功能继续扩展。

## 症状同义词

文件：

```text
agent/config/symptom_synonyms.json
agent/tools/synonym_tool.py
```

用途：

- 把口语表达映射为标准症状。
- 给症状提取 Agent 提供 ICD-11 或量表相关线索。

查询方式：

```python
query_synonyms("睡不着")
```

匹配策略：

- 先精确匹配。
- 再部分匹配。
- 未命中时返回原始短语和空 ICD-11 编码。

## 数据导入推荐流程

完整开发流程：

```bash
# 1. 启动基础服务
cd docker
docker compose up -d

# 2. 导入 RAG 文档
cd ../agent
python test/milvus_rag.py

# 3. 导入知识图谱
python test/build_kg.py ../mock_data/icd11_depression.md
python test/build_kg.py ../mock_data/icd11_anxiety.md
python test/build_kg.py ../mock_data/icd11_bipolar.md
python test/build_kg.py ../mock_data/icd11_ocd.md
python test/build_kg.py ../mock_data/icd11_schizophrenia.md
python test/build_kg.py ../mock_data/psychiatric_drugs.md

# 4. 预热 API 语义缓存
cd ../app
python preload_cache.py
```

## Neo4j 浏览器

Docker 启动后可以访问：

```text
http://localhost:7474
```

登录：

```text
username: neo4j
password: password123
```

示例查询：

```cypher
MATCH (n) RETURN labels(n), n LIMIT 25;
```

查看疾病和症状：

```cypher
MATCH (d:Disease)-[r:HAS_SYMPTOM]->(s:Symptom)
RETURN d.name_cn, type(r), s.name_cn
LIMIT 50;
```

查看药物相互作用：

```cypher
MATCH (a:Drug)-[r:INTERACTS_WITH]->(b:Drug)
RETURN a.name_cn, r.risk, b.name_cn
LIMIT 50;
```

## Milvus Collection 名称总结

| Collection | 用途 | 创建位置 |
| --- | --- | --- |
| `long_term_memory` | 用户长期记忆 | `agent/core/memory/long_term.py` |
| `cloud_product_docs` | 临床文档 RAG | `agent/test/milvus_rag.py`, `agent/tools/vector_tool.py` |
| `qa_semantic_cache` | API 高频问答缓存 | `app/infra/cache.py` |

## 数据安全

- 不要把真实患者资料写入 `mock_data/`。
- 测试病例应使用脱敏样例。
- Milvus 和 Redis 中可能保存对话内容，生产环境需要访问控制、加密和过期策略。
- Neo4j 中的医学知识需要标注来源和版本，避免使用过期资料。
