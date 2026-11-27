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
    # Empty = run the embedding model on this computer (needs sentence-transformers).
    # Set to the Kaggle URL (same as LLM_BASE_URL) to compute embeddings on Kaggle's GPU instead.
    embedding_base_url: str = ""
    embedding_api_key: str = "not-needed"
    chunk_size: int = 800
    chunk_overlap: int = 150
    top_k: int = 5
    # Passages less similar than this are dropped (cosine, 0-1). Raise it if answers cite unrelated pages.
    min_score: float = 0.2
    # Hybrid retrieval: BM25 keyword ranking fused with the dense ranking (Reciprocal Rank Fusion).
    hybrid_retrieval: bool = True
    rrf_k: int = 60
    # Optional cross-encoder re-ranking of the fused candidates. Empty = off. Needs sentence-transformers,
    # e.g. cross-encoder/ms-marco-MiniLM-L-6-v2 (~90 MB). If it can't load, the fused order is used.
    rerank_model: str = ""
    rerank_candidates: int = 20
    # Most tokens (~4 characters each) of retrieved passages put in one prompt. Overlapping/duplicate passages
    # are removed and neighbouring chunks merged first; then passages are added best-first until this is hit.
    context_budget_tokens: int = 2000
    # Answer verifier for /api/ask: every [S#] must exist and each sentence must be supported by its cited
    # passage (share of content words). Below VERIFY_MIN_SUPPORT the model gets VERIFY_RETRIES more tries,
    # then the answer is returned with grounded=false.
    verify_answers: bool = True
    verify_sentence_support: float = 0.5
    verify_min_support: float = 0.75
    verify_retries: int = 1

    data_dir: str = "./data"
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
