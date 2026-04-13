from __future__ import annotations

from datetime import datetime
import re

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError

from app.core.config import Settings, get_settings
from app.core.knowledge import GLOBAL_KNOWLEDGE_SPACE_KEY
from app.core.markdown import read_markdown_body
from app.db.models import Page, RawPageChunk, Space, WikiDocument
from app.db.session import is_sqlite_database_url

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
MARKDOWN_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)")
WIKI_LINK_RE = re.compile(r"!\[\[(?P<embed>[^\]]+)\]\]|\[\[(?P<target>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]")
CODE_RE = re.compile(r"`([^`]*)`")


class SearchIndexService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def replace_page_chunks(
        self,
        session,
        *,
        page_id: int,
        title: str,
        summary: str | None,
        body: str,
    ) -> None:
        self.ensure_sqlite_fts_objects(session)
        chunks = self._chunk_markdown(title=title, summary=summary or "", body=body)
        session.execute(delete(RawPageChunk).where(RawPageChunk.page_id == page_id))
        for index, chunk in enumerate(chunks):
            session.add(
                RawPageChunk(
                    page_id=page_id,
                    chunk_no=index,
                    content=chunk,
                    updated_at=datetime.now(),
                )
            )
        session.flush()

    def reindex_pages(self, session, page_ids: set[int] | None = None) -> int:
        self.ensure_sqlite_fts_objects(session)
        statement = (
            select(Page, WikiDocument, Space)
            .join(WikiDocument, WikiDocument.page_id == Page.id)
            .join(Space, Space.id == Page.space_id)
            .where(Space.space_key != GLOBAL_KNOWLEDGE_SPACE_KEY)
        )
        if page_ids:
            statement = statement.where(Page.id.in_(page_ids))
        rows = session.execute(statement).all()
        for page, wiki_document, _space in rows:
            markdown_path = self.settings.wiki_root / wiki_document.markdown_path
            body = read_markdown_body(markdown_path) if markdown_path.exists() else ""
            self.replace_page_chunks(
                session,
                page_id=page.id,
                title=page.title,
                summary=wiki_document.summary,
                body=body,
            )
        return len(rows)

    def find_candidate_page_ids(
        self,
        session,
        *,
        query: str,
        selected_space: str | None = None,
        limit: int = 48,
    ) -> list[int]:
        match_expression = self._build_match_expression(query)
        if not match_expression:
            return []
        if not is_sqlite_database_url(self.settings.database_url):
            return self._fallback_candidate_page_ids(session, query=query, selected_space=selected_space, limit=limit)
        self.ensure_sqlite_fts_objects(session)
        try:
            rows = session.execute(
                text(
                    """
                    SELECT rpc.page_id AS page_id, bm25(raw_page_chunks_fts) AS score
                    FROM raw_page_chunks_fts
                    JOIN raw_page_chunks rpc ON rpc.id = raw_page_chunks_fts.rowid
                    JOIN pages p ON p.id = rpc.page_id
                    JOIN spaces s ON s.id = p.space_id
                    WHERE raw_page_chunks_fts MATCH :match
                      AND s.space_key != :global_space
                      AND (
                        :selected_space IS NULL
                        OR :selected_space = ''
                        OR :selected_space = 'all'
                        OR s.space_key = :selected_space
                      )
                    ORDER BY score ASC, rpc.page_id ASC
                    LIMIT :scan_limit
                    """
                ),
                {
                    "match": match_expression,
                    "global_space": GLOBAL_KNOWLEDGE_SPACE_KEY,
                    "selected_space": selected_space,
                    "scan_limit": int(max(limit * 6, 32)),
                },
            ).all()
        except OperationalError:
            return []
        page_ids: list[int] = []
        seen: set[int] = set()
        for row in rows:
            page_id = int(row.page_id)
            if page_id in seen:
                continue
            seen.add(page_id)
            page_ids.append(page_id)
            if len(page_ids) >= limit:
                break
        return page_ids

    def needs_initial_backfill(self, session) -> bool:
        total_pages = int(
            session.scalar(
                select(func.count(Page.id))
                .join(Space, Space.id == Page.space_id)
                .where(Space.space_key != GLOBAL_KNOWLEDGE_SPACE_KEY)
            )
            or 0
        )
        if total_pages == 0:
            return False
        chunk_count = int(session.scalar(select(func.count(RawPageChunk.id))) or 0)
        return chunk_count == 0

    def ensure_sqlite_fts_objects(self, session) -> None:
        if not is_sqlite_database_url(self.settings.database_url):
            return
        session.execute(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS raw_page_chunks_fts
                USING fts5(content, content='raw_page_chunks', content_rowid='id', tokenize='unicode61')
                """
            )
        )
        session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS raw_page_chunks_ai AFTER INSERT ON raw_page_chunks BEGIN
                  INSERT INTO raw_page_chunks_fts(rowid, content) VALUES (new.id, new.content);
                END
                """
            )
        )
        session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS raw_page_chunks_ad AFTER DELETE ON raw_page_chunks BEGIN
                  INSERT INTO raw_page_chunks_fts(raw_page_chunks_fts, rowid, content)
                  VALUES ('delete', old.id, old.content);
                END
                """
            )
        )
        session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS raw_page_chunks_au AFTER UPDATE ON raw_page_chunks BEGIN
                  INSERT INTO raw_page_chunks_fts(raw_page_chunks_fts, rowid, content)
                  VALUES ('delete', old.id, old.content);
                  INSERT INTO raw_page_chunks_fts(rowid, content) VALUES (new.id, new.content);
                END
                """
            )
        )

    @staticmethod
    def _normalize_search_text(value: str) -> str:
        text_value = str(value or "")
        text_value = MARKDOWN_LINK_RE.sub(lambda match: match.group("label"), text_value)
        text_value = WIKI_LINK_RE.sub(lambda match: match.group("label") or match.group("target") or "", text_value)
        text_value = CODE_RE.sub(lambda match: match.group(1), text_value)
        cleaned_lines: list[str] = []
        for raw_line in text_value.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith(("```", "---", "> [!", "![[", "![", "|")):
                continue
            if stripped.startswith("#"):
                stripped = stripped.lstrip("#").strip()
            if stripped.startswith(("- ", "* ")):
                stripped = stripped[2:].strip()
            cleaned_lines.append(" ".join(stripped.split()))
        return "\n".join(cleaned_lines).strip()

    def _chunk_markdown(self, *, title: str, summary: str, body: str, max_chars: int = 1000, max_chunks: int = 16) -> list[str]:
        prefix_parts = [part.strip() for part in (title, summary) if str(part or "").strip()]
        prefix = "\n".join(prefix_parts).strip()
        normalized_body = self._normalize_search_text(body)
        segments = [segment.strip() for segment in re.split(r"\n{2,}", normalized_body) if segment.strip()]
        if not segments:
            segments = [prefix] if prefix else [title]

        chunks: list[str] = []
        current = prefix
        for segment in segments:
            candidate = f"{current}\n\n{segment}".strip() if current else segment
            if current and len(candidate) > max_chars:
                chunks.append(current.strip())
                if len(chunks) >= max_chunks:
                    break
                current = f"{prefix}\n\n{segment}".strip() if prefix else segment
                continue
            current = candidate
        if current and len(chunks) < max_chunks:
            chunks.append(current.strip())
        deduped: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            trimmed = chunk[:max_chars].strip()
            if not trimmed or trimmed in seen:
                continue
            seen.add(trimmed)
            deduped.append(trimmed)
        return deduped or [prefix or title]

    @staticmethod
    def _quote_match_term(term: str) -> str:
        return '"' + term.replace('"', '""') + '"'

    def _build_match_expression(self, query: str) -> str:
        normalized_query = " ".join(str(query or "").split()).strip()
        if not normalized_query:
            return ""
        clauses: list[str] = []
        if len(TOKEN_RE.findall(normalized_query)) > 1:
            clauses.append(self._quote_match_term(normalized_query))
        seen_tokens: set[str] = set()
        for token in TOKEN_RE.findall(normalized_query.lower()):
            if token in seen_tokens:
                continue
            seen_tokens.add(token)
            clauses.append(self._quote_match_term(token))
        return " OR ".join(clauses)

    def _fallback_candidate_page_ids(
        self,
        session,
        *,
        query: str,
        selected_space: str | None,
        limit: int,
    ) -> list[int]:
        tokens = [token.lower() for token in TOKEN_RE.findall(query)]
        statement = (
            select(Page.id, Page.title, WikiDocument.summary)
            .join(WikiDocument, WikiDocument.page_id == Page.id)
            .join(Space, Space.id == Page.space_id)
            .where(Space.space_key != GLOBAL_KNOWLEDGE_SPACE_KEY)
        )
        if selected_space and selected_space not in {"", "all"}:
            statement = statement.where(Space.space_key == selected_space)
        rows = session.execute(statement).all()
        ranked: list[tuple[int, int]] = []
        for row in rows:
            haystack = f"{row.title} {row.summary or ''}".lower()
            score = sum(1 for token in tokens if token in haystack)
            if score > 0:
                ranked.append((score, int(row.id)))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [page_id for _score, page_id in ranked[:limit]]
