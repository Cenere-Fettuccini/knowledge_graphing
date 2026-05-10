from __future__ import annotations

import logging

from src.memory.manager import get_memory_manager

logger = logging.getLogger(__name__)


def ensure_graph_online() -> str | None:
    if not get_memory_manager().is_graph_online():
        return "Knowledge Graph is currently offline."
    return None
