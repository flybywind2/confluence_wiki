from pathlib import Path

from app.services.sync_service import SyncService


class FakeConfluenceClient:
    async def fetch_descendant_pages(self, root_page_id: str):
        return [{"id": root_page_id}, {"id": "200"}]

    async def fetch_page(self, page_id: str):
        return {
            "id": page_id,
            "title": "Root Page" if page_id == "100" else "Child Page",
            "space_key": "DEMO",
            "parent_id": None if page_id == "100" else "100",
            "version": 1,
            "updated_at": "2026-04-04T09:00:00+09:00",
            "body": "<h1>본문</h1><p>설명</p>",
            "webui": f"/pages/viewpage.action?pageId={page_id}",
        }

    async def search_cql(self, space_key: str, cql: str):
        return [{"id": "100"}, {"id": "200"}]

    async def list_attachments(self, page_id: str):
        return []


class FakeVisionClient:
    def describe_image(self, image_path: Path) -> str:
        return f"{image_path.name} 설명"


def test_incremental_sync_creates_markdown_and_graph_artifacts(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(settings=settings, confluence_client=FakeConfluenceClient(), vision_client=FakeVisionClient())

    result = service.run_incremental(space_key="DEMO")

    assert result.processed_pages == 2
    assert (tmp_path / "wiki" / "spaces" / "DEMO" / "pages").exists()
    assert (tmp_path / "wiki" / "spaces" / "DEMO" / "index.md").exists()
    assert (tmp_path / "wiki" / "spaces" / "DEMO" / "log.md").exists()
    assert (tmp_path / "wiki" / "global" / "graph.json").exists()
