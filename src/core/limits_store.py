"""LimitsStore — manages dynamic rate limit data from AI Studio paste imports.

Priority chain for limits:
  1. data/limits_override.json  (set by paste import)
  2. Hardcoded defaults in router.py (fallback)
"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import httpx

from src.core.config import settings
from src.core.limiter import InternalRateLimiter

logger = logging.getLogger(__name__)

LIMITS_PATH = Path("./data/limits_override.json")
MISMATCHES_PATH = Path("./data/limit_mismatches.json")
MODEL_CATALOG_PATH = Path("./data/gemini_model_catalog.json")


# ── Number helpers ────────────────────────────────────────────────────────────

def _parse_num(s: str) -> Optional[int]:
    """Parse '250K', '1M', 'Unlimited', '14.4K' etc. Returns None for '-'."""
    s = s.strip()
    if not s or s in ('-', '—', ''):
        return None
    if s.lower() == 'unlimited':
        return 999_999_999
    m = re.match(r'^([\d,]+\.?\d*)\s*([KkMmBb]?)$', s.replace(',', ''))
    if m:
        v = float(m.group(1))
        suffix = m.group(2).upper()
        mult = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}.get(suffix, 1)
        return int(v * mult)
    return None


def _parse_fraction(s: str) -> tuple[Optional[int], Optional[int]]:
    """Parse 'used / limit' → (used, limit). Returns (None, None) for '-'."""
    s = s.strip()
    if not s or s == '-':
        return None, None
    parts = s.split('/')
    if len(parts) == 2:
        return _parse_num(parts[0]), _parse_num(parts[1])
    return None, None


# ── AI Studio paste parser ────────────────────────────────────────────────────

_SKIP_EXACT = {'Model', 'Category', 'RPM', 'TPM', 'RPD', 'Charts', 'Tools'}
_CATEGORY_KEYWORDS = ['models', 'Live API', 'Agents', 'grounding']
_SECTION_PREFIXES = ('Rate limits by model', 'Peak usage per model', 'Tools')
_TEXT_OUTPUT_CATEGORY = 'text-out models'


def _is_value(s: str) -> bool:
    s = s.strip()
    if s == '-':
        return False
    parts = [part.strip() for part in s.split('/')]
    if len(parts) != 2:
        return False

    left, right = parts
    left_ok = _parse_num(left) is not None
    right_ok = right.lower() == 'unlimited' or _parse_num(right) is not None
    return left_ok and right_ok


def _is_category(s: str) -> bool:
    return any(kw in s for kw in _CATEGORY_KEYWORDS)


def is_text_output_category(category: str | None) -> bool:
    """Return True only for AI Studio categories safe for text chat generation."""
    return (category or "").strip().lower() == _TEXT_OUTPUT_CATEGORY


def parse_aistudio_paste(text: str) -> dict:
    """
    Parse raw paste from the AI Studio rate limits page table.

    Returns a dict:
      {
        "Model Display Name": {
            category,
            rpm_limit, tpm_limit, rpd_limit,
            rpm_used, tpm_used, rpd_used
        }
      }
    """
    results = {}

    # Expand tab-separated tokens into separate logical lines
    expanded = []
    for raw in text.split('\n'):
        parts = [p.strip() for p in raw.split('\t')]
        parts = [p for p in parts if p]
        expanded.extend(parts)

    # Filter out noise
    lines = []
    for ln in expanded:
        if ln in _SKIP_EXACT:
            continue
        if any(ln.startswith(p) for p in _SECTION_PREFIXES):
            continue
        if not ln:
            continue
        lines.append(ln)

    def frac(value: Optional[str]) -> tuple[Optional[int], Optional[int]]:
        if value is None or value == '-':
            return None, None
        return _parse_fraction(value)

    # Consume rows shaped like:
    #   model_name
    #   category
    #   rpm_slot
    #   tpm_slot
    #   rpd_slot
    #
    # Metric slots may be '-' for missing values, but we always consume exactly
    # three slots once a category is found. This prevents usage cells from being
    # misread as the next model name.
    i = 0
    while i < len(lines):
        model_name = lines[i]

        # Skip anything that cannot start a model row.
        if _is_category(model_name) or _is_value(model_name) or model_name == '-':
            i += 1
            continue

        if i + 1 >= len(lines):
            break

        category = lines[i + 1]
        if not _is_category(category):
            i += 1
            continue

        slots = []
        j = i + 2
        while j < len(lines) and len(slots) < 3:
            token = lines[j]
            if _is_value(token) or token == '-':
                slots.append(token)
                j += 1
                continue
            break

        slots = (slots + [None, None, None])[:3]
        rpm_used, rpm_limit = frac(slots[0])
        tpm_used, tpm_limit = frac(slots[1])
        rpd_used, rpd_limit = frac(slots[2])

        results[model_name] = {
            'category': category,
            'rpm_used': rpm_used,
            'rpm_limit': rpm_limit,
            'tpm_used': tpm_used,
            'tpm_limit': tpm_limit,
            'rpd_used': rpd_used,
            'rpd_limit': rpd_limit,
        }

        i = j

    return results


# ── Model ID resolver ─────────────────────────────────────────────────────────


def _normalize_model_name(value: str) -> str:
    """Normalize model labels so display names and IDs can be compared safely."""
    normalized = value.lower().strip()
    normalized = normalized.replace("-lite", " lite").replace("-", " ")
    normalized = normalized.replace("flashlite", "flash lite")
    normalized = normalized.replace("3n", "3 n")
    normalized = normalized.replace("previewtts", "preview tts")
    normalized = re.sub(r'[^a-z0-9\. ]+', ' ', normalized)
    normalized = normalized.replace("2.0", "2")
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip()


def _load_model_catalog() -> dict:
    if not MODEL_CATALOG_PATH.exists():
        return {}
    try:
        return json.loads(MODEL_CATALOG_PATH.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning("Could not load gemini model catalog: %s", e)
        return {}


def _save_model_catalog(data: dict) -> None:
    MODEL_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_CATALOG_PATH.write_text(json.dumps(data, indent=2), encoding='utf-8')


def refresh_model_catalog(api_key: Optional[str] = None) -> dict:
    """
    Fetch the Gemini model catalog and cache it locally.

    Uses the REST models.list endpoint so display names can be matched to the
    same base model IDs that generation requests should use.
    """
    key = api_key or settings.google_api_key
    if not key:
        return _load_model_catalog()

    models = []
    page_token = None

    try:
        with httpx.Client(timeout=20.0) as client:
            while True:
                params = {"key": key, "pageSize": 1000}
                if page_token:
                    params["pageToken"] = page_token
                response = client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
                models.extend(payload.get("models", []))
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
    except Exception as e:
        logger.warning("Could not refresh Gemini model catalog: %s", e)
        return _load_model_catalog()

    catalog = {
        "fetched_at": time.time(),
        "models": models,
    }
    _save_model_catalog(catalog)
    return catalog


def _resolve_short_id(display_name: str, catalog: Optional[dict] = None) -> str:
    """
    Resolve an AI Studio display name to the short model ID used by requests.

    Prefers the live Gemini model catalog, then falls back to curated aliases,
    then finally to a slugified best-effort ID.
    """
    catalog = catalog or {}
    normalized_display = _normalize_model_name(display_name)

    normalized_display_no_preview = re.sub(r'\bpreview\b', '', normalized_display).strip()

    exact_matches = []
    fuzzy_matches = []
    for model in catalog.get("models", []):
        model_display = model.get("displayName") or ""
        normalized_model_display = _normalize_model_name(model_display)
        normalized_model_no_preview = re.sub(r'\bpreview\b', '', normalized_model_display).strip()

        if normalized_model_display == normalized_display:
            exact_matches.append(model)
            continue

        if normalized_model_no_preview == normalized_display_no_preview:
            fuzzy_matches.append(model)

    for candidates in (exact_matches, fuzzy_matches):
        for model in candidates:
            base_model_id = model.get("baseModelId")
            model_name = model.get("name", "")
            if base_model_id:
                return base_model_id
            if model_name.startswith("models/"):
                return model_name.split("/", 1)[1]

    slug = re.sub(r'[^a-z0-9]+', '-', display_name.lower()).strip('-')
    if slug.startswith("gemini-2-0-"):
        slug = slug.replace("gemini-2-0-", "gemini-2-", 1)
    return slug


def get_limit_for_model(model_id: str) -> Optional[dict]:
    """
    Look up stored limits for a model_id (e.g. 'models/gemini-2.5-flash').
    Returns {'rpm_limit': int, 'tpm_limit': int, 'rpd_limit': int} or None.
    """
    data = load_limits()
    if not data:
        return None
    short_id = model_id.split('/')[-1]  # strip 'models/' prefix
    if short_id in data:
        return data[short_id]
    return None


# ── Persistence ───────────────────────────────────────────────────────────────

def load_limits() -> dict:
    """Load limits from disk. Keys are short model IDs (e.g. 'gemini-2.5-flash')."""
    if not LIMITS_PATH.exists():
        return {}
    try:
        return json.loads(LIMITS_PATH.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning("Could not load limits_override.json: %s", e)
        return {}


def save_limits(data: dict) -> None:
    LIMITS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIMITS_PATH.write_text(json.dumps(data, indent=2), encoding='utf-8')


def _seed_usage_tracking(imported_usage: dict[str, dict]) -> None:
    """
    Seed usage_tracking.json from AI Studio's current usage snapshot.

    AI Studio usage is project-scoped, so we only seed automatically when the
    configured Gemini keys all resolve to a single unique project scope.
    """
    unique_scopes = {cfg["project_scope"] for cfg in settings.google_key_configs} or {"default"}
    if len(unique_scopes) != 1:
        logger.warning(
            "Skipping usage snapshot seeding because multiple project scopes are configured: %s",
            sorted(unique_scopes),
        )
        return

    project_scope = next(iter(unique_scopes))
    limiter = InternalRateLimiter()
    now = time.time()

    for short_id, usage in imported_usage.items():
        limiter.set_usage_snapshot(
            model_id=f"models/{short_id}",
            project_scope=project_scope,
            rpm_used=usage.get("rpm_used") or 0,
            tpm_used=usage.get("tpm_used") or 0,
            rpd_used=usage.get("rpd_used") or 0,
            ts=now,
        )

    limiter.save()


def import_from_paste(text: str) -> tuple[dict, list[str]]:
    """
    Parse AI Studio paste text and merge into limits_override.json.
    Returns (updated_store, list_of_matched_model_ids).
    """
    parsed = parse_aistudio_paste(text)
    existing = load_limits()
    existing = {
        model_id: entry
        for model_id, entry in existing.items()
        if entry.get('category') != 'Unknown'
    }
    matched = []
    imported_usage = {}
    catalog = refresh_model_catalog()

    for display_name, limits in parsed.items():
        if limits.get('category') == 'Unknown':
            logger.info("Skipping AI Studio row with unknown category: %s", display_name)
            continue

        short_id = _resolve_short_id(display_name, catalog)

        # Exclude models with 0 requests limit by deleting them if they exist
        if limits['rpm_limit'] == 0 or limits['rpd_limit'] == 0:
            if short_id in existing:
                del existing[short_id]
            continue

        entry = {}
        if limits['rpm_limit'] is not None:
            entry['rpm_limit'] = limits['rpm_limit']
        if limits['tpm_limit'] is not None:
            entry['tpm_limit'] = limits['tpm_limit']
        if limits['rpd_limit'] is not None:
            entry['rpd_limit'] = limits['rpd_limit']
        entry['category'] = limits['category']
        entry['display_name'] = display_name
        entry['imported_at'] = time.time()

        if entry:
            existing[short_id] = entry
            matched.append(short_id)
            imported_usage[short_id] = {
                'rpm_used': limits.get('rpm_used') or 0,
                'tpm_used': limits.get('tpm_used') or 0,
                'rpd_used': limits.get('rpd_used') or 0,
            }

    save_limits(existing)
    if imported_usage:
        _seed_usage_tracking(imported_usage)
    logger.info("Imported limits for %d models: %s", len(matched), matched)
    return existing, matched


# ── 429 Mismatch tracking ─────────────────────────────────────────────────────

def log_429_event(model_id: str, rpm_used: int, tpm_used: int, rpd_used: int,
                  rpm_limit: int, tpm_limit: int, rpd_limit: int) -> None:
    """Record a 429 event for later mismatch analysis on the credits dashboard."""
    event = {
        'model_id': model_id,
        'timestamp': time.time(),
        'usage_at_hit': {'rpm': rpm_used, 'tpm': tpm_used, 'rpd': rpd_used},
        'stored_limits': {'rpm': rpm_limit, 'tpm': tpm_limit, 'rpd': rpd_limit},
    }
    events = load_mismatch_log()
    events.append(event)
    # Keep last 200 events
    events = events[-200:]
    try:
        MISMATCHES_PATH.parent.mkdir(parents=True, exist_ok=True)
        MISMATCHES_PATH.write_text(json.dumps(events, indent=2), encoding='utf-8')
    except Exception as e:
        logger.warning("Could not save mismatch log: %s", e)


def load_mismatch_log() -> list:
    if not MISMATCHES_PATH.exists():
        return []
    try:
        return json.loads(MISMATCHES_PATH.read_text(encoding='utf-8'))
    except Exception:
        return []
