# Agent 多智能体系统

## 入口文件

Agent CLI 入口是：

```text
agent/main.py
```

它支持两种模式：

- 交互模式：`python main.py`
- 单次查询：`python main.py --query "..."`

主入口做的事情：

1. 配置日志。
2. 读取 `agent/.env`。
3. 初始化 `MemoryManager`。
4. 构建 `AgentGraphManager`。
5. 从 Redis/Milvus 提取记忆上下文。
6. 调用 LangGraph。
7. 保存短期对话记忆。
8. 周期性或会话结束时提取长期记忆。

## 全局状态 `AgentState`

定义位置：

```text
agent/core/workflow/state.py
```

字段：

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    next_agent: str
    user_id: str
    session_id: str
    memory_context: str
    metadata: dict[str, Any]
```

含义：

- `messages`：对话消息，由 LangGraph 在节点之间传递和追加。
- `next_agent`：Router 决定的下一节点名称。
- `user_id`：用户标识，用于记忆隔离。
- `session_id`：会话标识，用于短期记忆隔离。
- `memory_context`：从 Redis 和 Milvus 提取出的上下文文本。
- `metadata`：流程元数据，例如是否为药物审查工作流。

## 图结构

定义位置：

```text
agent/core/workflow/graph_manager.py
```

节点：

- `orchestrator`
- `symptom_extraction`
- `differential_diagnosis`
- `treatment_recommend`
- `drug_interaction`

图结构：

```text
START
  -> orchestrator
  -> conditional route:
       symptom_extraction
       differential_diagnosis
       treatment_recommend
       drug_interaction

symptom_extraction
  -> differential_diagnosis
  -> treatment_recommend
  -> drug_interaction
  -> END
```

注意：Router 可以决定入口，但当前实现中后续节点会继续自动串行执行。例如 Router 进入 `symptom_extraction` 后，流程仍会继续到诊断、治疗和药物审查。

## Router Agent

定义位置：

```text
agent/agents/orchestrator.py
```

职责：

- 分析医生输入。
- 判断请求类型。
- 输出下一个节点名称。

可路由目标：

- `symptom_extraction`：自然语言症状描述。
- `differential_diagnosis`：已有症状清单，需要诊断。
- `treatment_recommend`：已有诊断，需要治疗方案。
- `drug_interaction`：输入药物或治疗方案，需要相互作用审查。

Router 使用 `ChatOpenAI`，连接 DashScope OpenAI 兼容接口：

```python
ChatOpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    model=os.getenv("MODEL", "qwen-plus"),
    base_url=os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    temperature=0.1,
)
```

## 症状提取 Agent

定义位置：

```text
agent/agents/symptom_agent.py
```

职责：

- 将医生自然语言描述转成结构化症状清单。
- 将口语症状映射为 ICD-11 标准术语。
- 推断 PHQ-9 和 GAD-7 条目得分。
- 输出 JSON 风格结构。

工具：

- `query_synonyms`
- `query_vector_db`

典型输出结构：

```json
{
  "symptoms": [
    {
      "term": "情绪低落",
      "icd11": "MB21.0",
      "evidence": "患者自述...",
      "phq9_score": 2
    }
  ],
  "inferred_scales": {
    "PHQ-9": {
      "scores": [2, 0, 2, 1, 0, 0, 2, 0, 0],
      "total": 7,
      "severity": "轻度"
    },
    "GAD-7": null
  }
}
```

## 鉴别诊断 Agent

定义位置：

```text
agent/agents/diagnosis_agent.py
```

职责：

- 根据症状列表查询知识图谱。
- 检索 ICD-11 诊断标准。
- 对候选疾病逐条对照核心标准。
- 输出候选疾病排序。

工具：

- `query_knowledge_graph`
- `query_vector_db`

输出要求：

- 每条标准用满足、不满足或信息不足标注。
- 必须引用对话原文或说明未提及。
- 信息不足时给出补充问询建议。

## 治疗推荐 Agent

定义位置：

```text
agent/agents/treatment_agent.py
```

职责：

- 读取前序诊断结论。
- 检索中国精神科指南和治疗路径。
- 查询知识图谱中的一线、二线药物和方案。
- 输出分级治疗建议。

工具：

- `query_vector_db`
- `query_knowledge_graph`

输出结构：

```text
治疗方案

