import asyncio
import json
import sys
import os
import time

# 初始化 Agent 和 Graph
AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from core.workflow.graph_manager import AgentGraphManager
from core.memory.memory_manager import MemoryManager
from infra.cache import semantic_cache

# Global variables for graph and memory
graph = None
memory = None

MIN_CLINICAL_QUERY_LENGTH = 4
SHORT_QUERY_RESPONSE = (
    "请输入更完整的临床问题或患者信息，例如症状、持续时间、严重程度、既往用药、"
    "量表分数或需要审查的药物组合。当前输入过短，系统不会进入诊疗推理流程。"
)

async def init_agent_system():
    global graph, memory
    if graph is None:
        print("🚀 初始化 Multi-Agent 图编排...")
        graph_manager = AgentGraphManager()
        graph = graph_manager.build_graph()
        
        print("🧠 初始化 Memory 系统...")
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
        print("✅ Agent 系统初始化完成！")

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

    def log_step(name: str) -> None:
        nonlocal last_step
        now = time.perf_counter()
        print(f"⏱️ [chat] {name}: {now - last_step:.2f}s (total {now - request_start:.2f}s)")
        last_step = now

    should_save_memory = True

    if _is_insufficient_query(query):
        response_text = SHORT_QUERY_RESPONSE
        should_save_memory = False
        print(f"🚦 输入过短，跳过缓存和 Agent 工作流: {query!r}")
        log_step("本地输入校验")
    else:
        cache_hit = await semantic_cache.get_cache(query, user_id)
        log_step("语义缓存检查")
        if cache_hit:
            response_text = cache_hit["answer"]
            print(
                f"⚡ 语义缓存命中: {cache_hit['level']} distance={cache_hit['distance']:.4f} matched='{cache_hit['matched_question']}'"
            )
        else:
            print("🏃 进入 Agent 工作流推理...")
            mem_context = await _extract_memory_context(user_id, session_id, query)
            log_step("记忆上下文提取")
            state = {
                "messages": [("user", query)],
                "user_id": user_id,
                "session_id": session_id,
                "memory_context": mem_context,
                "next_agent": "",
                "metadata": {}
            }
            config = {"configurable": {"user_id": user_id}}

            # 逐 Agent 流式推送
            full_response = ""
            async for update in graph.astream(state, config=config, stream_mode="updates"):
                for node_name, node_output in update.items():
                    if "messages" in node_output and node_output["messages"]:
                        msg = node_output["messages"][-1]
                        content = msg.content if hasattr(msg, "content") else str(msg)
                        # 只推送新增的内容
                        if content and content not in full_response:
                            new_content = content[len(full_response):] if full_response.startswith(content[:50]) else content
                            if new_content:
                                yield f"data: {json.dumps({'agent': node_name, 'content': new_content})}\n\n"
                            full_response = content
            log_step("Agent 工作流")
            response_text = full_response

    # 保存短时记忆
    if should_save_memory and memory and memory.short_term.available:
        turn = [
            {"role": "user", "content": query},
            {"role": "assistant", "content": response_text},
        ]
        await memory.save_conversation(user_id, session_id, turn)
        log_step("短期记忆保存")

    yield f"data: {json.dumps({'done': True})}\n\n"
    log_step("SSE 输出完成")
