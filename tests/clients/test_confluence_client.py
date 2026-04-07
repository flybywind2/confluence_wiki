import pytest
import httpx

import app.clients.confluence as confluence_module
from app.clients.confluence import ConfluenceClient, MissingAttachmentRedirect
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


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_search_cql_follows_pagination(sample_settings_dict, monkeypatch):
    settings = Settings.model_validate(sample_settings_dict)
    client = ConfluenceClient(settings)
    payloads = [
        {"results": [{"id": "1"}], "_links": {"next": "/rest/api/content/search?start=1"}},
        {"results": [{"id": "2"}], "_links": {}},
    ]

    async def fake_request(method, path, **kwargs):
        return _DummyResponse(payloads.pop(0))

    monkeypatch.setattr(client, "_request", fake_request)

    results = await client.search_cql("DEMO", 'space="DEMO"')

    assert [item["id"] for item in results] == ["1", "2"]


@pytest.mark.asyncio
async def test_fetch_page_tree_walks_children_recursively(sample_settings_dict, monkeypatch):
    settings = Settings.model_validate(sample_settings_dict)
    client = ConfluenceClient(settings)
    calls = []

    async def fake_collect(path, params=None):
        calls.append(path)
        mapping = {
            "/content/100/child/page": [{"id": "200"}, {"id": "300"}],
            "/content/200/child/page": [{"id": "400"}],
            "/content/300/child/page": [],
            "/content/400/child/page": [],
        }
        return mapping[path]

    monkeypatch.setattr(client, "_collect_paginated_results", fake_collect)

    results = await client.fetch_page_tree("100")

    assert [item["id"] for item in results] == ["200", "300", "400"]
    assert "/content/100/child/page" in calls
    assert "/content/200/child/page" in calls
    assert "/content/300/child/page" in calls


def test_download_target_rewrites_prod_absolute_url_to_mirror(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = ConfluenceClient(settings)

    resolved = client._resolve_download_url("https://prod.example.com/confluence/download/attachments/100/diagram.png")

    assert resolved == "https://mirror.example.com/confluence/download/attachments/100/diagram.png"


def test_download_target_rewrites_root_relative_path_under_confluence_base(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = ConfluenceClient(settings)

    resolved = client._resolve_download_url("/download/attachments/100/diagram.png")

    assert resolved == "https://mirror.example.com/confluence/download/attachments/100/diagram.png"


def test_download_target_rejects_non_confluence_absolute_url(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = ConfluenceClient(settings)

    with pytest.raises(ValueError):
        client._resolve_download_url("https://evil.example.com/malware.png")


def test_download_target_rejects_allowed_host_outside_confluence_base(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = ConfluenceClient(settings)

    with pytest.raises(ValueError):
        client._resolve_download_url("https://prod.example.com/evil.png")


def test_download_target_rejects_relative_path_escape(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = ConfluenceClient(settings)

    with pytest.raises(ValueError):
        client._resolve_download_url("../../evil.png")


class _RedirectingAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, target_url):
        request = httpx.Request("GET", target_url)
        return httpx.Response(
            302,
            headers={"location": "/pages/attachmentnotfound.action?pageId=100&filename=diagram.png"},
            request=request,
        )


@pytest.mark.asyncio
async def test_download_bytes_raises_missing_attachment_redirect_for_attachmentnotfound_302(
    sample_settings_dict, monkeypatch
):
    settings = Settings.model_validate(sample_settings_dict)
    client = ConfluenceClient(settings)

    monkeypatch.setattr(confluence_module.httpx, "AsyncClient", _RedirectingAsyncClient)

    with pytest.raises(MissingAttachmentRedirect) as exc_info:
        await client.download_bytes("/download/attachments/100/diagram.png")

    assert "attachmentnotfound" in exc_info.value.location.casefold()
