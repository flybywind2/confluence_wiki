from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.core.config import Settings, get_settings
from app.db.models import Asset, Page, PageLink, PageVersion, WikiDocument
from app.db.session import create_session_factory
from app.graph.builder import build_graph_payload, write_graph_cache
from app.services.index_builder import append_space_log, build_global_index, build_space_index, build_space_synthesis, read_space_log_excerpt
from app.services.space_registry import upsert_space
from app.services.wiki_writer import write_history_markdown, write_page_markdown

DEMO_ROOT = Path(__file__).resolve().parent.parent / "data" / "demo_seed"
PAGES_ROOT = DEMO_ROOT / "pages"
ASSETS_ROOT = DEMO_ROOT / "assets"

SPACES = {
    "DEMO": {"name": "Demo Showcase", "root_page_id": "9001"},
    "ARCH": {"name": "Architecture Notes", "root_page_id": "9101"},
}

PAGES = [
    {
        "space_key": "DEMO",
        "page_id": "9001",
        "title": "Confluence Wiki Demo 홈",
        "slug": "demo-home-9001",
        "parent_page_id": None,
        "updated_at": "2026-04-06T09:30:00+09:00",
        "body_source": PAGES_ROOT / "DEMO" / "demo-home.md",
        "wiki_targets": ["9002", "9003", "9101"],
        "assets": ["atlas-graph.svg"],
    },
    {
        "space_key": "DEMO",
        "page_id": "9002",
        "title": "운영 대시보드",
        "slug": "ops-dashboard-9002",
        "parent_page_id": "9001",
        "updated_at": "2026-04-05T17:20:00+09:00",
        "body_source": PAGES_ROOT / "DEMO" / "ops-dashboard.md",
        "wiki_targets": ["9003"],
        "assets": [],
    },
    {
        "space_key": "DEMO",
        "page_id": "9003",
        "title": "동기화 런북",
        "slug": "sync-runbook-9003",
        "parent_page_id": "9001",
        "updated_at": "2026-04-04T14:10:00+09:00",
        "body_source": PAGES_ROOT / "DEMO" / "sync-runbook.md",
        "wiki_targets": ["9002"],
        "assets": [],
    },
    {
        "space_key": "ARCH",
        "page_id": "9101",
        "title": "아키텍처 메모",
        "slug": "architecture-notes-9101",
        "parent_page_id": None,
        "updated_at": "2026-04-03T11:05:00+09:00",
        "body_source": PAGES_ROOT / "ARCH" / "architecture-notes.md",
        "wiki_targets": ["9001"],
        "assets": [],
    },
]


