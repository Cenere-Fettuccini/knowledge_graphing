/**
 * Graph API Client
 */
const API = {
    async getOverview() {
        try {
            const res = await fetch('/api/graph/overview');
            if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
            return await res.json();
        } catch (e) {
            console.error("API Error: getOverview", e);
            return { nodes: [], edges: [], stats: {} };
        }
    },

    async getNodeDetail(nodeId) {
        try {
            const res = await fetch(`/api/graph/node/${nodeId}`);
            if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
            return await res.json();
        } catch (e) {
            console.error("API Error: getNodeDetail", e);
            return null;
        }
    }
};
