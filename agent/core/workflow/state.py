import operator
from typing import Annotated, TypedDict, Any, Sequence
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    """
    LangGraph 全局状态。
    负责在 Router、各个子 Agent 以及 Memory 之间传递信息。
    """
    # 消息记录，使用 operator.add 将新消息追加到列表末尾
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # 决定下一步走向哪个节点的路由标记
    next_agent: str
    
    # 用户信息，用于鉴权和记忆隔离
    user_id: str
    session_id: str
    
    # 注入的记忆信息 (长短期记忆提取出的背景上下文)
    memory_context: str
    
    # 工具调用的附带信息或元数据
    metadata: dict[str, Any]

class AgentOutput(TypedDict):
    """Agent 执行的标准输出格式。"""
    response: str
    tool_calls: list[dict[str, Any]]
    metadata: dict[str, Any]
