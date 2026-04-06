from __future__ import annotations

import json
from pathlib import Path


def _space_color(space_key: str) -> str:
    palette = ["#2f855a", "#0f766e", "#b45309", "#9a3412", "#1d4ed8", "#7c3aed"]
    return palette[sum(ord(char) for char in space_key) % len(palette)]


def build_graph_payload(nodes: list[dict], edges: list[dict], selected_space: str | None = None) -> dict:
    if selected_space:
        allowed_ids = {node["id"] for node in nodes if node.get("space_key") == selected_space}
    else:
        allowed_ids = {node["id"] for node in nodes}

    filtered_nodes = [
        {**node, "color": node.get("color") or _space_color(node.get("space_key", ""))}
        for node in nodes
        if node["id"] in allowed_ids
    ]
    filtered_edges = [
        {"source": edge["source"], "target": edge["target"], "type": edge["link_type"]}
        for edge in edges
        if edge["source"] in allowed_ids and edge["target"] in allowed_ids
    ]
    return {"nodes": filtered_nodes, "edges": filtered_edges}


def write_graph_cache(root: Path, payload: dict) -> Path:
    target = root / "global" / "graph.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
