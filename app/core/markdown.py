from __future__ import annotations

import re
from pathlib import Path

from markdown_it import MarkdownIt
import yaml
from app.core.knowledge import knowledge_segment

_WIKI_LINK_RE = re.compile(r"(?<!\!)\[\[([^\]]+)\]\]")
_WIKI_EMBED_RE = re.compile(r"!\[\[([^\]]+)\]\]")
_PAGE_LINK_RE = re.compile(r"\[\[pageid:(?P<page_id>\d+)(?:\|(?P<label>[^\]]+))?\]\]")


def resolve_page_placeholders(markdown_text: str, page_lookup: dict[str, tuple[str, str]]) -> str:
    def _replace(match: re.Match[str]) -> str:
        page_id = match.group("page_id")
        label = match.group("label") or page_id
        target = page_lookup.get(page_id)
        if target is None:
            return label
        space_key, slug = target
        return f"[[spaces/{space_key}/pages/{slug}|{label}]]"

    return _PAGE_LINK_RE.sub(_replace, markdown_text)


def extract_wiki_links(markdown_text: str) -> list[str]:
    links: list[str] = []
    for match in _WIKI_LINK_RE.finditer(markdown_text):
        target = match.group(1).strip().split("|", 1)[0].strip()
        if not target:
            continue
        if target.startswith("spaces/") and "/assets/" in target:
            continue
        links.append(target)
    return links


def strip_frontmatter(content: str) -> str:
    if not content.startswith("---"):
        return content
    marker = content.find("\n---", 3)
    if marker == -1:
        return content
    return content[marker + 4 :].lstrip()


def split_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content
    marker = content.find("\n---", 3)
    if marker == -1:
        return {}, content
    frontmatter_text = content[4:marker]
    body = content[marker + 4 :].lstrip()
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        frontmatter = {}
    return frontmatter, body


def render_markdown(markdown_text: str) -> str:
    def _route_for_target(target: str) -> str | None:
        parts = target.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "knowledge":
            return f"/knowledge/{knowledge_segment(parts[1])}/{parts[2]}"
        if len(parts) == 2:
            return f"/spaces/{parts[0]}/pages/{parts[1]}"
        if len(parts) >= 4 and parts[0] == "spaces" and parts[2] == "pages":
            return f"/spaces/{parts[1]}/pages/{parts[3]}"
        if len(parts) >= 5 and parts[0] == "spaces" and parts[2] == "knowledge":
            return f"/spaces/{parts[1]}/knowledge/{knowledge_segment(parts[3])}/{parts[4]}"
        return None

    def _replace_embed(match: re.Match[str]) -> str:
        target = match.group(1).strip().split("|", 1)[0].strip()
        parts = target.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "spaces" and parts[2] == "assets":
            filename = parts[3]
            return f'<img src="/wiki-static/spaces/{parts[1]}/assets/{filename}" alt="{filename}" />'
        return match.group(0)

    def _replace_link(match: re.Match[str]) -> str:
        raw_target = match.group(1).strip()
        target, _, label = raw_target.partition("|")
        target = target.strip()
        route = _route_for_target(target)
        if route is None:
            return match.group(0)
        display = label.strip() if label.strip() else Path(target).name.replace("-", " ")
        return f"[{display}]({route})"

    parser = MarkdownIt("commonmark", {"html": True, "linkify": True, "breaks": True})
    hydrated = _WIKI_EMBED_RE.sub(_replace_embed, markdown_text)
    hydrated = _WIKI_LINK_RE.sub(_replace_link, hydrated)
    return parser.render(hydrated)


def read_markdown_body(path: Path) -> str:
    return strip_frontmatter(path.read_text(encoding="utf-8"))


def read_markdown_document(path: Path) -> tuple[dict, str]:
    return split_frontmatter(path.read_text(encoding="utf-8"))
