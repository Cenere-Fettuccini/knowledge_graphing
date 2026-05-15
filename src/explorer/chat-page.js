(function () {
    const CHAT_CONTEXT_STORAGE_KEY = 'aimanager_chat_context';

    const state = {
        initialized: false,
        sessions: [],
        activeSessionId: null,
        activeSessionTitle: '',
        messages: [],
        searchQuery: '',
        chatContext: null,
        sending: false,
        pendingDeleteSessionId: null,
        deletingSessionId: null,
    };

    function chatClient() {
        return window.AIManagerShell?.clients?.chat || window.AIManagerClients?.chat;
    }

    function fmtDate(iso) {
        if (!iso) return 'No timestamp';
        try {
            const date = new Date(iso);
            return `${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ${date.toLocaleDateString()}`;
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

    function setMemoryWarning(degraded, health) {
        const wrap = document.getElementById('chatMemoryWarning');
        const text = document.getElementById('chatMemoryWarningText');
        if (!wrap) return;
        if (!degraded) {
            wrap.hidden = true;
            return;
        }
        let label = 'Memory degraded';
        const pending = (health && health.spillover_pending) || null;
        const pendingTotal = pending ? (Number(pending.chroma) || 0) + (Number(pending.neo4j) || 0) : 0;
        const offline = [];
        if (health && health.chroma === 'offline') offline.push('Chroma');
        if (health && health.neo4j === 'offline') offline.push('Neo4j');
        if (offline.length) {
            label = `${offline.join(' + ')} offline — your message is queued`;
        } else if (pendingTotal > 0) {
            label = `Memory degraded — ${pendingTotal} write${pendingTotal === 1 ? '' : 's'} pending replay`;
        }
        if (text) text.textContent = label;
        wrap.hidden = false;
    }

    function getPendingDeleteSession() {
        return state.sessions.find((session) => session.session_id === state.pendingDeleteSessionId) || null;
    }

    function syncDeleteModal() {
        const modal = document.getElementById('chatDeleteModal');
        const message = document.getElementById('chatDeleteModalMessage');
        const confirmBtn = document.getElementById('chatDeleteConfirmBtn');
        if (!modal || !message || !confirmBtn) return;

        const session = getPendingDeleteSession();
        const isOpen = !!state.pendingDeleteSessionId;
        const isDeleting = !!state.deletingSessionId;
        modal.classList.toggle('open', isOpen);
        modal.setAttribute('aria-hidden', isOpen ? 'false' : 'true');

        if (session) {
            message.textContent = `Delete "${sessionTitle(session)}"? This permanently removes the conversation from the session list.`;
        } else {
            message.textContent = 'This will permanently remove the selected conversation from the session list.';
        }

        confirmBtn.disabled = isDeleting;
        confirmBtn.textContent = isDeleting ? 'Deleting...' : 'Delete';
    }

    function openDeleteModal(sessionId) {
        state.pendingDeleteSessionId = sessionId;
        syncDeleteModal();
    }

    function closeDeleteModal() {
        state.pendingDeleteSessionId = null;
        state.deletingSessionId = null;
        syncDeleteModal();
    }

    async function confirmDeleteSession() {
        const sessionId = state.pendingDeleteSessionId;
        if (!sessionId || state.deletingSessionId) return;

        state.deletingSessionId = sessionId;
        syncDeleteModal();
        setStatus('Deleting session...');

        const result = await chatClient().deleteSession(sessionId);
        if (result.ok) {
            if (state.activeSessionId === sessionId) {
                state.activeSessionId = null;
                state.activeSessionTitle = '';
                state.messages = [];
                renderMessages();
            }
            closeDeleteModal();
            await refreshSessions();
            setStatus('Session deleted');
        } else {
            state.deletingSessionId = null;
            syncDeleteModal();
            setStatus('Failed to delete session');
        }
    }

    function persistContext(context) {
        if (!context) {
            sessionStorage.removeItem(CHAT_CONTEXT_STORAGE_KEY);
            return;
        }
        sessionStorage.setItem(CHAT_CONTEXT_STORAGE_KEY, JSON.stringify(context));
    }

    function loadPersistedContext() {
        try {
            const raw = sessionStorage.getItem(CHAT_CONTEXT_STORAGE_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (_) {
            return null;
        }
    }

    function renderContext() {
        const box = document.getElementById('chatAnchorBox');
        const title = document.getElementById('chatAnchorTitle');
        const subtitle = document.getElementById('chatAnchorSubtitle');
        if (!box || !title || !subtitle) return;

        if (!state.chatContext) {
            box.hidden = true;
            return;
        }

        title.textContent = state.chatContext.context_summary || state.chatContext.context_id;
        subtitle.textContent = `${state.chatContext.context_type || 'Context'}${state.chatContext.context_id ? ` · ${state.chatContext.context_id}` : ''}`;
        box.hidden = false;
    }

    function renderSessions() {
        const list = document.getElementById('chatSessionList');
        const count = document.getElementById('chatSessionCount');
        if (!list) return;

        const filtered = state.sessions.filter((session) => {
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

        list.innerHTML = filtered.map((session) => `
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

        list.querySelectorAll('.chat-session-item').forEach((item) => {
            const sessionId = item.getAttribute('data-session-id');
            item.addEventListener('click', () => {
                if (sessionId) void selectSession(sessionId);
            });

            const deleteBtn = item.querySelector('.chat-session-item__delete');
            deleteBtn?.addEventListener('click', (event) => {
                event.stopPropagation();
                openDeleteModal(sessionId);
            });
        });
    }

    function parseMarkdown(text) {
        if (!text) return '';
        let html = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
        html = html.replace(/`(.*?)`/g, '<code>$1</code>');
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
        const parts = html.split(/(<pre><code>[\s\S]*?<\/code><\/pre>)/);
        for (let index = 0; index < parts.length; index += 1) {
            if (!parts[index].startsWith('<pre>')) {
                parts[index] = parts[index].replace(/\n/g, '<br/>');
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
                    ${state.chatContext
                        ? 'This chat is anchored to platform context.<br>Ask the assistant to analyze or elaborate from here.'
                        : 'Start a chat, or jump here from a graph node to talk from that point.'}
                </div>
            `;
            return;
        }

        let html = state.messages.map((message) => `
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
        if (!thread) return;
        setTimeout(() => {
            thread.scrollTo({ top: thread.scrollHeight, behavior: 'smooth' });
        }, 50);
    }

    function appendMessage(role, text, timestamp = new Date().toISOString()) {
        state.messages.push({ role, text, timestamp });
        renderMessages();
    }

    async function refreshSessions() {
        const payload = await chatClient().getSessions();
        state.sessions = payload.sessions || [];
        renderSessions();
    }

    async function selectSession(sessionId) {
        state.activeSessionId = sessionId;
        state.activeSessionTitle = sessionId;
        renderSessions();
        setStatus('Loading conversation...');

        const payload = await chatClient().getSession(sessionId);
        state.messages = payload.messages || [];
        const sessionMeta = state.sessions.find((session) => session.session_id === sessionId);
        state.activeSessionTitle = sessionMeta ? sessionTitle(sessionMeta) : sessionId;
        renderMessages();
        renderSessions();
        setStatus(`Session loaded · ${state.messages.length} messages`);
    }

    async function ensureSession() {
        if (state.activeSessionId) return state.activeSessionId;
        const payload = await chatClient().createSession('web');
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
        const messageTimestamp = new Date().toISOString();

        state.sending = true;
        if (sendBtn) sendBtn.disabled = true;

        const sessionId = await ensureSession();
        appendMessage('user', raw, messageTimestamp);
        if (input) {
            input.value = '';
            autoResize(input);
        }

        setStatus(
            state.chatContext
                ? `Thinking from context: ${state.chatContext.context_summary || state.chatContext.context_id}...`
                : 'Thinking...'
        );
        renderMessages();

        const result = await chatClient().sendMessage(sessionId, raw, messageTimestamp, state.chatContext);
        state.sending = false;

        if (result.ok) {
            appendMessage('assistant', result.reply, result.timestamp);
            if (result.context) {
                state.chatContext = result.context;
                persistContext(state.chatContext);
                renderContext();
            }
            setStatus('Replied successfully');
            setMemoryWarning(Boolean(result.memory_degraded), result.memory_health);
            await refreshSessions();
        } else if (result.queued) {
            setStatus(`Server unreachable — queued offline (${result.pending_count} pending)`);
        } else {
            appendMessage('assistant', `**Error:** ${result.error || 'Unknown network error occurred.'}`);
            setStatus('Request failed');
        }

        if (sendBtn) sendBtn.disabled = false;
    }

    async function startNewSession() {
        const payload = await chatClient().createSession('web');
        state.activeSessionId = payload.session_id;
        state.activeSessionTitle = 'New conversation';
        state.messages = [];
        renderMessages();
        renderSessions();
        setStatus('New session created');
    }

    async function adoptPendingContext() {
        const pending = loadPersistedContext();
        if (!pending) return;

        state.chatContext = pending;
        renderContext();
        if (!state.activeSessionId) {
            await startNewSession();
        }
        setStatus(`Anchored to ${pending.context_summary || pending.context_id}`);
    }

    function bindEvents() {
        document.getElementById('chatComposer')?.addEventListener('submit', handleSubmit);
        document.getElementById('chatNewSessionBtn')?.addEventListener('click', () => {
            void startNewSession();
        });
        document.getElementById('chatClearAnchorBtn')?.addEventListener('click', () => {
            state.chatContext = null;
            persistContext(null);
            renderContext();
            setStatus('Platform context cleared');
        });
        document.getElementById('chatDeleteCancelBtn')?.addEventListener('click', closeDeleteModal);
        document.getElementById('chatDeleteConfirmBtn')?.addEventListener('click', () => {
            void confirmDeleteSession();
        });
        document.getElementById('chatDeleteModal')?.addEventListener('click', (event) => {
            if (event.target?.id === 'chatDeleteModal' && !state.deletingSessionId) {
                closeDeleteModal();
            }
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && state.pendingDeleteSessionId && !state.deletingSessionId) {
                closeDeleteModal();
            }
        });

        const input = document.getElementById('chatMessageInput');
        if (!input) return;
        input.addEventListener('input', () => autoResize(input));
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                if (!state.sending) {
                    document.getElementById('chatComposer')?.dispatchEvent(new Event('submit', { cancelable: true }));
                }
            }
        });
    }

    PageRouter.register({
        id: 'chat',
        label: 'Chat',
        role: 'cross_cutting',
        paths: ['/chat', '/apps/chat'],
        async mount(_root, shellContext) {
            if (!state.initialized) {
                bindEvents();
                state.initialized = true;
            }

            shellContext.setTopStats('', false);
            shellContext.setSearchPlaceholder('Search conversation sessions...');
            shellContext.setSearchValue(state.searchQuery);

            renderContext();
            await refreshSessions();
            await adoptPendingContext();

            if (!state.activeSessionId && state.sessions.length) {
                await selectSession(state.sessions[0].session_id);
            } else if (state.activeSessionId) {
                await selectSession(state.activeSessionId);
            } else {
                renderMessages();
            }
        },
        unmount() { },
        onSearch(query) {
            state.searchQuery = query;
            renderSessions();
        },
        onContext(event) {
            if (event.type !== 'chat:open-context') return;
            state.chatContext = event.payload;
            persistContext(state.chatContext);
            renderContext();
            setStatus(`Anchored to ${state.chatContext.context_summary || state.chatContext.context_id}`);
        },
    });
})();
