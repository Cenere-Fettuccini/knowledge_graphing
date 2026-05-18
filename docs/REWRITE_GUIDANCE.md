# AIManager Rewrite Guidance

This document distils the hard lessons embedded in the current codebase's
~200-commit history so the next implementation (three-agent design: chat
agent, backend graph-construction agent, scheduled agent) does not have to
re-discover them. Read the section relevant to what you are building; each
bullet is **rule — reason**.

Bullets marked `(?)` are reasonable inferences from commit context but were
not confirmed against current code; a human reviewer should verify before
treating them as load-bearing.

---

## 1. Concurrency & Chokepoints

The single biggest source of pain has been *uncoordinated fan-in onto one
slow LLM endpoint* (LM Studio) and *uncoordinated fan-in onto Neo4j writes*.

- **One global semaphore in front of the local LLM** — six independent
  entry points (live chat extraction × N, refinement extraction, deep pass,
  rabbit hole, manual `/analyze/run`, drain-all button, bulk-import
  post-write) all hit `chat_completion` concurrently. No global guard
  exists today and it pins the machine. Pick a fixed concurrency cap and
  serialise *across* triggers, not just within one trigger.
- **Per-trigger locks are not enough** — current code has
  `graph_ingest_trigger._lock` and `services._drain_lock` as separate
  `asyncio.Lock`s. Each guards *its own* caller pattern; together they
  still let a manual drain and an auto-trigger fight each other. In the
  rewrite, model the LLM as a single owned resource, not a stateless
  callable.
- **Single-flight per user action, not per code path** — the "Process all
  pending" button uses an `asyncio.Lock` so a second click while one drain
  runs returns `started: false` instead of stacking. Mirror this for any
  user-visible action that does meaningful work; do not let the UI queue
  duplicate work behind the user's back.
- **Throttle drains by row count + sleep, not by tick frequency** — the
  drain-after-reset path was originally uncapped and could pull up to
  1000 rows; it was clamped to 200 rows with a 2-second inter-batch sleep
  to keep the local model responsive. Pick batch sizes that complete in
  seconds, not minutes; insert mandatory sleeps between batches so other
  callers get a turn.
- **Bulk and live work share the queue; live wins** — Sprint 2 added
  "live-first" queue ordering on the analyzer: a 10k-row historical
  backfill should never block responsiveness to a fresh chat turn. If you
  share a queue between bulk and live, sort live first and bulk
  oldest-first within itself.
- **Schedulers must floor their tick interval** — a misconfigured env
  (`tick_seconds = 0`) once spun the analyzer scheduler into a tight loop.
  Floor at ~30s in code regardless of config.
- **Schedulers must not fire on startup** — the first tick is one interval
  later by design, so the system doesn't hammer LM Studio while it's still
  loading the model.
- **Adaptive pacing tied to queue depth** — when the unanalyzed queue
  crossed a threshold the scheduler switched from 900s/20-row pacing to
  60s/100-row "bulk mode" and reverted automatically when drained. Useful
  pattern: let the system pace itself, don't make the operator flip a
  toggle.
- **Lazy back-edge from write to extraction trigger** — `MemoryManager.store`
  fires `graph_ingest_trigger.maybe_trigger` as fire-and-forget. This is
  the *only* place the memory layer calls into the analyzer layer. Keep
  that direction deliberate; do not let analyzers call back into memory
  writes from inside a trigger callback or you will deadlock the lock.
- **`count_unanalyzed` failures must not block stores** — the queue-depth
  probe runs on every store; swallow its errors. A write should never fail
  because the probe couldn't talk to Chroma.
- **Sync over async at the LLM boundary** — `asyncio.to_thread` is used to
  keep the event loop unblocked while Gemini / LM Studio calls iterate.
  Without this, the bot stops responding to typing indicators and the API
  stops accepting new requests during long extractions.
- **Typing indicators need their own keepalive task** — Telegram's typing
  indicator expires every 5s; the bot spawns a `_keep_typing()` task that
  refreshes it every 4s and cancels on completion. Without this the user
  thinks the bot has died during long agent turns.

---

## 2. Memory Layer (Chroma + Neo4j split)

The split was not accidental. Chroma is the *queue + ground truth for
conversation text*; Neo4j is a *derived structured view*. Treat the graph
as a cache that can always be rebuilt from Chroma rows.

