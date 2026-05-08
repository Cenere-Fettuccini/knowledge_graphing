(function () {
    const state = {
        searchQuery: '',
        initialized: false,
    };

    function buildRoutineContext() {
        return {
            source_section: 'routine',
            context_type: 'routine_overview',
            context_id: 'routine-scheduler',
            context_summary: 'Routine Scheduler overview',
            context_payload: {
                scope: 'routines, timeblocks, recurring plans',
            },
        };
    }

    PageRouter.register({
        id: 'routine',
        label: 'Routine',
        role: 'domain',
        paths: ['/routine', '/apps/routine-scheduler'],
        mount(root, shellContext) {
            if (!state.initialized) {
                root.querySelector('#routineOpenChatBtn')?.addEventListener('click', () => {
                    void shellContext.navigateToSection('chat', {
                        type: 'chat:open-context',
                        payload: buildRoutineContext(),
                    });
                });
                state.initialized = true;
            }

            shellContext.setSearchPlaceholder('Search routines, blocks, or recurring plans...');
            shellContext.setSearchValue(state.searchQuery);
            shellContext.setTopStats('', false);
        },
        unmount() { },
        onSearch(query) {
            state.searchQuery = query;
        },
    });
})();
