import asyncio
import json
import logging

from app.infra.logging_config import configure_backend_logging
from app.service import chat_service
from core.memory.memory_manager import MemoryManager


def _parse_sse_chunk(chunk: str) -> dict:
    assert chunk.startswith("data: ")
    return json.loads(chunk.removeprefix("data: ").strip())


def test_configure_backend_logging_writes_to_file(tmp_path):
    log_file = tmp_path / "backend.log"

    configure_backend_logging(log_file=log_file, force=True)
    logging.getLogger("clinical_cds.test").info("timing-log-smoke")

    assert log_file.exists()
    assert "timing-log-smoke" in log_file.read_text(encoding="utf-8")


def test_stream_chat_logs_short_query_timing(caplog):
    async def collect_stream():
        chunks = []
        async for chunk in chat_service.stream_chat("短", "doctor_001", "session_demo"):
            chunks.append(chunk)
        return chunks

    with caplog.at_level(logging.INFO, logger="clinical_cds.chat"):
        chunks = asyncio.run(collect_stream())

    assert chunks[-1] == 'data: {"done": true}\n\n'
    assert _parse_sse_chunk(chunks[0])["status"] == "accepted"
    assert any(_parse_sse_chunk(chunk).get("content") == chat_service.SHORT_QUERY_RESPONSE for chunk in chunks)
    messages = [record.getMessage() for record in caplog.records]
    assert any("event=chat_request_start" in message for message in messages)
    assert any("event=sse_emit" in message and "kind=status" in message for message in messages)
    assert any("event=chat_step" in message for message in messages)
    assert any("step=local_input_validation" in message for message in messages)
    assert any("step=sse_complete" in message for message in messages)


def test_stream_chat_emits_accepted_status_first_for_cache_hit(monkeypatch):
    cached_answer = "cached clinical answer"

    class DummySemanticCache:
        async def get_cache(self, query, user_id):
            return {
                "answer": cached_answer,
                "level": "L1_EXACT",
                "distance": 0.0,
                "matched_question": query,
            }

    monkeypatch.setattr(chat_service, "semantic_cache", DummySemanticCache())

    async def collect_stream():
        chunks = []
        async for chunk in chat_service.stream_chat(
            "患者近两周情绪低落并伴有失眠", "doctor_001", "session_demo"
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(collect_stream())

    assert _parse_sse_chunk(chunks[0]) == {
        "status": "accepted",
        "content": "已接收病例，开始分析...",
    }
    assert any(_parse_sse_chunk(chunk).get("content") == cached_answer for chunk in chunks)


def test_stream_chat_schedules_long_term_memory_extract_after_valid_turn(monkeypatch):
    scheduled = []

    class DummySemanticCache:
        async def get_cache(self, query, user_id):
            return {
                "answer": "建议进一步评估抑郁症状和睡眠问题。",
                "level": "L1_EXACT",
                "distance": 0.0,
                "matched_question": query,
            }

    class DummyShortTerm:
        available = True

        async def get_messages(self, user_id, session_id):
            return []

    class DummyLongTerm:
        available = True

    class DummyMemory:
        short_term = DummyShortTerm()
        long_term = DummyLongTerm()

        async def save_conversation(self, user_id, session_id, messages):
            assert user_id == "doctor_001"
            assert session_id == "session_demo"
            assert messages[0]["role"] == "user"
            assert messages[1]["role"] == "assistant"

        async def background_extract(self, user_id, session_id, llm):
            scheduled.append((user_id, session_id, llm))
            return ["主诉: 情绪低落、失眠"]

    monkeypatch.setattr(chat_service, "semantic_cache", DummySemanticCache())
    monkeypatch.setattr(chat_service, "memory", DummyMemory())
    monkeypatch.setattr(chat_service, "_create_memory_extraction_llm", lambda: object(), raising=False)

    async def collect_stream():
        chunks = []
        async for chunk in chat_service.stream_chat(
            "患者近两周情绪低落并伴有失眠", "doctor_001", "session_demo"
        ):
            chunks.append(chunk)
        await asyncio.sleep(0)
        return chunks

    chunks = asyncio.run(collect_stream())

    assert _parse_sse_chunk(chunks[-1]) == {"done": True}
    assert scheduled
    assert scheduled[0][0] == "doctor_001"
    assert scheduled[0][1] == "session_demo"


def test_stream_chat_does_not_schedule_long_term_memory_extract_for_short_query(monkeypatch):
    scheduled = []

    class DummyMemory:
        class short_term:
            available = True

        class long_term:
            available = True

        async def save_conversation(self, user_id, session_id, messages):
            raise AssertionError("short invalid queries should not be saved")

        async def background_extract(self, user_id, session_id, llm):
            scheduled.append((user_id, session_id, llm))

    monkeypatch.setattr(chat_service, "memory", DummyMemory())
    monkeypatch.setattr(chat_service, "_create_memory_extraction_llm", lambda: object(), raising=False)

    async def collect_stream():
        chunks = []
        async for chunk in chat_service.stream_chat("短", "doctor_001", "session_demo"):
            chunks.append(chunk)
        await asyncio.sleep(0)
        return chunks

    chunks = asyncio.run(collect_stream())

    assert _parse_sse_chunk(chunks[-1]) == {"done": True}
    assert scheduled == []


def test_background_extract_runs_after_one_complete_turn():
    saved = []

    class DummyShortTerm:
        async def get_messages(self, user_id, session_id):
            return [
                {"role": "user", "content": "患者 PHQ-9 14 分，近两周情绪低落、失眠。"},
                {"role": "assistant", "content": "建议评估中度抑郁发作并关注睡眠。"},
            ]

    class DummyLongTerm:
        available = True

        async def retrieve_relevant(self, user_id, query, top_k):
            return []

        async def save_memory(self, user_id, content, memory_type="general"):
            saved.append((user_id, content, memory_type))

    class DummyLLM:
        async def ainvoke(self, messages):
            class Response:
                content = "PHQ-9: 14 分\n主诉: 情绪低落、失眠 2 周"

            return Response()

    manager = object.__new__(MemoryManager)
    manager.short_term = DummyShortTerm()
    manager.long_term = DummyLongTerm()

    result = asyncio.run(manager.background_extract("doctor_001", "session_demo", DummyLLM()))

    assert result == ["PHQ-9: 14 分", "主诉: 情绪低落、失眠 2 周"]
    assert saved == [
        ("doctor_001", "PHQ-9: 14 分", "preference"),
        ("doctor_001", "主诉: 情绪低落、失眠 2 周", "preference"),
    ]
