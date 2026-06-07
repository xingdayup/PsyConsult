# 第三章：Agent 工作流代码走读

> 本文档逐行解读核心 Agent 的工作流代码，涵盖 Orchestrator 路由逻辑、ReAct Agent 通用模式、流式事件类型、性能包装器、CLI 交互模式以及工具分配策略。

---

## 1. Orchestrator 路由逻辑

完整的 `OrchestratorAgent.route()` 方法在 `agent/agents/orchestrator.py` L22-L86。

### 完整代码（L22-L86）

```python
# source: agent/agents/orchestrator.py (L22-L86)
async def route(self, state: AgentState) -> Dict[str, Any]:
    """
    根据用户的最新输入，决定路由走向。
    """
    # 流式状态：开始路由
    writer = get_stream_writer()
    writer({"agent": "orchestrator", "event": "start"})

    # 获取最新的一条用户消息
    messages = state.get("messages", [])
    if not messages:
        last_message = ""
    else:
        # langgraph 内部有时候会把 tuple 转成实际的 BaseMessage 子类
        last_msg_obj = messages[-1]
        if isinstance(last_msg_obj, tuple):
            last_message = last_msg_obj[1]
        elif hasattr(last_msg_obj, "content"):
            last_message = last_msg_obj.content
        else:
            last_message = str(last_msg_obj)
    memory_context = state.get("memory_context", "")

    memory_block = f"\n【历史对话参考】：\n{memory_context}" if memory_context else ""

    system_prompt = f"""你是一个精神科临床决策支持系统的总路由（Clinical Router）。
...（全文见 [第二章 Orchestrator 路由 Prompt](02-core-prompts-compendium.md#1-orchestrator-路由-prompt)）...
"""

    response = await self.llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=last_message)
    ])

    decision = response.content.strip().lower()
    if "drug" in decision:
        next_node = "drug_interaction"
        state["metadata"]["is_drug_review_workflow"] = True
        print("🧭 [ClinicalRouter] 识别到药物审查意图，路由至: drug_interaction")
    elif "diagnosis" in decision or "differential" in decision:
        next_node = "differential_diagnosis"
        print("🧭 [ClinicalRouter] 识别到鉴别诊断意图，路由至: differential_diagnosis")
    elif "treatment" in decision:
        next_node = "treatment_recommend"
        print("🧭 [ClinicalRouter] 识别到治疗推荐意图，路由至: treatment_recommend")
    else:
        next_node = "differential_diagnosis"
        print("🧭 [ClinicalRouter] 默认路由至: differential_diagnosis")

    return {"next_agent": next_node, "metadata": state.get("metadata", {})}
```

### 逐段注解

**第 27-28 行：流式事件发射**
```python
writer = get_stream_writer()
writer({"agent": "orchestrator", "event": "start"})
```
`get_stream_writer()` 是 `langgraph.config` 提供的一个 callable，通过它将自定义事件发送到 `stream_mode="custom"` 的流中。orchestrator 是图中第一个节点，因此 `start` 事件也标志整个工作流的启动。

**第 30-41 行：消息提取**
```python
messages = state.get("messages", [])
if not messages:
    last_message = ""
else:
    last_msg_obj = messages[-1]
    if isinstance(last_msg_obj, tuple):
        last_message = last_msg_obj[1]
    elif hasattr(last_msg_obj, "content"):
        last_message = last_msg_obj.content
    else:
        last_message = str(last_msg_obj)
```
**三种消息格式的处理**反映了 LangGraph 内部状态表示的复杂性：
- **tuple** 类型：当 `add_messages` reducer 接收新消息时，内部可能用 tuple 表示 (index, message) 格式。
- **BaseMessage** 子类：标准的 LangChain 消息格式，通过 `.content` 访问。
- **其他**：兜底 str() 转换。

**第 45 行：memory_context 注入**
```python
memory_block = f"\n【历史对话参考】：\n{memory_context}" if memory_context else ""
```
条件性注入块，仅在 memory_context 非空时追加到 system_prompt 末尾。

**第 66-69 行：LLM 调用**
```python
response = await self.llm.ainvoke([
    SystemMessage(content=system_prompt),
    HumanMessage(content=last_message)
])
```
使用 `ainvoke`（非流式）调用 LLM——orchestrator 不需要流式输出，它只需要一个简短的路由名称。

