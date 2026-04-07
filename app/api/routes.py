from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select

from app.core.knowledge import knowledge_href, knowledge_label, normalize_knowledge_kind
from app.core.markdown import read_markdown_body, render_markdown
from app.db.models import KnowledgeDocument, Page, PageVersion, Space, WikiDocument
from app.graph.builder import build_graph_payload, build_knowledge_graph_payload
from app.services.sync_service import SyncService
from app.services.wiki_qa import WikiQAService

router = APIRouter()


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _session_factory(request: Request):
    return request.app.state.session_factory


def _settings(request: Request):
    return request.app.state.settings


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


def _history_snapshot_path(request: Request, space_key: str, slug: str, version_number: int) -> Path:
    return _settings(request).wiki_root / "spaces" / space_key / "history" / slug / f"v{version_number:04d}.md"


def _page_result_item(page: Page, space_key: str, space_name: str) -> dict:
    return {
        "title": page.title,
        "slug": page.slug,
        "space_key": space_key,
        "space_name": space_name,
        "href": f"/spaces/{space_key}/pages/{page.slug}",
        "updated_at_label": str(page.updated_at_remote) if page.updated_at_remote else "",
        "kind_label": "원문",
        "sort_value": page.updated_at_remote.isoformat() if page.updated_at_remote else "",
    }


def _knowledge_result_item(doc: KnowledgeDocument, space_key: str, space_name: str) -> dict:
    return {
        "title": doc.title,
        "slug": doc.slug,
        "space_key": space_key,
        "space_name": space_name,
        "href": knowledge_href(space_key, doc.kind, doc.slug),
        "updated_at_label": str(doc.updated_at),
        "kind_label": knowledge_label(doc.kind),
        "sort_value": doc.updated_at.isoformat(),
    }


def _is_user_visible_knowledge(doc: KnowledgeDocument) -> bool:
    return normalize_knowledge_kind(doc.kind) in {"concept", "analysis", "lint"}


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
            allowed_ids = {node["id"] for node in payload["nodes"] if node.get("space_key") == selected_space}
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
            knowledge_rows = session.execute(select(KnowledgeDocument, Space).join(Space, Space.id == KnowledgeDocument.space_id)).all()
            page_rows = session.execute(select(Page, WikiDocument, Space).join(WikiDocument, WikiDocument.page_id == Page.id).join(Space, Space.id == Page.space_id)).all()
            knowledge_documents = [
                {
                    "title": doc.title,
                    "slug": doc.slug,
                    "space_key": space.space_key,
                    "kind": doc.kind,
                    "summary": doc.summary or "",
                    "href": knowledge_href(space.space_key, doc.kind, doc.slug),
                    "source_refs": doc.source_refs or "",
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


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    space: str | None = None,
    kind: str | None = None,
    recent: str | None = None,
) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        space_name_by_key = _space_name_by_key(spaces)
        knowledge_query = select(KnowledgeDocument, Space).join(Space, Space.id == KnowledgeDocument.space_id)
        if space and space != "all":
            knowledge_query = knowledge_query.where(Space.space_key == space)
        knowledge_rows = session.execute(knowledge_query).all()
        recent_days = _parse_recent_days(recent)
        pages = [
            _knowledge_result_item(doc, doc_space.space_key, _space_display_name(doc_space))
            for doc, doc_space in knowledge_rows
            if _is_user_visible_knowledge(doc) and _matches_filters(doc, kind, recent_days)
        ]
        pages.sort(key=lambda item: (item["sort_value"], item["title"].lower()), reverse=True)
        pages = pages[:20]
        return _templates(request).TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space or "all",
                "selected_space_name": space_name_by_key.get(space or "", space or "전체 Space") if space and space != "all" else "전체 Space",
                "pages": pages,
                "selected_kind": normalize_knowledge_kind(kind) if kind and kind != "all" else "all",
                "selected_recent": recent or "all",
                "synthesis_href": f"/spaces/{space}/synthesis" if space and space != "all" else None,
                "filter_action": request.url.path,
                "meta_description": _meta_description(
                    f"{(space or '전체')} space 문서 홈입니다. 최근 문서 {len(pages)}건을 표시합니다."
                ),
            },
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}", response_class=HTMLResponse)
async def space_index(
    request: Request,
    space_key: str,
    kind: str | None = Query(default=None),
    recent: str | None = Query(default=None),
) -> HTMLResponse:
    return await index(request, space=space_key, kind=kind, recent=recent)


