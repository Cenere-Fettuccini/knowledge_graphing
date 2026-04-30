/**
 * D3.js Force-Directed Graph - Zen Minimalist Edition
 */

let simulation, svg, link, node;
let graphData = { nodes: [], edges: [] };
let activeNodeId = null;

// Map categories to CSS variables
const colorMap = {
    'Person': 'var(--color-person)',
    'Project': 'var(--color-project)',
    'Topic': 'var(--color-topic)',
    'Belief': 'var(--color-belief)',
    'Task': 'var(--color-task)'
};

async function initGraph() {
    const container = document.getElementById('graphCanvas');
    const width = container.clientWidth;
    const height = container.clientHeight;

    svg = d3.select("#graphCanvas").append("svg")
        .attr("width", width)
        .attr("height", height);

    // Group for zoom/pan
    const g = svg.append("g");

    // Setup zoom - subtle limits
    svg.call(d3.zoom()
        .extent([[0, 0], [width, height]])
        .scaleExtent([0.2, 3])
        .on("zoom", (e) => g.attr("transform", e.transform))
    );

    // Fetch data
    const data = await API.getOverview();
    graphData.nodes = data.nodes || [];
    graphData.edges = (data.edges || []).map(e => ({
        source: e.source,
        target: e.target,
        type: e.type
    }));

    // Setup Force Simulation - gentle spacing
    simulation = d3.forceSimulation(graphData.nodes)
        .force("link", d3.forceLink(graphData.edges).id(d => d.id).distance(120))
        .force("charge", d3.forceManyBody().strength(-400))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("collide", d3.forceCollide().radius(50));

    // Draw Edges (Links)
    link = g.append("g")
        .attr("class", "links")
        .selectAll("line")
        .data(graphData.edges)
        .join("line")
        .attr("class", "link");

    // Draw Nodes
    node = g.append("g")
        .attr("class", "nodes")
        .selectAll("g")
        .data(graphData.nodes)
        .join("g")
        .attr("class", "node")
        .call(d3.drag()
            .on("start", dragstarted)
            .on("drag", dragged)
            .on("end", dragended));

    // Zen Nodes: Soft circles
    node.append("circle")
        .attr("class", "node-circle")
        .attr("r", 14)
        .attr("fill", d => colorMap[d.label] || '#CCCCCC');

    // Soft text below the node
    node.append("text")
        .attr("class", "node-text")
        .attr("dy", 30) // position below the circle
        .attr("text-anchor", "middle")
        .text(d => d.name);

    // Interactions
    node.on("click", (event, d) => {
        // Deselect all
        node.classed("selected", false);
        // Select clicked
        d3.select(event.currentTarget).classed("selected", true);
        activeNodeId = d.id;
        
        // Update Panel
        Panel.loadNode(d.id);
    });

    // Simulation Tick
    simulation.on("tick", () => {
        link
            .attr("x1", d => d.source.x)
            .attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x)
            .attr("y2", d => d.target.y);

        node
            .attr("transform", d => `translate(${d.x},${d.y})`);
    });

    // Handle window resize gracefully
    window.addEventListener('resize', () => {
        const newWidth = container.clientWidth;
        const newHeight = container.clientHeight;
        svg.attr("width", newWidth).attr("height", newHeight);
        simulation.force("center", d3.forceCenter(newWidth / 2, newHeight / 2));
        simulation.alpha(0.3).restart();
    });

    // Populate Top Stats gently
    if (data.stats) {
        document.getElementById('topStats').innerText = 
            `${data.stats.nodes} Nodes • ${data.stats.edges} Connections`;
    }
}

// Drag functions - gentle ease
function dragstarted(event, d) {
    if (!event.active) simulation.alphaTarget(0.2).restart();
    d.fx = d.x;
    d.fy = d.y;
}
function dragged(event, d) {
    d.fx = event.x;
    d.fy = event.y;
}
function dragended(event, d) {
    if (!event.active) simulation.alphaTarget(0);
    d.fx = null;
    d.fy = null;
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", initGraph);
