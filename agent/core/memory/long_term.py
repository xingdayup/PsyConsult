"""由 Milvus 向量数据库支持的长期内存。

用户偏好和关键事实作为密集向量嵌入进行存储。
检索使用余弦相似度搜索，并按 user_id 进行过滤，因此每个用户的记忆保持隔离。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION_NAME = "long_term_memory"
EMBEDDING_DIM = 1536  


class LongTermMemory:
    """用于用户偏好和事实的基于 Milvus 的长期内存。

    功能：
    - 通过 Milvus 进行密集向量搜索（余弦相似度）
    - 对 ``user_id`` 进行标量过滤，实现每用户隔离
    - 偏好助手：``save_preference(user_id, type, value)``
    - 优雅降级：如果 Milvus 不可用，操作将变为空操作

    用法::

        mem = LongTermMemory(embedding_api_key="sk-...")
        await mem.initialize()

        await mem.save_preference("user1", "language", "Chinese")
        results = await mem.retrieve_relevant("user1", "preferred language")
        await mem.close()
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 19530,
        api_key: str | None = None,
        embedding_api_key: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._api_key = api_key
        self._embedding_api_key = embedding_api_key
        self._client: Any = None
        self._embeddings: Any = None
        self._available: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect to Milvus and ensure collection exists.

        Sets _available=False on failure (no exception raised).
        """
        if not self._embedding_api_key:
            logger.info(
                "LongTermMemory disabled: no DashScope embedding key. "
                "Set DASHSCOPE_EMBEDDING_API_KEY or EMBEDDING_API_KEY to enable it."
            )
            self._available = False
            return

        try:
            from pymilvus import MilvusClient  # type: ignore[import]
            from langchain_community.embeddings import DashScopeEmbeddings  # type: ignore[import]

            uri = f"http://{self._host}:{self._port}"
            connect_kwargs: dict[str, Any] = {"uri": uri}
            if self._api_key:
                connect_kwargs["token"] = self._api_key

            self._client = MilvusClient(**connect_kwargs)
            self._embeddings = DashScopeEmbeddings(
                model="text-embedding-v2",
                dashscope_api_key=self._embedding_api_key,
            )
            self._ensure_collection()
            self._available = True
            logger.info("LongTermMemory: Milvus connected at %s:%s", self._host, self._port)
        except Exception as exc:
            logger.warning(
                "LongTermMemory: Milvus unavailable (%s) – long-term memory disabled.", exc
            )
            self._available = False

    async def close(self) -> None:
        """Close Milvus client."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save_memory(
        self,
        user_id: str,
        content: str,
        memory_type: str = "general",
    ) -> None:
        """Embed and store a memory entry.

        Args:
            user_id: Owner of this memory.
            content: Text to embed and store.
            memory_type: Category label (e.g. "preference", "fact").
        """
        if not self._available:
            return
        try:
            embedding = await self._embeddings.aembed_query(content)
            self._client.insert(
                collection_name=COLLECTION_NAME,
                data=[
                    {
                        "user_id": user_id,
                        "content": content,
                        "memory_type": memory_type,
                        "embedding": embedding,
                    }
                ],
            )
            logger.debug(
                "LongTermMemory: stored %s memory for user %s: %s",
                memory_type, user_id, content[:60],
            )
        except Exception as exc:
            logger.error("LongTermMemory.save_memory failed: %s", exc)

    async def save_preference(
        self, user_id: str, preference_type: str, value: str
    ) -> None:
        """Convenience wrapper for storing a user preference.

        Args:
            user_id: Owner of this preference.
            preference_type: Short label (e.g. "language", "city").
            value: Preference value (e.g. "Chinese", "Beijing").
        """
        content = f"User preference – {preference_type}: {value}"
        await self.save_memory(user_id, content, memory_type="preference")

    async def retrieve_relevant(
        self, user_id: str, query: str, top_k: int = 5
    ) -> list[str]:
        """Return the top-k most relevant memory entries for a query.

        Args:
            user_id: Filter results to this user only.
            query: Natural-language query text.
            top_k: Maximum number of results to return.

        Returns:
            List of content strings ordered by relevance.
        """
        if not self._available:
            return []
        try:
            query_embedding = await self._embeddings.aembed_query(query)
            results = self._client.search(
                collection_name=COLLECTION_NAME,
                data=[query_embedding],
                filter=f'user_id == "{user_id}"',
                limit=top_k,
                output_fields=["content", "memory_type"],
            )
            memories: list[str] = []
            for hits in results:
                for hit in hits:
                    memories.append(hit["entity"]["content"])
            return memories
        except Exception as exc:
            logger.error("LongTermMemory.retrieve_relevant failed: %s", exc)
            return []

    @property
    def available(self) -> bool:
        """True if Milvus is reachable."""
        return self._available

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_collection(self) -> None:
        """Create the Milvus collection and index if they do not exist."""
        from pymilvus import DataType  # type: ignore[import]

        if self._client.has_collection(COLLECTION_NAME):
            return

        schema = self._client.create_schema()
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("user_id", DataType.VARCHAR, max_length=128)
        schema.add_field("content", DataType.VARCHAR, max_length=2048)
        schema.add_field("memory_type", DataType.VARCHAR, max_length=64)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            "embedding",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": 128},
        )

        self._client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
        )
        logger.info("LongTermMemory: created Milvus collection '%s'", COLLECTION_NAME)
