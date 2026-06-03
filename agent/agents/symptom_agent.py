"""症状提取 Agent。"""
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from typing import Dict, Any
from core.workflow.state import AgentState
from tools.vector_tool import query_vector_db
from tools.synonym_tool import query_synonyms


class SymptomAgentNode:
    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(dotenv_path)
        from config import get_settings
        llm_cfg = get_settings().get_model_config()
        self.llm = ChatOpenAI(**llm_cfg, temperature=0.1)
        self.tools = [query_synonyms, query_vector_db]

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        memory_context = state.get("memory_context", "")
        system_prompt = f"""你是一个精神科症状学专家 Agent。

任务：从医生的描述中提取结构化症状清单，并推断 PHQ-9 和 GAD-7 量表分数。

工作流程：
1. 用 query_synonyms 将口语表达（如"睡不着"）映射为标准术语（如"失眠"）
2. 如果描述不清晰，用 query_vector_db 检索 ICD-11 症状定义辅助判断
3. 根据症状描述强度推断 PHQ-9 的 9 个条目和 GAD-7 的 7 个条目得分（0-3 分），然后手动加总计算 total 分数
4. 严重度分级标准：PHQ-9: 0-4 无/5-9 轻度/10-14 中度/15-19 中重度/20-27 重度；GAD-7: 0-4 无/5-9 轻度/10-14 中度/15-21 重度

输出格式（JSON）：
```json
{{
  "symptoms": [
    {{"term": "情绪低落", "icd11": "MB21.0", "evidence": "患者自述...", "phq9_score": 2}}
  ],
  "inferred_scales": {{
    "PHQ-9": {{"scores": [2,0,2,1,0,0,2,0,0], "total": 7, "severity": "轻度"}},
    "GAD-7": null
  }}
}}
```

约束：
- 每项症状必须有 evidence 字段，引用对话原文
- 如果患者信息不足以推断某个条目，填 0
- 不要编造未提及的症状

【记忆上下文】: {memory_context}
"""
        inner_agent = create_react_agent(self.llm, self.tools, prompt=system_prompt)
        result = await inner_agent.ainvoke({"messages": state["messages"]})
        final_message = result["messages"][-1]
        return {"messages": [final_message]}
