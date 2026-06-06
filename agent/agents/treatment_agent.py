"""治疗推荐 Agent。
根据鉴别诊断结果，检索中国精神科指南和药物知识图谱，
输出分级的治疗方案建议。
"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent
from langgraph.config import get_stream_writer
from typing import Dict, Any
from core.workflow.state import AgentState
from tools.vector_tool import query_vector_db
from tools.graph_tool import query_knowledge_graph


class TreatmentAgentNode:
    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(dotenv_path)
        from config import get_settings
        self.llm = ChatOpenAI(**get_settings().get_model_config(), temperature=0.1)
        self.tools = [query_vector_db, query_knowledge_graph]
        self.inner_agent = create_react_agent(self.llm, self.tools)

    def _build_system_prompt(self, memory_context: str) -> str:
        memory_block = f"\n## 历史对话 / 用户偏好\n{memory_context}" if memory_context else ""
        return f"""你是一个精神科治疗推荐专家 Agent。

任务：从对话记录中读取鉴别诊断结论，基于中国精神科指南和药物知识图谱，给出分级治疗建议。

工作流程：
1. 阅读对话历史中的诊断结论（上一步鉴别诊断 Agent 的输出）
2. 调用 query_vector_db 检索相关中国精神科防治指南的治疗路径
3. 调用 query_knowledge_graph 搜索一线和二线药物及其详细信息
4. 输出分级治疗方案

输出格式：
```
治疗方案

诊断: [诊断名称] (ICD-11: [编码])

【一线方案】
- [药物名] [类别] [起始剂量] → [目标剂量]
  依据: [指南来源]

【二线方案】（一线无效或不耐受时）
- [药物名] [类别] ...
  依据: [指南来源]

【非药物治疗】
- [治疗方式]
  依据: [指南来源]

【注意事项】
- [具体注意事项]
```

约束：
- 药物名称必须是 query_knowledge_graph 实际返回的，不能编造
- 所有推荐依据必须标明指南来源
- 如果不确定，明确标注"建议参考最新临床指南"
- ⚠️ 工具调用限制：你最多调用 2 次工具，之后必须输出最终方案
{memory_block}"""

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        writer = get_stream_writer()
        writer({"agent": "treatment_recommend", "event": "start"})

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
                        writer({"agent": "treatment_recommend", "chunk": buffer})
                        buffer = ""
                elif hasattr(msg, "tool_calls") and msg.tool_calls:
                    if buffer:
                        writer({"agent": "treatment_recommend", "chunk": buffer})
                        buffer = ""
                    for tc in msg.tool_calls:
                        writer({"agent": "treatment_recommend", "event": "tool_call", "tool": tc.get("name", "")})
            elif isinstance(msg, ToolMessage):
                if buffer:
                    writer({"agent": "treatment_recommend", "chunk": buffer})
                    buffer = ""
                writer({"agent": "treatment_recommend", "event": "tool_done"})
        if buffer:
            writer({"agent": "treatment_recommend", "chunk": buffer})

        return {"messages": [AIMessage(content=full_content)]}
