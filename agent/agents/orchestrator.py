"""临床路由节点 — 分析用户意图并分发给对应的领域 Agent。"""
import os
from typing import Dict, Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.config import get_stream_writer

from core.workflow.state import AgentState

class OrchestratorAgent:
    """
    中心路由节点 (Orchestrator/Router)
    负责分析用户意图，并将请求分发给相应的专门 Agent。
    """
    def __init__(self):
        dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        load_dotenv(dotenv_path)
        from config import get_settings
        self.llm = ChatOpenAI(**get_settings().get_model_config(), temperature=0.1)

    async def route(self, state: AgentState) -> Dict[str, Any]:
        """
        根据用户的最新输入，决定路由走向。
        """
        # 流式状态：开始路由
        writer = get_stream_writer()
        writer({"agent": "orchestrator", "event": "start"})

        # 获取最新的一条用户消息
        messages = state.get("messages", [])
        if not messages:
            last_message = ""
        else:
            # langgraph 内部有时候会把 tuple 转成实际的 BaseMessage 子类
            last_msg_obj = messages[-1]
            if isinstance(last_msg_obj, tuple):
                last_message = last_msg_obj[1]
            elif hasattr(last_msg_obj, "content"):
                last_message = last_msg_obj.content
            else:
                last_message = str(last_msg_obj)
        memory_context = state.get("memory_context", "")

        memory_block = f"\n【历史对话参考】：\n{memory_context}" if memory_context else ""

        system_prompt = f"""你是一个精神科临床决策支持系统的总路由（Clinical Router）。
你的任务是根据医生的输入，决定将诊疗请求分发给哪个专业的临床 Agent 处理。

当前可用的临床 Agent 有：
1. "differential_diagnosis" : 患者评估与鉴别诊断。负责从自然语言描述中提取症状、做同义词映射、推断量表分数，然后基于 ICD-11 标准做鉴别诊断。
2. "treatment_recommend" : 已有诊断结论，需要检索治疗指南，给出分级治疗建议（一线/二线方案）。
4. "drug_interaction" : 医生输入了治疗方案或药物列表，需要审查药物相互作用风险。

路由细则：
- 医生描述患者症状（如"近两周情绪低落..."）→ differential_diagnosis
- 已有症状清单需要诊断 → differential_diagnosis
- 已有诊断需要治疗方案 → treatment_recommend
- 涉及药物名称或用药方案 → drug_interaction
{memory_block}

请仅输出你要路由到的名称（必须是: differential_diagnosis, treatment_recommend, drug_interaction 中的一个），不要输出任何其他解释性文字。
如果你无法判断，默认输出 differential_diagnosis。
"""

        response = await self.llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=last_message)
        ])

        decision = response.content.strip().lower()
        if "drug" in decision:
            next_node = "drug_interaction"
            state["metadata"]["is_drug_review_workflow"] = True
            print("🧭 [ClinicalRouter] 识别到药物审查意图，路由至: drug_interaction")
        elif "diagnosis" in decision or "differential" in decision:
            next_node = "differential_diagnosis"
            print("🧭 [ClinicalRouter] 识别到鉴别诊断意图，路由至: differential_diagnosis")
        elif "treatment" in decision:
            next_node = "treatment_recommend"
            print("🧭 [ClinicalRouter] 识别到治疗推荐意图，路由至: treatment_recommend")
        else:
            next_node = "differential_diagnosis"
            print("🧭 [ClinicalRouter] 默认路由至: differential_diagnosis")

        return {"next_agent": next_node, "metadata": state.get("metadata", {})}
