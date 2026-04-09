from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlencode

from bs4 import BeautifulSoup
from fastapi import APIRouter, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import OperationalError

from app.core.knowledge import (
    GLOBAL_KNOWLEDGE_SPACE_KEY,
    knowledge_href,
    knowledge_label,
    knowledge_segment,
    legacy_knowledge_href,
    normalize_knowledge_kind,
    source_space_keys,
)
from app.core.markdown import read_markdown_body, read_markdown_document, render_markdown
from app.db.models import KnowledgeDocument, Page, PageVersion, Space, User, WikiDocument
from app.graph.builder import build_graph_payload, build_knowledge_graph_payload
from app.services.auth_service import authenticate_user, create_user, role_allows
from app.services.schedule_service import ScheduleService
from app.services.space_registry import upsert_space
from app.services.wiki_writer import write_markdown_file
from app.services.knowledge_service import KnowledgeService
from app.services.sync_service import SyncService
from app.services.wiki_qa import WikiQAService

router = APIRouter()
_RAW_PAGE_REF_RE = re.compile(r"(?:/spaces/|spaces/)(?P<space_key>[^/\]]+)/pages/(?P<slug>[^|\]\s]+)")
_SOURCE_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_MARKDOWN_LINK_RE = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)")
_WIKI_LINK_RE = re.compile(r"!\[\[(?P<embed>[^\]]+)\]\]|\[\[(?P<target>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]")
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_MARKDOWN_LIST_RE = re.compile(r"^[>\-\*\d\.\)\s]+")
_MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _session_factory(request: Request):
    return request.app.state.session_factory


def _settings(request: Request):
    return request.app.state.settings


def _query_jobs(request: Request):
    return request.app.state.query_jobs


def _current_user(session, request: Request) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        return session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def _role_label(role: str | None) -> str:
    return {
        "viewer": "조회자",
        "editor": "편집자",
        "admin": "관리자",
    }.get(str(role or "").strip(), "미지정")


def _login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


def _admin_redirect(*, notice: str | None = None, error: str | None = None) -> RedirectResponse:
    params: dict[str, str] = {}
    if notice:
        params["notice"] = notice
    if error:
        params["error"] = error
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/admin/operations{suffix}", status_code=303)


def _is_sqlite_lock_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def _admin_write_locked_redirect(target: str) -> RedirectResponse:
    return _admin_redirect(error=f"{target} 저장 중 DB가 사용 중입니다. 잠시 후 다시 시도해주세요.")


def _ensure_html_role(session, request: Request, required_role: str = "viewer") -> User | RedirectResponse:
    user = _current_user(session, request)
    if user is None or not user.is_active:
        return _login_redirect(request)
    if not role_allows(user.role, required_role):
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


def _ensure_api_role(session, request: Request, required_role: str = "viewer") -> User:
    user = _current_user(session, request)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not role_allows(user.role, required_role):
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


def _ensure_admin_token_or_session(request: Request, x_admin_token: str | None = None) -> None:
    if x_admin_token and x_admin_token == _settings(request).sync_admin_token:
        return
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
    finally:
        session.close()


def _load_page_row(session, space_key: str, slug: str):
    statement = (
        select(Page, WikiDocument)
        .join(Space, Space.id == Page.space_id)
        .join(WikiDocument, WikiDocument.page_id == Page.id)
        .where(Space.space_key == space_key, Page.slug == slug)
    )
    return session.execute(statement).first()


def _meta_description(text: str, fallback: str = "Confluence mirror에서 동기화한 markdown wiki를 읽기 중심 UI로 제공합니다.") -> str:
    compact = " ".join(str(text or "").split()).strip()
    return (compact or fallback)[:180]


def _space_display_name(space: Space) -> str:
    return space.name or space.space_key


def _space_name_by_key(spaces: list[Space]) -> dict[str, str]:
    return {space.space_key: _space_display_name(space) for space in spaces}


def _visible_spaces(session) -> list[Space]:
    return session.scalars(
        select(Space).where(Space.space_key != GLOBAL_KNOWLEDGE_SPACE_KEY).order_by(Space.space_key)
    ).all()


def _sidebar_metrics(session) -> dict[str, int]:
    spaces = _visible_spaces(session)
    raw_page_count = int(session.scalar(select(func.count(Page.id))) or 0)
    visible_kinds = {"keyword", "analysis", "query", "lint"}
    knowledge_rows = session.scalars(
        select(KnowledgeDocument.kind)
        .join(Space, Space.id == KnowledgeDocument.space_id)
        .where(Space.space_key == GLOBAL_KNOWLEDGE_SPACE_KEY)
    ).all()
    knowledge_count = sum(1 for kind in knowledge_rows if normalize_knowledge_kind(kind) in visible_kinds)
    return {
        "raw_page_count": raw_page_count,
        "knowledge_count": knowledge_count,
        "source_space_count": len(spaces),
    }


def _with_sidebar_metrics(context: dict, session) -> dict:
    enriched = dict(context)
    enriched.setdefault("sidebar_metrics", _sidebar_metrics(session))
    request = enriched.get("request")
    if isinstance(request, Request):
        current_user = _current_user(session, request)
        enriched.setdefault("current_user", current_user)
        enriched.setdefault("current_user_role_label", _role_label(current_user.role if current_user else None))
        enriched.setdefault("can_edit", bool(current_user and role_allows(current_user.role, "editor")))
        enriched.setdefault("can_admin", bool(current_user and role_allows(current_user.role, "admin")))
    return enriched


def _replace_wiki_link_with_label(match: re.Match[str]) -> str:
    if match.group("embed"):
        return ""
    label = match.group("label")
    target = match.group("target") or ""
    if label:
        return label
    return target.rsplit("/", 1)[-1]


def _display_document_title(space_key: str | None, title: str | None) -> str:
    normalized = str(title or "").strip()
    prefix = f"{space_key} " if space_key else ""
    if normalized.startswith(prefix):
        return normalized[len(prefix) :]
    return normalized


def _display_summary_excerpt(text: str | None, *, title: str | None = None, limit: int = 180) -> str:
    normalized_title = " ".join(str(title or "").split()).strip().lower()
    cleaned_segments: list[str] = []
    for raw_line in str(text or "").splitlines():
        stripped = raw_line.strip()
        if not stripped or _MARKDOWN_TABLE_SEPARATOR_RE.match(stripped):
            continue
        if stripped.startswith(("```", "> [!", "![[", "![", "---")):
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|") if cell.strip()]
            stripped = " / ".join(cells[:3])
        stripped = _MARKDOWN_HEADING_RE.sub("", stripped)
        stripped = _MARKDOWN_LIST_RE.sub("", stripped)
        stripped = _MARKDOWN_LINK_RE.sub(lambda match: match.group("label"), stripped)
        stripped = _WIKI_LINK_RE.sub(_replace_wiki_link_with_label, stripped)
        stripped = re.sub(r"`([^`]*)`", r"\1", stripped)
        stripped = BeautifulSoup(stripped, "html.parser").get_text(" ", strip=True)
        stripped = " ".join(stripped.split()).strip(" -|")
        if not stripped:
            continue
        if normalized_title and stripped.lower() == normalized_title:
            continue
        if stripped not in cleaned_segments:
            cleaned_segments.append(stripped)
    if not cleaned_segments:
        return "-"
    excerpt_parts: list[str] = []
    total_length = 0
    for segment in cleaned_segments:
        separator_length = 2 if excerpt_parts else 0
        if total_length + len(segment) + separator_length > limit:
            break
        excerpt_parts.append(segment)
        total_length += len(segment) + separator_length
    excerpt = " · ".join(excerpt_parts or cleaned_segments[:1]).strip()
    return excerpt[:limit].rstrip(" .,") if excerpt else "-"


