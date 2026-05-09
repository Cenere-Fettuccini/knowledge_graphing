(function () {
    const http = window.AIManagerHttp;

    window.AIManagerClients = window.AIManagerClients || {};
    window.AIManagerClients.credits = {
        async getCredits() {
            return await http.get('/api/credits-app');
        },

        async getMismatches() {
            return await http.get('/api/credits-app/mismatches');
        },

        async importLimits(text) {
            return await http.post('/api/credits-app/limits/import', { text });
        },
    };
})();
