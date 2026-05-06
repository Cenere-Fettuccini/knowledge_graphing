(function () {
    const ANCHOR_STORAGE_KEY = 'aimanager_chat_anchor';

    const state = {
        initialized: false,
        sessions: [],
        activeSessionId: null,
        activeSessionTitle: '',
        messages: [],
        searchQuery: '',
        anchor: null,
        sending: false,
    };

    function fmtDate(iso) {
        if (!iso) return 'No timestamp';
        try {
            return new Date(iso).toLocaleString();
        } catch (_) {
            return iso;
        }
    }

    function sessionTitle(session) {
        const preview = (session.preview || '').trim();
        if (!preview) return session.session_id;
        return preview.length > 44 ? `${preview.slice(0, 44)}...` : preview;
    }

    function autoResize(el) {
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
    }

    function setStatus(text) {
        const el = document.getElementById('chatSessionStatus');
        if (el) el.textContent = text;
    }

    function persistAnchor(anchor) {
        if (!anchor) {
            sessionStorage.removeItem(ANCHOR_STORAGE_KEY);
            return;
        }
        sessionStorage.setItem(ANCHOR_STORAGE_KEY, JSON.stringify(anchor));
    }

    function loadPersistedAnchor() {
        try {
            const raw = sessionStorage.getItem(ANCHOR_STORAGE_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (_) {
            return null;
        }
    }

    function renderAnchor() {
        const box = document.getElementById('chatAnchorBox');
        const title = document.getElementById('chatAnchorTitle');
        const subtitle = document.getElementById('chatAnchorSubtitle');
        if (!box || !title || !subtitle) return;

        if (!state.anchor) {
            box.hidden = true;
            return;
        }

        title.textContent = state.anchor.name || state.anchor.id;
        subtitle.textContent = `${state.anchor.label || 'Node'}${state.anchor.id ? ` · ${state.anchor.id}` : ''}`;
        box.hidden = false;
    }

    function renderSessions() {
        const list = document.getElementById('chatSessionList');
        const count = document.getElementById('chatSessionCount');
        if (!list) return;

        const filtered = state.sessions.filter(session => {
            if (!state.searchQuery) return true;
            const haystack = `${session.session_id} ${session.preview || ''}`.toLowerCase();
            return haystack.includes(state.searchQuery.toLowerCase());
        });

        if (count) {
            count.textContent = `${filtered.length} session${filtered.length === 1 ? '' : 's'}`;
        }

        if (filtered.length === 0) {
            list.innerHTML = '<div class="chat-empty-state">No conversations match the current search.</div>';
            return;
        }

        list.innerHTML = filtered.map(session => `
            <div class="chat-session-item ${session.session_id === state.activeSessionId ? 'active' : ''}" data-session-id="${session.session_id}">
                <div class="chat-session-item__title">${sessionTitle(session)}</div>
                <div class="chat-session-item__preview">${session.preview || 'No preview yet.'}</div>
                <div class="chat-session-item__meta">
                    <span>${session.turn_count || 0} turns</span>
                    <span>${fmtDate(session.last_timestamp)}</span>
                </div>
            </div>
        `).join('');

        list.querySelectorAll('.chat-session-item').forEach(item => {
            item.addEventListener('click', () => {
                const sessionId = item.getAttribute('data-session-id');
                if (sessionId) {
                    void selectSession(sessionId);
                }
            });
        });
    }

    function renderMessages() {
        const thread = document.getElementById('chatThread');
        const title = document.getElementById('chatSessionTitle');
        if (!thread || !title) return;

        title.textContent = state.activeSessionTitle || 'New conversation';

        if (!state.messages.length) {
            thread.innerHTML = `
                <div class="chat-empty-state">
                    ${state.anchor
                    ? 'This chat is anchored to a graph node. Ask the assistant to analyze or elaborate from here.'
                    : 'Start a chat, or jump here from a graph node to talk from that point.'}
                </div>
            `;
            return;
        }

        thread.innerHTML = state.messages.map(message => `
            <div class="chat-message ${message.role}">
                <div class="chat-message__meta">${message.role === 'user' ? 'You' : 'AIManager'} · ${fmtDate(message.timestamp)}</div>
                <div class="chat-message__bubble">${escapeHtml(message.text)}</div>
            </div>
        `).join('');

        thread.scrollTop = thread.scrollHeight;
    }

    function appendMessage(role, text, timestamp = new Date().toISOString()) {
        state.messages.push({ role, text, timestamp });
        renderMessages();
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    async function refreshSessions() {
        const payload = await API.getChatSessions();
        state.sessions = payload.sessions || [];
        renderSessions();
    }

    async function selectSession(sessionId) {
        state.activeSessionId = sessionId;
        state.activeSessionTitle = sessionId;
        renderSessions();
        setStatus('Loading conversation...');

        const payload = await API.getChatSession(sessionId);
        state.messages = payload.messages || [];
        const sessionMeta = state.sessions.find(s => s.session_id === sessionId);
        state.activeSessionTitle = sessionMeta ? sessionTitle(sessionMeta) : sessionId;
        renderMessages();
        renderSessions();
        setStatus(`Session ${sessionId} · ${state.messages.length} messages loaded`);
    }

    async function ensureSession() {
        if (state.activeSessionId) return state.activeSessionId;
        const payload = await API.createChatSession('web');
        state.activeSessionId = payload.session_id;
        state.activeSessionTitle = 'New conversation';
        state.messages = [];
        renderMessages();
        setStatus(`Created ${state.activeSessionId}`);
        return state.activeSessionId;
    }

    async function handleSubmit(event) {
        event.preventDefault();
        if (state.sending) return;

        const input = document.getElementById('chatMessageInput');
        const sendBtn = document.getElementById('chatSendBtn');
        const raw = input ? input.value.trim() : '';
        if (!raw) return;

        state.sending = true;
        if (sendBtn) sendBtn.disabled = true;

        const sessionId = await ensureSession();
        appendMessage('user', raw);
        if (input) {
            input.value = '';
            autoResize(input);
        }

        setStatus(state.anchor
            ? `Thinking from graph anchor ${state.anchor.name || state.anchor.id}...`
            : 'Thinking...'
        );

        const result = await API.sendChatMessage(
            sessionId,
            raw,
            state.anchor ? state.anchor.id : null
        );

        if (result.ok) {
            appendMessage('assistant', result.reply, result.timestamp);
            if (result.anchor) {
                state.anchor = result.anchor;
                persistAnchor(state.anchor);
                renderAnchor();
            }
            setStatus(`Replied in session ${sessionId}`);
            await refreshSessions();
            renderSessions();
        } else {
            appendMessage('assistant', `I hit an error: ${result.error || 'Unknown error'}`);
            setStatus('Request failed');
        }

        state.sending = false;
        if (sendBtn) sendBtn.disabled = false;
    }

    async function startNewSession() {
        const payload = await API.createChatSession('web');
        state.activeSessionId = payload.session_id;
        state.activeSessionTitle = 'New conversation';
        state.messages = [];
        renderMessages();
        renderSessions();
        setStatus(`Created ${state.activeSessionId}`);
    }

    async function adoptPendingAnchor() {
        const pending = loadPersistedAnchor();
        if (!pending) return;

        state.anchor = pending;
        renderAnchor();

        if (!state.activeSessionId) {
            await startNewSession();
        }

        setStatus(`Anchored to ${pending.name || pending.id}`);
    }

    function bindEvents() {
        document.getElementById('chatComposer')?.addEventListener('submit', handleSubmit);
        document.getElementById('chatNewSessionBtn')?.addEventListener('click', () => {
            void startNewSession();
        });
        document.getElementById('chatClearAnchorBtn')?.addEventListener('click', () => {
            state.anchor = null;
            persistAnchor(null);
            renderAnchor();
            setStatus('Graph anchor cleared');
        });

        const input = document.getElementById('chatMessageInput');
        if (input) {
            input.addEventListener('input', () => autoResize(input));
            input.addEventListener('keydown', event => {
                if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    document.getElementById('chatComposer')?.requestSubmit();
                }
            });
        }
    }

    window.ChatPage = {
        openFromGraph(node) {
            state.anchor = {
                id: node.id,
                name: node.name,
                label: node.label,
            };
            persistAnchor(state.anchor);
            renderAnchor();
            PageRouter.navigateTo('chat');
        }
    };

    PageRouter.register({
        id: 'chat',
        label: 'Chat',
        async init() {
            if (!state.initialized) {
                bindEvents();
                state.initialized = true;
            }

            const topStats = document.getElementById('topStats');
            if (topStats) topStats.style.display = 'none';

            const searchInput = document.getElementById('searchInput');
            if (searchInput) {
                searchInput.placeholder = 'Search conversation sessions...';
                searchInput.value = state.searchQuery;
                searchInput.oninput = event => {
                    if (PageRouter.getActive() !== 'chat') return;
                    state.searchQuery = event.target.value;
                    renderSessions();
                };
            }

            renderAnchor();
            await refreshSessions();
            await adoptPendingAnchor();

            if (!state.activeSessionId && state.sessions.length) {
                await selectSession(state.sessions[0].session_id);
            } else if (state.activeSessionId) {
                await selectSession(state.activeSessionId);
            } else {
                renderMessages();
            }
        },
        destroy() { }
    });
})();
