"""LangGraph Redis Checkpoint 工厂。

会话级状态（消息历史、中间推理结果、工具调用上下文）通过 LangGraph
Checkpointer 持久化到 Redis，以 ``session_id`` 作为 ``thread_id`` 实现多轮
问答的状态恢复与连续推理。

Redis 不可用或依赖缺失时返回 ``None``，图退化为无状态执行（优雅降级）。
"""

import logging
from typing import Any

logger = logging.getLogger("clinical_cds.agent")

# 会话 checkpoint 的默认 TTL（24 小时），读取时自动续期；
# 对应旧短期记忆 30 分钟 TTL 的放宽版本，超时后由 Redis 自动回收。
DEFAULT_CHECKPOINT_TTL_SECONDS = 86400


async def create_redis_checkpointer(
    redis_url: str,
    ttl_seconds: int = DEFAULT_CHECKPOINT_TTL_SECONDS,
) -> Any | None:
    """创建并初始化 AsyncRedisSaver；失败时返回 None。

    Args:
        redis_url: Redis 连接 URL（复用短期记忆同一实例）。
        ttl_seconds: checkpoint 键的 TTL 秒数，读取时刷新。
    """
    try:
        from langgraph.checkpoint.redis import AsyncRedisSaver
    except ImportError:
        logger.warning(
            "Checkpointer disabled: langgraph-checkpoint-redis is not installed. "
            "Run `pip install langgraph-checkpoint-redis` to enable session state."
        )
        return None

    try:
        saver = AsyncRedisSaver(
            redis_url=redis_url,
            ttl={"default_ttl": ttl_seconds, "refresh_on_read": True},
        )
        await saver.asetup()
        await saver.aset_client_info()
        logger.info("Checkpointer ready – Redis session state at %s", redis_url)
        return saver
    except Exception as exc:
        logger.warning(
            "Checkpointer disabled: Redis unavailable (%s) – graph runs stateless.", exc
        )
        return None


async def close_checkpointer(checkpointer: Any) -> None:
    """关闭 checkpointer 连接（容忍任何关闭失败）。"""
    if checkpointer is None:
        return
    try:
        close = getattr(checkpointer, "aclose", None) or getattr(
            checkpointer, "close", None
        )
        result = close()
        if hasattr(result, "__await__"):
            await result
    except Exception as exc:
        logger.warning("Checkpointer close failed: %s", exc)
