from __future__ import annotations

from datetime import datetime
from pathlib import Path


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}


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


def asset_metadata(path: Path, is_image: bool, caption: str | None) -> dict[str, str | bool | datetime | None]:
    return {
        "filename": path.name,
        "local_path": str(path),
        "is_image": is_image,
        "vlm_summary": caption,
        "downloaded_at": datetime.utcnow(),
    }
