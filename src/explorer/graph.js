window.ColorManager = {
    map: new Map(),
    palette: [
        "#7FA38D", // Sage Green
        "#B88E7D", // Terracotta
        "#8497B0", // Dusty Slate
        "#BEAA7E", // Muted Mustard
        "#A37A87", // Mauve
        "#889C9B", // Seafoam grey
        "#D2B8A3", // Warm Sand
        "#7E8C8D", // Cool Grey
        "#C49081", // Rose clay
        "#98A886"  // Olive soft
    ],
    getColor(label) {
        if (!this.map.has(label)) {
            const index = this.map.size % this.palette.length;
            this.map.set(label, this.palette[index]);
        }
        return this.map.get(label);
    }
};

let simulation, svg, link, node;
let graphData = { nodes: [], edges: [] };
let activeNodeId = null;
let activeFilters = new Set();
let searchQuery = "";

async function initGraph() {
    const container = document.getElementById('graphCanvas');
    const width = container.clientWidth;
    const height = container.clientHeight;

    svg = d3.select("#graphCanvas").append("svg")
        .attr("width", width)
        .attr("height", height);

    const g = svg.append("g");
    const zoomBehavior = d3.zoom().extent([[0, 0], [width, height]]).scaleExtent([0.2, 3]).on("zoom", (e) => g.attr("transform", e.transform));
    svg.call(zoomBehavior);

    document.getElementById('zoomInBtn')?.addEventListener('click', () => {
        svg.transition().duration(300).call(zoomBehavior.scaleBy, 1.3);
    });
    document.getElementById('zoomOutBtn')?.addEventListener('click', () => {
        svg.transition().duration(300).call(zoomBehavior.scaleBy, 0.7);
    });
    document.getElementById('recenterBtn')?.addEventListener('click', () => {
        svg.transition().duration(500).call(zoomBehavior.transform, d3.zoomIdentity);
    });

    const data = await API.getOverview();
    graphData.nodes = data.nodes || [];
    graphData.edges = (data.edges || []).map(e => ({ source: e.source, target: e.target, type: e.type }));

    // Extract unique labels for taxonomy
    const uniqueLabels = [...new Set(graphData.nodes.map(n => n.label))];
    const taxonomyList = document.getElementById('taxonomyList');
    taxonomyList.innerHTML = '';
    
    uniqueLabels.forEach(label => {
        const color = window.ColorManager.getColor(label);
        activeFilters.add(label);
        
        const li = document.createElement('li');
        li.innerHTML = `
            <label class="filter-item">
                <input type="checkbox" class="filter-cb" value="${label}" checked>
                <span class="color-box" style="--cb-color: ${color}"></span>
                <span class="filter-name">${label}</span>
            </label>
        `;
        taxonomyList.appendChild(li);
    });

    simulation = d3.forceSimulation(graphData.nodes)
        .force("link", d3.forceLink(graphData.edges).id(d => d.id).distance(120))
        .force("charge", d3.forceManyBody().strength(-400))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collide", d3.forceCollide().radius(50));

    link = g.append("g").attr("class", "links").selectAll("line").data(graphData.edges).join("line").attr("class", "link");

    node = g.append("g").attr("class", "nodes").selectAll("g").data(graphData.nodes).join("g").attr("class", "node")
        .call(d3.drag().on("start", dragstarted).on("drag", dragged).on("end", dragended));

    node.append("circle").attr("class", "node-circle").attr("r", 14)
        .attr("fill", d => window.ColorManager.getColor(d.label));

    node.append("text").attr("class", "node-text").attr("dy", 30).attr("text-anchor", "middle").text(d => d.name);

    node.on("click", (event, d) => {
        node.classed("selected", false);
        d3.select(event.currentTarget).classed("selected", true);
        activeNodeId = d.id;
        Panel.loadNode(d.id);
    });

    simulation.on("tick", () => {
        link.attr("x1", d => d.source.x).attr("y1", d => d.source.y).attr("x2", d => d.target.x).attr("y2", d => d.target.y);
        node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

    function applyFilters() {
        node.style("display", d => {
            const matchesType = activeFilters.has(d.label);
            const matchesSearch = d.name.toLowerCase().includes(searchQuery.toLowerCase());
            d.visible = matchesType && matchesSearch;
            return d.visible ? "inline" : "none";
        });
        link.style("display", d => (d.source.visible && d.target.visible) ? "inline" : "none");
    }

    document.querySelectorAll('.filter-item').forEach(labelEl => {
        const cb = labelEl.querySelector('.filter-cb');
        
        cb.addEventListener('change', (e) => {
            if (e.target.checked) activeFilters.add(e.target.value);
            else activeFilters.delete(e.target.value);
            applyFilters();
        });

        labelEl.addEventListener('dblclick', (e) => {
            // Prevent text selection on double click
            window.getSelection().removeAllRanges();
            
            const targetValue = cb.value;
            
            // Clear all filters, only add this one
            activeFilters.clear();
            activeFilters.add(targetValue);
            
            // Update all checkboxes visually
            document.querySelectorAll('.filter-cb').forEach(otherCb => {
                otherCb.checked = (otherCb.value === targetValue);
            });
            
            applyFilters();
        });
    });

    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            searchQuery = e.target.value;
            applyFilters();
        });
    }

    const selectAllBtn = document.getElementById('selectAllBtn');
    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', () => {
            document.querySelectorAll('.filter-cb').forEach(cb => {
                cb.checked = true;
                activeFilters.add(cb.value);
            });
            applyFilters();
        });
    }

    const invertBtn = document.getElementById('invertFiltersBtn');
    if (invertBtn) {
        invertBtn.addEventListener('click', () => {
            document.querySelectorAll('.filter-cb').forEach(cb => {
                cb.checked = !cb.checked;
                if (cb.checked) activeFilters.add(cb.value);
                else activeFilters.delete(cb.value);
            });
            applyFilters();
        });
    }
    
    applyFilters();

    window.addEventListener('resize', () => {
        const newWidth = container.clientWidth;
        const newHeight = container.clientHeight;
        svg.attr("width", newWidth).attr("height", newHeight);
        simulation.force("center", d3.forceCenter(newWidth / 2, newHeight / 2));
        simulation.alpha(0.3).restart();
    });

    if (data.stats) {
        document.getElementById('topStats').innerText = `${data.stats.nodes} Nodes • ${data.stats.edges} Connections`;
    }
}

function dragstarted(event, d) { if (!event.active) simulation.alphaTarget(0.2).restart(); d.fx = d.x; d.fy = d.y; }
function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
function dragended(event, d) { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }

document.addEventListener("DOMContentLoaded", initGraph);
