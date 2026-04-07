from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from app.clients.rate_limit import MinuteRateLimiter, get_shared_rate_limiter
from app.core.config import Settings, get_settings


class MissingAttachmentRedirect(RuntimeError):
    def __init__(self, download_path: str, location: str) -> None:
        self.download_path = download_path
        self.location = location
        super().__init__(f"missing attachment redirect for {download_path}: {location}")


def is_missing_attachment_redirect(exc: BaseException) -> bool:
    if isinstance(exc, MissingAttachmentRedirect):
        return True
    if not isinstance(exc, httpx.HTTPStatusError) or exc.response is None:
        return False
    location = exc.response.headers.get("location", "")
    return exc.response.status_code in {301, 302, 303, 307, 308} and "attachmentnotfound" in location.casefold()


class ConfluenceClient:
    def __init__(self, settings: Settings | None = None, limiter: MinuteRateLimiter | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.conf_mirror_base_url.rstrip("/")
        self.prod_base_url = self.settings.conf_prod_base_url.rstrip("/")
        self.verify_ssl = self.settings.conf_verify_ssl
        self.timeout = self.settings.sync_request_timeout_seconds
        self.limiter = limiter or get_shared_rate_limiter(limit=self.settings.sync_rate_limit_per_minute)

    def build_page_url(self, page_id: str) -> str:
        return f"{self.prod_base_url}/pages/viewpage.action?pageId={page_id}"

    def _api_url(self, path: str) -> str:
        path = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}/rest/api{path}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        await self.limiter.acquire()
        async with httpx.AsyncClient(
            auth=(self.settings.conf_username, self.settings.conf_password),
            timeout=self.timeout,
            verify=self.verify_ssl,
        ) as client:
            response = await client.request(method, self._api_url(path), **kwargs)
            response.raise_for_status()
            return response

    async def _collect_paginated_results(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        current_path = path
        current_params = dict(params or {})
        results: list[dict[str, Any]] = []

        while True:
            response = await self._request("GET", current_path, params=current_params)
            payload = response.json()
            results.extend(payload.get("results", []))

            next_link = payload.get("_links", {}).get("next")
            if not next_link:
                break

            parsed = urlparse(next_link)
            current_path = parsed.path.removeprefix("/rest/api") or path
            current_params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            for key, value in (params or {}).items():
                current_params.setdefault(key, value)

        return results

    async def fetch_page(self, page_id: str) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"/content/{page_id}",
            params={"expand": "body.storage,version,space,history,ancestors"},
        )
        return self._normalize_page_payload(response.json())

    def _normalize_page_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        ancestors = data.get("ancestors") or []
        parent_id = str(ancestors[-1]["id"]) if ancestors else None
        return {
            "id": str(data["id"]),
            "title": data["title"],
            "space_key": data.get("space", {}).get("key", ""),
            "parent_id": parent_id,
            "version": data.get("version", {}).get("number", 1),
            "updated_at": data.get("version", {}).get("when"),
            "body": data.get("body", {}).get("storage", {}).get("value", ""),
            "webui": data.get("_links", {}).get("webui", f"/pages/viewpage.action?pageId={data['id']}"),
        }

    async def fetch_descendant_pages(self, root_page_id: str) -> list[dict[str, Any]]:
        results = await self._collect_paginated_results(f"/content/{root_page_id}/descendant/page", params={"limit": 1000})
        return [{"id": str(item["id"])} for item in results]

    async def fetch_child_pages(self, root_page_id: str) -> list[dict[str, Any]]:
        results = await self._collect_paginated_results(f"/content/{root_page_id}/child/page", params={"limit": 1000})
        return [{"id": str(item["id"])} for item in results]

    async def fetch_page_tree(self, root_page_id: str) -> list[dict[str, Any]]:
        pending = [str(root_page_id)]
        seen = {str(root_page_id)}
        collected: list[dict[str, Any]] = []

        while pending:
            current_page_id = pending.pop(0)
            for item in await self.fetch_child_pages(current_page_id):
                page_id = str(item["id"])
                if page_id in seen:
                    continue
                seen.add(page_id)
                collected.append({"id": page_id})
                pending.append(page_id)

        return collected

    async def search_cql(self, space_key: str, cql: str) -> list[dict[str, Any]]:
        results = await self._collect_paginated_results("/content/search", params={"cql": cql, "limit": 1000})
        return [{"id": str(item["id"])} for item in results]

    async def list_attachments(self, page_id: str) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        results = await self._collect_paginated_results(f"/content/{page_id}/child/attachment", params={"limit": 1000})
        for item in results:
            attachments.append(
                {
                    "id": str(item["id"]),
                    "filename": item["title"],
                    "mime_type": item.get("metadata", {}).get("mediaType"),
                    "download": item.get("_links", {}).get("download"),
                }
            )
        return attachments

    async def download_bytes(self, download_path: str) -> bytes:
        await self.limiter.acquire()
        target_url = self._resolve_download_url(download_path)
        async with httpx.AsyncClient(
            auth=(self.settings.conf_username, self.settings.conf_password),
            timeout=self.timeout,
            verify=self.verify_ssl,
        ) as client:
            response = await client.get(target_url)
            location = response.headers.get("location", "")
            if response.status_code in {301, 302, 303, 307, 308} and "attachmentnotfound" in location.casefold():
                raise MissingAttachmentRedirect(download_path=download_path, location=location)
            response.raise_for_status()
            return response.content

    def _resolve_download_url(self, download_path: str) -> str:
        parsed = urlparse(download_path)
        if not parsed.scheme and not parsed.netloc:
            if download_path.startswith("/"):
                resolved = urlparse(f"{self.base_url.rstrip('/')}/{download_path.lstrip('/')}")
            else:
                resolved = urlparse(urljoin(self.base_url.rstrip("/") + "/", download_path))
            base_path = urlparse(self.base_url).path.rstrip("/")
            if not (resolved.path == base_path or resolved.path.startswith(f"{base_path}/")):
                raise ValueError(f"download path is outside configured confluence base: {resolved.path}")
            return resolved.geturl()

        mirror = urlparse(self.base_url)
        prod = urlparse(self.prod_base_url)
        allowed_hosts = {mirror.netloc, prod.netloc}
        if parsed.netloc not in allowed_hosts:
            raise ValueError(f"download host is not allowed: {parsed.netloc}")

        base_path = None
        for candidate in (prod.path.rstrip("/"), mirror.path.rstrip("/")):
            if candidate and (parsed.path == candidate or parsed.path.startswith(f"{candidate}/")):
                base_path = parsed.path[len(candidate) :]
                break
        if base_path is None:
            raise ValueError(f"download path is outside configured confluence base: {parsed.path}")

        query = f"?{parsed.query}" if parsed.query else ""
        return f"{self.base_url.rstrip('/')}/{base_path.lstrip('/')}{query}"

    def fetch_page_sync(self, page_id: str) -> dict[str, Any]:
        return asyncio.run(self.fetch_page(page_id))