- **Chroma is the source of truth; Neo4j is derived** — the Stage-1
  refactor stopped writing to Neo4j synchronously on every chat turn.
  `MemoryManager.store()` writes Chroma with `analyzed: false`; the graph
  is built later by the extraction pipeline. This means a Neo4j wipe is
  recoverable (mark all rows unanalyzed and re-drain) and conversations
  don't block on graph writes.
- **Embeddings stay on Google even when chat moves off Gemini** — switching
  embedding provider invalidates the whole Chroma store. If you need
  offline operation, route *generation* off Google but keep embeddings on
  one provider for the lifetime of the store. Plan migration explicitly,
  do not silently swap.
- **On-disk spillover for failed writes** — when either backend is down,
  `MemoryManager` appends the op to a JSONL spillover file rather than
  silently dropping. The next scheduler tick replays. Critical: a backend
  outage must not lose data, and the user must keep chatting.
- **Health snapshots surface degradation to the chat response** —
  `AgentRunResult` carries `memory_degraded` + `memory_health`; the chat
  UI shows a chip. The user keeps talking but knows their recent writes
  haven't landed. Don't hide backend degradation behind a generic 500.
- **Health checks are cached (~60s)** — every call into MemoryManager used
  to ping both DBs. Cache aggressively; expose
  `invalidate_health_cache()` as a public method (not a `_private = 0`
  hack) for routes that need fresh status.
- **All access through the facade — never `memory.neo4j.*` or
  `memory.chroma.*`** — apps and tools that reached past the facade had to
  be refactored multiple times. Boundary violations were tracked as bugs.
  In the rewrite, make the underlying stores private by construction
  (e.g. nested module, not attribute).
- **Lazy singletons, not import-time singletons** — `memory_manager` and
  `agent_service` were originally module-level instances; this fired DB
  connections on *any* import and made testing impossible. They are now
  `get_memory_manager()` / `get_agent_service()` factories. Build the
  rewrite this way from day one.
- **Chroma `PersistentClient` has a known first-init failure** — on
  chromadb ≥ 0.5 the Rust binding sometimes fails first try with
  `AttributeError: 'RustBindingsAPI' object has no attribute 'bindings'`
  and poisons `SharedSystemClient._identifier_to_system`. The init helper
  pre-creates the persist dir, retries once on that specific error, and
  clears the shared cache between attempts. Replicate this retry or pin a
  version that doesn't have it.
- **Neo4j 5.x driver: disable `UNRECOGNIZED` notifications** — task
  queries flooded the log with "property key does not exist for
  `priority` / `due_date`" warnings on every list. Pass
  `notifications_disabled_categories=["UNRECOGNIZED"]` at driver
  construction.
- **Empty-relationship truthiness gotcha in the Neo4j Python driver** —
  the driver returns an empty list-like for "no relationships" that
  evaluates falsy in unexpected places. Explicit `is None` / `len()` checks
  needed.
- **Sanitize all label strings before Cypher** — LLMs produce
  `"Academic Goal"` / `"social-circles"` / `"  career  goal  "` and Cypher
  treats spaces as token boundaries. `sanitize_label` coerces to
  PascalCase, strips leading digits, falls back to `"Entity"` on empty,
  de-duplicates. Route every multi-label upsert through it. Without this,
  one bad LLM output aborts a whole batch.
- **Atomic batch writes via transaction context manager** — per-op writes
  meant a mid-batch failure left orphaned nodes. `batch_graph_writes()`
  yields a `GraphWriteBatch`; on exit it flushes in one transaction. On
  failure, the buffered ops spill for replay. All extraction code must
  use the batch context, never the single-op writes directly.
- **Dead-letter queue for unprocessable batches** — malformed LLM JSON
  used to loop forever on the same rows, burning LLM calls every tick.
  Add `analyzer_status` (`pending` / `success` / `failed`) + a
  failure-reason field on Chroma rows; route malformed batches to a DLQ
  that's still queryable and retryable.
- **`mark_analyzed` even on empty intent output** — if the LLM extracted
  *nothing*, still mark the row analyzed. Otherwise the trigger loops on
  the same backlog forever. Failure to extract ≠ failure to process.
