(function () {
    async function request(path, options = {}) {
        const response = await fetch(path, options);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        if (response.status === 204) {
            return null;
        }
        return await response.json();
    }

    window.AIManagerHttp = {
        request,
        get(path) {
            return request(path);
        },
        post(path, body) {
            return request(path, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
        },
        delete(path) {
            return request(path, { method: 'DELETE' });
        },
    };
})();
