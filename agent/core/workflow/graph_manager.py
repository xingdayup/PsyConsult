"""LangGraph 临床决策支持系统图组装器。"""

import asyncio
import os
import time
from langgraph.graph import StateGraph, START, END
from core.workflow.state import AgentState
from agents.orchestrator import OrchestratorAgent
from agents.symptom_agent import SymptomAgentNode
from agents.diagnosis_agent import DiagnosisAgentNode
from agents.treatment_agent import TreatmentAgentNode
from agents.drug_review_agent import DrugReviewAgentNode


class AgentGraphManager:
    """组装临床多 Agent 编排图。支持 3 级流水线条件边自动衔接。"""

    def __init__(self):
        self.orchestrator = OrchestratorAgent()
        self.symptom_node = SymptomAgentNode()
        self.diagnosis_node = DiagnosisAgentNode()
        self.treatment_node = TreatmentAgentNode()
        self.drug_review_node = DrugReviewAgentNode()

    def _route_condition(self, state: AgentState) -> str:
        return state.get("next_agent", "symptom_extraction")

    @staticmethod
    def _env_flag(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _latest_user_text(state: AgentState) -> str:
        messages = state.get("messages", [])
        for message in reversed(messages):
            if isinstance(message, tuple) and len(message) >= 2 and message[0] == "user":
                return str(message[1])
            if getattr(message, "type", None) == "human":
                return str(getattr(message, "content", ""))
        return ""

    @classmethod
    def _has_treatment_intent(cls, state: AgentState) -> bool:
        text = cls._latest_user_text(state)
        keywords = ("治疗", "用药", "药物", "方案", "一线", "二线", "剂量", "处方")
        return any(keyword in text for keyword in keywords)

    async def _timed_node(self, node_name: str, node, state: AgentState):
        start = time.perf_counter()
        print(f"⏱️ [agent:{node_name}] 开始")
        try:
            return await node(state)
        finally:
            print(f"⏱️ [agent:{node_name}] 结束: {time.perf_counter() - start:.2f}s")

    async def _run_orchestrator(self, state: AgentState):
        return await self._timed_node("orchestrator", self.orchestrator.route, state)

    async def _run_symptom(self, state: AgentState):
        return await self._timed_node("symptom", self.symptom_node, state)

    async def _run_diagnosis(self, state: AgentState):
        return await self._timed_node("diagnosis", self.diagnosis_node, state)

    async def _run_treatment(self, state: AgentState):
        return await self._timed_node("treatment", self.treatment_node, state)

    async def _run_drug_review(self, state: AgentState):
        return await self._timed_node("drug_review", self.drug_review_node, state)

    def _symptom_post_condition(self, state: AgentState) -> str:
        """症状提取完成后自动进入鉴别诊断。"""
        return "differential_diagnosis"

    def _diagnosis_post_condition(self, state: AgentState) -> str:
        """诊断完成后按需进入治疗推荐。"""
        if self._env_flag("ENABLE_AUTO_TREATMENT_PIPELINE", False):
            return "treatment_recommend"
        if self._has_treatment_intent(state):
            return "treatment_recommend"
        print("⚡ [ClinicalGraph] 快速模式：诊断完成后结束；如需自动治疗推荐，设置 ENABLE_AUTO_TREATMENT_PIPELINE=true")
        return "end"

    def _treatment_post_condition(self, state: AgentState) -> str:
        """治疗推荐后，如果涉及多药联用则进入药物审查。"""
        if state.get("metadata", {}).get("is_drug_review_workflow"):
            return "drug_interaction"
        return "end"

    def build_graph(self) -> StateGraph:
        builder = StateGraph(AgentState)

        # 添加节点
        builder.add_node("orchestrator", self._run_orchestrator)
        builder.add_node("symptom_extraction", self._run_symptom)
        builder.add_node("differential_diagnosis", self._run_diagnosis)
        builder.add_node("treatment_recommend", self._run_treatment)
        builder.add_node("drug_interaction", self._run_drug_review)

        # START → Orchestrator
        builder.add_edge(START, "orchestrator")

        # Orchestrator → 症状提取（默认入口）
        builder.add_conditional_edges(
            "orchestrator",
            self._route_condition,
            {
                "symptom_extraction": "symptom_extraction",
                "differential_diagnosis": "differential_diagnosis",
                "treatment_recommend": "treatment_recommend",
                "drug_interaction": "drug_interaction",
            }
        )

        # 3 级自动流水线（固定顺序，不做条件跳转）
        builder.add_edge("symptom_extraction", "differential_diagnosis")
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
    state["messages"].append(("user", query))

    result = await graph.ainvoke(state)
    print(f"\n🤖 CDS:\n{result['messages'][-1].content}")


if __name__ == "__main__":
    asyncio.run(test_graph())
