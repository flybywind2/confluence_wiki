from pathlib import Path

from sqlalchemy import func, select

from app.db.models import Asset, Page, PageVersion, WikiDocument
from app.services.sync_service import SyncService


class FakeConfluenceClient:
    def __init__(self, search_ids=None, include_attachment=False, title_overrides=None):
        self.search_ids = search_ids or ["100", "200"]
        self.include_attachment = include_attachment
        self.title_overrides = title_overrides or {}

    async def fetch_descendant_pages(self, root_page_id: str):
        return [{"id": root_page_id}, {"id": "200"}]

    async def fetch_page(self, page_id: str):
        return {
            "id": page_id,
            "title": self.title_overrides.get(page_id, "Root Page" if page_id == "100" else "Child Page"),
            "space_key": "DEMO",
            "parent_id": None if page_id == "100" else "100",
            "version": 1,
            "updated_at": "2026-04-04T09:00:00+09:00",
            "body": "<h1>본문</h1><p>설명</p>",
            "webui": f"/pages/viewpage.action?pageId={page_id}",
        }

    async def search_cql(self, space_key: str, cql: str):
        return [{"id": item} for item in self.search_ids]

    async def list_attachments(self, page_id: str):
        if self.include_attachment and page_id == "100":
            return [
                {
                    "id": "att-1",
                    "filename": "diagram.png",
                    "mime_type": "image/png",
                    "download": "/download/attachments/100/diagram.png",
                }
            ]
        return []

    async def download_bytes(self, download_path: str):
        return b"fake-image"


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


def test_incremental_sync_rebuilds_indexes_from_existing_db_state(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    first_service = SyncService(settings=settings, confluence_client=FakeConfluenceClient())
    first_service.run_incremental(space_key="DEMO")

    second_service = SyncService(settings=settings, confluence_client=FakeConfluenceClient(search_ids=["100"]))
    second_service.run_incremental(space_key="DEMO")

    index_text = (tmp_path / "wiki" / "spaces" / "DEMO" / "index.md").read_text(encoding="utf-8")
    graph_text = (tmp_path / "wiki" / "global" / "graph.json").read_text(encoding="utf-8")

    assert "child-page-200" in index_text
    assert "child-page-200" in graph_text


def test_repeat_sync_does_not_duplicate_assets_or_versions(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(settings=settings, confluence_client=FakeConfluenceClient(include_attachment=True), vision_client=FakeVisionClient())
    service.run_incremental(space_key="DEMO")
    service.run_incremental(space_key="DEMO")

    session = service.session_factory()
    try:
        page_id = session.scalar(select(Page.id).where(Page.confluence_page_id == "100"))
        asset_count = session.scalar(select(func.count(Asset.id)).where(Asset.page_id == page_id))
        version_count = session.scalar(select(func.count(PageVersion.id)).where(PageVersion.page_id == page_id))
        document_count = session.scalar(select(func.count(WikiDocument.id)).where(WikiDocument.page_id == page_id))
    finally:
        session.close()

    assert asset_count == 1
    assert version_count == 1
    assert document_count == 1


def test_page_slug_stays_stable_when_title_changes(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    first_service = SyncService(settings=settings, confluence_client=FakeConfluenceClient(search_ids=["100"]))
    first_service.run_incremental(space_key="DEMO")

    renamed_service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(search_ids=["100"], title_overrides={"100": "Renamed Root Page"}),
    )
    renamed_service.run_incremental(space_key="DEMO")

    session = renamed_service.session_factory()
    try:
        page = session.scalar(select(Page).where(Page.confluence_page_id == "100"))
    finally:
        session.close()

    assert page.slug == "root-page-100"
