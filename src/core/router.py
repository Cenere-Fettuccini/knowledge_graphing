import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from src.core.config import settings
from src.core.limiter import InternalRateLimiter
from src.core.limits_store import get_limit_for_model, log_429_event, load_limits

logger = logging.getLogger(__name__)

@dataclass
class ModelSpec:
    model_id: str
    provider: str  # "google", "local", etc.
    api_key: str = ""
    # Scores (0.0 to 1.0) for different task types
    capabilities: Dict[str, float] = field(default_factory=lambda: {
        "QA": 0.5,
        "EXTRACTION": 0.5,
        "SUMMARIZATION": 0.5,
        "CODE": 0.5,
        "REASONING": 0.5
    })
    # Limits (sensible defaults for free-tier Gemini)
    rpm_limit: int = 15
    tpm_limit: int = 1000000
    rpd_limit: int = 1500

class LLMRouter:
    """Decides best model/key pair based on capability scores and usage headroom."""

    def __init__(self):
        self.models: List[ModelSpec] = []
        self.limiter = InternalRateLimiter()
        self._load_registry()

    def _load_registry(self):
        """Populate models based on available API keys.
        Loads dynamic models from limits_override.json, or falls back to defaults.
        """
        keys = settings.api_keys
        overrides = load_limits()
        
        if not overrides:
            # Fallback defaults if no limits have been imported
            for key in keys:
                self.models.append(self._make_spec(
                    model_id="models/gemini-2.5-pro", api_key=key,
                    capabilities={"QA": 0.9, "EXTRACTION": 1.0, "SUMMARIZATION": 0.8, "CODE": 0.9, "REASONING": 1.0},
                    default_rpm=5, default_rpd=25, default_tpm=32_000,
                ))
                self.models.append(self._make_spec(
                    model_id="models/gemini-2.5-flash", api_key=key,
                    capabilities={"QA": 0.7, "EXTRACTION": 0.6, "SUMMARIZATION": 0.9, "CODE": 0.6, "REASONING": 0.6},
                    default_rpm=5, default_rpd=20, default_tpm=250_000,
                ))
        else:
            # Dynamically register every model imported from AI Studio
            for short_id, limits in overrides.items():
                lower_id = short_id.lower()
                
                # Exclude models not meant for text generation via generateContent
                exclusions = ['embedding', 'imagen', 'tts', 'audio', 'veo', 'lyria', 'nano-banana', 'robotics', 'live']
                if any(ex in lower_id for ex in exclusions):
                    continue

                is_pro = "pro" in lower_id
                is_lite = "lite" in lower_id
                
                # Derive capabilities heuristically
                if is_pro:
                    caps = {"QA": 0.9, "EXTRACTION": 1.0, "SUMMARIZATION": 0.8, "CODE": 0.9, "REASONING": 1.0}
                elif is_lite:
                    caps = {"QA": 0.5, "EXTRACTION": 0.4, "SUMMARIZATION": 0.6, "CODE": 0.3, "REASONING": 0.4}
                else:
                    caps = {"QA": 0.7, "EXTRACTION": 0.6, "SUMMARIZATION": 0.9, "CODE": 0.6, "REASONING": 0.6}
                
                for key in keys:
                    self.models.append(self._make_spec(
                        model_id=f"models/{short_id}",
                        api_key=key,
                        capabilities=caps,
                        default_rpm=1, default_rpd=1, default_tpm=1000 # Make defaults low so overrides apply
                    ))

        # Local fallback — always available, no limits
        self.models.append(ModelSpec(
            model_id="local-slm",
            provider="local",
            capabilities={"QA": 0.4, "EXTRACTION": 0.3, "SUMMARIZATION": 0.5, "CODE": 0.2, "REASONING": 0.2},
            rpm_limit=9999, rpd_limit=9999, tpm_limit=9_999_999,
        ))

    def _make_spec(self, model_id: str, api_key: str, capabilities: dict,
                   default_rpm: int, default_rpd: int, default_tpm: int) -> ModelSpec:
        """Build a ModelSpec, preferring stored limits over hardcoded defaults."""
        stored = get_limit_for_model(model_id)
        rpm = stored.get('rpm_limit') if stored and stored.get('rpm_limit') is not None else default_rpm
        rpd = stored.get('rpd_limit') if stored and stored.get('rpd_limit') is not None else default_rpd
        tpm = stored.get('tpm_limit') if stored and stored.get('tpm_limit') is not None else default_tpm
        if stored:
            logger.info("[LimitsStore] %s: rpm=%s rpd=%s tpm=%s (from override)",
                        model_id.split('/')[-1], rpm, rpd, tpm)
        return ModelSpec(
            model_id=model_id, provider="google", api_key=api_key,
            capabilities=capabilities,
            rpm_limit=rpm,
            rpd_limit=rpd,
            tpm_limit=tpm,
        )

    def get_best_model(self, task_type: str) -> ModelSpec:
        """Rank models based on capability and current internal headroom."""
        best_model = self.models[-1] # Default to local
        best_score = -1.0
        
        for model in self.models:
            capability = model.capabilities.get(task_type, 0.5)
            headroom = self.limiter.get_headroom(
                model.model_id, 
                model.api_key,
                model.rpm_limit,
                model.rpd_limit,
                model.tpm_limit
            )
            score = capability * headroom
            
            if score > best_score:
                best_score = score
                best_model = model
                
        return best_model

    def track_usage(self, model_id: str, api_key: str = "", tokens: int = 0):
        """Signal the limiter to record usage."""
        self.limiter.track(model_id, api_key, tokens=tokens)

    def track_429(self, model_id: str, api_key: str = "") -> None:
        """Record a 429 event with current usage snapshot for mismatch analysis."""
        spec = next((m for m in self.models if m.model_id == model_id), None)
        if not spec:
            return
        state = self.limiter._get_state(model_id, api_key)
        now = time.time()
        rpm_used = len([t for t in state.used_rpm if now - t < 60])
        tpm_used = sum(e["tokens"] for e in state.used_tpm if now - e["ts"] < 60)
        rpd_used = len([t for t in state.used_rpd if now - t < 86400])
        log_429_event(
            model_id=model_id,
            rpm_used=rpm_used, tpm_used=tpm_used, rpd_used=rpd_used,
            rpm_limit=spec.rpm_limit, tpm_limit=spec.tpm_limit, rpd_limit=spec.rpd_limit,
        )
        logger.warning("[429] %s — usage: rpm=%d/%d rpd=%d/%d tpm=%d/%d",
                       model_id.split('/')[-1],
                       rpm_used, spec.rpm_limit,
                       rpd_used, spec.rpd_limit,
                       tpm_used, spec.tpm_limit)

    def reload_limits(self) -> None:
        """Re-read limits_override.json and rebuild model specs in-place."""
        self.models.clear()
        self._load_registry()
        logger.info("[LimitsStore] Reloaded model registry with fresh limits.")


# ── Singleton instance ────────────────────────────────────────────────────────
llm_router = LLMRouter()
