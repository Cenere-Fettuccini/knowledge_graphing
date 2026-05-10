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
