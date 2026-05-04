"""Local SLM-based task classification — identifies complexity without external API calls."""

import logging
import json
from langchain_openai import ChatOpenAI
from src.core.config import settings

logger = logging.getLogger(__name__)

class TaskAnalyzer:
    """Uses a small local model to classify the incoming request."""

    def __init__(self):
        # We use OpenAI compatibility for LM Studio / local LLMs
        self.slm = ChatOpenAI(
            base_url=settings.lm_studio_base_url,
            api_key="not-needed",
            model_name=settings.lm_studio_model,
            temperature=0.0,
        )

    def classify(self, text: str) -> str:
        """Categorise the task into one of the supported types."""
        prompt = f"""
        Classify the following user request into exactly one of these categories:
        - QA: General questions, chat, or simple lookups.
        - EXTRACTION: Turning text into structured data (JSON, Graph nodes, lists).
        - SUMMARIZATION: Compressing long text or summarizing history.
        - CODE: Writing or debugging code.
        - REASONING: Complex, multi-step problems or long document analysis.

        Request: "{text}"

        Category:"""
        
        try:
            response = self.slm.invoke(prompt)
            category = response.content.strip().upper()
            
            # Sanitise
            for valid in ["QA", "EXTRACTION", "SUMMARIZATION", "CODE", "REASONING"]:
                if valid in category:
                    return valid
            return "QA" # Default
        except Exception as e:
            logger.warning("Local task analysis failed (is LM Studio running?): %s", e)
            return "QA"
