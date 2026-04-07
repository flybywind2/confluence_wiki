from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Callable
import uuid

from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from slugify import slugify

from app.core.config import Settings, get_settings
from app.core.knowledge import (
    GLOBAL_KNOWLEDGE_SPACE_KEY,
    knowledge_href,
    legacy_knowledge_href,
    normalize_knowledge_kind,
    source_space_keys,
)
from app.core.markdown import read_markdown_body, read_markdown_document
from app.core.obsidian import knowledge_link, page_link
from app.core.slugs import page_slug
from app.db.models import KnowledgeDocument, Page, PageLink, Space, WikiDocument
from app.db.session import create_session_factory
from app.llm.text_client import TextLLMClient
from app.services.index_builder import append_space_log, build_global_index, build_space_index, build_space_synthesis, read_space_log_excerpt
from app.services.space_registry import ensure_global_knowledge_space
from app.services.wiki_writer import write_global_document, write_knowledge_markdown, write_markdown_file

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
PHRASE_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
MARKDOWN_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)")
WIKI_LINK_RE = re.compile(r"!\[\[(?P<embed>[^\]]+)\]\]|\[\[(?P<target>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]")
MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<text>.+?)\s*$")
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
ASCII_WITH_PARTICLE_RE = re.compile(r"^(?P<base>[A-Za-z]+)(?P<particle>가|이|는|은|를|을|와|과|의|도|만|로|에)$")
BODY_FRAGMENT_SPLIT_RE = re.compile(r"[\n\r.!?;:]+")
STRUCTURAL_FRAGMENT_SPLIT_RE = re.compile(r"\s*(?:—|–|,|/|\(|\)|\bvs\.?\b)\s*", re.IGNORECASE)
PHRASE_NORMALIZATIONS = (
    (re.compile(r"삼성\s*DS", re.IGNORECASE), "DS부문"),
    (re.compile(r"삼성DS", re.IGNORECASE), "DS부문"),
    (re.compile(r"DS\s*부문", re.IGNORECASE), "DS부문"),
    (re.compile(r"Device\s+Solutions", re.IGNORECASE), "DS부문"),
)
TITLE_BLACKLIST = {
    "회의록",
    "회의",
    "주간",
    "월간",
    "일간",
    "공지",
    "자료",
    "자료공유",
    "공유",
    "정리",
    "업데이트",
}
WEAK_SINGLE_TOPIC_KEYS = {
    "ai",
    "agent",
    "analysis",
    "assistant",
    "check",
    "vs",
    "dashboard",
    "flow",
    "guide",
    "issue",
    "memo",
    "overview",
    "plan",
    "policy",
    "portal",
    "report",
    "runbook",
    "source",
    "sources",
    "status",
    "wiki",
    "workflow",
    "개요",
    "검토",
    "결과",
    "계획",
    "공유",
    "공통",
    "과정",
    "관련",
    "구조",
    "구축",
    "가이드",
    "대상",
    "대시보드",
    "대응",
    "런북",
    "명분",
    "메모",
    "문서",
    "범위",
    "보고",
    "분석",
    "분야",
    "상태",
    "설명",
    "소개",
    "요약",
    "운영",
    "우리",
    "위키",
    "유형",
    "이중성",
    "이슈",
    "일정",
    "이후",
    "절차",
    "정책",
    "점검",
    "주요",
    "주간",
    "지표",
    "지원",
    "진행",
    "창업",
    "체계",
    "체크리스트",
    "포털",
    "현황",
    "현실",
    "흐름",
    "핵심",
    "그를",
    "기회",
    "미래",
    "모른다",
    "신뢰할",
    "있을까",
    "통제할지",
    "회의",
    "회의록",
    "개인",
    "간극",
    "도구",
    "레이어",
    "선택적",
    "아이디어",
    "인덱싱",
    "작동",
    "작업",
    "하기",
    "활용",
    "활용하여",
    "가치",
    "기능",
    "기본",
    "구축한",
    "결론",
    "내부",
    "맞춤화하기",
    "방법",
    "미치",
    "배경",
    "방향",
    "영향",
    "유형별",
    "장점",
    "제공",
    "향후",
    "형성",
}
STRONG_SINGLE_TOPIC_KEYS = {
    "architecture",
    "altman",
    "amodei",
    "anthropic",
    "claude",
    "codex",
    "combinator",
    "cxl",
    "dario",
    "deepseek",
    "dram",
    "ds부문",
    "gemma",
    "gemini",
    "ghidra",
    "gpu",
    "hbm",
    "ilya",
    "kimi",
    "llm",
    "microsoft",
    "mcp",
    "npu",
    "openai",
    "ollama",
    "qwen3",
    "sam",
    "yc",
    "공급망",
    "공정",
    "국방부",
    "규제",
    "권력",
    "로비",
    "안전",
    "수율",
    "아키텍처",
    "인증",
    "장애",
    "자금",
    "자산",
    "조달",
    "패키징",
}
ALLOWED_WEAK_PHRASE_COMPONENT_KEYS = {
    "ai",
    "agent",
    "assistant",
    "portal",
    "source",
    "sources",
    "wiki",
}
WEAK_PHRASE_COMPONENT_KEYS = WEAK_SINGLE_TOPIC_KEYS.difference(ALLOWED_WEAK_PHRASE_COMPONENT_KEYS)
GENERIC_CONTEXT_STOPWORDS = {
    "개요",
    "체크리스트",
    "현황",
    "진행",
    "상태",
    "점검",
    "계획",
    "대응",
    "요청사항",
    "내용",
    "항목",
    "결과",
    "유형",
    "사항",
    "바로가기",
    "요소",
    "방식",
    "포인트",
    "보기",
    "전환",
    "왼쪽",
    "상단",
    "예시",
    "위한",
    "확인하기",
    "가능한",
    "화면으로",
    "화면",
    "화면에서",
    "실제",
    "값",
    "표",
    "홈",
    "후",
    "어떤",
    "여러",
    "중심",
    "사이드바",
    "원문",
    "그래프",
    "graph",
    "knowledge",
    "preview",
    "view",
    "verify",
    "atlas",
    "bootstrap",
    "cache",
    "hierarchy",
    "static",
    "link",
    "conf",
    "mirror",
    "svg",
    "url",
    "prod",
    "stg",
    "ui",
    "ssl",
    "false",
    "true",
    "geek",
    "geeknews",
    "hada",
    "id",
    "io",
    "news",
    "topic",
}
GENERIC_COMMUNICATION_STOPWORDS = {
    "후속",
    "논의",
    "상황",
    "사본",
    "바로",
    "관련된",
    "메신저",
    "부탁",
    "드립니다",
    "전달",
    "요청",
    "회신",
    "참고",
    "협의",
    "검토",
    "공유",
    "추가",
}
LOW_SIGNAL_SUFFIXES = (
    "합니다",
    "됩니다",
    "있는지",
    "하는지",
    "했는지",
    "되었는지",
    "되었는가",
)
TOPIC_HEADWORDS = {
    "agent",
    "analysis",
    "architecture",
    "assistant",
    "dashboard",
    "flow",
    "guide",
    "issue",
    "memo",
    "model",
    "models",
    "overview",
    "plan",
    "platform",
    "policy",
    "portal",
    "report",
    "runbook",
    "server",
    "sources",
    "wiki",
    "workflow",
    "구조",
    "검증",
    "대시보드",
    "런북",
    "메모",
    "모델",
    "아키텍처",
    "어시스턴트",
    "엔지니어",
    "에이전트",
    "연동",
    "이슈",
    "원칙",
    "논란",
    "절차",
    "정책",
    "플랫폼",
    "포털",
    "위키",
    "흐름",
}
KOREAN_PARTICLE_SUFFIXES = (
    "으로",
    "와의",
    "과의",
    "과",
    "와",
    "을",
    "를",
    "은",
    "는",
    "이",
    "가",
    "의",
    "도",
    "로",
    "에",
    "만",
)
STOPWORDS = {
    "문서",
    "페이지",
    "설명",
    "정리",
    "현재",
    "space",
    "demo",
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
    *GENERIC_CONTEXT_STOPWORDS,
    *TITLE_BLACKLIST,
    *GENERIC_COMMUNICATION_STOPWORDS,
}
SOURCE_WEIGHTS = {
    "title": 9,
    "heading": 7,
    "table": 5,
    "link": 4,
    "summary": 3,
    "body": 2,
    "existing": 6,
}
MAX_PHRASE_TOKENS = 2


