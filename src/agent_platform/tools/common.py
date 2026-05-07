from __future__ import annotations

import logging

from src.memory.manager import memory_manager

logger = logging.getLogger(__name__)


def ensure_graph_online() -> str | None:
    if not memory_manager.neo4j.driver:
        return "Knowledge Graph is currently offline."
    return None
