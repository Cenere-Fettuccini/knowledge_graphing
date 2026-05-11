"""Unit tests for the entity canonicalizer (S2.4)."""

from __future__ import annotations

from src.agent_platform.analyzers.canonicalize import (
    BeliefCanonicalizer,
    DEFAULT_BELIEF_THRESHOLD,
    EntityCanonicalizer,
    _cluster_by_cosine,
    _proposal_id,
)


class _StubEmbedder:
    """Returns whatever vectors the test sets up, keyed by name."""

    def __init__(self, vectors_by_name: dict[str, list[float]]):
        self._vectors = vectors_by_name

    def embed_documents(self, texts):
        return [self._vectors[t] for t in texts]


class _StubMemory:
    """Records calls to the canonicalization-facing memory surface."""

    def __init__(
        self,
        labels: list[str],
        nodes_by_label: dict[str, list[dict]],
        degrees: dict[str, int] | None = None,
        existing_proposals: dict[str, dict] | None = None,
    ):
        self._labels = labels
        self._nodes_by_label = nodes_by_label
        self._degrees = degrees or {}
        self._existing = existing_proposals or {}
        self.created: list[dict] = []
        self.list_label_args: list[str] = []

    def list_distinct_graph_labels(self, *, exclude=None):
        exclude = exclude or set()
        return [l for l in self._labels if l not in exclude]

    def list_named_nodes_by_label(self, label, *, exclude_roots=True):
        self.list_label_args.append(label)
        return list(self._nodes_by_label.get(label, []))

    def count_node_connections(self, node_ids):
        return {nid: self._degrees.get(nid, 0) for nid in node_ids}

    def get_merge_proposal(self, proposal_id):
        return self._existing.get(proposal_id)

    def create_merge_proposal(
        self,
        *,
        proposal_id,
        label,
        primary_id,
        duplicate_ids,
        scores,
        canonical_name,
    ):
        self.created.append({
            "proposal_id": proposal_id,
            "label": label,
            "primary_id": primary_id,
            "duplicate_ids": list(duplicate_ids),
            "scores": list(scores),
            "canonical_name": canonical_name,
        })
        return proposal_id


# ── _cluster_by_cosine ───────────────────────────────────────────────────────

def test_cluster_by_cosine_groups_above_threshold():
    nodes = [
        {"id": "person:mom", "name": "mom"},
        {"id": "person:my-mother", "name": "my mother"},
        {"id": "person:dad", "name": "dad"},
    ]
    # mom & my-mother nearly identical (sim ≈ 1.0); dad orthogonal.
    vectors = [
        [1.0, 0.0, 0.0],
        [0.999, 0.045, 0.0],
        [0.0, 0.0, 1.0],
    ]
    clusters = _cluster_by_cosine(nodes, vectors, threshold=0.92)
    assert len(clusters) == 1
    members, scores = clusters[0]
    assert {n["id"] for n in members} == {"person:mom", "person:my-mother"}
    assert scores and scores[0] >= 0.92


def test_cluster_by_cosine_returns_empty_when_below_threshold():
    nodes = [
        {"id": "a", "name": "alpha"},
        {"id": "b", "name": "beta"},
    ]
    vectors = [[1.0, 0.0], [0.0, 1.0]]
    assert _cluster_by_cosine(nodes, vectors, threshold=0.92) == []


def test_cluster_by_cosine_chains_transitive_links_via_union_find():
    """A→B and B→C above threshold puts all three in the same cluster, even
    if A→C alone wouldn't quite clear the bar."""
    nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    vectors = [
        [1.0, 0.0],
        [0.96, 0.28],   # close to both a and c
        [0.85, 0.53],
    ]
    clusters = _cluster_by_cosine(nodes, vectors, threshold=0.92)
    assert len(clusters) == 1
    assert {n["id"] for n in clusters[0][0]} == {"a", "b", "c"}


# ── EntityCanonicalizer.propose_merges ──────────────────────────────────────

def test_propose_merges_acceptance_case_mom_and_my_mother():
    """Seed two near-duplicate Person nodes; expect exactly one proposal."""
    nodes = [
        {"id": "person:mom", "name": "mom", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "person:my-mother", "name": "my mother", "created_at": "2024-06-01T00:00:00Z"},
    ]
    memory = _StubMemory(
        labels=["Person"],
        nodes_by_label={"Person": nodes},
        degrees={"person:mom": 4, "person:my-mother": 1},
    )
    embedder = _StubEmbedder({
        "mom": [1.0, 0.0],
        "my mother": [0.99, 0.02],
    })

    canon = EntityCanonicalizer(memory=memory, embedder=embedder)
    result = canon.propose_merges(threshold=0.92)

    assert result.proposals_created == 1
    assert result.labels_scanned == 1
    assert result.nodes_scanned == 2

    assert len(memory.created) == 1
    proposal = memory.created[0]
    assert proposal["label"] == "Person"
    # `person:mom` has more connections, so it's the canonical primary.
    assert proposal["primary_id"] == "person:mom"
    assert proposal["duplicate_ids"] == ["person:my-mother"]
    assert proposal["canonical_name"] == "mom"


