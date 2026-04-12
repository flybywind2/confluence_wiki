from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

import yaml
from sqlalchemy import delete, select

from app.clients.confluence import ConfluenceClient, is_missing_attachment_redirect
from app.core.config import Settings, get_settings
from app.core.knowledge import GLOBAL_KNOWLEDGE_SPACE_KEY, knowledge_href, source_space_keys
from app.core.obsidian import asset_target, page_link
from app.core.markdown import extract_wiki_links, resolve_page_placeholders
from app.core.slugs import page_slug
from app.db.models import Asset, KnowledgeDocument, Page, PageLink, PageVersion, Space, SyncRun, WikiDocument
from app.db.session import create_session_factory, run_sqlite_maintenance_for_url
from app.graph.builder import build_graph_payload, build_knowledge_graph_payload, write_graph_cache, write_named_graph_cache
from app.llm.text_client import TextLLMClient
from app.llm.vision_client import VisionClient
from app.parser.storage import storage_to_markdown
from app.services.assets import BODY_IMAGE_PLACEHOLDER_RE, build_image_markdown, build_wiki_asset_url, is_image_filename, save_asset
from app.services.cql import build_incremental_cql
from app.services.index_builder import append_space_log, build_global_index, build_space_index, build_space_synthesis, read_space_log_excerpt
from app.services.knowledge_service import KnowledgeService
from app.services.lint_service import LintService
from app.services.space_registry import ensure_global_knowledge_space, upsert_space
from app.services.sync_window import build_day_before_yesterday_window
from app.services.sync_lease import SyncLeaseHandle, SyncLeaseService
from app.services.wiki_writer import write_history_markdown, write_page_markdown

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


