/**
 * Detail Panel logic
 */

const Panel = {
    init() {
        this.nodeInfo = document.getElementById('nodeInfo');
        this.nodeConnections = document.getElementById('nodeConnections');
        this.edgeList = document.getElementById('edgeList');
    },

    clear() {
        this.nodeInfo.innerHTML = '<p class="dim">No target selected.</p>';
        this.nodeConnections.style.display = 'none';
        this.edgeList.innerHTML = '';
    },

    async loadNode(nodeId) {
        this.nodeInfo.innerHTML = '<p class="dim">Fetching data...</p>';
        const data = await API.getNodeDetail(nodeId);

        if (!data || !data.node) {
            this.nodeInfo.innerHTML = '<p class="dim" style="color:var(--c-red)">ERR: Node not found.</p>';
            return;
        }

        const n = data.node;

        const colorMap = {
            'Person': 'var(--color-person)',
            'Project': 'var(--color-project)',
            'Topic': 'var(--color-topic)',
            'Belief': 'var(--color-belief)',
            'Task': 'var(--color-task)'
        };
        const bgColor = colorMap[n.label] || 'var(--fg-dim)';

        let html = `
            <div class="node-header">
                <div class="node-label" style="background-color: ${bgColor}">${n.label}</div>
                <div class="node-name">${n.name}</div>
                <div class="node-id">${n.id}</div>
            </div>
        `;

        // Render extra props based on type
        if (n.label === 'Belief') {
            html += `<p><span class="dim">Status:</span> ${n.status}</p>`;
            html += `<p><span class="dim">Conf:</span> ${n.conf}</p>`;
            html += `<br/><a href="#" style="color:var(--c-blue)">[VIEW_TRAIL]</a>`;
        } else if (n.label === 'Task') {
            html += `<p><span class="dim">Status:</span> <span class="highlight">${n.status}</span></p>`;
        }

        this.nodeInfo.innerHTML = html;

        // Render connections
        if (data.connections && data.connections.length > 0) {
            this.nodeConnections.style.display = 'block';
            this.edgeList.innerHTML = data.connections.map(c =>
                `<li><span>${c.target}</span> <span class="edge-type">[${c.type}]</span></li>`
            ).join('');
        } else {
            this.nodeConnections.style.display = 'none';
        }
    }
};

const ThemeManager = {
    init() {
        this.btn = document.getElementById('themeToggle');
        this.body = document.body;
        this.icon = this.btn.querySelector('svg');
        
        // Check local storage
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'light') {
            this.setLightMode();
        }
        
        this.btn.addEventListener('click', () => {
            if (this.body.classList.contains('light-theme')) {
                this.setDarkMode();
            } else {
                this.setLightMode();
            }
        });
    },
    
    setLightMode() {
        this.body.classList.add('light-theme');
        localStorage.setItem('theme', 'light');
        // Sun icon
        this.icon.innerHTML = '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>';
    },
    
    setDarkMode() {
        this.body.classList.remove('light-theme');
        localStorage.setItem('theme', 'dark');
        // Moon icon
        this.icon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';
    }
};

document.addEventListener('DOMContentLoaded', () => {
    Panel.init();
    ThemeManager.init();
});
