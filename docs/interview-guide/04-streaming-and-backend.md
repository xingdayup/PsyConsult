# 04. 流式输出与后端 API

## 模块解决的问题

LLM 和工具调用可能需要数秒到几十秒。如果前端一直无反馈，用户会认为系统卡住。项目通过 SSE 实现两类流式：

- **状态流**：已接收、正在检查缓存、正在提取记忆、正在调用工具、Agent 完成。
- **内容流**：Agent 生成的正文 chunk。

## API 路由

核心文件：`app/router/chat.py`

```python
return StreamingResponse(
    stream_chat(request.query, user_id, request.session_id),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    },
)
```

面试讲法：  
`StreamingResponse` 负责把异步生成器里的每个 `yield` 直接发给浏览器。`X-Accel-Buffering: no` 和 `Cache-Control: no-transform` 是为了减少代理层缓冲，保证流式体验。

## 请求身份与安全边界

```python
def require_chat_identity(authorization=None, x_user_id=None) -> str:
    if settings.api_auth_token:
        token = _extract_bearer_token(authorization)
        if token is None or not secrets.compare_digest(token, settings.api_auth_token):
            raise HTTPException(status_code=401)

    if not x_user_id:
        raise HTTPException(status_code=400)
    if not USER_ID_PATTERN.fullmatch(x_user_id):
        raise HTTPException(status_code=400)
    return x_user_id
```

面试讲法：  
当前不是完整登录系统，但已经避免直接信任 body 里的 `user_id`，改用请求头 `X-User-Id`，并支持轻量 Bearer Token。

`user_id` 和 `session_id` 的分工：

```text
X-User-Id 请求头 -> user_id -> 代表当前医生/用户
body.session_id -> session_id -> 代表当前诊疗会话窗口
Redis 短期记忆 key -> memory:short:{user_id}:{session_id}
Milvus 长期记忆 filter -> user_id == 当前用户
```

面试讲法：  
`user_id` 不放在 body 里，是为了避免前端随意伪造业务身份字段；当前原型用请求头承载。`session_id` 表示一次诊疗对话窗口，切换窗口时 Redis 短期上下文互不污染；长期记忆按 `user_id` 跨 session 召回。

## stream_chat 主流程

核心文件：`app/service/chat_service.py`

```python
yield emit_sse({"status": "accepted", "content": "已接收病例，开始分析..."}, "status")

yield emit_sse({"status": "semantic_cache_check", "content": "正在检查语义缓存..."}, "status")
cache_hit = await semantic_cache.get_cache(query, user_id)

yield emit_sse({"status": "memory_context_extract", "content": "正在提取会话记忆..."}, "status")
mem_context = await _extract_memory_context(user_id, session_id, query)

async for stream_mode, data in graph.astream(
    state, config=config, stream_mode=["updates", "custom"]
):
    ...
```

面试讲法：  
第一条 SSE 在进入请求后立即发送，所以前端 1 秒内能看到“已接收”。之后再进入语义缓存、记忆提取和 Agent 工作流。

回答结束后，后端先保存 Redis 短期记忆，再用后台任务触发长期记忆抽取：

```python
await memory.save_conversation(user_id, session_id, turn)
asyncio.create_task(_run_long_term_memory_extract(user_id, session_id))
```

这个任务不阻塞 SSE `done`，所以长期记忆沉淀不会拖慢用户看到最终回答。

## SSE 统一出口

```python
def emit_sse(payload: dict, kind: str) -> str:
    logger.info(
        "event=sse_emit user_id=%s session_id=%s kind=%s total=%.3fs",
        user_id, session_id, kind, time.perf_counter() - request_start,
    )
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

面试讲法：  
所有 SSE 都通过统一函数输出，同时记录 `sse_emit` 日志，这样可以定位首个字节到底什么时候发出。

## Agent 内部流式

核心文件：`agent/agents/diagnosis_agent.py`

```python
async for msg, metadata in self.inner_agent.astream(
    {"messages": messages}, stream_mode="messages",
):
    if isinstance(msg, AIMessageChunk):
        if msg.content:
            full_content += msg.content
            buffer += msg.content
            if len(buffer) >= 20 or "\n" in buffer:
                writer({"agent": "differential_diagnosis", "chunk": buffer})
                buffer = ""
```

面试讲法：  
这里不是等节点完成才返回，而是在 Agent 生成过程中把 token chunk 缓冲成较小片段再推给前端。缓冲 20 字符是为了避免每个字符都触发前端 Markdown 重渲染。

## 面试 Q&A

**Q：为什么用 SSE，不用 WebSocket？**  
A：这个场景主要是客户端发一次请求，服务端持续返回文本和状态，SSE 更简单，HTTP 兼容性好，也更容易和 FastAPI 的 `StreamingResponse` 配合。

**Q：如何证明它是真的流式？**  
A：后端每次 `yield` 前记录 `event=sse_emit`，前端用 `ReadableStream.getReader()` 逐块读取。日志可以看到第一条 status 在请求开始后很快发出。

**Q：你遇到过什么流式问题？**  
A：早期 `stream_mode="updates"` 只能在节点完成后推送，用户等待时间长。后来改成 `["updates", "custom"]`，Agent 内部用 `get_stream_writer()` 主动推送节点开始、工具调用和内容 chunk。

## 截图建议

- 截 `StreamingResponse` 和防缓冲 header。
- 截 `emit_sse()`，说明日志和 SSE 格式。
- 截 `graph.astream(..., stream_mode=["updates", "custom"])`。
- 截 Agent `AIMessageChunk` 缓冲逻辑。