def _paginate_items(items: list[dict], page: int, per_page: int) -> tuple[list[dict], dict | None]:
    total_items = len(items)
    if total_items <= 0:
        return items, None
    total_pages = max(1, (total_items + per_page - 1) // per_page)
    current_page = min(max(page, 1), total_pages)
    start = (current_page - 1) * per_page
    end = start + per_page
    sliced = items[start:end]
    if total_pages == 1:
        return sliced, None

    window: list[int | None] = []
    if total_pages <= 7:
        window = list(range(1, total_pages + 1))
    else:
        candidates = {1, total_pages}
        for value in range(current_page - 2, current_page + 3):
            if 1 <= value <= total_pages:
                candidates.add(value)
        ordered = sorted(candidates)
        previous = None
        for number in ordered:
            if previous is not None and number - previous > 1:
                window.append(None)
            window.append(number)
            previous = number
    return sliced, {
        "page": current_page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_prev": current_page > 1,
        "has_next": current_page < total_pages,
        "prev_page": current_page - 1,
        "next_page": current_page + 1,
        "window": window,
    }


def _pagination_links(path: str, params: dict[str, str], pagination: dict | None) -> dict | None:
    if not pagination:
        return None

    def build_href(page_number: int) -> str:
        query = {key: value for key, value in params.items() if value not in {"", "all", None}}
        if page_number > 1:
            query["page"] = str(page_number)
        else:
            query.pop("page", None)
        suffix = f"?{urlencode(query)}" if query else ""
        return f"{path}{suffix}"

    pages = []
    for item in pagination["window"]:
        if item is None:
            pages.append({"number": None, "href": None, "current": False})
            continue
        pages.append({"number": item, "href": build_href(item), "current": item == pagination["page"]})
    return {
        **pagination,
        "pages": pages,
        "prev_href": build_href(pagination["prev_page"]) if pagination["has_prev"] else None,
        "next_href": build_href(pagination["next_page"]) if pagination["has_next"] else None,
    }


def _is_editable_knowledge_kind(kind: str) -> bool:
    return normalize_knowledge_kind(kind) in {"entity", "keyword", "analysis", "query", "lint"}


def _is_regenerable_knowledge_kind(kind: str) -> bool:
    return normalize_knowledge_kind(kind) in {"entity", "keyword", "analysis", "query", "lint"}


def _knowledge_regenerate_label(kind: str) -> str:
    normalized_kind = normalize_knowledge_kind(kind)
    if normalized_kind in {"entity", "keyword", "analysis", "query"}:
        return "LLM 재작성"
    return "다시 생성"


def _history_snapshot_path(request: Request, space_key: str, slug: str, version_number: int) -> Path:
    return _settings(request).wiki_root / "spaces" / space_key / "history" / slug / f"v{version_number:04d}.md"


def _knowledge_prod_url(session, settings, source_refs: str | None) -> str | None:
    source_pages = _knowledge_source_pages(session, settings, source_refs)
    if len(source_pages) != 1:
        return None
    return source_pages[0]["prod_url"] or None


def _normalize_source_text(text: str) -> str:
    plain = BeautifulSoup(str(text or ""), "html.parser").get_text(" ", strip=True)
    return " ".join(plain.split()).strip()


def _source_tokens(text: str) -> Counter[str]:
    return Counter(token.lower() for token in _SOURCE_TOKEN_RE.findall(_normalize_source_text(text)))


def _format_source_date(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d")


def _knowledge_source_pages(session, settings, source_refs: str | None) -> list[dict[str, str]]:
    if not source_refs:
        return []
    raw_page_refs: list[tuple[str, str]] = []
    for match in _RAW_PAGE_REF_RE.finditer(source_refs):
        ref = ((match.group("space_key") or "").strip(), (match.group("slug") or "").strip())
        if not ref[0] or not ref[1] or ref in raw_page_refs:
            continue
        raw_page_refs.append(ref)
    if not raw_page_refs:
        return []
    rows = session.execute(
        select(Page.slug, Page.title, Page.prod_url, Page.updated_at_remote, Space.space_key, WikiDocument.markdown_path, WikiDocument.summary)
        .join(Space, Space.id == Page.space_id)
        .join(WikiDocument, WikiDocument.page_id == Page.id)
    ).all()
    by_ref: dict[tuple[str, str], dict[str, object]] = {}
    for slug, title, prod_url, updated_at_remote, space_key_value, markdown_path, summary in rows:
        body_excerpt = ""
        if markdown_path:
            page_path = settings.wiki_root / str(markdown_path)
            if page_path.exists():
                body_excerpt = read_markdown_body(page_path)[:2500]
        match_text = "\n".join(part for part in [title or "", summary or "", body_excerpt] if part)
        by_ref[(space_key_value, slug)] = {
            "slug": slug,
            "title": title,
            "prod_url": prod_url or "",
            "space_key": space_key_value,
            "updated_at_remote": updated_at_remote,
            "updated_at_label": _format_source_date(updated_at_remote),
            "match_text": match_text,
            "match_tokens": _source_tokens(match_text),
            "title_tokens": _source_tokens(title or ""),
        }
    ordered_sources: list[dict[str, object]] = []
    for number, ref in enumerate((ref for ref in raw_page_refs if ref in by_ref), start=1):
        ordered_sources.append({**by_ref[ref], "number": number, "anchor_id": f"source-evidence-{number}"})
    return ordered_sources


def _best_matching_source_numbers(text: str, source_links: list[dict[str, object]]) -> list[int]:
    if not source_links:
        return []
    normalized_text = _normalize_source_text(text)
    if len(normalized_text) < 10:
        return []
    if len(source_links) == 1:
        return [int(source_links[0]["number"])]
    query_tokens = _source_tokens(normalized_text)
    if not query_tokens:
        return []
    ranked: list[tuple[int, int]] = []
    lowered_text = normalized_text.lower()
    for source in source_links:
        score = 0
        source_token_counts = source.get("match_tokens") or Counter()
        title_tokens = source.get("title_tokens") or Counter()
        score += sum(min(query_tokens[token], source_token_counts.get(token, 0)) for token in query_tokens)
        title = str(source.get("title") or "").lower()
        if title and title in lowered_text:
            score += 6
        score += sum(min(query_tokens[token], title_tokens.get(token, 0)) for token in query_tokens) * 2
        if score > 0:
            ranked.append((score, int(source["number"])))
    ranked.sort(reverse=True)
    return [ranked[0][1]] if ranked else []


def _annotate_knowledge_body_html(body_html: str, source_links: list[dict[str, object]]) -> str:
    if not body_html or not source_links:
        return body_html
    soup = BeautifulSoup(body_html, "html.parser")
    numbered_sources = {int(source["number"]): source for source in source_links}
    for element in soup.select("li, p"):
        if element.find("sub", class_="inline-source-citation"):
            continue
        if element.name == "p" and element.parent and element.parent.name == "li":
            continue
        if any(parent.name in {"blockquote", "table", "thead", "tbody", "tr", "td", "th"} for parent in element.parents):
            continue
        matches = _best_matching_source_numbers(element.get_text(" ", strip=True), source_links)
        if not matches:
            continue
        citation = soup.new_tag("sub", attrs={"class": "inline-source-citation"})
        for index, number in enumerate(matches):
            source = numbered_sources[number]
            link = soup.new_tag(
                "a",
                attrs={
                    "class": "inline-source-link",
                    "href": str(source.get("prod_url") or f"#{source.get('anchor_id')}"),
                    "target": "_blank",
                    "rel": "noreferrer",
                },
            )
            link.string = f"[{number}]"
            citation.append(link)
            if index < len(matches) - 1:
                citation.append(" ")
        updated_at_label = str(numbered_sources[matches[0]].get("updated_at_label") or "").strip()
        if updated_at_label:
            citation.append(" ")
            date_span = soup.new_tag("span", attrs={"class": "inline-source-date"})
            date_span.string = updated_at_label
            citation.append(date_span)
        element.append(" ")
        element.append(citation)
    return str(soup)


def _document_source_space_keys(doc: KnowledgeDocument) -> list[str]:
    return source_space_keys(doc.source_refs)


def _source_page_count_for_doc(doc: KnowledgeDocument) -> int:
    refs = {
        (match.group("space_key") or "", match.group("slug") or "")
        for match in _RAW_PAGE_REF_RE.finditer(doc.source_refs or "")
    }
    return len({ref for ref in refs if ref[0] and ref[1]})


def _space_filter_matches(doc: KnowledgeDocument, selected_space: str | None) -> bool:
    if not selected_space or selected_space == "all":
        return True
    return selected_space in set(_document_source_space_keys(doc))


def _space_names_for_doc(doc: KnowledgeDocument, space_name_by_key: dict[str, str]) -> list[str]:
    names = [space_name_by_key.get(key, key) for key in _document_source_space_keys(doc)]
    return names or ["통합"]


def _edit_notice(page_kind: str) -> str | None:
    if page_kind in {"keyword", "query", "lint", "synthesis"}:
        return "이 문서는 다음 동기화 또는 재생성 작업에서 다시 덮어써질 수 있습니다."
    return None


def _page_result_item(page: Page, space_key: str, space_name: str) -> dict:
    return {
        "title": page.title,
        "slug": page.slug,
        "space_key": space_key,
        "space_name": space_name,
        "href": f"/spaces/{space_key}/pages/{page.slug}",
        "updated_at_label": _format_source_date(page.updated_at_remote),
        "kind_label": "원문",
        "sort_value": page.updated_at_remote.isoformat() if page.updated_at_remote else "",
    }


def _knowledge_result_item(doc: KnowledgeDocument, space_key: str, space_name: str) -> dict:
    return {
        "title": _display_document_title(None, doc.title),
        "slug": doc.slug,
        "space_key": space_key,
        "space_name": space_name,
        "href": knowledge_href(doc.kind, doc.slug),
        "updated_at_label": _format_source_date(doc.updated_at),
        "kind_label": knowledge_label(doc.kind),
        "sort_value": doc.updated_at.isoformat(),
    }


def _is_user_visible_knowledge(doc: KnowledgeDocument) -> bool:
    return normalize_knowledge_kind(doc.kind) in {"keyword", "analysis", "query", "lint"}


def _parse_recent_days(value: str | None) -> int | None:
    if not value or value in {"all", ""}:
        return None
    normalized = value.strip().lower()
    if normalized.endswith("d") and normalized[:-1].isdigit():
        return int(normalized[:-1])
    return None


def _matches_filters(doc: KnowledgeDocument, kind: str | None, recent_days: int | None) -> bool:
    normalized_kind = normalize_knowledge_kind(doc.kind)
    if kind and kind not in {"", "all"} and normalized_kind != normalize_knowledge_kind(kind):
        return False
    if recent_days is not None:
        cutoff = datetime.now() - timedelta(days=recent_days)
        if doc.updated_at < cutoff:
            return False
    return True


def _load_graph_payload(request: Request, selected_space: str | None = None, view: str = "knowledge") -> dict:
    filename = "knowledge-graph.json" if view == "knowledge" else "graph.json"
    graph_path = _settings(request).wiki_root / "global" / filename
    if graph_path.exists():
        payload = json.loads(graph_path.read_text(encoding="utf-8"))
        if not selected_space:
            return payload
        if view == "knowledge":
            allowed_ids = {
                node["id"]
                for node in payload["nodes"]
                if selected_space in set(node.get("source_spaces") or [node.get("space_key")])
            }
            return {
                "nodes": [node for node in payload["nodes"] if node["id"] in allowed_ids],
                "edges": [
                    edge
                    for edge in payload["edges"]
                    if edge["source"] in allowed_ids and edge["target"] in allowed_ids
                ],
            }
        return build_graph_payload(payload["nodes"], [{"source": e["source"], "target": e["target"], "link_type": e["type"]} for e in payload["edges"]], selected_space)

    session = _session_factory(request)()
    try:
        if view == "knowledge":
            knowledge_rows = session.execute(
                select(KnowledgeDocument, Space).join(Space, Space.id == KnowledgeDocument.space_id).where(
                    Space.space_key == GLOBAL_KNOWLEDGE_SPACE_KEY
                )
            ).all()
            page_rows = session.execute(select(Page, WikiDocument, Space).join(WikiDocument, WikiDocument.page_id == Page.id).join(Space, Space.id == Page.space_id)).all()
            knowledge_documents = [
                {
                    "title": doc.title,
                    "slug": doc.slug,
                    "space_key": space.space_key,
                    "kind": doc.kind,
                    "summary": doc.summary or "",
                    "href": knowledge_href(doc.kind, doc.slug),
                    "source_refs": doc.source_refs or "",
                    "source_spaces": _document_source_space_keys(doc),
                }
                for doc, space in knowledge_rows
            ]
            page_documents = [
                {
                    "title": page.title,
                    "slug": page.slug,
                    "space_key": space.space_key,
                    "summary": wiki_document.summary or "",
                    "href": f"/spaces/{space.space_key}/pages/{page.slug}",
                }
                for page, wiki_document, space in page_rows
            ]
            return build_knowledge_graph_payload(knowledge_documents, page_documents, selected_space)
        pages = session.scalars(select(Page)).all()
        nodes = [{"id": page.id, "title": page.title, "space_key": page.space.space_key, "slug": page.slug} for page in pages]
        return build_graph_payload(nodes, [])
    finally:
        session.close()


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str | None = Query(default=None), error: str | None = Query(default=None)) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        current_user = _current_user(session, request)
        if current_user is not None and current_user.is_active:
            return RedirectResponse(url=next or "/", status_code=303)
        return _templates(request).TemplateResponse(
            request,
            "login.html",
            _with_sidebar_metrics(
                {
                    "request": request,
                    "selected_space": "all",
                    "selected_space_name": "로그인",
                    "login_next": next or "/",
                    "login_error": error or "",
                    "meta_description": _meta_description("Confluence Wiki 로그인"),
                },
                session,
            ),
        )
    finally:
        session.close()


@router.post("/auth/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        user = authenticate_user(session, username=username, password=password)
        if user is None:
            destination = f"/login?error={quote('아이디 또는 비밀번호가 올바르지 않습니다.')}"
            if next:
                destination += f"&next={quote(next, safe='/%?=&')}"
            return RedirectResponse(url=destination, status_code=303)
        request.session["user_id"] = user.id
        return RedirectResponse(url=next or "/", status_code=303)
    finally:
        session.close()


@router.post("/auth/logout")
async def logout_submit(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "admin")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        users = session.scalars(select(User).order_by(User.username.asc())).all()
        return _templates(request).TemplateResponse(
            request,
            "admin_users.html",
            _with_sidebar_metrics(
                {
                    "request": request,
                    "selected_space": "all",
                    "selected_space_name": "관리",
                    "users": users,
                    "page_title": "사용자 관리",
                    "meta_description": _meta_description("Confluence Wiki 사용자 관리"),
                },
                session,
            ),
        )
    finally:
        session.close()


@router.post("/admin/users")
async def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
        create_user(session, username=username, password=password, role=role)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/role")
async def admin_update_user_role(
    request: Request,
    user_id: int,
    role: str = Form(...),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in {"viewer", "editor", "admin"}:
            raise HTTPException(status_code=400, detail="Invalid role")
        user.role = normalized_role
        session.commit()
    finally:
        session.close()
    return RedirectResponse(url="/admin/users", status_code=303)


@router.get("/admin/operations", response_class=HTMLResponse)
async def admin_operations(
    request: Request,
    notice: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "admin")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        schedule_service = ScheduleService(_settings(request))
        operation_rows = schedule_service.operations_rows(session)
        summary = {
            "space_count": len(operation_rows),
            "enabled_space_count": sum(1 for row in operation_rows if row["enabled"]),
            "enabled_schedule_count": sum(1 for row in operation_rows if row["schedule"]["enabled"]),
            "due_schedule_count": sum(1 for row in operation_rows if row["schedule"]["due"]),
            "app_timezone": _settings(request).app_timezone,
        }
        return _templates(request).TemplateResponse(
            request,
            "admin_operations.html",
            _with_sidebar_metrics(
                {
                    "request": request,
                    "selected_space": "all",
                    "selected_space_name": "운영 관리",
                    "page_title": "운영 관리",
                    "meta_description": _meta_description("Confluence bootstrap과 증분 동기화 스케줄 관리"),
                    "operation_rows": operation_rows,
                    "operations_summary": summary,
                    "notice": notice or "",
                    "error": error or "",
                },
                session,
            ),
        )
    finally:
        session.close()


@router.post("/admin/spaces")
async def admin_upsert_space(
    request: Request,
    space_key: str = Form(...),
    name: str = Form(default=""),
    root_page_id: str = Form(default=""),
    enabled: str | None = Form(default=None),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
        normalized_key = str(space_key or "").strip()
        if not normalized_key:
            raise ValueError("space_key is required")
        upsert_space(
            session,
            space_key=normalized_key,
            name=str(name or "").strip() or normalized_key,
            root_page_id=str(root_page_id or "").strip() or None,
        ).enabled = bool(enabled)
        session.commit()
    except ValueError as exc:
        session.rollback()
        return _admin_redirect(error=str(exc))
    except OperationalError as exc:
        session.rollback()
        if _is_sqlite_lock_error(exc):
            return _admin_write_locked_redirect("공간 설정")
        raise
    finally:
        session.close()
    return _admin_redirect(notice=f"{space_key} 공간 설정을 저장했습니다.")


@router.post("/admin/spaces/{space_key}/schedule")
async def admin_save_space_schedule(
    request: Request,
    space_key: str,
    enabled: str | None = Form(default=None),
    run_time: str = Form(...),
    timezone: str = Form(default=""),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
        space = session.scalar(select(Space).where(Space.space_key == space_key))
        if space is None:
            raise ValueError("space not found")
        ScheduleService(_settings(request)).upsert_incremental_schedule(
            session,
            space=space,
            enabled=bool(enabled),
            run_time=run_time,
            timezone_name=timezone,
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        return _admin_redirect(error=str(exc))
    except OperationalError as exc:
        session.rollback()
        if _is_sqlite_lock_error(exc):
            return _admin_write_locked_redirect("증분 스케줄")
        raise
    finally:
        session.close()
    return _admin_redirect(notice=f"{space_key} 증분 스케줄을 저장했습니다.")


@router.post("/admin/spaces/{space_key}/bootstrap")
async def admin_run_space_bootstrap(
    request: Request,
    space_key: str,
) -> RedirectResponse:
    root_page_id = ""
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
        space = session.scalar(select(Space).where(Space.space_key == space_key))
        if space is None or not space.root_page_id:
            raise ValueError("bootstrap root page id is required")
        root_page_id = space.root_page_id
    except ValueError as exc:
        return _admin_redirect(error=str(exc))
    finally:
        session.close()
    try:
        await SyncService(settings=_settings(request)).run_bootstrap_async(space_key=space_key, root_page_id=root_page_id)
    except Exception as exc:  # noqa: BLE001
        return _admin_redirect(error=f"{space_key} bootstrap 실패: {exc}")
    return _admin_redirect(notice=f"{space_key} bootstrap을 실행했습니다.")


@router.post("/admin/spaces/{space_key}/sync")
async def admin_run_space_incremental(
    request: Request,
    space_key: str,
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
        space = session.scalar(select(Space).where(Space.space_key == space_key))
        if space is None:
            raise ValueError("space not found")
    except ValueError as exc:
        return _admin_redirect(error=str(exc))
    finally:
        session.close()
    try:
        await SyncService(settings=_settings(request)).run_incremental_async(space_key=space_key)
    except Exception as exc:  # noqa: BLE001
        return _admin_redirect(error=f"{space_key} 증분 동기화 실패: {exc}")
    return _admin_redirect(notice=f"{space_key} 증분 동기화를 실행했습니다.")


@router.post("/admin/schedules/run-due-now")
async def admin_run_due_schedules_now(request: Request) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
        results = await ScheduleService(_settings(request)).run_due_incremental_schedules(session)
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return _admin_redirect(error=f"도래한 스케줄 실행 실패: {exc}")
    finally:
        session.close()
    return _admin_redirect(notice=f"도래한 스케줄 {len(results)}건을 실행했습니다.")


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    space: str | None = None,
    kind: str | None = None,
    recent: str | None = None,
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "viewer")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        knowledge_query = (
            select(KnowledgeDocument, Space)
            .join(Space, Space.id == KnowledgeDocument.space_id)
            .where(Space.space_key == GLOBAL_KNOWLEDGE_SPACE_KEY)
        )
        knowledge_rows = session.execute(knowledge_query).all()
        recent_days = _parse_recent_days(recent)
        pages = [
            {
                **_knowledge_result_item(doc, "global", ", ".join(_space_names_for_doc(doc, space_name_by_key))),
                "source_space_names": _space_names_for_doc(doc, space_name_by_key),
            }
            for doc, doc_space in knowledge_rows
            if _is_user_visible_knowledge(doc) and _matches_filters(doc, kind, recent_days) and _space_filter_matches(doc, space)
        ]
        pages.sort(key=lambda item: (item["sort_value"], item["title"].lower()), reverse=True)
        pages, pagination = _paginate_items(pages, page, per_page=10)
        pagination = _pagination_links(
            request.url.path,
            {"space": space or "", "kind": kind or "", "recent": recent or ""},
            pagination,
        )
        show_home_rail = (space or "all") == "all"
        featured_topics = []
        recent_sources = []
        if show_home_rail:
            featured_docs = [
                doc
                for doc, _doc_space in knowledge_rows
                if _is_user_visible_knowledge(doc) and normalize_knowledge_kind(doc.kind) in {"keyword", "query"}
            ]
            featured_docs.sort(
                key=lambda doc: (
                    _source_page_count_for_doc(doc),
                    1 if normalize_knowledge_kind(doc.kind) == "query" else 0,
                    doc.updated_at.isoformat(),
                    (doc.title or "").lower(),
                ),
                reverse=True,
            )
            featured_topics = [
                {
                    "title": _display_document_title(None, doc.title),
                    "href": knowledge_href(doc.kind, doc.slug),
                    "kind_label": knowledge_label(doc.kind),
                    "source_count": _source_page_count_for_doc(doc),
                    "source_space_names": _space_names_for_doc(doc, space_name_by_key),
                }
                for doc in featured_docs[:4]
            ]
            raw_rows = session.execute(
                select(Page, Space)
                .join(Space, Space.id == Page.space_id)
                .order_by(Page.updated_at_remote.desc(), Page.id.desc())
                .limit(5)
            ).all()
            recent_sources = [
                {
                    "title": page.title,
                    "href": f"/spaces/{space_obj.space_key}/pages/{page.slug}",
                    "space_name": _space_display_name(space_obj),
                    "updated_at_label": _format_source_date(page.updated_at_remote),
                }
                for page, space_obj in raw_rows
            ]
        return _templates(request).TemplateResponse(
            request,
            "index.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space or "all",
                "selected_space_name": space_name_by_key.get(space or "", space or "전체 Space") if space and space != "all" else "전체 Space",
                "pages": pages,
                "selected_kind": normalize_knowledge_kind(kind) if kind and kind != "all" else "all",
                "selected_recent": recent or "all",
                "pagination": pagination,
                "synthesis_href": f"/spaces/{space}/synthesis" if space and space != "all" else None,
                "filter_action": request.url.path,
                "show_home_rail": show_home_rail,
                "featured_topics": featured_topics,
                "recent_sources": recent_sources,
                "meta_description": _meta_description(
                    f"{(space or '전체')} space 문서 홈입니다. 최근 문서 {pagination['total_items'] if pagination else len(pages)}건을 표시합니다."
                ),
            }, session),
        )
    finally:
        session.close()


@router.get("/knowledge-board", response_class=HTMLResponse)
async def knowledge_board(
    request: Request,
    q: str = Query(default=""),
    kind: str | None = Query(default=None),
    recent: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "viewer")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        knowledge_query = (
            select(KnowledgeDocument, Space)
            .join(Space, Space.id == KnowledgeDocument.space_id)
            .where(Space.space_key == GLOBAL_KNOWLEDGE_SPACE_KEY)
        )
        knowledge_rows = session.execute(knowledge_query).all()
        recent_days = _parse_recent_days(recent)
        submitted_query = str(q or "").strip().lower()
        board_rows = []
        for doc, _doc_space in knowledge_rows:
            if not _is_user_visible_knowledge(doc):
                continue
            if not _matches_filters(doc, kind, recent_days):
                continue
            haystack = " ".join([str(doc.title or ""), str(doc.slug or ""), str(doc.summary or "")]).lower()
            if submitted_query and submitted_query not in haystack:
                continue
            board_rows.append(
                {
                    **_knowledge_result_item(doc, "global", ", ".join(_space_names_for_doc(doc, space_name_by_key))),
                    "source_space_names": _space_names_for_doc(doc, space_name_by_key),
                    "source_count": _source_page_count_for_doc(doc),
                    "summary": _display_summary_excerpt(doc.summary, title=doc.title),
                }
            )
        board_rows.sort(key=lambda item: (item["sort_value"], item["title"].lower()), reverse=True)
        board_rows, pagination = _paginate_items(board_rows, page, per_page=12)
        pagination = _pagination_links(
            request.url.path,
            {"q": q, "kind": kind or "", "recent": recent or ""},
            pagination,
        )
        return _templates(request).TemplateResponse(
            request,
            "knowledge_board.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": "all",
                "selected_space_name": "전체 지식",
                "board_rows": board_rows,
                "board_query": q,
                "selected_kind": normalize_knowledge_kind(kind) if kind and kind != "all" else "all",
                "selected_recent": recent or "all",
                "pagination": pagination,
                "meta_description": _meta_description(
                    f"전체 지식 문서 {pagination['total_items'] if pagination else len(board_rows)}건을 게시판 형태로 조회합니다."
                ),
            }, session),
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}", response_class=HTMLResponse)
async def space_index(
    request: Request,
    space_key: str,
    kind: str | None = Query(default=None),
    recent: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    return await index(request, space=space_key, kind=kind, recent=recent, page=page)


@router.get("/knowledge/{kind}/{slug}", response_class=HTMLResponse)
async def knowledge_view(request: Request, kind: str, slug: str, space: str | None = Query(default=None)) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "viewer")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        settings = _settings(request)
        normalized_kind = normalize_knowledge_kind(kind)
        doc = session.scalar(
            select(KnowledgeDocument)
            .join(Space, Space.id == KnowledgeDocument.space_id)
            .where(Space.space_key == GLOBAL_KNOWLEDGE_SPACE_KEY, KnowledgeDocument.kind == normalized_kind, KnowledgeDocument.slug == slug)
        )
        if doc is None:
            doc = session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.kind == normalized_kind,
                    KnowledgeDocument.slug == slug,
                )
            )
        if doc is None:
            raise HTTPException(status_code=404, detail="Knowledge page not found")
        markdown_path = settings.wiki_root / doc.markdown_path
        source_links = _knowledge_source_pages(session, settings, doc.source_refs)
        body_html = _annotate_knowledge_body_html(render_markdown(read_markdown_body(markdown_path)), source_links)
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        display_title = _display_document_title(None, doc.title)
        doc_space_names = _space_names_for_doc(doc, space_name_by_key)
        page_obj = SimpleNamespace(
            title=display_title,
            prod_url=_knowledge_prod_url(session, settings, doc.source_refs),
            updated_at_remote=doc.updated_at,
            current_version=None,
            slug=doc.slug,
        )
        return _templates(request).TemplateResponse(
            request,
            "page.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space or "all",
                "selected_space_name": space_name_by_key.get(space or "", space or "전체 Space") if space and space != "all" else "전체 Space",
                "page": page_obj,
                "page_space_key": "global",
                "page_space_name": "통합 지식",
                "knowledge_source_spaces": doc_space_names,
                "body_html": body_html,
                "page_kind": "knowledge",
                "page_badge": knowledge_label(normalized_kind),
                "history_versions": [],
                "history_href": None,
                "history_notice": None,
                "current_page_href": None,
                "edit_href": (
                    f"/knowledge/{knowledge_segment(normalized_kind)}/{slug}/edit"
                    if role_allows(auth_result.role, "editor") and _is_editable_knowledge_kind(normalized_kind)
                    else None
                ),
                "regenerate_href": (
                    f"/knowledge/{knowledge_segment(normalized_kind)}/{quote(slug)}/regenerate"
                    if role_allows(auth_result.role, "editor") and _is_regenerable_knowledge_kind(normalized_kind)
                    else None
                ),
                "regenerate_label": (
                    _knowledge_regenerate_label(normalized_kind)
                    if role_allows(auth_result.role, "editor") and _is_regenerable_knowledge_kind(normalized_kind)
                    else None
                ),
                "regenerate_selected_space": "" if (space or "all") == "all" else (space or ""),
                "regenerate_kind": normalized_kind,
                "delete_href": (
                    f"/knowledge/{knowledge_segment(normalized_kind)}/{quote(slug)}/delete"
                    if role_allows(auth_result.role, "admin")
                    else None
                ),
                "source_links": source_links,
                "meta_description": _meta_description(doc.summary or display_title),
            }, session),
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}/knowledge/{kind}/{slug}", response_class=HTMLResponse)
async def knowledge_view_legacy(space_key: str, kind: str, slug: str) -> RedirectResponse:
    return RedirectResponse(url=knowledge_href(kind, slug), status_code=307)


