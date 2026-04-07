from __future__ import annotations

import re

GLOBAL_KNOWLEDGE_SPACE_KEY = "__global__"

KNOWLEDGE_KIND_SEGMENTS = {
    "entity": "entities",
    "keyword": "keywords",
    "analysis": "analyses",
    "query": "queries",
    "lint": "lint",
}

KNOWLEDGE_SEGMENT_KINDS = {segment: kind for kind, segment in KNOWLEDGE_KIND_SEGMENTS.items()}

KNOWLEDGE_KIND_LABELS = {
    "entity": "지식 문서",
    "keyword": "키워드 문서",
    "analysis": "분석 문서",
    "query": "검색 위키",
    "lint": "Lint Report",
}

_RAW_PAGE_REF_RE = re.compile(r"(?:/spaces/|spaces/)(?P<space_key>[^/\]]+)/pages/(?P<slug>[^|\]\s]+)")
_LEGACY_KNOWLEDGE_REF_RE = re.compile(
    r"(?:/spaces/|spaces/)(?P<space_key>[^/\]]+)/knowledge/(?P<kind>[^/\]]+)/(?P<slug>[^|\]\s]+)"
)


def normalize_knowledge_kind(kind_or_segment: str) -> str:
    normalized = (kind_or_segment or "").strip().lower()
    if normalized in KNOWLEDGE_KIND_SEGMENTS:
        return normalized
    return KNOWLEDGE_SEGMENT_KINDS.get(normalized, normalized)


def knowledge_segment(kind_or_segment: str) -> str:
    kind = normalize_knowledge_kind(kind_or_segment)
    return KNOWLEDGE_KIND_SEGMENTS.get(kind, kind)


def knowledge_label(kind_or_segment: str) -> str:
    kind = normalize_knowledge_kind(kind_or_segment)
    return KNOWLEDGE_KIND_LABELS.get(kind, kind)


def knowledge_href(kind_or_segment: str, slug: str) -> str:
    return f"/knowledge/{knowledge_segment(kind_or_segment)}/{slug}"


def legacy_knowledge_href(space_key: str, kind_or_segment: str, slug: str) -> str:
    return f"/spaces/{space_key}/knowledge/{knowledge_segment(kind_or_segment)}/{slug}"


def is_global_knowledge_space(space_key: str | None) -> bool:
    return (space_key or "").strip() == GLOBAL_KNOWLEDGE_SPACE_KEY


def source_space_keys(source_refs: str | None) -> list[str]:
    if not source_refs:
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for pattern in (_RAW_PAGE_REF_RE, _LEGACY_KNOWLEDGE_REF_RE):
        for match in pattern.finditer(source_refs):
            space_key = (match.group("space_key") or "").strip()
            if not space_key or is_global_knowledge_space(space_key) or space_key in seen:
                continue
            seen.add(space_key)
            ordered.append(space_key)
    return ordered
