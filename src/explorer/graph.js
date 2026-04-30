// graph.js — 3D Zen Mesh Network
// Drop-in replacement for the D3 force-simulation graph.js
// Requires: ColorManager (graph.js loads after api.js which defines it)
// Contracts: API.getOverview() → { nodes, edges, stats }
//            Panel.loadNode(id) — called on node click
//            window.ColorManager.getColor(label) → hex color

(function () {

    // ── State ──────────────────────────────────────────────────────────────────

    let canvas, ctx, wrap;
    let W = 0, H = 0;           // canvas pixel dims (post-DPR)
    let dpr = 1;

    let graphData = { nodes: [], edges: [] };
    let activeFilters = new Set();
    let searchQuery = "";
    let activeNodeId = null;
    let hoveredId = null;

    // Camera
    let transformMatrix = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]; // Identity matrix
    // Initial tilt
    const c = Math.cos(0.28), s = Math.sin(0.28);
    transformMatrix = [[1, 0, 0], [0, c, -s], [0, s, c]];
    
    let dragging = false, lastMX = 0, lastMY = 0;
    let fov = 420; 
    let edgeAlpha = 0.20;
    let spinning = false; // Stopped auto-rotation
    let isAnimating = false;
    let targetMatrix = null;
    let targetFov = 420;

    // ── Projection math ────────────────────────────────────────────────────────

    function matRotX(a) {
        const c = Math.cos(a), s = Math.sin(a);
        return [[1, 0, 0], [0, c, -s], [0, s, c]];
    }
    function matRotY(a) {
        const c = Math.cos(a), s = Math.sin(a);
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]];
    }
    function mulMM(a, b) {
        return a.map(row =>
            [0, 1, 2].map(j => row.reduce((sum, _, k) => sum + row[k] * b[k][j], 0))
        );
    }
    function mulMV(m, v) {
        return m.map(row => row.reduce((s, c, i) => s + c * v[i], 0));
    }

    function project(node) {
        const [x, y, z] = mulMV(transformMatrix, [node.x3d, node.y3d, node.z3d]);
        // Perspective scale (produces the fisheye effect when fov changes)
        const pScale = fov / (fov + z + 200);
        // Base scale to fit the volume into the smallest screen dimension
        const screenScale = Math.min(W, H) / (320 * dpr); 
        // Final combined scale
        const finalScale = pScale * screenScale;
        
        return { sx: W / 2 + x * finalScale, sy: H / 2 + y * finalScale, scale: finalScale, z };
    }

    // ── Node placement — spherical + cluster by label ──────────────────────────

    function placeNodes(nodes) {
        // Collect unique labels and assign cluster centers on a sphere shell
        const labels = [...new Set(nodes.map(n => n.label))];
        const clusterCenters = {};
        labels.forEach((lbl, i) => {
            const phi = Math.acos(1 - 2 * (i + 0.5) / labels.length);
            const theta = Math.PI * (1 + Math.sqrt(5)) * i;
            const R = 180; // Increased base radius for more depth
            clusterCenters[lbl] = {
                cx: R * Math.sin(phi) * Math.cos(theta),
                cy: R * Math.sin(phi) * Math.sin(theta),
                cz: R * Math.cos(phi),
            };
        });

        nodes.forEach((n, i) => {
            const { cx, cy, cz } = clusterCenters[n.label];
            // Scatter within cluster
            const jitter = 110; // Increased jitter for a thicker volume
            const theta = Math.random() * Math.PI * 2;
            const phi = Math.acos(2 * Math.random() - 1);
            const r = Math.random() * jitter;
            n.x3d = cx + r * Math.sin(phi) * Math.cos(theta);
            n.y3d = cy + r * Math.sin(phi) * Math.sin(theta);
            n.z3d = cz + r * Math.cos(phi);
            n.baseR = 2.8 + Math.random() * 2.2;   // canvas-space base radius (pre-scale)
        });
    }

    // ── Taxonomy sidebar ───────────────────────────────────────────────────────

    function buildTaxonomy(nodes) {
        const labels = [...new Set(nodes.map(n => n.label))];
        const list = document.getElementById('taxonomyList');
        if (!list) return;
        list.innerHTML = '';

        labels.forEach(label => {
            const color = window.ColorManager.getColor(label);
            activeFilters.add(label);
            const li = document.createElement('li');
            li.innerHTML = `
        <label class="filter-item">
          <input type="checkbox" class="filter-cb" value="${label}" checked>
          <span class="color-box" style="--cb-color:${color}"></span>
          <span class="filter-name">${label}</span>
        </label>`;
            list.appendChild(li);
        });

        // Wire filter interactions
        list.querySelectorAll('.filter-item').forEach(item => {
            const cb = item.querySelector('.filter-cb');
            cb.addEventListener('change', e => {
                if (e.target.checked) activeFilters.add(e.target.value);
                else activeFilters.delete(e.target.value);
            });
            item.addEventListener('dblclick', () => {
                window.getSelection().removeAllRanges();
                const val = cb.value;
                activeFilters.clear();
                activeFilters.add(val);
                list.querySelectorAll('.filter-cb').forEach(c => {
                    c.checked = c.value === val;
                });
            });
        });

        document.getElementById('selectAllBtn')?.addEventListener('click', () => {
            list.querySelectorAll('.filter-cb').forEach(c => {
                c.checked = true;
                activeFilters.add(c.value);
            });
        });
        document.getElementById('invertFiltersBtn')?.addEventListener('click', () => {
            list.querySelectorAll('.filter-cb').forEach(c => {
                c.checked = !c.checked;
                if (c.checked) activeFilters.add(c.value);
                else activeFilters.delete(c.value);
            });
        });
    }

    // ── Visibility helpers ─────────────────────────────────────────────────────

    function isVisible(node) {
        return activeFilters.has(node.label) &&
            node.name.toLowerCase().includes(searchQuery.toLowerCase());
    }

    // ── Render loop ────────────────────────────────────────────────────────────

    function getStyle(varName) {
        return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
    }

    function draw() {
        ctx.clearRect(0, 0, W, H);

        // Project all nodes
        const projected = graphData.nodes.map(n => ({ p: project(n), n }));

        // Sort by z (painter's order, back to front)
        const sorted = [...projected].sort((a, b) => a.p.z - b.p.z);

        // ── Edges ────────────────────────────────────────────────────────────────
        graphData.edges.forEach(e => {
            const src = projected[e.si], tgt = projected[e.ti];
            if (!src || !tgt) return;
            if (!isVisible(src.n) || !isVisible(tgt.n)) return;

            const avgScale = (src.p.scale + tgt.p.scale) * 0.5;
            const alpha = edgeAlpha * Math.min(1, avgScale * 1.4);

            ctx.beginPath();
            ctx.moveTo(src.p.sx, src.p.sy);
            ctx.lineTo(tgt.p.sx, tgt.p.sy);
            ctx.strokeStyle = `rgba(160,155,148,${alpha.toFixed(3)})`;
            ctx.lineWidth = 0.5 * avgScale * dpr;
            ctx.stroke();
        });

        // ── Nodes ────────────────────────────────────────────────────────────────
        sorted.forEach(({ p, n }) => {
            if (!isVisible(n)) return;

            const isHov = n.id === hoveredId;
            const isSel = n.id === activeNodeId;
            const r = n.baseR * p.scale * dpr;
            const color = window.ColorManager.getColor(n.label);

            // Outer ring for selected
            if (isSel) {
                ctx.beginPath();
                ctx.arc(p.sx, p.sy, r * 2.8, 0, Math.PI * 2);
                ctx.strokeStyle = color + '55';
                ctx.lineWidth = 1 * dpr;
                ctx.stroke();
            }

            // Halo for hovered
            if (isHov && !isSel) {
                ctx.beginPath();
                ctx.arc(p.sx, p.sy, r * 2.2, 0, Math.PI * 2);
                ctx.strokeStyle = color + '44';
                ctx.lineWidth = 0.8 * dpr;
                ctx.stroke();
            }

            // Node dot — flat fill, no shadow, no gradient
            ctx.beginPath();
            ctx.arc(p.sx, p.sy, (isHov || isSel) ? r * 1.55 : r, 0, Math.PI * 2);
            ctx.fillStyle = color + (isSel ? 'ff' : isHov ? 'ee' : 'bb');
            ctx.fill();

            // Label — only on hover or selected
            if (isHov || isSel) {
                const label = n.name || n.id;
                const fontSize = Math.round(10 * dpr);
                ctx.font = `${fontSize}px Inter, sans-serif`;
                ctx.fillStyle = isSel ? color : 'rgba(180,176,170,0.9)';
                ctx.fillText(label, p.sx + r * 1.6 + 3 * dpr, p.sy + fontSize * 0.35);
            }
        });
    }

    // ── Animation loop ────────────────────────────────────────────────────────

    let raf, lastTs = 0;
    function tick(ts) {
        raf = requestAnimationFrame(tick);
        if (ts - lastTs < 14) return;   // ~70fps cap
        lastTs = ts;
        
        if (isAnimating && targetMatrix) {
            // Smoothly interpolate FOV
            fov += (targetFov - fov) * 0.12;
            
            // Smoothly interpolate Matrix components
            let diff = 0;
            for (let i = 0; i < 3; i++) {
                for (let j = 0; j < 3; j++) {
                    const delta = (targetMatrix[i][j] - transformMatrix[i][j]) * 0.12;
                    transformMatrix[i][j] += delta;
                    diff += Math.abs(delta);
                }
            }
            
            // Gram-Schmidt Orthogonalization to prevent matrix warping during lerp
            let m = transformMatrix;
            
            // X axis
            let lenX = Math.hypot(m[0][0], m[0][1], m[0][2]);
            m[0] = m[0].map(v => v / lenX);
            
            // Y axis = Y - (Y dot X)*X
            let dotYX = m[1][0]*m[0][0] + m[1][1]*m[0][1] + m[1][2]*m[0][2];
            m[1] = [m[1][0] - dotYX * m[0][0], m[1][1] - dotYX * m[0][1], m[1][2] - dotYX * m[0][2]];
            let lenY = Math.hypot(m[1][0], m[1][1], m[1][2]);
            m[1] = m[1].map(v => v / lenY);
            
            // Z axis = X cross Y
            m[2][0] = m[0][1]*m[1][2] - m[0][2]*m[1][1];
            m[2][1] = m[0][2]*m[1][0] - m[0][0]*m[1][2];
            m[2][2] = m[0][0]*m[1][1] - m[0][1]*m[1][0];
            
            // Stop condition
            if (diff < 0.005 && Math.abs(targetFov - fov) < 1) {
                isAnimating = false;
                fov = targetFov;
                transformMatrix = targetMatrix;
            }
        }
        
        draw();
    }

    // ── Canvas resize ─────────────────────────────────────────────────────────

    function resize() {
        const rect = wrap.getBoundingClientRect();
        dpr = window.devicePixelRatio || 1;
        W = rect.width * dpr;
        H = rect.height * dpr;
        canvas.width = W;
        canvas.height = H;
        canvas.style.width = rect.width + 'px';
        canvas.style.height = rect.height + 'px';
    }

    // ── Hit testing ───────────────────────────────────────────────────────────

    function hitTest(clientX, clientY) {
        const rect = canvas.getBoundingClientRect();
        const cx = (clientX - rect.left) * dpr;
        const cy = (clientY - rect.top) * dpr;
        let best = null, bestD = 22 * dpr;
        graphData.nodes.forEach(n => {
            if (!isVisible(n)) return;
            const p = project(n);
            const r = n.baseR * p.scale * dpr;
            const d = Math.hypot(cx - p.sx, cy - p.sy);
            if (d < Math.max(bestD, r * 2)) { bestD = d; best = n; }
        });
        return best;
    }

    // ── Tooltip ───────────────────────────────────────────────────────────────

    let tooltip;
    function showTooltip(n, clientX, clientY) {
        if (!tooltip) return;
        const rect = wrap.getBoundingClientRect();
        tooltip.style.opacity = '1';
        tooltip.style.left = (clientX - rect.left + 16) + 'px';
        tooltip.style.top = (clientY - rect.top - 4) + 'px';
        tooltip.textContent = n.name + ' · ' + n.label;
    }
    function hideTooltip() {
        if (tooltip) tooltip.style.opacity = '0';
    }

    // ── Graph controls (zoom reinterpreted as FOV) ────────────────────────────

    function bindGraphControls() {
        document.getElementById('zoomInBtn')?.addEventListener('click', () => {
            fov = Math.min(800, fov + 40);
        });
        document.getElementById('zoomOutBtn')?.addEventListener('click', () => {
            fov = Math.max(180, fov - 40);
        });
        document.getElementById('recenterBtn')?.addEventListener('click', () => {
            const c = Math.cos(0.28), s = Math.sin(0.28);
            targetMatrix = [[1, 0, 0], [0, c, -s], [0, s, c]];
            targetFov = 420;
            isAnimating = true;
        });
    }

    // ── Main init ─────────────────────────────────────────────────────────────

    async function initGraph() {
        wrap = document.getElementById('graphCanvas');
        if (!wrap) return;

        // Replace the SVG-based approach with a canvas
        wrap.innerHTML = '';

        // Tooltip overlay
        tooltip = document.createElement('div');
        tooltip.id = 'graph3d-tooltip';
        Object.assign(tooltip.style, {
            position: 'absolute',
            pointerEvents: 'none',
            opacity: '0',
            transition: 'opacity .12s',
            fontSize: '11px',
            letterSpacing: '.04em',
            textTransform: 'uppercase',
            color: 'var(--fg-dim)',
            background: 'var(--bg-module)',
            border: '1px solid var(--border-main)',
            padding: '3px 8px',
            borderRadius: '4px',
            whiteSpace: 'nowrap',
            zIndex: '20',
        });
        wrap.appendChild(tooltip);

        // Canvas
        canvas = document.createElement('canvas');
        Object.assign(canvas.style, { display: 'block', position: 'absolute', top: '0', left: '0' });
        wrap.style.position = 'relative';
        wrap.style.cursor = 'grab';
        wrap.appendChild(canvas);
        ctx = canvas.getContext('2d');

        resize();
        new ResizeObserver(resize).observe(wrap);

        // ── Fetch data ──────────────────────────────────────────────────────────
        let data = { nodes: [], edges: [], stats: null };
        try { data = await API.getOverview(); } catch (e) { console.warn('[graph3d] API unavailable, using empty graph.', e); }

        graphData.nodes = (data.nodes || []).map((n, i) => ({ ...n, _idx: i }));

        // Build index map for edge references (id → array index)
        const idxByID = new Map(graphData.nodes.map((n, i) => [n.id, i]));

        graphData.edges = (data.edges || []).reduce((acc, e) => {
            const si = idxByID.get(e.source ?? e.from);
            const ti = idxByID.get(e.target ?? e.to);
            if (si !== undefined && ti !== undefined) acc.push({ si, ti, type: e.type });
            return acc;
        }, []);

        // Assign 3D positions
        placeNodes(graphData.nodes);

        // Build taxonomy sidebar
        buildTaxonomy(graphData.nodes);

        // Stats bar
        if (data.stats) {
            const el = document.getElementById('topStats');
            if (el) el.textContent = `${data.stats.nodes} Nodes · ${data.stats.edges} Connections`;
        }

        // ── Mouse / touch events ────────────────────────────────────────────────
        wrap.addEventListener('mousedown', e => {
            dragging = true;
            lastMX = e.clientX;
            lastMY = e.clientY;
            wrap.style.cursor = 'grabbing';
        });
        window.addEventListener('mouseup', () => {
            dragging = false;
            wrap.style.cursor = 'grab';
        });
        wrap.addEventListener('mousemove', e => {
            if (dragging) {
                isAnimating = false; // Cancel animation if user grabs it
                const dx = (lastMX - e.clientX) * 0.005;
                const dy = (e.clientY - lastMY) * 0.005;
                
                // Trackball incremental rotation (Screen Space)
                const rotXMat = matRotX(dy);
                const rotYMat = matRotY(dx);
                const dm = mulMM(rotXMat, rotYMat);
                transformMatrix = mulMM(dm, transformMatrix);
                
                lastMX = e.clientX;
                lastMY = e.clientY;
                hideTooltip();
                hoveredId = null;
            } else {
                const hit = hitTest(e.clientX, e.clientY);
                hoveredId = hit ? hit.id : null;
                if (hit) showTooltip(hit, e.clientX, e.clientY);
                else hideTooltip();
            }
        });
        wrap.addEventListener('mouseleave', () => { hoveredId = null; hideTooltip(); });

        // Scroll to zoom
        wrap.addEventListener('wheel', e => {
            e.preventDefault(); // Prevent page scrolling
            isAnimating = false; // Cancel any centering animation
            
            // deltaY is positive when scrolling down (zoom out), negative when scrolling up (zoom in)
            // Increasing FOV zooms in, decreasing FOV zooms out.
            const zoomSpeed = 0.5;
            fov = Math.max(180, Math.min(800, fov - e.deltaY * zoomSpeed));
        }, { passive: false });

        wrap.addEventListener('click', e => {
            if (dragging) return;
            const hit = hitTest(e.clientX, e.clientY);
            if (hit) {
                activeNodeId = hit.id;
                if (typeof Panel !== 'undefined') Panel.loadNode(hit.id);
                
                // Bring node forward and center
                let v_curr = mulMV(transformMatrix, [hit.x3d, hit.y3d, hit.z3d]);
                let mag = Math.hypot(v_curr[0], v_curr[1], v_curr[2]);
                if (mag > 0.001) {
                    let n1 = [v_curr[0]/mag, v_curr[1]/mag, v_curr[2]/mag];
                    let crossX = -n1[1], crossY = n1[0], crossZ = 0; // cross with [0,0,-1]
                    let sin_t = Math.hypot(crossX, crossY, crossZ);
                    let cos_t = -n1[2];
                    
                    let R_delta = [[1,0,0], [0,1,0], [0,0,1]];
                    if (sin_t > 0.001) {
                        let ax = crossX / sin_t, ay = crossY / sin_t, az = crossZ / sin_t;
                        let v = 1 - cos_t;
                        R_delta = [
                            [ cos_t + ax*ax*v, ax*ay*v - az*sin_t, ax*az*v + ay*sin_t ],
                            [ ay*ax*v + az*sin_t, cos_t + ay*ay*v, ay*az*v - ax*sin_t ],
                            [ az*ax*v - ay*sin_t, az*ay*v + ax*sin_t, cos_t + az*az*v ]
                        ];
                    } else if (cos_t < 0) {
                        R_delta = [[1,0,0], [0,-1,0], [0,0,-1]]; // 180 flip
                    }
                    
                    targetMatrix = mulMM(R_delta, transformMatrix);
                    targetFov = Math.max(500, fov); // Bring it a bit closer too
                    isAnimating = true;
                }
            }
        });

        // Touch
        wrap.addEventListener('touchstart', e => {
            const t = e.touches[0];
            dragging = true; lastMX = t.clientX; lastMY = t.clientY;
        }, { passive: true });
        wrap.addEventListener('touchmove', e => {
            isAnimating = false; // Cancel animation if user grabs it
            const t = e.touches[0];
            const dx = (lastMX - t.clientX) * 0.005;
            const dy = (t.clientY - lastMY) * 0.005;
            
            const rotXMat = matRotX(dy);
            const rotYMat = matRotY(dx);
            const dm = mulMM(rotXMat, rotYMat);
            transformMatrix = mulMM(dm, transformMatrix);
            
            lastMX = t.clientX; lastMY = t.clientY;
        }, { passive: true });
        window.addEventListener('touchend', () => { dragging = false; });

        // Search
        document.getElementById('searchInput')?.addEventListener('input', e => {
            searchQuery = e.target.value;
        });

        // Graph controls
        bindGraphControls();

        // Start render loop
        requestAnimationFrame(tick);
    }

    document.addEventListener('DOMContentLoaded', initGraph);

})();