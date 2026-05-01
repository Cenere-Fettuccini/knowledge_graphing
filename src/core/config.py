"""Application-wide settings loaded from .env via pydantic-settings.

Every module that needs configuration imports the singleton:

    from src.core.config import settings
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed, validated settings with automatic .env loading."""

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str
    allowed_user_id: str  # comma-separated list of Telegram user IDs

    # ── LLM (placeholder — not wired yet) ─────────────────────────────────────
    google_api_key: str = ""
    llm_model: str = "models/gemini-2.5-flash"
    llm_temperature: float = 0.7

    # ── Local LLM (LM Studio — optional) ─────────────────────────────────────
    lm_studio_base_url: str = "http://localhost:1234/v1"
    lm_studio_model: str = "qwen2.5-3b-instruct"

    # ── Session persistence ───────────────────────────────────────────────────
    session_store_path: str = "./data/sessions.json"

    # ── ChromaDB (placeholder) ────────────────────────────────────────────────
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection: str = "conversations"

    # ── Neo4j (placeholder) ───────────────────────────────────────────────────
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # ── Agent (placeholder) ───────────────────────────────────────────────────
    context_window_turns: int = 20
    rag_top_k: int = 5

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def allowed_user_ids(self) -> set[str]:
        """Parse the comma-separated whitelist into a set of string IDs."""
        return {uid.strip() for uid in self.allowed_user_id.split(",") if uid.strip()}

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
