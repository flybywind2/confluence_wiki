from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.markdown import read_markdown_body
from app.db.models import Page, Space, WikiDocument
from app.db.session import create_session_factory
from app.llm.text_client import TextLLMClient

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")


class WikiQAService:
    def __init__(
        self,
        settings: Settings | None = None,
        text_client: TextLLMClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.text_client = text_client or TextLLMClient(self.settings)
        self.session_factory = create_session_factory(self.settings.database_url)

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
                    "source_url": item["source_url"],
                    "excerpt": item["excerpt"],
                }
                for item in sources
            ],
        }

    def _collect_sources(self, question: str, scope: str, selected_space: str | None, max_documents: int) -> list[dict[str, str]]:
        session = self.session_factory()
        try:
            query = select(Page, WikiDocument, Space).join(WikiDocument, WikiDocument.page_id == Page.id).join(Space, Space.id == Page.space_id)
            if scope == "space" and selected_space:
                query = query.where(Space.space_key == selected_space)
            rows = session.execute(query).all()
        finally:
            session.close()

        question_tokens = [token.lower() for token in TOKEN_RE.findall(question)]
        ranked: list[tuple[int, dict[str, str]]] = []
        for page, wiki_document, space in rows:
            markdown_path = self.settings.wiki_root / wiki_document.markdown_path
            if not markdown_path.exists():
                continue
            body = read_markdown_body(markdown_path)
            title_text = page.title.lower()
            slug_text = page.slug.lower()
            body_text = body.lower()
            score = 0
            for token in question_tokens:
                score += title_text.count(token) * 8
                score += slug_text.count(token) * 5
                score += body_text.count(token)
            if not question_tokens:
                score = 1
            elif score == 0:
                continue
            ranked.append(
                (
                    score,
                    {
                        "title": page.title,
                        "space_key": space.space_key,
                        "slug": page.slug,
                        "source_url": page.prod_url,
                        "excerpt": self._excerpt(body, question_tokens),
                    },
                )
            )

        if not ranked:
            for page, wiki_document, space in rows[:max_documents]:
                markdown_path = self.settings.wiki_root / wiki_document.markdown_path
                if not markdown_path.exists():
                    continue
                body = read_markdown_body(markdown_path)
                ranked.append(
                    (
                        0,
                        {
                            "title": page.title,
                            "space_key": space.space_key,
                            "slug": page.slug,
                            "source_url": page.prod_url,
                            "excerpt": self._excerpt(body, []),
                        },
                    )
                )

        ranked.sort(key=lambda item: (-item[0], item[1]["title"]))
        return [payload for _score, payload in ranked[:max_documents]]

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
