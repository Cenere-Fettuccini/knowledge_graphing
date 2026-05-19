"""The three registries (agent / model / tool) populate themselves on
import, expose identity metadata, and raise typed lookup errors on a miss.

This is the contract that lets the rest of the system address an agent
by name (``get_agent_service("chat")``) and know that misnamed
references will fail loudly at boot rather than at request time.
"""

from __future__ import annotations

import pytest

from src.agent import (
    UnknownAgentError,
    UnknownModelError,
    UnknownToolError,
    get_agent_service,
)
from src.agent._agents import all_agents, get_agent_def
from src.agent._agents._base import BaseAgent
from src.agent._models import all_models, get_model
from src.agent._models._base import BaseModel
from src.agent._tools import all_tools, get_tool
from src.agent._tools._base import BaseTool


def test_chat_agent_is_registered_with_its_prompt_model_and_tools():
    """The shipped agent identifies itself via class-level metadata."""
    agent_cls = get_agent_def("chat")
    info = agent_cls.identify()
    assert info["name"] == "chat"
    assert info["model"] == "lmstudio"
    assert info["tools"] == ["recall_recent"]
    assert info["prompt_chars"] > 0
    assert "chat" in BaseAgent.all_names()


def test_lmstudio_model_is_registered_and_identifies():
    model = get_model("lmstudio")
    info = model.identify()
    assert info["name"] == "lmstudio"
    assert "lmstudio" in BaseModel.all_names()


def test_recall_recent_tool_is_registered_with_schema():
    tool = get_tool("recall_recent")
    schema = tool.schema
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "recall_recent"
    assert "session_id" in schema["function"]["parameters"]["properties"]
    assert "recall_recent" in BaseTool.all_names()


def test_unknown_lookups_raise_typed_errors():
    """Each registry raises its own subclass of ``RegistryLookupError``."""
    with pytest.raises(UnknownAgentError, match="ghost"):
        get_agent_def("ghost")
    with pytest.raises(UnknownModelError, match="phantom"):
        get_model("phantom")
    with pytest.raises(UnknownToolError, match="missing_tool"):
        get_tool("missing_tool")


def test_registries_enumerate_all_registered_members():
    assert get_agent_def("chat") in all_agents()
    assert any(m.name == "lmstudio" for m in all_models())
    assert any(t.name == "recall_recent" for t in all_tools())


def test_get_agent_service_defaults_to_chat_and_identifies_itself(fake_llm, text_response):
    """``get_agent_service()`` with no args returns the default chat
    service; ``identify()`` reports the bound agent / model / tools."""
    fake_llm.responses = [text_response("ok")]
    service = get_agent_service()  # defaults to "chat"
    info = service.identify()
    assert info["agent"]["name"] == "chat"
    assert info["model"]["name"] == "fake"  # FakeLLM swapped in by fixture
    assert [t["name"] for t in info["tools"]] == ["recall_recent"]


def test_get_agent_service_raises_unknown_agent_for_misnamed_agent():
    with pytest.raises(UnknownAgentError):
        get_agent_service("not_a_real_agent")
