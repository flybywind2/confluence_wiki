from app.core.config import Settings
from app.core.markdown import read_markdown_body
from app.core.knowledge import GLOBAL_KNOWLEDGE_SPACE_KEY
from app.demo_seed import seed_demo_content
from app.db.models import KnowledgeDocument, Space
from app.services.lint_service import LintService


def test_demo_seed_creates_lint_report_with_health_sections(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    seed_demo_content(settings)

    lint_path = tmp_path / "wiki" / "global" / "knowledge" / "lint" / "report.md"
    lint_text = lint_path.read_text(encoding="utf-8")

    assert "# Lint Report" in lint_text
    assert "## Missing Summaries" in lint_text
    assert "## Unmapped Raw Pages" in lint_text
    assert "## Orphans" in lint_text
    assert "## History Coverage" in lint_text


def test_lint_report_flags_overlapping_topics(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    sample_settings_dict["DATABASE_URL"] = f"sqlite:///{tmp_path / 'app.db'}"
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)
    lint_service = LintService(settings)
    session = lint_service.knowledge_service.session_factory()
    try:
        global_space = session.query(Space).filter(Space.space_key == GLOBAL_KNOWLEDGE_SPACE_KEY).one()
        source_refs = "\n".join(
            [
                "/spaces/DEMO/pages/ops-dashboard-9002",
                "/spaces/DEMO/pages/sync-runbook-9003",
            ]
        )
        session.add_all(
            [
                KnowledgeDocument(
                    space_id=global_space.id,
                    kind="keyword",
                    slug="운영-대시보드",
                    title="운영 대시보드",
                    summary="운영 대시보드 요약",
                    markdown_path="global/knowledge/keywords/운영-대시보드.md",
                    source_refs=source_refs,
                ),
                KnowledgeDocument(
                    space_id=global_space.id,
                    kind="keyword",
                    slug="대시보드-운영",
                    title="대시보드 운영",
                    summary="대시보드 운영 요약",
                    markdown_path="global/knowledge/keywords/대시보드-운영.md",
                    source_refs=source_refs,
                ),
            ]
        )
        session.commit()

        doc = lint_service.rebuild_global_with_session(session)
        session.commit()
        lint_text = read_markdown_body(settings.wiki_root / doc.markdown_path)
    finally:
        session.close()

    assert "## Topic Overlap" in lint_text
    assert "운영 대시보드" in lint_text
    assert "대시보드 운영" in lint_text