- **Reject-then-don't-mark for failed writes** — when `graph_write`
  returns `ok=false` (e.g. isolation guard rejected the batch), rows are
  *not* marked analyzed so the agent can retry with better intents next
  pass. Two distinct outcomes: "LLM ran, nothing to write" (mark) vs
  "write rejected, retry later" (don't mark).
- **Belief content uses embedding-aware dedup, not string equality** —
  initial "3-strike permanent rejection" used `==` on belief content;
  paraphrases never aggregated. Use cosine similarity ≥ 0.88 against
  stored embeddings (lower than entity 0.92 because beliefs paraphrase
  more). Always store the embedding alongside the rejected node so future
  comparisons don't re-embed.
- **Belief chain depth must be clamped server-side** — `*0..20` was
  originally hardcoded. The parameterised version clamps caller input to
  `[1, 200]` because nothing prevents a malformed `:Belief` chain from
  containing a cycle.
- **Schema-drift snapshot filenames must not be parsed for dates** —
  filenames substituted `:` → `-` for filesystem safety; the loader's
  reverse `replace('-', ':', 2)` also clobbered date dashes. Snapshots
  were silently invisible to drift detection for weeks. Lesson: store
  the timestamp *inside* the JSON body and treat filenames as opaque
  identifiers.
- **Detect "small labels" in drift output** — newly introduced labels with
  fewer than 3 nodes are almost always one-off LLM hallucinations.
  Surface them as alerts before they multiply.

### Schema decisions that mattered

- **Hub topology was a mistake** — early code forced every task /
  belief / knowledge node through `TaskHub` / `BeliefHub` / `KnowledgeHub`
  super-nodes. The refactor to semantic web topology (node connects
  directly to what it relates to) made queries much simpler and stopped
  the hubs from becoming dumping grounds.
- **Beliefs are nodes, not edge properties** — `(:Belief)` with an
  `[:ABOUT]` edge to the subject, plus `[:EVOLVED_FROM]` chains for
  supersession and `[:SUPPORTED_BY]` / `[:WEAKENED_BY]` to evidence
  conversations. Edges-as-beliefs lose evidence and chain history.
- **Provenance is mandatory on every materialised node** — every node
  gets a `MENTIONED_IN` edge back to a `ConversationTurn` keyed by
  `session_id`. Otherwise you cannot answer "where did this come from?"
  and the graph becomes untrustable.
- **Tasks must hang off the entity they relate to** — `OWNS_TASK` from
  root was removed; tasks attach via `for_person` / `about_entity`.
  Auto-linking everything to root made it a giant supernode.
- **New `Person` nodes do not auto-link to the user root** — interpersonal
  edges (`FAMILY_OF`, `FRIEND_OF`) from the extractor define their place.
  Auto-linking to root created false "I know everyone" topology.
- **`Era` is a first-class node** — eras carry `start_date` / `end_date`
  (null `end_date` = ongoing); other nodes opt in via `OCCURRED_IN`. Eras
  auto-attach to root via `HAS_ERA` so the reachability sweep doesn't
  quarantine empty new eras.
- **Don't slug era IDs from name** — two trips can both be named "Berlin"
  and need to be distinct.
- **Quarantine, don't delete** — the reachability sweep labels unreachable
  nodes `:Quarantine` with a timestamp. Nothing is deleted; read paths
  filter quarantined nodes by default. `purge_quarantined` is the manual
  hard-delete on a cutoff. Soft state lets you investigate before losing
  data.
- **Tasks become ephemeral by stamping `completed_at`** — DONE / CANCELLED
  tasks stay in the graph but the default list view filters them.
  Scrollback views explicitly pass `include_completed=True`. This avoids
  task deletion (which loses history) while keeping the active list
  small.
- **`PendingBelief` / `RejectedHypothesis` as labels** — low-confidence
  beliefs land as `:PendingBelief` and get promoted to `:Belief` on
  approve, or land as `:RejectedHypothesis` with a 30-day TTL on reject.
  Rejected hypotheses stay so rumination can use them as *negative*
  examples.

---

## 3. LLM Routing & Quotas

- **Three tiers of provider exist for a reason**:
  - **Local LM Studio** for entity / edge extraction (cheap, offline, but
    a 4B model is a real quality bottleneck on subjective content).
  - **Gemini Flash** for belief extraction, contradiction detection,
    orphan reattachment, refinement parsing — anything that needs
    judgement.
  - **Embeddings on Google** — locked in by Chroma's existing vectors.
- **Local model for facts, cloud for judgement** — `graph_extraction`
  produces only entity / task / edge intents; if the local model emits a
  belief it's filtered client-side. Beliefs are routed to a separate
  cloud-belief pass. Subjective content + small model = noise.
- **`max_tokens` must accommodate reasoning models** — default raised to
  4096 because reasoning models truncated their JSON mid-token. Whatever
  the new system uses, budget for the *whole* tool-call output, not just
  the human-readable answer.
- **Multi-key Gemini router with persistent rate limiter** — the system
  rotates across multiple API keys and tracks per-key/per-model usage so
  one key's 429 doesn't kill the surface. The limiter is persistent; an
  in-memory counter loses state on restart and instantly re-429s.
- **Separate locks for local and cloud passes** — `graph_ingest_trigger`
  and `cloud_belief_trigger` use independent `asyncio.Lock`s so a slow
  Gemini call doesn't block the local pipeline (and a 429 on Gemini
  doesn't fail-closed on local extraction).
- **Cloud threshold is independent from local threshold** — typically
  lower, because cloud calls cost money and you can't let backlogs grow
  unbounded. Setting `cloud_belief_threshold=0` disables only the cloud
  auto-trigger, not the manual route.
- **Soft skip when LLM is offline, don't crash** — `LocalLLMUnavailable`
  causes the analyzer tick to *skip* and leave rows unprocessed (NOT
  marked analyzed). Crashing the scheduler loses retry semantics.
- **Bootstrap-status returns an offline flag, not a 500** — when Neo4j
  is offline the explorer activates in degraded mode instead of prompting
  for a root name. Health signals are first-class, not exceptions.

---

## 4. Agent Loop

- **Async agent processing is mandatory** — the original sync
  `process_message` blocked the bot's event loop during LLM calls; the
  bot stopped responding to other users. Build the rewrite async-first.
- **Retry with exponential backoff (3 attempts, 2s/4s/8s)** — transient
  Gemini / network errors are common enough that one-shot failure is a
  bad UX. But the user message must be persisted to Chroma *even on
  permanent LLM failure* so it isn't lost.
- **Token tracking from the response, not estimates** — earlier versions
  guessed token counts; route limits then drifted. Read the actual count
  off the LLM response metadata.
- **Single write surface for the agent** — early design had `save_belief`
  / `create_task` / `store_knowledge` as separate write tools. They
  bypassed the isolation guard and reachability sweep. They were all
  retired in favour of one `graph_write` tool that takes a list of typed
  `Intent` objects. The agent now constructs an atomic batch instead of
  firing per-fact tool calls.
- **Topological intent ordering matters** — the resolver topo-sorts
  `entity → task → belief → edge` so name→id lookups are populated before
  edges consume them. Without this, edge intents reference unresolved
  names and silently drop to root fallback.
- **Edge intents make node-to-node connections explicit** — early
  attempts had the resolver infer edges from co-occurrence; this produced
  spurious relationships. Make the LLM emit explicit `EdgeIntent`s with
  named endpoints.
- **Write-time isolation guard** — every node op in a batch must appear as
  an edge endpoint in the same batch. If any node is isolated, the whole
  batch is discarded and `ok=false` returned so the agent retries with
  the missing edge. Without this, every parser hiccup produces orphans.
- **Beliefs decompose to node + optional ABOUT edge inside the batch** —
  earlier code emitted a belief node and then a separate edge; either
  could succeed without the other. Decompose at intent time so atomicity
  is preserved.
- **LLM anchor proposal is the third-tier fallback for missing endpoints**
  — when an edge endpoint name doesn't resolve deterministically, ask
  Gemini to propose a sensible entity. Depth-capped at 3 to prevent
  infinite proposal cascades. Failure modes (LLM down, malformed output,
  name mismatch) must be caught *inside* the proposal call — never let
  them propagate or the whole batch is lost.
- **Root-reachability sweep after every commit** — BFS from
  `(:Person:User)`; anything unreachable gets `:Quarantine`. Catches
  islands the write-time guard can't see (merges, edge deletions,
  partial writes). Bail-out: if the user root isn't bootstrapped, the
  sweep is a no-op (quarantining the entire graph because no root exists
  is worse than doing nothing).
