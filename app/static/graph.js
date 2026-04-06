(async () => {
  const container = document.getElementById("graph-canvas");
  if (!container) return;

  const space = container.dataset.space;
  const query = space && space !== "all" ? `?space=${encodeURIComponent(space)}` : "";
  const response = await fetch(`/api/graph${query}`);
  const payload = await response.json();

  const width = container.clientWidth || 900;
  const height = container.clientHeight || 640;
  const svg = d3.select(container).append("svg").attr("viewBox", `0 0 ${width} ${height}`);

  const simulation = d3.forceSimulation(payload.nodes)
    .force("link", d3.forceLink(payload.edges).id(d => d.id).distance(d => d.type === "hierarchy" ? 80 : 130))
    .force("charge", d3.forceManyBody().strength(-210))
    .force("center", d3.forceCenter(width / 2, height / 2));

  const link = svg.append("g")
    .selectAll("line")
    .data(payload.edges)
    .join("line")
    .attr("stroke", d => d.type === "hierarchy" ? "#b45309" : "#1d4ed8")
    .attr("stroke-width", d => d.type === "hierarchy" ? 2.2 : 1.5)
    .attr("stroke-dasharray", d => d.type === "hierarchy" ? null : "6 4")
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
      if (d.space_key && d.slug) {
        window.location.href = `/spaces/${d.space_key}/pages/${d.slug}`;
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

  simulation.on("tick", () => {
    link
      .attr("x1", d => d.source.x)
      .attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x)
      .attr("y2", d => d.target.y);

    node.attr("transform", d => `translate(${d.x},${d.y})`);
  });
})();
