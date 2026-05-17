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
        if (status && status.neo4j_offline) {
            // Neo4j is down — don't prompt for bootstrap, just activate with degraded state
            window.ExplorerPageController?.activate?.(shellContext);
            return;
        }
        showBootstrapModal({
            onSubmit: async (name) => {
                await client.bootstrap(name);
                window.ExplorerPageController?.activate?.(shellContext);
                window.GraphManager?.reload?.({ full: true });
            },
        });
    }

    function wireResetButton() {
        const btn = document.getElementById('resetGraphBtn');
        const statusEl = document.getElementById('resetGraphStatus');
        const modal = document.getElementById('resetGraphModal');
        const confirmBtn = document.getElementById('resetGraphConfirmBtn');
        const cancelBtn = document.getElementById('resetGraphCancelBtn');
        const errorEl = document.getElementById('resetGraphError');
        if (!btn || !modal) return;

        btn.addEventListener('click', () => {
            if (errorEl) errorEl.hidden = true;
            modal.hidden = false;
        });

        cancelBtn?.addEventListener('click', () => {
            modal.hidden = true;
        });

        modal.querySelector('.bootstrap-modal__backdrop')?.addEventListener('click', () => {
            modal.hidden = true;
        });

        confirmBtn?.addEventListener('click', async () => {
            const client = getExplorerClient();
            if (!client) return;

            confirmBtn.disabled = true;
            cancelBtn.disabled = true;
            confirmBtn.textContent = 'Resetting…';
            if (errorEl) errorEl.hidden = true;

            try {
                const result = await client.resetGraph();
                modal.hidden = true;
                if (statusEl) statusEl.textContent = `Done — ${result.requeued ?? 0} conversation(s) queued.`;
                window.GraphManager?.reload?.({ full: true });
            } catch (err) {
                console.error('resetGraph failed', err);
                if (errorEl) {
                    errorEl.textContent = 'Reset failed — is Neo4j running?';
                    errorEl.hidden = false;
                }
            } finally {
                confirmBtn.disabled = false;
                cancelBtn.disabled = false;
                confirmBtn.textContent = 'Yes, nuke it';
            }
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
            wireResetButton();
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
