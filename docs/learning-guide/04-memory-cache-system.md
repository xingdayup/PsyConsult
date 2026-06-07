# 第四章：记忆系统与语义缓存详解

## 4.1 概述

临床 CDS 系统的记忆系统分为**三层**：

| 层级 | 存储后端 | 用途 | 生命周期 |
|------|----------|------|----------|
| 短期记忆 | Redis | 最近 N 条对话历史 | TTL 30 分钟，超量裁剪 |
| 长期记忆 | Milvus | 用户偏好/关键事实向量存储 | 持久化，语义检索 |
| 语义缓存 | Milvus | QA 问答缓存（精确+语义） | 持久化，自动命中 |

此外，`PreferenceExtractor` 通过 LLM 从对话中提取结构化偏好，作为长期记忆的数据来源。

---

## 4.2 MemoryManager：统一入口

`MemoryManager` 是记忆系统的唯一入口，封装了短期、长期和偏好提取三个子模块。其类结构如下：

**文件：** `agent/core/memory/memory_manager.py`（第 34-96 行，初始化与生命周期）

```python
class MemoryManager:
    """协调短期 Redis 内存和长期 Milvus 内存。"""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        redis_ttl: int = 1800,
        milvus_host: str = "localhost",
        milvus_port: int = 19530,
        milvus_api_key: str | None = None,
        embedding_api_key: str | None = None,
    ) -> None:
        self.short_term = ShortTermMemory(redis_url=redis_url, ttl=redis_ttl)
        self.long_term = LongTermMemory(
            host=milvus_host,
            port=milvus_port,
            api_key=milvus_api_key,
            embedding_api_key=embedding_api_key,
        )
```

关键设计 —— 使用 `asyncio.gather` 并发初始化两个后端，`return_exceptions=True` 确保一个后端失败不影响另一个：

**文件：** `agent/core/memory/memory_manager.py`（第 83-96 行）

```python
async def initialize(self) -> None:
    import asyncio
    await asyncio.gather(
        self.short_term.initialize(),
        self.long_term.initialize(),
        return_exceptions=True,
    )
    logger.info(
        "MemoryManager ready – short_term=%s, long_term=%s",
        "✓" if self.short_term.available else "✗ (disabled)",
        "✓" if self.long_term.available else "✗ (disabled)",
    )
```

### 四个核心生命周期方法

**文件：** `agent/core/memory/memory_manager.py`（第 113-266 行）

1. **`save_conversation`** — 每轮对话后保存。追加非 system 消息到 Redis 已有历史中：

```python
async def save_conversation(
    self, user_id: str, session_id: str, messages: list[dict[str, Any]],
) -> None:
    non_system = [m for m in messages if m.get("role") != "system"]
    existing = await self.short_term.get_messages(user_id, session_id)
    combined = existing + non_system
    await self.short_term.save_messages(user_id, session_id, combined)
```

2. **`load_preferences`** — 新会话时调用一次，从 Milvus 检索用户偏好：

```python
async def load_preferences(
    self, user_id: str, query: str = "用户偏好习惯个性特点", top_k: int = 3,
) -> list[str]:
    if not self.long_term.available:
        return []
    result = await self.long_term.retrieve_relevant(
        user_id=user_id, query=query, top_k=top_k,
    )
    return result
```

3. **`background_extract`** — 每 N 轮对话后台异步提取偏好（不清理 Redis）：

```python
async def background_extract(
    self, user_id: str, session_id: str, llm: Any
) -> list[str]:
    if not self.long_term.available:
        return []
    messages = await self.short_term.get_messages(user_id, session_id)
    if len(messages) < 2:
        return []
    recent = messages[-_MAX_HISTORY_TURNS:]
    conversation_text = "\n".join(
        f"{m['role']}: {m['content']}" for m in recent
    )
    extractor = PreferenceExtractor(llm=llm)
    existing = await self.load_preferences(user_id)
    new_items = await extractor.extract(
        conversation_text=conversation_text, existing=existing,
    )
    for item in new_items:
        await self.long_term.save_memory(
            user_id=user_id, content=item, memory_type="preference",
        )
    return new_items
```

4. **`finalize_session`** — 会话结束时提取偏好、保存到 Milvus、清理 Redis。流程与 `background_extract` 类似但多了最后一步 `await self.short_term.clear(user_id, session_id)`。

