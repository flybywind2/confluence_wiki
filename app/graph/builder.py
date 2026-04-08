from __future__ import annotations

import json
import math
from pathlib import Path
import re

from app.core.knowledge import knowledge_href, normalize_knowledge_kind, source_space_keys


def _space_color(space_key: str) -> str:
    palette = ["#2f855a", "#0f766e", "#b45309", "#9a3412", "#1d4ed8", "#7c3aed"]
    return palette[sum(ord(char) for char in space_key) % len(palette)]


REF_RE = re.compile(r"\[\[(?P<target>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]|\[(?P<md_label>[^\]]+)\]\((?P<md_href>[^)]+)\)")
PATH_RE = re.compile(r"(?P<href>/spaces/[^\s)]+)")


def _kind_color(kind: str, space_key: str) -> str:
    return {
        "keyword": "#0f766e",
        "analysis": "#9a3412",
        "query": "#7c3aed",
        "page": _space_color(space_key),
    }.get(kind, _space_color(space_key))


def _kind_importance_weight(kind: str) -> float:
    normalized = normalize_knowledge_kind(kind or "page")
    return {
        "query": 6.0,
        "keyword": 4.5,
        "entity": 4.0,
        "analysis": 3.0,
        "lint": 1.5,
        "page": 0.0,
    }.get(normalized, 0.0)


def _annotate_node_metrics(nodes: list[dict], edges: list[dict]) -> list[dict]:
    degree: dict[str, int] = {}
    inbound: dict[str, int] = {}
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        degree[source] = degree.get(source, 0) + 1
        degree[target] = degree.get(target, 0) + 1
        inbound[target] = inbound.get(target, 0) + 1

    annotated: list[dict] = []
    for node in nodes:
        kind = normalize_knowledge_kind(str(node.get("kind") or "page"))
        source_page_count = int(node.get("source_page_count") or len(node.get("source_spaces") or []) or (1 if kind == "page" else 0))
        degree_score = float(degree.get(node["id"], 0))
        inbound_score = float(inbound.get(node["id"], 0))
        importance = (
            degree_score * 1.4
            + inbound_score * 0.8
            + math.log2(source_page_count + 1) * 2.0
            + _kind_importance_weight(kind)
        )
        radius = max(8.0, min(24.0, 8.0 + math.sqrt(max(importance, 1.0)) * 2.2))
        annotated.append(
            {
                **node,
                "kind": kind,
                "importance": round(importance, 3),
                "radius": round(radius, 2),
                "label_size": round(max(11.0, min(18.0, 10.0 + radius / 3.4)), 2),
            }
        )
    return annotated


def _extract_refs(text: str) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    raw_text = text or ""
    for match in REF_RE.finditer(raw_text):
        target = (match.group("target") or match.group("md_href") or "").strip()
        if not target.startswith("/"):
            target = f"/{target}"
        parts = target.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "spaces" and parts[2] == "pages":
            refs.append({"space_key": parts[1], "kind": "page", "slug": parts[3]})
        elif len(parts) >= 5 and parts[0] == "spaces" and parts[2] == "knowledge":
            refs.append({"space_key": parts[1], "kind": normalize_knowledge_kind(parts[3]), "slug": parts[4]})
        elif len(parts) >= 3 and parts[0] == "knowledge":
            refs.append({"space_key": "global", "kind": normalize_knowledge_kind(parts[1]), "slug": parts[2]})
    for match in PATH_RE.finditer(raw_text):
        target = match.group("href").strip()
        parts = target.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "spaces" and parts[2] == "pages":
            refs.append({"space_key": parts[1], "kind": "page", "slug": parts[3]})
        elif len(parts) >= 5 and parts[0] == "spaces" and parts[2] == "knowledge":
            refs.append({"space_key": parts[1], "kind": normalize_knowledge_kind(parts[3]), "slug": parts[4]})
        elif len(parts) >= 3 and parts[0] == "knowledge":
            refs.append({"space_key": "global", "kind": normalize_knowledge_kind(parts[1]), "slug": parts[2]})
    return refs


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
    return {"nodes": _annotate_node_metrics(filtered_nodes, filtered_edges), "edges": filtered_edges}


def write_graph_cache(root: Path, payload: dict) -> Path:
    return write_named_graph_cache(root, "graph.json", payload)


