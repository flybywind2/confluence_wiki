from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_service import PhraseToken


def test_upsert_markdown_section_preserves_blank_line_before_next_heading():
    markdown = "\n".join(
        [
            "# Topic",
            "",
            "## 관련 문서",
            "",
            "- doc one",
            "## 관련 주제",
            "",
            "- topic two",
        ]
    )

    updated = KnowledgeService._upsert_markdown_section(
        markdown,
        "## 관련 문서",
        "- doc one\n- doc two",
        replace_existing=True,
    )

    assert "- doc two\n\n## 관련 주제" in updated


def test_meaningful_phrase_rejects_generic_korean_bigrams():
    assert not KnowledgeService._is_meaningful_phrase(
        [
            PhraseToken(display="구축한", key="구축한"),
            PhraseToken(display="방법", key="방법"),
        ]
    )
    assert not KnowledgeService._is_meaningful_phrase(
        [
            PhraseToken(display="미치", key="미치"),
            PhraseToken(display="영향", key="영향"),
        ]
    )


def test_meaningful_phrase_keeps_strong_compound_topics():
    assert KnowledgeService._is_meaningful_phrase(
        [
            PhraseToken(display="Ghidra", key="ghidra"),
            PhraseToken(display="MCP", key="mcp"),
        ]
    )
    assert KnowledgeService._is_meaningful_phrase(
        [
            PhraseToken(display="로컬", key="로컬"),
            PhraseToken(display="모델", key="모델"),
        ]
    )
