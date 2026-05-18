(function () {
    'use strict';

    // ══════════════════════════════════════════════════════════════════════════
    // FLOWS PAGE — Per-Scenario Data Flow Diagrams
    // ══════════════════════════════════════════════════════════════════════════
    //
    // Each scenario traces one user action through the codebase as a mermaid
    // sequenceDiagram. The diagram convention:
    //
    //   ->>   solid arrow         = synchronous awaited call
    //   -->>  dashed return       = return value
    //   -)    async no-wait arrow = fire-and-forget (BackgroundTasks,
    //                                asyncio.create_task, lazy maybe_trigger)
    //   rect rgba(...)            = block where a named lock/semaphore is held
    //   Note right of X: HTTP/...  = external I/O boundary
    //   «chokepoint» suffix       = participant where N callers fan in
    //
    // Each scenario also lists diagnostic notes — known chokepoints, where
    // demand stacks up, where state crosses async boundaries.

    const SCENARIOS = [
        // ────────────────────────────────────────────────────────────────────
        // LIFECYCLE
        // ────────────────────────────────────────────────────────────────────
        {
            id: 'app-startup',
            label: 'App startup',
            category: 'Lifecycle',
            blurb: 'uvicorn → main.py → create_platform_app() → FastAPI lifespan → MemoryManager warm-up → RuminationScheduler.start().',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant Proc as uvicorn process
    participant Main as src/main.py
    participant Fact as platform.app_factory.create_platform_app
    participant Log as core.logging_config.setup_logging
    participant Reg as platform.registry.AppRegistry
    participant Apps as 5× apps/*/app.py · get_<app>_app()
    participant Mem as memory.manager.get_memory_manager (lazy)
    participant Cx as memory.stores.chroma_store
    participant Nx as memory.stores.neo4j_store
    participant Rum as rumination.engine.RuminationScheduler
    participant PBot as bot.proactive.ProactiveBot

    Proc->>Main: process start
    Main->>Fact: create_platform_app()
    Fact->>Log: setup_logging()
    Fact->>Reg: AppRegistry()
    Fact->>Apps: get_chat / explorer / credits / financial / routine _app()
    Apps-->>Fact: AppDefinition × 5 (mount routers)
    Fact-->>Main: FastAPI instance
    Main->>Proc: uvicorn.run(app)

    Note over Proc,Fact: FastAPI lifespan startup
    Proc->>Fact: lifespan enter
    Fact->>Mem: get_memory_manager()  [first call → init]
    Mem->>Cx: ChromaClient + ensure collection
    Note right of Cx: Chroma RPC (local SQLite/HTTP)
    Mem->>Nx: Neo4jDriver.verify_connectivity()
    Note right of Nx: Bolt TCP to Neo4j
    Mem-->>Fact: MemoryManager (singleton cached)
    Fact->>Rum: RuminationScheduler(memory).start()
    Rum->>PBot: ProactiveBot(...) (owned)
    Rum-)Rum: deep_pass loop task
    Rum-)Rum: rabbit_hole loop task
    Rum-->>Fact: 2 asyncio tasks running
    Fact-->>Proc: lifespan ready · serving requests
`,
            notes: [
                "Memory connection pools are <code>lazy singleton</code> — first call wins, no shutdown teardown.",
                "RuminationScheduler launches with <code>asyncio.create_task</code> (fire-and-forget). If <code>settings.rumination_enabled=False</code>, both tasks no-op.",
                "<code>get_agent_service()</code> is NOT called at startup — it is created on first chat/HTTP request that needs the agent.",
            ],
        },
        {
            id: 'app-shutdown',
            label: 'App shutdown',
            category: 'Lifecycle',
            blurb: 'SIGINT / lifespan exit → RuminationScheduler.stop() cancels background tasks. Memory pools rely on process exit.',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant Sig as SIGINT / uvicorn
    participant Fact as platform.app_factory lifespan
    participant Rum as rumination.engine.RuminationScheduler
    participant Tasks as deep_pass / rabbit_hole asyncio tasks
    participant Mem as memory.manager.MemoryManager
    participant Nx as memory.stores.neo4j_store
    participant Cx as memory.stores.chroma_store

    Sig->>Fact: lifespan exit
    Fact->>Rum: stop()
    Rum->>Tasks: task.cancel() × N
    Tasks-->>Rum: CancelledError swallowed
    Rum-->>Fact: stopped
    Note over Mem,Cx: Connection pools NOT explicitly closed
    Note over Mem,Nx: relies on process exit to release Bolt / SQLite handles
    Fact-->>Sig: lifespan complete · process exits
`,
            notes: [
                "There is no explicit <code>memory.close()</code> — driver pools are released when the interpreter exits.",
                "If a deep-pass tick is mid-LLM call when shutdown fires, the outgoing HTTP request completes (httpx is sync inside <code>asyncio.to_thread</code>); cancellation only stops the next iteration.",
            ],
        },

        // ────────────────────────────────────────────────────────────────────
        // CHAT
        // ────────────────────────────────────────────────────────────────────
        {
            id: 'chat-web',
            label: 'Send chat message (web)',
            category: 'Chat',
            blurb: 'Browser → POST /apps/chat/message → AgentService.arun → Agent.aprocess_message → context build → LLM → memory.store → lazy analyzer trigger.',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant UI as Browser (chat-page.js)
    participant API as apps.chat.api · POST /apps/chat/message
    participant Svc as apps.chat.services.send_chat_message
    participant GW as agent_platform.public.agent_service.arun
    participant Ag as core.agent.Agent.aprocess_message
    participant Ctx as core.context.ContextManager.build
    participant Mem as memory.manager.MemoryManager
    participant Cx as memory.stores.chroma_store
    participant Router as core.router.LLMRouter
    participant Lim as core.limiter.InternalRateLimiter
    participant LLM as Gemini Flash «external»
    participant Tools as agent_platform.tools.* (optional)
    participant Trig as analyzers.graph_ingest_trigger.maybe_trigger

    UI->>API: POST {session_id, text}
    API->>Svc: send_chat_message(memory, service, ...)
    Svc->>Mem: store(user_text, role="user")
    Mem->>Cx: add_memory(embedding, metadata)
    Note right of Cx: Chroma write (local)
    Svc->>GW: arun(AgentRunRequest)
    GW->>Ag: aprocess_message(user_id, text, session_id)
    Ag->>Ctx: build(session_id)
    Ctx->>Mem: get_history(session_id, limit)
    Ctx->>Mem: search(text, k=rag_top_k)
    Mem-->>Ctx: history + RAG hits
    Ctx-->>Ag: assembled prompt
    Ag->>Router: get_best_model("chat")
    Router->>Lim: get_headroom(...)
    Lim-->>Router: 0.0–1.0
    Router-->>Ag: ModelSpec
    Ag->>LLM: chat.completion(messages, tools=[...])
    Note right of LLM: HTTPS POST generativelanguage.googleapis.com
    LLM-->>Ag: reply (may include tool calls)
    opt tool calls
        Ag->>Tools: invoke(tool_name, args)
        Tools->>Mem: read/write
        Tools-->>Ag: tool result
        Ag->>LLM: follow-up completion
        LLM-->>Ag: final reply
    end
    Ag-->>GW: AgentRunResult.reply
    GW-->>Svc: AgentRunResult
    Svc->>Mem: store(reply, role="assistant")
    Mem->>Cx: add_memory(reply)
    Mem-)Trig: maybe_trigger(self)  · fire-and-forget
    Note over Trig: count_unanalyzed() ≥ threshold? → schedule _run_once
    Svc-->>API: {reply, session_id}
    API-->>UI: 200 OK
`,
            notes: [
                "<code>memory.store()</code> fires <code>graph_ingest_trigger.maybe_trigger</code> as a lazy event — the chat reply does NOT wait for analyzer work.",
                "<code>maybe_trigger</code> only schedules <code>_run_once</code> if its own <code>_lock</code> is free; concurrent chat turns that all cross the threshold collapse into a single run.",
                "If tools are invoked, the chat path makes 2+ Gemini round-trips. Tool calls hit <code>get_memory_manager()</code> directly (no Depends).",
                "All Gemini traffic shares a single <code>InternalRateLimiter</code>; 429s back-pressure the chat reply itself.",
            ],
        },
        {
            id: 'chat-bot',
            label: 'Send Telegram message (bot)',
            category: 'Chat',
            blurb: 'Telegram poll → TelegramBot handler → Agent.aprocess_message → same memory.store + lazy trigger path → bot replies on Telegram HTTP.',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant TG as Telegram «external»
    participant Bot as bot.telegram_bot.TelegramBot
    participant Sess as bot.SessionStore (JSON-on-disk)
    participant Ag as core.agent.Agent.aprocess_message
    participant Ctx as core.context.ContextManager
    participant Mem as memory.manager.MemoryManager
    participant Router as core.router.LLMRouter
    participant LLM as Gemini Flash «external»
    participant Trig as analyzers.graph_ingest_trigger.maybe_trigger

    TG->>Bot: update (message)
    Note right of TG: long-poll HTTPS getUpdates
    Bot->>Sess: load session_id, pinned node
    Note right of Sess: JSON file read
    Bot->>Ag: aprocess_message(user_id, text, session_id)
    Ag->>Mem: store(user_text, role="user")
    Mem-)Trig: maybe_trigger · fire-and-forget
    Ag->>Ctx: build(session_id)
    Ctx->>Mem: get_history + search
    Mem-->>Ctx: history + RAG hits
    Ctx-->>Ag: prompt
    Ag->>Router: get_best_model("chat")
    Router-->>Ag: ModelSpec
    Ag->>LLM: chat.completion
    Note right of LLM: HTTPS Gemini
    LLM-->>Ag: reply
    Ag->>Mem: store(reply, role="assistant")
    Mem-)Trig: maybe_trigger · fire-and-forget
    Ag-->>Bot: reply text
    Bot->>TG: sendMessage(chat_id, reply)
    Note right of TG: HTTPS sendMessage
`,
            notes: [
                "<code>TelegramBot</code> calls <code>core.agent.Agent</code> directly (legacy pre-AgentService). Migrating to <code>AgentService.arun()</code> would make this identical to the web path.",
                "Each user turn fires <code>maybe_trigger</code> twice (user store + assistant store). The trigger's <code>_lock</code> deduplicates.",
                "<code>SessionStore</code> reads/writes a JSON file synchronously inside the async handler. Fine at single-user volume; a chokepoint if the bot ever serves many users.",
            ],
        },

        // ────────────────────────────────────────────────────────────────────
        // EXPLORER
        // ────────────────────────────────────────────────────────────────────
        {
            id: 'explorer-node-click',
            label: 'Click a node in Explorer graph',
            category: 'Explorer',
            blurb: 'Browser click → GET /graph/node/{id} → memory.graph_node_detail → Neo4j Cypher → render in detail panel.',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant UI as Browser (graph.js / panel.js)
    participant API as apps.explorer.api · GET /graph/node/{id}
    participant Svc as apps.explorer.services
    participant Mem as memory.manager.MemoryManager
    participant Nx as memory.stores.neo4j_store
    participant Neo as Neo4j «external»

    UI->>API: GET /api/explorer/graph/node/{id}
    API->>Svc: get_node_detail(memory, id)
    Svc->>Mem: graph_node_detail(id)
    Mem->>Nx: get_node_detail(id)
    Nx->>Neo: MATCH (n {id:$id})-[r]-(m) RETURN ...
    Note right of Neo: Bolt query
    Neo-->>Nx: rows
    Nx-->>Mem: {node, connections[]}
    Mem-->>Svc: dict
    Svc-->>API: dict
    API-->>UI: 200 OK {node, connections}
    opt panel wants provenance
        UI->>API: GET /graph/node/{id}/provenance
        API->>Svc: get_node_provenance
        Svc->>Mem: graph_node_provenance(id)
        Mem->>Nx: get_node_provenance(id)
        Nx->>Neo: MATCH provenance chain
        Neo-->>Nx: rows
        Nx-->>API: dict
        API-->>UI: 200 OK
    end
`,
            notes: [
                "Read-only path. Single Neo4j session per request, no locks. Cheap if Neo4j indexes are present.",
                "Detail panel may fire 2–3 parallel <code>GET</code>s (node, provenance, belief trail). These all share the Neo4j driver pool — bounded by pool size in <code>settings</code>.",
            ],
        },
        {
            id: 'nuke-and-reanalyse',
            label: 'Click Nuke & Reanalyse',
            category: 'Explorer',
            blurb: 'POST /graph/reset → wipe Neo4j + flag all Chroma rows unanalyzed → BackgroundTasks drain → LM Studio chokepoint.',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant UI as Browser (explorer-page.js)
    participant API as apps.explorer.api · POST /graph/reset
    participant Svc as apps.explorer.services.reset_graph
    participant Mem as memory.manager.MemoryManager
    participant Nx as memory.stores.neo4j_store
    participant Cx as memory.stores.chroma_store
    participant BG as FastAPI BackgroundTasks
    participant Drain as services.drain_after_reset
    participant DQ as services._drain_queue (200-row cap)
    participant Ext as analyzers.graph_ingest_trigger.run_extraction_pass
    participant GE as analyzers.graph_extraction.extract_intents
    participant GR as analyzers.graph_extraction.repair_isolated_nodes
    participant LMC as analyzers.local_llm.LMStudioClient
    participant LM as LM Studio «chokepoint»
    participant GW as tools.graph_write
    participant CBT as analyzers.cloud_belief_trigger.maybe_trigger

    UI->>API: POST /api/explorer/graph/reset
    API->>Svc: reset_graph(memory)
    Svc->>Mem: bootstrap_user_root("Kevin")
    Mem->>Nx: wipe all nodes + reseed :Person:User
    Note right of Nx: Bolt: DETACH DELETE n
    Svc->>Mem: mark_all_unanalyzed(include_ephemeral=False)
    Mem->>Cx: update all rows · analyzed=False
    Note right of Cx: Chroma metadata update
    Svc-->>API: {user, requeued: N}
    API-)BG: add_task(drain_after_reset)  · fire-and-forget
    API-->>UI: 200 OK
    Note over BG,Drain: response already returned to UI
    BG-)Drain: drain_after_reset(memory)  · NO LOCK HELD

    loop until row_cap=200 hit or queue empty
        Drain->>DQ: _drain_queue(row_cap=200)
        DQ->>Mem: count_unanalyzed()
        DQ->>Ext: run_extraction_pass(batch_size=1)
        Ext->>Mem: list_unanalyzed(1)
        Ext->>Ext: _build_sliding_windows
        loop per window
            Ext->>GE: extract_intents(window, schema, prior_ctx)
            GE->>LMC: chat_completion(messages, json_mode)
            LMC->>LM: HTTP POST /v1/chat/completions
            Note right of LM: blocking httpx · in asyncio.to_thread
            LM-->>LMC: JSON intents
            LMC-->>GE: raw
        end
        opt isolated nodes
            Ext->>GR: repair_isolated_nodes
            GR->>LMC: chat_completion (extra LM call)
            LMC->>LM: HTTP POST
            LM-->>LMC: edge intents
        end
        Ext->>GW: graph_write(intents)
        GW->>Mem: upsert nodes / edges / tasks
        Mem->>Nx: Cypher writes
        Ext->>Mem: mark_analyzed(row_ids)
        Mem->>Cx: analyzed=True
        Ext-)CBT: maybe_trigger · fire-and-forget (cloud belief pass, Gemini)
        DQ->>DQ: asyncio.sleep(30s)
    end
`,
            notes: [
                "<code>drain_after_reset</code> does NOT acquire <code>graph_ingest_trigger._lock</code>. A chat turn that arrives mid-drain fires <code>maybe_trigger → _run_once</code> in parallel — both paths hit LM Studio simultaneously.",
                "Each batch = ≥1 LM Studio call (windows × 1 row). Plus 1 extra if the batch leaves isolated nodes.",
                "<code>asyncio.sleep(30)</code> between batches is the only throttle. Removing it without serializing all LM Studio callers would saturate the local model.",
                "200-row cap is per click. Remaining queue drains on subsequent chat turns (via lazy trigger) or via the Process All button.",
            ],
        },
        {
            id: 'run-analyzer',
            label: 'Click Run Analyzer',
            category: 'Explorer',
            blurb: 'Manual one-shot extraction pass. No lock held — always runs even if a background drain is active.',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant UI as Browser
    participant API as apps.explorer.api · POST /analyze/run
    participant Svc as apps.explorer.services.run_analyzer
    participant Ext as graph_ingest_trigger.run_extraction_pass
    participant Mem as MemoryManager
    participant GE as graph_extraction.extract_intents
    participant LMC as LMStudioClient
    participant LM as LM Studio «chokepoint»
    participant GW as tools.graph_write

    UI->>API: POST /api/explorer/analyze/run {batch_size}
    API->>Svc: run_analyzer(memory, batch_size)
    Note over Svc,Ext: NO lock acquired · "manual always runs"
    Svc->>Ext: run_extraction_pass(batch_size)
    Ext->>Mem: list_unanalyzed(batch_size)
    Ext->>Ext: _build_sliding_windows
    loop per window
        Ext->>GE: extract_intents
        GE->>LMC: chat_completion
        LMC->>LM: HTTP POST
        Note right of LM: blocks per call
        LM-->>LMC: intents
    end
    Ext->>GW: graph_write(intents)
    GW->>Mem: upsert nodes / edges
    Ext->>Mem: mark_analyzed
    Ext-->>API: stats {processed, written, ...}
    API-->>UI: 200 OK
`,
            notes: [
                "Manual run is the only path with no lock check. If a background drain is in flight, two extractions hit LM Studio in parallel.",
                "Bottleneck is purely the LM Studio sequence inside the windows loop. Single user, but no protection against concurrent callers.",
            ],
        },
        {
            id: 'process-all',
            label: 'Click Process All',
            category: 'Explorer',
            blurb: 'Drain the whole unanalyzed queue. Holds _drain_lock (single-flight against itself, not against other paths).',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant UI as Browser
    participant API as apps.explorer.api · POST /analyze/process-all
    participant Svc as apps.explorer.services.process_all_queue
    participant Lock as services._drain_lock (asyncio.Lock)
    participant DQ as services._drain_queue (no cap)
    participant Ext as run_extraction_pass
    participant LM as LM Studio «chokepoint»

    UI->>API: POST /api/explorer/analyze/process-all
    API->>Svc: process_all_queue(memory)
    alt _drain_lock already held
        Svc-->>API: {started: False, reason: "already running"}
        API-->>UI: 200 OK (no-op)
    else
        rect rgba(214, 167, 90, 0.10)
            Note over Lock: holds <b>_drain_lock</b>
            Svc->>DQ: _drain_queue(row_cap=None)
            loop until queue empty
                DQ->>Ext: run_extraction_pass(batch_size=1)
                Ext->>LM: HTTP POST × windows
                Note right of LM: shared with chat-trigger / nuke-drain — NO global lock
                LM-->>Ext: intents
                DQ->>DQ: asyncio.sleep(30s)
            end
        end
        Svc-->>API: {started: True, processed: N, remaining: 0}
        API-->>UI: 200 OK
    end
`,
            notes: [
                "<code>_drain_lock</code> is single-flight only against another Process All click. It does NOT block <code>drain_after_reset</code>, manual <code>analyze/run</code>, or chat-triggered <code>_run_once</code>.",
                "Any of those other callers can run in parallel and queue requests at LM Studio.",
            ],
        },

        // ────────────────────────────────────────────────────────────────────
        // INGEST / BACKGROUND
        // ────────────────────────────────────────────────────────────────────
        {
            id: 'bulk-import',
            label: 'Bulk import a file',
            category: 'Background',
            blurb: 'POST /ingest/bulk → BulkImporter → memory.store per chunk → each store fires maybe_trigger → post-loop drain.',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant UI as Browser / curl
    participant API as apps.explorer.api · POST /ingest/bulk
    participant Svc as apps.explorer.services.run_bulk_import
    participant BI as ingestion.BulkImporter
    participant Ck as ingestion.chunker.chunk_text
    participant Mem as MemoryManager
    participant Cx as Chroma
    participant Trig as graph_ingest_trigger.maybe_trigger
    participant Ext as run_extraction_pass
    participant LM as LM Studio «chokepoint»

    UI->>API: POST /api/explorer/ingest/bulk {path}
    API->>Svc: run_bulk_import(path, memory)
    Svc->>BI: import_directory(path)
    loop per file
        BI->>BI: detect_format + parse
        BI->>Ck: chunk_text(doc, size, overlap)
        Ck-->>BI: chunks[]
        loop per chunk
            BI->>Mem: store(chunk, ephemeral=False)
            Mem->>Cx: add_memory
            Mem-)Trig: maybe_trigger · fire-and-forget
            Note over Trig: most calls no-op — <i>_lock</i> already held
        end
    end
    BI-->>Svc: {imported, skipped, errors}
    Note over Svc,Ext: post-loop drain · NO lock held
    loop up to 50 batches
        Svc->>Ext: run_extraction_pass(batch_size)
        Ext->>LM: HTTP POST × windows
        LM-->>Ext: intents
    end
    Svc-->>API: BulkImportResult + drain stats
    API-->>UI: 200 OK
`,
            notes: [
                "Two waves of LM Studio traffic: (1) the lazy <code>maybe_trigger</code> from each <code>store()</code> (mostly deduped by <code>_lock</code>), (2) the explicit post-loop <code>run_extraction_pass</code> × 50.",
                "<code>BulkImporter</code> does not deduplicate. Re-importing the same path doubles the Chroma rows; the canonicalizer is meant to clean up later.",
                "If chat is active during a bulk import, chat-triggered <code>_run_once</code> runs in parallel with the post-loop drain → two simultaneous LM Studio calls.",
            ],
        },
        {
            id: 'rumination-tick',
            label: 'Rumination deep-pass tick',
            category: 'Background',
            blurb: 'Scheduled asyncio loop → DeepPass.analyze → AgentService (Gemini) → optional digest via ProactiveBot → Telegram.',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant Clock as asyncio.sleep(deep_pass_tick_seconds)
    participant Rum as RuminationScheduler._deep_pass_loop
    participant DP as DeepPass.analyze
    participant Mem as MemoryManager
    participant GW as AgentService.arun
    participant Ag as core.agent.Agent
    participant LLM as Gemini «external»
    participant PBot as ProactiveBot.send_belief_digest
    participant TG as Telegram «external»

    Note over Clock,Rum: launched at startup, fire-and-forget task
    Clock-->>Rum: tick
    Rum->>DP: analyze(memory, service)
    DP->>Mem: list_active_beliefs(limit=1000)
    Mem-->>DP: beliefs[]
    DP->>GW: arun(AgentRunRequest synth prompt)
    GW->>Ag: aprocess_message
    Ag->>LLM: chat.completion
    Note right of LLM: HTTPS Gemini
    LLM-->>Ag: synthesis reply
    Ag-->>GW: AgentRunResult
    GW-->>DP: result
    DP->>Mem: store digest (optional)
    opt digest has content
        DP->>PBot: send_belief_digest(chat_id)
        PBot->>TG: sendMessage(chat_id, digest)
        Note right of TG: HTTPS
    end
    DP-->>Rum: done
    Rum->>Clock: sleep next tick
`,
            notes: [
                "Tick is throttled by <code>settings.deep_pass_tick_seconds</code> and only runs if <code>settings.rumination_enabled=True</code>.",
                "Touches Gemini, not LM Studio — does not contend with the analyzer pipeline.",
                "If a tick overruns the next interval, the loop body just runs back-to-back (no overlap, since it's a single asyncio task awaiting itself).",
            ],
        },
        {
            id: 'bot-reconciliation',
            label: 'Bot reconciliation reply (CT8)',
            category: 'Background',
            blurb: 'Telegram reply to a reconciliation prompt → ProactiveBot routes to refinement_extraction → LM Studio parse → memory update.',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant TG as Telegram «external»
    participant Bot as TelegramBot reply handler
    participant PBot as ProactiveBot.handle_refinement_reply
    participant Ref as analyzers.refinement_extraction.parse_reconciliation_reply
    participant LMC as LMStudioClient
    participant LM as LM Studio «chokepoint»
    participant Mem as MemoryManager
    participant Nx as Neo4j

    TG->>Bot: reply text on reconciliation thread
    Bot->>PBot: handle_refinement_reply(chat_id, text)
    PBot->>Ref: parse_reconciliation_reply(memory, text)
    Ref->>LMC: chat_completion(parse prompt, json_mode)
    LMC->>LM: HTTP POST
    Note right of LM: shared chokepoint with extraction pipeline
    LM-->>LMC: {summary, evidence, resolved}
    LMC-->>Ref: parsed
    Ref-->>PBot: dict
    PBot->>Mem: write resolution / update belief
    Mem->>Nx: Cypher
    PBot->>TG: sendMessage(confirmation)
`,
            notes: [
                "This is the only bot-initiated LM Studio call. It bypasses any analyzer locks — runs in parallel with any active drain.",
                "If LM Studio is busy, the bot reply hangs on <code>httpx</code> with a 60s timeout. No retry — user sees no reply if the call fails.",
            ],
        },
        {
            id: 'graph-ingest-external',
            label: 'Graph ingest (external POST /graph/ingest)',
            category: 'Background',
            blurb: 'External pipeline POSTs to /graph/ingest with shared secret → run_extraction_pass directly → LM Studio.',
            mermaid: String.raw`
sequenceDiagram
    autonumber
    participant Ext as External pipeline
    participant Rt as platform.graph_ingest router
    participant Cfg as settings.graph_ingest_secret
    participant Mem as MemoryManager
    participant Run as run_extraction_pass
    participant LMC as LMStudioClient
    participant LM as LM Studio «chokepoint»

    Ext->>Rt: POST /graph/ingest + X-Ingest-Secret
    Rt->>Cfg: compare secret
    alt secret mismatch
        Rt-->>Ext: 401 Unauthorized
    else
        Rt->>Run: run_extraction_pass(memory, batch_size)
        Note over Run: NO lock held · same path as manual analyze
        Run->>Mem: list_unanalyzed
        Run->>LMC: chat_completion × windows
        LMC->>LM: HTTP POST
        LM-->>LMC: intents
        Run-->>Rt: stats
        Rt-->>Ext: 200 OK {processed, written, ...}
    end
`,
            notes: [
                "Same lock-free pattern as <code>POST /analyze/run</code>. External pipelines can stack LM Studio requests at will.",
                "Shared secret check is the only auth. If exposed publicly, an attacker can drain LM Studio capacity by hammering this endpoint.",
            ],
        },
    ];

    // ══════════════════════════════════════════════════════════════════════════
    // STATE
    // ══════════════════════════════════════════════════════════════════════════

    let _mounted        = false;
    let _mermaidInited  = false;
    let _activeId       = null;
    let _renderedIds    = new Set();

    // ══════════════════════════════════════════════════════════════════════════
    // MERMAID INIT + RENDER
    // ══════════════════════════════════════════════════════════════════════════

    function _initMermaid() {
        if (_mermaidInited || typeof window.mermaid === 'undefined') return;
        window.mermaid.initialize({
            startOnLoad: false,
            theme: 'dark',
            securityLevel: 'loose',
            sequence: {
                actorMargin: 50,
                boxMargin: 8,
                noteMargin: 8,
                messageMargin: 32,
                mirrorActors: false,
                useMaxWidth: true,
                wrap: true,
            },
        });
        _mermaidInited = true;
    }

    async function _renderScenario(scenario) {
        const el = document.getElementById('flowsMermaidSrc');
        if (!el || typeof window.mermaid === 'undefined') return;
        // Mermaid 10 needs a fresh node each render — clear data-processed and
        // re-inject the source.
        el.textContent = scenario.mermaid.trim();
        el.removeAttribute('data-processed');
        try {
            await window.mermaid.run({ nodes: [el] });
            _renderedIds.add(scenario.id);
        } catch (err) {
            console.error('mermaid render failed', err);
            el.textContent = `Mermaid render failed: ${err && err.message || err}`;
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // RAIL + MAIN PANE
    // ══════════════════════════════════════════════════════════════════════════

    function _buildRail() {
        const list = document.getElementById('flowsList');
        if (!list) return;
        list.innerHTML = '';

        // Group scenarios by category, preserving array order.
        const byCategory = new Map();
        SCENARIOS.forEach(s => {
            if (!byCategory.has(s.category)) byCategory.set(s.category, []);
            byCategory.get(s.category).push(s);
        });

        byCategory.forEach((items, cat) => {
            const head = document.createElement('li');
            head.className = 'flows-rail-group';
            head.textContent = cat;
            list.appendChild(head);

            items.forEach(s => {
                const li = document.createElement('li');
                li.className = 'flows-rail-item';
                li.dataset.id = s.id;
                li.setAttribute('role', 'option');
                li.innerHTML = `${s.label}<span class="flows-rail-item-sub">${s.blurb.split('.')[0]}.</span>`;
                li.addEventListener('click', () => _select(s.id));
                list.appendChild(li);
            });
        });
    }

    function _select(id) {
        const scenario = SCENARIOS.find(s => s.id === id);
        if (!scenario) return;
        _activeId = id;

        // Rail highlight
        document.querySelectorAll('.flows-rail-item').forEach(el => {
            el.classList.toggle('is-active', el.dataset.id === id);
        });

        // Main pane
        const elCat   = document.getElementById('flowsCategory');
        const elTitle = document.getElementById('flowsTitle');
        const elBlurb = document.getElementById('flowsBlurb');
        if (elCat)   elCat.textContent   = scenario.category;
        if (elTitle) elTitle.textContent = scenario.label;
        if (elBlurb) elBlurb.textContent = scenario.blurb;

        // Notes list
        const notesEl = document.getElementById('flowsNotes');
        const notesList = document.getElementById('flowsNotesList');
        if (notesEl && notesList) {
            notesList.innerHTML = '';
            if (scenario.notes && scenario.notes.length) {
                scenario.notes.forEach(html => {
                    const li = document.createElement('li');
                    li.innerHTML = html;
                    notesList.appendChild(li);
                });
                notesEl.hidden = false;
            } else {
                notesEl.hidden = true;
            }
        }

        _initMermaid();
        _renderScenario(scenario);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // PAGE MODULE
    // ══════════════════════════════════════════════════════════════════════════

    function mount(_root, shell) {
        if (_mounted) return;
        _mounted = true;
        _buildRail();
        shell?.setSearchPlaceholder('Filter scenarios...');
        // Default to first scenario.
        if (SCENARIOS.length > 0) {
            requestAnimationFrame(() => _select(_activeId || SCENARIOS[0].id));
        }
    }

    function unmount() {
        _mounted     = false;
        _renderedIds = new Set();
    }

    function onSearch(query) {
        const q = (query || '').trim().toLowerCase();
        const items = document.querySelectorAll('.flows-rail-item');
        items.forEach(el => {
            const id = el.dataset.id;
            const s = SCENARIOS.find(x => x.id === id);
            if (!s) return;
            const haystack = `${s.label} ${s.blurb} ${s.category}`.toLowerCase();
            el.style.display = (!q || haystack.includes(q)) ? '' : 'none';
        });
    }

    window.PageRouter?.register({
        id:    'flows',
        label: 'Flows',
        role:  'cross_cutting',
        paths: ['/flows'],
        mount,
        unmount,
        onSearch,
    });
})();
