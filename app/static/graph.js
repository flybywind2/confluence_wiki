(async () => {
  const container = document.getElementById("graph-canvas");
  if (!container) return;

  const space = container.dataset.space;
  const view = container.dataset.view || "knowledge";
  const params = new URLSearchParams();
  if (space && space !== "all") params.set("space", space);
  if (view) params.set("view", view);
  const query = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`/api/graph${query}`);
  const payload = await response.json();
  const resetButton = document.getElementById("graph-reset");

  const width = container.clientWidth || 900;
  const height = container.clientHeight || 640;
  const svg = d3.select(container).append("svg").attr("viewBox", `0 0 ${width} ${height}`);
  const initialPositions = new Map();
  let initialLayoutCaptured = false;

  const simulation = d3.forceSimulation(payload.nodes)
    .force("link", d3.forceLink(payload.edges).id(d => d.id).distance(d => {
      if (d.type === "hierarchy" || d.type === "synthesis-keyword") return 90;
      if (d.type === "keyword-source") return 120;
      return 140;
    }))
    .force("charge", d3.forceManyBody().strength(-210))
    .force("center", d3.forceCenter(width / 2, height / 2));

  const link = svg.append("g")
    .selectAll("line")
    .data(payload.edges)
    .join("line")
    .attr("stroke", d => {
      if (d.type === "hierarchy") return "#b45309";
      if (d.type === "keyword-source") return "#0f766e";
      if (d.type === "keyword-related") return "#1d4ed8";
      if (d.type === "analysis-keyword") return "#9a3412";
      if (d.type === "synthesis-keyword") return "#334155";
      return "#1d4ed8";
    })
    .attr("stroke-width", d => d.type === "hierarchy" || d.type === "synthesis-keyword" ? 2.2 : 1.6)
    .attr("stroke-dasharray", d => d.type === "keyword-related" || d.type === "analysis-keyword" ? "6 4" : null)
    .attr("stroke-opacity", 0.65);

  const node = svg.append("g")
    .selectAll("g")
    .data(payload.nodes)
    .join("g")
    .style("cursor", "pointer")
    .call(
      d3.drag()
        .on("start", (event) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          event.subject.fx = event.subject.x;
          event.subject.fy = event.subject.y;
        })
        .on("drag", (event) => {
          event.subject.fx = event.x;
          event.subject.fy = event.y;
        })
        .on("end", (event) => {
          if (!event.active) simulation.alphaTarget(0);
          event.subject.fx = null;
          event.subject.fy = null;
        })
    )
    .on("click", (_, d) => {
      if (d.href) {
        window.location.href = d.href;
      }
    });

  node.append("circle")
    .attr("r", 10)
    .attr("fill", d => d.color || "#2f855a")
    .attr("stroke", "#fdf8ef")
    .attr("stroke-width", 2);

  node.append("text")
    .text(d => d.title)
    .attr("font-size", 11)
    .attr("dx", 14)
    .attr("dy", 4)
    .attr("fill", "#334155");

  const render = () => {
    link
      .attr("x1", d => d.source.x)
      .attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x)
      .attr("y2", d => d.target.y);

    node.attr("transform", d => `translate(${d.x},${d.y})`);
  };

  simulation.on("tick", render);
  simulation.on("end", () => {
    if (initialLayoutCaptured) return;
    payload.nodes.forEach((item) => {
      initialPositions.set(item.id, { x: item.x, y: item.y });
    });
    initialLayoutCaptured = true;
    if (resetButton) resetButton.disabled = false;
  });

  if (resetButton) {
    resetButton.addEventListener("click", () => {
      if (!initialLayoutCaptured) return;
      simulation.stop();
      payload.nodes.forEach((item) => {
        const saved = initialPositions.get(item.id);
        if (!saved) return;
        item.x = saved.x;
        item.y = saved.y;
        item.fx = null;
        item.fy = null;
      });
      render();
    });
  }
})();
