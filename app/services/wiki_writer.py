from __future__ import annotations

from pathlib import Path

import yaml


def frontmatter_to_yaml(frontmatter: dict) -> str:
    rendered = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{rendered}\n---\n"


def write_markdown_file(path: Path, frontmatter: dict | None, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered_frontmatter = frontmatter_to_yaml(frontmatter) + "\n" if frontmatter else ""
    path.write_text(rendered_frontmatter + body.strip() + "\n", encoding="utf-8")
    return path


def write_page_markdown(root: Path, space_key: str, slug: str, frontmatter: dict, body: str) -> Path:
    page_dir = root / "spaces" / space_key / "pages"
    path = page_dir / f"{slug}.md"
    return write_markdown_file(path, frontmatter, body)


def write_history_markdown(root: Path, space_key: str, slug: str, version_number: int, frontmatter: dict, body: str) -> Path:
    history_dir = root / "spaces" / space_key / "history" / slug
    path = history_dir / f"v{version_number:04d}.md"
    return write_markdown_file(path, frontmatter, body)


def write_space_document(root: Path, space_key: str, filename: str, body: str, frontmatter: dict | None = None) -> Path:
    space_dir = root / "spaces" / space_key
    path = space_dir / filename
    return write_markdown_file(path, frontmatter, body)
    return path
