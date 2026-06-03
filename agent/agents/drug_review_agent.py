"""药物相互作用审查 Agent。
流水线末端节点。对治疗方案中的药物组合进行相互作用风险审查。
"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
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

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        memory_context = state.get("memory_context", "")
        system_prompt = f"""你是一个精神科药物相互作用审查专家 Agent。

任务：审查治疗方案中药物组合的相互作用风险。

工作流程：
1. 从对话历史中提取治疗方案里的所有药物
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

【记忆上下文】: {memory_context}
"""
        inner_agent = create_react_agent(self.llm, self.tools, prompt=system_prompt)
        result = await inner_agent.ainvoke(
            {"messages": state["messages"]})
        final_message = result["messages"][-1]
        # 终端节点，清空 next_agent 表示流程结束
        return {"messages": [final_message], "next_agent": ""}
