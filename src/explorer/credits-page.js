(function () {
    const state = {
        allModels: [],
        activeGroup: 'all',
        searchQuery: '',
        countdown: 30,
        timerId: null,
        initialized: false,
    };

    function creditsClient() {
        return window.AIManagerShell?.clients?.credits || window.AIManagerClients?.credits;
    }

    function headroomColor(pct) {
        if (pct === null || pct === undefined) return 'var(--fg-dim)';
        if (pct >= 60) return 'var(--c-green)';
        if (pct >= 25) return 'var(--c-yellow)';
        return 'var(--c-red)';
    }

    function usedColor(usedPct) {
        if (usedPct === null || usedPct === undefined) return 'var(--fg-muted)';
        if (usedPct <= 40) return 'var(--c-green)';
        if (usedPct <= 75) return 'var(--c-yellow)';
        return 'var(--c-red)';
    }

    function fmtNum(n) {
        if (n === null || n === undefined) return '—';
        if (n === 0) return '0';
        if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
        if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
        return String(n);
    }

    function buildRing(pct, color) {
        const radius = 26;
        const circumference = 2 * Math.PI * radius;
        if (pct === null || pct === undefined) {
            return `
                <div class="ring-wrap">
                    <svg viewBox="0 0 64 64">
                        <circle class="ring-track" cx="32" cy="32" r="${radius}" stroke-dasharray="4 4"/>
                    </svg>
                    <div class="ring-pct" style="color:var(--fg-dim);font-size:9px">N/A</div>
                </div>`;
        }

        const safePct = Math.max(0, Math.min(100, pct));
        const offset = circumference * (1 - safePct / 100);
        return `
            <div class="ring-wrap">
                <svg viewBox="0 0 64 64">
                    <circle class="ring-track" cx="32" cy="32" r="${radius}"/>
                    <circle class="ring-fill"
                        cx="32" cy="32" r="${radius}"
                        stroke="${color}"
                        stroke-dasharray="${circumference.toFixed(1)}"
                        stroke-dashoffset="${offset.toFixed(1)}"
                        style="transition: stroke-dashoffset 0.8s cubic-bezier(0.16,1,0.3,1)"
                    />
                </svg>
                <div class="ring-pct" style="color:${color}">${Math.round(safePct)}%</div>
            </div>`;
    }

    function buildStatRow(label, used, limit) {
        const hasData = used !== null && used !== undefined;
        const usedPct = hasData && limit > 0 ? Math.min((used / limit) * 100, 100) : null;
        const color = usedColor(usedPct);
        const barStyle = hasData
            ? `width:${usedPct.toFixed(1)}%; background:${color}`
            : 'width:100%; background: repeating-linear-gradient(90deg, var(--border-main) 0px, var(--border-main) 4px, transparent 4px, transparent 8px)';

        return `
            <div class="stat-row">
                <div class="stat-meta">
                    <span class="stat-label">${label}</span>
                    <span class="stat-value">
                        <span class="used" style="color:${hasData ? color : 'var(--fg-muted)'}">${hasData ? fmtNum(used) : '—'}</span>
                        <span class="limit"> / ${fmtNum(limit)}</span>
                    </span>
                </div>
                <div class="bar-bg">
                    <div class="bar-fill" style="${barStyle}"></div>
                </div>
            </div>`;
    }

    function buildCapabilityPills(capabilities) {
        if (!capabilities || Object.keys(capabilities).length === 0) return '';
        const labelMap = {
            QA: 'Q&A',
            REASONING: 'Reasoning',
            EXTRACTION: 'Extraction',
            SUMMARIZATION: 'Summarization',
            CODE: 'Code',
        };
        return `<div class="cap-pills">${Object.entries(capabilities)
            .sort((a, b) => b[1] - a[1])
            .map(([task, score]) => {
                const pct = Math.round(score * 100);
                let scoreColor = 'var(--fg-muted)';
                if (pct >= 80) scoreColor = 'var(--c-green)';
                else if (pct >= 55) scoreColor = 'var(--c-yellow)';
                else if (pct >= 30) scoreColor = 'var(--fg-dim)';
                return `<span class="cap-pill" title="${pct}% ${task}">
                    <span class="cap-pill__label">${labelMap[task] || task}</span>
                    <span class="cap-pill__score" style="color:${scoreColor}">${pct}%</span>
                </span>`;
            })
            .join('')}</div>`;
    }

    function renderSummary(models) {
        const el = document.getElementById('creditsSummaryBanner');
        if (!el) return;
        const trackedHeadrooms = models.map((model) => model.headroom).filter((value) => value !== null);
        const minHeadroom = trackedHeadrooms.length > 0 ? Math.min(...trackedHeadrooms) : null;
        const trackedModels = models.filter((model) => model.headroom !== null).length;
        const untrackedModels = models.length - trackedModels;
        const totalRpdUsed = models.reduce((total, model) => total + (model.rpd.used || 0), 0);

        el.innerHTML = `
            <div class="summary-tile">
                <div class="tile-val">${models.length}</div>
                <div class="tile-label">Models tracked</div>
            </div>
            <div class="summary-tile">
                <div class="tile-val">${trackedModels}</div>
                <div class="tile-label">Live monitored</div>
            </div>
            <div class="summary-tile">
                <div class="tile-val">${minHeadroom === null ? '<span style="color:var(--fg-dim)">—</span>' : `<span style="color:${headroomColor(minHeadroom)}">${minHeadroom}%</span>`}</div>
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
                </div>` : ''}
        `;
    }

    function renderSidebar(models) {
        const dynamicGroups = document.getElementById('creditsDynamicGroups');
        if (!dynamicGroups) return;

        const allItem = document.querySelector('#page-credits .sidebar-item[data-group="all"]');
        allItem?.classList.toggle('active', state.activeGroup === 'all');

        dynamicGroups.innerHTML = [...new Set(models.map((model) => model.group))]
            .sort()
            .map((group) => `
                <div class="sidebar-item ${state.activeGroup === group ? 'active' : ''}" data-group="${group}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 15.5"></path>
                    </svg>
                    ${group}
                </div>
            `)
            .join('');

        document.querySelectorAll('#page-credits .sidebar-item').forEach((item) => {
            item.onclick = () => {
                document.querySelectorAll('#page-credits .sidebar-item').forEach((node) => node.classList.remove('active'));
                item.classList.add('active');
                state.activeGroup = item.getAttribute('data-group');
                renderCards(state.allModels);
            };
        });
    }

    function renderCards(models) {
        const container = document.getElementById('creditsCardsContainer');
        if (!container) return;
        if (!models || models.length === 0) {
            container.innerHTML = '<div class="state-msg"><p>No model data available.</p></div>';
            return;
        }

        let filtered = state.activeGroup === 'all'
            ? models
            : models.filter((model) => model.group === state.activeGroup);

        if (state.searchQuery) {
            const query = state.searchQuery.toLowerCase();
            filtered = filtered.filter((model) =>
                (model.model && model.model.toLowerCase().includes(query))
                || (model.provider && model.provider.toLowerCase().includes(query))
                || (model.group && model.group.toLowerCase().includes(query))
                || (model.function && model.function.toLowerCase().includes(query))
            );
        }

        const groups = filtered.reduce((acc, model) => {
            const key = model.group || 'Other Models';
            acc[key] = acc[key] || [];
            acc[key].push(model);
            return acc;
        }, {});

        const providerColors = {
            google: 'var(--c-blue)',
            local: 'var(--c-green)',
        };

        container.innerHTML = Object.entries(groups).map(([groupName, groupModels]) => `
            <div class="section-label" style="margin-top: 32px; border-bottom: 1px solid var(--border-main); padding-bottom: 6px; margin-bottom: 16px;">${groupName}</div>
            <div class="cards-grid">
                ${groupModels.map((model) => {
                    const accentColor = providerColors[model.provider] || 'var(--c-green)';
                    const hColor = headroomColor(model.headroom);
                    const isUntracked = model.headroom === null;
                    const exhaustedBadge = model.headroom === 0 ? '<span class="exhausted-badge">EXHAUSTED</span>' : '';
                    const untrackedBadge = isUntracked ? '<span class="untracked-badge">LIMITS ONLY</span>' : '';
                    return `
                        <div class="model-card ${isUntracked ? 'model-card--untracked' : ''}" style="--card-accent: ${accentColor}">
                            <div class="card-head">
                                <div class="card-head__info">
                                    <div class="model-name">${model.model}</div>
                                    <div class="model-function">${model.function || 'General'} ${exhaustedBadge} ${untrackedBadge}</div>
                                    <div class="model-provider">${model.provider}</div>
                                </div>
                                ${buildRing(model.headroom, hColor)}
                            </div>
                            ${buildCapabilityPills(model.capabilities)}
                            <div class="card-divider"></div>
                            <div class="stat-rows">
                                ${buildStatRow('Req / Min (RPM)', model.rpm.used, model.rpm.limit)}
                                ${buildStatRow('Req / Day (RPD)', model.rpd.used, model.rpd.limit)}
                                ${buildStatRow('Tokens / Min (TPM)', model.tpm.used, model.tpm.limit)}
                            </div>
                            <div class="card-footer">
                                ${isUntracked
                                    ? '<span style="color:var(--fg-muted)">No live usage data — limits stored only</span>'
                                    : `Headroom: <span style="color:${hColor}; font-weight:600">${model.headroom}%</span> &nbsp;·&nbsp; Ring = available capacity`}
                            </div>
                        </div>`;
                }).join('')}
            </div>
        `).join('');
    }

    function updateCountdownLabel() {
        const el = document.getElementById('creditsNextRefreshLabel');
        if (el) el.textContent = state.countdown > 0 ? `Refreshes in ${state.countdown}s` : 'Refreshing...';
    }

    async function fetchCredits() {
        clearInterval(state.timerId);
        state.countdown = 0;
        updateCountdownLabel();

        const refreshSvg = document.querySelector('#creditsRefreshBtn svg');
        if (refreshSvg) {
            refreshSvg.style.transition = 'transform 0.5s ease';
            refreshSvg.style.transform = 'rotate(180deg)';
        }

        try {
            const data = await creditsClient().getCredits();
            const ts = new Date(data.timestamp * 1000);
            const tsLabel = document.getElementById('creditsTsLabel');
            if (tsLabel) tsLabel.textContent = `Last updated: ${ts.toLocaleTimeString()}`;
            state.allModels = data.models || [];
            renderSidebar(state.allModels);
            renderSummary(state.allModels);
            renderCards(state.allModels);
        } catch (error) {
            console.error('[Credits] fetch failed', error);
            const tsLabel = document.getElementById('creditsTsLabel');
            if (tsLabel) tsLabel.textContent = 'Failed to fetch — is the backend running?';
            const container = document.getElementById('creditsCardsContainer');
            if (container) {
                container.innerHTML = `
                    <div class="section-label" style="margin-top: 18px;">Error</div>
                    <div class="cards-grid">
                        <div class="state-msg" style="grid-column:1/-1">
                            <p>Could not connect to backend.<br/><span style="font-size:11px;opacity:.6">${error.message}</span></p>
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
            state.countdown = 30;
            state.timerId = setInterval(() => {
                state.countdown -= 1;
                updateCountdownLabel();
                if (state.countdown <= 0) void fetchCredits();
            }, 1000);
        }
    }

    async function fetchMismatches() {
        try {
            const data = await creditsClient().getMismatches();
            const el = document.getElementById('creditsMismatchList');
            if (!el) return;
            if (!data.events || data.events.length === 0) {
                el.innerHTML = '<p class="dim" style="font-size:12px;color:var(--fg-dim)">No rate limit events recorded yet. 429 errors will appear here automatically.</p>';
                return;
            }
            el.innerHTML = [...data.events].reverse().map((event) => {
                const ts = new Date(event.timestamp * 1000).toLocaleString();
                const modelId = event.model_id.split('/').pop();
                const usage = event.usage_at_hit;
                const stored = event.stored_limits;
                const override = event.override_limits || {};

                const renderFlag = (used, storedLimit, overrideLimit) => {
                    const limit = overrideLimit ?? storedLimit;
                    if (used === null || used === undefined) return '<span style="color:var(--fg-muted)">—</span>';
                    if (!limit) return `<span>${fmtNum(used)}</span>`;
                    const pct = Math.round((used / limit) * 100);
                    const color = pct >= 90 ? 'var(--c-red)' : pct >= 60 ? 'var(--c-yellow)' : 'var(--c-green)';
                    return `<span style="color:${color};font-weight:600">${fmtNum(used)}/${fmtNum(limit)}</span><span style="font-size:9px;color:var(--fg-dim)"> (${pct}%)</span>`;
                };

                return `
                    <div class="mismatch-card">
                        <div class="mismatch-head">
                            <span class="mismatch-model">${modelId}</span>
                            <span class="mismatch-time">${ts}</span>
                        </div>
                        <div class="mismatch-grid">
                            <div class="mismatch-stat"><span class="dim">RPM at hit</span>${renderFlag(usage.rpm, stored.rpm, override.rpm)}</div>
                            <div class="mismatch-stat"><span class="dim">TPM at hit</span>${renderFlag(usage.tpm, stored.tpm, override.tpm)}</div>
                            <div class="mismatch-stat"><span class="dim">RPD at hit</span>${renderFlag(usage.rpd, stored.rpd, override.rpd)}</div>
                        </div>
                    </div>`;
            }).join('');
        } catch (error) {
            console.warn('[Mismatches] fetch failed', error);
        }
    }

    function wireModal() {
        const pasteModal = document.getElementById('creditsPasteModal');
        if (!pasteModal) return;

        document.getElementById('creditsOpenPasteBtn')?.addEventListener('click', () => {
            pasteModal.classList.add('open');
            const input = document.getElementById('creditsPasteInput');
            const status = document.getElementById('creditsImportStatus');
            if (status) status.textContent = '';
            if (input) {
                input.value = '';
                setTimeout(() => input.focus(), 100);
            }
        });

        document.getElementById('creditsClosePasteBtn')?.addEventListener('click', () => pasteModal.classList.remove('open'));
        pasteModal.addEventListener('click', (event) => {
            if (event.target === pasteModal) pasteModal.classList.remove('open');
        });

        document.getElementById('creditsSubmitPasteBtn')?.addEventListener('click', async () => {
            const text = document.getElementById('creditsPasteInput')?.value.trim();
            const statusEl = document.getElementById('creditsImportStatus');
            if (!text) {
                if (statusEl) {
                    statusEl.textContent = 'Paste some text first.';
                    statusEl.className = 'import-status err';
                }
                return;
            }

            if (statusEl) {
                statusEl.textContent = 'Parsing...';
                statusEl.className = 'import-status';
            }

            try {
                const data = await creditsClient().importLimits(text);
                if (data.ok) {
                    if (statusEl) {
                        statusEl.textContent = `Imported ${data.matched.length} models: ${data.matched.slice(0, 5).join(', ')}${data.matched.length > 5 ? '…' : ''}`;
                        statusEl.className = 'import-status ok';
                    }
                    setTimeout(() => {
                        pasteModal.classList.remove('open');
                        void fetchCredits();
                    }, 1800);
                } else if (statusEl) {
                    statusEl.textContent = `Error: ${data.error}`;
                    statusEl.className = 'import-status err';
                }
            } catch (error) {
                if (statusEl) {
                    statusEl.textContent = `Request failed: ${error.message}`;
                    statusEl.className = 'import-status err';
                }
            }
        });
    }

    PageRouter.register({
        id: 'credits',
        label: 'Credit Limits',
        role: 'cross_cutting',
        paths: ['/credits', '/apps/credits'],
        mount(_root, shellContext) {
            if (!state.initialized) {
                wireModal();
                document.getElementById('creditsRefreshBtn')?.addEventListener('click', () => {
                    void fetchCredits();
                    void fetchMismatches();
                });
                state.initialized = true;
            }

            shellContext.setSearchPlaceholder('Search models, functions, providers...');
            shellContext.setSearchValue(state.searchQuery);
            shellContext.setTopStats('', false);

            void fetchCredits();
            void fetchMismatches();
        },
        unmount() {
            clearInterval(state.timerId);
            state.timerId = null;
        },
        onSearch(query) {
            state.searchQuery = query;
            renderCards(state.allModels);
        },
    });
})();
