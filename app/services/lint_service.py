from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.models import KnowledgeDocument, Page, PageLink, PageVersion, Space, WikiDocument
from app.services.knowledge_service import KnowledgeService


class LintService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.knowledge_service = KnowledgeService(self.settings)

    def rebuild_space_with_session(self, session, space_key: str) -> KnowledgeDocument | None:
        space = session.scalar(select(Space).where(Space.space_key == space_key))
        if space is None:
            return None

        pages = session.scalars(select(Page).where(Page.space_id == space.id)).all()
        wiki_documents = session.scalars(select(WikiDocument)).all()
        wiki_doc_by_page_id = {doc.page_id: doc for doc in wiki_documents}
        knowledge_docs = session.scalars(select(KnowledgeDocument).where(KnowledgeDocument.space_id == space.id)).all()
        inbound_targets = {
            target_id for target_id in session.scalars(select(PageLink.target_page_id)).all() if target_id is not None
        }

        orphan_pages = [page for page in pages if page.parent_confluence_page_id and page.id not in inbound_targets]
        missing_summaries = [page for page in pages if not (wiki_doc_by_page_id.get(page.id) and wiki_doc_by_page_id[page.id].summary)]
        history_gaps = []
        for page in pages:
            current_version = session.scalar(
                select(PageVersion).where(PageVersion.page_id == page.id, PageVersion.version_number == page.current_version)
            )
            if current_version is None or not current_version.markdown_path:
                history_gaps.append(page)
                continue
            history_path = self.settings.wiki_root / current_version.markdown_path
            if not history_path.exists():
                history_gaps.append(page)

        orphan_knowledge = [doc for doc in knowledge_docs if doc.kind != "lint" and not doc.source_refs]
        synthesis_path = self.settings.wiki_root / "spaces" / space_key / "synthesis.md"

        lines = [f"# {space_key} Lint Report", "", "이 문서는 위키 상태를 점검한 결과입니다.", "", "## Missing Summaries", ""]
        lines.extend([f"- {page.title}" for page in missing_summaries] or ["- 없음"])
        lines.extend(["", "## Orphans", ""])
        lines.extend([f"- page: {page.title}" for page in orphan_pages] or ["- 없음"])
        lines.extend([f"- knowledge: {doc.title}" for doc in orphan_knowledge] or [])
        lines.extend(["", "## History Coverage", ""])
        lines.extend([f"- {page.title}" for page in history_gaps] or ["- 정상"])
        lines.extend(["", "## Synthesis", ""])
        lines.append("- 존재" if synthesis_path.exists() else "- 없음")

        return self.knowledge_service._upsert_document(
            session=session,
            space=space,
            kind="lint",
            slug="report",
            title=f"{space_key} Lint Report",
            summary=f"{space_key} 위키 점검 보고서",
            body="\n".join(lines),
            source_refs="",
        )
