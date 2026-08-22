# 03 请求的一生

> 学习目标：跟着一个请求从浏览器走到返回，把每一环的代码位置和 SSE 事件对上号。本章是后面所有章节的地图。

## 0. 全链路时序

```
前端                FastAPI                     Agent 层                    存储
 │ POST /api/chat     │                            │                        │
 │───────────────────►│ 鉴权(Bearer+X-User-Id)      │                        │
 │                    │ 输入校验(≥4字符)            │                        │
 │◄─accepted──────────│                            │                        │
 │                    │ ──语义缓存查询─────────────────────────────────────►│ Milvus
 │                    │   命中？──是──► 返回缓存 + aupdate_state 补记该轮 ──►│ Redis
 │                    │   │否                      │                        │
 │◄─semantic_cache_check / memory_context_extract─  │                        │
 │                    │ ──长期记忆检索────────────────────────────────────►│ Milvus
 │                    │ state = {新消息 + memory_context}                    │
 │◄─agent_workflow_start                             │                        │
 │                    │ ──astream(state, config={thread_id})──────────────►│ Redis(读checkpoint)
 │                    │                            │ history_compression    │
 │                    │                            │ orchestrator 路由      │
 │◄─agent_node_start──│◄─writer({"event":"start"})─│                        │
 │◄─chunk chunk...────│◄─writer({"chunk":...})─────│ 诊断节点(ReAct+工具)   │
 │                    │                            │   ├─query_synonyms     │
 │                    │                            │   ├─query_knowledge_graph ──► Neo4j
 │                    │                            │   └─query_vector_db ───────► Milvus
 │                    │                            │ 治疗 → 药审（同构）     │
 │◄─agent_node_complete ×N                          │                        │
 │                    │ ──写入 checkpoint──────────────────────────────────►│ Redis
 │                    │ ──set_cache(问答对)────────────────────────────────►│ Milvus
 │                    │ 每5轮: 后台提取临床要点────────────────────────────►│ Milvus
 │◄─done──────────────│                            │                        │
```

## 1. 入口与鉴权（`app/router/chat.py`）

- `X-User-Id` 必填且匹配 `^[A-Za-z0-9_.:-]{1,128}$`（防注入到 Redis key / Milvus filter）
- `API_AUTH_TOKEN` 非空时强制 Bearer 校验，用 `secrets.compare_digest`（恒定时间比较）
- Body：`ChatRequest {query: 1-4000 字, session_id: 同上正则}`

**关键点**：`session_id` 就是后续一切会话状态的钥匙（Checkpoint 的 thread_id）。

## 2. 输入校验（`app/service/chat_service.py`）

归一化后 `< 4` 个非空白字符 → 返回引导话术，**不进图、不记状态、不计轮次**（`should_record_turn = False`）。这是本地第一道闸，省一次图执行。

## 3. 语义缓存（`app/infra/cache.py`）

两级：
- **L1_EXACT**：规范化文本（lowercase + 去多余空白）精确匹配
- **L1_SEMANTIC**：向量距离 < 0.08 判为相似

命中 → 直接回答案。**但缓存命中不经过图，该轮必须用 `graph.aupdate_state` 手动补写进 checkpoint**，否则多轮上下文断裂（这是 v2 重构时补的关键逻辑，第 09 章展开）。

## 4. 记忆上下文 + 图执行

- 只注入**长期记忆**（Milvus 检索的临床要点）；**近期历史不用拼**——checkpoint 自动携带
- 每轮只传**新消息**：`state = {"messages": [HumanMessage(query)], ...}`，`add_messages` reducer 负责追加（第 04 章）
- `config = {"configurable": {"thread_id": session_id}}`（第 05 章）

## 5. SSE 事件协议（前端据此渲染）

| 事件字段 | 含义 | 前端行为 |
|---------|------|---------|
| `status=accepted` | 已受理 | 顶部提示 |
| `status=semantic_cache_check / memory_context_extract / agent_workflow_start` | 阶段进度 | 右侧工作流面板 |
| `status=agent_node_start` + `agent` | 节点开始 | 阶段高亮 |
| `status=agent_tool_call / agent_tool_done` + `tool` | 工具调用 | 显示"正在调用 xxx" |
| `agent=xxx, content=chunk` | **正文增量** | 追加到消息气泡 |
| `status=agent_node_complete` | 节点完成 | 阶段打勾 |
| `done=true` | 结束 | 解锁输入框 |

节点内部怎么拿到 `writer` 推流？`langgraph.config.get_stream_writer()`——图用 `stream_mode=["updates","custom"]` 调用，custom 事件就是节点里 writer 发的内容。

## 6. 响应后的三件事（容易漏讲）

1. **写 checkpoint**：图执行完 LangGraph 自动持久化
2. **写语义缓存**：`semantic_cache.set_cache(query, response, user_id)`——v2 补上的，之前只有预载脚本会写（第 11 章坑 7）
3. **第 5 轮触发后台提取**：`asyncio.create_task` 从 checkpoint 读历史 → LLM 提取临床要点 → 存 Milvus（任务持有强引用防 GC，这是 Python asyncio 的经典坑）

## 面试官可能追问

1. SSE 和 WebSocket 怎么选？（单向流式 + HTTP 基建复用 → SSE；需要双向（打断、语音）才上 WS）
2. 客户端中途断开，流的生成会怎样？状态还一致吗？（生成器被取消；checkpoint 已记录到完成的节点）
3. 缓存命中为什么还要写 checkpoint？不写会怎样？（下一轮历史缺一问一答，agent 看到的对话是断裂的）
