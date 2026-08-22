"""LangGraph 临床决策支持系统图组装器。

支持传入 LangGraph Checkpointer（如 AsyncRedisSaver）实现会话级状态持久化：
以 ``session_id`` 为 ``thread_id``，消息历史、中间推理结果与工具调用上下文
跨轮次保留。启用 checkpointer 时，图入口增加历史压缩节点（短期窗口 +
历史摘要）控制上下文长度。
"""

import logging
import time
from langchain_core.messages import BaseMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI

from config import get_settings
from core.workflow.state import AgentState
from agents.orchestrator import OrchestratorAgent
from agents.diagnosis_agent import DiagnosisAgentNode
from agents.treatment_agent import TreatmentAgentNode
from agents.drug_review_agent import DrugReviewAgentNode

logger = logging.getLogger("clinical_cds.agent")

# 历史压缩：消息总数超过阈值时触发，保留最近窗口，其余摘要为一条 SystemMessage
HISTORY_COMPRESS_THRESHOLD = 16
HISTORY_KEEP_RECENT = 8

_SUMMARY_PROMPT = """\
请将以下医患对话历史压缩为一段临床摘要，供后续诊疗推理参考。
必须保留：主诉与症状、持续时间、量表分数、诊断结论、用药方案、
既往工具检索到的关键临床知识、医生的偏好与要求。
直接输出摘要正文，不要任何前缀或解释。

对话历史：
{conversation}"""


class AgentGraphManager:
    """组装临床多 Agent 编排图。诊断 Agent 内置症状提取步骤。"""

    def __init__(self):
        self.orchestrator = OrchestratorAgent()
        self.diagnosis_node = DiagnosisAgentNode()
        self.treatment_node = TreatmentAgentNode()
        self.drug_review_node = DrugReviewAgentNode()
        self._summary_llm = ChatOpenAI(
            **get_settings().get_model_config(), temperature=0
        )

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
        return await self._timed_node("drug_interaction", self.drug_review_node, state)

    async def _compress_history(self, state: AgentState):
        """历史压缩节点：超出窗口的消息摘要为一条 SystemMessage。

        无 checkpointer 时图不会累积历史，此节点不会加入图中；
        消息缺少 id 或 LLM 失败时跳过压缩（优雅降级）。
        """
        messages = list(state.get("messages", []))
        if len(messages) <= HISTORY_COMPRESS_THRESHOLD:
            return {}

        if any(m.id is None for m in messages):
            logger.warning("History compression skipped: message without id")
            return {}

        keep = messages[-HISTORY_KEEP_RECENT:]
        old = messages[:-HISTORY_KEEP_RECENT]
        conversation = "\n".join(
            f"{self._role_of(m)}: {m.content}" for m in old if m.content
        )
        if not conversation.strip():
            return {}

        try:
            response = await self._summary_llm.ainvoke(
                [HumanMessage(content=_SUMMARY_PROMPT.format(conversation=conversation))]
            )
            summary = response.content.strip()
        except Exception as exc:
            logger.warning("History compression failed, keeping full history: %s", exc)
            return {}

        logger.info(
            "event=history_compressed old=%d kept=%d summary_chars=%d",
            len(old), len(keep), len(summary),
        )
        # 先全部移除再按 [摘要, 保留窗口] 顺序重放，实现可控排序
        return {
            "messages": [RemoveMessage(id=m.id) for m in messages]
            + [SystemMessage(content=f"【历史会话摘要】\n{summary}")]
            + keep
        }

    @staticmethod
    def _role_of(message: BaseMessage) -> str:
        if isinstance(message, SystemMessage):
            return "System"
        return "User" if isinstance(message, HumanMessage) else "Assistant"

    def build_graph(self, checkpointer=None) -> StateGraph:
        builder = StateGraph(AgentState)

        builder.add_node("orchestrator", self._run_orchestrator)
        builder.add_node("differential_diagnosis", self._run_diagnosis)
        builder.add_node("treatment_recommend", self._run_treatment)
        builder.add_node("drug_interaction", self._run_drug_review)
        if checkpointer is not None:
            builder.add_node("history_compression", self._compress_history)

        if checkpointer is not None:
            builder.add_edge(START, "history_compression")
            builder.add_edge("history_compression", "orchestrator")
        else:
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

        return builder.compile(checkpointer=checkpointer)


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
    import asyncio

    asyncio.run(test_graph())
