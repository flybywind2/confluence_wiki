from app.graph.builder import build_graph_payload, build_knowledge_graph_payload


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


def test_graph_payload_assigns_larger_radius_to_more_connected_nodes():
    payload = build_graph_payload(
        nodes=[
            {"id": "hub", "title": "Hub", "space_key": "DEMO", "kind": "page"},
            {"id": "leaf-a", "title": "Leaf A", "space_key": "DEMO", "kind": "page"},
            {"id": "leaf-b", "title": "Leaf B", "space_key": "DEMO", "kind": "page"},
        ],
        edges=[
            {"source": "hub", "target": "leaf-a", "link_type": "wiki"},
            {"source": "hub", "target": "leaf-b", "link_type": "wiki"},
        ],
    )

    by_id = {node["id"]: node for node in payload["nodes"]}
    assert by_id["hub"]["importance"] > by_id["leaf-a"]["importance"]
    assert by_id["hub"]["radius"] > by_id["leaf-a"]["radius"]


def test_graph_payload_uses_kind_weight_when_connectivity_is_equal():
    payload = build_graph_payload(
        nodes=[
            {"id": "query-doc", "title": "대표 검색 위키", "space_key": "global", "kind": "query", "source_page_count": 2},
            {"id": "keyword-doc", "title": "핵심 키워드", "space_key": "global", "kind": "keyword", "source_page_count": 2},
            {"id": "raw-page", "title": "원문 문서", "space_key": "DEMO", "kind": "page", "source_page_count": 2},
        ],
        edges=[],
    )

    by_id = {node["id"]: node for node in payload["nodes"]}
    assert by_id["query-doc"]["importance"] > by_id["keyword-doc"]["importance"] > by_id["raw-page"]["importance"]
    assert by_id["query-doc"]["radius"] > by_id["raw-page"]["radius"]


def test_knowledge_graph_annotates_nodes_with_visual_metrics():
    payload = build_knowledge_graph_payload(
        knowledge_documents=[
            {
                "title": "대표 검색 위키",
                "slug": "top-query",
                "space_key": "global",
                "kind": "query",
                "summary": "",
                "href": "/knowledge/queries/top-query",
                "source_refs": "[[spaces/DEMO/pages/demo-home-9001]]",
                "source_spaces": ["DEMO"],
            },
            {
                "title": "원문에서 정리한 키워드",
                "slug": "top-keyword",
                "space_key": "global",
                "kind": "keyword",
                "summary": "",
                "href": "/knowledge/keywords/top-keyword",
                "source_refs": "[[spaces/DEMO/pages/demo-home-9001]]",
                "source_spaces": ["DEMO"],
            },
        ],
        page_documents=[
            {
                "title": "원문 문서",
                "slug": "demo-home-9001",
                "space_key": "DEMO",
                "summary": "",
                "href": "/spaces/DEMO/pages/demo-home-9001",
            }
        ],
    )

    for node in payload["nodes"]:
        assert "importance" in node
        assert "radius" in node
        assert "label_size" in node


def test_knowledge_graph_excludes_synthesis_nodes_and_edges():
    payload = build_knowledge_graph_payload(
        knowledge_documents=[
            {
                "title": "대표 검색 위키",
                "slug": "top-query",
                "space_key": "global",
                "kind": "query",
                "summary": "",
                "href": "/knowledge/queries/top-query",
                "source_refs": "[[spaces/DEMO/pages/demo-home-9001]]",
                "source_spaces": ["DEMO"],
            },
            {
                "title": "원문에서 정리한 키워드",
                "slug": "top-keyword",
                "space_key": "global",
                "kind": "keyword",
                "summary": "",
                "href": "/knowledge/keywords/top-keyword",
                "source_refs": "[[spaces/DEMO/pages/demo-home-9001]]",
                "source_spaces": ["DEMO"],
            },
        ],
        page_documents=[
            {
                "title": "원문 문서",
                "slug": "demo-home-9001",
                "space_key": "DEMO",
                "summary": "",
                "href": "/spaces/DEMO/pages/demo-home-9001",
            }
        ],
    )

    assert all(node["kind"] != "synthesis" for node in payload["nodes"])
    assert all(edge["type"] != "synthesis-keyword" for edge in payload["edges"])


def test_knowledge_graph_uses_distinct_colors_for_keyword_and_page_nodes():
    payload = build_knowledge_graph_payload(
        knowledge_documents=[
            {
                "title": "원문에서 정리한 키워드",
                "slug": "top-keyword",
                "space_key": "global",
                "kind": "keyword",
                "summary": "",
                "href": "/knowledge/keywords/top-keyword",
                "source_refs": "[[spaces/DEMO/pages/demo-home-9001]]",
                "source_spaces": ["DEMO"],
            },
        ],
        page_documents=[
            {
                "title": "원문 문서",
                "slug": "demo-home-9001",
                "space_key": "DEMO",
                "summary": "",
                "href": "/spaces/DEMO/pages/demo-home-9001",
            }
        ],
    )

    by_kind = {node["kind"]: node for node in payload["nodes"]}
    assert by_kind["keyword"]["color"] == "#0f766e"
    assert by_kind["page"]["color"] == "#64748b"
