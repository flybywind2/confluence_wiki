from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import Asset, Page, PageVersion, WikiDocument
from app.services.sync_service import SyncService


class FakeConfluenceClient:
    def __init__(
        self,
        search_ids=None,
        include_attachment=False,
        title_overrides=None,
        body_overrides=None,
        attachment_overrides=None,
        version_overrides=None,
        updated_at_overrides=None,
    ):
        self.search_ids = search_ids or ["100", "200"]
        self.include_attachment = include_attachment
        self.title_overrides = title_overrides or {}
        self.body_overrides = body_overrides or {}
        self.attachment_overrides = attachment_overrides or {}
        self.version_overrides = version_overrides or {}
        self.updated_at_overrides = updated_at_overrides or {}

    async def fetch_page_tree(self, root_page_id: str):
        return [{"id": root_page_id}, {"id": "200"}]

    async def fetch_page(self, page_id: str):
        return {
            "id": page_id,
            "title": self.title_overrides.get(page_id, "Root Page" if page_id == "100" else "Child Page"),
            "space_key": "DEMO",
            "parent_id": None if page_id == "100" else "100",
            "version": self.version_overrides.get(page_id, 1),
            "updated_at": self.updated_at_overrides.get(page_id, "2026-04-04T09:00:00+09:00"),
            "body": self.body_overrides.get(page_id, "<h1>본문</h1><p>설명</p>"),
            "webui": f"/pages/viewpage.action?pageId={page_id}",
        }

    async def search_cql(self, space_key: str, cql: str):
        return [{"id": item} for item in self.search_ids]

    async def list_attachments(self, page_id: str):
        if page_id in self.attachment_overrides:
            return self.attachment_overrides[page_id]
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


class FailingDownloadConfluenceClient(FakeConfluenceClient):
    async def download_bytes(self, download_path: str):
        raise RuntimeError("download failed")


class RejectingExternalImageConfluenceClient(FakeConfluenceClient):
    async def download_bytes(self, download_path: str):
        if download_path.startswith("https://cdn.example.com/"):
            raise ValueError("external downloads are not allowed")
        return await super().download_bytes(download_path)


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


def test_incremental_sync_emits_progress_logs(tmp_path, sample_settings_dict, caplog):
    import logging
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(settings=settings, confluence_client=FakeConfluenceClient(), vision_client=FakeVisionClient())

    sync_logger = logging.getLogger("app.services.sync_service")
    sync_logger.disabled = False

    with caplog.at_level(logging.INFO, logger="app.services.sync_service"):
        service.run_incremental(space_key="DEMO")

    assert "sync start mode=incremental space=DEMO pages=2" in caplog.text
    assert "processing page 1/2 id=100 title=Root Page" in caplog.text
    assert "processing page 2/2 id=200 title=Child Page" in caplog.text
    assert "sync complete mode=incremental space=DEMO pages=2 assets=0" in caplog.text


def test_incremental_sync_emits_verbose_attachment_logs(tmp_path, sample_settings_dict, caplog):
    import logging
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(include_attachment=True),
        vision_client=FakeVisionClient(),
    )

    sync_logger = logging.getLogger("app.services.sync_service")
    sync_logger.disabled = False

    with caplog.at_level(logging.DEBUG, logger="app.services.sync_service"):
        service.run_incremental(space_key="DEMO")

    assert "downloading attachment page_id=100 filename=diagram.png" in caplog.text
    assert "downloaded asset page_id=100 filename=diagram.png image=True" in caplog.text


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


def test_new_remote_version_creates_history_snapshots_and_version_metadata(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    first_service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(search_ids=["100"], version_overrides={"100": 1}),
    )
    first_service.run_incremental(space_key="DEMO")

    second_service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100"],
            version_overrides={"100": 2},
            updated_at_overrides={"100": "2026-04-05T09:00:00+09:00"},
            body_overrides={"100": "<h1>본문</h1><p>두 번째 버전 설명</p>"},
        ),
    )
    second_service.run_incremental(space_key="DEMO")

    history_root = tmp_path / "wiki" / "spaces" / "DEMO" / "history" / "root-page-100"
    assert (history_root / "v0001.md").exists()
    assert (history_root / "v0002.md").exists()

    session = second_service.session_factory()
    try:
        versions = session.scalars(
            select(PageVersion).join(Page).where(Page.confluence_page_id == "100").order_by(PageVersion.version_number)
        ).all()
    finally:
        session.close()

    assert [version.version_number for version in versions] == [1, 2]
    assert versions[0].markdown_path.endswith("history/root-page-100/v0001.md")
    assert versions[1].markdown_path.endswith("history/root-page-100/v0002.md")
    assert versions[1].summary