@dataclass(frozen=True)
class PhraseToken:
    display: str
    key: str


@dataclass
class PhraseCandidate:
    key: str
    display: str
    score: int = 0
    occurrences: int = 0
    token_count: int = 1
    components: tuple[str, ...] = ()
    sources: set[str] = field(default_factory=set)


class KnowledgeService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.session_factory = create_session_factory(self.settings.database_url)
        self.text_client = TextLLMClient(self.settings)

    def rebuild_space(self, space_key: str) -> list[KnowledgeDocument]:
        return self.rebuild_global()

    def rebuild_global(self) -> list[KnowledgeDocument]:
        session = self.session_factory()
        try:
            docs = self.rebuild_global_with_session(session)
            session.commit()
            return docs
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def rebuild_space_with_session(self, session, space_key: str) -> list[KnowledgeDocument]:
        return self.rebuild_global_with_session(session)

    def rebuild_global_with_session(self, session) -> list[KnowledgeDocument]:
        global_space = ensure_global_knowledge_space(session)
        existing_keyword_topics = self._existing_keyword_topics(session, global_space.id)

        session.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.kind.in_(["entity", "keyword", "lint"]),
            )
        )
        session.flush()

        page_rows = session.execute(
            select(Page, WikiDocument, Space)
            .join(WikiDocument, WikiDocument.page_id == Page.id)
            .join(Space, Space.id == Page.space_id)
            .where(Space.space_key != GLOBAL_KNOWLEDGE_SPACE_KEY)
        ).all()
        inbound_link_counts = Counter(
            target_id for target_id in session.scalars(select(PageLink.target_page_id)).all() if target_id is not None
        )
        docs: list[KnowledgeDocument] = []
        fact_cards: list[dict[str, str]] = []

        for page, wiki_document, page_space in page_rows:
            markdown_path = self.settings.wiki_root / wiki_document.markdown_path
            body = read_markdown_body(markdown_path) if markdown_path.exists() else ""
            summary = wiki_document.summary or self._first_line(body)
            fact_card = self.text_client.summarize_fact_card(page.title, body, prefer_llm=False)
            keyword_signal = self._extract_keyword_signal(page_space.space_key, page.title, summary, body)
            fact_cards.append(
                {
                    "title": page.title,
                    "slug": page.slug,
                    "space_key": page_space.space_key,
                    "space_name": page_space.name or page_space.space_key,
                    "summary": summary or page.title,
                    "href": f"/spaces/{page_space.space_key}/pages/{page.slug}",
                    "prod_url": page.prod_url or "",
                    "fact_card": fact_card,
                    "body": body,
                    "keyword_signal": keyword_signal,
                }
            )

        for keyword in self._build_keyword_documents(fact_cards, existing_keyword_topics):
            docs.append(
                self._upsert_document(
                    session=session,
                    space=global_space,
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
        source_space = session.scalar(select(Space).where(Space.space_key == space_key))
        if source_space is None:
            raise ValueError("unknown space")
        space = ensure_global_knowledge_space(session)
        if not question.strip():
            raise ValueError("question is required")
        if not answer.strip():
            raise ValueError("answer is required")
        saved_at = datetime.now()
        suffix = uuid.uuid4().hex[:8]
        slug = page_slug(question[:40], suffix)
        title = f"분석: {question[:50]}"
        source_links = [self._render_source_reference(item) for item in sources]
        expanded_source_refs = self._expanded_source_refs(session, sources)
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
            source_refs="\n".join(expanded_source_refs),
        )
        self._rebuild_indexes_for_space(session, space)
        append_space_log(
            self.settings.wiki_root,
            source_space.space_key,
            "analysis-save",
            saved_at,
            [{"title": doc.title, "slug": doc.slug, "kind": doc.kind, "href": knowledge_href(doc.kind, doc.slug)}],
        )
        return {
            "kind": doc.kind,
            "slug": doc.slug,
            "title": doc.title,
            "href": knowledge_href(doc.kind, doc.slug),
        }

    def save_query_wiki(
        self,
        query: str,
        selected_space: str | None = None,
        max_documents: int = 8,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict[str, str]:
        session = self.session_factory()
        try:
            result = self.save_query_wiki_with_session(
                session,
                query=query,
                selected_space=selected_space,
                max_documents=max_documents,
                progress_callback=progress_callback,
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save_query_wiki_with_session(
        self,
        session,
        query: str,
        selected_space: str | None = None,
        max_documents: int = 8,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict[str, str]:
        def notify(progress: int, message: str) -> None:
            if progress_callback is not None:
                progress_callback(progress, message)

        normalized_query = self._normalize_query_topic(query)
        if not normalized_query:
            raise ValueError("query is required")
        notify(8, "검색 질의를 정리하는 중입니다.")
        global_space = ensure_global_knowledge_space(session)
        page_rows = session.execute(
            select(Page, WikiDocument, Space)
            .join(WikiDocument, WikiDocument.page_id == Page.id)
            .join(Space, Space.id == Page.space_id)
            .where(Space.space_key != GLOBAL_KNOWLEDGE_SPACE_KEY)
        ).all()
        total_rows = len(page_rows)
        notify(15, f"raw 문서 {total_rows}건을 확인하는 중입니다.")
        ranked: list[tuple[int, dict[str, str]]] = []
        query_tokens = [token.lower() for token in TOKEN_RE.findall(normalized_query)]
        for index, (page, wiki_document, space) in enumerate(page_rows, start=1):
            if selected_space and selected_space not in {"", "all"} and space.space_key != selected_space:
                continue
            markdown_path = self.settings.wiki_root / wiki_document.markdown_path
            if not markdown_path.exists():
                continue
            body = read_markdown_body(markdown_path)
            score = self._score_raw_query_match(query_tokens, page.title, wiki_document.summary or "", body)
            if score <= 0:
                continue
            fact_card = self.text_client.summarize_fact_card(page.title, body, prefer_llm=False)
            ranked.append(
                (
                    score,
                    {
                        "title": page.title,
                        "slug": page.slug,
                        "space_key": space.space_key,
                        "space_name": space.name or space.space_key,
                        "summary": wiki_document.summary or self._first_line(body),
                        "href": f"/spaces/{space.space_key}/pages/{page.slug}",
                        "prod_url": page.prod_url or "",
                        "fact_card": fact_card,
                        "body": body,
                    },
                )
            )
            if total_rows and (index == total_rows or index == 1 or index % 5 == 0):
                scan_progress = 15 + int((index / max(total_rows, 1)) * 45)
                notify(scan_progress, f"raw 문서 {index}/{total_rows}건을 분석하는 중입니다.")
        if not ranked:
            raise ValueError("no raw pages matched the query")
        ranked.sort(key=lambda item: (-item[0], item[1]["title"].lower()))
        items = [payload for _score, payload in ranked[:max_documents]]
        notify(68, f"관련 raw 문서 {len(items)}건을 주제 문서로 정리하는 중입니다.")
        related_keywords = self._related_topics_from_items(session, items, exclude_title=normalized_query)
        body = self.text_client.synthesize_topic_page(
            ", ".join(sorted({item["space_key"] for item in items})),
            normalized_query,
            items,
            related_keywords,
            prefer_llm=False,
        )
        notify(85, "위키 문서를 저장하는 중입니다.")
        doc = self._upsert_document(
            session=session,
            space=global_space,
            kind="query",
            slug=self._keyword_slug(normalized_query),
            title=normalized_query,
            summary=self._keyword_summary(normalized_query, items),
            body=self._ensure_keyword_sections(normalized_query, items, related_keywords, body),
            source_refs="\n".join(self._page_reference(item) for item in items),
        )
        notify(92, "인덱스와 연결 정보를 갱신하는 중입니다.")
        self._rebuild_indexes_for_space(session, global_space)
        append_space_log(
            self.settings.wiki_root,
            selected_space if selected_space and selected_space not in {"", "all"} else "GLOBAL",
            "query-build",
            datetime.now(),
            [{"title": doc.title, "slug": doc.slug, "kind": doc.kind, "href": knowledge_href(doc.kind, doc.slug)}],
            window_label=f"query: {normalized_query}",
        )
        notify(100, "위키 생성이 완료되었습니다.")
        return {
            "kind": doc.kind,
            "slug": doc.slug,
            "title": doc.title,
            "href": knowledge_href(doc.kind, doc.slug),
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

        space = ensure_global_knowledge_space(session)
        doc = session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.space_id == space.id,
                KnowledgeDocument.kind == normalized_kind,
                KnowledgeDocument.slug == slug,
            )
        )
        if doc is None:
            doc = session.scalar(
                select(KnowledgeDocument).where(
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
            space_key,
            "knowledge-edit",
            updated_at,
            [{"title": doc.title, "slug": doc.slug, "kind": doc.kind, "href": knowledge_href(doc.kind, doc.slug)}],
        )
        return {
            "kind": doc.kind,
            "slug": doc.slug,
            "title": doc.title,
            "href": knowledge_href(doc.kind, doc.slug),
        }

    def list_documents(self, session, space_id: int | None = None) -> list[KnowledgeDocument]:
        statement = select(KnowledgeDocument).order_by(KnowledgeDocument.updated_at.desc())
        if space_id is not None:
            statement = statement.where(KnowledgeDocument.space_id == space_id)
        return session.scalars(statement).all()

    def _rebuild_indexes_for_space(self, session, _space: Space) -> None:
        global_space = ensure_global_knowledge_space(session)
        knowledge_docs = [
            {
                "title": doc.title,
                "slug": doc.slug,
                "kind": doc.kind,
                "summary": doc.summary or doc.title,
                "href": knowledge_href(doc.kind, doc.slug),
                "source_spaces": source_space_keys(doc.source_refs),
            }
            for doc in self.list_documents(session, global_space.id)
        ]

        grouped_documents: dict[str, list[dict[str, str]]] = {}
        visible_spaces = session.scalars(
            select(Space).where(Space.space_key != GLOBAL_KNOWLEDGE_SPACE_KEY).order_by(Space.space_key)
        ).all()
        for current_space in visible_spaces:
            current_page_rows = session.execute(
                select(Page, WikiDocument).join(WikiDocument, WikiDocument.page_id == Page.id).where(Page.space_id == current_space.id)
            ).all()
            current_page_docs = [
                {
                    "title": page.title,
                    "slug": page.slug,
                    "summary": wiki_document.summary or page.title,
                    "href": f"/spaces/{current_space.space_key}/pages/{page.slug}",
                    "kind": "page",
                }
                for page, wiki_document in current_page_rows
            ]
            grouped_documents[current_space.space_key] = [
                *current_page_docs,
                *[
                    doc
                    for doc in knowledge_docs
                    if current_space.space_key in set(doc.get("source_spaces") or [])
                ],
            ]
            build_space_index(self.settings.wiki_root, current_space.space_key, current_page_docs, knowledge_docs)
            build_space_synthesis(
                self.settings.wiki_root,
                current_space.space_key,
                current_page_docs,
                generated_at=datetime.now(),
                recent_log_entries=read_space_log_excerpt(self.settings.wiki_root, current_space.space_key),
            )
        build_global_index(self.settings.wiki_root, grouped_documents, knowledge_docs)

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
        source_spaces = source_space_keys(source_refs)
        frontmatter = {
            "space_key": space.space_key,
            "kind": normalized_kind,
            "slug": slug,
            "title": title,
            "aliases": [title],
            "tags": [*[f"space/{value}" for value in source_spaces], f"kind/{normalized_kind}", "source/wiki"],
            "source_spaces": source_spaces,
            "source_refs": source_refs or "",
            "updated_at": datetime.now().isoformat(),
        }
        markdown_path = write_knowledge_markdown(
            root=self.settings.wiki_root,
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

    def _normalize_query_topic(self, query: str) -> str:
        tokens = self._extract_phrase_tokens(query, GLOBAL_KNOWLEDGE_SPACE_KEY, drop_title_blacklist=False)
        if tokens:
            return " ".join(token.display for token in tokens[:MAX_PHRASE_TOKENS]).strip()
        normalized = self._apply_phrase_normalization(query).strip()
        if normalized.isascii():
            return normalized.title()
        return normalized

    @staticmethod
    def _score_raw_query_match(tokens: list[str], title: str, summary: str, body: str) -> int:
        if not tokens:
            return 0
        title_text = title.lower()
        summary_text = summary.lower()
        body_text = body.lower()
        score = 0
        for token in tokens:
            score += title_text.count(token) * 12
            score += summary_text.count(token) * 8
            score += body_text.count(token) * 2
        return score

    def _related_topics_from_items(
        self,
        session,
        items: list[dict[str, str]],
        exclude_title: str,
        limit: int = 6,
    ) -> list[str]:
        global_space = ensure_global_knowledge_space(session)
        existing_topics = {
            doc.title
            for doc in session.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.space_id == global_space.id,
                    KnowledgeDocument.kind == "keyword",
                )
            ).all()
        }
        related: Counter[str] = Counter()
        exclude_key = self._normalize_topic_key(exclude_title)
        for item in items:
            signal = self._extract_keyword_signal(item["space_key"], item["title"], item.get("summary", ""), item.get("body", ""))
            for topic in self._select_keywords_for_page(signal, {self._normalize_topic_key(value): value for value in existing_topics}):
                if self._normalize_topic_key(topic) == exclude_key:
                    continue
                related[topic] += 1
        return [topic for topic, _count in related.most_common(limit)]

    def _build_keyword_documents(
        self,
        fact_cards: list[dict[str, str]],
        existing_topics: dict[str, str],
    ) -> list[dict[str, str]]:
        if not fact_cards:
            return []

        total_scores: Counter[str] = Counter()
        doc_counts: Counter[str] = Counter()
        selected_topics_by_slug: dict[str, list[str]] = {}
        for item in fact_cards:
            signal = item["keyword_signal"]
            selected_topics = self._select_keywords_for_page(signal, existing_topics)
            selected_topics_by_slug[item["slug"]] = selected_topics
            candidates: dict[str, PhraseCandidate] = signal["candidates"]  # type: ignore[assignment]
            for topic in selected_topics:
                topic_key = self._normalize_topic_key(topic)
                total_scores[topic] += candidates.get(topic_key, PhraseCandidate(key=topic_key, display=topic)).score or 1
                doc_counts[topic] += 1

        keyword_pages: dict[str, list[dict[str, str]]] = {}
        co_occurrence: dict[str, Counter[str]] = {}
        for item in fact_cards:
            selected_topics = selected_topics_by_slug.get(item["slug"], [])
            if not selected_topics:
                continue
            for topic in selected_topics:
                keyword_pages.setdefault(topic, []).append(item)
            for topic in selected_topics:
                neighbors = [candidate for candidate in selected_topics if candidate != topic]
                co_occurrence.setdefault(topic, Counter()).update(neighbors)

        documents: list[dict[str, str]] = []
        for topic, items in sorted(
            keyword_pages.items(),
            key=lambda pair: (-doc_counts[pair[0]], -total_scores[pair[0]], pair[0]),
        ):
            related_topics = [candidate for candidate, _count in co_occurrence.get(topic, Counter()).most_common(6)]
            source_spaces = [item["space_key"] for item in items]
            synthesized = self.text_client.synthesize_topic_page(
                ", ".join(sorted(set(source_spaces))),
                topic,
                items,
                related_topics,
                prefer_llm=False,
            )
            documents.append(
                {
                    "slug": self._keyword_slug(topic),
                    "title": topic,
                    "summary": self._keyword_summary(topic, items),
                    "body": self._ensure_keyword_sections(topic, items, related_topics, synthesized),
                    "source_refs": [page_link(item["space_key"], item["slug"], item["title"]) for item in items],
                }
            )
        return documents

    def _expanded_source_refs(self, session, sources: list[dict[str, str]]) -> list[str]:
        refs: list[str] = []
        for item in sources:
            href = self._source_href(item)
            if href not in refs:
                refs.append(href)
            kind = normalize_knowledge_kind(str(item.get("kind") or "page"))
            if kind == "page":
                continue
            doc = session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.kind == kind,
                    KnowledgeDocument.slug == str(item.get("slug") or ""),
                )
            )
            if doc is None or not doc.source_refs:
                continue
            for line in str(doc.source_refs).splitlines():
                normalized = line.strip()
                if normalized and normalized not in refs:
                    refs.append(normalized)
        return refs

    @staticmethod
    def _source_href(item: dict[str, str]) -> str:
        space_key = str(item.get("space_key") or "").strip()
        slug = str(item.get("slug") or "").strip()
        kind = normalize_knowledge_kind(str(item.get("kind") or "page"))
        if kind == "page":
            return page_link(space_key, slug, str(item.get("title") or slug))
        return knowledge_link(kind, slug, str(item.get("title") or slug))

    @classmethod
    def _render_source_reference(cls, item: dict[str, str]) -> str:
        internal = cls._source_href(item)
        kind = normalize_knowledge_kind(str(item.get("kind") or "page"))
        external = str(item.get("source_url") or item.get("prod_url") or "").strip()
        if kind == "page" and external.startswith(("http://", "https://")):
            return f"- {internal} ([Confluence 원문]({external}))"
        return f"- {internal}"

    @staticmethod
    def _keyword_summary(topic: str, items: list[dict[str, str]]) -> str:
        titles = ", ".join(item["title"] for item in items[:2])
        if len(items) > 2:
            titles = f"{titles} 외 {len(items) - 2}건"
        source_spaces = sorted({item["space_name"] for item in items})
        if source_spaces:
            return f"{topic} 주제와 직접 연결되는 문서: {titles} · {'/'.join(source_spaces)}"
        return f"{topic} 주제와 직접 연결되는 문서: {titles}"

    def _ensure_keyword_sections(
        self,
        title: str,
        items: list[dict[str, str]],
        related_keywords: list[str],
        body: str,
    ) -> str:
        source_spaces = sorted({item["space_key"] for item in items})
        section_requirements = {
            "## 개요": self._default_keyword_overview(title, items),
            "## 핵심 사실": "\n".join(f"- {item['title']}: {item['summary']}" for item in items) or "- 정보 없음",
            "## 관련 문서": "\n".join(self._page_reference(item) for item in items),
            "## 관련 주제": "\n".join(
                f"- {knowledge_link('keyword', self._keyword_slug(keyword), keyword)}" for keyword in related_keywords if keyword != title
            )
            or "- 관련 주제가 아직 충분히 정리되지 않았습니다.",
            "## 원문 근거": "\n".join(self._page_reference(item) for item in items),
            "## 참고 Space": "\n".join(f"- {item}" for item in source_spaces) or "- 없음",
        }
        normalized = body.strip()
        if not normalized.startswith("# "):
            normalized = f"# {title}\n\n{normalized}".strip()
        normalized = self._upsert_markdown_section(normalized, "## 개요", section_requirements["## 개요"], replace_existing=False)
        normalized = self._upsert_markdown_section(normalized, "## 핵심 사실", section_requirements["## 핵심 사실"], replace_existing=False)
        normalized = self._upsert_markdown_section(normalized, "## 참고 Space", section_requirements["## 참고 Space"], replace_existing=True)
        normalized = self._upsert_markdown_section(normalized, "## 관련 문서", section_requirements["## 관련 문서"], replace_existing=True)
        normalized = self._upsert_markdown_section(normalized, "## 관련 주제", section_requirements["## 관련 주제"], replace_existing=True)
        normalized = self._upsert_markdown_section(normalized, "## 원문 근거", section_requirements["## 원문 근거"], replace_existing=True)
        return normalized.strip()

    @staticmethod
    def _upsert_markdown_section(markdown: str, heading: str, content: str, *, replace_existing: bool) -> str:
        rendered = f"{heading}\n\n{content.strip()}".strip()
        pattern = re.compile(rf"(?ms)^{re.escape(heading)}\s*\n.*?(?=^##\s|\Z)")
        if pattern.search(markdown):
            if not replace_existing:
                return markdown.strip()
            return pattern.sub(f"{rendered}\n\n", markdown, count=1).strip()
        return f"{markdown.rstrip()}\n\n{rendered}".strip()

    @staticmethod
    def _default_keyword_overview(title: str, items: list[dict[str, str]]) -> str:
        if not items:
            return f"여러 raw 문서에서 '{title}' 주제와 연결되는 내용을 모아 정리한 페이지입니다."
        source_spaces = ", ".join(sorted({item['space_name'] for item in items}))
        return f"{source_spaces}에서 반복적으로 나타나는 '{title}' 주제를 한 페이지로 통합 정리한 문서입니다."

    @staticmethod
    def _page_reference(item: dict[str, str]) -> str:
        reference = page_link(item["space_key"], item["slug"], item["title"])
        prod_url = str(item.get("prod_url") or "").strip()
        if prod_url.startswith(("http://", "https://")):
            return f"- {reference} ([Confluence 원문]({prod_url}))"
        return f"- {reference}"

    def _existing_keyword_topics(self, session, space_id: int) -> dict[str, str]:
        existing_docs = session.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.space_id == space_id, KnowledgeDocument.kind == "keyword")
        ).all()
        topics: dict[str, str] = {}
        for doc in existing_docs:
            if not doc.title:
                continue
            topics[self._normalize_topic_key(doc.title)] = doc.title
        return topics

    def _extract_keyword_signal(self, space_key: str, title: str, summary: str, body: str) -> dict[str, object]:
        normalized_title = self._apply_phrase_normalization(title)
        normalized_summary = self._apply_phrase_normalization(summary)
        normalized_body = self._normalize_keyword_source(body)

        candidates: dict[str, PhraseCandidate] = {}
        document_token_counts: Counter[str] = Counter()
        structural_token_counts: Counter[str] = Counter()

        fragments_by_source = {
            "title": [normalized_title],
            "heading": self._extract_heading_texts(body),
            "table": self._extract_table_header_texts(body),
            "link": self._extract_link_texts(body),
            "summary": [normalized_summary] if normalized_summary else [],
            "body": self._extract_body_fragments(normalized_body),
        }

        for source, fragments in fragments_by_source.items():
            for fragment in fragments:
                for chunk in self._split_keyword_fragment(fragment, source):
                    tokens = self._extract_phrase_tokens(chunk, space_key, drop_title_blacklist=source != "title")
                    if not tokens:
                        continue
                    for token in tokens:
                        document_token_counts[token.key] += 1
                        if source != "body":
                            structural_token_counts[token.key] += 1
                    self._register_phrase_candidates(candidates, tokens, source)

        return {
            "page_title": title,
            "page_summary": summary,
            "candidates": candidates,
            "document_token_counts": document_token_counts,
            "structural_token_counts": structural_token_counts,
            "doc_length": len(normalized_body),
        }

    def _select_keywords_for_page(self, signal: dict[str, object], existing_topics: dict[str, str]) -> list[str]:
        candidates: dict[str, PhraseCandidate] = {
            key: PhraseCandidate(
                key=value.key,
                display=value.display,
                score=value.score,
                occurrences=value.occurrences,
                token_count=value.token_count,
                components=value.components,
                sources=set(value.sources),
            )
            for key, value in (signal["candidates"] or {}).items()  # type: ignore[union-attr]
        }
        document_token_counts: Counter[str] = signal["document_token_counts"]  # type: ignore[assignment]
        doc_length = int(signal["doc_length"])  # type: ignore[arg-type]

        self._inject_existing_topic_candidates(candidates, existing_topics, document_token_counts)

        minimum_count = self._minimum_keyword_count(doc_length)
        candidate_payload = [
            {
                "topic": candidate.display,
                "key": candidate.key,
                "score": candidate.score,
                "occurrences": candidate.occurrences,
                "sources": sorted(candidate.sources),
                "token_count": candidate.token_count,
                "components": list(candidate.components),
            }
            for candidate in sorted(
                (candidate for candidate in candidates.values() if self._is_candidate_usable(candidate)),
                key=lambda item: (-item.token_count, -item.score, -item.occurrences, item.display.lower()),
            )
        ]
        return self.text_client.select_topic_phrases(
            page_title=str(signal["page_title"]),
            page_summary=str(signal["page_summary"] or ""),
            candidates=candidate_payload,
            existing_topics=list(existing_topics.values()),
            minimum_count=minimum_count,
        )

    @staticmethod
    def _is_candidate_usable(candidate: PhraseCandidate) -> bool:
        if candidate.token_count > 1:
            return True

        key = candidate.key.lower()
        structural_sources = {"title", "heading", "table", "link", "existing"}
        if key in {item.lower() for item in GENERIC_COMMUNICATION_STOPWORDS}:
            return False
        if key in WEAK_SINGLE_TOPIC_KEYS:
            return False
        if key in STRONG_SINGLE_TOPIC_KEYS and (
            candidate.sources.intersection(structural_sources) or candidate.occurrences >= 2
        ):
            return True
        if (
            candidate.display.isascii()
            and candidate.display.upper() == candidate.display
            and 2 <= len(candidate.display) <= 8
            and candidate.sources.intersection(structural_sources)
            and candidate.occurrences >= 2
        ):
            return True
        return False

    @classmethod
    def _minimum_keyword_count(cls, doc_length: int) -> int:
        if doc_length <= 150:
            return 3
        if doc_length <= 300:
            return 6
        if doc_length <= 600:
            return 9
        if doc_length <= 2000:
            return 12
        if doc_length <= 5000:
            return 15
        if doc_length <= 10000:
            return 18
        if doc_length <= 20000:
            return 24
        return 30

    @classmethod
    def _extract_phrase_tokens(cls, text: str, space_key: str, drop_title_blacklist: bool = True) -> list[PhraseToken]:
        tokens: list[PhraseToken] = []
        normalized_text = cls._apply_phrase_normalization(text)
        for raw_token in PHRASE_TOKEN_RE.findall(normalized_text):
            token = cls._normalize_phrase_token(raw_token, space_key, drop_title_blacklist=drop_title_blacklist)
            if token is not None:
                tokens.append(token)
        return tokens

    @classmethod
    def _normalize_phrase_token(
        cls,
        raw_token: str,
        space_key: str,
        drop_title_blacklist: bool = True,
    ) -> PhraseToken | None:
        normalized = cls._apply_phrase_normalization(str(raw_token or "").strip())
        if not normalized or normalized[0].isdigit():
            return None
        ascii_with_particle = ASCII_WITH_PARTICLE_RE.match(normalized)
        if ascii_with_particle:
            normalized = ascii_with_particle.group("base")
        normalized = cls._strip_korean_particle(normalized)
        if len(normalized) < 2:
            return None
        key = cls._normalize_topic_key(normalized)
        if not key or key == space_key.lower():
            return None
        if key in STOPWORDS:
            return None
        if drop_title_blacklist and key in TITLE_BLACKLIST:
            return None
        if any(key.endswith(suffix) for suffix in LOW_SIGNAL_SUFFIXES):
            return None
        display = cls._display_topic_token(normalized)
        return PhraseToken(display=display, key=key)

    @classmethod
    def _register_phrase_candidates(
        cls,
        candidates: dict[str, PhraseCandidate],
        tokens: list[PhraseToken],
        source: str,
    ) -> None:
        if not tokens:
            return
        base_weight = SOURCE_WEIGHTS.get(source, 1)
        for token in tokens:
            cls._add_phrase_candidate(candidates, [token], source, max(1, base_weight - 2))
        if source == "body":
            return
        upper_bound = min(MAX_PHRASE_TOKENS, len(tokens))
        for size in range(2, upper_bound + 1):
            for start in range(0, len(tokens) - size + 1):
                phrase_tokens = tokens[start : start + size]
                if not cls._is_meaningful_phrase(phrase_tokens):
                    continue
                cls._add_phrase_candidate(candidates, phrase_tokens, source, base_weight + size)

    @classmethod
    def _add_phrase_candidate(
        cls,
        candidates: dict[str, PhraseCandidate],
        tokens: list[PhraseToken],
        source: str,
        weight: int,
    ) -> None:
        display = " ".join(token.display for token in tokens).strip()
        key = cls._normalize_topic_key(display)
        if not key:
            return
        candidate = candidates.get(key)
        if candidate is None:
            candidate = PhraseCandidate(
                key=key,
                display=display,
                token_count=len(tokens),
                components=tuple(token.key for token in tokens),
            )
            candidates[key] = candidate
        elif cls._prefer_display(display, candidate.display):
            candidate.display = display
        candidate.score += weight
        candidate.occurrences += 1
        candidate.sources.add(source)

    @classmethod
    def _inject_existing_topic_candidates(
        cls,
        candidates: dict[str, PhraseCandidate],
        existing_topics: dict[str, str],
        document_token_counts: Counter[str],
    ) -> None:
        for key, display in existing_topics.items():
            components = cls._topic_components(display)
            if not components:
                continue
            if len(components) == 1 and components[0] in WEAK_SINGLE_TOPIC_KEYS:
                continue
            if len(components) > 1 and not cls._is_meaningful_phrase(
                [PhraseToken(display=component, key=component) for component in components]
            ):
                continue
            if not all(document_token_counts.get(component, 0) > 0 for component in components):
                continue
            candidate = candidates.get(key)
            if candidate is None:
                candidates[key] = PhraseCandidate(
                    key=key,
                    display=display,
                    score=SOURCE_WEIGHTS["existing"],
                    occurrences=1,
                    token_count=len(components),
                    components=tuple(components),
                    sources={"existing"},
                )
                continue
            candidate.score += SOURCE_WEIGHTS["existing"]
            candidate.occurrences += 1
            candidate.sources.add("existing")

    @classmethod
    def _topic_components(cls, text: str) -> list[str]:
        components: list[str] = []
        for raw_token in PHRASE_TOKEN_RE.findall(cls._apply_phrase_normalization(text)):
            key = cls._normalize_topic_key(raw_token)
            if key and key not in STOPWORDS:
                components.append(key)
        return components

    @staticmethod
    def _prefer_display(candidate: str, existing: str) -> bool:
        if len(candidate.split()) != len(existing.split()):
            return len(candidate.split()) > len(existing.split())
        return candidate != candidate.lower() and existing == existing.lower()

    @staticmethod
    def _is_meaningful_phrase(tokens: list[PhraseToken]) -> bool:
        if len(tokens) < 2:
            return False
        unique_keys = {token.key for token in tokens}
        if len(unique_keys) != len(tokens):
            return False
        if any(token.key in GENERIC_COMMUNICATION_STOPWORDS for token in tokens):
            return False
        headword = tokens[-1].key
        weak_components = [token.key for token in tokens if token.key in WEAK_PHRASE_COMPONENT_KEYS]
        if headword in TOPIC_HEADWORDS:
            return True
        if weak_components and len(weak_components) == len(tokens):
            return False
        if weak_components:
            return False
        if all(token.display.isascii() for token in tokens):
            return any(token.key in STRONG_SINGLE_TOPIC_KEYS for token in tokens)
        if all(not token.display.isascii() for token in tokens):
            return any(token.key in STRONG_SINGLE_TOPIC_KEYS for token in tokens)
        if tokens[0].key in STRONG_SINGLE_TOPIC_KEYS and headword in STRONG_SINGLE_TOPIC_KEYS:
            return True
        return False

    @classmethod
    def _display_topic_token(cls, token: str) -> str:
        normalized = cls._apply_phrase_normalization(token)
        if normalized == "DS부문":
            return "DS부문"
        if normalized.isupper():
            return normalized
        if normalized.isascii():
            return normalized.title()
        return normalized

    @classmethod
    def _normalize_topic_key(cls, token: str) -> str:
        normalized = cls._apply_phrase_normalization(str(token or "").strip())
        if not normalized:
            return ""
        if normalized == "DS부문":
            return "ds부문"
        normalized = cls._strip_korean_particle(normalized)
        if len(normalized) < 2:
            return ""
        if normalized and normalized[0].isdigit():
            return ""
        return normalized.lower()

    @staticmethod
    def _strip_korean_particle(token: str) -> str:
        normalized = str(token or "").strip()
        for suffix in KOREAN_PARTICLE_SUFFIXES:
            if len(normalized) > len(suffix) + 1 and normalized.endswith(suffix):
                return normalized[: -len(suffix)]
        return normalized

    @classmethod
    def _apply_phrase_normalization(cls, text: str) -> str:
        normalized = str(text or "")
        for pattern, replacement in PHRASE_NORMALIZATIONS:
            normalized = pattern.sub(replacement, normalized)
        return normalized

    @classmethod
    def _normalize_keyword_source(cls, body: str) -> str:
        text = cls._apply_phrase_normalization(body)
        text = WIKI_LINK_RE.sub(lambda match: match.group("label") or match.group("target") or "", text)
        text = MARKDOWN_LINK_RE.sub(lambda match: match.group("label"), text)
        text = text.replace("![[", "[[")
        return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)

    @classmethod
    def _extract_body_fragments(cls, body_text: str) -> list[str]:
        fragments = [fragment.strip() for fragment in BODY_FRAGMENT_SPLIT_RE.split(body_text) if fragment.strip()]
        return fragments

    @classmethod
    def _split_keyword_fragment(cls, fragment: str, source: str) -> list[str]:
        normalized = str(fragment or "").strip()
        if not normalized:
            return []
        if source == "body":
            return [normalized]
        pieces = [piece.strip() for piece in STRUCTURAL_FRAGMENT_SPLIT_RE.split(normalized) if piece.strip()]
        return pieces or [normalized]

    @classmethod
    def _extract_heading_texts(cls, body: str) -> list[str]:
        headings: list[str] = []
        normalized = cls._apply_phrase_normalization(body)
        for line in normalized.splitlines():
            match = MARKDOWN_HEADING_RE.match(line.strip())
            if match:
                headings.append(match.group("text"))
        soup = BeautifulSoup(normalized, "html.parser")
        for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            text = element.get_text(" ", strip=True)
            if text:
                headings.append(text)
        return headings

    @classmethod
    def _extract_table_header_texts(cls, body: str) -> list[str]:
        headers: list[str] = []
        normalized = cls._apply_phrase_normalization(body)
        soup = BeautifulSoup(normalized, "html.parser")
        for element in soup.find_all("th"):
            text = element.get_text(" ", strip=True)
            if text:
                headers.append(text)
        lines = normalized.splitlines()
        for index, line in enumerate(lines[:-1]):
            if "|" not in line:
                continue
            if not MARKDOWN_TABLE_SEPARATOR_RE.match(lines[index + 1].strip()):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            headers.extend(cell for cell in cells if cell)
        return headers

    @classmethod
    def _extract_link_texts(cls, body: str) -> list[str]:
        texts: list[str] = []
        normalized = cls._apply_phrase_normalization(body)
        for match in MARKDOWN_LINK_RE.finditer(normalized):
            label = (match.group("label") or "").strip()
            if label:
                texts.append(label)
        for match in WIKI_LINK_RE.finditer(normalized):
            if match.group("embed"):
                continue
            label = (match.group("label") or match.group("target") or "").strip()
            if label:
                texts.append(label)
        return texts

    @staticmethod
    def _keyword_slug(keyword: str) -> str:
        return slugify(keyword, allow_unicode=True) or "keyword"
