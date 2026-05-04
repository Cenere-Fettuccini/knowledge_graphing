import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from src.core.config import settings
from src.core.limiter import InternalRateLimiter
from src.core.scraper import QuotaScraper

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
    # Limits (Can be updated by the scraper)
    rpm_limit: int = 15
    tpm_limit: int = 1000000
    rpd_limit: int = 1500

class LLMRouter:
    """Decides best model/key pair with daily calibration from AI Studio."""

    def __init__(self):
        self.models: List[ModelSpec] = []
        self.limiter = InternalRateLimiter()
        self.scraper = QuotaScraper()
        self._load_registry()
        
        self._last_calibration_time = 0
        self._calibration_interval = 86400  # 24 hours

    def _load_registry(self):
        """Populate models based on available API keys."""
        keys = settings.api_keys
        for key in keys:
            # Defaults for Gemini 1.5 Pro
            self.models.append(ModelSpec(
                model_id="models/gemini-1.5-pro",
                provider="google",
                api_key=key,
                capabilities={"QA": 0.9, "EXTRACTION": 1.0, "SUMMARIZATION": 0.8, "CODE": 0.9, "REASONING": 1.0},
                rpm_limit=2,
                rpd_limit=50,
                tpm_limit=32000
            ))
            # Defaults for Gemini 1.5 Flash
            self.models.append(ModelSpec(
                model_id="models/gemini-1.5-flash",
                provider="google",
                api_key=key,
                capabilities={"QA": 0.7, "EXTRACTION": 0.6, "SUMMARIZATION": 0.9, "CODE": 0.6, "REASONING": 0.6},
                rpm_limit=15,
                rpd_limit=1500,
                tpm_limit=1000000
            ))
            
        self.models.append(ModelSpec(
            model_id="local-slm",
            provider="local",
            capabilities={"QA": 0.4, "EXTRACTION": 0.3, "SUMMARIZATION": 0.5, "CODE": 0.2, "REASONING": 0.2},
            rpm_limit=9999,
            rpd_limit=9999,
            tpm_limit=9999999
        ))

    def get_best_model(self, task_type: str) -> ModelSpec:
        """Rank models based on capability and current internal headroom."""
        # Periodic calibration check
        self._check_calibration()
        
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

    def _check_calibration(self):
        """Run the scraper if a new day has started."""
        now = time.time()
        if now - self._last_calibration_time > self._calibration_interval:
            logger.info("New day detected. Running quota calibration...")
            try:
                # This is a bit heavy for the main thread, 
                # but it only happens once every 24h.
                live_limits = self.scraper.run_sync()
                for model_id, metrics in live_limits.items():
                    for model in self.models:
                        if model.model_id == model_id:
                            # Update the TOTAL limits based on what the dashboard says
                            if "rpm_total" in metrics: model.rpm_limit = metrics["rpm_total"]
                            if "rpd_total" in metrics: model.rpd_limit = metrics["rpd_total"]
                self._last_calibration_time = now
            except Exception as e:
                logger.error("Calibration failed: %s", e)
                # Don't try again for another hour to avoid spamming
                self._last_calibration_time = now - (self._calibration_interval - 3600)


# ── Singleton instance ────────────────────────────────────────────────────────
llm_router = LLMRouter()
