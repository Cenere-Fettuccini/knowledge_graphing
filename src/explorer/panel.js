/**
 * Detail Panel logic
 */

function getExplorerClient() {
    return window.AIManagerShell?.clients?.explorer || window.AIManagerClients?.explorer;
}

function buildGraphChatContext(node, detail) {
    const connections = detail?.connections || [];
    return {
        source_section: 'explorer',
        context_type: 'graph_node',
        context_id: node.id,
        context_summary: `${node.name} (${node.label})`,
        context_payload: {
            node: {
                id: node.id,
                label: node.label,
                name: node.name,
            },
            details: detail?.node || node,
            connections,
            relation_summary: connections
                .slice(0, 8)
                .map((entry) => `${entry.type} -> ${entry.target}`)
                .join(', '),
        },
    };
}

const Panel = {
    typeSequence: 0,
    appendProvHeader(list, label, color = 'var(--fg-dim)') {
        const header = document.createElement('li');
        header.innerHTML = `<span style="font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:${color}">${label}</span>`;
        header.classList.add('visible');
        list.appendChild(header);
    },

    appendProvEntry(list, html, onClick = null, delay = 100) {
        const li = document.createElement('li');
        li.innerHTML = html;
        if (onClick) {
            li.style.cursor = 'pointer';
            li.addEventListener('click', onClick);
        }
        list.appendChild(li);
        setTimeout(() => li.classList.add('visible'), delay);
    },

    focusProvenanceNode(id) {
        this.loadNode(id);
        if (window.GraphManager) window.GraphManager.focusNode(id);
    },

    init() {
        if (this._initialized) return;
        this.container = document.getElementById('detailPanel');
        this.nodeInfo = document.getElementById('nodeInfo');
        this.nodeConnections = document.getElementById('nodeConnections');
        this.edgeList = document.getElementById('edgeList');
        const backdrop = document.createElement('div');
        backdrop.className = 'module-backdrop';
        document.body.appendChild(backdrop);
        
        let activeMod = null;
        let originalRect = null;
        
        const collapseModule = (mod) => {
            if (!mod) return;
            mod.style.top = originalRect.top + 'px';
            mod.style.left = originalRect.left + 'px';
            mod.style.width = originalRect.width + 'px';
            mod.style.height = originalRect.height + 'px';
            mod.classList.remove('expanded-module');
            backdrop.classList.remove('active');
            
            setTimeout(() => {
                if (!mod.classList.contains('expanded-module')) {
                    mod.style.position = '';
                    mod.style.margin = '';
                    mod.style.top = '';
                    mod.style.left = '';
                    mod.style.width = '';
                    mod.style.height = '';
                    mod.style.zIndex = '';
                    mod.style.transition = '';
                    activeMod = null;
                }
            }, 500);
        };

        const expandModule = (mod) => {
            if (activeMod) return;
            activeMod = mod;
            originalRect = mod.getBoundingClientRect();
            
            mod.style.position = 'fixed';
            mod.style.margin = '0';
            mod.style.top = originalRect.top + 'px';
            mod.style.left = originalRect.left + 'px';
            mod.style.width = originalRect.width + 'px';
            mod.style.height = originalRect.height + 'px';
            mod.style.zIndex = '1000';
            mod.style.transition = 'all 0.5s cubic-bezier(0.25, 1, 0.5, 1)';
            
            mod.classList.add('expanded-module');
            backdrop.classList.add('active');
            
            void mod.offsetWidth; // Force reflow
            
            mod.style.top = '12px';
            mod.style.left = '12px';
            mod.style.width = 'calc(100vw - 24px)';
            mod.style.height = 'calc(100vh - 24px)';
        };

        backdrop.addEventListener('click', () => collapseModule(activeMod));

        document.querySelectorAll('.placeholder-module').forEach(mod => {
            const closeBtn = document.createElement('button');
            closeBtn.className = 'module-close-btn';
            closeBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg> <span>Back</span>`;
            mod.appendChild(closeBtn);

            mod.addEventListener('click', (e) => {
                if (mod.classList.contains('expanded-module')) {
                    if (e.target.closest('.module-close-btn')) collapseModule(mod);
                    return;
                }
                if (e.target.closest('button') || e.target.closest('a')) return;
                expandModule(mod);
            });
        });
        this._initialized = true;
    },

    close() {
        if (this.container) this.container.classList.remove('active');
    },

    async typeWriter(element, html, speed = 8) {
        this.typeSequence++;
        const currentSeq = this.typeSequence;
        element.innerHTML = '';
        const temp = document.createElement('div');
        temp.innerHTML = html;
        
        const typeNode = async (node, parent) => {
            if (currentSeq !== this.typeSequence) return;
            if (node.nodeType === Node.TEXT_NODE) {
                const text = node.textContent;
                for (let i = 0; i < text.length; i++) {
                    if (currentSeq !== this.typeSequence) return;
                    parent.appendChild(document.createTextNode(text.charAt(i)));
                    await new Promise(r => setTimeout(r, speed));
                }
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                const clone = node.cloneNode(false);
                parent.appendChild(clone);
                for (let child of node.childNodes) {
                    if (currentSeq !== this.typeSequence) return;
                    await typeNode(child, clone);
                }
            }
        };
        
        for (let child of temp.childNodes) {
            if (currentSeq !== this.typeSequence) return;
            await typeNode(child, element);
        }
    },

    clear() {
        this.nodeInfo.innerHTML = '<p class="dim">No target selected.</p>';
        this.nodeConnections.style.display = 'none';
        this.edgeList.innerHTML = '';
    },

    async loadNode(nodeId) {
        const provSec = document.getElementById('nodeProvenance');
        const provList = document.getElementById('provenanceList');

        if (this.container && this.container.classList.contains('active')) {
            if (provSec.style.display !== 'none') {
                provSec.classList.add('slide-out');
                await new Promise(r => setTimeout(r, 200));
            }
        } else {
            provSec.classList.add('slide-out');
            if (this.container) this.container.classList.add('active');
        }

        this.nodeInfo.innerHTML = '<p class="dim">Fetching data...</p>';
        const data = await getExplorerClient().getNodeDetail(nodeId);

        if (!data || !data.node) {
            await this.typeWriter(this.nodeInfo, '<p class="dim" style="color:var(--c-red)">ERR: Node not found.</p>');
            return;
        }

        const n = data.node;
        const bgColor = window.ColorManager ? window.ColorManager.getColor(n.label) : 'var(--fg-dim)';

        let html = `
            <div class="node-header">
                <div class="node-label" style="background-color: ${bgColor}">${n.label}</div>
                <div class="node-name">${n.name}</div>
                <div class="node-id">${n.id}</div>
            </div>
        `;
        html += `
            <div style="margin: 10px 0 14px;">
                <button id="talkFromNodeBtn" class="btn btn-ghost" style="padding: 6px 12px;">
                    Open in Chat
                </button>
            </div>
        `;

        if (n.label === 'Belief') {
            const confPct = Math.round((n.confidence || 0) * 100);
            const confColor = confPct >= 70 ? 'var(--c-green, #7FA38D)' : confPct >= 40 ? 'var(--c-yellow, #BEAA7E)' : 'var(--c-red, #A37A87)';
            html += `<p><span class="dim">Status:</span> <span class="highlight">${n.status || 'active'}</span></p>`;
            html += `<p><span class="dim">Confidence:</span> <span style="color:${confColor};font-weight:600">${confPct}%</span></p>`;
            html += `<div style="background:rgba(255,255,255,0.06);border-radius:3px;height:4px;margin:6px 0 2px">
                        <div style="width:${confPct}%;height:100%;background:${confColor};border-radius:3px;transition:width .4s ease"></div>
                      </div>`;
            if (n.content) {
                html += `<p><span class="dim">Claim:</span> ${n.content}</p>`;
            }
        } else if (n.label === 'Entity') {
            html += `<p><span class="dim">Type:</span> <span class="highlight">${n.entity_type || 'Topic'}</span></p>`;
            if (n.description) {
                html += `<p><span class="dim">Description:</span> ${n.description}</p>`;
            }
        } else if (n.label === 'Task') {
            html += `<p><span class="dim">Status:</span> <span class="highlight">${n.status}</span></p>`;
        }

        const connSec = this.nodeConnections;
        const edgeList = this.edgeList;
        edgeList.innerHTML = '';
        if (data.connections && data.connections.length > 0) {
            data.connections.forEach(c => {
                const li = document.createElement('li');
                li.style.cursor = 'pointer';
                const dirIcon = c.direction === 'in' ? '↙' : '↗';
                const labelColor = window.ColorManager ? window.ColorManager.getColor(c.target_label) : 'var(--fg-dim)';
                
                li.innerHTML = `
                    <div style="display:flex; flex-direction:column;">
                        <span style="font-size:13px; font-weight:500;">${c.target}</span>
                        <div style="display:flex; align-items:center; gap:4px; margin-top:2px;">
                            <span style="font-size:8px; color:var(--bg-app); background:${labelColor}; padding:1px 4px; border-radius:4px; font-weight:600; text-transform:uppercase;">${c.target_label}</span>
                            <span style="font-size:9px; color:var(--fg-dim);">${dirIcon} ${c.direction === 'in' ? 'From' : 'To'}</span>
                        </div>
                    </div>
                    <span class="edge-type">${c.type}</span>
                `;

                li.addEventListener('click', () => {
                    this.loadNode(c.id);
                    if (window.GraphManager) window.GraphManager.focusNode(c.id);
                });

                edgeList.appendChild(li);
            });
            connSec.style.display = 'block';
        } else {
            connSec.style.display = 'none';
        }

        await this.typeWriter(this.nodeInfo, html);

        document.getElementById('talkFromNodeBtn')?.addEventListener('click', () => {
            void window.AIManagerShell?.navigateToSection('chat', {
                type: 'chat:open-context',
                payload: buildGraphChatContext(n, data),
            });
        });

        // ── Provenance / Belief Trail ────────────────────────────────────
        provList.innerHTML = '';
        try {
            const provenance = await getExplorerClient().getNodeProvenance(nodeId);
            provSec.style.display = 'block';
            let rendered = false;

            if (provenance?.chain?.length > 1) {
                this.appendProvHeader(provList, 'Evolution Chain');
                provenance.chain.forEach((b, i) => {
                    const statusIcon = b.status === 'active' ? '●' : '○';
                    const statusColor = b.status === 'active' ? 'var(--c-green, #7FA38D)' : 'var(--fg-dim)';
                    this.appendProvEntry(
                        provList,
                        `<span style="color:${statusColor}">${statusIcon}</span> "${b.content}"<br/><span style="opacity:0.5;font-size:9px">${b.status} · conf ${Math.round((b.confidence || 0) * 100)}% · ${b.created_at || ''}</span>`,
                        () => this.focusProvenanceNode(b.id),
                        i * 120 + 100
                    );
                });
                rendered = true;
            }

            if (provenance?.evidence?.supports?.length) {
                this.appendProvHeader(provList, 'Supporting Evidence', 'var(--c-green, #7FA38D)');
                provenance.evidence.supports.forEach((s, i) => {
                    this.appendProvEntry(
                        provList,
                        `"${s.text || s.session_id}"<br/><span style="opacity:0.5;font-size:9px">${s.timestamp || ''}</span>`,
                        null,
                        i * 120 + 220
                    );
                });
                rendered = true;
            }

            if (provenance?.evidence?.weakens?.length) {
                this.appendProvHeader(provList, 'Weakening Evidence', 'var(--c-red, #A37A87)');
                provenance.evidence.weakens.forEach((w, i) => {
                    this.appendProvEntry(
                        provList,
                        `"${w.text || w.session_id}"<br/><span style="opacity:0.5;font-size:9px">${w.timestamp || ''}</span>`,
                        null,
                        i * 120 + 220
                    );
                });
                rendered = true;
            }

            if (provenance?.timeline?.length) {
                this.appendProvHeader(provList, 'Conversation Timeline', 'var(--color-topic)');
                provenance.timeline.forEach((entry, i) => {
                    this.appendProvEntry(
                        provList,
                        `<span class="highlight">${entry.label}</span> "${entry.text || entry.name}"<br/><span style="opacity:0.5;font-size:9px">turn ${entry.sequence || '?'} · ${entry.timestamp || ''}</span>`,
                        () => this.focusProvenanceNode(entry.id),
                        i * 90 + 180
                    );
                });
                rendered = true;
            }

            if (provenance?.incoming?.length) {
                this.appendProvHeader(provList, 'Incoming Links');
                provenance.incoming.forEach((entry, i) => {
                    this.appendProvEntry(
                        provList,
                        `${entry.name} <span class="highlight">(${entry.label})</span><br/><span style="opacity:0.5;font-size:9px">${entry.type}</span>`,
                        () => this.focusProvenanceNode(entry.id),
                        i * 90 + 180
                    );
                });
                rendered = true;
            }

            if (provenance?.outgoing?.length) {
                this.appendProvHeader(provList, 'Outgoing Links');
                provenance.outgoing.forEach((entry, i) => {
                    this.appendProvEntry(
                        provList,
                        `${entry.name} <span class="highlight">(${entry.label})</span><br/><span style="opacity:0.5;font-size:9px">${entry.type}</span>`,
                        () => this.focusProvenanceNode(entry.id),
                        i * 90 + 180
                    );
                });
                rendered = true;
            }

            if (!rendered) {
                this.appendProvEntry(provList, '<span class="dim">No provenance trail yet.</span>');
            }

            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    provSec.classList.remove('slide-out');
                });
            });
            return;
        } catch (e) {
            provSec.style.display = 'block';
            this.appendProvEntry(provList, '<span class="dim">Could not load provenance.</span>');
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    provSec.classList.remove('slide-out');
                });
            });
            return;
        }
        if (n.label === 'Belief') {
            provSec.style.display = 'block';

            try {
                const trail = await getExplorerClient().getBeliefTrail(nodeId);

                // Evolution chain
                if (trail.chain && trail.chain.length > 1) {
                    const header = document.createElement('li');
                    header.innerHTML = `<span style="font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--fg-dim)">Evolution Chain</span>`;
                    header.classList.add('visible');
                    provList.appendChild(header);

                    trail.chain.forEach((b, i) => {
                        const li = document.createElement('li');
                        const statusIcon = b.status === 'active' ? '●' : '○';
                        const statusColor = b.status === 'active' ? 'var(--c-green, #7FA38D)' : 'var(--fg-dim)';
                        li.innerHTML = `
                            <span style="color:${statusColor}">${statusIcon}</span>
                            "${b.content}"
                            <br/><span style="opacity:0.5;font-size:9px">${b.status} · conf ${Math.round((b.confidence || 0) * 100)}% · ${b.created_at || ''}</span>
                        `;
                        li.style.cursor = 'pointer';
                        li.addEventListener('click', () => {
                            this.loadNode(b.id);
                            if (window.GraphManager) window.GraphManager.focusNode(b.id);
                        });
                        provList.appendChild(li);
                        setTimeout(() => li.classList.add('visible'), i * 120 + 100);
                    });
                }

                // Supporting evidence
                if (trail.evidence?.supports?.length) {
                    const header = document.createElement('li');
                    header.innerHTML = `<span style="font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--c-green, #7FA38D)">Supporting Evidence</span>`;
                    header.classList.add('visible');
                    provList.appendChild(header);

                    trail.evidence.supports.forEach((s, i) => {
                        const li = document.createElement('li');
                        li.innerHTML = `"${s.text || s.session_id}" <br/><span style="opacity:0.5;font-size:9px">— ${s.timestamp || ''}</span>`;
                        provList.appendChild(li);
                        setTimeout(() => li.classList.add('visible'), i * 120 + 300);
                    });
                }

                // Weakening evidence
                if (trail.evidence?.weakens?.length) {
                    const header = document.createElement('li');
                    header.innerHTML = `<span style="font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--c-red, #A37A87)">Weakening Evidence</span>`;
                    header.classList.add('visible');
                    provList.appendChild(header);

                    trail.evidence.weakens.forEach((w, i) => {
                        const li = document.createElement('li');
                        li.innerHTML = `"${w.text || w.session_id}" <br/><span style="opacity:0.5;font-size:9px">— ${w.timestamp || ''}</span>`;
                        provList.appendChild(li);
                        setTimeout(() => li.classList.add('visible'), i * 120 + 300);
                    });
                }

                // No evidence at all
                if ((!trail.evidence?.supports?.length) && (!trail.evidence?.weakens?.length) && trail.chain?.length <= 1) {
                    const li = document.createElement('li');
                    li.innerHTML = `<span class="dim">No evidence trail yet.</span>`;
                    li.classList.add('visible');
                    provList.appendChild(li);
                }
            } catch (e) {
                const li = document.createElement('li');
                li.innerHTML = `<span class="dim">Could not load belief trail.</span>`;
                li.classList.add('visible');
                provList.appendChild(li);
            }

            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    provSec.classList.remove('slide-out');
                });
            });
        } else if (n.label === 'Task' || n.label === 'Project') {
            provSec.style.display = 'block';
            const li = document.createElement('li');
            li.innerHTML = `<span class="dim">Provenance tracking available for Belief nodes.</span>`;
            li.classList.add('visible');
            provList.appendChild(li);
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    provSec.classList.remove('slide-out');
                });
            });
        } else {
            provSec.style.display = 'none';
        }
    }
};

// ThemeManager removed — now handled by shared ThemeEngine in app.js

const StatusManager = {
    _prevNeo4j: null,  // Track previous state for transition detection

    init() {
        if (this._initialized) return;
        this.btn = document.getElementById('refreshStatusBtn');
        this.neo4jBadge = document.getElementById('status-neo4j');
        this.chromaBadge = document.getElementById('status-chroma');
        this.agentBadge = document.getElementById('status-agent');
        
        this.btn.addEventListener('click', async () => {
            await Promise.all([
                this.fetchStatus(),
                window.GraphManager?.reload?.()
            ]);
        });
        this._initialized = true;
    },

    start() {
        this.init();
        this.fetchStatus();
        clearInterval(this._timerId);
        this._timerId = setInterval(() => this.fetchStatus(), 30000);
    },

    stop() {
        clearInterval(this._timerId);
        this._timerId = null;
    },
    
    async fetchStatus() {
        // Set to connecting
        this.neo4jBadge.className = 'status-badge connecting';
        this.neo4jBadge.innerText = 'PINGING...';
        this.chromaBadge.className = 'status-badge connecting';
        this.chromaBadge.innerText = 'PINGING...';
        this.agentBadge.className = 'status-badge connecting';
        this.agentBadge.innerText = 'PINGING...';
        
        // Spin the refresh button
        const svg = this.btn.querySelector('svg');
        svg.style.transition = 'transform 0.5s ease';
        svg.style.transform = 'rotate(180deg)';
        
        const data = await getExplorerClient().getSystemStatus();
        
        this.updateBadge(this.neo4jBadge, data.neo4j, data.details?.neo4j);
        this.updateBadge(this.chromaBadge, data.chroma, data.details?.chroma);
        this.updateBadge(this.agentBadge, data.agent, `System Overall: ${data.status}`);
        
        // Auto-reload graph when Neo4j comes back online
        if (this._prevNeo4j && this._prevNeo4j !== 'online' && data.neo4j === 'online') {
            console.log('[StatusManager] Neo4j came online — reloading graph data');
            window.GraphManager?.reload?.();
            TaskManager?.fetchTasks?.();
        }
        this._prevNeo4j = data.neo4j;

        // Render Quota Bars
        const quotaList = document.getElementById('quotaList');
        if (quotaList && data.quota) {
            quotaList.innerHTML = data.quota.map(q => `
                <div class="quota-item">
                    <div class="quota-label">
                        <span>${q.model}</span>
                        <span class="dim">${q.headroom}%</span>
                    </div>
                    <div class="progress-bg">
                        <div class="progress-bar" style="width: ${q.headroom}%"></div>
                    </div>
                </div>
            `).join('');
        }
        
        setTimeout(() => {
            svg.style.transition = 'none';
            svg.style.transform = 'rotate(0deg)';
        }, 500);
    },
    
    updateBadge(element, state, details) {
        element.className = `status-badge ${state}`;
        element.innerText = state.toUpperCase();
        if (details) {
            element.title = details;
        }
    }
};

const TaskManager = {
    init() {
        if (this._initialized) return;
        this.container = document.getElementById('activeTasks');
        this._initialized = true;
    },

    start() {
        this.init();
        this.fetchTasks();
        clearInterval(this._timerId);
        this._timerId = setInterval(() => this.fetchTasks(), 60000);
    },

    stop() {
        clearInterval(this._timerId);
        this._timerId = null;
    },

    async fetchTasks() {
        try {
            const tasks = await getExplorerClient().getActiveTasks();
            this.render(tasks);
        } catch (e) {
            console.error("Failed to fetch tasks", e);
        }
    },

    render(tasks) {
        if (!this.container) return;
        if (!tasks || tasks.length === 0) {
            this.container.innerHTML = '<div class="dim center" style="padding: 20px;">No active tasks.</div>';
            return;
        }

        this.container.innerHTML = tasks.map(t => `
            <div class="task-item">
                <div class="task-info">
                    <span class="task-title">${t.name}</span>
                    <span class="task-meta">${t.priority || 'medium'} · ${t.due_date || 'No date'}</span>
                </div>
                <div class="task-status">${t.status || 'TODO'}</div>
            </div>
        `).join('');
    }
};

window.ExplorerPageController = {
    _active: false,
    activate(shellContext) {
        this._active = true;
        this.shellContext = shellContext;
        Panel.init();
        StatusManager.start();
        TaskManager.start();
        window.GraphManager?.activate?.();
    },

    deactivate() {
        this._active = false;
        StatusManager.stop();
        TaskManager.stop();
        window.GraphManager?.deactivate?.();
    },

    setSearchQuery(query) {
        window.GraphManager?.setSearchQuery?.(query);
    },
};
