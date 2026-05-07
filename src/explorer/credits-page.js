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

    /**
     * headroomColor — colour for a measured headroom value.
     * null = no data (untracked), handled separately upstream.
     */
    function headroomColor(pct) {
        if (pct === null || pct === undefined) return 'var(--fg-dim)';
        if (pct >= 60) return 'var(--c-green)';
        if (pct >= 25) return 'var(--c-yellow)';
        // pct === 0 is exhausted, not "fine" — explicit red
        return 'var(--c-red)';
    }

    /**
     * usedColor — colour for a usage bar (how much is consumed).
     * null = no data, show muted.
     */
    function usedColor(usedPct) {
        if (usedPct === null || usedPct === undefined) return 'var(--fg-muted)';
        if (usedPct <= 40) return 'var(--c-green)';
        if (usedPct <= 75) return 'var(--c-yellow)';
        return 'var(--c-red)';
    }

    /**
     * fmtNum — format a number with K/M suffixes.
     * Explicitly renders 0 as "0", never hides it.
     * null renders as "—".
     */
    function fmtNum(n) {
        if (n === null || n === undefined) return '—';
        if (n === 0) return '0';
        if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
        if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
        return String(n);
    }

    // ── Ring SVG helper ─────────────────────────────────────────────────────

    /**
     * buildRing — renders the circular headroom gauge.
     *
     * null  → grey dashed ring with "N/A" — no live data (untracked model)
     * 0     → full red ring showing "0%" — exhausted
     * 1–100 → normal colour-coded ring
     */
    function buildRing(pct, color) {
        const r = 26;
        const circ = 2 * Math.PI * r;

        // No live data at all — untracked model
        if (pct === null || pct === undefined) {
            return `
                <div class="ring-wrap">
                    <svg viewBox="0 0 64 64">
                        <circle class="ring-track" cx="32" cy="32" r="${r}" stroke-dasharray="4 4"/>
                    </svg>
                    <div class="ring-pct" style="color:var(--fg-dim);font-size:9px">N/A</div>
                </div>`;
        }

        // Clamp to [0, 100], preserve exact 0 (exhausted)
        const safePct = Math.max(0, Math.min(100, pct));
        const offset = circ * (1 - safePct / 100);

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
                <div class="ring-pct" style="color:${color}">${Math.round(safePct)}%</div>
            </div>`;
    }

    // ── Stat row helper ─────────────────────────────────────────────────────

    /**
     * buildStatRow — renders a single RPM / RPD / TPM row.
     *
     * used === null  → "—" with grey bar (no data)
     * used === 0     → "0" with green bar (truly nothing consumed yet)
     * limit === 0    → show limit as "0" not blank
     */
    function buildStatRow(label, used, limit) {
        const hasData = used !== null && used !== undefined;
        const usedPct = (hasData && limit > 0) ? Math.min((used / limit) * 100, 100) : null;
        const color = usedColor(usedPct);

        const usedDisplay = hasData ? fmtNum(used) : '—';
        const limitDisplay = fmtNum(limit);   // limit === 0 shows "0"

        const barWidth = (usedPct !== null) ? `${usedPct.toFixed(1)}%` : '0%';
        const barColor = hasData ? color : 'var(--border-main)';
        const barStyle = hasData
            ? `width:${barWidth}; background:${barColor}`
            : `width:100%; background: repeating-linear-gradient(90deg, var(--border-main) 0px, var(--border-main) 4px, transparent 4px, transparent 8px)`;

        return `
            <div class="stat-row">
                <div class="stat-meta">
                    <span class="stat-label">${label}</span>
                    <span class="stat-value">
                        <span class="used" style="color:${hasData ? color : 'var(--fg-muted)'}">${usedDisplay}</span>
                        <span class="limit"> / ${limitDisplay}</span>
                    </span>
                </div>
                <div class="bar-bg">
                    <div class="bar-fill" style="${barStyle}"></div>
                </div>
            </div>`;
    }

    // ── Capability pills helper ──────────────────────────────────────────────

    /**
     * buildCapabilityPills — renders small scored pills for each task type.
     * Shows all tasks the model is configured for, scored 0.0–1.0.
     */
    function buildCapabilityPills(capabilities) {
        if (!capabilities || Object.keys(capabilities).length === 0) return '';

        const labelMap = {
            QA: 'Q&A',
            REASONING: 'Reasoning',
            EXTRACTION: 'Extraction',
            SUMMARIZATION: 'Summarization',
            CODE: 'Code',
        };

        const sorted = Object.entries(capabilities).sort((a, b) => b[1] - a[1]);

        const pills = sorted.map(([task, score]) => {
            const pct = Math.round(score * 100);
            let scoreColor = 'var(--fg-muted)';
            if (pct >= 80) scoreColor = 'var(--c-green)';
            else if (pct >= 55) scoreColor = 'var(--c-yellow)';
            else if (pct >= 30) scoreColor = 'var(--fg-dim)';

            return `<span class="cap-pill" title="${pct}% ${task}">
                <span class="cap-pill__label">${labelMap[task] || task}</span>
                <span class="cap-pill__score" style="color:${scoreColor}">${pct}%</span>
            </span>`;
        }).join('');

        return `<div class="cap-pills">${pills}</div>`;
    }

    const PROVIDER_COLORS = {
        google: 'var(--c-blue)',
        local: 'var(--c-green)',
    };

    // ── Render functions ────────────────────────────────────────────────────
    function renderSummary(models) {
        const el = document.getElementById('creditsSummaryBanner');
        if (!el) return;

        const totalModels = models.length;
        const trackedModels = models.filter(m => m.headroom !== null).length;
        const untrackedModels = totalModels - trackedModels;

        // Only compute min headroom from models that have live data
        const trackedHeadrooms = models.map(m => m.headroom).filter(h => h !== null);
        const minHeadroom = trackedHeadrooms.length > 0
            ? Math.min(...trackedHeadrooms)
            : null;

        const totalRpdUsed = models.reduce((acc, m) => {
            return acc + (m.rpd.used !== null ? m.rpd.used : 0);
        }, 0);

        const minDisplay = minHeadroom === null
            ? '<span style="color:var(--fg-dim)">—</span>'
            : `<span style="color:${headroomColor(minHeadroom)}">${minHeadroom}%</span>`;

        el.innerHTML = `
            <div class="summary-tile">
                <div class="tile-val">${totalModels}</div>
                <div class="tile-label">Models tracked</div>
            </div>
            <div class="summary-tile">
                <div class="tile-val">${trackedModels}</div>
                <div class="tile-label">Live monitored</div>
            </div>
            <div class="summary-tile">
                <div class="tile-val">${minDisplay}</div>
                <div class="tile-label">Min headroom (live)</div>
            </div>
            <div class="summary-tile">
                <div class="tile-val">${fmtNum(totalRpdUsed)}</div>
                <div class="tile-label">Reqs today (total)</div>
            </div>
            ${untrackedModels > 0 ? `
            <div class="summary-tile summary-tile--muted">
                <div class="tile-val" style="color:var(--fg-dim)">${untrackedModels}</div>
                <div class="tile-label">Limits only (no live data)</div>
            </div>` : ''}`;
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
                (m.group && m.group.toLowerCase().includes(q)) ||
                (m.function && m.function.toLowerCase().includes(q))
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
                const isUntracked = m.headroom === null;

                // Exhausted badge — shown when headroom is exactly 0
                const exhaustedBadge = (m.headroom === 0)
                    ? `<span class="exhausted-badge">EXHAUSTED</span>`
                    : '';

                // Untracked badge — shown when model has no live usage data
                const untrackedBadge = isUntracked
                    ? `<span class="untracked-badge">LIMITS ONLY</span>`
                    : '';

                return `
                    <div class="model-card ${isUntracked ? 'model-card--untracked' : ''}" style="--card-accent: ${accentColor}">
                        <div class="card-head">
                            <div class="card-head__info">
                                <div class="model-name">${m.model}</div>
                                <div class="model-function">
                                    ${m.function || 'General'}
                                    ${exhaustedBadge}
                                    ${untrackedBadge}
                                </div>
                                <div class="model-provider">${m.provider}</div>
                            </div>
                            ${buildRing(m.headroom, hColor)}
                        </div>
                        ${buildCapabilityPills(m.capabilities)}
                        <div class="card-divider"></div>
                        <div class="stat-rows">
                            ${buildStatRow('Req / Min (RPM)', m.rpm.used, m.rpm.limit)}
                            ${buildStatRow('Req / Day (RPD)', m.rpd.used, m.rpd.limit)}
                            ${buildStatRow('Tokens / Min (TPM)', m.tpm.used, m.tpm.limit)}
                        </div>
                        <div class="card-footer">
                            ${isUntracked
                        ? `<span style="color:var(--fg-muted)">No live usage data — limits stored only</span>`
                        : `Headroom: <span style="color:${hColor}; font-weight:600">${m.headroom}%</span>
                                   &nbsp;·&nbsp; Ring = available capacity`
                    }
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
                    // used === 0 must display as "0/N", not be hidden
                    if (used === null || used === undefined) return '<span style="color:var(--fg-muted)">—</span>';
                    if (!limit) return `<span>${fmtNum(used)}</span>`;
                    const pct = Math.round((used / limit) * 100);
                    const color = pct >= 90 ? 'var(--c-red)' : pct >= 60 ? 'var(--c-yellow)' : 'var(--c-green)';
                    // Show "0/N (0%)" explicitly — not hidden
                    return `<span style="color:${color};font-weight:600">${fmtNum(used)}/${fmtNum(limit)}</span><span style="font-size:9px;color:var(--fg-dim)"> (${pct}%)</span>`;
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
                searchInput.placeholder = "Search models, functions, providers...";
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