(function () {
    const http = window.AIManagerHttp;

    window.AIManagerClients = window.AIManagerClients || {};
    window.AIManagerClients.explorer = {
        async getOverview(limit) {
            try {
                const url = limit
                    ? `/api/explorer/graph/overview?limit=${encodeURIComponent(limit)}`
                    : '/api/explorer/graph/overview';
                return await http.get(url);
            } catch (error) {
                console.error('ExplorerClient.getOverview failed', error);
                return { nodes: [], edges: [], stats: {} };
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

        async listAnalyzerModels() {
            try {
                return await http.get('/api/explorer/analyze/models');
            } catch (error) {
                console.error('ExplorerClient.listAnalyzerModels failed', error);
                return [];
            }
        },

        async runAnalyzer({ batchSize = 20, model = null } = {}) {
            const body = { batch_size: batchSize };
            if (model) body.model = model;
            return await http.post('/api/explorer/analyze/run', body);
        },
    };
})();
