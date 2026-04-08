from app.core.config import Settings
from app.demo_seed import seed_demo_content
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_service import PhraseToken
from app.services.sync_service import SyncService


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


def test_build_wiki_state_snapshot_includes_topic_inventory(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    sample_settings_dict["DATABASE_URL"] = f"sqlite:///{tmp_path / 'app.db'}"
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)
    service = KnowledgeService(settings)
    session = service.session_factory()
    try:
        snapshot = service._build_wiki_state_snapshot(session)
    finally:
        session.close()

    assert "Wiki topics" in snapshot
    assert "운영" in snapshot
    assert "source pages" in snapshot


def test_rebuild_global_passes_existing_topics_and_existing_body_to_llm_editor(
    tmp_path,
    sample_settings_dict,
    monkeypatch,
):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    sample_settings_dict["DATABASE_URL"] = f"sqlite:///{tmp_path / 'app.db'}"
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)
    service = KnowledgeService(settings)
    session = service.session_factory()
    proposal_calls: list[dict[str, object]] = []
    update_calls: list[dict[str, object]] = []
    try:
        monkeypatch.setattr(
            service.text_client,
            "propose_topics_for_document",
            lambda **kwargs: proposal_calls.append(kwargs) or [str(kwargs["existing_topics"][0])],
        )
        monkeypatch.setattr(
            service.text_client,
            "classify_topic_type",
            lambda **kwargs: "concept",
        )
        monkeypatch.setattr(
            service.text_client,
            "update_topic_page",
            lambda **kwargs: update_calls.append(kwargs)
            or "\n".join(
                [
                    "# 운영",
                    "",
                    "## 개요",
                    "",
                    "편집자 갱신 결과",
                    "",
                    "## 핵심 사실",
                    "",
                    "- 기존 내용을 유지하면서 새 근거를 반영했습니다.",
                    "",
                    "## 관련 문서",
                    "",
                    "- 테스트",
                    "",
                    "## 관련 주제",
                    "",
                    "- 없음",
                    "",
                    "## 원문 근거",
                    "",
                    "- 테스트",
                ]
            ),
        )

        service.rebuild_global_with_session(session)
    finally:
        session.rollback()
        session.close()

    assert proposal_calls
    assert "existing_topics" in proposal_calls[0]
    assert proposal_calls[0]["existing_topics"]
    assert any("런북" in str(topic) or "대시보드" in str(topic) for topic in proposal_calls[0]["existing_topics"])
    assert "Wiki topics" in str(proposal_calls[0]["wiki_state"])
    assert update_calls
    assert any(str(call["existing_content"]).strip() for call in update_calls)
    assert any("## 관련 문서" in str(call["existing_content"]) for call in update_calls if str(call["existing_content"]).strip())


def test_ensure_keyword_sections_replaces_title_only_key_facts_with_multiple_real_content_lines(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    sample_settings_dict["DATABASE_URL"] = f"sqlite:///{tmp_path / 'app.db'}"
    settings = Settings.model_validate(sample_settings_dict)
    service = KnowledgeService(settings)

    items = [
        {
            "title": "AI Portal 운영 점검",
            "slug": "ai-portal-ops",
            "space_key": "DEMO",
            "space_name": "Demo Showcase",
            "summary": "# AI Portal 운영 현황",
            "href": "/spaces/DEMO/pages/ai-portal-ops",
            "prod_url": "https://prod.example.com/pages/viewpage.action?pageId=100",
            "fact_card": "\n".join(
                [
                    "# AI Portal 운영 점검",
                    "",
                    "## 개요",
                    "",
                    "AI Portal 운영 상태를 정리한 문서입니다.",
                    "",
                    "## 핵심 사실",
                    "",
                    "- AI Portal 인증 흐름과 장애 대응 절차를 정리합니다.",
                    "- 관리자 승인 없이 토큰 재발급이 되지 않도록 막았습니다.",
                    "",
                    "## 운영 포인트",
                    "",
                    "- 운영 시 원문 확인 필요",
                    "",
                    "## 원문 근거",
                    "",
                    "- AI Portal 운영 점검",
                ]
            ),
            "body": "\n".join(
                [
                    "# AI Portal 운영 현황",
                    "",
                    "이번 문서는 운영 상태를 정리한 문서입니다.",
                    "",
                    "## AI Portal 인증 이슈",
                    "",
                    "AI Portal 인증 흐름과 장애 대응 절차를 정리합니다.",
                    "- 관리자 승인 없이 토큰 재발급이 되지 않도록 막았습니다.",
                    "- 장애 발생 시 포털 접근 로그를 먼저 확인합니다.",
                ]
            ),
        }
    ]
    generated = "\n".join(
        [
            "# AI Portal",
            "",
            "## 개요",
            "",
            "테스트 개요",
            "",
            "## 핵심 사실",
            "",
            "- AI Portal",
        ]
    )

    updated = service._ensure_keyword_sections("AI Portal", items, [], generated)

    assert "- AI Portal 인증 흐름과 장애 대응 절차를 정리합니다." in updated
    assert "- 관리자 승인 없이 토큰 재발급이 되지 않도록 막았습니다." in updated
    assert "이번 문서는 운영 상태를 정리한 문서입니다." not in updated
    assert "- AI Portal 운영 점검:" not in updated


def test_ensure_keyword_sections_preserves_rich_generated_key_facts_when_present(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    sample_settings_dict["DATABASE_URL"] = f"sqlite:///{tmp_path / 'app.db'}"
    settings = Settings.model_validate(sample_settings_dict)
    service = KnowledgeService(settings)

    items = [
        {
            "title": "DS Assistant 회의록",
            "slug": "ds-assistant-note",
            "space_key": "DEMO",
            "space_name": "Demo Showcase",
            "summary": "DS Assistant 운영 이슈를 정리한 회의록입니다.",
            "href": "/spaces/DEMO/pages/ds-assistant-note",
            "prod_url": "https://prod.example.com/confluence/pages/viewpage.action?pageId=200",
            "fact_card": "# DS Assistant 회의록\n\n## 개요\n\nDS Assistant 운영 이슈를 정리한 회의록입니다.",
            "body": "# DS Assistant 회의록\n\n이번 문서는 운영 상태를 정리한 문서입니다.",
        }
    ]
    generated = "\n".join(
        [
            "# DS Assistant",
            "",
            "## 개요",
            "",
            "DS Assistant 주제 개요",
            "",
            "## 핵심 사실",
            "",
            "- DS Assistant는 권한 캐시 만료 시 재시도 로직이 없습니다.",
            "- 포털 검색 API timeout이 2초라서 응답 지연이 커집니다.",
        ]
    )

    updated = service._ensure_keyword_sections("DS Assistant", items, [], generated)

    assert "- DS Assistant는 권한 캐시 만료 시 재시도 로직이 없습니다." in updated
    assert "- 포털 검색 API timeout이 2초라서 응답 지연이 커집니다." in updated


def test_sync_summary_fallback_prefers_content_line_over_heading(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    sample_settings_dict["DATABASE_URL"] = f"sqlite:///{tmp_path / 'app.db'}"
    settings = Settings.model_validate(sample_settings_dict)
    service = SyncService(settings=settings)

    summary = service._summarize("# AI Portal 운영 현황\n\nAI Portal 인증 흐름과 장애 대응 절차를 정리합니다.")

    assert summary == "AI Portal 인증 흐름과 장애 대응 절차를 정리합니다."