---

## 4.3 短期记忆（ShortTermMemory）

基于 Redis 的短期对话历史存储，代码简洁，约 160 行。

### 连接配置

**文件：** `agent/core/memory/short_term.py`（第 47-67 行）

```python
async def initialize(self) -> None:
    try:
        import redis.asyncio as aioredis
        self._client = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
            retry_on_timeout=True,
        )
        await self._client.ping()
        self._available = True
    except Exception as exc:
        logger.warning(
            "ShortTermMemory: Redis unavailable (%s) – short-term memory disabled.", exc
        )
        self._available = False
```

关键参数：
- `socket_connect_timeout=2` / `socket_timeout=2` — 连接超时 2 秒，避免无限阻塞
- `decode_responses=True` — Redis 自动解码字节为字符串
- `retry_on_timeout=True` — 超时重试

### Key 格式与 TTL

**文件：** `agent/core/memory/short_term.py`（第 149-151 行）

```python
@staticmethod
def _key(user_id: str, session_id: str) -> str:
    return f"memory:short:{user_id}:{session_id}"
```

格式：`memory:short:{user_id}:{session_id}`，TTL 默认 30 分钟（1800 秒），通过 `ex=self._ttl` 参数设置。

### 消息序列化

**文件：** `agent/core/memory/short_term.py`（第 96-121 行）

```python
async def save_messages(
    self, user_id: str, session_id: str, messages: list[dict[str, Any]]
) -> None:
    if not self._available:
        return
    try:
        if len(messages) > COMPRESSION_THRESHOLD:
            messages = self._trim(messages)
        await self._client.set(
            self._key(user_id, session_id),
            json.dumps(messages, ensure_ascii=False),
            ex=self._ttl,
        )
    except Exception as exc:
        logger.warning("ShortTermMemory.save_messages failed: %s", exc)
        self._available = False
```

读取时反序列化：

```python
async def get_messages(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
    if not self._available:
        return []
    try:
        data = await self._client.get(self._key(user_id, session_id))
        return json.loads(data) if data else []
    except Exception as exc:
        logger.warning("ShortTermMemory.get_messages failed: %s", exc)
        self._available = False
        return []
```

### 消息压缩（COMPRESSION_THRESHOLD）

**文件：** `agent/core/memory/short_term.py`（第 14、153-158 行）

```python
COMPRESSION_THRESHOLD = 10  # trim when messages exceed this count

@staticmethod
def _trim(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep system messages + the 6 most recent non-system messages."""
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]
    return system_msgs + other_msgs[-6:]
```

超过 10 条时，保留所有 system 消息 + 最近 6 条非 system 消息。

### 优雅降级模式

整个 `ShortTermMemory` 类采用 `_available` 布尔标志模式：
- 初始化失败 `→ _available = False`
- 每次操作失败 `→ _available = False`
- 所有方法在 `_available` 为 `False` 时静默返回空值/空操作
- 没有任何异常会向上传播导致调用链中断

---

## 4.4 长期记忆（LongTermMemory）

基于 Milvus 的向量存储，用户偏好和关键事实作为 1536 维浮点向量嵌入存储。

### Collection Schema

**文件：** `agent/core/memory/long_term.py`（第 192-218 行）

```python
def _ensure_collection(self) -> None:
    from pymilvus import DataType
    if self._client.has_collection(COLLECTION_NAME):
        return

    schema = self._client.create_schema()
    schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field("user_id", DataType.VARCHAR, max_length=128)
    schema.add_field("content", DataType.VARCHAR, max_length=2048)
    schema.add_field("memory_type", DataType.VARCHAR, max_length=64)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)

    index_params = self._client.prepare_index_params()
    index_params.add_index(
        "embedding",
        index_type="IVF_FLAT",
        metric_type="COSINE",
        params={"nlist": 128},
    )

    self._client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INT64 (auto_id) | 主键，自动生成 |
| `user_id` | VARCHAR(128) | 用户 ID，用于标量过滤 |
| `content` | VARCHAR(2048) | 记忆内容文本 |
| `memory_type` | VARCHAR(64) | 类型标签（如 "preference"） |
| `embedding` | FLOAT_VECTOR(1536) | text-embedding-v2 向量 |

索引：`IVF_FLAT`，`COSINE` 余弦距离，`nlist=128`。

### 嵌入模型

**文件：** `agent/core/memory/long_term.py`（第 77-80 行）

```python
self._embeddings = DashScopeEmbeddings(
    model="text-embedding-v2",
    dashscope_api_key=self._embedding_api_key,
)
```

使用阿里云 DashScope 的 `text-embedding-v2` 模型，输出 1536 维向量。

### 保存记忆流程

**文件：** `agent/core/memory/long_term.py`（第 102-135 行）

```python
async def save_memory(
    self, user_id: str, content: str, memory_type: str = "general",
) -> None:
    if not self._available:
        return
    try:
        embedding = await self._embeddings.aembed_query(content)
        self._client.insert(
            collection_name=COLLECTION_NAME,
            data=[{
                "user_id": user_id,
                "content": content,
                "memory_type": memory_type,
                "embedding": embedding,
            }],
        )
    except Exception as exc:
        logger.error("LongTermMemory.save_memory failed: %s", exc)
