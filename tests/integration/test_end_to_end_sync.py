from pathlib import Path

import pytest
import httpx
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


class MissingAttachmentRedirectConfluenceClient(FakeConfluenceClient):
    async def download_bytes(self, download_path: str):
        request = httpx.Request("GET", f"https://mirror.example.com{download_path}")
        raise httpx.HTTPStatusError(
            "Redirect response '302 Found' for url 'https://mirror.example.com/download/attachments/100/diagram.png'",
            request=request,
            response=httpx.Response(
                302,
                headers={"location": "/pages/attachmentnotfound.action?pageId=100&filename=diagram.png"},
                request=request,
            ),
        )


class RecordingConfluenceClient(FakeConfluenceClient):
    def __init__(self, events: list[str], **kwargs):
        super().__init__(**kwargs)
        self.events = events

    async def fetch_page(self, page_id: str):
        self.events.append(f"fetch_page:{page_id}")
        return await super().fetch_page(page_id)


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
        confluence_client=FakeConfluenceClient(
            include_attachment=True,
            search_ids=["100"],
            body_overrides={"100": '<ac:image><ri:attachment ri:filename="diagram.png"></ri:attachment></ac:image>'},
        ),
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


def test_incremental_sync_fetches_remote_pages_before_opening_write_session(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    events: list[str] = []
    service = SyncService(
        settings=settings,
        confluence_client=RecordingConfluenceClient(events=events),
        vision_client=FakeVisionClient(),
    )
    real_session_factory = service.session_factory

    def wrapped_session_factory():
        events.append("session_factory")
        return real_session_factory()

    service.session_factory = wrapped_session_factory

    service.run_incremental(space_key="DEMO")

    assert "session_factory" in events
    assert "fetch_page:100" in events
    assert events.index("fetch_page:100") < events.index("session_factory")


def test_repeat_sync_does_not_duplicate_assets_or_versions(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            include_attachment=True,
            search_ids=["100"],
            body_overrides={"100": '<ac:image><ri:attachment ri:filename="diagram.png"></ri:attachment></ac:image>'},
        ),
        vision_client=FakeVisionClient(),
    )
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
    assert "[[spaces/DEMO/pages/root-page-100|Root Page]]" in log_text
    assert "# Synthesis" in synthesis_text
    assert "[[spaces/DEMO/pages/root-page-100|Root Page]]" in synthesis_text


def test_incremental_sync_creates_multiple_keyword_documents(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100", "200"],
            title_overrides={"100": "운영 대시보드", "200": "동기화 런북"},
            body_overrides={
                "100": "<h1>운영 대시보드</h1><p>핵심 지표, 경보, SLA를 설명합니다.</p>",
                "200": "<h1>동기화 런북</h1><p>배치 실행, 장애 대응, 재시도 절차를 설명합니다.</p>",
            },
        ),
    )

    service.run_incremental(space_key="DEMO")

    keyword_root = tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords"
    keyword_files = sorted(path.name for path in keyword_root.glob("*.md"))

    assert "운영-대시보드.md" in keyword_files
    assert "동기화-런북.md" in keyword_files
    assert len(keyword_files) >= 2


def test_keyword_page_contains_related_docs_and_related_keywords(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100", "200"],
            title_overrides={"100": "운영 대시보드", "200": "동기화 런북"},
            body_overrides={
                "100": "<h1>운영 대시보드</h1><p>핵심 지표, 경보, SLA를 설명합니다.</p>",
                "200": "<h1>동기화 런북</h1><p>배치 실행, 장애 대응, 재시도 절차를 설명합니다.</p>",
            },
        ),
    )

    service.run_incremental(space_key="DEMO")

    keyword_root = tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords"
    keyword_page = keyword_root / "운영-대시보드.md"
    content = keyword_page.read_text(encoding="utf-8")

    assert "## 관련 문서" in content
    assert "## 관련 주제" in content


def test_ds_department_terms_normalize_without_display_guess(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100"],
            title_overrides={"100": "삼성 DS 주간 회의록"},
            body_overrides={
                "100": (
                    "<h1>Device Solutions 운영 현황</h1>"
                    "<h2>HBM 일정</h2>"
                    "<p>삼성 DS 요청사항과 DS부문 운영 내용을 정리합니다. "
                    "Device Solutions 조직의 우선순위와 DS부문 이슈를 공유합니다.</p>"
                )
            },
        ),
    )

    service.run_incremental(space_key="DEMO")

    keyword_root = tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords"
    keyword_files = {path.name for path in keyword_root.glob("*.md")}

    assert "ds부문.md" in keyword_files
    assert "디스플레이.md" not in keyword_files
    assert "삼성디스플레이.md" not in keyword_files


