# 05. 数据、记忆与 RAG

## 模块解决的问题

LLM 自身不可靠，也不了解项目内的指南、图谱和会话上下文。项目用三类数据能力增强回答：

- Redis：短期对话记忆。
- Milvus：语义缓存、长期记忆、指南/诊断标准向量检索。
- Neo4j：疾病、症状、药物、治疗关系的结构化图谱查询。

## Redis 短期记忆

核心文件：`agent/core/memory/short_term.py`

```python
def _key(user_id: str, session_id: str) -> str:
    return f"memory:short:{user_id}:{session_id}"

await self._client.set(
    self._key(user_id, session_id),
    json.dumps(messages, ensure_ascii=False),
    ex=self._ttl,
)
```

面试讲法：  
短期记忆按用户和会话隔离，默认 TTL 是 30 分钟，适合保存当前诊疗对话。超过阈值会裁剪，只保留最近消息，避免上下文无限增长。

## Milvus 长期记忆

核心文件：`agent/core/memory/long_term.py`、`agent/core/memory/preference_extractor.py`

```python
results = self._client.search(
    collection_name="long_term_memory",
    data=[query_embedding],
    filter=f'user_id == "{user_id}"',
    limit=top_k,
    output_fields=["content", "memory_type"],
)
```

写入链路：

```text
本轮问答完成
  -> 写入 Redis 短期记忆
  -> 后台触发 background_extract(user_id, session_id)
  -> PreferenceExtractor 从近期对话抽取临床关键信息
  -> LongTermMemory.save_memory()
  -> embedding 后写入 Milvus long_term_memory
```

召回链路：

```text
新请求进入
  -> _extract_memory_context(user_id, session_id, query)
  -> 按 user_id 过滤 Milvus long_term_memory
  -> 用 query 向量召回相关历史背景
  -> 拼入 memory_context
  -> 注入 Orchestrator / Diagnosis / Treatment / Drug Review Prompt
```

面试讲法：  
长期记忆不是保存整段聊天，而是从 Redis 会话中抽取稳定的临床关键信息，例如主诉、用药、量表分数、过敏史和复诊安排。Milvus 负责语义召回，`user_id` 负责隔离不同医生或用户的长期背景。

## MemoryManager

核心文件：`agent/core/memory/memory_manager.py`

```python
self.short_term = ShortTermMemory(redis_url=redis_url, ttl=redis_ttl)
self.long_term = LongTermMemory(
    host=milvus_host,
    port=milvus_port,
    api_key=milvus_api_key,
    embedding_api_key=embedding_api_key,
)

await asyncio.gather(
    self.short_term.initialize(),
    self.long_term.initialize(),
    return_exceptions=True,
)
```

面试讲法：  
MemoryManager 是统一入口，隐藏 Redis 和 Milvus 的差异。初始化失败时优雅降级，不会因为某个存储不可用导致主聊天接口不可用。

## 语义缓存

核心文件：`app/infra/cache.py`

```python
COLLECTION_NAME = "qa_semantic_cache"
L1_SEMANTIC_DISTANCE_THRESHOLD = 0.08

user_exact = self._query_one(user_filter)
public_exact = self._query_one(public_filter)

results = self._client.search(
    collection_name=COLLECTION_NAME,
    data=[query_embedding],
    filter=scoped_filter,
    limit=1,
)
```

面试讲法：  
语义缓存分两层：先查精确归一化问题，再查向量相似问题。它可以加速高频问答，也减少重复调用 Agent 和 LLM。

## Milvus RAG 工具

核心文件：`agent/tools/vector_tool.py`

```python
@tool
def query_vector_db(query: str) -> str:
    """
    通过语义搜索查询精神科临床指南和诊断标准（RAG）。
    """
    store = _get_milvus_store()
    results = store.similarity_search_with_score(query, k=3)
    ...
```

面试讲法：  
向量检索适合查指南文本、诊断标准原文、药物说明书这类非结构化文档。返回时保留来源文件，方便回答中标注依据。

## Neo4j 知识图谱工具

核心文件：`agent/tools/graph_tool.py`

```python
@tool
def query_knowledge_graph(query: str) -> str:
    """
    查询精神科临床知识图谱。
    当需要查询疾病-症状关联、药物-副作用关系、药物相互作用等结构化医学知识时使用。
    """
    if not _use_llm_graph_cypher():
        return _fallback_graph_keyword_search(query)
    ...
```

面试讲法：  
图谱适合查确定关系，例如疾病有哪些症状、药物之间是否相互作用。默认使用快速关键词图谱查询，必要时可打开 LLM Cypher 模式。

## 数据层分工

| 需求 | 用什么 | 原因 |
|---|---|---|
| 当前会话上下文 | Redis | 快速、TTL、按 session 隔离 |
| 用户长期偏好 | Milvus long_term_memory | 用向量检索语义相关偏好 |
| 高频问答缓存 | Milvus qa_semantic_cache | 精确/语义命中后直接返回 |
| 指南和标准检索 | Milvus cloud_product_docs | 非结构化文本语义搜索 |
| 药物和疾病关系 | Neo4j | 结构化关系查询 |

## 面试 Q&A

**Q：为什么同时用 Milvus 和 Neo4j？**  
A：Milvus 适合非结构化文本相似检索，Neo4j 适合结构化关系查询。临床场景既需要查指南文本，也需要查疾病-症状、药物-相互作用这种关系。

**Q：数据库不可用怎么办？**  
A：记忆和缓存模块都有 graceful degradation，初始化失败会标记不可用。主链路仍然可以调用 LLM，只是缺少部分增强能力。

**Q：语义缓存和 RAG 有什么区别？**  
A：语义缓存是“相似问题直接返回已有答案”，RAG 是“检索材料后让 Agent 生成答案”。缓存偏性能优化，RAG 偏知识增强。

**Q：长期记忆和 Redis 短期记忆有什么区别？**  
A：Redis 保存当前会话最近上下文，key 是 `user_id + session_id`，适合连续对话。Milvus 长期记忆保存跨会话的临床关键信息，按 `user_id` 过滤，再用语义相似度召回，适合“新会话也能记得历史背景”。

## 截图建议

- 截 `MemoryManager.initialize()`，说明并发初始化和降级。
- 截 `background_extract()`，说明从 Redis 抽取并写入 Milvus。
- 截 `SemanticCache.get_cache()`，说明精确命中和语义命中。
- 截 `query_vector_db()`，说明向量检索。
- 截 `query_knowledge_graph()`，说明图谱工具和关键词兜底。

