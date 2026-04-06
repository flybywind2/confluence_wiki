from fastapi.testclient import TestClient

from app.main import app


def test_graph_endpoint_returns_nodes_and_edges():
    client = TestClient(app)
    response = client.get("/api/graph")

    assert response.status_code == 200
    body = response.json()
    assert "nodes" in body
    assert "edges" in body