def test_incremental_sync_appends_log_entries_and_creates_synthesis_page(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(settings=settings, confluence_client=FakeConfluenceClient(search_ids=["100"]))
    service.run_incremental(space_key="DEMO")
    service.run_incremental(space_key="DEMO")

    log_path = tmp_path / "wiki" / "spaces" / "DEMO" / "log.md"
    synthesis_path = tmp_path / "wiki" / "spaces" / "DEMO" / "synthesis.md"

    assert log_path.exists()
    assert synthesis_path.exists()

    log_text = log_path.read_text(encoding="utf-8")
    synthesis_text = synthesis_path.read_text(encoding="utf-8")

    assert log_text.count("sync | DEMO | incremental") == 2
    assert "[[DEMO/root-page-100]]" in log_text
    assert "# DEMO Synthesis" in synthesis_text
    assert "[[DEMO/root-page-100]]" in synthesis_text


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


def test_body_images_are_rendered_inline_with_wiki_static_paths(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100"],
            body_overrides={
                "100": (
                    "<p>앞 문장</p>"
                    "<p><img src=\"/download/attachments/100/diagram.png\" alt=\"구성도\" /></p>"
                    "<p>뒤 문장</p>"
                )
            },
            attachment_overrides={
                "100": [
                    {
                        "id": "att-1",
                        "filename": "diagram.png",
                        "mime_type": "image/png",
                        "download": "/download/attachments/100/diagram.png",
                    }
                ]
            },
        ),
        vision_client=FakeVisionClient(),
    )

    service.run_incremental(space_key="DEMO")
    markdown = (tmp_path / "wiki" / "spaces" / "DEMO" / "pages" / "root-page-100.md").read_text(encoding="utf-8")

    assert "앞 문장" in markdown
    assert "![구성도](/wiki-static/spaces/DEMO/assets/diagram.png)" in markdown
    assert markdown.index("앞 문장") < markdown.index("![구성도]")
    assert markdown.index("![구성도]") < markdown.index("뒤 문장")


def test_body_image_reuses_url_encoded_attachment_filename(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100"],
            body_overrides={
                "100": (
                    "<p>앞 문장</p>"
                    "<p><img src=\"/download/attachments/100/diagram%20one.png?version=1\" alt=\"구성도\" /></p>"
                    "<p>뒤 문장</p>"
                )
            },
            attachment_overrides={
                "100": [
                    {
                        "id": "att-1",
                        "filename": "diagram one.png",
                        "mime_type": "image/png",
                        "download": "/download/attachments/100/diagram%20one.png?version=1",
                    }
                ]
            },
        ),
        vision_client=FakeVisionClient(),
    )

    service.run_incremental(space_key="DEMO")
    markdown = (tmp_path / "wiki" / "spaces" / "DEMO" / "pages" / "root-page-100.md").read_text(encoding="utf-8")

    session = service.session_factory()
    try:
        page_id = session.scalar(select(Page.id).where(Page.confluence_page_id == "100"))
        asset_count = session.scalar(select(func.count(Asset.id)).where(Asset.page_id == page_id))
    finally:
        session.close()

    assert "![구성도](/wiki-static/spaces/DEMO/assets/diagram%20one.png)" in markdown
    assert asset_count == 1


def test_body_image_download_failure_raises_and_does_not_silently_drop_content(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FailingDownloadConfluenceClient(
            search_ids=["100"],
            body_overrides={
                "100": (
                    "<p>앞 문장</p>"
                    "<p><img src=\"/download/attachments/100/diagram.png\" alt=\"구성도\" /></p>"
                    "<p>뒤 문장</p>"
                )
            },
        ),
    )

    with pytest.raises(RuntimeError, match="download failed"):
        service.run_incremental(space_key="DEMO")


def test_external_body_image_reference_is_preserved_when_mirror_download_is_rejected(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=RejectingExternalImageConfluenceClient(
            search_ids=["100"],
            body_overrides={
                "100": (
                    "<p>앞 문장</p>"
                    "<p><img src=\"https://cdn.example.com/diagram.png\" alt=\"외부구성도\" /></p>"
                    "<p>뒤 문장</p>"
                )
            },
        ),
    )

    service.run_incremental(space_key="DEMO")
    markdown = (tmp_path / "wiki" / "spaces" / "DEMO" / "pages" / "root-page-100.md").read_text(encoding="utf-8")

    assert "![외부구성도](https://cdn.example.com/diagram.png)" in markdown
