from pathlib import Path
from uuid import uuid4

from src.core.limiter import InternalRateLimiter


def _workspace_usage_path() -> Path:
    path = Path("data") / f"test-usage-{uuid4().hex}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_usage_is_shared_within_same_project_scope():
    persist_path = _workspace_usage_path()
    try:
        limiter = InternalRateLimiter(persist_path=str(persist_path))

        limiter.track("models/gemini-2.5-flash", "project-a", tokens=100)

        shared_headroom = limiter.get_headroom(
            "models/gemini-2.5-flash", "project-a", rpm_limit=10, rpd_limit=100, tpm_limit=1000
        )
        repeated_scope_headroom = limiter.get_headroom(
            "models/gemini-2.5-flash", "project-a", rpm_limit=10, rpd_limit=100, tpm_limit=1000
        )

        assert shared_headroom == repeated_scope_headroom
    finally:
        persist_path.unlink(missing_ok=True)


def test_usage_is_isolated_across_project_scopes():
    persist_path = _workspace_usage_path()
    try:
        limiter = InternalRateLimiter(persist_path=str(persist_path))

        limiter.track("models/gemini-2.5-flash", "project-a", tokens=100)

        isolated_headroom = limiter.get_headroom(
            "models/gemini-2.5-flash", "project-b", rpm_limit=10, rpd_limit=100, tpm_limit=1000
        )

        assert isolated_headroom == 1.0
    finally:
        persist_path.unlink(missing_ok=True)
