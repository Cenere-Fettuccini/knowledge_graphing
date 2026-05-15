(function () {
    const http = window.AIManagerHttp;

    // ── Offline send queue (S0.9) ─────────────────────────────────────────
    //
    // When the chat server is unreachable we keep the user's outbound
    // messages in localStorage so they survive page reload. Each entry
    // carries a client_msg_id; the server dedupes on retry so a recovered
    // queue never produces duplicate replies.

    const PENDING_KEY = 'chat_pending';
    const DRAIN_INTERVAL_MS = 30000;
    const drainListeners = new Set();

    function uuid() {
        if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
        return 'msg_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
    }

    function loadPending() {
        try {
            const raw = window.localStorage.getItem(PENDING_KEY);
            if (!raw) return [];
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch (err) {
            console.warn('chat_pending parse failed; resetting', err);
            return [];
        }
    }

    function savePending(items) {
        try {
            window.localStorage.setItem(PENDING_KEY, JSON.stringify(items));
        } catch (err) {
            console.warn('chat_pending save failed', err);
        }
        notifyDrainListeners(items.length);
    }

    function notifyDrainListeners(count) {
        drainListeners.forEach((fn) => {
            try { fn(count); } catch (err) { console.warn(err); }
        });
    }

    function isTransientError(error) {
        // No response (fetch network failure) or 5xx -> retry. Anything else
        // (400, 401, etc.) is treated as terminal — queueing it would just
        // bounce forever.
        if (!error) return false;
        if (error.name === 'TypeError') return true;  // fetch network error
        if (typeof error.status === 'number') {
            return error.status >= 500 && error.status < 600;
        }
        return true;  // unknown shape — assume transient, give it a chance
    }

    async function postMessage(payload) {
        return http.post('/api/chat-app/message', payload);
    }

    async function drainPending() {
        const items = loadPending();
        if (items.length === 0) return { drained: 0, remaining: 0 };

        const remaining = [];
        let drained = 0;
        for (const item of items) {
            try {
                await postMessage(item.payload);
                drained += 1;
            } catch (err) {
                if (isTransientError(err)) {
                    remaining.push(item);
                } else {
                    // Terminal error — drop the message rather than retry forever.
                    console.error('Dropping pending message (terminal error)', err, item);
                }
            }
        }
        savePending(remaining);
        return { drained, remaining: remaining.length };
    }

    function getPendingCount() {
        return loadPending().length;
    }

    function onPendingChange(callback) {
        drainListeners.add(callback);
        return () => drainListeners.delete(callback);
    }

    // Drain whenever the browser regains connectivity, and on a slow timer
    // as a fallback for partial / flaky connections that don't fire 'online'.
    window.addEventListener('online', () => { void drainPending(); });
    setInterval(() => { void drainPending(); }, DRAIN_INTERVAL_MS);

    window.AIManagerClients = window.AIManagerClients || {};
    window.AIManagerClients.chat = {
        async getSessions() {
            try {
                return await http.get('/api/chat-app/sessions');
            } catch (error) {
                console.error('ChatClient.getSessions failed', error);
                return { sessions: [] };
            }
        },

        async getSession(sessionId) {
            try {
                return await http.get(`/api/chat-app/session/${sessionId}`);
            } catch (error) {
                console.error('ChatClient.getSession failed', error);
                return { session_id: sessionId, messages: [] };
            }
        },

        async createSession(label = 'browser') {
            try {
                return await http.post('/api/chat-app/session', { label });
            } catch (error) {
                console.error('ChatClient.createSession failed', error);
                return { session_id: `browser_${Date.now()}` };
            }
        },

        async deleteSession(sessionId) {
            try {
                return await http.delete(`/api/chat-app/session/${sessionId}`);
            } catch (error) {
                console.error('ChatClient.deleteSession failed', error);
                return { ok: false, error: error.message || 'Request failed' };
            }
        },

        async sendMessage(sessionId, message, messageTimestamp, context = null) {
            const payload = {
                session_id: sessionId,
                message,
                message_timestamp: messageTimestamp,
                context,
                client_msg_id: uuid(),
            };
            try {
                return await postMessage(payload);
            } catch (error) {
                if (isTransientError(error)) {
                    const pending = loadPending();
                    pending.push({ payload, queued_at: new Date().toISOString() });
                    savePending(pending);
                    return {
                        ok: false,
                        queued: true,
                        pending_count: pending.length,
                        client_msg_id: payload.client_msg_id,
                        error: 'Server unreachable; message queued offline.',
                    };
                }
                console.error('ChatClient.sendMessage failed', error);
                return { ok: false, error: error.message || 'Request failed' };
            }
        },

        // Drain API for chat-page.js (badge, manual retry buttons, etc.)
        getPendingCount,
        drainPending,
        onPendingChange,
    };
})();
