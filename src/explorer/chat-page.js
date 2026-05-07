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
            const d = new Date(iso);
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' · ' + d.toLocaleDateString();
        } catch (_) {
            return iso;
        }
    }

    function sessionTitle(session) {
        const preview = (session.preview || '').trim();
        if (!preview) return session.session_id;
        return preview.length > 40 ? `${preview.slice(0, 40)}...` : preview;
    }

    function autoResize(el) {
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
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
            list.innerHTML = '<div style="padding: 16px; color: var(--fg-dim); font-size: 11px; text-align: center;">No conversations match the current search.</div>';
            return;
        }

        list.innerHTML = filtered.map(session => `
            <div class="chat-session-item ${session.session_id === state.activeSessionId ? 'active' : ''}" data-session-id="${session.session_id}">
                <button class="chat-session-item__delete" title="Delete Session">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
                <div class="chat-session-item__title">${sessionTitle(session)}</div>
                <div class="chat-session-item__preview">${session.preview || 'No preview yet.'}</div>
                <div class="chat-session-item__meta">
                    <span>${session.turn_count || 0} turns</span>
                    <span>${fmtDate(session.last_timestamp).split(' · ')[0]}</span>
                </div>
            </div>
        `).join('');

        list.querySelectorAll('.chat-session-item').forEach(item => {
            const sessionId = item.getAttribute('data-session-id');
            item.addEventListener('click', () => {
                if (sessionId) {
                    void selectSession(sessionId);
                }
            });

            const deleteBtn = item.querySelector('.chat-session-item__delete');
            if (deleteBtn) {
                deleteBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (!confirm('Are you sure you want to delete this conversation?')) return;
                    
                    setStatus('Deleting session...');
                    const result = await API.deleteChatSession(sessionId);
                    if (result.ok) {
                        if (state.activeSessionId === sessionId) {
                            state.activeSessionId = null;
                            state.activeSessionTitle = '';
                            state.messages = [];
                            renderMessages();
                        }
                        await refreshSessions();
                        setStatus('Session deleted');
                    } else {
                        setStatus('Failed to delete session');
                    }
                });
            }
        });
    }

    function parseMarkdown(text) {
        if (!text) return '';
        // Escape HTML
        let html = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        
        // Code blocks
        html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
        // Inline code
        html = html.replace(/`(.*?)`/g, '<code>$1</code>');
        // Bold
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        // Italic
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
        // Newlines to <br> outside of pre blocks
        // A simple approach: split by <pre>, replace newlines in non-pre, then rejoin
        const parts = html.split(/(<pre><code>[\s\S]*?<\/code><\/pre>)/);
        for (let i = 0; i < parts.length; i++) {
            if (!parts[i].startsWith('<pre>')) {
                parts[i] = parts[i].replace(/\n/g, '<br/>');
            }
        }
        return parts.join('');
    }

    function renderMessages() {
        const thread = document.getElementById('chatThread');
        const title = document.getElementById('chatSessionTitle');
        if (!thread || !title) return;

        title.textContent = state.activeSessionTitle || 'New conversation';

        if (!state.messages.length && !state.sending) {
            thread.innerHTML = `
                <div class="chat-empty-state">
                    ${state.anchor
                    ? 'This chat is anchored to a graph node.<br>Ask the assistant to analyze or elaborate from here.'
                    : 'Start a chat, or jump here from a graph node to talk from that point.'}
                </div>
            `;
            return;
        }

        let html = state.messages.map(message => `
            <div class="chat-message ${message.role}">
                <div class="chat-message__meta">${message.role === 'user' ? 'You' : 'AIManager'} · ${fmtDate(message.timestamp)}</div>
                <div class="chat-message__bubble">${parseMarkdown(message.text)}</div>
            </div>
        `).join('');

        if (state.sending) {
            html += `
                <div class="chat-message assistant" id="chatTypingIndicator">
                    <div class="chat-message__meta">AIManager · Typing...</div>
                    <div class="chat-message__bubble">
                        <div class="typing-indicator"><span></span><span></span><span></span></div>
                    </div>
                </div>
            `;
        }

        thread.innerHTML = html;
        scrollToBottom();
    }

    function scrollToBottom() {
        const thread = document.getElementById('chatThread');
        if (thread) {
            setTimeout(() => {
                thread.scrollTo({ top: thread.scrollHeight, behavior: 'smooth' });
            }, 50);
        }
    }

    function appendMessage(role, text, timestamp = new Date().toISOString()) {
        state.messages.push({ role, text, timestamp });
        renderMessages();
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
        setStatus(`Session loaded · ${state.messages.length} messages`);
    }

    async function ensureSession() {
        if (state.activeSessionId) return state.activeSessionId;
        const payload = await API.createChatSession('web');
        state.activeSessionId = payload.session_id;
        state.activeSessionTitle = 'New conversation';
        state.messages = [];
        renderMessages();
        setStatus('New session started');
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
            ? `Thinking from anchor: ${state.anchor.name || state.anchor.id}...`
            : 'Thinking...'
        );

        // Force a re-render to show typing indicator
        renderMessages();

        const result = await API.sendChatMessage(
            sessionId,
            raw,
            state.anchor ? state.anchor.id : null
        );

        state.sending = false;

        if (result.ok) {
            appendMessage('assistant', result.reply, result.timestamp);
            if (result.anchor) {
                state.anchor = result.anchor;
                persistAnchor(state.anchor);
                renderAnchor();
            }
            setStatus('Replied successfully');
            await refreshSessions();
            renderSessions();
        } else {
            appendMessage('assistant', `⚠️ **Error:** ${result.error || 'Unknown network error occurred.'}`);
            setStatus('Request failed');
        }

        if (sendBtn) sendBtn.disabled = false;
    }

    async function startNewSession() {
        const payload = await API.createChatSession('web');
        state.activeSessionId = payload.session_id;
        state.activeSessionTitle = 'New conversation';
        state.messages = [];
        renderMessages();
        renderSessions();
        setStatus('New session created');
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
                    // Avoid duplicate submission if already sending
                    if (!state.sending) {
                        const evt = new Event('submit', { cancelable: true });
                        document.getElementById('chatComposer')?.dispatchEvent(evt);
                    }
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
