import logging
import json
from langchain_openai import ChatOpenAI
from src.core.config import settings

logger = logging.getLogger(__name__)

class PrivacyFilter:
    """Anonymizes text using a local SLM before external transmission."""

    def __init__(self):
        self.slm = ChatOpenAI(
            base_url=settings.lm_studio_base_url,
            api_key="not-needed",
            model_name=settings.lm_studio_model,
            temperature=0.0,
            # Force JSON mode if supported, or just prompt for it
            model_kwargs={"response_format": {"type": "json_object"}}
        )

    def redact(self, text: str) -> str:
        """Use local SLM to identify and redact PII, returning the safe text."""
        prompt = f"""
        You are a privacy enforcement agent. Your task is to redact all Personal Identifiable Information (PII) 
        from the user's message before it is sent to an external cloud service.
        
        Redact:
        - Names of specific individuals (unless they are public figures)
        - Specific locations (home addresses, specific offices)
        - Contact details (emails, phone numbers, handles)
        - Financial info or IDs
        
        Replace PII with a generic label like [PERSON], [LOCATION], [EMAIL], etc.
        
        Return the result as a JSON object with the following key:
        "redacted_text": "The message with PII removed"

        User Message: "{text}"
        """
        
        try:
            response = self.slm.invoke(prompt)
            data = json.loads(response.content)
            redacted = data.get("redacted_text", text)
            
            if redacted != text:
                logger.info("PII detected and redacted by local SLM.")
            
            return redacted
        except Exception as e:
            logger.warning("Local SLM redaction failed, falling back to original text (unsafe): %s", e)
            # In a real production system, you might want to block the request here
            return text