@router.get("/spaces/{space_key}/synthesis", response_class=HTMLResponse)
async def synthesis_view(request: Request, space_key: str) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "viewer")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        synthesis_path = _settings(request).wiki_root / "spaces" / space_key / "synthesis.md"
        if not synthesis_path.exists():
            raise HTTPException(status_code=404, detail="Synthesis not found")
        body_html = render_markdown(read_markdown_body(synthesis_path))
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        return _templates(request).TemplateResponse(
            request,
            "page.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space_key,
                "selected_space_name": space_name_by_key.get(space_key, space_key),
                "page": {"title": "Synthesis", "prod_url": None},
                "page_space_key": space_key,
                "page_space_name": space_name_by_key.get(space_key, space_key),
                "body_html": body_html,
                "page_kind": "synthesis",
                "meta_description": _meta_description("Synthesis"),
                "history_versions": [],
                "history_href": None,
                "history_notice": None,
                "current_page_href": None,
                "edit_href": f"/spaces/{space_key}/synthesis/edit" if role_allows(auth_result.role, "editor") else None,
            }, session),
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}/pages/{slug}/history", response_class=HTMLResponse)
async def page_history(request: Request, space_key: str, slug: str) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "viewer")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        row = _load_page_row(session, space_key, slug)
        if row is None:
            raise HTTPException(status_code=404, detail="Page not found")
        page, wiki_document = row
        versions = session.scalars(
            select(PageVersion).where(PageVersion.page_id == page.id).order_by(PageVersion.version_number.desc())
        ).all()
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        return _templates(request).TemplateResponse(
            request,
            "page_history.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space_key,
                "selected_space_name": space_name_by_key.get(space_key, space_key),
                "page": page,
                "page_space_key": space_key,
                "page_space_name": space_name_by_key.get(space_key, space_key),
                "versions": versions,
                "meta_description": _meta_description(wiki_document.summary or page.title),
            }, session),
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}/pages/{slug}/history/{version_number}", response_class=HTMLResponse)
async def page_history_version(request: Request, space_key: str, slug: str, version_number: int) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "viewer")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        row = _load_page_row(session, space_key, slug)
        if row is None:
            raise HTTPException(status_code=404, detail="Page not found")
        page, wiki_document = row
        version = session.scalar(
            select(PageVersion).where(PageVersion.page_id == page.id, PageVersion.version_number == version_number)
        )
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        markdown_path = _settings(request).wiki_root / version.markdown_path if version.markdown_path else None
        history_notice = f"이전 버전 문서 · 버전 {version.version_number}"
        if markdown_path is None or not markdown_path.exists():
            expected_history_path = _history_snapshot_path(request, space_key, slug, version_number)
            if expected_history_path.exists():
                markdown_path = expected_history_path
                version.markdown_path = expected_history_path.relative_to(_settings(request).wiki_root).as_posix()
                session.commit()
            elif version.version_number == page.current_version:
                current_markdown_path = _settings(request).wiki_root / wiki_document.markdown_path
                current_markdown = current_markdown_path.read_text(encoding="utf-8")
                expected_history_path.parent.mkdir(parents=True, exist_ok=True)
                expected_history_path.write_text(current_markdown, encoding="utf-8")
                version.markdown_path = expected_history_path.relative_to(_settings(request).wiki_root).as_posix()
                version.summary = version.summary or wiki_document.summary
                session.commit()
                markdown_path = expected_history_path
            else:
                body_html = (
                    "<p>이 버전의 snapshot 파일이 아직 없습니다. 기존 DB에서 업그레이드된 문서라면 "
                    "해당 페이지를 다시 동기화해야 과거 버전을 파일 기반으로 복구할 수 있습니다.</p>"
                )
                history_notice = f"{history_notice} · snapshot 없음"
        if markdown_path is not None and markdown_path.exists():
            body_html = render_markdown(read_markdown_body(markdown_path))
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        return _templates(request).TemplateResponse(
            request,
            "page.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space_key,
                "selected_space_name": space_name_by_key.get(space_key, space_key),
                "page": page,
                "page_space_key": space_key,
                "page_space_name": space_name_by_key.get(space_key, space_key),
                "body_html": body_html,
                "page_kind": "history_snapshot",
                "history_versions": [],
                "history_href": f"/spaces/{space_key}/pages/{slug}/history",
                "history_notice": history_notice,
                "current_page_href": f"/spaces/{space_key}/pages/{slug}",
                "edit_href": None,
                "meta_description": _meta_description(version.summary or page.title),
            }, session),
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}/pages/{slug}", response_class=HTMLResponse)
async def page_view(request: Request, space_key: str, slug: str) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "viewer")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        row = _load_page_row(session, space_key, slug)
        if row is None:
            raise HTTPException(status_code=404, detail="Page not found")
        page, wiki_document = row
        markdown_path = _settings(request).wiki_root / wiki_document.markdown_path
        body_html = render_markdown(read_markdown_body(markdown_path))
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        versions = session.scalars(
            select(PageVersion).where(PageVersion.page_id == page.id).order_by(PageVersion.version_number.desc())
        ).all()
        return _templates(request).TemplateResponse(
            request,
            "page.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space_key,
                "selected_space_name": space_name_by_key.get(space_key, space_key),
                "page": page,
                "page_space_key": space_key,
                "page_space_name": space_name_by_key.get(space_key, space_key),
                "body_html": body_html,
                "page_kind": "page",
                "history_versions": versions,
                "history_href": f"/spaces/{space_key}/pages/{slug}/history",
                "history_notice": None,
                "current_page_href": None,
                "edit_href": None,
                "meta_description": _meta_description(wiki_document.summary or page.title),
            }, session),
        )
    finally:
        session.close()


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = Query(default=""),
    space: str | None = None,
    kind: str | None = None,
    recent: str | None = None,
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "viewer")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        results = []
        if q:
            knowledge_query = (
                select(KnowledgeDocument, Space)
                .join(Space)
                .where(Space.space_key == GLOBAL_KNOWLEDGE_SPACE_KEY)
            )
            knowledge_query = knowledge_query.where(
                or_(
                    KnowledgeDocument.title.ilike(f"%{q}%"),
                    KnowledgeDocument.slug.ilike(f"%{q}%"),
                    KnowledgeDocument.summary.ilike(f"%{q}%"),
                )
            )
            knowledge_rows = session.execute(knowledge_query.limit(50)).all()
            recent_days = _parse_recent_days(recent)
            results = [
                {
                    **_knowledge_result_item(doc, "global", ", ".join(_space_names_for_doc(doc, space_name_by_key))),
                    "source_space_names": _space_names_for_doc(doc, space_name_by_key),
                }
                for doc, doc_space in knowledge_rows
                if _is_user_visible_knowledge(doc) and _matches_filters(doc, kind, recent_days) and _space_filter_matches(doc, space)
            ]
            results.sort(key=lambda item: (item["sort_value"], item["title"].lower()), reverse=True)
        results, pagination = _paginate_items(results, page, per_page=10)
        pagination = _pagination_links(
            request.url.path,
            {"q": q, "space": space or "", "kind": kind or "", "recent": recent or ""},
            pagination,
        )
        return _templates(request).TemplateResponse(
            request,
            "index.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space or "all",
                "selected_space_name": space_name_by_key.get(space or "", space or "전체 위키") if space and space != "all" else "전체 위키",
                "pages": results,
                "search_query": q,
                "selected_kind": normalize_knowledge_kind(kind) if kind and kind != "all" else "all",
                "selected_recent": recent or "all",
                "pagination": pagination,
                "synthesis_href": f"/spaces/{space}/synthesis" if space and space != "all" else None,
                "filter_action": request.url.path,
                "meta_description": _meta_description(
                    f"검색어 {q} 에 대한 결과 {pagination['total_items'] if pagination else len(results)}건입니다. 범위는 {(space or '전체 위키')} 입니다."
                ),
            }, session),
        )
    finally:
        session.close()


