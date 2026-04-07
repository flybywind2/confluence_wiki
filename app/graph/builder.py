from __future__ import annotations

import json
from pathlib import Path
import re

from app.core.knowledge import knowledge_href, normalize_knowledge_kind


def _space_color(space_key: str) -> str:
    palette = ["#2f855a", "#0f766e", "#b45309", "#9a3412", "#1d4ed8", "#7c3aed"]
    return palette[sum(ord(char) for char in space_key) % len(palette)]


REF_RE = re.compile(r"\[\[(?P<target>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]|\[(?P<md_label>[^\]]+)\]\((?P<md_href>[^)]+)\)")
PATH_RE = re.compile(r"(?P<href>/spaces/[^\s)]+)")


def _kind_color(kind: str, space_key: str) -> str:
    return {
        "concept": "#0f766e",
        "analysis": "#9a3412",
        "synthesis": "#1d4ed8",
        "page": _space_color(space_key),
    }.get(kind, _space_color(space_key))


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
    for match in PATH_RE.finditer(raw_text):
        target = match.group("href").strip()
        parts = target.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "spaces" and parts[2] == "pages":
            refs.append({"space_key": parts[1], "kind": "page", "slug": parts[3]})
        elif len(parts) >= 5 and parts[0] == "spaces" and parts[2] == "knowledge":
            refs.append({"space_key": parts[1], "kind": normalize_knowledge_kind(parts[3]), "slug": parts[4]})
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
    return {"nodes": filtered_nodes, "edges": filtered_edges}


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
    concept_nodes_by_space: dict[str, list[str]] = {}
    concept_page_refs: dict[str, set[tuple[str, str]]] = {}

    def register_node(node: dict) -> None:
        if selected_space and node.get("space_key") != selected_space:
            return
        nodes[node["id"]] = node

    def register_edge(source: str, target: str, edge_type: str) -> None:
        if source not in nodes or target not in nodes:
            return
        edges[(source, target, edge_type)] = {"source": source, "target": target, "type": edge_type}

    for doc in knowledge_documents:
        space_key = doc["space_key"]
        kind = normalize_knowledge_kind(doc["kind"])
        node_id = f"knowledge:{space_key}:{kind}:{doc['slug']}"
        register_node(
            {
                "id": node_id,
                "title": doc["title"],
                "space_key": space_key,
                "slug": doc["slug"],
                "kind": kind,
                "href": knowledge_href(space_key, kind, doc["slug"]),
                "color": _kind_color(kind, space_key),
            }
        )
        if kind == "concept":
            concept_nodes_by_space.setdefault(space_key, []).append(node_id)
            concept_page_refs[node_id] = set()

    for doc in knowledge_documents:
        space_key = doc["space_key"]
        kind = normalize_knowledge_kind(doc["kind"])
        node_id = f"knowledge:{space_key}:{kind}:{doc['slug']}"
        if node_id not in nodes:
            continue
        refs = _extract_refs(doc.get("source_refs") or "")
        if kind == "concept":
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
                        "slug": page["slug"],
                        "kind": "page",
                        "href": page["href"],
                        "color": _kind_color("page", page["space_key"]),
                    }
                )
                concept_page_refs.setdefault(node_id, set()).add(page_key)
                register_edge(node_id, page_node_id, "concept-source")
        if kind == "analysis":
            referenced_concepts = {
                f"knowledge:{ref['space_key']}:{normalize_knowledge_kind(ref['kind'])}:{ref['slug']}"
                for ref in refs
                if normalize_knowledge_kind(ref["kind"]) == "concept"
            }
            if not referenced_concepts:
                referenced_concepts = {
                    concept_id
                    for concept_id in concept_nodes_by_space.get(space_key, [])
                    if doc["slug"] != concept_id.rsplit(":", 1)[-1]
                }
            for concept_id in sorted(referenced_concepts):
                if concept_id in nodes:
                    register_edge(node_id, concept_id, "analysis-concept")

    for space_key, concept_ids in concept_nodes_by_space.items():
        synthesis_id = f"synthesis:{space_key}"
        register_node(
            {
                "id": synthesis_id,
                "title": f"{space_key} Synthesis",
                "space_key": space_key,
                "slug": "synthesis",
                "kind": "synthesis",
                "href": f"/spaces/{space_key}/synthesis",
                "color": _kind_color("synthesis", space_key),
            }
        )
        core_topic_id = next((concept_id for concept_id in concept_ids if concept_id.endswith(":core-topics")), None)
        for concept_id in sorted(concept_ids):
            register_edge(synthesis_id, concept_id, "synthesis-concept")
            if core_topic_id and concept_id != core_topic_id:
                register_edge(core_topic_id, concept_id, "concept-related")
        for idx, left in enumerate(concept_ids):
            left_refs = concept_page_refs.get(left, set())
            for right in concept_ids[idx + 1 :]:
                if left_refs and left_refs.intersection(concept_page_refs.get(right, set())):
                    register_edge(left, right, "concept-related")

    return {"nodes": list(nodes.values()), "edges": list(edges.values())}
