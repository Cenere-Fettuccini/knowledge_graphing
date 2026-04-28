/**
 * panel.js — Detail panel + source conversation overlay.
 * Depends on: api.js (must be loaded first), graph.js (for focusNode).
 */

const Panel = (() => {
    // ── Label colour map (mirrors CSS variables) ──────────────────────────────
    const LABEL_COLORS = {
        Person: '#7eb8f7',
        Organization: '#f7c27e',
        Project: '#7ee8a2',
        Topic: '#c27ef7',
        Event: '#f77ec2',
        Fact: '#f7e87e',
    };

    function labelColor(label) {
        return LABEL_COLORS[label] || '#888';
    }

    // ── DOM refs ──────────────────────────────────────────────────────────────
    const panelEl = document.getElementById('detail-panel');
    const panelContent = document.getElementById('panel-content');
    const panelClose = document.getElementById('panel-close');
    const sourceOverlay = document.getElementById('source-overlay');
    const sourceBody = document.getElementById('source-body');
    const sourceTitle = document.getElementById('source-title');
    const sourceClose = document.getElementById('source-close');

    // ── Close handlers ────────────────────────────────────────────────────────
    panelClose.addEventListener('click', () => {
        panelEl.classList.add('hidden');
        if (typeof Graph !== 'undefined') Graph.clearSelection();
    });

    sourceClose.addEventListener('click', () => sourceOverlay.classList.add('hidden'));
    sourceOverlay.addEventListener('click', (e) => {
        if (e.target === sourceOverlay) sourceOverlay.classList.add('hidden');
    });

    // ── Public: show loading state ────────────────────────────────────────────
    function showLoading(nodeName) {
        panelContent.innerHTML = `
      <div class="panel-loading">Loading ${nodeName || ''}…</div>
    `;
        panelEl.classList.remove('hidden');
    }

    // ── Public: render a full node detail ────────────────────────────────────
    function renderNode(data) {
        const { node, connections, facts } = data;
        const color = labelColor(node.label);

        // Header
        let html = `
      <div class="panel-node-name">${esc(node.name)}</div>
      <span class="panel-node-label" style="background:${color}22;color:${color}">${esc(node.label)}</span>
    `;

        // Properties
        const props = node.properties || {};
        const propKeys = Object.keys(props);
        if (propKeys.length) {
            html += `<div class="panel-section-title">Properties</div>`;
            for (const k of propKeys) {
                html += `
          <div class="panel-prop-row">
            <span class="panel-prop-key">${esc(k)}</span>
            <span class="panel-prop-val">${esc(String(props[k]))}</span>
          </div>`;
            }
        }

        // Connections
        if (connections && connections.length) {
            html += `<div class="panel-section-title">Connections (${connections.length})</div>`;
            for (const c of connections) {
                const cColor = labelColor(c.node.label);
                const arrow = c.direction === 'out' ? '→' : '←';
                html += `
          <div class="conn-item" data-node-id="${esc(c.node.id)}">
            <span class="conn-dot" style="background:${cColor}"></span>
            <span class="conn-arrow">${arrow}</span>
            <span class="conn-rel">${esc(c.rel)}</span>
            <span class="conn-name">${esc(c.node.name)}</span>
          </div>`;
            }
        }

        // Facts
        if (facts && facts.length) {
            html += `<div class="panel-section-title">Facts (${facts.length})</div>`;
            for (const f of facts) {
                const conf = f.properties?.confidence;
                const date = f.properties?.source_date;
                html += `
          <div class="fact-item">
            <div class="fact-text">${esc(f.name)}</div>
            <div class="fact-meta">
              ${conf !== undefined ? `confidence: ${conf}` : ''}
              ${date ? ` · ${esc(date)}` : ''}
            </div>
            <button class="fact-source-btn" data-fact-id="${esc(f.id)}">View Source ↗</button>
          </div>`;
            }
        }

        panelContent.innerHTML = html;
        panelEl.classList.remove('hidden');

        // Wire connection clicks → focus that node
        panelContent.querySelectorAll('.conn-item').forEach(el => {
            el.addEventListener('click', () => {
                const id = el.dataset.nodeId;
                if (typeof Graph !== 'undefined') Graph.focusNode(id);
            });
        });

        // Wire "View Source" buttons
        panelContent.querySelectorAll('.fact-source-btn').forEach(btn => {
            btn.addEventListener('click', () => showSource(btn.dataset.factId, node.name));
        });
    }

    // ── Source conversation overlay ───────────────────────────────────────────
    async function showSource(factId, nodeName) {
        sourceTitle.textContent = `Source — ${nodeName}`;
        sourceBody.innerHTML = `<div class="panel-loading">Fetching conversation…</div>`;
        sourceOverlay.classList.remove('hidden');

        try {
            const data = await API.factSource(factId);
            if (!data.conversations || !data.conversations.length) {
                sourceBody.innerHTML = `<p style="color:var(--text-muted);font-size:0.8rem">No source conversation found.</p>`;
                return;
            }

            sourceBody.innerHTML = data.conversations.map(msg => {
                const ts = msg.timestamp
                    ? new Date(msg.timestamp).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
                    : '';
                return `
          <div class="chat-bubble ${msg.role}">
            <span class="bubble-meta">${msg.role === 'user' ? 'You' : 'AIManager'} · ${esc(ts)}</span>
            <span class="bubble-text">${esc(msg.text)}</span>
          </div>`;
            }).join('');
        } catch (err) {
            sourceBody.innerHTML = `<p style="color:var(--accent2);font-size:0.8rem">Error: ${esc(err.message)}</p>`;
        }
    }

    // ── Util ──────────────────────────────────────────────────────────────────
    function esc(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    return { showLoading, renderNode, labelColor };
})();