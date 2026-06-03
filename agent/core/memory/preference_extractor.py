"""用于长期内存的基于 LLM 的用户偏好提取器。

职责：
- 使用 LLM 分析对话并提取结构化偏好
- 在返回新项之前，与已存储的偏好进行去重
- 保持无状态：调用者负责持久化

此模块有意地与 BaseAgent 和 MemoryManager 解耦，
以便它可以独立测试或替换为不同的提取器。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Extraction prompt – intentionally concise to minimize token usage.
_PROMPT_TEMPLATE = """\
分析以下医生诊疗对话，提取患者的临床关键信息。
每条用单独一行，格式为"类别: 内容"。
只包含具体的、可操作的临床信息。
如果没有相关信息，就输出: 无
所有输出内容必须用中文。

提取示例：
  主诉: 情绪低落、失眠 2 周
  诊断: 中度抑郁发作 (ICD-11: 6A70)
  用药: 舍曲林 50mg qd
  PHQ-9: 14 分
  复诊周期: 每 4 周
  过敏史: 无

对话内容：
{conversation}

提取结果（或"无"）："""


class PreferenceExtractor:
    """Extracts user preferences from conversation text using an LLM.

    Args:
        llm: Any LangChain-compatible chat model (``ainvoke`` required).
        max_conversation_chars: Truncate conversation input to this length
            before sending to the LLM. Keeps token usage bounded.

    Example::

        extractor = PreferenceExtractor(llm=chat_model)
        new_prefs = await extractor.extract(
            conversation_text="user: I live in Beijing...",
            existing=["city: Shanghai"],
        )
        # new_prefs -> ["city: Beijing"]
    """

    def __init__(self, llm: Any, max_conversation_chars: int = 3000) -> None:
        self._llm = llm
        self._max_chars = max_conversation_chars

    async def extract(
        self,
        conversation_text: str,
        existing: list[str] | None = None,
    ) -> list[str]:
        """Extract new preferences from conversation text.

        Args:
            conversation_text: Raw conversation (role: content lines).
            existing: Already-stored preferences for deduplication.
                      Duplicates are silently dropped.

        Returns:
            List of new preference strings in ``"category: value"`` format.
            Empty list if nothing found or on extraction failure.
        """
        truncated = conversation_text[: self._max_chars]
        logger.debug(
            "[EXTRACTOR] Input conversation (%d chars, truncated to %d):\n%s",
            len(conversation_text), len(truncated), truncated[:400],
        )
        prompt = _PROMPT_TEMPLATE.format(conversation=truncated)

        try:
            response = await self._llm.ainvoke([{"role": "user", "content": prompt}])
            raw = response.content.strip()
            logger.debug("[EXTRACTOR] LLM raw response: %s", raw)
        except Exception as exc:
            logger.warning("PreferenceExtractor LLM call failed: %s", exc)
            return []

        if not raw or raw.strip() in ("NONE", "无", "提取结果: 无", "无相关信息"):
            logger.info("[EXTRACTOR] LLM found no preferences")
            return []

        # Parse lines that look like "category: value"
        candidates = [line.strip() for line in raw.split("\n") if ":" in line]
        logger.debug("[EXTRACTOR] Parsed %d candidates: %s", len(candidates), candidates)
        if not candidates:
            return []

        if not existing:
            logger.info("[EXTRACTOR] No existing prefs, keeping all %d candidates", len(candidates))
            return candidates

        # Deduplicate: skip items whose text substantially overlaps existing
        existing_lower = [e.lower() for e in existing]
        new_items: list[str] = []
        for item in candidates:
            item_lower = item.lower()
            if any(item_lower in ex or ex in item_lower for ex in existing_lower):
                logger.debug("[EXTRACTOR] Duplicate skipped: %s", item)
                continue
            new_items.append(item)

        logger.info(
            "[EXTRACTOR] Result: %d new / %d skipped(dup) / %d total candidates",
            len(new_items), len(candidates) - len(new_items), len(candidates),
        )
        return new_items