- **Orphan reattachment is semantic, not structural** — the original
  fallback was `ORPHANED_LINK` to root (dumb edge). The current pipeline
  RAG-searches Chroma for the turns that produced the orphan, fetches
  graph schema, asks Gemini Flash for a meaningful target + rel_type, and
  only falls back to `ORPHANED_LINK` if the LLM has no confident answer.
- **Defence-in-depth self-loop guard** — the orphan-reattachment prompt
  was scrubbed of the word "orphan" and the candidate list never
  contains the subject itself. There's *also* a consumer-side self-loop
  check. Both are needed: prompt hygiene drops the rate, the guard
  catches the rest.
- **Same-batch repair pass for isolated nodes** — when a batch leaves a
  node isolated, immediately re-prompt the LLM with the *same*
  conversation rows and just the missing-edge ask. Much higher precision
  than the post-commit semantic-RAG sweep (the "Mom LIKES blueberry cake"
  hallucination class).
- **Schema snapshot is fed into the extractor prompt** — labels +
  relationship types + sample entities. Without this the LLM coins
  parallel labels for the same concept on every batch.

---

## 5. Chat / Bot Flow

- **Client-generated message IDs + server-side LRU dedupe** — frontend
  generates a `client_msg_id` per send; on network error or 5xx the
  message is queued in `localStorage` and drained on the `online` event
  + 30s timer fallback. Backend maintains a per-session LRU of the last
  50 responses keyed by id; retries replay the cached reply marked
  `deduped: true` instead of re-running the agent. The cache is
  in-process — a server restart between original send and retry produces
  a duplicate, which is accepted for a single-user local app. Decide
  early whether your rewrite tolerates this.