def test_weak_title_uses_structural_keywords_from_headings_and_tables(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100"],
            title_overrides={"100": "주간 회의록"},
            body_overrides={
                "100": (
                    "<h1>HBM 진행 현황</h1>"
                    "<h2>수율 점검</h2>"
                    "<table><thead><tr><th>패키징</th><th>검증</th></tr></thead>"
                    "<tbody><tr><td>진행</td><td>확인</td></tr></tbody></table>"
                    "<p>HBM 수율과 패키징 검증 항목을 공유합니다.</p>"
                )
            },
        ),
    )

    service.run_incremental(space_key="DEMO")

    keyword_root = tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords"
    keyword_files = {path.name for path in keyword_root.glob("*.md")}

    assert "hbm.md" in keyword_files
    assert "수율.md" in keyword_files
    assert "패키징.md" in keyword_files
    assert "회의록.md" not in keyword_files


def test_long_document_enforces_tripled_minimum_keyword_count(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    long_body = "".join(
        [
            "<h1>주간 회의록</h1>",
            "<h2>HBM 현황</h2><p>HBM 일정과 HBM 수율을 상세히 정리합니다.</p>",
            "<h2>수율 점검</h2><p>수율 분석과 수율 개선 항목을 정리합니다.</p>",
            "<h2>패키징 상태</h2><p>패키징 공정과 패키징 일정 이슈를 공유합니다.</p>",
            "<h2>테스트 계획</h2><p>테스트 범위와 테스트 일정, 테스트 위험을 정리합니다.</p>",
            "<h2>공정 대응</h2><p>공정 변경과 공정 안정화 계획을 정리합니다.</p>",
            "<h2>설계 변경</h2><p>설계 이슈와 설계 대응 방안을 정리합니다.</p>",
            "<h2>검증 현황</h2><p>검증 결과와 검증 리스크를 정리합니다.</p>",
            "<h2>공급망 이슈</h2><p>공급망 리스크와 공급망 대응안을 정리합니다.</p>",
            "<h2>장애 대응</h2><p>장애 유형과 장애 대응 절차를 정리합니다.</p>",
            "<h2>운영 지표</h2><p>운영 지표와 운영 현황을 정리합니다.</p>",
        ]
    )

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100"],
            title_overrides={"100": "주간 회의록"},
            body_overrides={"100": long_body},
        ),
    )

    service.run_incremental(space_key="DEMO")

    keyword_root = tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords"
    keyword_files = sorted(path.name for path in keyword_root.glob("*.md"))

    assert len(keyword_files) >= 9


def test_phrase_topics_prefer_structural_meaning_bundles(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100", "200"],
            title_overrides={"100": "AI Portal 운영 점검", "200": "AI Agent 배포 회의"},
            body_overrides={
                "100": (
                    "<h1>AI Portal 운영 현황</h1>"
                    "<p>AI Portal 인증 흐름과 AI Portal 장애 대응 절차를 정리합니다.</p>"
                ),
                "200": (
                    "<h1>AI Agent 배포 절차</h1>"
                    "<p>AI Agent 운영 기준과 AI Agent 재시도 흐름을 설명합니다.</p>"
                ),
            },
        ),
    )

    service.run_incremental(space_key="DEMO")

    keyword_root = tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords"
    keyword_files = {path.name for path in keyword_root.glob("*.md")}

    assert "ai-portal.md" in keyword_files
    assert "ai-agent.md" in keyword_files
    assert "ai.md" not in keyword_files
    assert "portal.md" not in keyword_files
    assert "agent.md" not in keyword_files
    assert "# AI Portal" in (keyword_root / "ai-portal.md").read_text(encoding="utf-8")