**第 71-84 行：响应解析**
```python
decision = response.content.strip().lower()
if "drug" in decision:
    next_node = "drug_interaction"
    state["metadata"]["is_drug_review_workflow"] = True
elif "diagnosis" in decision or "differential" in decision:
    next_node = "differential_diagnosis"
elif "treatment" in decision:
    next_node = "treatment_recommend"
else:
    next_node = "differential_diagnosis"
```
**关键字匹配优先级**：`"drug"` 优先于 `"diagnosis"` 和 `"treatment"`。这是因为"药物审查"场景中用户输入可能同时包含诊断和药物名，优先匹配 drug 更安全。

`is_drug_review_workflow` 仅在路由到 drug 时被设置为 `True`，这是提供给前端或调用方的额外上下文。

**第 86 行：返回值**
```python
return {"next_agent": next_node, "metadata": state.get("metadata", {})}
```
`next_agent` 被 LangGraph 的条件边 `_route_condition()` 读取（`graph_manager.py` L27-L28）：
```python
def _route_condition(self, state: AgentState) -> str:
    return state.get("next_agent", "differential_diagnosis")
```

---

## 2. ReAct Agent 通用模式

三个领域 Agent（Diagnosis、Treatment、DrugReview）共享完全相同的代码结构。以 `diagnosis_agent.py` 为例：

### `__init__`：初始化（L17-L24）

```python
# source: agent/agents/diagnosis_agent.py (L17-L24)
class DiagnosisAgentNode:
    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(dotenv_path)
        from config import get_settings
        self.llm = ChatOpenAI(**get_settings().get_model_config(), temperature=0.1)
        self.tools = [query_synonyms, query_knowledge_graph, query_vector_db]
        self.inner_agent = create_react_agent(self.llm, self.tools)
```

**初始化的 4 个步骤**：
1. 加载 `.env`（当前文件所在目录的父目录下的 `.env`）
2. 通过 `get_settings()` 获取配置
3. 实例化 `ChatOpenAI`，temperature=0.1
4. 创建 `create_react_agent(llm, tools)`——这是 LangGraph 预构建的 ReAct 循环

**三个 Agent 的工具分配差异**：

| Agent | tools | 文件行 |
|---|---|---|
| Diagnosis | `[query_synonyms, query_knowledge_graph, query_vector_db]` | `diagnosis_agent.py` L23 |
| Treatment | `[query_vector_db, query_knowledge_graph]` | `treatment_agent.py` L23 |
| DrugReview | `[query_knowledge_graph]` | `drug_review_agent.py` L21 |

### `__call__`：核心执行循环（L67-L100）

```python
# source: agent/agents/diagnosis_agent.py (L67-L100)
async def __call__(self, state: AgentState) -> Dict[str, Any]:
    writer = get_stream_writer()
    writer({"agent": "differential_diagnosis", "event": "start"})

    system_prompt = self._build_system_prompt(state.get("memory_context", ""))
    messages = [SystemMessage(content=system_prompt)] + list(state["messages"])

    full_content = ""
    buffer = ""
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
            elif hasattr(msg, "tool_calls") and msg.tool_calls:
                if buffer:
                    writer({"agent": "differential_diagnosis", "chunk": buffer})
                    buffer = ""
                for tc in msg.tool_calls:
                    writer({"agent": "differential_diagnosis", "event": "tool_call", "tool": tc.get("name", "")})
        elif isinstance(msg, ToolMessage):
            if buffer:
                writer({"agent": "differential_diagnosis", "chunk": buffer})
                buffer = ""
            writer({"agent": "differential_diagnosis", "event": "tool_done"})
    if buffer:
        writer({"agent": "differential_diagnosis", "chunk": buffer})

    return {"messages": [AIMessage(content=full_content)]}
```

### 执行流程详解

```
1. get_stream_writer()          → 获取 LangGraph 流写入器
2. writer({"agent":..., "event": "start"})  → 通知前端 Agent 开始执行
3. _build_system_prompt()       → 构建含 memory_context 的系统提示
4. inner_agent.astream(         → 启动 ReAct 循环流式执行
      stream_mode="messages")
   │
   ├── AIMessageChunk           → 文本 token → 累积到 buffer → 按条件刷出
   │   ├── len(buffer) >= 20    → 按长度刷出（避免前端逐字闪烁）
   │   └── "\n" in buffer       → 遇到换行立即刷出（保持行完整性）
   │
   ├── AIMessageChunk.tool_calls→ 工具调用 → 先刷 buffer，再发 tool_call 事件
   │
   └── ToolMessage              → 工具返回 → 先刷 buffer，再发 tool_done 事件
   │
5. return {"messages": [AIMessage(content=full_content)]}  → 返回完整结果
```

