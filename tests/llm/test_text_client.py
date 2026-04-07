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