class SyncCancelledError(Exception):
    pass


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
    skipped_attachments: list[str] = field(default_factory=list)


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
        self.sync_lease_service = SyncLeaseService(self.settings)
        self._active_sync_lease: SyncLeaseHandle | None = None
        self.settings.wiki_root.mkdir(parents=True, exist_ok=True)
        self.settings.cache_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def run_bootstrap(self, space_key: str, root_page_id: str) -> SyncResult:
        return asyncio.run(self.run_bootstrap_async(space_key, root_page_id))

    def run_incremental(self, space_key: str, now: datetime | None = None) -> SyncResult:
        return asyncio.run(self.run_incremental_async(space_key, now))

    async def run_bootstrap_async(
        self,
        space_key: str,
        root_page_id: str,
        progress_callback: ProgressCallback | None = None,
        cancel_requested: CancelCallback | None = None,
    ) -> SyncResult:
        lease_handle = self._acquire_sync_lease(mode="bootstrap", space_key=space_key)
        self._active_sync_lease = lease_handle
        try:
            progress_callback = self._lease_progress_callback(progress_callback)
            if progress_callback is None:
                result = await self._run_bootstrap(
                    space_key,
                    root_page_id,
                    cancel_requested=cancel_requested,
                )
            else:
                result = await self._run_bootstrap(
                    space_key,
                    root_page_id,
                    progress_callback,
                    cancel_requested,
                )
            self._run_post_sync_sqlite_maintenance()
            return result
        finally:
            self._active_sync_lease = None
            self._release_sync_lease(lease_handle)

    async def run_incremental_async(
        self,
        space_key: str,
        now: datetime | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_requested: CancelCallback | None = None,
    ) -> SyncResult:
        lease_handle = self._acquire_sync_lease(mode="incremental", space_key=space_key)
        self._active_sync_lease = lease_handle
        try:
            progress_callback = self._lease_progress_callback(progress_callback)
            if progress_callback is None:
                result = await self._run_incremental(
                    space_key,
                    now,
                    cancel_requested=cancel_requested,
                )
            else:
                result = await self._run_incremental(
                    space_key,
                    now,
                    progress_callback,
                    cancel_requested,
                )
            self._run_post_sync_sqlite_maintenance()
            return result
        finally:
            self._active_sync_lease = None
            self._release_sync_lease(lease_handle)

    async def _run_bootstrap(
        self,
        space_key: str,
        root_page_id: str,
        progress_callback: ProgressCallback | None = None,
        cancel_requested: CancelCallback | None = None,
    ) -> SyncResult:
        self._raise_if_cancelled(cancel_requested)
        self._emit_progress(progress_callback, 5, "하위 페이지 트리를 확인하는 중입니다.")
        if hasattr(self.confluence_client, "fetch_page_tree"):
            descendants = await self.confluence_client.fetch_page_tree(root_page_id)
        else:
            descendants = await self.confluence_client.fetch_descendant_pages(root_page_id)
        self._raise_if_cancelled(cancel_requested)
        page_ids = [root_page_id, *[item["id"] for item in descendants if item["id"] != root_page_id]]
        logger.info("bootstrap start space=%s root_page_id=%s pages=%s", space_key, root_page_id, len(page_ids))
        self._emit_progress(progress_callback, 15, f"Bootstrap 대상 {len(page_ids)}건을 확인했습니다.")
        result = await self._sync_pages(
            space_key=space_key,
            page_ids=page_ids,
            mode="bootstrap",
            root_page_id=root_page_id,
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )
        session = self.session_factory()
        try:
            space = session.scalar(select(Space).where(Space.space_key == space_key))
            if space is not None:
                space.root_page_id = root_page_id
                space.last_bootstrap_at = self._utcnow()
                session.commit()
        finally:
            session.close()
        return result

    async def _run_incremental(
        self,
        space_key: str,
        now: datetime | None,
        progress_callback: ProgressCallback | None = None,
        cancel_requested: CancelCallback | None = None,
    ) -> SyncResult:
        self._raise_if_cancelled(cancel_requested)
        self._emit_progress(progress_callback, 5, "증분 변경 범위를 계산하는 중입니다.")
        timezone = ZoneInfo(self.settings.app_timezone)
        effective_now = now or datetime.now(tz=timezone)
        start, end = build_day_before_yesterday_window(effective_now)
        cql = build_incremental_cql(space_key, start, end)
        search_results = await self.confluence_client.search_cql(space_key, cql)
        self._raise_if_cancelled(cancel_requested)
        page_ids = [item["id"] for item in search_results]
        logger.info(
            "incremental start space=%s window=%s ~ %s pages=%s",
            space_key,
            start.isoformat(),
            end.isoformat(),
            len(page_ids),
        )
        self._emit_progress(progress_callback, 15, f"증분 대상 {len(page_ids)}건을 확인했습니다.")
        result = await self._sync_pages(
            space_key=space_key,
            page_ids=page_ids,
            mode="incremental",
            root_page_id=None,
            window_label=f"{start.isoformat()} ~ {end.isoformat()}",
            progress_callback=progress_callback,
            cancel_requested=cancel_requested,
        )
        session = self.session_factory()
        try:
            space = session.scalar(select(Space).where(Space.space_key == space_key))
            if space is not None:
                space.last_incremental_at = self._utcnow()
                session.commit()
        finally:
            session.close()
        return result

    async def _sync_pages(
        self,
        space_key: str,
        page_ids: list[str],
        mode: str,
        root_page_id: str | None,
        window_label: str | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_requested: CancelCallback | None = None,
    ) -> SyncResult:
        self._raise_if_cancelled(cancel_requested)
        unique_page_ids = list(dict.fromkeys(page_ids))
        slug_lookup = {
            page_id: (space_key, slug)
            for page_id, slug in self._load_existing_page_slugs_from_markdown(space_key).items()
        }
        raw_pages: list[dict] = []
        for page_id in unique_page_ids:
            self._raise_if_cancelled(cancel_requested)
            raw_page = await self.confluence_client.fetch_page(page_id)
            raw_page["space_key"] = raw_page.get("space_key") or space_key
            existing_slug = slug_lookup.get(raw_page["id"], ("", ""))[1]
            raw_page["slug"] = existing_slug or page_slug(raw_page["title"], raw_page["id"])
            raw_pages.append(raw_page)
            slug_lookup[raw_page["id"]] = (space_key, raw_page["slug"])

        session = self.session_factory()
        processed_assets = 0
        skipped_attachments: list[str] = []
        sync_run_id: int | None = None
        committed_page_count = 0
        try:
            logger.info("sync start mode=%s space=%s pages=%s", mode, space_key, len(unique_page_ids))
            space = upsert_space(session, space_key=space_key, root_page_id=root_page_id)
            sync_run = SyncRun(mode=mode, space_id=space.id, status="running")
            session.add(sync_run)
            session.flush()
            sync_run_id = sync_run.id
            session.commit()

            page_records: dict[str, Page] = {}
            documents_for_index: list[dict[str, str]] = []
            for index, raw_page in enumerate(raw_pages, start=1):
                self._raise_if_cancelled(cancel_requested)
                if raw_pages:
                    progress = 20 + int(((index - 1) / max(len(raw_pages), 1)) * 65)
                    self._emit_progress(
                        progress_callback,
                        progress,
                        f"{index}/{len(raw_pages)} 페이지를 처리하는 중입니다: {raw_page['title']}",
                    )
                logger.info(
                    "processing page %s/%s id=%s title=%s",
                    index,
                    len(raw_pages),
                    raw_page["id"],
                    raw_page["title"],
                )
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

                session.execute(delete(Asset).where(Asset.page_id == page_record.id))

                body_image_refs = self._extract_body_image_references(markdown_body)
                downloaded_assets: dict[str, dict[str, str | None]] = {}
                attachment_links: list[str] = []
                self._raise_if_cancelled(cancel_requested)
                for attachment in await self.confluence_client.list_attachments(raw_page["id"]):
                    self._raise_if_cancelled(cancel_requested)
                    if not attachment.get("download"):
                        continue
                    attachment_filename = self._normalize_attachment_name(attachment["filename"])
                    mime_type = attachment.get("mime_type")
                    is_image_attachment = is_image_filename(attachment_filename) or bool((mime_type or "").startswith("image/"))
                    if not is_image_attachment:
                        attachment_links.append(
                            self._build_attachment_link_markdown(attachment_filename, attachment["download"])
                        )
                        continue
                    if attachment_filename not in body_image_refs:
                        continue
                    logger.debug(
                        "downloading attachment page_id=%s filename=%s",
                        raw_page["id"],
                        attachment_filename,
                    )
                    try:
                        asset_info = await self._materialize_asset(
                            session=session,
                            page_record=page_record,
                            space_key=space_key,
                            filename=attachment_filename,
                            download_path=attachment["download"],
                            confluence_attachment_id=attachment.get("id"),
                            mime_type=mime_type,
                            cancel_requested=cancel_requested,
                        )
                    except Exception as exc:
                        if not is_missing_attachment_redirect(exc):
                            raise
                        skipped_attachments.append(f"{space_key}/{raw_page['id']} {attachment_filename}")
                        continue
                    if asset_info is not None:
                        downloaded_assets[attachment_filename] = asset_info
                        processed_assets += 1
                        logger.debug(
                            "downloaded asset page_id=%s filename=%s image=%s",
                            raw_page["id"],
                            attachment_filename,
                            asset_info.get("is_image"),
                        )

                markdown_body, inline_image_keys, new_body_assets = await self._replace_body_image_placeholders(
                    session=session,
                    page_record=page_record,
                    space_key=space_key,
                    markdown_body=markdown_body,
                    downloaded_assets=downloaded_assets,
                    skipped_attachments=skipped_attachments,
                    cancel_requested=cancel_requested,
                )
                downloaded_assets.update(new_body_assets)
                processed_assets += len(new_body_assets)
                if new_body_assets:
                    logger.debug(
                        "replaced body images page_id=%s count=%s",
                        raw_page["id"],
                        len(new_body_assets),
                    )

                trailing_images = []
                for filename, asset_info in downloaded_assets.items():
                    if filename in inline_image_keys or asset_info.get("is_image") is not True:
                        continue
                    trailing_images.append(
                        build_image_markdown(
                            str(asset_info.get("vault_path") or asset_info["public_url"]),
                            str(asset_info.get("alt_text") or filename),
                            str(asset_info.get("caption") or "") or None,
                        )
                    )

                if trailing_images:
                    markdown_body = markdown_body + "\n\n## 이미지\n\n" + "\n\n".join(trailing_images)
                if attachment_links:
                    markdown_body = markdown_body + "\n\n## 첨부 파일\n\n" + "\n".join(attachment_links)

                frontmatter = {
                    "space_key": space_key,
                    "page_id": raw_page["id"],
                    "parent_page_id": raw_page.get("parent_id"),
                    "title": raw_page["title"],
                    "slug": raw_page["slug"],
                    "aliases": [raw_page["title"]],
                    "tags": [f"space/{space_key}", "kind/page", "source/confluence"],
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
                history_frontmatter = {
                    **frontmatter,
                    "historical": True,
                    "version_number": raw_page.get("version", 1),
                    "latest_slug": raw_page["slug"],
                }
                history_path = write_history_markdown(
                    root=self.settings.wiki_root,
                    space_key=space_key,
                    slug=raw_page["slug"],
                    version_number=raw_page.get("version", 1),
                    frontmatter=history_frontmatter,
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
                            markdown_path=history_path.relative_to(self.settings.wiki_root).as_posix(),
                            summary=summary,
                            source_updated_at=page_record.updated_at_remote,
                        )
                    )
                else:
                    page_version.body_hash = body_hash
                    page_version.source_excerpt_hash = body_hash
                    page_version.markdown_path = history_path.relative_to(self.settings.wiki_root).as_posix()
                    page_version.summary = summary
                    page_version.source_updated_at = page_record.updated_at_remote
                    page_version.synced_at = self._utcnow()

                wiki_document = session.scalar(select(WikiDocument).where(WikiDocument.page_id == page_record.id))
                if wiki_document is None:
                    wiki_document = WikiDocument(
                        page_id=page_record.id,
                        markdown_path=markdown_path.relative_to(self.settings.wiki_root).as_posix(),
                        summary=summary,
                        index_line=f"- {page_link(space_key, raw_page['slug'], raw_page['title'])}",
                    )
                    session.add(wiki_document)
                else:
                    wiki_document.markdown_path = markdown_path.relative_to(self.settings.wiki_root).as_posix()
                    wiki_document.summary = summary
                    wiki_document.index_line = f"- {page_link(space_key, raw_page['slug'], raw_page['title'])}"

                page_document = {
                    "title": raw_page["title"],
                    "slug": raw_page["slug"],
                    "updated_at": raw_page.get("updated_at") or "",
                    "summary": summary,
                    "href": f"/spaces/{space_key}/pages/{raw_page['slug']}",
                }
                sync_run.processed_pages = index
                sync_run.processed_assets = processed_assets
                session.commit()
                page_records[raw_page["id"]] = page_record
                documents_for_index.append(page_document)
                committed_page_count = index
                logger.info(
                    "processed page id=%s assets=%s summary=%s",
                    raw_page["id"],
                    len(downloaded_assets),
                    bool(summary),
                )

            append_space_log(
                self.settings.wiki_root,
                space_key=space_key,
                mode=mode,
                timestamp=datetime.now(ZoneInfo(self.settings.app_timezone)),
                documents=documents_for_index,
                window_label=window_label,
            )
            session.execute(delete(PageLink).where(PageLink.source_page_id.in_([page.id for page in page_records.values()])))
            session.flush()
            self._raise_if_cancelled(cancel_requested)
            self._emit_progress(progress_callback, 92, "인덱스와 링크를 재구성하는 중입니다.")

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
                    parts = wiki_link.strip("/").split("/")
                    if len(parts) >= 4 and parts[0] == "spaces" and parts[2] == "pages":
                        target_space = parts[1]
                        target_slug = parts[3]
                    else:
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

            logger.debug("rebuilding materialized views space=%s", space_key)
            self._raise_if_cancelled(cancel_requested)
            self._rebuild_materialized_views(session)
            logger.debug("rebuilt materialized views space=%s", space_key)

            sync_run.status = "success"
            sync_run.processed_pages = committed_page_count
            sync_run.processed_assets = processed_assets
            sync_run.finished_at = self._utcnow()
            session.commit()
            self._emit_progress(progress_callback, 100, "동기화가 완료되었습니다.")
            logger.info(
                "sync complete mode=%s space=%s pages=%s assets=%s",
                mode,
                space_key,
                len(raw_pages),
                processed_assets,
            )

            return SyncResult(
                mode=mode,
                space_key=space_key,
                processed_pages=len(raw_pages),
                processed_assets=processed_assets,
                skipped_attachments=skipped_attachments,
            )
        except SyncCancelledError as exc:
            session.rollback()
            if sync_run_id is not None:
                self._finalize_sync_run(
                    sync_run_id=sync_run_id,
                    status="cancelled",
                    processed_pages=committed_page_count,
                    processed_assets=processed_assets,
                    error_message=str(exc),
                )
            logger.info("sync cancelled mode=%s space=%s processed_pages=%s", mode, space_key, committed_page_count)
            raise
        except Exception as exc:
            session.rollback()
            if sync_run_id is not None:
                self._finalize_sync_run(
                    sync_run_id=sync_run_id,
                    status="failed",
                    processed_pages=committed_page_count,
                    processed_assets=processed_assets,
                    error_message=str(exc),
                )
            logger.exception("sync failed mode=%s space=%s", mode, space_key)
            raise
        finally:
            session.close()

    def _summarize(self, markdown_body: str) -> str:
        if self.text_client:
            summary = (self.text_client.summarize(markdown_body) or "").strip()
            if summary and not summary.startswith("#"):
                return summary[:180]
        fallback = self._first_summary_sentence(markdown_body)
        if fallback:
            return fallback[:180]
        first_line = next((line.strip() for line in markdown_body.splitlines() if line.strip()), "")
        return re.sub(r"^\s*#{1,6}\s*", "", first_line).strip()[:180]

    @staticmethod
    def _first_summary_sentence(markdown_body: str) -> str:
        for raw_line in markdown_body.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith(("![[", "![", "|", "```")):
                continue
            cleaned = re.sub(r"^\s*[-*>]+\s*", "", stripped)
            cleaned = re.sub(r"\[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)", lambda match: match.group("label"), cleaned)
            cleaned = re.sub(r"!\[\[(?P<embed>[^\]]+)\]\]|\[\[(?P<target>[^\]|]+)(?:\|(?P<label>[^\]]+))?\]\]", lambda match: match.group("label") or match.group("target") or "", cleaned)
            cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:|")
            if cleaned:
                return cleaned
        return ""

    def _build_prod_url(self, raw_page: dict) -> str:
        if hasattr(self.confluence_client, "build_page_url"):
            return self.confluence_client.build_page_url(raw_page["id"])
        webui = raw_page.get("webui") or f"/pages/viewpage.action?pageId={raw_page['id']}"
        return f"{self.settings.conf_prod_base_url.rstrip('/')}/{webui.lstrip('/')}"

    @staticmethod
    def _image_reference_name(value: str) -> str:
        return Path(unquote(urlparse(value).path)).name

    @staticmethod
    def _normalize_attachment_name(value: str) -> str:
        return Path(unquote(value)).name

    def _extract_body_image_references(self, markdown_body: str) -> set[str]:
        references: set[str] = set()
        for match in BODY_IMAGE_PLACEHOLDER_RE.finditer(markdown_body):
            kind = match.group("kind")
            value = match.group("value").strip()
            if kind == "attachment":
                normalized = self._normalize_attachment_name(value)
            else:
                normalized = self._image_reference_name(value)
            if normalized:
                references.add(normalized)
        return references

    def _build_attachment_link_markdown(self, filename: str, download_path: str) -> str:
        return f"- [{filename}]({self._build_prod_download_url(download_path)})"

    def _build_prod_download_url(self, download_path: str) -> str:
        parsed = urlparse(download_path)
        if not parsed.scheme and not parsed.netloc:
            if download_path.startswith("/"):
                return f"{self.settings.conf_prod_base_url.rstrip('/')}/{download_path.lstrip('/')}"
            return urljoin(self.settings.conf_prod_base_url.rstrip("/") + "/", download_path)

        mirror = urlparse(self.settings.conf_mirror_base_url)
        prod = urlparse(self.settings.conf_prod_base_url)
        allowed_hosts = {mirror.netloc, prod.netloc}
        if parsed.netloc not in allowed_hosts:
            return download_path

        for candidate in (prod.path.rstrip("/"), mirror.path.rstrip("/")):
            if candidate and (parsed.path == candidate or parsed.path.startswith(f"{candidate}/")):
                base_path = parsed.path[len(candidate) :]
                query = f"?{parsed.query}" if parsed.query else ""
                return f"{self.settings.conf_prod_base_url.rstrip('/')}/{base_path.lstrip('/')}{query}"
        return download_path

    async def _materialize_asset(
        self,
        session,
        page_record: Page,
        space_key: str,
        filename: str,
        download_path: str,
        confluence_attachment_id: str | None,
        mime_type: str | None,
        force_image: bool = False,
        cancel_requested: CancelCallback | None = None,
    ) -> dict[str, str | bool | None]:
        self._raise_if_cancelled(cancel_requested)
        safe_filename = Path(filename).name or "asset"
        content = await self.confluence_client.download_bytes(download_path)
        asset_root = self.settings.wiki_root / "spaces" / space_key / "assets"
        local_path = save_asset(asset_root, safe_filename, content)
        is_image = force_image or is_image_filename(safe_filename) or bool((mime_type or "").startswith("image/"))
        caption = self.vision_client.describe_image(local_path) if is_image and self.vision_client else None
        public_url = build_wiki_asset_url(space_key, safe_filename)
        vault_path = asset_target(space_key, safe_filename)

        session.add(
            Asset(
                page_id=page_record.id,
                confluence_attachment_id=confluence_attachment_id,
                filename=safe_filename,
                mime_type=mime_type,
                local_path=str(local_path.relative_to(self.settings.wiki_root)),
                body_path=download_path,
                is_image=is_image,
                vlm_status="done" if caption else "skipped",
                vlm_summary=caption,
                downloaded_at=self._utcnow(),
            )
        )
        return {
            "filename": safe_filename,
            "public_url": public_url,
            "vault_path": vault_path,
            "local_path": str(local_path.relative_to(self.settings.wiki_root)),
            "body_path": download_path,
            "is_image": is_image,
            "caption": caption,
            "alt_text": safe_filename,
        }

    async def _replace_body_image_placeholders(
        self,
        session,
        page_record: Page,
        space_key: str,
        markdown_body: str,
        downloaded_assets: dict[str, dict[str, str | bool | None]],
        skipped_attachments: list[str],
        cancel_requested: CancelCallback | None = None,
    ) -> tuple[str, set[str], dict[str, dict[str, str | bool | None]]]:
        if not BODY_IMAGE_PLACEHOLDER_RE.search(markdown_body):
            return markdown_body, set(), {}

        logger.debug("replacing body image placeholders page_id=%s", page_record.confluence_page_id)
        available_assets = dict(downloaded_assets)
        new_body_assets: dict[str, dict[str, str | bool | None]] = {}
        inline_image_keys: set[str] = set()
        rendered_parts: list[str] = []
        cursor = 0

        for match in BODY_IMAGE_PLACEHOLDER_RE.finditer(markdown_body):
            self._raise_if_cancelled(cancel_requested)
            rendered_parts.append(markdown_body[cursor : match.start()])
            kind = match.group("kind")
            value = match.group("value").strip()
            alt_text = match.group("alt").strip() or "image"

            asset_key: str | None = None
            asset_info: dict[str, str | bool | None] | None = None

            if kind == "attachment":
                asset_key = Path(value).name
                asset_info = available_assets.get(asset_key)
            else:
                candidate_name = self._image_reference_name(value)
                if candidate_name:
                    asset_key = candidate_name
                    asset_info = available_assets.get(asset_key)

                if asset_info is None:
                    generated_name = candidate_name or f"image-{page_record.confluence_page_id}"
                    try:
                        asset_info = await self._materialize_asset(
                            session=session,
                            page_record=page_record,
                            space_key=space_key,
                            filename=generated_name,
                            download_path=value,
                            confluence_attachment_id=None,
                            mime_type=None,
                            force_image=True,
                            cancel_requested=cancel_requested,
                        )
                    except ValueError:
                        asset_info = None
                        rendered_parts.append(f"![{alt_text}]({value})")
                        cursor = match.end()
                        continue
                    except Exception as exc:
                        if not is_missing_attachment_redirect(exc):
                            raise
                        skipped_attachments.append(f"{space_key}/{page_record.confluence_page_id} {generated_name}")
                        asset_info = None
                    else:
                        asset_key = str(asset_info["filename"])
                        new_body_assets[asset_key] = asset_info
                        available_assets[asset_key] = asset_info

            if asset_info is not None and asset_info.get("is_image") is True and asset_key:
                asset_info["alt_text"] = alt_text
                inline_image_keys.add(asset_key)
                rendered_parts.append(
                    build_image_markdown(
                        str(asset_info.get("vault_path") or asset_info["public_url"]),
                        alt_text,
                        str(asset_info.get("caption") or "") or None,
                    )
                )
            else:
                rendered_parts.append(alt_text)

            cursor = match.end()

        rendered_parts.append(markdown_body[cursor:])
        return "".join(rendered_parts), inline_image_keys, new_body_assets

    def _raise_if_cancelled(self, cancel_requested: CancelCallback | None) -> None:
        self._renew_sync_lease()
        if cancel_requested is not None and cancel_requested():
            raise SyncCancelledError("cancelled by user")

    def _acquire_sync_lease(self, *, mode: str, space_key: str) -> SyncLeaseHandle:
        return self.sync_lease_service.acquire(
            holder_kind=mode,
            holder_scope=f"{space_key}:{uuid.uuid4().hex[:8]}",
            ttl_seconds=300,
        )

    def _renew_sync_lease(self) -> None:
        if self._active_sync_lease is None:
            return
        self.sync_lease_service.renew(self._active_sync_lease)

    def _release_sync_lease(self, lease_handle: SyncLeaseHandle | None) -> None:
        if lease_handle is None:
            return
        self.sync_lease_service.release(lease_handle)

    def _lease_progress_callback(self, progress_callback: ProgressCallback | None) -> ProgressCallback | None:
        if progress_callback is None:
            return None

        def wrapped(progress: int, message: str) -> None:
            self._renew_sync_lease()
            progress_callback(progress, message)

        return wrapped

    def _emit_progress(
        self,
        progress_callback: ProgressCallback | None,
        progress: int,
        message: str,
    ) -> None:
        if progress_callback is not None:
            progress_callback(progress, message)

    def _run_post_sync_sqlite_maintenance(self) -> None:
        try:
            run_sqlite_maintenance_for_url(self.settings.database_url)
        except Exception:
            logger.warning("sqlite maintenance failed", exc_info=True)

    def _finalize_sync_run(
        self,
        *,
        sync_run_id: int,
        status: str,
        processed_pages: int,
        processed_assets: int,
        error_message: str | None = None,
    ) -> None:
        session = self.session_factory()
        try:
            sync_run = session.get(SyncRun, sync_run_id)
            if sync_run is None:
                return
            sync_run.status = status
            sync_run.processed_pages = processed_pages
            sync_run.processed_assets = processed_assets
            sync_run.finished_at = self._utcnow()
            sync_run.error_message = error_message
            session.commit()
        finally:
            session.close()

    def _rebuild_materialized_views(self, session) -> None:
        grouped_documents: dict[str, list[dict[str, str]]] = {}
        all_pages = session.scalars(select(Page)).all()
        spaces = session.scalars(select(Space)).all()
        space_lookup = {space.id: space.space_key for space in spaces}
        knowledge_service = KnowledgeService(self.settings)
        lint_service = LintService(self.settings)
        all_page_documents: list[dict[str, str]] = []
        global_space = ensure_global_knowledge_space(session)
        knowledge_service.rebuild_global_with_session(session)
        lint_service.rebuild_global_with_session(session)
        all_knowledge_documents = [
            {
                "title": doc.title,
                "slug": doc.slug,
                "kind": doc.kind,
                "summary": doc.summary or "",
                "href": knowledge_href(doc.kind, doc.slug),
                "source_refs": doc.source_refs or "",
                "source_spaces": source_space_keys(doc.source_refs),
            }
            for doc in session.scalars(
                select(KnowledgeDocument).where(KnowledgeDocument.space_id == global_space.id)
            ).all()
        ]
        for space_id, space_key in sorted(space_lookup.items(), key=lambda item: item[1]):
            if space_key == global_space.space_key:
                continue
            rows = session.execute(
                select(Page, WikiDocument)
                .join(WikiDocument, WikiDocument.page_id == Page.id)
                .where(Page.space_id == space_id)
            ).all()
            documents = [
                {
                    "title": page.title,
                    "slug": page.slug,
                    "space_key": space_key,
                    "updated_at": page.updated_at_remote.isoformat() if page.updated_at_remote else "",
                    "summary": _wiki_document.summary or "",
                    "href": f"/spaces/{space_key}/pages/{page.slug}",
                }
                for page, _wiki_document in rows
            ]
            grouped_documents[space_key] = [*documents]
            all_page_documents.extend(documents)
            build_space_index(self.settings.wiki_root, space_key, documents, all_knowledge_documents)
            build_space_synthesis(
                self.settings.wiki_root,
                space_key,
                documents,
                generated_at=datetime.now(ZoneInfo(self.settings.app_timezone)),
                recent_log_entries=read_space_log_excerpt(self.settings.wiki_root, space_key),
            )

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
        write_named_graph_cache(
            self.settings.wiki_root,
            "knowledge-graph.json",
            build_knowledge_graph_payload(
                knowledge_documents=all_knowledge_documents,
                page_documents=all_page_documents,
            ),
        )

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    def _load_existing_page_slugs_from_markdown(self, space_key: str) -> dict[str, str]:
        pages_root = self.settings.wiki_root / "spaces" / space_key / "pages"
        if not pages_root.exists():
            return {}
        page_slugs: dict[str, str] = {}
        for path in pages_root.glob("*.md"):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
                if not lines or lines[0].strip() != "---":
                    continue
                end_index = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
                frontmatter = yaml.safe_load("\n".join(lines[1:end_index])) or {}
                page_id = str(frontmatter.get("page_id") or "").strip()
                slug = str(frontmatter.get("slug") or path.stem).strip()
                if page_id and slug:
                    page_slugs[page_id] = slug
            except (OSError, StopIteration, yaml.YAMLError):
                continue
        return page_slugs