def test_propose_merges_picks_oldest_when_degrees_tie():
    """With equal degree, the older node wins (it likely anchors older facts)."""
    nodes = [
        {"id": "a", "name": "alpha", "created_at": "2024-06-01T00:00:00Z"},
        {"id": "b", "name": "alpha-2", "created_at": "2023-01-01T00:00:00Z"},
    ]
    memory = _StubMemory(
        labels=["Thing"],
        nodes_by_label={"Thing": nodes},
        degrees={"a": 0, "b": 0},
    )
    embedder = _StubEmbedder({"alpha": [1.0, 0.0], "alpha-2": [0.99, 0.01]})

    canon = EntityCanonicalizer(memory=memory, embedder=embedder)
    canon.propose_merges()

    assert memory.created[0]["primary_id"] == "b"


def test_propose_merges_skips_when_proposal_already_exists():
    nodes = [
        {"id": "x", "name": "Foo"},
        {"id": "y", "name": "Foo-2"},
    ]
    proposal_id = _proposal_id("Thing", nodes)
    memory = _StubMemory(
        labels=["Thing"],
        nodes_by_label={"Thing": nodes},
        existing_proposals={proposal_id: {"status": "dismissed"}},
    )
    embedder = _StubEmbedder({"Foo": [1.0, 0.0], "Foo-2": [0.99, 0.01]})

    canon = EntityCanonicalizer(memory=memory, embedder=embedder)
    result = canon.propose_merges()

    assert result.proposals_created == 0
    assert result.proposals_skipped == 1
    assert memory.created == []


def test_propose_merges_skips_labels_with_single_node():
    memory = _StubMemory(
        labels=["Person"],
        nodes_by_label={"Person": [{"id": "only", "name": "Only"}]},
    )
    embedder = _StubEmbedder({"Only": [1.0]})
    canon = EntityCanonicalizer(memory=memory, embedder=embedder)
    result = canon.propose_merges()
    assert result.proposals_created == 0


def test_propose_merges_excludes_internal_labels_by_default():
    """Belief / MergeProposal / Era are off-limits for entity canonicalization."""
    memory = _StubMemory(
        labels=["Person", "Belief", "MergeProposal", "Era"],
        nodes_by_label={
            "Person": [
                {"id": "p1", "name": "Alice"},
                {"id": "p2", "name": "alice"},
            ],
            "Belief": [
                {"id": "b1", "name": "Belief A"},
                {"id": "b2", "name": "Belief B"},
            ],
        },
    )
    embedder = _StubEmbedder({
        "Alice": [1.0, 0.0],
        "alice": [0.99, 0.01],
    })
    canon = EntityCanonicalizer(memory=memory, embedder=embedder)
    canon.propose_merges()

    assert memory.list_label_args == ["Person"]
    assert all(p["label"] == "Person" for p in memory.created)


def test_propose_merges_records_embedder_errors_and_continues():
    class BoomEmbedder:
        def embed_documents(self, texts):
            raise RuntimeError("api down")

    memory = _StubMemory(
        labels=["Person"],
        nodes_by_label={"Person": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]},
    )
    canon = EntityCanonicalizer(memory=memory, embedder=BoomEmbedder())
    result = canon.propose_merges()

    assert result.proposals_created == 0
    assert any("embedding failed" in e for e in result.errors)


class _BeliefStubMemory:
    """Minimal memory stub focused on the belief-canonicalization surface."""

    def __init__(
        self,
        beliefs: list[dict],
        degrees: dict[str, int] | None = None,
        existing_proposals: dict[str, dict] | None = None,
    ):
        self._beliefs = beliefs
        self._degrees = degrees or {}
        self._existing = existing_proposals or {}
        self.created: list[dict] = []

    def list_active_beliefs(self, limit: int = 1000):
        return list(self._beliefs)[:limit]

    def count_node_connections(self, node_ids):
        return {nid: self._degrees.get(nid, 0) for nid in node_ids}

    def get_merge_proposal(self, proposal_id):
        return self._existing.get(proposal_id)

    def create_merge_proposal(
        self,
        *,
        proposal_id,
        label,
        primary_id,
        duplicate_ids,
        scores,
        canonical_name,
    ):
        self.created.append({
            "proposal_id": proposal_id,
            "label": label,
            "primary_id": primary_id,
            "duplicate_ids": list(duplicate_ids),
            "scores": list(scores),
            "canonical_name": canonical_name,
        })
        return proposal_id


