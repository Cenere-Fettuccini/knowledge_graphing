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

logger = logging.getLogger(__name__)

LIMITS_PATH = Path("./data/limits_override.json")
MISMATCHES_PATH = Path("./data/limit_mismatches.json")


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


def _is_value(s: str) -> bool:
    return bool(re.match(r'^\d[\d,\.]*\s*/\s*[\d,\.KkMm]', s, re.I)) or \
           bool(re.match(r'^\d+\s*/\s*Unlimited', s, re.I))


def _is_category(s: str) -> bool:
    return any(kw in s for kw in _CATEGORY_KEYWORDS)


def parse_aistudio_paste(text: str) -> dict:
    """
    Parse raw paste from the AI Studio rate limits page table.

    Returns a dict:
      { "Model Display Name": {category, rpm_limit, tpm_limit, rpd_limit} }
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

    # State machine: find model → find category → collect 0-3 value lines
    i = 0
    current_model = None
    current_category = None
    # slots: how many of [RPM, TPM, RPD] are dashes (skip from head)
    leading_dashes = 0

    while i < len(lines):
        line = lines[i]

        # Value or lone dash
        if _is_value(line) or line == '-':
            if current_model:
                # Collect up to 3 consecutive value/dash lines
                vals = []
                j = i
                while j < len(lines) and len(vals) < 3:
                    v = lines[j]
                    if _is_value(v) or v == '-':
                        vals.append(v)
                        j += 1
                    else:
                        break

                # Map leading_dashes to slot positions
                # e.g. leading_dashes=2 → RPM=None, TPM=None, RPD=vals[0]
                slots = ['-'] * leading_dashes + vals
                slots = (slots + [None, None, None])[:3]

                def frac(s):
                    if s is None or s == '-':
                        return None, None
                    return _parse_fraction(s)

                _, rpm_limit = frac(slots[0])
                _, tpm_limit = frac(slots[1])
                _, rpd_limit = frac(slots[2])

                results[current_model] = {
                    'category': current_category or 'Unknown',
                    'rpm_limit': rpm_limit,
                    'tpm_limit': tpm_limit,
                    'rpd_limit': rpd_limit,
                }
                current_model = None
                current_category = None
                leading_dashes = 0
                i = j
            else:
                i += 1
            continue

        # Category line
        if _is_category(line):
            current_category = line
            # Count leading dashes in remaining tokens of the same original line
            # (already split by tab, they appear as separate '-' entries right after)
            # Count how many immediately following lines are bare '-'
            leading_dashes = 0
            k = i + 1
            while k < len(lines) and lines[k] == '-':
                leading_dashes += 1
                k += 1
            i = k  # skip those dash tokens
            continue

        # Otherwise treat as a model name
        current_model = line
        current_category = None
        leading_dashes = 0
        i += 1

    return results


# ── Model ID fuzzy matcher ────────────────────────────────────────────────────

# Map display name fragments → canonical model_id suffixes used in router.py
_DISPLAY_TO_ID = {
    'Gemini 2.5 Flash Lite': 'gemini-2.5-flash-lite',
    'Gemini 2.5 Flash': 'gemini-2.5-flash',
    'Gemini 2.5 Pro': 'gemini-2.5-pro',
    'Gemini 3.1 Flash Lite': 'gemini-3.1-flash-lite',
    'Gemini 3.1 Pro': 'gemini-3.1-pro',
    'Gemini 3 Flash': 'gemini-3-flash',
    'Gemini 2 Flash Lite': 'gemini-2.0-flash-lite',
    'Gemini 2 Flash': 'gemini-2.0-flash',
    'Gemma 3 27B': 'gemma-3-27b-it',
    'Gemma 3 12B': 'gemma-3-12b-it',
    'Gemma 3 4B': 'gemma-3-4b-it',
    'Gemma 3 1B': 'gemma-3-1b-it',
    'Gemma 4 26B': 'gemma-4-26b',
    'Gemma 4 31B': 'gemma-4-31b',
}


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


def import_from_paste(text: str) -> tuple[dict, list[str]]:
    """
    Parse AI Studio paste text and merge into limits_override.json.
    Returns (updated_store, list_of_matched_model_ids).
    """
    parsed = parse_aistudio_paste(text)
    existing = load_limits()
    matched = []

    for display_name, limits in parsed.items():
        # Try direct mapping first
        short_id = _DISPLAY_TO_ID.get(display_name)
        if not short_id:
            slug = re.sub(r'[^a-z0-9]+', '-', display_name.lower()).strip('-')
            short_id = slug

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

    save_limits(existing)
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
