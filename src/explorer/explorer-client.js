(function () {
    const http = window.AIManagerHttp;

    window.AIManagerClients = window.AIManagerClients || {};
    window.AIManagerClients.explorer = {
        async getOverview(limit, opts = {}) {
            try {
                const params = new URLSearchParams();
                if (limit) params.set('limit', String(limit));
                if (opts.eraId) params.set('era_id', opts.eraId);
                if (opts.activeSelfOnly) params.set('active_self_only', 'true');
                const qs = params.toString();
                const url = qs
                    ? `/api/explorer/graph/overview?${qs}`
                    : '/api/explorer/graph/overview';
                return await http.get(url);
            } catch (error) {
                console.error('ExplorerClient.getOverview failed', error);
                return { nodes: [], edges: [], stats: {} };
            }
        },

        async getNeighborhood(nodeId, { depth = 1, limit = 200 } = {}) {
            try {
                const url = `/api/explorer/graph/neighborhood/${encodeURIComponent(nodeId)}?depth=${depth}&limit=${limit}`;
                return await http.get(url);
            } catch (error) {
                console.error('ExplorerClient.getNeighborhood failed', error);
                return { focal: null, nodes: [], edges: [], stats: {} };
            }
        },

        async getEras({ activeOnly = false } = {}) {
            try {
                const url = activeOnly ? '/api/explorer/eras?active_only=true' : '/api/explorer/eras';
                return await http.get(url);
            } catch (error) {
                console.error('ExplorerClient.getEras failed', error);
                return { eras: [] };
            }
        },

        async getErasActiveAt(isoDate) {
            try {
                return await http.get(`/api/explorer/eras/active-at?date=${encodeURIComponent(isoDate)}`);
            } catch (error) {
                console.error('ExplorerClient.getErasActiveAt failed', error);
                return { eras: [] };
            }
        },

        async getNodeDetail(nodeId) {
            try {
                return await http.get(`/api/explorer/graph/node/${nodeId}`);
            } catch (error) {
                console.error('ExplorerClient.getNodeDetail failed', error);
                return null;
            }
        },

        async getNodeProvenance(nodeId) {
            try {
                return await http.get(`/api/explorer/graph/node/${nodeId}/provenance`);
            } catch (error) {
                console.error('ExplorerClient.getNodeProvenance failed', error);
                return null;
            }
        },

        async getBeliefTrail(nodeId) {
            try {
                return await http.get(`/api/explorer/graph/belief/${nodeId}/trail`);
            } catch (error) {
                console.error('ExplorerClient.getBeliefTrail failed', error);
                return null;
            }
        },

        async getSystemStatus() {
            try {
                return await http.get('/api/explorer/system/status');
            } catch (error) {
                console.error('ExplorerClient.getSystemStatus failed', error);
                return { neo4j: 'offline', chroma: 'offline', agent: 'offline' };
            }
        },

        async getActiveTasks() {
            try {
                return await http.get('/api/explorer/tasks/active');
            } catch (error) {
                console.error('ExplorerClient.getActiveTasks failed', error);
                return [];
            }
        },

        async getBootstrapStatus() {
            try {
                return await http.get('/api/explorer/bootstrap/status');
            } catch (error) {
                console.error('ExplorerClient.getBootstrapStatus failed', error);
                return { initialized: false, user: null, _error: true };
            }
        },

        async bootstrap(name) {
            return await http.post('/api/explorer/bootstrap', { name });
        },

        async getAnalyzerStatus() {
            try {
                return await http.get('/api/explorer/analyze/status');
            } catch (error) {
                console.error('ExplorerClient.getAnalyzerStatus failed', error);
                return { unanalyzed_count: 0, local_llm_available: false, default_model: '' };
            }
        },

        async runAnalyzer({ batchSize = 20 } = {}) {
            const body = { batch_size: batchSize };
            return await http.post('/api/explorer/analyze/run', body);
        },

        async processAllQueue() {
            return await http.post('/api/explorer/analyze/process-all', {});
        },

        async resetGraph() {
            return await http.post('/api/explorer/graph/reset', {});
        },
    };
})();
