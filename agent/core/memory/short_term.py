"""由 Redis 支持的短期对话内存。

消息按用户/会话存储，并基于 TTL 过期。
当消息数量超过 COMPRESSION_THRESHOLD 时，较旧的消息
会自动被修剪，以仅保留最近的消息。
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

COMPRESSION_THRESHOLD = 10  # trim when messages exceed this count
DEFAULT_TTL = 1800          # 30 minutes in seconds


class ShortTermMemory:
    """基于 Redis 的短期对话内存。

    功能：
    - 按用户/会话的键隔离 (`memory:short:{user_id}:{session_id}`)
    - 基于 TTL 的自动过期（默认 30 分钟，可配置）
    - 当超过 COMPRESSION_THRESHOLD 时自动修剪消息
    - 优雅降级：如果 Redis 不可用，操作将变为空操作

    用法::

        mem = ShortTermMemory()
        await mem.initialize()

        await mem.save_messages("user1", "s1", messages)
        msgs = await mem.get_messages("user1", "s1")
        await mem.close()
    """

    def __init__(self, redis_url: str = "redis://localhost:6379", ttl: int = DEFAULT_TTL) -> None:
        self._redis_url = redis_url
        self._ttl = ttl
        self._client: Any = None
        self._available: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect to Redis; sets _available=False on failure (no exception raised)."""
        try:
            import redis.asyncio as aioredis  # type: ignore[import]

            self._client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
                retry_on_timeout=True,
            )
            await self._client.ping()
            self._available = True
            logger.info("ShortTermMemory: Redis connected at %s", self._redis_url)
        except Exception as exc:
            logger.warning(
                "ShortTermMemory: Redis unavailable (%s) – short-term memory disabled.", exc
            )
            self._available = False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_messages(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        """Return stored messages for the given user/session.

        Returns an empty list when Redis is unavailable or the key is missing.
        """
        if not self._available:
            return []
        try:
            data = await self._client.get(self._key(user_id, session_id))
            return json.loads(data) if data else []
        except Exception as exc:
            logger.warning("ShortTermMemory.get_messages failed: %s", exc)
            self._available = False
            return []

    async def save_messages(
        self, user_id: str, session_id: str, messages: list[dict[str, Any]]
    ) -> None:
        """Persist messages to Redis, applying compression when needed.

        Args:
            user_id: Unique user identifier.
            session_id: Unique session identifier.
            messages: List of message dicts with ``role`` and ``content`` keys.
        """
        if not self._available:
            return
        try:
            if len(messages) > COMPRESSION_THRESHOLD:
                messages = self._trim(messages)
            await self._client.set(
                self._key(user_id, session_id),
                json.dumps(messages, ensure_ascii=False),
                ex=self._ttl,
            )
            logger.debug(
                "ShortTermMemory: saved %d messages for %s:%s", len(messages), user_id, session_id
            )
        except Exception as exc:
            logger.warning("ShortTermMemory.save_messages failed: %s", exc)
            self._available = False

    async def append_message(
        self, user_id: str, session_id: str, role: str, content: str
    ) -> None:
        """Append a single message and re-persist."""
        messages = await self.get_messages(user_id, session_id)
        messages.append({"role": role, "content": content})
        await self.save_messages(user_id, session_id, messages)

    async def clear(self, user_id: str, session_id: str) -> None:
        """Delete all messages for a user/session."""
        if not self._available:
            return
        try:
            await self._client.delete(self._key(user_id, session_id))
        except Exception as exc:
            logger.error("ShortTermMemory.clear failed: %s", exc)

    @property
    def available(self) -> bool:
        """True if Redis is reachable."""
        return self._available

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(user_id: str, session_id: str) -> str:
        return f"memory:short:{user_id}:{session_id}"

    @staticmethod
    def _trim(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep system messages + the 6 most recent non-system messages."""
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]
        return system_msgs + other_msgs[-6:]
