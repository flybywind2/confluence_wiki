from __future__ import annotations

from collections import Counter
from datetime import datetime
import re
import uuid

from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from slugify import slugify

from app.core.config import Settings, get_settings
from app.core.knowledge import knowledge_href, normalize_knowledge_kind
from app.core.markdown import read_markdown_body, read_markdown_document
from app.core.obsidian import knowledge_link, page_link
from app.core.slugs import page_slug
from app.db.models import KnowledgeDocument, Page, PageLink, Space, WikiDocument
from app.db.session import create_session_factory
from app.llm.text_client import TextLLMClient
from app.services.index_builder import append_space_log, build_global_index, build_space_index
from app.services.wiki_writer import write_knowledge_markdown, write_markdown_file

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
MARKDOWN_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)")
WIKI_LINK_RE = re.compile(r"!\[\[(?P<embed>[^\]]+)\]\]|\[\[(?P<target>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]")
STOPWORDS = {
    "위키",
    "문서",
    "페이지",
    "설명",
    "정리",
    "현재",
    "space",
    "demo",
    "wiki",
    "confluence",
    "arch",
    "데모",
    "메모",
    "관련",
    "현재",
    "구성",
    "확인",
    "표시",
    "정상",
    "샘플",
    "이미지",
    "버튼",
    "링크",
    "화면",
    "적용",
    "point",
    "td",
    "tr",
    "th",
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
        existing_keyword_tokens = self._existing_keyword_tokens(session, space.id)

        session.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.space_id == space.id,
                KnowledgeDocument.kind.in_(["entity", "concept", "keyword"]),
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
            token_counts = self._extract_keyword_counts(space.space_key, page.title, summary, body)
            fact_cards.append(
                {
                    "title": page.title,
                    "slug": page.slug,
                    "summary": summary or page.title,
                    "href": f"/spaces/{space_key}/pages/{page.slug}",
                    "fact_card": fact_card,
                    "body": body,
                    "token_counts": token_counts,
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

        for keyword in self._build_keyword_documents(space_key, fact_cards, existing_keyword_tokens):
            docs.append(
                self._upsert_document(
                    session=session,
                    space=space,
                    kind="keyword",
                    slug=keyword["slug"],
                    title=keyword["title"],
                    summary=keyword["summary"],
                    body=keyword["body"],
                    source_refs="\n".join(keyword["source_refs"]),
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

    def update_document_body(self, space_key: str, kind: str, slug: str, body: str) -> dict[str, str]:
        session = self.session_factory()
        try:
            result = self.update_document_body_with_session(session, space_key, kind, slug, body)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_document_body_with_session(
        self,
        session,
        space_key: str,
        kind: str,
        slug: str,
        body: str,
    ) -> dict[str, str]:
        normalized_kind = normalize_knowledge_kind(kind)
        if normalized_kind not in {"keyword", "analysis", "lint"}:
            raise ValueError("editing is only allowed for user-visible knowledge documents")
        content = body.strip()
        if not content:
            raise ValueError("body is required")

        space = session.scalar(select(Space).where(Space.space_key == space_key))
        if space is None:
            raise ValueError("unknown space")
        doc = session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.space_id == space.id,
                KnowledgeDocument.kind == normalized_kind,
                KnowledgeDocument.slug == slug,
            )
        )
        if doc is None:
            raise ValueError("knowledge document not found")

        markdown_path = self.settings.wiki_root / doc.markdown_path
        frontmatter, _existing_body = read_markdown_document(markdown_path)
        updated_at = datetime.now()
        summary = self.text_client.summarize(content) or self._first_line(content)
        frontmatter["title"] = doc.title
        frontmatter["updated_at"] = updated_at.isoformat()
        write_markdown_file(markdown_path, frontmatter, content)

        doc.summary = summary
        doc.updated_at = updated_at
        session.flush()
        self._rebuild_indexes_for_space(session, space)
        append_space_log(
            self.settings.wiki_root,
            space.space_key,
            "knowledge-edit",
            updated_at,
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

    def _build_keyword_documents(
        self,
        space_key: str,
        fact_cards: list[dict[str, str]],
        existing_keywords: set[str],
    ) -> list[dict[str, str]]:
        if not fact_cards:
            return []

        total_counts: Counter[str] = Counter()
        doc_counts: Counter[str] = Counter()
        for item in fact_cards:
            token_counts = item["token_counts"]
            total_counts.update(token_counts)
            for token in token_counts:
                doc_counts[token] += 1

        eligible = {
            token
            for token, count in total_counts.items()
            if doc_counts[token] >= 2 or count >= 3 or token in existing_keywords
        }
        if not eligible:
            eligible = {token for token, _count in total_counts.most_common(6)}

        keyword_pages: dict[str, list[dict[str, str]]] = {}
        co_occurrence: dict[str, Counter[str]] = {}
        for item in fact_cards:
            selected_keywords = self._select_keywords_for_page(item["token_counts"], total_counts, doc_counts, eligible)
            if not selected_keywords:
                continue
            for keyword in selected_keywords:
                keyword_pages.setdefault(keyword, []).append(item)
            for keyword in selected_keywords:
                neighbors = [candidate for candidate in selected_keywords if candidate != keyword]
                co_occurrence.setdefault(keyword, Counter()).update(neighbors)

        documents: list[dict[str, str]] = []
        for keyword, items in sorted(
            keyword_pages.items(),
            key=lambda pair: (-doc_counts[pair[0]], -total_counts[pair[0]], pair[0]),
        ):
            related_keywords = [candidate for candidate, _count in co_occurrence.get(keyword, Counter()).most_common(6)]
            synthesized = self.text_client.synthesize_keyword_page(space_key, keyword, items, related_keywords)
            documents.append(
                {
                    "slug": self._keyword_slug(keyword),
                    "title": keyword,
                    "summary": self._keyword_summary(keyword, items),
                    "body": self._ensure_keyword_sections(space_key, keyword, items, related_keywords, synthesized),
                    "source_refs": [page_link(space_key, item["slug"], item["title"]) for item in items],
                }
            )
        return documents

    @staticmethod
    def _source_href(item: dict[str, str]) -> str:
        space_key = str(item.get("space_key") or "").strip()
        slug = str(item.get("slug") or "").strip()
        kind = normalize_knowledge_kind(str(item.get("kind") or "page"))
        if kind == "page":
            return page_link(space_key, slug, str(item.get("title") or slug))
        return knowledge_link(space_key, kind, slug, str(item.get("title") or slug))

    @staticmethod
    def _keyword_summary(topic: str, items: list[dict[str, str]]) -> str:
        titles = ", ".join(item["title"] for item in items[:2])
        if len(items) > 2:
            titles = f"{titles} 외 {len(items) - 2}건"
        return f"{topic} 키워드와 직접 연결되는 문서: {titles}"

    def _ensure_keyword_sections(
        self,
        space_key: str,
        title: str,
        items: list[dict[str, str]],
        related_keywords: list[str],
        body: str,
    ) -> str:
        section_requirements = {
            "## 개요": self._default_keyword_overview(space_key, title, items),
            "## 핵심 사실": "\n".join(f"- {item['title']}: {item['summary']}" for item in items) or "- 정보 없음",
            "## 관련 문서": "\n".join(self._page_reference(space_key, item) for item in items),
            "## 관련 키워드": "\n".join(
                f"- {knowledge_link(space_key, 'keyword', self._keyword_slug(keyword), keyword)}" for keyword in related_keywords if keyword != title
            )
            or "- 관련 키워드가 아직 충분히 추출되지 않았습니다.",
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
    def _default_keyword_overview(space_key: str, title: str, items: list[dict[str, str]]) -> str:
        if not items:
            return f"{space_key} space에서 '{title}' 키워드와 연결되는 문서를 묶은 페이지입니다."
        return f"{space_key} space에서 '{title}' 키워드가 반복적으로 등장하는 원문을 모아 빠르게 파악할 수 있게 정리한 문서입니다."

    @staticmethod
    def _page_reference(space_key: str, item: dict[str, str]) -> str:
        return f"- {page_link(space_key, item['slug'], item['title'])}"

    def _existing_keyword_tokens(self, session, space_id: int) -> set[str]:
        existing_docs = session.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.space_id == space_id, KnowledgeDocument.kind == "keyword")
        ).all()
        return {self._normalize_keyword_token(doc.title) for doc in existing_docs if doc.title}

    def _extract_keyword_counts(self, space_key: str, title: str, summary: str, body: str) -> Counter[str]:
        normalized_body = self._normalize_keyword_source(body)
        weighted_text = " ".join([title] * 3 + [summary] * 2 + [normalized_body])
        counts: Counter[str] = Counter()
        for token in TOKEN_RE.findall(weighted_text):
            normalized = self._normalize_keyword_token(token)
            if not normalized or normalized in STOPWORDS or normalized == space_key.lower():
                continue
            counts[normalized] += 1
        return counts

    @staticmethod
    def _normalize_keyword_token(token: str) -> str:
        return str(token or "").strip().lower()

    @staticmethod
    def _normalize_keyword_source(body: str) -> str:
        text = str(body or "")
        text = WIKI_LINK_RE.sub(lambda match: match.group("label") or match.group("target") or "", text)
        text = MARKDOWN_LINK_RE.sub(lambda match: match.group("label"), text)
        text = text.replace("![[", "[[")
        return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)

    @staticmethod
    def _keyword_slug(keyword: str) -> str:
        return slugify(keyword, allow_unicode=True) or "keyword"

    @staticmethod
    def _select_keywords_for_page(
        token_counts: Counter[str],
        total_counts: Counter[str],
        doc_counts: Counter[str],
        eligible: set[str],
    ) -> list[str]:
        ranked = [
            token
            for token, _count in sorted(
                token_counts.items(),
                key=lambda item: (-item[1], -doc_counts[item[0]], -total_counts[item[0]], item[0]),
            )
            if token in eligible
        ]
        if ranked:
            return ranked[:3]
        fallback = [
            token
            for token, _count in sorted(
                token_counts.items(),
                key=lambda item: (-item[1], -doc_counts[item[0]], -total_counts[item[0]], item[0]),
            )
        ]
        return fallback[:1]