@router.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request, space: str | None = None, view: str = Query(default="knowledge")) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "viewer")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        return _templates(request).TemplateResponse(
            request,
            "graph.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space or "all",
                "selected_space_name": space_name_by_key.get(space or "", space or "전체 그래프") if space and space != "all" else "전체 그래프",
                "selected_view": view if view in {"knowledge", "raw"} else "knowledge",
                "meta_description": _meta_description(
                    f"{(space or '전체')} 범위 문서 연결 그래프를 표시합니다."
                ),
            }, session),
        )
    finally:
        session.close()


@router.get("/api/spaces")
async def api_spaces(request: Request) -> list[dict[str, str]]:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "viewer")
        spaces = _visible_spaces(session)
        return [{"space_key": space.space_key, "name": space.name or space.space_key} for space in spaces]
    finally:
        session.close()


@router.get("/api/search")
async def api_search(request: Request, q: str = Query(default=""), space: str | None = None) -> list[dict[str, str]]:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "viewer")
        if not q:
            return []
        knowledge_query = (
            select(KnowledgeDocument, Space)
            .join(Space)
            .where(Space.space_key == GLOBAL_KNOWLEDGE_SPACE_KEY)
        )
        knowledge_query = knowledge_query.where(
            or_(
                KnowledgeDocument.title.ilike(f"%{q}%"),
                KnowledgeDocument.slug.ilike(f"%{q}%"),
                KnowledgeDocument.summary.ilike(f"%{q}%"),
            )
        )
        knowledge_rows = session.execute(knowledge_query.limit(50)).all()
        results = [
            {
                "title": doc.title,
                "space_key": ",".join(_document_source_space_keys(doc)),
                "slug": doc.slug,
                "href": knowledge_href(doc.kind, doc.slug),
            }
            for doc, doc_space in knowledge_rows
            if _is_user_visible_knowledge(doc) and _space_filter_matches(doc, space)
        ]
        return results
    finally:
        session.close()