### Token 缓冲机制

```python
# L83-L84: 双条件刷出策略
if len(buffer) >= 20 or "\n" in buffer:
    writer({"agent": "differential_diagnosis", "chunk": buffer})
    buffer = ""
```

**设计理由**：
- `len(buffer) >= 20`：批量发送，减少 SSE 事件数量。20 个字符是平衡"实时性"和"网络开销"的经验值。
- `"\n" in buffer`：遇到换行立即刷新，保证 markdown 表格的行完整性——如果跨行发送，前端接收到的中间状态可能无法正确渲染。

三个 Agent 完全一致的实现模式（Treatment: L80-L84, DrugReview: L84-L88）。

---

## 3. 流式事件类型

后端通过 `graph.astream(state, stream_mode=["updates", "custom"])` 同时运行两种流模式，见 `chat_service.py` L197-L235。

### 事件类型枚举

```python
# source: app/service/chat_service.py (L197-L235)
async for stream_mode, data in graph.astream(
    state, config=config, stream_mode=["updates", "custom"]
):
    if stream_mode == "custom":
        # 自定义事件 — 由各 Agent 通过 get_stream_writer() 发射
        ...
    elif stream_mode == "updates":
        # LangGraph 节点完成事件 — 自动发射
        ...
```

### Event Type 1: `start`

```json
// 由每个 Agent __call__ 方法的第一行发射
{"agent": "differential_diagnosis", "event": "start"}
```

**发生时机**：Agent 节点开始执行时。
**前端行为**：显示"正在进入鉴别诊断..."状态。

### Event Type 2: `tool_call`

```json
// 由 ReAct Agent 内部工具调用时发射
{"agent": "differential_diagnosis", "event": "tool_call", "tool": "query_synonyms"}
```

**发生时机**：ReAct 循环决定调用工具时（`tool_calls` 列表非空）。
**前端行为**：显示"正在调用 query_synonyms..."状态。

### Event Type 3: `tool_done`

```json
// 由 ReAct Agent 收到工具返回时发射
{"agent": "differential_diagnosis", "event": "tool_done"}
```

**发生时机**：`ToolMessage` 返回时。
**前端行为**：显示"工具查询完成，正在生成分析..."状态。

### Event Type 4: `chunk`

```json
// 由 Agent 的 buffer 机制批量发射
{"agent": "differential_diagnosis", "chunk": "根据患者的症状描述，初步"}
```

**发生时机**：buffer 达到 20 字符或遇到换行时。
**前端行为**：追加到当前 Agent 的消息内容中（`full_response += data["chunk"]`）。

### Event Type 5: `agent_node_complete`

```json
// 由 LangGraph updates 模式自动发射
{"status": "agent_node_complete", "agent": "differential_diagnosis",
 "content": "differential_diagnosis 已完成，正在整理结果..."}
```

**发生时机**：LangGraph 的 `updates` 模式在每个节点完成后自动发射。
**前端行为**：标记当前 Agent 完成，准备进入下一阶段。

### Event Type 6: `done`

```json
// 由 chat_service.py 在所有处理后发射
{"done": true}
```

**发生时机**：记忆保存完成后、SSE 流结束前。
**前端行为**：关闭 SSE 连接，标记消息流结束。

### 事件序列示例

以完整三步骤流程为例：

```
1.  {"event": "start", "agent": "orchestrator"}
2.  {"event": "agent_node_complete", "agent": "orchestrator", ...}
3.  {"event": "start", "agent": "differential_diagnosis"}
4.  {"event": "tool_call", "agent": "differential_diagnosis", "tool": "query_synonyms"}
5.  {"event": "tool_done", "agent": "differential_diagnosis"}
6.  {"event": "tool_call", "agent": "differential_diagnosis", "tool": "query_knowledge_graph"}
7.  {"event": "tool_done", "agent": "differential_diagnosis"}
8.  {"chunk": "## 症状清单\n| 症状 | ...", "agent": "differential_diagnosis"}
9.  {"chunk": "满足 4/6 条 → 建议诊断: 抑郁发作", "agent": "differential_diagnosis"}
10. {"event": "agent_node_complete", "agent": "differential_diagnosis", ...}
11. {"event": "start", "agent": "treatment_recommend"}
12. {"chunk": "## 治疗方案\n诊断: 抑郁发作 (ICD-11: 6A70)", "agent": "treatment_recommend"}
13. ...
14. {"event": "agent_node_complete", "agent": "drug_interaction", ...}
15. {"done": true}
```

