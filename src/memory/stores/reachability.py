"""Root-reachability sweep for the knowledge graph.

A node is "live" if it's reachable from the user root via any sequence of
relationships (direction-agnostic). Anything else is an island left behind
by a merge, a stale edge deletion, or an analyzer bug.

The sweep doesn't delete — it adds a ``:Quarantine`` label and a
``quarantined_at`` timestamp. Read paths filter quarantined nodes out by
default; a separate manual or scheduled step decides whether to reattach
or purge.

Called from ``graph_write`` after each successful batch commit. Cheap on
a single-user graph (thousands of nodes); at >10k nodes, switch to
``apoc.path.subgraphNodes`` scoped to the touched subgraph.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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


def quarantine_unreachable(driver, now_iso: str) -> int:
    """Label nodes unreachable from the user root with ``:Quarantine``.

    Returns the count newly quarantined this run. Returns 0 if the root
    hasn't been bootstrapped yet — without a root, "reachable from root"
    is undefined and we'd quarantine the entire graph, which is wrong.
    """
    if driver is None:
        return 0
    try:
        with driver.session() as session:
            # Bail out if there's no root — quarantining everything is worse
            # than doing nothing.
            check = session.run(
                "MATCH (r:Person:User {is_root: true}) RETURN count(r) AS c"
            ).single()
            if not check or check["c"] == 0:
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
