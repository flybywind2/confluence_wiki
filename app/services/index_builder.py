from __future__ import annotations

from datetime import datetime
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
        target.write_text(f"# {space_key} Activity Log\n", encoding="utf-8")

    lines = [f"## [{timestamp.isoformat()}] sync | {space_key} | {mode}"]
    if window_label:
        lines.append(f"- window: {window_label}")
    if documents:
        links = ", ".join(f"[[{space_key}/{doc['slug']}]]" for doc in documents)
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
    lines = [f"# {space_key} Synthesis", "", f"- generated_at: {generated_at.isoformat()}", ""]
    if documents:
        lines.extend(["## 핵심 문서", ""])
        for doc in sorted(documents, key=lambda item: item["title"].lower()):
            summary = doc.get("summary") or ""
            lines.append(f"- [[{space_key}/{doc['slug']}]]: {summary}".rstrip(": "))
        lines.append("")
    if recent_log_entries:
        lines.extend(["## 최근 동기화", ""])
        for entry in recent_log_entries:
            lines.append(f"- {entry}")
        lines.append("")
    lines.extend(["## 메모", "", "이 문서는 현재 space의 누적 요약 페이지입니다."])
    target = space_root / "synthesis.md"
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
