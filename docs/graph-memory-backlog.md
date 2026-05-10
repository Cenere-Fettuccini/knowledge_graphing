# Graph & Memory Pipeline — Sprint Backlog

Last updated: 2026-05-11

Captures the work to take the graph/memory pipeline from "rudimentary" to a
trustworthy substrate for long-term self-mapping. Organized into themed epics
and grouped into four sprint-sized increments.

## Epics

| ID | Epic | Priority | Why |
|----|------|----------|-----|
| E1 | Resilience & Operability | P0 | Silent data loss on DB failures; no DLQ |
| E2 | Bulk Ingestion Revival | P0 | Pipeline was deleted; blocks any historical seeding |
| E3 | Entity & Belief Canonicalization | P1 | Graph fragments without dedup as it grows |
| E4 | Temporal Context (Eras) | P1 | Long-horizon evolution chains become unreadable |
| E5 | Belief Extraction Quality | P1 | 8B local model is a quality bottleneck on subjective content |
| E6 | Approval & Refinement Layer | P2 | Cold-path output needs human-in-the-loop |
| E7 | Explorer UX | P2 | Hard 100-node cap; no focal-node exploration |

---

## Sprint 1 — Resilience Floor (E1)

Goal: stop silent data loss; make the pipeline crash-safe.

### S1.1 — Spillover writes for Chroma and Neo4j (P0)
- On Chroma write failure, append to `data/spillover/chroma.jsonl`.
- On Neo4j write failure, append to `data/spillover/neo4j.jsonl`.
- Background task replays spillover on next successful health check.
- **Acceptance**: kill Neo4j mid-conversation; restart it; verify replayed writes appear with original timestamps.

### S1.2 — Dead-letter queue for analyzer (P0)
- When LLM returns malformed JSON or graph writes fail, mark items `analyzed: failed` instead of `analyzed: true`.
- Add `analyzer_failure_reason` metadata field.
- Add `/api/explorer/analyze/retry-failed` endpoint.
- **Acceptance**: force a JSON parse failure; verify items remain queryable and retryable.

### S1.3 — Transactional batch boundaries (P1)
- Wrap analyzer's `_apply_extraction` in a Neo4j transaction per batch.
- Roll back partial graph state if any node/edge write fails.
- **Acceptance**: kill process mid-batch; verify no orphaned nodes in graph.

### S1.4 — Graceful degradation signaling (P1)
- When memory write fails, attach a `memory_degraded` flag to agent response metadata.
- Surface in UI as a small warning indicator.
- **Acceptance**: take Neo4j down; user sees degradation indicator, conversation still works.

---

## Sprint 2 — Bulk Ingestion + Canonicalization (E2, E3)

Goal: rebuild the import path; stop graph fragmentation.

### S2.1 — Bulk import endpoint (P0)
- New module: `src/ingestion/bulk_importer.py`.
- Input: directory of files OR a single JSONL with `{timestamp, text, source}` rows.
- Output: writes to Chroma with `analyzed: false`, `source: bulk`, `imported_at` timestamp.
- No inline graph extraction — defer to analyzer.
- **Acceptance**: import a 1000-entry JSONL; all rows queryable in Chroma; analyzer queue grows by 1000.

### S2.2 — Bulk-mode analyzer pacing (P0)
- New flag on analyzer: `bulk_mode={True,False}`.
- In bulk mode: batch size 100, tick 60s instead of 20/900s.
- **Acceptance**: bulk-import 10k entries; queue drained in <3 hours.

### S2.3 — Chronological queue ordering (P1)
- Analyzer queue prioritizes oldest-first by source `timestamp` for bulk items.
- Live conversations stay FIFO and bypass bulk backlog.
- **Acceptance**: import journal entries from 2019–2024; verify entities are extracted in order, evolution chains read forward in time.

