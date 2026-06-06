import re
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from app.app_config.settings import settings
from app.schemas.chat import ChatRequest
from app.service.chat_service import stream_chat

router = APIRouter()
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def require_chat_identity(
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> str:
    if settings.api_auth_token:
        token = _extract_bearer_token(authorization)
        if token is None or not secrets.compare_digest(token, settings.api_auth_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-User-Id header",
        )

    user_id = x_user_id
    if not USER_ID_PATTERN.fullmatch(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-User-Id header",
        )
    return user_id

@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    user_id: Annotated[str, Depends(require_chat_identity)],
):
    """
    处理多智能体聊天请求，并使用 SSE (Server-Sent Events) 返回流式响应。
    如果命中 L1 语义缓存，将直接返回缓存结果。
    否则进入 Agent 图编排流程。
    """
    return StreamingResponse(
        stream_chat(request.query, user_id, request.session_id),
        media_type="text/event-stream"
    )
