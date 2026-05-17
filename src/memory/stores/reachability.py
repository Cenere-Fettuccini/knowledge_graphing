"""Root-reachability sweep for the knowledge graph.

A node is "live" if it's reachable from the user root via any sequence of
relationships (direction-agnostic). Anything else is an island left behind
by a merge, a stale edge deletion, or an analyzer bug.

**Hot path** (called after every successful batch commit):
  1. ``detect_orphans()``   — find unreachable nodes, return their props
  2. Orphan reattachment analyzer runs RAG + Gemini Flash to propose a
     meaningful edge for each orphan and writes it via MemoryManager
  3. ``prune_orphaned_links()`` — remove any stale ``ORPHANED_LINK`` edges
     from nodes that now have a real path to root

**Manual / scheduled helpers** (not on the hot path):
  ``quarantine_unreachable()``, ``unquarantine()``, ``purge_quarantined()``
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_DETECT_ORPHANS_CYPHER = """
MATCH (root:Person:User {is_root: true})
WITH root
MATCH (n)
WHERE n <> root
  AND NOT n:Quarantine
  AND NOT (root)-[*]-(n)
RETURN n.id AS id, n.name AS name, labels(n) AS labels,
       n.description AS description, n.content AS content
"""


_PRUNE_ORPHANED_LINKS_CYPHER = """
MATCH (root:Person:User {is_root: true})-[r:ORPHANED_LINK]->(n)
WHERE (root)-[*2..]-(n)
DELETE r
RETURN count(r) AS pruned
"""

_QUARANTINE_UNREACHABLE_CYPHER = """
MATCH (root:Person:User {is_root: true})
WITH root
MATCH (n)
WHERE n <> root
  AND NOT n:Quarantine
  AND NOT (root)-[*]-(n)
SET n:Quarantine, n.quarantined_at = $now
RETURN count(n) AS quarantined
"""


def _root_exists(session) -> bool:
    check = session.run(
        "MATCH (r:Person:User {is_root: true}) RETURN count(r) AS c"
    ).single()
    return bool(check and check["c"] > 0)


def detect_orphans(driver) -> list[dict]:
    """Return unreachable nodes as dicts without writing anything.

    Each dict: ``{"id", "name", "labels", "description", "content"}``.
    Returns ``[]`` if the root doesn't exist yet.
    """
    if driver is None:
        return []
    try:
        with driver.session() as session:
            if not _root_exists(session):
                return []
            rows = session.run(_DETECT_ORPHANS_CYPHER)
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "labels": list(r["labels"] or []),
                    "description": r["description"],
                    "content": r["content"],
                }
                for r in rows
            ]
    except Exception as e:
        logger.error("detect_orphans failed: %s", e)
        return []



def prune_orphaned_links(driver) -> int:
    """Delete ORPHANED_LINK edges from nodes that now have a real path to root.

    Called post-commit so stale fallback edges don't accumulate once the node
    has been properly connected by extraction or reattachment.
    Returns the number of edges deleted.
    """
    if driver is None:
        return 0
    try:
        with driver.session() as session:
            if not _root_exists(session):
                return 0
            result = session.run(_PRUNE_ORPHANED_LINKS_CYPHER).single()
            count = int(result["pruned"]) if result else 0
            if count:
                logger.info("reachability: pruned %d stale ORPHANED_LINK edge(s)", count)
            return count
    except Exception as e:
        logger.error("prune_orphaned_links failed: %s", e)
        return 0


def quarantine_unreachable(driver, now_iso: str) -> int:
    """Label nodes unreachable from the user root with ``:Quarantine``.

    Not on the hot write path — use for manual / scheduled passes.
    Returns the count newly quarantined.
    """
    if driver is None:
        return 0
    try:
        with driver.session() as session:
            if not _root_exists(session):
                return 0
            result = session.run(_QUARANTINE_UNREACHABLE_CYPHER, now=now_iso).single()
            count = int(result["quarantined"]) if result else 0
            if count:
                logger.info("reachability sweep: quarantined %d node(s)", count)
            return count
    except Exception as e:
        logger.error("reachability sweep failed: %s", e)
        return 0


def unquarantine(driver, node_id: str) -> bool:
    """Lift the ``:Quarantine`` label from a single node."""
    if driver is None:
        return False
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (n:Quarantine {id: $node_id})
                REMOVE n:Quarantine
                REMOVE n.quarantined_at
                RETURN count(n) AS lifted
                """,
                node_id=node_id,
            ).single()
            return bool(result and result["lifted"] > 0)
    except Exception as e:
        logger.error("unquarantine(%s) failed: %s", node_id, e)
        return False


def purge_quarantined(driver, older_than_iso: str) -> int:
    """DETACH DELETE quarantined nodes older than the cutoff. Returns count."""
    if driver is None:
        return 0
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (n:Quarantine)
                WHERE n.quarantined_at < $cutoff
                WITH collect(n) AS doomed
                FOREACH (x IN doomed | DETACH DELETE x)
                RETURN size(doomed) AS deleted
                """,
                cutoff=older_than_iso,
            ).single()
            return int(result["deleted"]) if result else 0
    except Exception as e:
        logger.error("purge_quarantined failed: %s", e)
        return 0
