# 01 - Agent 流水线

## 为什么用多 Agent？

临床推理有天然的分阶段特征。一个医生看病的流程是：

```
问诊 → 诊断 → 开药 → 审方
```

每个阶段用的知识不同——问诊需要症状学知识，诊断需要 ICD-11 标准，开药需要治疗指南，审方需要药物相互作用数据库。如果把这些全塞进一个大提示词，LLM 会混淆各阶段的职责。

所以拆成 4 个 Agent，各管一段。前一个的输出是后一个的输入，串成固定流水线。

## 4 个 Agent 一览

| Agent | 文件 | 做什么 | 用的工具 |
|-------|------|--------|----------|
| 症状提取 | `symptom_agent.py` | 口语→术语 + 量表推断 | `query_synonyms` + `query_vector_db` |
| 鉴别诊断 | `diagnosis_agent.py` | 症状→疾病 + ICD-11 逐条对照 | `query_knowledge_graph` + `query_vector_db` |
| 治疗推荐 | `treatment_agent.py` | 诊断→一线/二线方案 | `query_vector_db` + `query_knowledge_graph` |
| 药物审查 | `drug_review_agent.py` | 药物组合→相互作用风险 | `query_knowledge_graph` |

全部 `temperature=0.1`——临床决策不能有随机性。

## 流水线怎么串的

`core/workflow/graph_manager.py` 里用 LangGraph 的顺序边：

```python
# 固定顺序，没有分支
builder.add_edge("symptom_extraction", "differential_diagnosis")
builder.add_edge("differential_diagnosis", "treatment_recommend")
builder.add_edge("treatment_recommend", "drug_interaction")
builder.add_edge("drug_interaction", END)
```

每步执行完自动进入下一步，不需要任何条件判断。这和临床推理的自然流程一致——不可能跳过症状直接诊断，也不可能跳过诊断直接开药。

## 全局状态

所有 Agent 共享同一个 `AgentState`（`core/workflow/state.py`）：

```python
class AgentState(TypedDict):
    messages: list        # 对话历史，自动追加
    next_agent: str       # 路由标记（Orchestrator 写，图引擎读）
    user_id: str          # 医生 ID
    session_id: str       # 诊疗会话 ID
    memory_context: str   # 注入的记忆背景（Redis 历史 + Milvus 画像）
    metadata: dict        # 跨 Agent 传递的临时数据
```

`messages` 字段用了 `operator.add`，Agent 节点返回新消息时自动追加到历史末尾，不需要手动拼接。

## 各 Agent 怎么工作的

所有 Agent 遵循相同的代码结构——这是有意设计的：

```python
class XxxAgentNode:
    def __init__(self):
        self.llm = ChatOpenAI(...)    # 统一用 DashScope Qwen-Plus
        self.tools = [...]            # 每个 Agent 绑不同的工具

    async def __call__(self, state: AgentState) -> dict:
        # 1. 构造系统提示词（f-string 注入 memory_context）
        system_prompt = f"""你是 XXX 专家...{memory_context}..."""

        # 2. 创建 ReAct Agent（LLM 可以调用工具、做多步推理）
        inner_agent = create_react_agent(self.llm, self.tools, prompt=system_prompt)

        # 3. 传入完整对话历史执行
        result = await inner_agent.ainvoke({"messages": state["messages"]})

        # 4. 只返回新产生的 AI 回复
        return {"messages": [result["messages"][-1]]}
```

## 症状提取 Agent

**输入示例**："患者近两周情绪低落、失眠，以前喜欢打篮球现在没兴趣了"

**做什么**：

1. 用 `query_synonyms` 把口语映射成标准术语——"睡不着"→"失眠(ICD-11: MB21.0)"
2. 根据描述强度推断 PHQ-9 各条目分数（"每天都不想动"→2分，"凌晨醒"→2分）
3. 加总计算总分和严重度分级

**输出**：结构化症状清单 + 推断的量表分数

```json
{
  "symptoms": [
    {"term": "情绪低落", "icd11": "MB21.0", "evidence": "每天都不想动", "phq9_score": 2},
    {"term": "失眠", "icd11": "MB21.0", "evidence": "凌晨醒", "phq9_score": 2}
  ],
  "inferred_scales": {
    "PHQ-9": {"total": 14, "severity": "中重度"}
  }
}
```

## 鉴别诊断 Agent

**核心约束**：必须逐条对照 ICD-11 标准，用 ✅/❌ 标注每条是否满足。不能只输出一个结论，必须让医生能验证。

**工作流程**：

1. 从对话历史中提取症状清单
2. 用 `query_knowledge_graph` 搜索与症状匹配的疾病
3. 用 `query_vector_db` 检索 ICD-11 诊断标准原文
4. 逐条对照输出

**输出示例**：

```
候选 1: 抑郁发作 (ICD-11: 6A70)
  ✅ 情绪低落   — "每天都不想动"
  ✅ 兴趣减退   — "以前喜欢打篮球现在没兴趣"
  ✅ 睡眠障碍   — "凌晨三四点醒"
  ❌ 自责自罪   — 未提及
  满足 3/5 核心症状 → 符合 ICD-11

候选 2: 双相障碍 II 型 (ICD-11: 6A61)
  ❌ 轻躁狂史   — 未提及
  不满足核心标准
```

## 治疗推荐 Agent

根据诊断结论，检索中国精神科指南（向量 RAG）和药物知识图谱，分级输出：

- **一线方案**：SSRI（舍曲林/帕罗西汀）等，附剂量和指南出处
- **二线方案**：换药策略或增效方案
- **非药物治疗**：CBT 认知行为治疗等

药物名称必须来自知识图谱实际返回的结果，不能编造。

## 药物审查 Agent

流水线末端。从治疗方案中提取药物，查知识图谱中 `INTERACTS_WITH` 关系：

```
| 药物 A  | 药物 B  | 风险 |
|---------|---------|------|
| 舍曲林  | 帕罗西汀 | 🔴 禁忌（5-HT 综合征） |
```

返回 `next_agent: ""` 标记流程结束。

## Orchestrator 路由

`agents/orchestrator.py` 是入口路由器。LLM 分析医生输入，输出一个路由目标名称：

| 医生在做什么 | 路由到 |
|-------------|--------|
| 描述患者症状 | `symptom_extraction` |
| 拿着症状清单要诊断 | `differential_diagnosis` |
| 已有诊断，要治疗方案 | `treatment_recommend` |
| 问药物相互作用 | `drug_interaction` |

大部分请求路由到 `symptom_extraction`，然后自动走完完整流水线。

## 下一步

- 知识图谱：→ `02-Knowledge-Graph.md`
- 检索工具：→ `03-RAG-and-Tools.md`
