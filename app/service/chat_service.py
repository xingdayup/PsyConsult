import asyncio
import json
import logging
import sys
import os
import time

# 初始化 Agent 和 Graph
AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from langchain_core.messages import HumanMessage
from core.workflow.graph_manager import AgentGraphManager
from core.memory.memory_manager import MemoryManager
from app.infra.cache import semantic_cache

# Global variables for graph and memory
graph = None
memory = None
logger = logging.getLogger("clinical_cds.chat")

MIN_CLINICAL_QUERY_LENGTH = 4
SHORT_QUERY_RESPONSE = (
    "请输入更完整的临床问题或患者信息，例如症状、持续时间、严重程度、既往用药、"
    "量表分数或需要审查的药物组合。当前输入过短，系统不会进入诊疗推理流程。"
)

async def init_agent_system():
    global graph, memory
    if graph is None:
        logger.info("event=agent_system_init step=graph_start")
        graph_manager = AgentGraphManager()
        graph = graph_manager.build_graph()
        
        logger.info("event=agent_system_init step=memory_start")
        from config import get_settings
        settings = get_settings()
        memory = MemoryManager(
            redis_url=settings.redis_url,
            redis_ttl=settings.redis_ttl,
            milvus_host=settings.milvus_host,
            milvus_port=settings.milvus_port,
            milvus_api_key=settings.milvus_api_key,
            embedding_api_key=settings.get_embedding_api_key(),
        )
        await memory.initialize()
        await semantic_cache.initialize()
        logger.info("event=agent_system_init step=complete")

async def _extract_memory_context(user_id: str, session_id: str, query: str) -> str:
    context_parts = []
    if memory and memory.short_term.available:
        history = await memory.short_term.get_messages(user_id, session_id)
        if history:
            recent_history = history[-10:] if len(history) > 10 else history
            context_parts.append("【近期对话历史】:")
            for msg in recent_history:
                role = "User" if msg["role"] == "user" else "Assistant"
                context_parts.append(f"{role}: {msg['content']}")
    
    if memory and memory.long_term.available:
        prefs = await memory.long_term.retrieve_relevant(user_id, query)
        if prefs:
            context_parts.append("\n【用户长期偏好/背景】:")
            for p in prefs:
                context_parts.append(f"- {p}")
                
    return "\n".join(context_parts)

def _is_insufficient_query(query: str) -> bool:
    normalized = "".join(query.strip().split())
    return len(normalized) < MIN_CLINICAL_QUERY_LENGTH

async def stream_chat(query: str, user_id: str, session_id: str):
    request_start = time.perf_counter()
    last_step = request_start

    def emit_sse(payload: dict, kind: str) -> str:
        logger.info(
            "event=sse_emit user_id=%s session_id=%s kind=%s total=%.3fs",
            user_id,
            session_id,
            kind,
            time.perf_counter() - request_start,
        )
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def log_step(name: str) -> None:
        nonlocal last_step
        now = time.perf_counter()
        logger.info(
            "event=chat_step user_id=%s session_id=%s step=%s elapsed=%.3fs total=%.3fs",
            user_id,
            session_id,
            name,
            now - last_step,
            now - request_start,
        )
        last_step = now

    logger.info(
        "event=chat_request_start user_id=%s session_id=%s query_chars=%d",
        user_id,
        session_id,
        len(query),
    )
    yield emit_sse({"status": "accepted", "content": "已接收病例，开始分析..."}, "status")

    should_save_memory = True

    if _is_insufficient_query(query):
        response_text = SHORT_QUERY_RESPONSE
        should_save_memory = False
        logger.info("event=chat_short_query user_id=%s session_id=%s query=%r", user_id, session_id, query)
        log_step("local_input_validation")
        yield emit_sse({"agent": "input_validation", "content": response_text}, "content")
    else:
        yield emit_sse({"status": "semantic_cache_check", "content": "正在检查语义缓存..."}, "status")
        cache_hit = await semantic_cache.get_cache(query, user_id)
        log_step("semantic_cache_check")
        if cache_hit:
            response_text = cache_hit["answer"]
            logger.info(
                "event=semantic_cache_hit user_id=%s session_id=%s level=%s distance=%.4f matched=%r",
                user_id,
                session_id,
                cache_hit["level"],
                cache_hit["distance"],
                cache_hit["matched_question"],
            )
            yield emit_sse({"agent": "semantic_cache", "content": response_text}, "content")
        else:
            logger.info("event=agent_workflow_start user_id=%s session_id=%s", user_id, session_id)
            yield emit_sse({"status": "memory_context_extract", "content": "正在提取会话记忆..."}, "status")
            mem_context = await _extract_memory_context(user_id, session_id, query)
            log_step("memory_context_extract")
            state = {
                "messages": [HumanMessage(content=query)],
                "user_id": user_id,
                "session_id": session_id,
                "memory_context": mem_context,
                "next_agent": "",
                "metadata": {}
            }
            config = {"configurable": {"user_id": user_id}}

            yield emit_sse({"status": "agent_workflow_start", "content": "正在进入多智能体分析..."}, "status")
            full_response = ""
            current_agent = None

            async for stream_mode, data in graph.astream(
                state, config=config, stream_mode=["updates", "custom"]
            ):
                if stream_mode == "custom":
                    if data.get("event") == "start":
                        current_agent = data["agent"]
                        yield emit_sse(
                            {"status": "agent_node_start", "agent": current_agent},
                            "status",
                        )
                    elif data.get("event") == "tool_call":
                        tool_name = data.get("tool") or "知识库工具"
                        yield emit_sse(
                            {"status": "agent_tool_call", "agent": current_agent, "content": f"正在调用 {tool_name}..."},
                            "status",
                        )
                    elif data.get("event") == "tool_done":
                        yield emit_sse(
                            {"status": "agent_tool_done", "agent": current_agent, "content": "工具查询完成，正在生成分析..."},
                            "status",
                        )
                    elif "chunk" in data:
                        full_response += data["chunk"]
                        yield emit_sse(
                            {"agent": data.get("agent", current_agent), "content": data["chunk"]},
                            "content",
                        )

                elif stream_mode == "updates":
                    for node_name, node_output in data.items():
                        logger.info("event=agent_update user_id=%s session_id=%s node=%s", user_id, session_id, node_name)
                        yield emit_sse(
                            {
                                "status": "agent_node_complete",
                                "agent": node_name,
                                "content": f"{node_name} 已完成，正在整理结果...",
                            },
                            "status",
                        )

            log_step("agent_workflow")
            response_text = full_response

    # 保存短时记忆
    if should_save_memory and memory and memory.short_term.available:
        turn = [
            {"role": "user", "content": query},
            {"role": "assistant", "content": response_text},
        ]
        await memory.save_conversation(user_id, session_id, turn)
        log_step("short_term_memory_save")

    yield emit_sse({"done": True}, "done")
    log_step("sse_complete")
