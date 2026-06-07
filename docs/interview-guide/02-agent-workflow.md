# 02. Agent 工作流

## 模块解决的问题

精神科辅助决策不是单一步骤。系统把医生输入拆成临床流程：

1. 路由判断：这是诊断、治疗，还是药物审查？
2. 临床评估与鉴别诊断：抽取症状，做 ICD-11 标准对照。
3. 治疗推荐：结合诊断结论和指南，给出分级方案。
4. 药物审查：检查药物相互作用和风险。

这样做的好处是职责清晰、Prompt 更可控、每一步都能记录耗时和流式状态。

## LangGraph 编排

核心文件：`agent/core/workflow/graph_manager.py`

```python
builder = StateGraph(AgentState)

builder.add_node("orchestrator", self._run_orchestrator)
builder.add_node("differential_diagnosis", self._run_diagnosis)
builder.add_node("treatment_recommend", self._run_treatment)
builder.add_node("drug_interaction", self._run_drug_review)

builder.add_edge(START, "orchestrator")
builder.add_conditional_edges(
    "orchestrator",
    self._route_condition,
    {
        "differential_diagnosis": "differential_diagnosis",
        "treatment_recommend": "treatment_recommend",
        "drug_interaction": "drug_interaction",
    },
)
builder.add_edge("differential_diagnosis", "treatment_recommend")
builder.add_edge("treatment_recommend", "drug_interaction")
builder.add_edge("drug_interaction", END)
```

面试讲法：  
Orchestrator 先判断用户意图，再进入对应临床 Agent。当前诊断链路会继续串到治疗推荐和药物审查，保证初诊问题能输出完整闭环。

## AgentState

核心文件：`agent/core/workflow/state.py`

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    next_agent: str
    user_id: str
    session_id: str
    memory_context: str
    metadata: dict[str, Any]
```

面试讲法：  
`messages` 使用 LangGraph 的 `add_messages` reducer，能够把新消息追加到历史里，并保持 LangChain 消息类型一致。`user_id` 和 `session_id` 用于记忆隔离，`memory_context` 用于把 Redis/Milvus 检索到的上下文注入 Prompt。

## 各 Agent 职责

| Agent | 节点名 | 主要职责 | 工具 |
|---|---|---|---|
| Orchestrator | `orchestrator` | 判断请求类型，决定下一步 | LLM 路由 |
| Diagnosis | `differential_diagnosis` | 症状抽取、PHQ-9 推断、ICD-11 鉴别诊断 | 同义词、Neo4j、Milvus |
| Treatment | `treatment_recommend` | 基于诊断结论和指南给治疗建议 | Milvus、Neo4j |
| Drug Review | `drug_interaction` | 审查治疗方案中的药物相互作用 | Neo4j |

## 节点耗时日志

```python
async def _timed_node(self, node_name: str, node, state: AgentState):
    start = time.perf_counter()
    try:
        return await node(state)
    finally:
        logger.info(
            "event=agent_node_complete ... node=%s elapsed=%.3fs",
            node_name,
            time.perf_counter() - start,
        )
```

面试讲法：  
这不是只做功能 Demo，我还加了每个节点的耗时日志。之前线上出现“20 秒才开始回答”的问题，就是通过请求级日志和节点耗时定位到首字节和工具调用等待的。

## 面试 Q&A

**Q：为什么不用一个 Agent 全部完成？**  
A：一个 Agent 能跑通 Demo，但输出不稳定，Prompt 也容易过长。拆成多个 Agent 后，每个 Agent 的任务、工具和输出格式都更明确，也更符合临床流程。

**Q：为什么先有 Orchestrator？**  
A：医生输入可能是症状、诊断、治疗方案或药物列表。Orchestrator 可以把不同类型的问题分发给合适的 Agent，避免每次都走完整链路。

**Q：当前工作流有什么不足？**  
A：现在链路偏原型，诊断后默认继续治疗和药物审查。生产系统应根据用户意图和医生确认来决定是否继续后续节点，并增加更严格的临床安全边界。

## 截图建议

- 截 `AgentGraphManager.build_graph()`，重点框出 `add_node`、`add_conditional_edges` 和三步流水线。
- 截 `AgentState`，说明消息、用户、会话和记忆上下文如何在节点间传递。
- 截 `_timed_node()`，说明你做了耗时可观测性。

