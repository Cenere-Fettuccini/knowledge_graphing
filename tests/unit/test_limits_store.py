from src.core import limits_store
from src.core.limits_store import _resolve_short_id, is_text_output_category


def test_resolve_short_id_prefers_live_catalog_base_model_id():
    catalog = {
        "models": [
            {
                "displayName": "Gemini 2.5 Flash-Lite",
                "baseModelId": "gemini-2.5-flash-lite",
                "name": "models/gemini-2.5-flash-lite-001",
            }
        ]
    }

    assert _resolve_short_id("Gemini 2.5 Flash Lite", catalog) == "gemini-2.5-flash-lite"


def test_resolve_short_id_handles_preview_label_differences():
    catalog = {
        "models": [
            {
                "displayName": "Gemini 3.1 Flash-Lite Preview",
                "baseModelId": "gemini-3.1-flash-lite-preview-06-17",
                "name": "models/gemini-3.1-flash-lite-preview-06-17",
            }
        ]
    }

    assert _resolve_short_id("Gemini 3.1 Flash Lite", catalog) == "gemini-3.1-flash-lite-preview-06-17"


def test_resolve_short_id_slugifies_unknown_models():
    assert _resolve_short_id("Gemini Robotics ER 1.6 Preview", {}) == "gemini-robotics-er-1-6-preview"


def test_is_text_output_category_only_accepts_text_out_models():
    assert is_text_output_category("Text-out models") is True
    assert is_text_output_category("Other models") is False
    assert is_text_output_category("Multi-modal generative models") is False


def test_import_from_paste_skips_unknown_category_rows(monkeypatch):
    monkeypatch.setattr(
        limits_store,
        "parse_aistudio_paste",
        lambda _text: {
            "Gemini 2.5 Flash": {
                "category": "Text-out models",
                "rpm_used": 1,
                "rpm_limit": 5,
                "tpm_used": None,
                "tpm_limit": None,
                "rpd_used": None,
                "rpd_limit": None,
            },
            "1.43K / 250K": {
                "category": "Unknown",
                "rpm_used": 20,
                "rpm_limit": 20,
                "tpm_used": None,
                "tpm_limit": None,
                "rpd_used": None,
                "rpd_limit": None,
            },
        },
    )
    monkeypatch.setattr(limits_store, "refresh_model_catalog", lambda api_key=None: {})
    monkeypatch.setattr(limits_store, "load_limits", lambda: {})
    monkeypatch.setattr(limits_store, "_seed_usage_tracking", lambda imported_usage: None)

    saved = {}

    def fake_save_limits(data):
        saved.clear()
        saved.update(data)

    monkeypatch.setattr(limits_store, "save_limits", fake_save_limits)

    updated, matched = limits_store.import_from_paste("ignored")

    assert len(updated) == 1
    only_key = next(iter(updated))
    assert updated[only_key]["display_name"] == "Gemini 2.5 Flash"
    assert "1-43k-250k" not in updated
    assert matched == [only_key]
    assert "1-43k-250k" not in saved


def test_import_from_paste_removes_existing_unknown_category_rows(monkeypatch):
    monkeypatch.setattr(
        limits_store,
        "parse_aistudio_paste",
        lambda _text: {
            "Gemini 2.5 Flash": {
                "category": "Text-out models",
                "rpm_used": 1,
                "rpm_limit": 5,
                "tpm_used": 1430,
                "tpm_limit": 250000,
                "rpd_used": 2,
                "rpd_limit": 20,
            },
        },
    )
    monkeypatch.setattr(limits_store, "refresh_model_catalog", lambda api_key=None: {})
    monkeypatch.setattr(limits_store, "_seed_usage_tracking", lambda imported_usage: None)
    monkeypatch.setattr(
        limits_store,
        "load_limits",
        lambda: {
            "1-43k-250k": {
                "category": "Unknown",
                "display_name": "1.43K / 250K",
                "rpm_limit": 20,
            }
        },
    )

    saved = {}

    def fake_save_limits(data):
        saved.clear()
        saved.update(data)

    monkeypatch.setattr(limits_store, "save_limits", fake_save_limits)

    updated, matched = limits_store.import_from_paste("ignored")

    assert "1-43k-250k" not in updated
    assert "1-43k-250k" not in saved
    assert len(matched) == 1


def test_parse_aistudio_paste_does_not_promote_usage_cells_to_fake_models():
    pasted = """
Gemini 2.5 Flash
Text-out models
1 / 5
1.43K / 250K
2 / 20
Gemini Embedding 2
Other models
3 / 100
403 / 30K
25 / 1K
"""

    parsed = limits_store.parse_aistudio_paste(pasted)

    assert "Gemini 2.5 Flash" in parsed
    assert parsed["Gemini 2.5 Flash"] == {
        "category": "Text-out models",
        "rpm_used": 1,
        "rpm_limit": 5,
        "tpm_used": 1430,
        "tpm_limit": 250000,
        "rpd_used": 2,
        "rpd_limit": 20,
    }
    assert "Gemini Embedding 2" in parsed
    assert "1.43K / 250K" not in parsed


def test_parse_aistudio_paste_handles_dash_placeholders_in_metric_slots():
    pasted = """
Imagen 4 Generate
Multi-modal generative models
-
-
0 / 25
"""

    parsed = limits_store.parse_aistudio_paste(pasted)

    assert parsed["Imagen 4 Generate"] == {
        "category": "Multi-modal generative models",
        "rpm_used": None,
        "rpm_limit": None,
        "tpm_used": None,
        "tpm_limit": None,
        "rpd_used": 0,
        "rpd_limit": 25,
    }


def test_seed_usage_tracking_uses_single_project_scope(monkeypatch):
    class FakeLimiter:
        def __init__(self):
            self.snapshots = []
            self.saved = False

        def set_usage_snapshot(self, **kwargs):
            self.snapshots.append(kwargs)

        def save(self):
            self.saved = True

    fake_limiter = FakeLimiter()

    monkeypatch.setattr(
        limits_store.settings.__class__,
        "google_key_configs",
        property(lambda self: [{"api_key": "a", "project_scope": "project-a"}]),
    )
    monkeypatch.setattr(limits_store, "InternalRateLimiter", lambda: fake_limiter)

    limits_store._seed_usage_tracking(
        {
            "gemini-2.5-flash": {"rpm_used": 1, "tpm_used": 1430, "rpd_used": 2},
        }
    )

    assert fake_limiter.saved is True
    assert fake_limiter.snapshots[0]["model_id"] == "models/gemini-2.5-flash"
    assert fake_limiter.snapshots[0]["project_scope"] == "project-a"
    assert fake_limiter.snapshots[0]["rpm_used"] == 1
    assert fake_limiter.snapshots[0]["tpm_used"] == 1430
    assert fake_limiter.snapshots[0]["rpd_used"] == 2
