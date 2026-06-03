"""临床决策支持系统集成测试。
端到端验证一条完整的鉴别诊断链路。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.workflow.graph_manager import AgentGraphManager
from core.workflow.state import AgentState


async def test_depression_case():
    manager = AgentGraphManager()
    graph = manager.build_graph()

    state: AgentState = {
        "messages": [],
        "user_id": "doctor_001",
        "session_id": "test_depression",
        "memory_context": "",
        "next_agent": "",
        "metadata": {},
    }

    # 测试病例: 典型抑郁发作
    query = "患者近两周情绪低落、失眠、食欲下降，以前喜欢打篮球现在没兴趣了，体重减轻约5公斤"
    print(f"👨‍⚕️ 医生: {query}")
    state["messages"].append(("user", query))

    result = await graph.ainvoke(state)
    print(f"\n🤖 CDS:\n{result['messages'][-1].content}")
    print("\n" + "=" * 60)

    # 查看路由路径
    print(f"路由路径: {state.get('next_agent', 'N/A')}")
    print(f"消息总数: {len(result['messages'])}")


if __name__ == "__main__":
    asyncio.run(test_depression_case())
