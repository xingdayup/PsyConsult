"""临床决策支持系统（Clinical CDS）的主入口。

该模块提供了一个 CLI 接口，用于与基于 LangGraph 的多智能体系统进行交互，
并集成了 FastMCP 工具和长/短期内存。

用法:
    python main.py                    # 交互模式
    python main.py --query "什么是VPC"  # 单次查询模式
"""

import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# 抑制 macOS 上与 gRPC fork 相关的警告（无害，来自 pymilvus/grpcio）
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
os.environ.setdefault("GRPC_TRACE", "")

# 将父目录添加到导入路径
sys.path.insert(0, str(Path(__file__).parent))

# 确保所有平台上的 stdin/stdout 都使用 UTF-8（修复 macOS 终端中文输入问题）
if hasattr(sys.stdin, 'reconfigure'):
    sys.stdin.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from config import get_settings
from core.memory import MemoryManager
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from core.workflow.graph_manager import AgentGraphManager
from core.workflow.state import AgentState


def setup_logging(log_level: str = "INFO") -> None:
    """为应用程序配置日志记录。"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )


def _create_memory_extraction_llm():
    return ChatOpenAI(**get_settings().get_model_config(), temperature=0)

async def _extract_memory_context(memory: MemoryManager, user_id: str, session_id: str, query: str) -> str:
    """从 Redis（短期）和 Milvus（长期）获取内存上下文的辅助函数。"""
    context_parts = []
    
    # 1. 获取短期历史
    if memory.short_term.available:
        history = await memory.short_term.get_messages(user_id, session_id)
        if history:
            # 只取最近几轮
            recent_history = history[-10:] if len(history) > 10 else history
            context_parts.append("【近期对话历史】:")
            for msg in recent_history:
                role = "User" if msg["role"] == "user" else "Assistant"
                context_parts.append(f"{role}: {msg['content']}")
    
    # 2. 获取长期偏好
    if memory.long_term.available:
        prefs = await memory.long_term.retrieve_relevant(user_id, query)
        if prefs:
            context_parts.append("\n【用户长期偏好/背景】:")
            for p in prefs:
                context_parts.append(f"- {p}")
                
    return "\n".join(context_parts)

async def run_interactive_mode(
    graph_manager: AgentGraphManager,
    user_id: str,
    session_id: str,
    memory: MemoryManager,
) -> None:
    """运行与多智能体图的交互式聊天循环。"""
    print("\n" + "=" * 60)
    print("🏥 Clinical Decision Support System Ready!")
    print(f"  Doctor:  {user_id}")
    print(f"  Session: {session_id}")
    print("  Type 'quit' / 'exit' / 'q' to stop")
    print("=" * 60)

    st_ok = memory.short_term.available
    lt_ok = memory.long_term.available
    print(f"\n  [MEM] Short-term (Redis) : {'✅ connected' if st_ok else '❌ not available'}")
    print(f"  [MEM] Long-term  (Milvus): {'✅ connected' if lt_ok else '❌ not available'}")
    print()

    graph = graph_manager.build_graph()
    
    # 初始化状态
    state: AgentState = {
        "messages": [],
        "user_id": user_id,
        "session_id": session_id,
        "memory_context": "",
        "next_agent": "",
        "metadata": {}
    }
    
    turn_count = 0

    try:
        while True:
            try:
                user_input = input("\n👤 You: ").strip()
            except UnicodeDecodeError:
                raw = sys.stdin.buffer.readline()
                user_input = raw.decode('utf-8', errors='replace').strip()
            except EOFError:
                break

            if user_input.lower() in ("quit", "exit", "q"):
                break
            if not user_input:
                continue

            # 1. 在执行前获取内存上下文
            print("🧠 Retrieving memory context...")
            mem_context = await _extract_memory_context(memory, user_id, session_id, user_input)
            
            # 使用新输入和内存更新状态
            state["messages"].append(HumanMessage(content=user_input))
            state["memory_context"] = mem_context

            # 2. 执行图
            print("🤖 Processing...")
            result = await graph.ainvoke(state)
            
            # 使用结果消息更新状态
            state["messages"] = result["messages"]
            response_text = result["messages"][-1].content
            
            print(f"\n🤖 AI: {response_text}\n")
            
            # 3. 保存到短期内存
            if memory.short_term.available:
                turn = [
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": response_text},
                ]
                await memory.save_conversation(user_id, session_id, turn)
            
            # 4. 定期触发长期内存提取
            turn_count += 1
            if turn_count % 5 == 0:
                print("🔄 [Background] Triggering long-term memory extraction...")
                asyncio.create_task(
                    memory.background_extract(user_id, session_id, _create_memory_extraction_llm())
                )

    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        logging.exception("Agent execution failed")
    finally:
        print("\n" + "-" * 60)
        print("💾 Saving session preferences to long-term memory...")
        await memory.finalize_session(user_id, session_id, _create_memory_extraction_llm())
        print("✅ Session finalized.")
        print("-" * 60 + "\n")


async def main() -> None:
    """主入口点。"""
    parser = argparse.ArgumentParser(description="Clinical Decision Support System - Multi-Agent")
    parser.add_argument("--query", "-q", type=str, help="Single query mode")
    parser.add_argument("--user", "-u", type=str, default="user_1001", help="User ID")
    parser.add_argument("--session", "-s", type=str, default=None, help="Session ID")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    
    log_level = "DEBUG" if args.debug else get_settings().log_level
    setup_logging(log_level)
    
    user_id = args.user
    session_id = args.session or f"session_{uuid.uuid4().hex[:8]}"
    
    settings = get_settings()
    
    # 初始化内存管理器
    memory = MemoryManager(
        redis_url=settings.redis_url,
        redis_ttl=settings.redis_ttl,
        milvus_host=settings.milvus_host,
        milvus_port=settings.milvus_port,
        milvus_api_key=settings.milvus_api_key,
        embedding_api_key=settings.dashscope_api_key,
    )
    await memory.initialize()
    
    # 初始化图管理器
    graph_manager = AgentGraphManager()
    
    try:
        if args.query:
            # 为简单起见，单次查询使用相同的流程，但不使用循环
            graph = graph_manager.build_graph()
            mem_context = await _extract_memory_context(memory, user_id, session_id, args.query)
            state: AgentState = {
                "messages": [HumanMessage(content=args.query)],
                "user_id": user_id,
                "session_id": session_id,
                "memory_context": mem_context,
                "next_agent": "",
                "metadata": {}
            }
            print(f"\n👤 User: {args.query}")
            result = await graph.ainvoke(state)
            print(f"\n🤖 AI: {result['messages'][-1].content}\n")
        else:
            await run_interactive_mode(graph_manager, user_id, session_id, memory)
    finally:
        await memory.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.exception("Application failed")
        sys.exit(1)
