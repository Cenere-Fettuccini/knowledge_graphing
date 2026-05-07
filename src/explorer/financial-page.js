(function () {
    PageRouter.register({
        id: 'financial',
        label: 'Financial',
        init() {
            const searchInput = document.getElementById('searchInput');
            if (searchInput) {
                searchInput.placeholder = 'Search accounts, budgets, or spending plans...';
                searchInput.value = '';
            }

            const topStats = document.getElementById('topStats');
            if (topStats) topStats.style.display = 'none';
        },
        destroy() { }
    });
})();
