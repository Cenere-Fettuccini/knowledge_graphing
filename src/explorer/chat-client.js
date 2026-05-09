(function () {
    const http = window.AIManagerHttp;

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
            try {
                return await http.post('/api/chat-app/message', {
                    session_id: sessionId,
                    message,
                    message_timestamp: messageTimestamp,
                    context,
                });
            } catch (error) {
                console.error('ChatClient.sendMessage failed', error);
                return { ok: false, error: error.message || 'Request failed' };
            }
        },
    };
})();
