import re

from app.core.config import Settings
from app.llm.text_client import TextLLMClient


def test_system_prompts_are_english_and_request_korean_responses(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = TextLLMClient(settings)

    prompts = [
        client._summary_system_prompt(),
        client._fact_card_system_prompt(),
        client._topic_page_system_prompt(),
        client._topic_selection_system_prompt(),
        client._qa_system_prompt(),
    ]

    for prompt in prompts:
        assert "Korean" in prompt
        assert re.search(r"[가-힣]", prompt) is None


def test_topic_update_prompt_mentions_body_excerpt(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = TextLLMClient(settings)

    prompt = client._topic_update_system_prompt()

    assert "body_excerpt" in prompt
    assert "primary source of facts" in prompt


def test_extract_meaningful_excerpt_collects_multiple_segments(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = TextLLMClient(settings)

    text = "\n".join(
        [
            "# AI Portal 운영 현황",
            "",
            "## 핵심 사실",
            "",
            "- AI Portal 인증 흐름과 장애 대응 절차를 정리합니다.",
            "- 관리자 승인 없이 토큰 재발급이 되지 않습니다.",
            "- 장애 발생 시 포털 접근 로그를 먼저 확인합니다.",
        ]
    )

    excerpt = client._extract_meaningful_excerpt(text, limit=200, max_segments=3)

    assert "AI Portal 인증 흐름과 장애 대응 절차를 정리합니다." in excerpt
    assert "관리자 승인 없이 토큰 재발급이 되지 않습니다." in excerpt
    assert "\n" in excerpt


def test_fallback_fact_card_keeps_multiple_relevant_points(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = TextLLMClient(settings)

    text = "\n".join(
        [
            "# AI Portal 운영 현황",
            "",
            "AI Portal 인증 흐름과 장애 대응 절차를 정리합니다.",
            "관리자 승인 없이 토큰 재발급이 되지 않습니다.",
            "장애 발생 시 포털 접근 로그를 먼저 확인합니다.",
        ]
    )

    fact_card = client._fallback_fact_card("AI Portal 운영 점검", text)

    assert "- AI Portal 인증 흐름과 장애 대응 절차를 정리합니다." in fact_card
    assert "- 관리자 승인 없이 토큰 재발급이 되지 않습니다." in fact_card


def test_fallback_evidence_detail_prefers_block_over_title_only_summary(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)
    client = TextLLMClient(settings)

    detail = client._fallback_evidence_detail(
        {
            "title": "AI Portal 운영 점검",
            "summary": "AI Portal",
            "fact_card": "",
            "body_excerpt": "AI Portal 인증 흐름과 장애 대응 절차를 정리합니다.\n관리자 승인 없이 토큰 재발급이 되지 않습니다.",
        }
    )

    assert "AI Portal 인증 흐름과 장애 대응 절차를 정리합니다." in detail
    assert "관리자 승인 없이 토큰 재발급이 되지 않습니다." in detail