# ── BeliefCanonicalizer ──────────────────────────────────────────────────────

def test_belief_canonicalizer_acceptance_pair_with_near_identical_content():
    """Two beliefs phrased differently for the same conviction must surface as a merge candidate."""
    beliefs = [
        {
            "id": "belief:1",
            "content": "I prefer working alone on hard problems.",
            "confidence": 0.8,
            "created_at": "2024-02-01T00:00:00Z",
        },
        {
            "id": "belief:2",
            "content": "Working alone on hard problems is what I prefer.",
            "confidence": 0.7,
            "created_at": "2024-09-01T00:00:00Z",
        },
    ]
    memory = _BeliefStubMemory(
        beliefs=beliefs,
        degrees={"belief:1": 5, "belief:2": 1},
    )
    embedder = _StubEmbedder({
        beliefs[0]["content"]: [1.0, 0.0, 0.0],
        beliefs[1]["content"]: [0.95, 0.10, 0.0],
    })

    canon = BeliefCanonicalizer(memory=memory, embedder=embedder)
    result = canon.propose_merges()

    assert result.proposals_created == 1
    assert result.nodes_scanned == 2
    proposal = memory.created[0]
    assert proposal["label"] == "Belief"
    # The more-connected belief becomes the canonical primary.
    assert proposal["primary_id"] == "belief:1"
    assert proposal["duplicate_ids"] == ["belief:2"]
    assert proposal["canonical_name"] == beliefs[0]["content"]


def test_belief_canonicalizer_uses_lower_default_threshold():
    """Paraphrased beliefs at sim 0.89 should cluster — that's the whole point of the 0.88 default."""
    assert DEFAULT_BELIEF_THRESHOLD < 0.92
    beliefs = [
        {"id": "b1", "content": "X causes Y", "confidence": 0.5, "created_at": "2024-01-01"},
        {"id": "b2", "content": "Y is caused by X", "confidence": 0.5, "created_at": "2024-02-01"},
    ]
    memory = _BeliefStubMemory(beliefs=beliefs)
    embedder = _StubEmbedder({
        beliefs[0]["content"]: [1.0, 0.0],
        # Cosine ≈ 0.891 — over 0.88, under 0.92.
        beliefs[1]["content"]: [0.891, 0.454],
    })
    canon = BeliefCanonicalizer(memory=memory, embedder=embedder)
    result = canon.propose_merges()
    assert result.proposals_created == 1


def test_belief_canonicalizer_breaks_degree_ties_by_confidence():
    beliefs = [
        {"id": "b1", "content": "alpha", "confidence": 0.4, "created_at": "2024-01-01"},
        {"id": "b2", "content": "alpha-near", "confidence": 0.9, "created_at": "2024-02-01"},
    ]
    memory = _BeliefStubMemory(beliefs=beliefs, degrees={"b1": 0, "b2": 0})
    embedder = _StubEmbedder({
        "alpha": [1.0, 0.0],
        "alpha-near": [0.99, 0.01],
    })
    canon = BeliefCanonicalizer(memory=memory, embedder=embedder)
    canon.propose_merges()

    # Equal degree → higher confidence wins.
    assert memory.created[0]["primary_id"] == "b2"


def test_belief_canonicalizer_skips_existing_proposal():
    beliefs = [
        {"id": "b1", "content": "X", "confidence": 0.5, "created_at": "2024-01-01"},
        {"id": "b2", "content": "X-near", "confidence": 0.5, "created_at": "2024-02-01"},
    ]
    proposal_id = _proposal_id("Belief", beliefs)
    memory = _BeliefStubMemory(
        beliefs=beliefs,
        existing_proposals={proposal_id: {"status": "applied"}},
    )
    embedder = _StubEmbedder({"X": [1.0, 0.0], "X-near": [0.99, 0.01]})

    canon = BeliefCanonicalizer(memory=memory, embedder=embedder)
    result = canon.propose_merges()

    assert result.proposals_created == 0
    assert result.proposals_skipped == 1
    assert memory.created == []


def test_belief_canonicalizer_handles_empty_pool():
    memory = _BeliefStubMemory(beliefs=[])
    canon = BeliefCanonicalizer(memory=memory, embedder=_StubEmbedder({}))
    result = canon.propose_merges()
    assert result.proposals_created == 0
    assert result.nodes_scanned == 0


def test_proposal_id_is_deterministic_regardless_of_member_order():
    """Same cluster signature must produce the same id even if listed in
    different orders — otherwise repeat runs would duplicate proposals."""
    a = {"id": "x"}
    b = {"id": "y"}
    assert _proposal_id("Person", [a, b]) == _proposal_id("Person", [b, a])
