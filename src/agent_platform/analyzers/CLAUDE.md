# Agent Platform — Analyzers

Background agents that process queued data into the knowledge graph. They run
on triggers (count, manual, post-bulk-ingest), **not** on every chat turn.
Conversations are stored as `analyzed: false` rows in Chroma; analyzers drain
that queue.

## Files
| File | Role |
|------|------|
| `local_llm.py` | `LMStudioClient` — OpenAI-compatible client for the local LLM server |
| `graph_extraction.py` | Local-LLM extraction (Gemma 4): entity / task / edge intents only; beliefs deferred to the cloud pass |
| `graph_ingest_trigger.py` | Count-based trigger: fires `graph_write` when `count_unanalyzed >= settings.graph_ingest_threshold` |
| `cloud_belief_extraction.py` | Gemini Flash pass that drains `belief_candidate` rows into Belief nodes |
| `cloud_belief_trigger.py` | Count-based trigger for the cloud pass (`count_belief_candidates >= settings.cloud_belief_threshold`) |
| `knowledge.py` | `KnowledgeAnalyzer` — legacy direct-write extractor, kept for the manual `/analyze/run` route and the bulk-importer post-write drain |
| `canonicalize.py` | `EntityCanonicalizer` (per-label entity dedup, threshold 0.92) and `BeliefCanonicalizer` (active :Belief content dedup, threshold 0.88); both write `:MergeProposal` nodes for human approval |
| `schema_drift.py` | Snapshot + diff tool that flags new low-population labels and disappeared labels/rel-types |

## Adding a New Analyzer
Each analyzer is a class or module-level function that:
1. Accepts a `MemoryProtocol` (and any model clients it needs) via constructor injection or parameter.
2. Exposes one or more `analyze_*()` / `run_*_once` methods.
3. Marks consumed Chroma rows via `memory.mark_analyzed(ids, run_id=...)` so they aren't reprocessed.
4. Never imports from `src.apps.*` — analyzers are infrastructure, apps consume their output via the explorer's read endpoints.

## Triggers (where analyzers get invoked from)
- **Count-based (auto)** — `graph_ingest_trigger.maybe_trigger` and
  `cloud_belief_trigger.maybe_trigger` fire from `MemoryManager.store` and
  from the local pass's tail respectively. This is the default path; the
  old time-tick `AnalyzerScheduler` was deleted in CT1.
- **Manual** — `POST /api/explorer/analyze/run` calls
  `KnowledgeAnalyzer.analyze_pending` directly. Still useful for ad-hoc
  reprocessing and debugging.
- **Post-bulk-ingest** — `KnowledgeIngestor.ingest_directory()` drains the
  queue inline after writing the chunks via the same legacy analyzer.
- **Canonicalization** — `POST /api/explorer/canonicalize/run` calls the
  canonicalizer for the requested target (`target='entities'` →
  `EntityCanonicalizer`, `target='beliefs'` → `BeliefCanonicalizer`). Both
  cold-path, never auto-merge; surface proposals via
  `GET /canonicalize/proposals` and apply via
  `POST /canonicalize/apply/{id}`.

## LM Studio
`LMStudioClient` is an OpenAI-compatible REST wrapper around `httpx`. Default
URL is `settings.lm_studio_base_url` (`http://localhost:1234/v1`); default
model is `settings.lm_studio_model`. The client raises
`LocalLLMUnavailable` when the server is unreachable so the analyzer can
gracefully skip a tick and retry on the next one.