@router.get("/spaces/{space_key}/knowledge/{kind}/{slug}", response_class=HTMLResponse)
async def knowledge_view(request: Request, space_key: str, kind: str, slug: str) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        normalized_kind = normalize_knowledge_kind(kind)
        doc = session.scalar(
            select(KnowledgeDocument)
            .join(Space, Space.id == KnowledgeDocument.space_id)
            .where(Space.space_key == space_key, KnowledgeDocument.kind == normalized_kind, KnowledgeDocument.slug == slug)
        )
        if doc is None:
            raise HTTPException(status_code=404, detail="Knowledge page not found")
        markdown_path = _settings(request).wiki_root / doc.markdown_path
        body_html = render_markdown(read_markdown_body(markdown_path))
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        space_name_by_key = _space_name_by_key(spaces)
        page_obj = SimpleNamespace(
            title=doc.title,
            prod_url=None,
            updated_at_remote=doc.updated_at,
            current_version=None,
            slug=doc.slug,
        )
        return _templates(request).TemplateResponse(
            request,
            "page.html",
            {
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space_key,
                "selected_space_name": space_name_by_key.get(space_key, space_key),
                "page": page_obj,
                "page_space_key": space_key,
                "page_space_name": space_name_by_key.get(space_key, space_key),
                "body_html": body_html,
                "page_kind": "knowledge",
                "page_badge": knowledge_label(normalized_kind),
                "history_versions": [],
                "history_href": None,
                "history_notice": None,
                "current_page_href": None,
                "meta_description": _meta_description(doc.summary or doc.title),
            },
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}/synthesis", response_class=HTMLResponse)
async def synthesis_view(request: Request, space_key: str) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        synthesis_path = _settings(request).wiki_root / "spaces" / space_key / "synthesis.md"
        if not synthesis_path.exists():
            raise HTTPException(status_code=404, detail="Synthesis not found")
        body_html = render_markdown(read_markdown_body(synthesis_path))
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        space_name_by_key = _space_name_by_key(spaces)
        return _templates(request).TemplateResponse(
            request,
            "page.html",
            {
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space_key,
                "selected_space_name": space_name_by_key.get(space_key, space_key),
                "page": {"title": f"{space_key} Synthesis", "prod_url": None},
                "page_space_key": space_key,
                "page_space_name": space_name_by_key.get(space_key, space_key),
                "body_html": body_html,
                "page_kind": "synthesis",
                "meta_description": _meta_description(f"{space_key} synthesis"),
                "history_versions": [],
                "history_href": None,
                "history_notice": None,
                "current_page_href": None,
            },
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}/pages/{slug}/history", response_class=HTMLResponse)
async def page_history(request: Request, space_key: str, slug: str) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        row = _load_page_row(session, space_key, slug)
        if row is None:
            raise HTTPException(status_code=404, detail="Page not found")
        page, wiki_document = row
        versions = session.scalars(
            select(PageVersion).where(PageVersion.page_id == page.id).order_by(PageVersion.version_number.desc())
        ).all()
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        space_name_by_key = _space_name_by_key(spaces)
        return _templates(request).TemplateResponse(
            request,
            "page_history.html",
            {
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
            },
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}/pages/{slug}/history/{version_number}", response_class=HTMLResponse)
async def page_history_version(request: Request, space_key: str, slug: str, version_number: int) -> HTMLResponse:
    session = _session_factory(request)()
    try:
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
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        space_name_by_key = _space_name_by_key(spaces)
        return _templates(request).TemplateResponse(
            request,
            "page.html",
            {
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
                "meta_description": _meta_description(version.summary or page.title),
            },
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}/pages/{slug}", response_class=HTMLResponse)
async def page_view(request: Request, space_key: str, slug: str) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        row = _load_page_row(session, space_key, slug)
        if row is None:
            raise HTTPException(status_code=404, detail="Page not found")
        page, wiki_document = row
        markdown_path = _settings(request).wiki_root / wiki_document.markdown_path
        body_html = render_markdown(read_markdown_body(markdown_path))
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        space_name_by_key = _space_name_by_key(spaces)
        versions = session.scalars(
            select(PageVersion).where(PageVersion.page_id == page.id).order_by(PageVersion.version_number.desc())
        ).all()
        return _templates(request).TemplateResponse(
            request,
            "page.html",
            {
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
                "meta_description": _meta_description(wiki_document.summary or page.title),
            },
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
) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        space_name_by_key = _space_name_by_key(spaces)
        results = []
        if q:
            knowledge_query = select(KnowledgeDocument, Space).join(Space)
            if space and space != "all":
                knowledge_query = knowledge_query.where(Space.space_key == space)
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
                _knowledge_result_item(doc, doc_space.space_key, _space_display_name(doc_space))
                for doc, doc_space in knowledge_rows
                if _is_user_visible_knowledge(doc) and _matches_filters(doc, kind, recent_days)
            ]
            results.sort(key=lambda item: (item["sort_value"], item["title"].lower()), reverse=True)
        return _templates(request).TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space or "all",
                "selected_space_name": space_name_by_key.get(space or "", space or "전체 위키") if space and space != "all" else "전체 위키",
                "pages": results,
                "search_query": q,
                "selected_kind": normalize_knowledge_kind(kind) if kind and kind != "all" else "all",
                "selected_recent": recent or "all",
                "synthesis_href": f"/spaces/{space}/synthesis" if space and space != "all" else None,
                "filter_action": request.url.path,
                "meta_description": _meta_description(
                    f"검색어 {q} 에 대한 결과 {len(results)}건입니다. 범위는 {(space or '전체 위키')} 입니다."
                ),
            },
        )
    finally:
        session.close()