---

## 4. _timed_node 包装器

定义在 `agent/core/workflow/graph_manager.py` L30-L49。

### 完整代码

```python
# source: agent/core/workflow/graph_manager.py (L30-L49)
async def _timed_node(self, node_name: str, node, state: AgentState):
    start = time.perf_counter()
    user_id = state.get("user_id", "")
    session_id = state.get("session_id", "")
    logger.info(
        "event=agent_node_start user_id=%s session_id=%s node=%s",
        user_id,
        session_id,
        node_name,
    )
    try:
        return await node(state)
    finally:
        logger.info(
            "event=agent_node_complete user_id=%s session_id=%s node=%s elapsed=%.3fs",
            user_id,
            session_id,
            node_name,
            time.perf_counter() - start,
        )
```

### 被包装的四个节点

```python
# source: agent/core/workflow/graph_manager.py (L51-L61)
async def _run_orchestrator(self, state: AgentState):
    return await self._timed_node("orchestrator", self.orchestrator.route, state)

async def _run_diagnosis(self, state: AgentState):
    return await self._timed_node("diagnosis", self.diagnosis_node, state)

async def _run_treatment(self, state: AgentState):
    return await self._timed_node("treatment", self.treatment_node, state)

async def _run_drug_review(self, state: AgentState):
    return await self._timed_node("drug_review", self.drug_review_node, state)
```

### 设计分析

| 特性 | 说明 |
|---|---|
| **AOP 风格** | `_timed_node` 是一个包装器（wrapper），在节点执行前后自动记录日志，类似于面向切面编程的 around advice |
| **finally 保证** | `try/finally` 确保即使节点抛出异常，`_agent_node_complete` 日志仍然会输出（含 elapsed 时间），这对排查性能问题和超时场景非常关键 |
| **结构化日志** | 使用 `event=` 前缀的 key=value 格式，便于日志系统（如 ELK）解析。字段：`event`, `user_id`, `session_id`, `node`, `elapsed` |
| **性能基准** | 每次节点执行都记录耗时，可用于后续的性能分析看板 |

**日志输出示例**：
```
event=agent_node_start user_id=doctor_001 session_id=test_session_1 node=orchestrator
event=agent_node_complete user_id=doctor_001 session_id=test_session_1 node=orchestrator elapsed=1.234s
event=agent_node_start user_id=doctor_001 session_id=test_session_1 node=diagnosis
event=agent_node_complete user_id=doctor_001 session_id=test_session_1 node=diagnosis elapsed=8.567s
```

---

## 5. Agent CLI 交互模式

定义在 `agent/main.py` L80-L173。

### 主循环代码（L80-L173）

```python
# source: agent/main.py (L80-L173)
async def run_interactive_mode(
    graph_manager: AgentGraphManager,
    user_id: str,
    session_id: str,
    memory: MemoryManager,
) -> None:
    """运行与多智能体图的交互式聊天循环。"""
    print("\n" + "=" * 60)
    print("🏥 Clinical Decision Support System Ready!")
    print(f"  Doctor:  {user_id}")
    print(f"  Session: {session_id}")
    print("  Type 'quit' / 'exit' / 'q' to stop")
    print("=" * 60)

    st_ok = memory.short_term.available
    lt_ok = memory.long_term.available
    print(f"\n  [MEM] Short-term (Redis) : {'✅ connected' if st_ok else '❌ not available'}")
    print(f"  [MEM] Long-term  (Milvus): {'✅ connected' if lt_ok else '❌ not available'}")
    print()

    graph = graph_manager.build_graph()

    # 初始化状态
    state: AgentState = {
        "messages": [],
        "user_id": user_id,
        "session_id": session_id,
        "memory_context": "",
        "next_agent": "",
        "metadata": {}
    }

    turn_count = 0

    try:
        while True:
            try:
                user_input = input("\n👤 You: ").strip()
            except UnicodeDecodeError:
                raw = sys.stdin.buffer.readline()
                user_input = raw.decode('utf-8', errors='replace').strip()
            except EOFError:
                break

            if user_input.lower() in ("quit", "exit", "q"):
                break
            if not user_input:
                continue

            # 1. 在执行前获取内存上下文
            print("🧠 Retrieving memory context...")
            mem_context = await _extract_memory_context(memory, user_id, session_id, user_input)

            # 使用新输入和内存更新状态
            state["messages"].append(HumanMessage(content=user_input))
            state["memory_context"] = mem_context

            # 2. 执行图
            print("🤖 Processing...")
            result = await graph.ainvoke(state)

            # 使用结果消息更新状态
            state["messages"] = result["messages"]
            response_text = result["messages"][-1].content

            print(f"\n🤖 AI: {response_text}\n")

            # 3. 保存到短期内存
            if memory.short_term.available:
                turn = [
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": response_text},
                ]
                await memory.save_conversation(user_id, session_id, turn)

            # 4. 定期触发长期内存提取
            turn_count += 1
            if turn_count % 5 == 0:
                print("🔄 [Background] Triggering long-term memory extraction...")
                asyncio.create_task(
                    memory.background_extract(user_id, session_id, _create_memory_extraction_llm())
                )

    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        logging.exception("Agent execution failed")
    finally:
        print("\n" + "-" * 60)
        print("💾 Saving session preferences to long-term memory...")
        await memory.finalize_session(user_id, session_id, _create_memory_extraction_llm())
        print("✅ Session finalized.")
        print("-" * 60 + "\n")
```

