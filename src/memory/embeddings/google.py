from langchain_google_genai import GoogleGenerativeAIEmbeddings
from src.core.config import settings

def get_embedding_model():
    """Returns the configured Google Generative AI embedding model."""
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-2",
        google_api_key=settings.google_api_key
    )