@router.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request, space: str | None = None, view: str = Query(default="knowledge")) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        space_name_by_key = _space_name_by_key(spaces)
        return _templates(request).TemplateResponse(
            request,
            "graph.html",
            {
                "request": request,
                "spaces": spaces,
                "space_name_by_key": space_name_by_key,
                "selected_space": space or "all",
                "selected_space_name": space_name_by_key.get(space or "", space or "전체 그래프") if space and space != "all" else "전체 그래프",
                "selected_view": view if view in {"knowledge", "raw"} else "knowledge",
                "meta_description": _meta_description(
                    f"{(space or '전체')} 범위 문서 연결 그래프를 표시합니다."
                ),
            },
        )
    finally:
        session.close()


@router.get("/api/spaces")
async def api_spaces(request: Request) -> list[dict[str, str]]:
    session = _session_factory(request)()
    try:
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        return [{"space_key": space.space_key, "name": space.name or space.space_key} for space in spaces]
    finally:
        session.close()


@router.get("/api/search")
async def api_search(request: Request, q: str = Query(default=""), space: str | None = None) -> list[dict[str, str]]:
    session = _session_factory(request)()
    try:
        if not q:
            return []
        knowledge_query = select(KnowledgeDocument, Space).join(Space)
        if space and space != "all":
            knowledge_query = knowledge_query.where(Space.space_key == space)
        knowledge_query = knowledge_query.where(
            or_(
                KnowledgeDocument.title.ilike(f"%{q}%"),
                KnowledgeDocument.slug.ilike(f"%{q}%"),
                KnowledgeDocument.summary.ilike(f"%{q}%"),
            )
        )
        knowledge_rows = session.execute(knowledge_query.limit(50)).all()
        results = [
            {"title": doc.title, "space_key": doc_space.space_key, "slug": doc.slug, "href": knowledge_href(doc_space.space_key, doc.kind, doc.slug)}
            for doc, doc_space in knowledge_rows
            if _is_user_visible_knowledge(doc)
        ]
        return results
    finally:
        session.close()


@router.get("/api/graph")
async def api_graph(request: Request, space: str | None = None, view: str = Query(default="raw")) -> dict:
    normalized_view = view if view in {"knowledge", "raw"} else "raw"
    return _load_graph_payload(request, None if space in {None, "", "all"} else space, normalized_view)


@router.get("/api/pages/{space_key}/{slug}")
async def api_page(request: Request, space_key: str, slug: str) -> dict:
    session = _session_factory(request)()
    try:
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


@router.post("/admin/bootstrap")
async def admin_bootstrap(
    request: Request,
    payload: dict,
    x_admin_token: str | None = Header(default=None),
) -> JSONResponse:
    if x_admin_token != _settings(request).sync_admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    service = SyncService(settings=_settings(request))
    result = await service.run_bootstrap_async(space_key=payload["space"], root_page_id=payload["page_id"])
    return JSONResponse({"mode": result.mode, "processed_pages": result.processed_pages})


@router.post("/admin/sync")
async def admin_sync(
    request: Request,
    payload: dict,
    x_admin_token: str | None = Header(default=None),
) -> JSONResponse:
    if x_admin_token != _settings(request).sync_admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    service = SyncService(settings=_settings(request))
    result = await service.run_incremental_async(space_key=payload["space"])
    return JSONResponse({"mode": result.mode, "processed_pages": result.processed_pages})
