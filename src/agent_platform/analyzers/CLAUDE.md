# Agent Platform — Analyzers

Background agents that process queued Chroma rows into the Neo4j knowledge
graph. They run on triggers (count-based, manual, post-bulk-ingest), **not**
on every chat turn. Conversations are stored as `analyzed: false` rows in
Chroma; analyzers drain that queue.

## Files
| File | Role |
|------|------|
| `local_llm.py` | `LMStudioClient` — OpenAI-compatible client for the local LLM server |
| `graph_extraction.py` | `GraphExtractor` — local-LLM (Gemma 4) pass: entity/task/edge intents only |
| `graph_ingest_trigger.py` | Count-based trigger + manual `run_extraction_pass()` entry point |
| `cloud_belief_extraction.py` | Gemini Flash pass that drains `belief_candidate` rows into Belief nodes |
| `cloud_belief_trigger.py` | Count-based trigger for the cloud belief pass |
| `refinement_extraction.py` | Parses a reconciliation reply into `{summary, evidence, resolved}` (CT8) |
| `canonicalize.py` | `EntityCanonicalizer` + `BeliefCanonicalizer` — dedup via `:MergeProposal` nodes |
| `schema_drift.py` | Snapshot + diff tool flagging new/disappeared labels and rel-types |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.memory.manager` | `graph_ingest_trigger.maybe_trigger()` — lazy trigger from `store()` |
| `src.apps.explorer.api` | `graph_ingest_trigger.run_extraction_pass()` — `POST /analyze/run` |
| `src.apps.explorer.services` | `GraphExtractor`, `EntityCanonicalizer`, `BeliefCanonicalizer`, `LMStudioClient` |
| `src.apps.explorer.api` | `cloud_belief_extraction.run_belief_extraction_once()` — `POST /analyze/beliefs/extract` |
| `src.apps.explorer.api` | `contradiction_detection.run_contradiction_detection()` — `POST /analyze/contradictions` |
| `src.apps.explorer.api` | `schema_drift.check_drift()`, `schema_drift.take_snapshot()` |
| `src.platform.graph_ingest` | `graph_ingest_trigger.run_extraction_pass()` — `POST /graph/ingest` |
| `src.bot.proactive` | `refinement_extraction.parse_reconciliation_reply()` — CT8 quick mode |

---

## Calls Into
| Dependency | What is called |
|------------|---------------|
| `src.memory.manager` | `MemoryManager` — `list_unanalyzed()`, `mark_analyzed()`, `upsert_node()`, `upsert_relationship()`, etc. |
| `src.core.config` | `settings` — thresholds, LM Studio URL/model, Gemini key |
| `src.agent_platform.analyzers.local_llm` | `LMStudioClient` — local extraction pass |
| `src.agent_platform.analyzers.cloud_belief_trigger` | `maybe_trigger()` — called from `graph_ingest_trigger` after local pass |
| LM Studio REST API | Local Gemma 4 model via `LMStudioClient` |
| Google Gemini API | Cloud belief extraction and contradiction detection |

---

## Public API

### `graph_ingest_trigger.py`
```python
def maybe_trigger(memory: MemoryManager) -> None:
    """Fire extraction if count_unanalyzed() >= settings.graph_ingest_threshold.
    No-ops if a pass is already running (lock-and-skip)."""

async def run_extraction_pass(
    memory: MemoryManager,
    batch_size: int = 20,
    model: str | None = None,
) -> dict:
    """Run one analysis pass: fetch unanalyzed batch, extract via local LLM,
    write to graph, mark analyzed. Returns {processed, skipped, errors}."""
```

### `cloud_belief_extraction.py`
```python
async def run_belief_extraction_once(memory: MemoryManager, batch_size: int = 25) -> dict:
    """Extract beliefs from belief_candidate rows using Gemini Flash.
    Returns {processed, created, skipped}."""
```

### `canonicalize.py`
```python
class EntityCanonicalizer:
    def __init__(memory: MemoryManager, threshold: float = 0.92)
    def run() -> dict   # Dedup per label; writes :MergeProposal nodes

class BeliefCanonicalizer:
    def __init__(memory: MemoryManager, threshold: float = 0.88)
    def run() -> dict   # Dedup active :Belief content; writes :MergeProposal nodes
```

### `refinement_extraction.py`
```python
async def parse_reconciliation_reply(memory: MemoryManager, reply_text: str) -> dict:
    """Parse LLM reconciliation text → {summary, evidence, resolved: bool}.
    Called from ProactiveBot in the CT8 quick-mode contradiction flow."""
```

### `schema_drift.py`
```python
def check_drift(memory: MemoryManager, window_days: int = 7) -> dict:
def take_snapshot(memory: MemoryManager) -> dict:
```

### `local_llm.py`
```python
class LocalLLMUnavailable(Exception): ...

class LMStudioClient:
    def is_available() -> bool
    def list_models() -> list[dict]
    async def extract_batch(batch: list[dict], model: str | None = None) -> dict
```

---

## Trigger Paths
- **Auto (count-based)** — `graph_ingest_trigger.maybe_trigger` fires from
  `MemoryManager.store()`. After the local pass, `cloud_belief_trigger.maybe_trigger`
  fires if belief candidates exceed the cloud threshold.
- **Manual** — `POST /api/explorer/analyze/run` calls `run_extraction_pass()`
  directly (no lock check — manual always runs).
- **Post-bulk-ingest** — `explorer/services.run_bulk_import()` loops
  `run_extraction_pass()` until queue is empty or 50-batch safety cap hits.
- **Reconciliation** — `refinement_extraction.parse_reconciliation_reply()` is
  called from `ProactiveBot.handle_refinement_reply()`.
- **Canonicalization** — `POST /api/explorer/canonicalize/run` instantiates
  `EntityCanonicalizer` or `BeliefCanonicalizer`; never auto-merged.

## Coupling Notes
- Analyzers **never** import from `src.apps.*` — they are infrastructure.
  Apps consume analyzer *output* via graph read endpoints.
- Each analyzer accepts `MemoryManager` (or `MemoryProtocol`) as a parameter
  rather than calling `get_memory_manager()` internally. This keeps them
  testable without a live database.
- `LMStudioClient` raises `LocalLLMUnavailable` when LM Studio is unreachable.
  The trigger swallows this and logs a warning — analysis is deferred to the
  next trigger.
