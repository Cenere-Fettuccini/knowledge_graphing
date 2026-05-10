# Agent Platform — Analyzers

Background agents that process queued data into the knowledge graph. They run
on triggers (manual, scheduled, post-bulk-ingest), **not** on every chat turn.
Conversations are stored as `analyzed: false` rows in Chroma; analyzers drain
that queue.

## Files
| File | Role |
|------|------|
| `local_llm.py` | `LMStudioClient` — OpenAI-compatible client for the local LLM server |
| `knowledge.py` | `KnowledgeAnalyzer` — extracts durable facts about the user, people, preferences |
| `scheduler.py` | `AnalyzerScheduler` — apscheduler-driven periodic auto-drain of the queue |

## Adding a New Analyzer
Each analyzer is a class that:
1. Accepts a `MemoryProtocol` (and any model clients it needs) via constructor injection.
2. Exposes one or more `analyze_*()` methods that return a small dataclass of stats.
3. Marks consumed Chroma rows via `memory.mark_analyzed(ids, run_id=...)` so they aren't reprocessed.
4. Never imports from `src.apps.*` — analyzers are infrastructure, apps consume their output via the explorer's read endpoints.

## Triggers (where analyzers get invoked from)
- **Manual** — `POST /api/explorer/analyze/run` from the explorer panel.
- **Scheduled** — `AnalyzerScheduler` ticks every `settings.analyzer_tick_seconds`
  (default 900s). Started from the FastAPI lifespan in `platform.app_factory`.
  Disable via `ANALYZER_ENABLED=false`.
- **Post-bulk-ingest** — `KnowledgeIngestor.ingest_directory()` drains the queue
  inline after writing the chunks. Pass `analyze=False` to suppress, e.g. in
  tests, and let the scheduler pick it up later.

## LM Studio
`LMStudioClient` is an OpenAI-compatible REST wrapper around `httpx`. Default
URL is `settings.lm_studio_base_url` (`http://localhost:1234/v1`); default
model is `settings.lm_studio_model`. The client raises
`LocalLLMUnavailable` when the server is unreachable so the analyzer can
gracefully skip a tick and retry on the next one.