### S2.4 — Entity dedup pass (P1)
- New job: `src/agent_platform/analyzers/canonicalize.py`.
- For each entity label, fetch all nodes; embed names; cluster near-duplicates (cosine > 0.92).
- Generate merge proposals (no auto-merge).
- New endpoint: `GET /api/explorer/canonicalize/proposals`, `POST /api/explorer/canonicalize/apply/{id}`.
- **Acceptance**: seed graph with `person:mom` and `person:my-mother`; canonicalization proposes a merge.

### S2.5 — Belief dedup pass (P1)
- Same approach for `:Belief` nodes, but use content embeddings.
- Lower threshold (0.88) since beliefs are paraphrased more.
- **Acceptance**: two beliefs with near-identical content show up as merge candidates.

---

## Sprint 3 — Eras & Belief Quality (E4, E5)

Goal: temporal scaffolding and better extraction on subjective content.

### S3.1 — Era node type (P1)
- New label `:Era` with `start_date`, `end_date` (nullable for ongoing), `name`, `description`.
- Many-to-many `OCCURRED_IN` edges from any node to one or more eras.
- CRUD via `/api/explorer/eras`.
- **Acceptance**: create an era "Berlin years (2021–2024)"; bind 5 entities to it; query graph filtered by that era.

### S3.2 — Era-scoped graph queries (P1)
- Extend `graph_overview` and node detail to accept `era_id` filter.
- "Active self" = nodes in eras with `end_date IS NULL` or future-dated.
- **Acceptance**: explorer shows toggle for "current eras only" / "all time" / specific era.

### S3.3 — Soft-archive prompts via bot (P2)
- Background job flags entities not mentioned in N months as soft-archive candidates.
- Bot opens a short conversation: "I haven't seen X come up in a while — should this be archived to a past era, or is it still live?"
- User response binds the entity to an era (closing or new), keeps it active, or dismisses with reason.
- **Acceptance**: entity untouched for 6 months triggers a bot DM; user response updates the graph accordingly.

### S3.4 — Split extraction tiers (P1)
- Knowledge analyzer (Gemma 8B local) extracts entities and structural relationships only.
- Beliefs are flagged as candidates with a `belief_candidate: true` Chroma metadata, not written directly.
- New job picks up belief candidates and runs them through Gemini Flash for extraction.
- **Acceptance**: entity extraction throughput unchanged; belief content quality measurably improves on a held-out set of 50 conversations.

### S3.5 — Schema drift monitor (P2)
- Job that diffs label/relationship type counts week-over-week.
- Alerts if a new label is created with <3 nodes attached (likely drift, not a real type).
- **Acceptance**: feed analyzer noisy data; drift monitor flags spurious label `Stuff` after 1 week.

---

## Sprint 4 — Approval Layer & Explorer UX (E6, E7)

Goal: human-in-the-loop for synthesis; usable graph at scale.

### S4.1 — Pending belief queue with expiring rejections (P1)
- Rumination output goes to `:PendingBelief` nodes instead of `:Belief`.
- Three transitions: approve → `:Belief`, reject → `:RejectedHypothesis` (temporary), edit → `:Belief` with edit log.
- `:RejectedHypothesis` nodes carry a `expires_at` timestamp (default 30 days from rejection).
- A nightly cleanup job (runs at 23:00 local) deletes expired rejections from the graph.
- During their lifetime, rejections are fed to the rumination engine as negative examples to suppress re-proposal of the same idea.
- If the same hypothesis is rejected 3+ times within the TTL window, promote to a permanent `:RejectedBelief` instead — that's a strong signal worth keeping.
- **Acceptance**: rejected hypothesis is suppressed in next 5 rumination runs; auto-deleted after 30 days; repeated rejection promotes to permanent.

