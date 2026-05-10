"""Tests for the PersistentClient init-retry guard."""

from __future__ import annotations

import pytest

from src.memory.stores import chroma_store


class _Sentinel:
    """Stand-in for a real Chroma client — we only need identity checks."""


def test_create_persistent_client_succeeds_first_try(tmp_path, monkeypatch):
    calls = []

    def fake_persistent_client(path):
        calls.append(path)
        return _Sentinel()

    monkeypatch.setattr(chroma_store.chromadb, "PersistentClient", fake_persistent_client)
    cleared = []
    monkeypatch.setattr(
        chroma_store, "_clear_chroma_shared_cache", lambda: cleared.append(True)
    )

    client = chroma_store._create_persistent_client(str(tmp_path / "chroma"))

    assert isinstance(client, _Sentinel)
    assert len(calls) == 1
    # Cache clear should NOT happen on the happy path.
    assert cleared == []
    # The directory must be ensured before the call.
    assert (tmp_path / "chroma").is_dir()


def test_create_persistent_client_retries_on_attribute_error(tmp_path, monkeypatch):
    """Repro of the RustBindingsAPI / KeyError init dance."""
    attempts = {"n": 0}

    def fake_persistent_client(path):
        attempts["n"] += 1
        if attempts["n"] == 1:
            # First call fails the way chromadb does in the wild.
            raise AttributeError("'RustBindingsAPI' object has no attribute 'bindings'")
        return _Sentinel()

    monkeypatch.setattr(chroma_store.chromadb, "PersistentClient", fake_persistent_client)
    cleared = []
    monkeypatch.setattr(
        chroma_store, "_clear_chroma_shared_cache", lambda: cleared.append(True)
    )

    client = chroma_store._create_persistent_client(str(tmp_path / "chroma"))

    assert isinstance(client, _Sentinel)
    assert attempts["n"] == 2
    # Cache clear must happen between the two attempts.
    assert cleared == [True]


def test_create_persistent_client_retries_on_key_error(tmp_path, monkeypatch):
    """Second symptom seen in the user's logs."""
    attempts = {"n": 0}

    def fake_persistent_client(path):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise KeyError(path)
        return _Sentinel()

    monkeypatch.setattr(chroma_store.chromadb, "PersistentClient", fake_persistent_client)
    monkeypatch.setattr(chroma_store, "_clear_chroma_shared_cache", lambda: None)

    client = chroma_store._create_persistent_client(str(tmp_path / "chroma"))
    assert isinstance(client, _Sentinel)
    assert attempts["n"] == 2


def test_create_persistent_client_propagates_second_failure(tmp_path, monkeypatch):
    """If retry also blows up, raise — the caller chooses what to do."""

    def fake_persistent_client(path):
        raise ValueError("Could not connect to tenant default_tenant")

    monkeypatch.setattr(chroma_store.chromadb, "PersistentClient", fake_persistent_client)
    monkeypatch.setattr(chroma_store, "_clear_chroma_shared_cache", lambda: None)

    with pytest.raises(ValueError, match="default_tenant"):
        chroma_store._create_persistent_client(str(tmp_path / "chroma"))


def test_create_persistent_client_does_not_swallow_unrelated_errors(tmp_path, monkeypatch):
    """A genuinely unrelated exception (e.g. permission) shouldn't be retried away."""

    def fake_persistent_client(path):
        raise PermissionError("nope")

    monkeypatch.setattr(chroma_store.chromadb, "PersistentClient", fake_persistent_client)
    cleared = []
    monkeypatch.setattr(
        chroma_store, "_clear_chroma_shared_cache", lambda: cleared.append(True)
    )

    with pytest.raises(PermissionError):
        chroma_store._create_persistent_client(str(tmp_path / "chroma"))
    # No retry, no cache clear — this isn't one of the documented transients.
    assert cleared == []