- **Non-transient errors must NOT be queued forever** — 4xx (other than
  5xx ranges) drop instead of retrying. Otherwise bad requests pile up
  in localStorage indefinitely.
- **One terminal endpoint for conversation memory** — `ConversationMemory`
  was introduced specifically because the bot and the web chat had
  diverged on how they recorded turns and fetched recent slices. Build
  the rewrite with one abstraction from day one; don't let the bot and
  the web frontend grow their own recall logic.
- **Conversation tracking has been in-memory dict, Neo4j-resident, and
  hybrid in turn** — the multi-turn refinement state machine lives in
  Neo4j as a `:RefinementSession` node anchored to root via `NOTE_FOR`.
  Single-shot ephemeral state (edit-belief replies) stays in an
  in-memory dict. Lesson: pick *durable* (Neo4j) for state that must
  survive restart and *ephemeral* (in-memory) for state that's worthless
  past the next user message. The "consume_user_message" router checks
  durable first, then ephemeral, then falls through to the agent.
- **All multi-turn loops need an idle TTL + turn cap** — refinement
  sessions cap at 6 user turns and have a 30-min idle TTL. Without these
  a bad LLM can loop forever asking clarifying questions, and stale
  sessions accumulate. Nightly cleanup job marks idle sessions abandoned.
- **Empty clarification question from the LLM means "resolve"** — the
  parser falls back to `{action: "resolve", resolved: false}` so the
  loop always terminates. Never wait for a perfect LLM output to exit a
  loop.
- **Proactive bot (scheduled outbound DMs) has three jobs and shares the
  bot's event loop** — daily digest of pending beliefs, weekly
  soft-archive prompt for one dormant person, nightly cleanup of expired
  rejections. APScheduler starts in `Application.post_init` so it shares
  the loop. Skip entirely when there's nothing to show (no empty pings).
- **Allowed-user-ids gate must disable proactive bot too** — if no users
  are allowed, the scheduler doesn't start at all.

---

## 6. Knowledge Graph Extraction

The pipeline grew in layers. Each layer exists because a previous layer
was insufficient:

1. **Regex extractor** (deleted) — too brittle.
2. **`KnowledgeAnalyzer`** (deleted) — single LLM pass over Chroma queue,
   wrote directly to Neo4j with per-op transactions. Replaced because
   per-op writes left orphans and the scheduled-tick pattern was
   superseded by count-triggered.
3. **`graph_ingest_trigger` + `graph_extraction` + `graph_write`** —
   count-triggered (queue depth crossing threshold), single transaction
   per batch, isolation guard, reachability sweep, dead-letter queue,
   spillover replay.
4. **`cloud_belief_extraction`** — separate cloud pass for belief-quality
   subjective content, also count-triggered with an independent lock.
5. **`orphan_reattachment`** — post-commit semantic sweep using RAG +
   Gemini to attach isolated nodes meaningfully.
6. **`refinement_extraction`** — parses user's natural-language
   reconciliation replies into structured `SUPPORTED_BY` / `WEAKENED_BY`
   edges.