@router.get("/knowledge/{kind}/{slug}/edit", response_class=HTMLResponse)
async def knowledge_edit_form(request: Request, kind: str, slug: str, space: str | None = Query(default=None)) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "editor")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        normalized_kind = normalize_knowledge_kind(kind)
        if not _is_editable_knowledge_kind(normalized_kind):
            raise HTTPException(status_code=404, detail="Knowledge page not editable")
        doc = session.scalar(
            select(KnowledgeDocument)
            .join(Space, Space.id == KnowledgeDocument.space_id)
            .where(Space.space_key == GLOBAL_KNOWLEDGE_SPACE_KEY, KnowledgeDocument.kind == normalized_kind, KnowledgeDocument.slug == slug)
        )
        if doc is None:
            doc = session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.kind == normalized_kind,
                    KnowledgeDocument.slug == slug,
                )
            )
        if doc is None:
            raise HTTPException(status_code=404, detail="Knowledge page not found")
        markdown_path = _settings(request).wiki_root / doc.markdown_path
        _frontmatter, body_markdown = read_markdown_document(markdown_path)
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        display_title = _display_document_title(None, doc.title)
        return _templates(request).TemplateResponse(
            request,
            "page_edit.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space or "all",
                "selected_space_name": space_name_by_key.get(space or "", space or "전체 Space") if space and space != "all" else "전체 Space",
                "page_title": display_title,
                "document_title": doc.title,
                "page_kind": normalized_kind,
                "body_markdown": body_markdown,
                "form_action": f"/knowledge/{knowledge_segment(normalized_kind)}/{slug}/edit",
                "cancel_href": knowledge_href(normalized_kind, slug),
                "edit_notice": _edit_notice(normalized_kind),
                "meta_description": _meta_description(f"{display_title} 편집"),
            }, session),
        )
    finally:
        session.close()


