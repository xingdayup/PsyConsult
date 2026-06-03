"""Application settings using Pydantic Settings."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # LLM Configuration
    dashscope_api_key: str = Field(alias="DASHSCOPE_API_KEY")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    model: str = Field(default="qwen-plus", alias="MODEL")
    base_url: str | None = Field(default=None, alias="BASE_URL")
    embedding_api_key: str | None = Field(default=None, alias="EMBEDDING_API_KEY")
    dashscope_embedding_api_key: str | None = Field(default=None, alias="DASHSCOPE_EMBEDDING_API_KEY")
    
    # MCP Configuration
    mcp_servers_config: Path = Field(
        default=Path(__file__).parent / "mcp_servers.json",
        alias="MCP_SERVERS_CONFIG"
    )
    
    # Weather API
    openweather_api_key: str | None = Field(default=None, alias="OPENWEATHER_API_KEY")
    
    # Redis (short-term memory)
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")
    redis_ttl: int = Field(default=1800, alias="REDIS_TTL")  # seconds
    
    # Milvus (long-term memory)
    milvus_host: str = Field(default="localhost", alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, alias="MILVUS_PORT")
    milvus_api_key: str | None = Field(default=None, alias="MILVUS_API_KEY")
    
    # Neo4j (knowledge graph)
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="password", alias="NEO4J_PASSWORD")
    neo4j_database: str = Field(default="neo4j", alias="NEO4J_DATABASE")
    
    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    
    @field_validator("dashscope_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Validate API key is not empty."""
        if not v or v.strip() == "":
            raise ValueError("DASHSCOPE_API_KEY cannot be empty")
        return v.strip()
    
    def get_model_config(self) -> dict[str, Any]:
        """Get model configuration for LangChain."""
        config: dict[str, Any] = {
            "model": self.model,
            "api_key": self.get_llm_api_key(),
        }
        if self.base_url:
            config["base_url"] = self.base_url
        return config

    def get_llm_api_key(self) -> str:
        """Return the chat model API key, preferring provider-specific LLM_API_KEY."""
        if self.llm_api_key:
            return self.llm_api_key.strip()
        return self.dashscope_api_key

    def get_embedding_api_key(self) -> str | None:
        """Return a DashScope-compatible embedding key when explicitly configured."""
        if self.embedding_api_key:
            return self.embedding_api_key.strip()
        if self.dashscope_embedding_api_key:
            return self.dashscope_embedding_api_key.strip()
        if self.llm_api_key and self.dashscope_api_key:
            return self.dashscope_api_key
        if self.base_url and "dashscope.aliyuncs.com" in self.base_url.lower():
            return self.dashscope_api_key
        return None


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
