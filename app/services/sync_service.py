from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from app.clients.confluence import ConfluenceClient
from app.core.config import Settings, get_settings
from app.core.markdown import extract_wiki_links, resolve_page_placeholders
from app.core.slugs import page_slug
from app.db.models import Asset, Page, PageLink, PageVersion, Space, SyncRun, WikiDocument
from app.db.session import create_session_factory
from app.graph.builder import build_graph_payload, write_graph_cache
from app.llm.text_client import TextLLMClient
from app.llm.vision_client import VisionClient
from app.parser.storage import storage_to_markdown
from app.services.assets import build_image_markdown, is_image_filename, save_asset
from app.services.cql import build_incremental_cql
from app.services.index_builder import build_global_index, build_space_index, build_space_log
from app.services.space_registry import upsert_space
from app.services.sync_window import build_day_before_yesterday_window
from app.services.wiki_writer import write_page_markdown


@dataclass
class SyncPlan:
    mode: str
    scope: str
    space_key: str

    @classmethod
    def for_incremental(cls, space_key: str) -> "SyncPlan":
        return cls(mode="incremental", scope="space", space_key=space_key)


@dataclass
class SyncResult:
    mode: str
    space_key: str
    processed_pages: int
    processed_assets: int


class SyncService:
    def __init__(
        self,
        settings: Settings | None = None,
        confluence_client: ConfluenceClient | None = None,
        vision_client: VisionClient | None = None,
        text_client: TextLLMClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.confluence_client = confluence_client or ConfluenceClient(self.settings)
        self.vision_client = vision_client
        self.text_client = text_client
        self.session_factory = create_session_factory(self.settings.database_url)
        self.settings.wiki_root.mkdir(parents=True, exist_ok=True)
        self.settings.cache_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def run_bootstrap(self, space_key: str, root_page_id: str) -> SyncResult:
        return asyncio.run(self.run_bootstrap_async(space_key, root_page_id))

    def run_incremental(self, space_key: str, now: datetime | None = None) -> SyncResult:
        return asyncio.run(self.run_incremental_async(space_key, now))

    async def run_bootstrap_async(self, space_key: str, root_page_id: str) -> SyncResult:
        return await self._run_bootstrap(space_key, root_page_id)

    async def run_incremental_async(self, space_key: str, now: datetime | None = None) -> SyncResult:
        return await self._run_incremental(space_key, now)

    async def _run_bootstrap(self, space_key: str, root_page_id: str) -> SyncResult:
        descendants = await self.confluence_client.fetch_descendant_pages(root_page_id)
        page_ids = [root_page_id, *[item["id"] for item in descendants if item["id"] != root_page_id]]
        return await self._sync_pages(space_key=space_key, page_ids=page_ids, mode="bootstrap", root_page_id=root_page_id)

    async def _run_incremental(self, space_key: str, now: datetime | None) -> SyncResult:
        timezone = ZoneInfo(self.settings.app_timezone)
        effective_now = now or datetime.now(tz=timezone)
        start, end = build_day_before_yesterday_window(effective_now)
        cql = build_incremental_cql(space_key, start, end)
        search_results = await self.confluence_client.search_cql(space_key, cql)
        page_ids = [item["id"] for item in search_results]
        return await self._sync_pages(space_key=space_key, page_ids=page_ids, mode="incremental", root_page_id=None)

    async def _sync_pages(
        self,
        space_key: str,
        page_ids: list[str],
        mode: str,
        root_page_id: str | None,
    ) -> SyncResult:
        session = self.session_factory()
        processed_assets = 0
        try:
            unique_page_ids = list(dict.fromkeys(page_ids))
            space = upsert_space(session, space_key=space_key, root_page_id=root_page_id)
            sync_run = SyncRun(mode=mode, space_id=space.id, status="running")
            session.add(sync_run)
            session.flush()

            existing_pages = session.scalars(select(Page).where(Page.space_id == space.id)).all()
            existing_pages_by_confluence_id = {page.confluence_page_id: page for page in existing_pages}
            slug_lookup: dict[str, tuple[str, str]] = {
                page.confluence_page_id: (space_key, page.slug) for page in existing_pages
            }

            raw_pages: list[dict] = []
            for page_id in unique_page_ids:
                raw_page = await self.confluence_client.fetch_page(page_id)
                raw_page["space_key"] = raw_page.get("space_key") or space_key
                existing_page = existing_pages_by_confluence_id.get(raw_page["id"])
                raw_page["slug"] = existing_page.slug if existing_page is not None else page_slug(raw_page["title"], raw_page["id"])
                raw_pages.append(raw_page)
                slug_lookup[raw_page["id"]] = (space_key, raw_page["slug"])

            page_records: dict[str, Page] = {}
            documents_for_index: list[dict[str, str]] = []
            for raw_page in raw_pages:
                markdown_body = storage_to_markdown(raw_page.get("body", ""))
                markdown_body = resolve_page_placeholders(markdown_body, slug_lookup)
                summary = self._summarize(markdown_body)

                page_record = session.scalar(
                    select(Page).where(Page.confluence_page_id == raw_page["id"], Page.space_id == space.id)
                )
                if page_record is None:
                    page_record = Page(
                        confluence_page_id=raw_page["id"],
                        space_id=space.id,
                        parent_confluence_page_id=raw_page.get("parent_id"),
                        title=raw_page["title"],
                        slug=raw_page["slug"],
                        prod_url=self._build_prod_url(raw_page),
                        current_version=raw_page.get("version", 1),
                    )
                    session.add(page_record)
                    session.flush()
                else:
                    page_record.parent_confluence_page_id = raw_page.get("parent_id")
                    page_record.title = raw_page["title"]
                    page_record.slug = raw_page["slug"]
                    page_record.prod_url = self._build_prod_url(raw_page)
                    page_record.current_version = raw_page.get("version", 1)

                page_record.updated_at_remote = self._parse_datetime(raw_page.get("updated_at"))
                page_record.last_synced_at = self._utcnow()
                page_records[raw_page["id"]] = page_record

                session.execute(delete(Asset).where(Asset.page_id == page_record.id))

                image_blocks: list[str] = []
                for attachment in await self.confluence_client.list_attachments(raw_page["id"]):
                    if not attachment.get("download"):
                        continue
                    is_image = is_image_filename(attachment["filename"])
                    content = await self.confluence_client.download_bytes(attachment["download"])
                    asset_root = self.settings.wiki_root / "spaces" / space_key / "assets"
                    local_path = save_asset(asset_root, attachment["filename"], content)
                    caption = self.vision_client.describe_image(local_path) if is_image and self.vision_client else None
                    if is_image:
                        relative_path = local_path.relative_to(self.settings.wiki_root / "spaces" / space_key).as_posix()
                        image_blocks.append(build_image_markdown(relative_path, attachment["filename"], caption))
                    processed_assets += 1
                    session.add(
                        Asset(
                            page_id=page_record.id,
                            confluence_attachment_id=attachment.get("id"),
                            filename=attachment["filename"],
                            mime_type=attachment.get("mime_type"),
                            local_path=str(local_path.relative_to(self.settings.wiki_root)),
                            body_path=attachment.get("download"),
                            is_image=is_image,
                            vlm_status="done" if caption else "skipped",
                            vlm_summary=caption,
                            downloaded_at=self._utcnow(),
                        )
                    )

                if image_blocks:
                    markdown_body = markdown_body + "\n\n## 이미지\n\n" + "\n\n".join(image_blocks)

                frontmatter = {
                    "space_key": space_key,
                    "page_id": raw_page["id"],
                    "parent_page_id": raw_page.get("parent_id"),
                    "title": raw_page["title"],
                    "slug": raw_page["slug"],
                    "source_url": self._build_prod_url(raw_page),
                    "updated_at": raw_page.get("updated_at"),
                }
                markdown_path = write_page_markdown(
                    root=self.settings.wiki_root,
                    space_key=space_key,
                    slug=raw_page["slug"],
                    frontmatter=frontmatter,
                    body=markdown_body,
                )

                body_hash = hashlib.sha256(markdown_body.encode("utf-8")).hexdigest()
                page_version = session.scalar(
                    select(PageVersion).where(
                        PageVersion.page_id == page_record.id,
                        PageVersion.version_number == raw_page.get("version", 1),
                    )
                )
                if page_version is None:
                    session.add(
                        PageVersion(
                            page_id=page_record.id,
                            version_number=raw_page.get("version", 1),
                            body_hash=body_hash,
                            source_excerpt_hash=body_hash,
                        )
                    )
                else:
                    page_version.body_hash = body_hash
                    page_version.source_excerpt_hash = body_hash
                    page_version.synced_at = self._utcnow()

                wiki_document = session.scalar(select(WikiDocument).where(WikiDocument.page_id == page_record.id))
                if wiki_document is None:
                    wiki_document = WikiDocument(
                        page_id=page_record.id,
                        markdown_path=str(markdown_path.relative_to(self.settings.wiki_root)),
                        summary=summary,
                        index_line=f"- [[{space_key}/{raw_page['slug']}]]",
                    )
                    session.add(wiki_document)
                else:
                    wiki_document.markdown_path = str(markdown_path.relative_to(self.settings.wiki_root))
                    wiki_document.summary = summary
                    wiki_document.index_line = f"- [[{space_key}/{raw_page['slug']}]]"

                documents_for_index.append(
                    {
                        "title": raw_page["title"],
                        "slug": raw_page["slug"],
                        "updated_at": raw_page.get("updated_at") or "",
                    }
                )

            session.execute(delete(PageLink).where(PageLink.source_page_id.in_([page.id for page in page_records.values()])))
            session.flush()

            edges: list[dict] = []
            known_pages_by_confluence_id = {
                page.confluence_page_id: page for page in session.scalars(select(Page).where(Page.space_id == space.id)).all()
            }
            known_pages_by_slug = {page.slug: page for page in known_pages_by_confluence_id.values()}
            for raw_page in raw_pages:
                source_page = page_records[raw_page["id"]]
                parent_id = raw_page.get("parent_id")
                parent_page = known_pages_by_confluence_id.get(parent_id) if parent_id else None
                if parent_page is not None:
                    session.add(
                        PageLink(
                            source_page_id=source_page.id,
                            target_page_id=parent_page.id,
                            target_title=parent_page.title,
                            link_type="hierarchy",
                        )
                    )
                    edges.append({"source": source_page.id, "target": parent_page.id, "link_type": "hierarchy"})

                markdown_path = self.settings.wiki_root / "spaces" / space_key / "pages" / f"{raw_page['slug']}.md"
                markdown_text = markdown_path.read_text(encoding="utf-8")
                for wiki_link in extract_wiki_links(markdown_text):
                    target_space, _, target_slug = wiki_link.partition("/")
                    if target_space != space_key or not target_slug:
                        continue
                    target_page = known_pages_by_slug.get(target_slug)
                    if target_page is None:
                        continue
                    session.add(
                        PageLink(
                            source_page_id=source_page.id,
                            target_page_id=target_page.id,
                            target_title=target_page.title,
                            link_type="wiki",
                        )
                    )
                    edges.append({"source": source_page.id, "target": target_page.id, "link_type": "wiki"})

            self._rebuild_materialized_views(session)

            sync_run.status = "success"
            sync_run.processed_pages = len(raw_pages)
            sync_run.processed_assets = processed_assets
            sync_run.finished_at = self._utcnow()
            session.commit()

            return SyncResult(mode=mode, space_key=space_key, processed_pages=len(raw_pages), processed_assets=processed_assets)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _summarize(self, markdown_body: str) -> str:
        if self.text_client:
            return self.text_client.summarize(markdown_body)
        first_line = next((line.strip() for line in markdown_body.splitlines() if line.strip()), "")
        return first_line[:180]

    def _build_prod_url(self, raw_page: dict) -> str:
        if hasattr(self.confluence_client, "build_page_url"):
            return self.confluence_client.build_page_url(raw_page["id"])
        webui = raw_page.get("webui") or f"/pages/viewpage.action?pageId={raw_page['id']}"
        return f"{self.settings.conf_prod_base_url.rstrip('/')}/{webui.lstrip('/')}"

    def _rebuild_materialized_views(self, session) -> None:
        grouped_documents: dict[str, list[dict[str, str]]] = {}
        all_pages = session.scalars(select(Page)).all()
        space_lookup = {space.id: space.space_key for space in session.scalars(select(Space)).all()}
        for space_id, space_key in sorted(space_lookup.items(), key=lambda item: item[1]):
            rows = session.execute(
                select(Page, WikiDocument)
                .join(WikiDocument, WikiDocument.page_id == Page.id)
                .where(Page.space_id == space_id)
            ).all()
            documents = [
                {
                    "title": page.title,
                    "slug": page.slug,
                    "updated_at": page.updated_at_remote.isoformat() if page.updated_at_remote else "",
                }
                for page, _wiki_document in rows
            ]
            grouped_documents[space_key] = documents
            build_space_index(self.settings.wiki_root, space_key, documents)
            build_space_log(self.settings.wiki_root, space_key, documents)

        build_global_index(self.settings.wiki_root, grouped_documents)

        page_id_lookup = {page.id: page for page in all_pages}
        nodes = [
            {
                "id": page.id,
                "title": page.title,
                "space_key": space_lookup.get(page.space_id, ""),
                "slug": page.slug,
            }
            for page in all_pages
        ]
        page_links = session.scalars(select(PageLink)).all()
        edges = [
            {"source": link.source_page_id, "target": link.target_page_id, "link_type": link.link_type}
            for link in page_links
            if link.target_page_id in page_id_lookup and link.source_page_id in page_id_lookup
        ]
        write_graph_cache(self.settings.wiki_root, build_graph_payload(nodes=nodes, edges=edges))

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
