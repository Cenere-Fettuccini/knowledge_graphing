from google import genai

from src.core.config import settings


class GoogleEmbeddingModel:
    """Small adapter around Google's native embedding API."""

    def __init__(self):
        api_key = settings.api_keys[0] if settings.api_keys else ""
        self._client = genai.Client(api_key=api_key)
        self._model = "gemini-embedding-2"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self._client.models.embed_content(
            model=self._model,
            contents=texts,
        )
        return [embedding.values for embedding in response.embeddings]


def get_embedding_model() -> GoogleEmbeddingModel:
    """Returns the configured Google Generative AI embedding model."""
    return GoogleEmbeddingModel()
