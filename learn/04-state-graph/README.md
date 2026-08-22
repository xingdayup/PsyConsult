# 04 StateGraph 编排

> 学习目标：讲清楚图的组装、路由机制、AgentState 每个 channel 的语义，以及 add_messages reducer 为什么是整个多轮能力的基础。
> 状态：骨架已含全部要点与代码锚点，叙述性文字待补。

## 1. 图的组装（`agent/core/workflow/graph_manager.py`）

- 节点：`orchestrator` / `differential_diagnosis` / `treatment_recommend` / `drug_interaction` + `history_compression`（仅启用 checkpointer 时加入）
- 边：`START → history_compression → orchestrator → (条件边) → 流水线 → END`
- 条件边：`_route_condition` 读 `state["next_agent"]`，映射表 `{differential_diagnosis / treatment_recommend / drug_interaction}`
- **中途入链**：治疗/药审意图直接从 orchestrator 进对应节点，沿边走到 END——这就是"条件入口 + 固定流水线"

要点：`build_graph(checkpointer=None)` 参数化——同一个类支持有状态/无状态两种编译产物。

## 2. AgentState 详解（`agent/core/workflow/state.py`）

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]  # 唯一有 reducer 的通道
    next_agent: str      # 路由标记，orchestrator 写、条件边读
    user_id: str
    session_id: str
    memory_context: str  # 每轮覆盖写入（长期记忆检索结果）
    metadata: dict       # 如 is_drug_review_workflow
```

**reducer 语义**（面试高频）：
- 无 reducer 的通道：新输入**覆盖**旧值（`next_agent`、`memory_context` 每轮重写，天然防陈旧）
- `add_messages`：新消息**追加**；按 id 去重更新；配合 `RemoveMessage` 可删除——checkpoint 多轮累积全靠它

## 3. 节点内部：外层图节点 + 内层 ReAct agent 的双层结构

以诊断节点为例（`agent/agents/diagnosis_agent.py`）：

- 外层是图节点：拿全量 `state["messages"]`（含历史）+ `memory_context` 拼进 system prompt
- 内层 `create_react_agent(llm, tools)`：自主决定调 `query_synonyms / query_knowledge_graph / query_vector_db`
- 流式：内层 `astream(stream_mode="messages")` 逐 chunk 用 `writer` 发出；**只有最终 AIMessage 写回 state**（工具调用轨迹不进 checkpoint——这是第 09 章演进讨论的点）

三个领域 agent 的工具配置差异：

| 节点 | 工具 |
|------|------|
| differential_diagnosis | 同义词 + 图谱 + 向量（3 个） |
| treatment_recommend | 向量 + 图谱 |
| drug_interaction | 仅图谱 |

## 4. orchestrator 路由（`agent/agents/orchestrator.py`）

- LLM 输出意图词 → 关键词包含匹配到节点名（"drug" → drug_interaction）
- 兜底：无法判断默认 differential_diagnosis
- 写 `next_agent` + `metadata["is_drug_review_workflow"]`

## 待补内容

- [ ] 每个节点 system prompt 的设计意图走读（为什么诊断要求"逐条对照 ICD-11 + 原文引用"）
- [ ] `_timed_node` 装饰器与日志埋点（event=agent_node_start/complete elapsed=...）
- [ ] 配一张节点执行的实测时序（从 10-e2e-verification 拿数据）

## 面试官可能追问

1. 如果两个节点并发写 messages 会怎样？（reducer 保证合并；本项目流水线是串行的）
2. add_messages 收到相同 id 的消息会怎样？（按 id 更新而非重复追加——历史压缩的重放依赖这一点）
3. 为什么路由用关键词包含而不是结构化输出？（简单意图空间下更稳，失败模式更可控；可讨论 trade-off）