- **Count-triggered beats time-triggered** — time-based ticks either
  burn LLM calls on an empty queue or fall behind a busy one. Triggering
  on `count_unanalyzed >= threshold` self-adapts to load.
- **`graph_ingest_threshold = 0` disables the local trigger entirely** —
  for environments that only want manual extraction. Same shape for
  cloud.
- **Stamp `belief_candidate=true` on Chroma rows when the local pass
  succeeds** — the cloud pass drains rows where `belief_candidate AND
  NOT belief_processed`. Empty cloud output still clears the flag so
  Gemini doesn't get re-asked the same rows.
- **RAG window for re-prompting: 15 turns, not 5** — original 5-turn
  window missed context for orphan reattachment. Widen when you need the
  LLM to actually understand what entity it's seeing.
- **Contradiction detection is two-stage: cosine shortlist + LLM verdict**
  — pairwise cosine similarity gets candidates cheaply (similarity
  alone fires on paraphrases of the same idea, which we *don't* want
  labelled contradictions). Only the LLM's "yes these contradict"
  verdict actually writes the edge. Stores `run_id` so re-runs are
  idempotent.
- **Quarantined beliefs are excluded from the sweep** — otherwise islands
  pollute the readout.
- **MERGE for contradiction edges to stay idempotent** — re-runs must
  not double-stamp.
- **Source provenance on every belief** — `extraction_method`
  (`deep_pass` / `rabbit_hole` / `cloud_extract` / agent), optional
  `derived_from_belief_id` for the deep pass's synthesis chain
  (`[:DEDUCED_FROM]`), and `source_session_id` linking back to the
  Chroma row via `[:EXTRACTED_FROM]`. Without these you cannot walk back
  from an insight to its origin and the explorer can't differentiate
  human-confirmed from machine-synthesised.
- **Calibration metric: per-source approve / reject counts** — the
  digest gives clean ground truth on which beliefs the user keeps;
  surface as an aggregate per `source` so you know whether rumination is
  worth its compute or whether cloud-extract has higher precision than
  the agent's direct emits.
- **Approve / reject preserve `source` and other properties** — Neo4j
  label changes leave properties intact; rely on this for the
  calibration metric.
- **Schema is open on first sight** — new labels and edge types are
  accepted automatically; the operator prunes later through the
  explorer. Closed-schema gating produced more friction than precision.

---

## 7. Frontend / Explorer

Frontend is being kept; lessons here are mostly principles, not API
prescriptions.

- **Persist node positions across polls** — incremental graph reloads
  keep surviving nodes' positions; only genuinely new nodes get fresh
  placement plus a short relaxation pass near a connected anchor.
  Without this, every poll relays out the whole graph and the user
  loses their spatial memory.
- **Fade out removed nodes over several frames; re-index edges via
  persisted `sid` / `tid`** — Otherwise array compaction leaves
  dangling edge references.
- **Deterministic seed for node placement** — early frontend used
  `Math.random()` for cluster offsets; positions changed on every
  refresh. Hash the node id and seed a PRNG; spatial memory matters.
- **Custom canvas renderer beat 3D force-directed library** — for this
  use case (annotations, era timelines, focal navigation) a custom
  renderer was simpler than fighting a library's layout. Keep this if
  the new design has similar requirements.
- **Don't double-apply zoom transforms** — SVG `viewBox` +
  `preserveAspectRatio` already fits the diagram; an extra zoom
  transform on top double-scaled.
- **Status panel must be fluid, not fixed-height** — hard-coded
  140px hid critical controls below the fold. Use
  `minmax(200px, min(45vh, max-content))`.
- **Zoom buttons must kill ongoing animations AND sync targetFov** — a
  click that only mutates `fov` gets silently re-absorbed by any
  in-flight animation. Synchronize the animation target with the new
  value, not just the current value.
- **Bind keyboard shortcuts once** — `initGraph` may run multiple times;
  guard the listener install so you don't pile up duplicate handlers.
- **Hex-alpha suffixes (`#aabbccff`) only work on 6-char hex** — using
  them on HSL strings produced silent wrong colors. Use `globalAlpha`
  for opacity, never string concatenation.
- **NaN-defensive node rendering** — guard against undefined
  `animScale` / `edgeProgress` before the BFS loop runs; the edge-less
  bootstrap graph (single root node) hit this and silently rendered
  nothing.