def write_named_graph_cache(root: Path, filename: str, payload: dict) -> Path:
    target = root / "global" / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def build_knowledge_graph_payload(
    knowledge_documents: list[dict],
    page_documents: list[dict],
    selected_space: str | None = None,
) -> dict:
    page_lookup = {(item["space_key"], item["slug"]): item for item in page_documents}
    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str, str], dict[str, str]] = {}
    keyword_nodes_by_space: dict[str, list[str]] = {}
    keyword_page_refs: dict[str, set[tuple[str, str]]] = {}

    def register_node(node: dict) -> None:
        if selected_space:
            if node.get("kind") == "page" and node.get("space_key") != selected_space:
                return
            if node.get("kind") != "page" and selected_space not in set(node.get("source_spaces") or [node.get("space_key")]):
                return
        nodes[node["id"]] = node

    def register_edge(source: str, target: str, edge_type: str) -> None:
        if source not in nodes or target not in nodes:
            return
        edges[(source, target, edge_type)] = {"source": source, "target": target, "type": edge_type}

    for doc in knowledge_documents:
        source_spaces = doc.get("source_spaces") or source_space_keys(doc.get("source_refs"))
        if selected_space and selected_space not in set(source_spaces):
            continue
        kind = normalize_knowledge_kind(doc["kind"])
        if kind not in {"keyword", "analysis", "query"}:
            continue
        node_id = f"knowledge:{kind}:{doc['slug']}"
        register_node(
            {
                "id": node_id,
                "title": doc["title"],
                "space_key": "global",
                "source_spaces": source_spaces,
                "source_page_count": len(
                    {
                        (ref["space_key"], ref["slug"])
                        for ref in _extract_refs(doc.get("source_refs") or "")
                        if ref["kind"] == "page"
                    }
                ),
                "slug": doc["slug"],
                "kind": kind,
                "href": knowledge_href(kind, doc["slug"]),
                "color": _kind_color(kind, "global"),
            }
        )
        if kind == "keyword":
            for source_space in source_spaces:
                keyword_nodes_by_space.setdefault(source_space, []).append(node_id)
            keyword_page_refs[node_id] = set()

    for doc in knowledge_documents:
        source_spaces = doc.get("source_spaces") or source_space_keys(doc.get("source_refs"))
        kind = normalize_knowledge_kind(doc["kind"])
        if kind not in {"keyword", "analysis", "query"}:
            continue
        node_id = f"knowledge:{kind}:{doc['slug']}"
        if node_id not in nodes:
            continue
        refs = _extract_refs(doc.get("source_refs") or "")
        if kind == "keyword":
            for ref in refs:
                if ref["kind"] != "page":
                    continue
                page_key = (ref["space_key"], ref["slug"])
                page = page_lookup.get(page_key)
                if page is None:
                    continue
                page_node_id = f"page:{page['space_key']}:{page['slug']}"
                register_node(
                    {
                        "id": page_node_id,
                        "title": page["title"],
                        "space_key": page["space_key"],
                        "source_page_count": 1,
                        "slug": page["slug"],
                        "kind": "page",
                        "href": page["href"],
                        "color": _kind_color("page", page["space_key"]),
                    }
                )
                keyword_page_refs.setdefault(node_id, set()).add(page_key)
                register_edge(node_id, page_node_id, "keyword-source")
        if kind == "analysis":
            referenced_keywords = {
                f"knowledge:{normalize_knowledge_kind(ref['kind'])}:{ref['slug']}"
                for ref in refs
                if normalize_knowledge_kind(ref["kind"]) == "keyword"
            }
            if not referenced_keywords:
                referenced_keywords = {
                    keyword_id
                    for source_space in source_spaces
                    for keyword_id in keyword_nodes_by_space.get(source_space, [])
                    if doc["slug"] != keyword_id.rsplit(":", 1)[-1]
                }
            for keyword_id in sorted(referenced_keywords):
                if keyword_id in nodes:
                    register_edge(node_id, keyword_id, "analysis-keyword")

    for space_key, keyword_ids in keyword_nodes_by_space.items():
        for idx, left in enumerate(keyword_ids):
            left_refs = keyword_page_refs.get(left, set())
            for right in keyword_ids[idx + 1 :]:
                if left_refs and left_refs.intersection(keyword_page_refs.get(right, set())):
                    register_edge(left, right, "keyword-related")

    edge_list = list(edges.values())
    return {"nodes": _annotate_node_metrics(list(nodes.values()), edge_list), "edges": edge_list}