### 循环步骤注解

**第 1 步：获取输入（L117-L127）**
```python
try:
    user_input = input("\n👤 You: ").strip()
except UnicodeDecodeError:
    raw = sys.stdin.buffer.readline()
    user_input = raw.decode('utf-8', errors='replace').strip()
except EOFError:
    break
```
处理了两种边界情况：`UnicodeDecodeError`（Windows/macOS 终端编码问题）和 `EOFError`（管道输入结束）。

**第 2 步：提取记忆上下文（L130-L134）**
```python
mem_context = await _extract_memory_context(memory, user_id, session_id, user_input)
state["messages"].append(HumanMessage(content=user_input))
state["memory_context"] = mem_context
```
`_extract_memory_context` 函数（`main.py` L55-L78）从 Redis 获取最近 10 条对话历史，从 Milvus 获取语义相关的长期偏好。

**第 3 步：执行图（L137-L145）**
```python
result = await graph.ainvoke(state)
state["messages"] = result["messages"]
response_text = result["messages"][-1].content
```
CLI 模式下使用非流式的 `ainvoke`（与后端 SSE 模式不同）。完整的结果通过 `result["messages"][-1]` 获取。

**第 4 步：保存短期记忆（L148-L153）**
```python
if memory.short_term.available:
    turn = [{"role": "user", ...}, {"role": "assistant", ...}]
    await memory.save_conversation(user_id, session_id, turn)
```
将当前轮次的对话保存到 Redis。

**第 5 步：定期提取长期记忆（L156-L161）**
```python
turn_count += 1
if turn_count % 5 == 0:
    asyncio.create_task(
        memory.background_extract(user_id, session_id, _create_memory_extraction_llm())
    )
```
每 5 轮触发一次异步后台提取，使用 `asyncio.create_task` 实现"fire-and-forget"，不阻塞主循环。

**第 6 步：会话结束清理（finally 块 L168-L173）**
```python
await memory.finalize_session(user_id, session_id, _create_memory_extraction_llm())
```
提取全部偏好保存到 Milvus，然后清空 Redis 短期记忆。

### CLI 入口点

```python
# source: agent/main.py (L176-L233)
async def main() -> None:
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--query", "-q", type=str, help="Single query mode")
    parser.add_argument("--user", "-u", type=str, default="user_1001")
    parser.add_argument("--session", "-s", type=str, default=None)
    parser.add_argument("--debug", "-d", action="store_true")
    args = parser.parse_args()
    ...
    # 初始化内存管理器
    memory = MemoryManager(
        redis_url=settings.redis_url,
        redis_ttl=settings.redis_ttl,
        milvus_host=settings.milvus_host,
        milvus_port=settings.milvus_port,
        ...
    )
    await memory.initialize()

    # 初始化图管理器
    graph_manager = AgentGraphManager()
    ...
```

---

## 6. 工具分配表