- **Add new SPA routes to `legacy_route_prefixes`** — hard-refresh on a
  client-side route otherwise hits FastAPI's 404 JSON, not the SPA shell.
  Every new top-level route needs this.

---

## 8. Operational Gotchas

- **Redact secrets in log records, not in log call sites** — the original
  approach was "don't log URLs with keys". httpx logs URLs at INFO with
  the URL passed as an *arg* (URL object, not string), so any printf-
  style filter that only redacts the message string misses it. The fix
  *materialises* the formatted message, redacts that, writes it back as
  `msg`, sets `args=None`. Catches any arg whose `__str__` contains a
  credential.
- **Attach the redactor to handlers, not loggers** — handler filters run
  for every record the handler emits, including records propagated up
  from unknown child loggers (`httpx._client`, `google.*`). Attaching to
  specific named loggers misses records from new dependency versions.
- **`setup_logging()` must be idempotent and runnable after external libs
  install handlers** — uvicorn (and others) install root handlers
  before app code runs; the original `setup_logging` short-circuited if
  root already had a handler, so the redactor never attached.
- **Shared-secret auth for the graph-ingest HTTP endpoint** —
  `POST /graph/ingest` checks `X-Graph-Ingest-Secret` against
  `settings.graph_ingest_secret`. If the secret is **unset**, the route
  returns **503**, not 401 — opening an unauthenticated write path
  because someone forgot an env var would be much worse than the
  endpoint being unavailable. Fail closed.
- **`.env` is symlinked from the repo root** — when working in a
  worktree, recreate the symlink (`ln -s …/.env .env`) or every config
  read returns defaults. Document this in the rewrite's setup.
- **Worktrees and `.claude/` were a source of confusion** — track
  `.claude/` config but `.gitignore` worktrees and local settings.
- **Singleton driver close in worker scripts kills the shared driver** —
  the night-shift runner originally instantiated its own
  `MemoryManager()` then called `memory.neo4j.driver.close()`. That
  closes the shared singleton's driver. Always use
  `get_memory_manager()` and let process exit handle cleanup.
- **Don't `MemoryManager()` directly in tools** — every tool should call
  `get_memory_manager()` inside its function body, not hold a
  module-level reference. Module-level reference fires DB connections on
  import.
- **`/api/system/status` invalidates the health cache before responding**
  — without this the UI saw stale "offline" for up to 60s after a
  backend came back. Status endpoints need to be liveness probes, not
  cache reads.
- **Auto-reload graph when Neo4j transitions offline → online** — the
  status manager tracks `_prevNeo4j` and triggers a graph reload on the
  transition. Otherwise the user has to manually refresh after every
  hiccup.

---

## What to Keep

- **The Chroma-as-queue, Neo4j-as-derived-view split.** Re-deriving the
  graph from conversation rows has saved the system multiple times.
- **`graph_write` as a single typed-intent batch tool.** The isolation
  guard + topo-resolver + reachability sweep + LLM anchor proposal stack
  is the right shape; only the implementation lives in the wrong file.
- **Count-triggered extraction with separate locks for local and cloud.**
  Independent failure modes, independent thresholds.
- **Spillover JSONL for failed writes + scheduler-driven replay.** Simple
  and resilient; do not skip it.
- **Dead-letter queue for malformed LLM batches.** Cheap to add, prevents
  infinite-loop LLM burn.
- **PendingBelief → Belief / RejectedHypothesis lifecycle with TTL on
  rejections.** Rejected hypotheses as negative examples for rumination
  is a genuinely useful pattern.
- **Quarantine instead of delete, with `purge_quarantined` as a separate
  step.** Soft state lets you investigate.
- **`sanitize_label`, `notifications_disabled_categories`, the Chroma
  init retry.** All three are low-level workarounds you will rediscover
  in pain if you skip them.
- **Client-generated `client_msg_id` + offline queue + server-side LRU
  dedupe.** The simplest correct shape for "user kept typing while
  network died".
- **Provenance edges on everything materialised** (`MENTIONED_IN`,
  `EXTRACTED_FROM`, `DEDUCED_FROM`, `source` property). Walk-back is
  worth its storage cost.
- **The custom canvas renderer + persistent node positions.** Spatial
  memory genuinely helps comprehension.
- **`/flows` page concept** — per-action sequence diagrams annotated with
  sync / async / lock-held / chokepoint markings. Build this into the
  rewrite from the start; the connections it surfaces are the same ones
  you'll fight about in code review.

