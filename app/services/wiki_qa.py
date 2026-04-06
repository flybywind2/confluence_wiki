from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.knowledge import knowledge_href, knowledge_label, normalize_knowledge_kind
from app.core.markdown import read_markdown_body
from app.db.models import KnowledgeDocument, Page, Space, WikiDocument
from app.db.session import create_session_factory
from app.llm.text_client import TextLLMClient
from app.services.index_builder import append_space_log, build_global_index, build_space_index, build_space_synthesis, read_space_log_excerpt
from app.services.knowledge_service import KnowledgeService
from app.services.lint_service import LintService

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
MARKDOWN_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)")
WIKI_LINK_RE = re.compile(r"\[\[(?P<space>[^/\]]+)/(?P<slug>[^\]]+)\]\]")


class WikiQAService:
    def __init__(
        self,
        settings: Settings | None = None,
        text_client: TextLLMClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.text_client = text_client or TextLLMClient(self.settings)
        self.session_factory = create_session_factory(self.settings.database_url)
        self.knowledge_service = KnowledgeService(self.settings)
        self.lint_service = LintService(self.settings)

    def answer(self, question: str, scope: str, selected_space: str | None, max_documents: int = 3) -> dict:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("question is required")
        if scope not in {"space", "global"}:
            raise ValueError("scope must be either 'space' or 'global'")
        if scope == "space" and (not selected_space or selected_space == "all"):
            raise ValueError("selected space is required for space scope")

        sources = self._collect_sources(
            question=normalized_question,
            scope=scope,
            selected_space=selected_space,
            max_documents=max_documents,
        )
        answer = self.text_client.answer_question(normalized_question, sources)
        return {
            "scope": scope,
            "selected_space": selected_space,
            "answer": answer,
            "sources": [
                {
                    "title": item["title"],
                    "space_key": item["space_key"],
                    "slug": item["slug"],
                    "kind": item["kind"],
                    "kind_label": knowledge_label(item["kind"]) if item["kind"] != "page" else "원문",
                    "href": item["href"],
                    "source_url": item["source_url"],
                    "excerpt": item["excerpt"],
                }
                for item in sources
            ],
        }

    def save_answer(
        self,
        space_key: str,
        question: str,
        scope: str,
        answer: str,
        sources: list[dict[str, str]],
    ) -> dict[str, str]:
        normalized_space_key = (space_key or "").strip()
        normalized_question = (question or "").strip()
        normalized_scope = (scope or "").strip()
        normalized_answer = (answer or "").strip()
        if not normalized_space_key or normalized_space_key == "all":
            raise ValueError("space_key is required")
        if not normalized_question:
            raise ValueError("question is required")
        if normalized_scope not in {"space", "global"}:
            raise ValueError("scope must be either 'space' or 'global'")
        if not normalized_answer:
            raise ValueError("answer is required")
        result = self.knowledge_service.save_analysis(
            space_key=normalized_space_key,
            question=normalized_question,
            scope=normalized_scope,
            answer=normalized_answer,
            sources=sources,
        )
        append_space_log(
            self.settings.wiki_root,
            space_key=normalized_space_key,
            mode="analysis-save",
            timestamp=datetime.now(),
            documents=[
                {
                    "title": result["title"],
                    "slug": result["slug"],
                    "href": result["href"],
                    "summary": normalized_question[:180],
                }
            ],
            window_label=f"question: {normalized_question[:120]}",
        )
        self._refresh_materialized_views(normalized_space_key)
        return result

    def _collect_sources(self, question: str, scope: str, selected_space: str | None, max_documents: int) -> list[dict[str, str]]:
        session = self.session_factory()
        try:
            page_query = select(Page, WikiDocument, Space).join(WikiDocument, WikiDocument.page_id == Page.id).join(Space, Space.id == Page.space_id)
            knowledge_query = select(KnowledgeDocument, Space).join(Space, Space.id == KnowledgeDocument.space_id)
            if scope == "space" and selected_space:
                page_query = page_query.where(Space.space_key == selected_space)
                knowledge_query = knowledge_query.where(Space.space_key == selected_space)
            page_rows = session.execute(page_query).all()
            knowledge_rows = session.execute(knowledge_query).all()
        finally:
            session.close()

        question_tokens = [token.lower() for token in TOKEN_RE.findall(question)]
        index_hints = self._load_index_hints(scope, selected_space)
        ranked: list[tuple[int, dict[str, str]]] = []

        for page, wiki_document, space in page_rows:
            markdown_path = self.settings.wiki_root / wiki_document.markdown_path
            if not markdown_path.exists():
                continue
            body = read_markdown_body(markdown_path)
            hint = index_hints.get((space.space_key, "page", page.slug), "")
            score = self._score_candidate(
                tokens=question_tokens,
                title=page.title,
                slug=page.slug,
                body=body,
                summary=wiki_document.summary or "",
                hint=hint,
                source_refs=page.prod_url,
            )
            if question_tokens and score == 0:
                continue
            ranked.append(
                (
                    score,
                    {
                        "title": page.title,
                        "space_key": space.space_key,
                        "slug": page.slug,
                        "kind": "page",
                        "href": f"/spaces/{space.space_key}/pages/{page.slug}",
                        "source_url": page.prod_url,
                        "excerpt": self._excerpt(body, question_tokens),
                    },
                )
            )

        for doc, space in knowledge_rows:
            markdown_path = self.settings.wiki_root / doc.markdown_path
            if not markdown_path.exists():
                continue
            body = read_markdown_body(markdown_path)
            normalized_kind = normalize_knowledge_kind(doc.kind)
            hint = index_hints.get((space.space_key, normalized_kind, doc.slug), "")
            score = self._score_candidate(
                tokens=question_tokens,
                title=doc.title,
                slug=doc.slug,
                body=body,
                summary=doc.summary or "",
                hint=hint,
                source_refs=doc.source_refs or "",
            )
            if question_tokens and score == 0:
                continue
            ranked.append(
                (
                    score,
                    {
                        "title": doc.title,
                        "space_key": space.space_key,
                        "slug": doc.slug,
                        "kind": normalized_kind,
                        "href": knowledge_href(space.space_key, normalized_kind, doc.slug),
                        "source_url": knowledge_href(space.space_key, normalized_kind, doc.slug),
                        "excerpt": self._excerpt(body, question_tokens),
                    },
                )
            )

        if not ranked:
            fallback_sources: list[dict[str, str]] = []
            for page, wiki_document, space in page_rows:
                markdown_path = self.settings.wiki_root / wiki_document.markdown_path
                if not markdown_path.exists():
                    continue
                body = read_markdown_body(markdown_path)
                fallback_sources.append(
                    {
                        "title": page.title,
                        "space_key": space.space_key,
                        "slug": page.slug,
                        "kind": "page",
                        "href": f"/spaces/{space.space_key}/pages/{page.slug}",
                        "source_url": page.prod_url,
                        "excerpt": self._excerpt(body, []),
                    }
                )
                if len(fallback_sources) >= max_documents:
                    break
            if len(fallback_sources) < max_documents:
                for doc, space in knowledge_rows:
                    markdown_path = self.settings.wiki_root / doc.markdown_path
                    if not markdown_path.exists():
                        continue
                    body = read_markdown_body(markdown_path)
                    kind = normalize_knowledge_kind(doc.kind)
                    fallback_sources.append(
                        {
                            "title": doc.title,
                            "space_key": space.space_key,
                            "slug": doc.slug,
                            "kind": kind,
                            "href": knowledge_href(space.space_key, kind, doc.slug),
                            "source_url": knowledge_href(space.space_key, kind, doc.slug),
                            "excerpt": self._excerpt(body, []),
                        }
                    )
                    if len(fallback_sources) >= max_documents:
                        break
            return fallback_sources[:max_documents]

        ranked.sort(key=lambda item: (-item[0], item[1]["title"]))
        return [payload for _score, payload in ranked[:max_documents]]

    def _load_index_hints(self, scope: str, selected_space: str | None) -> dict[tuple[str, str, str], str]:
        candidates: list[Path] = []
        if scope == "space" and selected_space and selected_space != "all":
            candidates.append(self.settings.wiki_root / "spaces" / selected_space / "index.md")
        else:
            candidates.append(self.settings.wiki_root / "global" / "index.md")
            if selected_space and selected_space != "all":
                candidates.append(self.settings.wiki_root / "spaces" / selected_space / "index.md")

        hints: dict[tuple[str, str, str], str] = {}
        for path in candidates:
            if not path.exists():
                continue
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line.startswith("- "):
                    continue
                wiki_match = WIKI_LINK_RE.search(line)
                if wiki_match:
                    key = (wiki_match.group("space"), "page", wiki_match.group("slug"))
                    hints[key] = line
                    continue
                link_match = MARKDOWN_LINK_RE.search(line)
                if not link_match:
                    continue
                href = link_match.group("href").strip()
                parts = href.strip("/").split("/")
                if len(parts) >= 5 and parts[0] == "spaces" and parts[2] == "knowledge":
                    hints[(parts[1], normalize_knowledge_kind(parts[3]), parts[4])] = line
                elif len(parts) >= 4 and parts[0] == "spaces" and parts[2] == "pages":
                    hints[(parts[1], "page", parts[3])] = line
        return hints

    def _refresh_materialized_views(self, space_key: str) -> None:
        session = self.session_factory()
        try:
            space = session.scalar(select(Space).where(Space.space_key == space_key))
            if space is None:
                return

            self.lint_service.rebuild_space_with_session(session, space_key)
            session.flush()

            page_rows = session.execute(
                select(Page, WikiDocument)
                .join(WikiDocument, WikiDocument.page_id == Page.id)
                .where(Page.space_id == space.id)
            ).all()
            knowledge_rows = session.scalars(
                select(KnowledgeDocument).where(KnowledgeDocument.space_id == space.id)
            ).all()

            documents = [
                {
                    "title": page.title,
                    "slug": page.slug,
                    "summary": wiki_document.summary or "",
                    "href": f"/spaces/{space_key}/pages/{page.slug}",
                }
                for page, wiki_document in page_rows
            ]
            knowledge_documents = [
                {
                    "title": doc.title,
                    "slug": doc.slug,
                    "kind": doc.kind,
                    "summary": doc.summary or "",
                    "href": knowledge_href(space_key, doc.kind, doc.slug),
                }
                for doc in knowledge_rows
            ]

            build_space_index(self.settings.wiki_root, space_key, documents, knowledge_documents)
            build_space_synthesis(
                self.settings.wiki_root,
                space_key,
                documents,
                generated_at=datetime.now(),
                recent_log_entries=read_space_log_excerpt(self.settings.wiki_root, space_key),
            )

            grouped_documents: dict[str, list[dict[str, str]]] = {}
            for listed_space in session.scalars(select(Space).order_by(Space.space_key)).all():
                listed_page_rows = session.execute(
                    select(Page, WikiDocument)
                    .join(WikiDocument, WikiDocument.page_id == Page.id)
                    .where(Page.space_id == listed_space.id)
                ).all()
                listed_knowledge_rows = session.scalars(
                    select(KnowledgeDocument).where(KnowledgeDocument.space_id == listed_space.id)
                ).all()
                grouped_documents[listed_space.space_key] = [
                    *[
                        {
                            "title": page.title,
                            "slug": page.slug,
                            "summary": wiki_document.summary or "",
                            "href": f"/spaces/{listed_space.space_key}/pages/{page.slug}",
                        }
                        for page, wiki_document in listed_page_rows
                    ],
                    *[
                        {
                            "title": doc.title,
                            "slug": doc.slug,
                            "summary": doc.summary or "",
                            "href": knowledge_href(listed_space.space_key, doc.kind, doc.slug),
                        }
                        for doc in listed_knowledge_rows
                    ],
                ]
            build_global_index(self.settings.wiki_root, grouped_documents)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _score_candidate(
        tokens: list[str],
        title: str,
        slug: str,
        body: str,
        summary: str,
        hint: str,
        source_refs: str,
    ) -> int:
        if not tokens:
            return 1
        title_text = title.lower()
        slug_text = slug.lower()
        body_text = body.lower()
        summary_text = summary.lower()
        hint_text = hint.lower()
        refs_text = source_refs.lower()
        score = 0
        for token in tokens:
            score += title_text.count(token) * 9
            score += slug_text.count(token) * 5
            score += summary_text.count(token) * 6
            score += hint_text.count(token) * 4
            score += refs_text.count(token) * 3
            score += body_text.count(token)
        return score

    @staticmethod
    def _excerpt(body: str, tokens: list[str], limit: int = 500) -> str:
        compact = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1 이미지", body)
        compact = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", compact)
        compact = BeautifulSoup(compact, "html.parser").get_text(" ")
        compact = re.sub(r"[#`>*-]+", " ", compact)
        compact = re.sub(r"\s+", " ", compact).strip()
        if not compact:
            return ""
        if not tokens:
            return compact[:limit]
        lowered = compact.lower()
        positions = [lowered.find(token) for token in tokens if lowered.find(token) != -1]
        if not positions:
            return compact[:limit]
        start = max(min(positions) - 120, 0)
        return compact[start : start + limit].strip()
