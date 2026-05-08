(function () {
    const state = {
        searchQuery: '',
        mounted: false,
    };

    PageRouter.register({
        id: 'explorer',
        label: 'Explorer',
        role: 'cross_cutting',
        paths: ['/explorer', '/apps/explorer'],
        mount(_root, shellContext) {
            state.mounted = true;
            shellContext.setSearchPlaceholder('Search memories, beliefs, tasks...');
            shellContext.setSearchValue(state.searchQuery);
            shellContext.setTopStats('System Ready', true);
            window.ExplorerPageController?.activate?.(shellContext);
        },
        unmount() {
            state.mounted = false;
            window.ExplorerPageController?.deactivate?.();
        },
        onSearch(query) {
            state.searchQuery = query;
            window.ExplorerPageController?.setSearchQuery?.(query);
        },
    });
})();
