import pytest

from src.apps.explorer import services


class _FakeMemory:
    def __init__(self, *, root=None):
        self._root = root
        self.bootstrapped = []

    def get_user_root(self):
        return self._root

    def bootstrap_user_root(self, name):
        node = {
            "id": f"user:{name.lower()}",
            "label": "User",
            "labels": ["Person", "User"],
            "name": name,
        }
        self.bootstrapped.append(name)
        self._root = node
        return node


def test_get_bootstrap_status_reports_uninitialized():
    memory = _FakeMemory(root=None)
    status = services.get_bootstrap_status(memory)
    assert status == {"initialized": False, "user": None}


def test_get_bootstrap_status_reports_initialized():
    memory = _FakeMemory(root={"id": "user:kevin", "name": "Kevin"})
    status = services.get_bootstrap_status(memory)
    assert status["initialized"] is True
    assert status["user"]["id"] == "user:kevin"


def test_bootstrap_user_seeds_root_via_memory():
    memory = _FakeMemory(root=None)
    result = services.bootstrap_user("Kevin", memory)
    assert memory.bootstrapped == ["Kevin"]
    assert "User" in result["user"]["labels"]
    assert "Person" in result["user"]["labels"]


def test_bootstrap_user_rejects_blank_name():
    memory = _FakeMemory(root=None)
    with pytest.raises(ValueError):
        services.bootstrap_user("   ", memory)
    assert memory.bootstrapped == []


# ── DLQ services ─────────────────────────────────────────────────────────────


class _DLQMemory:
    """Stand-in that exposes the DLQ surface used by the explorer services."""

    def __init__(self, failed=None):
        self._failed = list(failed or [])
        self.retried_ids: list[list[str] | None] = []

    def list_failed(self, limit=50):
        return self._failed[:limit]

    def count_failed(self):
        return len(self._failed)

    def retry_failed(self, memory_ids=None):
        self.retried_ids.append(list(memory_ids) if memory_ids else None)
        if memory_ids is None:
            n = len(self._failed)
            self._failed = []
            return n
        ids_set = set(memory_ids)
        before = len(self._failed)
        self._failed = [row for row in self._failed if row["id"] not in ids_set]
        return before - len(self._failed)


def test_list_analyzer_failures_shapes_each_row_for_the_panel():
    memory = _DLQMemory(failed=[
        {
            "id": "c1",
            "text": "first failure",
            "metadata": {
                "analyzer_failure_reason": "invalid_json_response",
                "analyzer_failed_at": "2026-05-11T10:00:00Z",
                "analysis_run_id": "r-1",
                "session_id": "s-1",
            },
        },
        {"id": "c2", "text": "second failure", "metadata": {}},
    ])
    payload = services.list_analyzer_failures(memory, limit=10)
    assert payload["count"] == 2
    assert len(payload["items"]) == 2
    assert payload["items"][0] == {
        "id": "c1",
        "text": "first failure",
        "reason": "invalid_json_response",
        "failed_at": "2026-05-11T10:00:00Z",
        "run_id": "r-1",
        "session_id": "s-1",
    }
    # Missing metadata still produces a stable shape.
    assert payload["items"][1]["reason"] is None


def test_retry_analyzer_failures_with_specific_ids():
    memory = _DLQMemory(failed=[
        {"id": "c1", "metadata": {}},
        {"id": "c2", "metadata": {}},
    ])
    result = services.retry_analyzer_failures(memory, memory_ids=["c1"])
    assert result == {"reset": 1, "remaining": 1}
    assert memory.retried_ids == [["c1"]]


def test_retry_analyzer_failures_with_no_ids_drains_dlq():
    memory = _DLQMemory(failed=[
        {"id": "c1", "metadata": {}},
        {"id": "c2", "metadata": {}},
    ])
    result = services.retry_analyzer_failures(memory)
    assert result == {"reset": 2, "remaining": 0}
    assert memory.retried_ids == [None]
