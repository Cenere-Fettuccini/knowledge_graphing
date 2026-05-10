"""CLI utilities for querying and inspecting the memory subsystem.

Usage:
    python -m src.tools.memory_tools search "what did I say about work?"
    python -m src.tools.memory_tools recent 20
    python -m src.tools.memory_tools unanalyzed
    python -m src.tools.memory_tools status
"""

import json
import logging
import sys

from src.core.logging_config import setup_logging
from src.memory.manager import get_memory_manager

setup_logging()
logger = logging.getLogger(__name__)


def search_memories(query: str, k: int = 5) -> list[dict]:
    """Semantic search over all stored memories."""
    return get_memory_manager().search(query, k=k)


def get_recent(n: int = 20) -> list[dict]:
    """Return the n most recent memory entries across all sessions."""
    return get_memory_manager().get_recent_memories(n=n)


def list_unanalyzed(limit: int = 20) -> list[dict]:
    """Return conversation turns still waiting to be analyzed."""
    return get_memory_manager().list_unanalyzed(limit=limit)


def memory_status() -> dict:
    """Return health status of all memory backends."""
    return get_memory_manager().status()


def _print(data) -> None:
    print(json.dumps(data, indent=2, default=str))


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd, *rest = args

    if cmd == "search":
        if not rest:
            print("Usage: memory_tools search <query>")
            sys.exit(1)
        _print(search_memories(" ".join(rest)))

    elif cmd == "recent":
        n = int(rest[0]) if rest else 20
        _print(get_recent(n))

    elif cmd == "unanalyzed":
        limit = int(rest[0]) if rest else 20
        _print(list_unanalyzed(limit))

    elif cmd == "status":
        _print(memory_status())

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
