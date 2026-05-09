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

## Adding a New Analyzer
Each analyzer is a class that:
1. Accepts a `MemoryProtocol` (and any model clients it needs) via constructor injection.
2. Exposes one or more `analyze_*()` methods that return a small dataclass of stats.
3. Marks consumed Chroma rows via `memory.mark_analyzed(ids, run_id=...)` so they aren't reprocessed.
4. Never imports from `src.apps.*` — analyzers are infrastructure, apps consume their output via the explorer's read endpoints.

## Triggers (where analyzers get invoked from)
- **Manual** — `POST /api/explorer/analyze/run` (Stage 3, this commit).
- **Scheduled** — periodic ticking via `apscheduler` (Stage 4).
- **Post-bulk-ingest** — `KnowledgeIngestor.ingest_directory()` queues rows; the next scheduler tick drains them (Stage 4).

## LM Studio
`LMStudioClient` is an OpenAI-compatible REST wrapper around `httpx`. Default
URL is `settings.lm_studio_base_url` (`http://localhost:1234/v1`); default
model is `settings.lm_studio_model`. The client raises
`LocalLLMUnavailable` when the server is unreachable so the analyzer can
gracefully skip a tick and retry on the next one.
