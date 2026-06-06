import os
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "agent", ".env")
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

class Settings(BaseSettings):
    dashscope_api_key: str
    llm_api_key: str | None = None
    base_url: str | None = None
    embedding_api_key: str | None = None
    enable_semantic_cache: bool = True
    redis_url: str
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_api_key: str | None = None
    api_auth_token: str | None = None
    cors_origins: str = DEFAULT_CORS_ORIGINS
    
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra='ignore')

    def get_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

settings = Settings()