```

三步：`aembed_query` 嵌入 → `client.insert` 写入 → 异常捕获降级。

### 检索相关记忆

**文件：** `agent/core/memory/long_term.py`（第 150-181 行）

```python
async def retrieve_relevant(
    self, user_id: str, query: str, top_k: int = 5
) -> list[str]:
    if not self._available:
        return []
    try:
        query_embedding = await self._embeddings.aembed_query(query)
        results = self._client.search(
            collection_name=COLLECTION_NAME,
            data=[query_embedding],
            filter=f'user_id == "{user_id}"',
            limit=top_k,
            output_fields=["content", "memory_type"],
        )
        memories: list[str] = []
        for hits in results:
            for hit in hits:
                memories.append(hit["entity"]["content"])
        return memories
    except Exception as exc:
        logger.error("LongTermMemory.retrieve_relevant failed: %s", exc)
        return []
```

关键点：
- 用 `filter` 参数按 `user_id` 做标量过滤，保证用户隔离
- 返回 `top_k` 条最相似的内容文本
- 默认 `top_k=5`，但 `MemoryManager.load_preferences` 传入 `top_k=3`

### 优雅降级

与 `ShortTermMemory` 一致的 `_available` 模式，外加一个前置检查 —— 没有 embedding API key 时直接禁用：

```python
if not self._embedding_api_key:
    logger.info("LongTermMemory disabled: no DashScope embedding key.")
    self._available = False
    return
```

---

## 4.5 PreferenceExtractor：LLM 偏好提取

### 提取模板（完整原文）

**文件：** `agent/core/memory/preference_extractor.py`（第 18-36 行）

```python
_PROMPT_TEMPLATE = """\
分析以下医生诊疗对话，提取患者的临床关键信息。
每条用单独一行，格式为"类别: 内容"。
只包含具体的、可操作的临床信息。
如果没有相关信息，就输出: 无
所有输出内容必须用中文。

提取示例：
  主诉: 情绪低落、失眠 2 周
  诊断: 中度抑郁发作 (ICD-11: 6A70)
  用药: 舍曲林 50mg qd
  PHQ-9: 14 分
  复诊周期: 每 4 周
  过敏史: 无

对话内容：
{conversation}

提取结果（或"无"）："""
```

### 完整提取逻辑

**文件：** `agent/core/memory/preference_extractor.py`（第 57-120 行）

```python
class PreferenceExtractor:
    def __init__(self, llm: Any, max_conversation_chars: int = 3000) -> None:
        self._llm = llm
        self._max_chars = max_conversation_chars

    async def extract(
        self, conversation_text: str, existing: list[str] | None = None,
    ) -> list[str]:
        truncated = conversation_text[: self._max_chars]
        prompt = _PROMPT_TEMPLATE.format(conversation=truncated)

        try:
            response = await self._llm.ainvoke(
                [{"role": "user", "content": prompt}]
            )
            raw = response.content.strip()
        except Exception as exc:
            logger.warning("PreferenceExtractor LLM call failed: %s", exc)
            return []

        if not raw or raw.strip() in ("NONE", "无", "提取结果: 无", "无相关信息"):
            return []

        candidates = [line.strip() for line in raw.split("\n") if ":" in line]
        if not candidates:
            return []

        if not existing:
            return candidates

        # 去重逻辑：双向不区分大小写的子串检查
        existing_lower = [e.lower() for e in existing]
        new_items: list[str] = []
        for item in candidates:
            item_lower = item.lower()
            if any(item_lower in ex or ex in item_lower for ex in existing_lower):
                continue
            new_items.append(item)

        return new_items
