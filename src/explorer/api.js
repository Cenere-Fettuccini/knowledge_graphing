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
    },

    async getSystemStatus() {
        try {
            const res = await fetch('/api/system/status');
            if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
            return await res.json();
        } catch (e) {
            console.error("API Error: getSystemStatus", e);
            return { neo4j: "offline", chroma: "offline", agent: "offline" };
        }
    },

    async getChatSessions() {
        try {
            const res = await fetch('/api/chat/sessions');
            if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
            return await res.json();
        } catch (e) {
            console.error("API Error: getChatSessions", e);
            return { sessions: [] };
        }
    },

    async getChatSession(sessionId) {
        try {
            const res = await fetch(`/api/chat/session/${sessionId}`);
            if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
            return await res.json();
        } catch (e) {
            console.error("API Error: getChatSession", e);
            return { session_id: sessionId, messages: [] };
        }
    },

    async createChatSession(label = "browser") {
        try {
            const res = await fetch('/api/chat/session', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ label })
            });
            if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
            return await res.json();
        } catch (e) {
            console.error("API Error: createChatSession", e);
            return { session_id: `browser_${Date.now()}` };
        }
    },

    async deleteChatSession(sessionId) {
        try {
            const res = await fetch(`/api/chat/session/${sessionId}`, { method: 'DELETE' });
            if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
            return await res.json();
        } catch (e) {
            console.error("API Error: deleteChatSession", e);
            return { ok: false, error: e.message || 'Request failed' };
        }
    },

    async sendChatMessage(sessionId, message, anchorNodeId = null) {
        try {
            const res = await fetch('/api/chat/message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId,
                    message,
                    anchor_node_id: anchorNodeId
                })
            });
            if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
            return await res.json();
        } catch (e) {
            console.error("API Error: sendChatMessage", e);
            return { ok: false, error: e.message || 'Request failed' };
        }
    }
};

/**
 * Dynamic Color Manager for Graph Labels
 */
window.ColorManager = {
    // A carefully curated, zen-minimalist aesthetic palette
    palette: [
        '#7FA38D', // soft green
        '#A37A87', // muted pink
        '#BEAA7E', // earthy gold
        '#7E91BE', // soft blue
        '#A89274', // warm brown
        '#8F859A', // muted purple
        '#C49B76', // soft orange
        '#8B9B97', // slate green
        '#9C8E7D', // taupe
    ],
    assignedColors: new Map(),
    goldenAngle: 137.508, 
    lastGeneratedHue: 0,

    init() {
        // Load saved state from previous sessions
        try {
            const savedMap = localStorage.getItem('aimanager_graph_colors');
            if (savedMap) this.assignedColors = new Map(JSON.parse(savedMap));
            
            const savedHue = localStorage.getItem('aimanager_last_hue');
            if (savedHue) this.lastGeneratedHue = parseFloat(savedHue);
            else this.lastGeneratedHue = Math.random() * 360;
        } catch (e) {
            console.warn("Could not load color state from LocalStorage", e);
            this.lastGeneratedHue = Math.random() * 360;
        }
    },

    saveState() {
        try {
            localStorage.setItem('aimanager_graph_colors', JSON.stringify([...this.assignedColors]));
            localStorage.setItem('aimanager_last_hue', this.lastGeneratedHue.toString());
        } catch (e) {
            console.warn("Could not save color state to LocalStorage", e);
        }
    },

    getColor(label) {
        if (!label) return '#99958E'; // Default muted grey
        
        const key = label.toLowerCase().trim();
        
        // 1. If assigned previously (even in a past session), use it
        if (this.assignedColors.has(key)) {
            return this.assignedColors.get(key);
        }
        
        // 2. If we still have curated colors left, assign the next one
        if (this.assignedColors.size < this.palette.length) {
            const color = this.palette[this.assignedColors.size];
            this.assignedColors.set(key, color);
            this.saveState();
            return color;
        }
        
        // 3. Fallback: Generate unique colors
        this.lastGeneratedHue = (this.lastGeneratedHue + this.goldenAngle) % 360;
        const generatedColor = `hsl(${Math.round(this.lastGeneratedHue)}, 30%, 55%)`;
        
        this.assignedColors.set(key, generatedColor);
        this.saveState();
        return generatedColor;
    }
};

// Initialize color persistence on load
window.ColorManager.init();
