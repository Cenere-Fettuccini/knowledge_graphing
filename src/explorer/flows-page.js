(function () {
    'use strict';

    // ══════════════════════════════════════════════════════════════════════════
    // FLOWS PAGE — Single-screen d3 data-flow map with scenario highlighting
    // ══════════════════════════════════════════════════════════════════════════
    //
    // One canvas shows every concrete function / class / process that
    // participates in any data path. Selecting a scenario from the left rail
    // dims everything that doesn't participate and draws the ordered edges
    // for that scenario, annotated with sync / async / fire-and-forget /
    // lock / external-I/O semantics.

    // ── LAYER COLUMNS ─────────────────────────────────────────────────────────
    // 6 columns flow left → right: where the data originates → where it lands.
    const LAYERS = {
        entry:    { label: 'Entry',     col: 0, color: '#70695f' },
        route:    { label: 'Routes',    col: 1, color: '#7E91BE' },
        service:  { label: 'Services',  col: 2, color: '#7FA38D' },
        gateway:  { label: 'Gateway',   col: 3, color: '#BEAA7E' },
        analyzer: { label: 'Analyzers', col: 4, color: '#C49B76' },
        external: { label: 'External',  col: 5, color: '#A37A87' },
    };

    // ── NODES ────────────────────────────────────────────────────────────────
    //   id        — stable string id used by SCENARIOS
    //   label     — short display text
    //   layer     — which column it lives in
    //   y         — fractional vertical position (0–1) inside the column
    //   sub       — small subscript label (optional, e.g. "asyncio.Lock")
    //   desc      — tooltip text (optional)
    const NODES = [
        // ── Column 0: Entry points
        { id: 'browser',         label: 'Browser',                       layer: 'entry',    y: 0.10, sub: 'web UI' },
        { id: 'telegram',        label: 'Telegram',                      layer: 'entry',    y: 0.30, sub: 'long-poll' },
        { id: 'ext-pipeline',    label: 'External pipeline',             layer: 'entry',    y: 0.55, sub: 'X-Ingest-Secret' },
        { id: 'uvicorn',         label: 'uvicorn',                       layer: 'entry',    y: 0.78, sub: 'lifespan' },

        // ── Column 1: Routes / Bot / Scheduler
        { id: 'chat-api',        label: 'apps.chat.api',                 layer: 'route',    y: 0.06 },
        { id: 'explorer-api',    label: 'apps.explorer.api',             layer: 'route',    y: 0.18 },
        { id: 'graph-ingest',    label: 'platform.graph_ingest',         layer: 'route',    y: 0.32, sub: '/graph/ingest' },
        { id: 'app-factory',     label: 'platform.app_factory',          layer: 'route',    y: 0.46, sub: 'lifespan' },
        { id: 'bot-tg',          label: 'bot.TelegramBot',               layer: 'route',    y: 0.60 },
        { id: 'bot-proactive',   label: 'bot.ProactiveBot',              layer: 'route',    y: 0.74 },
        { id: 'rum-scheduler',   label: 'rumination.Scheduler',          layer: 'route',    y: 0.88, sub: 'asyncio tasks' },

        // ── Column 2: Services
        { id: 'chat-svc',        label: 'chat.send_chat_message',        layer: 'service',  y: 0.05 },
        { id: 'exp-node',        label: 'explorer.get_node_detail',      layer: 'service',  y: 0.16 },
        { id: 'exp-reset',       label: 'explorer.reset_graph',          layer: 'service',  y: 0.27 },
        { id: 'exp-run',         label: 'explorer.run_analyzer',         layer: 'service',  y: 0.37, sub: 'no lock' },
        { id: 'exp-procall',     label: 'explorer.process_all_queue',    layer: 'service',  y: 0.47, sub: '_drain_lock' },
        { id: 'exp-drain-after', label: 'explorer.drain_after_reset',    layer: 'service',  y: 0.57, sub: 'BG task' },
        { id: 'exp-drain-q',     label: 'explorer._drain_queue',         layer: 'service',  y: 0.67, sub: '30s sleep' },
        { id: 'exp-bulk',        label: 'explorer.run_bulk_import',      layer: 'service',  y: 0.77 },
        { id: 'bulk-importer',   label: 'ingestion.BulkImporter',        layer: 'service',  y: 0.86 },
        { id: 'deep-pass',       label: 'rumination.DeepPass',           layer: 'service',  y: 0.95 },

        // ── Column 3: Gateway / Agent / Trigger / Memory facade
        { id: 'agent-svc',       label: 'AgentService.arun',             layer: 'gateway',  y: 0.06 },
        { id: 'agent',           label: 'core.agent.Agent',              layer: 'gateway',  y: 0.18 },
        { id: 'ctx-mgr',         label: 'core.context.Context',          layer: 'gateway',  y: 0.30 },
        { id: 'llm-router',      label: 'core.router.LLMRouter',         layer: 'gateway',  y: 0.42 },
        { id: 'memory',          label: 'memory.MemoryManager',          layer: 'gateway',  y: 0.56, sub: 'lazy singleton' },
        { id: 'trig-maybe',      label: 'trigger.maybe_trigger',         layer: 'gateway',  y: 0.70, sub: '_lock' },
        { id: 'trig-extract',    label: 'trigger.run_extraction_pass',   layer: 'gateway',  y: 0.84, sub: 'sliding windows' },

        // ── Column 4: Analyzers / Tools
        { id: 'extract-int',     label: 'graph_extraction.extract',      layer: 'analyzer', y: 0.07 },
        { id: 'repair-iso',      label: 'graph_extraction.repair',       layer: 'analyzer', y: 0.18 },
        { id: 'refinement',     label: 'refinement_extraction',         layer: 'analyzer', y: 0.30 },
        { id: 'contradiction',   label: 'contradiction_detection',       layer: 'analyzer', y: 0.42 },
        { id: 'orphan',          label: 'orphan_reattachment',           layer: 'analyzer', y: 0.54 },
        { id: 'cloud-belief',    label: 'cloud_belief_extraction',       layer: 'analyzer', y: 0.66 },
        { id: 'lmstudio-client', label: 'LMStudioClient',                layer: 'analyzer', y: 0.78, sub: 'httpx' },
        { id: 'graph-write',     label: 'tools.graph_write',             layer: 'analyzer', y: 0.90 },

        // ── Column 5: External I/O
        { id: 'lmstudio-ext',    label: 'LM Studio',                     layer: 'external', y: 0.12, sub: 'chokepoint' },
        { id: 'gemini-ext',      label: 'Gemini',                        layer: 'external', y: 0.30, sub: 'HTTPS' },
        { id: 'telegram-ext',    label: 'Telegram HTTPS',                layer: 'external', y: 0.48 },
        { id: 'chroma-ext',      label: 'Chroma',                        layer: 'external', y: 0.66, sub: 'RPC / SQLite' },
        { id: 'neo4j-ext',       label: 'Neo4j',                         layer: 'external', y: 0.84, sub: 'Bolt' },
    ];

    const NODE_BY_ID = {};
    NODES.forEach(n => { NODE_BY_ID[n.id] = n; });

    // ── EDGE KINDS (visual conventions) ──────────────────────────────────────
    const KINDS = {
        sync:     { color: '#7AB0FF', dash: null,      width: 1.8, label: 'sync / awaited'   },
        async:    { color: '#7AB0FF', dash: '4,3',     width: 1.8, label: 'async'             },
        forget:   { color: '#C49B76', dash: '2,4',     width: 1.8, label: 'fire-and-forget'   },
        locked:   { color: '#E0A45F', dash: null,      width: 2.4, label: 'held under lock'   },
        external: { color: '#9BD4A8', dash: null,      width: 2.0, label: 'external I/O'      },
        choke:    { color: '#E6B673', dash: null,      width: 2.8, label: 'chokepoint hit'    },
    };

    // ── SCENARIOS ────────────────────────────────────────────────────────────
    //   steps: ordered list of edges {from, to, kind, detail?}
    //   nodes: optional explicit node set (auto-derived from steps otherwise)
    //   notes: bullet list of diagnostic observations
    const SCENARIOS = [
        // ── Lifecycle ────────────────────────────────────────────────────────
        {
            id: 'app-startup',
            label: 'App startup',
            category: 'Lifecycle',
            blurb: 'uvicorn → app_factory → FastAPI lifespan → memory warm-up → rumination start.',
            steps: [
                { from: 'uvicorn',       to: 'app-factory',    kind: 'sync',   detail: '1 · create_platform_app()' },
                { from: 'app-factory',   to: 'memory',         kind: 'sync',   detail: '2 · get_memory_manager() warm-up' },
                { from: 'memory',        to: 'chroma-ext',     kind: 'sync',   detail: '3 · Chroma client init' },
                { from: 'memory',        to: 'neo4j-ext',      kind: 'sync',   detail: '4 · Neo4j driver verify' },
                { from: 'app-factory',   to: 'rum-scheduler',  kind: 'sync',   detail: '5 · RuminationScheduler.start()' },
                { from: 'rum-scheduler', to: 'deep-pass',      kind: 'forget', detail: '6 · asyncio.create_task' },
                { from: 'rum-scheduler', to: 'bot-proactive',  kind: 'sync',   detail: '7 · ProactiveBot(memory)' },
            ],
            notes: [
                "<code>MemoryManager</code> is a lazy singleton — first call wins, no shutdown teardown.",
                "<code>AgentService</code> is NOT created at startup; it's lazy on first agent run.",
                "RuminationScheduler tasks no-op if <code>settings.rumination_enabled=False</code>.",
            ],
        },
        {
            id: 'app-shutdown',
            label: 'App shutdown',
            category: 'Lifecycle',
            blurb: 'lifespan exit → cancel rumination tasks → memory pools rely on process exit.',
            steps: [
                { from: 'uvicorn',       to: 'app-factory',    kind: 'sync',   detail: '1 · lifespan exit' },
                { from: 'app-factory',   to: 'rum-scheduler',  kind: 'sync',   detail: '2 · stop()' },
                { from: 'rum-scheduler', to: 'deep-pass',      kind: 'async',  detail: '3 · task.cancel()' },
            ],
            notes: [
                "No explicit <code>memory.close()</code> — driver pools released on process exit.",
                "In-flight LM Studio call completes (httpx blocks inside <code>asyncio.to_thread</code>); cancellation only stops the next iteration.",
            ],
        },

        // ── Chat ─────────────────────────────────────────────────────────────
        {
            id: 'chat-web',
            label: 'Send chat message (web)',
            category: 'Chat',
            blurb: 'Browser → chat.api → AgentService → Agent → context + LLM → memory.store → lazy maybe_trigger.',
            steps: [
                { from: 'browser',       to: 'chat-api',       kind: 'sync',     detail: '1 · POST /apps/chat/message' },
                { from: 'chat-api',      to: 'chat-svc',       kind: 'sync',     detail: '2 · send_chat_message(memory, service)' },
                { from: 'chat-svc',      to: 'memory',         kind: 'sync',     detail: '3 · store(user_text)' },
                { from: 'memory',        to: 'chroma-ext',     kind: 'external', detail: '4 · Chroma write' },
                { from: 'memory',        to: 'trig-maybe',     kind: 'forget',   detail: '5 · maybe_trigger (fire-and-forget)' },
                { from: 'chat-svc',      to: 'agent-svc',      kind: 'sync',     detail: '6 · arun(AgentRunRequest)' },
                { from: 'agent-svc',     to: 'agent',          kind: 'sync',     detail: '7 · aprocess_message' },
                { from: 'agent',         to: 'ctx-mgr',        kind: 'sync',     detail: '8 · build context' },
                { from: 'ctx-mgr',       to: 'memory',         kind: 'sync',     detail: '9 · get_history + search' },
                { from: 'agent',         to: 'llm-router',     kind: 'sync',     detail: '10 · get_best_model' },
                { from: 'agent',         to: 'gemini-ext',     kind: 'external', detail: '11 · chat.completion' },
                { from: 'chat-svc',      to: 'memory',         kind: 'sync',     detail: '12 · store(reply)' },
                { from: 'memory',        to: 'trig-maybe',     kind: 'forget',   detail: '13 · maybe_trigger' },
            ],
            notes: [
                "Chat reply does NOT wait for analyzer work — <code>maybe_trigger</code> is fire-and-forget.",
                "If the threshold is crossed, <code>maybe_trigger</code> spawns <code>_run_once</code> under <code>_lock</code>; concurrent chat turns collapse into one run.",
                "Tool calls (not shown) add another Gemini round-trip and may write back through <code>graph_write</code>.",
            ],
        },
        {
            id: 'chat-bot',
            label: 'Send Telegram message (bot)',
            category: 'Chat',
            blurb: 'Telegram update → TelegramBot → Agent (direct, legacy) → memory.store → lazy trigger → reply.',
            steps: [
                { from: 'telegram',      to: 'bot-tg',         kind: 'sync',     detail: '1 · getUpdates returns' },
                { from: 'bot-tg',        to: 'agent',          kind: 'sync',     detail: '2 · aprocess_message (legacy direct)' },
                { from: 'agent',         to: 'memory',         kind: 'sync',     detail: '3 · store(user_text)' },
                { from: 'memory',        to: 'chroma-ext',     kind: 'external', detail: '4 · Chroma write' },
                { from: 'memory',        to: 'trig-maybe',     kind: 'forget',   detail: '5 · maybe_trigger' },
                { from: 'agent',         to: 'ctx-mgr',        kind: 'sync',     detail: '6 · build context' },
                { from: 'ctx-mgr',       to: 'memory',         kind: 'sync',     detail: '7 · history + search' },
                { from: 'agent',         to: 'gemini-ext',     kind: 'external', detail: '8 · chat.completion' },
                { from: 'agent',         to: 'memory',         kind: 'sync',     detail: '9 · store(reply)' },
                { from: 'bot-tg',        to: 'telegram-ext',   kind: 'external', detail: '10 · sendMessage' },
            ],
            notes: [
                "<code>TelegramBot</code> bypasses <code>AgentService</code> — only non-app caller of <code>core.agent.Agent</code> directly.",
                "<code>SessionStore</code> JSON writes are synchronous inside the async handler — chokepoint at scale.",
            ],
        },

        // ── Explorer ─────────────────────────────────────────────────────────
        {
            id: 'explorer-node',
            label: 'Click a node in Explorer',
            category: 'Explorer',
            blurb: 'GET /graph/node/{id} → memory.graph_node_detail → Neo4j Cypher → detail panel.',
            steps: [
                { from: 'browser',       to: 'explorer-api',   kind: 'sync',     detail: '1 · GET /graph/node/{id}' },
                { from: 'explorer-api',  to: 'exp-node',       kind: 'sync',     detail: '2 · get_node_detail' },
                { from: 'exp-node',      to: 'memory',         kind: 'sync',     detail: '3 · graph_node_detail(id)' },
                { from: 'memory',        to: 'neo4j-ext',      kind: 'external', detail: '4 · MATCH (n {id})-[r]-(m)' },
            ],
            notes: [
                "Read-only. Single Neo4j session per request, no locks.",
                "Detail panel may fire 2–3 parallel GETs — all share the Neo4j driver pool.",
            ],
        },
        {
            id: 'nuke-and-reanalyse',
            label: 'Click Nuke & Reanalyse',
            category: 'Explorer',
            blurb: 'reset_graph wipes Neo4j + flags all Chroma rows unanalyzed; BackgroundTasks drain hits LM Studio.',
            steps: [
                { from: 'browser',         to: 'explorer-api',   kind: 'sync',     detail: '1 · POST /graph/reset' },
                { from: 'explorer-api',    to: 'exp-reset',      kind: 'sync',     detail: '2 · reset_graph(memory)' },
                { from: 'exp-reset',       to: 'memory',         kind: 'sync',     detail: '3 · bootstrap_user_root' },
                { from: 'memory',          to: 'neo4j-ext',      kind: 'external', detail: '4 · DETACH DELETE n' },
                { from: 'exp-reset',       to: 'memory',         kind: 'sync',     detail: '5 · mark_all_unanalyzed' },
                { from: 'memory',          to: 'chroma-ext',     kind: 'external', detail: '6 · update analyzed=False' },
                { from: 'explorer-api',    to: 'exp-drain-after',kind: 'forget',   detail: '7 · BackgroundTasks · NO LOCK' },
                { from: 'exp-drain-after', to: 'exp-drain-q',    kind: 'async',    detail: '8 · _drain_queue(row_cap=200)' },
                { from: 'exp-drain-q',     to: 'trig-extract',   kind: 'async',    detail: '9 · loop run_extraction_pass' },
                { from: 'trig-extract',    to: 'extract-int',    kind: 'async',    detail: '10 · per sliding window' },
                { from: 'extract-int',     to: 'lmstudio-client',kind: 'sync',     detail: '11 · chat_completion' },
                { from: 'lmstudio-client', to: 'lmstudio-ext',   kind: 'choke',    detail: '12 · POST /v1/chat/completions' },
                { from: 'trig-extract',    to: 'repair-iso',     kind: 'async',    detail: '13 · if isolated nodes' },
                { from: 'repair-iso',      to: 'lmstudio-client',kind: 'sync',     detail: '14 · extra LM call' },
                { from: 'trig-extract',    to: 'graph-write',    kind: 'sync',     detail: '15 · graph_write(intents)' },
                { from: 'graph-write',     to: 'memory',         kind: 'sync',     detail: '16 · upsert nodes / edges' },
                { from: 'memory',          to: 'neo4j-ext',      kind: 'external', detail: '17 · Cypher writes' },
            ],
            notes: [
                "<code>drain_after_reset</code> holds NO lock. A chat turn arriving mid-drain fires <code>_run_once</code> in parallel — both paths hit LM Studio simultaneously.",
                "Each batch costs at least 1 LM Studio call (windows × 1 row) + up to 1 repair call.",
                "<code>asyncio.sleep(30)</code> between batches is the only throttle — and it doesn't span callers.",
                "200-row cap per click; the rest drains on subsequent chat turns or via Process All.",
            ],
        },
        {
            id: 'run-analyzer',
            label: 'Click Run Analyzer',
            category: 'Explorer',
            blurb: 'Manual one-shot extraction; no lock held — runs in parallel with any active drain.',
            steps: [
                { from: 'browser',         to: 'explorer-api',   kind: 'sync',     detail: '1 · POST /analyze/run' },
                { from: 'explorer-api',    to: 'exp-run',        kind: 'sync',     detail: '2 · run_analyzer (NO LOCK)' },
                { from: 'exp-run',         to: 'trig-extract',   kind: 'async',    detail: '3 · run_extraction_pass' },
                { from: 'trig-extract',    to: 'memory',         kind: 'sync',     detail: '4 · list_unanalyzed' },
                { from: 'trig-extract',    to: 'extract-int',    kind: 'async',    detail: '5 · per window' },
                { from: 'extract-int',     to: 'lmstudio-client',kind: 'sync',     detail: '6 · chat_completion' },
                { from: 'lmstudio-client', to: 'lmstudio-ext',   kind: 'choke',    detail: '7 · HTTP POST' },
                { from: 'trig-extract',    to: 'graph-write',    kind: 'sync',     detail: '8 · graph_write(intents)' },
                { from: 'graph-write',     to: 'memory',         kind: 'sync',     detail: '9 · upsert' },
                { from: 'memory',          to: 'neo4j-ext',      kind: 'external', detail: '10 · Cypher' },
            ],
            notes: [
                "Only path that holds no lock at all. If a background drain is in flight, two extractions hit LM Studio in parallel.",
            ],
        },
        {
            id: 'process-all',
            label: 'Click Process All',
            category: 'Explorer',
            blurb: 'Drain entire queue; holds _drain_lock (single-flight against itself only).',
            steps: [
                { from: 'browser',         to: 'explorer-api',   kind: 'sync',     detail: '1 · POST /analyze/process-all' },
                { from: 'explorer-api',    to: 'exp-procall',    kind: 'sync',     detail: '2 · process_all_queue' },
                { from: 'exp-procall',     to: 'exp-drain-q',    kind: 'locked',   detail: '3 · acquire _drain_lock + loop' },
                { from: 'exp-drain-q',     to: 'trig-extract',   kind: 'async',    detail: '4 · run_extraction_pass' },
                { from: 'trig-extract',    to: 'extract-int',    kind: 'async',    detail: '5 · per window' },
                { from: 'extract-int',     to: 'lmstudio-client',kind: 'sync',     detail: '6 · chat_completion' },
                { from: 'lmstudio-client', to: 'lmstudio-ext',   kind: 'choke',    detail: '7 · HTTP POST' },
                { from: 'trig-extract',    to: 'graph-write',    kind: 'sync',     detail: '8 · graph_write' },
                { from: 'graph-write',     to: 'memory',         kind: 'sync',     detail: '9 · upsert' },
            ],
            notes: [
                "<code>_drain_lock</code> is single-flight only against another Process All click. Does NOT block drain-after-reset, run-analyzer, or chat-triggered <code>_run_once</code>.",
            ],
        },

        // ── Background ───────────────────────────────────────────────────────
        {
            id: 'bulk-import',
            label: 'Bulk import a file',
            category: 'Background',
            blurb: 'BulkImporter → memory.store per chunk → post-loop run_extraction_pass × 50.',
            steps: [
                { from: 'browser',         to: 'explorer-api',   kind: 'sync',     detail: '1 · POST /ingest/bulk' },
                { from: 'explorer-api',    to: 'exp-bulk',       kind: 'sync',     detail: '2 · run_bulk_import' },
                { from: 'exp-bulk',        to: 'bulk-importer',  kind: 'sync',     detail: '3 · BulkImporter(memory).import_directory' },
                { from: 'bulk-importer',   to: 'memory',         kind: 'sync',     detail: '4 · store(chunk) loop' },
                { from: 'memory',          to: 'chroma-ext',     kind: 'external', detail: '5 · Chroma writes' },
                { from: 'memory',          to: 'trig-maybe',     kind: 'forget',   detail: '6 · maybe_trigger × many' },
                { from: 'exp-bulk',        to: 'trig-extract',   kind: 'async',    detail: '7 · post-loop drain (50 cap)' },
                { from: 'trig-extract',    to: 'extract-int',    kind: 'async',    detail: '8 · per window' },
                { from: 'extract-int',     to: 'lmstudio-client',kind: 'sync',     detail: '9 · chat_completion' },
                { from: 'lmstudio-client', to: 'lmstudio-ext',   kind: 'choke',    detail: '10 · HTTP POST' },
            ],
            notes: [
                "Two waves of LM Studio traffic: lazy <code>maybe_trigger</code> per <code>store()</code>, then explicit post-loop drain.",
                "No dedup — re-importing doubles Chroma rows.",
                "If chat is active during import, chat-triggered <code>_run_once</code> runs in parallel with the post-loop drain.",
            ],
        },
        {
            id: 'rumination-tick',
            label: 'Rumination deep-pass tick',
            category: 'Background',
            blurb: 'Scheduled loop → DeepPass → AgentService → Gemini → optional ProactiveBot digest.',
            steps: [
                { from: 'rum-scheduler',   to: 'deep-pass',      kind: 'async',    detail: '1 · tick fires' },
                { from: 'deep-pass',       to: 'memory',         kind: 'sync',     detail: '2 · list_active_beliefs' },
                { from: 'deep-pass',       to: 'agent-svc',      kind: 'sync',     detail: '3 · arun(synth prompt)' },
                { from: 'agent-svc',       to: 'agent',          kind: 'sync',     detail: '4 · aprocess_message' },
                { from: 'agent',           to: 'gemini-ext',     kind: 'external', detail: '5 · Gemini call' },
                { from: 'deep-pass',       to: 'bot-proactive',  kind: 'sync',     detail: '6 · send_belief_digest' },
                { from: 'bot-proactive',   to: 'telegram-ext',   kind: 'external', detail: '7 · sendMessage' },
            ],
            notes: [
                "Touches Gemini, not LM Studio. Doesn't contend with extraction pipeline.",
                "Tick overruns don't overlap — single asyncio task awaiting itself.",
            ],
        },
        {
            id: 'bot-reconciliation',
            label: 'Bot reconciliation reply (CT8)',
            category: 'Background',
            blurb: 'Telegram reply → ProactiveBot → refinement_extraction → LM Studio.',
            steps: [
                { from: 'telegram',        to: 'bot-tg',         kind: 'sync',     detail: '1 · reply on reconciliation thread' },
                { from: 'bot-tg',          to: 'bot-proactive',  kind: 'sync',     detail: '2 · handle_refinement_reply' },
                { from: 'bot-proactive',   to: 'refinement',     kind: 'async',    detail: '3 · parse_reconciliation_reply' },
                { from: 'refinement',      to: 'lmstudio-client',kind: 'sync',     detail: '4 · chat_completion' },
                { from: 'lmstudio-client', to: 'lmstudio-ext',   kind: 'choke',    detail: '5 · HTTP POST' },
                { from: 'bot-proactive',   to: 'memory',         kind: 'sync',     detail: '6 · update belief' },
                { from: 'memory',          to: 'neo4j-ext',      kind: 'external', detail: '7 · Cypher' },
                { from: 'bot-proactive',   to: 'telegram-ext',   kind: 'external', detail: '8 · sendMessage confirm' },
            ],
            notes: [
                "Only bot-initiated LM Studio call. Bypasses any analyzer lock — runs in parallel with active drains.",
                "If LM Studio is busy, the bot reply hangs on httpx (60s timeout); no retry.",
            ],
        },
        {
            id: 'graph-ingest-external',
            label: 'External /graph/ingest',
            category: 'Background',
            blurb: 'External pipeline → shared secret check → run_extraction_pass → LM Studio.',
            steps: [
                { from: 'ext-pipeline',    to: 'graph-ingest',   kind: 'sync',     detail: '1 · POST + X-Ingest-Secret' },
                { from: 'graph-ingest',    to: 'trig-extract',   kind: 'async',    detail: '2 · run_extraction_pass (NO LOCK)' },
                { from: 'trig-extract',    to: 'extract-int',    kind: 'async',    detail: '3 · per window' },
                { from: 'extract-int',     to: 'lmstudio-client',kind: 'sync',     detail: '4 · chat_completion' },
                { from: 'lmstudio-client', to: 'lmstudio-ext',   kind: 'choke',    detail: '5 · HTTP POST' },
                { from: 'trig-extract',    to: 'graph-write',    kind: 'sync',     detail: '6 · graph_write' },
                { from: 'graph-write',     to: 'memory',         kind: 'sync',     detail: '7 · upsert' },
                { from: 'memory',          to: 'neo4j-ext',      kind: 'external', detail: '8 · Cypher' },
            ],
            notes: [
                "Same lock-free pattern as <code>POST /analyze/run</code>. External pipelines can stack LM Studio requests at will.",
                "Shared secret is the only auth.",
            ],
        },
    ];

    // ── DERIVED: union of all edges (the base call graph drawn faintly) ──────
    const ALL_EDGES = (() => {
        const seen = new Set();
        const out = [];
        SCENARIOS.forEach(s => {
            s.steps.forEach(st => {
                const key = `${st.from}→${st.to}`;
                if (seen.has(key)) return;
                seen.add(key);
                out.push({ from: st.from, to: st.to });
            });
        });
        return out;
    })();

    // ══════════════════════════════════════════════════════════════════════════
    // LAYOUT
    // ══════════════════════════════════════════════════════════════════════════

    const CANVAS_W   = 1400;
    const CANVAS_H   = 760;
    const PAD_TOP    = 50;
    const PAD_BOTTOM = 30;
    const PAD_LEFT   = 24;
    const PAD_RIGHT  = 24;
    const NODE_W     = 168;
    const NODE_H     = 38;
    const NODE_RX    = 5;
    const COL_X      = [0.06, 0.225, 0.42, 0.605, 0.79, 0.955];

    function computePositions() {
        const drawW = CANVAS_W - PAD_LEFT - PAD_RIGHT;
        const drawH = CANVAS_H - PAD_TOP - PAD_BOTTOM;
        const pos = {};
        NODES.forEach(n => {
            const ci = LAYERS[n.layer].col;
            pos[n.id] = {
                x: PAD_LEFT + COL_X[ci] * drawW,
                y: PAD_TOP  + n.y     * drawH,
            };
        });
        return pos;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // STATE
    // ══════════════════════════════════════════════════════════════════════════

    let _mounted    = false;
    let _svg        = null;
    let _g          = null;
    let _zoom       = null;
    let _positions  = null;
    let _activeId   = null;
    let _hoverNode  = null;
    let _typeTimers = {};   // per-element typewriter timers, so re-selection cancels prior
    let _focusNodeId = null; // when set, view is in node-focus mode instead of scenario mode

    // ══════════════════════════════════════════════════════════════════════════
    // EDGE GEOMETRY
    // ══════════════════════════════════════════════════════════════════════════

    const ARROW_LEN = 10;

    function trimEnd(sx, sy, tx, ty) {
        const dx = tx - sx, dy = ty - sy;
        const d = Math.hypot(dx, dy);
        if (d < 0.5) return { tx, ty };
        const ux = dx / d, uy = dy / d;
        return { tx: tx - ux * ARROW_LEN, ty: ty - uy * ARROW_LEN };
    }

    function edgePath(srcNode, tgtNode) {
        const sp = _positions[srcNode.id];
        const tp = _positions[tgtNode.id];
        const srcCol = LAYERS[srcNode.layer].col;
        const tgtCol = LAYERS[tgtNode.layer].col;

        // Default: sideways from right of src to left of tgt
        if (tgtCol > srcCol) {
            const sx = sp.x + NODE_W / 2 + 1;
            const sy = sp.y;
            const txO = tp.x - NODE_W / 2 - 1;
            const tyO = tp.y;
            const dx = txO - sx;
            const cp1x = sx + dx * 0.45;
            const cp2x = txO - dx * 0.45;
            const { tx, ty } = trimEnd(cp2x, tyO, txO, tyO);
            return `M ${sx} ${sy} C ${cp1x} ${sy}, ${cp2x} ${tyO}, ${tx} ${ty}`;
        }
        if (tgtCol === srcCol) {
            // Same column — arc to the right
            const sx = sp.x + NODE_W / 2 + 1;
            const sy = sp.y;
            const txO = tp.x + NODE_W / 2 + 1;
            const tyO = tp.y;
            const offset = 36;
            const { tx, ty } = trimEnd(txO + offset, tyO, txO, tyO);
            return `M ${sx} ${sy} C ${sx + offset} ${sy}, ${txO + offset} ${tyO}, ${tx} ${ty}`;
        }
        // Backward edge — drop below, loop back
        const sx = sp.x - NODE_W / 2 - 1;
        const sy = sp.y;
        const txO = tp.x + NODE_W / 2 + 1;
        const tyO = tp.y;
        const dx = txO - sx;
        const cp1x = sx + dx * 0.45;
        const cp2x = txO - dx * 0.45;
        const dropY = Math.max(sy, tyO) + 50;
        const { tx, ty } = trimEnd(cp2x, dropY, txO, tyO);
        return `M ${sx} ${sy} C ${cp1x} ${dropY}, ${cp2x} ${dropY}, ${tx} ${ty}`;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // RENDER
    // ══════════════════════════════════════════════════════════════════════════

    function _teardown() {
        const wrap = document.getElementById('flowsCanvas');
        if (wrap) wrap.innerHTML = '';
        _svg = null; _g = null; _zoom = null; _positions = null;
    }

    function _render() {
        const wrap = document.getElementById('flowsCanvas');
        if (!wrap || typeof d3 === 'undefined') return;

        _positions = computePositions();

        _svg = d3.select('#flowsCanvas')
            .append('svg')
            .attr('width', '100%')
            .attr('height', '100%')
            .attr('viewBox', `0 0 ${CANVAS_W} ${CANVAS_H}`)
            .attr('preserveAspectRatio', 'xMidYMid meet');

        // Arrow markers — one per kind
        const defs = _svg.append('defs');
        Object.entries(KINDS).forEach(([id, cfg]) => {
            defs.append('marker')
                .attr('id', `flows-arr-${id}`)
                .attr('viewBox', '0 -3 10 6')
                .attr('refX', 0).attr('refY', 0)
                .attr('markerUnits', 'userSpaceOnUse')
                .attr('markerWidth', 10).attr('markerHeight', 6)
                .attr('orient', 'auto')
                .append('path').attr('d', 'M0,-3 L10,0 L0,3 Z').attr('fill', cfg.color);
        });
        // Faint marker for base edges
        defs.append('marker')
            .attr('id', 'flows-arr-base')
            .attr('viewBox', '0 -3 10 6')
            .attr('refX', 0).attr('refY', 0)
            .attr('markerUnits', 'userSpaceOnUse')
            .attr('markerWidth', 10).attr('markerHeight', 6)
            .attr('orient', 'auto')
            .append('path').attr('d', 'M0,-3 L10,0 L0,3 Z').attr('fill', '#3a3833');

        _g = _svg.append('g').attr('class', 'flows-root');
        _zoom = d3.zoom()
            .scaleExtent([0.5, 3.0])
            .on('zoom', ev => _g.attr('transform', ev.transform));
        _svg.call(_zoom);

        // Column headers
        const drawW = CANVAS_W - PAD_LEFT - PAD_RIGHT;
        Object.values(LAYERS).forEach(cfg => {
            const x = PAD_LEFT + COL_X[cfg.col] * drawW;
            _g.append('line')
                .attr('x1', x).attr('y1', PAD_TOP - 18)
                .attr('x2', x).attr('y2', CANVAS_H - PAD_BOTTOM + 10)
                .attr('stroke', '#2c2a27').attr('stroke-width', 1).attr('stroke-dasharray', '3,8');
            _g.append('text')
                .attr('x', x).attr('y', PAD_TOP - 24)
                .attr('text-anchor', 'middle')
                .attr('font-size', 9).attr('font-family', 'Inter, sans-serif')
                .attr('letter-spacing', '0.10em').attr('fill', '#5a5650')
                .text(cfg.label.toUpperCase());
        });

        // ── BASE EDGES (faint grey, always visible) ───────────────────────────
        const baseEdgeG = _g.append('g').attr('class', 'flows-base-edges');
        ALL_EDGES.forEach(e => {
            const src = NODE_BY_ID[e.from], tgt = NODE_BY_ID[e.to];
            if (!src || !tgt) return;
            baseEdgeG.append('path')
                .attr('class', `flows-edge-base flows-e-${e.from}-${e.to}`)
                .attr('d', edgePath(src, tgt))
                .attr('fill', 'none')
                .attr('stroke', '#2e2c28')
                .attr('stroke-width', 1.2)
                .attr('marker-end', 'url(#flows-arr-base)');
        });

        // ── SCENARIO EDGES layer (populated on selection) ─────────────────────
        _g.append('g').attr('class', 'flows-scenario-edges');

        // ── NODES ────────────────────────────────────────────────────────────
        const nodeG = _g.append('g').attr('class', 'flows-nodes');
        NODES.forEach(n => {
            const p = _positions[n.id];
            const color = LAYERS[n.layer].color;
            const g = nodeG.append('g')
                .attr('class', `flows-node nd-${n.id}`)
                .attr('transform', `translate(${p.x - NODE_W / 2}, ${p.y - NODE_H / 2})`)
                .attr('cursor', 'pointer')
                .on('click',      (ev) => { ev.stopPropagation(); _focusOnNode(n.id); })
                .on('mouseenter', () => _onNodeHover(n.id, true))
                .on('mouseleave', () => _onNodeHover(n.id, false));

            g.append('rect').attr('class', 'flows-node-bg')
                .attr('width', NODE_W).attr('height', NODE_H).attr('rx', NODE_RX)
                .attr('fill', '#1e1d1a').attr('stroke', color)
                .attr('stroke-width', 1.4).attr('stroke-opacity', 0.70);

            g.append('rect').attr('class', 'flows-node-strip')
                .attr('x', 1).attr('y', 1).attr('width', NODE_W - 2).attr('height', 3)
                .attr('rx', NODE_RX - 1).attr('fill', color).attr('opacity', 0.75);

            g.append('text').attr('class', 'flows-node-label')
                .attr('x', NODE_W / 2).attr('y', n.sub ? 17 : NODE_H / 2 + 2)
                .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
                .attr('font-size', 10.5).attr('font-family', 'Inter, sans-serif')
                .attr('fill', '#DFDCD6').attr('pointer-events', 'none')
                .text(n.label);

            if (n.sub) {
                g.append('text').attr('class', 'flows-node-sub')
                    .attr('x', NODE_W / 2).attr('y', NODE_H - 9)
                    .attr('text-anchor', 'middle')
                    .attr('font-size', 8.5).attr('font-family', 'Inter, sans-serif')
                    .attr('fill', '#888479').attr('letter-spacing', '0.04em')
                    .attr('pointer-events', 'none')
                    .text(n.sub);
            }
        });

        // ── KIND LEGEND (top-right inside canvas) ─────────────────────────────
        const legendG = _svg.append('g').attr('class', 'flows-kind-legend');
        const kinds = Object.entries(KINDS);
        kinds.forEach(([id, cfg], i) => {
            const lx = CANVAS_W - PAD_RIGHT - 220;
            const ly = 16 + i * 14;
            legendG.append('line')
                .attr('x1', lx).attr('y1', ly).attr('x2', lx + 22).attr('y2', ly)
                .attr('stroke', cfg.color)
                .attr('stroke-width', cfg.width)
                .attr('stroke-dasharray', cfg.dash || null);
            legendG.append('text')
                .attr('x', lx + 28).attr('y', ly + 3)
                .attr('font-size', 9.5).attr('font-family', 'Inter, sans-serif')
                .attr('fill', '#a8a39a').text(cfg.label);
        });
    }

    // ══════════════════════════════════════════════════════════════════════════
    // SELECTION + HIGHLIGHTING
    // ══════════════════════════════════════════════════════════════════════════

    // Typewriter: replace an element's text one char at a time. Cancels any
    // pending timer for that element so rapid scenario switches don't stack.
    function _typewrite(el, text, opts) {
        if (!el) return;
        const key = el.id || el.dataset.tw || (el.dataset.tw = `tw-${Math.random().toString(36).slice(2, 8)}`);
        if (_typeTimers[key]) {
            clearInterval(_typeTimers[key]);
            _typeTimers[key] = null;
        }
        const charDelay  = (opts && opts.charDelay)  || 12;
        const initDelay  = (opts && opts.initDelay)  || 0;
        const target = String(text || '');
        el.textContent = '';
        // For HTML content (e.g. notes), opts.html=true bypasses the typewriter
        // and just fades in. Typewriter is for plain text.
        if (opts && opts.html) {
            el.innerHTML = target;
            return;
        }
        let i = 0;
        const start = () => {
            _typeTimers[key] = setInterval(() => {
                i += 1;
                el.textContent = target.slice(0, i);
                if (i >= target.length) {
                    clearInterval(_typeTimers[key]);
                    _typeTimers[key] = null;
                }
            }, charDelay);
        };
        if (initDelay > 0) {
            setTimeout(start, initDelay);
        } else {
            start();
        }
    }

    function _select(id) {
        const scenario = SCENARIOS.find(s => s.id === id);
        if (!scenario) return;
        const isSwitching = (_activeId && _activeId !== id) || _focusNodeId;
        _activeId = id;
        _focusNodeId = null;

        // Rail: scenario highlight, clear any node-focus "related" markers
        document.querySelectorAll('.flows-rail-item').forEach(el => {
            el.classList.toggle('is-active', el.dataset.id === id);
            el.classList.remove('is-related');
        });

        // Header — typewriter the three fields. Stagger so the eye flows
        // eyebrow → title → blurb. Title is the longest visible string, so
        // we use a slightly faster char-delay on the blurb to keep total
        // typing under ~600ms.
        const elCat   = document.getElementById('flowsCategory');
        const elTitle = document.getElementById('flowsTitle');
        const elBlurb = document.getElementById('flowsBlurb');
        _typewrite(elCat,   scenario.category, { charDelay: 18, initDelay: 0   });
        _typewrite(elTitle, scenario.label,    { charDelay: 16, initDelay: 80  });
        _typewrite(elBlurb, scenario.blurb,    { charDelay:  6, initDelay: 220 });

        // Notes — fade the panel out, swap content, fade back in
        const notesEl = document.getElementById('flowsNotes');
        const notesList = document.getElementById('flowsNotesList');
        if (notesEl && notesList) {
            const hasNotes = scenario.notes && scenario.notes.length > 0;
            if (!hasNotes) {
                notesEl.classList.add('is-fading');
                setTimeout(() => { notesEl.hidden = true; notesEl.classList.remove('is-fading'); }, 180);
            } else {
                const swap = () => {
                    notesList.innerHTML = '';
                    scenario.notes.forEach((html, idx) => {
                        const li = document.createElement('li');
                        li.innerHTML = html;
                        li.style.opacity = '0';
                        li.style.transition = 'opacity 220ms ease';
                        li.style.transitionDelay = `${idx * 40}ms`;
                        notesList.appendChild(li);
                        requestAnimationFrame(() => { li.style.opacity = '1'; });
                    });
                    notesEl.hidden = false;
                    requestAnimationFrame(() => notesEl.classList.remove('is-fading'));
                };
                if (isSwitching) {
                    notesEl.classList.add('is-fading');
                    setTimeout(swap, 160);
                } else {
                    notesEl.hidden = false;
                    swap();
                }
            }
        }

        _applyHighlight(scenario);
    }

    function _applyHighlight(scenario) {
        if (!_g) return;
        const activeNodes = new Set();
        scenario.steps.forEach(st => {
            activeNodes.add(st.from);
            activeNodes.add(st.to);
        });

        const DUR_NODE = 260;
        const DUR_OUT  = 180;
        const DUR_IN   = 260;
        const STAGGER  = 35;     // ms per step number — edges flow in sequentially

        // Smoothly transition every node toward its new active/inactive look.
        // Using d3's interpolators so the fade is continuous instead of a
        // hard attribute swap.
        NODES.forEach(n => {
            const isActive = activeNodes.has(n.id);
            d3.select(`.nd-${n.id} .flows-node-bg`).transition().duration(DUR_NODE)
                .attr('stroke-opacity', isActive ? 1.0 : 0.10)
                .attr('fill',           isActive ? '#2a2924' : '#1a1917');
            d3.select(`.nd-${n.id} .flows-node-strip`).transition().duration(DUR_NODE)
                .attr('opacity',        isActive ? 0.90 : 0.10);
            d3.select(`.nd-${n.id} .flows-node-label`).transition().duration(DUR_NODE)
                .attr('opacity',        isActive ? 1 : 0.18);
            d3.select(`.nd-${n.id} .flows-node-sub`).transition().duration(DUR_NODE)
                .attr('opacity',        isActive ? 0.85 : 0.12);
        });

        // Base edges fade to background level.
        d3.selectAll('.flows-edge-base').transition().duration(DUR_NODE)
            .attr('stroke-opacity', 0.18)
            .attr('stroke',         '#2e2c28');

        // Fade out the previously-drawn scenario edges, then remove them.
        const layer = _g.select('.flows-scenario-edges');
        layer.selectAll('.flows-scenario-edge, .flows-step-badge')
            .transition().duration(DUR_OUT)
                .attr('opacity', 0)
                .remove();

        // Draw the new scenario edges with a small stagger so the eye can
        // follow the sequence visually as it appears.
        scenario.steps.forEach((st, i) => {
            const src = NODE_BY_ID[st.from];
            const tgt = NODE_BY_ID[st.to];
            if (!src || !tgt) return;
            const cfg = KINDS[st.kind] || KINDS.sync;
            const pathD = edgePath(src, tgt);
            const delay = DUR_OUT + i * STAGGER;

            const path = layer.append('path')
                .attr('class', 'flows-scenario-edge')
                .attr('d', pathD)
                .attr('fill', 'none')
                .attr('stroke', cfg.color)
                .attr('stroke-width', cfg.width)
                .attr('stroke-linecap', 'round')
                .attr('stroke-dasharray', cfg.dash || null)
                .attr('marker-end', `url(#flows-arr-${st.kind})`)
                .attr('opacity', 0);

            path.transition().duration(DUR_IN).delay(delay)
                .attr('opacity', 1);

            // Step badge at midpoint — fade in slightly after the line.
            const node = path.node();
            if (node) {
                const len = node.getTotalLength();
                const mid = node.getPointAtLength(len * 0.5);
                const badgeR = 9;
                const badge = layer.append('g')
                    .attr('class', 'flows-step-badge')
                    .attr('opacity', 0);
                badge.append('rect')
                    .attr('x', mid.x - badgeR).attr('y', mid.y - badgeR)
                    .attr('width', badgeR * 2).attr('height', badgeR * 2)
                    .attr('fill', '#1a1917')
                    .attr('opacity', 0.85)
                    .attr('rx', badgeR);
                badge.append('circle')
                    .attr('cx', mid.x).attr('cy', mid.y).attr('r', badgeR)
                    .attr('fill', 'none').attr('stroke', cfg.color)
                    .attr('stroke-width', 1.4);
                badge.append('text')
                    .attr('x', mid.x).attr('y', mid.y + 3.5)
                    .attr('text-anchor', 'middle')
                    .attr('font-size', 10).attr('font-family', 'Inter, sans-serif')
                    .attr('font-weight', 600)
                    .attr('fill', cfg.color)
                    .text(i + 1);
                badge.append('title').text(st.detail || `${st.from} → ${st.to}`);
                badge.transition().duration(DUR_IN).delay(delay + 60)
                    .attr('opacity', 1);
            }
        });
    }

    function _onNodeHover(nodeId, on) {
        _hoverNode = on ? nodeId : null;
        // Optional: future enhancement — light up adjacent base edges
    }

    // ── NODE-FOCUS MODE ──────────────────────────────────────────────────────
    //
    // Click a node to pivot the view from "trace this scenario" to "what
    // touches this component". Highlights every edge across every scenario
    // that has this node as either source or target, dims everything else.
    // Re-clicking the focused node (or selecting a scenario from the rail)
    // exits focus mode.

    function _computeFocus(nodeId) {
        const adjacent = new Set([nodeId]);
        const seen = new Set();
        const edges = [];
        const scenarios = [];
        SCENARIOS.forEach(s => {
            let touches = false;
            s.steps.forEach(st => {
                if (st.from === nodeId || st.to === nodeId) {
                    touches = true;
                    adjacent.add(st.from);
                    adjacent.add(st.to);
                    const key = `${st.from}|${st.to}|${st.kind}`;
                    if (!seen.has(key)) {
                        seen.add(key);
                        edges.push({ from: st.from, to: st.to, kind: st.kind, scenario: s.id });
                    }
                }
            });
            if (touches) scenarios.push(s);
        });
        return { adjacent, edges, scenarios };
    }

    function _focusOnNode(nodeId) {
        const node = NODE_BY_ID[nodeId];
        if (!node) return;

        // Toggle: clicking the same node again returns to the last active scenario.
        if (_focusNodeId === nodeId) {
            const lastScenario = _activeId || SCENARIOS[0]?.id;
            if (lastScenario) _select(lastScenario);
            return;
        }

        const wasInScenario = !!_activeId && !_focusNodeId;
        _focusNodeId = nodeId;

        const { adjacent, edges, scenarios } = _computeFocus(nodeId);

        // Rail — clear scenario "active", mark scenarios that include this node.
        document.querySelectorAll('.flows-rail-item').forEach(el => {
            el.classList.remove('is-active');
            el.classList.toggle('is-related', scenarios.some(s => s.id === el.dataset.id));
        });

        // Header — typewriter the node's identity + how many scenarios use it.
        const elCat   = document.getElementById('flowsCategory');
        const elTitle = document.getElementById('flowsTitle');
        const elBlurb = document.getElementById('flowsBlurb');
        _typewrite(elCat,   `Component · ${LAYERS[node.layer].label}`, { charDelay: 18, initDelay: 0 });
        _typewrite(elTitle, node.label + (node.sub ? `  ·  ${node.sub}` : ''), { charDelay: 16, initDelay: 80 });
        const blurb = scenarios.length === 0
            ? `${node.label} is not yet referenced by any scenario.`
            : `Touched by ${scenarios.length} scenario${scenarios.length === 1 ? '' : 's'} (${edges.length} edge${edges.length === 1 ? '' : 's'}). Click a scenario in the left rail to drill into its step-by-step trace, or click another node to pivot.`;
        _typewrite(elBlurb, blurb, { charDelay: 6, initDelay: 220 });

        // Notes — list participating scenarios as clickable links.
        const notesEl = document.getElementById('flowsNotes');
        const notesList = document.getElementById('flowsNotesList');
        if (notesEl && notesList) {
            const swap = () => {
                notesList.innerHTML = '';
                if (scenarios.length === 0) {
                    notesEl.hidden = true;
                    notesEl.classList.remove('is-fading');
                    return;
                }
                scenarios.forEach((s, idx) => {
                    const li = document.createElement('li');
                    li.innerHTML = `<a class="flows-scenario-link" data-scenario="${s.id}">${s.label}</a> <span class="flows-scenario-link-sub">— ${(s.blurb || '').split('.')[0]}.</span>`;
                    li.style.opacity = '0';
                    li.style.transition = 'opacity 220ms ease';
                    li.style.transitionDelay = `${idx * 40}ms`;
                    notesList.appendChild(li);
                    requestAnimationFrame(() => { li.style.opacity = '1'; });
                });
                notesList.querySelectorAll('.flows-scenario-link').forEach(a => {
                    a.addEventListener('click', (ev) => {
                        ev.preventDefault();
                        _select(a.dataset.scenario);
                    });
                });
                notesEl.hidden = false;
                requestAnimationFrame(() => notesEl.classList.remove('is-fading'));
            };
            if (wasInScenario || true) {
                notesEl.classList.add('is-fading');
                setTimeout(swap, 160);
            } else {
                swap();
            }
        }

        _applyNodeHighlight(nodeId, adjacent, edges);
    }

    function _applyNodeHighlight(focusId, adjacentSet, edges) {
        if (!_g) return;
        const DUR_NODE = 260;
        const DUR_OUT  = 180;
        const DUR_IN   = 260;
        const STAGGER  = 22;

        NODES.forEach(n => {
            const isActive = adjacentSet.has(n.id);
            const isFocus  = n.id === focusId;
            d3.select(`.nd-${n.id} .flows-node-bg`).transition().duration(DUR_NODE)
                .attr('stroke-opacity', isActive ? 1.0 : 0.10)
                .attr('stroke-width',   isFocus  ? 2.6 : 1.4)
                .attr('fill',           isFocus  ? '#33312b' : (isActive ? '#2a2924' : '#1a1917'));
            d3.select(`.nd-${n.id} .flows-node-strip`).transition().duration(DUR_NODE)
                .attr('opacity', isActive ? 0.90 : 0.10);
            d3.select(`.nd-${n.id} .flows-node-label`).transition().duration(DUR_NODE)
                .attr('opacity', isActive ? 1 : 0.18);
            d3.select(`.nd-${n.id} .flows-node-sub`).transition().duration(DUR_NODE)
                .attr('opacity', isActive ? 0.85 : 0.12);
        });

        d3.selectAll('.flows-edge-base').transition().duration(DUR_NODE)
            .attr('stroke-opacity', 0.10);

        const layer = _g.select('.flows-scenario-edges');
        layer.selectAll('.flows-scenario-edge, .flows-step-badge')
            .transition().duration(DUR_OUT)
                .attr('opacity', 0)
                .remove();

        edges.forEach((e, i) => {
            const src = NODE_BY_ID[e.from];
            const tgt = NODE_BY_ID[e.to];
            if (!src || !tgt) return;
            const cfg = KINDS[e.kind] || KINDS.sync;
            const pathD = edgePath(src, tgt);
            const delay = DUR_OUT + i * STAGGER;
            const path = layer.append('path')
                .attr('class', 'flows-scenario-edge')
                .attr('d', pathD)
                .attr('fill', 'none')
                .attr('stroke', cfg.color)
                .attr('stroke-width', cfg.width)
                .attr('stroke-linecap', 'round')
                .attr('stroke-dasharray', cfg.dash || null)
                .attr('marker-end', `url(#flows-arr-${e.kind})`)
                .attr('opacity', 0);
            path.transition().duration(DUR_IN).delay(delay)
                .attr('opacity', 1);
            path.append('title').text(`${e.from} → ${e.to}  (${e.kind})  · used in ${e.scenario}`);
        });
    }

    // ══════════════════════════════════════════════════════════════════════════
    // RAIL
    // ══════════════════════════════════════════════════════════════════════════

    function _buildRail() {
        const list = document.getElementById('flowsList');
        if (!list) return;
        list.innerHTML = '';
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
                li.innerHTML = `${s.label}<span class="flows-rail-item-sub">${(s.blurb || '').split('.')[0]}.</span>`;
                li.addEventListener('click', () => _select(s.id));
                list.appendChild(li);
            });
        });
    }

    // ══════════════════════════════════════════════════════════════════════════
    // PAGE MODULE
    // ══════════════════════════════════════════════════════════════════════════

    function mount(_root, shell) {
        if (_mounted) return;
        _mounted = true;
        _buildRail();
        shell?.setSearchPlaceholder('Filter scenarios...');
        requestAnimationFrame(() => {
            _render();
            if (SCENARIOS.length > 0) _select(_activeId || SCENARIOS[0].id);
        });
    }

    function unmount() {
        _mounted = false;
        _activeId = null;
        _teardown();
    }

    function onSearch(query) {
        const q = (query || '').trim().toLowerCase();
        document.querySelectorAll('.flows-rail-item').forEach(el => {
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
