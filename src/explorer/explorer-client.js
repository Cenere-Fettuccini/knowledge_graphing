(function () {
    const http = window.AIManagerHttp;

    window.AIManagerClients = window.AIManagerClients || {};
    window.AIManagerClients.explorer = {
        async getOverview() {
            try {
                return await http.get('/api/explorer/graph/overview');
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
    };
})();
