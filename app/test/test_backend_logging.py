import asyncio
import json
import logging

from app.infra.logging_config import configure_backend_logging
from app.service import chat_service


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