def test_existing_phrase_topic_absorbs_related_document_even_with_weak_title(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    first_service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100"],
            title_overrides={"100": "DS Assistant 운영 개요"},
            body_overrides={
                "100": (
                    "<h1>DS Assistant 운영 개요</h1>"
                    "<p>DS Assistant 사용 흐름과 DS Assistant 공통 정책을 설명합니다.</p>"
                )
            },
        ),
    )
    first_service.run_incremental(space_key="DEMO")

    second_service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100", "200"],
            title_overrides={"100": "DS Assistant 운영 개요", "200": "주간 회의록"},
            body_overrides={
                "100": (
                    "<h1>DS Assistant 운영 개요</h1>"
                    "<p>DS Assistant 사용 흐름과 DS Assistant 공통 정책을 설명합니다.</p>"
                ),
                "200": (
                    "<h1>장애 대응</h1>"
                    "<h2>Assistant 이슈 공유</h2>"
                    "<p>DS Assistant 장애 복구 절차와 DS Assistant 대응 대상을 공유합니다.</p>"
                ),
            },
        ),
    )
    second_service.run_incremental(space_key="DEMO")

    keyword_root = tmp_path / "wiki" / "spaces" / "DEMO" / "knowledge" / "keywords"
    ds_assistant = (keyword_root / "ds-assistant.md").read_text(encoding="utf-8")

    assert "DS Assistant 운영 개요" in ds_assistant
    assert "주간 회의록" in ds_assistant
    assert "ds.md" not in {path.name for path in keyword_root.glob("*.md")}


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
    assert "![[spaces/DEMO/assets/diagram.png]]" in markdown
    assert markdown.index("앞 문장") < markdown.index("![[spaces/DEMO/assets/diagram.png]]")
    assert markdown.index("![[spaces/DEMO/assets/diagram.png]]") < markdown.index("뒤 문장")


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

    assert "![[spaces/DEMO/assets/diagram one.png]]" in markdown
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


def test_attachmentnotfound_redirect_is_skipped_and_reported_in_result(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=MissingAttachmentRedirectConfluenceClient(
            include_attachment=True,
            search_ids=["100"],
            body_overrides={"100": '<ac:image><ri:attachment ri:filename="diagram.png"></ri:attachment></ac:image>'},
        ),
        vision_client=FakeVisionClient(),
    )

    result = service.run_incremental(space_key="DEMO")

    session = service.session_factory()
    try:
        page_id = session.scalar(select(Page.id).where(Page.confluence_page_id == "100"))
        asset_count = session.scalar(select(func.count(Asset.id)).where(Asset.page_id == page_id))
    finally:
        session.close()

    assert result.processed_pages == 1
    assert result.processed_assets == 0
    assert result.skipped_attachments == ["DEMO/100 diagram.png"]
    assert asset_count == 0


def test_unreferenced_attachment_image_is_not_saved_or_rendered(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100"],
            body_overrides={"100": "<p>본문에는 이미지가 없습니다.</p>"},
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

    session = service.session_factory()
    try:
        page_id = session.scalar(select(Page.id).where(Page.confluence_page_id == "100"))
        asset_count = session.scalar(select(func.count(Asset.id)).where(Asset.page_id == page_id))
    finally:
        session.close()

    assert "## 이미지" not in markdown
    assert "![[spaces/DEMO/assets/diagram.png]]" not in markdown
    assert asset_count == 0


def test_non_image_attachments_are_left_as_source_links_without_local_storage(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=FakeConfluenceClient(
            search_ids=["100"],
            body_overrides={"100": "<p>첨부 파일을 확인하세요.</p>"},
            attachment_overrides={
                "100": [
                    {
                        "id": "att-2",
                        "filename": "runbook.pdf",
                        "mime_type": "application/pdf",
                        "download": "/download/attachments/100/runbook.pdf",
                    }
                ]
            },
        ),
    )

    service.run_incremental(space_key="DEMO")
    markdown = (tmp_path / "wiki" / "spaces" / "DEMO" / "pages" / "root-page-100.md").read_text(encoding="utf-8")

    session = service.session_factory()
    try:
        page_id = session.scalar(select(Page.id).where(Page.confluence_page_id == "100"))
        asset_count = session.scalar(select(func.count(Asset.id)).where(Asset.page_id == page_id))
    finally:
        session.close()

    assert "## 첨부 파일" in markdown
    assert "[runbook.pdf](https://prod.example.com/confluence/download/attachments/100/runbook.pdf)" in markdown
    assert asset_count == 0


def test_body_image_attachmentnotfound_redirect_is_skipped_and_keeps_sync_running(tmp_path, sample_settings_dict):
    from app.core.config import Settings

    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    service = SyncService(
        settings=settings,
        confluence_client=MissingAttachmentRedirectConfluenceClient(
            search_ids=["100"],
            body_overrides={
                "100": (
                    "<p>앞 문장</p>"
                    "<p><img src=\"/download/attachments/100/missing-inline.png\" alt=\"누락이미지\" /></p>"
                    "<p>뒤 문장</p>"
                )
            },
            attachment_overrides={"100": []},
        ),
    )

    result = service.run_incremental(space_key="DEMO")
    markdown = (tmp_path / "wiki" / "spaces" / "DEMO" / "pages" / "root-page-100.md").read_text(encoding="utf-8")

    assert result.skipped_attachments == ["DEMO/100 missing-inline.png"]
    assert "앞 문장" in markdown
    assert "누락이미지" in markdown
    assert "뒤 문장" in markdown
