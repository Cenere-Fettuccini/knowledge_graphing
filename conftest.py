"""Shared pytest fixtures for all test modules."""

import logging
import shutil
import tempfile
from pathlib import Path

import pytest

from src.memory.stores.neo4j_store import Neo4jStore


_WORKSPACE_TMP_ROOT = Path(__file__).resolve().parent / "data" / "pytest_tmp"
logger = logging.getLogger(__name__)


class _FakeEmbeddingModel:
    """Deterministic local embedder for offline tests."""

    _DIMENSIONS = 16

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._DIMENSIONS
        for token in text.lower().split():
            slot = sum(ord(ch) for ch in token) % self._DIMENSIONS
            vector[slot] += 1.0
        return vector


@pytest.fixture(autouse=True)
def _offline_embeddings(monkeypatch):
    """Keep tests off the network by replacing the Google embedder."""
    monkeypatch.setattr(
        "src.memory.stores.chroma_store.get_embedding_model",
        lambda: _FakeEmbeddingModel(),
    )


@pytest.fixture
def tmp_path():
    """
    Workspace-local replacement for pytest's default tmp_path fixture.

    The default Windows temp location on this machine is intermittently
    permission-restricted, which causes otherwise healthy tests to fail during
    fixture setup. Keeping temporary test data under the repo gives us a stable,
    writable path for local verification.
    """
    _WORKSPACE_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="case-", dir=_WORKSPACE_TMP_ROOT))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_neo4j_test_artifacts():
    """
    Purge graph test artifacts before and after the suite.

    This keeps local Neo4j instances from accumulating nodes created by pytest
    while avoiding destructive full-database wipes outside tests that explicitly
    ask for them.
    """
    store = Neo4jStore()
    if not store.driver:
        yield
        return

    deleted_before = store.cleanup_test_artifacts()
    if deleted_before:
        logger.info("Removed %s stale Neo4j test artifacts before pytest.", deleted_before)

    try:
        yield
    finally:
        deleted_after = store.cleanup_test_artifacts()
        if deleted_after:
            logger.info("Removed %s Neo4j test artifacts after pytest.", deleted_after)
        store.close()
