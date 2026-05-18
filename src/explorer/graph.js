// graph.js — 3D Zen Mesh Network
// Requires: section-owned explorer client, ColorManager, and Panel

(function () {
    function getExplorerClient() {
        return window.AIManagerShell?.clients?.explorer || window.AIManagerClients?.explorer;
    }

    // ── State ──────────────────────────────────────────────────────────────────

    let canvas, ctx, wrap;
    let W = 0, H = 0;           // canvas pixel dims (post-DPR)
    let dpr = 1;

    let graphData = { nodes: [], edges: [] };
    let activeFilters = new Set();
    let activeEdgeFilters = new Set();
    let searchQuery = "";
    let activeNodeId = null;
    let hoveredId = null;
    let currentLimit = 100;
    let reloadTimer = null;
    const RELOAD_INTERVAL_MS = 60000;

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

    // ── Node placement — Force-Directed 3D Semantic Layout ──────────────────────────

    function placeNodes(nodes, edges) {
        // 1. Initial deterministic placement (random scatter in small volume)
        nodes.forEach((n, i) => {
            let seed = 0;
            const idStr = String(n.id || i);
            for (let j = 0; j < idStr.length; j++) {
                seed = ((seed << 5) - seed) + idStr.charCodeAt(j);
                seed |= 0;
            }
            seed = Math.abs(seed) || 1;
            function rand() {
                let x = Math.sin(seed++) * 10000;
                return x - Math.floor(x);
            }

            n.x3d = (rand() - 0.5) * 150;
            n.y3d = (rand() - 0.5) * 150;
            n.z3d = (rand() - 0.5) * 150;
            n.vx = 0; n.vy = 0; n.vz = 0;
            n.baseR = 2.8 + rand() * 2.2;
            n.animScale = 0;    // must be set here so tick() can animate isolated nodes
            n.edgeProgress = 0;
        });

        if (!edges || edges.length === 0) return;

        // 2. Pre-calculate force layout (fast background simulation)
        const iterations = 150;
        const repulseStrength = 6000;
        const linkStrength = 0.05;
        const gravity = 0.01;
        let damping = 0.85;

        for (let iter = 0; iter < iterations; iter++) {
            // Repulsion (N^2)
            for (let i = 0; i < nodes.length; i++) {
                for (let j = i + 1; j < nodes.length; j++) {
                    const n1 = nodes[i];
                    const n2 = nodes[j];
                    let dx = n1.x3d - n2.x3d;
                    let dy = n1.y3d - n2.y3d;
                    let dz = n1.z3d - n2.z3d;
                    let distSq = dx*dx + dy*dy + dz*dz;
                    if (distSq === 0) { dx = 0.1; dy = 0.1; dz = 0.1; distSq = 0.03; }
                    
                    if (distSq < 40000) { // optimization: ignore far nodes
                        const force = repulseStrength / distSq;
                        const fx = dx * force;
                        const fy = dy * force;
                        const fz = dz * force;
                        n1.vx += fx; n1.vy += fy; n1.vz += fz;
                        n2.vx -= fx; n2.vy -= fy; n2.vz -= fz;
                    }
                }
            }

            // Attraction (Edges)
            edges.forEach(e => {
                const n1 = nodes[e.si];
                const n2 = nodes[e.ti];
                if (!n1 || !n2) return;
                
                let dx = n2.x3d - n1.x3d;
                let dy = n2.y3d - n1.y3d;
                let dz = n2.z3d - n1.z3d;
                
                // Weight by edge type
                let strength = linkStrength;
                if (e.type === 'ABOUT' || e.type === 'WORKS_ON') strength *= 1.5;
                if (e.type === 'SUPPORTED_BY' || e.type === 'WEAKENED_BY' || e.type === 'EXTRACTED_FROM') strength *= 1.2;

                const fx = dx * strength;
                const fy = dy * strength;
                const fz = dz * strength;
                
                n1.vx += fx; n1.vy += fy; n1.vz += fz;
                n2.vx -= fx; n2.vy -= fy; n2.vz -= fz;
            });

            // Gravity & Position Update
            nodes.forEach(n => {
                // Semantic Gravity: Pull core entities to exact center strongly
                let nodeGravity = gravity;
                if (n.label === 'User' || n.label === 'AIManager') nodeGravity = 0.08;

                n.vx -= n.x3d * nodeGravity;
                n.vy -= n.y3d * nodeGravity;
                n.vz -= n.z3d * nodeGravity;

                // Apply velocity with damping
                n.vx *= damping;
                n.vy *= damping;
                n.vz *= damping;

                // Move node
                n.x3d += n.vx;
                n.y3d += n.vy;
                n.z3d += n.vz;
            });
            
            damping *= 0.98; // cool down
        }

        // 3. Center the graph and prep branching animation
        let cx = 0, cy = 0, cz = 0;
        nodes.forEach(n => { cx += n.x3d; cy += n.y3d; cz += n.z3d; });
        if (nodes.length > 0) {
            cx /= nodes.length; cy /= nodes.length; cz /= nodes.length;
            
            // Build adjacency for BFS
            const adj = new Map();
            nodes.forEach(n => adj.set(n._idx, []));
            edges.forEach(e => {
                if (adj.has(e.si)) adj.get(e.si).push(e.ti);
                if (adj.has(e.ti)) adj.get(e.ti).push(e.si);
            });

            // Find root (User or AIManager, else highest degree)
            let rootIdx = 0;
            let root = nodes.find(n => n.label === 'User') || nodes.find(n => n.label === 'AIManager');
            if (root) {
                rootIdx = root._idx;
            } else {
                let maxDeg = -1;
                adj.forEach((neighbors, i) => {
                    if (neighbors.length > maxDeg) { maxDeg = neighbors.length; rootIdx = i; }
                });
            }

            // BFS to assign parent nodes for branching animation
            nodes.forEach(n => { n.depth = -1; n.parentId = -1; });
            nodes[rootIdx].depth = 0;
            nodes[rootIdx].parentId = rootIdx;
            
            const queue = [rootIdx];
            while (queue.length > 0) {
                const curr = queue.shift();
                adj.get(curr).forEach(neighbor => {
                    if (nodes[neighbor].depth === -1) {
                        nodes[neighbor].depth = nodes[curr].depth + 1;
                        nodes[neighbor].parentId = curr;
                        queue.push(neighbor);
                    }
                });
            }

            nodes.forEach((n, i) => { 
                if (n.depth === -1) {
                    n.depth = 1;
                    n.parentId = rootIdx; // tie disconnected nodes to root
                }
                
                n.targetX = n.x3d - cx; 
                n.targetY = n.y3d - cy; 
                n.targetZ = n.z3d - cz; 
                
                // Initialize exactly at final positions for branching edge animation
                n.x3d = n.targetX;
                n.y3d = n.targetY;
                n.z3d = n.targetZ;
                
                n.animScale = 0; // 0 = invisible, 1 = fully popped
                n.edgeProgress = 0; // branch growth from parent (0 to 1)
            });
            nodes[rootIdx].animScale = 1; // Root pops instantly
            nodes[rootIdx].edgeProgress = 1;
        }
    }

    // ── Incremental merge ─────────────────────────────────────────────────────
    // Preserves positions/animation state of nodes that survive between reloads.
    // Only newly-arrived nodes get fresh placement + a short relaxation pass.

    function mergeGraphData(newNodes, newEdges) {
        const oldById = new Map(graphData.nodes.map(n => [n.id, n]));
        const newIds = new Set(newNodes.map(n => n.id));

        // Carry-over existing position/animation state; mark genuinely new nodes.
        const merged = newNodes.map((n, i) => {
            const prev = oldById.get(n.id);
            if (prev) {
                // If it was previously fading out and reappeared, revive it.
                prev._dying = false;
                return Object.assign(prev, n, { _idx: i, _isNew: false });
            }
            return { ...n, _idx: i, _isNew: true, _dying: false,
                     x3d: 0, y3d: 0, z3d: 0,
                     vx: 0, vy: 0, vz: 0,
                     animScale: 0, edgeProgress: 0 };
        });

        // Keep nodes that vanished so they can fade out; they hold no incoming
        // edges in the rebuilt edge list, so they just shrink and drop off.
        graphData.nodes.forEach(prev => {
            if (newIds.has(prev.id)) return;
            if (prev.animScale <= 0.02) return; // already invisible — drop permanently
            prev._dying = true;
            prev._idx = merged.length;
            merged.push(prev);
        });

        const newNodeList = merged.filter(n => n._isNew);

        // Seed new-node positions near a connected, already-placed anchor if possible.
        const idxByID = new Map(merged.map((n, i) => [n.id, i]));
        newNodeList.forEach(n => {
            let anchor = null;
            for (const e of newEdges) {
                const s = e.source ?? e.from;
                const t = e.target ?? e.to;
                if (s === n.id) {
                    const a = merged[idxByID.get(t)];
                    if (a && !a._isNew) { anchor = a; break; }
                } else if (t === n.id) {
                    const a = merged[idxByID.get(s)];
                    if (a && !a._isNew) { anchor = a; break; }
                }
            }
            const j = Math.abs((n.id || '').split('').reduce((s, c) => ((s << 5) - s) + c.charCodeAt(0), 0)) || 1;
            const r = () => { const x = Math.sin(j * 9301 + 49297) * 10000; return x - Math.floor(x); };
            const jitter = 40;
            if (anchor) {
                n.x3d = anchor.x3d + (r() - 0.5) * jitter;
                n.y3d = anchor.y3d + (r() - 0.5) * jitter;
                n.z3d = anchor.z3d + (r() - 0.5) * jitter;
            } else {
                n.x3d = (r() - 0.5) * 150;
                n.y3d = (r() - 0.5) * 150;
                n.z3d = (r() - 0.5) * 150;
            }
            n.baseR = n.baseR || (2.8 + r() * 2.2);
            n.depth = 1;
            n.parentId = anchor ? anchor._idx : 0;
        });

        // Rebuild edge index list. Keep source/target ids on each edge so we can
        // re-resolve si/ti after node GC.
        const edges = newEdges.reduce((acc, e) => {
            const sid = e.source ?? e.from;
            const tid = e.target ?? e.to;
            const si = idxByID.get(sid);
            const ti = idxByID.get(tid);
            if (si !== undefined && ti !== undefined) acc.push({ si, ti, sid, tid, type: e.type });
            return acc;
        }, []);

        graphData.nodes = merged;
        graphData.edges = edges;

        // Short relaxation pass — only if we added something — to nudge new nodes
        // into space without disturbing established layout much.
        if (newNodeList.length > 0) {
            relaxNewNodes(merged, edges, newNodeList);
        }

        // Removed nodes naturally drop out (no exit animation for now). Clear
        // selection/hover if they pointed at one of them.
        if (activeNodeId && !newIds.has(activeNodeId)) activeNodeId = null;
        if (hoveredId && !newIds.has(hoveredId)) hoveredId = null;
    }

    // Light force step that only moves _isNew nodes; established nodes stay put.
    function relaxNewNodes(nodes, edges, newNodes) {
        const iterations = 40;
        const repulse = 6000;
        const link = 0.05;
        let damping = 0.85;
        for (let iter = 0; iter < iterations; iter++) {
            for (const n of newNodes) { n.vx = 0; n.vy = 0; n.vz = 0; }
            for (const n of newNodes) {
                for (const m of nodes) {
                    if (m === n) continue;
                    let dx = n.x3d - m.x3d, dy = n.y3d - m.y3d, dz = n.z3d - m.z3d;
                    let d2 = dx*dx + dy*dy + dz*dz;
                    if (d2 === 0) { dx = 0.1; dy = 0.1; dz = 0.1; d2 = 0.03; }
                    if (d2 < 40000) {
                        const f = repulse / d2;
                        n.vx += dx * f; n.vy += dy * f; n.vz += dz * f;
                    }
                }
            }
            edges.forEach(e => {
                const a = nodes[e.si], b = nodes[e.ti];
                if (!a || !b) return;
                if (a._isNew) {
                    a.vx += (b.x3d - a.x3d) * link;
                    a.vy += (b.y3d - a.y3d) * link;
                    a.vz += (b.z3d - a.z3d) * link;
                }
                if (b._isNew) {
                    b.vx += (a.x3d - b.x3d) * link;
                    b.vy += (a.y3d - b.y3d) * link;
                    b.vz += (a.z3d - b.z3d) * link;
                }
            });
            for (const n of newNodes) {
                n.vx *= damping; n.vy *= damping; n.vz *= damping;
                n.x3d += n.vx;   n.y3d += n.vy;   n.z3d += n.vz;
            }
            damping *= 0.98;
        }
        // Set parent-target for pop-in animation
        newNodes.forEach(n => {
            n.targetX = n.x3d; n.targetY = n.y3d; n.targetZ = n.z3d;
        });
    }

    // ── Taxonomy sidebar ───────────────────────────────────────────────────────

    function buildTaxonomy(nodes, edges) {
        const labels = [...new Set(nodes.map(n => n.label))];
        const list = document.getElementById('taxonomyList');
        if (!list) return;
        list.innerHTML = '';
        activeFilters.clear();
        activeEdgeFilters.clear();

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
            if (cb) {
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
            }
        });

        const edgeTypes = [...new Set(edges.map(e => e.type))];
        if (edgeTypes.length > 0) {
            const separator = document.createElement('li');
            separator.innerHTML = '<div style="margin: 12px 0 6px; font-size: 10px; font-weight: 600; color: var(--fg-dim); text-transform: uppercase; letter-spacing: 0.05em;">Relationships</div>';
            list.appendChild(separator);
            
            edgeTypes.forEach(type => {
                activeEdgeFilters.add(type);
                const li = document.createElement('li');
                
                const color = window.ColorManager.getColor(type);
                
                li.innerHTML = `
            <label class="filter-item">
              <input type="checkbox" class="edge-filter-cb" value="${type}" checked>
              <span class="color-box" style="--cb-color:${color}; width: 8px; height: 2px; border-radius: 0;"></span>
              <span class="filter-name">${type}</span>
            </label>`;
                list.appendChild(li);
            });
            
            list.querySelectorAll('.edge-filter-cb').forEach(cb => {
                cb.addEventListener('change', e => {
                    if (e.target.checked) activeEdgeFilters.add(e.target.value);
                    else activeEdgeFilters.delete(e.target.value);
                });
            });
        }

        const selectAllBtn = document.getElementById('selectAllBtn');
        if (selectAllBtn) {
            selectAllBtn.onclick = () => {
                list.querySelectorAll('.filter-cb').forEach(c => { c.checked = true; activeFilters.add(c.value); });
                list.querySelectorAll('.edge-filter-cb').forEach(c => { c.checked = true; activeEdgeFilters.add(c.value); });
            };
        }
        const invertBtn = document.getElementById('invertFiltersBtn');
        if (invertBtn) {
            invertBtn.onclick = () => {
                list.querySelectorAll('.filter-cb').forEach(c => {
                    c.checked = !c.checked;
                    if (c.checked) activeFilters.add(c.value); else activeFilters.delete(c.value);
                });
                list.querySelectorAll('.edge-filter-cb').forEach(c => {
                    c.checked = !c.checked;
                    if (c.checked) activeEdgeFilters.add(c.value); else activeEdgeFilters.delete(c.value);
                });
            };
        }
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

        // Sort by z (painter's order, back to front: largest Z is back)
        const sorted = [...projected].sort((a, b) => b.p.z - a.p.z);

        // ── Edges ────────────────────────────────────────────────────────────────
        const labelsToDraw = [];
        graphData.edges.forEach(e => {
            if (!activeEdgeFilters.has(e.type)) return;
            const src = projected[e.si], tgt = projected[e.ti];
            if (!src || !tgt) return;
            if (!isVisible(src.n) || !isVisible(tgt.n)) return;

            const isRelated = (src.n.id === hoveredId || tgt.n.id === hoveredId || src.n.id === activeNodeId || tgt.n.id === activeNodeId);

            const avgScale = (src.p.scale + tgt.p.scale) * 0.5;
            let alpha = edgeAlpha * Math.min(1, avgScale * 1.4);
            // Boost alpha more when related, and base alpha for all edges slightly
            if (isRelated) alpha = Math.min(1, alpha * 4.0);
            else alpha = Math.min(1, alpha * 1.5); 

            const color = window.ColorManager.getColor(e.type);

            // Check animation states
            let drawSrcX = src.p.sx, drawSrcY = src.p.sy;
            let drawTgtX = tgt.p.sx, drawTgtY = tgt.p.sy;

            if (src.n.animScale < 1 || tgt.n.animScale < 1) {
                // If it's the BFS parent-child edge, draw partial branch
                if (tgt.n.parentId === src.n._idx && src.n.animScale >= 1) {
                    drawTgtX = src.p.sx + (tgt.p.sx - src.p.sx) * tgt.n.edgeProgress;
                    drawTgtY = src.p.sy + (tgt.p.sy - src.p.sy) * tgt.n.edgeProgress;
                } else if (src.n.parentId === tgt.n._idx && tgt.n.animScale >= 1) {
                    drawSrcX = tgt.p.sx + (src.p.sx - tgt.p.sx) * src.n.edgeProgress;
                    drawSrcY = tgt.p.sy + (src.p.sy - tgt.p.sy) * src.n.edgeProgress;
                } else {
                    return; // Cross-edges wait until both nodes are popped
                }
            }

            ctx.globalAlpha = alpha;
            ctx.beginPath();
            ctx.moveTo(drawSrcX, drawSrcY);
            ctx.lineTo(drawTgtX, drawTgtY);
            ctx.strokeStyle = color;
            ctx.lineWidth = (isRelated ? 1.5 : 0.5) * avgScale * dpr;
            ctx.stroke();
            ctx.globalAlpha = 1.0;

            if (isRelated && src.n.animScale >= 1 && tgt.n.animScale >= 1) {
                labelsToDraw.push({
                    text: e.type,
                    x: Math.round((src.p.sx + tgt.p.sx) / 2),
                    y: Math.round((src.p.sy + tgt.p.sy) / 2),
                    color: color
                });
            }
        });

        // ── Nodes ────────────────────────────────────────────────────────────────
        sorted.forEach(({ p, n }) => {
            if (!isVisible(n)) return;
            if (n.animScale === 0) return; // skip drawing if not popped yet

            const isHov = n.id === hoveredId;
            const isSel = n.id === activeNodeId;
            const r = n.baseR * p.scale * dpr * n.animScale; // Apply pop animation scale
            const color = window.ColorManager.getColor(n.label);

            // Outer ring for selected
            if (isSel) {
                ctx.globalAlpha = 0.33;
                ctx.beginPath();
                ctx.arc(p.sx, p.sy, r * 2.8, 0, Math.PI * 2);
                ctx.strokeStyle = color;
                ctx.lineWidth = 1 * dpr;
                ctx.stroke();
                ctx.globalAlpha = 1.0;
            }

            // Halo for hovered
            if (isHov && !isSel) {
                ctx.globalAlpha = 0.27;
                ctx.beginPath();
                ctx.arc(p.sx, p.sy, r * 2.2, 0, Math.PI * 2);
                ctx.strokeStyle = color;
                ctx.lineWidth = 0.8 * dpr;
                ctx.stroke();
                ctx.globalAlpha = 1.0;
            }

            // Node dot — fillStyle uses the raw color so it always matches the
            // filter chip (hex-alpha suffixes break HSL colors and look wrong on
            // dark backgrounds; use globalAlpha for any opacity variation instead)
            ctx.beginPath();
            ctx.arc(p.sx, p.sy, (isHov || isSel) ? r * 1.55 : r, 0, Math.PI * 2);
            ctx.fillStyle = color;
            ctx.fill();

            // Label — only on hover or selected
            if (isHov || isSel) {
                const label = n.name || n.id;
                const fontSize = Math.round(10 * dpr);
                ctx.font = `${fontSize}px Inter, sans-serif`;
                ctx.fillStyle = isSel ? color : 'rgba(180,176,170,0.9)';
                ctx.fillText(label, Math.round(p.sx + r * 1.6 + 3 * dpr), Math.round(p.sy + fontSize * 0.35));
            }
        });

        // ── Edge Labels (on top of nodes) ────────────────────────────────────────
        if (labelsToDraw.length > 0) {
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            labelsToDraw.forEach(lbl => {
                const fontSize = Math.round(8 * dpr);
                ctx.font = `600 ${fontSize}px Inter, sans-serif`;
                const tw = Math.round(ctx.measureText(lbl.text).width);
                const padX = Math.round(4 * dpr), padY = Math.round(2 * dpr);
                
                const rectX = Math.round(lbl.x - tw/2 - padX);
                const rectY = Math.round(lbl.y - fontSize/2 - padY);
                const rectW = tw + padX*2;
                const rectH = fontSize + padY*2;

                ctx.fillStyle = 'rgba(28,26,24,0.85)';
                ctx.beginPath();
                if (ctx.roundRect) {
                    ctx.roundRect(rectX, rectY, rectW, rectH, 3 * dpr);
                } else {
                    ctx.fillRect(rectX, rectY, rectW, rectH);
                }
                ctx.fill();
                
                ctx.fillStyle = lbl.color;
                ctx.fillText(lbl.text, lbl.x, Math.round(lbl.y + dpr));
            });
        }
    }

    // ── Animation loop ────────────────────────────────────────────────────────

    let raf, lastTs = 0;
    let hasStartedTick = false;
    function tick(ts) {
        raf = requestAnimationFrame(tick);
        if (ts - lastTs < 14) return;   // ~70fps cap
        lastTs = ts;
        
        // Node branching animation (branch growth -> node pop), plus fade-out
        // for nodes that disappeared from the latest reload (n._dying).
        if (graphData.nodes.length > 0) {
            graphData.nodes.forEach(n => {
                if (n._dying) {
                    n.animScale = Math.max(0, n.animScale - 0.12);
                    n.edgeProgress = Math.max(0, n.edgeProgress - 0.12);
                    return;
                }
                if (n.parentId !== undefined && n.parentId !== n._idx) {
                    const p = graphData.nodes[n.parentId];
                    // If parent is fully popped, start growing the edge to this node
                    if (p.animScale >= 1.0) {
                        if (n.edgeProgress < 1.0) {
                            n.edgeProgress = Math.min(1.0, n.edgeProgress + 0.05); // branch grows
                        } else if (n.animScale < 1.0) {
                            // branch reached tip, pop the node
                            n.animScale = Math.min(1.0, n.animScale + 0.15); // quick pop
                        }
                    }
                } else if (n.animScale < 1.0) {
                    // Root or disconnected nodes pop instantly
                    n.animScale = Math.min(1.0, n.animScale + 0.15);
                    n.edgeProgress = 1.0;
                }
            });

            // Garbage-collect nodes that finished fading. Re-resolve edge si/ti
            // via the persisted sid/tid since array indices shift after filter.
            const deadIds = new Set();
            graphData.nodes.forEach(n => {
                if (n._dying && n.animScale <= 0) deadIds.add(n.id);
            });
            if (deadIds.size > 0) {
                graphData.nodes = graphData.nodes.filter(n => !deadIds.has(n.id));
                const reindex = new Map();
                graphData.nodes.forEach((n, i) => {
                    n._idx = i;
                    reindex.set(n.id, i);
                });
                graphData.edges = graphData.edges.reduce((acc, e) => {
                    const si = reindex.get(e.sid);
                    const ti = reindex.get(e.tid);
                    if (si !== undefined && ti !== undefined) {
                        e.si = si; e.ti = ti;
                        acc.push(e);
                    }
                    return acc;
                }, []);
                // parentId references can become stale too — clear those that died.
                graphData.nodes.forEach(n => {
                    if (n.parentId !== undefined && !graphData.nodes[n.parentId]) {
                        n.parentId = n._idx;
                    }
                });
            }
        }
        
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

    // Apply a zoom step. Mirrors what the scroll-wheel handler does so the
    // buttons and keyboard shortcuts can't be overridden mid-click by the
    // node-focus / recenter animation loop.
    function applyZoomStep(delta) {
        isAnimating = false;
        const next = Math.max(180, Math.min(800, fov + delta));
        fov = next;
        targetFov = next;
    }

    function bindGraphControls() {
        document.getElementById('zoomInBtn')?.addEventListener('click', () => {
            applyZoomStep(40);
        });
        document.getElementById('zoomOutBtn')?.addEventListener('click', () => {
            applyZoomStep(-40);
        });
        document.getElementById('navBackBtn')?.addEventListener('click', () => {
            window.GraphManager.back();
        });
        document.getElementById('recenterBtn')?.addEventListener('click', () => {
            const c = Math.cos(0.28), s = Math.sin(0.28);
            targetMatrix = [[1, 0, 0], [0, c, -s], [0, s, c]];
            targetFov = 420;
            isAnimating = true;
        });
        const limitSelect = document.getElementById('graphLimitSelect');
        if (limitSelect) {
            const initial = parseInt(limitSelect.value, 10);
            if (Number.isFinite(initial) && initial > 0) currentLimit = initial;
            limitSelect.addEventListener('change', () => {
                const next = parseInt(limitSelect.value, 10);
                if (Number.isFinite(next) && next > 0) {
                    window.GraphManager?.setLimit?.(next);
                }
            });
        }

        // Keyboard shortcuts: "+" / "=" to zoom in, "-" / "_" to zoom out.
        // Skipped when the user is typing in an input/textarea/contenteditable
        // so the search box etc. stay unaffected. Bound on the document so
        // they work as long as the explorer page is in focus.
        if (!window.__explorerZoomKeysBound) {
            document.addEventListener('keydown', (e) => {
                // Only when the explorer's graph canvas is on-screen.
                const canvas = document.getElementById('graphCanvas');
                if (!canvas || canvas.offsetParent === null) return;
                const t = e.target;
                if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
                if (e.ctrlKey || e.metaKey || e.altKey) return;
                if (e.key === '+' || e.key === '=') {
                    e.preventDefault();
                    applyZoomStep(40);
                } else if (e.key === '-' || e.key === '_') {
                    e.preventDefault();
                    applyZoomStep(-40);
                }
            });
            window.__explorerZoomKeysBound = true;
        }
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

        // ── Focal-node nav + era filter state (S4.5 / S4.6) ────────────────
        const navStack = [];           // stack of focal node ids
        let currentEraFilter = null;   // { eraId } or { activeSelfOnly: true } or null
        let currentDepth = 1;

        function topFocal() {
            return navStack.length ? navStack[navStack.length - 1] : null;
        }

        function renderBreadcrumb() {
            const el = document.getElementById('graphBreadcrumb');
            const backBtn = document.getElementById('navBackBtn');
            if (backBtn) backBtn.style.display = navStack.length ? '' : 'none';
            if (!el) return;
            if (!navStack.length) { el.textContent = ''; el.style.display = 'none'; return; }
            el.style.display = '';
            const names = navStack.map(id => {
                const node = graphData.nodes.find(n => n.id === id);
                return node ? (node.name || id) : id;
            });
            el.textContent = '🧭 ' + names.join(' › ');
        }

        // ── Data Loading ────────────────────────────────────────────────────────
        // Two modes:
        //   - full: throw away current layout, run the whole force pass (initial
        //     load, focal-nav change, era-filter change, limit change).
        //   - incremental: keep positions of surviving nodes, only place + relax
        //     genuinely new ones. Used for the periodic poll.
        async function reload({ full = false } = {}) {
            let data = { nodes: [], edges: [], stats: null };
            const client = getExplorerClient();
            const focal = topFocal();
            try {
                if (focal) {
                    data = await client.getNeighborhood(focal, { depth: currentDepth, limit: 250 });
                } else {
                    const opts = currentEraFilter || {};
                    data = await client.getOverview(currentLimit, opts);
                }
            } catch (e) {
                console.warn('[graph3d] API unavailable, using empty graph.', e);
            }

            const incoming = data.nodes || [];
            const incomingEdges = data.edges || [];
            const isFirstLoad = graphData.nodes.length === 0;

            if (full || isFirstLoad) {
                graphData.nodes = incoming.map((n, i) => ({ ...n, _idx: i }));
                const idxByID = new Map(graphData.nodes.map((n, i) => [n.id, i]));
                graphData.edges = incomingEdges.reduce((acc, e) => {
                    const sid = e.source ?? e.from;
                    const tid = e.target ?? e.to;
                    const si = idxByID.get(sid);
                    const ti = idxByID.get(tid);
                    if (si !== undefined && ti !== undefined) acc.push({ si, ti, sid, tid, type: e.type });
                    return acc;
                }, []);
                placeNodes(graphData.nodes, graphData.edges);
            } else {
                mergeGraphData(incoming, incomingEdges);
            }

            buildTaxonomy(graphData.nodes, graphData.edges);
            draw();
            renderBreadcrumb();

            if (data.stats) {
                const el = document.getElementById('topStats');
                const n = data.stats.nodes ?? 0;
                const e = data.stats.edges ?? 0;
                const suffix = focal ? ` · focal depth ${data.stats.depth || currentDepth}` : '';
                if (el) el.textContent = `${n} Nodes · ${e} Connections${suffix}`;
            }
        }
        window.GraphManager = {
            focusNode,
            reload,
            setSearchQuery(query) {
                searchQuery = query || '';
            },
            setLimit(n) {
                const next = parseInt(n, 10);
                if (!Number.isFinite(next) || next <= 0 || next === currentLimit) return;
                currentLimit = next;
                reload({ full: true });
            },
            // ── Focal-node navigation (S4.5) ───────────────────────────────
            drillInto(nodeId) {
                if (!nodeId) return;
                navStack.push(nodeId);
                reload({ full: true });
            },
            back() {
                if (!navStack.length) return;
                navStack.pop();
                reload({ full: true });
            },
            resetNav() {
                navStack.length = 0;
                reload({ full: true });
            },
            setDepth(d) {
                const next = parseInt(d, 10);
                if (!Number.isFinite(next) || next < 1 || next > 4) return;
                currentDepth = next;
                if (navStack.length) reload({ full: true });
            },
            // ── Era filter (S4.6) ──────────────────────────────────────────
            setEraFilter(filter) {
                // filter: null | {eraId: str} | {activeSelfOnly: true}
                currentEraFilter = filter;
                if (!navStack.length) reload({ full: true });
            },
            getEraFilter() { return currentEraFilter; },
            activate() {
                if (!hasStartedTick) {
                    hasStartedTick = true;
                    requestAnimationFrame(tick);
                }
                if (reloadTimer === null) {
                    reloadTimer = setInterval(() => reload(), RELOAD_INTERVAL_MS);
                }
            },
            deactivate() {
                if (reloadTimer !== null) {
                    clearInterval(reloadTimer);
                    reloadTimer = null;
                }
            },
        };

        await reload();

        const activeSection = window.AIManagerShell?.getCurrentSectionId?.();
        if (activeSection === 'explorer') {
            window.GraphManager.activate();
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

        // Shift-click / double-click drills into a focal node (S4.5).
        wrap.addEventListener('dblclick', e => {
            const hit = hitTest(e.clientX, e.clientY);
            if (hit) window.GraphManager.drillInto(hit.id);
        });

        wrap.addEventListener('click', e => {
            if (dragging) return;
            const hit = hitTest(e.clientX, e.clientY);
            if (hit) {
                if (e.shiftKey) { window.GraphManager.drillInto(hit.id); return; }
                focusNode(hit.id);
                if (typeof Panel !== 'undefined') Panel.loadNode(hit.id);
            } else {
                // Clicked empty space
                activeNodeId = null;
                if (typeof Panel !== 'undefined') Panel.close();
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

        // Graph controls
        bindGraphControls();
    }

    function focusNode(nodeId) {
        const node = graphData.nodes.find(n => n.id === nodeId);
        if (!node) return;
        
        activeNodeId = node.id;
        
        // Bring node forward and center
        let v_curr = mulMV(transformMatrix, [node.x3d, node.y3d, node.z3d]);
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
            targetFov = Math.max(550, fov); // Bring it significantly closer
            isAnimating = true;
        }
    }
    document.addEventListener('DOMContentLoaded', initGraph);

})();
