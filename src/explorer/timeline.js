/**
 * Era timeline (S4.6).
 *
 * Renders a horizontal SVG strip of :Era nodes ordered by start_date.
 * Three control modes share the same downstream "filter graph by era_id":
 *
 *   - Click an era bar  -> snap, set GraphManager era filter to that id
 *   - Drag the cursor    -> fine scrub; on release, GET /eras/active-at,
 *                           filter to the first match (or clear if none)
 *   - Date picker        -> jump cursor to that date, same active-at lookup
 *   - "∞" button         -> clear era filter (show all-time graph)
 *   - "●" button         -> active_self_only mode (no specific era id)
 */
(function () {
    function clientApi() {
        return window.AIManagerShell?.clients?.explorer || window.AIManagerClients?.explorer;
    }

    const state = {
        eras: [],
        startMs: null,
        endMs: null,
        cursorMs: null,
        activeEraId: null,
        svg: null,
        dragging: false,
    };

    function toMs(iso) {
        if (!iso) return null;
        const d = new Date(iso);
        return Number.isFinite(d.getTime()) ? d.getTime() : null;
    }

    function fmt(ms) {
        return new Date(ms).toISOString().slice(0, 10);
    }

    async function init() {
        state.svg = document.getElementById('eraTimelineSvg');
        const datePicker = document.getElementById('eraDatePicker');
        const allTime = document.getElementById('eraAllTime');
        const activeOnly = document.getElementById('eraActiveOnly');
        if (!state.svg) return;

        await reloadEras();
        bindEvents(datePicker, allTime, activeOnly);
        new ResizeObserver(render).observe(state.svg);
        render();
    }

    async function reloadEras() {
        const api = clientApi();
        if (!api) return;
        const resp = await api.getEras();
        const eras = (resp && resp.eras) || [];
        const now = Date.now();
        let minStart = Infinity, maxEnd = -Infinity;
        eras.forEach(e => {
            const s = toMs(e.start_date) ?? toMs(e.created_at);
            const en = toMs(e.end_date) ?? now;
            if (s !== null) { minStart = Math.min(minStart, s); maxEnd = Math.max(maxEnd, en); }
        });
        if (!Number.isFinite(minStart) || !Number.isFinite(maxEnd) || maxEnd <= minStart) {
            // pad a year on either side of "now" so the cursor is usable even
            // when there are no eras yet
            minStart = now - 365 * 24 * 3600 * 1000;
            maxEnd = now + 30 * 24 * 3600 * 1000;
        }
        state.eras = eras;
        state.startMs = minStart;
        state.endMs = maxEnd;
        if (state.cursorMs === null) state.cursorMs = now;
    }

    function bindEvents(datePicker, allTime, activeOnly) {
        if (allTime) {
            allTime.addEventListener('click', () => {
                state.activeEraId = null;
                window.GraphManager?.setEraFilter(null);
                render();
            });
        }
        if (activeOnly) {
            activeOnly.addEventListener('click', () => {
                state.activeEraId = null;
                window.GraphManager?.setEraFilter({ activeSelfOnly: true });
                render();
            });
        }
        if (datePicker) {
            datePicker.addEventListener('change', async () => {
                const v = datePicker.value;
                if (!v) return;
                state.cursorMs = toMs(v);
                await applyDate(v);
                render();
            });
        }
        if (state.svg) {
            state.svg.addEventListener('mousedown', onPointerDown);
            window.addEventListener('mousemove', onPointerMove);
            window.addEventListener('mouseup', onPointerUp);
        }
    }

    function xToMs(x) {
        const w = state.svg.clientWidth;
        if (!w) return state.cursorMs;
        const frac = Math.max(0, Math.min(1, x / w));
        return state.startMs + frac * (state.endMs - state.startMs);
    }

    function msToX(ms) {
        const w = state.svg.clientWidth;
        if (!w || state.endMs <= state.startMs) return 0;
        return ((ms - state.startMs) / (state.endMs - state.startMs)) * w;
    }

    function onPointerDown(e) {
        const rect = state.svg.getBoundingClientRect();
        const localX = e.clientX - rect.left;
        // Click on an era bar — snap
        const hitEra = state.eras.find(era => {
            const s = toMs(era.start_date);
            const en = toMs(era.end_date) ?? Date.now();
            if (s === null) return false;
            const x1 = msToX(s), x2 = msToX(en);
            return localX >= x1 && localX <= x2;
        });
        if (hitEra) {
            state.activeEraId = hitEra.id;
            state.cursorMs = toMs(hitEra.start_date) ?? state.cursorMs;
            window.GraphManager?.setEraFilter({ eraId: hitEra.id });
            render();
            return;
        }
        state.dragging = true;
        state.cursorMs = xToMs(localX);
        render();
    }

    function onPointerMove(e) {
        if (!state.dragging) return;
        const rect = state.svg.getBoundingClientRect();
        state.cursorMs = xToMs(e.clientX - rect.left);
        render();
    }

    async function onPointerUp() {
        if (!state.dragging) return;
        state.dragging = false;
        if (state.cursorMs !== null) {
            await applyDate(fmt(state.cursorMs));
        }
    }

    async function applyDate(iso) {
        const api = clientApi();
        if (!api) return;
        const resp = await api.getErasActiveAt(iso);
        const eras = (resp && resp.eras) || [];
        if (!eras.length) {
            state.activeEraId = null;
            window.GraphManager?.setEraFilter(null);
        } else {
            state.activeEraId = eras[0].id;
            window.GraphManager?.setEraFilter({ eraId: eras[0].id });
        }
        render();
    }

    function render() {
        if (!state.svg) return;
        const w = state.svg.clientWidth;
        const h = state.svg.clientHeight;
        if (!w || !h) return;
        state.svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
        // Clear
        while (state.svg.firstChild) state.svg.removeChild(state.svg.firstChild);

        const NS = 'http://www.w3.org/2000/svg';
        const trackY = h / 2 - 8;
        const barH = 16;

        state.eras.forEach(era => {
            const s = toMs(era.start_date);
            const en = toMs(era.end_date) ?? Date.now();
            if (s === null) return;
            const x1 = msToX(s);
            const x2 = msToX(en);
            const rect = document.createElementNS(NS, 'rect');
            rect.setAttribute('class', 'era-bar' + (era.id === state.activeEraId ? ' active' : ''));
            rect.setAttribute('x', String(x1));
            rect.setAttribute('y', String(trackY));
            rect.setAttribute('width', String(Math.max(2, x2 - x1)));
            rect.setAttribute('height', String(barH));
            rect.setAttribute('rx', '4');
            rect.dataset.eraId = era.id;
            const title = document.createElementNS(NS, 'title');
            title.textContent = `${era.name}\n${era.start_date || '?'} → ${era.end_date || 'ongoing'}`;
            rect.appendChild(title);
            state.svg.appendChild(rect);

            // Era label above the bar if there's enough room
            if (x2 - x1 > 40) {
                const text = document.createElementNS(NS, 'text');
                text.setAttribute('class', 'era-label');
                text.setAttribute('x', String(x1 + 4));
                text.setAttribute('y', String(trackY - 4));
                text.textContent = (era.name || '').slice(0, 20);
                state.svg.appendChild(text);
            }
        });

        // Cursor
        if (state.cursorMs !== null) {
            const cx = msToX(state.cursorMs);
            const cursor = document.createElementNS(NS, 'line');
            cursor.setAttribute('class', 'era-cursor');
            cursor.setAttribute('x1', String(cx));
            cursor.setAttribute('x2', String(cx));
            cursor.setAttribute('y1', '4');
            cursor.setAttribute('y2', String(h - 4));
            state.svg.appendChild(cursor);
        }
    }

    window.EraTimeline = { init, reloadEras, render };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
