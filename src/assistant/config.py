"""Application settings.

All configuration (API keys, model IDs, URLs, limits) is read from environment
variables / the `.env` file. Nothing secret or model-specific is hardcoded in code.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Nebius Token Factory (OpenAI-compatible API)
    nebius_api_key: SecretStr
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    llm_model: str
    embed_model: str
    embed_dim: int = Field(gt=0)
    embed_batch_size: int = Field(default=32, gt=0)
    max_completion_tokens: int = Field(default=2048, gt=0)
    llm_timeout_s: float = 60.0
    embed_timeout_s: float = 30.0
    # The user's question is embedded on every chat turn: fail fast if Nebius is slow.
    query_embed_timeout_s: float = 20.0
    query_embed_attempts: int = Field(default=2, gt=0)

    # Local storage
    qdrant_url: str = "http://localhost:6333"
    data_dir: Path = Path("./data")

    # Ingestion: chunk sizes in characters (~4 chars per token → ~800 / ~120 tokens)
    chunk_max_chars: int = Field(default=3200, gt=100)
    chunk_overlap_chars: int = Field(default=480, ge=0)
    max_upload_mb: int = Field(default=20, gt=0)

    # Retrieval and long-term memory
    retrieval_top_k: int = Field(default=5, gt=0)
    retrieval_min_score: float = 0.42  # calibrated with scripts/eval_retrieval.py
    fact_dedup_threshold: float = 0.9

    # Agent
    max_agent_iterations: int = Field(default=6, gt=0)

    # Sandbox (isolated Docker container for code written by the agent)
    sandbox_image: str = "assistant-sandbox:latest"
    sandbox_timeout_s: int = Field(default=30, gt=0)
    sandbox_memory: str = "512m"
    sandbox_cpus: float = Field(default=1.0, gt=0)
    sandbox_max_output_bytes: int = Field(default=65536, gt=0)

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_url: str = "http://127.0.0.1:8000"  # used by the CLI

    # Privacy
    log_prompts: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read .env once per process)."""
    return Settings()  # type: ignore[call-arg]