```

### 去重策略

去重使用**双向不区分大小写的子串检查**：

```python
if any(item_lower in ex or ex in item_lower for ex in existing_lower):
    continue
```

这意味着：
- 如果已有 "用药: 舍曲林"，新提取 "用药: 舍曲林 50mg qd" **会被去重**（因为已有文本是新文本的子串）
- 如果新提取 "用药: 舍曲林"，已有 "用药: 舍曲林 50mg qd" **也会被去重**（因为新文本是已有文本的子串）

### 调用时机

`background_extract` 和 `finalize_session` 中调用，关键参数：
- `max_conversation_chars = 3000`（截断对话文本）
- `_MAX_HISTORY_TURNS = 20`（只取最近 20 轮）
- LLM 温度 0（确定性提取）

---

## 4.6 语义缓存（SemanticCache）

基于 Milvus 的 QA 缓存系统，支持两级查找：精确匹配（L1_EXACT）和语义相似度匹配（L1_SEMANTIC）。

### Collection Schema

**文件：** `app/infra/cache.py`（第 199-227 行）

```python
def _ensure_collection(self) -> None:
    from pymilvus import DataType
    if self._client.has_collection(COLLECTION_NAME):
        return

    schema = self._client.create_schema()
    schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field("question", DataType.VARCHAR, max_length=2048)
    schema.add_field("question_norm", DataType.VARCHAR, max_length=2048)
    schema.add_field("answer", DataType.VARCHAR, max_length=8192)
    schema.add_field("scope", DataType.VARCHAR, max_length=16)
    schema.add_field("user_id", DataType.VARCHAR, max_length=128)
    schema.add_field("enabled", DataType.INT8)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)

    index_params = self._client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="IVF_FLAT",
        metric_type="COSINE",
        params={"nlist": 256},
    )
```

与长期记忆的区别：

| 特性 | long_term_memory | qa_semantic_cache |
|------|------------------|-------------------|
| 用途 | 用户偏好 | QA 缓存 |
| 字段 | content, memory_type | question, question_norm, answer, scope, user_id, enabled |
| 标量过滤 | user_id | question_norm + scope + user_id + enabled |
| 索引 nlist | 128 | 256 |
| answer 长度 | — | VARCHAR(8192) |

### 两级查找

**文件：** `app/infra/cache.py`（第 92-155 行）

```python
async def get_cache(self, query: str, user_id: str) -> dict[str, Any] | None:
    if not self._available:
        return None
    normalized = self._normalize(query)
    safe_norm = normalized.replace('"', '\\"')
    safe_user = user_id.replace('"', '\\"')

    # L1_EXACT: 用户级精确匹配
    user_filter = (
        f'enabled == 1 and question_norm == "{safe_norm}" and scope == "user" and user_id == "{safe_user}"'
    )
    public_filter = (
        f'enabled == 1 and question_norm == "{safe_norm}" and scope == "public"'
    )
    user_exact = self._query_one(user_filter)
    if user_exact:
        return {
            "answer": user_exact["answer"],
            "matched_question": user_exact["question"],
            "level": "L1_EXACT",
            "distance": 0.0,
        }

    # L1_EXACT: 公共级精确匹配
    public_exact = self._query_one(public_filter)
    if public_exact:
        return {
            "answer": public_exact["answer"],
            "matched_question": public_exact["question"],
            "level": "L1_EXACT",
            "distance": 0.0,
        }

    # L1_SEMANTIC: 语义相似度（最小查询长度 4 字符）
    if len("".join(normalized.split())) < MIN_SEMANTIC_CACHE_QUERY_LENGTH:
        return None

    query_embedding = await self._embeddings.aembed_query(normalized)
    scoped_filter = (
        f'enabled == 1 and (scope == "public" or (scope == "user" and user_id == "{safe_user}"))'
    )
    results = self._client.search(
        collection_name=COLLECTION_NAME,
        data=[query_embedding],
        filter=scoped_filter,
        limit=1,
        output_fields=["question", "answer", "scope", "user_id"],
    )
    hit = results[0][0] if results and results[0] else None
    if not hit:
        return None
    distance = float(hit.get("distance", 1.0))
    if distance > L1_SEMANTIC_DISTANCE_THRESHOLD:  # 0.08
        return None

    return {
        "answer": entity.get("answer", ""),
        "matched_question": entity.get("question", ""),
        "level": "L1_SEMANTIC",
        "distance": distance,
    }
