from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Telegram ---
    telegram_bot_token: str
    allowed_user_id: str  # Comma-separated list for multi-user support, e.g. "123,456"

    # --- LLM ---
    google_api_key: str
    llm_model: str = "gemini-2.5-flash"
    llm_temperature: float = 0.7
    embedding_model: str = "models/gemini-embedding-2"

    # --- LM Studio ---
    lm_studio_base_url: str | None = None
    lm_studio_model: str | None = None

    # --- Session ---
    session_store_path: str | None = None

    # --- ChromaDB ---
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection: str = "conversations"

    # --- Neo4j ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # --- Rumination Engine ---
    rumination_interval_hours: int = 6
    rumination_batch_size: int = 50
    taxonomy_bloat_threshold: int = 50

    # --- Agent ---
    context_window_turns: int = 20
    rag_top_k: int = 5

    # --- Explorer / FastAPI ---
    explorer_host: str = "127.0.0.1"
    explorer_port: int = 8000

    @property
    def allowed_user_ids(self) -> set[str]:
        """Parse the comma-separated ALLOWED_USER_ID into a set of strings."""
        return {uid.strip() for uid in self.allowed_user_id.split(",")}

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# Singleton — import this everywhere instead of instantiating Settings() each time.
settings = Settings()