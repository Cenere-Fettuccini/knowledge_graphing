(function () {
    const state = {
        searchQuery: '',
        initialized: false,
    };

    function buildFinanceContext() {
        return {
            source_section: 'financial',
            context_type: 'finance_overview',
            context_id: 'financial-manager',
            context_summary: 'Financial Manager overview',
            context_payload: {
                scope: 'accounts, spending, planning',
            },
        };
    }

    PageRouter.register({
        id: 'financial',
        label: 'Financial',
        role: 'domain',
        paths: ['/financial', '/apps/financial-manager'],
        mount(root, shellContext) {
            if (!state.initialized) {
                root.querySelector('#financialOpenChatBtn')?.addEventListener('click', () => {
                    void shellContext.navigateToSection('chat', {
                        type: 'chat:open-context',
                        payload: buildFinanceContext(),
                    });
                });
                state.initialized = true;
            }

            shellContext.setSearchPlaceholder('Search accounts, budgets, or spending plans...');
            shellContext.setSearchValue(state.searchQuery);
            shellContext.setTopStats('', false);
        },
        unmount() { },
        onSearch(query) {
            state.searchQuery = query;
        },
    });
})();
