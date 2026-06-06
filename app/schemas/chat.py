from pydantic import BaseModel, Field, field_validator

ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,128}$"

class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default="default_session", pattern=ID_PATTERN)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query cannot be blank")
        return normalized

class ChatResponse(BaseModel):
    status: str
    reply: str
    user_id: str
    session_id: str
