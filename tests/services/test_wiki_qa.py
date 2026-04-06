import pytest

from app.core.config import Settings
from app.demo_seed import seed_demo_content
from app.services.wiki_qa import WikiQAService


class FakeTextClient:
    def answer_question(self, question: str, contexts: list[dict[str, str]]) -> str:
        joined_titles = ", ".join(item["title"] for item in contexts)
        return f"질문: {question}\n근거: {joined_titles}"


def test_wiki_qa_limits_answers_to_selected_space(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    service = WikiQAService(settings=settings, text_client=FakeTextClient())
    result = service.answer(question="운영 대시보드와 런북 요약", scope="space", selected_space="DEMO")

    assert result["scope"] == "space"
    assert result["selected_space"] == "DEMO"
    assert result["sources"]
    assert all(source["space_key"] == "DEMO" for source in result["sources"])
    assert "운영 대시보드" in result["answer"]


def test_wiki_qa_can_search_across_global_wiki(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    service = WikiQAService(settings=settings, text_client=FakeTextClient())
    result = service.answer(question="아키텍처 메모가 무엇을 설명해?", scope="global", selected_space="DEMO")

    assert result["scope"] == "global"
    assert any(source["space_key"] == "ARCH" for source in result["sources"])
    assert "아키텍처 메모" in result["answer"]


def test_wiki_qa_requires_concrete_space_for_space_scope(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)
    seed_demo_content(settings)

    service = WikiQAService(settings=settings, text_client=FakeTextClient())

    with pytest.raises(ValueError):
        service.answer(question="질문", scope="space", selected_space="all")
