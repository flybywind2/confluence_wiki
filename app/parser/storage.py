from __future__ import annotations

import re

from bs4 import BeautifulSoup
from selectolax.parser import HTMLParser, Node

from app.parser.tables import render_table_block
from app.services.assets import make_attachment_image_placeholder, make_source_image_placeholder

_PAGE_ID_RE = re.compile(r"pageId=(\d+)")
_CDATA_COMMENT_RE = re.compile(r"^\s*<!--\[CDATA\[(?P<body>.*)\]\]-->\s*$", re.DOTALL)
_CALLOUT_KIND_BY_MACRO = {
    "info": "info",
    "note": "note",
    "tip": "tip",
    "warning": "warning",
    "panel": "note",
}
_BLOCK_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "table",
    "blockquote",
    "pre",
    "ac:structured-macro",
    "ac:image",
    "img",
}


def _node_tag(node: Node | None) -> str:
    return str(getattr(node, "tag", "") or "").lower()


def _iter_children(node: Node | None):
    child = getattr(node, "child", None)
    while child is not None:
        yield child
        child = child.next


def _node_attr(node: Node, key: str) -> str | None:
    value = dict(getattr(node, "attributes", {}) or {}).get(key)
    return str(value) if value is not None else None


def _node_text(node: Node | None, *, strip: bool = True) -> str:
    if node is None:
        return ""
    try:
        return node.text(strip=strip)
    except TypeError:
        return node.text().strip() if strip else node.text()


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _link_target(node: Node) -> str | None:
    resource_id = _node_attr(node, "data-linked-resource-id")
    if resource_id:
        return resource_id
    href = _node_attr(node, "href") or ""
    match = _PAGE_ID_RE.search(href)
    return match.group(1) if match else None


def _macro_name(node: Node) -> str:
    return (_node_attr(node, "ac:name") or "").strip().lower()


def _first_descendant(node: Node, tag_name: str) -> Node | None:
    for child in node.traverse():
        if child is node:
            continue
        if _node_tag(child) == tag_name:
            return child
    return None


def _find_macro_parameter(node: Node, parameter_name: str) -> str:
    for child in node.traverse():
        if child is node or _node_tag(child) != "ac:parameter":
            continue
        if (_node_attr(child, "ac:name") or "").strip().lower() == parameter_name.lower():
            return _collapse_whitespace(_node_text(child, strip=False))
    return ""


def _extract_plain_text_body(node: Node) -> str:
    plain = _first_descendant(node, "ac:plain-text-body")
    if plain is None:
        return ""
    parts: list[str] = []
    for child in _iter_children(plain):
        tag = _node_tag(child)
        if tag == "_comment":
            html = getattr(child, "html", "") or ""
            match = _CDATA_COMMENT_RE.match(html)
            if match:
                parts.append(match.group("body"))
                continue
        if tag == "-text":
            parts.append(_node_text(child, strip=False))
            continue
        parts.append(_node_text(child, strip=False))
    return "".join(parts).strip()


def _render_inline(node: Node) -> str:
    tag = _node_tag(node)
    if tag == "-text":
        return _node_text(node, strip=False)
    if tag == "_comment":
        return ""
    if tag == "a":
        text = _collapse_whitespace("".join(_render_inline(child) for child in _iter_children(node))) or "link"
        target_id = _link_target(node)
        if target_id:
            return f"[[pageid:{target_id}|{text}]]"
        href = _node_attr(node, "href") or "#"
        return f"[{text}]({href})"
    if tag == "img":
        src = (_node_attr(node, "src") or "").strip()
        alt = (_node_attr(node, "alt") or "").strip() or "image"
        return make_source_image_placeholder(src, alt) if src else ""
    if tag == "ac:image":
        attachment = _first_descendant(node, "ri:attachment")
        if attachment is not None and _node_attr(attachment, "ri:filename"):
            filename = _node_attr(attachment, "ri:filename") or "image"
            return make_attachment_image_placeholder(filename, filename)
        url_node = _first_descendant(node, "ri:url")
        if url_node is not None and _node_attr(url_node, "ri:value"):
            src = _node_attr(url_node, "ri:value") or ""
            return make_source_image_placeholder(src, "image")
        return ""
    if tag in {"strong", "b"}:
        inner = _collapse_whitespace("".join(_render_inline(child) for child in _iter_children(node)))
        return f"**{inner}**" if inner else ""
    if tag in {"em", "i"}:
        inner = _collapse_whitespace("".join(_render_inline(child) for child in _iter_children(node)))
        return f"*{inner}*" if inner else ""
    if tag == "code":
        return f"`{_node_text(node, strip=True)}`"
    if tag == "br":
        return "\n"
    return "".join(_render_inline(child) for child in _iter_children(node))