@router.post("/knowledge/{kind}/{slug}/edit")
async def knowledge_edit_save(
    request: Request,
    kind: str,
    slug: str,
    title: str = Form(...),
    body: str = Form(...),
    selected_space: str = Form(default=""),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "editor")
        result = KnowledgeService(_settings(request)).update_document_body(
            space_key=selected_space or "GLOBAL",
            kind=kind,
            slug=slug,
            title=title,
            body=body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    return RedirectResponse(url=result["href"], status_code=303)


@router.post("/knowledge/{kind}/{slug}/regenerate")
async def knowledge_regenerate(
    request: Request,
    kind: str,
    slug: str,
    selected_space: str = Form(default=""),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "editor")
        result = KnowledgeService(_settings(request)).regenerate_document(
            kind=kind,
            slug=slug,
            selected_space=selected_space or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    return RedirectResponse(url=result["href"], status_code=303)


@router.post("/knowledge/{kind}/{slug}/delete")
async def knowledge_delete(
    request: Request,
    kind: str,
    slug: str,
    selected_space: str = Form(default=""),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
        result = KnowledgeService(_settings(request)).delete_document(
            kind=kind,
            slug=slug,
            selected_space=selected_space or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    return RedirectResponse(url=result["href"], status_code=303)


@router.get("/spaces/{space_key}/knowledge/{kind}/{slug}/edit")
async def knowledge_edit_form_legacy(space_key: str, kind: str, slug: str) -> RedirectResponse:
    return RedirectResponse(url=f"/knowledge/{knowledge_segment(kind)}/{slug}/edit?space={space_key}", status_code=307)


@router.post("/spaces/{space_key}/knowledge/{kind}/{slug}/edit")
async def knowledge_edit_save_legacy(
    request: Request,
    space_key: str,
    kind: str,
    slug: str,
    title: str = Form(...),
    body: str = Form(...),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "editor")
        result = KnowledgeService(_settings(request)).update_document_body(
            space_key=space_key,
            kind=kind,
            slug=slug,
            title=title,
            body=body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    return RedirectResponse(url=result["href"], status_code=303)


@router.post("/spaces/{space_key}/knowledge/{kind}/{slug}/regenerate")
async def knowledge_regenerate_legacy(
    request: Request,
    space_key: str,
    kind: str,
    slug: str,
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "editor")
        result = KnowledgeService(_settings(request)).regenerate_document(
            kind=kind,
            slug=slug,
            selected_space=space_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    return RedirectResponse(url=result["href"], status_code=303)


@router.post("/spaces/{space_key}/knowledge/{kind}/{slug}/delete")
async def knowledge_delete_legacy(
    request: Request,
    space_key: str,
    kind: str,
    slug: str,
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
        result = KnowledgeService(_settings(request)).delete_document(
            kind=kind,
            slug=slug,
            selected_space=space_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    return RedirectResponse(url=result["href"], status_code=303)


@router.get("/spaces/{space_key}/synthesis/edit", response_class=HTMLResponse)
async def synthesis_edit_form(request: Request, space_key: str) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        auth_result = _ensure_html_role(session, request, "editor")
        if isinstance(auth_result, RedirectResponse):
            return auth_result
        synthesis_path = _settings(request).wiki_root / "spaces" / space_key / "synthesis.md"
        if not synthesis_path.exists():
            raise HTTPException(status_code=404, detail="Synthesis not found")
        _frontmatter, body_markdown = read_markdown_document(synthesis_path)
        spaces = _visible_spaces(session)
        space_name_by_key = _space_name_by_key(spaces)
        return _templates(request).TemplateResponse(
            request,
            "page_edit.html",
            _with_sidebar_metrics({
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space_key,
                "selected_space_name": space_name_by_key.get(space_key, space_key),
                "page_title": "Synthesis",
                "page_kind": "synthesis",
                "body_markdown": body_markdown,
                "form_action": f"/spaces/{space_key}/synthesis/edit",
                "cancel_href": f"/spaces/{space_key}/synthesis",
                "edit_notice": _edit_notice("synthesis"),
                "meta_description": _meta_description("Synthesis 편집"),
            }, session),
        )
    finally:
        session.close()


@router.post("/spaces/{space_key}/synthesis/edit")
async def synthesis_edit_save(
    request: Request,
    space_key: str,
    body: str = Form(...),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "editor")
    finally:
        session.close()
    content = body.strip()
    if not content:
        raise HTTPException(status_code=400, detail="body is required")
    synthesis_path = _settings(request).wiki_root / "spaces" / space_key / "synthesis.md"
    if not synthesis_path.exists():
        raise HTTPException(status_code=404, detail="Synthesis not found")
    frontmatter, _existing_body = read_markdown_document(synthesis_path)
    frontmatter["title"] = "Synthesis"
    frontmatter["aliases"] = ["Synthesis"]
    frontmatter["updated_at"] = datetime.now().isoformat()
    write_markdown_file(synthesis_path, frontmatter, content)
    return RedirectResponse(url=f"/spaces/{space_key}/synthesis", status_code=303)


@router.get("/api/graph")
async def api_graph(request: Request, space: str | None = None, view: str = Query(default="raw")) -> dict:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "viewer")
    finally:
        session.close()
    normalized_view = view if view in {"knowledge", "raw"} else "raw"
    return _load_graph_payload(request, None if space in {None, "", "all"} else space, normalized_view)


@router.get("/api/pages/{space_key}/{slug}")
async def api_page(request: Request, space_key: str, slug: str) -> dict:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "viewer")
        statement = (
            select(Page, WikiDocument)
            .join(Space, Space.id == Page.space_id)
            .join(WikiDocument, WikiDocument.page_id == Page.id)
            .where(Space.space_key == space_key, Page.slug == slug)
        )
        row = session.execute(statement).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Page not found")
        page, wiki_document = row
        return {
            "title": page.title,
            "space_key": space_key,
            "slug": slug,
            "source_url": page.prod_url,
            "markdown_path": wiki_document.markdown_path,
        }
    finally:
        session.close()


@router.post("/api/ask")
async def api_ask(request: Request, payload: dict) -> dict:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "viewer")
    finally:
        session.close()
    question = str(payload.get("question") or "").strip()
    scope = str(payload.get("scope") or "space").strip()
    selected_space = payload.get("selected_space")
    service = WikiQAService(settings=_settings(request))
    try:
        return service.answer(question=question, scope=scope, selected_space=selected_space)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/ask/save")
async def api_ask_save(request: Request, payload: dict) -> dict:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "editor")
    finally:
        session.close()
    service = WikiQAService(settings=_settings(request))
    try:
        return service.save_answer(
            space_key=str(payload.get("space_key") or ""),
            question=str(payload.get("question") or ""),
            scope=str(payload.get("scope") or ""),
            answer=str(payload.get("answer") or ""),
            sources=list(payload.get("sources") or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/knowledge/generate")
async def generate_query_wiki(
    request: Request,
    q: str | None = Form(default=None),
    query: str | None = Form(default=None),
    space: str = Form(default=""),
) -> RedirectResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "editor")
    finally:
        session.close()
    submitted_query = str(q or query or request.query_params.get("q") or request.query_params.get("query") or "").strip()
    if not submitted_query:
        return RedirectResponse(url=request.headers.get("referer") or "/", status_code=303)
    try:
        result = KnowledgeService(_settings(request)).save_query_wiki(
            query=submitted_query,
            selected_space=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=result["href"], status_code=303)


@router.post("/api/wiki-from-query")
async def api_generate_query_wiki(request: Request, payload: dict) -> dict:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "editor")
    finally:
        session.close()
    try:
        return KnowledgeService(_settings(request)).save_query_wiki(
            query=str(payload.get("query") or ""),
            selected_space=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/query-jobs")
async def api_start_query_job(request: Request, payload: dict) -> JSONResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "editor")
    finally:
        session.close()
    query = str(payload.get("query") or payload.get("q") or "").strip()
    selected_space = str(payload.get("selected_space") or payload.get("space") or "").strip() or None
    try:
        snapshot = _query_jobs(request).start_job(query=query, selected_space=selected_space)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(snapshot, status_code=202)


@router.post("/api/query-jobs/knowledge")
async def api_start_regenerate_job(request: Request, payload: dict) -> JSONResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "editor")
    finally:
        session.close()
    kind = str(payload.get("kind") or "").strip()
    slug = str(payload.get("slug") or "").strip()
    title = str(payload.get("title") or "").strip() or None
    selected_space = str(payload.get("selected_space") or payload.get("space") or "").strip() or None
    try:
        snapshot = _query_jobs(request).start_regenerate_job(
            kind=kind,
            slug=slug,
            title=title,
            selected_space=selected_space,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(snapshot, status_code=202)


@router.post("/api/query-jobs/sync")
async def api_start_sync_job(request: Request, payload: dict) -> JSONResponse:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "admin")
    finally:
        session.close()
    mode = str(payload.get("mode") or "").strip().lower()
    space_key = str(payload.get("space_key") or payload.get("space") or "").strip()
    root_page_id = str(payload.get("root_page_id") or payload.get("page_id") or "").strip() or None
    try:
        snapshot = _query_jobs(request).start_sync_job(
            mode=mode,
            space_key=space_key,
            root_page_id=root_page_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(snapshot, status_code=202)


@router.get("/api/query-jobs")
async def api_query_job_queue(request: Request, types: str | None = Query(default=None)) -> dict:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "viewer")
    finally:
        session.close()
    job_types = {item.strip() for item in str(types or "").split(",") if item.strip()} or None
    manager = _query_jobs(request)
    if job_types is None:
        return manager.list_jobs()
    try:
        return manager.list_jobs(job_types=job_types)
    except TypeError:
        return manager.list_jobs()


@router.get("/api/query-jobs/{job_id}")
async def api_query_job_status(request: Request, job_id: str) -> dict:
    session = _session_factory(request)()
    try:
        _ensure_api_role(session, request, "viewer")
    finally:
        session.close()
    snapshot = _query_jobs(request).get_job(job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="query job not found")
    return snapshot


@router.post("/admin/bootstrap")
async def admin_bootstrap(
    request: Request,
    payload: dict,
    x_admin_token: str | None = Header(default=None),
) -> JSONResponse:
    _ensure_admin_token_or_session(request, x_admin_token)
    service = SyncService(settings=_settings(request))
    result = await service.run_bootstrap_async(space_key=payload["space"], root_page_id=payload["page_id"])
    return JSONResponse({"mode": result.mode, "processed_pages": result.processed_pages})


@router.post("/admin/sync")
async def admin_sync(
    request: Request,
    payload: dict,
    x_admin_token: str | None = Header(default=None),
) -> JSONResponse:
    _ensure_admin_token_or_session(request, x_admin_token)
    service = SyncService(settings=_settings(request))
    result = await service.run_incremental_async(space_key=payload["space"])
    return JSONResponse({"mode": result.mode, "processed_pages": result.processed_pages})


@router.post("/admin/schedules/run-due")
async def admin_run_due_schedules(
    request: Request,
    payload: dict | None = None,
    x_admin_token: str | None = Header(default=None),
) -> JSONResponse:
    _ensure_admin_token_or_session(request, x_admin_token)
    now_value: datetime | None = None
    if payload and payload.get("now"):
        try:
            now_value = datetime.fromisoformat(str(payload["now"]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid now timestamp") from exc
    session = _session_factory(request)()
    try:
        results = await ScheduleService(_settings(request)).run_due_incremental_schedules(session, now=now_value)
        session.commit()
        return JSONResponse(
            {
                "executed_count": len(results),
                "results": [
                    {
                        "space_key": item.space_key,
                        "schedule_id": item.schedule_id,
                        "status": item.status,
                        "processed_pages": item.processed_pages,
                        "error": item.error,
                    }
                    for item in results
                ],
            }
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
