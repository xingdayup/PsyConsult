# 03. Prompt 与工具调用

## 模块解决的问题

LLM 直接生成临床建议风险较高，容易出现幻觉、格式不稳定、工具调用不受控。项目的 Prompt 设计重点是：

- 明确角色：每个 Agent 是一个临床子任务专家。
- 明确输入来源：从对话记录读取，不因为记忆为空误判无输入。
- 明确工具：什么时候调用 Milvus、Neo4j、同义词。
- 明确输出格式：表格、分级治疗方案、药物相互作用矩阵。
- 明确约束：不能编造症状、药物必须来自工具结果、工具调用次数限制。

## Orchestrator 路由 Prompt

核心文件：`agent/agents/orchestrator.py`

精选片段：

```python
system_prompt = f"""你是一个精神科临床决策支持系统的总路由（Clinical Router）。
你的任务是根据医生的输入，决定将诊疗请求分发给哪个专业的临床 Agent 处理。

当前可用的临床 Agent 有：
1. "differential_diagnosis" : 患者评估与鉴别诊断。
2. "treatment_recommend" : 已有诊断结论，需要检索治疗指南。
4. "drug_interaction" : 医生输入了治疗方案或药物列表，需要审查药物相互作用风险。

请仅输出你要路由到的名称。
如果你无法判断，默认输出 differential_diagnosis。
"""
```

面试讲法：  
路由 Prompt 不要求模型解释原因，只要求输出节点名，降低解析复杂度。代码里再做兜底判断，无法判断时默认进入鉴别诊断。

## Diagnosis Prompt

核心文件：`agent/agents/diagnosis_agent.py`

精选片段：

```python
return f"""你是一个精神科临床诊断专家 Agent。请从对话记录中读取患者的症状描述，完成两步任务。

**第一步：症状提取**
- 用 query_synonyms 将口语表达映射为标准术语
- 根据症状描述强度推断 PHQ-9 条目得分

**第二步：鉴别诊断**
- 用 query_knowledge_graph 搜索与症状匹配的疾病
- 用 query_vector_db 检索前 2 个候选的 ICD-11 诊断标准
- 逐条对照，用 ✅/❌/⚠ 标注

约束：
- 每项症状必须有 evidence 引用对话原文
- 只输出前 2 个最可能候选
- 不要编造未提及的症状
{memory_block}"""
```

面试讲法：  
这个 Prompt 把诊断任务拆成“症状标准化”和“鉴别诊断”两步。工具调用不是开放式的，而是围绕同义词、图谱和诊断标准检索。

## Treatment Prompt

核心文件：`agent/agents/treatment_agent.py`

精选片段：

```python
任务：从对话记录中读取鉴别诊断结论，
基于中国精神科指南和药物知识图谱，给出分级治疗建议。

工作流程：
1. 阅读上一步鉴别诊断 Agent 的输出
2. 调用 query_vector_db 检索治疗路径
3. 调用 query_knowledge_graph 搜索一线和二线药物

约束：
- 药物名称必须是 query_knowledge_graph 实际返回的，不能编造
- 所有推荐依据必须标明指南来源
```

面试讲法：  
治疗推荐 Agent 不直接凭模型记忆开药，而是要求药物和依据来自检索或图谱结果。

## Drug Review Prompt

核心文件：`agent/agents/drug_review_agent.py`

精选片段：

```python
任务：从对话记录中读取治疗方案和药物清单，审查药物组合的相互作用风险。

工作流程：
1. 提取治疗方案里的所有药物
2. 调用 query_knowledge_graph 查询 INTERACTS_WITH 关系
3. 对没有直接关系的药物对，标注图谱中未找到直接数据

输出：相互作用矩阵、风险汇总、建议。
```

面试讲法：  
药物审查强调结构化关系查询，适合用 Neo4j。对于查不到的数据，Prompt 要求明确标注，而不是让模型臆测。

## 工具调用状态

Agent 内部会通过 `get_stream_writer()` 把工具调用状态传给后端：

```python
for tc in msg.tool_calls:
    writer({
        "agent": "differential_diagnosis",
        "event": "tool_call",
        "tool": tc.get("name", ""),
    })
```

面试讲法：  
用户等待工具查询时，前端不会空白等待，而是能看到“正在调用知识库工具”等阶段提示。这是从用户体验角度做的流式优化。

## 面试 Q&A

**Q：你的 Prompt 设计有什么原则？**  
A：我用“角色、任务、工具、输出格式、约束”五部分设计 Prompt。尤其在医疗场景，不能只给角色提示，还要限制工具来源、证据引用和输出结构。

**Q：如何减少幻觉？**  
A：一是要求关键症状有原文 evidence；二是药物和指南依据必须来自工具结果；三是检索不到时明确标注不确定，而不是编造。

**Q：Prompt 中为什么加工具调用次数限制？**  
A：为了控制成本和延迟，也避免 Agent 在工具和模型之间反复循环。当前每个临床子任务最多调用 2 次工具。

## 截图建议

- 截 Orchestrator Prompt，说明路由节点名输出。
- 截 Diagnosis Prompt 中“症状提取、鉴别诊断、约束”三段。
- 截 Treatment Prompt 的“药物必须来自图谱结果”约束。
- 截 Drug Review Prompt 的相互作用矩阵输出格式。

