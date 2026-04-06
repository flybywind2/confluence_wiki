from __future__ import annotations

from pathlib import Path

import yaml


def frontmatter_to_yaml(frontmatter: dict) -> str:
    rendered = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{rendered}\n---\n"


def write_page_markdown(root: Path, space_key: str, slug: str, frontmatter: dict, body: str) -> Path:
    page_dir = root / "spaces" / space_key / "pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    path = page_dir / f"{slug}.md"
    path.write_text(frontmatter_to_yaml(frontmatter) + "\n" + body.strip() + "\n", encoding="utf-8")
    return path
