"""Application-wide settings loaded from .env via pydantic-settings.

Every module that needs configuration imports the singleton:

    from src.core.config import settings
"""

from pydantic import Field, PrivateAttr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed, validated settings with automatic .env loading."""

    _google_key_configs_override: list[dict[str, str]] | None = PrivateAttr(default=None)

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
    lm_studio_model: str = "google/gemma-4-e4b"

    # ── Knowledge analyzer ───────────────────────────────────────────────────
    # Disabled by default after S0.10 — the count-triggered ingestion path
    # (graph_ingest_trigger + graph_write) replaces the time-based extraction
    # tick. Flip back to True only if you need to fall back to the legacy
    # direct-write KnowledgeAnalyzer.
    analyzer_enabled: bool = False
    analyzer_tick_seconds: int = 900   # how often the auto-drain scheduler ticks
    analyzer_batch_size: int = 20      # Chroma rows per LLM call

    # Bulk-mode pacing: when the unanalyzed queue exceeds the threshold the
    # scheduler switches to tighter ticks and a larger batch so a backfill
    # (journal import, history dump, etc.) drains in hours rather than days.
    # Falls back to the normal pacing as soon as the queue is below the
    # threshold again.
    analyzer_bulk_threshold: int = 100        # depth that flips bulk mode on
    analyzer_bulk_tick_seconds: int = 60
    analyzer_bulk_batch_size: int = 100

    # ── Session persistence ───────────────────────────────────────────────────
    session_store_path: str = "./data/sessions.json"

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection: str = "conversations"

    # ── Spillover (write-ahead for DB failures) ───────────────────────────────
    spillover_dir: str = "./data/spillover"

    # ── Graph ingest (shared-secret HTTP entry point for batch writes) ───────
    # Set to a long random string in .env to enable POST /graph/ingest.
    # Leave empty to disable the endpoint entirely.
    graph_ingest_secret: str = ""

    # When the unanalyzed Chroma queue reaches this depth, the count-triggered
    # ingestion job fires and routes the backlog through graph_write. Set to
    # 0 to disable the trigger entirely (the analyzer scheduler still runs).
    graph_ingest_threshold: int = 20

    # When this many rows are flagged ``belief_candidate: true`` and haven't
    # been processed by the cloud pass yet, fire the cloud belief extractor.
    # Lower default than graph_ingest_threshold because cloud calls cost
    # real money. 0 disables the auto-trigger; manual /analyze/beliefs/extract
    # still works.
    cloud_belief_threshold: int = 10

    # ── Proactive bot (S3.3 / S4.2 / S4.4) ───────────────────────────────────
    # Started inside run_bot.py when the bot process boots. Set to False to
    # disable all outbound jobs without touching the bot itself.
    proactive_bot_enabled: bool = True
    digest_hour_local: int = 18
    digest_minute_local: int = 30
    digest_max_items: int = 8
    soft_archive_dormant_days: int = 180  # ~6 months
    soft_archive_check_weekday: str = "sun"  # APScheduler weekday short name

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # ── Web search (Google Custom Search) ────────────────────────────────────
    google_cse_id: str = ""          # Custom Search Engine ID from cse.google.com

    # ── Google Calendar ───────────────────────────────────────────────────────
    google_calendar_credentials_path: str = "./data/google_calendar_creds.json"
    google_calendar_token_path: str = "./data/google_calendar_token.json"

    # ── Rumination Engine ─────────────────────────────────────────────────────
    rumination_enabled: bool = False       # off by default — heavy LLM workload
    deep_pass_tick_seconds: int = 3600     # belief deep-analysis interval
    rabbit_hole_tick_seconds: int = 7200   # creative synthesis interval

    # ── Agent ─────────────────────────────────────────────────────────────────
    context_window_turns: int = 20
    rag_top_k: int = 5
    log_level: str = "INFO"

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
        if self._google_key_configs_override is not None:
            return self._google_key_configs_override
        return [
            {"api_key": api_key, "project_scope": project_scope}
            for api_key, project_scope in zip(self.api_keys, self.project_scopes)
        ]

    @google_key_configs.setter
    def google_key_configs(self, value: list[dict[str, str]]) -> None:
        """Allow tests to override computed key configs on the singleton instance."""
        self._google_key_configs_override = value

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
