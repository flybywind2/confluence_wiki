from __future__ import annotations

from pathlib import Path


def build_space_index(root: Path, space_key: str, documents: list[dict[str, str]]) -> Path:
    space_root = root / "spaces" / space_key
    space_root.mkdir(parents=True, exist_ok=True)
    lines = [f"# {space_key} Index", ""]
    for doc in sorted(documents, key=lambda item: item["title"].lower()):
        lines.append(f"- [[{space_key}/{doc['slug']}]]")
    target = space_root / "index.md"
    target.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return target


def build_space_log(root: Path, space_key: str, documents: list[dict[str, str]]) -> Path:
    space_root = root / "spaces" / space_key
    lines = [f"# {space_key} Recent Updates", ""]
    for doc in sorted(documents, key=lambda item: item.get("updated_at", ""), reverse=True):
        lines.append(f"- {doc.get('updated_at', '')} [[{space_key}/{doc['slug']}]]")
    target = space_root / "log.md"
    target.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return target


def build_global_index(root: Path, grouped_documents: dict[str, list[dict[str, str]]]) -> Path:
    global_root = root / "global"
    global_root.mkdir(parents=True, exist_ok=True)
    lines = ["# Global Wiki Index", ""]
    for space_key, documents in sorted(grouped_documents.items()):
        lines.append(f"## {space_key}")
        for doc in sorted(documents, key=lambda item: item["title"].lower()):
            lines.append(f"- [[{space_key}/{doc['slug']}]]")
        lines.append("")
    target = global_root / "index.md"
    target.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return target