def _summary(markdown_body: str) -> str:
    for line in markdown_body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:180]
    return ""


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _copy_asset(source_name: str, settings: Settings, space_key: str) -> Path:
    source = ASSETS_ROOT / source_name
    target = settings.wiki_root / "spaces" / space_key / "assets" / source_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def seed_demo_content(settings: Settings | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    session = create_session_factory(settings.database_url)()
    settings.wiki_root.mkdir(parents=True, exist_ok=True)
    settings.cache_root.mkdir(parents=True, exist_ok=True)

    try:
        spaces_by_key = {}
        for space_key, metadata in SPACES.items():
            spaces_by_key[space_key] = upsert_space(
                session,
                space_key=space_key,
                root_page_id=metadata["root_page_id"],
                name=metadata["name"],
            )

        page_records_by_confluence_id: dict[str, Page] = {}
        documents_by_space: dict[str, list[dict[str, str]]] = {space_key: [] for space_key in SPACES}

        for page_def in PAGES:
            body = page_def["body_source"].read_text(encoding="utf-8").strip()
            space = spaces_by_key[page_def["space_key"]]
            prod_url = f"{settings.conf_prod_base_url.rstrip('/')}/pages/viewpage.action?pageId={page_def['page_id']}"
            updated_at = _parse_datetime(page_def["updated_at"])
            page_record = session.scalar(
                select(Page).where(Page.confluence_page_id == page_def["page_id"], Page.space_id == space.id)
            )
            if page_record is None:
                page_record = Page(
                    confluence_page_id=page_def["page_id"],
                    space_id=space.id,
                    parent_confluence_page_id=page_def["parent_page_id"],
                    title=page_def["title"],
                    slug=page_def["slug"],
                    prod_url=prod_url,
                    current_version=1,
                    updated_at_remote=updated_at,
                )
                session.add(page_record)
                session.flush()
            else:
                page_record.parent_confluence_page_id = page_def["parent_page_id"]
                page_record.title = page_def["title"]
                page_record.slug = page_def["slug"]
                page_record.prod_url = prod_url
                page_record.current_version = 1
                page_record.updated_at_remote = updated_at

            frontmatter = {
                "space_key": page_def["space_key"],
                "page_id": page_def["page_id"],
                "parent_page_id": page_def["parent_page_id"],
                "title": page_def["title"],
                "slug": page_def["slug"],
                "source_url": prod_url,
                "updated_at": page_def["updated_at"],
            }
            markdown_path = write_page_markdown(
                root=settings.wiki_root,
                space_key=page_def["space_key"],
                slug=page_def["slug"],
                frontmatter=frontmatter,
                body=body,
            )
            history_path = write_history_markdown(
                root=settings.wiki_root,
                space_key=page_def["space_key"],
                slug=page_def["slug"],
                version_number=1,
                frontmatter={**frontmatter, "historical": True, "version_number": 1, "latest_slug": page_def["slug"]},
                body=body,
            )

            body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            page_version = session.scalar(
                select(PageVersion).where(PageVersion.page_id == page_record.id, PageVersion.version_number == 1)
            )
            if page_version is None:
                session.add(
                    PageVersion(
                        page_id=page_record.id,
                        version_number=1,
                        body_hash=body_hash,
                        source_excerpt_hash=body_hash,
                        markdown_path=history_path.relative_to(settings.wiki_root).as_posix(),
                        summary=_summary(body),
                        source_updated_at=updated_at,
                    )
                )
            else:
                page_version.body_hash = body_hash
                page_version.source_excerpt_hash = body_hash
                page_version.markdown_path = history_path.relative_to(settings.wiki_root).as_posix()
                page_version.summary = _summary(body)
                page_version.source_updated_at = updated_at

            wiki_document = session.scalar(select(WikiDocument).where(WikiDocument.page_id == page_record.id))
            if wiki_document is None:
                wiki_document = WikiDocument(page_id=page_record.id)
                session.add(wiki_document)
            wiki_document.markdown_path = markdown_path.relative_to(settings.wiki_root).as_posix()
            wiki_document.summary = _summary(body)
            wiki_document.index_line = f"- [[{page_def['space_key']}/{page_def['slug']}]]"

            session.execute(delete(Asset).where(Asset.page_id == page_record.id))
            for asset_name in page_def["assets"]:
                local_path = _copy_asset(asset_name, settings, page_def["space_key"])
                session.add(
                    Asset(
                        page_id=page_record.id,
                        confluence_attachment_id=None,
                        filename=asset_name,
                        mime_type="image/svg+xml",
                        local_path=str(local_path.relative_to(settings.wiki_root)),
                        body_path=f"/wiki-static/spaces/{page_def['space_key']}/assets/{asset_name}",
                        is_image=True,
                        vlm_status="done",
                        vlm_summary="데모용 그래프 미리보기 이미지",
                    )
                )

            page_records_by_confluence_id[page_def["page_id"]] = page_record
            documents_by_space[page_def["space_key"]].append(
                {
                    "title": page_def["title"],
                    "slug": page_def["slug"],
                    "updated_at": page_def["updated_at"],
                }
            )

        seeded_page_ids = [page.id for page in page_records_by_confluence_id.values()]
        if seeded_page_ids:
            session.execute(delete(PageLink).where(PageLink.source_page_id.in_(seeded_page_ids)))

        graph_edges: list[dict[str, int | str]] = []
        for page_def in PAGES:
            source_page = page_records_by_confluence_id[page_def["page_id"]]
            parent_id = page_def["parent_page_id"]
            if parent_id:
                target_page = page_records_by_confluence_id[parent_id]
                session.add(
                    PageLink(
                        source_page_id=source_page.id,
                        target_page_id=target_page.id,
                        target_title=target_page.title,
                        link_type="hierarchy",
                    )
                )
                graph_edges.append({"source": source_page.id, "target": target_page.id, "link_type": "hierarchy"})

            for target_id in page_def["wiki_targets"]:
                target_page = page_records_by_confluence_id[target_id]
                session.add(
                    PageLink(
                        source_page_id=source_page.id,
                        target_page_id=target_page.id,
                        target_title=target_page.title,
                        link_type="wiki",
                    )
                )
                graph_edges.append({"source": source_page.id, "target": target_page.id, "link_type": "wiki"})

        for space_key, docs in documents_by_space.items():
            build_space_index(settings.wiki_root, space_key, docs)
            append_space_log(settings.wiki_root, space_key, "demo-seed", datetime.now(), docs)
            build_space_synthesis(
                settings.wiki_root,
                space_key,
                docs,
                generated_at=datetime.now(),
                recent_log_entries=read_space_log_excerpt(settings.wiki_root, space_key),
            )
        build_global_index(settings.wiki_root, documents_by_space)

        graph_nodes = [
            {
                "id": page.id,
                "title": page.title,
                "space_key": next(key for key, space in spaces_by_key.items() if space.id == page.space_id),
                "slug": page.slug,
            }
            for page in page_records_by_confluence_id.values()
        ]
        write_graph_cache(settings.wiki_root, build_graph_payload(graph_nodes, graph_edges))

        session.commit()
        return {"spaces": len(SPACES), "pages": len(PAGES)}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    result = seed_demo_content()
    print(f"Seeded demo content: {result['spaces']} spaces, {result['pages']} pages")


if __name__ == "__main__":
    main()
