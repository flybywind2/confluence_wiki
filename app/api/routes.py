from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select

from app.core.markdown import read_markdown_body, render_markdown
from app.db.models import Page, Space, WikiDocument
from app.graph.builder import build_graph_payload
from app.services.sync_service import SyncService
from app.services.wiki_qa import WikiQAService

router = APIRouter()


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _session_factory(request: Request):
    return request.app.state.session_factory


def _settings(request: Request):
    return request.app.state.settings


def _load_graph_payload(request: Request, selected_space: str | None = None) -> dict:
    graph_path = _settings(request).wiki_root / "global" / "graph.json"
    if graph_path.exists():
        payload = json.loads(graph_path.read_text(encoding="utf-8"))
        if not selected_space:
            return payload
        return build_graph_payload(payload["nodes"], [{"source": e["source"], "target": e["target"], "link_type": e["type"]} for e in payload["edges"]], selected_space)

    session = _session_factory(request)()
    try:
        pages = session.scalars(select(Page)).all()
        nodes = [{"id": page.id, "title": page.title, "space_key": page.space.space_key, "slug": page.slug} for page in pages]
        return build_graph_payload(nodes, [])
    finally:
        session.close()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, space: str | None = None) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        query = select(Page).order_by(Page.updated_at_remote.desc().nullslast(), Page.title)
        if space and space != "all":
            query = query.join(Space).where(Space.space_key == space)
        page_rows = session.scalars(query.limit(20)).all()
        space_lookup = {item.id: item.space_key for item in spaces}
        pages = [
            {
                "title": page.title,
                "slug": page.slug,
                "space_key": space_lookup.get(page.space_id, ""),
                "updated_at_remote": page.updated_at_remote,
            }
            for page in page_rows
        ]
        return _templates(request).TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "spaces": spaces,
                "selected_space": space or "all",
                "pages": pages,
            },
        )
    finally:
        session.close()


@router.get("/spaces/{space_key}", response_class=HTMLResponse)
async def space_index(request: Request, space_key: str) -> HTMLResponse:
    return await index(request, space=space_key)


@router.get("/spaces/{space_key}/pages/{slug:path}", response_class=HTMLResponse)
async def page_view(request: Request, space_key: str, slug: str) -> HTMLResponse:
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
        markdown_path = _settings(request).wiki_root / wiki_document.markdown_path
        body_html = render_markdown(read_markdown_body(markdown_path))
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        return _templates(request).TemplateResponse(
            request,
            "page.html",
            {
                "request": request,
                "spaces": spaces,
                "selected_space": space_key,
                "page": page,
                "page_space_key": space_key,
                "body_html": body_html,
            },
        )
    finally:
        session.close()


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = Query(default=""), space: str | None = None) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        results = []
        if q:
            query = select(Page).join(Space)
            if space and space != "all":
                query = query.where(Space.space_key == space)
            query = query.where(or_(Page.title.ilike(f"%{q}%"), Page.slug.ilike(f"%{q}%")))
            page_rows = session.scalars(query.limit(50)).all()
            space_lookup = {item.id: item.space_key for item in spaces}
            results = [
                {
                    "title": page.title,
                    "slug": page.slug,
                    "space_key": space_lookup.get(page.space_id, ""),
                    "updated_at_remote": page.updated_at_remote,
                }
                for page in page_rows
            ]
        return _templates(request).TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "spaces": spaces,
                "selected_space": space or "all",
                "pages": results,
                "search_query": q,
            },
        )
    finally:
        session.close()


@router.get("/graph", response_class=HTMLResponse)
async def graph_page(request: Request, space: str | None = None) -> HTMLResponse:
    session = _session_factory(request)()
    try:
        spaces = session.scalars(select(Space).order_by(Space.space_key)).all()
        return _templates(request).TemplateResponse(
            request,
            "graph.html",
            {
                "request": request,
                "spaces": spaces,
                "selected_space": space or "all",
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
        query = select(Page).join(Space)
        if space and space != "all":
            query = query.where(Space.space_key == space)
        query = query.where(or_(Page.title.ilike(f"%{q}%"), Page.slug.ilike(f"%{q}%")))
        pages = session.scalars(query.limit(50)).all()
        return [{"title": page.title, "space_key": page.space.space_key, "slug": page.slug} for page in pages]
    finally:
        session.close()


@router.get("/api/graph")
async def api_graph(request: Request, space: str | None = None) -> dict:
    return _load_graph_payload(request, None if space in {None, "", "all"} else space)


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