### S4.2 — Daily digest delivery (P1)
- Cron job runs weekdays at 18:30 local time.
- Assembles pending beliefs, contradictions, and soft-archive prompts into a digest message.
- Delivered via Telegram bot.
- User responds inline; responses are parsed back into approve/reject/edit/archive actions.
- One-question-per-thread budget — if the digest is too long, queue overflow items for the next day rather than dumping everything.
- Skip digest entirely if there are zero items (don't send empty pings).
- **Acceptance**: weekday 18:30 digest arrives with 5–10 items; user can resolve all from chat; weekend silence; empty days produce no message.

### S4.3 — Contradiction detection (P2)
- Job runs nightly: for each new belief, semantic-search for active beliefs with high similarity but opposing sentiment.
- When found, write a `CONTRADICTS` edge and add to digest as a "reconcile this" prompt.
- **Acceptance**: seed two contradictory beliefs; nightly job links them and adds to digest.

### S4.4 — Conversational refinement flow (P2)
- For high-value pending beliefs (e.g., contradictions), bot opens a Socratic-style conversation.
- Prompt template: "I noticed X in [contexts]. What do you make of it?" — never leading.
- Conversation outcome writes evidence edges back to the belief.
- **Acceptance**: contradiction triggers a bot DM; user response updates the graph with new edges.

### S4.5 — Focal-node exploration (P2)
- Replace hard `limit=100` with breadth-first expansion from a focal node.
- Frontend maintains a "navigation stack" with return-to-root button.
- Lazy-load neighbors at depth N+1 on demand.
- **Acceptance**: graph with 1000 nodes is navigable without lag; user can drill from a focal node to depth 3 and return.

### S4.6 — Era-aware timeline scrub (P2)
- Explorer adds a horizontal era timeline.
- Dragging the time cursor filters the graph to that era's active state.
- **Acceptance**: scrubbing through eras visibly adds/removes nodes from the graph view.

---

## Cross-Cutting / Tech Debt

These should be picked up opportunistically inside other sprints:

- **CT1**: Replace fixed `analyzer_tick_seconds` with adaptive backpressure (faster ticks when queue depth grows).
- **CT2**: Add provenance edges (`EXTRACTED_FROM`) on rumination output, currently inconsistent.
- **CT3**: Add a `belief_calibration` metric — track approve/reject ratios per source model to detect drift.
- **CT4**: Migrate `EVOLVED_FROM` chain queries to use parameterized depth (currently unbounded recursion risk).

---

## Suggested Execution Order

1. **Sprint 1** is non-negotiable first. Without resilience, every sprint after this risks compounding silent data loss.
2. **Sprint 2** must come before any historical seeding — bulk import enables the actual self-discovery use case.
3. **Sprint 3** can run partly parallel to Sprint 2 since eras are an independent schema addition.
4. **Sprint 4** depends on the canonicalization (S2.4–5) and tiered extraction (S3.4) being in place — otherwise the approval queue gets flooded with low-quality candidates.

## Decisions Log

Resolved 2026-05-11:

- **Era boundary detection**: manual only for v1. Auto-suggestions can come later if there's signal.
- **Soft-archive trigger**: bot opens a conversation about candidates rather than queuing them silently. The interaction itself is more useful than the archival.
- **`:RejectedHypothesis` lifetime**: temporary nodes with 30-day TTL. Used as negative examples for rumination during the window, then auto-deleted. Repeated rejection (3+ in window) promotes to permanent `:RejectedBelief`.
- **Cleanup job cadence**: nightly at 23:00 local. Handles expired rejections and other housekeeping.
- **Digest cadence**: daily, weekdays only, 18:30 local. Skip empty days. Cap items per digest with overflow rolling to next day.
- **Belief extraction model split**: flagged-only. Gemma 8B handles entities/structural extraction; only `belief_candidate: true` items get routed to Gemini Flash. Keeps cost bounded.
- **Snooze digest override**: deferred. Ship daily-with-skip-empty first; revisit if friction emerges.
- **Cross-era beliefs**: no special `:Era {name: "lifetime"}` node. Instead, beliefs that keep accruing evidence have their lifetime extended automatically — every new `SUPPORTED_BY` edge bumps a `last_supported_at` timestamp, which resets the soft-archive countdown. Beliefs that span eras stay alive naturally because they keep getting reinforced; beliefs tied to a specific chapter age out via the existing soft-archive flow. No special-case schema needed.
