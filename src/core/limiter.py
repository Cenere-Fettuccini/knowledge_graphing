"""Internal Rate Limiter — persistent tracking of LLM usage (RPM, TPM, RPD)."""

import json
import logging
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

@dataclass
class UsageState:
    """Serializable usage state for a specific API key + model."""
    used_rpm: List[float] = field(default_factory=list) # timestamps
    used_rpd: List[float] = field(default_factory=list) # timestamps
    used_tpm: List[Dict[str, Any]] = field(default_factory=list) # {ts: float, tokens: int}

class InternalRateLimiter:
    """Tracks and persists usage across restarts to respect RPD/TPM/RPM limits."""

    def __init__(self, persist_path: str = "./data/usage_tracking.json"):
        self.persist_path = Path(persist_path)
        self.states: Dict[str, UsageState] = {} # key: "model:api_key"
        self._load()

    def _load(self):
        """Load usage state from disk."""
        if self.persist_path.exists():
            try:
                data = json.loads(self.persist_path.read_text())
                for key, state_data in data.items():
                    self.states[key] = UsageState(**state_data)
                logger.info("Loaded usage state for %d instances", len(self.states))
            except Exception as e:
                logger.warning("Failed to load usage state: %s", e)

    def _save(self):
        """Persist usage state to disk."""
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {k: asdict(v) for k, v in self.states.items()}
            self.persist_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error("Failed to save usage state: %s", e)

    def _get_state(self, model_id: str, api_key: str) -> UsageState:
        key = f"{model_id}:{api_key}"
        if key not in self.states:
            self.states[key] = UsageState()
        return self.states[key]

    def track(self, model_id: str, api_key: str, tokens: int = 0):
        """Record a call and its token usage."""
        state = self._get_state(model_id, api_key)
        now = time.time()
        
        state.used_rpm.append(now)
        state.used_rpd.append(now)
        if tokens > 0:
            state.used_tpm.append({"ts": now, "tokens": tokens})
            
        self._save()

    def get_headroom(self, model_id: str, api_key: str, 
                     rpm_limit: int, rpd_limit: int, tpm_limit: int) -> float:
        """Calculate fraction of limits remaining (0.0 to 1.0)."""
        state = self._get_state(model_id, api_key)
        now = time.time()
        
        # Prune old data
        state.used_rpm = [t for t in state.used_rpm if now - t < 60]
        state.used_rpd = [t for t in state.used_rpd if now - t < 86400]
        state.used_tpm = [entry for entry in state.used_tpm if now - entry["ts"] < 60]
        
        # Calculate fractions
        rpm_head = 1.0 - (len(state.used_rpm) / rpm_limit)
        rpd_head = 1.0 - (len(state.used_rpd) / rpd_limit)
        
        current_tpm = sum(e["tokens"] for e in state.used_tpm)
        tpm_head = 1.0 - (current_tpm / tpm_limit)
        
        headroom = min(rpm_head, rpd_head, tpm_head)
        return max(0.0, headroom)
