(function () {
    const state = {
        searchQuery: '',
        mounted: false,
    };

    function getExplorerClient() {
        return window.AIManagerShell?.clients?.explorer || window.AIManagerClients?.explorer;
    }

    function showBootstrapModal({ onSubmit }) {
        const modal = document.getElementById('bootstrapModal');
        const input = document.getElementById('bootstrapNameInput');
        const submit = document.getElementById('bootstrapSubmit');
        const errorBox = document.getElementById('bootstrapError');
        if (!modal || !input || !submit) return;

        modal.hidden = false;
        errorBox.hidden = true;
        input.value = '';
        setTimeout(() => input.focus(), 0);

        async function handle() {
            const name = (input.value || '').trim();
            if (!name) {
                errorBox.textContent = 'Please enter a name.';
                errorBox.hidden = false;
                return;
            }
            submit.disabled = true;
            errorBox.hidden = true;
            try {
                await onSubmit(name);
                modal.hidden = true;
            } catch (error) {
                console.error('Bootstrap failed', error);
                errorBox.textContent = 'Could not create root node — is Neo4j running?';
                errorBox.hidden = false;
            } finally {
                submit.disabled = false;
            }
        }
        submit.onclick = handle;
        input.onkeydown = (e) => { if (e.key === 'Enter') handle(); };
    }

    async function ensureBootstrapped(shellContext) {
        const client = getExplorerClient();
        if (!client) {
            window.ExplorerPageController?.activate?.(shellContext);
            return;
        }
        const status = await client.getBootstrapStatus();
        if (status && status.initialized) {
            window.ExplorerPageController?.activate?.(shellContext);
            return;
        }
        showBootstrapModal({
            onSubmit: async (name) => {
                await client.bootstrap(name);
                window.ExplorerPageController?.activate?.(shellContext);
                window.GraphManager?.reload?.();
            },
        });
    }

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
            ensureBootstrapped(shellContext);
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
