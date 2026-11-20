"""All settings come from environment variables or backend/.env (see .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    use_mocks: bool = True
    # Real LLM but fake retrieved passages: lets you test prompts before the RAG pipeline exists
    mock_retrieval: bool = False

    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen3:8b"
    llm_api_key: str = "not-needed"
    llm_timeout_seconds: float = 120
    llm_disable_thinking: bool = True

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    chunk_size: int = 800
    chunk_overlap: int = 150
    top_k: int = 5

    data_dir: str = "./data"
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
