"""临床决策支持系统（Clinical CDS）的主入口。

该模块提供了一个 CLI 接口，用于与基于 LangGraph 的多智能体系统进行交互。
会话级状态通过 LangGraph Checkpoint + Redis 管理（session_id 作为 thread_id），
长期临床要点存储在 Milvus 并按语义检索。

用法:
    python main.py                    # 交互模式
    python main.py --query "患者近两周情绪低落..."  # 单次查询模式
"""

import argparse
import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

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
from core.workflow.graph_manager import AgentGraphManager
from core.workflow.checkpointer import close_checkpointer, create_redis_checkpointer
from core.workflow.state import AgentState

EXTRACT_EVERY_N_TURNS = 5


def setup_logging(log_level: str = "INFO") -> None:
    """为应用程序配置日志记录。"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ]
    )

async def _extract_long_term_context(memory: MemoryManager, user_id: str, query: str) -> str:
    """从 Milvus（长期）获取临床要点上下文；近期历史由 checkpoint 自动携带。"""
    if not memory.long_term.available:
        return ""
    prefs = await memory.load_preferences(user_id, query)
    if not prefs:
        return ""
    lines = ["【用户长期临床背景】:"]
    lines.extend(f"- {p}" for p in prefs)
    return "\n".join(lines)

def _format_conversation(messages: list[BaseMessage]) -> str:
    """将 checkpoint 消息历史渲染为提取器所需的 role: content 文本。"""
    parts = []
    for m in messages:
        content = getattr(m, "content", "")
        if not content:
            continue
        if isinstance(m, SystemMessage):
            role = "System"
        elif isinstance(m, HumanMessage):
            role = "User"
        else:
            role = "Assistant"
        parts.append(f"{role}: {content}")
    return "\n".join(parts)

async def _extract_from_checkpoint(graph, config: dict, memory: MemoryManager,
                                   user_id: str, llm) -> list[str]:
    """从 checkpoint 会话历史提取临床要点并写入 Milvus。"""
    try:
        snapshot = await graph.aget_state(config)
        messages = list(snapshot.values.get("messages", []))
        conversation = _format_conversation(messages)
        if conversation.strip():
            return await memory.extract_from_conversation(user_id, conversation, llm)
    except Exception as exc:
        print(f"⚠️  长期记忆提取失败: {exc}")
    return []

async def run_interactive_mode(
    graph_manager: AgentGraphManager,
    user_id: str,
    session_id: str,
    memory: MemoryManager,
    checkpointer,
) -> None:
    """运行与多智能体图的交互式聊天循环。"""
    print("\n" + "=" * 60)
    print("🏥 Clinical Decision Support System Ready!")
    print(f"  Doctor:  {user_id}")
    print(f"  Session: {session_id} (thread_id)")
    print("  Type 'quit' / 'exit' / 'q' to stop")
    print("=" * 60)

    lt_ok = memory.long_term.available
    print(f"\n  [MEM] Session state (Checkpoint): {'✅ enabled' if checkpointer else '❌ disabled (Redis unavailable)'}")
    print(f"  [MEM] Long-term  (Milvus):        {'✅ connected' if lt_ok else '❌ not available'}")
    print()

    graph = graph_manager.build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": session_id, "user_id": user_id}}

    # 独立的轻量 LLM 实例，用于长期记忆提取
    extraction_llm = ChatOpenAI(**get_settings().get_model_config(), temperature=0)

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

            # 1. 检索长期临床要点（历史由 checkpoint 携带）
            print("🧠 Retrieving memory context...")
            mem_context = await _extract_long_term_context(memory, user_id, user_input)

            # 2. 执行图：每轮只传新消息，历史由 checkpoint 累积
            print("🤖 Processing...")
            state: AgentState = {
                "messages": [HumanMessage(content=user_input)],
                "user_id": user_id,
                "session_id": session_id,
                "memory_context": mem_context,
                "next_agent": "",
                "metadata": {}
            }
            result = await graph.ainvoke(state, config=config)
            response_text = result["messages"][-1].content

            print(f"\n🤖 AI: {response_text}\n")

            # 3. 定期触发长期记忆提取
            turn_count += 1
            if turn_count % EXTRACT_EVERY_N_TURNS == 0 and lt_ok:
                print("🔄 [Background] Triggering long-term memory extraction...")
                await _extract_from_checkpoint(graph, config, memory, user_id, extraction_llm)

    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {e}\n")
        logging.exception("Agent execution failed")
    finally:
        print("\n" + "-" * 60)
        print("💾 Extracting clinical facts from session into long-term memory...")
        if lt_ok:
            new_items = await _extract_from_checkpoint(graph, config, memory, user_id, extraction_llm)
            if new_items:
                print(f"   新增 {len(new_items)} 条临床要点")
        print("✅ Session finalized.")
        print("-" * 60 + "\n")


async def main() -> None:
    """主入口点。"""
    parser = argparse.ArgumentParser(description="Clinical Decision Support System - Multi-Agent")
    parser.add_argument("--query", "-q", type=str, help="Single query mode")
    parser.add_argument("--user", "-u", type=str, default="user_1001", help="User ID")
    parser.add_argument("--session", "-s", type=str, default=None, help="Session ID (used as checkpoint thread_id)")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    log_level = "DEBUG" if args.debug else get_settings().log_level
    setup_logging(log_level)

    user_id = args.user
    session_id = args.session or f"session_{uuid.uuid4().hex[:8]}"

    settings = get_settings()

    # 会话级状态：LangGraph Checkpoint + Redis
    checkpointer = await create_redis_checkpointer(settings.redis_url)

    # 长期记忆管理器（Milvus）
    memory = MemoryManager(
        milvus_host=settings.milvus_host,
        milvus_port=settings.milvus_port,
        milvus_api_key=settings.milvus_api_key,
        embedding_api_key=settings.get_embedding_api_key(),
    )
    await memory.initialize()

    # 初始化图管理器
    graph_manager = AgentGraphManager()

    try:
        if args.query:
            # 单次查询：同样走 checkpoint，可后续用相同 --session 继续
            graph = graph_manager.build_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": session_id, "user_id": user_id}}
            mem_context = await _extract_long_term_context(memory, user_id, args.query)
            state: AgentState = {
                "messages": [HumanMessage(content=args.query)],
                "user_id": user_id,
                "session_id": session_id,
                "memory_context": mem_context,
                "next_agent": "",
                "metadata": {}
            }
            print(f"\n👤 User: {args.query}")
            result = await graph.ainvoke(state, config=config)
            print(f"\n🤖 AI: {result['messages'][-1].content}\n")
            if memory.long_term.available:
                extraction_llm = ChatOpenAI(**settings.get_model_config(), temperature=0)
                await _extract_from_checkpoint(graph, config, memory, user_id, extraction_llm)
        else:
            await run_interactive_mode(graph_manager, user_id, session_id, memory, checkpointer)
    finally:
        await memory.close()
        await close_checkpointer(checkpointer)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.exception("Application failed")
        sys.exit(1)
