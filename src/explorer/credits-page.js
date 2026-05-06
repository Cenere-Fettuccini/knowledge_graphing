/**
 * ═══════════════════════════════════════════════════════════════════════════
 *  Credits Page Module
 * ─────────────────────────────────────────────────────────────────────────
 *  Registers with PageRouter. Manages credit limit data fetching,
 *  model card rendering, sidebar filtering, and the paste import modal.
 * ═══════════════════════════════════════════════════════════════════════════
 */

(function () {

    // ── State ────────────────────────────────────────────────────────────────
    let allModelsCache = [];
    let activeGroup = 'all';
    let searchQuery = '';
    let countdown = 30;
    let timerId = null;
    let _initialized = false;

    // ── Colour helpers ──────────────────────────────────────────────────────
    function headroomColor(pct) {
        if (pct >= 60) return 'var(--c-green)';
        if (pct >= 25) return 'var(--c-yellow)';
        return 'var(--c-red)';
    }

    function usedColor(usedPct) {
        if (usedPct <= 40) return 'var(--c-green)';
        if (usedPct <= 75) return 'var(--c-yellow)';
        return 'var(--c-red)';
    }

    function fmtNum(n) {
        if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
        if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
        return String(n);
    }

    // ── Ring SVG helper ─────────────────────────────────────────────────────
    function buildRing(pct, color) {
        const r = 26;
        const circ = 2 * Math.PI * r;
        const offset = circ * (1 - pct / 100);
        return `
            <div class="ring-wrap">
                <svg viewBox="0 0 64 64">
                    <circle class="ring-track" cx="32" cy="32" r="${r}"/>
                    <circle class="ring-fill"
                        cx="32" cy="32" r="${r}"
                        stroke="${color}"
                        stroke-dasharray="${circ.toFixed(1)}"
                        stroke-dashoffset="${offset.toFixed(1)}"
                        style="transition: stroke-dashoffset 0.8s cubic-bezier(0.16,1,0.3,1)"
                    />
                </svg>
                <div class="ring-pct">${Math.round(pct)}%</div>
            </div>`;
    }

    // ── Stat row helper ─────────────────────────────────────────────────────
    function buildStatRow(label, used, limit) {
        const usedPct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
        const color = usedColor(usedPct);
        return `
            <div class="stat-row">
                <div class="stat-meta">
                    <span class="stat-label">${label}</span>
                    <span class="stat-value">
                        <span class="used" style="color:${color}">${fmtNum(used)}</span>
                        <span class="limit"> / ${fmtNum(limit)}</span>
                    </span>
                </div>
                <div class="bar-bg">
                    <div class="bar-fill" style="width:${usedPct.toFixed(1)}%; background:${color}"></div>
                </div>
            </div>`;
    }

    const PROVIDER_COLORS = {
        google: 'var(--c-blue)',
        local:  'var(--c-green)',
    };

    // ── Render functions ────────────────────────────────────────────────────
    function renderSummary(models) {
        const el = document.getElementById('creditsSummaryBanner');
        if (!el) return;
        const totalModels = models.length;
        const cloudModels = models.filter(m => m.provider !== 'local').length;
        const minHeadroom = Math.min(...models.map(m => m.headroom));
        const totalRpdUsed = models.reduce((acc, m) => acc + m.rpd.used, 0);

        el.innerHTML = `
            <div class="summary-tile">
                <div class="tile-val">${totalModels}</div>
                <div class="tile-label">Models tracked</div>
            </div>
            <div class="summary-tile">
                <div class="tile-val">${cloudModels}</div>
                <div class="tile-label">Cloud APIs</div>
            </div>
            <div class="summary-tile">
                <div class="tile-val" style="color:${headroomColor(minHeadroom)}">${minHeadroom}%</div>
                <div class="tile-label">Min headroom</div>
            </div>
            <div class="summary-tile">
                <div class="tile-val">${fmtNum(totalRpdUsed)}</div>
                <div class="tile-label">Reqs today (total)</div>
            </div>`;
    }

    function renderSidebar(models) {
        const dynamicGroups = document.getElementById('creditsDynamicGroups');
        if (!dynamicGroups) return;
        const uniqueGroups = [...new Set(models.map(m => m.group))].sort();

        const allItem = document.querySelector('#page-credits .sidebar-item[data-group="all"]');
        if (allItem) allItem.classList.toggle('active', activeGroup === 'all');

        dynamicGroups.innerHTML = uniqueGroups.map(g => `
            <div class="sidebar-item ${activeGroup === g ? 'active' : ''}" data-group="${g}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 15.5"></path>
                </svg>
                ${g}
            </div>
        `).join('');

        // Attach listeners to ALL sidebar items
        document.querySelectorAll('#page-credits .sidebar-item').forEach(item => {
            item.onclick = () => {
                document.querySelectorAll('#page-credits .sidebar-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                activeGroup = item.getAttribute('data-group');
                renderCards(allModelsCache);
            };
        });
    }

    function renderCards(models) {
        const container = document.getElementById('creditsCardsContainer');
        if (!container) return;

        if (!models || models.length === 0) {
            container.innerHTML = `<div class="state-msg"><p>No model data available.</p></div>`;
            return;
        }

        let filteredModels = activeGroup === 'all'
            ? models
            : models.filter(m => m.group === activeGroup);

        if (searchQuery) {
            const q = searchQuery.toLowerCase();
            filteredModels = filteredModels.filter(m => 
                (m.model && m.model.toLowerCase().includes(q)) || 
                (m.provider && m.provider.toLowerCase().includes(q)) ||
                (m.group && m.group.toLowerCase().includes(q))
            );
        }

        const groups = {};
        for (const m of filteredModels) {
            const g = m.group || 'Other Models';
            if (!groups[g]) groups[g] = [];
            groups[g].push(m);
        }

        let html = '';
        for (const [groupName, groupModels] of Object.entries(groups)) {
            html += `<div class="section-label" style="margin-top: 32px; border-bottom: 1px solid var(--border-main); padding-bottom: 6px; margin-bottom: 16px;">${groupName}</div>`;
            html += `<div class="cards-grid">`;

            html += groupModels.map(m => {
                const accentColor = PROVIDER_COLORS[m.provider] || 'var(--c-green)';
                const hColor = headroomColor(m.headroom);
                return `
                    <div class="model-card" style="--card-accent: ${accentColor}">
                        <div class="card-head">
                            <div>
                                <div class="model-name">${m.model}</div>
                                <div class="model-provider">${m.provider}</div>
                            </div>
                            ${buildRing(m.headroom, hColor)}
                        </div>
                        <div class="card-divider"></div>
                        <div class="stat-rows">
                            ${buildStatRow('Req / Min (RPM)', m.rpm.used, m.rpm.limit)}
                            ${buildStatRow('Req / Day (RPD)', m.rpd.used, m.rpd.limit)}
                            ${buildStatRow('Tokens / Min (TPM)', m.tpm.used, m.tpm.limit)}
                        </div>
                        <div style="margin-top:12px; font-size:10px; color:var(--fg-dim);">
                            Headroom: <span style="color:${hColor}; font-weight:600">${m.headroom}%</span>
                            &nbsp;·&nbsp; Ring = available capacity
                        </div>
                    </div>`;
            }).join('');

            html += `</div>`;
        }
        container.innerHTML = html;
    }

    // ── Fetch & Auto-Refresh ────────────────────────────────────────────────
    function updateCountdownLabel() {
        const el = document.getElementById('creditsNextRefreshLabel');
        if (el) el.textContent = countdown > 0 ? `Refreshes in ${countdown}s` : 'Refreshing...';
    }

    async function fetchCredits() {
        clearInterval(timerId);
        countdown = 0;
        updateCountdownLabel();

        const refreshSvg = document.querySelector('#creditsRefreshBtn svg');
        if (refreshSvg) {
            refreshSvg.style.transition = 'transform 0.5s ease';
            refreshSvg.style.transform = 'rotate(180deg)';
        }

        try {
            const res = await fetch('/api/credits');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            const ts = new Date(data.timestamp * 1000);
            const tsLabel = document.getElementById('creditsTsLabel');
            if (tsLabel) tsLabel.textContent = `Last updated: ${ts.toLocaleTimeString()}`;

            allModelsCache = data.models;
            renderSidebar(data.models);
            renderSummary(data.models);
            renderCards(data.models);
        } catch (err) {
            console.error('[Credits] fetch failed', err);
            const tsLabel = document.getElementById('creditsTsLabel');
            if (tsLabel) tsLabel.textContent = 'Failed to fetch — is the backend running?';
            const container = document.getElementById('creditsCardsContainer');
            if (container) {
                container.innerHTML = `
                    <div class="section-label" style="margin-top: 18px;">Error</div>
                    <div class="cards-grid">
                        <div class="state-msg" style="grid-column:1/-1">
                            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                            </svg>
                            <p>Could not connect to backend.<br/>
                               <span style="font-size:11px;opacity:.6">${err.message}</span>
                            </p>
                        </div>
                    </div>`;
            }
        } finally {
            if (refreshSvg) {
                setTimeout(() => {
                    refreshSvg.style.transition = 'none';
                    refreshSvg.style.transform = 'rotate(0deg)';
                }, 500);
            }
            countdown = 30;
            timerId = setInterval(() => {
                countdown--;
                updateCountdownLabel();
                if (countdown <= 0) fetchCredits();
            }, 1000);
        }
    }

    // ── Mismatch Log ────────────────────────────────────────────────────────
    async function fetchMismatches() {
        try {
            const res = await fetch('/api/credits/mismatches');
            const data = await res.json();
            const el = document.getElementById('creditsMismatchList');
            if (!el) return;
            if (!data.events || data.events.length === 0) {
                el.innerHTML = '<p class="dim" style="font-size:12px;color:var(--fg-dim)">No rate limit events recorded yet. 429 errors will appear here automatically.</p>';
                return;
            }
            el.innerHTML = [...data.events].reverse().map(ev => {
                const ts = new Date(ev.timestamp * 1000).toLocaleString();
                const mid = ev.model_id.split('/').pop();
                const u = ev.usage_at_hit;
                const s = ev.stored_limits;
                const ov = ev.override_limits || {};

                const flag = (used, stored, override) => {
                    const limit = override ?? stored;
                    if (!limit) return '';
                    const pct = Math.round((used / limit) * 100);
                    const color = pct >= 90 ? 'var(--c-red)' : pct >= 60 ? 'var(--c-yellow)' : 'var(--c-green)';
                    return `<span style="color:${color};font-weight:600">${used}/${limit}</span><span style="font-size:9px;color:var(--fg-dim)"> (${pct}%)</span>`;
                };
                return `
                <div class="mismatch-card">
                    <div class="mismatch-head">
                        <span class="mismatch-model">${mid}</span>
                        <span class="mismatch-time">${ts}</span>
                    </div>
                    <div class="mismatch-grid">
                        <div class="mismatch-stat"><span class="dim">RPM at hit</span>${flag(u.rpm, s.rpm, ov.rpm)}</div>
                        <div class="mismatch-stat"><span class="dim">TPM at hit</span>${flag(u.tpm, s.tpm, ov.tpm)}</div>
                        <div class="mismatch-stat"><span class="dim">RPD at hit</span>${flag(u.rpd, s.rpd, ov.rpd)}</div>
                    </div>
                </div>`;
            }).join('');
        } catch (e) { console.warn('[Mismatches] fetch failed', e); }
    }

    // ── Modal wiring ────────────────────────────────────────────────────────
    function wireModal() {
        const pasteModal = document.getElementById('creditsPasteModal');
        if (!pasteModal) return;

        document.getElementById('creditsOpenPasteBtn')?.addEventListener('click', () => {
            pasteModal.classList.add('open');
            const inp = document.getElementById('creditsPasteInput');
            const stat = document.getElementById('creditsImportStatus');
            if (stat) stat.textContent = '';
            if (inp) { inp.value = ''; setTimeout(() => inp.focus(), 100); }
        });

        document.getElementById('creditsClosePasteBtn')?.addEventListener('click', () => pasteModal.classList.remove('open'));
        pasteModal.addEventListener('click', e => { if (e.target === pasteModal) pasteModal.classList.remove('open'); });

        document.getElementById('creditsSubmitPasteBtn')?.addEventListener('click', async () => {
            const text = document.getElementById('creditsPasteInput')?.value.trim();
            const statusEl = document.getElementById('creditsImportStatus');
            if (!text) { if (statusEl) { statusEl.textContent = 'Paste some text first.'; statusEl.className = 'import-status err'; } return; }
            if (statusEl) { statusEl.textContent = 'Parsing...'; statusEl.className = 'import-status'; }
            try {
                const res = await fetch('/api/credits/limits/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text })
                });
                const data = await res.json();
                if (data.ok) {
                    if (statusEl) {
                        statusEl.textContent = `✓ Imported ${data.matched.length} models: ${data.matched.slice(0, 5).join(', ')}${data.matched.length > 5 ? '…' : ''}`;
                        statusEl.className = 'import-status ok';
                    }
                    setTimeout(() => { pasteModal.classList.remove('open'); fetchCredits(); }, 1800);
                } else {
                    if (statusEl) { statusEl.textContent = `Error: ${data.error}`; statusEl.className = 'import-status err'; }
                }
            } catch (e) {
                if (statusEl) { statusEl.textContent = `Request failed: ${e.message}`; statusEl.className = 'import-status err'; }
            }
        });
    }

    // ── Page Lifecycle ──────────────────────────────────────────────────────
    PageRouter.register({
        id: 'credits',
        label: 'Credit Limits',
        init() {
            if (!_initialized) {
                wireModal();
                document.getElementById('creditsRefreshBtn')?.addEventListener('click', () => {
                    fetchCredits();
                    fetchMismatches();
                });
                
                document.getElementById('searchInput')?.addEventListener('input', e => {
                    if (PageRouter.getActive() === 'credits') {
                        searchQuery = e.target.value;
                        renderCards(allModelsCache);
                    }
                });

                _initialized = true;
            }
            
            const searchInput = document.getElementById('searchInput');
            if (searchInput) {
                searchInput.placeholder = "Search models, providers, limits...";
                searchInput.value = searchQuery;
            }

            const topStats = document.getElementById('topStats');
            if (topStats) topStats.style.display = 'none';

            fetchCredits();
            fetchMismatches();
        },
        destroy() {
            clearInterval(timerId);
            timerId = null;
        }
    });

})();
