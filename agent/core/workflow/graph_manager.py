"""LangGraph 临床决策支持系统图组装器。"""

import asyncio
import logging
import os
import time
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage
from core.workflow.state import AgentState
from agents.orchestrator import OrchestratorAgent
from agents.diagnosis_agent import DiagnosisAgentNode
from agents.treatment_agent import TreatmentAgentNode
from agents.drug_review_agent import DrugReviewAgentNode

logger = logging.getLogger("clinical_cds.agent")


class AgentGraphManager:
    """组装临床多 Agent 编排图。诊断 Agent 内置症状提取步骤。"""

    def __init__(self):
        self.orchestrator = OrchestratorAgent()
        self.diagnosis_node = DiagnosisAgentNode()
        self.treatment_node = TreatmentAgentNode()
        self.drug_review_node = DrugReviewAgentNode()

    def _route_condition(self, state: AgentState) -> str:
        return state.get("next_agent", "differential_diagnosis")

    async def _timed_node(self, node_name: str, node, state: AgentState):
        start = time.perf_counter()
        user_id = state.get("user_id", "")
        session_id = state.get("session_id", "")
        logger.info(
            "event=agent_node_start user_id=%s session_id=%s node=%s",
            user_id,
            session_id,
            node_name,
        )
        try:
            return await node(state)
        finally:
            logger.info(
                "event=agent_node_complete user_id=%s session_id=%s node=%s elapsed=%.3fs",
                user_id,
                session_id,
                node_name,
                time.perf_counter() - start,
            )

    async def _run_orchestrator(self, state: AgentState):
        return await self._timed_node("orchestrator", self.orchestrator.route, state)

    async def _run_diagnosis(self, state: AgentState):
        return await self._timed_node("diagnosis", self.diagnosis_node, state)

    async def _run_treatment(self, state: AgentState):
        return await self._timed_node("treatment", self.treatment_node, state)

    async def _run_drug_review(self, state: AgentState):
        return await self._timed_node("drug_review", self.drug_review_node, state)

    def build_graph(self) -> StateGraph:
        builder = StateGraph(AgentState)

        builder.add_node("orchestrator", self._run_orchestrator)
        builder.add_node("differential_diagnosis", self._run_diagnosis)
        builder.add_node("treatment_recommend", self._run_treatment)
        builder.add_node("drug_interaction", self._run_drug_review)

        builder.add_edge(START, "orchestrator")

        builder.add_conditional_edges(
            "orchestrator", self._route_condition,
            {"differential_diagnosis": "differential_diagnosis",
             "treatment_recommend": "treatment_recommend",
             "drug_interaction": "drug_interaction"})

        # 3 步流水线（诊断内置症状提取 → 治疗 → 药物审查）
        builder.add_edge("differential_diagnosis", "treatment_recommend")
        builder.add_edge("treatment_recommend", "drug_interaction")
        builder.add_edge("drug_interaction", END)

        return builder.compile()


async def test_graph():
    """临床链路集成测试。"""
    manager = AgentGraphManager()
    graph = manager.build_graph()

    print("🏥 临床决策支持系统 (Multi-Agent 编排模式)")
    print("=" * 60)

    state: AgentState = {
        "messages": [],
        "user_id": "doctor_001",
        "session_id": "test_session_1",
        "memory_context": "",
        "next_agent": "",
        "metadata": {},
    }

    # 测试病例: 典型抑郁发作
    query = "患者近两周情绪低落、失眠、食欲下降，以前喜欢打篮球现在没兴趣了"
    print(f"👨‍⚕️ 医生: {query}")
    state["messages"].append(HumanMessage(content=query))

    result = await graph.ainvoke(state)
    print(f"\n🤖 CDS:\n{result['messages'][-1].content}")


if __name__ == "__main__":
    asyncio.run(test_graph())