诊断: [诊断名称] (ICD-11: [编码])

【一线方案】
- [药物名] [类别] [起始剂量] -> [目标剂量]
  依据: [指南来源]

【二线方案】
- ...

【非药物治疗】
- ...

【注意事项】
- ...
```

## 药物审查 Agent

定义位置：

```text
agent/agents/drug_review_agent.py
```

职责：

- 从治疗方案或医生输入中提取药物。
- 查询药物之间的 `INTERACTS_WITH` 关系。
- 输出相互作用矩阵。
- 给出禁忌、谨慎、安全评级。

工具：

- `query_knowledge_graph`

风险等级：

- 禁忌：严禁联用。
- 谨慎：可联用但需密切监测。
- 安全：无已知相互作用。

## 工具层

### 症状同义词工具

文件：

```text
agent/tools/synonym_tool.py
agent/config/symptom_synonyms.json
```

功能：

- 精确匹配口语表达。
- 部分匹配关键词。
- 返回标准术语、ICD-11 编码等 JSON 信息。

### 向量检索工具

文件：

```text
agent/tools/vector_tool.py
```

功能：

- 使用 DashScope `text-embedding-v2`。
- 连接 Milvus。
- 查询 Collection：`cloud_product_docs`。
- 返回 top 3 文档片段。

虽然集合名是 `cloud_product_docs`，当前项目实际用于存储精神科指南和诊断标准片段。

### 知识图谱工具

文件：

```text
agent/tools/graph_tool.py
```

功能：

- 连接 Neo4j。
- 使用 `GraphCypherQAChain` 让 LLM 生成 Cypher。
- 查询疾病、症状、药物、副作用、治疗方案等节点和关系。
- 当 Cypher 查询失败时，尝试关键词兜底检索。

图谱建议节点：

- `Disease`
- `Symptom`
- `Drug`
- `SideEffect`
- `Treatment`

图谱建议关系：

- `HAS_SYMPTOM`
- `FIRST_LINE`
- `SECOND_LINE`
- `CAUSES`
- `INTERACTS_WITH`
- `USES_DRUG`

## 记忆系统

统一入口：

```text
agent/core/memory/memory_manager.py
```

短期记忆：

```text
agent/core/memory/short_term.py
```

- 后端：Redis。
- key 格式：`memory:short:{user_id}:{session_id}`。
- 默认 TTL：1800 秒。
- 超过 10 条消息后保留系统消息和最近 6 条非系统消息。
- Redis 不可用时返回空列表，不中断主流程。

长期记忆：

```text
agent/core/memory/long_term.py
```

- 后端：Milvus。
- Collection：`long_term_memory`。
- embedding 维度：1536。
- 按 `user_id` 过滤。
- 存储用户偏好、临床关键信息、诊疗背景。

偏好提取：

```text
agent/core/memory/preference_extractor.py
```

- 使用 LLM 分析对话。
- 提取格式类似：`主诉: 情绪低落、失眠 2 周`。
- 和已有偏好去重。
- 会话结束或后台周期任务中写入 Milvus。

## MCP 配置

配置文件：

```text
agent/config/mcp_servers.json
```

当前配置：

```json
{
  "mcpServers": {
    "clinical_tools": {
      "command": "python",
      "args": ["-m", "mcp_servers.clinical_tools"],
      "cwd": "agent",
      "transport": "stdio"
    }
  }
}
```

MCP 服务文件：

```text
agent/mcp_servers/clinical_tools.py
```

该配置表示从 `agent/` 目录启动 Python 模块 `mcp_servers.clinical_tools`，通过 stdio 传输。

## 运行示例

```bash
cd agent
python main.py --query "患者近两周情绪低落、失眠、食欲下降，以前喜欢的活动现在也没兴趣了"
```

如果基础服务正常，输出中会显示：

- Redis 短期记忆是否连接。
- Milvus 长期记忆是否连接。
- Agent 处理结果。

## 扩展一个新 Agent 的思路

1. 在 `agent/agents/` 新建节点类，实现 `async __call__(self, state: AgentState)`。
2. 在节点内部定义系统提示词和工具列表。
3. 在 `AgentGraphManager.__init__()` 中实例化。
4. 在 `build_graph()` 中 `add_node()`。
5. 根据需要修改 Router 提示词和条件边。
6. 增加脚本式测试，验证路由和输出格式。