def _render_inline_children(node: Node, *, skip_block_children: bool = False) -> str:
    rendered: list[str] = []
    for child in _iter_children(node):
        if skip_block_children and _node_tag(child) in {"ul", "ol"}:
            continue
        rendered.append(_render_inline(child))
    text = "".join(rendered)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [_collapse_whitespace(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _indent_block(text: str, prefix: str) -> str:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(f"{prefix}{line}" for line in lines)


def _render_list(list_node: Node, depth: int = 0) -> str:
    ordered = _node_tag(list_node) == "ol"
    lines: list[str] = []
    index = 1
    for item in _iter_children(list_node):
        if _node_tag(item) != "li":
            continue
        marker = f"{index}." if ordered else "-"
        index += 1
        inline = _render_inline_children(item, skip_block_children=True)
        content = inline or _collapse_whitespace(_node_text(item, strip=True))
        lines.append(f"{'  ' * depth}{marker} {content}".rstrip())
        for child in _iter_children(item):
            if _node_tag(child) in {"ul", "ol"}:
                nested = _render_list(child, depth + 1)
                if nested:
                    lines.append(nested)
    return "\n".join(line for line in lines if line.strip())


def _render_blockquote(node: Node) -> str:
    content = _render_children_as_blocks(node)
    if not content:
        content = _render_inline_children(node)
    return _indent_block(content, "> ")


def _render_macro(node: Node) -> str:
    name = _macro_name(node)
    if name == "code":
        language = _find_macro_parameter(node, "language")
        body = _extract_plain_text_body(node)
        fence = f"```{language}".rstrip()
        return f"{fence}\n{body}\n```".strip()
    if name == "expand":
        title = _find_macro_parameter(node, "title") or "자세히 보기"
        body = _first_descendant(node, "ac:rich-text-body")
        content = _render_children_as_blocks(body) if body is not None else _render_inline_children(node)
        return "\n".join([f"> [!summary] {title}", _indent_block(content, "> ")]).strip()
    if name in _CALLOUT_KIND_BY_MACRO:
        label = name.capitalize()
        body = _first_descendant(node, "ac:rich-text-body")
        content = _render_children_as_blocks(body) if body is not None else _render_inline_children(node)
        return "\n".join([f"> [!{_CALLOUT_KIND_BY_MACRO[name]}] {label}", _indent_block(content, "> ")]).strip()
    body = _first_descendant(node, "ac:rich-text-body")
    if body is not None:
        return _render_children_as_blocks(body)
    plain = _extract_plain_text_body(node)
    if plain:
        return plain
    return _collapse_whitespace(_node_text(node, strip=True))


def _render_block(node: Node) -> str:
    tag = _node_tag(node)
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(tag[1])
        return f"{'#' * level} {_collapse_whitespace(_node_text(node, strip=True))}"
    if tag == "p":
        return _render_inline_children(node)
    if tag in {"ul", "ol"}:
        return _render_list(node)
    if tag == "table":
        return render_table_block(getattr(node, "html", "") or "")
    if tag == "blockquote":
        return _render_blockquote(node)
    if tag == "pre":
        return f"```\n{_node_text(node, strip=False).strip()}\n```"
    if tag == "ac:structured-macro":
        return _render_macro(node)
    if tag in {"img", "ac:image"}:
        return _render_inline(node).strip()
    return _render_inline_children(node)


def _render_children_as_blocks(node: Node | None) -> str:
    if node is None:
        return ""
    blocks: list[str] = []
    for child in _iter_children(node):
        tag = _node_tag(child)
        if tag in {"-text", "_comment"}:
            text = _collapse_whitespace(_node_text(child, strip=False))
            if text:
                blocks.append(text)
            continue
        block = _render_block(child)
        if block:
            blocks.append(block.strip())
    return "\n\n".join(block for block in blocks if block).strip()


def storage_to_markdown(storage_html: str) -> str:
    if not str(storage_html or "").strip():
        return ""
    parser = HTMLParser(storage_html)
    body = parser.body or parser.root
    rendered = _render_children_as_blocks(body)
    if rendered:
        return rendered

    soup = BeautifulSoup(storage_html, "html.parser")
    text = soup.get_text(" ", strip=True)
    return _collapse_whitespace(text)
