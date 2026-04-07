from __future__ import annotations

from pathlib import Path

from app.core.knowledge import knowledge_segment


def page_target(space_key: str, slug: str) -> str:
    return f"spaces/{space_key}/pages/{slug}"


def knowledge_target(space_key: str, kind: str, slug: str) -> str:
    return f"spaces/{space_key}/knowledge/{knowledge_segment(kind)}/{slug}"


def asset_target(space_key: str, filename: str) -> str:
    return f"spaces/{space_key}/assets/{Path(filename).name}"


def wiki_link(target: str, label: str | None = None) -> str:
    return f"[[{target}|{label}]]" if label else f"[[{target}]]"


def page_link(space_key: str, slug: str, label: str | None = None) -> str:
    return wiki_link(page_target(space_key, slug), label)


def knowledge_link(space_key: str, kind: str, slug: str, label: str | None = None) -> str:
    return wiki_link(knowledge_target(space_key, kind, slug), label)


def asset_embed(space_key: str, filename: str) -> str:
    return f"![[{asset_target(space_key, filename)}]]"
