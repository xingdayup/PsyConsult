from pydantic import BaseModel
from typing import Optional

class ChatRequest(BaseModel):
    query: str
    user_id: Optional[str] = "user_1001"
    session_id: Optional[str] = "default_session"

class ChatResponse(BaseModel):
    status: str
    reply: str
    user_id: str
    session_id: str
