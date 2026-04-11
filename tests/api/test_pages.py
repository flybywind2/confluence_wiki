from fastapi.testclient import TestClient
from datetime import timedelta

from sqlalchemy import select

from app.core.config import Settings
from app.core.markdown import read_markdown_document
from app.db.models import KnowledgeDocument, Page, PageVersion, Space
from app.db.session import create_session_factory
from app.demo_seed import seed_demo_content
from app.services.knowledge_service import KnowledgeService
from app.services.space_registry import ensure_global_knowledge_space
from app.main import app, create_app
from app.services.wiki_writer import write_markdown_file


def _login(client: TestClient, role: str = "viewer") -> None:
    password = {
        "viewer": "viewer-pass",
        "editor": "editor-pass",
        "admin": "admin-pass",
    }[role]
    response = client.post(
        "/auth/login",
        data={"username": role, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _append_global_knowledge_docs(settings: Settings, count: int, *, summary_prefix: str = "요약") -> None:
    session_factory = create_session_factory(settings.database_url)
    session = session_factory()
    try:
        global_space = ensure_global_knowledge_space(session)
        base_time = global_space.updated_at
        for index in range(count):
            doc = KnowledgeDocument(
                space_id=global_space.id,
                kind="analysis",
                slug=f"board-doc-{index:02d}",
                title=f"보드 문서 {index:02d}",
                markdown_path=f"global/knowledge/analyses/board-doc-{index:02d}.md",
                summary=f"# 보드 문서 {index:02d}\n\n{summary_prefix} {index:02d} 상세 설명과 근거 문장을 담습니다.",
                source_refs="",
                created_at=base_time + timedelta(minutes=index),
                updated_at=base_time + timedelta(minutes=index),
            )
            session.add(doc)
        session.commit()
    finally:
        session.close()


def test_index_page_hides_space_selector_and_document_kind_filter():
    client = TestClient(app)
    _login(client, "viewer")
    response = client.get("/")

    assert response.status_code == 200
    assert '<div class="sidebar-title">Space</div>' not in response.text
    assert ">문서 유형<" not in response.text
    assert "위키에게 묻기" in response.text
    assert 'href="/knowledge-board"' in response.text


def test_sidebar_shows_reference_metrics(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/")

    assert response.status_code == 200
    assert "참고 정보" in response.text
    assert "원본 문서 수" in response.text
    assert "지식 문서 수" in response.text
    assert "참조 공간 수" in response.text
    assert 'class="sidebar-metric-value">4<' in response.text
    assert 'class="sidebar-metric-value">2<' in response.text


def test_sidebar_search_and_generate_buttons_share_primary_action_style(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "editor")
    response = client.get("/")

    assert response.status_code == 200
    assert 'class="sidebar-action-button"' in response.text
    assert 'id="query-generator-open"' in response.text
    assert ">위키 생성</button>" in response.text
    assert 'id="query-generator-queue-summary"' in response.text
    assert 'id="query-generator-queued-list"' in response.text


def test_home_page_renders_summary_rail_without_quick_generation_panel(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/")

    assert response.status_code == 200
    assert "핵심 주제" in response.text
    assert "최근 반영된 원문" in response.text
    assert "빠른 생성" not in response.text
    assert 'data-query-seed="' not in response.text
    assert "/knowledge/keywords/" in response.text
    assert "/spaces/DEMO/pages/" in response.text
    assert 'class="home-dashboard-shell"' not in response.text
    assert 'class="hero-card home-dashboard-hero"' in response.text
    assert '<div class="home-primary">\n    <section class="hero-card home-dashboard-hero">' in response.text
    assert 'class="list-card dashboard-list-card"' in response.text


def test_wiki_static_route_serves_space_assets(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    asset_path = tmp_path / "wiki" / "spaces" / "DEMO" / "assets" / "diagram.png"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"fake-image")

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    response = client.get("/wiki-static/spaces/DEMO/assets/diagram.png")

    assert response.status_code == 200
    assert response.content == b"fake-image"


def test_search_page_shows_query_context_and_result_count(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/search?q=런북&space=DEMO")

    assert response.status_code == 200
    assert "검색 결과" in response.text
    assert "런북" in response.text
    assert "운영" in response.text or "동기화" in response.text


def test_space_home_can_filter_by_kind_and_recent_group(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/spaces/DEMO", params={"kind": "keyword", "recent": "7d"})

    assert response.status_code == 200
    assert "키워드 문서" in response.text
    assert "DEMO Lint Report" not in response.text


def test_ui_uses_space_names_instead_of_keys(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")

    home = client.get("/")
    assert home.status_code == 200
    assert "Demo Showcase" in home.text
    assert "Architecture Notes" in home.text

    page = client.get("/spaces/DEMO/pages/demo-home-9001")
    assert page.status_code == 200
    assert "Demo Showcase" in page.text


def test_search_page_shows_empty_state_for_no_results(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/search?q=없는문서&space=DEMO")

    assert response.status_code == 200
    assert "검색 결과가 없습니다." in response.text


def test_knowledge_board_renders_table_and_filters(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/knowledge-board?q=운영&kind=keyword&recent=30d")

    assert response.status_code == 200
    assert "전체 지식 게시판" in response.text
    assert '<table class="knowledge-board-table">' in response.text
    assert "운영 대시보드" in response.text
    assert "키워드 문서" in response.text
    assert "참조 공간" in response.text
    assert "원문 수" in response.text


def test_knowledge_board_paginates_and_sanitizes_summary(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)
    _append_global_knowledge_docs(settings, 15)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")

    first_page = client.get("/knowledge-board")
    second_page = client.get("/knowledge-board?page=2")

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert "page=2" in first_page.text
    assert 'class="pagination"' in first_page.text
    assert "보드 문서 14" in first_page.text
    assert "보드 문서 00" not in first_page.text
    assert "보드 문서 00" in second_page.text
    assert "# 보드 문서 14" not in first_page.text
    assert "요약 14 상세 설명과 근거 문장을 담습니다" in first_page.text


def test_home_page_paginates_long_knowledge_lists(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)
    _append_global_knowledge_docs(settings, 18, summary_prefix="홈")

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")

    first_page = client.get("/")
    second_page = client.get("/?page=2")

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert 'class="pagination"' in first_page.text
    assert "page=2" in first_page.text
    assert "보드 문서 17" in first_page.text
    assert "보드 문서 03" not in first_page.text
    assert "보드 문서 03" in second_page.text


def test_sidebar_navigation_marks_active_section(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")

    home = client.get("/")
    board = client.get("/knowledge-board")

    assert home.status_code == 200
    assert board.status_code == 200
    assert 'href="/" class="active"' in home.text
    assert 'href="/knowledge-board" class="active"' in board.text


def test_page_view_renders_breadcrumb_and_meta_description(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/spaces/DEMO/pages/demo-home-9001")

    assert response.status_code == 200
    assert "전체" in response.text
    assert "DEMO" in response.text
    assert "마지막 동기화 원문 시각" in response.text
    assert '<meta name="description"' in response.text


def test_page_view_exposes_history_navigation(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/spaces/DEMO/pages/demo-home-9001")

    assert response.status_code == 200
    assert "문서 이력" in response.text
    assert "/spaces/DEMO/pages/demo-home-9001/history" in response.text


def test_history_routes_render_revision_list_and_snapshot(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")

    history = client.get("/spaces/DEMO/pages/demo-home-9001/history")
    assert history.status_code == 200
    assert "버전 1" in history.text

    snapshot = client.get("/spaces/DEMO/pages/demo-home-9001/history/1")
    assert snapshot.status_code == 200
    assert "이전 버전 문서" in snapshot.text
    assert "Confluence Wiki Demo 홈" in snapshot.text


def test_space_home_links_to_synthesis_page(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/spaces/DEMO")

    assert response.status_code == 200
    assert "/spaces/DEMO/synthesis" in response.text


def test_synthesis_route_renders_space_summary(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/spaces/DEMO/synthesis")

    assert response.status_code == 200
    assert "Synthesis" in response.text
    assert "DEMO Synthesis" not in response.text
    assert "핵심 문서" in response.text


def test_graph_page_renders_navigation_controls_and_scope_selector_without_synthesis_legend(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/graph?space=DEMO&view=knowledge")

    assert response.status_code == 200
    assert "확대" in response.text
    assert "축소" in response.text
    assert "보기 리셋" in response.text
    assert "위치 리셋" in response.text
    assert ">전체 그래프<" in response.text
    assert "Demo Showcase" in response.text
    assert 'name="space"' in response.text
    assert "노드 범례" in response.text
    assert "키워드 문서" in response.text
    assert "검색 위키" in response.text
    assert "분석 문서" in response.text
    assert "원문 페이지" in response.text
    assert 'class="legend-toggle"' in response.text
    assert 'data-legend-group="node"' in response.text
    assert 'data-legend-key="keyword"' in response.text
    assert 'data-legend-key="page"' in response.text
    assert "링크 범례" in response.text
    assert "Keyword Source" in response.text
    assert "Keyword Related" in response.text
    assert 'data-legend-group="edge"' in response.text
    assert 'data-legend-key="keyword-source"' in response.text
    assert 'data-legend-key="analysis-keyword"' in response.text
    assert "Synthesis" not in response.text


def test_knowledge_route_renders_global_keyword_page(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/knowledge/keywords/운영-대시보드")

    assert response.status_code == 200
    assert "키워드 문서" in response.text
    assert "운영 대시보드" in response.text


def test_knowledge_page_shows_edit_link_and_raw_page_does_not(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "editor")

    knowledge_response = client.get("/knowledge/keywords/운영-대시보드")
    assert knowledge_response.status_code == 200
    assert '/knowledge/keywords/운영-대시보드/edit' in knowledge_response.text

    raw_response = client.get("/spaces/DEMO/pages/demo-home-9001")
    assert raw_response.status_code == 200
    assert '/spaces/DEMO/pages/demo-home-9001/edit' not in raw_response.text


def test_generated_knowledge_page_shows_regenerate_action(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "editor")
    response = client.get("/knowledge/keywords/운영-대시보드")

    assert response.status_code == 200
    assert 'action="/knowledge/keywords/%EC%9A%B4%EC%98%81-%EB%8C%80%EC%8B%9C%EB%B3%B4%EB%93%9C/regenerate"' in response.text
    assert "LLM 재작성" in response.text
    assert 'data-queue-regenerate="true"' in response.text
    assert 'data-regenerate-kind="keyword"' in response.text
    assert 'data-regenerate-slug="운영-대시보드"' in response.text


def test_admin_sees_delete_action_but_editor_does_not(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    editor_client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(editor_client, "editor")
    editor_response = editor_client.get("/knowledge/keywords/운영-대시보드")

    assert editor_response.status_code == 200
    assert "/knowledge/keywords/%EC%9A%B4%EC%98%81-%EB%8C%80%EC%8B%9C%EB%B3%B4%EB%93%9C/delete" not in editor_response.text
    assert "지식 삭제" not in editor_response.text

    admin_client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(admin_client, "admin")
    admin_response = admin_client.get("/knowledge/keywords/운영-대시보드")

    assert admin_response.status_code == 200
    assert 'action="/knowledge/keywords/%EC%9A%B4%EC%98%81-%EB%8C%80%EC%8B%9C%EB%B3%B4%EB%93%9C/delete"' in admin_response.text
    assert "지식 삭제" in admin_response.text


def test_admin_can_delete_knowledge_document(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "admin")

    response = client.post(
        "/knowledge/keywords/운영-대시보드/delete",
        data={"selected_space": "all"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"

    deleted = client.get("/knowledge/keywords/운영-대시보드")
    assert deleted.status_code == 404

    keyword_file = tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "운영-대시보드.md"
    assert not keyword_file.exists()

    session = create_session_factory(settings.database_url)()
    try:
        doc = session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.kind == "keyword",
                KnowledgeDocument.slug == "운영-대시보드",
            )
        )
        assert doc is None
    finally:
        session.close()


def test_analysis_knowledge_page_shows_llm_regenerate_action(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    result = KnowledgeService(settings).save_analysis(
        space_key="DEMO",
        question="운영 대시보드가 설명하는 핵심 지표는 무엇인가?",
        scope="space",
        answer="초기 답변입니다.",
        sources=[
            {
                "title": "운영 대시보드",
                "space_key": "DEMO",
                "slug": "ops-dashboard-9002",
                "kind": "page",
                "href": "/spaces/DEMO/pages/ops-dashboard-9002",
                "prod_url": "https://prod.example.com/confluence/pages/viewpage.action?pageId=9002",
            }
        ],
    )

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "editor")
    response = client.get(result["href"])

    assert response.status_code == 200
    assert "/knowledge/analyses/" in response.text
    assert "/regenerate" in response.text
    assert "LLM 재작성" in response.text


def test_global_keyword_page_shows_clickable_original_confluence_link(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/knowledge/keywords/운영-대시보드")

    assert response.status_code == 200
    assert 'href="https://prod.example.com/confluence/pages/viewpage.action?pageId=9002"' in response.text
    assert ">Confluence 원문<" in response.text


def test_keyword_knowledge_page_shows_clickable_original_confluence_links(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/knowledge/keywords/운영-대시보드")

    assert response.status_code == 200
    assert 'href="https://prod.example.com/confluence/pages/viewpage.action?pageId=9001"' in response.text
    assert 'href="https://prod.example.com/confluence/pages/viewpage.action?pageId=9002"' in response.text
    assert response.text.count(">Confluence 원문<") >= 2


def test_knowledge_page_renders_inline_source_citations_and_numbered_evidence(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    session = create_session_factory(settings.database_url)()
    try:
        global_space = session.scalar(select(Space).where(Space.space_key == "__global__"))
        document = session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.space_id == global_space.id,
                KnowledgeDocument.kind == "keyword",
                KnowledgeDocument.slug == "운영-대시보드",
            )
        )
        document.source_refs = "[[spaces/DEMO/pages/ops-dashboard-9002|운영 대시보드]]"
        session.commit()
    finally:
        session.close()

    keyword_file = tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "운영-대시보드.md"
    frontmatter, _body = read_markdown_document(keyword_file)
    write_markdown_file(
        keyword_file,
        frontmatter,
        "\n".join(
            [
                "# 운영 대시보드",
                "",
                "## 핵심 사실",
                "",
                "- 문서 수와 그래프 링크를 함께 확인한다.",
                "- 이미지 처리 상태를 wiki-static 노출 기준으로 점검한다.",
            ]
        ),
    )

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/knowledge/keywords/운영-대시보드")

    assert response.status_code == 200
    assert "원문 근거" in response.text
    assert 'class="inline-source-citation"' in response.text
    assert 'class="inline-source-date">2026-04-05<' in response.text
    assert "source-evidence-list" in response.text
    assert 'id="source-evidence-1"' in response.text
    assert 'class="source-evidence-date">2026-04-05<' in response.text
    assert 'href="https://prod.example.com/confluence/pages/viewpage.action?pageId=9002"' in response.text


def test_knowledge_edit_form_renders_markdown_body(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "editor")
    response = client.get("/knowledge/keywords/운영-대시보드/edit")

    assert response.status_code == 200
    assert 'name="title"' in response.text
    assert 'value="운영 대시보드"' in response.text
    assert "<textarea" in response.text
    assert "운영 대시보드" in response.text


def test_knowledge_edit_save_updates_rendered_content(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "editor")
    new_title = "운영 대시보드 재정리"
    new_body = "# 운영 대시보드\n\n수정된 본문입니다.\n\n- 새 메모"

    response = client.post(
        "/knowledge/keywords/운영-대시보드/edit",
        data={"title": new_title, "body": new_body},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/knowledge/keywords/%EC%9A%B4%EC%98%81-%EB%8C%80%EC%8B%9C%EB%B3%B4%EB%93%9C")

    rendered = client.get("/knowledge/keywords/운영-대시보드")
    assert rendered.status_code == 200
    assert "운영 대시보드 재정리" in rendered.text
    assert "수정된 본문입니다." in rendered.text

    keyword_file = tmp_path / "wiki" / "global" / "knowledge" / "keywords" / "운영-대시보드.md"
    frontmatter, body = read_markdown_document(keyword_file)
    assert frontmatter["title"] == new_title
    assert frontmatter["aliases"] == [new_title]
    assert "수정된 본문입니다." in body
    assert "수정된 본문입니다." in keyword_file.read_text(encoding="utf-8")


def test_keyword_regenerate_route_rebuilds_single_document_from_current_raw_sources(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    raw_page_path = tmp_path / "wiki" / "spaces" / "DEMO" / "pages" / "ops-dashboard-9002.md"
    frontmatter, body_markdown = read_markdown_document(raw_page_path)
    updated_body = body_markdown + "\n\n대시보드 경보 임계치와 알림 지연 원인을 다시 정리합니다.\n"
    write_markdown_file(raw_page_path, frontmatter, updated_body)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "editor")
    response = client.post(
        "/knowledge/keywords/운영-대시보드/regenerate",
        data={"selected_space": "DEMO"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/knowledge/keywords/%EC%9A%B4%EC%98%81-%EB%8C%80%EC%8B%9C%EB%B3%B4%EB%93%9C")

    rendered = client.get("/knowledge/keywords/운영-대시보드")
    assert rendered.status_code == 200
    assert "대시보드 경보 임계치와 알림 지연 원인을 다시 정리합니다." in rendered.text


def test_analysis_regenerate_route_rewrites_answer_from_current_raw_sources(tmp_path, sample_settings_dict, monkeypatch):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    service = KnowledgeService(settings)
    result = service.save_analysis(
        space_key="DEMO",
        question="운영 대시보드가 설명하는 핵심 지표는 무엇인가?",
        scope="space",
        answer="초기 답변입니다.",
        sources=[
            {
                "title": "운영 대시보드",
                "space_key": "DEMO",
                "slug": "ops-dashboard-9002",
                "kind": "page",
                "href": "/spaces/DEMO/pages/ops-dashboard-9002",
                "prod_url": "https://prod.example.com/confluence/pages/viewpage.action?pageId=9002",
            }
        ],
    )

    monkeypatch.setattr(
        "app.services.knowledge_service.TextLLMClient.answer_question",
        lambda self, question, contexts: "재작성된 답변입니다.\n\n근거: 현재 운영 지표와 임계치 정책을 다시 설명합니다.",
    )

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "editor")
    response = client.post(f'{result["href"]}/regenerate', data={"selected_space": "DEMO"}, follow_redirects=False)

    assert response.status_code == 303
    rendered = client.get(result["href"])
    assert rendered.status_code == 200
    assert "재작성된 답변입니다." in rendered.text


def test_query_page_renders_under_canonical_query_route(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "editor")
    build_response = client.post("/api/wiki-from-query", json={"query": "운영 대시보드"})
    assert build_response.status_code == 200
    href = build_response.json()["href"]

    response = client.get(href)
    assert response.status_code == 200
    assert "검색 위키" in response.text
    assert "운영 대시보드" in response.text


def test_history_route_backfills_current_version_when_snapshot_path_is_missing(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    session = create_session_factory(settings.database_url)()
    try:
        page = session.scalar(select(Page).where(Page.slug == "demo-home-9001"))
        version = session.scalar(select(PageVersion).where(PageVersion.page_id == page.id, PageVersion.version_number == 1))
        version.markdown_path = None
        session.commit()
    finally:
        session.close()

    history_file = tmp_path / "wiki" / "spaces" / "DEMO" / "history" / "demo-home-9001" / "v0001.md"
    history_file.unlink()

    client = TestClient(create_app(settings=settings, allow_test_fallback=False))
    _login(client, "viewer")
    response = client.get("/spaces/DEMO/pages/demo-home-9001/history/1")

    assert response.status_code == 200
    assert "이전 버전 문서" in response.text
    assert history_file.exists()
