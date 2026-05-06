/**
 * ═══════════════════════════════════════════════════════════════════════════
 *  Explorer Page Module
 * ─────────────────────────────────────────────────────────────────────────
 *  Registers with PageRouter. Manages graph visualization initialization,
 *  system status, panel logic, and search filtering.
 *  Delegates heavy lifting to graph.js (3D canvas) and panel.js.
 * ═══════════════════════════════════════════════════════════════════════════
 */

(function () {

    let _initialized = false;

    PageRouter.register({
        id: 'explorer',
        label: 'Explorer',
        init() {
            if (!_initialized) {
                // Panel, ThemeManager (explorer), StatusManager, TaskManager
                // are initialized from panel.js via DOMContentLoaded.
                // Graph initializes itself from graph.js.
                // We just need to trigger a reload if re-entering.
                _initialized = true;
            } else {
                // Re-entering the page — reload graph data
                if (window.GraphManager && window.GraphManager.reload) {
                    window.GraphManager.reload();
                }
            }
            
            const searchInput = document.getElementById('searchInput');
            if (searchInput) {
                searchInput.placeholder = "Search memories, beliefs, tasks...";
                searchInput.value = window.explorerSearchQuery || "";
            }

            const topStats = document.getElementById('topStats');
            if (topStats) topStats.style.display = '';
        },
        destroy() {
            // Graph keeps running its RAF loop but that's fine —
            // it's hidden by CSS (page-view opacity: 0)
        }
    });

})();
