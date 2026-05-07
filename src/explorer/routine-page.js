(function () {
    PageRouter.register({
        id: 'routine',
        label: 'Routine',
        init() {
            const searchInput = document.getElementById('searchInput');
            if (searchInput) {
                searchInput.placeholder = 'Search routines, blocks, or recurring plans...';
                searchInput.value = '';
            }

            const topStats = document.getElementById('topStats');
            if (topStats) topStats.style.display = 'none';
        },
        destroy() { }
    });
})();
