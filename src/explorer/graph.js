/**
 * graph.js — D3 v7 force-directed graph renderer.
 * Depends on: d3.min.js, api.js, panel.js (must be loaded first).
 */

const Graph = (() => {
    // ── Config ────────────────────────────────────────────────────────────────
    const RADIUS_BASE = 8;
    const RADIUS_SCALE = d3.scaleSqrt().domain([0, 20]).range([RADIUS_BASE, 22]).clamp(true);
    const LABEL_COLORS = {
        Person: '#7eb8f7',
        Organization: '#f7c27e',
        Project: '#7ee8a2',
        Topic: '#c27ef7',
        Event: '#f77ec2',
        Fact: '#f7e87e',
    };
    function nodeColor(label) { return LABEL_COLORS[label] || '#6a6e88'; }

    // ── State ─────────────────────────────────────────────────────────────────
    let allNodes = [], allEdges = [];
    let activeLabels = new Set();
    let selectedNodeId = null;
    let simulation, svg, g, linkSel, nodeSel, labelSel;

    // ── DOM refs ──────────────────────────────────────────────────────────────
    const svgEl = document.getElementById('graph-svg');
    const hintEl = document.getElementById('canvas-hint');
    const filterWrap = document.getElementById('label-filters');
    const legendWrap = document.getElementById('legend');
    const statNeo4j = document.getElementById('stat-neo4j');
    const statNodes = document.getElementById('stat-nodes');
    const statEdges = document.getElementById('stat-edges');
    const statRum = document.getElementById('stat-rumination');
    const searchInput = document.getElementById('search-input');
    const searchRes = document.getElementById('search-results');

    // ── Init ──────────────────────────────────────────────────────────────────
    async function init() {
        const data = await API.overview();
        allNodes = data.nodes || [];
        allEdges = data.edges || [];

        // Stats bar
        statNodes.textContent = `${allNodes.length} nodes`;
        statEdges.textContent = `${allEdges.length} edges`;
        statRum.textContent = `rumination: ${data.stats?.last_rumination ?? 'never'}`;
        
        if (data.stats?.neo4j_connected) {
            statNeo4j.textContent = '● Neo4j Connected';
            statNeo4j.style.color = '#7ee8a2'; // Green
        } else {
            statNeo4j.textContent = '○ Neo4j Offline';
            statNeo4j.style.color = '#f77e7e'; // Red
        }

        // Compute degree for radius scaling
        const degree = {};
        allEdges.forEach(e => {
            degree[e.source] = (degree[e.source] || 0) + 1;
            degree[e.target] = (degree[e.target] || 0) + 1;
        });
        allNodes.forEach(n => { n._degree = degree[n.id] || 0; });

        // Label set
        activeLabels = new Set(allNodes.map(n => n.label));
        buildFilters();
        buildLegend();
        buildSVG();
        render();
        wireSearch();
    }

    // ── Label filter sidebar ──────────────────────────────────────────────────
    function buildFilters() {
        const labels = [...new Set(allNodes.map(n => n.label))].sort();
        filterWrap.innerHTML = '';
        for (const label of labels) {
            const row = document.createElement('div');
            row.className = 'filter-row';
            row.dataset.label = label;
            row.innerHTML = `
        <div class="filter-dot" style="background:${nodeColor(label)}"></div>
        <span class="filter-name">${label}</span>
        <input type="checkbox" checked />`;
            row.addEventListener('click', () => toggleLabel(label, row));
            filterWrap.appendChild(row);
        }
    }

    function buildLegend() {
        const labels = [...new Set(allNodes.map(n => n.label))].sort();
        legendWrap.innerHTML = '';
        for (const label of labels) {
            legendWrap.innerHTML += `
        <div class="legend-row">
          <div class="legend-dot" style="background:${nodeColor(label)}"></div>
          <span>${label}</span>
        </div>`;
        }
    }

    function toggleLabel(label, rowEl) {
        if (activeLabels.has(label)) {
            activeLabels.delete(label);
            rowEl.classList.add('inactive');
        } else {
            activeLabels.add(label);
            rowEl.classList.remove('inactive');
        }
        render();
    }

    // ── SVG setup ─────────────────────────────────────────────────────────────
    function buildSVG() {
        svg = d3.select(svgEl);
        svg.selectAll('*').remove();

        // Zoom
        const zoom = d3.zoom()
            .scaleExtent([0.1, 5])
            .on('zoom', (e) => g.attr('transform', e.transform));
        svg.call(zoom);

        g = svg.append('g');
        // Marker for edges
        svg.append('defs').append('marker')
            .attr('id', 'arrow')
            .attr('viewBox', '0 -4 8 8')
            .attr('refX', 18).attr('refY', 0)
            .attr('markerWidth', 4).attr('markerHeight', 4)
            .attr('orient', 'auto')
            .append('path')
            .attr('d', 'M0,-4L8,0L0,4')
            .attr('fill', '#3d4155');
    }

    // ── Render ────────────────────────────────────────────────────────────────
    function render() {
        const visNodes = allNodes.filter(n => activeLabels.has(n.label));
        const visNodeIds = new Set(visNodes.map(n => n.id));
        const visEdges = allEdges.filter(e => visNodeIds.has(e.source) && visNodeIds.has(e.target));

        // D3 needs mutable copies
        const nodes = visNodes.map(n => ({ ...n }));
        const edges = visEdges.map(e => ({ ...e }));

        if (simulation) simulation.stop();

        const W = svgEl.clientWidth || 900;
        const H = svgEl.clientHeight || 600;

        simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(edges).id(d => d.id).distance(90).strength(0.4))
            .force('charge', d3.forceManyBody().strength(-220))
            .force('center', d3.forceCenter(W / 2, H / 2))
            .force('collide', d3.forceCollide(d => RADIUS_SCALE(d._degree) + 6))
            .alphaDecay(0.025);

        g.selectAll('*').remove();

        // Edges
        linkSel = g.append('g').selectAll('line')
            .data(edges).join('line')
            .attr('class', 'edge-line')
            .attr('marker-end', 'url(#arrow)');

        // Edge labels (show on longer edges only — determined after tick)
        const edgeLabelSel = g.append('g').selectAll('text')
            .data(edges).join('text')
            .attr('class', 'edge-label')
            .text(d => d.type);

        // Nodes
        nodeSel = g.append('g').selectAll('circle')
            .data(nodes, d => d.id).join('circle')
            .attr('class', 'node-circle')
            .attr('r', d => RADIUS_SCALE(d._degree))
            .attr('fill', d => nodeColor(d.label) + '33')
            .attr('stroke', d => nodeColor(d.label))
            .call(drag(simulation))
            .on('click', (event, d) => selectNode(d.id))
            .on('dblclick', (event, d) => { event.stopPropagation(); expandNode(d.id); });

        // Node labels
        labelSel = g.append('g').selectAll('text')
            .data(nodes, d => d.id).join('text')
            .attr('class', 'node-label')
            .attr('dy', d => RADIUS_SCALE(d._degree) + 12)
            .text(d => d.name.length > 18 ? d.name.slice(0, 16) + '…' : d.name);

        simulation.on('tick', () => {
            linkSel
                .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x).attr('y2', d => d.target.y);

            edgeLabelSel
                .attr('x', d => ((d.source.x ?? 0) + (d.target.x ?? 0)) / 2)
                .attr('y', d => ((d.source.y ?? 0) + (d.target.y ?? 0)) / 2);

            nodeSel
                .attr('cx', d => d.x)
                .attr('cy', d => d.y);

            labelSel
                .attr('x', d => d.x)
                .attr('y', d => d.y);
        });
    }

    // ── Node selection ────────────────────────────────────────────────────────
    async function selectNode(nodeId) {
        selectedNodeId = nodeId;
        hintEl.style.opacity = '0';

        // Visual selection state
        if (nodeSel) {
            nodeSel.classed('selected', d => d.id === nodeId);
        }

        const node = allNodes.find(n => n.id === nodeId);
        Panel.showLoading(node?.name);

        try {
            const data = await API.nodeDetail(nodeId);
            Panel.renderNode(data);
        } catch (err) {
            console.error('nodeDetail failed', err);
        }
    }

    // ── Node expand (dblclick) ────────────────────────────────────────────────
    async function expandNode(nodeId) {
        try {
            const data = await API.expand(nodeId);
            // Merge new nodes into allNodes (deduplicate by id)
            const existingIds = new Set(allNodes.map(n => n.id));
            const degree = {};
            (data.edges || []).forEach(e => {
                degree[e.source] = (degree[e.source] || 0) + 1;
                degree[e.target] = (degree[e.target] || 0) + 1;
            });
            for (const n of (data.nodes || [])) {
                if (!existingIds.has(n.id)) {
                    n._degree = degree[n.id] || 0;
                    allNodes.push(n);
                    activeLabels.add(n.label);
                }
            }
            // Merge edges (deduplicate by source+target+type)
            const existingEdgeKeys = new Set(allEdges.map(e => `${e.source}|${e.target}|${e.type}`));
            for (const e of (data.edges || [])) {
                const key = `${e.source}|${e.target}|${e.type}`;
                if (!existingEdgeKeys.has(key)) allEdges.push(e);
            }
            render();
        } catch (err) {
            console.error('expand failed', err);
        }
    }

    // ── Public: focus a node by ID (called from panel connection clicks) ──────
    function focusNode(nodeId) {
        selectNode(nodeId);
        // Pan the camera to the node
        if (!nodeSel) return;
        nodeSel.each(function (d) {
            if (d.id !== nodeId) return;
            const W = svgEl.clientWidth || 900;
            const H = svgEl.clientHeight || 600;
            const zoom = d3.zoom().scaleExtent([0.1, 5]).on('zoom', (e) => g.attr('transform', e.transform));
            d3.select(svgEl).transition().duration(500)
                .call(zoom.transform, d3.zoomIdentity.translate(W / 2 - d.x, H / 2 - d.y));
        });
    }

    // ── Public: clear selection ───────────────────────────────────────────────
    function clearSelection() {
        selectedNodeId = null;
        if (nodeSel) nodeSel.classed('selected', false);
        hintEl.style.opacity = '1';
    }

    // ── Search ────────────────────────────────────────────────────────────────
    function wireSearch() {
        let debounce;
        searchInput.addEventListener('input', () => {
            clearTimeout(debounce);
            debounce = setTimeout(doSearch, 220);
        });
        searchInput.addEventListener('blur', () => {
            setTimeout(() => searchRes.classList.add('hidden'), 200);
        });
        searchInput.addEventListener('focus', () => {
            if (searchInput.value.trim()) doSearch();
        });
    }

    async function doSearch() {
        const q = searchInput.value.trim();
        if (!q) { searchRes.classList.add('hidden'); return; }

        try {
            const data = await API.search(q);
            const results = data.results || [];
            if (!results.length) { searchRes.classList.add('hidden'); return; }

            searchRes.innerHTML = results.slice(0, 8).map(r => `
        <div class="search-result-item" data-id="${r.id}">
          <span class="search-result-label" style="background:${Panel.labelColor(r.label)}22;color:${Panel.labelColor(r.label)}">${r.label}</span>
          <span class="search-result-name">${r.name}</span>
        </div>`).join('');

            searchRes.classList.remove('hidden');

            searchRes.querySelectorAll('.search-result-item').forEach(el => {
                el.addEventListener('click', () => {
                    focusNode(el.dataset.id);
                    searchRes.classList.add('hidden');
                    searchInput.value = '';
                });
            });
        } catch (e) {
            console.error('search failed', e);
        }
    }

    // ── Drag helper ───────────────────────────────────────────────────────────
    function drag(sim) {
        return d3.drag()
            .on('start', (event, d) => {
                if (!event.active) sim.alphaTarget(0.3).restart();
                d.fx = d.x; d.fy = d.y;
            })
            .on('drag', (event, d) => {
                d.fx = event.x; d.fy = event.y;
            })
            .on('end', (event, d) => {
                if (!event.active) sim.alphaTarget(0);
                d.fx = null; d.fy = null;
            });
    }

    // ── Boot ──────────────────────────────────────────────────────────────────
    init().catch(err => console.error('Graph init failed:', err));

    return { focusNode, clearSelection };
})();