```

查找顺序：**用户精确 → 公共精确 → 语义相似**。

`L1_SEMANTIC_DISTANCE_THRESHOLD = 0.08` 是余弦距离阈值，只有当最相似条目的距离小于 0.08 时才返回命中。

### 写入缓存

**文件：** `app/infra/cache.py`（第 54-90 行）

```python
async def set_cache(
    self, query: str, response: str, user_id: str | None = None, scope: str = "public",
) -> None:
    if not self._available:
        return
    normalized = self._normalize(query)
    owner = user_id or ""
    cache_scope = "user" if owner else scope
    try:
        embedding = await self._embeddings.aembed_query(normalized)
        # 写前删除已有精确匹配的旧条目
        delete_filter = (
            f'question_norm == "{safe_norm}" and scope == "{safe_scope}" and user_id == "{safe_owner}"'
        )
        self._client.delete(collection_name=COLLECTION_NAME, filter=delete_filter)
        self._client.insert(
            collection_name=COLLECTION_NAME,
            data=[{
                "question": query.strip(),
                "question_norm": normalized,
                "answer": response,
                "scope": cache_scope,
                "user_id": owner,
                "enabled": 1,
                "embedding": embedding,
            }],
        )
    except Exception as exc:
        print(f"SemanticCache set_cache failed: {exc}")
```

写前先删除同 `question_norm` + `scope` + `user_id` 的旧条目，实现"upsert"语义。

### 条件初始化

**文件：** `app/infra/cache.py`（第 19-52 行）

```python
async def initialize(self) -> None:
    try:
        embedding_api_key = self._get_embedding_api_key()
        if not settings.enable_semantic_cache:
            print("SemanticCache disabled: ENABLE_SEMANTIC_CACHE=false")
            self._available = False
            return
        if not embedding_api_key:
            print("SemanticCache disabled: no DashScope embedding key.")
            self._available = False
            return
        # ... 初始化连接和集合 ...
    except Exception as exc:
        print(f"SemanticCache init failed: {exc}")
        self._available = False
```

两个开关同时满足才启用：`enable_semantic_cache=true` + embedding API key 存在。

### Embedding Key 解析链

**文件：** `app/infra/cache.py`（第 166-183 行）

```python
@staticmethod
def _get_embedding_api_key() -> str | None:
    import os
    explicit_key = (
        settings.embedding_api_key
        or os.getenv("DASHSCOPE_EMBEDDING_API_KEY")
        or os.getenv("EMBEDDING_API_KEY")
    )
    if explicit_key:
        return explicit_key.strip()

    if settings.llm_api_key and settings.dashscope_api_key:
        return settings.dashscope_api_key.strip()

    base_url = (settings.base_url or "").lower()
    if "dashscope.aliyuncs.com" in base_url:
        return settings.dashscope_api_key.strip()
    return None
```

优先级链：
1. `settings.embedding_api_key`（即环境变量 `EMBEDDING_API_KEY`）
2. 环境变量 `DASHSCOPE_EMBEDDING_API_KEY`
3. 环境变量 `EMBEDDING_API_KEY`
4. 如果 `LLM_API_KEY` 和 `DASHSCOPE_API_KEY` 都存在 → 用 `DASHSCOPE_API_KEY`
5. 如果 `BASE_URL` 包含 dashscope.aliyuncs.com → 用 `DASHSCOPE_API_KEY`

---

## 4.7 记忆在请求链路中的位置

从 `chat_service.py` 的 `stream_chat` 函数可以看到完整的记忆集成流程。

**文件：** `app/service/chat_service.py`（第 120-256 行）

### 步骤 1-2：输入校验与缓存检查

```python
async def stream_chat(query: str, user_id: str, session_id: str):
    # ... SSE 初始化 ...

    if _is_insufficient_query(query):
        # 过短查询，直接返回提示，不保存记忆
        should_save_memory = False
        yield emit_sse({"agent": "input_validation", "content": SHORT_QUERY_RESPONSE}, "content")
    else:
        # Step 3: 语义缓存检查
        cache_hit = await semantic_cache.get_cache(query, user_id)
        if cache_hit:
            # 缓存命中 → 直接返回，不进入 Agent 图
            yield emit_sse({"agent": "semantic_cache", "content": cache_hit["answer"]}, "content")
        else:
            # Step 4: 提取记忆上下文
            mem_context = await _extract_memory_context(user_id, session_id, query)
            # Step 5: 进入 Agent 图
            state = {
                "messages": [HumanMessage(content=query)],
                "user_id": user_id,
                "session_id": session_id,
                "memory_context": mem_context,
                "next_agent": "",
                "metadata": {}
            }
            # ... graph.astream 逐节点执行 ...
