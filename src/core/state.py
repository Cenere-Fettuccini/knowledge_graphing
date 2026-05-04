from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    """
    The state of the agent's reasoning loop.
    
    Attributes:
        messages: The history of messages in the current turn (including tool calls).
        task_type: The classified type of the task (from TaskAnalyzer).
        is_redacted: Whether the input has been processed by the privacy filter.
        session_id: The current Telegram session ID.
        headroom: The available quota headroom at the start of the loop.
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]
    task_type: str
    is_redacted: bool
    session_id: str
    headroom: float
