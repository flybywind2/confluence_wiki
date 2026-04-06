from app.clients.confluence import ConfluenceClient
from app.core.config import Settings


def test_client_uses_mirror_for_reads_and_disables_ssl_verification(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)

    client = ConfluenceClient(settings)

    assert client.base_url == "https://mirror.example.com/confluence"
    assert client.verify_ssl is False
    assert client.build_page_url("123").endswith("pageId=123")


def test_normalize_page_payload_extracts_parent_from_ancestors(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = ConfluenceClient(settings)

    payload = {
        "id": "321",
        "title": "Child",
        "space": {"key": "DEMO"},
        "version": {"number": 3, "when": "2026-04-04T10:00:00+09:00"},
        "body": {"storage": {"value": "<p>body</p>"}},
        "ancestors": [{"id": "100"}, {"id": "200"}],
        "_links": {"webui": "/pages/viewpage.action?pageId=321"},
    }

    normalized = client._normalize_page_payload(payload)

    assert normalized["parent_id"] == "200"