```

### `_extract_memory_context` 具体实现

**文件：** `app/service/chat_service.py`（第 96-114 行）

```python
async def _extract_memory_context(user_id: str, session_id: str, query: str) -> str:
    context_parts = []
    if memory and memory.short_term.available:
        history = await memory.short_term.get_messages(user_id, session_id)
        if history:
            recent_history = history[-10:] if len(history) > 10 else history
            context_parts.append("【近期对话历史】:")
            for msg in recent_history:
                role = "User" if msg["role"] == "user" else "Assistant"
                context_parts.append(f"{role}: {msg['content']}")

    if memory and memory.long_term.available:
        prefs = await memory.long_term.retrieve_relevant(user_id, query)
        if prefs:
            context_parts.append("\n【用户长期偏好/背景】:")
            for p in prefs:
                context_parts.append(f"- {p}")

    return "\n".join(context_parts)
```

提取的内容包含：
- 最近 10 条对话历史（从 Redis）
- 语义匹配的用户长期偏好（从 Milvus）

两者合并为一个字符串，注入 `state["memory_context"]`，Agent 节点通过系统提示引用。

### 步骤 6：保存记忆

**文件：** `app/service/chat_service.py`（第 241-254 行）

```python
# 保存短时记忆
if should_save_memory and memory and memory.short_term.available:
    turn = [
        {"role": "user", "content": query},
        {"role": "assistant", "content": response_text},
    ]
    await memory.save_conversation(user_id, session_id, turn)
    # 后台异步提取长期偏好（每 5 轮）
    asyncio.create_task(_run_long_term_memory_extract(user_id, session_id))
```

### 完整流程图

```
用户输入
  │
  ├── 输入长度校验 (< 4 字符) → 直接返回提示
  │
  ├── 语义缓存检查 (Milvus qa_semantic_cache)
  │     ├── L1 精确命中 → 直接返回缓存答案
  │     └── L1 语义命中 (< 0.08) → 直接返回缓存答案
  │
  └── 未命中缓存 → 进入推理流程
        │
        ├── _extract_memory_context()
        │     ├── Redis: 最近 10 条对话历史
        │     └── Milvus: 语义匹配的用户偏好 (top-3)
        │
        ├── graph.astream(state) → SSE 流式响应
        │
        └── 推理完成
              ├── save_conversation → Redis (追加当前轮)
              └── asyncio.create_task → 后台异步偏好提取 (每 5 轮)
```

### 关键设计要点总结

| 组件 | 后端 | 可用性要求 | 失败影响 |
|------|------|-----------|----------|
| 短期记忆 | Redis | 低（可选） | 丢失历史上下文，推理继续 |
| 长期记忆 | Milvus | 低（可选） | 丢失用户偏好，推理继续 |
| 语义缓存 | Milvus | 低（可选） | 不命中缓存，进入推理流程 |
| 偏好提取 | LLM + Milvus | 低（可选） | 跳过提取，不保存新偏好 |

三个组件都采用了**优雅降级**模式：任何组件连接失败或运行时异常，都不会影响主推理流程。

---

## 4.8 更新配置

记忆系统相关的 `.env` 配置：

```bash
# Redis（短期记忆）
REDIS_URL=redis://localhost:6379
REDIS_TTL=1800

# Milvus（长期记忆 + 语义缓存）
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_API_KEY=

# DashScope Embedding（长期记忆 + 语义缓存都需要）
EMBEDDING_API_KEY=          # 推荐使用独立的 embedding key
DASHSCOPE_EMBEDDING_API_KEY= # 替代方案

# 语义缓存开关
ENABLE_SEMANTIC_CACHE=true
```
