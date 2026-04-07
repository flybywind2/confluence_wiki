from __future__ import annotations

from collections import Counter
from datetime import datetime
import re
import uuid

from sqlalchemy import delete, select

from app.core.config import Settings, get_settings
from app.core.knowledge import knowledge_href, normalize_knowledge_kind
from app.core.markdown import read_markdown_body
from app.core.obsidian import knowledge_link, page_link
from app.core.slugs import page_slug
from app.db.models import KnowledgeDocument, Page, PageLink, Space, WikiDocument
from app.db.session import create_session_factory
from app.llm.text_client import TextLLMClient
from app.services.index_builder import append_space_log, build_global_index, build_space_index
from app.services.wiki_writer import write_knowledge_markdown

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
STOPWORDS = {
    "위키",
    "문서",
    "페이지",
    "설명",
    "정리",
    "현재",
    "space",
    "demo",
    "arch",
}


class KnowledgeService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.session_factory = create_session_factory(self.settings.database_url)
        self.text_client = TextLLMClient(self.settings)

    def rebuild_space(self, space_key: str) -> list[KnowledgeDocument]:
        session = self.session_factory()
        try:
            docs = self.rebuild_space_with_session(session, space_key)
            session.commit()
            return docs
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def rebuild_space_with_session(self, session, space_key: str) -> list[KnowledgeDocument]:
        space = session.scalar(select(Space).where(Space.space_key == space_key))
        if space is None:
            return []

        session.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.space_id == space.id,
                KnowledgeDocument.kind.in_(["entity", "concept"]),
            )
        )
        session.flush()

        page_rows = session.execute(
            select(Page, WikiDocument).join(WikiDocument, WikiDocument.page_id == Page.id).where(Page.space_id == space.id)
        ).all()
        inbound_link_counts = Counter(
            target_id for target_id in session.scalars(select(PageLink.target_page_id)).all() if target_id is not None
        )
        docs: list[KnowledgeDocument] = []
        fact_cards: list[dict[str, str]] = []

        for page, wiki_document in page_rows:
            markdown_path = self.settings.wiki_root / wiki_document.markdown_path
            body = read_markdown_body(markdown_path) if markdown_path.exists() else ""
            summary = wiki_document.summary or self._first_line(body)
            fact_card = self.text_client.summarize_fact_card(page.title, body)
            fact_cards.append(
                {
                    "title": page.title,
                    "slug": page.slug,
                    "summary": summary or page.title,
                    "href": f"/spaces/{space_key}/pages/{page.slug}",
                    "fact_card": fact_card,
                    "body": body,
                }
            )
            entity_body = "\n".join(
                [
                    f"# {page.title}",
                    "",
                    "이 문서는 Confluence 원문 페이지를 기반으로 정리한 지식 문서입니다.",
                    "",
                    "## 원문",
                    "",
                    f"- 최신 문서: {page_link(space_key, page.slug, page.title)}",
                    f"- 운영 URL: {page.prod_url}",
                    "",
                    "## 요약",
                    "",
                    summary or "요약 없음",
                    "",
                    "## fact card",
                    "",
                    fact_card or "fact card 없음",
                    "",
                    "## 상태",
                    "",
                    f"- 현재 버전: {page.current_version}",
                    f"- inbound links: {inbound_link_counts.get(page.id, 0)}",
                ]
            )
            docs.append(
                self._upsert_document(
                    session=session,
                    space=space,
                    kind="entity",
                    slug=page.slug,
                    title=page.title,
                    summary=summary or f"{page.title} 지식 문서",
                    body=entity_body,
                    source_refs=f"/spaces/{space_key}/pages/{page.slug}",
                )
            )

        concept_body = self._build_core_topics_body(space_key, page_rows)
        docs.append(
            self._upsert_document(
                session=session,
                space=space,
                kind="concept",
                slug="core-topics",
                title=f"{space_key} 핵심 개념",
                summary=f"{space_key} space의 주요 주제와 연결을 정리한 개념 문서",
                body=concept_body,
                source_refs="\n".join(f"/spaces/{space_key}/pages/{page.slug}" for page, _ in page_rows),
            )
        )
        for concept in self._build_cluster_concepts(space_key, fact_cards):
            docs.append(
                self._upsert_document(
                    session=session,
                    space=space,
                    kind="concept",
                    slug=concept["slug"],
                    title=concept["title"],
                    summary=concept["summary"],
                    body=concept["body"],
                    source_refs="\n".join(concept["source_refs"]),
                )
            )
        return docs

    def save_analysis(
        self,
        space_key: str,
        question: str,
        scope: str,
        answer: str,
        sources: list[dict[str, str]],
    ) -> dict[str, str]:
        session = self.session_factory()
        try:
            result = self.save_analysis_with_session(session, space_key, question, scope, answer, sources)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save_analysis_with_session(
        self,
        session,
        space_key: str,
        question: str,
        scope: str,
        answer: str,
        sources: list[dict[str, str]],
    ) -> dict[str, str]:
        space = session.scalar(select(Space).where(Space.space_key == space_key))
        if space is None:
            raise ValueError("unknown space")
        if not question.strip():
            raise ValueError("question is required")
        if not answer.strip():
            raise ValueError("answer is required")
        saved_at = datetime.now()
        suffix = uuid.uuid4().hex[:8]
        slug = page_slug(question[:40], suffix)
        title = f"분석: {question[:50]}"
        source_links = [f"- {self._source_href(item)}" for item in sources]
        body = "\n".join(
            [
                f"# {title}",
                "",
                "이 문서는 assistant 질문 결과를 위키에 저장한 분석 문서입니다.",
                "",
                "## 질문",
                "",
                question,
                "",
                "## 범위",
                "",
                scope,
                "",
                "## 저장 시각",
                "",
                saved_at.isoformat(),
                "",
                "## 답변",
                "",
                answer,
                "",
                "## 참고 문서",
                "",
                *source_links,
            ]
        )
        doc = self._upsert_document(
            session=session,
            space=space,
            kind="analysis",
            slug=slug,
            title=title,
            summary=answer.splitlines()[0][:180] if answer else question[:180],
            body=body,
            source_refs="\n".join(self._source_href(item) for item in sources),
        )
        self._rebuild_indexes_for_space(session, space)
        append_space_log(
            self.settings.wiki_root,
            space.space_key,
            "analysis-save",
            saved_at,
            [{"title": doc.title, "slug": doc.slug, "kind": doc.kind, "href": knowledge_href(space.space_key, doc.kind, doc.slug)}],
        )
        return {
            "kind": doc.kind,
            "slug": doc.slug,
            "title": doc.title,
            "href": knowledge_href(space_key, doc.kind, doc.slug),
        }

    def list_documents(self, session, space_id: int) -> list[KnowledgeDocument]:
        return session.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.space_id == space_id).order_by(KnowledgeDocument.updated_at.desc())
        ).all()

    def _rebuild_indexes_for_space(self, session, space: Space) -> None:
        page_rows = session.execute(
            select(Page, WikiDocument).join(WikiDocument, WikiDocument.page_id == Page.id).where(Page.space_id == space.id)
        ).all()
        page_docs = [
            {
                "title": page.title,
                "slug": page.slug,
                "summary": wiki_document.summary or page.title,
                "href": f"/spaces/{space.space_key}/pages/{page.slug}",
            }
            for page, wiki_document in page_rows
        ]
        knowledge_docs = [
            {
                "title": doc.title,
                "slug": doc.slug,
                "kind": doc.kind,
                "summary": doc.summary or doc.title,
                "href": knowledge_href(space.space_key, doc.kind, doc.slug),
            }
            for doc in self.list_documents(session, space.id)
        ]
        build_space_index(self.settings.wiki_root, space.space_key, page_docs, knowledge_docs)

        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        grouped_documents: dict[str, list[dict[str, str]]] = {}
        for current_space in spaces:
            current_page_rows = session.execute(
                select(Page, WikiDocument).join(WikiDocument, WikiDocument.page_id == Page.id).where(Page.space_id == current_space.id)
            ).all()
            grouped_documents[current_space.space_key] = [
                *[
                    {
                        "title": page.title,
                        "slug": page.slug,
                        "summary": wiki_document.summary or page.title,
                        "href": f"/spaces/{current_space.space_key}/pages/{page.slug}",
                    }
                    for page, wiki_document in current_page_rows
                ],
                *[
                    {
                        "title": doc.title,
                        "slug": doc.slug,
                        "summary": doc.summary or doc.title,
                        "href": knowledge_href(current_space.space_key, doc.kind, doc.slug),
                    }
                    for doc in self.list_documents(session, current_space.id)
                ],
            ]
        build_global_index(self.settings.wiki_root, grouped_documents)

    def _upsert_document(
        self,
        session,
        space: Space,
        kind: str,
        slug: str,
        title: str,
        summary: str,
        body: str,
        source_refs: str | None,
    ) -> KnowledgeDocument:
        normalized_kind = normalize_knowledge_kind(kind)
        frontmatter = {
            "space_key": space.space_key,
            "kind": normalized_kind,
            "slug": slug,
            "title": title,
            "aliases": [title],
            "tags": [f"space/{space.space_key}", f"kind/{normalized_kind}", "source/wiki"],
            "source_refs": source_refs or "",
            "updated_at": datetime.now().isoformat(),
        }
        markdown_path = write_knowledge_markdown(
            root=self.settings.wiki_root,
            space_key=space.space_key,
            kind=normalized_kind,
            slug=slug,
            frontmatter=frontmatter,
            body=body,
        )
        doc = session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.space_id == space.id,
                KnowledgeDocument.kind == normalized_kind,
                KnowledgeDocument.slug == slug,
            )
        )
        if doc is None:
            doc = KnowledgeDocument(space_id=space.id, kind=normalized_kind, slug=slug, title=title, markdown_path="")
            session.add(doc)
        doc.kind = normalized_kind
        doc.title = title
        doc.markdown_path = markdown_path.relative_to(self.settings.wiki_root).as_posix()
        doc.summary = summary
        doc.source_refs = source_refs
        session.flush()
        return doc

    @staticmethod
    def _first_line(body: str) -> str:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:180]
        return ""

    def _build_core_topics_body(self, space_key: str, page_rows: list[tuple[Page, WikiDocument]]) -> str:
        summaries = [wiki_document.summary or page.title for page, wiki_document in page_rows]
        tokens = [
            token.lower()
            for summary in summaries
            for token in TOKEN_RE.findall(summary)
            if token.lower() not in STOPWORDS
        ]
        top_terms = [token for token, _count in Counter(tokens).most_common(6)]
        lines = [f"# {space_key} 핵심 개념", "", "이 문서는 현재 space의 주요 주제와 연결을 정리한 개념 문서입니다.", "", "## 주요 문서", ""]
        for page, wiki_document in sorted(page_rows, key=lambda item: item[0].title.lower()):
            lines.append(f"- {page_link(space_key, page.slug, page.title)}: {wiki_document.summary or page.title}")
        lines.extend(["", "## 핵심 키워드", ""])
        if top_terms:
            lines.extend(f"- {term}" for term in top_terms)
        else:
            lines.append("- 키워드 추출 결과가 부족합니다.")
        return "\n".join(lines)

    def _build_cluster_concepts(self, space_key: str, fact_cards: list[dict[str, str]]) -> list[dict[str, str]]:
        if len(fact_cards) < 2:
            return []
        groups: dict[str, list[dict[str, str]]] = {}
        for item in fact_cards:
            topic = self._classify_topic(item["title"], item["summary"], item["body"])
            groups.setdefault(topic, []).append(item)

        concepts: list[dict[str, str]] = []
        for topic, items in sorted(groups.items()):
            title = f"{space_key} {topic}"
            synthesized = self.text_client.synthesize_concept(space_key, title, items)
            concepts.append(
                {
                    "slug": page_slug(topic, len(items)),
                    "title": title,
                    "summary": self._cluster_summary(topic, items),
                    "body": self._ensure_cluster_sections(space_key, title, items, synthesized),
                    "source_refs": [page_link(space_key, item["slug"], item["title"]) for item in items],
                }
            )
        return concepts

    @staticmethod
    def _classify_topic(title: str, summary: str, body: str) -> str:
        text = f"{title} {summary} {body}".lower()
        if any(token in text for token in ("런북", "장애", "재시도", "배치", "동기화", "sync")):
            return "운영과 런북"
        if any(token in text for token in ("대시보드", "지표", "sla", "경보", "모니터")):
            return "운영 지표와 모니터링"
        if any(token in text for token in ("권한", "정책", "보안", "인증")):
            return "권한과 정책"
        return "핵심 주제"

    @staticmethod
    def _source_href(item: dict[str, str]) -> str:
        space_key = str(item.get("space_key") or "").strip()
        slug = str(item.get("slug") or "").strip()
        kind = normalize_knowledge_kind(str(item.get("kind") or "page"))
        if kind == "page":
            return page_link(space_key, slug, str(item.get("title") or slug))
        return knowledge_link(space_key, kind, slug, str(item.get("title") or slug))

    @staticmethod
    def _cluster_summary(topic: str, items: list[dict[str, str]]) -> str:
        titles = ", ".join(item["title"] for item in items[:2])
        if len(items) > 2:
            titles = f"{titles} 외 {len(items) - 2}건"
        return f"{topic} 주제에서 확인할 핵심 문서: {titles}"

    def _ensure_cluster_sections(
        self,
        space_key: str,
        title: str,
        items: list[dict[str, str]],
        body: str,
    ) -> str:
        section_requirements = {
            "## 개요": self._default_overview(space_key, title, items),
            "## 핵심 사실": "\n".join(f"- {item['title']}: {item['summary']}" for item in items) or "- 정보 없음",
            "## 운영 포인트": "\n".join(f"- {item['title']} 문서 기준 운영 포인트 확인" for item in items[:3]),
            "## 대표 문서": "\n".join(self._page_reference(space_key, item) for item in items[: min(2, len(items))]),
            "## 관련 문서": "\n".join(self._page_reference(space_key, item) for item in items),
            "## 남은 질문": "\n".join(self._default_open_questions(items)),
            "## 원문 근거": "\n".join(self._page_reference(space_key, item) for item in items),
        }
        normalized = body.strip()
        if not normalized.startswith("# "):
            normalized = f"# {title}\n\n{normalized}".strip()
        for section, fallback_content in section_requirements.items():
            if section not in normalized:
                normalized += f"\n\n{section}\n\n{fallback_content}"
        return normalized.strip()

    @staticmethod
    def _default_overview(space_key: str, title: str, items: list[dict[str, str]]) -> str:
        if not items:
            return f"{space_key} space의 {title} 관련 문서를 묶은 개념 문서입니다."
        return f"{space_key} space에서 {title} 주제를 빠르게 파악할 수 있도록 관련 원문을 묶어 정리한 문서입니다."

    @staticmethod
    def _default_open_questions(items: list[dict[str, str]]) -> list[str]:
        doc_names = ", ".join(item["title"] for item in items[:2]) if items else "관련 문서"
        return [
            f"- {doc_names} 사이의 책임 경계와 운영 순서가 최신 상태로 유지되는지 확인이 필요합니다.",
            "- 최근 변경 이후에도 관련 지표, 런북, 정책 문서가 서로 일관되는지 검토가 필요합니다.",
        ]

    @staticmethod
    def _page_reference(space_key: str, item: dict[str, str]) -> str:
        return f"- {page_link(space_key, item['slug'], item['title'])}"
