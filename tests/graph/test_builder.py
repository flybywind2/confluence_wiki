from app.graph.builder import build_graph_payload


def test_graph_payload_distinguishes_hierarchy_and_wiki_edges():
    payload = build_graph_payload(
        nodes=[{"id": 1, "title": "A", "space_key": "DEMO"}, {"id": 2, "title": "B", "space_key": "DEMO"}],
        edges=[
            {"source": 1, "target": 2, "link_type": "hierarchy"},
            {"source": 2, "target": 1, "link_type": "wiki"},
        ],
    )

    assert payload["edges"][0]["type"] == "hierarchy"
    assert payload["edges"][1]["type"] == "wiki"
