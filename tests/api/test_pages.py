from fastapi.testclient import TestClient

from app.main import app


def test_index_page_renders_space_selector():
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "space" in response.text.lower()