| Agent | 工具 | 用途 | 来源文件 |
|---|---|---|---|
| **Orchestrator** | 无 | 纯 LLM 路由，不调用任何工具 | `orchestrator.py` L66-L69 |
| **Diagnosis** | `query_synonyms` | 口语→标准术语映射（如"睡不着"→"失眠"） | `synonym_tool.py` L22-L42 |
| | `query_knowledge_graph` | 查询疾病-症状关联、ICD-11 编码 | `graph_tool.py` L198-L229 |
| | `query_vector_db` | 检索 ICD-11 诊断标准原文（RAG） | `vector_tool.py` L99-L127 |
| **Treatment** | `query_vector_db` | 检索中国精神科指南的治疗路径 | `vector_tool.py` L99-L127 |
| | `query_knowledge_graph` | 查询一线/二线药物及详细信息 | `graph_tool.py` L198-L229 |
| **DrugReview** | `query_knowledge_graph` | 查询药物间的 INTERACTS_WITH 关系 | `graph_tool.py` L198-L229 |

### 工具分配的原理

```
Diagnosis Agent:    [synonym] ──→ 口语规范化
                    [graph]   ──→ 症状-疾病关联
                    [vector]  ──→ ICD-11 诊断标准（RAG）
                              ↓
Treatment Agent:    [vector]  ──→ 指南治疗路径（RAG）
                    [graph]   ──→ 药物信息查询
                              ↓
DrugReview Agent:   [graph]   ──→ 药物相互作用
```

**工具数量递减**：从 Diagnosis（3 个）到 Treatment（2 个）到 DrugReview（1 个）。这反映了流水线末端的 Agent 依赖上游已生产的信息，不需要从原始数据重新检索。

**graph_tool.py 的特殊性**：它是系统中被最广泛使用的工具（3 个 Agent 都依赖它）。它内部有双层查询策略（`graph_tool.py` L208-L229）：

```python
# source: agent/tools/graph_tool.py (L208-L212)
if not _use_llm_graph_cypher():
    # 默认：快速关键词查询
    fallback_result = _fallback_graph_keyword_search(query)
    return fallback_result
# 可选：LLM 生成的 Cypher 查询
chain = _get_graph_chain()
result = chain.invoke({"query": query})
```

默认使用关键词搜索（`_fallback_graph_keyword_search`），不依赖 LLM 生成 Cypher。这在 `graph_tool.py` L209 的日志说明："如需 LLM Cypher，设置 ENABLE_LLM_GRAPH_CYPHER=true"。

---

## 7. Agent 图集成测试

`graph_manager.py` L87-L114 提供了一个独立的集成测试函数，可在命令行直接运行验证：

```python
# source: agent/core/workflow/graph_manager.py (L87-L114)
async def test_graph():
    """临床链路集成测试。"""
    manager = AgentGraphManager()
    graph = manager.build_graph()

    print("🏥 临床决策支持系统 (Multi-Agent 编排模式)")
    print("=" * 60)

    state: AgentState = {
        "messages": [],
        "user_id": "doctor_001",
        "session_id": "test_session_1",
        "memory_context": "",
        "next_agent": "",
        "metadata": {},
    }

    # 测试病例: 典型抑郁发作
    query = "患者近两周情绪低落、失眠、食欲下降，以前喜欢打篮球现在没兴趣了"
    print(f"👨‍⚕️ 医生: {query}")
    state["messages"].append(HumanMessage(content=query))

    result = await graph.ainvoke(state)
    print(f"\n🤖 CDS:\n{result['messages'][-1].content}")


if __name__ == "__main__":
    asyncio.run(test_graph())
```

执行方式：
```bash
cd agent && python core/workflow/graph_manager.py
```

该测试会经历完整的三步骤流水线（orchestrator → diagnosis → treatment → drug_review），并在终端输出最终结果。

---

## 章末要点

1. Orchestrator 的路由逻辑使用**关键字子串匹配**（非严格全词匹配），容错性强，按 `drug > diagnosis > treatment` 优先级解析。
2. 三个领域 Agent 的 `__call__` 方法代码结构**完全一致**（差异仅在于 prompt 和 tools），是强约定的"共同模式"。
3. Token 缓冲使用 **20 字符 / 换行**双条件刷出策略，平衡实时性和 SSE 事件数量。
4. `_timed_node` 包装器通过 AOP 模式为每个节点提供性能日志，确保异常情况下也能记录耗时。
5. CLI 交互模式每 5 轮触发**异步后台长期记忆提取**，不阻塞主对话循环。
6. 工具分配从 Diagnosis 到 DrugReview 递减，graph_tool 是最核心的基础工具，内部默认使用关键词搜索而非 LLM 生成 Cypher。
