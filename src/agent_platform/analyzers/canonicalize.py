"""Entity canonicalization — propose merges for near-duplicate nodes.

For every entity label in the graph (excluding belief/scaffolding types
handled elsewhere), the canonicalizer fetches the label's named nodes,
embeds their ``name`` values, and clusters pairs whose cosine similarity
exceeds a configurable threshold (default 0.92). Each cluster becomes one
``:MergeProposal`` node that the user reviews and applies via the explorer.

This is a *cold* pass — it never auto-merges. The acceptance criterion is
that ``person:mom`` and ``person:my-mother`` end up in the same proposal,
not that they get silently collapsed.
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from typing import Iterable

from src.memory.embeddings.google import get_embedding_model
from src.memory.protocol import MemoryProtocol
from src.memory.stores.neo4j_store import Neo4jStore

logger = logging.getLogger(__name__)


DEFAULT_THRESHOLD = 0.92
# Beliefs are paraphrased much more than entity names, so the bar for clustering
# them sits lower — too tight and identical convictions stay split, too loose
# and unrelated thoughts collapse together. 0.88 is the value tuned in S2.5.
DEFAULT_BELIEF_THRESHOLD = 0.88
DEFAULT_EXCLUDED_LABELS: frozenset[str] = Neo4jStore.CANONICALIZATION_HIDDEN_LABELS


@dataclass
class CanonicalizationResult:
    proposals_created: int = 0
    proposals_skipped: int = 0
    labels_scanned: int = 0
    nodes_scanned: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "proposals_created": self.proposals_created,
            "proposals_skipped": self.proposals_skipped,
            "labels_scanned": self.labels_scanned,
            "nodes_scanned": self.nodes_scanned,
            "errors": self.errors,
        }


class EntityCanonicalizer:
    """Generates merge proposals for near-duplicate entities, grouped by label."""

    def __init__(
        self,
        memory: MemoryProtocol,
        embedder=None,
    ) -> None:
        self._memory = memory
        self._embedder = embedder

    def _get_embedder(self):
        if self._embedder is None:
            self._embedder = get_embedding_model()
        return self._embedder

    def propose_merges(
        self,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        excluded_labels: Iterable[str] | None = None,
        min_label_size: int = 2,
    ) -> CanonicalizationResult:
        """Scan every eligible label, cluster names, and write proposals."""
        excluded = set(excluded_labels if excluded_labels is not None else DEFAULT_EXCLUDED_LABELS)
        labels = self._memory.list_distinct_graph_labels(exclude=excluded)
        result = CanonicalizationResult()

        for label in labels:
            nodes = self._memory.list_named_nodes_by_label(label, exclude_roots=True)
            result.labels_scanned += 1
            result.nodes_scanned += len(nodes)
            if len(nodes) < min_label_size:
                continue

            try:
                vectors = self._get_embedder().embed_documents([n["name"] for n in nodes])
            except Exception as exc:
                msg = f"label {label}: embedding failed ({exc})"
                logger.warning(msg, exc_info=True)
                result.errors.append(msg)
                continue

            if len(vectors) != len(nodes):
                result.errors.append(
                    f"label {label}: embedder returned {len(vectors)} vectors for {len(nodes)} nodes"
                )
                continue

            clusters = _cluster_by_cosine(nodes, vectors, threshold=threshold)
            for cluster_members, cluster_scores in clusters:
                if not self._persist_proposal(label, cluster_members, cluster_scores, result):
                    result.proposals_skipped += 1

        return result

    def _persist_proposal(
        self,
        label: str,
        members: list[dict],
        scores: list[float],
        result: CanonicalizationResult,
    ) -> bool:
        proposal_id = _proposal_id(label, members)
        existing = self._memory.get_merge_proposal(proposal_id)
        if existing is not None:
            # Same cluster signature already seen — don't re-create. Whether it's
            # pending, applied, or dismissed, the user has already had their say.
            return False

        ranking = self._rank_for_primary(members)
        primary = ranking[0]
        duplicates = ranking[1:]

        self._memory.create_merge_proposal(
            proposal_id=proposal_id,
            label=label,
            primary_id=primary["id"],
            duplicate_ids=[n["id"] for n in duplicates],
            scores=scores,
            canonical_name=primary["name"],
        )
        result.proposals_created += 1
        return True

    def _rank_for_primary(self, members: list[dict]) -> list[dict]:
        """Order cluster members so the best canonical sits at index 0.

        Heuristic: most-connected node wins, tie-break by oldest ``created_at``,
        then by shortest name, then by case-insensitive name. The intuition is
        that the most-connected node already anchors the most relationships, so
        merging into it loses the least information.
        """
        ids = [n["id"] for n in members]
        try:
            degrees = self._memory.count_node_connections(ids)
        except Exception:
            logger.warning("count_node_connections failed; falling back to name-only ranking", exc_info=True)
            degrees = {}

        def sort_key(n: dict) -> tuple:
            return (
                -int(degrees.get(n["id"], 0)),
                n.get("created_at") or "9999-12-31",
                len(n.get("name") or ""),
                (n.get("name") or "").lower(),
            )

        return sorted(members, key=sort_key)


class BeliefCanonicalizer:
    """Same clustering machinery as :class:`EntityCanonicalizer`, but for
    active :Belief nodes and keyed on ``content`` (the full sentence) rather
    than ``name``. Threshold defaults to 0.88 because beliefs get
    paraphrased more aggressively than entities.

    Proposals share the :MergeProposal storage and apply path — the apply
    logic is label-agnostic and rewires every relationship type on the
    duplicate.
    """

    LABEL = "Belief"

    def __init__(
        self,
        memory: MemoryProtocol,
        embedder=None,
    ) -> None:
        self._memory = memory
        self._embedder = embedder

    def _get_embedder(self):
        if self._embedder is None:
            self._embedder = get_embedding_model()
        return self._embedder

    def propose_merges(
        self,
        *,
        threshold: float = DEFAULT_BELIEF_THRESHOLD,
        min_pool_size: int = 2,
        limit: int = 1000,
    ) -> CanonicalizationResult:
        """Cluster active beliefs by content similarity and write proposals."""
        result = CanonicalizationResult()
        beliefs = self._memory.list_active_beliefs(limit=limit)
        result.labels_scanned = 1
        result.nodes_scanned = len(beliefs)

        if len(beliefs) < min_pool_size:
            return result

        contents = [b.get("content") or "" for b in beliefs]
        try:
            vectors = self._get_embedder().embed_documents(contents)
        except Exception as exc:
            msg = f"belief embedding failed ({exc})"
            logger.warning(msg, exc_info=True)
            result.errors.append(msg)
            return result

        if len(vectors) != len(beliefs):
            result.errors.append(
                f"embedder returned {len(vectors)} vectors for {len(beliefs)} beliefs"
            )
            return result

        # Normalize the shape so the shared clustering helper can read
        # ``name`` — beliefs use ``content`` natively, but the clustering
        # routine is name-agnostic and just needs an id-bearing dict.
        nodes_for_clustering = [
            {**b, "name": b.get("content") or b.get("name") or ""}
            for b in beliefs
        ]

        clusters = _cluster_by_cosine(
            nodes_for_clustering, vectors, threshold=threshold
        )
        for members, scores in clusters:
            if not self._persist_proposal(members, scores, result):
                result.proposals_skipped += 1
        return result

    def _persist_proposal(
        self,
        members: list[dict],
        scores: list[float],
        result: CanonicalizationResult,
    ) -> bool:
        proposal_id = _proposal_id(self.LABEL, members)
        if self._memory.get_merge_proposal(proposal_id) is not None:
            return False

        ranked = self._rank_for_primary(members)
        primary = ranked[0]
        duplicates = ranked[1:]

        self._memory.create_merge_proposal(
            proposal_id=proposal_id,
            label=self.LABEL,
            primary_id=primary["id"],
            duplicate_ids=[n["id"] for n in duplicates],
            scores=scores,
            canonical_name=primary.get("content") or primary.get("name") or "",
        )
        result.proposals_created += 1
        return True

    def _rank_for_primary(self, members: list[dict]) -> list[dict]:
        """Order so the strongest-evidenced belief is the canonical.

        Heuristic: most-connected (proxy for evidence), tie-break by highest
        confidence, then oldest ``created_at`` (older beliefs already anchor
        more history), then alphabetic on content for full determinism.
        """
        ids = [n["id"] for n in members]
        try:
            degrees = self._memory.count_node_connections(ids)
        except Exception:
            logger.warning(
                "count_node_connections failed; falling back to confidence-only ranking",
                exc_info=True,
            )
            degrees = {}

        def confidence_of(n: dict) -> float:
            try:
                return float(n.get("confidence") or 0.0)
            except (TypeError, ValueError):
                return 0.0

        def sort_key(n: dict) -> tuple:
            return (
                -int(degrees.get(n["id"], 0)),
                -confidence_of(n),
                n.get("created_at") or "9999-12-31",
                (n.get("content") or n.get("name") or "").lower(),
            )

        return sorted(members, key=sort_key)


def _proposal_id(label: str, members: list[dict]) -> str:
    """Deterministic id keyed on the sorted node ids in the cluster."""
    sorted_ids = sorted(n["id"] for n in members if n.get("id"))
    fingerprint = hashlib.sha1("|".join(sorted_ids).encode("utf-8")).hexdigest()[:12]
    return f"merge:{label.lower()}:{fingerprint}"


def _cluster_by_cosine(
    nodes: list[dict],
    vectors: list[list[float]],
    *,
    threshold: float,
) -> list[tuple[list[dict], list[float]]]:
    """Group nodes into clusters where every member is within ``threshold`` of
    at least one other member (single-link via union-find).

    Returns ``[(members, scores)]`` for each cluster with ≥ 2 nodes. ``scores``
    are the pairwise similarities that triggered the merges, in cluster order.
    """
    n = len(nodes)
    if n < 2:
        return []

    norms = [_l2_norm(v) for v in vectors]
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    edges: list[tuple[int, int, float]] = []
    for i in range(n):
        if not norms[i]:
            continue
        for j in range(i + 1, n):
            if not norms[j]:
                continue
            sim = _cosine(vectors[i], vectors[j], norms[i], norms[j])
            if sim >= threshold:
                union(i, j)
                edges.append((i, j, sim))

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(i)

    cluster_edge_scores: dict[int, list[float]] = {}
    for i, j, sim in edges:
        root = find(i)
        cluster_edge_scores.setdefault(root, []).append(round(float(sim), 4))

    output: list[tuple[list[dict], list[float]]] = []
    for root, indices in clusters.items():
        if len(indices) < 2:
            continue
        members = [nodes[k] for k in indices]
        scores = cluster_edge_scores.get(root, [])
        output.append((members, scores))
    return output


def _l2_norm(vec: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vec))


def _cosine(a: list[float], b: list[float], norm_a: float, norm_b: float) -> float:
    if not norm_a or not norm_b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (norm_a * norm_b)
