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

    # Local storage
    qdrant_url: str = "http://localhost:6333"
    data_dir: Path = Path("./data")

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Privacy
    log_prompts: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read .env once per process)."""
    return Settings()  # type: ignore[call-arg]
