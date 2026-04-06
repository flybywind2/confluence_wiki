from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from app.parser.tables import render_table_block
from app.services.assets import make_attachment_image_placeholder, make_source_image_placeholder

_PAGE_ID_RE = re.compile(r"pageId=(\d+)")


def _link_target(tag: Tag) -> str | None:
    resource_id = tag.get("data-linked-resource-id")
    if resource_id:
        return str(resource_id)
    href = tag.get("href") or ""
    match = _PAGE_ID_RE.search(href)
    return match.group(1) if match else None


def _render_inline(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node)

    name = (node.name or "").lower()
    if name == "a":
        text = node.get_text(" ", strip=True) or "link"
        target_id = _link_target(node)
        if target_id:
            return f"[[pageid:{target_id}|{text}]]"
        href = node.get("href") or "#"
        return f"[{text}]({href})"
    if name == "img":
        src = (node.get("src") or "").strip()
        alt = (node.get("alt") or "").strip() or "image"
        if src:
            return make_source_image_placeholder(src, alt)
        return ""
    if name == "ac:image":
        attachment = node.find("ri:attachment")
        if attachment and attachment.get("ri:filename"):
            filename = attachment.get("ri:filename")
            return make_attachment_image_placeholder(filename, filename)
        url_node = node.find("ri:url")
        if url_node and url_node.get("ri:value"):
            src = url_node.get("ri:value")
            return make_source_image_placeholder(src, "image")
        return ""
    if name in {"strong", "b"}:
        return f"**{''.join(_render_inline(child) for child in node.children).strip()}**"
    if name in {"em", "i"}:
        return f"*{''.join(_render_inline(child) for child in node.children).strip()}*"
    if name == "code":
        return f"`{node.get_text(strip=True)}`"
    if name == "br":
        return "\n"
    return "".join(_render_inline(child) for child in node.children)


def _render_list(tag: Tag, ordered: bool) -> str:
    marker = "1." if ordered else "-"
    return "\n".join(
        f"{marker} {''.join(_render_inline(child) for child in item.children).strip()}"
        for item in tag.find_all("li", recursive=False)
    )


def storage_to_markdown(storage_html: str) -> str:
    soup = BeautifulSoup(storage_html, "html.parser")
    body = soup.body or soup
    blocks: list[str] = []
    for child in body.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                blocks.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        name = (child.name or "").lower()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            blocks.append(f"{'#' * int(name[1])} {child.get_text(' ', strip=True)}")
        elif name == "p":
            text = "".join(_render_inline(grandchild) for grandchild in child.children).strip()
            if text:
                blocks.append(text)
        elif name == "img":
            text = _render_inline(child).strip()
            if text:
                blocks.append(text)
        elif name == "ac:image":
            text = _render_inline(child).strip()
            if text:
                blocks.append(text)
        elif name == "ul":
            blocks.append(_render_list(child, ordered=False))
        elif name == "ol":
            blocks.append(_render_list(child, ordered=True))
        elif name == "table":
            blocks.append(render_table_block(str(child)))
        elif name == "blockquote":
            blocks.append("> " + child.get_text(" ", strip=True))
        else:
            text = child.get_text(" ", strip=True)
            if text:
                blocks.append(text)
    return "\n\n".join(blocks).strip()
