"""Typed exceptions raised out of the agent package.

``AgentRunError`` is part of the public surface — callers catch it to
distinguish degraded turns from caller-input bugs. The ``Unknown*Error``
classes are raised by the agent / model / tool registries when a name
isn't recognised; they share ``RegistryLookupError`` as a parent so
callers can catch the family with one ``except`` if they want.
"""

from __future__ import annotations


class AgentRunError(RuntimeError):
    """Raised by ``AgentService.arun`` when the run cannot produce a reply.

    Covers LLM-unreachable, malformed LLM responses, and iteration-cap
    exhaustion. Callers (typically ``backend.conversation``) catch this
    to surface a degraded turn while keeping the user's message
    persisted.
    """


class RegistryLookupError(LookupError):
    """Base for ``UnknownAgentError`` / ``UnknownModelError`` / ``UnknownToolError``.

    The agent, model, and tool registries each raise a specific subclass
    when an identifier isn't found, so misnamed references fail loudly
    at boot rather than producing surprises at request time.
    """


class UnknownAgentError(RegistryLookupError):
    """No agent is registered under the requested name."""


class UnknownModelError(RegistryLookupError):
    """No model adapter is registered under the requested name."""


class UnknownToolError(RegistryLookupError):
    """No tool is registered under the requested name."""
