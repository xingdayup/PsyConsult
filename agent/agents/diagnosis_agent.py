"""临床诊断 Agent（症状提取 + 鉴别诊断合并）。
第一步完成口语→术语映射和量表推断，第二步做 ICD-11 鉴别诊断。
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
from tools.synonym_tool import query_synonyms


class DiagnosisAgentNode:
    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(dotenv_path)
        from config import get_settings
        self.llm = ChatOpenAI(**get_settings().get_model_config(), temperature=0.1)
        self.tools = [query_synonyms, query_knowledge_graph, query_vector_db]
        self.inner_agent = create_react_agent(self.llm, self.tools)

    def _build_system_prompt(self, memory_context: str) -> str:
        memory_block = f"\n## 历史对话 / 用户偏好\n{memory_context}" if memory_context else ""
        return f"""你是一个精神科临床诊断专家 Agent。请从对话记录中读取患者的症状描述，完成两步任务。

**第一步：症状提取**
- 用 query_synonyms 将口语表达（如"睡不着"）映射为标准术语（如"失眠"）
- 根据症状描述强度推断 PHQ-9 的 9 个条目得分（0-3 分）
- 严重度分级：PHQ-9: 0-4无/5-9轻度/10-14中度/15-19中重度/20-27重度

**第二步：鉴别诊断**
- 用 query_knowledge_graph 一次性搜索与症状匹配的疾病
- 用 query_vector_db 检索前 2 个候选的 ICD-11 诊断标准
- 逐条对照，用 ✅/❌/⚠ 标注

输出格式：
```
## 症状清单
| 症状 | 原文引用 | PHQ-9 |
|------|---------|-------|
| 情绪低落 | "每天都不想动" | 2 |

> PHQ-9 推断总分: XX 分（XX）

## 鉴别诊断

候选 1: [疾病名] (ICD-11: [编码])
  ✅ [标准条目] — "[原文引用]"
  ❌ [标准条目] — 未提及
  满足 M/N 条 → [结论]

候选 2: [疾病名] (ICD-11: [编码])
  ...
```

约束：
- 每项症状必须有 evidence 引用对话原文
- 只输出前 2 个最可能候选，每个不超过 5 行对照
- ⚠️ 你最多调用 2 次工具，之后必须输出最终结果
- 不要编造未提及的症状
{memory_block}"""

    async def __call__(self, state: AgentState) -> Dict[str, Any]:
        writer = get_stream_writer()
        writer({"agent": "differential_diagnosis", "event": "start"})

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
                        writer({"agent": "differential_diagnosis", "chunk": buffer})
                        buffer = ""
                elif hasattr(msg, "tool_calls") and msg.tool_calls:
                    if buffer:
                        writer({"agent": "differential_diagnosis", "chunk": buffer})
                        buffer = ""
                    for tc in msg.tool_calls:
                        writer({"agent": "differential_diagnosis", "event": "tool_call", "tool": tc.get("name", "")})
            elif isinstance(msg, ToolMessage):
                if buffer:
                    writer({"agent": "differential_diagnosis", "chunk": buffer})
                    buffer = ""
                writer({"agent": "differential_diagnosis", "event": "tool_done"})
        if buffer:
            writer({"agent": "differential_diagnosis", "chunk": buffer})

        return {"messages": [AIMessage(content=full_content)]}
