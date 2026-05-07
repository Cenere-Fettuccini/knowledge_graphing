from src.core.router import LLMRouter


def test_router_only_registers_text_output_override_models(monkeypatch):
    monkeypatch.setattr(
        "src.core.router.settings.google_key_configs",
        [{"api_key": "test-key", "project_scope": "default"}],
    )
    monkeypatch.setattr(
        "src.core.router.load_limits",
        lambda: {
            "gemini-3-flash": {
                "category": "Text-out models",
                "rpm_limit": 5,
                "tpm_limit": 250000,
                "rpd_limit": 20,
            },
            "gemini-embedding-2": {
                "category": "Other models",
                "rpm_limit": 100,
                "tpm_limit": 30000,
                "rpd_limit": 1000,
            },
            "gemini-2.5-flash-tts": {
                "category": "Multi-modal generative models",
                "rpm_limit": 3,
                "tpm_limit": 10000,
                "rpd_limit": 10,
            },
        },
    )
    monkeypatch.setattr("src.core.router.get_limit_for_model", lambda _model_id: None)

    router = LLMRouter()
    model_ids = {model.model_id for model in router.models}

    assert "models/gemini-3-flash" in model_ids
    assert "models/gemini-embedding-2" not in model_ids
    assert "models/gemini-2.5-flash-tts" not in model_ids
    assert "local-slm" in model_ids
