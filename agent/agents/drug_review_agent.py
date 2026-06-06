"""药物相互作用审查 Agent。
流水线末端节点。对治疗方案中的药物组合进行相互作用风险审查。
"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent
from langgraph.config import get_stream_writer
from typing import Dict, Any
from core.workflow.state import AgentState
from tools.graph_tool import query_knowledge_graph


class DrugReviewAgentNode:
    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(dotenv_path)
        from config import get_settings
        self.llm = ChatOpenAI(**get_settings().get_model_config(), temperature=0.1)
        self.tools = [query_knowledge_graph]
        self.inner_agent = create_react_agent(self.llm, self.tools)

    def _build_system_prompt(self, memory_context: str) -> str:
        memory_block = f"\n## 历史对话 / 用户偏好\n{memory_context}" if memory_context else ""
        return f"""你是一个精神科药物相互作用审查专家 Agent。

任务：从对话记录中读取治疗方案和药物清单，审查药物组合的相互作用风险。

工作流程：
1. 从对话历史中提取治疗方案里的所有药物（上一步治疗推荐 Agent 的输出）
2. 调用 query_knowledge_graph 查询每对药物之间的 INTERACTS_WITH 关系
3. 对于没有直接关系的药物对，根据药理知识推理潜在风险
4. 输出相互作用矩阵和风险评级

输出格式：
```
药物相互作用审查报告

审查药物: [药物清单]

【相互作用矩阵】
| 药物 A | 药物 B | 风险等级 | 说明 |
|--------|--------|----------|------|
| 舍曲林 | 帕罗西汀 | 🔴 禁忌 | 两种 SSRI 联用增加 5-HT 综合征风险 |
| ... | ... | ... | ... |

【风险汇总】
- 🔴 禁忌: [N] 对
- 🟡 谨慎: [N] 对
- 🟢 安全: [N] 对

【建议】
- [具体建议]
```

风险等级定义：
- 🔴 禁忌: 严禁联用
- 🟡 谨慎: 可联用但需密切监测
- 🟢 安全: 无已知相互作用

约束：
- 药物名称必须来自对话历史中的实际处方
- 相互作用信息必须是 query_knowledge_graph 实际返回的
- 如果图谱中查不到某对药物的关系，标注"未在知识图谱中找到直接相互作用数据"
- ⚠️ 工具调用限制：你最多调用 2 次工具，之后必须输出最终审查报告
{memory_block}"""

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        writer = get_stream_writer()
        writer({"agent": "drug_interaction", "event": "start"})

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
                        writer({"agent": "drug_interaction", "chunk": buffer})
                        buffer = ""
                elif hasattr(msg, "tool_calls") and msg.tool_calls:
                    if buffer:
                        writer({"agent": "drug_interaction", "chunk": buffer})
                        buffer = ""
                    for tc in msg.tool_calls:
                        writer({"agent": "drug_interaction", "event": "tool_call", "tool": tc.get("name", "")})
            elif isinstance(msg, ToolMessage):
                if buffer:
                    writer({"agent": "drug_interaction", "chunk": buffer})
                    buffer = ""
                writer({"agent": "drug_interaction", "event": "tool_done"})
        if buffer:
            writer({"agent": "drug_interaction", "chunk": buffer})

        return {"messages": [AIMessage(content=full_content)], "next_agent": ""}
