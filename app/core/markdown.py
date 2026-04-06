from __future__ import annotations

import re
from pathlib import Path

from markdown_it import MarkdownIt

_WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_PAGE_LINK_RE = re.compile(r"\[\[pageid:(?P<page_id>\d+)(?:\|(?P<label>[^\]]+))?\]\]")


def resolve_page_placeholders(markdown_text: str, page_lookup: dict[str, tuple[str, str]]) -> str:
    def _replace(match: re.Match[str]) -> str:
        page_id = match.group("page_id")
        label = match.group("label") or page_id
        target = page_lookup.get(page_id)
        if target is None:
            return label
        space_key, slug = target
        return f"[[{space_key}/{slug}]]"

    return _PAGE_LINK_RE.sub(_replace, markdown_text)


def extract_wiki_links(markdown_text: str) -> list[str]:
    return [match.group(1).strip() for match in _WIKI_LINK_RE.finditer(markdown_text)]


def strip_frontmatter(content: str) -> str:
    if not content.startswith("---"):
        return content
    marker = content.find("\n---", 3)
    if marker == -1:
        return content
    return content[marker + 4 :].lstrip()


def render_markdown(markdown_text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        parts = target.split("/", 1)
        if len(parts) == 2:
            space_key, slug = parts
            return f"[{slug.replace('-', ' ')}](/spaces/{space_key}/pages/{slug})"
        return match.group(0)

    parser = MarkdownIt("commonmark", {"html": True, "linkify": True, "breaks": True})
    return parser.render(_WIKI_LINK_RE.sub(_replace, markdown_text))


def read_markdown_body(path: Path) -> str:
    return strip_frontmatter(path.read_text(encoding="utf-8"))