## What to Throw Away

- **Direct-write tools** (`save_belief`, `create_task`, `store_knowledge`)
  alongside `graph_write`. Two write surfaces means two places that need
  the isolation guard; we always forgot one.
- **Hub topology** (`TaskHub` / `BeliefHub` / `KnowledgeHub`). Already
  retired; do not reintroduce.
- **Per-type intent queue tools** that the agent fires one-by-one. The
  agent should construct a batch and submit once.
- **Time-tick `AnalyzerScheduler`.** Count-triggered + manual drain
  covers everything it did, without the empty-queue LLM burn or the
  config sprawl (`analyzer_tick_seconds`, `analyzer_bulk_threshold`,
  etc).
- **Multiple model picker UIs** when there's only one provider. The
  per-run model dropdown and per-model headroom bars were dead UI after
  the local-LLM consolidation.
- **`scraper.py`, `analyzer.py` (SLM classifier), `privacy.py` (SLM PII
  redactor), `proactive.py` (early version), `rumination.py` (early
  version), `forward_pass.py`, `slm_filter.py`, the regex
  `knowledge_extractor.py`, the `research/` stubs, the duplicate
  `src/tools/tasks.py`.** Each was retired with prejudice; don't port
  them.
- **`src/core/tools.py` compatibility shim and `src/api/routes.py`
  compatibility layer.** Both were "we'll clean this up later" routes
  that lasted a year. Just don't create them.
- **Module-level singletons of `MemoryManager` and `AgentService`.**
  Lazy factories from day one.
- **`KnowledgeAnalyzer` legacy module.** Superseded entirely by
  `graph_ingest_trigger` → `graph_extraction` → `graph_write`.

## Known Dragons

Things that broke before and will likely break again if naively
re-implemented:

1. **Concurrent LLM fan-in pinning a single local model.** Six callers,
   no global semaphore. Will deadlock CPU on day one of the rewrite
   unless you build it in.
2. **Module-level imports firing DB connections.** Makes the entire
   codebase un-testable in isolation. Easy to do without realising;
   bites you when you write the first unit test.
3. **Chroma's `PersistentClient` first-init failure.** Will fail on a
   fresh worktree clone. Wrap init in the documented retry.
4. **Neo4j driver returning falsy empty-relationship objects.** Explicit
   `is None` / `len()` checks needed.
5. **LLM-coined labels with spaces aborting whole Cypher statements.**
   Every multi-label upsert must go through `sanitize_label`.
6. **Orphan production at every layer of the extraction pipeline.**
   Write-time isolation guard, post-commit reachability sweep, semantic
   reattachment, AND defence-in-depth self-loop guard — all four exist
   because each catches something the others miss.
7. **Belief paraphrases bypassing rejection counting.** Use embedding
   similarity, not string equality.
8. **httpx logging full URLs (URL object) at INFO** — leaks API keys to
   stdout unless the redactor handles non-string args correctly.
9. **Worker scripts closing the shared Neo4j driver.** Use the singleton
   factory; let process exit clean up.
10. **Chat dedupe: server restart between original send and retry
    duplicates the work.** In-memory LRU only. If your rewrite needs
    cross-restart dedupe, persist the cache.
11. **Multi-turn LLM loops without a turn cap or idle TTL** will loop
    forever on a confused model. Hard cap both.
12. **Frontend hex-alpha string concat** for opacity silently produces
    wrong colors on HSL strings. Use `globalAlpha`.
13. **Refresh-time graph relayout** loses spatial memory. Persist
    positions per node id.
14. **SPA routes 404 on hard-refresh** unless registered in
    `legacy_route_prefixes`. Bite once per new route.
15. **Schedulers firing on startup** before LM Studio is loaded. Always
    delay the first tick by one full interval.
16. **`mark_analyzed` vs `mark_failed` vs "don't mark"** — three distinct
    outcomes that get conflated. The rules: empty output = mark; bad
    JSON = DLQ (mark_failed); rejected write = leave unmarked for retry.
17. **Snapshot filenames with sanitised characters.** Don't try to
    reverse the sanitisation on read. Store the metadata in the file.
18. **Auth that defaults to "no secret set ⇒ open"** — invert the
    default. No secret ⇒ 503.

---

*Document drawn from ~200 commits, April 2026 – May 2026. Cross-reference
any specific design decision against the original commit message before
committing to it in the rewrite.*
