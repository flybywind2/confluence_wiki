from __future__ import annotations

from datetime import datetime
from pathlib import Path
from collections import defaultdict

from app.core.obsidian import knowledge_link, page_link
from app.services.wiki_writer import write_markdown_file


def _doc_reference(doc: dict[str, str], space_key: str) -> str:
    title = str(doc.get("title") or doc.get("slug") or "document")
    if doc.get("kind") not in {None, "", "page"}:
        return knowledge_link(space_key, str(doc.get("kind") or ""), str(doc["slug"]), title)
    return page_link(space_key, str(doc["slug"]), title)


def build_space_index(
    root: Path,
    space_key: str,
    documents: list[dict[str, str]],
    knowledge_documents: list[dict[str, str]],
) -> Path:
    space_root = root / "spaces" / space_key
    space_root.mkdir(parents=True, exist_ok=True)
    lines = [f"# {space_key} Index", ""]
    sections = [("Pages", documents)]
    grouped_knowledge: dict[str, list[dict[str, str]]] = defaultdict(list)
    kind_titles = {
        "entity": "Entities",
        "keyword": "Keywords",
        "analysis": "Analyses",
        "lint": "Lint",
    }
    for doc in knowledge_documents:
        grouped_knowledge[kind_titles.get(doc.get("kind", ""), "Knowledge")].append(doc)

    for title, items in sections:
        lines.append(f"## {title}")
        lines.append("")
        for doc in sorted(items, key=lambda item: item["title"].lower()):
            summary = doc.get("summary") or ""
            lines.append(f"- {_doc_reference(doc, space_key)}: {summary}".rstrip(": "))
        lines.append("")
    for section_title in ("Entities", "Keywords", "Analyses", "Lint"):
        items = grouped_knowledge.get(section_title, [])
        if not items:
            continue
        lines.append(f"## {section_title}")
        lines.append("")
        for doc in sorted(items, key=lambda item: item["title"].lower()):
            summary = doc.get("summary") or ""
            lines.append(f"- [{doc['title']}]({doc['href']}): {summary}".rstrip(": "))
        lines.append("")
    target = space_root / "index.md"
    return write_markdown_file(
        target,
        {
            "title": f"{space_key} Index",
            "aliases": [f"{space_key} Index"],
            "tags": [f"space/{space_key}", "kind/index"],
        },
        "\n".join(lines).strip(),
    )


def append_space_log(
    root: Path,
    space_key: str,
    mode: str,
    timestamp: datetime,
    documents: list[dict[str, str]],
    window_label: str | None = None,
) -> Path:
    space_root = root / "spaces" / space_key
    target = space_root / "log.md"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        write_markdown_file(
            target,
            {
                "title": f"{space_key} Activity Log",
                "aliases": [f"{space_key} Activity Log"],
                "tags": [f"space/{space_key}", "kind/log"],
            },
            f"# {space_key} Activity Log",
        )

    lines = [f"## [{timestamp.isoformat()}] sync | {space_key} | {mode}"]
    if window_label:
        lines.append(f"- window: {window_label}")
    if documents:
        links = ", ".join(_doc_reference(doc, space_key) for doc in documents)
        lines.append(f"- pages: {links}")
    else:
        lines.append("- pages: none")
    with target.open("a", encoding="utf-8") as handle:
        handle.write("\n" + "\n".join(lines).strip() + "\n")
    return target


def read_space_log_excerpt(root: Path, space_key: str, limit: int = 4) -> list[str]:
    log_path = root / "spaces" / space_key / "log.md"
    if not log_path.exists():
        return []
    entries = [line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("## [")]
    return entries[-limit:]


def build_space_synthesis(
    root: Path,
    space_key: str,
    documents: list[dict[str, str]],
    generated_at: datetime,
    recent_log_entries: list[str],
) -> Path:
    space_root = root / "spaces" / space_key
    lines = ["# Synthesis", "", f"- generated_at: {generated_at.isoformat()}", ""]
    if documents:
        lines.extend(["## 핵심 문서", ""])
        for doc in sorted(documents, key=lambda item: item["title"].lower()):
            summary = doc.get("summary") or ""
            lines.append(f"- {_doc_reference(doc, space_key)}: {summary}".rstrip(": "))
        lines.append("")
    if recent_log_entries:
        lines.extend(["## 최근 동기화", ""])
        for entry in recent_log_entries:
            lines.append(f"- {entry}")
        lines.append("")
    lines.extend(["## 메모", "", "이 문서는 현재 space의 누적 요약 페이지입니다."])
    target = space_root / "synthesis.md"
    return write_markdown_file(
        target,
        {
            "title": "Synthesis",
            "aliases": ["Synthesis"],
            "tags": [f"space/{space_key}", "kind/synthesis"],
        },
        "\n".join(lines).strip(),
    )


def build_global_index(root: Path, grouped_documents: dict[str, list[dict[str, str]]]) -> Path:
    global_root = root / "global"
    global_root.mkdir(parents=True, exist_ok=True)
    lines = ["# Global Wiki Index", ""]
    for space_key, documents in sorted(grouped_documents.items()):
        lines.append(f"## {space_key}")
        for doc in sorted(documents, key=lambda item: item["title"].lower()):
            summary = doc.get("summary") or ""
            if doc.get("href"):
                lines.append(f"- [{doc['title']}]({doc['href']}): {summary}".rstrip(": "))
            else:
                lines.append(f"- [[{space_key}/{doc['slug']}]]: {summary}".rstrip(": "))
        lines.append("")
    target = global_root / "index.md"
    return write_markdown_file(
        target,
        {
            "title": "Global Wiki Index",
            "aliases": ["Global Wiki Index"],
            "tags": ["kind/global-index"],
        },
        "\n".join(lines).strip(),
    )
