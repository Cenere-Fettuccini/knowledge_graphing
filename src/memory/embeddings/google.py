from langchain_google_genai import GoogleGenerativeAIEmbeddings
from src.core.config import settings

def get_embedding_model():
    """Returns the configured Google Generative AI embedding model."""
    # Use the first available API key for embeddings
    key = settings.api_keys[0] if settings.api_keys else ""
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-2",
        google_api_key=key
    )
