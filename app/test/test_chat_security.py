import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.app_config.settings import settings
from app.app_main import app
from app.router import chat as chat_router
from app.schemas.chat import ChatRequest


def test_chat_request_rejects_blank_query():
    with pytest.raises(ValidationError):
        ChatRequest(query="   ", session_id="session_valid")


def test_chat_request_rejects_invalid_session_id():
    with pytest.raises(ValidationError):
        ChatRequest(query="患者近两周情绪低落", session_id="../bad")


def test_chat_requires_bearer_token_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_token", "local-dev-token", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        headers={"X-User-Id": "doctor_001"},
        json={"query": "患者近两周情绪低落", "session_id": "session_valid"},
    )

    assert response.status_code == 401


def test_chat_rejects_wrong_bearer_token(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_token", "local-dev-token", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        headers={
            "Authorization": "Bearer wrong-token",
            "X-User-Id": "doctor_001",
        },
        json={"query": "患者近两周情绪低落", "session_id": "session_valid"},
    )

    assert response.status_code == 401


def test_chat_rejects_invalid_user_header_when_authorized(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_token", "local-dev-token", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        headers={
            "Authorization": "Bearer local-dev-token",
            "X-User-Id": "../doctor",
        },
        json={"query": "患者近两周情绪低落", "session_id": "session_valid"},
    )

    assert response.status_code == 400


def test_chat_rejects_missing_user_header_when_authorized(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_token", "local-dev-token", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer local-dev-token"},
        json={"query": "患者近两周情绪低落", "session_id": "session_valid"},
    )

    assert response.status_code == 400


def test_chat_authorized_request_returns_sse(monkeypatch):
    monkeypatch.setattr(settings, "api_auth_token", "local-dev-token", raising=False)

    async def fake_stream_chat(query: str, user_id: str, session_id: str):
        assert query == "患者近两周情绪低落"
        assert user_id == "doctor_001"
        assert session_id == "session_valid"
        yield 'data: {"done": true}\n\n'

    monkeypatch.setattr(chat_router, "stream_chat", fake_stream_chat)
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        headers={
            "Authorization": "Bearer local-dev-token",
            "X-User-Id": "doctor_001",
        },
        json={"query": "患者近两周情绪低落", "session_id": "session_valid"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == 'data: {"done": true}\n\n'
