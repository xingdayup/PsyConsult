"""长期记忆管理器（Milvus 向量存储）。

会话级状态由 LangGraph Checkpoint + Redis 负责（见
``core/workflow/checkpointer.py``），本模块只负责跨会话的长期记忆：
用户/患者的临床要点（主诉、诊断、用药、量表分数等）经 LLM 提取后
向量化存入 Milvus，按 ``user_id`` 隔离并支持语义检索。

提取的对话文本由调用方提供（通常来自 checkpoint 中的消息历史）。
当 Milvus 不可用时优雅降级，所有操作变为空操作。
"""

import logging
from typing import Any

from .long_term import LongTermMemory
from .preference_extractor import PreferenceExtractor

logger = logging.getLogger(__name__)


class MemoryManager:
    """管理 Milvus 长期记忆的提取与检索。

    参数：
        milvus_host: Milvus 服务器主机名。
        milvus_port: Milvus 服务器端口。
        milvus_api_key: 可选的 Milvus 身份验证令牌。
        embedding_api_key: 用于 Milvus 嵌入的 DashScope API 密钥。

    示例::

        memory = MemoryManager(embedding_api_key="sk-...")
        await memory.initialize()

        # 每轮注入上下文：
        prefs = await memory.load_preferences(user_id, query)

        # 周期性 / 会话结束时，用 checkpoint 历史提取临床要点：
        await memory.extract_from_conversation(user_id, conv_text, llm)

        await memory.close()
    """

    def __init__(
        self,
        milvus_host: str = "localhost",
        milvus_port: int = 19530,
        milvus_api_key: str | None = None,
        embedding_api_key: str | None = None,
    ) -> None:
        self.long_term = LongTermMemory(
            host=milvus_host,
            port=milvus_port,
            api_key=milvus_api_key,
            embedding_api_key=embedding_api_key,
        )

    async def initialize(self) -> None:
        """Initialize the storage backend (no exception raised on failure)."""
        await self.long_term.initialize()
        logger.info(
            "MemoryManager ready – long_term=%s",
            "✓" if self.long_term.available else "✗ (disabled)",
        )

    async def close(self) -> None:
        """Close the storage backend."""
        await self.long_term.close()
        logger.info("MemoryManager closed")

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    async def load_preferences(
        self,
        user_id: str,
        query: str = "临床要点 病史 诊断 用药 量表 偏好",
        top_k: int = 5,
    ) -> list[str]:
        """Retrieve relevant long-term memories for a user from Milvus.

        Args:
            user_id: User identifier.
            query: Semantic search query (use the user's current question
                   for best relevance).
            top_k: Maximum number of memories to return.

        Returns:
            List of memory strings (may be empty if Milvus unavailable).
        """
        if not self.long_term.available:
            return []
        try:
            result = await self.long_term.retrieve_relevant(
                user_id=user_id,
                query=query,
                top_k=top_k,
            )
            logger.debug(
                "[MEMORY] load_preferences user='%s' query='%s' top_k=%d → %d results",
                user_id, query[:40], top_k, len(result),
            )
            return result
        except Exception as exc:
            logger.warning("load_preferences failed for %s: %s", user_id, exc)
            return []

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    async def extract_from_conversation(
        self,
        user_id: str,
        conversation_text: str,
        llm: Any,
    ) -> list[str]:
        """Extract clinical facts from conversation text and persist new ones.

        Args:
            user_id: User identifier.
            conversation_text: Conversation as ``role: content`` lines
                (usually rendered from checkpointed message history).
            llm: LangChain-compatible chat model for extraction.

        Returns:
            Newly saved memory strings (empty if nothing new or disabled).
        """
        if not self.long_term.available:
            return []
        if not user_id or not conversation_text.strip():
            return []

        try:
            extractor = PreferenceExtractor(llm=llm)
            # 去重时用宽泛查询尽量拉全已有记忆
            existing = await self.load_preferences(
                user_id, query="临床要点 病史 诊断 用药 量表 偏好", top_k=20
            )
            new_items = await extractor.extract(
                conversation_text=conversation_text,
                existing=existing,
            )
            for item in new_items:
                await self.long_term.save_memory(
                    user_id=user_id,
                    content=item,
                    memory_type="preference",
                )
            if new_items:
                logger.info(
                    "[MEMORY] Extracted %d new clinical facts for user '%s': %s",
                    len(new_items), user_id, new_items,
                )
            return new_items
        except Exception as exc:
            logger.warning("[MEMORY] Extraction failed for %s: %s", user_id, exc)
            return []

    async def save_preference(self, user_id: str, preference_type: str, value: str) -> None:
        """Manually store a single user preference.

        Args:
            user_id: User identifier.
            preference_type: Category label (e.g. ``"language"``)
            value: Preference value (e.g. ``"Chinese"``)
        """
        await self.long_term.save_preference(user_id, preference_type, value)
