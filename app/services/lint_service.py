from __future__ import annotations

import re

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.knowledge import GLOBAL_KNOWLEDGE_SPACE_KEY
from app.db.models import KnowledgeDocument, Page, PageLink, PageVersion, Space, WikiDocument
from app.services.knowledge_service import KnowledgeService
from app.services.space_registry import ensure_global_knowledge_space


class LintService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.knowledge_service = KnowledgeService(self.settings)

    def rebuild_space_with_session(self, session, space_key: str) -> KnowledgeDocument | None:
        return self.rebuild_global_with_session(session, selected_space=space_key)

    def rebuild_global_with_session(self, session, selected_space: str | None = None) -> KnowledgeDocument | None:
        global_space = ensure_global_knowledge_space(session)
        page_statement = (
            select(Page, Space, WikiDocument)
            .join(Space, Space.id == Page.space_id)
            .join(WikiDocument, WikiDocument.page_id == Page.id)
            .where(Space.space_key != GLOBAL_KNOWLEDGE_SPACE_KEY)
        )
        if selected_space and selected_space not in {"", "all"}:
            page_statement = page_statement.where(Space.space_key == selected_space)
        page_rows = session.execute(page_statement).all()
        wiki_doc_by_page_id = {wiki_doc.page_id: wiki_doc for _page, _space, wiki_doc in page_rows}
        knowledge_docs = session.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.space_id == global_space.id)
        ).all()
        inbound_targets = {
            target_id for target_id in session.scalars(select(PageLink.target_page_id)).all() if target_id is not None
        }

        orphan_pages = [
            (page, space)
            for page, space, _doc in page_rows
            if page.parent_confluence_page_id and page.id not in inbound_targets
        ]
        missing_summaries = [
            (page, space)
            for page, space, _doc in page_rows
            if not (wiki_doc_by_page_id.get(page.id) and wiki_doc_by_page_id[page.id].summary)
        ]
        history_gaps: list[tuple[Page, Space]] = []
        for page, space, _doc in page_rows:
            current_version = session.scalar(
                select(PageVersion).where(PageVersion.page_id == page.id, PageVersion.version_number == page.current_version)
            )
            if current_version is None or not current_version.markdown_path:
                history_gaps.append((page, space))
                continue
            history_path = self.settings.wiki_root / current_version.markdown_path
            if not history_path.exists():
                history_gaps.append((page, space))

        knowledge_source_page_keys = {
            (space_key, slug)
            for doc in knowledge_docs
            for space_key, slug in self._knowledge_source_page_keys(doc.source_refs)
        }
        unmapped_pages = [
            (page, space)
            for page, space, _doc in page_rows
            if (space.space_key, page.slug) not in knowledge_source_page_keys
        ]
        low_coverage_topics = [
            doc
            for doc in knowledge_docs
            if doc.kind == "keyword" and len(self._knowledge_source_page_keys(doc.source_refs)) <= 1
        ]
        topic_overlaps: list[tuple[KnowledgeDocument, KnowledgeDocument, float]] = []
        keyword_docs = [doc for doc in knowledge_docs if doc.kind == "keyword"]
        for index, left in enumerate(keyword_docs):
            left_sources = set(self._knowledge_source_page_keys(left.source_refs))
            if not left_sources:
                continue
            for right in keyword_docs[index + 1 :]:
                right_sources = set(self._knowledge_source_page_keys(right.source_refs))
                if not right_sources:
                    continue
                overlap_ratio = len(left_sources.intersection(right_sources)) / max(len(left_sources.union(right_sources)), 1)
                if overlap_ratio >= 0.6:
                    topic_overlaps.append((left, right, overlap_ratio))
        dangling_knowledge = [doc for doc in knowledge_docs if doc.kind in {"analysis", "query"} and not (doc.source_refs or "").strip()]
        global_index_path = self.settings.wiki_root / "global" / "index.md"

        scope_label = selected_space if selected_space and selected_space not in {"", "all"} else "전체 위키"
        lines = [
            "# Lint Report",
            "",
            f"이 문서는 {scope_label} 기준 위키 상태를 점검한 결과입니다.",
            "",
            "## Missing Summaries",
            "",
        ]
        lines.extend([f"- [{space.space_key}] {page.title}" for page, space in missing_summaries] or ["- 없음"])
        lines.extend(["", "## Unmapped Raw Pages", ""])
        lines.extend([f"- [{space.space_key}] {page.title}" for page, space in unmapped_pages] or ["- 없음"])
        lines.extend(["", "## Orphans", ""])
        lines.extend([f"- [{space.space_key}] {page.title}" for page, space in orphan_pages] or ["- 없음"])
        lines.extend(["", "## History Coverage", ""])
        lines.extend([f"- [{space.space_key}] {page.title}" for page, space in history_gaps] or ["- 정상"])
        lines.extend(["", "## Low Coverage Topics", ""])
        lines.extend(
            [f"- {doc.title} · source pages {len(self._knowledge_source_page_keys(doc.source_refs))}" for doc in low_coverage_topics]
            or ["- 없음"]
        )
        lines.extend(["", "## Topic Overlap", ""])
        lines.extend(
            [f"- {left.title} ↔ {right.title} · overlap {ratio:.0%}" for left, right, ratio in topic_overlaps]
            or ["- 없음"]
        )
        lines.extend(["", "## Query And Analysis Gaps", ""])
        lines.extend([f"- {doc.title}" for doc in dangling_knowledge] or ["- 없음"])
        lines.extend(["", "## Global Index", ""])
        lines.append("- 존재" if global_index_path.exists() else "- 없음")
        lines.extend(
            [
                "",
                "## Scheduler Recommendation",
                "",
                "- 경량 lint는 매 sync 뒤 자동 실행하는 것이 적절합니다.",
                "- 더 무거운 semantic lint는 하루 1회 외부 스케줄러로 별도 실행하는 것이 적절합니다.",
            ]
        )

        source_refs = "\n".join(
            f"/spaces/{space.space_key}/pages/{page.slug}"
            for page, space in ([*missing_summaries, *unmapped_pages, *history_gaps][:20])
        )
        return self.knowledge_service._upsert_document(
            session=session,
            space=global_space,
            kind="lint",
            slug="report",
            title="Lint Report",
            summary=f"{scope_label} 위키 점검 보고서",
            body="\n".join(lines),
            source_refs=source_refs,
        )

    @staticmethod
    def _knowledge_source_page_keys(source_refs: str | None) -> list[tuple[str, str]]:
        if not source_refs:
            return []
        pattern = re.compile(r"(?:/spaces/|spaces/)(?P<space_key>[^/\]]+)/pages/(?P<slug>[^|\]\s)]+)")
        refs: list[tuple[str, str]] = []
        for match in pattern.finditer(str(source_refs or "")):
            ref = ((match.group("space_key") or "").strip(), (match.group("slug") or "").strip())
            if ref[0] and ref[1] and ref not in refs:
                refs.append(ref)
        return refs
