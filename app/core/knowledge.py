from __future__ import annotations

KNOWLEDGE_KIND_SEGMENTS = {
    "entity": "entities",
    "concept": "concepts",
    "analysis": "analyses",
    "lint": "lint",
}

KNOWLEDGE_SEGMENT_KINDS = {segment: kind for kind, segment in KNOWLEDGE_KIND_SEGMENTS.items()}

KNOWLEDGE_KIND_LABELS = {
    "entity": "지식 문서",
    "concept": "개념 문서",
    "analysis": "분석 문서",
    "lint": "Lint Report",
}


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


def knowledge_href(space_key: str, kind_or_segment: str, slug: str) -> str:
    return f"/spaces/{space_key}/knowledge/{knowledge_segment(kind_or_segment)}/{slug}"
