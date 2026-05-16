(function () {
    'use strict';

    // ══════════════════════════════════════════════════════════════════════════
    // DATA — component coupling map derived from CLAUDE.md files
    // ══════════════════════════════════════════════════════════════════════════

    const LAYER_CONFIG = {
        entry:      { label: 'Entry Points',   color: '#70695f', row: 0 },
        platform:   { label: 'Boot',           color: '#7E91BE', row: 1 },
        bot:        { label: 'Boot',           color: '#8F859A', row: 1 },
        app:        { label: 'App Layer',      color: '#7FA38D', row: 2 },
        background: { label: 'Background',     color: '#C49B76', row: 2 },
        gateway:    { label: 'Public Gateway', color: '#BEAA7E', row: 3 },
        infra:      { label: 'Infrastructure', color: '#A37A87', row: 4 },
        core:       { label: 'Core',           color: '#7E91BE', row: 5 },
        storage:    { label: 'Storage',        color: '#6B8F7A', row: 6 },
    };

    // Row y-fractions (fraction of drawable height)
    const ROW_Y = [0.055, 0.175, 0.335, 0.510, 0.655, 0.800, 0.930];

    const NODES = [
        {
            id: 'main', label: 'main.py', layer: 'entry', xFrac: 0.30,
            desc: 'FastAPI server entry point. Calls create_platform_app() and runs uvicorn.',
            note: null,
            claudeMd: null,
            calledBy: [],
            callsInto: ['platform'],
        },
        {
            id: 'run_bot', label: 'run_bot.py', layer: 'entry', xFrac: 0.70,
            desc: 'Telegram bot entry point. Runs independently of the web server.',
            note: null,
            claudeMd: null,
            calledBy: [],
            callsInto: ['bot'],
        },
        {
            id: 'platform', label: 'platform/', layer: 'platform', xFrac: 0.33,
            desc: 'FastAPI app factory (create_platform_app), app registry, shell router, graph-ingest endpoint.',
            note: 'The only place that imports all five app get_*_app() factories. Starts/stops RuminationScheduler in lifespan.',
            claudeMd: 'src/platform/CLAUDE.md',
            calledBy: ['main'],
            callsInto: ['app_chat', 'app_explorer', 'app_credits', 'app_financial', 'app_routine', 'memory', 'rumination', 'core'],
        },
        {
            id: 'bot', label: 'bot/', layer: 'bot', xFrac: 0.70,
            desc: 'TelegramBot (handlers, session tracking) + ProactiveBot (outbound digests, reconciliation).',
            note: 'TelegramBot calls src.core.agent.Agent directly — pre-dates AgentService. Migrate to AgentService if refactoring.',
            claudeMd: 'src/bot/CLAUDE.md',
            calledBy: ['run_bot', 'rumination'],
            callsInto: ['core', 'memory', 'public_gateway'],
        },
        {
            id: 'app_chat', label: 'apps/chat', layer: 'app', xFrac: 0.06,
            desc: 'Browser conversation sessions. Session CRUD and message dispatch through the agent platform.',
            note: null,
            claudeMd: 'src/apps/chat/CLAUDE.md',
            calledBy: ['platform'],
            callsInto: ['public_gateway', 'memory'],
        },
        {
            id: 'app_explorer', label: 'apps/explorer', layer: 'app', xFrac: 0.22,
            desc: 'Knowledge graph UI, system status, analyzer controls, canonicalization, eras, pending beliefs.',
            note: 'Only app that imports analyzers directly — it is the admin surface for the extraction pipeline.',
            claudeMd: 'src/apps/explorer/CLAUDE.md',
            calledBy: ['platform'],
            callsInto: ['public_gateway', 'memory', 'analyzers', 'ingestion'],
        },
        {
            id: 'app_credits', label: 'apps/credits', layer: 'app', xFrac: 0.38,
            desc: 'LLM quota management console. Shows per-model headroom, imports rate limits.',
            note: 'Exception to the no-core-import rule — intentionally reads llm_router internals. Other apps use aquota_status() instead.',
            claudeMd: 'src/apps/credits/CLAUDE.md',
            calledBy: ['platform'],
            callsInto: ['core'],
        },
        {
            id: 'app_financial', label: 'apps/financial', layer: 'app', xFrac: 0.54,
            desc: 'Finance workflows — stub. AppDefinition only, no services or API yet.',
            note: null,
            claudeMd: 'src/apps/financial_manager/CLAUDE.md',
            calledBy: ['platform'],
            callsInto: [],
        },
        {
            id: 'app_routine', label: 'apps/routine', layer: 'app', xFrac: 0.68,
            desc: 'Scheduling automation — stub. AppDefinition only, no services or API yet.',
            note: null,
            claudeMd: 'src/apps/routine_scheduler/CLAUDE.md',
            calledBy: ['platform'],
            callsInto: [],
        },
        {
            id: 'rumination', label: 'rumination/', layer: 'background', xFrac: 0.86,
            desc: 'Background scheduler started in FastAPI lifespan. Deep-pass (belief synthesis) and rabbit-hole ticks.',
            note: 'Disabled by settings.rumination_enabled=False. Manages ProactiveBot lifecycle inside the web server process.',
            claudeMd: 'src/rumination/CLAUDE.md',
            calledBy: ['platform'],
            callsInto: ['memory', 'public_gateway', 'bot'],
        },
        {
            id: 'public_gateway', label: 'agent_platform/public', layer: 'gateway', xFrac: 0.50,
            desc: 'AgentService + contracts (AgentRunRequest, AgentRunResult). The only app-facing entry point for running the agent.',
            note: 'Wraps src.core.agent.Agent behind a stable interface. Apps must never import Agent directly.',
            claudeMd: 'src/agent_platform/public/CLAUDE.md',
            calledBy: ['app_chat', 'app_explorer', 'bot', 'rumination'],
            callsInto: ['core', 'memory'],
        },
        {
            id: 'tools', label: 'agent_platform/tools', layer: 'infra', xFrac: 0.18,
            desc: 'LLM-callable tools registered via registry.py: graph_write, search_memories, tasks, beliefs, web_search, calendar.',
            note: 'Loaded by src.core.agent at init. Invoked by the LLM during a turn — not called directly by app code.',
            claudeMd: 'src/agent_platform/tools/CLAUDE.md',
            calledBy: ['core'],
            callsInto: ['memory'],
        },
        {
            id: 'analyzers', label: 'agent_platform/analyzers', layer: 'infra', xFrac: 0.50,
            desc: 'Extraction pipeline: local-LLM (Gemma 4) for entities/tasks, Gemini cloud pass for beliefs, canonicalization.',
            note: 'Auto-triggered from MemoryManager.store() when unanalyzed queue depth ≥ settings.graph_ingest_threshold.',
            claudeMd: 'src/agent_platform/analyzers/CLAUDE.md',
            calledBy: ['app_explorer', 'memory', 'bot'],
            callsInto: ['memory', 'core'],
        },
        {
            id: 'ingestion', label: 'ingestion/', layer: 'infra', xFrac: 0.82,
            desc: 'Bulk import pipeline: JSONL, plaintext, Telegram export formats → Chroma queue.',
            note: 'Calls memory.store() only (Chroma). After import, app_explorer calls run_extraction_pass() to populate Neo4j.',
            claudeMd: 'src/ingestion/CLAUDE.md',
            calledBy: ['app_explorer'],
            callsInto: ['memory'],
        },
        {
            id: 'core', label: 'src/core', layer: 'core', xFrac: 0.50,
            desc: 'Agent, LLM router, rate limiter, config (settings), prompts — internal infrastructure.',
            note: 'Apps must not import from here directly (except settings). Only credits app uses llm_router intentionally.',
            claudeMd: 'src/core/CLAUDE.md',
            calledBy: ['public_gateway', 'tools', 'analyzers', 'bot', 'platform', 'app_credits', 'rumination'],
            callsInto: ['memory', 'tools'],
        },
        {
            id: 'memory', label: 'src/memory', layer: 'storage', xFrac: 0.50,
            desc: 'MemoryManager facade: ChromaDB (conversation history) + Neo4j (knowledge graph). Lazy singleton via get_memory_manager().',
            note: 'Never access .neo4j or .chroma directly. After store() calls, maybe_trigger() fires the analyzer if queue is full.',
            claudeMd: 'src/memory/CLAUDE.md',
            calledBy: ['app_chat', 'app_explorer', 'public_gateway', 'core', 'tools', 'analyzers', 'platform', 'rumination', 'bot', 'ingestion'],
            callsInto: ['analyzers'],
        },
    ];

    // ── Build edges from node data ─────────────────────────────────────────

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
    // LAYOUT
    // ══════════════════════════════════════════════════════════════════════════

    const NODE_W = 128;
    const NODE_H = 32;
    const NODE_RX = 5;
    const PAD_TOP = 32;
    const PAD_BOTTOM = 44;
    const PAD_LEFT = 108;   // space for layer labels
    const PAD_RIGHT = 24;

    function computePositions(canvasW, canvasH) {
        const drawW = canvasW - PAD_LEFT - PAD_RIGHT;
        const drawH = canvasH - PAD_TOP - PAD_BOTTOM;
        const pos = {};
        NODES.forEach(node => {
            const rowY = ROW_Y[LAYER_CONFIG[node.layer].row];
            pos[node.id] = {
                x: PAD_LEFT + node.xFrac * drawW,
                y: PAD_TOP + rowY * drawH,
            };
        });
        return pos;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // EDGE PATHS
    // ══════════════════════════════════════════════════════════════════════════

    function edgePath(srcPos, tgtPos) {
        const sx = srcPos.x;
        const sy = srcPos.y + NODE_H / 2 + 1;   // bottom of source
        const tx = tgtPos.x;
        const ty = tgtPos.y - NODE_H / 2 - 1;   // top of target

        const dy = ty - sy;

        if (dy > 8) {
            // Downward: smooth S-curve keeping x, meet in the middle
            const cp1y = sy + dy * 0.38;
            const cp2y = ty - dy * 0.38;
            return `M ${sx} ${sy} C ${sx} ${cp1y}, ${tx} ${cp2y}, ${tx} ${ty}`;
        }

        // Upward or same-level: route wide around to avoid overlapping nodes
        // Direction: go to the side that has more space from source
        const sideDir = sx > (PAD_LEFT + (800 - PAD_LEFT - PAD_RIGHT) * 0.5) ? 1 : -1;
        const offset = 80 + Math.abs(dy) * 0.3;
        const midY = (sy + ty) / 2;
        return `M ${sx} ${sy} C ${sx + sideDir * offset} ${sy + 24}, ${tx + sideDir * offset} ${ty - 24}, ${tx} ${ty}`;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // STATE
    // ══════════════════════════════════════════════════════════════════════════

    let _positions = null;
    let _selectedId = null;
    let _svg = null;
    let _g = null;
    let _zoom = null;
    let _mounted = false;
    let _tooltip = null;

    // ══════════════════════════════════════════════════════════════════════════
    // RENDER
    // ══════════════════════════════════════════════════════════════════════════

    function render(canvasId) {
        const wrap = document.getElementById(canvasId);
        if (!wrap) return;

        const W = wrap.clientWidth || 880;
        const H = Math.max(wrap.clientHeight || 680, 640);

        _positions = computePositions(W, H);

        // SVG root
        _svg = d3.select(`#${canvasId}`)
            .append('svg')
            .attr('width', '100%')
            .attr('height', '100%')
            .attr('viewBox', `0 0 ${W} ${H}`)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .on('click', () => deselect());

        // ── Defs: arrow markers ───────────────────────────────────────────

        const defs = _svg.append('defs');

        // Arrow for each layer color
        Object.entries(LAYER_CONFIG).forEach(([layerId, cfg]) => {
            defs.append('marker')
                .attr('id', `arr-${layerId}`)
                .attr('viewBox', '0 -4 8 8')
                .attr('refX', 7).attr('refY', 0)
                .attr('markerWidth', 5).attr('markerHeight', 5)
                .attr('orient', 'auto')
                .append('path')
                .attr('d', 'M0,-4L8,0L0,4')
                .attr('fill', cfg.color);
        });

        // Dimmed arrow
        defs.append('marker')
            .attr('id', 'arr-dim')
            .attr('viewBox', '0 -4 8 8')
            .attr('refX', 7).attr('refY', 0)
            .attr('markerWidth', 5).attr('markerHeight', 5)
            .attr('orient', 'auto')
            .append('path').attr('d', 'M0,-4L8,0L0,4')
            .attr('fill', '#3a3835');

        // ── Zoom group ────────────────────────────────────────────────────

        _g = _svg.append('g').attr('class', 'arch-root');

        _zoom = d3.zoom()
            .scaleExtent([0.35, 3.0])
            .on('zoom', (ev) => { _g.attr('transform', ev.transform); });
        _svg.call(_zoom);

        // ── Layer band guidelines ─────────────────────────────────────────

        const drawnRows = new Set();
        const drawH = H - PAD_TOP - PAD_BOTTOM;

        // Build unique rows
        const rowMeta = {};
        Object.entries(LAYER_CONFIG).forEach(([layerId, cfg]) => {
            const ri = cfg.row;
            if (!rowMeta[ri]) {
                rowMeta[ri] = { y: PAD_TOP + ROW_Y[ri] * drawH, labels: new Set() };
            }
            rowMeta[ri].labels.add(cfg.label);
        });

        Object.values(rowMeta).forEach(row => {
            const label = [...row.labels].join(' / ');
            // Dashed band line
            _g.append('line')
                .attr('x1', PAD_LEFT - 8).attr('y1', row.y)
                .attr('x2', W - PAD_RIGHT).attr('y2', row.y)
                .attr('stroke', '#2c2a27')
                .attr('stroke-width', 1)
                .attr('stroke-dasharray', '3,8');

            // Label
            _g.append('text')
                .attr('x', PAD_LEFT - 11).attr('y', row.y + 5)
                .attr('text-anchor', 'end')
                .attr('font-size', '9')
                .attr('font-family', 'Inter, sans-serif')
                .attr('fill', '#5a5650')
                .attr('letter-spacing', '0.06em')
                .text(label.toUpperCase());
        });

        // ── Edges ─────────────────────────────────────────────────────────

        const edgeG = _g.append('g').attr('class', 'edge-layer');

        EDGES.forEach(edge => {
            const sp = _positions[edge.source];
            const tp = _positions[edge.target];
            if (!sp || !tp) return;
            const srcNode = NODE_BY_ID[edge.source];
            const color = LAYER_CONFIG[srcNode.layer].color;
            const d = edgePath(sp, tp);

            edgeG.append('path')
                .attr('class', `edge e-src-${edge.source} e-tgt-${edge.target}`)
                .attr('d', d)
                .attr('fill', 'none')
                .attr('stroke', color)
                .attr('stroke-width', 1.4)
                .attr('stroke-opacity', 0.28)
                .attr('marker-end', `url(#arr-${srcNode.layer})`);
        });

        // ── Nodes ─────────────────────────────────────────────────────────

        const nodeG = _g.append('g').attr('class', 'node-layer');

        NODES.forEach(node => {
            const p = _positions[node.id];
            const color = LAYER_CONFIG[node.layer].color;

            const g = nodeG.append('g')
                .attr('class', `node nd-${node.id}`)
                .attr('transform', `translate(${p.x - NODE_W / 2}, ${p.y - NODE_H / 2})`)
                .attr('cursor', 'pointer')
                .on('click', (ev) => {
                    ev.stopPropagation();
                    select(node.id);
                })
                .on('mouseenter', (ev) => {
                    hovering(node.id, true);
                    showTooltip(ev, node.desc);
                })
                .on('mousemove', (ev) => moveTooltip(ev))
                .on('mouseleave', () => {
                    hovering(node.id, false);
                    hideTooltip();
                });

            // Background rect
            g.append('rect')
                .attr('class', 'nd-bg')
                .attr('width', NODE_W).attr('height', NODE_H)
                .attr('rx', NODE_RX)
                .attr('fill', '#21201d')
                .attr('stroke', color)
                .attr('stroke-width', 1.4)
                .attr('stroke-opacity', 0.65);

            // Left color strip
            g.append('rect')
                .attr('class', 'nd-strip')
                .attr('x', 1).attr('y', 1)
                .attr('width', 3).attr('height', NODE_H - 2)
                .attr('rx', 2)
                .attr('fill', color)
                .attr('opacity', 0.75);

            // Label
            g.append('text')
                .attr('class', 'nd-label')
                .attr('x', NODE_W / 2 + 3)
                .attr('y', NODE_H / 2 + 1)
                .attr('text-anchor', 'middle')
                .attr('dominant-baseline', 'middle')
                .attr('font-size', '10.5')
                .attr('font-family', 'Inter, sans-serif')
                .attr('fill', '#DFDCD6')
                .attr('pointer-events', 'none')
                .text(node.label);
        });
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
        if (!on) {
            resetVisuals();
            return;
        }
        const connected = connectedIds(nodeId);
        applyDimming(nodeId, connected, 0.22, 0.08);
    }

    function select(nodeId) {
        _selectedId = nodeId;
        const connected = connectedIds(nodeId);
        applyDimming(nodeId, connected, 0.28, 0.06);
        renderDetail(nodeId);
    }

    function deselect() {
        _selectedId = null;
        resetVisuals();
        clearDetail();
    }

    function applyDimming(selectedId, connected, edgeActiveOpacity, edgeDimOpacity) {
        // Nodes
        NODES.forEach(n => {
            const isSelected = n.id === selectedId;
            const isConnected = connected.has(n.id);
            d3.select(`.nd-${n.id} .nd-bg`)
                .attr('stroke-width', isSelected ? 2.2 : 1.4)
                .attr('stroke-opacity', isConnected ? 0.95 : 0.18)
                .attr('fill', isSelected ? '#2a2927' : '#21201d');
            d3.select(`.nd-${n.id} .nd-label`)
                .attr('opacity', isConnected ? 1 : 0.25);
            d3.select(`.nd-${n.id} .nd-strip`)
                .attr('opacity', isConnected ? 0.85 : 0.2);
        });

        // Edges
        d3.selectAll('.edge').each(function () {
            const el = d3.select(this);
            const cls = this.getAttribute('class') || '';
            const srcMatch = cls.match(/e-src-([^\s]+)/);
            const tgtMatch = cls.match(/e-tgt-([^\s]+)/);
            const src = srcMatch ? srcMatch[1] : '';
            const tgt = tgtMatch ? tgtMatch[1] : '';
            const active = (src === selectedId || tgt === selectedId);
            const srcNode = NODE_BY_ID[src];
            el.attr('stroke-opacity', active ? edgeActiveOpacity * 3.2 : edgeDimOpacity)
              .attr('stroke-width', active ? 2.2 : 1.4)
              .attr('marker-end', active
                  ? (srcNode ? `url(#arr-${srcNode.layer})` : 'url(#arr-dim)')
                  : 'url(#arr-dim)');
        });
    }

    function resetVisuals() {
        NODES.forEach(n => {
            d3.select(`.nd-${n.id} .nd-bg`)
                .attr('stroke-width', 1.4)
                .attr('stroke-opacity', 0.65)
                .attr('fill', '#21201d');
            d3.select(`.nd-${n.id} .nd-label`).attr('opacity', 1);
            d3.select(`.nd-${n.id} .nd-strip`).attr('opacity', 0.75);
        });
        d3.selectAll('.edge').each(function () {
            const el = d3.select(this);
            const cls = this.getAttribute('class') || '';
            const srcMatch = cls.match(/e-src-([^\s]+)/);
            const src = srcMatch ? srcMatch[1] : '';
            const srcNode = NODE_BY_ID[src];
            el.attr('stroke-opacity', 0.28)
              .attr('stroke-width', 1.4)
              .attr('marker-end', srcNode ? `url(#arr-${srcNode.layer})` : 'url(#arr-dim)');
        });
    }

    // ══════════════════════════════════════════════════════════════════════════
    // DETAIL PANEL
    // ══════════════════════════════════════════════════════════════════════════

    function renderDetail(nodeId) {
        const panel = document.getElementById('archDetail');
        const content = document.getElementById('archDetailContent');
        if (!panel || !content) return;

        const node = NODE_BY_ID[nodeId];
        if (!node) return;

        const cfg = LAYER_CONFIG[node.layer];
        const color = cfg.color;

        const renderChips = (ids) => {
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
                        ? renderChips(node.calledBy)
                        : '<span class="arch-detail-empty-chips">Top-level entry point</span>'}
                </div>
            </div>

            <div class="arch-detail-section">
                <div class="arch-detail-section-label">Calls Into</div>
                <div class="arch-chips">
                    ${node.callsInto.length
                        ? renderChips(node.callsInto)
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

    // Exposed for chip onclick callbacks
    window._archSelectNode = function (nodeId) {
        select(nodeId);
    };

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
        const x = ev.clientX + 14;
        const y = ev.clientY + 14;
        _tooltip.style.left = `${x}px`;
        _tooltip.style.top = `${y}px`;
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

        // Deduplicate by label
        const seen = new Set();
        const items = [];
        Object.values(LAYER_CONFIG).forEach(cfg => {
            if (!seen.has(cfg.label)) {
                seen.add(cfg.label);
                items.push({ label: cfg.label, color: cfg.color });
            }
        });

        legend.innerHTML = items.map(item =>
            `<div class="arch-legend-item">
                <div class="arch-legend-dot" style="background:${item.color};"></div>
                <span>${item.label}</span>
            </div>`
        ).join('');
    }

    // ══════════════════════════════════════════════════════════════════════════
    // PAGE MODULE
    // ══════════════════════════════════════════════════════════════════════════

    function mount(container, shell) {
        if (_mounted) return;
        _mounted = true;

        _tooltip = document.getElementById('archTooltip');

        buildLegend();
        requestAnimationFrame(() => {
            render('archCanvas');
            _wireToolbar();
        });

        shell?.setSearchPlaceholder('Filter components...');
    }

    function _wireToolbar() {
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
            if (_svg && _zoom) _svg.transition().duration(320).call(_zoom.transform, d3.zoomIdentity);
        });
    }

    function unmount() {
        _mounted = false;
        _selectedId = null;
        _svg = null;
        _g = null;
        _zoom = null;
        _positions = null;
        hideTooltip();
    }

    function onSearch(query, _shell) {
        if (!_g) return;
        const q = query.trim().toLowerCase();
        if (!q) {
            resetVisuals();
            return;
        }
        const matched = new Set(
            NODES
                .filter(n => n.label.toLowerCase().includes(q) || n.desc.toLowerCase().includes(q))
                .map(n => n.id)
        );
        NODES.forEach(n => {
            const dim = !matched.has(n.id);
            d3.select(`.nd-${n.id} .nd-bg`).attr('stroke-opacity', dim ? 0.15 : 0.8);
            d3.select(`.nd-${n.id} .nd-label`).attr('opacity', dim ? 0.2 : 1);
            d3.select(`.nd-${n.id} .nd-strip`).attr('opacity', dim ? 0.15 : 0.8);
        });
        d3.selectAll('.edge').attr('stroke-opacity', 0.08);
    }

    window.PageRouter?.register({
        id: 'arch',
        label: 'Architecture',
        paths: ['/arch', '/architecture'],
        mount,
        unmount,
        onSearch,
    });

})();
