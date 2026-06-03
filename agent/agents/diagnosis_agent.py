"""鉴别诊断 Agent。
根据症状列表搜索知识图谱，逐条对照 ICD-11 诊断标准，输出候选疾病排序。
"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from typing import Dict, Any
from core.workflow.state import AgentState
from tools.vector_tool import query_vector_db
from tools.graph_tool import query_knowledge_graph


class DiagnosisAgentNode:
    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(dotenv_path)
        from config import get_settings
        self.llm = ChatOpenAI(**get_settings().get_model_config(), temperature=0.1)
        self.tools = [query_knowledge_graph, query_vector_db]

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        memory_context = state.get("memory_context", "")
        system_prompt = f"""你是一个精神科鉴别诊断专家 Agent。

任务：根据症状列表，通过知识图谱和 ICD-11 标准，输出候选疾病排序列表。

工作流程：
1. 调用 query_knowledge_graph 搜索与症状集合匹配的疾病
2. 调用 query_vector_db 检索每个候选疾病的 ICD-11 诊断标准原文
3. 逐条对照诊断标准，用 ✅（满足）/ ❌（不满足）/ ⚠（信息不足）标注
4. 输出候选疾病列表，按证据强度排序

输出格式（每条候选必须严格按此格式）：
```
候选 N: [疾病名] (ICD-11: [编码])
  ✅ [诊断标准条目] — "[引用对话原文]"
  ❌ [诊断标准条目] — 未提及
  ⚠ [诊断标准条目] — 信息不足，建议补充问询

  满足 [M]/[N] 条核心标准 → [结论]
```

约束：
- 每条诊断标准对照必须引用对话原文或明确写"未提及"
- 不能跳过任何核心标准，必须逐条列出
- 如果信息不足，标注 ⚠ 并给出需要补充问询的具体问题
- 不要编造患者未提及的症状

【记忆上下文】: {memory_context}
"""
        inner_agent = create_react_agent(self.llm, self.tools, prompt=system_prompt)
        result = await inner_agent.ainvoke(
            {"messages": state["messages"]})
        final_message = result["messages"][-1]
        return {"messages": [final_message]}
