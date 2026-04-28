/**
 * api.js — REST client for /api/graph/* endpoints.
 * All functions return plain JS objects (already JSON-parsed).
 * Errors are re-thrown with a descriptive message so callers can handle them.
 */

const API = (() => {
    const BASE = '/api/graph';

    async function _get(path) {
        const res = await fetch(`${BASE}${path}`);
        if (!res.ok) throw new Error(`API ${path} → ${res.status} ${res.statusText}`);
        return res.json();
    }

    return {
        /** All nodes + edges + stats */
        overview: () => _get('/overview'),
        /** Full node detail (connections + facts) */
        nodeDetail: (id) => _get(`/node/${encodeURIComponent(id)}`),
        /** 2-hop neighbourhood */
        expand: (id) => _get(`/expand/${encodeURIComponent(id)}`),
        /** Full-text search */
        search: (q) => _get(`/search?q=${encodeURIComponent(q)}`),
        /** Source conversation for a fact */
        factSource: (factId) => _get(`/source/${encodeURIComponent(factId)}`),
        /** Live stats */
        stats: () => _get('/stats'),
    };
})();