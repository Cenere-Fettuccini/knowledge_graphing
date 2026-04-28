import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are AIManager, a personal AI assistant with a long memory.
You are attentive, concise, and thoughtful. You remember everything the user tells you.
When you don't know something, say so clearly."""


class Agent:
    """Stateless Gemini-backed agent. Memory wiring comes in Step 3/4."""

    def __init__(self):
        self._llm = ChatGoogleGenerativeAI(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            google_api_key=settings.google_api_key,
        )
        logger.info("Agent initialised (model=%s)", settings.llm_model)

    async def process_message(self, user_id: str, text: str) -> str:
        """
        Process a single user message and return the agent's response.

        Args:
            user_id: Telegram user ID (kept for future memory scoping).
            text:    The raw message text from the user.

        Returns:
            The agent's response as a plain string.
        """
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=text),
        ]

        try:
            response = await self._llm.ainvoke(messages)
            return response.content
        except Exception:
            logger.exception("LLM call failed for user_id=%s", user_id)
            raise