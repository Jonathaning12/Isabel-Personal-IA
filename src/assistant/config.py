"""Application settings.

All configuration (API keys, model IDs, URLs, limits) is read from environment
variables / the `.env` file. Nothing secret or model-specific is hardcoded in code.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Inference provider. "nebius" is the default and the only one allowed for the
    # hackathon submission; "gemini" exists for local testing only.
    llm_provider: Literal["nebius", "gemini"] = "nebius"

    # Nebius Token Factory (OpenAI-compatible API)
    nebius_api_key: SecretStr = SecretStr("")
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"

    # Google Gemini through its OpenAI-compatible endpoint (testing only)
    gemini_api_key: SecretStr = SecretStr("")
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    # Natural spoken replies (Gemini text-to-speech; native API, not OpenAI-compatible)
    gemini_native_url: str = "https://generativelanguage.googleapis.com/v1beta"
    tts_model: str = "gemini-3.8-flash-lite-tts"
    tts_fallback_model: str = "gemini-2.5-flash-preview-tts"  # tried when the main one is slow
    tts_attempt_timeout_s: float = 7.0  # per model; the app waits up to ~16 s in total
    tts_voice: str = "Achernar"
    # Local voice service (Piper, see services/voice). Empty = not used.
    local_voice_url: str = ""
    local_voice_timeout_s: float = 20.0
    # Web search (Gemini with Google Search grounding); falls back to LLM_MODEL
    search_model: str = "gemini-flash-latest"
    brave_api_key: SecretStr = SecretStr("")  # optional: Brave Search API (free tier)

    # Model IDs belong to the selected provider.
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

    # Obsidian vault (mounted at /vault by docker-compose from OBSIDIAN_VAULT on the host).
    # None = no vault: the note tools answer that it is not configured.
    vault_dir: Path | None = None
    obsidian_vault_name: str = ""  # for obsidian:// links in the desktop app

    # Projects folder (mounted at /projects from PROJECTS_HOST): folders and git repos.
    projects_dir: Path | None = None
    projects_name: str = "Documentos"  # how the user calls that folder
    projects_host_path: str = ""  # the same folder as seen by Windows (for the desktop app)
    github_token: SecretStr = SecretStr("")  # for git push to GitHub (HTTPS)
    git_autocrlf: str = "true"  # match the user's Windows git (line endings)

    @field_validator("vault_dir", "projects_dir", mode="before")
    @classmethod
    def empty_vault_is_none(cls, value: object) -> object:
        # docker-compose passes VAULT_DIR="" when no vault is configured.
        return None if value in ("", None) else value

    # Retrieval and long-term memory
    retrieval_top_k: int = Field(default=5, gt=0)
    retrieval_min_score: float = 0.42  # calibrated with scripts/eval_retrieval.py
    fact_dedup_threshold: float = 0.9
    # Facts this similar (but below the dedup threshold) are checked for contradictions.
    fact_related_threshold: float = 0.6
    # Past-conversation summaries at least this similar to the message go into the prompt.
    episode_min_score: float = 0.45
    # Only the last N user turns go to the model in full; older ones are covered by the
    # conversation's summary (episode). Keeps every request small and fast.
    history_turns: int = 6
    # Gemini thinking level for normal answers (low | medium | high); helpers use minimal.
    llm_reasoning_effort: str = "medium"  # "low" was faster but slipped on date math
    # Learn facts the user mentions in passing (one extra cheap LLM call per message).
    auto_learn: bool = True

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
    # Bearer token for every route but /health. Empty: generated once into data/api_token.
    api_token: SecretStr = SecretStr("")
    require_token: bool = True  # false only in unit tests

    # Privacy
    log_prompts: bool = False

    @property
    def inference_base_url(self) -> str:
        """Base URL of the selected provider's OpenAI-compatible API."""
        return self.gemini_base_url if self.llm_provider == "gemini" else self.nebius_base_url

    @property
    def inference_api_key(self) -> str:
        """API key of the selected provider (empty if not set)."""
        key = self.gemini_api_key if self.llm_provider == "gemini" else self.nebius_api_key
        return key.get_secret_value()

    @property
    def api_key_name(self) -> str:
        """Name of the .env variable that holds the selected provider's key."""
        return "GEMINI_API_KEY" if self.llm_provider == "gemini" else "NEBIUS_API_KEY"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read .env once per process)."""
    return Settings()  # type: ignore[call-arg]
