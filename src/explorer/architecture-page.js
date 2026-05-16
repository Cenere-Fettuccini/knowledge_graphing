(function () {
    'use strict';

    // ══════════════════════════════════════════════════════════════════════════
    // DATA — component coupling map derived from CLAUDE.md files
    // ══════════════════════════════════════════════════════════════════════════

    // col = column index used by both layouts:
    //   LTR (desktop): col maps to a left→right column position (COL_X)
    //   TTB (mobile):  col maps to a top→bottom row position   (ROW_Y)
    // Layers without a col are "band" layers — rendered as full-width
    // bars at the top or bottom of the canvas (see node.band).
    const LAYER_CONFIG = {
        entry:      { label: 'Entry Points',   color: '#70695f', col: 0 },
        platform:   { label: 'Boot',           color: '#7E91BE', col: 1 },
        bot:        { label: 'Boot',           color: '#8F859A', col: 1 },
        app:        { label: 'App Layer',      color: '#7FA38D', col: 2 },
        background: { label: 'Background',     color: '#C49B76', col: 2 },
        gateway:    { label: 'Public Gateway', color: '#BEAA7E', col: 3 },
        infra:      { label: 'Infrastructure', color: '#A37A87', col: 4 },
        core:       { label: 'Core',           color: '#7E91BE', col: 5 },
        storage:    { label: 'Storage',        color: '#6B8F7A' },
    };

    // yFrac: vertical position within the LTR column  (fraction of drawable height)
    // xFrac: horizontal position within the TTB row   (fraction of drawable width)
    const NODES = [
        {
            id: 'main', label: 'main.py', layer: 'entry',
            yFrac: 0.32, xFrac: 0.30,
            desc: 'FastAPI server entry point. Calls create_platform_app() and runs uvicorn.',
            note: null, claudeMd: null,
            calledBy: [], callsInto: ['platform'],
        },
        {
            id: 'run_bot', label: 'run_bot.py', layer: 'entry',
            yFrac: 0.68, xFrac: 0.70,
            desc: 'Telegram bot entry point. Runs independently of the web server.',
            note: null, claudeMd: null,
            calledBy: [], callsInto: ['bot'],
        },
        {
            id: 'platform', label: 'platform/', layer: 'platform',
            yFrac: 0.32, xFrac: 0.30,
            desc: 'FastAPI app factory (create_platform_app), app registry, shell router, graph-ingest endpoint.',
            note: 'The only place that imports all five app get_*_app() factories. Starts/stops RuminationScheduler in lifespan.',
            claudeMd: 'src/platform/CLAUDE.md',
            calledBy: ['main'],
            callsInto: ['app_chat', 'app_explorer', 'app_credits', 'app_financial', 'app_routine', 'memory_read', 'rumination', 'core'],
        },
        {
            id: 'bot', label: 'bot/', layer: 'bot',
            yFrac: 0.68, xFrac: 0.70,
            desc: 'TelegramBot (handlers, session tracking) + ProactiveBot (outbound digests, reconciliation).',
            note: 'TelegramBot calls src.core.agent.Agent directly — pre-dates AgentService. Migrate to AgentService if refactoring.',
            claudeMd: 'src/bot/CLAUDE.md',
            calledBy: ['run_bot', 'rumination'],
            callsInto: ['core', 'memory_write', 'public_gateway'],
        },
        {
            id: 'app_chat', label: 'apps/chat', layer: 'app',
            yFrac: 0.09, xFrac: 0.08,
            desc: 'Browser conversation sessions. Session CRUD and message dispatch through the agent platform.',
            note: null, claudeMd: 'src/apps/chat/CLAUDE.md',
            calledBy: ['platform'], callsInto: ['public_gateway', 'memory_read'],
        },
        {
            id: 'app_explorer', label: 'apps/explorer', layer: 'app',
            yFrac: 0.25, xFrac: 0.24,
            desc: 'Knowledge graph UI, system status, analyzer controls, canonicalization, eras, pending beliefs.',
            note: 'Only app that imports analyzers directly — it is the admin surface for the extraction pipeline.',
            claudeMd: 'src/apps/explorer/CLAUDE.md',
            calledBy: ['platform'], callsInto: ['public_gateway', 'memory_read', 'analyzers', 'ingestion'],
        },
        {
            id: 'app_credits', label: 'apps/credits', layer: 'app',
            yFrac: 0.41, xFrac: 0.40,
            desc: 'LLM quota management console. Shows per-model headroom, imports rate limits.',
            note: 'Exception to the no-core-import rule — intentionally reads llm_router internals. Other apps use aquota_status() instead.',
            claudeMd: 'src/apps/credits/CLAUDE.md',
            calledBy: ['platform'], callsInto: ['core'],
        },
        {
            id: 'app_financial', label: 'apps/financial', layer: 'app',
            yFrac: 0.57, xFrac: 0.57,
            desc: 'Finance workflows — stub. AppDefinition only, no services or API yet.',
            note: null, claudeMd: 'src/apps/financial_manager/CLAUDE.md',
            calledBy: ['platform'], callsInto: [],
        },
        {
            id: 'app_routine', label: 'apps/routine', layer: 'app',
            yFrac: 0.71, xFrac: 0.73,
            desc: 'Scheduling automation — stub. AppDefinition only, no services or API yet.',
            note: null, claudeMd: 'src/apps/routine_scheduler/CLAUDE.md',
            calledBy: ['platform'], callsInto: [],
        },
        {
            id: 'rumination', label: 'rumination/', layer: 'background',
            yFrac: 0.87, xFrac: 0.90,
            desc: 'Background scheduler started in FastAPI lifespan. Deep-pass belief synthesis and rabbit-hole ticks.',
            note: 'Disabled by settings.rumination_enabled=False. Manages ProactiveBot lifecycle inside the web server process.',
            claudeMd: 'src/rumination/CLAUDE.md',
            calledBy: ['platform'], callsInto: ['memory_write', 'public_gateway', 'bot'],
        },
        {
            id: 'public_gateway', label: 'agent_platform/public', layer: 'gateway',
            yFrac: 0.35, xFrac: 0.50,
            desc: 'AgentService + contracts (AgentRunRequest, AgentRunResult). The only app-facing entry point for the agent.',
            note: 'Wraps src.core.agent.Agent behind a stable interface. Apps must never import Agent directly.',
            claudeMd: 'src/agent_platform/public/CLAUDE.md',
            calledBy: ['app_chat', 'app_explorer', 'bot', 'rumination'],
            callsInto: ['core', 'memory_read'],
        },
        {
            id: 'tools', label: 'agent_platform/tools', layer: 'infra',
            yFrac: 0.24, xFrac: 0.22,
            desc: 'LLM-callable tools registered via registry.py: graph_write, search_memories, tasks, beliefs, web_search, calendar.',
            note: 'Loaded by src.core.agent at init. Invoked by the LLM during a turn — not called directly by app code.',
            claudeMd: 'src/agent_platform/tools/CLAUDE.md',
            calledBy: ['core'], callsInto: ['memory_read', 'memory_write'],
        },
        {
            id: 'analyzers', label: 'agent_platform/analyzers', layer: 'infra',
            yFrac: 0.50, xFrac: 0.50,
            desc: 'Extraction pipeline: local-LLM (Gemma 4) for entities/tasks, Gemini cloud pass for beliefs, canonicalization.',
            note: 'Auto-triggered from MemoryManager.store() when unanalyzed queue depth ≥ settings.graph_ingest_threshold.',
            claudeMd: 'src/agent_platform/analyzers/CLAUDE.md',
            calledBy: ['app_explorer', 'memory_write', 'bot'],
            callsInto: ['memory_write', 'core'],
        },
        {
            id: 'ingestion', label: 'ingestion/', layer: 'infra',
            yFrac: 0.76, xFrac: 0.78,
            desc: 'Bulk import pipeline: JSONL, plaintext, Telegram export formats → Chroma queue.',
            note: 'Calls memory.store() only (Chroma). After import, app_explorer calls run_extraction_pass() to populate Neo4j.',
            claudeMd: 'src/ingestion/CLAUDE.md',
            calledBy: ['app_explorer'], callsInto: ['memory_write'],
        },
        {
            id: 'core', label: 'src/core', layer: 'core',
            yFrac: 0.50, xFrac: 0.50,
            desc: 'Agent, LLM router, rate limiter, config (settings), prompts — internal infrastructure.',
            note: 'Apps must not import from here directly (except settings). Only credits app uses llm_router intentionally.',
            claudeMd: 'src/core/CLAUDE.md',
            calledBy: ['public_gateway', 'tools', 'analyzers', 'bot', 'platform', 'app_credits', 'rumination'],
            callsInto: ['memory_read', 'tools'],
        },
        {
            id: 'memory_read', label: 'memory · read', layer: 'storage',
            band: 'top',
            desc: 'MemoryManager (read facade): graph queries, conversation history, status, schema introspection. Methods: status(), graph_*(), search_memories(), list_*(), count_*(), eras_active_at(), graph_schema_snapshot().',
            note: 'Same MemoryManager singleton as the write node — split visually to clarify data direction. Obtained via get_memory_manager().',
            claudeMd: 'src/memory/CLAUDE.md',
            calledBy: ['app_chat', 'app_explorer', 'public_gateway', 'core', 'platform', 'tools'],
            callsInto: [],
        },
        {
            id: 'memory_write', label: 'memory · write', layer: 'storage',
            band: 'bottom',
            desc: 'MemoryManager (write facade): store() messages, bootstrap_user_root(), mark_analyzed/failed, era + belief CRUD, merge proposals, graph_write tool output, bulk ingest.',
            note: 'After store() calls, maybe_trigger() fires the analyzer if the unanalyzed queue is full — that is the outbound edge to analyzers.',
            claudeMd: 'src/memory/CLAUDE.md',
            calledBy: ['tools', 'analyzers', 'rumination', 'bot', 'ingestion'],
            callsInto: ['analyzers'],
        },
    ];

    // ── Derived edges ──────────────────────────────────────────────────────────

    const EDGES = [];
    const _edgeSet = new Set();
    NODES.forEach(node => {
        node.callsInto.forEach(targetId => {
            const key = `${node.id}→${targetId}`;
            if (!_edgeSet.has(key)) {
                _edgeSet.add(key);
                EDGES.push({ source: node.id, target: targetId });
            }
        });
    });

    const NODE_BY_ID = {};
    NODES.forEach(n => { NODE_BY_ID[n.id] = n; });

    // ══════════════════════════════════════════════════════════════════════════
    // LAYOUT CONSTANTS
    // ══════════════════════════════════════════════════════════════════════════

    const NODE_W  = 116;
    const NODE_H  = 32;
    const NODE_RX = 5;

    // Desktop — six middle columns flow left → right (storage is band-only)
    const CANVAS_W_LTR = 1120;
    const CANVAS_H_LTR = 620;
    const COL_X = [0.06, 0.22, 0.40, 0.58, 0.76, 0.94];

    // Mobile — six middle rows flow top → bottom (storage is band-only)
    const CANVAS_W_TTB = 900;
    const CANVAS_H_TTB = 920;
    const ROW_Y = [0.06, 0.22, 0.38, 0.55, 0.72, 0.92];

    const PAD_TOP    = 26;
    const PAD_BOTTOM = 22;
    const PAD_LEFT   = 18;
    const PAD_RIGHT  = 18;

    // Reserved top + bottom zones for the memory · read / memory · write bands
    const BAND_H            = 56;
    const COL_LABEL_GUTTER  = 18;  // LTR only — space for column header labels

    // Switch to TTB when the canvas container is narrower than this
    const MOBILE_BREAKPOINT = 640;

    // Middle (non-band) drawing zone — bracketed by the two memory bands
    function middleZone(canvasH, isLTR) {
        const labelGutter = isLTR ? COL_LABEL_GUTTER : 0;
        const drawTop = PAD_TOP    + BAND_H + labelGutter;
        const drawBot = canvasH    - PAD_BOTTOM - BAND_H;
        return { drawTop, drawBot, drawH: drawBot - drawTop };
    }

    // ══════════════════════════════════════════════════════════════════════════
    // POSITIONS
    // ══════════════════════════════════════════════════════════════════════════

    function computePositions(isLTR) {
        const canvasW = isLTR ? CANVAS_W_LTR : CANVAS_W_TTB;
        const canvasH = isLTR ? CANVAS_H_LTR : CANVAS_H_TTB;
        const drawW   = canvasW - PAD_LEFT - PAD_RIGHT;
        const { drawTop, drawH } = middleZone(canvasH, isLTR);

        const topBandY = PAD_TOP + BAND_H / 2;
        const botBandY = canvasH - PAD_BOTTOM - BAND_H / 2;

        const pos = {};
        NODES.forEach(node => {
            if (node.band === 'top') {
                pos[node.id] = { x: canvasW / 2, y: topBandY };
                return;
            }
            if (node.band === 'bottom') {
                pos[node.id] = { x: canvasW / 2, y: botBandY };
                return;
            }
            const ci = LAYER_CONFIG[node.layer].col;
            if (isLTR) {
                pos[node.id] = {
                    x: PAD_LEFT + COL_X[ci] * drawW,
                    y: drawTop  + node.yFrac * drawH,
                };
            } else {
                pos[node.id] = {
                    x: PAD_LEFT + node.xFrac * drawW,
                    y: drawTop  + ROW_Y[ci]  * drawH,
                };
            }
        });
        return pos;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // EDGE PATHS
    // ══════════════════════════════════════════════════════════════════════════

    function edgePath(sp, tp, isLTR) {
        if (isLTR) {
            // Right edge of source → left edge of target
            const sx = sp.x + NODE_W / 2 + 1;
            const sy = sp.y;
            const tx = tp.x - NODE_W / 2 - 1;
            const ty = tp.y;
            const dx = tx - sx;
            if (dx > 8) {
                const cp1x = sx + dx * 0.42;
                const cp2x = tx - dx * 0.42;
                return `M ${sx} ${sy} C ${cp1x} ${sy}, ${cp2x} ${ty}, ${tx} ${ty}`;
            }
            // Backward / same-column: arc above or below
            const arcDir = sy < tp.y ? -1 : 1;
            const offset = 55 + Math.abs(dx) * 0.25;
            return `M ${sx} ${sy} C ${sx + 30} ${sy + arcDir * offset}, ${tx - 30} ${ty + arcDir * offset}, ${tx} ${ty}`;
        } else {
            // Bottom edge of source → top edge of target
            const sx = sp.x;
            const sy = sp.y + NODE_H / 2 + 1;
            const tx = tp.x;
            const ty = tp.y - NODE_H / 2 - 1;
            const dy = ty - sy;
            if (dy > 8) {
                const cp1y = sy + dy * 0.42;
                const cp2y = ty - dy * 0.42;
                return `M ${sx} ${sy} C ${sx} ${cp1y}, ${tx} ${cp2y}, ${tx} ${ty}`;
            }
            // Backward / same-row: arc left or right
            const arcDir = sx < tp.x ? -1 : 1;
            const offset = 55 + Math.abs(dy) * 0.25;
            return `M ${sx} ${sy} C ${sx + arcDir * offset} ${sy + 30}, ${tx + arcDir * offset} ${ty - 30}, ${tx} ${ty}`;
        }
    }

    // ══════════════════════════════════════════════════════════════════════════
    // STATE
    // ══════════════════════════════════════════════════════════════════════════

    let _positions      = null;
    let _selectedId     = null;
    let _svg            = null;
    let _g              = null;
    let _zoom           = null;
    let _mounted        = false;
    let _tooltip        = null;
    let _isLTR          = true;
    let _resizeObserver = null;
    let _toolbarWired   = false;

    // ══════════════════════════════════════════════════════════════════════════
    // RENDER / TEARDOWN / FIT
    // ══════════════════════════════════════════════════════════════════════════

    function teardown(canvasId) {
        const wrap = document.getElementById(canvasId);
        if (wrap) wrap.innerHTML = '';
        _svg = null; _g = null; _zoom = null; _positions = null; _selectedId = null;
        clearDetail();
    }

    function resetZoom(animated) {
        // The SVG viewBox + preserveAspectRatio="xMidYMid meet" already auto-fits
        // the canvas to the container. The zoom transform sits on top in viewBox
        // coordinates — reset = identity.
        if (!_svg || !_zoom) return;
        const target = animated ? _svg.transition().duration(320) : _svg;
        target.call(_zoom.transform, d3.zoomIdentity);
    }

    function render(canvasId) {
        const wrap = document.getElementById(canvasId);
        if (!wrap) return;

        const isLTR   = _isLTR;
        const canvasW = isLTR ? CANVAS_W_LTR : CANVAS_W_TTB;
        const canvasH = isLTR ? CANVAS_H_LTR : CANVAS_H_TTB;

        _positions = computePositions(isLTR);

        _svg = d3.select(`#${canvasId}`)
            .append('svg')
            .attr('width', '100%')
            .attr('height', '100%')
            .attr('viewBox', `0 0 ${canvasW} ${canvasH}`)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .on('click', () => deselect());

        // ── Arrow markers ─────────────────────────────────────────────────────
        const defs = _svg.append('defs');
        Object.entries(LAYER_CONFIG).forEach(([layerId, cfg]) => {
            defs.append('marker')
                .attr('id', `arr-${layerId}`)
                .attr('viewBox', '0 -4 8 8')
                .attr('refX', 7).attr('refY', 0)
                .attr('markerWidth', 5).attr('markerHeight', 5)
                .attr('orient', 'auto')
                .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', cfg.color);
        });
        defs.append('marker')
            .attr('id', 'arr-dim')
            .attr('viewBox', '0 -4 8 8')
            .attr('refX', 7).attr('refY', 0)
            .attr('markerWidth', 5).attr('markerHeight', 5)
            .attr('orient', 'auto')
            .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', '#3a3835');

        // ── Zoom group ────────────────────────────────────────────────────────
        _g = _svg.append('g').attr('class', 'arch-root');
        _zoom = d3.zoom()
            .scaleExtent([0.25, 4.0])
            .on('zoom', (ev) => { _g.attr('transform', ev.transform); });
        _svg.call(_zoom);

        // ── Band lines + header labels ─────────────────────────────────────────
        const drawW = canvasW - PAD_LEFT - PAD_RIGHT;
        const { drawTop, drawBot, drawH } = middleZone(canvasH, isLTR);

        // Per-layer band lines + labels — skip layers without a `col` (storage)
        const bandMeta = {};
        Object.values(LAYER_CONFIG).forEach(cfg => {
            if (cfg.col == null) return;
            if (!bandMeta[cfg.col]) bandMeta[cfg.col] = new Set();
            bandMeta[cfg.col].add(cfg.label);
        });

        Object.entries(bandMeta).forEach(([ci, labelSet]) => {
            const label = [...labelSet].join(' / ');
            const idx   = parseInt(ci, 10);

            if (isLTR) {
                const x = PAD_LEFT + COL_X[idx] * drawW;
                _g.append('line')
                    .attr('x1', x).attr('y1', drawTop - 6)
                    .attr('x2', x).attr('y2', drawBot + 6)
                    .attr('stroke', '#2c2a27').attr('stroke-width', 1).attr('stroke-dasharray', '3,8');
                _g.append('text')
                    .attr('x', x).attr('y', drawTop - 10)
                    .attr('text-anchor', 'middle').attr('font-size', '9')
                    .attr('font-family', 'Inter, sans-serif').attr('fill', '#5a5650')
                    .attr('letter-spacing', '0.06em').text(label.toUpperCase());
            } else {
                const y = drawTop + ROW_Y[idx] * drawH;
                _g.append('line')
                    .attr('x1', PAD_LEFT).attr('y1', y)
                    .attr('x2', canvasW - PAD_RIGHT).attr('y2', y)
                    .attr('stroke', '#2c2a27').attr('stroke-width', 1).attr('stroke-dasharray', '3,8');
                _g.append('text')
                    .attr('x', PAD_LEFT + 4).attr('y', y - 6)
                    .attr('text-anchor', 'start').attr('font-size', '9')
                    .attr('font-family', 'Inter, sans-serif').attr('fill', '#5a5650')
                    .attr('letter-spacing', '0.06em').text(label.toUpperCase());
            }
        });

        // ── Edges ─────────────────────────────────────────────────────────────
        // Band geometry — the bars span the canvas width
        const BAR_H        = 34;
        const topBarBotY   = (PAD_TOP + BAND_H / 2) + BAR_H / 2;
        const botBarTopY   = (canvasH - PAD_BOTTOM - BAND_H / 2) - BAR_H / 2;

        const edgeG = _g.append('g').attr('class', 'edge-layer');
        EDGES.forEach(edge => {
            const sp      = _positions[edge.source];
            const tp      = _positions[edge.target];
            if (!sp || !tp) return;
            const srcNode = NODE_BY_ID[edge.source];
            const tgtNode = NODE_BY_ID[edge.target];

            let pathD;
            let strokeLayer;

            if (tgtNode.band === 'top') {
                // Visually inverted: arrow comes DOWN from the top band to the
                // consumer (data-flow direction). Vertical line at consumer's x.
                const x      = sp.x;
                const yStart = topBarBotY + 1;
                const yEnd   = sp.y - NODE_H / 2 - 1;
                if (yEnd <= yStart) return;
                pathD       = `M ${x} ${yStart} L ${x} ${yEnd}`;
                strokeLayer = tgtNode.layer;          // storage colour
            } else if (tgtNode.band === 'bottom') {
                // Arrow points DOWN from producer to the bottom band.
                const x      = sp.x;
                const yStart = sp.y + NODE_H / 2 + 1;
                const yEnd   = botBarTopY - 1;
                if (yEnd <= yStart) return;
                pathD       = `M ${x} ${yStart} L ${x} ${yEnd}`;
                strokeLayer = srcNode.layer;
            } else if (srcNode.band) {
                // Source is a band — this only happens for the lazy
                // memory_write → analyzers trigger. Skip the visible edge to
                // avoid a clutter-inducing upward arrow; the relationship still
                // shows in the detail panel.
                return;
            } else {
                pathD       = edgePath(sp, tp, isLTR);
                strokeLayer = srcNode.layer;
            }

            const color = LAYER_CONFIG[strokeLayer].color;
            edgeG.append('path')
                .attr('class', `edge e-src-${edge.source} e-tgt-${edge.target}`)
                .attr('d', pathD)
                .attr('fill', 'none')
                .attr('stroke', color)
                .attr('stroke-width', 1.4)
                .attr('stroke-opacity', 0.32)
                .attr('marker-end', `url(#arr-${strokeLayer})`);
        });

        // ── Nodes ─────────────────────────────────────────────────────────────
        const nodeG = _g.append('g').attr('class', 'node-layer');
        NODES.forEach(node => {
            const p     = _positions[node.id];
            const color = LAYER_CONFIG[node.layer].color;

            // ── Band node: full-width horizontal bar ──────────────────────────
            if (node.band) {
                const barW = canvasW - PAD_LEFT - PAD_RIGHT;
                const barX = PAD_LEFT;
                const barY = p.y - BAR_H / 2;

                const g = nodeG.append('g')
                    .attr('class', `node nd-${node.id}`)
                    .attr('cursor', 'pointer')
                    .on('click',      (ev) => { ev.stopPropagation(); select(node.id); })
                    .on('mouseenter', (ev) => { hovering(node.id, true); showTooltip(ev, node.desc); })
                    .on('mousemove',  (ev) => moveTooltip(ev))
                    .on('mouseleave', ()   => { hovering(node.id, false); hideTooltip(); });

                g.append('rect').attr('class', 'nd-bg')
                    .attr('x', barX).attr('y', barY)
                    .attr('width', barW).attr('height', BAR_H).attr('rx', NODE_RX)
                    .attr('fill', '#21201d').attr('stroke', color)
                    .attr('stroke-width', 1.4).attr('stroke-opacity', 0.7);

                // Color strip on the edge that "faces" the middle zone — the
                // bottom of the top bar, the top of the bottom bar.
                const stripY = (node.band === 'top') ? barY + BAR_H - 4 : barY + 1;
                g.append('rect').attr('class', 'nd-strip')
                    .attr('x', barX + 1).attr('y', stripY)
                    .attr('width', barW - 2).attr('height', 3)
                    .attr('rx', NODE_RX - 1).attr('fill', color).attr('opacity', 0.80);

                g.append('text').attr('class', 'nd-label')
                    .attr('x', barX + barW / 2).attr('y', p.y + 2)
                    .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
                    .attr('font-size', '11').attr('font-family', 'Inter, sans-serif')
                    .attr('fill', '#DFDCD6').attr('letter-spacing', '0.04em')
                    .attr('pointer-events', 'none')
                    .text(node.label);
                return;
            }

            // ── Regular node ──────────────────────────────────────────────────
            const g = nodeG.append('g')
                .attr('class', `node nd-${node.id}`)
                .attr('transform', `translate(${p.x - NODE_W / 2}, ${p.y - NODE_H / 2})`)
                .attr('cursor', 'pointer')
                .on('click',      (ev) => { ev.stopPropagation(); select(node.id); })
                .on('mouseenter', (ev) => { hovering(node.id, true); showTooltip(ev, node.desc); })
                .on('mousemove',  (ev) => moveTooltip(ev))
                .on('mouseleave', ()   => { hovering(node.id, false); hideTooltip(); });

            g.append('rect').attr('class', 'nd-bg')
                .attr('width', NODE_W).attr('height', NODE_H).attr('rx', NODE_RX)
                .attr('fill', '#21201d').attr('stroke', color)
                .attr('stroke-width', 1.4).attr('stroke-opacity', 0.65);

            if (isLTR) {
                g.append('rect').attr('class', 'nd-strip')
                    .attr('x', 1).attr('y', 1)
                    .attr('width', NODE_W - 2).attr('height', 3)
                    .attr('rx', NODE_RX - 1).attr('fill', color).attr('opacity', 0.70);
            } else {
                g.append('rect').attr('class', 'nd-strip')
                    .attr('x', 1).attr('y', 1)
                    .attr('width', 3).attr('height', NODE_H - 2)
                    .attr('rx', NODE_RX - 1).attr('fill', color).attr('opacity', 0.70);
            }

            g.append('text').attr('class', 'nd-label')
                .attr('x', NODE_W / 2).attr('y', NODE_H / 2 + 2)
                .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
                .attr('font-size', '10').attr('font-family', 'Inter, sans-serif')
                .attr('fill', '#DFDCD6').attr('pointer-events', 'none')
                .text(node.label);
        });
    }

    // ══════════════════════════════════════════════════════════════════════════
    // RESPONSIVE — re-render on orientation switch, fit on resize
    // ══════════════════════════════════════════════════════════════════════════

    function setupResponsive(canvasId) {
        if (typeof ResizeObserver === 'undefined') return;
        const wrap = document.getElementById(canvasId);
        if (!wrap) return;

        let lastLTR = _isLTR;

        _resizeObserver = new ResizeObserver((entries) => {
            if (!_mounted) return;
            const rect = entries[0].contentRect;
            const w    = rect.width;
            if (w === 0) return;

            const nowLTR = w >= MOBILE_BREAKPOINT;
            if (nowLTR !== lastLTR) {
                lastLTR = nowLTR;
                _isLTR  = nowLTR;
                teardown(canvasId);
                render(canvasId);
            }
            // No manual fit needed — viewBox + preserveAspectRatio="meet" auto-fits.
        });
        _resizeObserver.observe(wrap);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // INTERACTIONS
    // ══════════════════════════════════════════════════════════════════════════

    function connectedIds(nodeId) {
        const ids = new Set([nodeId]);
        EDGES.forEach(e => {
            if (e.source === nodeId) ids.add(e.target);
            if (e.target === nodeId) ids.add(e.source);
        });
        return ids;
    }

    function hovering(nodeId, on) {
        if (_selectedId) return;
        if (!on) { resetVisuals(); return; }
        applyDimming(nodeId, connectedIds(nodeId));
    }

    function select(nodeId) {
        _selectedId = nodeId;
        applyDimming(nodeId, connectedIds(nodeId));
        renderDetail(nodeId);
    }

    function deselect() {
        _selectedId = null;
        resetVisuals();
        clearDetail();
    }

    function applyDimming(selectedId, connected) {
        NODES.forEach(n => {
            const isSel  = n.id === selectedId;
            const isConn = connected.has(n.id);
            d3.select(`.nd-${n.id} .nd-bg`)
                .attr('stroke-width',   isSel ? 2.4 : 1.4)
                .attr('stroke-opacity', isConn ? 1.0 : 0.15)
                .attr('fill',           isSel ? '#2a2927' : '#21201d');
            d3.select(`.nd-${n.id} .nd-label`).attr('opacity', isConn ? 1 : 0.2);
            d3.select(`.nd-${n.id} .nd-strip`).attr('opacity', isConn ? 0.80 : 0.15);
        });
        d3.selectAll('.edge').each(function () {
            const el   = d3.select(this);
            const cls  = this.getAttribute('class') || '';
            const src  = (cls.match(/e-src-([^\s]+)/) || [])[1] || '';
            const tgt  = (cls.match(/e-tgt-([^\s]+)/) || [])[1] || '';
            const active   = (src === selectedId || tgt === selectedId);
            const srcNode  = NODE_BY_ID[src];
            el.attr('stroke-opacity', active ? 0.85 : 0.05)
              .attr('stroke-width',   active ? 2.2 : 1.4)
              .attr('marker-end', active
                  ? (srcNode ? `url(#arr-${srcNode.layer})` : 'url(#arr-dim)')
                  : 'url(#arr-dim)');
        });
    }

    function resetVisuals() {
        NODES.forEach(n => {
            d3.select(`.nd-${n.id} .nd-bg`)
                .attr('stroke-width', 1.4).attr('stroke-opacity', 0.65).attr('fill', '#21201d');
            d3.select(`.nd-${n.id} .nd-label`).attr('opacity', 1);
            d3.select(`.nd-${n.id} .nd-strip`).attr('opacity', 0.70);
        });
        d3.selectAll('.edge').each(function () {
            const cls     = this.getAttribute('class') || '';
            const src     = (cls.match(/e-src-([^\s]+)/) || [])[1] || '';
            const srcNode = NODE_BY_ID[src];
            d3.select(this)
                .attr('stroke-opacity', 0.28).attr('stroke-width', 1.4)
                .attr('marker-end', srcNode ? `url(#arr-${srcNode.layer})` : 'url(#arr-dim)');
        });
    }

    // ══════════════════════════════════════════════════════════════════════════
    // DETAIL PANEL
    // ══════════════════════════════════════════════════════════════════════════

    function renderDetail(nodeId) {
        const panel   = document.getElementById('archDetail');
        const content = document.getElementById('archDetailContent');
        if (!panel || !content) return;
        const node  = NODE_BY_ID[nodeId];
        if (!node) return;
        const cfg   = LAYER_CONFIG[node.layer];
        const color = cfg.color;

        const chips = (ids) => {
            if (!ids.length) return '<span class="arch-detail-empty-chips">None</span>';
            return ids.map(id => {
                const n = NODE_BY_ID[id];
                if (!n) return '';
                const nc = LAYER_CONFIG[n.layer].color;
                return `<button class="arch-chip" style="border-color:${nc}50;color:${nc};background:${nc}0f;"
                    onclick="window._archSelectNode('${n.id}')">${n.label}</button>`;
            }).join('');
        };

        content.innerHTML = `
            <div class="arch-detail-header">
                <div class="arch-detail-badge" style="background:${color}18;color:${color};border-color:${color}40;">
                    ${cfg.label}
                </div>
                <div class="arch-detail-title">${node.label}</div>
                <div class="arch-detail-desc">${node.desc}</div>
                ${node.note ? `<div class="arch-detail-note">${node.note}</div>` : ''}
            </div>
            <div class="arch-detail-section">
                <div class="arch-detail-section-label">Called By</div>
                <div class="arch-chips">
                    ${node.calledBy.length
                        ? chips(node.calledBy)
                        : '<span class="arch-detail-empty-chips">Top-level entry point</span>'}
                </div>
            </div>
            <div class="arch-detail-section">
                <div class="arch-detail-section-label">Calls Into</div>
                <div class="arch-chips">
                    ${node.callsInto.length
                        ? chips(node.callsInto)
                        : '<span class="arch-detail-empty-chips">No outbound dependencies</span>'}
                </div>
            </div>
            <div class="arch-detail-section">
                <div class="arch-detail-section-label">CLAUDE.md</div>
                ${node.claudeMd
                    ? `<div class="arch-detail-path">${node.claudeMd}</div>`
                    : '<div class="arch-detail-path-none">Entry point — no CLAUDE.md</div>'}
            </div>
        `;

        panel.classList.add('is-open');
    }

    function clearDetail() {
        const panel = document.getElementById('archDetail');
        if (panel) panel.classList.remove('is-open');
    }

    window._archSelectNode = function (nodeId) { select(nodeId); };

    // ══════════════════════════════════════════════════════════════════════════
    // TOOLTIP
    // ══════════════════════════════════════════════════════════════════════════

    function showTooltip(ev, text) {
        if (!_tooltip) return;
        _tooltip.textContent = text;
        _tooltip.classList.add('is-visible');
        moveTooltip(ev);
    }
    function moveTooltip(ev) {
        if (!_tooltip) return;
        _tooltip.style.left = `${ev.clientX + 14}px`;
        _tooltip.style.top  = `${ev.clientY + 14}px`;
    }
    function hideTooltip() {
        if (_tooltip) _tooltip.classList.remove('is-visible');
    }

    // ══════════════════════════════════════════════════════════════════════════
    // LEGEND
    // ══════════════════════════════════════════════════════════════════════════

    function buildLegend() {
        const legend = document.getElementById('archLegend');
        if (!legend) return;
        const seen  = new Set();
        const items = [];
        Object.values(LAYER_CONFIG).forEach(cfg => {
            if (!seen.has(cfg.label)) {
                seen.add(cfg.label);
                items.push({ label: cfg.label, color: cfg.color });
            }
        });
        legend.innerHTML = items.map(it =>
            `<div class="arch-legend-item">
                <div class="arch-legend-dot" style="background:${it.color};"></div>
                <span>${it.label}</span>
            </div>`
        ).join('');
    }

    // ══════════════════════════════════════════════════════════════════════════
    // TOOLBAR
    // ══════════════════════════════════════════════════════════════════════════

    function _wireToolbar() {
        if (_toolbarWired) return;
        _toolbarWired = true;

        document.getElementById('archZoomInBtn')?.addEventListener('click', (ev) => {
            ev.stopPropagation();
            if (_svg && _zoom) _svg.transition().duration(220).call(_zoom.scaleBy, 1.4);
        });
        document.getElementById('archZoomOutBtn')?.addEventListener('click', (ev) => {
            ev.stopPropagation();
            if (_svg && _zoom) _svg.transition().duration(220).call(_zoom.scaleBy, 1 / 1.4);
        });
        document.getElementById('archResetBtn')?.addEventListener('click', (ev) => {
            ev.stopPropagation();
            resetZoom(true);
        });
    }

    // ══════════════════════════════════════════════════════════════════════════
    // PAGE MODULE
    // ══════════════════════════════════════════════════════════════════════════

    function mount(container, shell) {
        if (_mounted) return;
        _mounted = true;
        _tooltip = document.getElementById('archTooltip');
        _isLTR   = (window.innerWidth >= MOBILE_BREAKPOINT);
        buildLegend();
        requestAnimationFrame(() => {
            render('archCanvas');
            _wireToolbar();
            setupResponsive('archCanvas');
        });
        shell?.setSearchPlaceholder('Filter components...');
    }

    function unmount() {
        _mounted      = false;
        _toolbarWired = false;
        _selectedId   = null;
        _svg          = null;
        _g            = null;
        _zoom         = null;
        _positions    = null;
        if (_resizeObserver) {
            _resizeObserver.disconnect();
            _resizeObserver = null;
        }
        hideTooltip();
    }

    function onSearch(query, _shell) {
        if (!_g) return;
        const q = query.trim().toLowerCase();
        if (!q) { resetVisuals(); return; }
        const matched = new Set(
            NODES.filter(n => n.label.toLowerCase().includes(q) || n.desc.toLowerCase().includes(q))
                 .map(n => n.id)
        );
        NODES.forEach(n => {
            const dim = !matched.has(n.id);
            d3.select(`.nd-${n.id} .nd-bg`).attr('stroke-opacity', dim ? 0.12 : 0.80);
            d3.select(`.nd-${n.id} .nd-label`).attr('opacity', dim ? 0.18 : 1);
            d3.select(`.nd-${n.id} .nd-strip`).attr('opacity', dim ? 0.12 : 0.80);
        });
        d3.selectAll('.edge').attr('stroke-opacity', 0.06);
    }

    window.PageRouter?.register({
        id:     'arch',
        label:  'Architecture',
        paths:  ['/arch', '/architecture'],
        mount,
        unmount,
        onSearch,
    });

})();
