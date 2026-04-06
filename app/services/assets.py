from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}
BODY_IMAGE_PLACEHOLDER_RE = re.compile(r"\[\[confluence-image:(?P<kind>attachment|src):(?P<value>[^|\]]+)\|(?P<alt>[^\]]*)\]\]")


def is_image_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_SUFFIXES


def save_asset(asset_root: Path, filename: str, content: bytes) -> Path:
    asset_root.mkdir(parents=True, exist_ok=True)
    target = asset_root / filename
    target.write_bytes(content)
    return target


def build_image_markdown(image_path: str, alt_text: str, caption: str | None) -> str:
    lines = [f"![{alt_text}]({image_path})"]
    if caption:
        lines.append("")
        lines.append(f"> 이미지 설명: {caption}")
    return "\n".join(lines)


def build_wiki_asset_url(space_key: str, filename: str) -> str:
    return f"/wiki-static/spaces/{quote(space_key)}/assets/{quote(filename)}"


def make_attachment_image_placeholder(filename: str, alt_text: str | None = None) -> str:
    return f"[[confluence-image:attachment:{filename}|{alt_text or filename}]]"


def make_source_image_placeholder(src: str, alt_text: str | None = None) -> str:
    return f"[[confluence-image:src:{src}|{alt_text or 'image'}]]"


def asset_metadata(path: Path, is_image: bool, caption: str | None) -> dict[str, str | bool | datetime | None]:
    return {
        "filename": path.name,
        "local_path": str(path),
        "is_image": is_image,
        "vlm_summary": caption,
        "downloaded_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
