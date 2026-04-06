from __future__ import annotations

from slugify import slugify


def page_slug(title: str, page_id: str | int) -> str:
    base = slugify(title, allow_unicode=True) or "page"
    return f"{base}-{page_id}"
