"""Application-wide settings loaded from .env via pydantic-settings.

Every module that needs configuration imports the singleton:

    from src.core.config import settings
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed, validated settings with automatic .env loading."""

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str
    allowed_user_id: str  # comma-separated list of Telegram user IDs

    # ── LLM ───────────────────────────────────────────────────────────────────
    google_api_keys: str = Field(default="", validation_alias="google_api_key")
    google_project_scopes: str = ""
    llm_model: str = "models/gemini-2.5-flash"
    llm_temperature: float = 0.7

    # ── Local LLM (LM Studio — optional) ─────────────────────────────────────
    lm_studio_base_url: str = "http://localhost:1234/v1"
    lm_studio_model: str = "qwen2.5-3b-instruct"

    # ── Session persistence ───────────────────────────────────────────────────
    session_store_path: str = "./data/sessions.json"

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection: str = "conversations"

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # ── Agent ─────────────────────────────────────────────────────────────────
    context_window_turns: int = 20
    rag_top_k: int = 5

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def google_api_key(self) -> str:
        """Backward compatibility for singular key access."""
        return self.api_keys[0] if self.api_keys else ""

    @property
    def api_keys(self) -> list[str]:
        """Parse the comma-separated API keys into a list."""
        return [k.strip() for k in self.google_api_keys.split(",") if k.strip()]

    @property
    def project_scopes(self) -> list[str]:
        """
        Parse comma-separated project scopes for Gemini API keys.

        If omitted, all keys are assumed to share one project-scoped quota pool.
        """
        keys = self.api_keys
        if not keys:
            return []

        raw_scopes = [scope.strip() for scope in self.google_project_scopes.split(",") if scope.strip()]
        if not raw_scopes:
            return ["default"] * len(keys)
        if len(raw_scopes) == 1:
            return raw_scopes * len(keys)
        if len(raw_scopes) < len(keys):
            return raw_scopes + ([raw_scopes[-1]] * (len(keys) - len(raw_scopes)))
        return raw_scopes[:len(keys)]

    @property
    def google_key_configs(self) -> list[dict[str, str]]:
        """Return per-key configs paired with their project-scoped quota bucket."""
        return [
            {"api_key": api_key, "project_scope": project_scope}
            for api_key, project_scope in zip(self.api_keys, self.project_scopes)
        ]

    @property
    def allowed_user_ids(self) -> set[str]:
        """Parse the comma-separated whitelist into a set of string IDs."""
        return {uid.strip() for uid in self.allowed_user_id.split(",") if uid.strip()}

    model_config = {
        "env_file": ".env", 
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }


settings = Settings()
